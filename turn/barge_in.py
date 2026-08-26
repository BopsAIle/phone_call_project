"""Barge-in: abort stale LLM/TTS and send `interrupt` after the last sent audio frame."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Awaitable, Callable, Protocol

logger = logging.getLogger(__name__)

INTERRUPT_JSON = json.dumps({"event": "interrupt"}, separators=(",", ":"))


class BridgeSocket(Protocol):
    async def send_bytes(self, data: bytes) -> None: ...

    async def send_text(self, data: str) -> None: ...


class SessionLike(Protocol):
    generation_id: int
    playing: bool
    state: Any
    closed: bool
    call_id: str

    def commit_partial_assistant(self) -> None: ...

    def mark_audio_sent(self) -> None: ...


class OutboundGate:
    """Serializes binary audio and the interrupt text frame on one WebSocket.

    Holding this lock around a send is what makes contract §6.3 true: once
    barge-in acquires it, every audio frame already handed to the writer has
    gone out, and no stale frame can follow the interrupt.
    """

    def __init__(self, websocket: BridgeSocket, session: SessionLike) -> None:
        self.websocket = websocket
        self.session = session
        self.lock = asyncio.Lock()

    async def send_audio(self, generation_id: int, pcm: bytes) -> bool:
        if len(pcm) % 2:
            pcm = pcm[:-1]
        if not pcm:
            return True
        async with self.lock:
            if self.session.closed or self.session.generation_id != generation_id:
                return False
            await self.websocket.send_bytes(pcm)
            self.session.mark_audio_sent()
            return True

    async def send_interrupt(self) -> None:
        async with self.lock:
            await self._send_interrupt_locked()

    async def _send_interrupt_locked(self) -> None:
        if self.session.closed:
            return
        await self.websocket.send_text(INTERRUPT_JSON)


async def abort_and_interrupt(
    *,
    session: SessionLike,
    outbound: OutboundGate,
    abort_work: Callable[[], Awaitable[None] | None],
) -> int:
    """Run the required barge-in sequence and return the new generation_id.

    1. Bump generation_id so in-flight LLM/TTS become stale.
    2. Do not send any more audio of the aborted turn.
    3. Send interrupt after the last binary frame already sent.
    4. Cancel local work *after* releasing the send lock (must not take it).
    5. Caller keeps appending user PCM to STT.
    """
    async with outbound.lock:
        session.generation_id += 1
        session.playing = False
        session.state = "BargeIn"
        logger.info(
            "barge-in generation_id=%s callId=%s",
            session.generation_id,
            session.call_id,
        )
        await outbound._send_interrupt_locked()
        session.commit_partial_assistant()
        session.state = "Listening"

    result = abort_work()
    if asyncio.iscoroutine(result):
        await result
    return session.generation_id
