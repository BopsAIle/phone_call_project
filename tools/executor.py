"""Run one tool call: parse, apply policy, dispatch, log.

Invariant I2 lives here — nothing reaches a tool's `run()` without clearing the
policy chain first.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Sequence

from llm.stream import ToolCallRequest
from tools.base import (
    Policy,
    ToolContext,
    ToolResult,
    reject_stale_generation,
    require_confirmed_details,
)
from tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

DEFAULT_POLICIES: tuple[Policy, ...] = (reject_stale_generation, require_confirmed_details)


class ToolExecutor:
    def __init__(self, registry: ToolRegistry, policies: Sequence[Policy] = DEFAULT_POLICIES) -> None:
        self._registry = registry
        self._policies = tuple(policies)

    async def execute(self, request: ToolCallRequest, ctx: ToolContext) -> ToolResult:
        tag = getattr(ctx.session, "tag", "")
        tool = self._registry.get(request.name)
        if tool is None:
            logger.error("Unknown tool %r %s", request.name, tag)
            return ToolResult.failure("unknown_tool", tool=request.name)

        try:
            args = json.loads(request.arguments or "{}")
        except json.JSONDecodeError:
            logger.error("Tool %s got unparseable arguments %s", request.name, tag)
            return ToolResult.failure("bad_arguments", tool=request.name)
        if not isinstance(args, dict):
            logger.error("Tool %s got non-object arguments %s", request.name, tag)
            return ToolResult.failure("bad_arguments", tool=request.name)

        # Argument *keys* only: names and phone numbers are PII on this path.
        logger.info(
            "tool.start name=%s call=%s arg_keys=%s %s",
            request.name,
            request.id,
            sorted(args),
            tag,
        )
        logger.debug("tool.args name=%s args=%r %s", request.name, args, tag)

        for policy in self._policies:
            denial = policy(tool, args, ctx)
            if denial is not None:
                logger.info(
                    "tool.denied name=%s call=%s reason=%s %s",
                    request.name,
                    request.id,
                    denial.data.get("error"),
                    tag,
                )
                return denial

        started = time.monotonic()
        try:
            result = await tool.run(args, ctx)
        except asyncio.CancelledError:
            # Barge-in or hangup. Propagate; the caller discards the turn.
            logger.info("tool.cancelled name=%s call=%s %s", request.name, request.id, tag)
            raise
        except Exception:
            logger.exception("tool.failed name=%s call=%s %s", request.name, request.id, tag)
            return ToolResult.failure("tool_error", tool=request.name)

        logger.info(
            "tool.done name=%s call=%s ok=%s duration_ms=%d %s",
            request.name,
            request.id,
            result.ok,
            int((time.monotonic() - started) * 1000),
            tag,
        )
        return result

    def message_for(self, request: ToolCallRequest, result: ToolResult) -> dict[str, Any]:
        """The `role: "tool"` history entry the model reads on the next round."""
        return {
            "role": "tool",
            "tool_call_id": request.id,
            "content": json.dumps(result.data, ensure_ascii=False),
        }


def assistant_tool_message(text: str, requests: Sequence[ToolCallRequest]) -> dict[str, Any]:
    """The assistant turn that requested the tools, in OpenAI's wire shape."""
    return {
        "role": "assistant",
        "content": text or None,
        "tool_calls": [
            {
                "id": request.id,
                "type": "function",
                "function": {"name": request.name, "arguments": request.arguments or "{}"},
            }
            for request in requests
        ],
    }
