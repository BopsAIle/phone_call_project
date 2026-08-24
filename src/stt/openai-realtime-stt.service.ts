import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { WebSocket } from 'ws';
import { decodeMulaw } from '../audio/mulaw.codec';
import { int16ToLe } from '../audio/pcm';
import { Upsampler } from '../audio/resampler';
import type { Env } from '../config/env.schema';
import type { SttProvider, SttSession } from './stt.provider';
import {
  REALTIME_URL,
  appendAudio,
  parseServerEvent,
  realtimeHeaders,
  sessionUpdate,
  type SessionConfig,
  type ServerEvent,
  type TurnDetection,
} from './realtime-events.types';

/**
 * Twilio's frame is 20 ms; five of them is ~100 ms per `append`.
 *
 * A 20 ms frame is a tiny WebSocket message and 50 of them per second per call
 * is needless overhead. 100 ms of added latency against a ~500 ms VAD window is
 * a good trade — but do not raise it much further, because this delay lands
 * directly in front of barge-in.
 */
const FRAMES_PER_BATCH = 5;

/** 5 frames × 480 samples @ 24 kHz × 2 bytes. */
const BATCH_BYTES = FRAMES_PER_BATCH * 480 * 2;

/**
 * ~2 seconds of 24 kHz PCM16. The cap on audio held while the socket is down or
 * stalled; past it the oldest is dropped.
 *
 * Stale audio transcribed late is worse than a missing word — it arrives after
 * the conversation has moved on and desynchronises every timestamp after it.
 * The real reason for a hard cap, though, is memory: without one, a single
 * wedged socket grows without bound, and across concurrent calls that is the
 * leak this phase would most plausibly ship.
 */
const MAX_QUEUE_BYTES = 24000 * 2 * 2;

/** If `ws` is holding more than this unsent, the far end is not keeping up. */
const SOCKET_BUFFER_CAP_BYTES = 256 * 1024;

/** Three attempts, then give up and let the call continue without transcription. */
const RECONNECT_BACKOFF_MS = [200, 500, 1000];

/**
 * Cap on VAD boundaries held while waiting for their transcript.
 *
 * Entries are removed when the matching `.completed` lands, so this only bites
 * if one never does — over a call that can run for many minutes, an unbounded
 * map would be a slow leak per concurrent call.
 */
const MAX_TRACKED_ITEMS = 16;

/**
 * Server-side voice activity detection, for models that support it.
 *
 * Measured against a live `gpt-4o-transcribe` session on 2026-08-21:
 * `speech_stopped` lands ~550–800 ms after the caller falls silent and the full
 * `.completed` transcript ~1.1–1.4 s after — against the 3700 ms the
 * transcript-activity fallback costs. That difference is most of this project's
 * latency problem.
 *
 * `silenceDurationMs` is the important knob and 500 ms is **too low**: it cut
 * *"Hello, my name is Anna. Can I book a table for two people?"* into three
 * separate turns, because the pauses at the commas cleared it. A caller
 * gathering their thoughts mid-sentence would be interrupted the same way.
 * 800 ms clears an ordinary comma pause while still ending a turn promptly; it
 * is the first thing to raise if the agent talks over people, and to lower if
 * replies feel sluggish.
 *
 * `sessionUpdate` drops this automatically for a model whose profile does not
 * accept it, so it is safe to leave set.
 */
const TURN_DETECTION: TurnDetection = {
  threshold: 0.5,
  prefixPaddingMs: 300,
  silenceDurationMs: 800,
};

/**
 * Latency against word error rate, for `gpt-live-transcribe` only — every other
 * model rejects the key, and `sessionUpdate` omits it for them.
 */
const TRANSCRIPTION_DELAY = 'low';

/**
 * How long the transcript must go quiet before the caller's turn is over —
 * **the fallback**, used only when the model reports no turn boundaries.
 *
 * `gpt-live-transcribe` emits none at all: no `speech_started`, no
 * `speech_stopped`, and no `.completed` unless the client commits. Verified
 * against a live session on 2026-08-21, where a full sentence plus four seconds
 * of trailing silence produced nothing but deltas. For that model endpointing is
 * ours to do, and the only signal available is the *transcript* going quiet
 * rather than the audio.
 *
 * A model with server VAD — the default since the model switch — disarms this
 * gate on its first boundary event. Both paths are kept because `STT_MODEL` is
 * configuration, so the code has to be correct either way; what it must never
 * do is run both at once, which would be two replies per turn.
 *
 * Measured mid-speech gaps between deltas, in two conditions:
 *
 * | Input | median | p90 | max |
 * | --- | --- | --- | --- |
 * | PCM16 @ 24 kHz, direct | 251 ms | 418 ms | 660 ms |
 * | mu-law @ 8 kHz, paced 20 ms — i.e. a phone call | — | — | **~1200 ms** |
 *
 * The telephony figure is what matters, and it is roughly double: worse audio
 * decodes in chunkier bursts. A value tuned on studio-quality input splits every
 * other sentence in two on a real call.
 *
 * It degrades gracefully in both directions, which is what makes it safe to pick
 * from few samples. Too low splits a sentence, and `CallSession` merges the
 * second final into the turn already in flight. Too high adds its excess to
 * every reply — and at this size it is now the largest single term in the
 * latency budget, which is the strongest argument for a real VAD later.
 */
const ENDPOINT_SILENCE_MS = 1200;

/**
 * The `ws` surface this session actually uses.
 *
 * Narrowed to nine members so the unit tests can supply a fake without
 * reimplementing a WebSocket. `ws`'s own class satisfies it structurally.
 */
export interface RealtimeSocket {
  readonly readyState: number;
  readonly bufferedAmount: number;
  send(data: string): void;
  close(): void;
  terminate(): void;
  /**
   * Declared as a method rather than a property so parameter checking stays
   * bivariant — that is what lets both `ws`'s overloaded `on` and a handler
   * typed `(raw: Buffer) => void` satisfy the same signature.
   */
  on(event: string, listener: (...args: unknown[]) => void): unknown;
  removeAllListeners(): unknown;
}

export type SocketFactory = () => RealtimeSocket;

type Listener<T extends unknown[]> = (...args: T) => void;

function noop(): void {}

/**
 * One call's transcription session.
 *
 * Owns the mu-law decode and the 8→24 kHz upsample, because `SttSession` takes
 * audio "exactly as Twilio delivers it" — keeping resampling behind this
 * interface is what lets a speech-to-speech adapter, which wants mu-law
 * directly, replace it later without touching the conversation layer.
 */
export class OpenAiSttSession implements SttSession {
  private readonly logger: Logger;

  /**
   * One instance for the whole call, driven one 20 ms frame at a time.
   *
   * The filter is 48 taps — far longer than a frame — so its history has to
   * survive across frames. A filter restarted per frame rings at every
   * boundary, which is a click 50 times a second. It also applies the ×3 gain
   * that keeps the level right; without it every transcript would be made from
   * audio 9.5 dB down, which reads as a weak model rather than a bug.
   */
  private readonly upsampler = new Upsampler();

  private socket?: RealtimeSocket;

  /** Bytes accumulating toward one `append`. */
  private batch: Buffer[] = [];
  private batchBytes = 0;

  /** Whole batches waiting for a socket that is down or stalled. */
  private queue: Buffer[] = [];
  private queuedBytes = 0;

  private attempt = 0;
  private reconnectTimer?: NodeJS.Timeout;

  /** Set by `close()`; suppresses the reconnect a deliberate close would trigger. */
  private closing = false;

  /**
   * Set after the backoff is exhausted. Phase 6 reads this to apologise rather
   * than leave dead air; in this phase it stops us retrying forever and makes
   * the failure one loud line instead of a stream of them.
   */
  private failed = false;

  /** 20 ms per frame pushed — a monotonic clock in the medium being measured. */
  private framesPushed = 0;

  /**
   * The audio-clock reading when the *current* OpenAI session began.
   *
   * `audio_start_ms` is relative to the buffer of the session that emitted it,
   * and a reconnect resets that buffer to zero while our own clock keeps
   * running. Without this offset every timestamp after the first reconnect
   * would silently jump backwards to near zero.
   */
  private sessionEpochMs = 0;

  private lastSpeechStartMs?: number;
  private lastSpeechStopMs?: number;

  /**
   * The current utterance, accumulated from deltas.
   *
   * Concatenating them is lossless: on the verified session the joined deltas
   * matched the committed `.completed` transcript exactly. That is what lets a
   * turn start without waiting the ~600 ms the commit round trip costs.
   */
  private transcript = '';

  /** Audio-clock offset of the first delta of the current utterance. */
  private utteranceStartMs?: number;

  private endpointTimer?: NodeJS.Timeout;

  /**
   * Set by the first boundary event the model sends.
   *
   * Once true the transcript-activity gate is disarmed for good and turns come
   * from VAD. The two must never run together: each would emit its own final
   * for the same utterance, and the conversation layer would answer twice.
   */
  private vadDriven = false;

  /** The last final emitted by the gate, to compare against the server's. */
  private lastFinal = '';

  /**
   * VAD boundaries awaiting their transcript, keyed by the item they describe.
   *
   * Not a single "most recent" pair, because `.completed` for one utterance
   * routinely arrives after `speech_started` for the next.
   */
  private readonly boundaries = new Map<
    string,
    { startMs?: number; endMs?: number }
  >();

  private partial: Listener<[string]> = noop;
  private final: Listener<[string, { startMs: number; endMs: number }]> = noop;
  private speechStarted: Listener<[]> = noop;
  private speechStopped: Listener<[]> = noop;

  constructor(
    private readonly createSocket: SocketFactory,
    private config: SessionConfig,
    label: string,
  ) {
    this.logger = new Logger(`${OpenAiSttSession.name}[${label}]`);
    this.connect();
  }

  /** True once the backoff is exhausted; the call continues without transcription. */
  get isFailed(): boolean {
    return this.failed;
  }

  /** Offset into the call's audio, by the frame counter. */
  get audioMs(): number {
    return this.framesPushed * 20;
  }

  pushAudio(mulaw8k: Buffer): void {
    if (this.closing) return;

    this.framesPushed++;

    const pcm24k = this.upsampler.process(decodeMulaw(mulaw8k));
    const bytes = int16ToLe(pcm24k);

    this.batch.push(bytes);
    this.batchBytes += bytes.length;

    if (this.batchBytes >= BATCH_BYTES) this.flushBatch();
  }

  onPartial(cb: (text: string) => void): void {
    this.partial = cb;
  }

  onFinal(
    cb: (text: string, meta: { startMs: number; endMs: number }) => void,
  ): void {
    this.final = cb;
  }

  onSpeechStarted(cb: () => void): void {
    this.speechStarted = cb;
  }

  onSpeechStopped(cb: () => void): void {
    this.speechStopped = cb;
  }

  setLocale(locale: 'en' | 'de'): void {
    if (this.config.locale === locale) return;

    // `sessionUpdate` shapes this into `language` or `languages` per the
    // model's dialect — sending the wrong one is rejected at connect time, on a
    // live call rather than in a test.
    this.config = { ...this.config, locale };

    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(sessionUpdate(this.config));
    }
  }

  async close(): Promise<void> {
    this.closing = true;

    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);

    // The caller's last sentence is usually still inside the endpointing
    // window when they hang up. Emitting it here is what stops the final
    // utterance of every call being silently dropped.
    if (this.endpointTimer) {
      clearTimeout(this.endpointTimer);
      this.endpoint();
    }

    // Send the tail. A caller's last word can easily sit in a partial batch,
    // and dropping it loses the end of the final sentence of the call.
    this.flushBatch();

    this.socket?.removeAllListeners();
    this.socket?.close();
    this.socket = undefined;

    return Promise.resolve();
  }

  // --- connection -------------------------------------------------------

  private connect(): void {
    const socket = this.createSocket();
    this.socket = socket;

    socket.on('open', () => this.handleOpen());
    socket.on('message', (raw: Buffer) => this.handleMessage(raw));
    socket.on('close', () => this.handleClose());
    socket.on('error', (error: Error) => {
      // Transport-level. `close` follows, and that is where reconnection is
      // decided — doing it here as well would double every backoff.
      this.logger.warn(`Realtime socket error: ${error.message}`);
    });
  }

  private handleOpen(): void {
    this.attempt = 0;
    this.sessionEpochMs = this.audioMs;

    this.socket?.send(sessionUpdate(this.config));
    this.drain();
  }

  private handleClose(): void {
    if (this.closing || this.failed) return;

    const backoff = RECONNECT_BACKOFF_MS[this.attempt];

    if (backoff === undefined) {
      this.failed = true;
      // Loud, once. The phone call itself is fine and must continue — the
      // caller keeps talking to an agent that can no longer hear them, which
      // Phase 6 turns into a spoken apology.
      this.logger.error(
        `Transcription unavailable after ${RECONNECT_BACKOFF_MS.length} attempts; the call continues without it`,
      );
      return;
    }

    this.attempt++;
    this.logger.warn(
      `Realtime socket closed; reconnecting in ${backoff}ms (attempt ${this.attempt})`,
    );

    this.reconnectTimer = setTimeout(() => {
      if (!this.closing) this.connect();
    }, backoff);
  }

  // --- inbound ----------------------------------------------------------

  private handleMessage(raw: Buffer): void {
    const parsed = parseServerEvent(raw);

    switch (parsed.kind) {
      case 'event':
        this.dispatch(parsed.event);
        return;

      case 'unhandled':
        // Routine: the API emits a wide vocabulary several times per turn.
        this.logger.debug(`Ignoring ${parsed.type}`);
        return;

      case 'malformed':
        // Not routine: an event we depend on arrived in a shape we do not
        // understand, which means the contract moved under us.
        this.logger.warn(
          `Malformed ${parsed.type ?? 'event'}: ${parsed.detail}`,
        );
        return;
    }
  }

  private dispatch(event: ServerEvent): void {
    switch (event.type) {
      case 'session.created':
        this.logger.log('Transcription session opened');
        return;

      case 'session.updated':
        this.logger.debug('Session configuration accepted');
        return;

      /**
       * The preferred path. A boundary event means the model endpoints for us,
       * which is both faster and more accurate than watching the transcript go
       * quiet — VAD hears the audio stop, the gate waits for the decoder to
       * catch up first.
       */
      case 'input_audio_buffer.speech_started':
        this.adoptVad();
        this.lastSpeechStartMs = this.absolute(event.audio_start_ms);
        this.rememberBoundary(event.item_id, {
          startMs: this.lastSpeechStartMs,
        });
        this.speechStarted();
        return;

      case 'input_audio_buffer.speech_stopped':
        this.adoptVad();
        this.lastSpeechStopMs = this.absolute(event.audio_end_ms);
        this.rememberBoundary(event.item_id, { endMs: this.lastSpeechStopMs });
        this.speechStopped();
        return;

      case 'conversation.item.input_audio_transcription.delta':
        if (this.vadDriven) {
          // Accumulated only to show a cumulative partial; the authoritative
          // transcript comes from `.completed`.
          this.transcript += event.delta;
          this.partial(this.transcript.trim());
          return;
        }

        this.onTranscriptActivity(event.delta);
        return;

      case 'conversation.item.input_audio_transcription.completed':
        if (this.vadDriven) {
          this.transcript = '';
          this.final(event.transcript.trim(), this.boundaryFor(event.item_id));
          return;
        }

        // Without VAD this is only ever the echo of a commit, arriving long
        // after the gate already ended the turn. Compared rather than
        // re-emitted, so drift from the joined deltas would be visible.
        if (event.transcript.trim() !== this.lastFinal) {
          this.logger.debug(
            `Server transcript differs from the joined deltas: ${event.transcript}`,
          );
        }
        return;

      case 'error':
        // Deliberately not a reconnect trigger. These are protocol complaints —
        // a rejected parameter, an unsupported value — and retrying the same
        // handshake would just reproduce them in a loop. A genuine disconnect
        // arrives as `close`.
        this.logger.error(
          `Realtime API error: ${event.error.message}${
            event.error.code ? ` (${event.error.code})` : ''
          }`,
        );
        return;
    }
  }

  /**
   * A session-relative VAD timestamp to an offset into the whole call.
   *
   * Falls back to the local audio clock when the field is absent — which, for
   * `gpt-live-transcribe`, is always, since it emits no VAD events at all.
   */
  private absolute(sessionMs: number | undefined): number {
    return sessionMs === undefined
      ? this.audioMs
      : this.sessionEpochMs + sessionMs;
  }

  /**
   * Files a VAD boundary against the item it belongs to.
   *
   * `.completed` for one utterance routinely arrives *after* `speech_started`
   * for the next, so reading the most recent boundary at completion time
   * attributes one turn's timestamps to another. Observed live on 2026-08-21:
   * two consecutive utterances both reported `startMs: 2476`.
   */
  private rememberBoundary(
    itemId: string | undefined,
    boundary: { startMs?: number; endMs?: number },
  ): void {
    if (itemId === undefined) return;

    const existing = this.boundaries.get(itemId);
    this.boundaries.set(itemId, { ...existing, ...boundary });

    // Entries are normally removed when their transcript lands. This caps the
    // damage if one never does, over a call that can run for many minutes.
    if (this.boundaries.size > MAX_TRACKED_ITEMS) {
      const oldest = this.boundaries.keys().next();
      if (!oldest.done) this.boundaries.delete(oldest.value);
    }
  }

  /** The boundaries for one item, falling back to the local audio clock. */
  private boundaryFor(itemId: string | undefined): {
    startMs: number;
    endMs: number;
  } {
    const tracked =
      itemId === undefined ? undefined : this.boundaries.get(itemId);
    if (itemId !== undefined) this.boundaries.delete(itemId);

    return {
      startMs: tracked?.startMs ?? this.lastSpeechStartMs ?? this.audioMs,
      endMs: tracked?.endMs ?? this.lastSpeechStopMs ?? this.audioMs,
    };
  }

  /**
   * Hands endpointing to the model on its first boundary event.
   *
   * Cancelling the pending timer here is the important part: a gate armed by
   * deltas that arrived before the first `speech_started` would otherwise fire
   * partway through the VAD-driven turn and emit a duplicate final.
   */
  private adoptVad(): void {
    if (this.vadDriven) return;

    this.vadDriven = true;

    if (this.endpointTimer) {
      clearTimeout(this.endpointTimer);
      this.endpointTimer = undefined;
    }

    this.transcript = '';
    this.logger.log('Server VAD active; using model turn detection');
  }

  // --- endpointing ------------------------------------------------------

  /**
   * The substitute for turn detection.
   *
   * A delta arriving after the buffer has been emptied means the caller has
   * started talking; the transcript then going quiet for
   * `ENDPOINT_SILENCE_MS` means they have stopped.
   *
   * The cost is honest and worth stating: this waits for the first *decoded
   * word* rather than the first energy, so it is roughly 700 ms later than a
   * true VAD edge. Barge-in inherits that delay.
   */
  private onTranscriptActivity(delta: string): void {
    if (this.transcript.length === 0) {
      this.utteranceStartMs = this.audioMs;
      this.lastSpeechStartMs = this.utteranceStartMs;
      this.speechStarted();
    }

    this.transcript += delta;

    // Cumulative rather than the fragment: a partial is only useful as the
    // sentence so far.
    this.partial(this.transcript.trim());

    if (this.endpointTimer) clearTimeout(this.endpointTimer);
    this.endpointTimer = setTimeout(() => this.endpoint(), ENDPOINT_SILENCE_MS);
  }

  /** Ends the caller's turn: emit the final, then let the server release the audio. */
  private endpoint(): void {
    this.endpointTimer = undefined;

    const text = this.transcript.trim();
    this.transcript = '';
    this.utteranceStartMs = undefined;

    if (text.length === 0) return;

    this.lastFinal = text;
    this.lastSpeechStopMs = this.audioMs;

    // `speech_stopped` before `final`, in that order: the conversation layer
    // stamps `t0` off the first and measures the reply against it.
    this.speechStopped();
    this.final(text, {
      startMs: this.lastSpeechStartMs ?? this.audioMs,
      endMs: this.lastSpeechStopMs,
    });

    /**
     * Deliberately **not** committing the audio buffer here.
     *
     * Committing does produce a clean `.completed` transcript, and with turn
     * detection off it is the documented way to delimit an utterance — but it
     * closes the item over whatever the transcriber has decoded *so far*, and
     * this model routinely runs seconds behind the audio. Observed on a live
     * session on 2026-08-21: committing at each endpoint lost the back half of
     * a sentence outright, because the words had been received but not yet
     * decoded when the commit landed.
     *
     * Since the joined deltas already give the full transcript, the commit buys
     * a tidier item boundary at the cost of dropping words. Not worth it.
     */
  }

  // --- outbound ---------------------------------------------------------

  private flushBatch(): void {
    if (this.batchBytes === 0) return;

    this.enqueue(Buffer.concat(this.batch, this.batchBytes));

    this.batch = [];
    this.batchBytes = 0;
  }

  private enqueue(chunk: Buffer): void {
    this.queue.push(chunk);
    this.queuedBytes += chunk.length;

    // Drop from the front: the oldest audio is the least useful, and the
    // alternative — refusing new audio — would freeze the transcript at the
    // moment of the stall rather than resuming from it.
    while (this.queuedBytes > MAX_QUEUE_BYTES) {
      const dropped = this.queue.shift();
      if (!dropped) break;

      this.queuedBytes -= dropped.length;
      this.logger.warn(`Dropped ${dropped.length} bytes of buffered audio`);
    }

    this.drain();
  }

  /**
   * Sends whatever the socket will currently take.
   *
   * Driven by batch completion and by the socket opening — deliberately not by
   * a timer. Twilio streams continuously for the length of the call, silence
   * included, so a batch completes every 100 ms; a queue held back by a stalled
   * socket therefore never waits more than that for the next attempt. A polling
   * timer would add a moving part per call to buy nothing.
   */
  private drain(): void {
    const socket = this.socket;
    if (!socket || socket.readyState !== WebSocket.OPEN) return;

    while (this.queue.length > 0) {
      if (socket.bufferedAmount > SOCKET_BUFFER_CAP_BYTES) return;

      const chunk = this.queue.shift();
      if (!chunk) return;

      this.queuedBytes -= chunk.length;
      socket.send(appendAudio(chunk.toString('base64')));
    }
  }
}

/**
 * Opens one transcription session per call.
 *
 * Never pooled or shared: a transcription session carries per-conversation
 * audio state, so crossing two callers would be both wrong and a privacy
 * breach.
 */
@Injectable()
export class OpenAiRealtimeSttService implements SttProvider {
  constructor(private readonly config: ConfigService<Env, true>) {}

  /**
   * Resolves immediately, with the socket still connecting.
   *
   * Waiting for the handshake would be tidier but drops audio: the caller may
   * already be speaking, and 100–300 ms of it would fall on the floor between
   * Twilio's `start` and the socket opening. The session buffers from the
   * moment it exists, using the same bounded queue that covers reconnection,
   * so audio pushed before the socket is up is sent the instant it comes up.
   */
  createSession(opts: {
    locale?: 'en' | 'de';
    callId?: string;
  }): Promise<SttSession> {
    const apiKey = this.config.get('OPENAI_API_KEY', { infer: true });

    // The trailing fallback is a type-level guard, not a runtime one: the env
    // schema gives DEFAULT_LOCALE a default, so it is always present by the time
    // anything boots. ConfigService types it as possibly-undefined regardless.
    const locale =
      opts.locale ?? this.config.get('DEFAULT_LOCALE', { infer: true }) ?? 'en';

    const sessionConfig: SessionConfig = {
      model: this.config.get('STT_MODEL', { infer: true }),
      locale,
      delay: TRANSCRIPTION_DELAY,
      turnDetection: TURN_DETECTION,
    };

    const session = new OpenAiSttSession(
      () => new WebSocket(REALTIME_URL, { headers: realtimeHeaders(apiKey) }),
      sessionConfig,
      opts.callId ?? 'unassigned',
    );

    return Promise.resolve(session);
  }
}
