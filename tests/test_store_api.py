from __future__ import annotations

import asyncio
import json
from datetime import date, timedelta

import httpx
import pytest

from agents.registry import build_registry
from bridge.session import CallPipeline
from llm.stream import SpeakSentence, ToolCallRequest
from tools.store_api import HttpStoreApi, StoreApiUncertain, StoreApiValidationError, StubStoreApi
from tests.fakes import FakeBridgeSocket, FakeSTT, ScriptedToolLlm, ScriptedTts

SOON = (date.today() + timedelta(days=7)).isoformat()
DETAILS = {
    "date": SOON,
    "time": "20:00",
    "party_size": 4,
    "name": "Anna",
    "phone": "+49 30 1234567",
}
INIT = {
    "event": "session.init",
    "callId": "call-1",
    "storeName": "Bella Vista",
    "timezone": "Europe/Berlin",
    "locale": "en",
    "greeting": "Thanks for calling Bella Vista. This is an automated assistant.",
}


def _api(handler, **kwargs) -> HttpStoreApi:
    return HttpStoreApi(
        "https://store.example/api",
        token="secret",
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


async def _submit(api: HttpStoreApi):
    return await api.submit_request(
        "booking", DETAILS, idempotency_key="call-1:abc123", call_id="call-1"
    )


# --- happy path -------------------------------------------------------------


async def test_successful_submit_posts_details_and_headers() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json={"request_id": "req-9"})

    result = await _submit(_api(handler))

    assert result == {"request_id": "req-9"}
    assert len(seen) == 1
    assert str(seen[0].url) == "https://store.example/api/bookings"
    assert seen[0].headers["Idempotency-Key"] == "call-1:abc123"
    assert seen[0].headers["Authorization"] == "Bearer secret"
    body = json.loads(seen[0].content)
    assert body["callId"] == "call-1"
    assert body["party_size"] == 4


async def test_non_json_success_is_still_accepted() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(204, text="")

    assert await _submit(_api(handler)) == {"status": "accepted"}


async def test_unknown_kind_is_a_validation_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - never called
        raise AssertionError("must not reach the network")

    with pytest.raises(StoreApiValidationError):
        await _api(handler).submit_request(
            "haircut", {}, idempotency_key="k", call_id="call-1"
        )


# --- failures ---------------------------------------------------------------


async def test_4xx_is_not_retried() -> None:
    """A validation error is deterministic; sending it again just wastes a second."""
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(422, text="party_size too large")

    with pytest.raises(StoreApiValidationError, match="party_size"):
        await _submit(_api(handler))
    assert calls == 1


async def test_5xx_is_retried_once_then_uncertain() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503)

    with pytest.raises(StoreApiUncertain):
        await _submit(_api(handler))
    assert calls == 2


async def test_retry_reuses_the_same_idempotency_key() -> None:
    """A duplicate staff note is minor, but the server can still dedupe."""
    keys: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        keys.append(request.headers["Idempotency-Key"])
        return httpx.Response(500)

    with pytest.raises(StoreApiUncertain):
        await _submit(_api(handler))
    assert keys == ["call-1:abc123", "call-1:abc123"]


async def test_retry_recovers_when_the_second_attempt_succeeds() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(502)
        return httpx.Response(200, json={"request_id": "req-2"})

    assert await _submit(_api(handler)) == {"request_id": "req-2"}
    assert calls == 2


async def test_timeout_is_uncertain_not_failed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    with pytest.raises(StoreApiUncertain, match="timeout"):
        await _submit(_api(handler))


# --- hangup mid-write -------------------------------------------------------


async def test_hangup_lets_a_confirmed_write_finish() -> None:
    """The caller said yes, then hung up. The request must still be filed."""
    ws = FakeBridgeSocket()
    api = StubStoreApi(delay=0.25)
    llm = ScriptedToolLlm(
        [
            [ToolCallRequest(id="h1", name="handoff_to_booking", arguments="{}")],
            [ToolCallRequest(id="s1", name="set_booking_details", arguments=json.dumps(DETAILS))],
            [ToolCallRequest(id="k1", name="confirm_booking_details", arguments="{}")],
        ]
    )
    pipeline = CallPipeline(
        ws, stt=FakeSTT(), llm=llm, tts=ScriptedTts(), tools=build_registry(api)
    )
    task = asyncio.create_task(pipeline.run())
    await asyncio.sleep(0.02)
    await ws.push_text(json.dumps(INIT))
    await asyncio.sleep(0.1)

    await pipeline.on_transcript_completed("A table, please.")
    await asyncio.sleep(0.3)
    assert pipeline.session.details_fingerprint is not None

    llm.rounds.append([ToolCallRequest(id="w1", name="submit_booking_request", arguments="{}")])
    llm.rounds.append([SpeakSentence("Someone will call you back.")])
    await pipeline.on_transcript_completed("Yes, that's right.")

    # Hang up while the write is still in flight.
    await asyncio.sleep(0.05)
    assert api.submitted == []
    await ws.disconnect()
    await asyncio.wait_for(task, timeout=3)

    assert len(api.submitted) == 1
    assert api.submitted[0]["payload"] == DETAILS


async def test_hangup_before_dispatch_files_nothing() -> None:
    """Only an already-dispatched write survives; an unconfirmed one does not."""
    ws = FakeBridgeSocket()
    api = StubStoreApi(delay=0.25)
    llm = ScriptedToolLlm(
        [
            [ToolCallRequest(id="h1", name="handoff_to_booking", arguments="{}")],
            [ToolCallRequest(id="s1", name="set_booking_details", arguments=json.dumps(DETAILS))],
        ]
    )
    pipeline = CallPipeline(
        ws, stt=FakeSTT(), llm=llm, tts=ScriptedTts(), tools=build_registry(api)
    )
    task = asyncio.create_task(pipeline.run())
    await asyncio.sleep(0.02)
    await ws.push_text(json.dumps(INIT))
    await asyncio.sleep(0.1)
    await pipeline.on_transcript_completed("A table, please.")
    await asyncio.sleep(0.2)

    await ws.disconnect()
    await asyncio.wait_for(task, timeout=3)

    assert api.submitted == []
