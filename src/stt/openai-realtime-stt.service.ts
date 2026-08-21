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

const VAD_DEFAULTS = {
  threshold: 0.5,
  prefixPaddingMs: 300,
  silenceDurationMs: 500,
};

/** Latency against word error rate. See the phase plan; may want raising on real phone audio. */
const TRANSCRIPTION_DELAY = 'low';

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
  on(event: string, listener: (...args: never[]) => void): unknown;
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
    if (this.config.languages[0] === locale) return;

    // `languages` is an array for gpt-live-transcribe; the singular `language`
    // of older models is rejected at connect time, on a live call.
    this.config = { ...this.config, languages: [locale] };

    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(sessionUpdate(this.config));
    }
  }

  async close(): Promise<void> {
    this.closing = true;

    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);

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

      case 'input_audio_buffer.speech_started':
        this.lastSpeechStartMs = this.absolute(event.audio_start_ms);
        this.speechStarted();
        return;

      case 'input_audio_buffer.speech_stopped':
        this.lastSpeechStopMs = this.absolute(event.audio_end_ms);
        this.speechStopped();
        return;

      case 'conversation.item.input_audio_transcription.delta':
        this.partial(event.delta);
        return;

      case 'conversation.item.input_audio_transcription.completed':
        this.final(event.transcript, {
          startMs: this.lastSpeechStartMs ?? this.audioMs,
          endMs: this.lastSpeechStopMs ?? this.audioMs,
        });
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
   * Falls back to the local audio clock when the field is absent — one of the
   * two things this phase verifies against a live session.
   */
  private absolute(sessionMs: number | undefined): number {
    return sessionMs === undefined
      ? this.audioMs
      : this.sessionEpochMs + sessionMs;
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
      languages: [locale],
      delay: TRANSCRIPTION_DELAY,
      turnDetection: VAD_DEFAULTS,
    };

    const session = new OpenAiSttSession(
      () => new WebSocket(REALTIME_URL, { headers: realtimeHeaders(apiKey) }),
      sessionConfig,
      opts.callId ?? 'unassigned',
    );

    return Promise.resolve(session);
  }
}
