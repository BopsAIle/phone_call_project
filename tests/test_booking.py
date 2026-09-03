from __future__ import annotations

import asyncio
import json
from datetime import date, timedelta

import pytest

from agents.registry import build_registry
from bridge.session import CallPipeline, CallSession
from llm.stream import SpeakSentence, ToolCallRequest
from tools.base import ToolContext
from tools.executor import ToolExecutor
from tools.slots import BookingSlots, DeliverySlots
from tools.store_api import StoreApiUncertain, StoreApiValidationError, StubStoreApi
from tests.fakes import FakeBridgeSocket, FakeSTT, ScriptedToolLlm, ScriptedTts, SlowTts

SOON = (date.today() + timedelta(days=7)).isoformat()
DETAILS = {
    "date": SOON,
    "time": "20:00",
    "party_size": 4,
    "name": "Anna",
    "phone": "+49 30 1234567",
}

INIT = {
    "event": "session.init",
    "callId": "call-1",
    "storeName": "Bella Vista",
    "timezone": "Europe/Berlin",
    "locale": "en",
    "greeting": "Thanks for calling Bella Vista. This is an automated assistant.",
}


def _session() -> CallSession:
    session = CallSession()
    session.call_id = "call-1"
    session.timezone = "Europe/Berlin"
    session.active_agent = "booking"
    return session


async def _call(registry, session: CallSession, name: str, args: dict | None = None):
    executor = ToolExecutor(registry)
    ctx = ToolContext(session=session, generation_id=0, should_abort=lambda: False)
    return await executor.execute(
        ToolCallRequest(id="c1", name=name, arguments=json.dumps(args or {})), ctx
    )


async def _fill_and_confirm(registry, session: CallSession) -> None:
    await _call(registry, session, "set_booking_details", DETAILS)
    await _call(registry, session, "confirm_booking_details")


# --- slot models ------------------------------------------------------------


def test_draft_reports_what_is_missing() -> None:
    draft = BookingSlots().apply({"party_size": 2})
    assert draft.missing() == ["date", "time", "name", "phone"]
    assert draft.is_complete() is False
    assert BookingSlots(**DETAILS).is_complete() is True


def test_fingerprint_changes_with_any_value() -> None:
    base = BookingSlots(**DETAILS)
    assert base.fingerprint() == BookingSlots(**DETAILS).fingerprint()
    assert base.fingerprint() != base.apply({"party_size": 6}).fingerprint()


def test_apply_ignores_empty_values() -> None:
    draft = BookingSlots(**DETAILS).apply({"name": "", "party_size": None})
    assert draft.name == "Anna"
    assert draft.party_size == 4


@pytest.mark.parametrize(
    "bad",
    [
        {"date": "next Friday"},
        {"time": "eight-ish"},
        {"party_size": 0},
        {"party_size": 500},
        {"phone": "12"},
        {"phone": "call me"},
    ],
)
def test_invalid_values_are_rejected(bad: dict) -> None:
    with pytest.raises(Exception):
        BookingSlots().apply(bad)


def test_incomplete_draft_cannot_become_a_request() -> None:
    with pytest.raises(ValueError, match="incomplete"):
        BookingSlots().apply({"name": "Anna"}).to_request()


def test_delivery_draft_has_its_own_required_fields() -> None:
    assert DeliverySlots().missing() == ["address", "items", "name", "phone"]


# --- collecting -------------------------------------------------------------


async def test_details_accumulate_across_calls() -> None:
    registry, session = build_registry(), _session()
    first = await _call(registry, session, "set_booking_details", {"party_size": 4})
    assert first.ok is True
    assert "date" in first.data["still_missing"]

    await _call(registry, session, "set_booking_details", {"date": SOON, "time": "20:00"})
    assert session.booking.party_size == 4
    assert session.booking.date == SOON


async def test_bad_detail_is_reported_not_stored() -> None:
    registry, session = build_registry(), _session()
    result = await _call(registry, session, "set_booking_details", {"party_size": 99})
    assert result.ok is False
    assert result.data["error"] == "invalid_details"
    assert session.booking.party_size is None


async def test_past_date_is_rejected() -> None:
    """The model resolves 'next Friday' itself; catch it resolving to last year."""
    registry, session = build_registry(), _session()
    stale = (date.today() - timedelta(days=3)).isoformat()
    result = await _call(registry, session, "set_booking_details", {"date": stale})
    assert result.ok is False
    assert "in the past" in result.data["problems"][0]
    assert session.booking.date is None


async def test_confirm_requires_complete_details() -> None:
    registry, session = build_registry(), _session()
    await _call(registry, session, "set_booking_details", {"party_size": 4})
    result = await _call(registry, session, "confirm_booking_details")
    assert result.ok is False
    assert result.data["error"] == "incomplete"
    assert session.details_fingerprint is None


# --- the write gate ---------------------------------------------------------


async def test_submit_refused_when_details_incomplete() -> None:
    api = StubStoreApi()
    registry, session = build_registry(api), _session()
    await _call(registry, session, "set_booking_details", {"party_size": 4})
    result = await _call(registry, session, "submit_booking_request")
    assert result.data["error"] == "incomplete"
    assert api.submitted == []


async def test_submit_refused_without_confirmation() -> None:
    api = StubStoreApi()
    registry, session = build_registry(api), _session()
    await _call(registry, session, "set_booking_details", DETAILS)
    result = await _call(registry, session, "submit_booking_request")
    assert result.data["error"] == "not_confirmed"
    assert api.submitted == []


async def test_confirmation_is_invalidated_by_a_later_change() -> None:
    """The caller confirms four, then says six. The old yes must not authorise it."""
    api = StubStoreApi()
    registry, session = build_registry(api), _session()
    await _fill_and_confirm(registry, session)

    await _call(registry, session, "set_booking_details", {"party_size": 6})
    result = await _call(registry, session, "submit_booking_request")

    assert result.data["error"] == "not_confirmed"
    assert api.submitted == []
    # Re-confirming the new details unblocks it.
    await _call(registry, session, "confirm_booking_details")
    assert (await _call(registry, session, "submit_booking_request")).ok is True
    assert api.submitted[0]["payload"]["party_size"] == 6


async def test_submit_is_filed_once_then_refused() -> None:
    api = StubStoreApi()
    registry, session = build_registry(api), _session()
    await _fill_and_confirm(registry, session)

    first = await _call(registry, session, "submit_booking_request")
    second = await _call(registry, session, "submit_booking_request")

    assert first.ok is True
    assert second.data["error"] == "already_filed"
    assert len(api.submitted) == 1


async def test_successful_submit_sends_details_and_a_stable_key() -> None:
    api = StubStoreApi()
    registry, session = build_registry(api), _session()
    await _fill_and_confirm(registry, session)
    result = await _call(registry, session, "submit_booking_request")

    filed = api.submitted[0]
    assert filed["kind"] == "booking"
    assert filed["payload"] == DETAILS
    assert filed["call_id"] == "call-1"
    assert filed["idempotency_key"] == f"call-1:{session.booking.fingerprint()}"
    # What the model is told to say next promises a call-back and explicitly
    # forbids the reservation-confirmed wording.
    note = result.data["next"]
    assert "call them back" in note
    assert "Do NOT say it is booked, reserved, or confirmed" in note


async def test_submit_is_gated_on_a_stale_generation() -> None:
    """I1: a barge-in mid-turn must stop the write reaching the API."""
    api = StubStoreApi()
    registry, session = build_registry(api), _session()
    await _fill_and_confirm(registry, session)

    executor = ToolExecutor(registry)
    ctx = ToolContext(session=session, generation_id=0, should_abort=lambda: True)
    result = await executor.execute(
        ToolCallRequest(id="c", name="submit_booking_request", arguments="{}"), ctx
    )
    assert result.data["error"] == "aborted"
    assert api.submitted == []


# --- API failures -----------------------------------------------------------


async def test_api_rejection_is_reported_for_the_model_to_fix() -> None:
    api = StubStoreApi(fail_with=StoreApiValidationError("party_size too large"))
    registry, session = build_registry(api), _session()
    await _fill_and_confirm(registry, session)
    result = await _call(registry, session, "submit_booking_request")

    assert result.data["error"] == "rejected"
    assert "party_size" in result.data["problems"][0]


async def test_uncertain_outcome_claims_neither_success_nor_failure() -> None:
    api = StubStoreApi(fail_with=StoreApiUncertain("timeout"))
    registry, session = build_registry(api), _session()
    await _fill_and_confirm(registry, session)
    result = await _call(registry, session, "submit_booking_request")

    assert result.data["error"] == "uncertain"
    guidance = result.data["guidance"].lower()
    assert "do not tell the caller it went through" in guidance
    assert "do not tell them it failed" in guidance
    # Not consumed: the caller may still need this handled another way.
    assert session.booking.fingerprint() not in session.consumed_fingerprints


# --- through the pipeline ---------------------------------------------------


async def _start(ws, llm, tts, api):
    pipeline = CallPipeline(ws, stt=FakeSTT(), llm=llm, tts=tts, tools=build_registry(api))
    task = asyncio.create_task(pipeline.run())
    await asyncio.sleep(0.02)
    await ws.push_text(json.dumps(INIT))
    await asyncio.sleep(0.1)
    return pipeline, task


async def test_full_booking_flow_files_one_request() -> None:
    ws, api, tts = FakeBridgeSocket(), StubStoreApi(), ScriptedTts()
    llm = ScriptedToolLlm(
        [
            [ToolCallRequest(id="h1", name="handoff_to_booking", arguments="{}")],
            [
                SpeakSentence("Let me take those details."),
                ToolCallRequest(id="s1", name="set_booking_details", arguments=json.dumps(DETAILS)),
            ],
            [ToolCallRequest(id="k1", name="confirm_booking_details", arguments="{}")],
        ]
    )
    pipeline, task = await _start(ws, llm, tts, api)
    await pipeline.on_transcript_completed("I'd like a table.")
    await asyncio.sleep(0.3)

    assert pipeline.session.active_agent == "booking"
    assert pipeline.session.booking.is_complete()
    assert pipeline.session.details_fingerprint == pipeline.session.booking.fingerprint()

    # A second turn does the write, as the model would after the caller says yes.
    llm.rounds.append([ToolCallRequest(id="w1", name="submit_booking_request", arguments="{}")])
    llm.rounds.append([SpeakSentence("Someone will call you back shortly to confirm.")])
    await pipeline.on_transcript_completed("Yes, that's right.")
    await asyncio.sleep(0.3)

    assert len(api.submitted) == 1
    assert api.submitted[0]["payload"] == DETAILS
    assert "Someone will call you back shortly to confirm." in tts.spoken
    await ws.disconnect()
    await asyncio.wait_for(task, timeout=2)


async def test_slots_survive_a_barge_in() -> None:
    """Barge-in invalidates audio, never a half-collected booking."""
    ws, api = FakeBridgeSocket(), StubStoreApi()
    llm = ScriptedToolLlm(
        [
            [ToolCallRequest(id="h1", name="handoff_to_booking", arguments="{}")],
            [
                ToolCallRequest(id="s1", name="set_booking_details", arguments=json.dumps(DETAILS)),
            ],
            [SpeakSentence("So that is a table for four.")],
        ]
    )
    pipeline, task = await _start(ws, llm, SlowTts(hold=0.5), api)
    await pipeline.on_transcript_completed("A table for four, please.")
    await asyncio.sleep(0.15)
    assert pipeline.session.booking.is_complete()

    await pipeline.on_speech_started()
    await asyncio.sleep(0.1)

    assert pipeline.session.booking.model_dump(exclude_none=True) == DETAILS
    assert pipeline.session.active_agent == "booking"
    await ws.disconnect()
    await asyncio.wait_for(task, timeout=2)
