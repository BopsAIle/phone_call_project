from __future__ import annotations

import json

from llm.history import is_well_formed, repair_tool_sequence

_INTERRUPTED = json.dumps({"ok": False, "error": "interrupted"})


def _assistant_calls(*ids: str) -> dict:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {"id": i, "type": "function", "function": {"name": "create_order", "arguments": "{}"}}
            for i in ids
        ],
    }


def _tool(call_id: str, content: str = '{"ok": true}') -> dict:
    return {"role": "tool", "tool_call_id": call_id, "content": content}


def test_healthy_history_is_untouched() -> None:
    history = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hai tô phở"},
        _assistant_calls("a"),
        _tool("a"),
        {"role": "assistant", "content": "Dạ xong rồi ạ."},
    ]
    assert repair_tool_sequence(history) == history
    assert is_well_formed(history) is True


def test_speech_wedged_between_call_and_result_is_pulled_apart() -> None:
    """Đúng hình dạng mà barge-in lúc tạo đơn sinh ra trước khi sửa."""
    history = [
        {"role": "user", "content": "chốt đơn"},
        _assistant_calls("a"),
        {"role": "assistant", "content": "Dạ em đang lên đơn."},
        _tool("a"),
    ]
    repaired = repair_tool_sequence(history)
    assert [m["role"] for m in repaired] == ["user", "assistant", "tool", "assistant"]
    assert repaired[1]["tool_calls"][0]["id"] == "a"
    assert repaired[2]["tool_call_id"] == "a"
    assert repaired[3]["content"] == "Dạ em đang lên đơn."
    assert is_well_formed(history) is False
    assert is_well_formed(repaired) is True


def test_missing_tool_reply_is_synthesized() -> None:
    history = [_assistant_calls("a", "b"), _tool("a")]
    repaired = repair_tool_sequence(history)
    assert [m["role"] for m in repaired] == ["assistant", "tool", "tool"]
    assert repaired[2] == {"role": "tool", "tool_call_id": "b", "content": _INTERRUPTED}


def test_tool_replies_are_reordered_to_match_the_call_order() -> None:
    history = [_assistant_calls("a", "b"), _tool("b", '{"second": true}'), _tool("a", '{"first": true}')]
    repaired = repair_tool_sequence(history)
    assert [m.get("tool_call_id") for m in repaired[1:]] == ["a", "b"]


def test_orphan_tool_message_is_dropped() -> None:
    history = [
        {"role": "user", "content": "xin chào"},
        _tool("ghost"),
        {"role": "assistant", "content": "Dạ vâng."},
    ]
    repaired = repair_tool_sequence(history)
    assert [m["role"] for m in repaired] == ["user", "assistant"]


def test_two_rounds_stay_separate() -> None:
    history = [
        _assistant_calls("a"),
        _tool("a"),
        {"role": "assistant", "content": "Tìm thấy rồi ạ."},
        _assistant_calls("b"),
        _tool("b"),
    ]
    assert repair_tool_sequence(history) == history


def test_empty_and_non_dict_entries_survive() -> None:
    assert repair_tool_sequence([]) == []
    weird = ["not a dict", {"role": "user", "content": "hi"}]
    assert repair_tool_sequence(weird) == weird


def test_repair_is_idempotent() -> None:
    history = [_assistant_calls("a"), {"role": "assistant", "content": "x"}, _tool("a")]
    once = repair_tool_sequence(history)
    assert repair_tool_sequence(once) == once
