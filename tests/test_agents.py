from __future__ import annotations

import asyncio
import json

from agents import BOOKING, CONCIERGE, DEFAULT_AGENT, DELIVERY, build_registry, resolve_agent
from bridge.session import CallPipeline, CallState
from llm.stream import SpeakSentence, ToolCallRequest
from tests.fakes import FakeBridgeSocket, FakeSTT, ScriptedToolLlm, ScriptedTts, SlowTts

INIT = {
    "event": "session.init",
    "callId": "clx8k2p9v0000abcd1234efgh",
    "storeName": "Bella Vista",
    "timezone": "Europe/Berlin",
    "locale": "en",
    "greeting": "Thanks for calling Bella Vista. This is an automated assistant — how can I help you today?",
}


async def _start_pipeline(ws, llm, tts):
    pipeline = CallPipeline(ws, stt=FakeSTT(), llm=llm, tts=tts, tools=build_registry())
    task = asyncio.create_task(pipeline.run())
    await asyncio.sleep(0.02)
    await ws.push_text(json.dumps(INIT))
    await asyncio.sleep(0.1)
    return pipeline, task


async def _stop(ws, task) -> None:
    await ws.disconnect()
    await asyncio.wait_for(task, timeout=2)


def _schema_names(schemas) -> list[str]:
    return sorted(s["function"]["name"] for s in schemas)


# --- static wiring ----------------------------------------------------------


def test_calls_start_with_the_concierge() -> None:
    assert DEFAULT_AGENT == CONCIERGE.name


def test_agent_tool_selection_includes_handoffs() -> None:
    assert CONCIERGE.tool_selection() == [
        "get_current_time",
        "handoff_to_booking",
        "handoff_to_delivery",
    ]
    # No agent can hand off to itself.
    for agent in (CONCIERGE, BOOKING, DELIVERY):
        assert f"handoff_to_{agent.name}" not in agent.tool_selection()


def test_registry_carries_every_handoff_tool() -> None:
    names = set(build_registry().names())
    assert {"handoff_to_booking", "handoff_to_concierge", "handoff_to_delivery"} <= names
    # Every tool an agent lists must actually exist, or the model sees a gap.
    for agent in (CONCIERGE, BOOKING, DELIVERY):
        assert set(agent.tool_selection()) <= names


def test_resolve_agent_falls_back_instead_of_raising() -> None:
    """An unknown name must not drop a live call."""
    assert resolve_agent("nonsense").name == DEFAULT_AGENT


def test_booking_prompt_forbids_confirmation_language() -> None:
    """Guards the prompt, not the model. The endpoint files a request only."""
    fragment = BOOKING.prompt_fragment.lower()
    assert "never say the table is booked" in fragment
    assert "call back" in fragment
    assert "cannot check" in fragment


def test_delivery_prompt_forbids_confirmation_language() -> None:
    fragment = DELIVERY.prompt_fragment.lower()
    assert "never say the order is placed" in fragment
    assert "call back" in fragment


# --- handoff at runtime -----------------------------------------------------


async def test_concierge_hands_off_to_booking_in_one_turn() -> None:
    ws = FakeBridgeSocket()
    tts = ScriptedTts()
    llm = ScriptedToolLlm(
        [
            [
                SpeakSentence("Of course, I can help with that."),
                ToolCallRequest(id="h1", name="handoff_to_booking", arguments="{}"),
            ],
            [SpeakSentence("What date were you thinking of?")],
        ]
    )
    pipeline, task = await _start_pipeline(ws, llm, tts)
    await pipeline.on_transcript_completed("I'd like a table for Friday.")
    await asyncio.sleep(0.2)

    assert pipeline.session.active_agent == "booking"
    # The bridging line was spoken in the same round as the handoff, so the
    # caller heard something while the swap happened.
    assert tts.spoken.index("Of course, I can help with that.") < tts.spoken.index(
        "What date were you thinking of?"
    )
    # Round two ran under the booking prompt and the booking tool set.
    assert "reservation REQUEST" in llm.calls[1][0]["content"]
    assert _schema_names(llm.tool_schemas[1]) == sorted(BOOKING.tool_selection())
    # The concierge never sees the booking workflow tools.
    assert "set_booking_details" not in _schema_names(llm.tool_schemas[0])
    await _stop(ws, task)


async def test_handoff_is_recorded_in_history() -> None:
    ws = FakeBridgeSocket()
    llm = ScriptedToolLlm(
        [
            [ToolCallRequest(id="h1", name="handoff_to_delivery", arguments="{}")],
            [SpeakSentence("What is the delivery address?")],
        ]
    )
    pipeline, task = await _start_pipeline(ws, llm, ScriptedTts())
    await pipeline.on_transcript_completed("Do you deliver?")
    await asyncio.sleep(0.2)

    tool_messages = [m for m in pipeline.session.history if m["role"] == "tool"]
    assert json.loads(tool_messages[0]["content"]) == {"active_agent": "delivery"}
    await _stop(ws, task)


async def test_caller_can_route_back_to_a_previous_agent() -> None:
    ws = FakeBridgeSocket()
    tts = ScriptedTts()
    llm = ScriptedToolLlm(
        [
            [ToolCallRequest(id="h1", name="handoff_to_booking", arguments="{}")],
            [SpeakSentence("What date?")],
            [ToolCallRequest(id="h2", name="handoff_to_delivery", arguments="{}")],
            [SpeakSentence("What is the address?")],
        ]
    )
    pipeline, task = await _start_pipeline(ws, llm, tts)
    await pipeline.on_transcript_completed("A table, please.")
    await asyncio.sleep(0.2)
    assert pipeline.session.active_agent == "booking"

    await pipeline.on_transcript_completed("Actually, delivery instead.")
    await asyncio.sleep(0.2)
    assert pipeline.session.active_agent == "delivery"
    assert "What is the address?" in tts.spoken
    await _stop(ws, task)


async def test_active_agent_survives_barge_in() -> None:
    """Routing is business state: a barge-in invalidates audio, not the agent."""
    ws = FakeBridgeSocket()
    llm = ScriptedToolLlm(
        [
            [ToolCallRequest(id="h1", name="handoff_to_booking", arguments="{}")],
            [SpeakSentence("What date were you thinking of?")],
        ]
    )
    pipeline, task = await _start_pipeline(ws, llm, SlowTts(hold=0.5))
    await pipeline.on_transcript_completed("I'd like a table.")
    await asyncio.sleep(0.1)
    assert pipeline.session.active_agent == "booking"

    await pipeline.on_speech_started()
    await asyncio.sleep(0.1)

    assert pipeline.session.active_agent == "booking"
    assert pipeline.session.state == CallState.LISTENING
    await _stop(ws, task)


async def test_system_prompt_is_rewritten_not_appended() -> None:
    ws = FakeBridgeSocket()
    llm = ScriptedToolLlm(
        [
            [ToolCallRequest(id="h1", name="handoff_to_booking", arguments="{}")],
            [SpeakSentence("What date?")],
        ]
    )
    pipeline, task = await _start_pipeline(ws, llm, ScriptedTts())
    await pipeline.on_transcript_completed("A table.")
    await asyncio.sleep(0.2)

    systems = [m for m in pipeline.session.history if m["role"] == "system"]
    assert len(systems) == 1
    assert "reservation REQUEST" in systems[0]["content"]
    # The store context from session.init survives the swap.
    assert "Bella Vista" in systems[0]["content"]
    await _stop(ws, task)
