import { encodeMulaw } from '../audio/mulaw.codec';
import { AiBridgeSession, type BridgeSocket } from './ai-bridge.service';
import type { SessionContext } from './wire-format';

const CONTEXT: SessionContext = {
  callId: 'call_1',
  storeName: 'Bella Vista',
  timezone: 'Europe/Berlin',
  locale: 'en',
  greeting: 'Thanks for calling Bella Vista.',
};

const CONNECTING = 0;
const OPEN = 1;
const CLOSED = 3;

/** Five 20 ms frames per send — see the service's own constant. */
const FRAMES_PER_BATCH = 5;

/** 5 frames × 320 samples @ 16 kHz × 2 bytes. */
const BATCH_BYTES = 3200;

/** One 20 ms Twilio frame: 160 mu-law bytes. Contents do not matter here. */
function frame(): Buffer {
  return encodeMulaw(new Int16Array(160).fill(1000));
}

/**
 * A `ws` stand-in, narrowed to what `AiBridgeSession` uses.
 *
 * `sent` keeps text and binary apart, because the split between them *is* the
 * wire contract — a test that merged them could not tell a control message from
 * audio.
 */
class FakeSocket implements BridgeSocket {
  readyState = CONNECTING;
  bufferedAmount = 0;
  readonly text: string[] = [];
  readonly binary: Buffer[] = [];

  private listeners = new Map<string, ((...args: unknown[]) => void)[]>();

  send(data: string | Buffer): void {
    if (typeof data === 'string') this.text.push(data);
    else this.binary.push(data);
  }

  close(): void {
    this.readyState = CLOSED;
    this.emit('close');
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

  get initEvents(): { resumed: boolean }[] {
    return this.text
      .map((raw) => JSON.parse(raw) as { event: string; resumed: boolean })
      .filter((message) => message.event === 'session.init');
  }
}

/** A session plus the sockets it has opened, newest last. */
function session(): { session: AiBridgeSession; sockets: FakeSocket[] } {
  const sockets: FakeSocket[] = [];

  const created = new AiBridgeSession(() => {
    const socket = new FakeSocket();
    sockets.push(socket);
    return socket;
  }, CONTEXT);

  return { session: created, sockets };
}

function push(target: AiBridgeSession, frames: number): void {
  for (let i = 0; i < frames; i++) target.pushAudio(frame());
}

describe('AiBridgeSession', () => {
  describe('handshake', () => {
    it('sends session.init as text the moment the socket opens', () => {
      const { sockets } = session();
      sockets[0].open();

      expect(sockets[0].initEvents).toHaveLength(1);
      expect(sockets[0].binary).toHaveLength(0);
    });

    it('does not send anything before the socket is open', () => {
      const { sockets } = session();

      expect(sockets[0].text).toHaveLength(0);
    });
  });

  describe('outbound audio', () => {
    it('batches five 20 ms frames into one binary send', () => {
      const { session: live, sockets } = session();
      sockets[0].open();

      push(live, FRAMES_PER_BATCH - 1);
      expect(sockets[0].binary).toHaveLength(0);

      push(live, 1);
      expect(sockets[0].binary).toHaveLength(1);
    });

    it('sends 16 kHz PCM16 — 3200 bytes per 100 ms batch', () => {
      const { session: live, sockets } = session();
      sockets[0].open();

      push(live, FRAMES_PER_BATCH);

      expect(sockets[0].binary[0]).toHaveLength(BATCH_BYTES);
    });

    /**
     * The caller may already be speaking when Twilio's `start` arrives, so audio
     * pushed before the handshake completes has to survive rather than fall on
     * the floor between the two.
     */
    it('buffers audio pushed before the socket opens, then sends it', () => {
      const { session: live, sockets } = session();

      push(live, FRAMES_PER_BATCH);
      expect(sockets[0].binary).toHaveLength(0);

      sockets[0].open();
      expect(sockets[0].binary).toHaveLength(1);
    });

    it('stops sending when the far end stops keeping up', () => {
      const { session: live, sockets } = session();
      sockets[0].open();

      sockets[0].bufferedAmount = 512 * 1024;
      push(live, FRAMES_PER_BATCH);

      expect(sockets[0].binary).toHaveLength(0);

      // And resumes from the queue once it drains, rather than losing the batch.
      sockets[0].bufferedAmount = 0;
      push(live, FRAMES_PER_BATCH);

      expect(sockets[0].binary).toHaveLength(2);
    });

    /**
     * ~2 seconds is the cap. Stale audio recognised late is worse than a missing
     * word, and without a bound one wedged socket grows until the process dies.
     */
    it('drops the oldest audio rather than growing without bound', () => {
      const { session: live, sockets } = session();
      sockets[0].open();
      sockets[0].bufferedAmount = 512 * 1024;

      // 30 batches is ~3 s, comfortably past the ~2 s cap.
      push(live, FRAMES_PER_BATCH * 30);
      sockets[0].bufferedAmount = 0;
      push(live, FRAMES_PER_BATCH);

      const sentBytes = sockets[0].binary.reduce(
        (total, chunk) => total + chunk.length,
        0,
      );

      expect(sentBytes).toBeLessThanOrEqual(16000 * 2 * 2 + BATCH_BYTES);
    });

    it('sends the partial batch on close, so the last word is not lost', async () => {
      const { session: live, sockets } = session();
      sockets[0].open();

      push(live, 2);
      expect(sockets[0].binary).toHaveLength(0);

      await live.close();

      expect(sockets[0].binary).toHaveLength(1);
      expect(sockets[0].binary[0]).toHaveLength(2 * 640);
    });
  });

  describe('inbound', () => {
    it('hands binary frames to onAudio untouched', () => {
      const { session: live, sockets } = session();
      const received: Buffer[] = [];
      live.onAudio((pcm) => received.push(pcm));
      sockets[0].open();

      const pcm = Buffer.from([0x01, 0x02, 0x03, 0x04]);
      sockets[0].emit('message', pcm, true);

      expect(received).toEqual([pcm]);
    });

    it('fires onInterrupt for the barge-in event', () => {
      const { session: live, sockets } = session();
      const interrupts = jest.fn();
      live.onInterrupt(interrupts);
      sockets[0].open();

      sockets[0].emit(
        'message',
        Buffer.from(JSON.stringify({ event: 'interrupt' })),
        false,
      );

      expect(interrupts).toHaveBeenCalledTimes(1);
    });

    it('ignores an unknown event without disturbing the call', () => {
      const { session: live, sockets } = session();
      const interrupts = jest.fn();
      live.onInterrupt(interrupts);
      sockets[0].open();

      expect(() =>
        sockets[0].emit(
          'message',
          Buffer.from(JSON.stringify({ event: 'response.done' })),
          false,
        ),
      ).not.toThrow();

      expect(interrupts).not.toHaveBeenCalled();
    });
  });

  describe('reconnection', () => {
    beforeEach(() => jest.useFakeTimers());
    afterEach(() => jest.useRealTimers());

    it('reconnects after an unexpected close', () => {
      const { sockets } = session();
      sockets[0].open();

      sockets[0].emit('close');
      jest.advanceTimersByTime(200);

      expect(sockets).toHaveLength(2);
    });

    /**
     * The reason `resumed` exists. The context has to be resent — the AI service
     * cannot recover it — but a caller mid-conversation would not understand
     * being greeted a second time.
     */
    it('marks the reconnect handshake as resumed', () => {
      const { sockets } = session();
      sockets[0].open();

      expect(sockets[0].initEvents[0].resumed).toBe(false);

      sockets[0].emit('close');
      jest.advanceTimersByTime(200);
      sockets[1].open();

      expect(sockets[1].initEvents[0].resumed).toBe(true);
    });

    it('gives up after three attempts and lets the call continue', () => {
      const { session: live, sockets } = session();
      sockets[0].open();

      for (const backoff of [200, 500, 1000]) {
        sockets[sockets.length - 1].emit('close');
        jest.advanceTimersByTime(backoff);
      }

      sockets[sockets.length - 1].emit('close');
      jest.advanceTimersByTime(10000);

      expect(sockets).toHaveLength(4);
      expect(live.isFailed).toBe(true);
    });

    it('does not reconnect after a deliberate close', async () => {
      const { session: live, sockets } = session();
      sockets[0].open();

      await live.close();
      jest.advanceTimersByTime(10000);

      expect(sockets).toHaveLength(1);
    });
  });
});
