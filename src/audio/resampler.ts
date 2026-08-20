/**
 * 8 kHz ↔ 24 kHz sample-rate conversion.
 *
 * The ratio is exactly 1:3, so there is no fractional resampling and no phase
 * drift to accumulate — the only state that has to survive between frames is
 * the FIR filter's history, and (for the downsampler) which of every three
 * input samples the next output lands on.
 *
 * Both directions are stateful objects rather than pure functions on purpose:
 * a 20 ms frame is far shorter than the filter, so a filter that restarted each
 * frame would ring at every 20 ms boundary. That is audible as a click 50 times
 * a second. One instance per call, per direction.
 */

import { OPENAI_SAMPLE_RATE, TELEPHONY_SAMPLE_RATE } from './mulaw.codec';

/** 24000 / 8000. */
const RATIO = OPENAI_SAMPLE_RATE / TELEPHONY_SAMPLE_RATE;

/**
 * Enough taps to put 6 kHz deep in the stopband, few enough to stay cheap.
 *
 * A Hamming window gives ~53 dB of stopband rejection and a transition band of
 * roughly 3.3/N — about 1.6 kHz at 24 kHz. With the cutoff at 3.4 kHz the
 * stopband is fully established by ~4.2 kHz, so content between 3.4 and 4 kHz
 * rolls off gradually. That is correct for telephony (the phone band ends at
 * 3.4 kHz) and is not a defect to be "fixed" with more taps and more latency.
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

/** Shared by both directions: the anti-alias/interpolation filter runs at 24 kHz. */
const COEFFICIENTS = designLowPass(TAPS, CUTOFF_HZ, OPENAI_SAMPLE_RATE);

function toInt16(value: number): number {
  const rounded = Math.round(value);
  if (rounded > 32767) return 32767;
  if (rounded < -32768) return -32768;
  return rounded;
}

/**
 * 24 kHz → 8 kHz, for TTS audio on its way to Twilio.
 *
 * **Low-pass first, then take every third sample.** Decimating without the
 * filter folds everything above 4 kHz back into the audible band; the result
 * sounds tinny and harsh, and is routinely misdiagnosed as a bad TTS voice.
 */
export class Downsampler {
  private readonly history = new Float64Array(TAPS - 1);

  /**
   * Which input sample the next output is taken from, modulo 3. Without this
   * the decimation phase resets every frame and the output is 3× too long at
   * the seams.
   */
  private phase = 0;

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

    const outputCount = Math.ceil((input.length - this.phase) / RATIO);
    const output = new Int16Array(Math.max(0, outputCount));

    let written = 0;
    for (let i = this.phase; i < input.length; i += RATIO) {
      let accumulator = 0;
      for (let k = 0; k < TAPS; k++) {
        accumulator += COEFFICIENTS[k] * window[i + TAPS - 1 - k];
      }
      output[written++] = toInt16(accumulator);
    }

    this.phase = (this.phase - input.length) % RATIO;
    if (this.phase < 0) this.phase += RATIO;

    this.history.set(window.subarray(window.length - this.history.length));

    return output;
  }
}

/**
 * 8 kHz → 24 kHz, for caller audio on its way to speech-to-text.
 *
 * Zero-stuff, low-pass, then **multiply by 3**. The gain step is not cosmetic:
 * inserting L-1 zeros and filtering divides the amplitude by L, so without it
 * every transcription request is fed audio about 9.5 dB down. Nothing throws
 * and transcription mostly still works — it just gets quietly worse on quiet
 * callers, which reads as a weak model rather than a resampler bug.
 */
export class Upsampler {
  private readonly history = new Float64Array(TAPS - 1);

  reset(): void {
    this.history.fill(0);
  }

  process(input: Int16Array): Int16Array {
    const stuffedLength = input.length * RATIO;
    const window = new Float64Array(this.history.length + stuffedLength);
    window.set(this.history, 0);
    for (let i = 0; i < input.length; i++) {
      window[this.history.length + i * RATIO] = input[i];
    }

    const output = new Int16Array(stuffedLength);
    for (let i = 0; i < stuffedLength; i++) {
      let accumulator = 0;
      for (let k = 0; k < TAPS; k++) {
        accumulator += COEFFICIENTS[k] * window[i + TAPS - 1 - k];
      }
      output[i] = toInt16(accumulator * RATIO);
    }

    this.history.set(window.subarray(window.length - this.history.length));

    return output;
  }
}
