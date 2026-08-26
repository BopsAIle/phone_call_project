import { FRAME_BYTES, SAMPLE_RATE } from "./protocol";

export function floatToPcm16(input: Float32Array): Int16Array {
  const out = new Int16Array(input.length);
  for (let i = 0; i < input.length; i++) {
    const s = Math.max(-1, Math.min(1, input[i] ?? 0));
    out[i] = s < 0 ? Math.round(s * 0x8000) : Math.round(s * 0x7fff);
  }
  return out;
}

export function pcm16ToFloat(bytes: ArrayBuffer): Float32Array {
  const view = new Int16Array(bytes.byteLength % 2 ? bytes.slice(0, bytes.byteLength - 1) : bytes);
  const out = new Float32Array(view.length);
  for (let i = 0; i < view.length; i++) {
    out[i] = (view[i] ?? 0) / 0x8000;
  }
  return out;
}

export function rms(samples: Float32Array): number {
  if (samples.length === 0) return 0;
  let sum = 0;
  for (let i = 0; i < samples.length; i++) {
    const v = samples[i] ?? 0;
    sum += v * v;
  }
  return Math.sqrt(sum / samples.length);
}

/**
 * Linear resample across chunk boundaries so 48 kHz (typical mic) → 16 kHz
 * without splitting a sample at the join.
 */
export class LinearResampler {
  private buf: number[] = [];
  private index = 0;
  private ratio: number;

  constructor(inRate: number, outRate = SAMPLE_RATE) {
    if (inRate <= 0 || outRate <= 0) {
      throw new Error("sample rates must be positive");
    }
    this.ratio = inRate / outRate;
  }

  setInputRate(inRate: number): void {
    this.ratio = inRate / SAMPLE_RATE;
  }

  push(input: Float32Array): Float32Array {
    for (let i = 0; i < input.length; i++) {
      this.buf.push(input[i] ?? 0);
    }
    const out: number[] = [];
    while (this.index + 1 < this.buf.length) {
      const i0 = Math.floor(this.index);
      const frac = this.index - i0;
      const s0 = this.buf[i0] ?? 0;
      const s1 = this.buf[i0 + 1] ?? s0;
      out.push(s0 + (s1 - s0) * frac);
      this.index += this.ratio;
    }
    const drop = Math.floor(this.index);
    if (drop > 0) {
      this.buf.splice(0, drop);
      this.index -= drop;
    }
    return Float32Array.from(out);
  }

  reset(): void {
    this.buf = [];
    this.index = 0;
  }
}

/** Gom PCM16 thành frame ~100 ms / 3200 byte như hợp đồng. */
export class PcmFramer {
  private leftover = new Uint8Array(0);

  constructor(private readonly frameBytes = FRAME_BYTES) {}

  push(pcm16: Int16Array): ArrayBuffer[] {
    const bytes = new Uint8Array(pcm16.buffer, pcm16.byteOffset, pcm16.byteLength);
    const merged = new Uint8Array(this.leftover.length + bytes.length);
    merged.set(this.leftover, 0);
    merged.set(bytes, this.leftover.length);

    const frames: ArrayBuffer[] = [];
    let offset = 0;
    while (offset + this.frameBytes <= merged.length) {
      const slice = merged.slice(offset, offset + this.frameBytes);
      frames.push(slice.buffer);
      offset += this.frameBytes;
    }
    this.leftover = merged.slice(offset);
    return frames;
  }

  reset(): void {
    this.leftover = new Uint8Array(0);
  }
}
