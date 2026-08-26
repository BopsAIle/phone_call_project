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

/**
 * The rate the AI bridge runs at. Everything above exercises the 24 kHz default
 * that the OpenAI path uses; these repeat the assertions that could plausibly
 * break at a different ratio.
 */
const AI_BRIDGE_RATE = 16000;

describe('Upsampler (8k → 16k)', () => {
  it('produces two output samples per input sample', () => {
    expect(
      new Upsampler(AI_BRIDGE_RATE).process(sine(500, 8000, 1600)),
    ).toHaveLength(3200);
  });

  /**
   * The gain check at ratio 2. Zero-stuffing by 2 halves the amplitude, so
   * without the compensation this reads ~5000 instead of ~10000 — audio 6 dB
   * down, feeding the AI team quiet input with nothing reporting a problem.
   */
  it('preserves amplitude rather than losing 6 dB to zero-stuffing', () => {
    const output = new Upsampler(AI_BRIDGE_RATE).process(sine(500, 8000, 1600));

    expect(
      toneAmplitude(steadyState(output), 500, AI_BRIDGE_RATE),
    ).toBeGreaterThan(AMPLITUDE * 0.9);
  });

  it('carries filter state across block boundaries', () => {
    const input = sine(500, 8000, 1600);

    const wholeBlock = new Upsampler(AI_BRIDGE_RATE).process(input);

    const blockwise = new Upsampler(AI_BRIDGE_RATE);
    const pieces: number[] = [];
    // 160 samples is one 20 ms Twilio frame — the block size the bridge feeds it.
    for (let offset = 0; offset < input.length; offset += 160) {
      pieces.push(...blockwise.process(input.subarray(offset, offset + 160)));
    }

    expect(pieces).toEqual(Array.from(wholeBlock));
  });
});

describe('Downsampler (16k → 8k)', () => {
  it('produces one output sample per two input samples', () => {
    expect(
      new Downsampler(AI_BRIDGE_RATE).process(sine(1000, AI_BRIDGE_RATE, 3200)),
    ).toHaveLength(1600);
  });

  /**
   * The anti-aliasing assertion at 16 kHz. 6 kHz is above the 4 kHz Nyquist of
   * the output rate, so undecimated it folds down to 2 kHz. The transition band
   * is *narrower* in Hz at 16 kHz than at 24 kHz — (3.3/N) × fs — so the
   * stopband is established sooner and this should hold at least as well.
   */
  it('rejects a 6 kHz tone by more than 40 dB instead of aliasing it to 2 kHz', () => {
    const output = new Downsampler(AI_BRIDGE_RATE).process(
      sine(6000, AI_BRIDGE_RATE, 3200),
    );

    const alias = toneAmplitude(steadyState(output), 2000, 8000);

    expect(20 * Math.log10(AMPLITUDE / alias)).toBeGreaterThan(40);
  });

  it('keeps the decimation phase across blocks that are not multiples of two', () => {
    const input = sine(1000, AI_BRIDGE_RATE, 3200);

    const wholeBlock = new Downsampler(AI_BRIDGE_RATE).process(input);

    const blockwise = new Downsampler(AI_BRIDGE_RATE);
    const pieces: number[] = [];
    for (let offset = 0; offset < input.length; offset += 161) {
      pieces.push(...blockwise.process(input.subarray(offset, offset + 161)));
    }

    expect(pieces).toEqual(Array.from(wholeBlock));
  });
});

describe('round trip at 16 kHz', () => {
  it('preserves both the frequency and the level of a 500 Hz tone', () => {
    const restored = new Downsampler(AI_BRIDGE_RATE).process(
      new Upsampler(AI_BRIDGE_RATE).process(sine(500, 8000, 4800)),
    );

    const amplitude = toneAmplitude(steadyState(restored), 500, 8000);

    expect(amplitude).toBeGreaterThan(AMPLITUDE * 0.9);
    expect(amplitude).toBeLessThan(AMPLITUDE * 1.1);
  });
});

describe('rate validation', () => {
  /**
   * A fractional ratio breaks the premise the whole file rests on. It would
   * surface as audio subtly the wrong length, drifting further out every frame
   * — so it throws at construction rather than at the first sample.
   */
  it.each([22050, 44100, 11025, 0])('rejects %i Hz', (rate) => {
    expect(() => new Upsampler(rate)).toThrow(/whole multiple/);
    expect(() => new Downsampler(rate)).toThrow(/whole multiple/);
  });

  it('accepts 8 kHz as a no-op ratio of 1', () => {
    expect(() => new Upsampler(8000)).not.toThrow();
  });
});
