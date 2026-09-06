"""HTTP client for restaurant menu and AI food orders.

GET /menu/branch/{branchId} and POST /menu/delivery/ai or /menu/takeout/ai.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from booking.client import unwrap_data
from order.models import MenuItem, MenuResult, OrderApiResult

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://phone-call-project.onrender.com"
_DEFAULT_TIMEOUT = 30.0
_AVAILABLE_STATUS = {"available"}
_UNAVAILABLE_STATUS = {"unavailable", "sold_out", "sold-out"}


def _parse_price(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    if price < 0:
        return None
    return price


def _parse_available(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"false", "0", "no", "unavailable", "sold_out", "sold-out", "out"}:
        return False
    return True


def _item_available(item: dict[str, Any]) -> bool:
    qty_raw = item.get("quantity_available")
    if qty_raw is not None and qty_raw != "":
        try:
            if int(qty_raw) == 0:
                return False
        except (TypeError, ValueError):
            pass
    status = item.get("status")
    if status is not None and str(status).strip():
        text = str(status).strip().lower()
        if text in _UNAVAILABLE_STATUS:
            return False
        return text in _AVAILABLE_STATUS
    return _parse_available(item.get("available"))


def menu_item_from_api(item: dict[str, Any]) -> Optional[MenuItem]:
    if not isinstance(item, dict):
        return None
    item_id = str(item.get("id") or item.get("menu_item_id") or "").strip()
    name = str(item.get("name") or "").strip()
    if not item_id or not name:
        return None
    currency = str(item.get("currency") or "VND").strip() or "VND"
    return MenuItem(
        id=item_id,
        name=name,
        price=_parse_price(item.get("price")),
        currency=currency,
        category=str(item.get("category") or "").strip(),
        description=str(item.get("description") or "").strip(),
        available=_item_available(item),
        unit=str(item.get("unit") or "").strip(),
    )


def _raw_item_list(payload: Any) -> list[Any]:
    data = unwrap_data(payload)
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    for key in ("items", "menu", "products"):
        value = data.get(key)
        if isinstance(value, list):
            return value
    nested = unwrap_data(data)
    if nested is not data:
        return _raw_item_list(nested)
    return []


def parse_menu_items(payload: Any) -> list[MenuItem]:
    items: list[MenuItem] = []
    seen: set[str] = set()
    for raw in _raw_item_list(payload):
        if not isinstance(raw, dict):
            continue
        item = menu_item_from_api(raw)
        if item is None or item.id in seen:
            continue
        seen.add(item.id)
        items.append(item)
    return items


def _error_message(payload: Any, fallback: str) -> str:
    if isinstance(payload, dict):
        for key in ("message", "error", "detail"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return fallback


def _phone_from_body(body: dict[str, Any]) -> str:
    return str(body.get("customer_phone") or body.get("phone_number") or "").strip()


def _order_items(body: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for raw in body.get("items") or []:
        if not isinstance(raw, dict):
            continue
        menu_item_id = str(raw.get("menu_item_id") or raw.get("id") or "").strip()
        try:
            quantity = int(raw.get("quantity"))
        except (TypeError, ValueError):
            continue
        if not menu_item_id or quantity < 1:
            continue
        items.append({"menu_item_id": menu_item_id, "quantity": quantity})
    return items


def _merged_note(body: dict[str, Any]) -> str:
    parts: list[str] = []
    note = str(body.get("note") or "").strip()
    if note:
        parts.append(note)
    for raw in body.get("items") or []:
        if not isinstance(raw, dict):
            continue
        line_note = str(raw.get("note") or "").strip()
        if line_note:
            parts.append(line_note)
    return "; ".join(parts)


def _order_body(body: dict[str, Any]) -> dict[str, Any]:
    fulfillment = str(body.get("fulfillment") or "").strip().lower()
    phone = _phone_from_body(body)
    booking_time = str(body.get("booking_time") or "").strip()
    payload: dict[str, Any] = {
        "restaurant_id": body["restaurant_id"],
        "branch_id": body["branch_id"],
        "customer_name": body["customer_name"],
        "customer_phone": phone,
        "booking_date": str(body.get("booking_date") or "").strip(),
        "booking_time": booking_time,
        "items": _order_items(body),
    }
    note = _merged_note(body)
    if note:
        payload["note"] = note
    if fulfillment == "delivery":
        address = str(body.get("delivery_address") or "").strip()
        if address:
            payload["delivery_address"] = address
        delivery_phone = str(body.get("delivery_phone") or "").strip() or phone
        if delivery_phone:
            payload["delivery_phone"] = delivery_phone
        payload["delivery_fee"] = 0
        payload["estimated_delivery_time"] = booking_time
    return payload


class OrderClient:
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

    async def get_menu(self, restaurant_id: str, branch_id: str = "") -> MenuResult:
        branch_id = (branch_id or "").strip()
        if not branch_id:
            return MenuResult(ok=False, error="no_branch")
        path = f"/menu/branch/{branch_id}"
        url = f"{self._base}{path}"
        try:
            response = await self._http.get(url)
        except Exception as exc:
            logger.warning("Get menu %s restaurant=%s failed: %s", path, restaurant_id, exc)
            return MenuResult(ok=False, error="network")
        if response.status_code >= 400:
            try:
                payload = response.json()
            except Exception:
                payload = None
            error = _error_message(payload, f"http_{response.status_code}")
            logger.warning("Get menu %s HTTP %s: %s", path, response.status_code, error)
            return MenuResult(ok=False, error=error)
        try:
            payload = response.json()
        except Exception:
            return MenuResult(ok=False, error="invalid_json")
        items = parse_menu_items(payload)
        logger.info("Get menu %s succeeded items=%s", path, len(items))
        return MenuResult(ok=True, items=items)

    async def create_order(self, body: dict[str, Any]) -> OrderApiResult:
        fulfillment = str(body.get("fulfillment") or "").strip().lower()
        if fulfillment == "delivery":
            path = "/menu/delivery/ai"
        elif fulfillment == "pickup":
            path = "/menu/takeout/ai"
        else:
            return OrderApiResult(ok=False, error="invalid_fulfillment")
        return await self._post_order(path, _order_body(body))

    async def _post_order(self, path: str, body: dict[str, Any]) -> OrderApiResult:
        url = f"{self._base}{path}"
        try:
            response = await self._http.post(url, json=body)
        except Exception as exc:
            logger.warning("Create order %s failed: %s", path, exc)
            return OrderApiResult(ok=False, error="network")
        try:
            payload = response.json()
        except Exception:
            payload = None
        if response.status_code >= 400:
            error = _error_message(payload, f"http_{response.status_code}")
            logger.warning("Create order %s HTTP %s: %s", path, response.status_code, error)
            return OrderApiResult(ok=False, error=error)
        data = unwrap_data(payload)
        if not isinstance(data, dict):
            data = {}
        logger.info("Create order %s succeeded id=%s", path, data.get("id") or "-")
        return OrderApiResult(ok=True, data=data)
