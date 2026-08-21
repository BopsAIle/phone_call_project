import { encodeMulaw } from '../audio/mulaw.codec';
import {
  OpenAiSttSession,
  type RealtimeSocket,
} from './openai-realtime-stt.service';
import type { SessionConfig } from './realtime-events.types';

const CONFIG: SessionConfig = {
  model: 'gpt-live-transcribe',
  languages: ['en'],
  delay: 'low',
  // gpt-live-transcribe chunks audio itself and rejects an explicit block.
  turnDetection: null,
};

const CONNECTING = 0;
const OPEN = 1;
const CLOSED = 3;

/** Five 20 ms frames per `append` — see the service's own constant. */
const FRAMES_PER_BATCH = 5;

/** One 20 ms Twilio frame: 160 mu-law bytes. Contents do not matter here. */
function frame(): Buffer {
  return encodeMulaw(new Int16Array(160).fill(1000));
}

/** Only the fields these tests read back off the wire. */
interface OutboundMessage {
  type: string;
  audio?: string;
  session?: unknown;
}

/**
 * A `ws` stand-in.
 *
 * Only the nine members `OpenAiSttSession` narrows to, so the tests exercise the
 * session's own logic rather than a WebSocket reimplementation.
 */
class FakeSocket implements RealtimeSocket {
  readyState = CONNECTING;
  bufferedAmount = 0;
  readonly sent: string[] = [];

  private listeners = new Map<string, ((...args: unknown[]) => void)[]>();

  send(data: string): void {
    this.sent.push(data);
  }

  close(): void {
    this.readyState = CLOSED;
  }

  terminate(): void {
    this.readyState = CLOSED;
  }

  on(event: string, listener: (...args: unknown[]) => void): this {
    const existing = this.listeners.get(event) ?? [];
    this.listeners.set(event, [...existing, listener]);
    return this;
  }

  removeAllListeners(): this {
    this.listeners.clear();
    return this;
  }

  emit(event: string, ...args: unknown[]): void {
    for (const listener of this.listeners.get(event) ?? []) {
      listener(...args);
    }
  }

  /** The handshake completing. */
  open(): void {
    this.readyState = OPEN;
    this.emit('open');
  }

  /** The far end going away, as opposed to us closing. */
  drop(): void {
    this.readyState = CLOSED;
    this.emit('close');
  }

  receive(event: unknown): void {
    this.emit('message', Buffer.from(JSON.stringify(event), 'utf8'));
  }

  /** The `append` messages only, decoded back to raw PCM bytes. */
  appended(): Buffer[] {
    return this.outbound()
      .filter((message) => message.type === 'input_audio_buffer.append')
      .map((message) => Buffer.from(message.audio ?? '', 'base64'));
  }

  sessionUpdates(): OutboundMessage[] {
    return this.outbound().filter(
      (message) => message.type === 'session.update',
    );
  }

  private outbound(): OutboundMessage[] {
    return this.sent.map((raw) => JSON.parse(raw) as OutboundMessage);
  }
}

/** Builds a session over a controllable socket, one socket per connect attempt. */
function harness() {
  const sockets: FakeSocket[] = [];

  const session = new OpenAiSttSession(
    () => {
      const socket = new FakeSocket();
      sockets.push(socket);
      return socket;
    },
    CONFIG,
    'call_test',
  );

  return {
    session,
    sockets,
    /** The socket for the most recent connect attempt. */
    get socket(): FakeSocket {
      return sockets[sockets.length - 1];
    },
  };
}

describe('OpenAiSttSession', () => {
  describe('connection', () => {
    it('sends session.update as soon as the socket opens', () => {
      const { session, socket } = harness();

      expect(socket.sessionUpdates()).toHaveLength(0);

      socket.open();

      expect(socket.sessionUpdates()).toHaveLength(1);

      void session.close();
    });
  });

  describe('batching', () => {
    /**
     * Five 20 ms frames upsampled 3× is 4800 bytes. Sending each frame on its
     * own would be 50 WebSocket messages a second per call.
     */
    it('holds audio until ~100 ms has accumulated, then sends one append', () => {
      const { session, socket } = harness();
      socket.open();

      for (let i = 0; i < 4; i++) session.pushAudio(frame());
      expect(socket.appended()).toHaveLength(0);

      session.pushAudio(frame());

      const appends = socket.appended();
      expect(appends).toHaveLength(1);
      expect(appends[0]).toHaveLength(4800);

      void session.close();
    });

    it('keeps batching across many frames', () => {
      const { session, socket } = harness();
      socket.open();

      for (let i = 0; i < 15; i++) session.pushAudio(frame());

      expect(socket.appended()).toHaveLength(3);

      void session.close();
    });

    /**
     * The caller's last word routinely sits in a partial batch. Dropping it
     * loses the end of the final sentence of the call.
     */
    it('flushes a partial batch on close', async () => {
      const { session, socket } = harness();
      socket.open();

      for (let i = 0; i < 2; i++) session.pushAudio(frame());
      expect(socket.appended()).toHaveLength(0);

      await session.close();

      const appends = socket.appended();
      expect(appends).toHaveLength(1);
      expect(appends[0]).toHaveLength(1920);
    });

    it('sends nothing on close when nothing is pending', async () => {
      const { session, socket } = harness();
      socket.open();

      await session.close();

      expect(socket.appended()).toHaveLength(0);
    });

    it('ignores audio pushed after close', async () => {
      const { session, socket } = harness();
      socket.open();
      await session.close();

      for (let i = 0; i < 10; i++) session.pushAudio(frame());

      expect(socket.appended()).toHaveLength(0);
    });
  });

  describe('buffering before the socket is up', () => {
    /**
     * The reason `createSession` resolves without waiting for the handshake:
     * the caller may already be speaking, and 100–300 ms of audio would
     * otherwise fall on the floor between Twilio's `start` and the socket
     * opening.
     */
    it('sends audio pushed before the handshake once it completes', () => {
      const { session, socket } = harness();

      for (let i = 0; i < 10; i++) session.pushAudio(frame());
      expect(socket.appended()).toHaveLength(0);

      socket.open();

      expect(socket.appended()).toHaveLength(2);

      void session.close();
    });
  });

  describe('backpressure', () => {
    /**
     * Recovery is driven by the next completed batch rather than a timer. That
     * is not a compromise at 50 frames a second: Twilio sends continuously for
     * the length of the call, silence included, so a batch completes every
     * 100 ms and the queue never waits longer than that for a drain.
     */
    it('stops sending while the socket is not draining, and resumes after', () => {
      const { session, socket } = harness();
      socket.open();

      socket.bufferedAmount = 512 * 1024;
      for (let i = 0; i < 10; i++) session.pushAudio(frame());

      expect(socket.appended()).toHaveLength(0);

      socket.bufferedAmount = 0;
      for (let i = 0; i < FRAMES_PER_BATCH; i++) session.pushAudio(frame());

      // Everything held back, plus the batch that triggered the drain.
      expect(socket.appended()).toHaveLength(3);

      void session.close();
    });

    /**
     * The bound that matters. Without it one wedged socket grows without limit,
     * and across concurrent calls that is a memory leak rather than a glitch.
     */
    it('drops the oldest audio past the cap instead of growing', () => {
      const { session, socket } = harness();
      socket.open();
      socket.bufferedAmount = 512 * 1024;

      // 10 seconds of audio into a 2-second cap.
      for (let i = 0; i < 500; i++) session.pushAudio(frame());

      socket.bufferedAmount = 0;
      session.pushAudio(frame());

      const total = socket
        .appended()
        .reduce((sum, chunk) => sum + chunk.length, 0);

      expect(total).toBeLessThanOrEqual(96000 + 4800);

      void session.close();
    });
  });

  describe('events', () => {
    it('routes partials and finals to their callbacks', () => {
      const { session, socket } = harness();
      socket.open();

      const partials: string[] = [];
      const finals: string[] = [];
      session.onPartial((text) => partials.push(text));
      session.onFinal((text) => finals.push(text));

      socket.receive({
        type: 'conversation.item.input_audio_transcription.delta',
        delta: 'a table for',
      });
      socket.receive({
        type: 'conversation.item.input_audio_transcription.completed',
        transcript: 'a table for four',
      });

      expect(partials).toEqual(['a table for']);
      expect(finals).toEqual(['a table for four']);

      void session.close();
    });

    it('fires the speech callbacks — phase 3 barge-in depends on it', () => {
      const { session, socket } = harness();
      socket.open();

      const started = jest.fn();
      const stopped = jest.fn();
      session.onSpeechStarted(started);
      session.onSpeechStopped(stopped);

      socket.receive({
        type: 'input_audio_buffer.speech_started',
        audio_start_ms: 100,
      });
      socket.receive({
        type: 'input_audio_buffer.speech_stopped',
        audio_end_ms: 900,
      });

      expect(started).toHaveBeenCalledTimes(1);
      expect(stopped).toHaveBeenCalledTimes(1);

      void session.close();
    });

    it('reports the VAD boundaries as the final transcript timestamps', () => {
      const { session, socket } = harness();
      socket.open();

      const meta = jest.fn();
      session.onFinal((_text, m) => {
        meta(m);
      });

      socket.receive({
        type: 'input_audio_buffer.speech_started',
        audio_start_ms: 1200,
      });
      socket.receive({
        type: 'input_audio_buffer.speech_stopped',
        audio_end_ms: 3400,
      });
      socket.receive({
        type: 'conversation.item.input_audio_transcription.completed',
        transcript: 'four please',
      });

      expect(meta).toHaveBeenCalledWith({ startMs: 1200, endMs: 3400 });

      void session.close();
    });

    /** The documented fallback for the field this phase has not yet seen live. */
    it('falls back to the audio clock when the VAD timestamps are absent', () => {
      const { session, socket } = harness();
      socket.open();

      const meta = jest.fn();
      session.onFinal((_text, m) => {
        meta(m);
      });

      for (let i = 0; i < 25; i++) session.pushAudio(frame());

      socket.receive({ type: 'input_audio_buffer.speech_started' });
      socket.receive({ type: 'input_audio_buffer.speech_stopped' });
      socket.receive({
        type: 'conversation.item.input_audio_transcription.completed',
        transcript: 'four please',
      });

      expect(meta).toHaveBeenCalledWith({ startMs: 500, endMs: 500 });

      void session.close();
    });

    /**
     * The property that keeps a live call alive: an unrecognised or malformed
     * event is a log line, never an exception. A throw inside the socket's
     * message handler takes the process down and every other call with it.
     */
    it('survives unknown and malformed events', () => {
      const { session, socket } = harness();
      socket.open();

      expect(() => {
        socket.receive({ type: 'rate_limits.updated', rate_limits: [] });
        socket.receive({ type: 'conversation.item.added' });
        socket.receive({
          type: 'conversation.item.input_audio_transcription.completed',
        });
        socket.emit('message', Buffer.from('not json', 'utf8'));
      }).not.toThrow();

      void session.close();
    });

    it('does not reconnect on a protocol error', () => {
      const { session, socket, sockets } = harness();
      socket.open();

      socket.receive({
        type: 'error',
        error: { type: 'invalid_request_error', message: 'Unknown parameter' },
      });

      expect(sockets).toHaveLength(1);

      void session.close();
    });
  });

  describe('setLocale', () => {
    it('re-sends the configuration with the new language', () => {
      const { session, socket } = harness();
      socket.open();

      session.setLocale('de');

      const updates = socket.sessionUpdates();
      expect(updates).toHaveLength(2);
      expect(updates[1]).toMatchObject({
        session: { audio: { input: { transcription: { languages: ['de'] } } } },
      });

      void session.close();
    });

    it('does nothing when the locale is unchanged', () => {
      const { session, socket } = harness();
      socket.open();

      session.setLocale('en');

      expect(socket.sessionUpdates()).toHaveLength(1);

      void session.close();
    });
  });

  describe('reconnection', () => {
    beforeEach(() => jest.useFakeTimers());
    afterEach(() => jest.useRealTimers());

    it('reconnects with backoff and replays the session config', () => {
      const { session, sockets } = harness();
      sockets[0].open();

      sockets[0].drop();
      expect(sockets).toHaveLength(1);

      jest.advanceTimersByTime(200);
      expect(sockets).toHaveLength(2);

      sockets[1].open();
      expect(sockets[1].sessionUpdates()).toHaveLength(1);

      void session.close();
    });

    it('gives up after three attempts and lets the call continue', () => {
      const { session, sockets } = harness();
      sockets[0].open();

      sockets[0].drop();
      jest.advanceTimersByTime(200);
      sockets[1].drop();
      jest.advanceTimersByTime(500);
      sockets[2].drop();
      jest.advanceTimersByTime(1000);

      expect(sockets).toHaveLength(4);
      expect(session.isFailed).toBe(false);

      sockets[3].drop();
      jest.advanceTimersByTime(10000);

      expect(sockets).toHaveLength(4);
      expect(session.isFailed).toBe(true);

      // The phone call is unaffected — pushing audio must still be safe.
      expect(() => session.pushAudio(frame())).not.toThrow();

      void session.close();
    });

    /**
     * Audio buffered while the socket was down is sent on reconnect, not lost —
     * up to the cap. A gap of a few hundred milliseconds should cost nothing.
     */
    it('replays buffered audio after reconnecting', () => {
      const { session, sockets } = harness();
      sockets[0].open();
      sockets[0].drop();

      for (let i = 0; i < 10; i++) session.pushAudio(frame());

      jest.advanceTimersByTime(200);
      sockets[1].open();

      expect(sockets[1].appended()).toHaveLength(2);

      void session.close();
    });

    /**
     * `audio_start_ms` is relative to the buffer of the session that emitted it,
     * and a reconnect resets that buffer to zero. Without the epoch offset every
     * timestamp after the first reconnect jumps backwards to near zero.
     */
    it('keeps timestamps monotonic across a reconnect', () => {
      const { session, sockets } = harness();
      sockets[0].open();

      // 2 seconds of audio, then the socket drops and comes back.
      for (let i = 0; i < 100; i++) session.pushAudio(frame());
      sockets[0].drop();
      jest.advanceTimersByTime(200);
      sockets[1].open();

      const meta = jest.fn();
      session.onFinal((_text, m) => {
        meta(m);
      });

      // The new session's own clock starts at zero again.
      sockets[1].receive({
        type: 'input_audio_buffer.speech_started',
        audio_start_ms: 40,
      });
      sockets[1].receive({
        type: 'input_audio_buffer.speech_stopped',
        audio_end_ms: 600,
      });
      sockets[1].receive({
        type: 'conversation.item.input_audio_transcription.completed',
        transcript: 'still here',
      });

      expect(meta).toHaveBeenCalledWith({ startMs: 2040, endMs: 2600 });

      void session.close();
    });

    it('does not reconnect after a deliberate close', async () => {
      const { session, sockets } = harness();
      sockets[0].open();

      await session.close();
      sockets[0].drop();
      jest.advanceTimersByTime(10000);

      expect(sockets).toHaveLength(1);
    });
  });
});
