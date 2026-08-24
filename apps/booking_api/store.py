from __future__ import annotations

from datetime import date, time

from shared.models import BookingRecord, CallSession

BRANCHES = {
    "quan-1": {"name": "Quận 1", "capacity": 40, "address": "22 Đồng Khởi, Quận 1"},
    "thao-dien": {"name": "Thảo Điền", "capacity": 24, "address": "115 Nguyễn Văn Hưởng, Thảo Điền"},
}

DEFAULT_BRANCH = "quan-1"
OPENING = time(11, 0)
CLOSING = time(22, 0)
MAX_PARTY = 20
LARGE_PARTY = 12


class BookingStore:
    def __init__(self) -> None:
        self.sessions: dict[str, CallSession] = {}
        self.bookings: dict[str, BookingRecord] = {}
        # (branch, date_iso, time_iso) -> seats already taken
        self.occupancy: dict[tuple[str, str, str], int] = {}
        self._seed()

    def _seed(self) -> None:
        # Fully booked Christmas Eve dinner at Quận 1 — used by tests/demos.
        self.occupancy[("quan-1", "2026-12-24", "19:00:00")] = 40
        self.occupancy[("quan-1", "2026-12-24", "18:00:00")] = 10
        self.occupancy[("quan-1", "2026-12-24", "20:00:00")] = 8

    def reset(self) -> None:
        self.sessions.clear()
        self.bookings.clear()
        self.occupancy.clear()
        self._seed()

    def remaining(self, branch: str, day: date, slot: time) -> int:
        capacity = BRANCHES.get(branch, {}).get("capacity", 0)
        taken = self.occupancy.get(_occ_key(branch, day, slot), 0)
        return max(0, capacity - taken)

    def add_occupancy(self, branch: str, day: date, slot: time, guests: int) -> None:
        key = _occ_key(branch, day, slot)
        self.occupancy[key] = self.occupancy.get(key, 0) + guests


def _occ_key(branch: str, day: date, slot: time) -> tuple[str, str, str]:
    return (branch, day.isoformat(), slot.replace(microsecond=0).isoformat())


store = BookingStore()
