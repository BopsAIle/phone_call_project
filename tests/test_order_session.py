from __future__ import annotations

import asyncio
import json

from booking.matcher import ScriptedBranchMatcher
from booking.models import Branch, Restaurant
from bridge.session import CallPipeline, CallState
from order.matcher import ScriptedMenuMatcher
from order.models import CartLine, MenuItem, MenuMatchResult
from tests.fakes import (
    FakeBridgeSocket,
    FakeOrderClient,
    FakeRestaurantClient,
    FakeSTT,
    ScriptedLlm,
    ScriptedTts,
    ToolThenSpeakLlm,
)
from tests.test_booking_session import INIT, _init, _start_pipeline, _stop

MINH_KHAI = Branch(id="mk", name="Chi nhánh Minh Khai", address="Minh Khai")
BA_DINH = Branch(id="bd", name="Chi nhánh Ba Đình", address="Ba Đình")
LONGWANG = Restaurant(
    id="rest-1",
    name="Nhà hàng LongWang",
    phone="1900636886",
    branches=[MINH_KHAI],
)
LONGWANG_TWO = Restaurant(
    id="rest-1",
    name="Nhà hàng LongWang",
    phone="1900636886",
    branches=[MINH_KHAI, BA_DINH],
)
PHO = MenuItem(id="pho-bo", name="Phở bò", price=55000, unit="tô")

_CREATE_ARGS = {
    "customer_name": "Nguyễn Văn A",
    "phone_number": "0901234567",
    "booking_date": "2026-09-04",
    "booking_time": "18:30",
    "restaurant_id": "should-be-ignored",
    "branch_id": "should-be-ignored",
}


def _control_events(ws: FakeBridgeSocket) -> list[dict]:
    events = []
    for kind, data in ws.sent:
        if kind == "text":
            events.append(json.loads(data))
    return events


def _arm_delivery_order(pipeline: CallPipeline) -> None:
    pipeline.session.select_branch("mk")
    pipeline.session.menu = [PHO]
    pipeline.session.menu_ready = True
    pipeline.session.cart = [
        CartLine(menu_item_id="pho-bo", name="Phở bò", quantity=2, price=55000, unit="tô")
    ]
    pipeline.session.fulfillment = "delivery"
    pipeline.session.delivery_address = "12 Nguyễn Trãi"


async def test_greeting_does_not_fetch_menu() -> None:
    ws = FakeBridgeSocket()
    restaurant = FakeRestaurantClient(result=LONGWANG)
    orders = FakeOrderClient(menu=[PHO])
    pipeline, task = await _start_pipeline(
        ws,
        FakeSTT(),
        ScriptedLlm([]),
        ScriptedTts(),
        restaurant_client=restaurant,
        order_client=orders,
    )
    await _init(ws, pipeline, {**INIT, "toNumber": "1900636886"})
    assert orders.menu_lookups == []
    assert pipeline.session.menu_ready is False
    assert pipeline.session.selected_branch_id == "mk"
    await _stop(ws, task)


async def test_create_order_tool_speaks_sentence_not_payload() -> None:
    ws = FakeBridgeSocket()
    tts = ScriptedTts()
    restaurant = FakeRestaurantClient(result=LONGWANG)
    orders = FakeOrderClient(menu=[PHO])
    spoken = "Your pho order is in. Pay when it arrives."
    llm = ToolThenSpeakLlm("create_order", _CREATE_ARGS, [spoken])
    pipeline, task = await _start_pipeline(
        ws,
        FakeSTT(),
        llm,
        tts,
        restaurant_client=restaurant,
        matcher=ScriptedBranchMatcher(),
        order_client=orders,
        menu_matcher=ScriptedMenuMatcher(),
    )
    await _init(ws, pipeline, {**INIT, "toNumber": "+1900636886"})
    _arm_delivery_order(pipeline)
    await pipeline.on_transcript_completed("Yes, that's right.")
    deadline = asyncio.get_event_loop().time() + 1.0
    while spoken not in tts.spoken:
        if asyncio.get_event_loop().time() > deadline:
            break
        await asyncio.sleep(0.02)
    assert spoken in tts.spoken
    for line in tts.spoken:
        assert "should-be-ignored" not in line
        assert "create_order" not in line
        assert "pho-bo" not in line
        assert "restaurant_id" not in line
    assert llm.results
    tool_result = json.loads(llm.results[0])
    assert tool_result["ok"] is True
    assert len(orders.created) == 1
    assert orders.created[0]["booking_date"] == "2026-09-04"
    assert orders.created[0]["booking_time"] == "18:30"
    assert restaurant.created == []
    assert pipeline.session.order_created is True
    created_events = [e for e in _control_events(ws) if e.get("event") == "order.created"]
    assert len(created_events) == 1
    assert created_events[0]["fulfillment"] == "delivery"
    await _stop(ws, task)


async def test_ship_pho_does_not_post_booking() -> None:
    ws = FakeBridgeSocket()
    tts = ScriptedTts()
    restaurant = FakeRestaurantClient(result=LONGWANG)
    orders = FakeOrderClient(menu=[PHO])
    spoken = "Phở bò, shall I add one bowl?"
    llm = ToolThenSpeakLlm("search_menu", {"spoken_name": "phở bò"}, [spoken])
    matcher = ScriptedMenuMatcher(
        {
            "phở bò": MenuMatchResult(
                status="match",
                menu_item_id="pho-bo",
                confidence="high",
                confirm_name="Phở bò",
            )
        }
    )
    pipeline, task = await _start_pipeline(
        ws,
        FakeSTT(),
        llm,
        tts,
        restaurant_client=restaurant,
        matcher=ScriptedBranchMatcher(),
        order_client=orders,
        menu_matcher=matcher,
    )
    await _init(ws, pipeline, {**INIT, "toNumber": "1900636886"})
    await pipeline.on_transcript_completed("Ship cho mình phở bò.")
    deadline = asyncio.get_event_loop().time() + 1.0
    while spoken not in tts.spoken:
        if asyncio.get_event_loop().time() > deadline:
            break
        await asyncio.sleep(0.02)
    assert spoken in tts.spoken
    assert restaurant.created == []
    assert orders.created == []
    assert orders.menu_lookups == [("rest-1", "mk")]
    assert pipeline.session.intent == "order"
    assert pipeline.session.booking_created is False
    await _stop(ws, task)


async def test_hotline_confirm_branch_then_order_uses_locked_id() -> None:
    ws = FakeBridgeSocket()
    restaurant = FakeRestaurantClient(result=LONGWANG_TWO)
    orders = FakeOrderClient(menu=[PHO])
    pipeline, task = await _start_pipeline(
        ws,
        FakeSTT(),
        ScriptedLlm([]),
        ScriptedTts(),
        restaurant_client=restaurant,
        matcher=ScriptedBranchMatcher(),
        order_client=orders,
        menu_matcher=ScriptedMenuMatcher(
            {
                "phở bò": MenuMatchResult(
                    status="match",
                    menu_item_id="pho-bo",
                    confidence="high",
                    confirm_name="Phở bò",
                )
            }
        ),
    )
    await _init(ws, pipeline, {**INIT, "toNumber": "1900636886"})
    assert pipeline.session.selected_branch_id == ""
    assert [b.id for b in pipeline.session.branches] == ["mk", "bd"]

    search = json.loads(await pipeline._execute_tool("search_menu", json.dumps({"spoken_name": "phở bò"})))
    assert search["error"] == "no_branch"
    assert orders.menu_lookups == []

    confirm = json.loads(await pipeline._execute_tool("confirm_branch", json.dumps({"branch_id": "bd"})))
    assert confirm["ok"] is True
    assert pipeline.session.selected_branch_id == "bd"

    search = json.loads(await pipeline._execute_tool("search_menu", json.dumps({"spoken_name": "phở bò"})))
    assert search["status"] == "match"
    assert orders.menu_lookups == [("rest-1", "bd")]

    add = json.loads(
        await pipeline._execute_tool("add_to_cart", json.dumps({"menu_item_id": "pho-bo", "quantity": 1}))
    )
    assert add["ok"] is True
    set_f = json.loads(
        await pipeline._execute_tool(
            "set_fulfillment",
            json.dumps({"fulfillment": "pickup"}),
        )
    )
    assert set_f["ok"] is True
    created = json.loads(await pipeline._execute_tool("create_order", json.dumps(_CREATE_ARGS)))
    assert created["ok"] is True
    assert orders.created[0]["branch_id"] == "bd"
    assert orders.created[0]["restaurant_id"] == "rest-1"
    await _stop(ws, task)


async def test_booking_tool_does_not_post_order() -> None:
    ws = FakeBridgeSocket()
    tts = ScriptedTts()
    restaurant = FakeRestaurantClient(result=LONGWANG)
    orders = FakeOrderClient(menu=[PHO])
    spoken = "Your table at Minh Khai is booked for four."
    llm = ToolThenSpeakLlm(
        "create_booking",
        {
            "customer_name": "Nguyễn Văn A",
            "phone_number": "0123456789",
            "party_size": 4,
            "booking_date": "2026-08-28",
            "booking_time": "19:30",
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
        order_client=orders,
        menu_matcher=ScriptedMenuMatcher(),
    )
    await _init(ws, pipeline, {**INIT, "toNumber": "1900636886"})
    pipeline.session.select_branch("mk")
    await pipeline.on_transcript_completed("Yes, please book it.")
    deadline = asyncio.get_event_loop().time() + 1.0
    while spoken not in tts.spoken:
        if asyncio.get_event_loop().time() > deadline:
            break
        await asyncio.sleep(0.02)
    assert spoken in tts.spoken
    assert len(restaurant.created) == 1
    assert orders.created == []
    assert pipeline.session.booking_created is True
    assert pipeline.session.order_created is False
    await _stop(ws, task)


async def test_change_intent_before_checkout_does_not_post_abandoned_booking() -> None:
    ws = FakeBridgeSocket()
    restaurant = FakeRestaurantClient(result=LONGWANG)
    orders = FakeOrderClient(menu=[PHO])
    tts = ScriptedTts()
    spoken = "Okay, two bowls of pho to go."
    llm = ToolThenSpeakLlm(
        "add_to_cart",
        {"menu_item_id": "pho-bo", "quantity": 2},
        [spoken],
    )
    pipeline, task = await _start_pipeline(
        ws,
        FakeSTT(),
        llm,
        tts,
        restaurant_client=restaurant,
        matcher=ScriptedBranchMatcher(),
        order_client=orders,
        menu_matcher=ScriptedMenuMatcher(),
    )
    await _init(ws, pipeline, {**INIT, "toNumber": "1900636886"})
    pipeline.session.select_branch("mk")
    pipeline.session.intent = "booking"
    pipeline.session.refresh_system_prompt()
    await pipeline.on_transcript_completed("Thôi đặt bàn, ship phở về giúp.")
    deadline = asyncio.get_event_loop().time() + 1.0
    while spoken not in tts.spoken:
        if asyncio.get_event_loop().time() > deadline:
            break
        await asyncio.sleep(0.02)
    assert spoken in tts.spoken
    assert restaurant.created == []
    assert orders.created == []
    assert pipeline.session.intent == "order"
    assert pipeline.session.cart[0].quantity == 2
    assert pipeline.session.state == CallState.LISTENING
    await _stop(ws, task)


async def test_create_delivery_order_sends_success_event() -> None:
    ws = FakeBridgeSocket()
    restaurant = FakeRestaurantClient(result=LONGWANG)
    orders = FakeOrderClient(menu=[PHO])
    pipeline, task = await _start_pipeline(
        ws,
        FakeSTT(),
        ScriptedLlm([]),
        ScriptedTts(),
        restaurant_client=restaurant,
        matcher=ScriptedBranchMatcher(),
        order_client=orders,
        menu_matcher=ScriptedMenuMatcher(),
    )
    await _init(ws, pipeline, {**INIT, "toNumber": "1900636886", "locale": "vi"})
    _arm_delivery_order(pipeline)
    created = json.loads(await pipeline._execute_tool("create_order", json.dumps(_CREATE_ARGS)))
    assert created["ok"] is True
    events = [e for e in _control_events(ws) if e.get("event") == "order.created"]
    assert len(events) == 1
    event = events[0]
    assert event["message"] == "Đã đặt hàng thành công"
    assert event["fulfillment"] == "delivery"
    assert event["orderId"] == "ord-1"
    assert event["customerName"] == "Nguyễn Văn A"
    assert event["phoneNumber"] == "0901234567"
    assert event["deliveryAddress"] == "12 Nguyễn Trãi"
    assert event["bookingDate"] == "2026-09-04"
    assert event["bookingTime"] == "18:30"
    assert event["cart"][0]["name"] == "Phở bò"
    await _stop(ws, task)


async def test_failed_create_order_does_not_send_success_event() -> None:
    ws = FakeBridgeSocket()
    restaurant = FakeRestaurantClient(result=LONGWANG)
    orders = FakeOrderClient(menu=[PHO], order_error="http_400")
    pipeline, task = await _start_pipeline(
        ws,
        FakeSTT(),
        ScriptedLlm([]),
        ScriptedTts(),
        restaurant_client=restaurant,
        matcher=ScriptedBranchMatcher(),
        order_client=orders,
        menu_matcher=ScriptedMenuMatcher(),
    )
    await _init(ws, pipeline, {**INIT, "toNumber": "1900636886", "locale": "vi"})
    _arm_delivery_order(pipeline)
    created = json.loads(await pipeline._execute_tool("create_order", json.dumps(_CREATE_ARGS)))
    assert created["ok"] is False
    assert pipeline.session.order_created is False
    events = [e for e in _control_events(ws) if e.get("event") == "order.created"]
    assert events == []
    await _stop(ws, task)


async def test_create_order_does_not_resend_success_event() -> None:
    ws = FakeBridgeSocket()
    restaurant = FakeRestaurantClient(result=LONGWANG)
    orders = FakeOrderClient(menu=[PHO])
    pipeline, task = await _start_pipeline(
        ws,
        FakeSTT(),
        ScriptedLlm([]),
        ScriptedTts(),
        restaurant_client=restaurant,
        matcher=ScriptedBranchMatcher(),
        order_client=orders,
        menu_matcher=ScriptedMenuMatcher(),
    )
    await _init(ws, pipeline, {**INIT, "toNumber": "1900636886", "locale": "vi"})
    _arm_delivery_order(pipeline)
    first = json.loads(await pipeline._execute_tool("create_order", json.dumps(_CREATE_ARGS)))
    second = json.loads(await pipeline._execute_tool("create_order", json.dumps(_CREATE_ARGS)))
    assert first["ok"] is True
    assert second["already_created"] is True
    events = [e for e in _control_events(ws) if e.get("event") == "order.created"]
    assert len(events) == 1
    await _stop(ws, task)
