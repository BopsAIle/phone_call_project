from __future__ import annotations

from dataclasses import dataclass, field

from apps.voice_agent.backend_client import BackendClient
from apps.voice_agent.escalation import looks_like_faq, match_transfer_reason
from apps.voice_agent.extractor import HeuristicExtractor, is_confirm
from apps.voice_agent.nlg import (
    REPEAT_LINE,
    TRANSFER_LINE,
    alternatives_line,
    booked_line,
    confirm_summary,
    faq_then_question,
    opening_line,
    question_for,
    speak_guidance,
    validation_line,
)
from apps.voice_agent.rag import KnowledgeRetriever
from shared.config import get_settings
from shared.models import (
    AvailabilityResponse,
    CallSession,
    SlotDelta,
)
from shared.slots import (
    has_availability_keys,
    missing_fields,
    touches_availability_keys,
)


@dataclass
class TurnResult:
    assistant_text: str
    action: str
    session: CallSession
    missing_fields: list[str] = field(default_factory=list)
    availability: AvailabilityResponse | None = None
    booking_id: str | None = None
    transfer_reason: str | None = None
    rag_hits: list[str] = field(default_factory=list)


class DialogEngine:
    """Text dialog orchestrator: extract slots, PATCH backend, check seats, RAG, transfer."""

    def __init__(
        self,
        backend: BackendClient,
        rag: KnowledgeRetriever,
        extractor: HeuristicExtractor | None = None,
        *,
        multi_branch: bool | None = None,
        large_party_threshold: int | None = None,
        max_stt_fail_turns: int | None = None,
    ) -> None:
        settings = get_settings()
        self.backend = backend
        self.rag = rag
        self.extractor = extractor or HeuristicExtractor()
        self.multi_branch = settings.multi_branch if multi_branch is None else multi_branch
        self.large_party_threshold = large_party_threshold or settings.large_party_threshold
        self.max_stt_fail_turns = max_stt_fail_turns or settings.max_stt_fail_turns
        self._stt_fails: dict[str, int] = {}

    async def start(
        self,
        *,
        call_sid: str | None = None,
        from_number: str | None = None,
        recording_id: str | None = None,
    ) -> TurnResult:
        session = await self.backend.create_session(
            call_sid=call_sid,
            from_number=from_number,
            recording_id=recording_id,
            multi_branch=self.multi_branch,
        )
        line = opening_line(session.slots)
        await self.backend.append_transcript(session.id, "assistant", line)
        session = await self.backend.get_session(session.id)
        return TurnResult(
            assistant_text=line,
            action="ask",
            session=session,
            missing_fields=missing_fields(session.slots, session.multi_branch),
        )

    async def handle_user_turn(self, session_id: str, user_text: str) -> TurnResult:
        session = await self.backend.get_session(session_id)
        text = (user_text or "").strip()
        await self.backend.append_transcript(session_id, "user", text)
        session = await self.backend.get_session(session_id)

        if not text:
            self._stt_fails[session_id] = self._stt_fails.get(session_id, 0) + 1
            if self._stt_fails[session_id] >= self.max_stt_fail_turns:
                return await self._transfer(session, "stt_failures")
            return await self._reply(session, REPEAT_LINE, "repeat")

        transfer_reason = match_transfer_reason(text, session, self.large_party_threshold)
        if transfer_reason and transfer_reason != "large_party":
            return await self._transfer(session, transfer_reason)

        rag_chunks = self.rag.retrieve(text) if looks_like_faq(text) else []
        rag_hits = [chunk.speakable() for chunk in rag_chunks]
        faq_text = rag_hits[0] if rag_hits else ""

        if session.status == "ready_to_confirm" and is_confirm(text):
            booking = await self.backend.create_booking(
                session_id=session.id,
                slots=session.slots,
                transcript=session.transcript,
                recording_id=session.recording_id,
            )
            line = booked_line(booking.id)
            session = await self._reply_session(session.id, line)
            return TurnResult(
                assistant_text=line,
                action="booked",
                session=session,
                missing_fields=[],
                booking_id=booking.id,
            )

        delta = self.extractor.extract(text, session)
        patch_payload = None
        if delta.has_any():
            patch_payload = await self.backend.patch_slots(session_id, delta)
            session = CallSession.model_validate(patch_payload["session"])
            errors = patch_payload.get("validation_errors") or []
            if errors:
                line = validation_line(errors)
                return await self._finish(session, line, "ask", rag_hits=rag_hits)
            if patch_payload.get("should_transfer"):
                return await self._transfer(
                    session, patch_payload.get("transfer_reason") or "large_party"
                )

        session = await self.backend.get_session(session_id)
        if session.slots.guest_count and session.slots.guest_count > self.large_party_threshold:
            return await self._transfer(session, "large_party")

        availability: AvailabilityResponse | None = None
        if has_availability_keys(session.slots, session.multi_branch) and (
            delta.has_any() and touches_availability_keys(delta) or _needs_initial_availability(session, delta)
        ):
            availability = await self.backend.check_availability(
                session_id=session.id,
                guest_count=session.slots.guest_count or 0,
                day=session.slots.date,  # type: ignore[arg-type]
                slot=session.slots.time,  # type: ignore[arg-type]
                branch=session.slots.branch or "quan-1",
            )
            session = await self.backend.get_session(session_id)
            if not availability.available:
                line = alternatives_line(availability)
                if session.availability_fail_count >= 2 and is_confirm(text) is False:
                    folded_deny = match_transfer_reason(text, session, self.large_party_threshold)
                    if folded_deny == "availability_exhausted":
                        return await self._transfer(session, "availability_exhausted")
                return await self._finish(
                    session, line, "suggest_alternatives", availability=availability, rag_hits=rag_hits
                )

        missing = missing_fields(session.slots, session.multi_branch)
        if not missing:
            if availability is None and has_availability_keys(session.slots, session.multi_branch):
                availability = await self.backend.check_availability(
                    session_id=session.id,
                    guest_count=session.slots.guest_count or 0,
                    day=session.slots.date,  # type: ignore[arg-type]
                    slot=session.slots.time,  # type: ignore[arg-type]
                    branch=session.slots.branch or "quan-1",
                )
                session = await self.backend.get_session(session_id)
                if not availability.available:
                    return await self._finish(
                        session,
                        alternatives_line(availability),
                        "suggest_alternatives",
                        availability=availability,
                        rag_hits=rag_hits,
                    )
            line = confirm_summary(session.slots)
            return await self._finish(session, line, "confirm", availability=availability)

        next_field = missing[0]
        if faq_text and not delta.has_any():
            line = faq_then_question(
                faq_text,
                next_field,
                slots=session.slots,
                delta=delta,
                last_user_text=text,
            )
            return await self._finish(session, line, "faq", rag_hits=rag_hits)

        if looks_like_faq(text) and not rag_hits and not delta.has_any():
            return await self._transfer(session, "unknown_policy")

        line = question_for(
            next_field,
            slots=session.slots,
            delta=delta,
            last_user_text=text,
        )
        if faq_text:
            line = faq_then_question(
                faq_text,
                next_field,
                slots=session.slots,
                delta=delta,
                last_user_text=text,
            )
        return await self._finish(session, line, "ask", rag_hits=rag_hits)

    async def apply_slot_delta(self, session_id: str, delta: SlotDelta) -> dict:
        """Used by LLM tools: always PATCH, then availability when keys exist."""
        patch = await self.backend.patch_slots(session_id, delta)
        session = CallSession.model_validate(patch["session"])
        availability = None
        if has_availability_keys(session.slots, session.multi_branch) and touches_availability_keys(delta):
            availability = await self.backend.check_availability(
                session_id=session.id,
                guest_count=session.slots.guest_count or 0,
                day=session.slots.date,  # type: ignore[arg-type]
                slot=session.slots.time,  # type: ignore[arg-type]
                branch=session.slots.branch or "quan-1",
            )
            session = await self.backend.get_session(session_id)
        missing = missing_fields(session.slots, session.multi_branch)
        available = None if availability is None else availability.available
        return {
            "session": session.model_dump(mode="json"),
            "missing_fields": missing,
            "validation_errors": patch.get("validation_errors") or [],
            "should_transfer": patch.get("should_transfer", False),
            "transfer_reason": patch.get("transfer_reason"),
            "availability": availability.model_dump(mode="json") if availability else None,
            "speak": speak_guidance(
                session.slots, missing, delta=delta, available=available
            ),
        }

    async def _transfer(self, session: CallSession, reason: str) -> TurnResult:
        summary = confirm_summary(session.slots) if session.slots.guest_count else ""
        session = await self.backend.transfer(session.id, reason, summary=summary)
        session = await self._reply_session(session.id, TRANSFER_LINE)
        return TurnResult(
            assistant_text=TRANSFER_LINE,
            action="transfer",
            session=session,
            missing_fields=missing_fields(session.slots, session.multi_branch),
            transfer_reason=reason,
        )

    async def _finish(
        self,
        session: CallSession,
        line: str,
        action: str,
        *,
        availability: AvailabilityResponse | None = None,
        rag_hits: list[str] | None = None,
    ) -> TurnResult:
        session = await self._reply_session(session.id, line)
        return TurnResult(
            assistant_text=line,
            action=action,
            session=session,
            missing_fields=missing_fields(session.slots, session.multi_branch),
            availability=availability,
            rag_hits=rag_hits or [],
        )

    async def _reply(self, session: CallSession, line: str, action: str) -> TurnResult:
        return await self._finish(session, line, action)

    async def _reply_session(self, session_id: str, line: str) -> CallSession:
        await self.backend.append_transcript(session_id, "assistant", line)
        return await self.backend.get_session(session_id)


def _needs_initial_availability(session: CallSession, delta: SlotDelta) -> bool:
    return (
        has_availability_keys(session.slots, session.multi_branch)
        and not delta.has_any()
        and session.status == "collecting"
    )
