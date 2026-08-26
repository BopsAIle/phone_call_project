from __future__ import annotations

import asyncio
from typing import Callable, Optional


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


class ScriptedLlm:
    def __init__(self, sentences: list[str], error: Exception | None = None) -> None:
        self.sentences = sentences
        self.error = error
        self.calls: list[list[dict[str, str]]] = []

    async def stream_sentences(self, messages: list[dict[str, str]], should_abort: Callable[[], bool]):
        self.calls.append(messages)
        if self.error:
            raise self.error
        for sentence in self.sentences:
            if should_abort():
                return
            yield sentence
