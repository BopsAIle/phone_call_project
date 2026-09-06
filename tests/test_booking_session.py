from __future__ import annotations

import asyncio
import json

from booking.matcher import ScriptedBranchMatcher
from booking.models import Branch, HotlineResult, MatchResult, Restaurant
from bridge.session import CallPipeline, CallState
from tests.fakes import (
    FakeBridgeSocket,
    FakeRestaurantClient,
    FakeSTT,
    ScriptedLlm,
    ScriptedTts,
    ToolThenSpeakLlm,
)

INIT = {
    "event": "session.init",
    "callId": "clx8k2p9v0000abcd1234efgh",
    "storeName": "Bella Vista",
    "timezone": "Europe/Berlin",
    "locale": "en",
    "greeting": "Thanks for calling Bella Vista. This is an automated assistant — how can I help you today?",
}

MINH_KHAI = Branch(id="mk", name="Chi nhánh Minh Khai", address="Minh Khai")
BA_DINH = Branch(id="bd", name="Chi nhánh Ba Đình", address="Ba Đình")
LONGWANG = Restaurant(
    id="rest-1",
    name="Nhà hàng LongWang",
    phone="1900636886",
    branches=[MINH_KHAI, BA_DINH],
)


async def _start_pipeline(ws, stt, llm, tts, **kwargs):
    pipeline = CallPipeline(ws, stt=stt, llm=llm, tts=tts, **kwargs)
    task = asyncio.create_task(pipeline.run())
    await asyncio.sleep(0.02)
    return pipeline, task


async def _init(ws, pipeline, payload: dict) -> None:
    await ws.push_text(json.dumps(payload))
    deadline = asyncio.get_event_loop().time() + 1.0
    while not pipeline.session.inited:
        if asyncio.get_event_loop().time() > deadline:
            raise AssertionError("session.init was not processed")
        await asyncio.sleep(0.01)
    if pipeline._catalog_task is not None:
        await pipeline._catalog_task
    deadline = asyncio.get_event_loop().time() + 1.0
    while pipeline.session.state == CallState.GREETING:
        if asyncio.get_event_loop().time() > deadline:
            break
        await asyncio.sleep(0.01)


async def _stop(ws, task) -> None:
    await ws.disconnect()
    await asyncio.wait_for(task, timeout=2)


async def test_prefetch_200_loads_restaurant_and_branches() -> None:
    ws = FakeBridgeSocket()
    client = FakeRestaurantClient(result=LONGWANG)
    pipeline, task = await _start_pipeline(
        ws, FakeSTT(), ScriptedLlm([]), ScriptedTts(), restaurant_client=client
    )
    await _init(ws, pipeline, {**INIT, "toNumber": "+1900636886"})
    assert pipeline.session.to_number == "1900636886"
    assert pipeline.session.restaurant_id == "rest-1"
    assert pipeline.session.restaurant_name == "Nhà hàng LongWang"
    assert pipeline.session.restaurant_missing is False
    assert [b.id for b in pipeline.session.branches] == ["mk", "bd"]
    assert client.lookups == ["1900636886"]
    await _stop(ws, task)


async def test_prefetch_404_marks_restaurant_missing() -> None:
    ws = FakeBridgeSocket()
    client = FakeRestaurantClient(result=HotlineResult(missing=True))
    pipeline, task = await _start_pipeline(
        ws, FakeSTT(), ScriptedLlm([]), ScriptedTts(), restaurant_client=client
    )
    await _init(ws, pipeline, {**INIT, "toNumber": "999"})
    assert pipeline.session.restaurant_missing is True
    assert pipeline.session.restaurant_id == ""
    assert pipeline.session.branches == []
    assert client.lookups == ["999"]
    await _stop(ws, task)


async def test_prefetch_missing_tonumber_skips_lookup() -> None:
    ws = FakeBridgeSocket()
    client = FakeRestaurantClient(result=LONGWANG)
    pipeline, task = await _start_pipeline(
        ws, FakeSTT(), ScriptedLlm([]), ScriptedTts(), restaurant_client=client
    )
    await _init(ws, pipeline, INIT)
    assert pipeline.session.to_number == ""
    assert pipeline.session.restaurant_missing is True
    assert client.lookups == []
    await _stop(ws, task)


async def test_tool_loop_speaks_sentence_not_tool_payload() -> None:
    ws = FakeBridgeSocket()
    tts = ScriptedTts()
    restaurant = FakeRestaurantClient(result=LONGWANG)
    spoken = "Your table at Minh Khai is booked for four at seven thirty."
    llm = ToolThenSpeakLlm(
        "create_booking",
        {
            "customer_name": "Nguyễn Văn A",
            "phone_number": "0123456789",
            "party_size": 4,
            "booking_date": "2026-08-28",
            "booking_time": "19:30",
            "restaurant_id": "should-be-ignored",
            "branch_id": "should-be-ignored",
        },
        [spoken],
    )
    pipeline, task = await _start_pipeline(
        ws,
        FakeSTT(),
        llm,
        tts,
        restaurant_client=restaurant,
        matcher=ScriptedBranchMatcher(),
    )
    await _init(ws, pipeline, {**INIT, "toNumber": "+1900636886"})
    pipeline.session.select_branch("mk")
    await pipeline.on_transcript_completed("Yes, please book it.")
    deadline = asyncio.get_event_loop().time() + 1.0
    while spoken not in tts.spoken or pipeline.session.state != CallState.LISTENING:
        if asyncio.get_event_loop().time() > deadline:
            break
        await asyncio.sleep(0.02)
    assert spoken in tts.spoken
    assert INIT["greeting"] in tts.spoken
    for line in tts.spoken:
        assert "phone_ai" not in line
        assert "should-be-ignored" not in line
        assert "restaurant_id" not in line
        assert "create_booking" not in line
    assert llm.results
    tool_result = json.loads(llm.results[0])
    assert tool_result["ok"] is True
    assert len(restaurant.created) == 1
    body = restaurant.created[0]
    assert body["restaurant_id"] == "rest-1"
    assert body["branch_id"] == "mk"
    assert body["customer_phone"] == "0123456789"
    assert pipeline.session.state == CallState.LISTENING
    assert pipeline.session.booking_created is True
    await _stop(ws, task)


async def test_resolve_branch_tool_then_confirm_aloud() -> None:
    ws = FakeBridgeSocket()
    tts = ScriptedTts()
    restaurant = FakeRestaurantClient(result=LONGWANG)
    spoken = "Minh Khai, is that the branch you want?"
    llm = ToolThenSpeakLlm(
        "resolve_branch",
        {"spoken_name": "Minh Khai"},
        [spoken],
    )
    matcher = ScriptedBranchMatcher(
        {
            "Minh Khai": MatchResult(
                status="match",
                branch_id="mk",
                confidence="high",
                confirm_name="Chi nhánh Minh Khai",
            )
        }
    )
    pipeline, task = await _start_pipeline(
        ws,
        FakeSTT(),
        llm,
        tts,
        restaurant_client=restaurant,
        matcher=matcher,
    )
    await _init(ws, pipeline, {**INIT, "toNumber": "1900636886"})
    await pipeline.on_transcript_completed("I'd like Minh Khai.")
    deadline = asyncio.get_event_loop().time() + 1.0
    while spoken not in tts.spoken:
        if asyncio.get_event_loop().time() > deadline:
            break
        await asyncio.sleep(0.02)
    assert spoken in tts.spoken
    assert pipeline.session.selected_branch_id == "mk"
    assert restaurant.created == []
    await _stop(ws, task)
