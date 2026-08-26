import type { ConfigService } from '@nestjs/config';
import type { AiSession } from '../ai-bridge/ai-bridge.provider';
import type { AiBridgeService } from '../ai-bridge/ai-bridge.service';
import type { OutboundAudioSink } from './audio-sink';
import { ConversationService } from './conversation.service';

/**
 * The `close` mock is returned alongside the session rather than read back off
 * it, because asserting on `session.close` detaches the method from its object
 * — which the lint rule rightly objects to.
 */
function stubAiSession(close = jest.fn().mockResolvedValue(undefined)) {
  const session: AiSession = {
    pushAudio: jest.fn(),
    onAudio: jest.fn(),
    onInterrupt: jest.fn(),
    close,
  };

  return { session, close };
}

// Held separately rather than read back off the object, for the same reason
// the AI close mock is.
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

function build(ai = stubAiSession()) {
  const createSession = jest.fn().mockResolvedValue(ai.session);

  const service = new ConversationService(
    { createSession } as unknown as AiBridgeService,
    { get: jest.fn().mockReturnValue('en') } as unknown as ConfigService<
      never,
      true
    >,
  );

  return { service, createSession, close: ai.close };
}

beforeEach(() => playFrame.mockClear());

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

  /**
   * The whole handshake in one assertion. The AI service composes no prompt of
   * its own, so every one of these fields has to arrive or the call is degraded:
   * no greeting, no store name, and "tonight" resolving against the wrong clock.
   */
  it('passes the full store context to the AI session', async () => {
    const { service, createSession } = build();

    await service.create({
      callId: 'call_1',
      streamSid: 'MZ1',
      locale: 'de',
      ...STORE,
    });

    expect(createSession).toHaveBeenCalledWith({
      callId: 'call_1',
      storeName: 'Trattoria Bella',
      timezone: 'Europe/Berlin',
      locale: 'de',
      greeting: STORE.greeting,
    });
  });

  it('falls back to the configured default locale', async () => {
    const { service, createSession } = build();

    await service.create({ callId: 'call_1', streamSid: 'MZ1', ...STORE });

    expect(createSession).toHaveBeenCalledWith(
      expect.objectContaining({ locale: 'en' }),
    );
  });

  /**
   * The greeting moved to the AI service, which speaks it on `session.init`.
   * Nothing in this repo synthesises audio any more, so `create` must not put a
   * frame on the wire itself.
   */
  it('plays no audio of its own on create', async () => {
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
        stubAiSession(
          jest.fn().mockRejectedValue(new Error('socket already gone')),
        ),
      );
      await service.create({ callId: 'call_1', streamSid: 'MZ1', ...STORE });

      await expect(service.destroy('MZ1')).resolves.toBeUndefined();
      expect(service.get('MZ1')).toBeUndefined();
    });
  });
});
