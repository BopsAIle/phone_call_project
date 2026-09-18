"""Keep the message list in the shape the Chat Completions API accepts.

The API requires every assistant message carrying `tool_calls` to be followed immediately
by one `tool` message per call id. Anything else is a 400 — and because the history is
never rebuilt, one malformed round poisons every later turn of the call: the caller hears
the same apology over and over with no idea why.

`stream_sentences` now commits each round atomically so it cannot produce that shape. This
module is the second belt: a call that is *already* corrupt heals on its next turn.
"""

from __future__ import annotations

import json
from typing import Any

_INTERRUPTED = json.dumps({"ok": False, "error": "interrupted"})


def _tool_call_ids(message: dict[str, Any]) -> list[str]:
    calls = message.get("tool_calls")
    if not isinstance(calls, list):
        return []
    ids: list[str] = []
    for call in calls:
        if isinstance(call, dict):
            ids.append(str(call.get("id") or ""))
    return ids


def repair_tool_sequence(messages: list[Any]) -> list[Any]:
    """Return a well-formed copy: displaced tool replies pulled back to their call,
    missing ones synthesized, orphans dropped. A no-op on healthy input.
    """
    rest = list(messages)
    out: list[Any] = []
    while rest:
        message = rest.pop(0)
        if not isinstance(message, dict):
            out.append(message)
            continue
        if message.get("role") == "tool":
            # Reached the top of the loop means no assistant tool_calls claimed it:
            # an orphan the API would reject on its own.
            continue
        wanted = _tool_call_ids(message) if message.get("role") == "assistant" else []
        out.append(message)
        if not wanted:
            continue
        found: dict[str, Any] = {}
        keep: list[Any] = []
        for later in rest:
            call_id = (
                str(later.get("tool_call_id") or "")
                if isinstance(later, dict) and later.get("role") == "tool"
                else None
            )
            if call_id is not None and call_id in wanted and call_id not in found:
                found[call_id] = later
            else:
                keep.append(later)
        rest = keep
        for call_id in wanted:
            out.append(
                found.get(call_id)
                or {"role": "tool", "tool_call_id": call_id, "content": _INTERRUPTED}
            )
    return out


def is_well_formed(messages: list[Any]) -> bool:
    """True when `repair_tool_sequence` would change nothing. Handy in tests and asserts."""
    repaired = repair_tool_sequence(messages)
    if len(repaired) != len(messages):
        return False
    return all(a is b for a, b in zip(repaired, messages))
