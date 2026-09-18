from __future__ import annotations

import asyncio
from typing import Callable, Optional


class FakeBridgeSocket:
    def __init__(self) -> None:
        self.sent: list[tuple[str, bytes | str]] = []
        self.incoming: asyncio.Queue[dict] = asyncio.Queue()
        self.close_calls: list[tuple[int, str]] = []
        self.closed = False

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

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.close_calls.append((code, reason))
        if self.closed:
            return
        self.closed = True
        await self.incoming.put({"type": "websocket.disconnect", "code": code})

    async def disconnect(self) -> None:
        await self.incoming.put({"type": "websocket.disconnect", "code": 1000})


class FakeSTT:
    def __init__(self) -> None:
        self.is_ready = False
        self.appended: list[bytes] = []
        self.handler = None
        self.locale: Optional[str] = None
        self.closed = False
        self.prompt = ""
        self.keywords: list[str] = []
        self.context_updates = 0

    async def start(self, handler, locale: str | None = None) -> None:
        self.handler = handler
        self.locale = locale
        self.is_ready = True

    async def update_context(self, *, prompt: str = "", keywords: list[str] | None = None) -> None:
        if prompt:
            self.prompt = prompt
        if keywords is not None:
            self.keywords = list(keywords)
        self.context_updates += 1

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


# --- Giả lập OpenAI chat.completions.create (stream) ---------------------------------
#
# llm/stream.py trước đây không có test trực tiếp nào, nên các lỗi cắt câu / sổ hội thoại
# / im lặng đều lọt. Fake này dựng đúng hình dạng chunk mà SDK trả về để test được.


class LlmRound:
    """Một lần gọi chat.completions.create trả về gì.

    text   — model nói ra chữ
    tools  — model gọi tool: [(call_id, tên, chuỗi JSON tham số)]
    Model thật hầu như không bao giờ vừa nói vừa gọi tool trong cùng một lượt; để cả hai
    rỗng là mô phỏng completion rỗng (đường dẫn tới im lặng).
    """

    def __init__(
        self,
        text: str = "",
        tools: list[tuple[str, str, str]] | None = None,
        finish_reason: str = "stop",
        token_size: int = 4,
    ) -> None:
        self.text = text
        self.tools = list(tools or [])
        self.finish_reason = finish_reason
        self.token_size = max(1, token_size)

    def chunks(self) -> list[object]:
        from types import SimpleNamespace

        out: list[object] = []
        for start in range(0, len(self.text), self.token_size):
            piece = self.text[start : start + self.token_size]
            out.append(
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(content=piece, tool_calls=None),
                            finish_reason=None,
                        )
                    ]
                )
            )
        for index, (call_id, name, arguments) in enumerate(self.tools):
            # Tên tới ở chunk đầu, tham số nhỏ giọt ở các chunk sau — giống SDK thật.
            out.append(
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(
                                content=None,
                                tool_calls=[
                                    SimpleNamespace(
                                        index=index,
                                        id=call_id,
                                        function=SimpleNamespace(name=name, arguments=""),
                                    )
                                ],
                            ),
                            finish_reason=None,
                        )
                    ]
                )
            )
            for start in range(0, len(arguments), 8):
                out.append(
                    SimpleNamespace(
                        choices=[
                            SimpleNamespace(
                                delta=SimpleNamespace(
                                    content=None,
                                    tool_calls=[
                                        SimpleNamespace(
                                            index=index,
                                            id=None,
                                            function=SimpleNamespace(
                                                name=None,
                                                arguments=arguments[start : start + 8],
                                            ),
                                        )
                                    ],
                                ),
                                finish_reason=None,
                            )
                        ]
                    )
                )
        out.append(
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(content=None, tool_calls=None),
                        finish_reason=self.finish_reason,
                    )
                ]
            )
        )
        return out


class _FakeStream:
    def __init__(self, chunks: list[object]) -> None:
        self._chunks = list(chunks)
        self.closed = False

    def __aiter__(self) -> "_FakeStream":
        return self

    async def __anext__(self) -> object:
        if not self._chunks:
            raise StopAsyncIteration
        await asyncio.sleep(0)
        return self._chunks.pop(0)

    async def close(self) -> None:
        self.closed = True


class FakeChatCompletions:
    """Client hình dạng như OpenAI SDK: `client.chat.completions.create(**kwargs)`.

    `rounds` là kịch bản cho từng vòng liên tiếp. Hết kịch bản thì lặp lại vòng cuối,
    để test được trường hợp model gọi tool mãi không dừng.
    """

    def __init__(self, rounds: list[LlmRound]) -> None:
        from types import SimpleNamespace

        self.rounds = list(rounds)
        self.requests: list[dict] = []
        self.streams: list[_FakeStream] = []
        self._index = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    @property
    def call_count(self) -> int:
        return len(self.requests)

    async def _create(self, **kwargs) -> _FakeStream:
        self.requests.append(kwargs)
        if self._index < len(self.rounds):
            spec = self.rounds[self._index]
            self._index += 1
        else:
            spec = self.rounds[-1]
        stream = _FakeStream(spec.chunks())
        self.streams.append(stream)
        return stream
