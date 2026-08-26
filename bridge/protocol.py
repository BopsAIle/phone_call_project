"""Wire protocol with the frontend: binary PCM + JSON control on one WebSocket.

Matches documents/backend_contract/ai-bridge-contract.md.
Frontend here is the telephony backend (or a browser demo) that dials this service.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional, Union

# --- Audio (both directions) ---
SAMPLE_RATE = 16_000
CHANNELS = 1
SAMPLE_WIDTH = 2  # PCM16 little-endian
BYTES_PER_SECOND = SAMPLE_RATE * CHANNELS * SAMPLE_WIDTH
FRAME_MS = 100
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000  # 1_600
FRAME_BYTES = FRAME_SAMPLES * SAMPLE_WIDTH  # 3_200

# --- Control events ---
EVENT_SESSION_INIT = "session.init"
EVENT_INTERRUPT = "interrupt"

LOCALES = frozenset({"en", "de"})

INTERRUPT_JSON = json.dumps({"event": EVENT_INTERRUPT}, separators=(",", ":"))


class ProtocolError(ValueError):
    """Malformed control JSON that the socket should ignore (contract §9)."""


@dataclass(frozen=True)
class SessionInit:
    call_id: str
    store_name: str
    timezone: str
    locale: str
    greeting: str

    def to_dict(self) -> dict[str, str]:
        return {
            "event": EVENT_SESSION_INIT,
            "callId": self.call_id,
            "storeName": self.store_name,
            "timezone": self.timezone,
            "locale": self.locale,
            "greeting": self.greeting,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> SessionInit:
        locale = str(payload.get("locale") or "en")
        if locale not in LOCALES:
            locale = locale[:2].lower() if locale else "en"
        return cls(
            call_id=str(payload.get("callId") or ""),
            store_name=str(payload.get("storeName") or ""),
            timezone=str(payload.get("timezone") or "UTC"),
            locale=locale,
            greeting=str(payload.get("greeting") or ""),
        )


@dataclass(frozen=True)
class Interrupt:
    event: str = EVENT_INTERRUPT

    def to_json(self) -> str:
        return INTERRUPT_JSON


@dataclass(frozen=True)
class UnknownControl:
    event: str
    payload: dict[str, Any]


ControlMessage = Union[SessionInit, Interrupt, UnknownControl]


def parse_text_frame(raw: str) -> Optional[ControlMessage]:
    """Parse a WebSocket text frame. Returns None if JSON is invalid."""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    event = payload.get("event")
    if event == EVENT_SESSION_INIT:
        return SessionInit.from_payload(payload)
    if event == EVENT_INTERRUPT:
        return Interrupt()
    return UnknownControl(event=str(event or ""), payload=payload)


def whole_pcm16(data: bytes) -> bytes:
    """Drop a trailing odd byte so a frame never splits a 16-bit sample."""
    if len(data) % 2:
        return data[:-1]
    return data


class PcmFramer:
    """Accumulate PCM16 and emit ~100 ms frames (3.200 bytes) for the frontend → AI path."""

    def __init__(self, frame_bytes: int = FRAME_BYTES) -> None:
        if frame_bytes % 2:
            raise ValueError("frame_bytes must be even")
        self.frame_bytes = frame_bytes
        self._buf = bytearray()

    def push(self, pcm: bytes) -> list[bytes]:
        pcm = whole_pcm16(pcm)
        if not pcm:
            return []
        self._buf.extend(pcm)
        frames: list[bytes] = []
        while len(self._buf) >= self.frame_bytes:
            frames.append(bytes(self._buf[: self.frame_bytes]))
            del self._buf[: self.frame_bytes]
        return frames

    def flush(self) -> bytes:
        leftover = whole_pcm16(bytes(self._buf))
        self._buf.clear()
        return leftover
