/**
 * Int16 PCM ↔ little-endian bytes.
 *
 * Byte layout, not signal processing — the DSP lives in mulaw.codec.ts and
 * resampler.ts. This is the last step before 24 kHz audio goes onto the wire as
 * base64, and the first step after it comes back.
 *
 * Both directions loop over `readInt16LE`/`writeInt16LE` rather than casting
 * through the underlying ArrayBuffer. The cast is tempting because it is free:
 *
 *     Buffer.from(pcm.buffer, pcm.byteOffset, pcm.byteLength)   // do not
 *
 * It is wrong twice. It reinterprets host memory, so on a big-endian machine it
 * silently emits byte-swapped audio — which is not a crash but a loud rasp, and
 * is diagnosed as a bad microphone rather than a bad cast. And it *aliases* the
 * source: the returned Buffer is a view, not a copy, so anything that reuses the
 * Int16Array mutates bytes we have already queued for sending. The batching in
 * the STT session queues exactly this kind of buffer, which turns that from a
 * theoretical concern into a landmine.
 *
 * The loop costs a few microseconds per 20 ms frame. Correctness that does not
 * depend on the machine is worth more than that.
 */

/** Samples to bytes, two per sample, little-endian. */
export function int16ToLe(pcm: Int16Array): Buffer {
  const bytes = Buffer.allocUnsafe(pcm.length * 2);

  for (let i = 0; i < pcm.length; i++) {
    bytes.writeInt16LE(pcm[i], i * 2);
  }

  return bytes;
}

/**
 * Bytes to samples, the inverse.
 *
 * A trailing odd byte is dropped rather than throwing. Streamed PCM arrives in
 * chunks sized by the transport, so a chunk splitting a sample in half is normal
 * and not an error — the caller carries the remainder to the next chunk, exactly
 * as FrameBuffer does for mu-law.
 */
export function leToInt16(bytes: Buffer): Int16Array {
  const pcm = new Int16Array(Math.floor(bytes.length / 2));

  for (let i = 0; i < pcm.length; i++) {
    pcm[i] = bytes.readInt16LE(i * 2);
  }

  return pcm;
}
