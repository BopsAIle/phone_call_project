from __future__ import annotations

from dataclasses import dataclass

from shared.models import AvailabilityResponse, BookingSlots, CallSession
from shared.slots import (
    has_availability_keys,
    missing_fields,
    branch_label,
)


@dataclass
class BookingView:
    session: CallSession
    availability: AvailabilityResponse | None = None

    @property
    def slots(self) -> BookingSlots:
        return self.session.slots

    def missing(self) -> list[str]:
        return missing_fields(self.session.slots, self.session.multi_branch)

    def can_check_availability(self) -> bool:
        return has_availability_keys(self.session.slots, self.session.multi_branch)

    def human_summary(self) -> str:
        slots = self.session.slots
        parts = []
        if slots.guest_count:
            parts.append(f"{slots.guest_count} khach")
        if slots.date:
            parts.append(f"ngay {slots.date.isoformat()}")
        if slots.time:
            parts.append(f"luc {slots.time.strftime('%H:%M')}")
        if slots.branch:
            parts.append(f"chi nhanh {branch_label(slots.branch)}")
        if slots.customer_name:
            parts.append(f"ten {slots.customer_name}")
        if slots.phone:
            parts.append(f"SDT {slots.phone}")
        if slots.notes:
            parts.append(f"ghi chu {slots.notes}")
        return ", ".join(parts)
