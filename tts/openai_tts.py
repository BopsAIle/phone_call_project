"""OpenAI TTS: stream PCM 24 kHz, downsample to 16 kHz, yield whole samples."""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator, Callable, Protocol

from audio.resample import BRIDGE_RATE, OPENAI_RATE, StreamResampler

logger = logging.getLogger(__name__)


class TtsStreamer(Protocol):
    async def stream_pcm16(
        self,
        text: str,
        locale: str,
        should_abort: Callable[[], bool],
    ) -> AsyncIterator[bytes]:
        ...


class OpenAiTts:
    def __init__(self, client: Any, model: str, voice: str, chunk_bytes: int = 4096) -> None:
        self._client = client
        self._model = model
        self._voice = voice
        self._chunk_bytes = max(2, chunk_bytes - chunk_bytes % 2)

    async def stream_pcm16(
        self,
        text: str,
        locale: str,
        should_abort: Callable[[], bool],
    ) -> AsyncIterator[bytes]:
        if not text.strip():
            return
        instructions = (
            f"Speak clearly for a phone call in locale '{locale}'. "
            "Natural, brief, no dramatic acting."
        )
        resampler = StreamResampler(OPENAI_RATE, BRIDGE_RATE)
        try:
            async with self._client.audio.speech.with_streaming_response.create(
                model=self._model,
                voice=self._voice,
                input=text.strip(),
                response_format="pcm",
                instructions=instructions,
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
