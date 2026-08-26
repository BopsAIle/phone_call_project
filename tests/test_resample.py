from __future__ import annotations

import numpy as np

from audio.resample import BRIDGE_RATE, OPENAI_RATE, StreamResampler, even_pcm16


def _sine(rate: int, seconds: float, freq: float = 440.0) -> bytes:
    n = int(rate * seconds)
    t = np.arange(n, dtype=np.float64) / rate
    samples = (0.4 * np.sin(2 * np.pi * freq * t) * 32767).astype(np.int16)
    return samples.tobytes()


def test_even_pcm16_holds_odd_byte() -> None:
    leftover = bytearray()
    assert even_pcm16(b"\x01", leftover) == b""
    assert leftover == b"\x01"
    out = even_pcm16(b"\x00\x02\x00", leftover)
    assert out == b"\x01\x00\x02\x00"
    assert leftover == b""


def test_upsample_100ms_frame_is_whole_samples() -> None:
    frame = _sine(BRIDGE_RATE, 0.1)
    assert len(frame) == 3200
    rs = StreamResampler(BRIDGE_RATE, OPENAI_RATE)
    out = rs.process(frame) + rs.flush()
    assert len(out) % 2 == 0
    samples = len(out) // 2
    assert 2390 <= samples <= 2410


def test_roundtrip_preserves_low_frequency() -> None:
    original = np.frombuffer(_sine(BRIDGE_RATE, 0.2, freq=300.0), dtype=np.int16).astype(np.float64)
    up = StreamResampler(BRIDGE_RATE, OPENAI_RATE)
    down = StreamResampler(OPENAI_RATE, BRIDGE_RATE)
    high = up.process(_sine(BRIDGE_RATE, 0.2, freq=300.0)) + up.flush()
    back = down.process(high) + down.flush()
    restored = np.frombuffer(back, dtype=np.int16).astype(np.float64)
    n = min(len(original), len(restored))
    orig = original[:n] - original[:n].mean()
    rest = restored[:n] - restored[:n].mean()
    corr = float(np.dot(orig, rest) / (np.linalg.norm(orig) * np.linalg.norm(rest) + 1e-9))
    assert corr > 0.95


def test_streaming_chunks_match_one_shot_length() -> None:
    pcm = _sine(BRIDGE_RATE, 0.15)
    one = StreamResampler(BRIDGE_RATE, OPENAI_RATE)
    streamed = StreamResampler(BRIDGE_RATE, OPENAI_RATE)
    all_at_once = one.process(pcm) + one.flush()
    parts = []
    for i in range(0, len(pcm), 640):
        parts.append(streamed.process(pcm[i : i + 640]))
    parts.append(streamed.flush())
    assert abs(len(b"".join(parts)) - len(all_at_once)) <= 4
