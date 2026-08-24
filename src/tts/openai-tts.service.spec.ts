import type { ConfigService } from '@nestjs/config';
import { MULAW_FRAME_BYTES } from '../audio/mulaw.codec';
import { int16ToLe } from '../audio/pcm';
import { OpenAiTtsService } from './openai-tts.service';

/** One second of 24 kHz PCM16: 24000 samples → 8000 mu-law bytes → 50 frames. */
const SAMPLES_PER_SECOND = 24000;

/** A gentle tone, so the anti-alias filter has something real to work on. */
function tone(samples: number): Buffer {
  const pcm = new Int16Array(samples);

  for (let i = 0; i < samples; i++) {
    pcm[i] = Math.round(
      8000 * Math.sin((2 * Math.PI * 440 * i) / SAMPLES_PER_SECOND),
    );
  }

  return int16ToLe(pcm);
}

function chunkInto(bytes: Buffer, size: number): Buffer[] {
  const chunks: Buffer[] = [];

  for (let at = 0; at < bytes.length; at += size) {
    chunks.push(bytes.subarray(at, at + size));
  }

  return chunks;
}

interface StubOptions {
  ok?: boolean;
  status?: number;
  errorBody?: string;
}

function stubFetch(chunks: Buffer[], options: StubOptions = {}) {
  const cancelled = { count: 0 };

  const fetchMock = jest.fn().mockImplementation(() => {
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        for (const chunk of chunks) controller.enqueue(new Uint8Array(chunk));
        controller.close();
      },
      cancel() {
        cancelled.count++;
      },
    });

    return Promise.resolve({
      ok: options.ok ?? true,
      status: options.status ?? 200,
      body,
      text: () => Promise.resolve(options.errorBody ?? ''),
    });
  });

  global.fetch = fetchMock;

  return { fetchMock, cancelled };
}

function buildService(): OpenAiTtsService {
  const values: Record<string, string> = {
    OPENAI_API_KEY: 'sk-test',
    TTS_MODEL: 'gpt-4o-mini-tts',
    TTS_VOICE: 'marin',
  };

  return new OpenAiTtsService({
    get: (key: string) => values[key],
  } as unknown as ConfigService<never, true>);
}

async function collect(
  service: OpenAiTtsService,
  signal = new AbortController().signal,
): Promise<Buffer[]> {
  const frames: Buffer[] = [];

  for await (const frame of service.synthesize({
    text: 'Of course, I can take a booking request for two.',
    locale: 'en',
    signal,
  })) {
    frames.push(frame);
  }

  return frames;
}

describe('OpenAiTtsService', () => {
  const originalFetch = global.fetch;

  afterEach(() => {
    global.fetch = originalFetch;
    jest.restoreAllMocks();
  });

  it('requests headerless PCM, which is what avoids a decode step', async () => {
    const { fetchMock } = stubFetch([tone(SAMPLES_PER_SECOND)]);

    await collect(buildService());

    const [, init] = fetchMock.mock.calls[0] as [string, { body: string }];
    const body = JSON.parse(init.body) as Record<string, unknown>;

    expect(body).toMatchObject({
      model: 'gpt-4o-mini-tts',
      voice: 'marin',
      response_format: 'pcm',
    });
    expect(body.instructions).toEqual(expect.stringContaining('warm'));
  });

  it('turns one second of 24 kHz PCM into 50 Twilio frames', async () => {
    stubFetch([tone(SAMPLES_PER_SECOND)]);

    const frames = await collect(buildService());

    expect(frames).toHaveLength(50);
    for (const frame of frames) expect(frame).toHaveLength(MULAW_FRAME_BYTES);
  });

  /**
   * The property that matters. HTTP chunks are sized by the transport, not by
   * the audio, so the same bytes arriving in different pieces must produce
   * identical frames — otherwise every chunk boundary is an audible click.
   */
  it('produces the same frames however the response is chunked', async () => {
    const pcm = tone(SAMPLES_PER_SECOND);

    stubFetch([pcm]);
    const atOnce = await collect(buildService());

    stubFetch(chunkInto(pcm, 4096));
    const evenly = await collect(buildService());

    // 999 is odd on purpose: every chunk boundary splits a sample in half.
    stubFetch(chunkInto(pcm, 999));
    const awkwardly = await collect(buildService());

    expect(Buffer.concat(evenly)).toEqual(Buffer.concat(atOnce));
    expect(Buffer.concat(awkwardly)).toEqual(Buffer.concat(atOnce));
  });

  /**
   * `leToInt16` drops a trailing odd byte by design, so a sample split across
   * two chunks has to be carried. Without that the stream loses a byte per
   * boundary and everything after it is byte-shifted — loud static, not silence.
   */
  it('carries a sample split across two chunks', async () => {
    const pcm = tone(SAMPLES_PER_SECOND / 4);

    stubFetch([pcm]);
    const whole = await collect(buildService());

    stubFetch([pcm.subarray(0, 4501), pcm.subarray(4501)]);
    const split = await collect(buildService());

    expect(Buffer.concat(split)).toEqual(Buffer.concat(whole));
  });

  it('pads a partial trailing frame rather than dropping it', async () => {
    // 8080 mu-law bytes: 50 whole frames and 80 bytes over.
    stubFetch([tone(SAMPLES_PER_SECOND + 240)]);

    const frames = await collect(buildService());

    expect(frames).toHaveLength(51);
    expect(frames[50]).toHaveLength(MULAW_FRAME_BYTES);
  });

  describe('abort', () => {
    it('stops yielding once the signal fires', async () => {
      stubFetch(chunkInto(tone(SAMPLES_PER_SECOND * 4), 2048));
      const controller = new AbortController();
      const frames: Buffer[] = [];

      for await (const frame of buildService().synthesize({
        text: 'a long reply',
        locale: 'en',
        signal: controller.signal,
      })) {
        frames.push(frame);
        if (frames.length === 3) controller.abort();
      }

      expect(frames.length).toBeLessThan(50);
    });

    /**
     * An aborted response whose body is never cancelled holds its socket open.
     * That only becomes visible after many interruptions on one long call —
     * exactly what barge-in produces.
     */
    it('cancels the response body so the socket is released', async () => {
      const { cancelled } = stubFetch(
        chunkInto(tone(SAMPLES_PER_SECOND * 4), 2048),
      );
      const controller = new AbortController();

      for await (const frame of buildService().synthesize({
        text: 'a long reply',
        locale: 'en',
        signal: controller.signal,
      })) {
        expect(frame).toBeInstanceOf(Buffer);
        controller.abort();
        break;
      }

      expect(cancelled.count).toBe(1);
    });

    /**
     * `CallSession` breaks out of its `for await` when a turn goes stale, which
     * is not the same path as aborting the signal. It has to release the socket
     * too, and it does — breaking a `for await` calls `.return()` on the
     * generator, which unwinds the `finally`.
     */
    it('cancels the body when the consumer just stops reading', async () => {
      const { cancelled } = stubFetch(
        chunkInto(tone(SAMPLES_PER_SECOND * 4), 2048),
      );

      for await (const frame of buildService().synthesize({
        text: 'a long reply',
        locale: 'en',
        signal: new AbortController().signal,
      })) {
        expect(frame).toBeInstanceOf(Buffer);
        break;
      }

      expect(cancelled.count).toBe(1);
    });

    /**
     * Cancelling a stream that has already closed is a no-op by the web-streams
     * spec, so a completed synthesis leaves nothing to release — asserted so
     * that the `finally` is never "fixed" into throwing on the happy path.
     */
    it('completes cleanly when the whole response is consumed', async () => {
      stubFetch([tone(SAMPLES_PER_SECOND)]);

      await expect(collect(buildService())).resolves.toHaveLength(50);
    });
  });

  /** The status alone is useless at three in the morning; the body says why. */
  it('surfaces the API complaint when the request is rejected', async () => {
    stubFetch([], {
      ok: false,
      status: 400,
      errorBody: '{"error":{"message":"Unknown voice: marin"}}',
    });

    await expect(collect(buildService())).rejects.toThrow('Unknown voice');
  });
});
