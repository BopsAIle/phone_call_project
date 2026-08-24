from __future__ import annotations

from datetime import date, time

from shared.models import SlotDelta


def delta_from_llm(
    *,
    guest_count: int | None = None,
    date_value: str | None = None,
    time_value: str | None = None,
    branch: str | None = None,
    customer_name: str | None = None,
    phone: str | None = None,
    notes: str | None = None,
) -> SlotDelta:
    parsed_date = None
    if date_value:
        parsed_date = date.fromisoformat(date_value[:10])
    parsed_time = None
    if time_value:
        parts = time_value.strip().split(":")
        parsed_time = time(int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)
    return SlotDelta(
        guest_count=guest_count,
        date=parsed_date,
        time=parsed_time,
        branch=branch,
        customer_name=customer_name,
        phone=phone,
        notes=notes,
    )
