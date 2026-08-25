import { parseInbound, sessionInit, type SessionContext } from './wire-format';

const CONTEXT: SessionContext = {
  callId: 'call_1',
  storeName: 'Bella Vista',
  timezone: 'Europe/Berlin',
  locale: 'en',
  greeting: 'Thanks for calling Bella Vista.',
};

function text(value: unknown): Buffer {
  return Buffer.from(JSON.stringify(value), 'utf8');
}

describe('sessionInit', () => {
  it('carries every field the AI service needs to answer as this store', () => {
    expect(JSON.parse(sessionInit(CONTEXT, { resumed: false }))).toEqual({
      event: 'session.init',
      ...CONTEXT,
      resumed: false,
    });
  });

  /**
   * The flag that stops a mid-call reconnect greeting the caller a second time.
   * The context has to be resent — the AI service cannot recover it otherwise —
   * so `resumed` is what distinguishes the two cases.
   */
  it('marks a reconnect as resumed while still resending the context', () => {
    const parsed = JSON.parse(sessionInit(CONTEXT, { resumed: true })) as {
      resumed: boolean;
      storeName: string;
      greeting: string;
    };

    expect(parsed.resumed).toBe(true);
    expect(parsed.storeName).toBe('Bella Vista');
    expect(parsed.greeting).toBe('Thanks for calling Bella Vista.');
  });
});

describe('parseInbound', () => {
  it('treats any binary frame as audio, without inspecting it', () => {
    const pcm = Buffer.from([0x01, 0x02, 0x03, 0x04]);

    expect(parseInbound(pcm, true)).toEqual({ kind: 'audio', pcm });
  });

  /**
   * An odd length means a PCM16 sample was split across frames, which the
   * contract forbids. Passed through rather than dropped: `leToInt16` discards a
   * trailing odd byte by design, so the damage is one sample, where dropping the
   * frame would lose ~100 ms of speech and desynchronise everything after it.
   */
  it('passes an odd-length binary frame through rather than rejecting it', () => {
    const pcm = Buffer.from([0x01, 0x02, 0x03]);

    expect(parseInbound(pcm, true)).toEqual({ kind: 'audio', pcm });
  });

  it('recognises the interrupt event', () => {
    expect(parseInbound(text({ event: 'interrupt' }), false)).toEqual({
      kind: 'interrupt',
    });
  });

  /**
   * Additive by design: the contract says unknown events are ignored, so the AI
   * team can introduce messages without breaking a deployed backend.
   */
  it('reports an unknown event by name rather than failing', () => {
    expect(parseInbound(text({ event: 'response.done' }), false)).toEqual({
      kind: 'unhandled',
      event: 'response.done',
    });
  });

  it.each([
    ['not JSON at all', Buffer.from('<html>502</html>', 'utf8')],
    ['JSON without an event field', text({ hello: 'world' })],
    ['a JSON array', text([1, 2, 3])],
    ['an event that is not a string', text({ event: 42 })],
  ])('reports %s as malformed', (_label, raw) => {
    expect(parseInbound(raw, false)).toMatchObject({ kind: 'malformed' });
  });

  /**
   * An exception inside a socket's message handler takes down a live phone
   * call, so every one of these has to be a return value rather than a throw.
   */
  it('never throws, whatever arrives', () => {
    const nasty = [
      Buffer.alloc(0),
      Buffer.from([0xff, 0xfe, 0xfd]),
      text(null),
      text('a bare string'),
    ];

    for (const raw of nasty) {
      expect(() => parseInbound(raw, false)).not.toThrow();
    }
  });
});
