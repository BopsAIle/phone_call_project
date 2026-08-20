/**
 * G.711 mu-law codec — the format Twilio speaks.
 *
 * 8-bit companded, 8 kHz, one byte per sample, 160 bytes per 20 ms frame.
 * Everything here is a pure function over numbers and buffers; nothing in this
 * file knows about Twilio, Nest, or the network.
 */

/** Twilio's frame size: 20 ms of 8 kHz mono mu-law. */
export const MULAW_FRAME_BYTES = 160;

/** Twilio's sample rate. */
export const TELEPHONY_SAMPLE_RATE = 8000;

/** What OpenAI's realtime API takes on the way in and hands back on the way out. */
export const OPENAI_SAMPLE_RATE = 24000;

/**
 * The quietest positive code. Decodes to exactly 0, so it is what to pad a
 * short frame with — 0x00 is the *loudest negative* sample, not silence.
 */
export const MULAW_SILENCE = 0xff;

const BIAS = 0x84;
const CLIP = 32635;

/**
 * Segment (exponent) for a biased magnitude, indexed by `magnitude >> 7`.
 *
 * The published version of this table is 256 hand-written entries. It is just
 * the index of the highest set bit, so it is generated instead — a typo in a
 * copied table produces audio that is quiet and distorted only in one amplitude
 * band, which is close to undiagnosable by ear.
 */
const EXP_LUT = new Uint8Array(256);
for (let i = 1; i < 256; i++) {
  EXP_LUT[i] = 31 - Math.clz32(i);
}

/**
 * Decode table for all 256 codes, built once at module load.
 *
 * There are only 256 possible inputs; computing the expansion per sample would
 * be 8000 redundant shifts per second per call.
 */
const DECODE_LUT = new Int16Array(256);
for (let code = 0; code < 256; code++) {
  const u = ~code & 0xff;
  const magnitude = (((u & 0x0f) << 3) + BIAS) << ((u & 0x70) >> 4);
  DECODE_LUT[code] = u & 0x80 ? BIAS - magnitude : magnitude - BIAS;
}

/** One mu-law byte to one signed 16-bit sample. */
export function mulawToPcm16(code: number): number {
  return DECODE_LUT[code & 0xff];
}

/**
 * One signed 16-bit sample to one mu-law byte, by the canonical Sun algorithm.
 *
 * The magnitude is negated in JavaScript's 64-bit float space, so `-32768` does
 * not overflow back to itself the way it does in the C original — it clips to
 * `CLIP` like any other loud negative sample.
 */
export function pcm16ToMulaw(sample: number): number {
  const sign = (sample >> 8) & 0x80;

  let magnitude = sign ? -sample : sample;
  if (magnitude > CLIP) magnitude = CLIP;
  magnitude += BIAS;

  const exponent = EXP_LUT[(magnitude >> 7) & 0xff];
  const mantissa = (magnitude >> (exponent + 3)) & 0x0f;

  return ~(sign | (exponent << 4) | mantissa) & 0xff;
}

/** A buffer of mu-law bytes to 16-bit PCM, one sample per input byte. */
export function decodeMulaw(mulaw: Buffer): Int16Array {
  const pcm = new Int16Array(mulaw.length);

  for (let i = 0; i < mulaw.length; i++) {
    pcm[i] = DECODE_LUT[mulaw[i]];
  }

  return pcm;
}

/** 16-bit PCM to mu-law, one output byte per input sample. */
export function encodeMulaw(pcm: Int16Array): Buffer {
  const mulaw = Buffer.allocUnsafe(pcm.length);

  for (let i = 0; i < pcm.length; i++) {
    mulaw[i] = pcm16ToMulaw(pcm[i]);
  }

  return mulaw;
}
