import { Downsampler, Upsampler } from './resampler';

/**
 * Goertzel: the amplitude of one frequency in a block of samples.
 *
 * Every assertion here is "how much of tone X survived", which is a single bin
 * of a DFT — running a whole FFT to read one bin, or eyeballing a spectrum,
 * would be more code and less certain.
 */
function toneAmplitude(
  samples: Int16Array,
  freqHz: number,
  sampleRateHz: number,
): number {
  const coeff = 2 * Math.cos((2 * Math.PI * freqHz) / sampleRateHz);
  let s1 = 0;
  let s2 = 0;

  for (const sample of samples) {
    const s0 = sample + coeff * s1 - s2;
    s2 = s1;
    s1 = s0;
  }

  const magnitude = Math.sqrt(s1 * s1 + s2 * s2 - coeff * s1 * s2);
  return (2 * magnitude) / samples.length;
}

function sine(
  freqHz: number,
  sampleRateHz: number,
  samples: number,
  amplitude = 10000,
): Int16Array {
  const out = new Int16Array(samples);

  for (let i = 0; i < samples; i++) {
    out[i] = Math.round(
      amplitude * Math.sin((2 * Math.PI * freqHz * i) / sampleRateHz),
    );
  }

  return out;
}

/** Skip filter start-up before measuring; the first taps are a transient. */
function steadyState(samples: Int16Array): Int16Array {
  return samples.subarray(100);
}

const AMPLITUDE = 10000;

describe('Downsampler (24k → 8k)', () => {
  it('produces one output sample per three input samples', () => {
    expect(new Downsampler().process(sine(1000, 24000, 4800))).toHaveLength(
      1600,
    );
  });

  it('passes a 1 kHz tone through at its original level', () => {
    const output = new Downsampler().process(sine(1000, 24000, 4800));

    expect(toneAmplitude(steadyState(output), 1000, 8000)).toBeGreaterThan(
      AMPLITUDE * 0.9,
    );
  });

  /**
   * The test this whole class exists for. 6 kHz is above the 4 kHz Nyquist
   * limit of the output rate, so undecimated it folds down to 2 kHz and appears
   * as a loud spurious tone. Measuring 6 kHz would be meaningless — that
   * frequency cannot exist in an 8 kHz signal — so the assertion is on the
   * 2 kHz bin, where the alias would land.
   */
  it('rejects a 6 kHz tone by more than 40 dB instead of aliasing it to 2 kHz', () => {
    const output = new Downsampler().process(sine(6000, 24000, 4800));

    const alias = toneAmplitude(steadyState(output), 2000, 8000);
    const attenuationDb = 20 * Math.log10(AMPLITUDE / alias);

    expect(attenuationDb).toBeGreaterThan(40);
  });

  it('carries filter state across block boundaries', () => {
    const input = sine(1000, 24000, 4800);

    const wholeBlock = new Downsampler().process(input);

    const blockwise = new Downsampler();
    const pieces: number[] = [];
    for (let offset = 0; offset < input.length; offset += 480) {
      pieces.push(...blockwise.process(input.subarray(offset, offset + 480)));
    }

    // 480 samples is 20 ms at 24 kHz — the block size Phase 3 will feed it.
    expect(Array.from(wholeBlock)).toEqual(pieces);
  });

  it('keeps the decimation phase across blocks that are not multiples of three', () => {
    const input = sine(1000, 24000, 4800);

    const wholeBlock = new Downsampler().process(input);

    const blockwise = new Downsampler();
    const pieces: number[] = [];
    for (let offset = 0; offset < input.length; offset += 161) {
      pieces.push(...blockwise.process(input.subarray(offset, offset + 161)));
    }

    expect(pieces).toEqual(Array.from(wholeBlock));
  });
});

describe('Upsampler (8k → 24k)', () => {
  it('produces three output samples per input sample', () => {
    expect(new Upsampler().process(sine(500, 8000, 1600))).toHaveLength(4800);
  });

  /**
   * The ×3 gain check. Zero-stuffing by 3 and filtering divides amplitude by 3,
   * so without the compensation this reads ~3333 instead of ~10000 — audio
   * 9.5 dB down, with nothing anywhere reporting a problem.
   */
  it('preserves amplitude rather than losing 9.5 dB to zero-stuffing', () => {
    const output = new Upsampler().process(sine(500, 8000, 1600));

    expect(toneAmplitude(steadyState(output), 500, 24000)).toBeGreaterThan(
      AMPLITUDE * 0.9,
    );
  });

  it('carries filter state across block boundaries', () => {
    const input = sine(500, 8000, 1600);

    const wholeBlock = new Upsampler().process(input);

    const blockwise = new Upsampler();
    const pieces: number[] = [];
    for (let offset = 0; offset < input.length; offset += 160) {
      pieces.push(...blockwise.process(input.subarray(offset, offset + 160)));
    }

    expect(pieces).toEqual(Array.from(wholeBlock));
  });
});

describe('round trip', () => {
  it('preserves both the frequency and the level of a 500 Hz tone', () => {
    const original = sine(500, 8000, 4800);

    const restored = new Downsampler().process(
      new Upsampler().process(original),
    );

    const amplitude = toneAmplitude(steadyState(restored), 500, 8000);

    expect(amplitude).toBeGreaterThan(AMPLITUDE * 0.9);
    expect(amplitude).toBeLessThan(AMPLITUDE * 1.1);
  });
});
