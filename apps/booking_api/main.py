from __future__ import annotations

import datetime as dt
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from apps.booking_api.availability import (
    bucket_time,
    check_availability,
    within_hours,
)
from apps.booking_api.store import (
    BRANCHES,
    DEFAULT_BRANCH,
    LARGE_PARTY,
    MAX_PARTY,
    store,
)
from shared.models import (
    BOOKING_SOURCE,
    AvailabilityResponse,
    BookingRecord,
    BookingSlots,
    CallSession,
    SlotDelta,
    TranscriptTurn,
)
from shared.slots import (
    apply_delta,
    has_availability_keys,
    missing_fields,
    normalize_branch,
)

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

app = FastAPI(title="Restaurant Booking API", version="0.1.0")


class CreateSessionRequest(BaseModel):
    call_sid: str | None = None
    from_number: str | None = None
    recording_id: str | None = None
    multi_branch: bool = True


class SlotPatchResponse(BaseModel):
    session: CallSession
    missing_fields: list[str]
    validation_errors: list[str] = Field(default_factory=list)
    should_transfer: bool = False
    transfer_reason: str | None = None


class AvailabilityRequest(BaseModel):
    session_id: str | None = None
    guest_count: int
    date: dt.date
    time: dt.time
    branch: str


class CreateBookingRequest(BaseModel):
    session_id: str
    slots: BookingSlots | None = None
    transcript: list[TranscriptTurn] = Field(default_factory=list)
    recording_id: str | None = None
    source: str = BOOKING_SOURCE


class TransferRequest(BaseModel):
    reason: str
    summary: str | None = None


class RecordingUpdate(BaseModel):
    recording_id: str


class TranscriptAppend(BaseModel):
    role: str
    content: str


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/call-sessions", response_model=CallSession)
def create_session(body: CreateSessionRequest) -> CallSession:
    session_id = str(uuid4())
    slots = BookingSlots()
    if not body.multi_branch:
        slots.branch = DEFAULT_BRANCH
    phone = _usable_caller_id(body.from_number)
    if phone:
        slots.phone = phone
    session = CallSession(
        id=session_id,
        call_sid=body.call_sid,
        from_number=body.from_number,
        recording_id=body.recording_id,
        multi_branch=body.multi_branch,
        slots=slots,
    )
    store.sessions[session_id] = session
    return session


@app.get("/v1/call-sessions/{session_id}", response_model=CallSession)
def get_session(session_id: str) -> CallSession:
    return _get_session(session_id)


@app.patch("/v1/call-sessions/{session_id}/slots", response_model=SlotPatchResponse)
def patch_slots(session_id: str, delta: SlotDelta) -> SlotPatchResponse:
    session = _get_session(session_id)
    errors: list[str] = []
    normalized = _normalize_delta(delta, errors)
    if errors:
        return SlotPatchResponse(
            session=session,
            missing_fields=missing_fields(session.slots, session.multi_branch),
            validation_errors=errors,
        )
    session.slots = apply_delta(session.slots, normalized)
    should_transfer = False
    transfer_reason = None
    if session.slots.guest_count is not None and session.slots.guest_count > LARGE_PARTY:
        should_transfer = True
        transfer_reason = "large_party"
    missing = missing_fields(session.slots, session.multi_branch)
    return SlotPatchResponse(
        session=session,
        missing_fields=missing,
        validation_errors=[],
        should_transfer=should_transfer,
        transfer_reason=transfer_reason,
    )


@app.post("/v1/availability/check", response_model=AvailabilityResponse)
def availability_check(body: AvailabilityRequest) -> AvailabilityResponse:
    branch = normalize_branch(body.branch) or body.branch
    if branch not in BRANCHES:
        raise HTTPException(status_code=400, detail=f"Unknown branch: {body.branch}")
    if body.guest_count < 1 or body.guest_count > MAX_PARTY:
        raise HTTPException(status_code=400, detail="guest_count must be 1-20")
    result = check_availability(body.guest_count, body.date, body.time, branch)
    if body.session_id and body.session_id in store.sessions:
        session = store.sessions[body.session_id]
        if not result.available:
            session.availability_fail_count += 1
        elif has_availability_keys(session.slots, session.multi_branch):
            if not missing_fields(session.slots, session.multi_branch):
                session.status = "ready_to_confirm"
    return result


@app.post("/v1/bookings", response_model=BookingRecord)
def create_booking(body: CreateBookingRequest) -> BookingRecord:
    session = _get_session(body.session_id)
    slots = body.slots or session.slots
    missing = missing_fields(slots, session.multi_branch)
    if missing:
        raise HTTPException(status_code=400, detail={"missing_fields": missing})
    if session.transferred:
        raise HTTPException(status_code=409, detail="Session already transferred")
    if session.booking_id:
        return store.bookings[session.booking_id]

    branch = slots.branch or DEFAULT_BRANCH
    avail = check_availability(slots.guest_count or 0, slots.date, slots.time, branch)  # type: ignore[arg-type]
    if not avail.available:
        raise HTTPException(
            status_code=409,
            detail={"message": "No availability", "availability": avail.model_dump(mode="json")},
        )

    booking_id = f"BK-{uuid4().hex[:8].upper()}"
    transcript = body.transcript or session.transcript
    recording_id = body.recording_id or session.recording_id
    record = BookingRecord(
        id=booking_id,
        session_id=session.id,
        slots=slots,
        transcript=transcript,
        recording_id=recording_id,
        source=body.source or BOOKING_SOURCE,
    )
    store.bookings[booking_id] = record
    store.add_occupancy(branch, slots.date, bucket_time(slots.time), slots.guest_count or 0)  # type: ignore[arg-type]
    session.booking_id = booking_id
    session.status = "booked"
    session.recording_id = recording_id
    session.transcript = transcript
    return record


@app.post("/v1/call-sessions/{session_id}/transfer", response_model=CallSession)
def transfer_session(session_id: str, body: TransferRequest) -> CallSession:
    session = _get_session(session_id)
    session.transferred = True
    session.transfer_reason = body.reason
    session.status = "transferred"
    if body.summary:
        session.transcript.append(TranscriptTurn(role="system", content=f"transfer: {body.summary}"))
    return session


@app.patch("/v1/call-sessions/{session_id}/recording", response_model=CallSession)
def set_recording(session_id: str, body: RecordingUpdate) -> CallSession:
    session = _get_session(session_id)
    session.recording_id = body.recording_id
    return session


@app.patch("/v1/recordings/by-call/{call_sid}", response_model=CallSession)
def set_recording_by_call_sid(call_sid: str, body: RecordingUpdate) -> CallSession:
    for session in store.sessions.values():
        if session.call_sid == call_sid:
            session.recording_id = body.recording_id
            return session
    raise HTTPException(status_code=404, detail="Call session not found")


@app.post("/v1/call-sessions/{session_id}/transcript", response_model=CallSession)
def append_transcript(session_id: str, body: TranscriptAppend) -> CallSession:
    session = _get_session(session_id)
    session.transcript.append(TranscriptTurn(role=body.role, content=body.content))  # type: ignore[arg-type]
    return session


@app.get("/v1/branches")
def list_branches() -> dict:
    return {"branches": BRANCHES, "multi_branch": True}


def _get_session(session_id: str) -> CallSession:
    session = store.sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


def _usable_caller_id(from_number: str | None) -> str | None:
    if not from_number:
        return None
    digits = "".join(ch for ch in from_number if ch.isdigit() or ch == "+")
    if len(digits) < 8 or from_number.lower().startswith("client:"):
        return None
    if from_number.lower() in {"anonymous", "restricted"}:
        return None
    return from_number


def _normalize_delta(delta: SlotDelta, errors: list[str]) -> SlotDelta:
    data = delta.model_dump(exclude_none=True)
    if "guest_count" in data:
        if data["guest_count"] < 1:
            errors.append("So khach phai lon hon 0.")
    if "date" in data:
        today = datetime.now(VN_TZ).date()
        if data["date"] < today:
            errors.append("Ngày đặt không được ở quá khứ.")
    if "time" in data:
        data["time"] = bucket_time(data["time"])
        if not within_hours(data["time"]):
            errors.append("Giờ đến ngoài khung mở cửa 11:00–22:00.")
    if "branch" in data:
        code = normalize_branch(data["branch"])
        if code not in BRANCHES:
            errors.append("Chi nhánh không hợp lệ.")
        else:
            data["branch"] = code
    return SlotDelta.model_validate(data)


def reset_store() -> None:
    store.reset()
