import { FrameBuffer } from './frame-buffer';
import { MULAW_FRAME_BYTES, MULAW_SILENCE } from './mulaw.codec';

/** Bytes that are easy to track through the buffer: 0, 1, 2, … mod 251. */
function counting(length: number, start = 0): Buffer {
  return Buffer.from(Array.from({ length }, (_, i) => (start + i) % 251));
}

describe('FrameBuffer', () => {
  it('emits nothing until a whole frame is available', () => {
    const buffer = new FrameBuffer();

    expect(buffer.push(counting(159))).toEqual([]);
    expect(buffer.pending).toBe(159);
  });

  it('emits a frame the moment the last byte arrives', () => {
    const buffer = new FrameBuffer();
    buffer.push(counting(159));

    const frames = buffer.push(counting(1, 159));

    expect(frames).toHaveLength(1);
    expect(frames[0]).toEqual(counting(MULAW_FRAME_BYTES));
    expect(buffer.pending).toBe(0);
  });

  it('emits several frames from one large chunk', () => {
    const frames = new FrameBuffer().push(counting(MULAW_FRAME_BYTES * 3));

    expect(frames).toHaveLength(3);
    expect(frames[2]).toEqual(
      counting(MULAW_FRAME_BYTES, MULAW_FRAME_BYTES * 2),
    );
  });

  /**
   * The property that matters: chunk boundaries must not be visible in the
   * output. Feeding the same bytes in awkward pieces has to produce byte-identical
   * frames, or Phase 3 gets a click at every TTS chunk boundary.
   */
  it('produces the same frames regardless of how the input is chunked', () => {
    const source = counting(MULAW_FRAME_BYTES * 5);

    const atOnce = new FrameBuffer().push(source);

    const piecemeal = new FrameBuffer();
    const frames: Buffer[] = [];
    for (let offset = 0; offset < source.length; offset += 37) {
      frames.push(...piecemeal.push(source.subarray(offset, offset + 37)));
    }

    expect(frames).toEqual(atOnce);
  });

  it('carries the remainder across chunks', () => {
    const buffer = new FrameBuffer();

    buffer.push(counting(100));
    const frames = buffer.push(counting(100, 100));

    expect(frames).toHaveLength(1);
    expect(frames[0]).toEqual(counting(MULAW_FRAME_BYTES));
    expect(buffer.pending).toBe(40);
  });

  describe('flush', () => {
    it('pads the tail with mu-law silence', () => {
      const buffer = new FrameBuffer();
      buffer.push(counting(10));

      const frame = buffer.flush();

      expect(frame).toHaveLength(MULAW_FRAME_BYTES);
      expect(frame?.subarray(0, 10)).toEqual(counting(10));
      expect(frame?.subarray(10)).toEqual(
        Buffer.alloc(MULAW_FRAME_BYTES - 10, MULAW_SILENCE),
      );
    });

    it('returns null when nothing is pending', () => {
      expect(new FrameBuffer().flush()).toBeNull();
    });

    it('empties the buffer', () => {
      const buffer = new FrameBuffer();
      buffer.push(counting(10));
      buffer.flush();

      expect(buffer.pending).toBe(0);
      expect(buffer.flush()).toBeNull();
    });
  });
});
