"""OpenAI Realtime transcription + server_vad. The model does not speak."""
## file này chuyển user nói thành text
from __future__ import annotations

import asyncio
import base64
import logging
from typing import Any, Optional, Protocol

logger = logging.getLogger(__name__)

SPEECH_STARTED = "input_audio_buffer.speech_started"
SPEECH_STOPPED = "input_audio_buffer.speech_stopped"
TRANSCRIPT_DELTA = "conversation.item.input_audio_transcription.delta"
TRANSCRIPT_DONE = "conversation.item.input_audio_transcription.completed"
TRANSCRIPT_FAILED = "conversation.item.input_audio_transcription.failed"

VAD = {
    "type": "server_vad",
    "threshold": 0.3,
    "prefix_padding_ms": 300,
    "silence_duration_ms": 450,
}


class SttHandler(Protocol):
    async def on_speech_started(self) -> None: ...

    async def on_speech_stopped(self) -> None: ...

    async def on_transcript_delta(self, delta: str) -> None: ...

    async def on_transcript_completed(self, text: str) -> None: ...

    async def on_transcript_failed(self) -> None: ...


def _event_type(event: Any) -> str:
    if isinstance(event, dict):
        raw = event.get("type") or ""
    else:
        raw = getattr(event, "type", "") or ""
    if hasattr(raw, "value"):
        raw = raw.value
    return str(raw or "")


def _event_field(event: Any, name: str, default: Any = None) -> Any:
    if isinstance(event, dict):
        return event.get(name, default)
    return getattr(event, name, default)


def transcript_from_event(event: Any) -> str:
    """Pull transcribed text from Realtime event shapes (top-level or item.content)."""
    direct = str(_event_field(event, "transcript", "") or "").strip()
    if direct:
        return direct
    item = _event_field(event, "item")
    if item is None:
        return ""
    role = _event_field(item, "role") if not isinstance(item, dict) else item.get("role")
    if role and str(role) != "user":
        return ""
    content = _event_field(item, "content") if not isinstance(item, dict) else item.get("content")
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for part in content:
        if isinstance(part, dict):
            piece = part.get("transcript") or part.get("text") or ""
        else:
            piece = getattr(part, "transcript", None) or getattr(part, "text", None) or ""
        text = str(piece or "").strip()
        if text:
            parts.append(text)
    return " ".join(parts).strip()

##stt
class RealtimeTranscriptionClient:
    def __init__(self, client: Any, model: str, call_id: str = "") -> None:
        self._client = client
        self._model = model
        self._call_id = call_id
        self._handler: Optional[SttHandler] = None
        self._manager: Any = None
        self._connection: Any = None
        self._recv_task: Optional[asyncio.Task[None]] = None
        self._ready = asyncio.Event()
        self.closed = False
        self._last_transcript_key = ""
        self._logged_events = 0

    @property
    def is_ready(self) -> bool:
        return self._connection is not None and not self.closed

    async def start(self, handler: SttHandler, locale: str | None = None) -> None:
        self._handler = handler
        if self._client is None:
            logger.error("No OpenAI client; STT disabled callId=%s", self._call_id)
            return
        try:
            self._manager = self._client.realtime.connect(
                extra_query={"intent": "transcription"},
            )
            self._connection = await self._manager.enter()
            await self._connection.session.update(session=self._session_payload(locale))
            self._recv_task = asyncio.create_task(self._recv_loop(), name="stt-recv")
            self._ready.set()
            logger.info("Realtime transcription connected callId=%s", self._call_id)
        except Exception:
            logger.exception("Failed to open Realtime transcription callId=%s", self._call_id)
            await self.close()

    def _session_payload(self, locale: str | None) -> dict[str, Any]:
        # Pin transcription.language to English: the deployment only handles
        # English speech, so forcing "en" avoids auto-detect flip-flopping on
        # short/noisy turns.
        del locale  # pinned to English regardless of session locale
        return {
            "type": "transcription",
            "audio": {
                "input": {
                    "format": {"type": "audio/pcm", "rate": 24000},
                    "transcription": {"model": self._model, "language": "en"},
                    "turn_detection": dict(VAD),
                    # Browser already filters; OpenAI NR before VAD can swallow laptop speech.
                    "noise_reduction": None,
                }
            },
        }

    async def update_language(self, locale: str) -> None:
        if not self._connection or self.closed:
            return
        try:
            await self._connection.session.update(session=self._session_payload(locale))
        except Exception:
            logger.exception("STT session.update(language) failed callId=%s", self._call_id)

    async def append_pcm24(self, pcm24: bytes) -> None:
        if not pcm24 or self.closed or self._connection is None:
            return
        audio_b64 = base64.b64encode(pcm24).decode("ascii")
        await self._connection.input_audio_buffer.append(audio=audio_b64)

    async def _recv_loop(self) -> None:
        assert self._connection is not None
        try:
            async for event in self._connection:
                if self.closed:
                    return
                await self._dispatch(event)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Realtime STT receive loop ended callId=%s", self._call_id)

    async def _dispatch(self, event: Any) -> None:
        et = _event_type(event)
        handler = self._handler
        if handler is None:
            return
        if self._logged_events < 12:
            self._logged_events += 1
            logger.info("STT event[%s] callId=%s type=%s", self._logged_events, self._call_id, et or "?")
        if et in {"session.created", "session.updated", "transcription_session.updated"}:
            logger.info("STT session event callId=%s type=%s", self._call_id, et)
        if et == SPEECH_STARTED:
            logger.info("STT speech_started callId=%s", self._call_id)
            await handler.on_speech_started()
        elif et == SPEECH_STOPPED:
            logger.info("STT speech_stopped callId=%s", self._call_id)
            await handler.on_speech_stopped()
        elif et == TRANSCRIPT_DELTA:
            delta = _event_field(event, "delta", "") or ""
            logger.debug("STT delta callId=%s %r", self._call_id, delta)
            await handler.on_transcript_delta(delta)
        elif et == TRANSCRIPT_DONE or et in {"conversation.item.done", "conversation.item.added"}:
            text = transcript_from_event(event)
            if et != TRANSCRIPT_DONE and not text:
                return
            key = str(_event_field(event, "item_id", "") or "")
            item = _event_field(event, "item")
            if not key and item is not None:
                key = str(_event_field(item, "id", "") or "")
            if key and key == self._last_transcript_key:
                return
            if key:
                self._last_transcript_key = key
            logger.info("Người gọi (STT): %s", text)
            await handler.on_transcript_completed(text)
        elif et == TRANSCRIPT_FAILED:
            logger.error("STT transcription failed callId=%s event=%s", self._call_id, event)
            await handler.on_transcript_failed()
        elif et == "error":
            err = _event_field(event, "error", event)
            logger.error("Realtime error callId=%s %s", self._call_id, err)
            await self._maybe_fallback_session(err)
        else:
            if "transcript" in et:
                text = transcript_from_event(event)
                logger.info("STT event callId=%s type=%s text=%r", self._call_id, et, text)
                if text:
                    await handler.on_transcript_completed(text)
                    return
            logger.debug("Realtime event %s callId=%s", et, self._call_id)

    async def _maybe_fallback_session(self, err: Any) -> None:
        """If the transcription model rejects VAD, use a silent realtime session."""
        message = ""
        if isinstance(err, dict):
            message = str(err.get("message") or "")
        else:
            message = str(getattr(err, "message", err) or "")
        lowered = message.lower()
        if "turn_detection" not in lowered and "vad" not in lowered:
            return
        if self._connection is None:
            return
        logger.warning(
            "STT VAD rejected; falling back to realtime session with create_response=false callId=%s",
            self._call_id,
        )
        try:
            await self._connection.session.update(
                session={
                    "type": "realtime",
                    "audio": {
                        "input": {
                            "format": {"type": "audio/pcm", "rate": 24000},
                            "transcription": {"model": self._model, "language": "en"},
                            "turn_detection": {
                                **VAD,
                                "create_response": False,
                                "interrupt_response": False,
                            },
                        }
                    },
                }
            )
        except Exception:
            logger.exception("Fallback realtime session.update failed callId=%s", self._call_id)

    async def close(self) -> None:
        self.closed = True
        self._ready.clear()
        if self._recv_task is not None:
            self._recv_task.cancel()
            try:
                await self._recv_task
            except (asyncio.CancelledError, Exception):
                pass
            self._recv_task = None
        if self._connection is not None:
            try:
                await self._connection.close()
            except Exception:
                logger.debug("STT close failed callId=%s", self._call_id, exc_info=True)
            self._connection = None
        self._manager = None
