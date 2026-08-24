from __future__ import annotations

from datetime import date, time
from typing import Any

import httpx

from shared.models import (
    AvailabilityResponse,
    BookingRecord,
    BookingSlots,
    CallSession,
    SlotDelta,
    TranscriptTurn,
)


class BackendClient:
    """HTTP client for the booking backend (real or in-repo mock)."""

    def __init__(self, base_url: str, client: httpx.AsyncClient | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(base_url=self.base_url, timeout=10.0)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def create_session(
        self,
        *,
        call_sid: str | None = None,
        from_number: str | None = None,
        recording_id: str | None = None,
        multi_branch: bool = True,
    ) -> CallSession:
        response = await self._client.post(
            "/v1/call-sessions",
            json={
                "call_sid": call_sid,
                "from_number": from_number,
                "recording_id": recording_id,
                "multi_branch": multi_branch,
            },
        )
        response.raise_for_status()
        return CallSession.model_validate(response.json())

    async def get_session(self, session_id: str) -> CallSession:
        response = await self._client.get(f"/v1/call-sessions/{session_id}")
        response.raise_for_status()
        return CallSession.model_validate(response.json())

    async def patch_slots(self, session_id: str, delta: SlotDelta) -> dict[str, Any]:
        response = await self._client.patch(
            f"/v1/call-sessions/{session_id}/slots",
            json=_jsonable(delta.model_dump(exclude_none=True)),
        )
        response.raise_for_status()
        return response.json()

    async def check_availability(
        self,
        *,
        session_id: str | None,
        guest_count: int,
        day: date,
        slot: time,
        branch: str,
    ) -> AvailabilityResponse:
        response = await self._client.post(
            "/v1/availability/check",
            json={
                "session_id": session_id,
                "guest_count": guest_count,
                "date": day.isoformat(),
                "time": slot.isoformat(),
                "branch": branch,
            },
        )
        response.raise_for_status()
        return AvailabilityResponse.model_validate(response.json())

    async def create_booking(
        self,
        *,
        session_id: str,
        slots: BookingSlots,
        transcript: list[TranscriptTurn],
        recording_id: str | None,
    ) -> BookingRecord:
        response = await self._client.post(
            "/v1/bookings",
            json={
                "session_id": session_id,
                "slots": _jsonable(slots.model_dump()),
                "transcript": [_jsonable(t.model_dump()) for t in transcript],
                "recording_id": recording_id,
                "source": slots.source,
            },
        )
        response.raise_for_status()
        return BookingRecord.model_validate(response.json())

    async def transfer(self, session_id: str, reason: str, summary: str | None = None) -> CallSession:
        response = await self._client.post(
            f"/v1/call-sessions/{session_id}/transfer",
            json={"reason": reason, "summary": summary},
        )
        response.raise_for_status()
        return CallSession.model_validate(response.json())

    async def set_recording(self, session_id: str, recording_id: str) -> CallSession:
        response = await self._client.patch(
            f"/v1/call-sessions/{session_id}/recording",
            json={"recording_id": recording_id},
        )
        response.raise_for_status()
        return CallSession.model_validate(response.json())

    async def set_recording_by_call_sid(self, call_sid: str, recording_id: str) -> CallSession:
        response = await self._client.patch(
            f"/v1/recordings/by-call/{call_sid}",
            json={"recording_id": recording_id},
        )
        response.raise_for_status()
        return CallSession.model_validate(response.json())

    async def append_transcript(self, session_id: str, role: str, content: str) -> CallSession:
        response = await self._client.post(
            f"/v1/call-sessions/{session_id}/transcript",
            json={"role": role, "content": content},
        )
        response.raise_for_status()
        return CallSession.model_validate(response.json())


def _jsonable(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    return value
