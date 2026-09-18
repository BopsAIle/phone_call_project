from __future__ import annotations

import asyncio
import json

import httpx

from calls.client import CallLogClient
from calls.logger import ROLE_ASSISTANT, ROLE_TOOL, ROLE_USER, CallLogger


class FakeCallLogClient:
    def __init__(self, *, record_id: str = "rec-1", fail_start: bool = False) -> None:
        self.record_id = record_id
        self.fail_start = fail_start
        self.started: list[dict] = []
        self.batches: list[list[dict]] = []
        self.ended: list[dict] = []
        self.append_fails = 0

    async def start(self, body: dict) -> str | None:
        self.started.append(body)
        return None if self.fail_start else self.record_id

    async def append_messages(self, record_id: str, messages: list[dict]) -> bool:
        if self.append_fails > 0:
            self.append_fails -= 1
            return False
        self.batches.append(list(messages))
        return True

    async def end(self, record_id: str, body: dict) -> bool:
        self.ended.append(body)
        return True


def _all_messages(client: FakeCallLogClient) -> list[dict]:
    out: list[dict] = []
    for batch in client.batches:
        out.extend(batch)
    for body in client.ended:
        out.extend(body.get("messages") or [])
    return out


# --- bộ gom ---


async def test_transcript_is_flushed_on_finish() -> None:
    client = FakeCallLogClient()
    log = CallLogger(client)
    log.start({"call_id": "abc"})
    await asyncio.sleep(0)
    log.note(ROLE_ASSISTANT, "Dạ nhà hàng Bella Vista xin nghe.")
    log.note(ROLE_USER, "cho tôi hai tô phở")
    log.note(ROLE_TOOL, '{"ok": true}', tool_name="search_menu")
    await log.finish({"status": "completed", "duration_seconds": 42})

    messages = _all_messages(client)
    assert [m["role"] for m in messages] == [ROLE_ASSISTANT, ROLE_USER, ROLE_TOOL]
    assert [m["sequence"] for m in messages] == [0, 1, 2]
    assert messages[2]["tool_name"] == "search_menu"
    assert client.ended[0]["duration_seconds"] == 42


async def test_batch_is_pushed_before_the_call_ends() -> None:
    """Cuộc gọi rớt giữa chừng vẫn phải còn lại phần đã nói."""
    client = FakeCallLogClient()
    log = CallLogger(client, batch_size=3)
    log.start({"call_id": "abc"})
    await asyncio.sleep(0)
    for i in range(3):
        log.note(ROLE_USER, f"câu {i}")
    await asyncio.sleep(0.02)
    assert len(client.batches) == 1
    assert [m["content"] for m in client.batches[0]] == ["câu 0", "câu 1", "câu 2"]


async def test_lines_spoken_before_the_record_exists_are_not_lost() -> None:
    """Lời chào nói trước khi BE trả id — vẫn phải vào transcript."""
    client = FakeCallLogClient()
    log = CallLogger(client)
    log.note(ROLE_ASSISTANT, "Xin chào.")
    log.start({"call_id": "abc"})
    await asyncio.sleep(0.02)
    log.note(ROLE_USER, "alo")
    await log.finish({"status": "completed"})
    assert [m["content"] for m in _all_messages(client)] == ["Xin chào.", "alo"]


async def test_failed_push_is_retried_at_the_end() -> None:
    client = FakeCallLogClient()
    client.append_fails = 1
    log = CallLogger(client, batch_size=1)
    log.start({"call_id": "abc"})
    await asyncio.sleep(0)
    log.note(ROLE_USER, "câu bị rớt")
    await asyncio.sleep(0.02)
    log.note(ROLE_USER, "câu sau")
    await log.finish({"status": "completed"})
    contents = [m["content"] for m in _all_messages(client)]
    assert "câu bị rớt" in contents
    assert "câu sau" in contents


async def test_a_backend_that_never_opens_the_record_does_not_raise() -> None:
    client = FakeCallLogClient(fail_start=True)
    log = CallLogger(client)
    log.start({"call_id": "abc"})
    await asyncio.sleep(0.02)
    log.note(ROLE_USER, "xin chào")
    await log.finish({"status": "completed"})  # không được ném ra ngoài
    assert client.batches == []
    assert client.ended == []


async def test_no_client_means_no_work() -> None:
    log = CallLogger(None)
    log.start({"call_id": "abc"})
    log.note(ROLE_USER, "xin chào")
    await log.finish({"status": "completed"})
    assert log.enabled is False


async def test_huge_tool_payload_is_truncated() -> None:
    client = FakeCallLogClient()
    log = CallLogger(client)
    log.start({"call_id": "abc"})
    await asyncio.sleep(0)
    log.note(ROLE_TOOL, "x" * 20000, tool_name="list_menu")
    await log.finish({})
    assert len(_all_messages(client)[0]["content"]) <= 8001


# --- client HTTP ---


def _client(handler) -> CallLogClient:
    transport = httpx.MockTransport(handler)
    return CallLogClient("http://be", http=httpx.AsyncClient(transport=transport))


async def test_client_reads_the_id_out_of_the_envelope() -> None:
    """BE bọc mọi phản hồi trong {success, message, data, ...}."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/calls/ai/start"
        return httpx.Response(201, json={"success": True, "data": {"id": "rec-9"}})

    assert await _client(handler).start({"call_id": "abc"}) == "rec-9"


async def test_client_swallows_a_400_instead_of_raising() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"message": "property foo should not exist"})

    assert await _client(handler).start({"call_id": "abc"}) is None


async def test_client_swallows_a_dead_backend() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = _client(handler)
    assert await client.start({"call_id": "abc"}) is None
    assert await client.append_messages("rec-1", [{"sequence": 0}]) is False
    assert await client.end("rec-1", {}) is False


async def test_client_posts_the_batch_shape_the_backend_expects() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(201, json={"data": {"added": 1, "total": 1}})

    await _client(handler).append_messages("rec-1", [{"sequence": 0, "role": "user", "content": "hi"}])
    assert seen["path"] == "/calls/ai/rec-1/messages"
    assert seen["body"] == {"messages": [{"sequence": 0, "role": "user", "content": "hi"}]}


# --- nối vào pipeline ---


async def test_pipeline_logs_a_whole_call() -> None:
    from booking.models import Branch, Restaurant
    from tests.fakes import (
        FakeBridgeSocket,
        FakeRestaurantClient,
        FakeSTT,
        ScriptedLlm,
        ScriptedTts,
    )
    from tests.test_booking_session import INIT, _init, _start_pipeline, _stop

    longwang = Restaurant(
        id="rest-1",
        name="Nhà hàng LongWang",
        phone="1900636886",
        branches=[Branch(id="mk", name="Chi nhánh Minh Khai", address="Minh Khai")],
    )
    client = FakeCallLogClient()
    ws = FakeBridgeSocket()
    pipeline, task = await _start_pipeline(
        ws,
        FakeSTT(),
        ScriptedLlm(["Dạ em ghi nhận rồi ạ."]),
        ScriptedTts(),
        restaurant_client=FakeRestaurantClient(result=longwang),
        call_log_client=client,
    )
    await _init(ws, pipeline, {**INIT, "toNumber": "1900636886", "fromNumber": "+84912345678"})
    await pipeline.on_transcript_completed("cho tôi đặt bàn")
    await asyncio.sleep(0.05)
    await _stop(ws, task)

    # Bản ghi được mở với đúng thông tin cuộc gọi
    assert len(client.started) == 1
    opened = client.started[0]
    assert opened["call_id"] == INIT["callId"]
    assert opened["restaurant_id"] == "rest-1"
    assert opened["to_number"] == "1900636886"
    assert opened["from_number"] == "+84912345678"

    # Transcript có cả hai chiều, đúng thứ tự
    messages = _all_messages(client)
    roles = [m["role"] for m in messages]
    assert ROLE_USER in roles and ROLE_ASSISTANT in roles
    assert roles.index(ROLE_USER) < roles.index("assistant", roles.index(ROLE_USER))
    contents = [m["content"] for m in messages]
    assert "cho tôi đặt bàn" in contents
    assert "Dạ em ghi nhận rồi ạ." in contents
    assert [m["sequence"] for m in messages] == sorted(m["sequence"] for m in messages)

    # Cuộc gọi được chốt
    assert len(client.ended) == 1
    assert client.ended[0]["status"] == "completed"
    assert client.ended[0]["duration_seconds"] >= 0


async def test_pipeline_survives_a_dead_call_log_backend() -> None:
    """BE lưu trữ sập thì cuộc gọi vẫn phải chạy bình thường."""
    from tests.fakes import FakeBridgeSocket, FakeSTT, ScriptedLlm, ScriptedTts
    from tests.test_booking_session import INIT, _init, _start_pipeline, _stop

    class DeadClient:
        async def start(self, body):
            raise httpx.ConnectError("boom")

        async def append_messages(self, record_id, messages):
            raise httpx.ConnectError("boom")

        async def end(self, record_id, body):
            raise httpx.ConnectError("boom")

    ws = FakeBridgeSocket()
    tts = ScriptedTts()
    pipeline, task = await _start_pipeline(
        ws, FakeSTT(), ScriptedLlm(["Dạ vâng ạ."]), tts, call_log_client=DeadClient()
    )
    await _init(ws, pipeline, INIT)
    await pipeline.on_transcript_completed("alo")
    await asyncio.sleep(0.05)
    assert "Dạ vâng ạ." in tts.spoken
    await _stop(ws, task)


async def test_only_what_the_caller_heard_reaches_the_transcript() -> None:
    """Câu bị barge-in giết trước khi ra loa không được vào transcript."""
    from tests.fakes import FakeBridgeSocket, FakeSTT, ScriptedLlm, SlowTts
    from tests.test_booking_session import INIT, _init, _start_pipeline, _stop

    client = FakeCallLogClient()
    ws = FakeBridgeSocket()
    pipeline, task = await _start_pipeline(
        ws,
        FakeSTT(),
        ScriptedLlm(["Câu một.", "Câu hai chưa kịp phát."]),
        SlowTts(hold=5.0),
        call_log_client=client,
    )
    await _init(ws, pipeline, INIT)
    await pipeline.on_transcript_completed("alo")
    await asyncio.sleep(0.05)
    await pipeline.on_speech_started()
    await asyncio.sleep(0.05)
    await _stop(ws, task)

    contents = [m["content"] for m in _all_messages(client)]
    assert "Câu hai chưa kịp phát." not in contents
