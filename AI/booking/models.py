"""In-memory restaurant / branch / booking types for one call."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(frozen=True)
class Branch:
    id: str
    name: str
    address: str = ""
    opening_time: str = ""
    closing_time: str = ""
    status: str = "active"


@dataclass(frozen=True)
class Restaurant:
    id: str
    name: str
    phone: str = ""
    status: str = "active"
    branches: list[Branch] = field(default_factory=list)


@dataclass(frozen=True)
class HotlineResult:
    restaurant: Optional[Restaurant] = None
    missing: bool = False
    error: str = ""


@dataclass(frozen=True)
class BookingApiResult:
    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: str = ""


@dataclass(frozen=True)
class MatchResult:
    status: str  # match | ambiguous | none
    branch_id: str = ""
    confidence: str = "low"  # high | low
    confirm_name: str = ""
    candidate_ids: tuple[str, ...] = ()
