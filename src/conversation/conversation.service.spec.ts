import type { ConfigService } from '@nestjs/config';
import type { OpenAiLlmService } from '../llm/openai-llm.service';
import type { PrismaService } from '../prisma/prisma.service';
import type { OpenAiRealtimeSttService } from '../stt/openai-realtime-stt.service';
import type { SttSession } from '../stt/stt.provider';
import type { GreetingCache } from '../tts/greeting-cache';
import type { OpenAiTtsService } from '../tts/openai-tts.service';
import type { OutboundAudioSink } from './audio-sink';
import { ConversationService } from './conversation.service';

/**
 * The `close` mock is returned alongside the session rather than read back off
 * it, because asserting on `session.close` detaches the method from its object
 * — which the lint rule rightly objects to.
 */
function stubSttSession(close = jest.fn().mockResolvedValue(undefined)) {
  const session: SttSession = {
    pushAudio: jest.fn(),
    onPartial: jest.fn(),
    onFinal: jest.fn(),
    onSpeechStarted: jest.fn(),
    onSpeechStopped: jest.fn(),
    setLocale: jest.fn(),
    close,
  };

  return { session, close };
}

// Held separately rather than read back off the object, for the same reason
// the STT close mock is.
const playFrame = jest.fn();
const sink: OutboundAudioSink = {
  playFrame,
  mark: jest.fn(),
  clear: jest.fn(),
};

/** Everything `create` needs beyond the ids, which no test varies. */
const STORE = {
  greeting: 'Hello, you are speaking with an automated assistant.',
  storeName: 'Trattoria Bella',
  timezone: 'Europe/Berlin',
  sink,
};

function build(stt = stubSttSession()) {
  const createSession = jest.fn().mockResolvedValue(stt.session);

  const service = new ConversationService(
    { createSession } as unknown as OpenAiRealtimeSttService,
    { respond: jest.fn() } as unknown as OpenAiLlmService,
    { synthesize: jest.fn() } as unknown as OpenAiTtsService,
    { frames: jest.fn().mockResolvedValue([]) } as unknown as GreetingCache,
    { utterance: { create: jest.fn() } } as unknown as PrismaService,
    { get: jest.fn().mockReturnValue('en') } as unknown as ConfigService<
      never,
      true
    >,
  );

  return { service, createSession, close: stt.close };
}

describe('ConversationService', () => {
  it('registers a new conversation under its streamSid', async () => {
    const { service } = build();

    const created = await service.create({
      callId: 'call_1',
      streamSid: 'MZ1',
      ...STORE,
    });

    expect(service.get('MZ1')).toBe(created);
  });

  /** Log correlation: a transcription error has to name the call it came from. */
  it('passes the call id and locale down to the transcription session', async () => {
    const { service, createSession } = build();

    await service.create({
      callId: 'call_1',
      streamSid: 'MZ1',
      locale: 'de',
      ...STORE,
    });

    expect(createSession).toHaveBeenCalledWith({
      callId: 'call_1',
      locale: 'de',
    });
  });

  it('falls back to the configured default locale', async () => {
    const { service, createSession } = build();

    await service.create({ callId: 'call_1', streamSid: 'MZ1', ...STORE });

    expect(createSession).toHaveBeenCalledWith({
      callId: 'call_1',
      locale: 'en',
    });
  });

  /**
   * The greeting is the gateway's call to make, after the session is registered
   * — otherwise a mark echoing back off it has nowhere to land.
   */
  it('does not play the greeting on create', async () => {
    const { service } = build();

    await service.create({ callId: 'call_1', streamSid: 'MZ1', ...STORE });

    expect(playFrame).not.toHaveBeenCalled();
  });

  it('returns undefined for a stream it does not know', () => {
    const { service } = build();

    expect(service.get('MZ-nope')).toBeUndefined();
  });

  it('keeps concurrent calls separate', async () => {
    const { service } = build();

    const first = await service.create({
      callId: 'c1',
      streamSid: 'MZ1',
      ...STORE,
    });
    const second = await service.create({
      callId: 'c2',
      streamSid: 'MZ2',
      ...STORE,
    });

    expect(first).not.toBe(second);
    expect(service.get('MZ1')).toBe(first);
    expect(service.get('MZ2')).toBe(second);
  });

  describe('destroy', () => {
    it('closes the session and forgets it', async () => {
      const { service, close } = build();
      await service.create({ callId: 'call_1', streamSid: 'MZ1', ...STORE });

      await service.destroy('MZ1');

      expect(close).toHaveBeenCalledTimes(1);
      expect(service.get('MZ1')).toBeUndefined();
    });

    /**
     * The gateway's teardown is idempotent because `stop`, `close`, and `error`
     * can all fire for one call — this has to be too, or the second pass throws
     * inside a socket handler.
     */
    it('is idempotent', async () => {
      const { service, close } = build();
      await service.create({ callId: 'call_1', streamSid: 'MZ1', ...STORE });

      await service.destroy('MZ1');
      await expect(service.destroy('MZ1')).resolves.toBeUndefined();

      expect(close).toHaveBeenCalledTimes(1);
    });

    it('tolerates being asked for a stream that never existed', async () => {
      const { service } = build();

      await expect(service.destroy('MZ-nope')).resolves.toBeUndefined();
    });

    /** A failing close must not stop the call being finalised. */
    it('swallows a close failure', async () => {
      const { service } = build(
        stubSttSession(
          jest.fn().mockRejectedValue(new Error('socket already gone')),
        ),
      );
      await service.create({ callId: 'call_1', streamSid: 'MZ1', ...STORE });

      await expect(service.destroy('MZ1')).resolves.toBeUndefined();
      expect(service.get('MZ1')).toBeUndefined();
    });
  });
});
