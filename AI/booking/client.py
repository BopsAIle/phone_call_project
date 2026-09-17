"""HTTP client for the restaurant booking API."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

import httpx

from booking.models import BookingApiResult, Branch, HotlineResult, Restaurant

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://127.0.0.1:3001"
_DEFAULT_TIMEOUT = 30.0

## Chuẩn hóa số điện thoại từ font-end gửi sang
def normalize_hotline(value: str) -> str:
    """Keep digits only so +4444444444 matches API hotline 4444444444."""
    return "".join(ch for ch in (value or "") if ch.isdigit())


def unwrap_data(payload: Any) -> Any:
    if isinstance(payload, dict) and "data" in payload:
        return payload["data"]
    return payload

# Lọc ra branch đang hoạt động và có status là active
def branch_from_api(item: dict[str, Any]) -> Optional[Branch]:
    if not isinstance(item, dict):
        return None
    branch_id = str(item.get("id") or "").strip()
    name = str(item.get("name") or "").strip()
    if not branch_id or not name:
        return None
    status = str(item.get("status") or "active").strip() or "active"
    if status != "active":
        return None
    return Branch(
        id=branch_id,
        name=name,
        address=str(item.get("address") or "").strip(),
        opening_time=str(item.get("opening_time") or "").strip(),
        closing_time=str(item.get("closing_time") or "").strip(),
        status=status,
    )

## data: trả về từ API GET /restaurants/by-hotline/{digits}
## Hàm này lọc danh sách  các branch trong restaurant để trả về 
def restaurant_from_api(data: dict[str, Any]) -> Optional[Restaurant]:
    if not isinstance(data, dict):
        return None
    restaurant_id = str(data.get("id") or "").strip()
    name = str(data.get("name") or "").strip()
    if not restaurant_id:
        return None
    raw_branches = data.get("branches") or []
    branches: list[Branch] = []
    if isinstance(raw_branches, list):
        for item in raw_branches:
            # Lọc ra branch đang hoạt động và có status là active
            branch = branch_from_api(item) if isinstance(item, dict) else None
            if branch is not None:
                branches.append(branch)
    return Restaurant(
        id=restaurant_id,
        name=name,
        phone=str(data.get("phone") or "").strip(),
        status=str(data.get("status") or "active").strip() or "active",
        branches=branches,
    )


def _phone_from_body(body: dict[str, Any]) -> str:
    return str(body.get("customer_phone") or body.get("phone_number") or "").strip()


def _ai_booking_body(body: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "restaurant_id": body["restaurant_id"],
        "branch_id": body["branch_id"],
        "customer_name": body["customer_name"],
        "customer_phone": _phone_from_body(body),
        "party_size": body["party_size"],
        "booking_date": body["booking_date"],
        "booking_time": body["booking_time"],
    }
    note = str(body.get("note") or "").strip()
    if note:
        payload["note"] = note
    return payload


def _public_booking_body(body: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "restaurant_id": body["restaurant_id"],
        "branch_id": body["branch_id"],
        "customer_name": body["customer_name"],
        "phone_number": _phone_from_body(body),
        "party_size": body["party_size"],
        "booking_date": body["booking_date"],
        "booking_time": body["booking_time"],
        "source": "phone_ai",
    }
    note = str(body.get("note") or "").strip()
    if note:
        payload["note"] = note
    return payload


def _error_message(payload: Any, fallback: str) -> str:
    if isinstance(payload, dict):
        for key in ("message", "error", "detail"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return fallback


class RestaurantClient:
    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        *,
        timeout: float = _DEFAULT_TIMEOUT,
        http: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self._base = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self._owns_http = http is None
        self._http = http or httpx.AsyncClient(timeout=timeout)

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()
### Từ số điện thoại cửa hàng, lọc ra branch đang hoạt động và có status là active
    async def find_by_hotline(self, hotline: str) -> HotlineResult:
        digits = normalize_hotline(hotline)
        if not digits:
            return HotlineResult(missing=True)
        url = f"{self._base}/restaurants/by-hotline/{digits}"
        response: Optional[httpx.Response] = None
        for attempt in range(2):
            try:
                response = await self._http.get(url)
                break
            except Exception as exc:
                logger.warning(
                    "Hotline lookup failed for %s (attempt %s): %s",
                    digits,
                    attempt + 1,
                    exc,
                )
                if attempt == 0:
                    await asyncio.sleep(0.8)
        if response is None:
            return HotlineResult(error="network")
        if response.status_code == 404:
            return HotlineResult(missing=True)
        if response.status_code >= 400:
            logger.warning("Hotline lookup HTTP %s for %s", response.status_code, digits)
            return HotlineResult(error=f"http_{response.status_code}")
        try:
            payload = response.json()
        except Exception:
            return HotlineResult(error="invalid_json")
        data = unwrap_data(payload)

        restaurant = restaurant_from_api(data) if isinstance(data, dict) else None
        if restaurant is None:
            return HotlineResult(missing=True)
        if restaurant.status and restaurant.status != "active":
            return HotlineResult(missing=True)
        return HotlineResult(restaurant=restaurant)

##Từ danh sách thông tin thu thập được từ khách hàng, tạo POST /bookings/ai hoặc POST /bookings
    async def create_booking(self, body: dict[str, Any]) -> BookingApiResult:
        ai_body = _ai_booking_body(body)
        result = await self._post_booking("/bookings/ai", ai_body)
        if result.ok:
            return result
        logger.warning("POST /bookings/ai failed (%s); falling back to POST /bookings", result.error)
        return await self._post_booking("/bookings", _public_booking_body(body))

    async def _post_booking(self, path: str, body: dict[str, Any]) -> BookingApiResult:
        url = f"{self._base}{path}"
        try:
            response = await self._http.post(url, json=body)
        except Exception as exc:
            logger.warning("Create booking %s failed: %s", path, exc)
            return BookingApiResult(ok=False, error="network")
        try:
            payload = response.json()
        except Exception:
            payload = None
        if response.status_code >= 400:
            error = _error_message(payload, f"http_{response.status_code}")
            logger.warning("Create booking %s HTTP %s: %s", path, response.status_code, error)
            return BookingApiResult(ok=False, error=error)
        data = unwrap_data(payload)
        if not isinstance(data, dict):
            data = {}
        logger.info("Create booking %s succeeded id=%s", path, data.get("id") or "-")
        return BookingApiResult(ok=True, data=data)
