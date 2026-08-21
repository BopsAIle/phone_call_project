import { Role } from '../generated/prisma/enums';
import type { LlmProvider } from '../llm/llm.provider';
import type { ChatMessage, ToolCall } from '../llm/llm.types';
import type { PrismaService } from '../prisma/prisma.service';
import type { SttSession } from '../stt/stt.provider';
import type { GreetingCache } from '../tts/greeting-cache';
import type { TtsProvider } from '../tts/tts.provider';
import type { OutboundAudioSink } from './audio-sink';
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

  emitFinal(text: string, meta = { startMs: 0, endMs: 100 }): void {
    this.final(text, meta);
  }

  emitSpeechStarted(): void {
    this.started();
  }

  emitSpeechStopped(): void {
    this.stopped();
  }
}

/**
 * Yields one scripted reply per call, pausing between sentences so a test can
 * interrupt mid-reply the way a real caller does.
 */
class FakeLlm implements LlmProvider {
  /** Sentences to yield, one array per successive `respond` call. */
  script: string[][] = [];
  /** The full message list each call was given, copied at call time. */
  readonly requests: ChatMessage[][] = [];

  respond(opts: { messages: ChatMessage[]; signal: AbortSignal }): {
    sentences: AsyncIterable<string>;
    toolCalls: Promise<ToolCall[]>;
  } {
    this.requests.push(opts.messages.map((message) => ({ ...message })));

    const sentences = this.script.shift() ?? [];
    let settle!: (calls: ToolCall[]) => void;
    const toolCalls = new Promise<ToolCall[]>((resolve) => {
      settle = resolve;
    });

    async function* stream(): AsyncGenerator<string> {
      try {
        for (const sentence of sentences) {
          await Promise.resolve();
          if (opts.signal.aborted) return;

          yield sentence;
        }
      } finally {
        settle([]);
      }
    }

    return { sentences: stream(), toolCalls };
  }
}

class FakeTts implements TtsProvider {
  framesPerSentence = 2;
  readonly synthesised: string[] = [];

  async *synthesize(opts: {
    text: string;
    signal: AbortSignal;
  }): AsyncGenerator<Buffer> {
    this.synthesised.push(opts.text);

    for (let i = 0; i < this.framesPerSentence; i++) {
      await Promise.resolve();
      if (opts.signal.aborted) return;

      yield Buffer.alloc(160, i + 1);
    }
  }
}

function fakeSink() {
  const frames: Buffer[] = [];
  const marks: string[] = [];
  const state = { clears: 0 };

  const sink: OutboundAudioSink = {
    playFrame: (frame) => frames.push(frame),
    mark: (name) => marks.push(name),
    clear: () => state.clears++,
  };

  return { sink, frames, marks, state };
}

const GREETING = 'Hello, you are speaking with an automated assistant.';

function build(
  options: {
    create?: jest.Mock;
    greetingFrames?: Buffer[];
    greetingError?: Error;
  } = {},
) {
  const create = options.create ?? jest.fn().mockResolvedValue({});
  const stt = new FakeStt();
  const llm = new FakeLlm();
  const tts = new FakeTts();
  const { sink, frames, marks, state } = fakeSink();

  const greetingFrames = options.greetingFrames ?? [Buffer.alloc(160, 9)];

  // Held separately rather than read back off the object, because asserting on
  // `greetings.frames` detaches the method from it — which the lint rule
  // rightly objects to.
  const requestGreeting = options.greetingError
    ? jest.fn().mockRejectedValue(options.greetingError)
    : jest.fn().mockResolvedValue(greetingFrames);

  const greetings = { frames: requestGreeting } as unknown as GreetingCache;

  const session = new CallSession({
    callId: 'call_1',
    streamSid: 'MZ1',
    locale: 'en',
    greeting: GREETING,
    storeName: 'Trattoria Bella',
    timezone: 'Europe/Berlin',
    stt,
    llm,
    tts,
    greetings,
    sink,
    prisma: { utterance: { create } } as unknown as PrismaService,
  });

  return {
    session,
    stt,
    llm,
    tts,
    frames,
    marks,
    state,
    create,
    requestGreeting,
  };
}

/** The `data` of every Utterance row written, in order. */
function rows(create: jest.Mock): Record<string, unknown>[] {
  return create.mock.calls.map(
    ([arg]) => (arg as { data: Record<string, unknown> }).data,
  );
}

/** Lets the fire-and-forget turn and persistence work settle. */
async function settle(): Promise<void> {
  for (let i = 0; i < 10; i++) {
    await new Promise((resolve) => setImmediate(resolve));
  }
}

/** Runs one complete turn and returns once the agent is speaking. */
async function speakOneTurn(
  built: ReturnType<typeof build>,
  reply: string[] = ['First sentence.', 'Second sentence.'],
): Promise<void> {
  built.llm.script.push(reply);
  built.stt.emitSpeechStopped();
  built.stt.emitFinal('may I book a table for two');
  await settle();
}

describe('CallSession', () => {
  it('forwards audio to the transcription session', () => {
    const { session, stt } = build();

    session.pushAudio(Buffer.from([1, 2, 3]));

    expect(stt.pushed).toEqual([Buffer.from([1, 2, 3])]);
  });

  it('starts in GREETING', () => {
    expect(build().session.turnState).toBe('GREETING');
  });

  describe('the greeting', () => {
    it('plays the cached frames and marks the end', async () => {
      const built = build({
        greetingFrames: [Buffer.alloc(160, 1), Buffer.alloc(160, 2)],
      });

      await built.session.start();

      expect(built.frames).toHaveLength(2);
      expect(built.marks).toHaveLength(1);
    });

    /** Silence at pickup makes callers say "hello?" or hang up. */
    it('does not wait for the caller to speak first', async () => {
      const built = build();

      await built.session.start();

      expect(built.requestGreeting).toHaveBeenCalledWith(
        expect.objectContaining({ text: GREETING, locale: 'en' }),
      );
    });

    it('listens once Twilio reports the greeting has finished playing', async () => {
      const built = build();
      await built.session.start();

      expect(built.session.turnState).toBe('GREETING');
      built.session.onMarkPlayed(built.marks[0]);

      expect(built.session.turnState).toBe('LISTENING');
    });

    it('is recorded as an AGENT utterance', async () => {
      const built = build();

      await built.session.start();
      await settle();

      expect(rows(built.create)).toContainEqual(
        expect.objectContaining({
          role: Role.AGENT,
          text: GREETING,
          startMs: 0,
          endMs: null,
        }),
      );
    });

    /**
     * A call with no greeting is far better than a call that drops. Phase 6
     * turns this into a spoken apology rather than an awkward silence.
     */
    it('falls back to listening when synthesis fails', async () => {
      const built = build({ greetingError: new Error('openai is down') });

      await expect(built.session.start()).resolves.toBeUndefined();

      expect(built.session.turnState).toBe('LISTENING');
    });
  });

  describe('a full turn', () => {
    it('moves LISTENING → SPEAKING and writes frames for every sentence', async () => {
      const built = build();
      await built.session.start();
      built.session.onMarkPlayed(built.marks[0]);
      built.frames.length = 0;
      built.marks.length = 0;

      await speakOneTurn(built);

      expect(built.tts.synthesised).toEqual([
        'First sentence.',
        'Second sentence.',
      ]);
      expect(built.frames).toHaveLength(4);
      expect(built.session.turnState).toBe('SPEAKING');
    });

    it('sends one mark per sentence, so a long reply reports progress', async () => {
      const built = build();
      await built.session.start();
      built.marks.length = 0;

      await speakOneTurn(built);

      expect(built.marks).toHaveLength(2);
    });

    it('returns to LISTENING only once every mark has echoed back', async () => {
      const built = build();
      await built.session.start();
      built.session.onMarkPlayed(built.marks[0]);
      built.marks.length = 0;

      await speakOneTurn(built);

      built.session.onMarkPlayed(built.marks[0]);
      expect(built.session.turnState).toBe('SPEAKING');

      built.session.onMarkPlayed(built.marks[1]);
      expect(built.session.turnState).toBe('LISTENING');
    });

    it('persists the reply as one AGENT utterance with its latency', async () => {
      const built = build();
      await built.session.start();
      built.create.mockClear();

      await speakOneTurn(built);

      expect(rows(built.create)).toContainEqual(
        expect.objectContaining({
          role: Role.AGENT,
          text: 'First sentence. Second sentence.',
          endMs: null,
          latencyMs: expect.any(Number) as number,
        }),
      );
    });

    it('feeds the reply back into history for the next turn', async () => {
      const built = build();
      await built.session.start();

      await speakOneTurn(built, ['First reply.']);
      built.session.onMarkPlayed(built.marks[built.marks.length - 1]);
      await speakOneTurn(built, ['Second reply.']);

      const second = built.llm.requests[1];
      expect(second.map((message) => message.role)).toEqual([
        'system',
        'assistant',
        'user',
        'assistant',
        'user',
      ]);
      expect(second[3].content).toBe('First reply.');
    });

    /** The model said nothing. Do not sit in THINKING waiting for a mark. */
    it('recovers to LISTENING when the model produces no text', async () => {
      const built = build();
      await built.session.start();

      await speakOneTurn(built, []);

      expect(built.session.turnState).toBe('LISTENING');
    });
  });

  describe('barge-in', () => {
    it('aborts, clears Twilio’s buffer, and listens', async () => {
      const built = build();
      await built.session.start();
      built.session.onMarkPlayed(built.marks[0]);

      await speakOneTurn(built);
      expect(built.session.turnState).toBe('SPEAKING');

      built.stt.emitSpeechStarted();

      expect(built.state.clears).toBe(1);
      expect(built.session.turnState).toBe('LISTENING');
    });

    /**
     * The `clear` is the step that is easy to forget: aborting our own streams
     * does nothing about audio Twilio has already buffered.
     */
    it('stops writing frames once interrupted', async () => {
      const built = build();
      built.tts.framesPerSentence = 50;
      await built.session.start();

      built.llm.script.push(['A long reply.', 'Still going.']);
      built.stt.emitFinal('hello');
      await Promise.resolve();
      await Promise.resolve();

      built.stt.emitSpeechStarted();
      const written = built.frames.length;
      await settle();

      expect(built.frames.length).toBe(written);
    });

    it('drops queued sentences that were never synthesised', async () => {
      const built = build();
      built.tts.framesPerSentence = 30;
      await built.session.start();

      built.llm.script.push(['One.', 'Two.', 'Three.']);
      built.stt.emitFinal('hello');
      await Promise.resolve();
      await Promise.resolve();

      built.stt.emitSpeechStarted();
      await settle();

      expect(built.tts.synthesised.length).toBeLessThan(3);
    });

    it('works while still THINKING, before any audio has played', async () => {
      const built = build();
      await built.session.start();
      built.session.onMarkPlayed(built.marks[0]);

      built.llm.script.push(['A reply.']);
      built.stt.emitFinal('hello');
      expect(built.session.turnState).toBe('THINKING');

      built.stt.emitSpeechStarted();
      await settle();

      expect(built.session.turnState).toBe('LISTENING');
    });

    /** Nothing is playing, so there is nothing to interrupt. */
    it('is ignored while LISTENING', async () => {
      const built = build();
      await built.session.start();
      built.session.onMarkPlayed(built.marks[0]);

      built.stt.emitSpeechStarted();

      expect(built.state.clears).toBe(0);
      expect(built.session.turnState).toBe('LISTENING');
    });
  });

  /**
   * `gpt-live-transcribe` chunks audio itself, so one spoken turn can arrive as
   * two finals. Without merging, that is two replies talking over each other.
   */
  describe('a second final in the same caller turn', () => {
    it('merges it into the pending message and restarts the completion', async () => {
      const built = build();
      await built.session.start();
      built.session.onMarkPlayed(built.marks[0]);

      built.llm.script.push(['Abandoned reply.'], ['Merged reply.']);

      built.stt.emitFinal('I would like a table.');
      expect(built.session.turnState).toBe('THINKING');
      built.stt.emitFinal('For four people.');

      await settle();

      expect(built.llm.requests).toHaveLength(2);
      const restarted = built.llm.requests[1];
      expect(restarted[restarted.length - 1].content).toBe(
        'I would like a table. For four people.',
      );
    });

    it('speaks only the merged reply, never both', async () => {
      const built = build();
      await built.session.start();
      built.marks.length = 0;

      built.llm.script.push(['Abandoned reply.'], ['Merged reply.']);

      built.stt.emitFinal('I would like a table.');
      built.stt.emitFinal('For four people.');
      await settle();

      expect(built.tts.synthesised).toEqual(['Merged reply.']);
    });
  });

  describe('transcripts', () => {
    it('persists a final with the VAD boundaries', async () => {
      const built = build();

      built.stt.emitFinal('a table for four', { startMs: 1200, endMs: 3400 });
      await settle();

      expect(rows(built.create)).toContainEqual(
        expect.objectContaining({
          callId: 'call_1',
          role: Role.CALLER,
          text: 'a table for four',
          startMs: 1200,
          endMs: 3400,
        }),
      );
    });

    /** Partials revise themselves several times per sentence. */
    it('never persists a partial', async () => {
      const built = build();

      built.stt.emitPartial('a table');
      built.stt.emitPartial('a table for');
      await settle();

      expect(built.create).not.toHaveBeenCalled();
    });

    it('ignores an empty final rather than starting a turn on it', async () => {
      const built = build();
      await built.session.start();
      built.session.onMarkPlayed(built.marks[0]);

      built.stt.emitFinal('   ');
      await settle();

      expect(built.llm.requests).toHaveLength(0);
      expect(built.session.turnState).toBe('LISTENING');
    });

    /**
     * A phone call must not end because Postgres hiccuped. An unhandled
     * rejection inside a socket handler takes down every other call too.
     */
    it('survives a database failure without throwing', async () => {
      const built = build({
        create: jest.fn().mockRejectedValue(new Error('connection terminated')),
      });

      expect(() => built.stt.emitFinal('a table for four')).not.toThrow();
      await settle();

      expect(() => built.session.pushAudio(Buffer.from([1]))).not.toThrow();
    });
  });

  it('ignores a mark it never sent', async () => {
    const built = build();
    await built.session.start();

    expect(() => built.session.onMarkPlayed('dev-12345')).not.toThrow();
    expect(built.session.turnState).toBe('GREETING');
  });

  it('closes the transcription session', async () => {
    const built = build();

    await built.session.close();

    expect(built.stt.closed).toBe(true);
  });

  it('stops speaking when the call closes mid-reply', async () => {
    const built = build();
    built.tts.framesPerSentence = 50;
    await built.session.start();

    built.llm.script.push(['A long reply.']);
    built.stt.emitFinal('hello');
    await Promise.resolve();

    await built.session.close();
    const written = built.frames.length;
    await settle();

    expect(built.frames.length).toBe(written);
  });

  it('passes a locale change through to transcription', () => {
    const built = build();

    built.session.setLocale('de');

    expect(built.stt.locale).toBe('de');
  });
});
