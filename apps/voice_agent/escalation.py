from __future__ import annotations

import re

from apps.voice_agent.extractor import fold_vi
from shared.models import CallSession

TRANSFER_PATTERNS = (
    r"gap nhan vien",
    r"gap nguoi",
    r"noi chuyen voi nguoi",
    r"chuyen may",
    r"gap quan ly",
    r"hoa don cong ty",
    r"xuat hoa don",
    r"tiec cuoi",
    r"su kien",
    r"set menu",
    r"di ung",
    r"khieu nai",
    r"complaint",
    r"manager",
)

FAQ_PATTERNS = (
    r"gio mo",
    r"mo cua",
    r"gui xe",
    r"parking",
    r"huy ban",
    r"chinh sach huy",
    r"tre em",
    r"ghe tre",
    r"dress",
    r"trang phuc",
    r"chi nhanh",
    r"dia chi",
    r"o dau",
)

_TRANSFER_RE = re.compile("|".join(TRANSFER_PATTERNS), re.IGNORECASE)
_FAQ_RE = re.compile("|".join(FAQ_PATTERNS), re.IGNORECASE)


def match_transfer_reason(user_text: str, session: CallSession, large_party: int = 12) -> str | None:
    folded = fold_vi(user_text)
    if _TRANSFER_RE.search(folded):
        if "tiec cuoi" in folded or "su kien" in folded or "set menu" in folded:
            return "complex_event"
        if "gap" in folded or "chuyen may" in folded or "quan ly" in folded:
            return "guest_requested_human"
        if "di ung" in folded or "khieu nai" in folded:
            return "complex_request"
        if "hoa don" in folded:
            return "invoice_request"
        return "complex_request"
    if session.slots.guest_count and session.slots.guest_count > large_party:
        return "large_party"
    if session.availability_fail_count >= 2 and re.search(r"khong|thoi|khac duoc", folded):
        return "availability_exhausted"
    if session.stt_fail_count >= 3:
        return "stt_failures"
    return None


def looks_like_faq(user_text: str) -> bool:
    return bool(_FAQ_RE.search(fold_vi(user_text)))
