"""Record caller audio to disk so `scripts/stt_eval.py` finally has something to measure.

Off unless `CALL_RECORD_DIR` is set. The tap sits where audio is handed to STT, not where
Telnyx delivers it: what is worth evaluating is exactly what STT heard, and that point
also covers the `/v1/bridge` socket and the browser demo.

Writes `<stamp>-<call_id>.wav` (mono PCM16 24 kHz) plus a sibling `.jsonl` holding byte
offsets for each event, which is what lets `scripts/split_call.py` cut one long recording
into per-turn clips.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import wave
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from audio.resample import OPENAI_RATE

logger = logging.getLogger(__name__)

BYTES_PER_SECOND = OPENAI_RATE * 2  # mono PCM16
_FLUSH_BYTES = BYTES_PER_SECOND * 2  # ~2 s between disk writes
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]")


def _safe_call_id(call_id: str) -> str:
    """Call ids come from the carrier and must never reach a path unfiltered."""
    cleaned = _SAFE_NAME.sub("-", (call_id or "").strip())[:64].strip("-.")
    return cleaned or "unknown"


class CallRecorder:
    def __init__(self, path: Path, *, max_seconds: int) -> None:
        self.path = path
        self.marks_path = path.with_suffix(".jsonl")
        self._raw_path = path.with_suffix(".pcm")
        self._max_bytes = max(1, int(max_seconds)) * BYTES_PER_SECOND
        self._buf = bytearray()
        self._written = 0
        self._capped = False
        self._marks: list[dict[str, Any]] = []
        self._closed = False

    @classmethod
    def maybe(
        cls,
        directory: str,
        call_id: str,
        *,
        max_seconds: int = 600,
    ) -> Optional["CallRecorder"]:
        """None when recording is off. That empty-string check is the whole opt-in."""
        if not (directory or "").strip():
            return None
        try:
            folder = Path(directory).expanduser()
            folder.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            return cls(folder / f"{stamp}-{_safe_call_id(call_id)}.wav", max_seconds=max_seconds)
        except Exception:
            logger.exception("Call recording could not start in %r; continuing without it", directory)
            return None

    @property
    def offset(self) -> int:
        """Bytes of audio recorded so far — the clock the marks are measured against."""
        return self._written + len(self._buf)

    def feed(self, pcm: bytes) -> None:
        if self._closed or not pcm:
            return
        room = self._max_bytes - self.offset
        if room <= 0:
            if not self._capped:
                self._capped = True
                logger.warning("Call recording hit its size cap: %s", self.path.name)
            return
        self._buf.extend(pcm[:room] if len(pcm) > room else pcm)

    def mark(self, event: str, text: str = "") -> None:
        if self._closed:
            return
        entry: dict[str, Any] = {"offset": self.offset, "event": event}
        if text:
            entry["text"] = text
        self._marks.append(entry)

    async def maybe_flush(self) -> None:
        if len(self._buf) >= _FLUSH_BYTES:
            await self.flush()

    async def flush(self) -> None:
        if self._closed or not self._buf:
            return
        chunk = bytes(self._buf)
        self._buf.clear()
        self._written += len(chunk)
        try:
            await asyncio.to_thread(self._append, chunk)
        except Exception:
            logger.exception("Call recording write failed: %s", self.path)

    def _append(self, chunk: bytes) -> None:
        # Raw PCM while the call runs: a plain append, and a killed process still leaves
        # every recorded byte on disk. `wave` would rewrite its header on every flush,
        # which means reading the whole file back each time — quadratic on a long call.
        with open(self._raw_path, "ab") as handle:
            handle.write(chunk)

    async def close(self) -> None:
        if self._closed:
            return
        await self.flush()
        self._closed = True
        try:
            await asyncio.to_thread(self._finalize)
        except Exception:
            logger.exception("Call recording could not be finalized: %s", self.path)
            return
        logger.info(
            "Call recording saved: %s (%.1fs)", self.path, self._written / BYTES_PER_SECOND
        )

    def _finalize(self) -> None:
        """Wrap the raw PCM in a wav header — the format scripts/stt_eval.py reads."""
        if self._raw_path.exists():
            frames = self._raw_path.read_bytes()
            with wave.open(str(self.path), "wb") as writer:
                writer.setnchannels(1)
                writer.setsampwidth(2)
                writer.setframerate(OPENAI_RATE)
                writer.writeframes(frames)
            self._raw_path.unlink()
        if self._marks:
            lines = "\n".join(json.dumps(m, ensure_ascii=False) for m in self._marks)
            self.marks_path.write_text(lines + "\n", encoding="utf-8")
