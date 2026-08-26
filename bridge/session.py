"""Per-call state machine: Init → Greeting → Listening ⇄ Thinking → Speaking, plus BargeIn."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from audio.resample import BRIDGE_RATE, OPENAI_RATE, StreamResampler, even_pcm16
from llm.stream import build_system_prompt, fallback_phrase
from turn.barge_in import OutboundGate, abort_and_interrupt

logger = logging.getLogger(__name__)

# ~2 s of 24 kHz PCM16 if STT is still connecting
_MAX_PENDING_STT_BYTES = BRIDGE_RATE * 2 * 3  # 16k→24k ≈ 3/2, times 2 bytes, ~2 s


class CallState(str, Enum):
    INIT = "Init"
    GREETING = "Greeting"
    LISTENING = "Listening"
    THINKING = "Thinking"
    SPEAKING = "Speaking"
    BARGE_IN = "BargeIn"
    CLOSED = "Closed"


@dataclass
class CallSession:
    state: CallState = CallState.INIT
    generation_id: int = 0
    playing: bool = False
    call_id: str = ""
    store_name: str = ""
    timezone: str = "UTC"
    locale: str = "en"
    greeting: str = ""
    inited: bool = False
    history: list[dict[str, str]] = field(default_factory=list)
    spoken_this_turn: str = ""
    closed: bool = False

    def begin_generation(self) -> int:
        self.generation_id += 1
        self.spoken_this_turn = ""
        return self.generation_id

    def mark_audio_sent(self) -> None:
        self.playing = True
        if self.state == CallState.THINKING:
            self.state = CallState.SPEAKING

    def note_spoken(self, sentence: str) -> None:
        sentence = sentence.strip()
        if not sentence:
            return
        if self.spoken_this_turn:
            self.spoken_this_turn = f"{self.spoken_this_turn} {sentence}"
        else:
            self.spoken_this_turn = sentence

    def commit_partial_assistant(self) -> None:
        text = self.spoken_this_turn.strip()
        self.spoken_this_turn = ""
        if not text:
            return
        last = self.history[-1] if self.history else None
        if last and last.get("role") == "assistant" and last.get("content") == text:
            return
        self.history.append({"role": "assistant", "content": text})

    def apply_init(self, payload: dict[str, Any]) -> None:
        self.call_id = str(payload.get("callId") or "")
        self.store_name = str(payload.get("storeName") or "")
        self.timezone = str(payload.get("timezone") or "UTC")
        self.locale = str(payload.get("locale") or "en")
        self.greeting = str(payload.get("greeting") or "")
        self.inited = True
        self.history = [
            {
                "role": "system",
                "content": build_system_prompt(
                    store_name=self.store_name,
                    timezone=self.timezone,
                    locale=self.locale,
                ),
            }
        ]
        if self.greeting.strip():
            self.history.append({"role": "assistant", "content": self.greeting})

    @property
    def tag(self) -> str:
        return f"callId={self.call_id or '-'} gen={self.generation_id} state={self.state}"


class TurnPlayer:
    """Synth sentences concurrently; send PCM to the bridge in order."""

    def __init__(
        self,
        session: CallSession,
        outbound: OutboundGate,
        tts: Any,
        locale: str,
    ) -> None:
        self.session = session
        self.outbound = outbound
        self.tts = tts
        self.locale = locale
        self.generation_id = session.generation_id
        self._sentence_qs: asyncio.Queue[Optional[tuple[str, asyncio.Queue[Optional[bytes]]]]] = asyncio.Queue()
        self._synth_tasks: list[asyncio.Task[None]] = []
        self._aborted = False
        self._sender = asyncio.create_task(self._sender_loop(), name="turn-sender")

    def should_abort(self) -> bool:
        return self._aborted or self.session.generation_id != self.generation_id or self.session.closed

    async def speak_sentence(self, text: str) -> None:
        text = (text or "").strip()
        if not text or self.should_abort():
            return
        queue: asyncio.Queue[Optional[bytes]] = asyncio.Queue()
        await self._sentence_qs.put((text, queue))
        self._synth_tasks.append(asyncio.create_task(self._synth(text, queue), name="tts-sentence"))

    async def _synth(self, text: str, queue: asyncio.Queue[Optional[bytes]]) -> None:
        try:
            async for pcm in self.tts.stream_pcm16(text, self.locale, self.should_abort):
                if self.should_abort():
                    break
                await queue.put(pcm)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("TTS sentence failed %s text=%r", self.session.tag, text[:80])
        finally:
            await queue.put(None)

    async def _sender_loop(self) -> None:
        while True:
            item = await self._sentence_qs.get()
            if item is None:
                return
            text, queue = item
            first = True
            while True:
                chunk = await queue.get()
                if chunk is None:
                    break
                if self.should_abort():
                    continue
                ok = await self.outbound.send_audio(self.generation_id, chunk)
                if not ok:
                    self._aborted = True
                    return
                if first:
                    self.session.note_spoken(text)
                    first = False

    async def finish(self) -> None:
        await self._sentence_qs.put(None)
        try:
            await self._sender
        except asyncio.CancelledError:
            return
        await asyncio.gather(*self._synth_tasks, return_exceptions=True)
        if self.should_abort() or self.session.closed:
            return
        self.session.playing = False
        if self.session.state in (CallState.GREETING, CallState.SPEAKING, CallState.THINKING):
            self.session.state = CallState.LISTENING
        self.session.commit_partial_assistant()

    async def abort(self) -> None:
        self._aborted = True
        for task in self._synth_tasks:
            task.cancel()
        if not self._sender.done():
            try:
                self._sentence_qs.put_nowait(None)
            except asyncio.QueueFull:
                pass
            self._sender.cancel()
            try:
                await self._sender
            except (asyncio.CancelledError, Exception):
                pass


class CallPipeline:
    def __init__(
        self,
        websocket: Any,
        stt: Any,
        llm: Any,
        tts: Any,
    ) -> None:
        self.websocket = websocket
        self.stt = stt
        self.llm = llm
        self.tts = tts
        self.session = CallSession()
        self.outbound = OutboundGate(websocket, self.session)
        self._upsampler = StreamResampler(BRIDGE_RATE, OPENAI_RATE)
        self._in_leftover = bytearray()
        self._pending_24k = bytearray()
        self._warned_pcm_before_init = False
        self._player: Optional[TurnPlayer] = None
        self._work_task: Optional[asyncio.Task[None]] = None
        self._turn_lock = asyncio.Lock()
        self._stt_start_task: Optional[asyncio.Task[None]] = None

    async def run(self) -> None:
        # asyncio.create_task() tạo ra 1 task mới.
        # Code không chờ asyncio chạy xong mà chạy thẳng xuống dưới
        self._stt_start_task = asyncio.create_task(self._start_stt(), name="stt-start")
        try:
            ## Chờ cho _receive_loop() hoàn thành.
            await self._receive_loop()
        finally:
            await self.shutdown()

    async def _start_stt(self) -> None:
        locale = self.session.locale if self.session.inited else None
        try:
            await self.stt.start(self, locale)
        except Exception:
            logger.exception("STT start failed %s", self.session.tag)
            return
        await self._flush_pending_stt()

    async def _flush_pending_stt(self) -> None:
        if self._pending_24k and getattr(self.stt, "is_ready", False):
            blob = bytes(self._pending_24k)
            self._pending_24k.clear()
            try:
                await self.stt.append_pcm24(blob)
            except Exception:
                logger.exception("Failed to flush pending STT audio %s", self.session.tag)

    async def _receive_loop(self) -> None:
        while not self.session.closed:
            try:
                message = await self.websocket.receive()
            except Exception as exc:
                logger.info("Bridge socket closed %s (%s)", self.session.tag, exc)
                break
            if message.get("type") == "websocket.disconnect":
                break
            data = message.get("bytes")
            text = message.get("text")
            if data is not None:
                await self.on_pcm(data)
            elif text is not None:
                await self.on_control(text)

    async def on_pcm(self, data: bytes) -> None:
        if self.session.closed:
            return
        if not self.session.inited and not self._warned_pcm_before_init:
            self._warned_pcm_before_init = True
            logger.error(
                "PCM arrived before session.init — accepting audio, but greeting and "
                "store context are missing. Socket stays open. %s",
                self.session.tag,
            )
        pcm = even_pcm16(data, self._in_leftover)
        pcm24 = self._upsampler.process(pcm)
        if not pcm24:
            return
        await self._send_to_stt(pcm24)

    async def _send_to_stt(self, pcm24: bytes) -> None:
        if getattr(self.stt, "is_ready", False):
            await self._flush_pending_stt()
            try:
                await self.stt.append_pcm24(pcm24)
            except Exception:
                logger.exception("STT append failed %s", self.session.tag)
            return
        self._pending_24k.extend(pcm24)
        overflow = len(self._pending_24k) - _MAX_PENDING_STT_BYTES
        if overflow > 0:
            drop = overflow + (overflow % 2)
            del self._pending_24k[:drop]

    async def on_control(self, raw: str) -> None:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Ignoring malformed inbound JSON %s payload=%r", self.session.tag, raw[:300])
            return
        if not isinstance(payload, dict):
            logger.warning("Ignoring non-object inbound JSON %s", self.session.tag)
            return
        event = payload.get("event")
        if event != "session.init":
            logger.warning("Ignoring unknown control event %r %s", event, self.session.tag)
            return
        await self.on_session_init(payload)

    async def on_session_init(self, payload: dict[str, Any]) -> None:
        if self.session.inited:
            logger.warning("Duplicate session.init ignored %s", self.session.tag)
            return
        self.session.apply_init(payload)
        logger.info("session.init %s store=%r locale=%s", self.session.tag, self.session.store_name, self.session.locale)
        update = getattr(self.stt, "update_language", None)
        if update is not None:
            try:
                await update(self.session.locale)
            except Exception:
                logger.exception("STT language update failed %s", self.session.tag)
        self._spawn(self._run_greeting())

    async def _run_greeting(self) -> None:
        if not self.session.greeting.strip():
            logger.error("session.init has empty greeting; going to Listening %s", self.session.tag)
            self.session.state = CallState.LISTENING
            return
        self.session.begin_generation()
        self.session.state = CallState.GREETING
        player = TurnPlayer(self.session, self.outbound, self.tts, self.session.locale)
        self._player = player
        try:
            await player.speak_sentence(self.session.greeting)
            await player.finish()
        except asyncio.CancelledError:
            await player.abort()
            raise
        except Exception:
            logger.exception("Greeting TTS failed %s", self.session.tag)
            if self.session.generation_id == player.generation_id:
                self.session.playing = False
                self.session.state = CallState.LISTENING
        finally:
            if self._player is player:
                self._player = None

    async def on_speech_started(self) -> None:
        async with self._turn_lock:
            if self.session.closed or self.session.state in (CallState.CLOSED, CallState.BARGE_IN, CallState.LISTENING):
                return
            if (
                self.session.state in (CallState.GREETING, CallState.THINKING, CallState.SPEAKING)
                or self.session.playing
                or (self._work_task is not None and not self._work_task.done())
            ):
                await self._barge_in()

    async def on_speech_stopped(self) -> None:
        logger.debug("speech_stopped %s", self.session.tag)

    async def on_transcript_delta(self, delta: str) -> None:
        logger.debug("transcript delta %s %r", self.session.tag, delta)

    async def on_transcript_completed(self, text: str) -> None:
        async with self._turn_lock:
            if self.session.closed:
                return
            busy = (
                self.session.state in (CallState.GREETING, CallState.THINKING, CallState.SPEAKING)
                or self.session.playing
                or (self._work_task is not None and not self._work_task.done())
            )
            if busy:
                await self._barge_in()
            self._spawn(self._run_reply(text))

    async def on_transcript_failed(self) -> None:
        await self.on_transcript_completed("")

    async def _run_reply(self, user_text: str) -> None:
        self.session.begin_generation()
        self.session.state = CallState.THINKING
        if not self.session.history:
            self.session.history = [
                {
                    "role": "system",
                    "content": build_system_prompt(store_name="", timezone="UTC", locale=self.session.locale),
                }
            ]
        player = TurnPlayer(self.session, self.outbound, self.tts, self.session.locale)
        self._player = player
        gen = player.generation_id
        try:
            text = (user_text or "").strip()
            if not text:
                await player.speak_sentence(fallback_phrase(self.session.locale))
                await player.finish()
                return
            self.session.history.append({"role": "user", "content": text})
            async for sentence in self.llm.stream_sentences(
                self.session.history,
                lambda: self.session.generation_id != gen or self.session.closed,
            ):
                if self.session.generation_id != gen:
                    return
                await player.speak_sentence(sentence)
            await player.finish()
        except asyncio.CancelledError:
            await player.abort()
            raise
        except Exception:
            logger.exception("LLM/TTS reply failed %s", self.session.tag)
            if self.session.generation_id == gen and not self.session.spoken_this_turn:
                try:
                    await player.speak_sentence(fallback_phrase(self.session.locale))
                    await player.finish()
                    return
                except Exception:
                    logger.exception("Fallback TTS failed %s", self.session.tag)
            if self.session.generation_id == gen:
                self.session.playing = False
                self.session.state = CallState.LISTENING
        finally:
            if self._player is player:
                self._player = None

    def _spawn(self, coro: Any) -> None:
        previous = self._work_task
        if previous is not None and not previous.done():
            previous.cancel()
        self._work_task = asyncio.create_task(coro, name="call-work")

    async def _barge_in(self) -> None:
        player = self._player
        work = self._work_task

        async def abort_work() -> None:
            if player is not None:
                await player.abort()
            if work is not None and not work.done() and work is not asyncio.current_task():
                work.cancel()
                try:
                    await work
                except (asyncio.CancelledError, Exception):
                    pass
            if self._player is player:
                self._player = None
            if self._work_task is work:
                self._work_task = None

        await abort_and_interrupt(session=self.session, outbound=self.outbound, abort_work=abort_work)

    async def shutdown(self) -> None:
        self.session.closed = True
        self.session.state = CallState.CLOSED
        self.session.playing = False
        if self._player is not None:
            await self._player.abort()
            self._player = None
        if self._work_task is not None and not self._work_task.done():
            self._work_task.cancel()
            try:
                await self._work_task
            except (asyncio.CancelledError, Exception):
                pass
        if self._stt_start_task is not None and not self._stt_start_task.done():
            self._stt_start_task.cancel()
            try:
                await self._stt_start_task
            except (asyncio.CancelledError, Exception):
                pass
        close = getattr(self.stt, "close", None)
        if close is not None:
            try:
                await close()
            except Exception:
                logger.debug("STT close failed %s", self.session.tag, exc_info=True)
        logger.info("Session released %s", self.session.tag)
