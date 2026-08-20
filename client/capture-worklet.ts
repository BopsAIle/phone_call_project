/**
 * Regroups the audio thread's render quantum into Twilio's frame size.
 *
 * `process` is always handed 128 samples regardless of sample rate, and Twilio
 * wants 160 (20 ms at 8 kHz). The two do not divide, so samples have to be
 * accumulated across calls rather than converted one block at a time.
 *
 * Nothing else happens here. Worklets run in their own global scope with no
 * access to the main bundle, so this file cannot share the codec — keeping it
 * to pure buffering is what makes that acceptable.
 */

/** 20 ms at 8 kHz, matching MULAW_FRAME_BYTES on the server. */
const FRAME_SAMPLES = 160;

class CaptureProcessor extends AudioWorkletProcessor {
  private readonly frame = new Float32Array(FRAME_SAMPLES);
  private filled = 0;

  process(inputs: Float32Array[][]): boolean {
    const channel = inputs[0]?.[0];

    // No input connected yet, or the node is between streams. Returning false
    // would let the browser garbage-collect the processor for good.
    if (!channel) return true;

    for (let i = 0; i < channel.length; i++) {
      this.frame[this.filled++] = channel[i];

      if (this.filled === FRAME_SAMPLES) {
        // slice(), not the array itself: `frame` is reused on the next block
        // and postMessage would otherwise race the structured clone.
        this.port.postMessage(this.frame.slice());
        this.filled = 0;
      }
    }

    return true;
  }
}

registerProcessor('capture-processor', CaptureProcessor);
