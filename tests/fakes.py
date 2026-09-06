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
        self.calls: list[list[dict]] = []

    async def stream_sentences(self, messages: list[dict], should_abort: Callable[[], bool], **_kwargs):
        self.calls.append(messages)
        if self.error:
            raise self.error
        for sentence in self.sentences:
            if should_abort():
                return
            yield sentence


class ToolThenSpeakLlm:
    """Execute one tool via the real executor, then speak. Never yields tool JSON."""

    def __init__(self, tool_name: str, tool_args: dict, sentences: list[str]) -> None:
        self.tool_name = tool_name
        self.tool_args = tool_args
        self.sentences = sentences
        self.results: list[str] = []
        self.calls: list[list[dict]] = []

    async def stream_sentences(self, messages: list[dict], should_abort: Callable[[], bool], **kwargs):
        self.calls.append(messages)
        execute_tool = kwargs.get("execute_tool")
        if execute_tool is not None:
            import json

            result = execute_tool(self.tool_name, json.dumps(self.tool_args))
            if hasattr(result, "__await__"):
                result = await result
            self.results.append(result)
        for sentence in self.sentences:
            if should_abort():
                return
            yield sentence


class FakeRestaurantClient:
    def __init__(self, result=None, booking_result=None, booking_error: str | None = None) -> None:
        self.result = result
        self.booking_result = booking_result if booking_result is not None else {"id": "bk-1"}
        self.booking_error = booking_error
        self.lookups: list[str] = []
        self.created: list[dict] = []

    async def find_by_hotline(self, hotline: str):
        from booking.models import HotlineResult, Restaurant

        self.lookups.append(hotline)
        if isinstance(self.result, HotlineResult):
            return self.result
        if isinstance(self.result, Restaurant):
            return HotlineResult(restaurant=self.result)
        return HotlineResult(missing=True)

    async def create_booking(self, body: dict):
        from booking.models import BookingApiResult

        self.created.append(body)
        if self.booking_error:
            return BookingApiResult(ok=False, error=self.booking_error)
        return BookingApiResult(ok=True, data=self.booking_result)


class FakeOrderClient:
    def __init__(
        self,
        menu=None,
        menu_error: str | None = None,
        order_result=None,
        order_error: str | None = None,
    ) -> None:
        self.menu = list(menu or [])
        self.menu_error = menu_error
        self.order_result = order_result if order_result is not None else {"id": "ord-1"}
        self.order_error = order_error
        self.menu_lookups: list[tuple[str, str]] = []
        self.created: list[dict] = []

    async def get_menu(self, restaurant_id: str, branch_id: str = ""):
        from order.models import MenuResult

        self.menu_lookups.append((restaurant_id, branch_id))
        if self.menu_error:
            return MenuResult(ok=False, error=self.menu_error)
        return MenuResult(ok=True, items=list(self.menu))

    async def create_order(self, body: dict):
        from order.models import OrderApiResult

        self.created.append(body)
        if self.order_error:
            return OrderApiResult(ok=False, error=self.order_error)
        return OrderApiResult(ok=True, data=self.order_result)
