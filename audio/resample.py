"""Streaming 16 kHz ↔ 24 kHz PCM16 resampling with anti-alias filtering."""

from __future__ import annotations

import numpy as np
import soxr

BRIDGE_RATE = 16_000
OPENAI_RATE = 24_000


def even_pcm16(data: bytes, leftover: bytearray) -> bytes:
    """Return a whole-sample PCM16 buffer; stash a trailing odd byte if any."""
    if leftover:
        data = bytes(leftover) + data
        leftover.clear()
    if len(data) % 2:
        leftover.append(data[-1])
        data = data[:-1]
    return data


class StreamResampler:
    """Stateful soxr stream so chunk boundaries do not click or split a sample."""

    def __init__(self, in_rate: int, out_rate: int) -> None:
        self.in_rate = in_rate
        self.out_rate = out_rate
        self._stream = soxr.ResampleStream(
            in_rate,
            out_rate,
            num_channels=1,
            dtype="int16",
            quality="HQ",
        )
        self._leftover = bytearray()

    def process(self, pcm16: bytes, last: bool = False) -> bytes:
        pcm16 = even_pcm16(pcm16, self._leftover)
        if not pcm16 and not last:
            return b""
        samples = np.frombuffer(pcm16, dtype=np.int16) if pcm16 else np.array([], dtype=np.int16)
        out = self._stream.resample_chunk(samples, last=last)
        if out.size == 0:
            return b""
        return np.asarray(out, dtype=np.int16).tobytes()

    def flush(self) -> bytes:
        return self.process(b"", last=True)
