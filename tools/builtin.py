"""Tools with no external dependency."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from tools.base import Tool, ToolContext, ToolResult

logger = logging.getLogger(__name__)


class GetCurrentTime(Tool):
    """Store-local clock, refreshed.

    The system prompt carries the local time as of `session.init`, which drifts
    over a long call. This re-reads it.
    """

    name = "get_current_time"
    description = (
        "Current date and time at the restaurant, in its own timezone. "
        "Use this before answering anything that depends on 'now', 'today', or 'tonight'."
    )
    parameters = {"type": "object", "properties": {}}
    slow = False
    safe_to_retry = True

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        tz_name = getattr(ctx.session, "timezone", "") or "UTC"
        try:
            now = datetime.now(ZoneInfo(tz_name))
        except Exception:
            # Same fallback as build_system_prompt: Windows without tzdata fails
            # even on ZoneInfo("UTC"), and the two must not disagree about "today".
            logger.warning("Timezone %r unavailable; using UTC. Is tzdata installed?", tz_name)
            tz_name = "UTC"
            now = datetime.now(UTC)
        return ToolResult(
            ok=True,
            data={
                "timezone": tz_name,
                "iso": now.isoformat(timespec="minutes"),
                "date": now.strftime("%Y-%m-%d"),
                "time": now.strftime("%H:%M"),
                "weekday": now.strftime("%A"),
            },
        )
