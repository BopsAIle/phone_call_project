from __future__ import annotations

import asyncio
import json

import pytest

from bridge.session import MAX_TOOL_ROUNDS, CallPipeline, CallSession
from llm.stream import (
    SpeakSentence,
    ToolCallAccumulator,
    ToolCallRequest,
    fallback_phrase,
    thinking_phrase,
)
from tools.base import ToolContext, ToolResult
from tools.executor import ToolExecutor
from tools.registry import ToolRegistry
from tests.fakes import (
    FakeBridgeSocket,
    FakeSTT,
    FakeTool,
    ScriptedToolLlm,
    ScriptedTts,
)

INIT = {
    "event": "session.init",
    "callId": "clx8k2p9v0000abcd1234efgh",
    "storeName": "Bella Vista",
    "timezone": "Europe/Berlin",
    "locale": "en",
    "greeting": "Thanks for calling Bella Vista. This is an automated assistant — how can I help you today?",
}


async def _start_pipeline(ws, llm, tts, tools):
    pipeline = CallPipeline(ws, stt=FakeSTT(), llm=llm, tts=tts, tools=tools)
    task = asyncio.create_task(pipeline.run())
    await asyncio.sleep(0.02)
    await ws.push_text(json.dumps(INIT))
    await asyncio.sleep(0.1)
    return pipeline, task


async def _stop(ws, task) -> None:
    await ws.disconnect()
    await asyncio.wait_for(task, timeout=2)


def _ctx(session: CallSession, abort: bool = False) -> ToolContext:
    return ToolContext(session=session, generation_id=1, should_abort=lambda: abort)


# --- streaming reassembly ---------------------------------------------------


class _Fn:
    def __init__(self, name=None, arguments=None):
        self.name = name
        self.arguments = arguments


class _Delta:
    def __init__(self, index, id=None, function=None):
        self.index = index
        self.id = id
        self.function = function


def test_accumulator_rebuilds_split_argument_json() -> None:
    acc = ToolCallAccumulator()
    acc.push([_Delta(0, id="call_1", function=_Fn(name="book", arguments='{"party'))])
    acc.push([_Delta(0, function=_Fn(arguments='_size": 4}'))])
    calls = acc.finish()
    assert calls == [ToolCallRequest(id="call_1", name="book", arguments='{"party_size": 4}')]
    assert acc.finish() == []


def test_accumulator_keeps_parallel_calls_apart() -> None:
    acc = ToolCallAccumulator()
    acc.push(
        [
            _Delta(0, id="a", function=_Fn(name="one", arguments="{}")),
            _Delta(1, id="b", function=_Fn(name="two", arguments='{"x":')),
        ]
    )
    acc.push([_Delta(1, function=_Fn(arguments="1}"))])
    assert [call.name for call in acc.finish()] == ["one", "two"]


def test_accumulator_drops_nameless_call() -> None:
    acc = ToolCallAccumulator()
    acc.push([_Delta(0, id="a", function=_Fn(arguments="{}"))])
    assert acc.finish() == []


# --- registry ---------------------------------------------------------------


def test_registry_schemas_select_by_name() -> None:
    registry = ToolRegistry([FakeTool("alpha"), FakeTool("beta")])
    assert registry.names() == ["alpha", "beta"]
    assert [s["function"]["name"] for s in registry.schemas(["beta"])] == ["beta"]
    # An agent may list a tool that is not wired up yet; narrow, do not raise.
    assert registry.schemas(["nope"]) == []


def test_registry_rejects_unnamed_tool() -> None:
    with pytest.raises(ValueError):
        ToolRegistry([FakeTool("")])


# --- executor policy --------------------------------------------------------


async def test_executor_rejects_unknown_tool() -> None:
    executor = ToolExecutor(ToolRegistry([]))
    result = await executor.execute(
        ToolCallRequest(id="c", name="ghost", arguments="{}"), _ctx(CallSession())
    )
    assert result.ok is False
    assert result.data["error"] == "unknown_tool"


async def test_executor_rejects_unparseable_arguments() -> None:
    tool = FakeTool("alpha")
    executor = ToolExecutor(ToolRegistry([tool]))
    result = await executor.execute(
        ToolCallRequest(id="c", name="alpha", arguments="{not json"), _ctx(CallSession())
    )
    assert result.data["error"] == "bad_arguments"
    assert tool.calls == []


async def test_executor_denies_stale_generation() -> None:
    """I1: a superseded turn must not reach a side effect."""
    tool = FakeTool("alpha")
    executor = ToolExecutor(ToolRegistry([tool]))
    result = await executor.execute(
        ToolCallRequest(id="c", name="alpha", arguments="{}"), _ctx(CallSession(), abort=True)
    )
    assert result.data["error"] == "aborted"
    assert tool.calls == []


async def test_executor_converts_tool_exception_to_result() -> None:
    tool = FakeTool("alpha", error=RuntimeError("boom"))
    executor = ToolExecutor(ToolRegistry([tool]))
    result = await executor.execute(
        ToolCallRequest(id="c", name="alpha", arguments="{}"), _ctx(CallSession())
    )
    assert result.ok is False
    assert result.data["error"] == "tool_error"


async def test_executor_propagates_cancellation() -> None:
    tool = FakeTool("alpha", delay=1.0)
    executor = ToolExecutor(ToolRegistry([tool]))
    task = asyncio.create_task(
        executor.execute(ToolCallRequest(id="c", name="alpha", arguments="{}"), _ctx(CallSession()))
    )
    await asyncio.sleep(0.02)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


# --- the turn loop ----------------------------------------------------------


async def test_tool_round_runs_tool_then_answers() -> None:
    ws = FakeBridgeSocket()
    tts = ScriptedTts()
    tool = FakeTool("lookup", data={"answer": 42})
    llm = ScriptedToolLlm(
        [
            [ToolCallRequest(id="c1", name="lookup", arguments='{"q": "x"}')],
            [SpeakSentence("The answer is forty-two.")],
        ]
    )
    pipeline, task = await _start_pipeline(ws, llm, tts, ToolRegistry([tool]))
    await pipeline.on_transcript_completed("What is the answer?")
    await asyncio.sleep(0.2)

    assert tool.calls == [{"q": "x"}]
    assert "The answer is forty-two." in tts.spoken
    roles = [m["role"] for m in pipeline.session.history]
    assert roles == ["system", "assistant", "user", "assistant", "tool", "assistant"]
    assert pipeline.session.history[3]["tool_calls"][0]["function"]["name"] == "lookup"
    assert json.loads(pipeline.session.history[4]["content"]) == {"answer": 42}
    assert pipeline.session.history[4]["tool_call_id"] == "c1"
    await _stop(ws, task)


async def test_turn_without_tool_calls_is_unchanged() -> None:
    ws = FakeBridgeSocket()
    tts = ScriptedTts()
    llm = ScriptedToolLlm([[SpeakSentence("We open at five.")]])
    pipeline, task = await _start_pipeline(ws, llm, tts, ToolRegistry([FakeTool("unused")]))
    await pipeline.on_transcript_completed("When do you open?")
    await asyncio.sleep(0.2)

    assert "We open at five." in tts.spoken
    assert len(llm.calls) == 1
    assert [m["role"] for m in pipeline.session.history][-2:] == ["user", "assistant"]
    await _stop(ws, task)


async def test_tool_rounds_are_bounded_and_fall_back() -> None:
    ws = FakeBridgeSocket()
    tts = ScriptedTts()
    tool = FakeTool("spin")
    llm = ScriptedToolLlm(
        [[ToolCallRequest(id=f"c{i}", name="spin", arguments="{}")] for i in range(MAX_TOOL_ROUNDS + 2)]
    )
    pipeline, task = await _start_pipeline(ws, llm, tts, ToolRegistry([tool]))
    await pipeline.on_transcript_completed("Loop please.")
    await asyncio.sleep(0.3)

    assert len(tool.calls) == MAX_TOOL_ROUNDS
    assert fallback_phrase("en") in tts.spoken
    await _stop(ws, task)


async def test_slow_tool_speaks_bridging_phrase_first() -> None:
    ws = FakeBridgeSocket()
    tts = ScriptedTts()
    tool = FakeTool("check", slow=True, delay=0.05)
    llm = ScriptedToolLlm(
        [
            [ToolCallRequest(id="c1", name="check", arguments="{}")],  # no speech this round
            [SpeakSentence("All set.")],
        ]
    )
    pipeline, task = await _start_pipeline(ws, llm, tts, ToolRegistry([tool]))
    await pipeline.on_transcript_completed("Is there space?")
    await asyncio.sleep(0.3)

    bridge_line = thinking_phrase("en")
    assert bridge_line in tts.spoken
    assert tts.spoken.index(bridge_line) < tts.spoken.index("All set.")
    await _stop(ws, task)


async def test_slow_tool_stays_quiet_when_model_already_spoke() -> None:
    ws = FakeBridgeSocket()
    tts = ScriptedTts()
    tool = FakeTool("check", slow=True, delay=0.05)
    llm = ScriptedToolLlm(
        [
            [SpeakSentence("One moment."), ToolCallRequest(id="c1", name="check", arguments="{}")],
            [SpeakSentence("All set.")],
        ]
    )
    pipeline, task = await _start_pipeline(ws, llm, tts, ToolRegistry([tool]))
    await pipeline.on_transcript_completed("Is there space?")
    await asyncio.sleep(0.3)

    assert thinking_phrase("en") not in tts.spoken
    await _stop(ws, task)


async def test_late_tool_result_from_old_generation_writes_nothing() -> None:
    """I1: generation moved on while the tool ran, so nothing may be recorded."""
    ws = FakeBridgeSocket()
    tts = ScriptedTts()

    class BumpingTool(FakeTool):
        async def run(self, args, ctx):
            ctx.session.generation_id += 1  # a barge-in landing mid-call
            return ToolResult(ok=True, data={"stale": True})

    tool = BumpingTool("bump")
    llm = ScriptedToolLlm(
        [
            [ToolCallRequest(id="c1", name="bump", arguments="{}")],
            [SpeakSentence("This must never be spoken.")],
        ]
    )
    pipeline, task = await _start_pipeline(ws, llm, tts, ToolRegistry([tool]))
    await pipeline.on_transcript_completed("Go.")
    await asyncio.sleep(0.2)

    assert not any(m["role"] == "tool" for m in pipeline.session.history)
    assert "This must never be spoken." not in tts.spoken
    assert len(llm.calls) == 1  # the loop stopped instead of streaming again
    await _stop(ws, task)
