from __future__ import annotations

import json
import wave
from pathlib import Path

from audio.recorder import BYTES_PER_SECOND, CallRecorder, _safe_call_id


def _tone(seconds: float) -> bytes:
    return b"\x01\x02" * int(BYTES_PER_SECOND * seconds / 2)


def test_recording_is_off_unless_a_directory_is_set() -> None:
    assert CallRecorder.maybe("", "call-1") is None
    assert CallRecorder.maybe("   ", "call-1") is None


async def test_writes_a_24k_mono_wav(tmp_path: Path) -> None:
    recorder = CallRecorder.maybe(str(tmp_path), "call-1", max_seconds=60)
    assert recorder is not None
    recorder.feed(_tone(0.5))
    await recorder.flush()
    recorder.feed(_tone(0.5))
    await recorder.close()

    files = list(tmp_path.glob("*.wav"))
    assert len(files) == 1
    with wave.open(str(files[0]), "rb") as reader:
        assert reader.getnchannels() == 1
        assert reader.getsampwidth() == 2
        assert reader.getframerate() == 24000
        assert reader.getnframes() == int(BYTES_PER_SECOND * 1.0 / 2)
    # File PCM tạm phải được dọn sau khi đóng gói
    assert list(tmp_path.glob("*.pcm")) == []


async def test_marks_record_byte_offsets(tmp_path: Path) -> None:
    recorder = CallRecorder.maybe(str(tmp_path), "call-1", max_seconds=60)
    assert recorder is not None
    recorder.mark("speech_started")
    recorder.feed(_tone(1.0))
    recorder.mark("transcript", "hai tô phở")
    recorder.feed(_tone(0.5))
    recorder.mark("agent", "Dạ vâng ạ.")
    await recorder.close()

    marks_file = list(tmp_path.glob("*.jsonl"))[0]
    marks = [json.loads(line) for line in marks_file.read_text(encoding="utf-8").splitlines()]
    assert [m["event"] for m in marks] == ["speech_started", "transcript", "agent"]
    assert marks[0]["offset"] == 0
    assert marks[1]["offset"] == BYTES_PER_SECOND
    assert marks[1]["text"] == "hai tô phở"
    assert marks[2]["offset"] == int(BYTES_PER_SECOND * 1.5)


async def test_size_cap_stops_writing(tmp_path: Path) -> None:
    recorder = CallRecorder.maybe(str(tmp_path), "call-1", max_seconds=1)
    assert recorder is not None
    recorder.feed(_tone(5.0))
    await recorder.close()
    with wave.open(str(list(tmp_path.glob("*.wav"))[0]), "rb") as reader:
        assert reader.getnframes() == BYTES_PER_SECOND // 2  # đúng 1 giây


def test_call_id_from_the_carrier_cannot_escape_the_directory() -> None:
    assert _safe_call_id("../../etc/passwd") == "etc-passwd"
    assert _safe_call_id("") == "unknown"
    assert _safe_call_id("/") == "unknown"
    assert _safe_call_id("clx8k2p9v0000abcd") == "clx8k2p9v0000abcd"
    assert "/" not in _safe_call_id("a/b/c")


async def test_bad_directory_never_breaks_the_call(tmp_path: Path) -> None:
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("tôi là file, không phải thư mục")
    assert CallRecorder.maybe(str(blocker), "call-1") is None


async def test_pipeline_records_what_stt_hears(tmp_path: Path) -> None:
    import asyncio
    import json as _json

    from tests.fakes import FakeBridgeSocket, FakeSTT, ScriptedLlm, ScriptedTts
    from tests.test_booking_session import INIT, _init, _start_pipeline, _stop

    ws = FakeBridgeSocket()
    stt = FakeSTT()
    pipeline, task = await _start_pipeline(
        ws, stt, ScriptedLlm([]), ScriptedTts(), call_record_dir=str(tmp_path)
    )
    await _init(ws, pipeline, INIT)
    await ws.push_bytes(_tone(0.2))
    await asyncio.sleep(0.05)
    await pipeline.on_transcript_completed("hai tô phở")
    await asyncio.sleep(0.05)
    await _stop(ws, task)

    wavs = list(tmp_path.glob("*.wav"))
    assert len(wavs) == 1
    with wave.open(str(wavs[0]), "rb") as reader:
        assert reader.getnframes() > 0
    marks = [
        _json.loads(line)
        for line in list(tmp_path.glob("*.jsonl"))[0].read_text(encoding="utf-8").splitlines()
    ]
    assert any(m["event"] == "transcript" and m.get("text") == "hai tô phở" for m in marks)


def test_greeting_announces_recording_only_when_enabled() -> None:
    from bridge.session import RECORDING_NOTICE_EN, ensure_intent_greeting

    plain = ensure_intent_greeting("Thanks for calling Bella Vista.", "en")
    assert RECORDING_NOTICE_EN not in plain
    assert "press 1" in plain.lower()

    noticed = ensure_intent_greeting("Thanks for calling Bella Vista.", "en", recording=True)
    assert RECORDING_NOTICE_EN in noticed
    # Thông báo phải đứng TRƯỚC menu bấm phím: khách bấm phím giữa menu vẫn đã nghe nó
    assert noticed.index(RECORDING_NOTICE_EN) < noticed.lower().index("press 1")


def test_recording_notice_is_not_repeated() -> None:
    from bridge.session import RECORDING_NOTICE_EN, ensure_intent_greeting

    already = f"Hello. {RECORDING_NOTICE_EN}"
    out = ensure_intent_greeting(already, "en", recording=True)
    assert out.count(RECORDING_NOTICE_EN) == 1
