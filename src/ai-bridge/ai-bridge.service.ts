import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { WebSocket } from 'ws';
import { decodeMulaw } from '../audio/mulaw.codec';
import { int16ToLe } from '../audio/pcm';
import { Upsampler } from '../audio/resampler';
import type { Env } from '../config/env.schema';
import type { AiBridgeProvider, AiSession } from './ai-bridge.provider';
import {
  AI_SAMPLE_RATE,
  parseInbound,
  sessionInit,
  type SessionContext,
} from './wire-format';

/**
 * Twilio's frame is 20 ms; five of them is ~100 ms per send.
 *
 * A 20 ms frame is a tiny WebSocket message and 50 of them per second per call
 * is needless overhead. But this delay lands directly in front of the AI team's
 * VAD, and therefore in front of barge-in responsiveness — so it is the first
 * thing to lower if interruptions feel sluggish, and it must not be raised
 * without saying so.
 */
const FRAMES_PER_BATCH = 5;

/** 5 frames × 320 samples @ 16 kHz × 2 bytes. */
const BATCH_BYTES = FRAMES_PER_BATCH * (AI_SAMPLE_RATE / 50) * 2;

/**
 * ~2 seconds of 16 kHz PCM16. The cap on audio held while the socket is down or
 * stalled; past it the oldest is dropped.
 *
 * Stale audio recognised late is worse than a missing word — it arrives after
 * the conversation has moved on. The real reason for a hard cap, though, is
 * memory: without one a single wedged socket grows without bound, and across
 * concurrent calls that is the leak this would most plausibly ship.
 */
const MAX_QUEUE_BYTES = AI_SAMPLE_RATE * 2 * 2;

/** If `ws` is holding more than this unsent, the far end is not keeping up. */
const SOCKET_BUFFER_CAP_BYTES = 256 * 1024;

/** Three attempts, then give up and let the call continue without the agent. */
const RECONNECT_BACKOFF_MS = [200, 500, 1000];

/**
 * The AI service closes 1008 for a bad or missing token, and 1011 when its own
 * pipeline crashes.
 *
 * 1008 is not worth retrying: the token that was rejected is the same token the
 * next attempt would present, so the backoff would spend ~1.7 s proving it. Fail
 * immediately and name the cause, because "the agent said nothing" is otherwise
 * indistinguishable from a network problem.
 */
const CLOSE_UNAUTHORIZED = 1008;

/**
 * The `ws` surface this session actually uses.
 *
 * Narrowed so the unit tests can supply a fake without reimplementing a
 * WebSocket. `ws`'s own class satisfies it structurally. `send` takes `Buffer`
 * as well as `string` because audio goes out as binary frames and control as
 * text — the one place this file's shape differs from the STT session it is
 * modelled on.
 */
export interface BridgeSocket {
  readonly readyState: number;
  readonly bufferedAmount: number;
  send(data: string | Buffer): void;
  close(): void;
  /**
   * Declared as a method rather than a property so parameter checking stays
   * bivariant — that is what lets both `ws`'s overloaded `on` and a handler
   * typed `(raw: Buffer, isBinary: boolean) => void` satisfy the same signature.
   */
  on(event: string, listener: (...args: unknown[]) => void): unknown;
  removeAllListeners(): unknown;
}

export type SocketFactory = () => BridgeSocket;

type Listener<T extends unknown[]> = (...args: T) => void;

function noop(): void {}

/**
 * One call's connection to the AI service.
 *
 * Owns the mu-law decode, the 8 → 16 kHz upsample, and the batching, because
 * `AiSession` takes audio exactly as Twilio delivers it. Everything the
 * conversation layer sees is either mu-law going in or raw PCM coming out.
 */
export class AiBridgeSession implements AiSession {
  private readonly logger: Logger;

  /**
   * One instance for the whole call, driven one 20 ms frame at a time.
   *
   * The filter is 48 taps — far longer than a frame — so its history has to
   * survive across frames. A filter restarted per frame rings at every boundary,
   * which is a click 50 times a second. It also applies the ×2 gain that keeps
   * the level right; without it the AI service is fed audio 6 dB down, which
   * reads as a weak model rather than a resampler bug.
   */
  private readonly upsampler = new Upsampler(AI_SAMPLE_RATE);

  private socket?: BridgeSocket;

  /** Bytes accumulating toward one send. */
  private batch: Buffer[] = [];
  private batchBytes = 0;

  /** Whole batches waiting for a socket that is down or stalled. */
  private queue: Buffer[] = [];
  private queuedBytes = 0;

  private attempt = 0;
  private reconnectTimer?: NodeJS.Timeout;

  /** Set by `close()`; suppresses the reconnect a deliberate close would trigger. */
  private closing = false;

  /** Set after the backoff is exhausted, so the failure is one loud line not a stream. */
  private failed = false;

  /**
   * False until the first socket has opened.
   *
   * Drives `resumed` on the handshake, which is what stops the AI service
   * greeting the caller a second time after a mid-call reconnect.
   */
  private greeted = false;

  /**
   * Whether any agent audio has arrived on this call.
   *
   * Only used to log the first frame. "Connected but silent" and "connected and
   * speaking" are the two outcomes that look identical from our side otherwise,
   * and they have completely different causes — the first is theirs, the second
   * means the fault is downstream in our own conversion or Twilio path.
   */
  private receivedAudio = false;

  private audio: Listener<[Buffer]> = noop;
  private interrupted: Listener<[]> = noop;

  constructor(
    private readonly createSocket: SocketFactory,
    private readonly context: SessionContext,
  ) {
    this.logger = new Logger(`${AiBridgeSession.name}[${context.callId}]`);
    this.connect();
  }

  /** True once the backoff is exhausted; the call continues without the agent. */
  get isFailed(): boolean {
    return this.failed;
  }

  pushAudio(mulaw8k: Buffer): void {
    if (this.closing) return;

    const pcm = this.upsampler.process(decodeMulaw(mulaw8k));
    const bytes = int16ToLe(pcm);

    this.batch.push(bytes);
    this.batchBytes += bytes.length;

    if (this.batchBytes >= BATCH_BYTES) this.flushBatch();
  }

  onAudio(cb: (pcm: Buffer) => void): void {
    this.audio = cb;
  }

  onInterrupt(cb: () => void): void {
    this.interrupted = cb;
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
    socket.on('message', (raw: Buffer, isBinary: boolean) =>
      this.handleMessage(raw, isBinary),
    );
    socket.on('close', (code: number) => this.handleClose(code));
    socket.on('error', (error: Error) => {
      // Transport-level. `close` follows, and that is where reconnection is
      // decided — doing it here as well would double every backoff.
      this.logger.warn(`AI bridge socket error: ${error.message}`);
    });
  }

  private handleOpen(): void {
    this.attempt = 0;

    const resumed = this.greeted;
    this.socket?.send(sessionInit(this.context, { resumed }));
    this.greeted = true;

    /**
     * Logged at `log`, not `debug`, and deliberately.
     *
     * Every other outcome on this socket is already loud — a rejected token, a
     * reconnect, a malformed message. Success was the only path that said
     * nothing, which made "are we actually talking to the AI service?"
     * answerable only by silence. That is the first question anyone asks when
     * bringing the integration up, and the last one they ask at three in the
     * morning.
     */
    this.logger.log(
      resumed
        ? 'AI bridge reconnected; session.init resent as resumed'
        : `AI bridge connected as ${this.context.storeName} (${this.context.locale})`,
    );

    this.drain();
  }

  private handleClose(code?: number): void {
    if (this.closing || this.failed) return;

    if (code === CLOSE_UNAUTHORIZED) {
      this.failed = true;
      this.logger.error(
        'AI bridge rejected our credentials (1008); check AI_BRIDGE_TOKEN. ' +
          'Not retrying — the call continues without the agent',
      );
      return;
    }

    const backoff = RECONNECT_BACKOFF_MS[this.attempt];

    if (backoff === undefined) {
      this.failed = true;
      // Loud, once. The phone call itself is fine and must continue — the
      // caller keeps talking to an agent that can no longer hear them.
      this.logger.error(
        `AI bridge unavailable after ${RECONNECT_BACKOFF_MS.length} attempts; the call continues without it`,
      );
      return;
    }

    this.attempt++;
    this.logger.warn(
      `AI bridge socket closed; reconnecting in ${backoff}ms (attempt ${this.attempt})`,
    );

    this.reconnectTimer = setTimeout(() => {
      if (!this.closing) this.connect();
    }, backoff);
  }

  // --- inbound ----------------------------------------------------------

  private handleMessage(raw: Buffer, isBinary: boolean): void {
    const message = parseInbound(raw, isBinary);

    switch (message.kind) {
      case 'audio':
        if (!this.receivedAudio) {
          this.receivedAudio = true;
          this.logger.log(
            `First agent audio: ${message.pcm.length} bytes from the AI service`,
          );
        }

        this.audio(message.pcm);
        return;

      case 'interrupt':
        this.logger.debug('Barge-in reported by the AI service');
        this.interrupted();
        return;

      case 'unhandled':
        // Routine, and additive by design: the contract says unknown events are
        // ignored, so the AI team can add messages without breaking us.
        this.logger.debug(`Ignoring ${message.event}`);
        return;

      case 'malformed':
        // Not routine: a message we depend on arrived in a shape we do not
        // understand, which means the contract moved under us.
        this.logger.warn(`Malformed message: ${message.detail}`);
        return;
    }
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
    // alternative — refusing new audio — would freeze the conversation at the
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
   * Driven by batch completion and by the socket opening — deliberately not by a
   * timer. Twilio streams continuously for the length of the call, silence
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
      socket.send(chunk);
    }
  }
}

/**
 * Opens one AI-bridge session per call.
 *
 * Not yet wired into `ConversationService` — the cutover is its own commit, so
 * that a broken bridge is one `git revert` away rather than tangled with the
 * removal of the pipeline it replaces.
 */
@Injectable()
export class AiBridgeService implements AiBridgeProvider {
  constructor(private readonly config: ConfigService<Env, true>) {}

  /**
   * Resolves immediately, with the socket still connecting.
   *
   * Waiting for the handshake would be tidier but drops audio: the caller may
   * already be speaking, and 100–300 ms of it would fall on the floor between
   * Twilio's `start` and the socket opening. The session buffers from the moment
   * it exists, using the same bounded queue that covers reconnection, so audio
   * pushed before the socket is up is sent the instant it comes up.
   */
  createSession(context: SessionContext): Promise<AiSession> {
    const url = this.config.get('AI_BRIDGE_URL', { infer: true });
    const token = this.config.get('AI_BRIDGE_TOKEN', { infer: true });

    if (!url) {
      // Optional in the schema only until the cutover commit makes this path
      // live; see the comment on the variable in env.schema.ts.
      throw new Error('AI_BRIDGE_URL is not configured');
    }

    const headers = token ? { Authorization: `Bearer ${token}` } : undefined;

    return Promise.resolve(
      new AiBridgeSession(() => new WebSocket(url, { headers }), context),
    );
  }
}
