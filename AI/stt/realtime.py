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

# Tuned for non-native callers: they hesitate mid-sentence, and a 450 ms cut
# chops the turn into fragments that give the model almost no context to work with.
VAD = {
    "type": "server_vad",
    "threshold": 0.45,
    "prefix_padding_ms": 400,
    "silence_duration_ms": 800,
}

def vad_config(silence_duration_ms: int | None = None) -> dict[str, Any]:
    """VAD mặc định, có thể chỉnh riêng mốc chờ im lặng.

    800 ms là mặc định **có chủ đích**: playbook đo được mốc cũ 450 ms cắt vụn câu của
    người nói tiếng Anh không phải bản ngữ, làm STT nghe sai nhiều hơn. Đây là chặng chờ
    cố định lớn nhất mỗi lượt, nên biến môi trường tồn tại để A/B có số đo — đừng hạ khi
    chưa chạy scripts/turn_stats.py trước và sau.
    """
    cfg = dict(VAD)
    if silence_duration_ms:
        cfg["silence_duration_ms"] = int(silence_duration_ms)
    return cfg


def build_transcription_session(
    model: str,
    languages: tuple[str, ...],
    *,
    prompt: str = "",
    keywords: tuple[str, ...] = (),
    silence_duration_ms: int = 0,
    noise_reduction: dict[str, str] | None = None,
    unsupported: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """Cấu hình phiên transcription. Một nguồn duy nhất cho cả runtime lẫn công cụ đo.

    Trước đây scripts/stt_eval.py tự dựng cấu hình riêng, và nó bỏ quên `prompt` —
    mà `prompt` là kênh mớm tên món DUY NHẤT trên gpt-4o-transcribe. Nghĩa là công cụ
    đo một cấu hình khác với cấu hình chạy thật, đúng ở chiều đang muốn tinh chỉnh.
    Gộp về một hàm để chuyện lệch đó không thể xảy ra lần nữa.
    """
    transcription: dict[str, Any] = {"model": model}
    langs = tuple(languages) or ("en",)

    def put(field: str, value: Any) -> None:
        if field not in unsupported and value:
            transcription[field] = value

    if model in NEW_MODELS:
        # `languages` and `language` are mutually exclusive — sending both is rejected.
        put("languages", list(langs))
        put("delay", TRANSCRIPTION_DELAY)
        put("keywords", list(keywords))
    else:
        transcription["language"] = langs[0]
    put("prompt", prompt)
    reduction = NOISE_REDUCTION if noise_reduction is None else noise_reduction
    return {
        "type": "transcription",
        "audio": {
            "input": {
                "format": {"type": "audio/pcm", "rate": 24000},
                "transcription": transcription,
                "turn_detection": vad_config(silence_duration_ms),
                "noise_reduction": dict(reduction) if reduction else None,
            }
        },
    }


# Only these two accept `keywords`; everything older takes `language` (singular).
NEW_MODELS = frozenset({"gpt-transcribe", "gpt-live-transcribe"})

# Higher delay lets the model hear more before it commits, at the cost of later
# partials. "low" is the balance for a phone call; try "medium" if accuracy lags.
TRANSCRIPTION_DELAY = "low"

# The browser stopped running its own NS (it ate the fricatives a non-native
# speaker already articulates weakly), so OpenAI cleans the signal instead.
# Use "far_field" for speakerphone or a reverberant room.
NOISE_REDUCTION: dict[str, str] | None = {"type": "near_field"}

# Optional fields the server may reject depending on model/account. Rejecting one
# must not cost us the session, so we drop it and re-send.
OPTIONAL_FIELDS = ("delay", "keywords", "prompt", "languages")


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
    def __init__(
        self,
        client: Any,
        model: str,
        call_id: str = "",
        languages: tuple[str, ...] = ("en",),
        silence_duration_ms: int = 0,
    ) -> None:
        self._client = client
        self._model = model
        self._call_id = call_id
        self._languages = tuple(languages) or ("en",)
        self._silence_ms = int(silence_duration_ms or 0)
        self._prompt = ""
        self._keywords: list[str] = []
        self._unsupported: set[str] = set()
        self._handler: Optional[SttHandler] = None
        self._manager: Any = None
        self._connection: Any = None
        self._recv_task: Optional[asyncio.Task[None]] = None
        self._ready = asyncio.Event()
        self.closed = False
        self._last_transcript_key = ""
        self._logged_events = 0
        self._partial = ""

    @property
    def is_ready(self) -> bool:
        return self._connection is not None and not self.closed

    async def start(self, handler: SttHandler, locale: str | None = None) -> None:
        del locale  # kept for the caller's signature; language comes from settings
        self._handler = handler
        if self._client is None:
            logger.error("No OpenAI client; STT disabled callId=%s", self._call_id)
            return
        try:
            self._manager = self._client.realtime.connect(
                extra_query={"intent": "transcription"},
            )
            self._connection = await self._manager.enter()
            await self._connection.session.update(session=self._session_payload())
            self._recv_task = asyncio.create_task(self._recv_loop(), name="stt-recv")
            self._ready.set()
            logger.info("Realtime transcription connected callId=%s", self._call_id)
        except Exception:
            logger.exception("Failed to open Realtime transcription callId=%s", self._call_id)
            await self.close()

    def _session_payload(self) -> dict[str, Any]:
        return build_transcription_session(
            self._model,
            self._languages,
            prompt=self._prompt,
            keywords=tuple(self._keywords),
            silence_duration_ms=self._silence_ms,
            unsupported=frozenset(self._unsupported),
        )

    async def update_context(
        self,
        *,
        prompt: str = "",
        keywords: list[str] | None = None,
    ) -> None:
        """Re-bias the live session with what we now know the caller can order.

        Safe to call repeatedly: the catalog arrives after the socket opens, and
        the menu later still, so context is pushed in stages during the call.
        """
        if prompt:
            self._prompt = prompt
        if keywords is not None:
            self._keywords = list(keywords)
        if not self._connection or self.closed:
            return
        try:
            await self._connection.session.update(session=self._session_payload())
            logger.info(
                "STT context updated callId=%s keywords=%s",
                self._call_id,
                len(self._keywords),
            )
        except Exception:
            # A failed update must never kill the call; the previous session stands.
            logger.exception("STT session.update(context) failed callId=%s", self._call_id)

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
            self._partial = ""
            logger.info("STT speech_started callId=%s", self._call_id)
            await handler.on_speech_started()
        elif et == SPEECH_STOPPED:
            logger.info("STT speech_stopped callId=%s", self._call_id)
            await handler.on_speech_stopped()
        elif et == TRANSCRIPT_DELTA:
            delta = _event_field(event, "delta", "") or ""
            # Log the running partial so the caller's words appear on screen while
            # they are still speaking, not only when the turn is committed.
            self._partial += str(delta)
            if self._partial.strip():
                logger.info("Người gọi (đang nói): %s", self._partial.strip())
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
            self._partial = ""
            logger.info("Người gọi (STT) callId=%s: %s", self._call_id, text)
            await handler.on_transcript_completed(text)
        elif et == TRANSCRIPT_FAILED:
            logger.error("STT transcription failed callId=%s event=%s", self._call_id, event)
            await handler.on_transcript_failed()
        elif et == "error":
            err = _event_field(event, "error", event)
            logger.error("Realtime error callId=%s %s", self._call_id, err)
            if await self._maybe_drop_unsupported(err):
                return
            await self._warn_if_vad_unsupported(err)
        else:
            if "transcript" in et:
                text = transcript_from_event(event)
                logger.info("STT event callId=%s type=%s text=%r", self._call_id, et, text)
                if text:
                    await handler.on_transcript_completed(text)
                    return
            logger.debug("Realtime event %s callId=%s", et, self._call_id)

    @staticmethod
    def _error_message(err: Any) -> str:
        if isinstance(err, dict):
            return str(err.get("message") or "")
        return str(getattr(err, "message", err) or "")

    async def _maybe_drop_unsupported(self, err: Any) -> bool:
        """Drop an optional field the server just rejected, then re-send.

        Model/account support for `delay`, `keywords` and friends is not uniform,
        and the docs disagree with the SDK on `delay`. Losing one hint beats losing
        transcription for the whole call.
        """
        lowered = self._error_message(err).lower()
        dropped = [
            field
            for field in OPTIONAL_FIELDS
            if field in lowered and field not in self._unsupported
        ]
        if not dropped or self._connection is None or self.closed:
            return False
        self._unsupported.update(dropped)
        logger.warning(
            "STT rejected %s; retrying without it callId=%s",
            ", ".join(dropped),
            self._call_id,
        )
        try:
            await self._connection.session.update(session=self._session_payload())
        except Exception:
            logger.exception("STT retry without %s failed callId=%s", dropped, self._call_id)
        return True

    async def _warn_if_vad_unsupported(self, err: Any) -> None:
        """Server VAD is not optional here — say so plainly instead of degrading.

        Measured: gpt-live-transcribe answers "Turn detection is not supported for
        this transcription model". Without VAD there is no speech_started (no
        barge-in) and nothing commits the input buffer, so no transcript ever
        arrives. Switching the session to type "realtime" is not a way out either:
        the API refuses that on a transcription socket.
        """
        lowered = self._error_message(err).lower()
        if "turn_detection" not in lowered and "turn detection" not in lowered:
            return
        logger.error(
            "STT model %r does not support server VAD, so this call cannot detect "
            "turns or barge-in. Set OPENAI_STT_MODEL to gpt-4o-transcribe. callId=%s",
            self._model,
            self._call_id,
        )

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
