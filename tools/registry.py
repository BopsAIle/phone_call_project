"""Name → Tool lookup, and the `tools=[...]` payload for a chat request."""

from __future__ import annotations

from typing import Any, Iterable, Optional, Sequence

from tools.base import Tool


class ToolRegistry:
    def __init__(self, tools: Iterable[Tool] = ()) -> None:
        self._tools: dict[str, Tool] = {}
        for tool in tools:
            self.add(tool)

    def add(self, tool: Tool) -> None:
        if not tool.name:
            raise ValueError(f"{type(tool).__name__} has no name")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def schemas(self, names: Optional[Sequence[str]] = None) -> list[dict[str, Any]]:
        """Schemas for `names`, or for every registered tool when names is None.

        Unknown names are skipped rather than raising: an agent may list a tool
        that is not wired up yet, and a missing tool should narrow the model's
        options, not drop the call.
        """
        if names is None:
            selected = [self._tools[key] for key in sorted(self._tools)]
        else:
            selected = [self._tools[name] for name in names if name in self._tools]
        return [tool.schema() for tool in selected]
