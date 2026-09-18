from __future__ import annotations

import json

from booking.models import Branch, Restaurant
from bridge.session import CallSession
from order.matcher import ScriptedMenuMatcher, coerce_menu_match
from order.models import CartLine, MenuItem, MenuMatchResult
from order.tools import OrderTools
from tests.fakes import FakeOrderClient

MINH_KHAI = Branch(id="mk", name="Chi nhánh Minh Khai", address="Minh Khai, Hà Nội")
BA_DINH = Branch(id="bd", name="Chi nhánh Ba Đình", address="Ba Đình, Hà Nội")
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
TRA_DAO = MenuItem(id="tra-dao", name="Trà đào", price=35000, unit="ly")
SOLD_OUT = MenuItem(id="bun-cha", name="Bún chả", price=60000, available=False)

_PHO_MATCH = MenuMatchResult(
    status="match",
    menu_item_id="pho-bo",
    confidence="high",
    confirm_name="Phở bò",
)

_CREATE_ARGS = {
    "customer_name": "Nguyễn Văn A",
    "phone_number": "0901234567",
    "booking_date": "2026-09-04",
    "booking_time": "18:30",
}


def _session_ready() -> CallSession:
    session = CallSession()
    session.apply_restaurant(LONGWANG)
    session.catalog_ready = True
    session.select_branch("mk")
    return session


def test_coerce_hallucinated_menu_id_is_none() -> None:
    result = coerce_menu_match(
        {"status": "match", "menu_item_id": "not-on-menu", "confidence": "high"},
        [PHO, TRA_DAO],
    )
    assert result.status == "none"
    assert result.menu_item_id == ""


def test_coerce_pho_match() -> None:
    result = coerce_menu_match(
        {"status": "match", "menu_item_id": "pho-bo", "confidence": "high", "confirm_name": "Phở bò"},
        [PHO, TRA_DAO],
    )
    assert result.status == "match"
    assert result.menu_item_id == "pho-bo"


async def test_search_menu_unknown_does_not_invent() -> None:
    session = _session_ready()
    client = FakeOrderClient(menu=[PHO, TRA_DAO])
    tools = OrderTools(session, client, ScriptedMenuMatcher())
    payload = json.loads(await tools.execute("search_menu", json.dumps({"spoken_name": "pizza"})))
    assert payload["status"] == "none"
    assert payload.get("menu_item_id") is None
    assert session.intent == "order"
    assert session.menu_ready is True
    assert client.created == []


async def test_search_menu_returns_catalog_name() -> None:
    session = _session_ready()
    client = FakeOrderClient(menu=[PHO, TRA_DAO])
    matcher = ScriptedMenuMatcher({"phở bò": _PHO_MATCH})
    tools = OrderTools(session, client, matcher)
    payload = json.loads(await tools.execute("search_menu", json.dumps({"spoken_name": "phở bò"})))
    assert payload["status"] == "match"
    assert payload["confirm_name"] == "Phở bò"
    assert payload["menu_item_id"] == "pho-bo"
    assert payload["available"] is True
    assert session.cart == []


async def test_search_menu_requires_branch_when_multiple() -> None:
    session = CallSession()
    session.apply_restaurant(LONGWANG_TWO)
    session.catalog_ready = True
    client = FakeOrderClient(menu=[PHO])
    tools = OrderTools(session, client, ScriptedMenuMatcher())
    payload = json.loads(await tools.execute("search_menu", json.dumps({"spoken_name": "phở bò"})))
    assert payload["ok"] is False
    assert payload["error"] == "no_branch"
    names = {row["name"] for row in payload["available_branches"]}
    assert names == {"Chi nhánh Minh Khai", "Chi nhánh Ba Đình"}
    assert all("id" not in row or row.get("branch_id") for row in payload["available_branches"])
    assert all("address" not in row for row in payload["available_branches"])
    assert client.menu_lookups == []
    assert session.menu_ready is False


async def test_search_menu_autolocks_sole_branch() -> None:
    session = CallSession()
    session.apply_restaurant(LONGWANG)
    session.catalog_ready = True
    client = FakeOrderClient(menu=[PHO])
    matcher = ScriptedMenuMatcher({"phở bò": _PHO_MATCH})
    tools = OrderTools(session, client, matcher)
    payload = json.loads(await tools.execute("search_menu", json.dumps({"spoken_name": "phở bò"})))
    assert payload["status"] == "match"
    assert session.selected_branch_id == "mk"
    assert client.menu_lookups == [("rest-1", "mk")]


async def test_list_menu_gets_locked_branch_menu() -> None:
    session = _session_ready()
    client = FakeOrderClient(menu=[PHO, TRA_DAO])
    tools = OrderTools(session, client, ScriptedMenuMatcher())
    payload = json.loads(await tools.execute("list_menu", "{}"))
    assert payload["ok"] is True
    assert payload["status"] == "browse"
    assert payload["branch_name"] == "Chi nhánh Minh Khai"
    assert payload["count"] == 2
    assert [row["name"] for row in payload["items"]] == ["Phở bò", "Trà đào"]
    assert client.menu_lookups == [("rest-1", "mk")]
    assert session.menu_ready is True
    assert session.intent == "order"


async def test_list_menu_gets_hcm_branch_after_lock() -> None:
    hcm = Branch(id="hcm", name="Chi nhánh HCM", address="Nguyễn Huệ, HCM")
    session = CallSession()
    session.apply_restaurant(
        Restaurant(
            id="rest-1",
            name="Nhà hàng LongWang",
            phone="1900636886",
            branches=[MINH_KHAI, hcm],
        )
    )
    session.catalog_ready = True
    session.select_branch("hcm")
    client = FakeOrderClient(menu=[PHO, TRA_DAO])
    tools = OrderTools(session, client, ScriptedMenuMatcher())
    payload = json.loads(await tools.execute("list_menu", "{}"))
    assert payload["ok"] is True
    assert payload["branch_name"] == "Chi nhánh HCM"
    assert [row["name"] for row in payload["items"]] == ["Phở bò", "Trà đào"]
    assert client.menu_lookups == [("rest-1", "hcm")]
    assert "address" not in payload
    session = CallSession()
    session.apply_restaurant(LONGWANG_TWO)
    session.catalog_ready = True
    client = FakeOrderClient(menu=[PHO])
    tools = OrderTools(session, client, ScriptedMenuMatcher())
    payload = json.loads(await tools.execute("list_menu", "{}"))
    assert payload["ok"] is False
    assert payload["error"] == "no_branch"
    assert client.menu_lookups == []


async def test_search_menu_browse_phrase_lists_locked_branch() -> None:
    session = _session_ready()
    client = FakeOrderClient(menu=[PHO, TRA_DAO])
    tools = OrderTools(session, client, ScriptedMenuMatcher())
    payload = json.loads(
        await tools.execute(
            "search_menu",
            json.dumps({"spoken_name": "chi nhánh HCM có những món gì"}),
        )
    )
    assert payload["status"] == "browse"
    assert [row["name"] for row in payload["items"]] == ["Phở bò", "Trà đào"]
    assert client.menu_lookups == [("rest-1", "mk")]


async def test_add_to_cart_rejects_unknown_id() -> None:
    session = _session_ready()
    client = FakeOrderClient(menu=[PHO])
    tools = OrderTools(session, client, ScriptedMenuMatcher())
    payload = json.loads(
        await tools.execute("add_to_cart", json.dumps({"menu_item_id": "invented", "quantity": 1}))
    )
    assert payload["ok"] is False
    assert payload["error"] == "unknown_item"
    assert "search_menu" in payload["next_step"]
    assert session.cart == []


async def test_add_to_cart_recovers_invented_id_from_name() -> None:
    """Models pass a slug of the dish name instead of calling search_menu first."""
    session = _session_ready()
    client = FakeOrderClient(menu=[PHO])
    tools = OrderTools(session, client, ScriptedMenuMatcher())
    slug = PHO.name.lower().replace(" ", "-")
    payload = json.loads(
        await tools.execute("add_to_cart", json.dumps({"menu_item_id": slug, "quantity": 2}))
    )
    assert payload["ok"] is True
    assert [(line.menu_item_id, line.quantity) for line in session.cart] == [(PHO.id, 2)]


async def test_add_to_cart_rejects_unavailable() -> None:
    session = _session_ready()
    client = FakeOrderClient(menu=[SOLD_OUT])
    tools = OrderTools(session, client, ScriptedMenuMatcher())
    payload = json.loads(
        await tools.execute("add_to_cart", json.dumps({"menu_item_id": "bun-cha", "quantity": 1}))
    )
    assert payload["ok"] is False
    assert payload["error"] == "unavailable"
    assert session.cart == []


async def test_add_to_cart_merges_same_item_and_note() -> None:
    session = _session_ready()
    client = FakeOrderClient(menu=[PHO])
    tools = OrderTools(session, client, ScriptedMenuMatcher())
    await tools.execute("add_to_cart", json.dumps({"menu_item_id": "pho-bo", "quantity": 1, "note": "ít cay"}))
    payload = json.loads(
        await tools.execute("add_to_cart", json.dumps({"menu_item_id": "pho-bo", "quantity": 2, "note": "ít cay"}))
    )
    assert payload["ok"] is True
    assert len(session.cart) == 1
    assert session.cart[0].quantity == 3
    assert payload["total"] == 165000


async def test_set_fulfillment_delivery_requires_address() -> None:
    session = _session_ready()
    tools = OrderTools(session, FakeOrderClient(menu=[PHO]), ScriptedMenuMatcher())
    payload = json.loads(await tools.execute("set_fulfillment", json.dumps({"fulfillment": "delivery"})))
    assert payload == {"ok": False, "error": "no_delivery_address"}


async def test_set_fulfillment_pickup_requires_branch() -> None:
    session = CallSession()
    session.apply_restaurant(LONGWANG_TWO)
    tools = OrderTools(session, FakeOrderClient(menu=[PHO]), ScriptedMenuMatcher())
    payload = json.loads(await tools.execute("set_fulfillment", json.dumps({"fulfillment": "pickup"})))
    assert payload == {"ok": False, "error": "no_branch"}


async def test_create_order_uses_ram_ids_not_llm_args() -> None:
    session = _session_ready()
    client = FakeOrderClient(menu=[PHO])
    tools = OrderTools(session, client, ScriptedMenuMatcher())
    await tools.execute("add_to_cart", json.dumps({"menu_item_id": "pho-bo", "quantity": 2, "note": "ít cay"}))
    await tools.execute(
        "set_fulfillment",
        json.dumps({"fulfillment": "delivery", "delivery_address": "12 Nguyễn Trãi"}),
    )
    payload = json.loads(
        await tools.execute(
            "create_order",
            json.dumps(
                {
                    **_CREATE_ARGS,
                    "restaurant_id": "hallucinated-rest",
                    "branch_id": "hallucinated-branch",
                    "items": [{"menu_item_id": "invented", "quantity": 99}],
                    "note": "gọi cửa",
                }
            ),
        )
    )
    assert payload["ok"] is True
    assert payload["payment"] == "cod"
    assert payload["booking_date"] == "2026-09-04"
    assert payload["booking_time"] == "18:30"
    assert len(client.created) == 1
    body = client.created[0]
    assert body["restaurant_id"] == "rest-1"
    assert body["branch_id"] == "mk"
    assert body["fulfillment"] == "delivery"
    assert body["delivery_address"] == "12 Nguyễn Trãi"
    assert body["booking_date"] == "2026-09-04"
    assert body["booking_time"] == "18:30"
    assert body["items"] == [{"menu_item_id": "pho-bo", "quantity": 2}]
    assert body["note"] == "gọi cửa; ít cay"
    assert session.order_created is True
    assert payload["order_id"] == "ord-1"


async def test_create_order_missing_date_time() -> None:
    session = _session_ready()
    client = FakeOrderClient(menu=[PHO])
    tools = OrderTools(session, client, ScriptedMenuMatcher())
    await tools.execute("add_to_cart", json.dumps({"menu_item_id": "pho-bo", "quantity": 1}))
    await tools.execute("set_fulfillment", json.dumps({"fulfillment": "pickup"}))
    payload = json.loads(
        await tools.execute(
            "create_order",
            json.dumps({"customer_name": "A", "phone_number": "0901234567"}),
        )
    )
    assert payload["ok"] is False
    assert payload["error"] == "missing_fields"
    assert payload["fields"] == ["booking_date", "booking_time"]
    assert client.created == []


async def test_create_order_rejects_delivery_without_address() -> None:
    session = _session_ready()
    client = FakeOrderClient(menu=[PHO])
    tools = OrderTools(session, client, ScriptedMenuMatcher())
    await tools.execute("add_to_cart", json.dumps({"menu_item_id": "pho-bo", "quantity": 1}))
    session.fulfillment = "delivery"
    session.delivery_address = ""
    payload = json.loads(
        await tools.execute(
            "create_order",
            json.dumps(_CREATE_ARGS),
        )
    )
    assert payload == {"ok": False, "error": "no_delivery_address"}
    assert client.created == []


async def test_create_order_rejects_empty_cart() -> None:
    session = _session_ready()
    client = FakeOrderClient(menu=[PHO])
    tools = OrderTools(session, client, ScriptedMenuMatcher())
    await tools.execute(
        "set_fulfillment",
        json.dumps({"fulfillment": "pickup"}),
    )
    payload = json.loads(
        await tools.execute(
            "create_order",
            json.dumps(_CREATE_ARGS),
        )
    )
    assert payload == {"ok": False, "error": "empty_cart"}
    assert client.created == []


async def test_create_order_idempotent() -> None:
    session = _session_ready()
    client = FakeOrderClient(menu=[PHO])
    tools = OrderTools(session, client, ScriptedMenuMatcher())
    await tools.execute("add_to_cart", json.dumps({"menu_item_id": "pho-bo", "quantity": 1}))
    await tools.execute("set_fulfillment", json.dumps({"fulfillment": "pickup"}))
    args = json.dumps(_CREATE_ARGS)
    first = json.loads(await tools.execute("create_order", args))
    second = json.loads(await tools.execute("create_order", args))
    assert first["ok"] is True
    assert second == {
        "ok": True,
        "already_created": True,
        "branch_name": "Chi nhánh Minh Khai",
    }
    assert len(client.created) == 1


async def test_save_order_details_fills_slots_and_ask_next() -> None:
    session = _session_ready()
    tools = OrderTools(session, FakeOrderClient(menu=[PHO]), ScriptedMenuMatcher())
    payload = json.loads(
        await tools.execute("save_order_details", json.dumps({"customer_name": "Nguyễn Văn A"}))
    )
    assert payload["ok"] is True
    assert payload["customer_name"] == "Nguyễn Văn A"
    assert payload["ask_next"] == "ask what they would like to order"
    assert "items" in payload["missing"]
    assert session.order_customer_name == "Nguyễn Văn A"


async def test_save_order_details_rejects_invalid_date() -> None:
    session = _session_ready()
    tools = OrderTools(session, FakeOrderClient(menu=[PHO]), ScriptedMenuMatcher())
    payload = json.loads(
        await tools.execute("save_order_details", json.dumps({"booking_date": "not-a-date"}))
    )
    assert payload["ok"] is False
    assert payload["error"] == "invalid_fields"
    assert payload["fields"] == ["booking_date"]
    assert session.order_booking_date == ""


async def test_save_order_details_accepts_tomorrow() -> None:
    from datetime import datetime, timedelta, timezone as dt_timezone

    session = _session_ready()
    session.timezone = "UTC"
    tools = OrderTools(session, FakeOrderClient(menu=[PHO]), ScriptedMenuMatcher())
    payload = json.loads(
        await tools.execute("save_order_details", json.dumps({"booking_date": "tomorrow"}))
    )
    expected = (datetime.now(dt_timezone.utc).date() + timedelta(days=1)).isoformat()
    assert payload["ok"] is True
    assert payload["booking_date"] == expected
    assert session.order_booking_date == expected


async def test_create_order_uses_saved_details_from_session() -> None:
    session = _session_ready()
    client = FakeOrderClient(menu=[PHO])
    tools = OrderTools(session, client, ScriptedMenuMatcher())
    await tools.execute("add_to_cart", json.dumps({"menu_item_id": "pho-bo", "quantity": 1}))
    await tools.execute("set_fulfillment", json.dumps({"fulfillment": "pickup"}))
    await tools.execute("save_order_details", json.dumps(_CREATE_ARGS))
    payload = json.loads(await tools.execute("create_order", "{}"))
    assert payload["ok"] is True
    assert client.created[0]["customer_name"] == "Nguyễn Văn A"
    assert client.created[0]["customer_phone"] == "0901234567"
    assert client.created[0]["booking_date"] == "2026-09-04"
    assert client.created[0]["booking_time"] == "18:30"


async def test_create_order_sends_distinct_delivery_phone() -> None:
    session = _session_ready()
    client = FakeOrderClient(menu=[PHO])
    tools = OrderTools(session, client, ScriptedMenuMatcher())
    await tools.execute("add_to_cart", json.dumps({"menu_item_id": "pho-bo", "quantity": 1}))
    await tools.execute(
        "set_fulfillment",
        json.dumps(
            {
                "fulfillment": "delivery",
                "delivery_address": "12 Nguyễn Trãi",
                "delivery_phone": "0987654321",
            }
        ),
    )
    payload = json.loads(await tools.execute("create_order", json.dumps(_CREATE_ARGS)))
    assert payload["ok"] is True
    assert payload["delivery_phone"] == "0987654321"
    body = client.created[0]
    assert body["customer_phone"] == "0901234567"
    assert body["delivery_phone"] == "0987654321"
    assert body["delivery_address"] == "12 Nguyễn Trãi"


def test_select_branch_resets_menu_and_cart() -> None:
    session = CallSession()
    session.apply_restaurant(LONGWANG_TWO)
    session.select_branch("mk")
    session.menu = [PHO]
    session.menu_ready = True
    session.cart = [CartLine(menu_item_id="pho-bo", name="Phở bò", quantity=1)]
    session.select_branch("bd")
    assert session.selected_branch_id == "bd"
    assert session.menu == []
    assert session.menu_ready is False
    assert session.cart == []


# --- giỏ hàng: update_cart / remove_from_cart (trước đây không có test nào) ---


async def _cart_with_two_pho_lines() -> tuple[CallSession, OrderTools]:
    """Cùng một món trên hai dòng, khác ghi chú — chỉ có thể dựng qua add_to_cart."""
    session = _session_ready()
    client = FakeOrderClient(menu=[PHO])
    tools = OrderTools(session, client, ScriptedMenuMatcher())
    await tools.execute(
        "add_to_cart", json.dumps({"menu_item_id": "pho-bo", "quantity": 1, "note": "ít cay"})
    )
    await tools.execute(
        "add_to_cart", json.dumps({"menu_item_id": "pho-bo", "quantity": 1, "note": "nhiều hành"})
    )
    assert len(session.cart) == 2
    return session, tools


async def test_update_cart_single_line_without_note() -> None:
    session = _session_ready()
    client = FakeOrderClient(menu=[PHO])
    tools = OrderTools(session, client, ScriptedMenuMatcher())
    await tools.execute("add_to_cart", json.dumps({"menu_item_id": "pho-bo", "quantity": 1}))
    payload = json.loads(
        await tools.execute("update_cart", json.dumps({"menu_item_id": "pho-bo", "quantity": 3}))
    )
    assert payload["ok"] is True
    assert session.cart[0].quantity == 3


async def test_update_cart_ambiguous_line_asks_instead_of_crashing() -> None:
    session, tools = await _cart_with_two_pho_lines()
    payload = json.loads(
        await tools.execute("update_cart", json.dumps({"menu_item_id": "pho-bo", "quantity": 3}))
    )
    assert payload["ok"] is False
    assert payload["error"] == "ambiguous_line"
    assert len(payload["lines"]) == 2
    assert {row.get("note") for row in payload["lines"]} == {"ít cay", "nhiều hành"}
    assert [line.quantity for line in session.cart] == [1, 1]


async def test_update_cart_with_note_picks_the_right_line() -> None:
    session, tools = await _cart_with_two_pho_lines()
    payload = json.loads(
        await tools.execute(
            "update_cart",
            json.dumps({"menu_item_id": "pho-bo", "quantity": 5, "note": "nhiều hành"}),
        )
    )
    assert payload["ok"] is True
    by_note = {line.note: line.quantity for line in session.cart}
    assert by_note == {"ít cay": 1, "nhiều hành": 5}


async def test_update_cart_not_in_cart() -> None:
    session = _session_ready()
    tools = OrderTools(session, FakeOrderClient(menu=[PHO]), ScriptedMenuMatcher())
    payload = json.loads(
        await tools.execute("update_cart", json.dumps({"menu_item_id": "pho-bo", "quantity": 2}))
    )
    assert payload == {"ok": False, "error": "not_in_cart"}


async def test_update_cart_rejects_bad_quantity() -> None:
    session = _session_ready()
    tools = OrderTools(session, FakeOrderClient(menu=[PHO]), ScriptedMenuMatcher())
    for bad in (0, 51, "hai", None):
        payload = json.loads(
            await tools.execute(
                "update_cart", json.dumps({"menu_item_id": "pho-bo", "quantity": bad})
            )
        )
        assert payload == {"ok": False, "error": "invalid_quantity"}, bad


async def test_remove_from_cart_without_note_removes_every_line() -> None:
    session, tools = await _cart_with_two_pho_lines()
    payload = json.loads(
        await tools.execute("remove_from_cart", json.dumps({"menu_item_id": "pho-bo"}))
    )
    assert payload["ok"] is True
    assert session.cart == []


async def test_remove_from_cart_with_note_removes_one_line() -> None:
    session, tools = await _cart_with_two_pho_lines()
    payload = json.loads(
        await tools.execute(
            "remove_from_cart", json.dumps({"menu_item_id": "pho-bo", "note": "ít cay"})
        )
    )
    assert payload["ok"] is True
    assert [line.note for line in session.cart] == ["nhiều hành"]


# --- create_order phải dùng kết quả kiểm tra của _apply_order_details ---


async def _cart_ready_for_pickup() -> tuple[CallSession, FakeOrderClient, OrderTools]:
    session = _session_ready()
    client = FakeOrderClient(menu=[PHO])
    tools = OrderTools(session, client, ScriptedMenuMatcher())
    await tools.execute("add_to_cart", json.dumps({"menu_item_id": "pho-bo", "quantity": 1}))
    await tools.execute("set_fulfillment", json.dumps({"fulfillment": "pickup"}))
    return session, client, tools


async def test_create_order_rejects_short_phone_without_posting() -> None:
    session, client, tools = await _cart_ready_for_pickup()
    payload = json.loads(
        await tools.execute("create_order", json.dumps({**_CREATE_ARGS, "phone_number": "5"}))
    )
    assert payload["ok"] is False
    assert payload["error"] == "invalid_fields"
    assert payload["fields"] == ["phone_number"]
    assert client.created == []
    assert session.order_created is False


async def test_create_order_rejects_unparseable_date_without_posting() -> None:
    session, client, tools = await _cart_ready_for_pickup()
    payload = json.loads(
        await tools.execute(
            "create_order", json.dumps({**_CREATE_ARGS, "booking_date": "thứ ba tuần sau"})
        )
    )
    assert payload["ok"] is False
    assert payload["error"] == "invalid_fields"
    assert "booking_date" in payload["fields"]
    assert client.created == []


async def test_create_order_keeps_valid_args_when_another_is_invalid() -> None:
    """Trường hợp lệ vẫn được lưu — khách không phải đọc lại từ đầu."""
    session, client, tools = await _cart_ready_for_pickup()
    await tools.execute(
        "create_order",
        json.dumps({**_CREATE_ARGS, "customer_name": "Trần Thị B", "phone_number": "5"}),
    )
    assert session.order_customer_name == "Trần Thị B"
    assert client.created == []


async def test_create_order_falls_back_to_stored_phone_when_caller_id_missing() -> None:
    session, client, tools = await _cart_ready_for_pickup()
    session.from_number = ""
    await tools.execute("save_order_details", json.dumps({"phone_number": "0901234567"}))
    payload = json.loads(
        await tools.execute(
            "create_order", json.dumps({**_CREATE_ARGS, "use_caller_number": True})
        )
    )
    assert payload["ok"] is True, payload
    assert client.created[0]["customer_phone"] == "0901234567"


async def test_create_order_still_posts_when_everything_is_valid() -> None:
    session, client, tools = await _cart_ready_for_pickup()
    payload = json.loads(await tools.execute("create_order", json.dumps(_CREATE_ARGS)))
    assert payload["ok"] is True
    assert len(client.created) == 1
