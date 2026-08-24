from __future__ import annotations

import datetime as dt
from typing import Literal, Optional

from pydantic import BaseModel, Field

BOOKING_SOURCE = "Phone AI"

SessionStatus = Literal["collecting", "ready_to_confirm", "booked", "transferred"]


class TranscriptTurn(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str
    ts: dt.datetime = Field(default_factory=lambda: dt.datetime.now(dt.timezone.utc))


class BookingSlots(BaseModel):
    guest_count: Optional[int] = None
    date: Optional[dt.date] = None
    time: Optional[dt.time] = None
    branch: Optional[str] = None
    customer_name: Optional[str] = None
    phone: Optional[str] = None
    notes: Optional[str] = None
    source: str = BOOKING_SOURCE


class SlotDelta(BaseModel):
    guest_count: Optional[int] = None
    date: Optional[dt.date] = None
    time: Optional[dt.time] = None
    branch: Optional[str] = None
    customer_name: Optional[str] = None
    phone: Optional[str] = None
    notes: Optional[str] = None

    def has_any(self) -> bool:
        return any(
            value is not None
            for value in (
                self.guest_count,
                self.date,
                self.time,
                self.branch,
                self.customer_name,
                self.phone,
                self.notes,
            )
        )


class CallSession(BaseModel):
    id: str
    call_sid: Optional[str] = None
    from_number: Optional[str] = None
    recording_id: Optional[str] = None
    multi_branch: bool = True
    slots: BookingSlots = Field(default_factory=BookingSlots)
    transcript: list[TranscriptTurn] = Field(default_factory=list)
    availability_fail_count: int = 0
    stt_fail_count: int = 0
    transferred: bool = False
    transfer_reason: Optional[str] = None
    booking_id: Optional[str] = None
    status: SessionStatus = "collecting"
    created_at: dt.datetime = Field(default_factory=lambda: dt.datetime.now(dt.timezone.utc))


class TimeAlternative(BaseModel):
    date: dt.date
    time: dt.time
    branch: str


class AvailabilityResponse(BaseModel):
    available: bool
    guest_count: int
    date: dt.date
    time: dt.time
    branch: str
    remaining_seats: int
    alternatives: list[TimeAlternative] = Field(default_factory=list)
    message: str = ""


class BookingRecord(BaseModel):
    id: str
    session_id: str
    slots: BookingSlots
    transcript: list[TranscriptTurn] = Field(default_factory=list)
    recording_id: Optional[str] = None
    source: str = BOOKING_SOURCE
    created_at: dt.datetime = Field(default_factory=lambda: dt.datetime.now(dt.timezone.utc))
