"""Typed request drafts, filled a field at a time across turns.

Every field is optional because slots arrive conversationally. Full validation
happens at the API boundary in `to_request()`, not on assignment.

The model resolves natural language ("next Friday", "eight-ish") against the
store-local time in its system prompt and emits ISO values here. This module
validates; it does not parse natural language.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import UTC, datetime
from datetime import date as date_cls
from datetime import time as time_cls
from typing import Any, ClassVar, Optional
from zoneinfo import ZoneInfo

from pydantic import BaseModel, field_validator

logger = logging.getLogger(__name__)

MAX_PARTY_SIZE = 20
MAX_DAYS_AHEAD = 365
_DIGITS = re.compile(r"\d")
_PHONE_ALLOWED = re.compile(r"^\+?[\d\s\-().]{6,25}$")


def date_problem(value: str, timezone: str) -> Optional[str]:
    """Catch a date the model resolved wrongly, e.g. last year's "next Friday".

    Uses the same store clock and the same UTC fallback as `build_system_prompt`,
    so the prompt and this check can never disagree about what "today" is.
    """
    try:
        parsed = date_cls.fromisoformat(value)
    except ValueError:
        return "date must be ISO format YYYY-MM-DD"
    try:
        today = datetime.now(ZoneInfo(timezone or "UTC")).date()
    except Exception:
        logger.warning("Timezone %r unavailable; using UTC. Is tzdata installed?", timezone)
        today = datetime.now(UTC).date()
    if parsed < today:
        return f"date {value} is in the past; today is {today.isoformat()}"
    if (parsed - today).days > MAX_DAYS_AHEAD:
        return f"date {value} is more than {MAX_DAYS_AHEAD} days away"
    return None


class RequestDraft(BaseModel):
    """Shared behaviour: what is missing, and a fingerprint of what is set."""

    REQUIRED: ClassVar[tuple[str, ...]] = ()

    def missing(self) -> list[str]:
        return [name for name in self.REQUIRED if getattr(self, name, None) in (None, "")]

    def is_complete(self) -> bool:
        return not self.missing()

    def fingerprint(self) -> str:
        """Stable hash of the values as they stand.

        Confirmation is recorded against this, so changing any field silently
        invalidates it — there is no flag to forget to reset.
        """
        payload = json.dumps(self.model_dump(exclude_none=True), sort_keys=True, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def to_request(self) -> dict[str, Any]:
        missing = self.missing()
        if missing:
            raise ValueError(f"incomplete: {', '.join(missing)}")
        return self.model_dump(exclude_none=True)

    def apply(self, values: dict[str, Any]) -> "RequestDraft":
        """Merge non-empty values, returning a new validated draft."""
        merged = self.model_dump(exclude_none=True)
        for key, value in values.items():
            if value is None or value == "":
                continue
            if key in type(self).model_fields:
                merged[key] = value
        return type(self)(**merged)


class BookingSlots(RequestDraft):
    REQUIRED: ClassVar[tuple[str, ...]] = ("date", "time", "party_size", "name", "phone")

    date: Optional[str] = None
    time: Optional[str] = None
    party_size: Optional[int] = None
    name: Optional[str] = None
    phone: Optional[str] = None

    @field_validator("date")
    @classmethod
    def _check_date(cls, value: str) -> str:
        try:
            date_cls.fromisoformat(value)
        except ValueError:
            raise ValueError("date must be ISO format YYYY-MM-DD")
        return value

    @field_validator("time")
    @classmethod
    def _check_time(cls, value: str) -> str:
        try:
            time_cls.fromisoformat(value)
        except ValueError:
            raise ValueError("time must be 24-hour HH:MM")
        return value

    @field_validator("party_size")
    @classmethod
    def _check_party(cls, value: int) -> int:
        if value < 1 or value > MAX_PARTY_SIZE:
            raise ValueError(f"party_size must be between 1 and {MAX_PARTY_SIZE}")
        return value

    @field_validator("phone")
    @classmethod
    def _check_phone(cls, value: str) -> str:
        return _validate_phone(value)


class DeliverySlots(RequestDraft):
    REQUIRED: ClassVar[tuple[str, ...]] = ("address", "items", "name", "phone")

    address: Optional[str] = None
    items: Optional[str] = None
    name: Optional[str] = None
    phone: Optional[str] = None

    @field_validator("phone")
    @classmethod
    def _check_phone(cls, value: str) -> str:
        return _validate_phone(value)


def _validate_phone(value: str) -> str:
    value = value.strip()
    if not _PHONE_ALLOWED.match(value) or len(_DIGITS.findall(value)) < 7:
        raise ValueError("phone must be a real number with at least 7 digits")
    return value
