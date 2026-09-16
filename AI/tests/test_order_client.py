from __future__ import annotations

import json

import httpx

from order.client import OrderClient, menu_item_from_api, parse_menu_items
from order.models import MenuResult


def test_menu_item_defaults_missing_fields() -> None:
    item = menu_item_from_api({"id": "pho-bo", "name": "Phở bò"})
    assert item is not None
    assert item.id == "pho-bo"
    assert item.name == "Phở bò"
    assert item.price is None
    assert item.currency == "VND"
    assert item.available is True
    assert item.unit == ""


def test_menu_item_unavailable_and_price() -> None:
    item = menu_item_from_api(
        {
            "id": "bun",
            "name": "Bún chả",
            "price": "60000",
            "available": False,
            "unit": "đĩa",
            "currency": "VND",
        }
    )
    assert item is not None
    assert item.price == 60000
    assert item.available is False
    assert item.unit == "đĩa"


def test_menu_item_status_and_quantity_available() -> None:
    sold = menu_item_from_api(
        {"id": "bun", "name": "Bún chả", "status": "sold_out", "quantity_available": 3}
    )
    assert sold is not None and sold.available is False
    empty = menu_item_from_api(
        {"id": "pho", "name": "Phở bò", "status": "available", "quantity_available": 0}
    )
    assert empty is not None and empty.available is False
    ok = menu_item_from_api(
        {"id": "tra", "name": "Trà đào", "status": "available", "quantity_available": 8}
    )
    assert ok is not None and ok.available is True
    unavailable = menu_item_from_api(
        {"id": "com", "name": "Cơm", "status": "unavailable"}
    )
    assert unavailable is not None and unavailable.available is False


def test_menu_item_requires_id_and_name() -> None:
    assert menu_item_from_api({"name": "Phở"}) is None
    assert menu_item_from_api({"id": "x"}) is None


def test_parse_menu_unwraps_items_envelope() -> None:
    items = parse_menu_items(
        {
            "success": True,
            "data": {
                "items": [
                    {"id": "pho-bo", "name": "Phở bò", "price": 55000},
                    {"id": "", "name": "Skip"},
                ]
            },
        }
    )
    assert [row.id for row in items] == ["pho-bo"]


async def test_get_menu_uses_branch_path() -> None:
    captured: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(str(request.url.path))
        assert request.url.path.endswith("/menu/branch/mk")
        assert not request.url.params
        return httpx.Response(
            200,
            json={"success": True, "data": [{"id": "pho-bo", "name": "Phở bò", "price": 55000}]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = OrderClient("https://example.test", http=http)
        result = await client.get_menu("rest-1", "mk")
    assert result.ok is True
    assert [item.id for item in result.items] == ["pho-bo"]
    assert captured == ["/menu/branch/mk"]


async def test_get_menu_404_does_not_fallback() -> None:
    captured: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(str(request.url.path))
        return httpx.Response(404, json={"message": "not found"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = OrderClient("https://example.test", http=http)
        result = await client.get_menu("rest-1", "mk")
    assert result.ok is False
    assert result.error == "not found"
    assert captured == ["/menu/branch/mk"]


async def test_get_menu_network_does_not_fallback() -> None:
    captured: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(str(request.url.path))
        raise httpx.ConnectError("down")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = OrderClient("https://example.test", http=http)
        result = await client.get_menu("rest-1", "mk")
    assert result.ok is False
    assert result.error == "network"
    assert captured == ["/menu/branch/mk"]


async def test_get_menu_missing_branch_skips_http() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected HTTP {request.method} {request.url}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = OrderClient("https://example.test", http=http)
        result = await client.get_menu("rest-1", "")
    assert result == MenuResult(ok=False, error="no_branch")


async def test_create_order_posts_delivery_dto() -> None:
    captured: list[tuple[str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append((str(request.url.path), json.loads(request.content)))
        if request.url.path.endswith("/menu/delivery/ai"):
            return httpx.Response(201, json={"success": True, "data": {"id": "ord-1"}})
        raise AssertionError(f"unexpected HTTP {request.method} {request.url}")

    body = {
        "restaurant_id": "rest-1",
        "branch_id": "mk",
        "fulfillment": "delivery",
        "customer_name": "Sam",
        "phone_number": "0901234567",
        "delivery_address": "12 Nguyen Trai",
        "booking_date": "2026-09-04",
        "booking_time": "18:30",
        "note": "gọi cửa",
        "items": [{"menu_item_id": "pho-bo", "quantity": 2, "note": "it cay"}],
    }
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = OrderClient("https://example.test", http=http)
        result = await client.create_order(body)
    assert result.ok is True
    assert result.data["id"] == "ord-1"
    assert len(captured) == 1
    path, sent = captured[0]
    assert path.endswith("/menu/delivery/ai")
    assert sent == {
        "restaurant_id": "rest-1",
        "branch_id": "mk",
        "customer_name": "Sam",
        "customer_phone": "0901234567",
        "booking_date": "2026-09-04",
        "booking_time": "18:30",
        "items": [{"menu_item_id": "pho-bo", "quantity": 2}],
        "note": "gọi cửa; it cay",
        "delivery_address": "12 Nguyen Trai",
        "delivery_phone": "0901234567",
        "delivery_fee": 0,
        "estimated_delivery_time": "18:30",
    }
    assert "fulfillment" not in sent
    assert "source" not in sent


async def test_create_order_posts_pickup_to_takeout() -> None:
    captured: list[tuple[str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append((str(request.url.path), json.loads(request.content)))
        assert request.url.path.endswith("/menu/takeout/ai")
        return httpx.Response(201, json={"success": True, "data": {"id": "ord-2"}})

    body = {
        "restaurant_id": "rest-1",
        "branch_id": "mk",
        "fulfillment": "pickup",
        "customer_name": "Sam",
        "customer_phone": "0901234567",
        "booking_date": "2026-09-04",
        "booking_time": "18:30",
        "items": [{"menu_item_id": "tra-dao", "quantity": 2}],
    }
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = OrderClient("https://example.test", http=http)
        result = await client.create_order(body)
    assert result.ok is True
    assert result.data["id"] == "ord-2"
    assert len(captured) == 1
    path, sent = captured[0]
    assert path.endswith("/menu/takeout/ai")
    assert "delivery_address" not in sent
    assert "delivery_phone" not in sent
    assert "delivery_fee" not in sent
    assert "estimated_delivery_time" not in sent
    assert sent["booking_date"] == "2026-09-04"
    assert sent["booking_time"] == "18:30"
    assert sent["items"] == [{"menu_item_id": "tra-dao", "quantity": 2}]


async def test_create_order_posts_distinct_delivery_phone() -> None:
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(201, json={"success": True, "data": {"id": "ord-3"}})

    body = {
        "restaurant_id": "rest-1",
        "branch_id": "mk",
        "fulfillment": "delivery",
        "customer_name": "Sam",
        "customer_phone": "0901234567",
        "delivery_address": "12 Nguyen Trai",
        "delivery_phone": "0987654321",
        "booking_date": "2026-09-04",
        "booking_time": "18:30",
        "items": [{"menu_item_id": "pho-bo", "quantity": 1}],
    }
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = OrderClient("https://example.test", http=http)
        result = await client.create_order(body)
    assert result.ok is True
    assert captured[0]["customer_phone"] == "0901234567"
    assert captured[0]["delivery_phone"] == "0987654321"


async def test_create_order_network_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    body = {
        "restaurant_id": "rest-1",
        "branch_id": "mk",
        "fulfillment": "pickup",
        "customer_name": "Sam",
        "customer_phone": "0901234567",
        "booking_date": "2026-09-04",
        "booking_time": "18:30",
        "items": [{"menu_item_id": "tra-dao", "quantity": 1}],
    }
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = OrderClient("https://example.test", http=http)
        result = await client.create_order(body)
    assert result.ok is False
    assert result.error == "network"
