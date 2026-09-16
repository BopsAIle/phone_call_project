from __future__ import annotations

from enum import Enum

from stt.realtime import _event_type, transcript_from_event


def test_transcript_from_top_level_field() -> None:
    assert transcript_from_event({"transcript": "KFC"}) == "KFC"


def test_transcript_from_item_content() -> None:
    event = {
        "type": "conversation.item.done",
        "item": {
            "id": "item-1",
            "role": "user",
            "content": [{"type": "input_audio", "transcript": "cho mình KFC"}],
        },
    }
    assert transcript_from_event(event) == "cho mình KFC"


def test_transcript_ignores_assistant_item() -> None:
    event = {
        "item": {
            "role": "assistant",
            "content": [{"transcript": "Hello"}],
        }
    }
    assert transcript_from_event(event) == ""


class _TypeEnum(str, Enum):
    SPEECH = "input_audio_buffer.speech_started"


def test_event_type_from_str_enum() -> None:
    event = type("E", (), {"type": _TypeEnum.SPEECH})()
    assert _event_type(event) == "input_audio_buffer.speech_started"
    assert _event_type({"type": "session.updated"}) == "session.updated"
