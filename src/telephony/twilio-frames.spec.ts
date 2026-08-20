import {
  clearMessage,
  markMessage,
  mediaMessage,
  parseInboundFrame,
} from './twilio-frames';

const STREAM_SID = 'MZ00000000000000000000000000000000';

describe('parseInboundFrame', () => {
  it('parses a start frame with its custom parameters', () => {
    const frame = parseInboundFrame(
      JSON.stringify({
        event: 'start',
        sequenceNumber: '1',
        streamSid: STREAM_SID,
        start: {
          streamSid: STREAM_SID,
          accountSid: 'AC00000000000000000000000000000000',
          callSid: 'CA00000000000000000000000000000000',
          tracks: ['inbound'],
          customParameters: { callId: 'call-1', storeId: 'store-1' },
          mediaFormat: {
            encoding: 'audio/x-mulaw',
            sampleRate: 8000,
            channels: 1,
          },
        },
      }),
    );

    expect(frame?.event).toBe('start');
    if (frame?.event !== 'start') throw new Error('narrowing');
    expect(frame.start.customParameters.callId).toBe('call-1');
    expect(frame.start.mediaFormat.sampleRate).toBe(8000);
  });

  it('defaults customParameters when the TwiML carried none', () => {
    const frame = parseInboundFrame(
      JSON.stringify({
        event: 'start',
        streamSid: STREAM_SID,
        start: {
          streamSid: STREAM_SID,
          accountSid: 'AC1',
          callSid: 'CA1',
          mediaFormat: {
            encoding: 'audio/x-mulaw',
            sampleRate: 8000,
            channels: 1,
          },
        },
      }),
    );

    if (frame?.event !== 'start') throw new Error('narrowing');
    expect(frame.start.customParameters).toEqual({});
  });

  it('parses a media frame', () => {
    const frame = parseInboundFrame(
      JSON.stringify({
        event: 'media',
        streamSid: STREAM_SID,
        media: {
          track: 'inbound',
          chunk: '1',
          timestamp: '20',
          payload: '//////8=',
        },
      }),
    );

    if (frame?.event !== 'media') throw new Error('narrowing');
    expect(frame.media.payload).toBe('//////8=');
  });

  it.each([
    ['connected', { event: 'connected', protocol: 'Call', version: '1.0.0' }],
    ['mark', { event: 'mark', streamSid: STREAM_SID, mark: { name: 'utt-1' } }],
    [
      'dtmf',
      {
        event: 'dtmf',
        streamSid: STREAM_SID,
        dtmf: { track: 'inbound_track', digit: '5' },
      },
    ],
    [
      'stop',
      {
        event: 'stop',
        streamSid: STREAM_SID,
        stop: { accountSid: 'AC1', callSid: 'CA1' },
      },
    ],
  ])('parses a %s frame', (event, payload) => {
    expect(parseInboundFrame(JSON.stringify(payload))?.event).toBe(event);
  });

  // Every one of these must be a log line rather than an exception: a throw
  // inside the socket's message handler ends a live phone call.
  it.each([
    ['an unknown event type', JSON.stringify({ event: 'somethingNew' })],
    ['malformed JSON', '{ not json'],
    ['an empty string', ''],
    ['a media frame with no payload', JSON.stringify({ event: 'media' })],
    [
      'a start frame with no media format',
      JSON.stringify({
        event: 'start',
        streamSid: STREAM_SID,
        start: { streamSid: STREAM_SID, accountSid: 'AC1', callSid: 'CA1' },
      }),
    ],
  ])('returns null for %s without throwing', (_label, raw) => {
    expect(() => parseInboundFrame(raw)).not.toThrow();
    expect(parseInboundFrame(raw)).toBeNull();
  });

  it('accepts a Buffer as well as a string', () => {
    const raw = Buffer.from(JSON.stringify({ event: 'connected' }));

    expect(parseInboundFrame(raw)?.event).toBe('connected');
  });
});

describe('outbound messages', () => {
  // Twilio discards a malformed message silently — no NACK, no console entry.
  // These assertions are the only thing standing between a typo and an
  // afternoon of debugging a barge-in that "does not work".
  it('builds a media message', () => {
    expect(JSON.parse(mediaMessage(STREAM_SID, 'abc123'))).toEqual({
      event: 'media',
      streamSid: STREAM_SID,
      media: { payload: 'abc123' },
    });
  });

  it('builds a mark message', () => {
    expect(JSON.parse(markMessage(STREAM_SID, 'utt-7-chunk-3'))).toEqual({
      event: 'mark',
      streamSid: STREAM_SID,
      mark: { name: 'utt-7-chunk-3' },
    });
  });

  it('builds a clear message with no payload of its own', () => {
    expect(JSON.parse(clearMessage(STREAM_SID))).toEqual({
      event: 'clear',
      streamSid: STREAM_SID,
    });
  });

  it('round-trips a media message back through the inbound parser', () => {
    const frame = parseInboundFrame(mediaMessage(STREAM_SID, 'abc123'));

    if (frame?.event !== 'media') throw new Error('narrowing');
    expect(frame.media.payload).toBe('abc123');
  });
});
