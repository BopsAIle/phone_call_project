from __future__ import annotations

from scripts.stt_eval import _words, keyword_hit, word_error_rate
from stt.realtime import build_transcription_session


# --- tách từ: không được xoá chữ có dấu ---


def test_words_keeps_accents() -> None:
    """Lỗi cũ: regex [^a-z0-9 ] xoá sạch dấu ở CẢ hai vế, nên nghe sai tên món
    lại được chấm là đúng — đúng những từ quan trọng nhất."""
    assert _words("Phở bò tái nạm") == ["phở", "bò", "tái", "nạm"]
    assert _words("Chicken Zinger Combo!") == ["chicken", "zinger", "combo"]
    assert _words("") == []


def test_words_does_not_collapse_different_dishes() -> None:
    assert _words("phở bò") != _words("phở gà")


# --- WER: phải phạt cả chữ thừa ---


def test_wer_counts_substitutions() -> None:
    assert word_error_rate("hai to pho ga", "hai to pho bo") == 0.25


def test_wer_counts_insertions() -> None:
    """Bản cũ ra 0.0: nghe ra dài gấp đôi mà chứa đủ chữ đúng vẫn coi là hoàn hảo."""
    assert word_error_rate("hai to pho bo them rau song", "hai to pho bo") == 0.75


def test_wer_counts_deletions() -> None:
    assert word_error_rate("hai to pho", "hai to pho bo") == 0.25


def test_wer_is_zero_when_identical() -> None:
    assert word_error_rate("hai to pho bo", "hai to pho bo") == 0.0


def test_wer_can_exceed_one_and_is_not_clamped() -> None:
    assert word_error_rate("a b c d e f", "a") > 1.0


def test_wer_handles_empty_sides() -> None:
    assert word_error_rate("", "") == 0.0
    assert word_error_rate("gì đó", "") == 1.0
    assert word_error_rate("", "hai to pho") == 1.0


def test_keyword_hit_is_none_when_the_clip_has_no_keyword() -> None:
    assert keyword_hit("bất kỳ", "không có tên món", ("Zinger",)) is None
    assert keyword_hit("tôi muốn Zinger", "cho tôi Zinger", ("Zinger",)) is True
    assert keyword_hit("tôi muốn singer", "cho tôi Zinger", ("Zinger",)) is False


# --- công cụ đo phải đo ĐÚNG cấu hình đang chạy ---


def test_eval_and_runtime_build_the_same_session() -> None:
    """Đây là bài test giữ cho công cụ đo không bao giờ lệch khỏi production nữa."""
    from stt.realtime import RealtimeTranscriptionClient

    client = RealtimeTranscriptionClient(object(), "gpt-4o-transcribe", languages=("en",))
    client._prompt = "Phone call to Bella Vista."
    runtime = client._session_payload()
    harness = build_transcription_session(
        "gpt-4o-transcribe", ("en",), prompt="Phone call to Bella Vista."
    )
    assert runtime == harness


def test_prompt_reaches_the_session_on_the_model_we_actually_run() -> None:
    """gpt-4o-transcribe không có `keywords`; prompt là kênh mớm tên món duy nhất."""
    session = build_transcription_session(
        "gpt-4o-transcribe", ("en",), prompt="Expect: Caesar Salad.", keywords=("Caesar Salad",)
    )
    transcription = session["audio"]["input"]["transcription"]
    assert transcription["prompt"] == "Expect: Caesar Salad."
    assert "keywords" not in transcription
    assert transcription["language"] == "en"


def test_noise_reduction_and_vad_are_part_of_what_gets_measured() -> None:
    session = build_transcription_session("gpt-4o-transcribe", ("en",))
    audio = session["audio"]["input"]
    assert audio["noise_reduction"] == {"type": "near_field"}
    assert audio["turn_detection"]["silence_duration_ms"] == 800
    assert audio["format"] == {"type": "audio/pcm", "rate": 24000}


def test_silence_override_changes_only_that_key() -> None:
    default = build_transcription_session("gpt-4o-transcribe", ("en",))
    tuned = build_transcription_session("gpt-4o-transcribe", ("en",), silence_duration_ms=600)
    a = default["audio"]["input"]["turn_detection"]
    b = tuned["audio"]["input"]["turn_detection"]
    assert b["silence_duration_ms"] == 600
    assert {k: v for k, v in a.items() if k != "silence_duration_ms"} == {
        k: v for k, v in b.items() if k != "silence_duration_ms"
    }


def test_rejected_fields_are_dropped_not_fatal() -> None:
    session = build_transcription_session(
        "gpt-transcribe", ("en",), keywords=("Zinger",), unsupported=frozenset({"keywords"})
    )
    transcription = session["audio"]["input"]["transcription"]
    assert "keywords" not in transcription
    assert transcription["languages"] == ["en"]
