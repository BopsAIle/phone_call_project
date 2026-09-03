"""What an agent is: a prompt fragment, a tool set, and who it can hand off to.

An agent is not a separate LLM loop. It is a selection made inside the one
streaming turn in `bridge/session.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tools.base import Tool, ToolContext, ToolResult

HANDOFF_PREFIX = "handoff_to_"


@dataclass(frozen=True)
class Agent:
    name: str
    prompt_fragment: str
    #: Why another agent would hand control here. The model reads this.
    handoff_description: str
    tool_names: tuple[str, ...] = ()
    handoffs: tuple[str, ...] = ()

    def tool_selection(self) -> list[str]:
        return [*self.tool_names, *(HANDOFF_PREFIX + target for target in self.handoffs)]


class HandoffTool(Tool):
    """Switches the active agent. Local only — never touches the network.

    Resolving a handoff as a tool call keeps routing inside the response the
    model is already streaming, so it costs no extra round-trip.
    """

    slow = False
    safe_to_retry = True

    def __init__(self, target: Agent) -> None:
        self.target = target
        self.name = HANDOFF_PREFIX + target.name
        self.description = target.handoff_description
        self.parameters = {"type": "object", "properties": {}}

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        ctx.session.active_agent = self.target.name
        return ToolResult(ok=True, data={"active_agent": self.target.name})
