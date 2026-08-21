import {
  appendAudio,
  parseServerEvent,
  realtimeHeaders,
  sessionUpdate,
  type SessionConfig,
} from './realtime-events.types';

const config: SessionConfig = {
  model: 'gpt-live-transcribe',
  languages: ['en'],
  delay: 'low',
  turnDetection: {
    threshold: 0.5,
    prefixPaddingMs: 300,
    silenceDurationMs: 500,
  },
};

describe('parseServerEvent', () => {
  it('reads a final transcript', () => {
    const result = parseServerEvent(
      JSON.stringify({
        type: 'conversation.item.input_audio_transcription.completed',
        item_id: 'item_1',
        transcript: 'a table for four on Friday',
      }),
    );

    expect(result).toEqual({
      kind: 'event',
      event: {
        type: 'conversation.item.input_audio_transcription.completed',
        item_id: 'item_1',
        transcript: 'a table for four on Friday',
      },
    });
  });

  it('reads a partial transcript', () => {
    const result = parseServerEvent(
      JSON.stringify({
        type: 'conversation.item.input_audio_transcription.delta',
        delta: 'a table for',
      }),
    );

    expect(result.kind).toBe('event');
    expect(result).toMatchObject({ event: { delta: 'a table for' } });
  });

  it('reads the VAD boundaries', () => {
    expect(
      parseServerEvent(
        JSON.stringify({
          type: 'input_audio_buffer.speech_started',
          audio_start_ms: 1200,
        }),
      ),
    ).toMatchObject({ event: { audio_start_ms: 1200 } });

    expect(
      parseServerEvent(
        JSON.stringify({
          type: 'input_audio_buffer.speech_stopped',
          audio_end_ms: 3400,
        }),
      ),
    ).toMatchObject({ event: { audio_end_ms: 3400 } });
  });

  /**
   * The documented fallback, exercised. `audio_start_ms` is one of the two
   * fields this phase verifies against a live session; if it is absent the
   * session must fall back to its own audio clock, so an event without it is
   * valid rather than malformed.
   */
  it('accepts a VAD event with no timestamp', () => {
    const result = parseServerEvent(
      JSON.stringify({ type: 'input_audio_buffer.speech_started' }),
    );

    expect(result).toEqual({
      kind: 'event',
      event: { type: 'input_audio_buffer.speech_started' },
    });
  });

  it('reads an error', () => {
    expect(
      parseServerEvent(
        JSON.stringify({
          type: 'error',
          error: {
            type: 'invalid_request_error',
            message: 'Unknown parameter',
          },
        }),
      ),
    ).toMatchObject({ event: { error: { message: 'Unknown parameter' } } });
  });

  it('reads the session acknowledgements', () => {
    expect(parseServerEvent('{"type":"session.created"}').kind).toBe('event');
    expect(parseServerEvent('{"type":"session.updated"}').kind).toBe('event');
  });

  /**
   * The distinction this parser exists for. OpenAI emits a wide vocabulary of
   * events several times per turn; reporting them the same way as a genuine
   * shape mismatch would bury the transcripts in the log.
   */
  it('reports an event type it does not handle as unhandled, not malformed', () => {
    expect(
      parseServerEvent(
        JSON.stringify({ type: 'rate_limits.updated', rate_limits: [] }),
      ),
    ).toEqual({ kind: 'unhandled', type: 'rate_limits.updated' });
  });

  it('reports a handled type in the wrong shape as malformed', () => {
    const result = parseServerEvent(
      JSON.stringify({
        type: 'conversation.item.input_audio_transcription.completed',
        // `transcript` missing — a real shape change to an event we depend on.
      }),
    );

    expect(result.kind).toBe('malformed');
    expect(result).toMatchObject({
      type: 'conversation.item.input_audio_transcription.completed',
    });
  });

  /**
   * The property that keeps a live call alive: nothing on this socket may throw.
   * An exception inside a `message` handler takes the process down, and with it
   * every other call in flight.
   */
  it('never throws, whatever arrives', () => {
    const garbage = [
      '',
      'not json at all',
      '{"unclosed": ',
      '[]',
      'null',
      '42',
      '{"type": 7}',
      '{"no": "type"}',
      Buffer.from([0xff, 0xfe, 0x00]),
    ];

    for (const raw of garbage) {
      expect(() => parseServerEvent(raw)).not.toThrow();
      expect(parseServerEvent(raw).kind).not.toBe('event');
    }
  });

  it('accepts a Buffer as readily as a string', () => {
    const raw = JSON.stringify({
      type: 'conversation.item.input_audio_transcription.completed',
      transcript: 'hello',
    });

    expect(parseServerEvent(Buffer.from(raw, 'utf8'))).toEqual(
      parseServerEvent(raw),
    );
  });
});

describe('sessionUpdate', () => {
  /**
   * The GA API rejects the beta's flat keys, and says so only as a generic
   * `error` event that does not name the offending parameter. The nesting is
   * therefore asserted here rather than discovered on a live call.
   */
  it('nests the config under session.audio.input', () => {
    const message: unknown = JSON.parse(sessionUpdate(config));

    expect(message).toEqual({
      type: 'session.update',
      session: {
        type: 'transcription',
        audio: {
          input: {
            format: { type: 'audio/pcm', rate: 24000 },
            transcription: {
              model: 'gpt-live-transcribe',
              languages: ['en'],
              delay: 'low',
            },
            turn_detection: {
              type: 'server_vad',
              threshold: 0.5,
              prefix_padding_ms: 300,
              silence_duration_ms: 500,
            },
          },
        },
      },
    });
  });

  it('carries none of the beta-era flat keys', () => {
    const raw = sessionUpdate(config);

    expect(raw).not.toContain('input_audio_format');
    expect(raw).not.toContain('input_audio_transcription');
    // Conversation-mode only; a transcription session must not ask for replies.
    expect(raw).not.toContain('create_response');
    expect(raw).not.toContain('interrupt_response');
  });

  it('sends languages as an array, never the singular field', () => {
    const message = JSON.parse(
      sessionUpdate({ ...config, languages: ['de'] }),
    ) as {
      session: {
        audio: {
          input: { transcription: { languages?: string[]; language?: string } };
        };
      };
    };
    const { transcription } = message.session.audio.input;

    expect(transcription.languages).toEqual(['de']);
    expect(transcription.language).toBeUndefined();
  });
});

describe('appendAudio', () => {
  it('carries the payload under `audio`', () => {
    expect(JSON.parse(appendAudio('AAEC'))).toEqual({
      type: 'input_audio_buffer.append',
      audio: 'AAEC',
    });
  });
});

describe('realtimeHeaders', () => {
  it('sends bearer auth and nothing else', () => {
    expect(realtimeHeaders('sk-test')).toEqual({
      Authorization: 'Bearer sk-test',
    });
  });

  /** Required during the beta, not on GA — and still in most tutorials. */
  it('does not send the beta header', () => {
    expect(Object.keys(realtimeHeaders('sk-test'))).not.toContain(
      'OpenAI-Beta',
    );
  });
});
