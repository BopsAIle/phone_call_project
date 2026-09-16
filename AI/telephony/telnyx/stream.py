"""Present a Telnyx media stream to CallPipeline as if it were a bridge WebSocket.

CallPipeline only ever asks its socket for four things: `receive`, `send_bytes`,
`send_text`, `close`. Satisfying exactly those here is what keeps
`bridge/session.py` free of any carrier-specific code.

    Telnyx WS  --JSON/base64 L16-->  TelnyxCallSocket  --PCM16-LE 24 kHz-->  CallPipeline
               <--JSON/base64 L16--                    <--PCM16-LE 24 kHz--
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
from typing import Any, Optional

from bridge.protocol import EVENT_CALL_END, EVENT_DTMF, EVENT_INTERRUPT, EVENT_SESSION_INIT
from telephony.telnyx.codec import InboundTranscoder, OutboundTranscoder

logger = logging.getLogger(__name__)

CALL_END_MARK = "ai-bridge-call-end"
DEFAULT_MARK_TIMEOUT = 20.0
# How long the outbound buffer may hold a sub-frame remainder before it is sent.
TAIL_FLUSH_DELAY = 0.06


class TelnyxCallSocket:
    """Bridge-shaped socket backed by one Telnyx bidirectional media stream."""

    def __init__(
        self,
        websocket: Any,
        *,
        telnyx_client: Any = None,
        out_rate: int = 16_000,
        frame_ms: int = 20,
        store_name: str = "",
        locale: str = "en",
        greeting: str = "",
        timezone: str = "UTC",
        mark_timeout: float = DEFAULT_MARK_TIMEOUT,
        tail_flush_delay: float = TAIL_FLUSH_DELAY,
        byteswap: bool = True,
    ) -> None:
        self.websocket = websocket
        self.telnyx = telnyx_client
        self.out_rate = out_rate
        self.store_name = store_name
        self.locale = locale
        self.greeting = greeting
        self.timezone = timezone
        self.mark_timeout = mark_timeout
        self.tail_flush_delay = tail_flush_delay
        self.byteswap = byteswap

        self.stream_id = ""
        self.call_control_id = ""
        self.call_session_id = ""
        self.from_number = ""
        self.to_number = ""
        self.in_rate = 0

        self.started = asyncio.Event()
        self._inbound: Optional[InboundTranscoder] = None
        self._outbound = OutboundTranscoder(out_rate, frame_ms, byteswap=byteswap)
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._marks: dict[str, asyncio.Event] = {}
        self._reader: Optional[asyncio.Task[None]] = None
        self._flush_task: Optional[asyncio.Task[None]] = None
        self._closed = False
        self._hung_up = False
        self._media_in = 0
        self._media_out = 0

    # --- lifecycle -------------------------------------------------------

    def start(self) -> None:
        if self._reader is None:
            self._reader = asyncio.create_task(self._read_loop(), name="telnyx-reader")

    async def wait_for_start(self, timeout: float = 15.0) -> bool:
        """Block until Telnyx sends `start` (it carries from/to and the codec)."""
        self.start()
        try:
            await asyncio.wait_for(self.started.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.error("Telnyx stream sent no start event within %ss", timeout)
            return False
        return True

    @property
    def tag(self) -> str:
        return f"stream={self.stream_id or '-'} ccid={self.call_control_id or '-'}"

    # --- Telnyx -> pipeline ----------------------------------------------

    async def _read_loop(self) -> None:
        try:
            while True:
                raw = await self.websocket.receive_text()
                try:
                    message = json.loads(raw)
                except json.JSONDecodeError:
                    logger.warning("Telnyx sent non-JSON frame %s", self.tag)
                    continue
                if not isinstance(message, dict):
                    continue
                await self._on_message(message)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.info("Telnyx stream closed %s (%s)", self.tag, exc)
        finally:
            await self._push({"type": "websocket.disconnect", "code": 1000})

    async def _on_message(self, message: dict[str, Any]) -> None:
        event = message.get("event")
        if event == "connected":
            logger.info("Telnyx stream connected version=%s", message.get("version"))
            return
        if event == "start":
            await self._on_start(message)
            return
        if event == "media":
            await self._on_media(message)
            return
        if event == "dtmf":
            digit = str((message.get("dtmf") or {}).get("digit") or "")
            if digit:
                logger.info("Telnyx DTMF %s digit=%s", self.tag, digit)
                await self._push_text({"event": EVENT_DTMF, "digit": digit, "callId": self.call_session_id})
            return
        if event == "mark":
            name = str((message.get("mark") or {}).get("name") or "")
            waiter = self._marks.get(name)
            if waiter is not None:
                waiter.set()
            return
        if event == "stop":
            logger.info("Telnyx stream stop %s media_in=%s media_out=%s", self.tag, self._media_in, self._media_out)
            await self._push({"type": "websocket.disconnect", "code": 1000})
            return
        if event == "error":
            logger.error("Telnyx stream error %s payload=%s", self.tag, message.get("payload"))
            return
        logger.debug("Ignoring Telnyx event %r %s", event, self.tag)

    async def _on_start(self, message: dict[str, Any]) -> None:
        start = message.get("start") or {}
        media_format = start.get("media_format") or {}
        self.stream_id = str(message.get("stream_id") or "")
        self.call_control_id = str(start.get("call_control_id") or "")
        self.call_session_id = str(start.get("call_session_id") or "") or self.stream_id
        self.from_number = str(start.get("from") or "")
        self.to_number = str(start.get("to") or "")
        try:
            self.in_rate = int(media_format.get("sample_rate") or 0)
        except (TypeError, ValueError):
            self.in_rate = 0
        if self.in_rate <= 0:
            # Telnyx omits the rate only in odd cases; assume what we asked for.
            self.in_rate = self.out_rate
            logger.warning("Telnyx start had no sample_rate %s; assuming %s", self.tag, self.in_rate)
        encoding = str(media_format.get("encoding") or "")
        if encoding and encoding.upper() not in {"L16", "LINEAR16", "PCM"}:
            logger.error(
                "Telnyx is streaming %s, but this adapter decodes L16 only %s. "
                "Set TELNYX_STREAM_CODEC=L16 or audio will be noise.",
                encoding,
                self.tag,
            )
        self._inbound = InboundTranscoder(self.in_rate, byteswap=self.byteswap)
        logger.info(
            "Telnyx start %s from=%s to=%s encoding=%s in_rate=%s out_rate=%s",
            self.tag,
            self.from_number or "-",
            self.to_number or "-",
            encoding or "-",
            self.in_rate,
            self.out_rate,
        )
        await self._push_text(
            {
                "event": EVENT_SESSION_INIT,
                "callId": self.call_session_id,
                "storeName": self.store_name,
                "timezone": self.timezone,
                "locale": self.locale,
                "greeting": self.greeting,
                "toNumber": self.to_number,
                "fromNumber": self.from_number,
            }
        )
        self.started.set()

    async def _on_media(self, message: dict[str, Any]) -> None:
        media = message.get("media") or {}
        if str(media.get("track") or "inbound") == "outbound":
            return  # our own audio echoed back; never feed it to STT
        payload = media.get("payload")
        if not payload or self._inbound is None:
            return
        try:
            raw = base64.b64decode(payload)
        except Exception:
            logger.warning("Undecodable Telnyx media payload %s", self.tag)
            return
        pcm24 = self._inbound.process(raw)
        self._media_in += 1
        if pcm24:
            await self._push({"type": "websocket.receive", "bytes": pcm24})

    async def _push(self, message: dict[str, Any]) -> None:
        await self._queue.put(message)

    async def _push_text(self, payload: dict[str, Any]) -> None:
        await self._push(
            {
                "type": "websocket.receive",
                "text": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            }
        )

    # --- pipeline-facing socket API --------------------------------------

    async def receive(self) -> dict[str, Any]:
        return await self._queue.get()

    async def send_bytes(self, pcm24_le: bytes) -> None:
        for frame in self._outbound.process(pcm24_le):
            await self._send_media(frame)
        self._schedule_tail_flush()

    def _schedule_tail_flush(self) -> None:
        """Push the sub-frame remainder once the turn stops producing audio.

        A turn rarely ends on a whole 20 ms boundary. Without this the last few
        milliseconds of a sentence would sit in the buffer until the next turn
        and be spoken as a click in front of it.
        """
        if self._flush_task is not None and not self._flush_task.done():
            self._flush_task.cancel()
        self._flush_task = asyncio.create_task(self._flush_tail_soon(), name="telnyx-tail-flush")

    def _cancel_tail_flush(self) -> None:
        if self._flush_task is not None and not self._flush_task.done():
            self._flush_task.cancel()
        self._flush_task = None

    async def _flush_tail_soon(self) -> None:
        try:
            await asyncio.sleep(self.tail_flush_delay)
        except asyncio.CancelledError:
            return
        tail = self._outbound.flush()
        if tail:
            await self._send_media(tail)

    async def send_text(self, raw: str) -> None:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return
        event = payload.get("event")
        if event == EVENT_INTERRUPT:
            await self._clear()
            return
        if event == EVENT_CALL_END:
            await self._drain_then_hangup(str(payload.get("reason") or "completed"))
            return
        # transcript / agent.speech / order.created are demo-UI events; Telnyx
        # has nowhere to put them, so they stay in the log.
        logger.debug("Telnyx socket dropping bridge event %r %s", event, self.tag)

    async def close(self, code: int = 1000, reason: str = "") -> None:
        if self._closed:
            return
        self._closed = True
        self._cancel_tail_flush()
        await self._hangup(reason or "closed")
        if self._reader is not None and self._reader is not asyncio.current_task():
            self._reader.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._reader
        with contextlib.suppress(Exception):
            await self.websocket.close(code=code)
        await self._push({"type": "websocket.disconnect", "code": code})

    # --- outbound helpers -------------------------------------------------

    async def _send_media(self, frame: bytes) -> None:
        if not frame or self._closed:
            return
        self._media_out += 1
        await self.websocket.send_text(
            json.dumps(
                {"event": "media", "media": {"payload": base64.b64encode(frame).decode()}},
                separators=(",", ":"),
            )
        )

    async def _clear(self) -> None:
        """Barge-in: drop audio Telnyx has buffered but not yet played."""
        self._cancel_tail_flush()
        self._outbound.reset()
        if self._closed:
            return
        with contextlib.suppress(Exception):
            await self.websocket.send_text(json.dumps({"event": "clear"}, separators=(",", ":")))
        logger.info("Telnyx clear sent (barge-in) %s", self.tag)

    async def _drain_then_hangup(self, reason: str) -> None:
        """Wait for Telnyx to finish playing, then end the call.

        The pipeline estimates playback time before it emits call.end; Telnyx
        can tell us for real. A `mark` queued behind the audio comes back only
        once that audio has left the buffer.
        """
        self._cancel_tail_flush()
        tail = self._outbound.flush()
        if tail:
            await self._send_media(tail)
        waiter = asyncio.Event()
        self._marks[CALL_END_MARK] = waiter
        try:
            await self.websocket.send_text(
                json.dumps({"event": "mark", "mark": {"name": CALL_END_MARK}}, separators=(",", ":"))
            )
            await asyncio.wait_for(waiter.wait(), timeout=self.mark_timeout)
        except asyncio.TimeoutError:
            logger.warning("Telnyx never echoed the call-end mark %s; hanging up anyway", self.tag)
        except Exception:
            logger.debug("Telnyx mark send failed %s", self.tag, exc_info=True)
        finally:
            self._marks.pop(CALL_END_MARK, None)
        await self._hangup(reason)

    async def _hangup(self, reason: str) -> None:
        if self._hung_up or self.telnyx is None or not self.call_control_id:
            return
        self._hung_up = True
        logger.info("Telnyx hangup %s reason=%s", self.tag, reason)
        try:
            await self.telnyx.hangup(self.call_control_id)
        except Exception:
            logger.info("Telnyx hangup failed %s (call likely already ended)", self.tag, exc_info=True)
