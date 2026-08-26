/**
 * 8 kHz ↔ wideband sample-rate conversion, for any integer multiple of 8 kHz.
 *
 * The ratio is a whole number — 3 for the 24 kHz OpenAI realtime path, 2 for the
 * 16 kHz AI-bridge path — so there is no fractional resampling and no phase
 * drift to accumulate. The only state that has to survive between frames is the
 * FIR filter's history, and (for the downsampler) which input sample the next
 * output lands on.
 *
 * Both directions are stateful objects rather than pure functions on purpose:
 * a 20 ms frame is far shorter than the filter, so a filter that restarted each
 * frame would ring at every 20 ms boundary. That is audible as a click 50 times
 * a second. One instance per call, per direction.
 *
 * The rate is a constructor argument rather than a module constant because two
 * consumers with different rates coexist during the migration to the external
 * AI bridge. It defaults to the 24 kHz OpenAI rate so existing callers are
 * unaffected; the default goes away with the last of them.
 */

import { OPENAI_SAMPLE_RATE, TELEPHONY_SAMPLE_RATE } from './mulaw.codec';

/**
 * Enough taps to put 6 kHz deep in the stopband, few enough to stay cheap.
 *
 * A Hamming window gives ~53 dB of stopband rejection and a transition band of
 * roughly 3.3/N — about 1.6 kHz at 24 kHz. With the cutoff at 3.4 kHz the
 * stopband is fully established by ~4.2 kHz, so content between 3.4 and 4 kHz
 * rolls off gradually. That is correct for telephony (the phone band ends at
 * 3.4 kHz) and is not a defect to be "fixed" with more taps and more latency.
 *
 * The same count holds at 16 kHz. Transition width is `(3.3/N) × fs`, so a lower
 * rate makes the filter *narrower* in Hz — ~1.1 kHz rather than ~1.65 kHz — which
 * puts the stopband fully in place below the 4 kHz Nyquist of the 8 kHz side.
 * Fewer taps would do at 16 kHz; keeping one number for both rates is worth more
 * than the handful of multiplies it saves.
 */
const TAPS = 48;

/** Just under the 4 kHz Nyquist limit of the 8 kHz side, at the phone band edge. */
const CUTOFF_HZ = 3400;

/**
 * Windowed-sinc low-pass, normalised to unity gain at DC.
 *
 * Unity DC gain means the filter neither adds nor removes level, which keeps
 * the upsampler's ×3 compensation below explicit instead of folded invisibly
 * into the coefficients.
 */
function designLowPass(
  taps: number,
  cutoffHz: number,
  sampleRateHz: number,
): Float64Array {
  const fc = cutoffHz / sampleRateHz;
  const centre = (taps - 1) / 2;
  const h = new Float64Array(taps);
  let sum = 0;

  for (let i = 0; i < taps; i++) {
    const x = i - centre;
    const sinc =
      x === 0 ? 2 * fc : Math.sin(2 * Math.PI * fc * x) / (Math.PI * x);
    const hamming = 0.54 - 0.46 * Math.cos((2 * Math.PI * i) / (taps - 1));

    h[i] = sinc * hamming;
    sum += h[i];
  }

  for (let i = 0; i < taps; i++) h[i] /= sum;

  return h;
}

/**
 * Coefficients per wideband rate, designed once and shared.
 *
 * Both directions run their filter at the wideband rate, so one table serves
 * each. Designing 48 taps is cheap, but it happens per call per direction, and
 * only one or two distinct rates ever exist in a process — a Map keyed on the
 * rate is simpler than threading a prebuilt table through the constructors.
 */
const coefficientCache = new Map<number, Float64Array>();

function coefficientsFor(sampleRateHz: number): Float64Array {
  const cached = coefficientCache.get(sampleRateHz);
  if (cached) return cached;

  const designed = designLowPass(TAPS, CUTOFF_HZ, sampleRateHz);
  coefficientCache.set(sampleRateHz, designed);

  return designed;
}

/**
 * The whole-number ratio between the wideband rate and 8 kHz.
 *
 * Throws rather than rounding. A fractional ratio breaks the premise the entire
 * file rests on — no phase drift to accumulate — and the failure would surface
 * as audio that is subtly the wrong length and drifts further out with every
 * frame, which is close to undiagnosable by ear.
 */
function ratioFor(sampleRateHz: number): number {
  const ratio = sampleRateHz / TELEPHONY_SAMPLE_RATE;

  if (!Number.isInteger(ratio) || ratio < 1) {
    throw new Error(
      `Wideband rate ${sampleRateHz} Hz is not a whole multiple of ${TELEPHONY_SAMPLE_RATE} Hz`,
    );
  }

  return ratio;
}

function toInt16(value: number): number {
  const rounded = Math.round(value);
  if (rounded > 32767) return 32767;
  if (rounded < -32768) return -32768;
  return rounded;
}

/**
 * Wideband → 8 kHz, for agent audio on its way to Twilio.
 *
 * **Low-pass first, then take every Nth sample.** Decimating without the filter
 * folds everything above 4 kHz back into the audible band; the result sounds
 * tinny and harsh, and is routinely misdiagnosed as a bad TTS voice.
 */
export class Downsampler {
  private readonly history = new Float64Array(TAPS - 1);
  private readonly coefficients: Float64Array;
  private readonly ratio: number;

  /**
   * Which input sample the next output is taken from, modulo the ratio. Without
   * this the decimation phase resets every frame and the output is `ratio`×
   * too long at the seams.
   */
  private phase = 0;

  constructor(sampleRateHz: number = OPENAI_SAMPLE_RATE) {
    // Validated before the filter is designed: `designLowPass` at a zero or
    // fractional rate returns NaN coefficients rather than throwing, and would
    // cache them under that rate for the life of the process.
    this.ratio = ratioFor(sampleRateHz);
    this.coefficients = coefficientsFor(sampleRateHz);
  }

  reset(): void {
    this.history.fill(0);
    this.phase = 0;
  }

  process(input: Int16Array): Int16Array {
    const window = new Float64Array(this.history.length + input.length);
    window.set(this.history, 0);
    for (let i = 0; i < input.length; i++) {
      window[this.history.length + i] = input[i];
    }

    const outputCount = Math.ceil((input.length - this.phase) / this.ratio);
    const output = new Int16Array(Math.max(0, outputCount));

    let written = 0;
    for (let i = this.phase; i < input.length; i += this.ratio) {
      let accumulator = 0;
      for (let k = 0; k < TAPS; k++) {
        accumulator += this.coefficients[k] * window[i + TAPS - 1 - k];
      }
      output[written++] = toInt16(accumulator);
    }

    this.phase = (this.phase - input.length) % this.ratio;
    if (this.phase < 0) this.phase += this.ratio;

    this.history.set(window.subarray(window.length - this.history.length));

    return output;
  }
}

/**
 * 8 kHz → wideband, for caller audio on its way to the recogniser.
 *
 * Zero-stuff, low-pass, then **multiply by the ratio**. The gain step is not
 * cosmetic: inserting L-1 zeros and filtering divides the amplitude by L, so
 * without it every request is fed audio ~9.5 dB down at ratio 3, or ~6 dB down
 * at ratio 2. Nothing throws and recognition mostly still works — it just gets
 * quietly worse on quiet callers, which reads as a weak model rather than a
 * resampler bug.
 */
export class Upsampler {
  private readonly history = new Float64Array(TAPS - 1);
  private readonly coefficients: Float64Array;
  private readonly ratio: number;

  constructor(sampleRateHz: number = OPENAI_SAMPLE_RATE) {
    // Validated first, for the reason given in `Downsampler`.
    this.ratio = ratioFor(sampleRateHz);
    this.coefficients = coefficientsFor(sampleRateHz);
  }

  reset(): void {
    this.history.fill(0);
  }

  process(input: Int16Array): Int16Array {
    const stuffedLength = input.length * this.ratio;
    const window = new Float64Array(this.history.length + stuffedLength);
    window.set(this.history, 0);
    for (let i = 0; i < input.length; i++) {
      window[this.history.length + i * this.ratio] = input[i];
    }

    const output = new Int16Array(stuffedLength);
    for (let i = 0; i < stuffedLength; i++) {
      let accumulator = 0;
      for (let k = 0; k < TAPS; k++) {
        accumulator += this.coefficients[k] * window[i + TAPS - 1 - k];
      }
      output[i] = toInt16(accumulator * this.ratio);
    }

    this.history.set(window.subarray(window.length - this.history.length));

    return output;
  }
}
