"""OpenAI tools: search_menu, list_menu, cart, fulfillment, create_order."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from booking.tools import (
    _DATE_RE,
    _catalog_public,
    normalize_booking_date,
    normalize_customer_phone,
    resolve_booking_when,
)
from order.models import CartLine, MenuItem, MenuMatchResult

logger = logging.getLogger(__name__)

_MENU_PREVIEW_LIMIT = 12
_BROWSE_MENU_RE = re.compile(
    r"(thực đơn|thuc don|\bmenu\b|những\s+món\s+gì|nhung\s+mon\s+gi|"
    r"món\s+gì|mon\s+gi|món\s+nào|mon\s+nao|có\s+những\s+món|co\s+nhung\s+mon)",
    re.IGNORECASE,
)

ORDER_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_menu",
            "description": (
                "Tra một món ăn hoặc đồ uống được nói trên thực đơn chi nhánh đã khóa. "
                "Gọi mỗi khi người gọi nêu tên món, trước khi khẳng định món đó có. "
                "Không bịa món. Nếu khách hỏi thực đơn / có món gì / những món nào, "
                "dùng list_menu, không dùng tool này."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "spoken_name": {
                        "type": "string",
                        "description": "Lời người gọi, đúng như bản ghi âm.",
                    }
                },
                "required": ["spoken_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_menu",
            "description": (
                "Lấy thực đơn chi nhánh đã khóa khi khách hỏi có món gì, thực đơn, "
                "những món nào. GET menu theo branch_id đã khóa. "
                "Đọc vài tên món với khách; không đọc hết nếu dài; không đọc địa chỉ chi nhánh."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_to_cart",
            "description": (
                "Thêm món vào giỏ. menu_item_id phải lấy từ search_menu, "
                "không được bịa."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "menu_item_id": {"type": "string"},
                    "quantity": {"type": "integer", "minimum": 1, "maximum": 50},
                    "note": {
                        "type": "string",
                        "description": "Ghi chú dòng, ví dụ ít cay.",
                    },
                },
                "required": ["menu_item_id", "quantity"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_cart",
            "description": "Đổi số lượng một dòng giỏ. menu_item_id phải đã có trong giỏ.",
            "parameters": {
                "type": "object",
                "properties": {
                    "menu_item_id": {"type": "string"},
                    "quantity": {"type": "integer", "minimum": 1, "maximum": 50},
                    "note": {
                        "type": "string",
                        "description": "Ghi chú dòng tùy chọn để phân biệt nếu cùng món được thêm hai lần.",
                    },
                },
                "required": ["menu_item_id", "quantity"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_from_cart",
            "description": "Xóa một dòng khỏi giỏ.",
            "parameters": {
                "type": "object",
                "properties": {
                    "menu_item_id": {"type": "string"},
                    "note": {"type": "string"},
                },
                "required": ["menu_item_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_fulfillment",
            "description": (
                "Chọn cách người gọi nhận đơn: giao tới một địa chỉ, "
                "hoặc đến lấy tại chi nhánh đã khóa."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "fulfillment": {
                        "type": "string",
                        "enum": ["delivery", "pickup"],
                    },
                    "delivery_address": {
                        "type": "string",
                        "description": "Địa chỉ đường phố nói miệng. Bắt buộc khi giao hàng.",
                    },
                    "delivery_phone": {
                        "type": "string",
                        "description": (
                            "Số điện thoại người nhận nếu khác số người đặt. "
                            "Chỉ dùng khi giao hàng."
                        ),
                    },
                },
                "required": ["fulfillment"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_order_details",
            "description": (
                "Lưu thông tin khách cho đơn món ngay khi người gọi nêu: "
                "tên, số điện thoại người đặt, ngày, giờ, ghi chú, "
                "hoặc số điện thoại người nhận. Không tạo đơn."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_name": {"type": "string"},
                    "phone_number": {"type": "string"},
                    "booking_date": {
                        "type": "string",
                        "description": (
                            "YYYY-MM-DD theo múi giờ nhà hàng, "
                            "hoặc tomorrow / today / ngày mai / hôm nay."
                        ),
                    },
                    "booking_time": {
                        "type": "string",
                        "description": (
                            "HH:MM 24 giờ. Giao hàng: giờ nhận hàng. "
                            "Mang về: giờ lấy món."
                        ),
                    },
                    "note": {"type": "string"},
                    "delivery_phone": {
                        "type": "string",
                        "description": "Số điện thoại người nhận nếu khác số người đặt.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_order",
            "description": (
                "Đặt đơn món sau khi người gọi đã xác nhận giỏ và đủ thông tin. "
                "Giao hàng cần địa chỉ; mang về không gửi địa chỉ. "
                "restaurant_id, branch_id và giỏ lấy từ bộ nhớ phiên. "
                "Thiếu field thì tool trả missing_fields, không POST."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_name": {"type": "string"},
                    "phone_number": {"type": "string"},
                    "booking_date": {
                        "type": "string",
                        "description": (
                            "YYYY-MM-DD theo múi giờ nhà hàng, "
                            "hoặc tomorrow / today / ngày mai / hôm nay. "
                            "Giao hàng: ngày giao. Mang về: ngày lấy."
                        ),
                    },
                    "booking_time": {
                        "type": "string",
                        "description": (
                            "HH:MM 24 giờ. Giao hàng: giờ nhận hàng. "
                            "Mang về: giờ lấy món."
                        ),
                    },
                    "note": {"type": "string"},
                    "delivery_phone": {
                        "type": "string",
                        "description": (
                            "Số điện thoại người nhận nếu khác số người đặt. "
                            "Bỏ trống thì dùng số người đặt."
                        ),
                    },
                },
                "required": [
                    "customer_name",
                    "phone_number",
                    "booking_date",
                    "booking_time",
                ],
            },
        },
    },
]

ORDER_TOOL_NAMES = frozenset(
    fn["function"]["name"] for fn in ORDER_TOOLS if "function" in fn
)


def _parse_quantity(raw: Any) -> Optional[int]:
    try:
        quantity = int(raw)
    except (TypeError, ValueError):
        return None
    return quantity


def _looks_like_menu_browse(spoken: str) -> bool:
    text = (spoken or "").strip()
    if not text:
        return False
    return _BROWSE_MENU_RE.search(text) is not None


def _menu_preview(session: Any) -> dict[str, Any]:
    available = [item for item in (getattr(session, "menu", None) or []) if item.available]
    preview: list[dict[str, Any]] = []
    for item in available[:_MENU_PREVIEW_LIMIT]:
        row: dict[str, Any] = {"name": item.name}
        if item.price is not None:
            row["price"] = item.price
            row["currency"] = item.currency
        if item.unit:
            row["unit"] = item.unit
        preview.append(row)
    return {
        "ok": True,
        "status": "browse",
        "branch_name": str(getattr(session, "selected_branch_name", "") or ""),
        "count": len(available),
        "items": preview,
        "truncated": len(available) > _MENU_PREVIEW_LIMIT,
        "note": (
            "Đọc vài tên món, không đọc hết nếu truncated. "
            "Không đọc địa chỉ chi nhánh. Hỏi khách muốn món nào."
        ),
    }


def _cart_public(session: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in getattr(session, "cart", None) or []:
        row: dict[str, Any] = {
            "menu_item_id": line.menu_item_id,
            "name": line.name,
            "quantity": line.quantity,
        }
        if line.note:
            row["note"] = line.note
        if line.price is not None:
            row["unit_price"] = line.price
            row["line_total"] = line.price * line.quantity
            row["currency"] = line.currency
        if line.unit:
            row["unit"] = line.unit
        rows.append(row)
    return rows


def _cart_total(session: Any) -> Optional[float]:
    total = 0.0
    any_price = False
    for line in getattr(session, "cart", None) or []:
        if line.price is not None:
            any_price = True
            total += line.price * line.quantity
    return total if any_price else None


def _menu_by_id(session: Any) -> dict[str, MenuItem]:
    return {item.id: item for item in getattr(session, "menu", None) or []}


def _find_cart_index(session: Any, menu_item_id: str, note: Optional[str]) -> int:
    cart = list(getattr(session, "cart", None) or [])
    wanted_note = None if note is None else note.strip()
    if wanted_note is not None:
        for index, line in enumerate(cart):
            if line.menu_item_id == menu_item_id and line.note == wanted_note:
                return index
        return -1
    matches = [i for i, line in enumerate(cart) if line.menu_item_id == menu_item_id]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        return -1
        return -2


def order_missing_fields(session: Any) -> list[str]:
    missing: list[str] = []
    if not list(getattr(session, "cart", None) or []):
        missing.append("items")
    fulfillment = str(getattr(session, "fulfillment", "") or "").strip().lower()
    if fulfillment not in {"delivery", "pickup"}:
        missing.append("fulfillment")
    elif fulfillment == "delivery" and not str(
        getattr(session, "delivery_address", "") or ""
    ).strip():
        missing.append("delivery_address")
    if not str(getattr(session, "order_customer_name", "") or "").strip():
        missing.append("customer_name")
    if not str(getattr(session, "order_customer_phone", "") or "").strip():
        missing.append("customer_phone")
    date = str(getattr(session, "order_booking_date", "") or "").strip()
    if not _DATE_RE.fullmatch(date):
        missing.append("booking_date")
    if not str(getattr(session, "order_booking_time", "") or "").strip():
        missing.append("booking_time")
    return missing


def _missing_spoken(field: str, fulfillment: str) -> str:
    if field == "items":
        return "món trong giỏ"
    if field == "fulfillment":
        return "giao hàng hay mang về"
    if field == "delivery_address":
        return "địa chỉ giao hàng"
    if field == "customer_name":
        return "tên người đặt"
    if field == "customer_phone":
        return "số điện thoại người đặt"
    if field == "booking_date":
        if fulfillment == "delivery":
            return "ngày giao hàng"
        if fulfillment == "pickup":
            return "ngày lấy món"
        return "ngày nhận hoặc lấy món"
    if field == "booking_time":
        if fulfillment == "delivery":
            return "giờ nhận hàng"
        if fulfillment == "pickup":
            return "giờ lấy món"
        return "giờ nhận hoặc lấy món"
    return field


def _ask_next(missing: list[str], fulfillment: str) -> str:
    if not missing:
        return ""
    field = missing[0]
    spoken = _missing_spoken(field, fulfillment)
    if field == "fulfillment":
        return "hỏi giao hàng hay mang về"
    if field == "items":
        return "hỏi khách muốn gọi món gì"
    return f"hỏi {spoken}"


def order_status_prompt(session: Any) -> str:
    fulfillment = str(getattr(session, "fulfillment", "") or "").strip().lower()
    missing = order_missing_fields(session)
    collected: list[str] = []
    name = str(getattr(session, "order_customer_name", "") or "").strip()
    if name:
        collected.append(f"tên {name}")
    phone = str(getattr(session, "order_customer_phone", "") or "").strip()
    if phone:
        collected.append(f"SĐT đặt {phone}")
    address = str(getattr(session, "delivery_address", "") or "").strip()
    if fulfillment == "delivery" and address:
        collected.append(f"giao tới {address}")
    delivery_phone = str(getattr(session, "delivery_phone", "") or "").strip()
    if fulfillment == "delivery" and delivery_phone and delivery_phone != phone:
        collected.append(f"SĐT nhận {delivery_phone}")
    date = str(getattr(session, "order_booking_date", "") or "").strip()
    if date:
        collected.append(f"ngày {date}")
    time = str(getattr(session, "order_booking_time", "") or "").strip()
    if time:
        collected.append(f"giờ {time}")
    note = str(getattr(session, "order_note", "") or "").strip()
    if note:
        collected.append(f"ghi chú {note}")
    parts: list[str] = []
    if missing:
        spoken = ", ".join(_missing_spoken(field, fulfillment) for field in missing)
        parts.append(f"Thông tin đơn còn thiếu: {spoken}.")
        ask = _ask_next(missing, fulfillment)
        if ask:
            parts.append(f"Hỏi tiếp: {ask}.")
    else:
        parts.append("Đã đủ thông tin bắt buộc để đặt đơn sau khi khách xác nhận.")
    if collected:
        parts.append("Đã thu: " + "; ".join(collected) + ".")
    return " ".join(parts)


def _apply_order_details(session: Any, args: dict[str, Any]) -> list[str]:
    invalid: list[str] = []
    name = str(args.get("customer_name") or "").strip()
    if name:
        session.order_customer_name = name
    raw_phone = str(args.get("phone_number") or args.get("customer_phone") or "")
    if raw_phone.strip():
        phone = normalize_customer_phone(raw_phone)
        if phone:
            session.order_customer_phone = phone
        else:
            invalid.append("phone_number")
    if "booking_date" in args or "booking_time" in args:
        tz = str(getattr(session, "timezone", "") or "UTC")
        raw_date = str(args.get("booking_date") or "").strip() if "booking_date" in args else ""
        raw_time = str(args.get("booking_time") or "").strip() if "booking_time" in args else ""
        if raw_date or raw_time:
            booking_date, booking_time = resolve_booking_when(raw_date, raw_time, tz)
            if booking_date:
                session.order_booking_date = booking_date
            elif "booking_date" in args and raw_date:
                invalid.append("booking_date")
            if booking_time:
                session.order_booking_time = booking_time
            elif "booking_time" in args and raw_time and normalize_booking_date(raw_time, tz) is None:
                invalid.append("booking_time")
    if "note" in args:
        session.order_note = str(args.get("note") or "").strip()
    raw_delivery = str(args.get("delivery_phone") or "")
    if raw_delivery.strip():
        delivery_phone = normalize_customer_phone(raw_delivery)
        if delivery_phone:
            session.delivery_phone = delivery_phone
        else:
            invalid.append("delivery_phone")
    return invalid


def _order_details_public(session: Any) -> dict[str, Any]:
    fulfillment = str(getattr(session, "fulfillment", "") or "").strip().lower()
    missing = order_missing_fields(session)
    payload: dict[str, Any] = {
        "customer_name": str(getattr(session, "order_customer_name", "") or "") or None,
        "phone_number": str(getattr(session, "order_customer_phone", "") or "") or None,
        "booking_date": str(getattr(session, "order_booking_date", "") or "") or None,
        "booking_time": str(getattr(session, "order_booking_time", "") or "") or None,
        "note": str(getattr(session, "order_note", "") or "") or None,
        "fulfillment": fulfillment or None,
        "missing": missing,
        "ask_next": _ask_next(missing, fulfillment),
    }
    if fulfillment == "delivery":
        payload["delivery_address"] = (
            str(getattr(session, "delivery_address", "") or "") or None
        )
        payload["delivery_phone"] = (
            str(getattr(session, "delivery_phone", "") or "") or None
        )
    return payload


class OrderTools:
    def __init__(self, session: Any, client: Any, matcher: Any) -> None:
        self._session = session
        self._client = client
        self._matcher = matcher

    def _mark_order_intent(self) -> None:
        session = self._session
        session.intent = "order"
        refresh = getattr(session, "refresh_system_prompt", None)
        if refresh is not None:
            refresh()

    async def execute(self, name: str, arguments_json: str) -> str:
        try:
            args = json.loads(arguments_json) if arguments_json else {}
        except json.JSONDecodeError:
            args = {}
        if not isinstance(args, dict):
            args = {}
        try:
            if name == "search_menu":
                result = await self.search_menu(str(args.get("spoken_name") or ""))
            elif name == "list_menu":
                result = await self.list_menu()
            elif name == "add_to_cart":
                result = await self.add_to_cart(args)
            elif name == "update_cart":
                result = self.update_cart(args)
            elif name == "remove_from_cart":
                result = self.remove_from_cart(args)
            elif name == "set_fulfillment":
                result = self.set_fulfillment(args)
            elif name == "save_order_details":
                result = self.save_order_details(args)
            elif name == "create_order":
                result = await self.create_order(args)
            else:
                result = {"ok": False, "error": "unknown_tool"}
        except Exception:
            logger.exception("Order tool %s failed", name)
            result = {"ok": False, "error": "tool_failed"}
        logger.info(
            "Order tool %s status=%s error=%s",
            name,
            result.get("ok", result.get("status")),
            result.get("error") or result.get("reason") or "-",
        )
        return json.dumps(result, ensure_ascii=False)

    def _no_branch_payload(self) -> dict[str, Any]:
        return {
            "ok": False,
            "error": "no_branch",
            "available_branches": _catalog_public(self._session),
        }

    def _lock_sole_branch(self) -> bool:
        session = self._session
        if str(getattr(session, "selected_branch_id", "") or ""):
            return True
        branches = list(getattr(session, "branches", None) or [])
        if len(branches) != 1:
            return False
        return session.select_branch(branches[0].id) is not None

    async def _ensure_menu(self) -> Optional[dict[str, Any]]:
        session = self._session
        if getattr(session, "menu_ready", False):
            return None
        restaurant_id = str(getattr(session, "restaurant_id", "") or "")
        if getattr(session, "restaurant_missing", False) or not restaurant_id:
            return {"ok": False, "error": "no_restaurant", "status": "none"}
        if not self._lock_sole_branch():
            payload = self._no_branch_payload()
            payload["status"] = "none"
            return payload
        branch_id = str(getattr(session, "selected_branch_id", "") or "")
        result = await self._client.get_menu(restaurant_id, branch_id)
        if not result.ok:
            return {"ok": False, "error": result.error or "menu_failed", "status": "none"}
        session.menu = list(result.items)
        session.menu_ready = True
        return None

    async def list_menu(self) -> dict[str, Any]:
        self._mark_order_intent()
        load_error = await self._ensure_menu()
        if load_error is not None:
            return load_error
        items = list(getattr(self._session, "menu", None) or [])
        if not items:
            return {"ok": False, "status": "none", "reason": "empty_menu"}
        return _menu_preview(self._session)

    async def search_menu(self, spoken_name: str) -> dict[str, Any]:
        self._mark_order_intent()
        session = self._session
        load_error = await self._ensure_menu()
        if load_error is not None:
            return load_error
        spoken = (spoken_name or "").strip()
        if _looks_like_menu_browse(spoken):
            return _menu_preview(session)
        if not spoken:
            return {"status": "none", "reason": "empty_name"}
        items = list(getattr(session, "menu", None) or [])
        if not items:
            return {"status": "none", "reason": "empty_menu"}
        if self._matcher is None:
            matched = MenuMatchResult(status="none")
        else:
            matched = await self._matcher.match(spoken, items)
        payload: dict[str, Any] = {
            "status": matched.status,
            "confidence": matched.confidence,
            "confirm_name": matched.confirm_name,
            "menu_item_id": matched.menu_item_id or None,
        }
        by_id = _menu_by_id(session)
        if matched.status == "match" and matched.menu_item_id:
            item = by_id.get(matched.menu_item_id)
            if item is not None:
                payload["available"] = item.available
                payload["unit"] = item.unit
                if item.price is not None:
                    payload["price"] = item.price
                    payload["currency"] = item.currency
        if matched.status == "ambiguous":
            names = []
            for cid in matched.candidate_ids:
                item = by_id.get(cid)
                if item is not None:
                    names.append({"menu_item_id": item.id, "name": item.name})
            payload["candidates"] = names
        return payload

    async def add_to_cart(self, args: dict[str, Any]) -> dict[str, Any]:
        self._mark_order_intent()
        load_error = await self._ensure_menu()
        if load_error is not None:
            return load_error
        session = self._session
        menu_item_id = str(args.get("menu_item_id") or "").strip()
        quantity = _parse_quantity(args.get("quantity"))
        note = str(args.get("note") or "").strip()
        if quantity is None or not 1 <= quantity <= 50:
            return {"ok": False, "error": "invalid_quantity"}
        item = _menu_by_id(session).get(menu_item_id)
        if item is None:
            return {"ok": False, "error": "unknown_item"}
        if not item.available:
            return {"ok": False, "error": "unavailable", "confirm_name": item.name}
        cart: list[CartLine] = list(getattr(session, "cart", None) or [])
        merged = False
        for line in cart:
            if line.menu_item_id == item.id and line.note == note:
                line.quantity += quantity
                merged = True
                break
        if not merged:
            cart.append(
                CartLine(
                    menu_item_id=item.id,
                    name=item.name,
                    quantity=quantity,
                    price=item.price,
                    currency=item.currency,
                    unit=item.unit,
                    note=note,
                )
            )
        session.cart = cart
        self._mark_order_intent()
        return {"ok": True, "cart": _cart_public(session), "total": _cart_total(session)}

    def update_cart(self, args: dict[str, Any]) -> dict[str, Any]:
        self._mark_order_intent()
        session = self._session
        menu_item_id = str(args.get("menu_item_id") or "").strip()
        quantity = _parse_quantity(args.get("quantity"))
        if quantity is None or not 1 <= quantity <= 50:
            return {"ok": False, "error": "invalid_quantity"}
        note = args.get("note")
        note_arg = None if note is None else str(note)
        index = _find_cart_index(session, menu_item_id, note_arg)
        if index == -2:
            return {"ok": False, "error": "ambiguous_line"}
        if index < 0:
            return {"ok": False, "error": "not_in_cart"}
        session.cart[index].quantity = quantity
        if note is not None:
            session.cart[index].note = str(note).strip()
        self._mark_order_intent()
        return {"ok": True, "cart": _cart_public(session), "total": _cart_total(session)}

    def remove_from_cart(self, args: dict[str, Any]) -> dict[str, Any]:
        self._mark_order_intent()
        session = self._session
        menu_item_id = str(args.get("menu_item_id") or "").strip()
        note = args.get("note")
        if note is None:
            kept = [line for line in session.cart if line.menu_item_id != menu_item_id]
            if len(kept) == len(session.cart):
                return {"ok": False, "error": "not_in_cart"}
            session.cart = kept
        else:
            index = _find_cart_index(session, menu_item_id, str(note))
            if index < 0:
                return {"ok": False, "error": "not_in_cart"}
            del session.cart[index]
        self._mark_order_intent()
        return {"ok": True, "cart": _cart_public(session), "total": _cart_total(session)}

    def set_fulfillment(self, args: dict[str, Any]) -> dict[str, Any]:
        self._mark_order_intent()
        session = self._session
        fulfillment = str(args.get("fulfillment") or "").strip().lower()
        if fulfillment not in {"delivery", "pickup"}:
            return {"ok": False, "error": "invalid_fulfillment"}
        if fulfillment == "pickup":
            branch_id = str(getattr(session, "selected_branch_id", "") or "")
            if not branch_id:
                return {"ok": False, "error": "no_branch"}
            session.fulfillment = "pickup"
            session.delivery_address = ""
            session.delivery_phone = ""
            self._mark_order_intent()
            payload: dict[str, Any] = {
                "ok": True,
                "fulfillment": "pickup",
                "branch_name": getattr(session, "selected_branch_name", "") or "",
            }
            payload.update(_order_details_public(session))
            return payload
        address = str(args.get("delivery_address") or session.delivery_address or "").strip()
        if not address:
            return {"ok": False, "error": "no_delivery_address"}
        session.fulfillment = "delivery"
        session.delivery_address = address
        raw_delivery = str(args.get("delivery_phone") or "")
        if raw_delivery.strip():
            delivery_phone = normalize_customer_phone(raw_delivery)
            if not delivery_phone:
                return {"ok": False, "error": "invalid_delivery_phone"}
            session.delivery_phone = delivery_phone
        self._mark_order_intent()
        payload = {
            "ok": True,
            "fulfillment": "delivery",
            "delivery_address": address,
        }
        if session.delivery_phone:
            payload["delivery_phone"] = session.delivery_phone
        payload.update(_order_details_public(session))
        return payload

    def save_order_details(self, args: dict[str, Any]) -> dict[str, Any]:
        self._mark_order_intent()
        invalid = _apply_order_details(self._session, args)
        payload: dict[str, Any] = {"ok": True}
        if invalid:
            payload["ok"] = False
            payload["error"] = "invalid_fields"
            payload["fields"] = invalid
        payload.update(_order_details_public(self._session))
        self._mark_order_intent()
        return payload

    async def create_order(self, args: dict[str, Any]) -> dict[str, Any]:
        self._mark_order_intent()
        session = self._session
        restaurant_id = str(getattr(session, "restaurant_id", "") or "")
        if getattr(session, "restaurant_missing", False) or not restaurant_id:
            return {"ok": False, "error": "no_restaurant"}
        if not self._lock_sole_branch():
            return self._no_branch_payload()
        branch_id = str(getattr(session, "selected_branch_id", "") or "")
        if getattr(session, "order_created", False):
            return {
                "ok": True,
                "already_created": True,
                "branch_name": getattr(session, "selected_branch_name", "") or "",
            }
        cart = list(getattr(session, "cart", None) or [])
        if not cart:
            return {"ok": False, "error": "empty_cart"}
        _apply_order_details(session, args)
        fulfillment = str(getattr(session, "fulfillment", "") or "").strip().lower()
        if fulfillment not in {"delivery", "pickup"}:
            return {"ok": False, "error": "no_fulfillment"}
        delivery_address = str(getattr(session, "delivery_address", "") or "").strip()
        if fulfillment == "delivery" and not delivery_address:
            return {"ok": False, "error": "no_delivery_address"}

        customer_name = str(getattr(session, "order_customer_name", "") or "").strip()
        phone_number = str(getattr(session, "order_customer_phone", "") or "").strip()
        order_note = str(getattr(session, "order_note", "") or "").strip()
        booking_date = str(getattr(session, "order_booking_date", "") or "").strip()
        booking_time = str(getattr(session, "order_booking_time", "") or "").strip() or None

        missing: list[str] = []
        if not customer_name:
            missing.append("customer_name")
        if not phone_number:
            missing.append("phone_number")
        if not _DATE_RE.fullmatch(booking_date):
            missing.append("booking_date")
        if not booking_time:
            missing.append("booking_time")
        if missing:
            payload = {
                "ok": False,
                "error": "missing_fields",
                "fields": missing,
            }
            payload.update(_order_details_public(session))
            return payload

        note_parts: list[str] = []
        if order_note:
            note_parts.append(order_note)
        items = []
        for line in cart:
            items.append(
                {
                    "menu_item_id": line.menu_item_id,
                    "quantity": line.quantity,
                }
            )
            if line.note:
                note_parts.append(line.note)
        note = "; ".join(note_parts)

        body: dict[str, Any] = {
            "restaurant_id": restaurant_id,
            "branch_id": branch_id,
            "fulfillment": fulfillment,
            "customer_name": customer_name,
            "customer_phone": phone_number,
            "booking_date": booking_date,
            "booking_time": booking_time,
            "items": items,
        }
        if fulfillment == "delivery":
            body["delivery_address"] = delivery_address
            delivery_phone = str(getattr(session, "delivery_phone", "") or "").strip()
            if delivery_phone:
                body["delivery_phone"] = delivery_phone
        if note:
            body["note"] = note

        result = await self._client.create_order(body)
        if not result.ok:
            return {"ok": False, "error": result.error or "order_failed"}
        session.order_created = True
        self._mark_order_intent()
        order_id = str((result.data or {}).get("id") or "").strip()
        payload = {
            "ok": True,
            "customer_name": customer_name,
            "phone_number": phone_number,
            "fulfillment": fulfillment,
            "branch_name": getattr(session, "selected_branch_name", "") or "",
            "cart": _cart_public(session),
            "total": _cart_total(session),
            "note": note,
            "payment": "cod",
            "booking_date": booking_date,
            "booking_time": booking_time,
        }
        if order_id:
            payload["order_id"] = order_id
        if fulfillment == "delivery":
            payload["delivery_address"] = delivery_address
            delivery_phone = str(getattr(session, "delivery_phone", "") or "").strip()
            payload["delivery_phone"] = delivery_phone or phone_number
        return payload
