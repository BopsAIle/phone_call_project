from __future__ import annotations

import asyncio
import json

from bridge.session import CallSession
from turn.barge_in import OutboundGate, abort_and_interrupt
from tests.fakes import FakeBridgeSocket


async def test_interrupt_follows_in_flight_audio() -> None:
    session = CallSession()
    session.generation_id = 1
    ws = FakeBridgeSocket()
    original_send = ws.send_bytes

    async def slow_send(data: bytes) -> None:
        await asyncio.sleep(0.05)
        await original_send(data)

    ws.send_bytes = slow_send  # type: ignore[method-assign]
    gate = OutboundGate(ws, session)

    send_task = asyncio.create_task(gate.send_audio(1, b"\x00\x01" * 16))
    await asyncio.sleep(0.01)
    await abort_and_interrupt(session=session, outbound=gate, abort_work=lambda: None)
    await send_task

    kinds = [kind for kind, _ in ws.sent]
    assert kinds[-1] == "text"
    assert json.loads(ws.sent[-1][1]) == {"event": "interrupt"}
    assert session.generation_id == 2
    assert session.playing is False
    assert session.state == "Listening"


async def test_stale_generation_does_not_send_after_interrupt() -> None:
    session = CallSession()
    session.generation_id = 1
    ws = FakeBridgeSocket()
    gate = OutboundGate(ws, session)
    await abort_and_interrupt(session=session, outbound=gate, abort_work=lambda: None)
    sent = await gate.send_audio(1, b"\x00\x01" * 8)
    assert sent is False
    assert all(kind != "bytes" for kind, _ in ws.sent)
    assert json.loads(ws.sent[0][1]) == {"event": "interrupt"}
