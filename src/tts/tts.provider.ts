/**
 * Text-to-speech. Implemented in Phase 3.
 *
 * Yields Twilio-ready audio — 160-byte, 20 ms, 8 kHz mu-law frames — so the
 * PCM 24 kHz output of the underlying model and the anti-aliased downsample to
 * 8 kHz are entirely the implementation's business.
 *
 * `signal` aborts an utterance mid-stream for barge-in.
 */
export interface TtsProvider {
  synthesize(opts: {
    text: string;
    locale: 'en' | 'de';
    signal: AbortSignal;
  }): AsyncIterable<Buffer>;
}
