from __future__ import annotations

import asyncio
import json
import time

from booking.matcher import ScriptedBranchMatcher
from booking.models import Branch, Restaurant
from bridge.protocol import BYTES_PER_SECOND, EVENT_CALL_END
from bridge.session import CallPipeline, CallSession, CallState
from tests.fakes import (
    FakeBridgeSocket,
    FakeRestaurantClient,
    FakeSTT,
    ScriptedLlm,
    ScriptedTts,
    ToolThenSpeakLlm,
)
from tests.test_booking_session import INIT, _init, _start_pipeline, _stop
from turn.barge_in import LEAD_SECONDS, OutboundGate, remaining_playback_seconds

MINH_KHAI = Branch(id="mk", name="Chi nhánh Minh Khai", address="Minh Khai")
LONGWANG = Restaurant(
    id="rest-1",
    name="Nhà hàng LongWang",
    phone="1900636886",
    branches=[MINH_KHAI],
)

_BOOKING_ARGS = {
    "customer_name": "Nguyễn Văn A",
    "phone_number": "0123456789",
    "party_size": 4,
    "booking_date": "2026-08-28",
    "booking_time": "19:30",
}

_CLOSING = "Your table at Minh Khai is booked. Thank you for calling."


def _events(ws: FakeBridgeSocket) -> list[dict]:
    return [json.loads(data) for kind, data in ws.sent if kind == "text"]


async def _wait_until(predicate, timeout: float = 2.0) -> bool:
    deadline = asyncio.get_event_loop().time() + timeout
    while not predicate():
        if asyncio.get_event_loop().time() > deadline:
            return False
        await asyncio.sleep(0.01)
    return True


def test_remaining_playback_seconds_no_audio() -> None:
    gate = OutboundGate(FakeBridgeSocket(), CallSession())
    assert remaining_playback_seconds(gate, 300) == 0.0


async def test_remaining_playback_seconds_from_bytes() -> None:
    session = CallSession()
    session.generation_id = 1
    gate = OutboundGate(FakeBridgeSocket(), session)
    pcm = b"\x00\x01" * (BYTES_PER_SECOND // 2)
    await gate.send_audio(1, pcm)
    remaining = remaining_playback_seconds(gate, 300)
    expected = 1.0 + LEAD_SECONDS + 0.3
    assert expected - 0.05 <= remaining <= expected


def test_remaining_playback_seconds_subtracts_elapsed() -> None:
    class _Gate:
        bytes_sent = BYTES_PER_SECOND * 2
        first_frame_at = time.monotonic() - 1.0

    remaining = remaining_playback_seconds(_Gate(), 300)
    expected = 1.0 + LEAD_SECONDS + 0.3
    assert expected - 0.05 <= remaining <= expected + 0.05


async def test_successful_booking_sends_call_end_and_closes() -> None:
    ws = FakeBridgeSocket()
    stt = FakeSTT()
    tts = ScriptedTts()
    restaurant = FakeRestaurantClient(result=LONGWANG)
    llm = ToolThenSpeakLlm("create_booking", _BOOKING_ARGS, [_CLOSING])
    pipeline, task = await _start_pipeline(
        ws,
        stt,
        llm,
        tts,
        restaurant_client=restaurant,
        matcher=ScriptedBranchMatcher(),
        call_end_grace_ms=0,
    )
    await _init(ws, pipeline, {**INIT, "toNumber": "1900636886"})
    pipeline.session.select_branch("mk")
    await pipeline.on_transcript_completed("Yes, please book it.")
    assert await _wait_until(lambda: bool(ws.close_calls))
    assert ws.close_calls[0] == (1000, "completed")
    assert pipeline.session.closed is True
    assert pipeline.session.state == CallState.CLOSED
    assert stt.closed is True
    assert any(event.get("event") == EVENT_CALL_END for event in _events(ws))
    end = next(event for event in _events(ws) if event.get("event") == EVENT_CALL_END)
    assert end["reason"] == "completed"
    assert end["callId"] == INIT["callId"]
    await asyncio.wait_for(task, timeout=2)


async def test_speech_started_during_grace_cancels_hangup() -> None:
    ws = FakeBridgeSocket()
    tts = ScriptedTts()
    restaurant = FakeRestaurantClient(result=LONGWANG)
    llm = ToolThenSpeakLlm("create_booking", _BOOKING_ARGS, [_CLOSING])
    pipeline, task = await _start_pipeline(
        ws,
        FakeSTT(),
        llm,
        tts,
        restaurant_client=restaurant,
        matcher=ScriptedBranchMatcher(),
    )
    await _init(ws, pipeline, {**INIT, "toNumber": "1900636886"})
    pipeline.session.select_branch("mk")
    await pipeline.on_transcript_completed("Yes, please book it.")
    assert await _wait_until(
        lambda: pipeline._hangup_task is not None and not pipeline._hangup_task.done()
    )
    assert pipeline.session.state == CallState.LISTENING
    await pipeline.on_speech_started()
    await asyncio.sleep(0.5)
    assert pipeline.session.closed is False
    assert pipeline.session.state == CallState.LISTENING
    assert ws.close_calls == []
    assert not any(event.get("event") == EVENT_CALL_END for event in _events(ws))
    await _stop(ws, task)


async def test_create_booking_error_does_not_hangup() -> None:
    ws = FakeBridgeSocket()
    tts = ScriptedTts()
    restaurant = FakeRestaurantClient(result=LONGWANG, booking_error="http_500")
    spoken = "Sorry, I could not complete that reservation."
    llm = ToolThenSpeakLlm("create_booking", _BOOKING_ARGS, [spoken])
    pipeline, task = await _start_pipeline(
        ws,
        FakeSTT(),
        llm,
        tts,
        restaurant_client=restaurant,
        matcher=ScriptedBranchMatcher(),
        call_end_grace_ms=0,
    )
    await _init(ws, pipeline, {**INIT, "toNumber": "1900636886"})
    pipeline.session.select_branch("mk")
    await pipeline.on_transcript_completed("Yes, please book it.")
    assert await _wait_until(lambda: spoken in tts.spoken)
    await asyncio.sleep(0.2)
    assert pipeline.session.booking_created is False
    assert pipeline.session.closed is False
    assert pipeline.session.state == CallState.LISTENING
    assert ws.close_calls == []
    assert not any(event.get("event") == EVENT_CALL_END for event in _events(ws))
    await _stop(ws, task)


async def test_plain_reply_does_not_hangup() -> None:
    ws = FakeBridgeSocket()
    tts = ScriptedTts()
    pipeline, task = await _start_pipeline(ws, FakeSTT(), ScriptedLlm(["How many people?"]), tts)
    await _init(ws, pipeline, INIT)
    await pipeline.on_transcript_completed("I want a table.")
    assert await _wait_until(lambda: "How many people?" in tts.spoken)
    await asyncio.sleep(0.2)
    assert pipeline.session.closed is False
    assert ws.close_calls == []
    await _stop(ws, task)
