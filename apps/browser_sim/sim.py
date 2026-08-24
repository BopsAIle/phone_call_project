"""Browser phone simulator: guest speaks or types in /browser, each utterance
POSTs to /browser/{session}/utterance, and GPT-4o-mini uses booking tools.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from openai import AsyncOpenAI

from apps.voice_agent.nlg import (
    GREETING,
    REPEAT_LINE,
    TRANSFER_LINE,
    call_context_note,
    load_system_prompt,
    opening_line,
)
from apps.voice_agent.slot_parse import delta_from_llm
from shared.config import REPO_ROOT, Settings
from shared.slots import missing_fields

logger = logging.getLogger(__name__)

BROWSER_HTML_PATH = REPO_ROOT / "apps" / "browser_sim" / "static" / "browser.html"
_TTS_CACHE_MAX = 32
_tts_cache: OrderedDict[str, str] = OrderedDict()
_openai_clients: dict[str, AsyncOpenAI] = {}
STT_PROMPT = (
    "Vietnamese restaurant booking call. Capture party size, date, time, "
    "branch names Quan 1 and Thao Dien, guest name, and phone numbers."
)
TTS_INSTRUCTIONS = (
    "Speak Vietnamese with diacritics, clearly and warmly, as a graceful "
    "restaurant host on a phone call. Natural intonation, unhurried but not slow."
)
MAX_TOOL_ROUNDS = 8

BROWSER_LLM_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "update_slots",
            "description": (
                "Save booking fields just extracted from the caller. Call this whenever "
                "the guest mentions guests, date, time, branch, name, phone, or notes."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "guest_count": {
                        "type": "integer",
                        "description": "Party size if mentioned.",
                    },
                    "date": {
                        "type": "string",
                        "description": "Booking date as YYYY-MM-DD if mentioned.",
                    },
                    "time": {
                        "type": "string",
                        "description": "Arrival time as HH:MM if mentioned.",
                    },
                    "branch": {
                        "type": "string",
                        "description": "Branch name or code if mentioned (quan-1 or thao-dien).",
                    },
                    "customer_name": {
                        "type": "string",
                        "description": "Guest name if mentioned.",
                    },
                    "phone": {
                        "type": "string",
                        "description": "Phone number if mentioned.",
                    },
                    "notes": {
                        "type": "string",
                        "description": "Birthday, children, high chair, seating, or other notes.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_knowledge",
            "description": (
                "Search internal restaurant documents for hours, parking, children, "
                "dress code, cancellation, branches. Never use this to decide if a table is free."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The guest question."},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "confirm_booking",
            "description": (
                "Create the reservation after the guest confirmed the summary. "
                "Only call when backend already reported availability."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "transfer_to_staff",
            "description": (
                "Hand the call to a human. Use for staff request, events, invoices, "
                "allergies, unknown policy, or repeated availability failure. "
                "On the browser simulator this ends the fake call."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": (
                            "Short machine reason such as guest_requested_human, "
                            "complex_event, large_party."
                        ),
                    },
                },
                "required": ["reason"],
            },
        },
    },
]


def browser_page_url(settings: Settings) -> str:
    return settings.browser_sim_base_url.rstrip("/") + "/browser"


def browser_voice_webhook_url(settings: Settings) -> str:
    return settings.browser_sim_base_url.rstrip("/") + "/browser/voice"


def new_browser_call_sid() -> str:
    return f"CA-browser-{uuid4().hex[:12]}"


class BrowserChatStore:
    """In-memory LLM histories for fake browser calls."""

    def __init__(self) -> None:
        self._messages: dict[str, list[dict[str, Any]]] = {}

    def start(self, session_id: str, opening: str | None = None) -> list[dict[str, Any]]:
        history = [
            {"role": "system", "content": load_system_prompt()},
            {"role": "system", "content": call_context_note()},
            {"role": "assistant", "content": opening or GREETING},
        ]
        self._messages[session_id] = history
        return history

    def get(self, session_id: str) -> list[dict[str, Any]] | None:
        return self._messages.get(session_id)

    def drop(self, session_id: str) -> None:
        self._messages.pop(session_id, None)


@dataclass
class BrowserTurnResult:
    assistant_text: str
    user_text: str | None = None
    audio_b64: str | None = None
    audio_format: str = "mp3"
    session_id: str = ""
    call_sid: str | None = None
    action: str = "ask"
    booking_id: str | None = None
    transfer_reason: str | None = None
    ended: bool = False
    slots: dict[str, Any] = field(default_factory=dict)

    def as_payload(self) -> dict[str, Any]:
        return {
            "assistant_text": self.assistant_text,
            "user_text": self.user_text,
            "audio_b64": self.audio_b64,
            "audio_format": self.audio_format,
            "session_id": self.session_id,
            "call_sid": self.call_sid,
            "action": self.action,
            "booking_id": self.booking_id,
            "transfer_reason": self.transfer_reason,
            "ended": self.ended,
            "slots": self.slots,
        }


async def start_browser_call(
    *,
    engine: Any,
    chats: BrowserChatStore,
    settings: Settings,
    from_number: str | None = None,
    call_sid: str | None = None,
) -> BrowserTurnResult:
    sid = call_sid or new_browser_call_sid()
    session = await engine.backend.create_session(
        call_sid=sid,
        from_number=from_number,
        multi_branch=settings.multi_branch,
    )
    opening = opening_line(session.slots)
    chats.start(session.id, opening=opening)
    session, audio_b64 = await asyncio.gather(
        engine.backend.append_transcript(session.id, "assistant", opening),
        synthesize_speech(settings, opening),
    )
    return BrowserTurnResult(
        assistant_text=opening,
        audio_b64=audio_b64,
        session_id=session.id,
        call_sid=session.call_sid,
        action="ask",
        slots=session.slots.model_dump(mode="json"),
    )


async def handle_browser_utterance(
    *,
    engine: Any,
    chats: BrowserChatStore,
    settings: Settings,
    session_id: str,
    text: str | None = None,
    audio_b64: str | None = None,
    audio_filename: str = "speech.webm",
) -> BrowserTurnResult:
    history = chats.get(session_id)
    if history is None:
        raise KeyError(session_id)

    session = await engine.backend.get_session(session_id)
    if session.status in {"booked", "transferred"}:
        line = (
            TRANSFER_LINE
            if session.status == "transferred"
            else f"Dạ em đã đặt bàn thành công, mã đặt {session.booking_id}."
        )
        return BrowserTurnResult(
            assistant_text=line,
            session_id=session.id,
            call_sid=session.call_sid,
            action=session.status,
            booking_id=session.booking_id,
            transfer_reason=session.transfer_reason,
            ended=True,
            slots=session.slots.model_dump(mode="json"),
        )

    from_voice = bool(audio_b64)
    user_text = (text or "").strip()
    if not user_text and audio_b64:
        user_text = (await transcribe_audio(settings, audio_b64, audio_filename)).strip()

    if not user_text:
        audio = await synthesize_speech(settings, REPEAT_LINE) if from_voice else None
        return BrowserTurnResult(
            assistant_text=REPEAT_LINE,
            user_text=user_text or None,
            audio_b64=audio,
            session_id=session.id,
            call_sid=session.call_sid,
            action="repeat",
            slots=session.slots.model_dump(mode="json"),
        )

    await engine.backend.append_transcript(session_id, "user", user_text)
    history.append({"role": "user", "content": user_text})

    turn = await run_browser_llm_turn(engine, session_id, history, settings)
    if from_voice:
        session, audio = await asyncio.gather(
            engine.backend.append_transcript(session_id, "assistant", turn.assistant_text),
            synthesize_speech(settings, turn.assistant_text),
        )
        turn.audio_b64 = audio
    else:
        # Typed turns skip TTS so the UI is not blocked on speech synthesis.
        session = await engine.backend.append_transcript(
            session_id, "assistant", turn.assistant_text
        )
    turn.user_text = user_text
    turn.session_id = session.id
    turn.call_sid = session.call_sid
    turn.slots = session.slots.model_dump(mode="json")
    turn.booking_id = turn.booking_id or session.booking_id
    if session.status in {"booked", "transferred"}:
        turn.ended = True
        turn.action = session.status
        turn.transfer_reason = session.transfer_reason
    return turn

# Gọi tool và thực hiện tool call
async def run_browser_llm_turn(
    engine: Any,
    session_id: str,
    history: list[dict[str, Any]],
    settings: Settings,
) -> BrowserTurnResult:
    client = _openai(settings)
    action = "ask"
    booking_id: str | None = None
    transfer_reason: str | None = None

    for _ in range(MAX_TOOL_ROUNDS):
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=history,
            tools=BROWSER_LLM_TOOLS,
            tool_choice="auto",
            temperature=0.75,
            frequency_penalty=0.3,
            presence_penalty=0.2,
        )
        ## message có thể trả về nhiều thứ, ví dụ như text, tool_calls, etc.nên cần hàm 
        #_assistant_message_dict để chuyển đổi thành dict
        message = response.choices[0].message
        history.append(_assistant_message_dict(message))
        tool_calls = message.tool_calls or []
        if not tool_calls:
            text = (message.content or "").strip() or REPEAT_LINE
            return BrowserTurnResult(
                assistant_text=text,
                action=action,
                booking_id=booking_id,
                transfer_reason=transfer_reason,
            )

        results_by_id = await _run_tool_calls(engine, session_id, tool_calls)
        for call in tool_calls:
            name, result = results_by_id[call.id]
            if name == "confirm_booking" and result.get("ok"):
                action = "booked"
                booking_id = result.get("booking_id")
            if name == "transfer_to_staff" and result.get("transferred"):
                action = "transfer"
                transfer_reason = result.get("reason")
            history.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(result, ensure_ascii=False, default=str),
                }
            )

        if action == "transfer":
            return BrowserTurnResult(
                assistant_text=TRANSFER_LINE,
                action=action,
                booking_id=booking_id,
                transfer_reason=transfer_reason,
                ended=True,
            )

    return BrowserTurnResult(
        assistant_text=REPEAT_LINE,
        action=action,
        booking_id=booking_id,
        transfer_reason=transfer_reason,
    )


async def execute_browser_tool(
    engine: Any,
    session_id: str,
    name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Apply booking side-effects for an LLM tool call."""
    if name == "update_slots":
        try:
            guest_count = arguments.get("guest_count")
            if isinstance(guest_count, float):
                guest_count = int(guest_count)
            delta = delta_from_llm(
                guest_count=guest_count,
                date_value=arguments.get("date"),
                time_value=arguments.get("time"),
                branch=arguments.get("branch"),
                customer_name=arguments.get("customer_name"),
                phone=arguments.get("phone"),
                notes=arguments.get("notes"),
            )
        except (TypeError, ValueError) as exc:
            return {"ok": False, "error": f"invalid slot values: {exc}"}
        return await engine.apply_slot_delta(session_id, delta)

    if name == "search_knowledge":
        hits = engine.rag.retrieve(str(arguments.get("query") or ""))
        payload: dict[str, Any] = {
            "chunks": [{"title": h.title, "text": h.speakable()} for h in hits],
            "note": "Do not claim table availability from these documents.",
        }
        try:
            session = await engine.backend.get_session(session_id)
            missing = missing_fields(session.slots, session.multi_branch)
            payload["speak"] = {
                "next_field": missing[0] if missing else None,
                "instruction": (
                    "Trả lời FAQ bằng lời nói tự nhiên, rồi hỏi tiếp đúng next_field "
                    "theo ngữ cảnh cuộc gọi. Không dùng câu hỏi khuôn."
                ),
            }
        except Exception:
            pass
        return payload

    if name == "confirm_booking":
        session = await engine.backend.get_session(session_id)
        missing = missing_fields(session.slots, session.multi_branch)
        if missing:
            return {"ok": False, "missing_fields": missing}
        booking = await engine.backend.create_booking(
            session_id=session.id,
            slots=session.slots,
            transcript=session.transcript,
            recording_id=session.recording_id,
        )
        return {"ok": True, "booking_id": booking.id}

    if name == "transfer_to_staff":
        reason = str(arguments.get("reason") or "guest_requested_human")
        session = await engine.backend.get_session(session_id)
        await engine.backend.transfer(
            session_id,
            reason,
            summary=str(session.slots.model_dump(mode="json")),
        )
        return {"transferred": True, "reason": reason}

    return {"ok": False, "error": f"unknown tool {name}"}


def _tool_stage(name: str) -> int:
    if name == "confirm_booking":
        return 1
    if name == "transfer_to_staff":
        return 2
    return 0


async def _invoke_tool(
    engine: Any, session_id: str, call: Any
) -> tuple[Any, str, dict[str, Any]]:
    name = call.function.name
    try:
        arguments = json.loads(call.function.arguments or "{}")
    except json.JSONDecodeError:
        arguments = {}
    try:
        result = await execute_browser_tool(engine, session_id, name, arguments)
    except Exception as exc:
        logger.exception("Browser tool %s failed", name)
        result = {"ok": False, "error": str(exc)}
    return call, name, result


async def _run_tool_calls(
    engine: Any, session_id: str, tool_calls: list[Any]
) -> dict[str, tuple[str, dict[str, Any]]]:
    """Run independent tools together; save slots before confirm/transfer."""
    by_id: dict[str, tuple[str, dict[str, Any]]] = {}
    for stage in (0, 1, 2):
        batch = [call for call in tool_calls if _tool_stage(call.function.name) == stage]
        if not batch:
            continue
        for call, name, result in await asyncio.gather(
            *[_invoke_tool(engine, session_id, call) for call in batch]
        ):
            by_id[call.id] = (name, result)
    return by_id


async def transcribe_audio(settings: Settings, audio_b64: str, filename: str) -> str:
    raw = base64.b64decode(audio_b64)
    if not raw:
        return ""
    client = _openai(settings)
    buffer = io.BytesIO(raw)
    buffer.name = filename
    try:
        result = await client.audio.transcriptions.create(
            model=settings.openai_stt_model or "gpt-4o-mini-transcribe",
            file=buffer,
            language="vi",
            prompt=STT_PROMPT,
        )
    except Exception:
        logger.exception("Browser STT failed")
        return ""
    return getattr(result, "text", None) or str(result)


async def synthesize_speech(settings: Settings, text: str) -> str | None:
    cleaned = (text or "").strip()
    if not cleaned or not settings.openai_api_key:
        return None
    cache_key = f"{settings.openai_tts_model}|{settings.openai_tts_voice}|{cleaned}"
    cached = _tts_cache.get(cache_key)
    if cached is not None:
        _tts_cache.move_to_end(cache_key)
        return cached
    client = _openai(settings)
    try:
        kwargs: dict[str, Any] = {
            "model": settings.openai_tts_model or "gpt-4o-mini-tts",
            "voice": settings.openai_tts_voice or "nova",
            "input": cleaned,
            "response_format": "mp3",
        }
        tts_model = settings.openai_tts_model or ""
        if "gpt-4o" in tts_model:
            kwargs["instructions"] = TTS_INSTRUCTIONS
        response = await client.audio.speech.create(**kwargs)
        audio_bytes = response.read() if hasattr(response, "read") else bytes(response)
        encoded = base64.b64encode(audio_bytes).decode("ascii")
        _tts_cache[cache_key] = encoded
        _tts_cache.move_to_end(cache_key)
        while len(_tts_cache) > _TTS_CACHE_MAX:
            _tts_cache.popitem(last=False)
        return encoded
    except Exception:
        logger.exception("Browser TTS failed")
        return None


def _openai(settings: Settings) -> AsyncOpenAI:
    key = settings.openai_api_key or ""
    client = _openai_clients.get(key)
    if client is None:
        client = AsyncOpenAI(api_key=key or None)
        _openai_clients[key] = client
    return client


def _assistant_message_dict(message: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"role": "assistant", "content": message.content}
    tool_calls = getattr(message, "tool_calls", None) or []
    if tool_calls:
        payload["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.function.name,
                    "arguments": call.function.arguments,
                },
            }
            for call in tool_calls
        ]
    return payload
