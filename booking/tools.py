"""OpenAI tools: resolve_branch, confirm_branch, create_booking."""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from datetime import datetime, timedelta, timezone as dt_timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from booking.models import MatchResult

logger = logging.getLogger(__name__)

BOOKING_TOOL_NAMES = frozenset({"resolve_branch", "confirm_branch", "create_booking"})

BOOKING_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "resolve_branch",
            "description": (
                "Đưa lời người gọi cho model so với list chi nhánh đang có trong cuộc gọi. "
                "Gọi mỗi khi người gọi chọn hoặc nêu địa điểm, trước khi khẳng định chi nhánh đó tồn tại."
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
            "name": "confirm_branch",
            "description": (
                "Khóa chi nhánh sau khi người gọi xác nhận. branch_id phải lấy từ "
                "resolve_branch, không được bịa. Khi nói với khách chỉ nêu tên; "
                "chỉ đọc địa chỉ nếu họ hỏi."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "branch_id": {
                        "type": "string",
                        "description": "UUID chi nhánh trong danh mục.",
                    }
                },
                "required": ["branch_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_booking",
            "description": (
                "Tạo đặt bàn sau khi người gọi đã xác nhận mọi chi tiết. "
                "restaurant_id và branch_id lấy từ bộ nhớ phiên, không phải đối số."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_name": {"type": "string"},
                    "phone_number": {"type": "string"},
                    "party_size": {"type": "integer", "minimum": 1, "maximum": 50},
                    "booking_date": {
                        "type": "string",
                        "description": (
                            "Ngày đặt theo múi giờ nhà hàng. "
                            "YYYY-MM-DD, hoặc tomorrow / today / ngày mai / hôm nay."
                        ),
                    },
                    "booking_time": {
                        "type": "string",
                        "description": "HH:MM 24 giờ.",
                    },
                    "note": {"type": "string"},
                },
                "required": [
                    "customer_name",
                    "phone_number",
                    "party_size",
                    "booking_date",
                    "booking_time",
                ],
            },
        },
    },
]

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})(?::\d{2})?$")
_TIME_AMPM_RE = re.compile(r"^(\d{1,2})(?::(\d{2}))?(am|pm)$")
_TOMORROW_TYPOS = ("tommorw", "tommorow", "tommorrow", "tomorow", "tommrow", "tommorow")
_DAY_AFTER_RE = re.compile(r"\b(day after tomorrow|ngay kia)\b")
_TOMORROW_RE = re.compile(r"\b(tomorrow|tmrw|ngay mai)\b")
_TODAY_RE = re.compile(r"\b(today|tonight|hom nay|toi nay)\b")
_STANDALONE_MAI_RE = re.compile(r"(?<!thang )\bmai\b")


def _local_now(timezone: str) -> datetime:
    tz_name = timezone or "UTC"
    try:
        return datetime.now(ZoneInfo(tz_name))
    except Exception:
        logger.warning("Timezone %r unavailable; using UTC for booking dates.", timezone)
        return datetime.now(dt_timezone.utc)


def _fold_date_phrase(text: str) -> str:
    raw = (text or "").replace("Đ", "D").replace("đ", "d")
    raw = unicodedata.normalize("NFD", raw).casefold()
    raw = "".join(ch for ch in raw if unicodedata.category(ch) != "Mn")
    for typo in _TOMORROW_TYPOS:
        raw = raw.replace(typo, "tomorrow")
    raw = re.sub(r"[^\w\s]+", " ", raw)
    return re.sub(r"\s+", " ", raw).strip()


def _relative_date_offset(folded: str) -> Optional[int]:
    if not folded:
        return None
    if _DAY_AFTER_RE.search(folded):
        return 2
    if _TOMORROW_RE.search(folded) or _STANDALONE_MAI_RE.search(folded):
        return 1
    if _TODAY_RE.search(folded):
        return 0
    return None


def normalize_booking_date(raw: str, timezone: str = "UTC") -> Optional[str]:
    text = (raw or "").strip()
    if not text:
        return None
    if _DATE_RE.fullmatch(text):
        try:
            datetime.strptime(text, "%Y-%m-%d")
        except ValueError:
            return None
        return text
    offset = _relative_date_offset(_fold_date_phrase(text))
    if offset is None:
        return None
    return (_local_now(timezone).date() + timedelta(days=offset)).isoformat()


_RELATIVE_RAW_RE = re.compile(
    r"\b("
    r"day after tomorrow|tomorrow|tommorw|tommorow|tommorrow|tomorow|tommrow|tmrw|"
    r"ng[aà]y mai|ngay mai|h[oô]m nay|hom nay|t[oó]i nay|toi nay|"
    r"today|tonight|mai"
    r")\b",
    re.IGNORECASE,
)


def leftover_booking_time(raw: str) -> Optional[str]:
    remainder = _RELATIVE_RAW_RE.sub(" ", raw or "")
    remainder = re.sub(r"\s+", " ", remainder).strip(" ,;.-")
    if not remainder:
        return None
    return normalize_booking_time(remainder)


def resolve_booking_when(
    raw_date: str,
    raw_time: str,
    timezone: str = "UTC",
) -> tuple[Optional[str], Optional[str]]:
    """Turn spoken/tool date+time into YYYY-MM-DD and HH:MM in restaurant TZ."""
    booking_date = normalize_booking_date(raw_date, timezone)
    booking_time = normalize_booking_time(raw_time)
    if booking_date is None:
        booking_date = normalize_booking_date(raw_time, timezone)
    if booking_time is None:
        booking_time = leftover_booking_time(raw_date) or leftover_booking_time(raw_time)
    if booking_time is None:
        booking_time = normalize_booking_time(raw_date)
    return booking_date, booking_time


def normalize_booking_time(raw: str) -> Optional[str]:
    text = (raw or "").strip()
    match = _TIME_RE.fullmatch(text)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2))
        if hour > 23 or minute > 59:
            return None
        return f"{hour:02d}:{minute:02d}"
    compact = re.sub(r"[\s.]", "", text.lower())
    ampm = _TIME_AMPM_RE.fullmatch(compact)
    if ampm is None:
        return None
    hour = int(ampm.group(1))
    minute = int(ampm.group(2) or 0)
    if minute > 59 or hour > 12 or hour < 1:
        return None
    hour = hour % 12
    if ampm.group(3) == "pm":
        hour += 12
    return f"{hour:02d}:{minute:02d}"


def normalize_customer_phone(raw: str) -> str:
    return "".join(ch for ch in (raw or "") if ch.isdigit())


def _catalog_public(session: Any) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for branch in getattr(session, "branches", None) or []:
        rows.append(
            {
                "branch_id": branch.id,
                "name": branch.name,
            }
        )
    return rows


class BookingTools:
    def __init__(self, session: Any, client: Any, matcher: Any) -> None:
        self._session = session
        self._client = client
        self._matcher = matcher

    async def execute(self, name: str, arguments_json: str) -> str:
        try:
            args = json.loads(arguments_json) if arguments_json else {}
        except json.JSONDecodeError:
            args = {}
        if not isinstance(args, dict):
            args = {}
        try:
            if name == "resolve_branch":
                result = await self.resolve_branch(str(args.get("spoken_name") or ""))
            elif name == "confirm_branch":
                result = self.confirm_branch(str(args.get("branch_id") or ""))
            elif name == "create_booking":
                result = await self.create_booking(args)
            else:
                result = {"ok": False, "error": "unknown_tool"}
        except Exception:
            logger.exception("Booking tool %s failed", name)
            result = {"ok": False, "error": "tool_failed"}
        logger.info(
            "Booking tool %s status=%s error=%s",
            name,
            result.get("ok", result.get("status")),
            result.get("error") or result.get("reason") or "-",
        )
        return json.dumps(result, ensure_ascii=False)

    async def resolve_branch(self, spoken_name: str) -> dict[str, Any]:
        session = self._session
        catalog = _catalog_public(session)
        if getattr(session, "restaurant_missing", False) or not getattr(session, "restaurant_id", ""):
            return {
                "status": "none",
                "locked": False,
                "reason": "no_restaurant",
                "available_branches": catalog,
            }
        spoken = (spoken_name or "").strip()
        if not spoken:
            return {
                "status": "none",
                "locked": False,
                "reason": "empty_name",
                "available_branches": catalog,
            }
        branches = list(getattr(session, "branches", None) or [])
        if not branches:
            return {
                "status": "none",
                "locked": False,
                "reason": "no_branches",
                "available_branches": catalog,
            }
        if self._matcher is None:
            matched = MatchResult(status="none")
        else:
            matched = await self._matcher.match(spoken, branches)
        locked = False
        if (
            matched.status == "match"
            and matched.confidence == "high"
            and matched.branch_id
        ):
            locked = session.select_branch(matched.branch_id) is not None
        payload: dict[str, Any] = {
            "status": matched.status,
            "locked": locked,
            "confidence": matched.confidence,
            "confirm_name": matched.confirm_name,
            "branch_id": matched.branch_id or None,
            "available_branches": catalog,
        }
        if matched.status == "ambiguous":
            names = []
            by_id = {b.id: b for b in branches}
            for cid in matched.candidate_ids:
                branch = by_id.get(cid)
                if branch is not None:
                    names.append({"branch_id": branch.id, "name": branch.name})
            payload["candidates"] = names
        if matched.status == "match" and not locked:
            payload["need_confirm"] = True
        return payload

    def confirm_branch(self, branch_id: str) -> dict[str, Any]:
        session = self._session
        branch = session.select_branch((branch_id or "").strip())
        if branch is None:
            return {
                "ok": False,
                "error": "unknown_branch",
                "available_branches": _catalog_public(session),
            }
        return {
            "ok": True,
            "locked": True,
            "confirm_name": branch.name,
            "note": "Chỉ nói tên chi nhánh với khách. Không đọc địa chỉ trừ khi họ hỏi ở đâu.",
        }

    async def create_booking(self, args: dict[str, Any]) -> dict[str, Any]:
        session = self._session
        session.intent = "booking"
        refresh = getattr(session, "refresh_system_prompt", None)
        if refresh is not None:
            refresh()
        restaurant_id = str(getattr(session, "restaurant_id", "") or "")
        branch_id = str(getattr(session, "selected_branch_id", "") or "")
        if getattr(session, "restaurant_missing", False) or not restaurant_id:
            return {"ok": False, "error": "no_restaurant"}
        if not branch_id:
            return {"ok": False, "error": "no_branch"}
        if getattr(session, "booking_created", False):
            return {
                "ok": True,
                "already_created": True,
                "branch_name": getattr(session, "selected_branch_name", "") or "",
            }

        customer_name = str(args.get("customer_name") or "").strip()
        phone_number = normalize_customer_phone(
            str(args.get("phone_number") or args.get("customer_phone") or "")
        )
        note = str(args.get("note") or "").strip()
        tz = str(getattr(session, "timezone", "") or "UTC")
        booking_date, booking_time = resolve_booking_when(
            str(args.get("booking_date") or "").strip(),
            str(args.get("booking_time") or "").strip(),
            tz,
        )

        try:
            party_size = int(args.get("party_size"))
        except (TypeError, ValueError):
            return {"ok": False, "error": "invalid_party_size"}

        missing: list[str] = []
        if not customer_name:
            missing.append("customer_name")
        if not phone_number:
            missing.append("phone_number")
        if not booking_date:
            missing.append("booking_date")
        if not booking_time:
            missing.append("booking_time")
        if missing:
            return {"ok": False, "error": "missing_fields", "fields": missing}
        if not 1 <= party_size <= 50:
            return {"ok": False, "error": "invalid_party_size"}

        body: dict[str, Any] = {
            "restaurant_id": restaurant_id,
            "branch_id": branch_id,
            "customer_name": customer_name,
            "customer_phone": phone_number,
            "party_size": party_size,
            "booking_date": booking_date,
            "booking_time": booking_time,
        }
        if note:
            body["note"] = note

        result = await self._client.create_booking(body)
        if not result.ok:
            return {"ok": False, "error": result.error or "booking_failed"}
        session.booking_created = True
        return {
            "ok": True,
            "customer_name": customer_name,
            "phone_number": phone_number,
            "party_size": party_size,
            "booking_date": booking_date,
            "booking_time": booking_time,
            "note": note,
            "branch_name": getattr(session, "selected_branch_name", "") or "",
        }
