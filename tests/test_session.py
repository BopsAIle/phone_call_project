from __future__ import annotations

import asyncio
import json

from bridge.session import CallPipeline, CallState
from llm.stream import fallback_phrase
from tests.fakes import FakeBridgeSocket, FakeSTT, ScriptedLlm, ScriptedTts, SlowTts

INIT = {
    "event": "session.init",
    "callId": "clx8k2p9v0000abcd1234efgh",
    "storeName": "Bella Vista",
    "timezone": "Europe/Berlin",
    "locale": "en",
    "greeting": "Thanks for calling Bella Vista. This is an automated assistant — how can I help you today?",
}


async def _start_pipeline(ws, stt, llm, tts):
    pipeline = CallPipeline(ws, stt=stt, llm=llm, tts=tts)
    task = asyncio.create_task(pipeline.run())
    await asyncio.sleep(0.02)
    return pipeline, task


async def _stop(ws, task) -> None:
    await ws.disconnect()
    await asyncio.wait_for(task, timeout=2)


async def test_greeting_speaks_verbatim_and_sends_pcm() -> None:
    ws = FakeBridgeSocket()
    tts = ScriptedTts()
    pipeline, task = await _start_pipeline(ws, FakeSTT(), ScriptedLlm([]), tts)
    await ws.push_text(json.dumps(INIT))
    await asyncio.sleep(0.1)
    assert tts.spoken == [INIT["greeting"]]
    assert any(kind == "bytes" for kind, _ in ws.sent)
    assert pipeline.session.state == CallState.LISTENING
    assert pipeline.session.generation_id == 1
    assistant = [m for m in pipeline.session.history if m["role"] == "assistant"]
    assert assistant == [{"role": "assistant", "content": INIT["greeting"]}]
    await _stop(ws, task)


async def test_pcm_before_init_is_accepted() -> None:
    ws = FakeBridgeSocket()
    stt = FakeSTT()
    pipeline, task = await _start_pipeline(ws, stt, ScriptedLlm([]), ScriptedTts())
    frame = b"\x00\x01" * 1600
    await ws.push_bytes(frame)
    await asyncio.sleep(0.05)
    assert pipeline.session.inited is False
    assert pipeline.session.state == CallState.INIT
    assert stt.appended  # forwarded to STT, socket stays up
    await _stop(ws, task)
    assert pipeline.session.state == CallState.CLOSED


async def test_bad_json_is_ignored() -> None:
    ws = FakeBridgeSocket()
    pipeline, task = await _start_pipeline(ws, FakeSTT(), ScriptedLlm([]), ScriptedTts())
    await ws.push_text("not-json{")
    await asyncio.sleep(0.05)
    assert pipeline.session.inited is False
    await _stop(ws, task)


async def test_empty_transcript_speaks_fallback() -> None:
    ws = FakeBridgeSocket()
    tts = ScriptedTts()
    pipeline, task = await _start_pipeline(ws, FakeSTT(), ScriptedLlm(["should not run"]), tts)
    await ws.push_text(json.dumps(INIT))
    await asyncio.sleep(0.1)
    await pipeline.on_transcript_completed("")
    await asyncio.sleep(0.1)
    assert fallback_phrase("en") in tts.spoken
    await _stop(ws, task)


async def test_transcript_runs_llm_and_tts() -> None:
    ws = FakeBridgeSocket()
    tts = ScriptedTts()
    llm = ScriptedLlm(["We have a table at seven."])
    pipeline, task = await _start_pipeline(ws, FakeSTT(), llm, tts)
    await ws.push_text(json.dumps(INIT))
    await asyncio.sleep(0.1)
    await pipeline.on_transcript_completed("A table for two tonight.")
    await asyncio.sleep(0.1)
    assert llm.calls
    user_msgs = [m for m in llm.calls[0] if m["role"] == "user"]
    assert user_msgs[-1]["content"] == "A table for two tonight."
    assert "We have a table at seven." in tts.spoken
    await _stop(ws, task)


async def test_llm_error_speaks_fallback() -> None:
    ws = FakeBridgeSocket()
    tts = ScriptedTts()
    llm = ScriptedLlm([], error=RuntimeError("boom"))
    pipeline, task = await _start_pipeline(ws, FakeSTT(), llm, tts)
    await ws.push_text(json.dumps(INIT))
    await asyncio.sleep(0.1)
    await pipeline.on_transcript_completed("Hello")
    await asyncio.sleep(0.1)
    assert fallback_phrase("en") in tts.spoken
    assert pipeline.session.state == CallState.LISTENING
    await _stop(ws, task)


async def test_barge_in_during_greeting_sends_interrupt_last() -> None:
    ws = FakeBridgeSocket()
    tts = SlowTts(hold=0.5)
    pipeline, task = await _start_pipeline(ws, FakeSTT(), ScriptedLlm([]), tts)
    await ws.push_text(json.dumps(INIT))
    await asyncio.sleep(0.05)
    assert pipeline.session.state == CallState.GREETING
    await pipeline.on_speech_started()
    await asyncio.sleep(0.1)
    kinds = [kind for kind, _ in ws.sent]
    assert "text" in kinds
    last_text = [payload for kind, payload in ws.sent if kind == "text"][-1]
    assert json.loads(last_text) == {"event": "interrupt"}
    text_index = max(i for i, kind in enumerate(kinds) if kind == "text")
    assert all(kind != "bytes" for kind in kinds[text_index + 1 :])
    assert pipeline.session.state == CallState.LISTENING
    assert pipeline.session.generation_id >= 2
    await _stop(ws, task)
