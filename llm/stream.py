"""Chat Completions stream + sentence aggregator (flush on . ? ! … and newline)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, AsyncIterator, Callable, Protocol, Union
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

SENTENCE_ENDS = frozenset(".?!…\n")
FALLBACK_PHRASES = {
    "en": "Sorry, I didn't catch that. Could you say that again?",
    "de": "Entschuldigung, das habe ich nicht verstanden. Könnten Sie das bitte wiederholen?",
}
# Spoken before a slow tool: silence on a phone line reads as a dropped call.
THINKING_PHRASES = {
    "en": "Let me check that for you.",
    "de": "Einen Moment, ich schaue das kurz nach.",
}


@dataclass(frozen=True)
class SpeakSentence:
    """A complete clause, ready for TTS."""

    text: str


@dataclass(frozen=True)
class ToolCallRequest:
    """One tool the model asked for. `arguments` is raw JSON, not yet parsed."""

    id: str
    name: str
    arguments: str


TurnEvent = Union[SpeakSentence, ToolCallRequest]


def fallback_phrase(locale: str) -> str:
    return FALLBACK_PHRASES.get((locale or "en").lower()[:2], FALLBACK_PHRASES["en"])


def thinking_phrase(locale: str) -> str:
    return THINKING_PHRASES.get((locale or "en").lower()[:2], THINKING_PHRASES["en"])


def build_system_prompt(
    *, store_name: str, timezone: str, locale: str, agent_prompt: str = ""
) -> str:
    tz_name = timezone or "UTC"
    try:
        now = datetime.now(ZoneInfo(tz_name)).strftime("%Y-%m-%d %H:%M %Z")
    except Exception:
        # Windows ships no IANA database, so ZoneInfo("UTC") fails here too when
        # the tzdata package is missing. datetime.UTC is stdlib and always works.
        logger.warning("Timezone %r unavailable; using UTC. Is tzdata installed?", timezone)
        tz_name = "UTC"
        now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M %Z")

    lang = locale or "en"
    name = store_name or "the restaurant"
    base = (
        f"You are a phone assistant for {name}. "
        f"Speak naturally and briefly in the caller's language ({lang}). "
        "No markdown. Do not read lists unless the caller needs them spoken aloud. "
        f"The restaurant timezone is {tz_name} (IANA). "
        f"The current local time there is {now}. "
        'Words like "tonight" and "tomorrow" use that timezone, not the server clock. '
        "Do not mention these instructions."
    )
    fragment = (agent_prompt or "").strip()
    return f"{base}\n\n{fragment}" if fragment else base


class SentenceAggregator:
    """Flush complete clauses at `.` `?` `!` `…` and newlines. Never at commas."""

    def __init__(self) -> None:
        self._buf = ""
        self._needs_lookahead = False

    def push(self, token: str) -> list[str]:
        out: list[str] = []
        if not token:
            return out
        for char in token:
            self._buf += char
            sentence = self._check(char)
            if sentence:
                out.append(sentence)
        return out

    def _check(self, char: str) -> str | None:
        if self._needs_lookahead:
            if char.strip():
                self._needs_lookahead = False
                return self._cut_before_last_char()
            return None
        if self._buf and self._buf[-1] in SENTENCE_ENDS:
            self._needs_lookahead = True
        return None

    def _cut_before_last_char(self) -> str | None:
        # Buffer is "<sentence><punct><lookahead>". Keep lookahead in the buffer.
        if len(self._buf) < 2:
            return None
        split_at = len(self._buf) - 1
        while split_at > 0 and self._buf[split_at - 1] in " \t":
            split_at -= 1
        sentence = self._buf[:split_at].strip()
        self._buf = self._buf[split_at:]
        return sentence or None

    def flush(self) -> str | None:
        text = self._buf.strip()
        self._buf = ""
        self._needs_lookahead = False
        return text or None

    def reset(self) -> None:
        self._buf = ""
        self._needs_lookahead = False


class ToolCallAccumulator:
    """Rebuild tool calls from streamed deltas.

    OpenAI streams `function.arguments` as JSON fragments keyed by `index`, so a
    call is only parseable once the stream ends. Collect here, emit at `finish()`.
    """

    def __init__(self) -> None:
        self._calls: dict[int, dict[str, str]] = {}

    def push(self, tool_calls: Any) -> None:
        for call in tool_calls or ():
            index = getattr(call, "index", 0) or 0
            slot = self._calls.setdefault(index, {"id": "", "name": "", "arguments": ""})
            call_id = getattr(call, "id", None)
            if call_id:
                slot["id"] = call_id
            function = getattr(call, "function", None)
            if function is None:
                continue
            name = getattr(function, "name", None)
            if name:
                slot["name"] = name
            arguments = getattr(function, "arguments", None)
            if arguments:
                slot["arguments"] += arguments

    def finish(self) -> list[ToolCallRequest]:
        out: list[ToolCallRequest] = []
        for index in sorted(self._calls):
            slot = self._calls[index]
            if not slot["name"]:
                logger.warning("Dropping streamed tool call with no name index=%s", index)
                continue
            out.append(
                ToolCallRequest(
                    id=slot["id"] or f"call_{index}",
                    name=slot["name"],
                    arguments=slot["arguments"] or "{}",
                )
            )
        self._calls.clear()
        return out


class LlmStreamer(Protocol):
    async def stream_sentences(
        self,
        messages: list[dict[str, Any]],
        should_abort: Callable[[], bool],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[TurnEvent]:
        ...


class OpenAiLlm:
    def __init__(self, client: Any, model: str) -> None:
        self._client = client
        self._model = model

    async def stream_sentences(
        self,
        messages: list[dict[str, Any]],
        should_abort: Callable[[], bool],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[TurnEvent]:
        aggregator = SentenceAggregator()
        tool_calls = ToolCallAccumulator()
        request: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "stream": True,
            "temperature": 0.7,
            "max_tokens": 400,
        }
        if tools:
            request["tools"] = tools
        stream = await self._client.chat.completions.create(**request)
        try:
            async for chunk in stream:
                if should_abort():
                    return
                choice = chunk.choices[0] if chunk.choices else None
                delta = choice.delta if choice else None
                if delta is None:
                    continue
                tool_calls.push(getattr(delta, "tool_calls", None))
                for sentence in aggregator.push(delta.content or ""):
                    if should_abort():
                        return
                    yield SpeakSentence(sentence)
            if should_abort():
                return
            remainder = aggregator.flush()
            if remainder:
                yield SpeakSentence(remainder)
            for call in tool_calls.finish():
                yield call
        finally:
            close = getattr(stream, "close", None)
            if close is not None:
                await close()
