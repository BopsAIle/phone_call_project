import { int16ToLe, leToInt16 } from './pcm';

describe('int16ToLe', () => {
  it('writes two bytes per sample, low byte first', () => {
    expect(int16ToLe(Int16Array.from([0x0102]))).toEqual(
      Buffer.from([0x02, 0x01]),
    );
  });

  it('writes negative samples in two’s complement', () => {
    expect(int16ToLe(Int16Array.from([-2]))).toEqual(Buffer.from([0xfe, 0xff]));
  });

  it('returns an empty buffer for empty input', () => {
    expect(int16ToLe(new Int16Array(0))).toEqual(Buffer.alloc(0));
  });

  /**
   * The aliasing guard. A `Buffer.from(pcm.buffer, …)` cast would return a view
   * over the caller's memory, so reusing the source array would rewrite bytes
   * already queued for sending — silent audio corruption under batching, which
   * is exactly what the STT session does.
   */
  it('copies rather than aliasing the source array', () => {
    const source = Int16Array.from([1000, 2000]);
    const bytes = int16ToLe(source);

    source[0] = -1;

    expect(bytes.readInt16LE(0)).toBe(1000);
  });
});

describe('leToInt16', () => {
  it('reads two bytes per sample, low byte first', () => {
    expect(leToInt16(Buffer.from([0x02, 0x01]))).toEqual(
      Int16Array.from([0x0102]),
    );
  });

  it('reads negative samples in two’s complement', () => {
    expect(leToInt16(Buffer.from([0xfe, 0xff]))).toEqual(Int16Array.from([-2]));
  });

  /**
   * Streamed PCM is chunked by the transport, not by sample boundaries, so a
   * chunk ending mid-sample is routine. Dropping the odd byte is the caller's
   * cue to carry it forward; throwing would turn a normal chunk boundary into
   * a dead phone call.
   */
  it('drops a trailing odd byte instead of throwing', () => {
    expect(leToInt16(Buffer.from([0x02, 0x01, 0x7f]))).toEqual(
      Int16Array.from([0x0102]),
    );
  });

  it('returns an empty array for empty input', () => {
    expect(leToInt16(Buffer.alloc(0))).toEqual(new Int16Array(0));
  });
});

describe('round trip', () => {
  /**
   * The extremes are where an implementation that reaches for `writeUInt16LE`
   * or a naive `& 0xffff` falls over, and -32768 in particular is the value
   * that has no positive counterpart.
   */
  it('preserves the full Int16 range', () => {
    const source = Int16Array.from([
      -32768, -32767, -1, 0, 1, 32766, 32767, 255, 256, -256,
    ]);

    expect(leToInt16(int16ToLe(source))).toEqual(source);
  });

  it('preserves a frame of 24 kHz audio', () => {
    const source = new Int16Array(480);
    for (let i = 0; i < source.length; i++) {
      source[i] = Math.round(20000 * Math.sin((2 * Math.PI * 440 * i) / 24000));
    }

    const bytes = int16ToLe(source);

    expect(bytes).toHaveLength(960);
    expect(leToInt16(bytes)).toEqual(source);
  });
});
