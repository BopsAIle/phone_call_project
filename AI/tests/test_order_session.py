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


async def test_greeting_preloads_menu_to_bias_stt() -> None:
    """The menu must reach STT as keywords BEFORE the caller names a dish.

    search_menu would only load it a turn later — by then the dish name has
    already been transcribed, badly.
    """
    ws = FakeBridgeSocket()
    restaurant = FakeRestaurantClient(result=LONGWANG)
    orders = FakeOrderClient(menu=[PHO])
    stt = FakeSTT()
    pipeline, task = await _start_pipeline(
        ws,
        stt,
        ScriptedLlm([]),
        ScriptedTts(),
        restaurant_client=restaurant,
        order_client=orders,
    )
    await _init(ws, pipeline, {**INIT, "toNumber": "1900636886"})
    assert orders.menu_lookups == [("rest-1", "mk")]
    assert pipeline.session.menu_ready is True
    assert pipeline.session.selected_branch_id == "mk"
    assert PHO.name in stt.keywords
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
    assert event["message"] == "Order placed successfully"
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


# --- A2: barge-in đúng lúc tạo đơn không được làm hỏng sổ hội thoại ---


class SlowOrderClient(FakeOrderClient):
    """create_order treo cho tới khi test thả ra, để barge-in rơi vào giữa POST."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def create_order(self, body: dict):
        self.entered.set()
        await self.release.wait()
        return await super().create_order(body)


async def test_barge_in_during_create_order_keeps_history_valid() -> None:
    """Lỗi cũ: câu AI vừa nói chen vào giữa lệnh gọi tool và kết quả tool.

    OpenAI từ chối nguyên request khi thấy hình dạng đó, và vì sổ hội thoại không bao
    giờ được sửa lại nên MỌI lượt sau đều lỗi — khách nghe câu xin lỗi lặp vô tận.
    """
    from llm.history import is_well_formed
    from llm.stream import OpenAiLlm
    from tests.fakes import FakeChatCompletions, LlmRound

    ws = FakeBridgeSocket()
    restaurant = FakeRestaurantClient(result=LONGWANG)
    orders = SlowOrderClient(menu=[PHO])
    client = FakeChatCompletions(
        [
            # Nói xong rồi gọi tool NGAY TRONG CÙNG một vòng — đây mới là hình dạng
            # sinh ra lỗi: câu đã phát ra loa trước khi tool kịp trả kết quả.
            LlmRound(
                text="Dạ em đang lên đơn cho mình.",
                tools=[("call_1", "create_order", json.dumps(_CREATE_ARGS))],
            ),
            LlmRound(text="Đơn của mình đã xong."),
        ]
    )
    pipeline, task = await _start_pipeline(
        ws,
        FakeSTT(),
        OpenAiLlm(client, "gpt-4o-mini"),
        ScriptedTts(),
        restaurant_client=restaurant,
        order_client=orders,
        menu_matcher=ScriptedMenuMatcher(),
        matcher=ScriptedBranchMatcher(),
    )
    await _init(ws, pipeline, {**INIT, "toNumber": "1900636886"})
    _arm_delivery_order(pipeline)

    await pipeline.on_transcript_completed("chốt đơn giúp em")
    await asyncio.wait_for(orders.entered.wait(), timeout=2)

    # Khách nói chen vào đúng lúc POST đang bay. barge-in cố ý CHỜ tool tạo đơn xong
    # (không huỷ), nên phải thả POST song song chứ không sau — đúng như đời thật.
    barge = asyncio.create_task(pipeline.on_speech_started())
    await asyncio.sleep(0.02)
    orders.release.set()
    await asyncio.wait_for(barge, timeout=2)
    await asyncio.sleep(0.05)

    history = pipeline.session.history
    assert is_well_formed(history), [m.get("role") for m in history]
    roles = [m.get("role") for m in history]
    call_at = roles.index("assistant", roles.index("user"))
    while history[call_at].get("tool_calls") is None:
        call_at = roles.index("assistant", call_at + 1)
    assert roles[call_at + 1] == "tool"
    assert history[call_at + 1]["tool_call_id"] == "call_1"
    # Đơn vẫn được tạo: barge-in dừng tiếng, không huỷ POST đã bay
    assert len(orders.created) == 1
    await _stop(ws, task)


async def test_next_turn_after_barge_in_create_still_works() -> None:
    """Hệ quả thật sự của lỗi cũ: lượt kế tiếp phải chạy bình thường."""
    from llm.stream import OpenAiLlm
    from tests.fakes import FakeChatCompletions, LlmRound

    ws = FakeBridgeSocket()
    restaurant = FakeRestaurantClient(result=LONGWANG)
    orders = SlowOrderClient(menu=[PHO])
    client = FakeChatCompletions(
        [
            LlmRound(
                text="Dạ em đang lên đơn cho mình.",
                tools=[("call_1", "create_order", json.dumps(_CREATE_ARGS))],
            ),
            LlmRound(text="Đơn của mình đã xong rồi ạ."),
        ]
    )
    tts = ScriptedTts()
    pipeline, task = await _start_pipeline(
        ws,
        FakeSTT(),
        OpenAiLlm(client, "gpt-4o-mini"),
        tts,
        restaurant_client=restaurant,
        order_client=orders,
        menu_matcher=ScriptedMenuMatcher(),
        matcher=ScriptedBranchMatcher(),
    )
    await _init(ws, pipeline, {**INIT, "toNumber": "1900636886"})
    _arm_delivery_order(pipeline)

    await pipeline.on_transcript_completed("chốt đơn giúp em")
    await asyncio.wait_for(orders.entered.wait(), timeout=2)
    barge = asyncio.create_task(pipeline.on_speech_started())
    await asyncio.sleep(0.02)
    orders.release.set()
    await asyncio.wait_for(barge, timeout=2)
    await asyncio.sleep(0.05)

    await pipeline.on_transcript_completed("bao lâu thì tới ạ")
    await asyncio.sleep(0.05)

    # Lượt sau nói được, và lịch sử gửi lên API ở lượt đó đúng hình dạng
    assert "Đơn của mình đã xong rồi ạ." in tts.spoken
    last_request = client.requests[-1]["messages"]
    for index, message in enumerate(last_request):
        if message.get("role") == "assistant" and message.get("tool_calls"):
            assert last_request[index + 1]["role"] == "tool"
    await _stop(ws, task)
