import { MULAW_FRAME_BYTES, MULAW_SILENCE } from './mulaw.codec';

/**
 * Cuts an arbitrary byte stream into exact 20 ms Twilio frames.
 *
 * TTS arrives in chunks sized by the HTTP response, not by the phone network,
 * so a chunk almost never divides evenly into 160-byte frames. The leftover has
 * to be carried into the next chunk rather than padded or dropped: padding
 * inserts a sliver of silence mid-word (a click, 50 times a second), and
 * dropping shortens the utterance and shifts everything after it.
 *
 * One instance per outbound audio stream.
 */
export class FrameBuffer {
  private remainder: Buffer = Buffer.alloc(0);

  constructor(private readonly frameBytes: number = MULAW_FRAME_BYTES) {}

  /** Bytes held back because they do not yet make a whole frame. */
  get pending(): number {
    return this.remainder.length;
  }

  /** Adds bytes and returns every whole frame that became available. */
  push(chunk: Buffer): Buffer[] {
    const available =
      this.remainder.length === 0
        ? chunk
        : Buffer.concat([this.remainder, chunk]);

    const wholeFrames = Math.floor(available.length / this.frameBytes);
    const frames: Buffer[] = [];

    for (let i = 0; i < wholeFrames; i++) {
      frames.push(
        available.subarray(i * this.frameBytes, (i + 1) * this.frameBytes),
      );
    }

    this.remainder = available.subarray(wholeFrames * this.frameBytes);

    return frames;
  }

  /**
   * Emits the tail, padded to a whole frame with mu-law silence.
   *
   * Call this at the end of an utterance, not between chunks — the padding is
   * what makes the final frame legal for Twilio, and inserting it mid-stream is
   * exactly the click this class exists to avoid.
   */
  flush(): Buffer | null {
    if (this.remainder.length === 0) return null;

    const frame = Buffer.alloc(this.frameBytes, MULAW_SILENCE);
    this.remainder.copy(frame);
    this.remainder = Buffer.alloc(0);

    return frame;
  }

  reset(): void {
    this.remainder = Buffer.alloc(0);
  }
}
