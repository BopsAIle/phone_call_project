from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from shared.models import CallSession, SlotDelta

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

_WEEKDAYS = {
    "thu hai": 0,
    "thu 2": 0,
    "thu ba": 1,
    "thu 3": 1,
    "thu tu": 2,
    "thu 4": 2,
    "thu nam": 3,
    "thu 5": 3,
    "thu sau": 4,
    "thu 6": 4,
    "thu bay": 5,
    "thu 7": 5,
    "chu nhat": 6,
    "cn": 6,
}

_CONFIRM_RE = re.compile(
    r"\b(duoc|ok|chot|dung roi|dung roi|yes|vang|dong y|chot giup|uh|um)\b",
    re.IGNORECASE,
)
_DENY_RE = re.compile(
    r"\b(khong|thoi|doi|khac|khong duoc|huy)\b",
    re.IGNORECASE,
)


def fold_vi(text: str) -> str:
    """Lowercase and strip Vietnamese diacritics for matching."""
    table = str.maketrans(
        "áàảãạăắằẳẵặâấầẩẫậéèẻẽẹêếềểễệíìỉĩịóòỏõọôốồổỗộơớờởỡợúùủũụưứừửữựýỳỷỹỵđ"
        "ÁÀẢÃẠĂẮẰẲẴẶÂẤẦẨẪẬÉÈẺẼẸÊẾỀỂỄỆÍÌỈĨỊÓÒỎÕỌÔỐỒỔỖỘƠỚỜỞỠỢÚÙỦŨỤƯỨỪỬỮỰÝỲỶỸỴĐ",
        "aaaaaaaaaaaaaaaaaeeeeeeeeeeeiiiiiooooooooooooooooouuuuuuuuuuuyyyyyd"
        "AAAAAAAAAAAAAAAAAEEEEEEEEEEEIIIIIOOOOOOOOOOOOOOOOOUUUUUUUUUUUYYYYYD",
    )
    return text.translate(table).lower()


class HeuristicExtractor:
    """Deterministic Vietnamese slot extractor used by tests and text mode."""

    def __init__(self, today: date | None = None) -> None:
        self.today = today or datetime.now(VN_TZ).date()

    def extract(self, user_text: str, session: CallSession | None = None) -> SlotDelta:
        folded = fold_vi(user_text)
        original = user_text
        return SlotDelta(
            guest_count=_guest_count(folded),
            date=_date(folded, self.today),
            time=_time(folded),
            branch=_branch(folded),
            customer_name=_name(original, folded),
            phone=_phone(original),
            notes=_notes(folded, original),
        )


def is_confirm(user_text: str) -> bool:
    return bool(_CONFIRM_RE.search(fold_vi(user_text)))


def is_deny(user_text: str) -> bool:
    return bool(_DENY_RE.search(fold_vi(user_text)))


def _guest_count(folded: str) -> int | None:
    match = re.search(r"(\d+)\s*(nguoi|khach|pax)", folded)
    if match:
        return int(match.group(1))
    match = re.search(r"(ban|dat)\s+(\d+)", folded)
    if match:
        return int(match.group(2))
    return None


def _date(folded: str, today: date) -> date | None:
    if re.search(r"\bhom nay\b|\bnay\b", folded) and "ngay mai" not in folded:
        if "hom nay" in folded:
            return today
    if "ngay mai" in folded or re.search(r"\bmai\b", folded):
        return today + timedelta(days=1)
    if "ngay kia" in folded:
        return today + timedelta(days=2)
    if "cuoi tuan" in folded:
        delta = (5 - today.weekday()) % 7
        return today + timedelta(days=delta or 7)

    for label, weekday in _WEEKDAYS.items():
        if label in folded:
            delta = (weekday - today.weekday()) % 7
            return today + timedelta(days=delta)

    match = re.search(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b", folded)
    if match:
        day_n, month_n, year_s = match.groups()
        year = today.year if not year_s else int(year_s)
        if year < 100:
            year += 2000
        return date(year, int(month_n), int(day_n))

    match = re.search(r"ngay\s+(\d{1,2})\s+thang\s+(\d{1,2})", folded)
    if match:
        return date(today.year, int(match.group(2)), int(match.group(1)))
    return None


def _time(folded: str) -> time | None:
    period_evening = bool(re.search(r"toi|chieu|dem", folded))
    period_morning = bool(re.search(r"sang", folded))

    match = re.search(r"\b(\d{1,2}):(\d{2})\b", folded)
    if match:
        hour, minute = int(match.group(1)), int(match.group(2))
        return time(hour, minute)

    match = re.search(r"\b(\d{1,2})\s*h(?:\s*(\d{2}))?", folded)
    if not match:
        match = re.search(r"\b(\d{1,2})\s*gio(?:\s*(\d{2}))?", folded)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2) or 0)
        if period_evening and hour <= 11:
            hour += 12
        elif period_morning:
            pass
        elif 1 <= hour <= 10:
            hour += 12
        if hour == 24:
            hour = 0
        return time(hour, minute)
    return None


def _branch(folded: str) -> str | None:
    if "thao dien" in folded or "q2" in folded or "quan 2" in folded:
        return "thao-dien"
    if "quan 1" in folded or "q1" in folded or "dong khoi" in folded:
        return "quan-1"
    return None


def _name(original: str, folded: str) -> str | None:
    match = re.search(
        r"(?:ten toi la|toi ten la|toi ten|ten minh la|ten la|\bten)\s+(.+)",
        folded,
    )
    if not match:
        return None
    stop = {"sdt", "so", "dien", "thoai", "quan", "ngay", "gio", "chi", "nhanh"}
    parts: list[str] = []
    for word in match.group(1).split():
        if word in stop or word[:1].isdigit():
            break
        parts.append(word)
        if len(parts) >= 3:
            break
    if not parts or parts[0] in {"toi", "minh", "la"}:
        return None
    return " ".join(parts).title()


def _phone(original: str) -> str | None:
    match = re.search(r"(\+?84|0)\d{8,10}", original.replace(" ", ""))
    if match:
        return match.group(0)
    match = re.search(r"(0\d{2,3}[\s.]?\d{3}[\s.]?\d{3,4})", original)
    if match:
        return re.sub(r"[\s.]", "", match.group(1))
    return None


def _notes(folded: str, original: str) -> str | None:
    hints: list[str] = []
    if "sinh nhat" in folded:
        hints.append("sinh nhat")
    if "ghe tre" in folded or "tre em" in folded:
        hints.append("ghe tre em")
    if "cua so" in folded or "view" in folded:
        hints.append("yeu cau vi tri")
    if "di ung" in folded:
        hints.append(original.strip())
    return "; ".join(hints) if hints else None
