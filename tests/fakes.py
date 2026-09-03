from __future__ import annotations

import asyncio
from typing import Any, Callable, Optional

from llm.stream import SpeakSentence
from tools.base import Tool, ToolContext, ToolResult


class FakeBridgeSocket:
    def __init__(self) -> None:
        self.sent: list[tuple[str, bytes | str]] = []
        self.incoming: asyncio.Queue[dict] = asyncio.Queue()

    async def send_bytes(self, data: bytes) -> None:
        self.sent.append(("bytes", data))

    async def send_text(self, data: str) -> None:
        self.sent.append(("text", data))

    async def receive(self) -> dict:
        return await self.incoming.get()

    async def push_text(self, text: str) -> None:
        await self.incoming.put({"type": "websocket.receive", "text": text})

    async def push_bytes(self, data: bytes) -> None:
        await self.incoming.put({"type": "websocket.receive", "bytes": data})

    async def disconnect(self) -> None:
        await self.incoming.put({"type": "websocket.disconnect", "code": 1000})


class FakeSTT:
    def __init__(self) -> None:
        self.is_ready = False
        self.appended: list[bytes] = []
        self.handler = None
        self.locale: Optional[str] = None
        self.closed = False

    async def start(self, handler, locale: str | None = None) -> None:
        self.handler = handler
        self.locale = locale
        self.is_ready = True

    async def update_language(self, locale: str) -> None:
        self.locale = locale

    async def append_pcm24(self, pcm: bytes) -> None:
        self.appended.append(pcm)

    async def close(self) -> None:
        self.closed = True
        self.is_ready = False


class ScriptedTts:
    def __init__(self, chunks_for: dict[str, list[bytes]] | None = None, default: bytes = b"\x00\x01" * 80) -> None:
        self.chunks_for = chunks_for or {}
        self.default = default
        self.spoken: list[str] = []

    async def stream_pcm16(self, text: str, locale: str, should_abort: Callable[[], bool]):
        self.spoken.append(text)
        for chunk in self.chunks_for.get(text, [self.default]):
            if should_abort():
                return
            yield chunk


class SlowTts:
    """Yields one chunk then blocks so barge-in can fire mid-playback."""

    def __init__(self, hold: float = 1.0) -> None:
        self.hold = hold
        self.spoken: list[str] = []

    async def stream_pcm16(self, text: str, locale: str, should_abort: Callable[[], bool]):
        self.spoken.append(text)
        yield b"\x00\x01" * 160
        await asyncio.sleep(self.hold)
        if should_abort():
            return
        yield b"\x02\x03" * 160


def _snapshot(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Copy the live history so later rounds do not rewrite an earlier record."""
    return [dict(message) for message in messages]


class ScriptedLlm:
    def __init__(self, sentences: list[str], error: Exception | None = None) -> None:
        self.sentences = sentences
        self.error = error
        self.calls: list[list[dict[str, Any]]] = []
        self.tool_schemas: list[Optional[list[dict[str, Any]]]] = []

    async def stream_sentences(
        self,
        messages: list[dict[str, Any]],
        should_abort: Callable[[], bool],
        tools: Optional[list[dict[str, Any]]] = None,
    ):
        self.calls.append(_snapshot(messages))
        self.tool_schemas.append(tools)
        if self.error:
            raise self.error
        for sentence in self.sentences:
            if should_abort():
                return
            yield SpeakSentence(sentence)


class ScriptedToolLlm:
    """One scripted list of TurnEvents per LLM round.

    `rounds[0]` is the first stream, `rounds[1]` the stream after tool results
    come back, and so on. An exhausted script yields nothing, which ends the turn.
    """

    def __init__(self, rounds: list[list[Any]]) -> None:
        self.rounds = rounds
        self.calls: list[list[dict[str, Any]]] = []
        self.tool_schemas: list[Optional[list[dict[str, Any]]]] = []

    async def stream_sentences(
        self,
        messages: list[dict[str, Any]],
        should_abort: Callable[[], bool],
        tools: Optional[list[dict[str, Any]]] = None,
    ):
        index = len(self.calls)
        self.calls.append(_snapshot(messages))
        self.tool_schemas.append(tools)
        for event in self.rounds[index] if index < len(self.rounds) else []:
            if should_abort():
                return
            yield event


class FakeTool(Tool):
    def __init__(
        self,
        name: str = "fake_tool",
        *,
        slow: bool = False,
        delay: float = 0.0,
        data: Optional[dict[str, Any]] = None,
        error: Exception | None = None,
    ) -> None:
        self.name = name
        self.description = f"Fake tool {name}."
        self.parameters = {"type": "object", "properties": {}}
        self.slow = slow
        self.delay = delay
        self.data = data if data is not None else {"value": "ok"}
        self.error = error
        self.calls: list[dict[str, Any]] = []

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        self.calls.append(args)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        return ToolResult(ok=True, data=self.data)
