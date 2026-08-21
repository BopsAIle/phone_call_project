import { encodeMulaw } from '../audio/mulaw.codec';
import {
  OpenAiSttSession,
  type RealtimeSocket,
} from './openai-realtime-stt.service';
import type { SessionConfig } from './realtime-events.types';

/**
 * The fallback dialect on purpose.
 *
 * `gpt-live-transcribe` reports no turn boundaries, so a session built from this
 * exercises the transcript-activity gate. The VAD path is covered by the tests
 * that emit `speech_started` — the session adopts VAD from the events it
 * receives, not from its config, so one fixture drives both.
 */
const CONFIG: SessionConfig = {
  model: 'gpt-live-transcribe',
  locale: 'en',
  delay: 'low',
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

  /**
   * `gpt-live-transcribe` emits **no** boundary events: no `speech_started`, no
   * `speech_stopped`, and no `.completed` unless the client commits. Verified
   * against a live session on 2026-08-21 — a full sentence plus four seconds of
   * trailing silence produced nothing but deltas.
   *
   * So turn boundaries come from the transcript going quiet, and these cover
   * that gate. The tests this replaced asserted the VAD-driven behaviour, and
   * passed against a fake socket that emitted events the real one never sends.
   */
  /**
   * The preferred path since the model switch. `gpt-4o-transcribe` and friends
   * report turn boundaries themselves, which is both faster and more accurate
   * than watching the transcript go quiet — VAD hears the audio stop, the gate
   * has to wait for the decoder to catch up first.
   *
   * Measured live on 2026-08-21: `speech_stopped` at +548 ms after the caller
   * fell silent and `.completed` at +1133 ms, against 3700 ms for the gate.
   */
  describe('server VAD', () => {
    beforeEach(() => jest.useFakeTimers());
    afterEach(() => jest.useRealTimers());

    function speak(socket: FakeSocket, transcript: string): void {
      socket.receive({
        type: 'input_audio_buffer.speech_started',
        audio_start_ms: 1200,
      });
      socket.receive({
        type: 'conversation.item.input_audio_transcription.delta',
        delta: transcript,
      });
      socket.receive({
        type: 'input_audio_buffer.speech_stopped',
        audio_end_ms: 3400,
      });
      socket.receive({
        type: 'conversation.item.input_audio_transcription.completed',
        transcript,
      });
    }

    it('emits the final from .completed, with the VAD boundaries', () => {
      const { session, socket } = harness();
      socket.open();

      const finals: string[] = [];
      const meta = jest.fn();
      session.onFinal((text, m) => {
        finals.push(text);
        meta(m);
      });

      speak(socket, 'a table for four');

      expect(finals).toEqual(['a table for four']);
      expect(meta).toHaveBeenCalledWith({ startMs: 1200, endMs: 3400 });

      void session.close();
    });

    it('routes the speech callbacks straight from the model', () => {
      const { session, socket } = harness();
      socket.open();

      const started = jest.fn();
      const stopped = jest.fn();
      session.onSpeechStarted(started);
      session.onSpeechStopped(stopped);

      speak(socket, 'hello');

      expect(started).toHaveBeenCalledTimes(1);
      expect(stopped).toHaveBeenCalledTimes(1);

      void session.close();
    });

    /**
     * The one thing that must never happen. Both endpointers emitting for the
     * same utterance means the conversation layer answers twice, talking over
     * itself — the exact failure the turn state machine exists to prevent.
     */
    it('disarms the transcript gate, so only one final is emitted', () => {
      const { session, socket } = harness();
      socket.open();

      const finals: string[] = [];
      session.onFinal((text) => finals.push(text));

      speak(socket, 'a table for four');
      // Far longer than the gate's window would have needed.
      jest.advanceTimersByTime(10000);

      expect(finals).toEqual(['a table for four']);

      void session.close();
    });

    /**
     * Deltas can arrive before the first boundary event, arming the gate. It has
     * to be cancelled when VAD takes over, or it fires partway through the
     * VAD-driven turn and emits a duplicate.
     */
    it('cancels a gate already armed by earlier deltas', () => {
      const { session, socket } = harness();
      socket.open();

      const finals: string[] = [];
      session.onFinal((text) => finals.push(text));

      socket.receive({
        type: 'conversation.item.input_audio_transcription.delta',
        delta: 'an early',
      });
      speak(socket, 'a table for four');
      jest.advanceTimersByTime(10000);

      expect(finals).toEqual(['a table for four']);

      void session.close();
    });

    it('reports partials cumulatively while speech is in progress', () => {
      const { session, socket } = harness();
      socket.open();

      const partials: string[] = [];
      session.onPartial((text) => partials.push(text));

      socket.receive({
        type: 'input_audio_buffer.speech_started',
        audio_start_ms: 0,
      });
      for (const delta of [' a', ' table']) {
        socket.receive({
          type: 'conversation.item.input_audio_transcription.delta',
          delta,
        });
      }

      expect(partials).toEqual(['a', 'a table']);

      void session.close();
    });

    /**
     * `.completed` for one utterance routinely arrives *after* `speech_started`
     * for the next, so reading the most recent boundary at completion time
     * attributes one turn's timestamps to another. Observed live on 2026-08-21:
     * two consecutive utterances both reported `startMs: 2476`, which would put
     * the transcript out of order in the database.
     */
    it('attributes boundaries to the right utterance when they interleave', () => {
      const { session, socket } = harness();
      socket.open();

      const meta: { startMs: number; endMs: number }[] = [];
      session.onFinal((_text, m) => meta.push(m));

      socket.receive({
        type: 'input_audio_buffer.speech_started',
        item_id: 'item_1',
        audio_start_ms: 1000,
      });
      socket.receive({
        type: 'input_audio_buffer.speech_stopped',
        item_id: 'item_1',
        audio_end_ms: 2000,
      });

      // The next turn begins before the previous transcript lands.
      socket.receive({
        type: 'input_audio_buffer.speech_started',
        item_id: 'item_2',
        audio_start_ms: 3000,
      });
      socket.receive({
        type: 'conversation.item.input_audio_transcription.completed',
        item_id: 'item_1',
        transcript: 'first',
      });
      socket.receive({
        type: 'input_audio_buffer.speech_stopped',
        item_id: 'item_2',
        audio_end_ms: 4000,
      });
      socket.receive({
        type: 'conversation.item.input_audio_transcription.completed',
        item_id: 'item_2',
        transcript: 'second',
      });

      expect(meta).toEqual([
        { startMs: 1000, endMs: 2000 },
        { startMs: 3000, endMs: 4000 },
      ]);

      void session.close();
    });

    it('falls back to the audio clock when an item is unknown', () => {
      const { session, socket } = harness();
      socket.open();

      const meta = jest.fn();
      session.onFinal((_text, m) => {
        meta(m);
      });

      for (let i = 0; i < 25; i++) session.pushAudio(frame());
      socket.receive({
        type: 'input_audio_buffer.speech_started',
        audio_start_ms: 100,
      });
      socket.receive({
        type: 'conversation.item.input_audio_transcription.completed',
        item_id: 'never-announced',
        transcript: 'orphaned',
      });

      expect(meta).toHaveBeenCalledWith({ startMs: 100, endMs: 500 });

      void session.close();
    });

    it('keeps utterances separate across turns', () => {
      const { session, socket } = harness();
      socket.open();

      const finals: string[] = [];
      session.onFinal((text) => finals.push(text));

      speak(socket, 'first');
      speak(socket, 'second');

      expect(finals).toEqual(['first', 'second']);

      void session.close();
    });
  });

  describe('endpointing', () => {
    beforeEach(() => jest.useFakeTimers());
    afterEach(() => jest.useRealTimers());

    /** Speaks `words` as separate deltas, `gapMs` apart, as the API does. */
    function say(socket: FakeSocket, words: string[], gapMs = 250): void {
      for (const delta of words) {
        socket.receive({
          type: 'conversation.item.input_audio_transcription.delta',
          delta,
        });
        jest.advanceTimersByTime(gapMs);
      }
    }

    it('emits a final once the transcript goes quiet', () => {
      const { session, socket } = harness();
      socket.open();

      const finals: string[] = [];
      session.onFinal((text) => finals.push(text));

      say(socket, [' a', ' table', ' for', ' four']);
      expect(finals).toEqual([]);

      jest.advanceTimersByTime(1200);

      expect(finals).toEqual(['a table for four']);

      void session.close();
    });

    /** Median gap 251 ms, p90 418 ms, max 660 ms on the verified session. */
    it('does not split on the gaps between words within a sentence', () => {
      const { session, socket } = harness();
      socket.open();

      const finals: string[] = [];
      session.onFinal((text) => finals.push(text));

      say(socket, [' a', ' table'], 1100);
      jest.advanceTimersByTime(1200);

      expect(finals).toEqual(['a table']);

      void session.close();
    });

    it('reports partials cumulatively, as the sentence so far', () => {
      const { session, socket } = harness();
      socket.open();

      const partials: string[] = [];
      session.onPartial((text) => partials.push(text));

      say(socket, [' a', ' table', ' for']);

      expect(partials).toEqual(['a', 'a table', 'a table for']);

      void session.close();
    });

    it('fires speech started on the first word and stopped at the boundary', () => {
      const { session, socket } = harness();
      socket.open();

      const started = jest.fn();
      const stopped = jest.fn();
      session.onSpeechStarted(started);
      session.onSpeechStopped(stopped);

      say(socket, [' hello', ' there']);
      expect(started).toHaveBeenCalledTimes(1);
      expect(stopped).not.toHaveBeenCalled();

      jest.advanceTimersByTime(1200);
      expect(stopped).toHaveBeenCalledTimes(1);

      // A second utterance starts a second turn.
      say(socket, [' again']);
      expect(started).toHaveBeenCalledTimes(2);

      void session.close();
    });

    it('timestamps the utterance from the audio clock', () => {
      const { session, socket } = harness();
      socket.open();

      const meta = jest.fn();
      session.onFinal((_text, m) => {
        meta(m);
      });

      // 25 frames × 20 ms = 500 ms of audio before the first word decodes.
      for (let i = 0; i < 25; i++) session.pushAudio(frame());
      say(socket, [' four'], 0);
      for (let i = 0; i < 10; i++) session.pushAudio(frame());
      jest.advanceTimersByTime(1200);

      expect(meta).toHaveBeenCalledWith({ startMs: 500, endMs: 700 });

      void session.close();
    });

    /**
     * Committing closes the item over whatever has been *decoded* so far, and
     * this model runs seconds behind the audio — observed live on 2026-08-21,
     * committing at each endpoint lost the back half of a sentence. The joined
     * deltas already carry the full transcript, so there is nothing to gain.
     */
    it('does not commit the audio buffer, which would drop undecoded words', () => {
      const { session, socket } = harness();
      socket.open();

      say(socket, [' four']);
      jest.advanceTimersByTime(1200);

      expect(socket.sent.join()).not.toContain('input_audio_buffer.commit');

      void session.close();
    });

    /** The echo of our own commit, long after the turn already started. */
    it('does not emit a second final when the committed transcript arrives', () => {
      const { session, socket } = harness();
      socket.open();

      const finals: string[] = [];
      session.onFinal((text) => finals.push(text));

      say(socket, [' a', ' table']);
      jest.advanceTimersByTime(1200);

      socket.receive({
        type: 'conversation.item.input_audio_transcription.completed',
        transcript: 'a table',
      });

      expect(finals).toEqual(['a table']);

      void session.close();
    });

    it('emits nothing when the transcript is empty', () => {
      const { session, socket } = harness();
      socket.open();

      const finals: string[] = [];
      session.onFinal((text) => finals.push(text));

      jest.advanceTimersByTime(5000);

      expect(finals).toEqual([]);

      void session.close();
    });

    /**
     * The caller's last sentence is usually still inside the endpointing window
     * when they hang up. Without this, the final utterance of every call is
     * silently dropped.
     */
    it('flushes a pending utterance on close', async () => {
      const { session, socket } = harness();
      socket.open();

      const finals: string[] = [];
      session.onFinal((text) => finals.push(text));

      say(socket, [' one', ' last', ' thing']);
      expect(finals).toEqual([]);

      await session.close();

      expect(finals).toEqual(['one last thing']);
    });
  });

  describe('events', () => {
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
     * The audio clock counts frames pushed over the whole call, so it does not
     * reset when a socket does. That is what keeps `Utterance` offsets ordered
     * across a mid-call reconnect — the model's own buffer clock restarts at
     * zero and would jump every timestamp backwards.
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

      sockets[1].receive({
        type: 'conversation.item.input_audio_transcription.delta',
        delta: ' still here',
      });
      jest.advanceTimersByTime(1200);

      // 100 frames × 20 ms, and still counting up rather than restarting.
      expect(meta).toHaveBeenCalledWith({ startMs: 2000, endMs: 2000 });

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
