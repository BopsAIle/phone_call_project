"""In-memory menu, cart, and order types for one call."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(frozen=True)
class MenuItem:
    id: str
    name: str
    price: Optional[float] = None
    currency: str = "VND"
    category: str = ""
    description: str = ""
    available: bool = True
    unit: str = ""


@dataclass
class CartLine:
    menu_item_id: str
    name: str
    quantity: int
    price: Optional[float] = None
    currency: str = "VND"
    unit: str = ""
    note: str = ""


@dataclass(frozen=True)
class MenuResult:
    ok: bool
    items: list[MenuItem] = field(default_factory=list)
    error: str = ""


@dataclass(frozen=True)
class OrderApiResult:
    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: str = ""


@dataclass(frozen=True)
class MenuMatchResult:
    status: str  # match | ambiguous | none
    menu_item_id: str = ""
    confidence: str = "low"  # high | low
    confirm_name: str = ""
    candidate_ids: tuple[str, ...] = ()
