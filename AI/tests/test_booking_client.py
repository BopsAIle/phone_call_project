from __future__ import annotations

import json

import httpx

from booking.client import (
    RestaurantClient,
    normalize_hotline,
    restaurant_from_api,
    unwrap_data,
)
from booking.models import HotlineResult


def test_normalize_hotline_strips_e164_plus() -> None:
    assert normalize_hotline("+4444444444") == "4444444444"
    assert normalize_hotline("+1900636886") == "1900636886"
    assert normalize_hotline("1900636886") == "1900636886"
    assert normalize_hotline("") == ""
    assert normalize_hotline("++") == ""


def test_unwrap_data_accepts_envelope_or_bare() -> None:
    inner = {"id": "rest-1", "name": "LongWang"}
    assert unwrap_data({"success": True, "data": inner}) == inner
    assert unwrap_data(inner) == inner
    assert unwrap_data("raw") == "raw"


def test_restaurant_from_api_keeps_active_branches_only() -> None:
    restaurant = restaurant_from_api(
        {
            "id": "rest-1",
            "name": "Nhà hàng LongWang",
            "phone": "1900636886",
            "status": "active",
            "branches": [
                {"id": "mk", "name": "Chi nhánh Minh Khai", "address": "Minh Khai", "status": "active"},
                {"id": "dead", "name": "Closed", "status": "inactive"},
                {"id": "", "name": "No id"},
            ],
        }
    )
    assert restaurant is not None
    assert [b.id for b in restaurant.branches] == ["mk"]


async def test_find_by_hotline_200_unwraps_branches() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert str(request.url).endswith("/restaurants/by-hotline/1900636886")
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "id": "rest-1",
                    "name": "Nhà hàng LongWang",
                    "phone": "1900636886",
                    "status": "active",
                    "branches": [
                        {"id": "mk", "name": "Chi nhánh Minh Khai", "status": "active"},
                        {"id": "bd", "name": "Chi nhánh Ba Đình", "status": "active"},
                    ],
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = RestaurantClient("https://example.test", http=http)
        result = await client.find_by_hotline("+1900636886")
    assert result.restaurant is not None
    assert result.restaurant.id == "rest-1"
    assert {b.id for b in result.restaurant.branches} == {"mk", "bd"}
    assert result.missing is False


async def test_find_by_hotline_404_is_missing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "not found"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = RestaurantClient("https://example.test", http=http)
        result = await client.find_by_hotline("999")
    assert result == HotlineResult(missing=True)


async def test_find_by_hotline_empty_digits_skips_http() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected HTTP {request.method} {request.url}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = RestaurantClient("https://example.test", http=http)
        result = await client.find_by_hotline("+")
    assert result.missing is True
    assert result.restaurant is None


async def test_create_booking_posts_json_body() -> None:
    captured: list[tuple[str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        captured.append((str(request.url), json.loads(request.content)))
        if str(request.url).endswith("/bookings/ai"):
            return httpx.Response(201, json={"success": True, "data": {"id": "bk-1"}})
        raise AssertionError(f"unexpected HTTP {request.method} {request.url}")

    body = {
        "restaurant_id": "rest-1",
        "branch_id": "mk",
        "customer_name": "Sam",
        "phone_number": "0123456789",
        "party_size": 2,
        "booking_date": "2026-08-28",
        "booking_time": "19:30",
        "source": "phone_ai",
    }
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = RestaurantClient("https://example.test", http=http)
        result = await client.create_booking(body)
    assert result.ok is True
    assert result.data["id"] == "bk-1"
    assert len(captured) == 1
    url, sent = captured[0]
    assert url.endswith("/bookings/ai")
    assert sent == {
        "restaurant_id": "rest-1",
        "branch_id": "mk",
        "customer_name": "Sam",
        "customer_phone": "0123456789",
        "party_size": 2,
        "booking_date": "2026-08-28",
        "booking_time": "19:30",
    }


async def test_create_booking_falls_back_to_public_endpoint() -> None:
    captured: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(str(request.url))
        if str(request.url).endswith("/bookings/ai"):
            return httpx.Response(400, json={"message": "Bad Request Exception"})
        assert str(request.url).endswith("/bookings")
        body = json.loads(request.content)
        assert body["phone_number"] == "0123456789"
        assert body["source"] == "phone_ai"
        return httpx.Response(201, json={"success": True, "data": {"id": "bk-2"}})

    body = {
        "restaurant_id": "rest-1",
        "branch_id": "mk",
        "customer_name": "Sam",
        "customer_phone": "0123456789",
        "party_size": 2,
        "booking_date": "2026-08-28",
        "booking_time": "19:30",
    }
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = RestaurantClient("https://example.test", http=http)
        result = await client.create_booking(body)
    assert result.ok is True
    assert result.data["id"] == "bk-2"
    assert captured[0].endswith("/bookings/ai")
    assert captured[1].endswith("/bookings")
