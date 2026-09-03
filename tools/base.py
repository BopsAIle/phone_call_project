"""Tool contract and the policy hook that guards side effects.

The LLM decides what it *wants* to do; policies decide whether it is *allowed*.
Every write passes the chain in `tools/executor.py` before it reaches the network.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, ClassVar, Optional


@dataclass
class ToolContext:
    """Everything a tool may read about the call it is running inside.

    `should_abort` is the same generation check the LLM and TTS streams use, so a
    barge-in cancels an in-flight tool the moment it is polled.
    """

    session: Any
    generation_id: int
    should_abort: Callable[[], bool]
    #: Hand a dispatched side effect here so a hangup lets it finish rather than
    #: cancelling it. The caller already authorised the write.
    register_write: Optional[Callable[[Any], None]] = None


@dataclass
class ToolResult:
    """What goes back to the model as the `role: "tool"` message."""

    ok: bool
    data: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def failure(cls, reason: str, **extra: Any) -> "ToolResult":
        return cls(ok=False, data={"error": reason, **extra})


class Tool:
    """Base class for anything the model can call.

    `slow` marks a tool that touches the network: the caller speaks a bridging
    phrase first, because silence on a phone line reads as a dropped call.
    `safe_to_retry` is False for anything that commits a side effect.
    """

    name: ClassVar[str] = ""
    description: ClassVar[str] = ""
    parameters: ClassVar[dict[str, Any]] = {"type": "object", "properties": {}}
    slow: ClassVar[bool] = False
    safe_to_retry: ClassVar[bool] = True
    #: Gate this tool on complete, caller-confirmed, not-yet-submitted details.
    requires_confirmation: ClassVar[bool] = False
    #: Attribute on CallSession holding this tool's draft, e.g. "booking".
    draft_attr: ClassVar[str] = ""

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        raise NotImplementedError


# Return None to allow the call, or a ToolResult to deny it and tell the model why.
Policy = Callable[[Tool, dict[str, Any], ToolContext], Optional[ToolResult]]


def reject_stale_generation(tool: Tool, args: dict[str, Any], ctx: ToolContext) -> Optional[ToolResult]:
    """Invariant I1: a superseded generation may not reach a side effect."""
    if ctx.should_abort():
        return ToolResult.failure("aborted", tool=tool.name)
    return None


def require_confirmed_details(tool: Tool, args: dict[str, Any], ctx: ToolContext) -> Optional[ToolResult]:
    """Nothing is filed without complete details the caller has just confirmed.

    Confirmation is held as a fingerprint of the slot values, so a detail changed
    after the read-back no longer matches and the write is refused. There is no
    boolean to forget to reset.
    """
    if not tool.requires_confirmation:
        return None
    draft = getattr(ctx.session, tool.draft_attr, None)
    if draft is None:
        return ToolResult.failure("no_draft", tool=tool.name)

    missing = draft.missing()
    if missing:
        return ToolResult.failure(
            "incomplete",
            still_missing=missing,
            guidance="Ask the caller for these, then read everything back.",
        )

    current = draft.fingerprint()
    if current in getattr(ctx.session, "consumed_fingerprints", ()):
        return ToolResult.failure(
            "already_filed",
            guidance="This exact request has already been sent. Do not send it twice.",
        )
    if getattr(ctx.session, "details_fingerprint", None) != current:
        return ToolResult.failure(
            "not_confirmed",
            guidance="Read the full details back and have the caller confirm them first.",
        )
    return None
