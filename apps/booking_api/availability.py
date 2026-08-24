from __future__ import annotations

from datetime import date, datetime, time, timedelta

from apps.booking_api.store import BRANCHES, CLOSING, OPENING, store
from shared.models import AvailabilityResponse, TimeAlternative


def bucket_time(value: time) -> time:
    minute = 0 if value.minute < 30 else 30
    return time(value.hour, minute)


def within_hours(value: time) -> bool:
    return OPENING <= value <= CLOSING


def check_availability(
    guest_count: int,
    day: date,
    slot: time,
    branch: str,
) -> AvailabilityResponse:
    slot = bucket_time(slot)
    remaining = store.remaining(branch, day, slot)
    available = remaining >= guest_count
    alternatives: list[TimeAlternative] = []
    if not available:
        alternatives = suggest_alternatives(guest_count, day, slot, branch)
    message = (
        "Còn chỗ."
        if available
        else "Hết chỗ khung giờ này."
        + (f" Gợi ý: {len(alternatives)} khung thay thế." if alternatives else "")
    )
    return AvailabilityResponse(
        available=available,
        guest_count=guest_count,
        date=day,
        time=slot,
        branch=branch,
        remaining_seats=remaining,
        alternatives=alternatives,
        message=message.strip(),
    )


def suggest_alternatives(
    guest_count: int,
    day: date,
    slot: time,
    branch: str,
    limit: int = 3,
) -> list[TimeAlternative]:
    found: list[TimeAlternative] = []
    seen: set[tuple[str, str, str]] = set()

    def consider(candidate_day: date, candidate_time: time, candidate_branch: str) -> None:
        if len(found) >= limit:
            return
        candidate_time = bucket_time(candidate_time)
        if not within_hours(candidate_time):
            return
        key = (candidate_branch, candidate_day.isoformat(), candidate_time.isoformat())
        if key in seen:
            return
        seen.add(key)
        if candidate_day == day and candidate_time == slot and candidate_branch == branch:
            return
        if store.remaining(candidate_branch, candidate_day, candidate_time) >= guest_count:
            found.append(
                TimeAlternative(date=candidate_day, time=candidate_time, branch=candidate_branch)
            )

    for minutes in (-60, 60, -30, 30, -120, 120):
        consider(day, _shift_time(slot, minutes), branch)
    consider(day + timedelta(days=1), slot, branch)
    for other_branch in BRANCHES:
        if other_branch != branch:
            consider(day, slot, other_branch)
    return found


def _shift_time(value: time, minutes: int) -> time:
    base = datetime.combine(date(2000, 1, 1), value)
    shifted = base + timedelta(minutes=minutes)
    return shifted.time()
