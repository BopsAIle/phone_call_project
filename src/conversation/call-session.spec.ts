import { Role } from '../generated/prisma/enums';
import type { PrismaService } from '../prisma/prisma.service';
import type { SttSession } from '../stt/stt.provider';
import { CallSession } from './call-session';

/** An `SttSession` whose events the test fires by hand. */
class FakeStt implements SttSession {
  readonly pushed: Buffer[] = [];
  closed = false;
  locale?: 'en' | 'de';

  private partial: (text: string) => void = () => {};
  private final: (
    text: string,
    meta: { startMs: number; endMs: number },
  ) => void = () => {};
  private started: () => void = () => {};
  private stopped: () => void = () => {};

  pushAudio(mulaw8k: Buffer): void {
    this.pushed.push(mulaw8k);
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
    this.started = cb;
  }

  onSpeechStopped(cb: () => void): void {
    this.stopped = cb;
  }

  setLocale(locale: 'en' | 'de'): void {
    this.locale = locale;
  }

  close(): Promise<void> {
    this.closed = true;
    return Promise.resolve();
  }

  emitPartial(text: string): void {
    this.partial(text);
  }

  emitFinal(text: string, meta: { startMs: number; endMs: number }): void {
    this.final(text, meta);
  }

  emitSpeechStarted(): void {
    this.started();
  }

  emitSpeechStopped(): void {
    this.stopped();
  }
}

function fakePrisma(create = jest.fn().mockResolvedValue({})) {
  return {
    prisma: { utterance: { create } } as unknown as PrismaService,
    create,
  };
}

/** Lets the fire-and-forget persistence settle. */
const settle = () => new Promise((resolve) => setImmediate(resolve));

describe('CallSession', () => {
  it('forwards audio to the transcription session', () => {
    const stt = new FakeStt();
    const session = new CallSession('call_1', 'MZ1', stt, fakePrisma().prisma);

    session.pushAudio(Buffer.from([1, 2, 3]));

    expect(stt.pushed).toEqual([Buffer.from([1, 2, 3])]);
  });

  it('persists a final transcript with the VAD boundaries', async () => {
    const stt = new FakeStt();
    const { prisma, create } = fakePrisma();
    new CallSession('call_1', 'MZ1', stt, prisma);

    stt.emitFinal('a table for four', { startMs: 1200, endMs: 3400 });
    await settle();

    expect(create).toHaveBeenCalledWith({
      data: {
        callId: 'call_1',
        role: Role.CALLER,
        text: 'a table for four',
        startMs: 1200,
        endMs: 3400,
      },
    });
  });

  /**
   * Partials revise themselves several times per sentence. Persisting them
   * would turn the table into noise and make the transcript unreadable.
   */
  it('never persists a partial transcript', async () => {
    const stt = new FakeStt();
    const { prisma, create } = fakePrisma();
    new CallSession('call_1', 'MZ1', stt, prisma);

    stt.emitPartial('a table');
    stt.emitPartial('a table for');
    await settle();

    expect(create).not.toHaveBeenCalled();
  });

  /**
   * A phone call must not end because Postgres hiccuped. The rejection is
   * caught and logged, and nothing propagates into the socket's event loop —
   * an unhandled one there would take down the process and every other call.
   */
  it('survives a database failure without throwing', async () => {
    const stt = new FakeStt();
    const { prisma } = fakePrisma(
      jest.fn().mockRejectedValue(new Error('connection terminated')),
    );
    const session = new CallSession('call_1', 'MZ1', stt, prisma);

    expect(() => {
      stt.emitFinal('a table for four', { startMs: 0, endMs: 100 });
    }).not.toThrow();

    await settle();

    // Still usable afterwards.
    expect(() => session.pushAudio(Buffer.from([1]))).not.toThrow();
  });

  describe('t0', () => {
    it('is unset until the caller finishes a turn', () => {
      const session = new CallSession(
        'call_1',
        'MZ1',
        new FakeStt(),
        fakePrisma().prisma,
      );

      expect(session.lastSpeechStoppedAt).toBeUndefined();
    });

    /** Phase 3 measures first-token and first-audio against this. */
    it('is recorded when the caller stops speaking', () => {
      const stt = new FakeStt();
      const session = new CallSession(
        'call_1',
        'MZ1',
        stt,
        fakePrisma().prisma,
      );

      const before = Date.now();
      stt.emitSpeechStopped();

      expect(session.lastSpeechStoppedAt).toBeGreaterThanOrEqual(before);
    });
  });

  /** Phase 3 hangs barge-in off this path; it must be wired today. */
  it('handles a speech-started event without throwing', () => {
    const stt = new FakeStt();
    new CallSession('call_1', 'MZ1', stt, fakePrisma().prisma);

    expect(() => stt.emitSpeechStarted()).not.toThrow();
  });

  it('closes the transcription session', async () => {
    const stt = new FakeStt();
    const session = new CallSession('call_1', 'MZ1', stt, fakePrisma().prisma);

    await session.close();

    expect(stt.closed).toBe(true);
  });

  it('passes a locale change through to transcription', () => {
    const stt = new FakeStt();
    const session = new CallSession('call_1', 'MZ1', stt, fakePrisma().prisma);

    session.setLocale('de');

    expect(stt.locale).toBe('de');
  });
});
