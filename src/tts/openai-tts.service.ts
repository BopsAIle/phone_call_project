import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { FrameBuffer } from '../audio/frame-buffer';
import { encodeMulaw } from '../audio/mulaw.codec';
import { leToInt16 } from '../audio/pcm';
import { Downsampler } from '../audio/resampler';
import type { Env } from '../config/env.schema';
import type { TtsProvider } from './tts.provider';

const SPEECH_URL = 'https://api.openai.com/v1/audio/speech';

/**
 * How the agent should sound. Phase 5 tunes the German copy against real callers.
 *
 * This is delivery, not content — the words themselves come from the LLM. Left
 * unset the model reads at a brisk, flat pace that sounds like a robocall.
 */
const INSTRUCTIONS: Record<'en' | 'de', string> = {
  en: 'Speak in a warm, professional, unhurried tone, like a friendly restaurant host.',
  de: 'Sprich ruhig, freundlich und deutlich, wie ein zuvorkommender Gastgeber im Restaurant.',
};

/**
 * Text to Twilio-ready audio.
 *
 * Raw `fetch` rather than the SDK, deliberately: the response is a stream of raw
 * bytes rather than SSE, so the SDK would only sit between `response.body` and
 * the frame chunker — and this is the path where an aborted response whose body
 * is never cancelled leaks a socket.
 *
 * Confirmed against the live API on 2026-08-21: `response_format: "pcm"` returns
 * `Content-Type: audio/pcm`, `Transfer-Encoding: chunked`, and the body begins on
 * sample data with no RIFF header to strip.
 */
@Injectable()
export class OpenAiTtsService implements TtsProvider {
  private readonly logger = new Logger(OpenAiTtsService.name);
  private readonly apiKey: string;
  private readonly model: string;
  private readonly voice: string;

  constructor(config: ConfigService<Env, true>) {
    this.apiKey = config.get('OPENAI_API_KEY', { infer: true });
    this.model = config.get('TTS_MODEL', { infer: true });
    this.voice = config.get('TTS_VOICE', { infer: true });
  }

  /**
   * Yields 160-byte, 20 ms, 8 kHz mu-law frames — Twilio's format exactly.
   *
   * One `Downsampler` and one `FrameBuffer` for the whole call, shared across
   * this response's HTTP chunks. Fresh instances per chunk would restart the
   * 48-tap filter at every arbitrary transport boundary, which rings audibly;
   * instances shared across *sentences* are unnecessary, because each sentence
   * is its own request and starts from silence.
   */
  async *synthesize(opts: {
    text: string;
    locale: 'en' | 'de';
    signal: AbortSignal;
  }): AsyncGenerator<Buffer> {
    const startedAt = Date.now();
    const downsampler = new Downsampler();
    const frames = new FrameBuffer();

    const response = await fetch(SPEECH_URL, {
      method: 'POST',
      signal: opts.signal,
      headers: {
        Authorization: `Bearer ${this.apiKey}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        model: this.model,
        voice: this.voice,
        input: opts.text,
        response_format: 'pcm',
        instructions: INSTRUCTIONS[opts.locale],
      }),
    });

    if (!response.ok || !response.body) {
      // Read the body for the message: OpenAI puts the actual complaint there,
      // and the status alone ("400") is useless at three in the morning.
      const detail = await response.text().catch(() => '');
      throw new Error(
        `Speech synthesis failed: ${response.status} ${detail.slice(0, 300)}`,
      );
    }

    const reader = response.body.getReader();

    /**
     * A sample split across two HTTP chunks.
     *
     * `leToInt16` drops a trailing odd byte by design, so without carrying it
     * the stream loses one byte per chunk boundary and every sample after it is
     * shifted — which is not silence but loud static.
     */
    let carry = Buffer.alloc(0);
    let firstFrame = true;

    try {
      for (;;) {
        // Checked explicitly rather than relying on `fetch` to tear the socket
        // down. It usually does — but once the body is buffered there is
        // nothing left to abort, and the loop would happily play out a reply
        // the caller has already talked over.
        if (opts.signal.aborted) break;

        const { done, value } = await reader.read();
        if (done) break;

        const bytes =
          carry.length === 0
            ? Buffer.from(value)
            : Buffer.concat([carry, Buffer.from(value)]);

        const usable = bytes.length - (bytes.length % 2);
        carry = bytes.subarray(usable);

        if (usable === 0) continue;

        const pcm8k = downsampler.process(leToInt16(bytes.subarray(0, usable)));

        for (const frame of frames.push(encodeMulaw(pcm8k))) {
          if (firstFrame) {
            firstFrame = false;
            this.logger.debug(`First audio +${Date.now() - startedAt}ms`);
          }

          yield frame;
        }
      }

      // The tail, padded to a whole frame. Dropping it would clip the last
      // syllable of every sentence.
      const tail = frames.flush();
      if (tail) yield tail;
    } finally {
      /**
       * Runs on abort and when the consumer breaks out of its `for await`.
       *
       * An aborted fetch whose body is never cancelled holds its socket open,
       * and that only becomes visible after many interruptions on a long call —
       * exactly the case barge-in produces. `cancel` on an already-errored
       * stream throws, and there is nothing useful to do about it here.
       */
      await reader.cancel().catch(() => undefined);
    }
  }
}
