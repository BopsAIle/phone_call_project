import {
  MULAW_SILENCE,
  decodeMulaw,
  encodeMulaw,
  mulawToPcm16,
  pcm16ToMulaw,
} from './mulaw.codec';

/** The loudest magnitude mu-law can represent. Louder input clips to it. */
const MAX_REPRESENTABLE = 32124;

/** Input above this clips; the codec's own ceiling, before decoding. */
const CLIP = 32635;

/**
 * mu-law's coarsest step is at the top of the range, so a round trip inside the
 * representable range may be off by half of that step.
 */
const MAX_QUANTISATION_ERROR = 512;

describe('mu-law codec', () => {
  describe('code-space round trip', () => {
    // Every code except one survives decode → encode unchanged. 0x7F is
    // negative zero: it decodes to 0, and 0 encodes to positive zero (0xFF).
    // The pair is the only place the mapping is not injective, and knowing
    // that up front stops it from looking like an encoder bug.
    it('preserves all 256 codes except negative zero', () => {
      const changed: number[] = [];

      for (let code = 0; code < 256; code++) {
        if (pcm16ToMulaw(mulawToPcm16(code)) !== code) changed.push(code);
      }

      expect(changed).toEqual([0x7f]);
    });

    it('collapses negative zero onto positive zero', () => {
      expect(mulawToPcm16(0x7f)).toBe(0);
      expect(mulawToPcm16(0xff)).toBe(0);
      expect(pcm16ToMulaw(0)).toBe(0xff);
    });

    it('uses the quietest positive code as silence', () => {
      expect(mulawToPcm16(MULAW_SILENCE)).toBe(0);
    });
  });

  describe('amplitude', () => {
    it('stays within the quantisation bound across the representable range', () => {
      let worst = 0;

      for (let sample = -CLIP; sample <= CLIP; sample++) {
        const error = Math.abs(mulawToPcm16(pcm16ToMulaw(sample)) - sample);
        if (error > worst) worst = error;
      }

      expect(worst).toBeLessThanOrEqual(MAX_QUANTISATION_ERROR);
    });

    // Above CLIP the error is not quantisation, it is saturation: mu-law simply
    // cannot express ±32768. Asserting the clipped value is what proves the
    // magnitude was clamped rather than allowed to wrap.
    it('saturates rather than wrapping at the int16 extremes', () => {
      expect(mulawToPcm16(pcm16ToMulaw(32767))).toBe(MAX_REPRESENTABLE);
      expect(mulawToPcm16(pcm16ToMulaw(-32768))).toBe(-MAX_REPRESENTABLE);
    });

    // A sign-handling bug here is loud and obvious on a real call, and almost
    // invisible in code review.
    it('keeps the sign of every segment boundary', () => {
      for (let magnitude = 1; magnitude <= 16384; magnitude *= 2) {
        expect(mulawToPcm16(pcm16ToMulaw(magnitude))).toBeGreaterThanOrEqual(0);
        expect(mulawToPcm16(pcm16ToMulaw(-magnitude))).toBeLessThanOrEqual(0);
      }
    });

    it('keeps quiet samples quiet', () => {
      expect(Math.abs(mulawToPcm16(pcm16ToMulaw(100)))).toBeLessThan(200);
    });
  });

  describe('buffer helpers', () => {
    // Note the polarity: 0x00 is the loudest *negative* code and 0x80 the
    // loudest positive one. Getting this backwards inverts the waveform, which
    // is inaudible on its own and wrong everywhere it is mixed.
    it('decodes one sample per byte', () => {
      const decoded = decodeMulaw(Buffer.from([0xff, 0x7f, 0x00, 0x80]));

      expect(decoded).toHaveLength(4);
      expect(decoded[0]).toBe(0);
      expect(decoded[1]).toBe(0);
      expect(decoded[2]).toBe(-MAX_REPRESENTABLE);
      expect(decoded[3]).toBe(MAX_REPRESENTABLE);
    });

    it('encodes one byte per sample', () => {
      expect(encodeMulaw(Int16Array.from([0, 1000, -1000]))).toHaveLength(3);
    });

    it('round-trips a buffer through both helpers', () => {
      const original = Buffer.from(
        Array.from({ length: 160 }, (_, i) => (i * 7 + 3) & 0xff),
      );

      const restored = encodeMulaw(decodeMulaw(original));

      // 0x7F is the one code that does not survive; normalise it before
      // comparing so this test asserts the buffer helpers, not the collapse.
      const expected = Buffer.from(
        original.map((b) => (b === 0x7f ? 0xff : b)),
      );
      expect(restored).toEqual(expected);
    });
  });
});
