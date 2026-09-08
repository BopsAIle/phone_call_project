from __future__ import annotations

import asyncio
import json

from booking.matcher import ScriptedBranchMatcher
from booking.models import Branch, Restaurant
from bridge.protocol import EVENT_DTMF, parse_text_frame
from bridge.session import CallPipeline, CallState
from llm.stream import INVALID_MENU_EN, INVALID_MENU_VI
from tests.fakes import (
    FakeBridgeSocket,
    FakeRestaurantClient,
    FakeSTT,
    ScriptedLlm,
    ScriptedTts,
    SlowTts,
    ToolThenSpeakLlm,
)
from tests.test_booking_session import INIT, _init, _start_pipeline, _stop
from tests.test_call_end import _BOOKING_ARGS, _CLOSING


MINH_KHAI = Branch(id="mk", name="Chi nhánh Minh Khai", address="Minh Khai")
LONGWANG = Restaurant(
    id="rest-1",
    name="Nhà hàng LongWang",
    phone="1900636886",
    branches=[MINH_KHAI],
)


async def _wait_until(predicate, timeout: float = 2.0) -> bool:
    deadline = asyncio.get_event_loop().time() + timeout
    while not predicate():
        if asyncio.get_event_loop().time() > deadline:
            return False
        await asyncio.sleep(0.01)
    return True


def test_parse_dtmf_valid() -> None:
    parsed = parse_text_frame(json.dumps({"event": EVENT_DTMF, "digit": "2", "callId": "c1"}))
    assert parsed is not None
    assert parsed.digit == "2"
    assert parsed.call_id == "c1"


def test_parse_dtmf_rejects_multi_and_empty() -> None:
    assert parse_text_frame(json.dumps({"event": EVENT_DTMF, "digit": "12"})) is None
    assert parse_text_frame(json.dumps({"event": EVENT_DTMF, "digit": ""})) is None
    assert parse_text_frame(json.dumps({"event": EVENT_DTMF})) is None


async def test_digits_set_intent_and_fulfillment() -> None:
    cases = (
        ("1", "booking", ""),
        ("2", "order", "pickup"),
        ("3", "order", "delivery"),
    )
    for digit, intent, fulfillment in cases:
        ws = FakeBridgeSocket()
        pipeline, task = await _start_pipeline(
            ws, FakeSTT(), ScriptedLlm(["Okay."]), ScriptedTts()
        )
        await _init(ws, pipeline, INIT)
        assert pipeline.session.awaiting_choice is True
        await pipeline.on_dtmf({"event": "dtmf", "digit": digit})
        assert pipeline.session.service_choice == digit
        assert pipeline.session.intent == intent
        assert pipeline.session.fulfillment == fulfillment
        assert pipeline.session.awaiting_choice is False
        prompt = pipeline.session.history[0]["content"]
        assert "nếu khách chưa nói rõ muốn gì" not in prompt
        await _stop(ws, task)


async def test_dtmf_during_greeting_interrupts() -> None:
    ws = FakeBridgeSocket()
    tts = SlowTts(hold=0.5)
    pipeline, task = await _start_pipeline(ws, FakeSTT(), ScriptedLlm(["Booking next."]), tts)
    await ws.push_text(json.dumps(INIT))
    await asyncio.sleep(0.05)
    assert pipeline.session.state == CallState.GREETING
    gen_before = pipeline.session.generation_id
    await pipeline.on_dtmf({"event": "dtmf", "digit": "1"})
    await asyncio.sleep(0.1)
    interrupts = [
        i
        for i, (kind, payload) in enumerate(ws.sent)
        if kind == "text" and json.loads(payload).get("event") == "interrupt"
    ]
    assert interrupts
    idx = interrupts[0]
    assert any(kind == "bytes" for kind, _ in ws.sent[:idx])
    assert pipeline.session.generation_id > gen_before
    assert pipeline.session.intent == "booking"
    await _stop(ws, task)


async def test_invalid_digit_replays_menu_then_falls_back() -> None:
    ws = FakeBridgeSocket()
    tts = ScriptedTts()
    pipeline, task = await _start_pipeline(ws, FakeSTT(), ScriptedLlm([]), tts)
    await _init(ws, pipeline, {**INIT, "locale": "vi", "greeting": "Xin chào."})
    assert pipeline.session.awaiting_choice is True
    await pipeline.on_dtmf({"event": "dtmf", "digit": "7"})
    assert pipeline.session.intent == ""
    assert pipeline.session.invalid_digit_count == 1
    assert pipeline.session.awaiting_choice is True
    assert await _wait_until(lambda: INVALID_MENU_VI in tts.spoken)
    await pipeline.on_dtmf({"event": "dtmf", "digit": "8"})
    assert pipeline.session.invalid_digit_count == 2
    assert pipeline.session.awaiting_choice is True
    await pipeline.on_dtmf({"event": "dtmf", "digit": "0"})
    assert pipeline.session.invalid_digit_count == 3
    assert pipeline.session.awaiting_choice is False
    prompt = pipeline.session.history[0]["content"]
    assert "bạn muốn đặt bàn hay mang về" in prompt
    await _stop(ws, task)


async def test_dtmf_debounce_same_digit() -> None:
    ws = FakeBridgeSocket()
    llm = ScriptedLlm(["First.", "Second."])
    pipeline, task = await _start_pipeline(ws, FakeSTT(), llm, ScriptedTts())
    await _init(ws, pipeline, INIT)
    await pipeline.on_dtmf({"event": "dtmf", "digit": "1"})
    await pipeline.on_dtmf({"event": "dtmf", "digit": "1"})
    await asyncio.sleep(0.1)
    assert pipeline.session.intent == "booking"
    assert len(llm.calls) == 1
    await _stop(ws, task)


async def test_change_digit_keeps_name_phone_branch() -> None:
    ws = FakeBridgeSocket()
    restaurant = FakeRestaurantClient(result=LONGWANG)
    pipeline, task = await _start_pipeline(
        ws,
        FakeSTT(),
        ScriptedLlm(["Okay."]),
        ScriptedTts(),
        restaurant_client=restaurant,
        matcher=ScriptedBranchMatcher(),
        dtmf_debounce_ms=0,
    )
    await _init(ws, pipeline, {**INIT, "toNumber": "1900636886"})
    pipeline.session.select_branch("mk")
    pipeline.session.order_customer_name = "Nguyễn Văn A"
    pipeline.session.order_customer_phone = "0901234567"
    await pipeline.on_dtmf({"event": "dtmf", "digit": "2"})
    assert pipeline.session.intent == "order"
    assert pipeline.session.fulfillment == "pickup"
    await pipeline.on_dtmf({"event": "dtmf", "digit": "1"})
    assert pipeline.session.intent == "booking"
    assert pipeline.session.fulfillment == ""
    assert pipeline.session.order_customer_name == "Nguyễn Văn A"
    assert pipeline.session.order_customer_phone == "0901234567"
    assert pipeline.session.selected_branch_id == "mk"
    await _stop(ws, task)


async def test_digit_3_after_booking_keeps_identity() -> None:
    ws = FakeBridgeSocket()
    restaurant = FakeRestaurantClient(result=LONGWANG)
    pipeline, task = await _start_pipeline(
        ws,
        FakeSTT(),
        ScriptedLlm(["Delivery next."]),
        ScriptedTts(),
        restaurant_client=restaurant,
        matcher=ScriptedBranchMatcher(),
    )
    await _init(ws, pipeline, {**INIT, "toNumber": "1900636886"})
    pipeline.session.select_branch("mk")
    pipeline.session.booking_created = True
    pipeline.session.order_customer_name = "Nguyễn Văn A"
    pipeline.session.order_customer_phone = "0901234567"
    pipeline.session.refresh_system_prompt()
    await pipeline.on_dtmf({"event": "dtmf", "digit": "3"})
    assert pipeline.session.intent == "order"
    assert pipeline.session.fulfillment == "delivery"
    assert pipeline.session.booking_created is True
    assert pipeline.session.order_customer_name == "Nguyễn Văn A"
    assert pipeline.session.order_customer_phone == "0901234567"
    assert pipeline.session.selected_branch_id == "mk"
    await _stop(ws, task)


async def test_digit_1_after_booking_does_not_post_again() -> None:
    ws = FakeBridgeSocket()
    tts = ScriptedTts()
    restaurant = FakeRestaurantClient(result=LONGWANG)
    llm = ToolThenSpeakLlm("create_booking", _BOOKING_ARGS, ["Already booked."])
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
    pipeline.session.booking_created = True
    await pipeline.on_dtmf({"event": "dtmf", "digit": "1"})
    assert await _wait_until(lambda: bool(llm.results))
    payload = json.loads(llm.results[0])
    assert payload["ok"] is True
    assert payload["already_created"] is True
    assert restaurant.created == []
    await _stop(ws, task)


async def test_dtmf_during_hangup_grace_cancels_close() -> None:
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
    await pipeline.on_dtmf({"event": "dtmf", "digit": "3"})
    assert pipeline.session.service_choice == "3"
    assert pipeline.session.intent == "order"
    assert pipeline.session.fulfillment == "delivery"
    await asyncio.sleep(0.5)
    assert pipeline.session.closed is False
    assert ws.close_calls == []
    await _stop(ws, task)


async def test_menu_timeout_falls_back_to_verbal_prompt() -> None:
    ws = FakeBridgeSocket()
    pipeline, task = await _start_pipeline(
        ws,
        FakeSTT(),
        ScriptedLlm([]),
        ScriptedTts(),
        dtmf_menu_timeout_seconds=0,
    )
    await _init(ws, pipeline, INIT)
    assert await _wait_until(lambda: pipeline.session.awaiting_choice is False)
    prompt = pipeline.session.history[0]["content"]
    assert "bạn muốn đặt bàn hay mang về" in prompt
    assert "đang nghe menu phím" not in prompt
    await _stop(ws, task)


async def test_speech_while_awaiting_choice_still_runs() -> None:
    ws = FakeBridgeSocket()
    tts = ScriptedTts()
    llm = ScriptedLlm(["A table for two, noted."])
    pipeline, task = await _start_pipeline(ws, FakeSTT(), llm, tts)
    await _init(ws, pipeline, INIT)
    assert pipeline.session.awaiting_choice is True
    await pipeline.on_transcript_completed("I want to book a table.")
    assert pipeline.session.awaiting_choice is False
    assert await _wait_until(lambda: "A table for two, noted." in tts.spoken)
    assert llm.calls
    await _stop(ws, task)


async def test_malformed_dtmf_is_ignored() -> None:
    ws = FakeBridgeSocket()
    pipeline, task = await _start_pipeline(ws, FakeSTT(), ScriptedLlm([]), ScriptedTts())
    await _init(ws, pipeline, INIT)
    await pipeline.on_dtmf({"event": "dtmf", "digit": "12"})
    await pipeline.on_dtmf({"event": "dtmf", "digit": ""})
    await ws.push_text(json.dumps({"event": "dtmf", "digit": "12"}))
    await asyncio.sleep(0.05)
    assert pipeline.session.intent == ""
    assert pipeline.session.service_choice == ""
    assert pipeline.session.awaiting_choice is True
    await _stop(ws, task)


async def test_english_invalid_menu_is_spoken() -> None:
    ws = FakeBridgeSocket()
    tts = ScriptedTts()
    pipeline, task = await _start_pipeline(ws, FakeSTT(), ScriptedLlm([]), tts)
    await _init(ws, pipeline, INIT)
    await pipeline.on_dtmf({"event": "dtmf", "digit": "7"})
    assert await _wait_until(lambda: INVALID_MENU_EN in tts.spoken)
    await _stop(ws, task)
