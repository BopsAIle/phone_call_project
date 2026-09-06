"""OpenAI TTS: stream PCM 24 kHz, downsample to 16 kHz, yield whole samples."""
## Chuyển câu nói thành audio giọng AI
from __future__ import annotations

import logging
from typing import Any, AsyncIterator, Callable, Protocol

from audio.resample import BRIDGE_RATE, OPENAI_RATE, StreamResampler

logger = logging.getLogger(__name__)

# ~21 ms at 24 kHz PCM16. 4096 (~85 ms) delayed the first yield after TTFB.
DEFAULT_CHUNK_BYTES = 1024


def _supports_instructions(model: str) -> bool:
    """tts-1 / tts-1-hd reject `instructions`; gpt-4o-*tts accept it."""
    name = (model or "").strip().lower()
    if name.startswith("tts-1"):
        return False
    return "gpt-4o" in name and "tts" in name


class TtsStreamer(Protocol):
    async def stream_pcm16(
        self,
        text: str,
        locale: str,
        should_abort: Callable[[], bool],
    ) -> AsyncIterator[bytes]:
        ...


class OpenAiTts:
    def __init__(
        self,
        client: Any,
        model: str,
        voice: str,
        chunk_bytes: int = DEFAULT_CHUNK_BYTES,
    ) -> None:
        self._client = client
        self._model = model
        self._voice = voice
        self._chunk_bytes = max(2, chunk_bytes - chunk_bytes % 2)

    def _speech_kwargs(self, text: str, locale: str) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": self._model,
            "voice": self._voice,
            "input": text,
            "response_format": "pcm",
        }
        if _supports_instructions(self._model):
            kwargs["instructions"] = f"Phone, {locale}."
        return kwargs

    async def stream_pcm16(
        self,
        text: str,
        locale: str,
        should_abort: Callable[[], bool],
    ) -> AsyncIterator[bytes]:
        if not text.strip():
            return
        resampler = StreamResampler(OPENAI_RATE, BRIDGE_RATE)
        try:
            async with self._client.audio.speech.with_streaming_response.create(
                **self._speech_kwargs(text.strip(), locale),
            ) as response:
                async for chunk in response.iter_bytes(chunk_size=self._chunk_bytes):
                    if should_abort():
                        return
                    pcm16 = resampler.process(chunk)
                    if pcm16:
                        yield pcm16
            if not should_abort():
                tail = resampler.flush()
                if tail:
                    yield tail
        except Exception:
            logger.exception("TTS failed for %r", text[:80])
            raise
