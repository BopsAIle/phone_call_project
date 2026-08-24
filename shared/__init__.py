"""Shared booking schema for the voice agent and mock booking API."""

from shared.models import (
    BOOKING_SOURCE,
    AvailabilityResponse,
    BookingRecord,
    BookingSlots,
    CallSession,
    SlotDelta,
    TimeAlternative,
    TranscriptTurn,
)
from shared.slots import (
    AVAILABILITY_KEYS,
    has_availability_keys,
    missing_fields,
    normalize_branch,
    touches_availability_keys,
)

__all__ = [
    "AVAILABILITY_KEYS",
    "BOOKING_SOURCE",
    "AvailabilityResponse",
    "BookingRecord",
    "BookingSlots",
    "CallSession",
    "SlotDelta",
    "TimeAlternative",
    "TranscriptTurn",
    "has_availability_keys",
    "missing_fields",
    "normalize_branch",
    "touches_availability_keys",
]
