"""Telnyx L16 (big-endian PCM16) ↔ bridge PCM16-LE 24 kHz.

Two traps live here, both silent if you get them wrong:

* L16 is network byte order (RFC 2586). The bridge, OpenAI, and `soxr` all
  speak little-endian. A missing byteswap is not an error — it is white noise.
* A byteswap and a resample both need whole 16-bit samples, so a chunk that
  ends mid-sample must carry its odd byte into the next chunk.
"""

from __future__ import annotations

import numpy as np

from audio.resample import OPENAI_RATE, StreamResampler, even_pcm16

# Telnyx accepts outbound frames from 20 ms up to 30 s. Stay at the low end:
# shorter frames mean barge-in `clear` drops less already-buffered speech.
DEFAULT_FRAME_MS = 20


def swap16(pcm: bytes) -> bytes:
    """Flip endianness of a whole-sample PCM16 buffer."""
    if not pcm:
        return b""
    return np.frombuffer(pcm, dtype="<i2").byteswap().tobytes()


class InboundTranscoder:
    """Caller audio: Telnyx L16 at `in_rate` → bridge PCM16-LE 24 kHz.

    `byteswap` exists because RFC 2586 says L16 is network byte order, but a
    given carrier may hand us little-endian anyway. Swapping when you should
    not is indistinguishable from not swapping when you should: both are white
    noise, and neither raises.
    """

    def __init__(self, in_rate: int, byteswap: bool = True) -> None:
        self.in_rate = in_rate
        self.byteswap = byteswap
        self._leftover = bytearray()
        self._resampler = StreamResampler(in_rate, OPENAI_RATE) if in_rate != OPENAI_RATE else None

    def process(self, payload: bytes) -> bytes:
        pcm_be = even_pcm16(payload, self._leftover)
        if not pcm_be:
            return b""
        pcm_le = swap16(pcm_be) if self.byteswap else pcm_be
        if self._resampler is None:
            return pcm_le
        return self._resampler.process(pcm_le)


class OutboundTranscoder:
    """Agent audio: bridge PCM16-LE 24 kHz → Telnyx L16 big-endian at `out_rate`.

    Emits fixed-size frames because the TTS chunk size (TTS_CHUNK_BYTES) is
    unrelated to what Telnyx wants on the wire.
    """

    def __init__(self, out_rate: int, frame_ms: int = DEFAULT_FRAME_MS, byteswap: bool = True) -> None:
        self.out_rate = out_rate
        self.byteswap = byteswap
        self.frame_ms = max(int(frame_ms), 20)
        self.frame_bytes = out_rate * self.frame_ms // 1000 * 2
        self._leftover = bytearray()
        self._buf = bytearray()
        self._resampler: StreamResampler | None = None
        if out_rate != OPENAI_RATE:
            self._resampler = StreamResampler(OPENAI_RATE, out_rate)

    def process(self, pcm24_le: bytes) -> list[bytes]:
        pcm = even_pcm16(pcm24_le, self._leftover)
        if pcm and self._resampler is not None:
            pcm = self._resampler.process(pcm)
        if pcm:
            self._buf.extend(pcm)
        frames: list[bytes] = []
        while len(self._buf) >= self.frame_bytes:
            frame = bytes(self._buf[: self.frame_bytes])
            frames.append(swap16(frame) if self.byteswap else frame)
            del self._buf[: self.frame_bytes]
        return frames

    def flush(self) -> bytes:
        """Emit everything still held back: the partial frame *and* the filter tail.

        soxr keeps roughly its filter length of audio inside the stream, so
        draining only `_buf` would silently clip the end of every turn. Closing
        the stream is what releases it, hence the fresh resampler afterwards.
        """
        if self._resampler is not None:
            tail = self._resampler.process(b"", last=True)
            if tail:
                self._buf.extend(tail)
            self._resampler = StreamResampler(OPENAI_RATE, self.out_rate)
        out = bytes(self._buf)
        self._buf.clear()
        if len(out) % 2:
            out = out[:-1]
        if not out:
            return b""
        return swap16(out) if self.byteswap else out

    def reset(self) -> None:
        """Barge-in: drop everything not yet handed to Telnyx and restart the filter.

        The resampler carries filter state across chunks, so a fresh turn must
        not inherit the tail of a turn the caller just interrupted.
        """
        self._buf.clear()
        self._leftover.clear()
        if self._resampler is not None:
            self._resampler = StreamResampler(OPENAI_RATE, self.out_rate)
