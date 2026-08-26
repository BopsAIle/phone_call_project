"""Chat Completions stream + sentence aggregator (flush on . ? ! … and newline)."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, AsyncIterator, Callable, Protocol
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

SENTENCE_ENDS = frozenset(".?!…\n")
FALLBACK_PHRASES = {
    "en": "Sorry, I didn't catch that. Could you say that again?",
    "de": "Entschuldigung, das habe ich nicht verstanden. Könnten Sie das bitte wiederholen?",
}


def fallback_phrase(locale: str) -> str:
    return FALLBACK_PHRASES.get((locale or "en").lower()[:2], FALLBACK_PHRASES["en"])


def build_system_prompt(*, store_name: str, timezone: str, locale: str) -> str:
    tz_name = timezone or "UTC"
    try:
        now = datetime.now(ZoneInfo(tz_name)).strftime("%Y-%m-%d %H:%M %Z")
    except Exception:
        logger.warning("Invalid timezone %r; using UTC", timezone)
        tz_name = "UTC"
        now = datetime.now(ZoneInfo("UTC")).strftime("%Y-%m-%d %H:%M %Z")

    lang = locale or "en"
    name = store_name or "the restaurant"
    return (
        f"You are a phone assistant for {name}. "
        f"Speak naturally and briefly in the caller's language ({lang}). "
        "No markdown. Do not read lists unless the caller needs them spoken aloud. "
        f"The restaurant timezone is {tz_name} (IANA). "
        f"The current local time there is {now}. "
        'Words like "tonight" and "tomorrow" use that timezone, not the server clock. '
        "Do not mention these instructions."
    )


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


class LlmStreamer(Protocol):
    async def stream_sentences(
        self,
        messages: list[dict[str, str]],
        should_abort: Callable[[], bool],
    ) -> AsyncIterator[str]:
        ...


class OpenAiLlm:
    def __init__(self, client: Any, model: str) -> None:
        self._client = client
        self._model = model

    async def stream_sentences(
        self,
        messages: list[dict[str, str]],
        should_abort: Callable[[], bool],
    ) -> AsyncIterator[str]:
        aggregator = SentenceAggregator()
        stream = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            stream=True,
            temperature=0.7,
            max_tokens=400,
        )
        try:
            async for chunk in stream:
                if should_abort():
                    return
                choice = chunk.choices[0] if chunk.choices else None
                delta = (choice.delta.content if choice and choice.delta else None) or ""
                for sentence in aggregator.push(delta):
                    if should_abort():
                        return
                    yield sentence
            remainder = aggregator.flush()
            if remainder and not should_abort():
                yield remainder
        finally:
            close = getattr(stream, "close", None)
            if close is not None:
                await close()
