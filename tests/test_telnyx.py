"""Telnyx adapter: codec correctness, virtual socket behaviour, webhook auth."""

from __future__ import annotations

import asyncio
import base64
import json
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

from audio.resample import OPENAI_RATE
from bridge.server import create_app
from config import Settings
from telephony.telnyx.codec import InboundTranscoder, OutboundTranscoder, swap16
from telephony.telnyx.routes import stream_url_with_token
from telephony.telnyx.signature import SIGNATURE_HEADER, TIMESTAMP_HEADER, SignatureError, verify_webhook
from telephony.telnyx.stream import CALL_END_MARK, TelnyxCallSocket
from tests.fakes import FakeSTT, ScriptedLlm, ScriptedTts


# --- fakes ---------------------------------------------------------------


class FakeTelnyxWs:
    """Stands in for the Telnyx media WebSocket."""

    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.incoming: asyncio.Queue[str] = asyncio.Queue()
        self.closed_with: list[int] = []

    async def send_text(self, data: str) -> None:
        self.sent.append(json.loads(data))

    async def receive_text(self) -> str:
        return await self.incoming.get()

    async def close(self, code: int = 1000) -> None:
        self.closed_with.append(code)

    async def push(self, message: dict) -> None:
        await self.incoming.put(json.dumps(message))

    def events(self, name: str) -> list[dict]:
        return [m for m in self.sent if m.get("event") == name]


class FakeTelnyxClient:
    def __init__(self) -> None:
        self.hangups: list[str] = []

    async def hangup(self, call_control_id: str, **_: object) -> dict:
        self.hangups.append(call_control_id)
        return {}


def start_message(sample_rate: int = 16_000, encoding: str = "L16") -> dict:
    return {
        "event": "start",
        "sequence_number": "1",
        "stream_id": "stream-1",
        "start": {
            "call_control_id": "ccid-1",
            "call_session_id": "sess-1",
            "from": "+15550001111",
            "to": "+15550002222",
            "media_format": {"encoding": encoding, "sample_rate": sample_rate, "channels": 1},
        },
    }


def l16_media(samples: list[int]) -> dict:
    payload = np.array(samples, dtype=">i2").tobytes()
    return {
        "event": "media",
        "stream_id": "stream-1",
        "media": {"track": "inbound", "chunk": "1", "timestamp": "0", "payload": base64.b64encode(payload).decode()},
    }


# --- codec ---------------------------------------------------------------


def test_swap16_roundtrip() -> None:
    original = np.array([0, 1, -1, 32767, -32768], dtype="<i2").tobytes()
    assert swap16(swap16(original)) == original


def test_inbound_decodes_big_endian_at_native_rate() -> None:
    """24 kHz in means no resampler, so the bytes must come out exactly byteswapped."""
    samples = [100, -200, 300, -400]
    transcoder = InboundTranscoder(OPENAI_RATE)
    out = transcoder.process(np.array(samples, dtype=">i2").tobytes())
    assert list(np.frombuffer(out, dtype="<i2")) == samples


def test_inbound_carries_an_odd_byte_across_chunks() -> None:
    """A split mid-sample must not shift every following sample by one byte."""
    samples = list(range(64))
    raw = np.array(samples, dtype=">i2").tobytes()
    transcoder = InboundTranscoder(OPENAI_RATE)
    out = transcoder.process(raw[:35]) + transcoder.process(raw[35:])
    assert list(np.frombuffer(out, dtype="<i2")) == samples


def test_inbound_resamples_16k_to_24k() -> None:
    transcoder = InboundTranscoder(16_000)
    produced = 0
    for _ in range(50):  # 1 s of 20 ms frames
        produced += len(transcoder.process(np.array([500] * 320, dtype=">i2").tobytes()))
    # 1 s at 24 kHz PCM16 = 48000 bytes, minus the one-off soxr filter delay.
    assert 45_000 <= produced <= 48_000


def test_outbound_emits_fixed_big_endian_frames() -> None:
    out = OutboundTranscoder(16_000, frame_ms=20)
    assert out.frame_bytes == 640
    frames = out.process(np.array([1234] * 2400, dtype="<i2").tobytes())  # 100 ms @ 24 kHz
    assert frames and all(len(f) == 640 for f in frames)
    # The resampler ramps up over the first few ms, so judge the settled tail:
    # read as big-endian it is ~1234, read as little-endian it would be garbage.
    settled = np.frombuffer(frames[-1], dtype=">i2")
    assert abs(float(settled.mean()) - 1234) < 20


def test_outbound_reset_drops_buffered_audio() -> None:
    out = OutboundTranscoder(16_000, frame_ms=20)
    out.process(np.array([10] * 200, dtype="<i2").tobytes())  # too little for a frame
    out.reset()
    assert out.flush() == b""


# --- signature -----------------------------------------------------------


def _signed(body: bytes, timestamp: str):
    from nacl.signing import SigningKey

    key = SigningKey.generate()
    signature = key.sign(f"{timestamp}|".encode() + body).signature
    public = base64.b64encode(bytes(key.verify_key)).decode()
    return base64.b64encode(signature).decode(), public


def test_verify_webhook_accepts_a_valid_signature() -> None:
    body = b'{"data":{"event_type":"call.initiated"}}'
    ts = str(int(time.time()))
    signature, public = _signed(body, ts)
    verify_webhook(body=body, signature_b64=signature, timestamp=ts, public_key_b64=public)


def test_verify_webhook_rejects_a_tampered_body() -> None:
    ts = str(int(time.time()))
    signature, public = _signed(b"original", ts)
    with pytest.raises(SignatureError):
        verify_webhook(body=b"tampered", signature_b64=signature, timestamp=ts, public_key_b64=public)


def test_verify_webhook_rejects_a_replayed_timestamp() -> None:
    body = b"payload"
    ts = str(int(time.time()) - 4000)
    signature, public = _signed(body, ts)
    with pytest.raises(SignatureError):
        verify_webhook(
            body=body, signature_b64=signature, timestamp=ts, public_key_b64=public, tolerance_seconds=300
        )


def test_verify_webhook_rejects_missing_headers() -> None:
    with pytest.raises(SignatureError):
        verify_webhook(body=b"x", signature_b64=None, timestamp=None, public_key_b64="irrelevant")


def test_stream_url_keeps_existing_query() -> None:
    assert stream_url_with_token("wss://h/telnyx/media?a=1", "sec") == "wss://h/telnyx/media?a=1&token=sec"
    assert stream_url_with_token("wss://h/telnyx/media", "") == "wss://h/telnyx/media"


# --- virtual socket ------------------------------------------------------


async def _started_socket(ws: FakeTelnyxWs, telnyx: FakeTelnyxClient, **kwargs) -> TelnyxCallSocket:
    socket = TelnyxCallSocket(ws, telnyx_client=telnyx, out_rate=16_000, greeting="Hi.", **kwargs)
    await ws.push({"event": "connected", "version": "1.0.0"})
    await ws.push(start_message())
    assert await socket.wait_for_start(timeout=2)
    return socket


async def test_start_event_becomes_session_init() -> None:
    ws, telnyx = FakeTelnyxWs(), FakeTelnyxClient()
    socket = await _started_socket(ws, telnyx)
    message = await asyncio.wait_for(socket.receive(), timeout=2)
    payload = json.loads(message["text"])
    assert payload["event"] == "session.init"
    assert payload["callId"] == "sess-1"
    assert payload["toNumber"] == "+15550002222"
    assert payload["greeting"] == "Hi."
    assert socket.call_control_id == "ccid-1"
    await socket.close()


async def test_media_reaches_the_pipeline_as_little_endian_pcm() -> None:
    ws, telnyx = FakeTelnyxWs(), FakeTelnyxClient()
    socket = await _started_socket(ws, telnyx)
    await asyncio.wait_for(socket.receive(), timeout=2)  # drain session.init
    for _ in range(20):
        await ws.push(l16_media([700] * 320))
    message = await asyncio.wait_for(socket.receive(), timeout=2)
    pcm = message["bytes"]
    assert len(pcm) % 2 == 0
    assert max(abs(int(s)) for s in np.frombuffer(pcm, dtype="<i2")) > 500
    await socket.close()


async def test_outbound_media_never_echoes_into_stt() -> None:
    """stream_track can be both_tracks; our own audio must not reach the pipeline."""
    ws, telnyx = FakeTelnyxWs(), FakeTelnyxClient()
    socket = await _started_socket(ws, telnyx)
    await asyncio.wait_for(socket.receive(), timeout=2)
    echo = l16_media([700] * 320)
    echo["media"]["track"] = "outbound"
    await ws.push(echo)
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(socket.receive(), timeout=0.3)
    await socket.close()


async def test_dtmf_becomes_a_bridge_dtmf_event() -> None:
    ws, telnyx = FakeTelnyxWs(), FakeTelnyxClient()
    socket = await _started_socket(ws, telnyx)
    await asyncio.wait_for(socket.receive(), timeout=2)
    await ws.push({"event": "dtmf", "stream_id": "stream-1", "dtmf": {"digit": "2"}})
    payload = json.loads((await asyncio.wait_for(socket.receive(), timeout=2))["text"])
    assert payload == {"event": "dtmf", "digit": "2", "callId": "sess-1"}
    await socket.close()


async def test_send_bytes_becomes_base64_l16_media() -> None:
    ws, telnyx = FakeTelnyxWs(), FakeTelnyxClient()
    socket = await _started_socket(ws, telnyx)
    await socket.send_bytes(np.array([2000] * 2400, dtype="<i2").tobytes())
    media = ws.events("media")
    assert media
    frame = base64.b64decode(media[0]["media"]["payload"])
    assert len(frame) == 640
    assert max(abs(int(s)) for s in np.frombuffer(frame, dtype=">i2")) > 1000
    await socket.close()


async def test_interrupt_becomes_clear() -> None:
    ws, telnyx = FakeTelnyxWs(), FakeTelnyxClient()
    socket = await _started_socket(ws, telnyx)
    await socket.send_text(json.dumps({"event": "interrupt"}))
    assert ws.events("clear")
    await socket.close()


async def test_call_end_waits_for_the_mark_then_hangs_up() -> None:
    ws, telnyx = FakeTelnyxWs(), FakeTelnyxClient()
    socket = await _started_socket(ws, telnyx, mark_timeout=2.0)
    task = asyncio.create_task(socket.send_text(json.dumps({"event": "call.end", "reason": "completed"})))
    await asyncio.sleep(0.05)
    assert not telnyx.hangups, "must not hang up before Telnyx finished playing"
    assert ws.events("mark")[0]["mark"]["name"] == CALL_END_MARK
    await ws.push({"event": "mark", "stream_id": "stream-1", "mark": {"name": CALL_END_MARK}})
    await asyncio.wait_for(task, timeout=2)
    assert telnyx.hangups == ["ccid-1"]
    await socket.close()
    assert telnyx.hangups == ["ccid-1"], "close must not hang up twice"


async def test_call_end_hangs_up_even_if_the_mark_never_returns() -> None:
    ws, telnyx = FakeTelnyxWs(), FakeTelnyxClient()
    socket = await _started_socket(ws, telnyx, mark_timeout=0.2)
    await socket.send_text(json.dumps({"event": "call.end"}))
    assert telnyx.hangups == ["ccid-1"]
    await socket.close()


async def test_stop_event_disconnects_the_pipeline() -> None:
    ws, telnyx = FakeTelnyxWs(), FakeTelnyxClient()
    socket = await _started_socket(ws, telnyx)
    await asyncio.wait_for(socket.receive(), timeout=2)
    await ws.push({"event": "stop", "stream_id": "stream-1", "stop": {"call_control_id": "ccid-1"}})
    message = await asyncio.wait_for(socket.receive(), timeout=2)
    assert message["type"] == "websocket.disconnect"
    await socket.close()


# --- wiring --------------------------------------------------------------


def _telnyx_app(**overrides):
    settings = Settings(
        ai_bridge_token="secret",
        openai_api_key="",
        telnyx_enabled=True,
        telnyx_api_key="key",
        telnyx_public_key="",
        telnyx_stream_url="wss://host.example/telnyx/media",
        telnyx_stream_token="stream-secret",
        **overrides,
    )
    return create_app(settings, stt_factory=FakeSTT, llm=ScriptedLlm([]), tts=ScriptedTts())


def test_webhook_rejects_an_unsigned_request() -> None:
    with TestClient(_telnyx_app()) as client:
        assert client.post("/telnyx/webhook", json={"data": {"event_type": "call.initiated"}}).status_code == 401


def test_media_socket_rejects_a_bad_token() -> None:
    with TestClient(_telnyx_app()) as client:
        with pytest.raises(Exception):
            with client.websocket_connect("/telnyx/media?token=wrong"):
                pass


def test_legacy_bridge_can_be_disabled() -> None:
    with TestClient(_telnyx_app(bridge_enabled=False)) as client:
        with pytest.raises(Exception):
            with client.websocket_connect("/v1/bridge?token=secret"):
                pass


def test_telnyx_stays_off_by_default() -> None:
    app = create_app(
        Settings(ai_bridge_token="secret", openai_api_key=""),
        stt_factory=FakeSTT,
        llm=ScriptedLlm([]),
        tts=ScriptedTts(),
    )
    with TestClient(app) as client:
        assert client.post("/telnyx/webhook", json={}).status_code == 404


# --- end to end through the real CallPipeline ----------------------------


async def test_call_answers_with_greeting_audio_over_telnyx() -> None:
    """A Telnyx `start` must make the pipeline speak, and the speech must come
    back as base64 L16 media frames — not as bridge binary frames."""
    from bridge.session import CallPipeline

    ws, telnyx = FakeTelnyxWs(), FakeTelnyxClient()
    socket = TelnyxCallSocket(
        ws,
        telnyx_client=telnyx,
        out_rate=16_000,
        greeting="Hello, you have reached our automated assistant.",
    )
    pipeline = CallPipeline(socket, stt=FakeSTT(), llm=ScriptedLlm([]), tts=ScriptedTts())
    await ws.push(start_message())
    assert await socket.wait_for_start(timeout=2)

    task = asyncio.create_task(pipeline.run())
    for _ in range(60):
        if ws.events("media"):
            break
        await asyncio.sleep(0.05)
    assert ws.events("media"), "greeting audio never reached Telnyx"
    assert pipeline.session.call_id == "sess-1"
    # normalize_hotline() strips the leading + so the catalog lookup can match.
    assert pipeline.session.to_number == "15550002222"
    # The service menu must be appended to the plain greeting (spoken sentence by sentence).
    assert "press 1" in " ".join(pipeline.tts.spoken).casefold()

    await ws.push({"event": "stop", "stream_id": "stream-1", "stop": {"call_control_id": "ccid-1"}})
    await asyncio.wait_for(task, timeout=5)
    await socket.close()


async def test_caller_speech_reaches_stt_as_24k_pcm() -> None:
    from bridge.session import CallPipeline

    ws, telnyx = FakeTelnyxWs(), FakeTelnyxClient()
    socket = TelnyxCallSocket(ws, telnyx_client=telnyx, out_rate=16_000, greeting="Hi.")
    stt = FakeSTT()
    pipeline = CallPipeline(socket, stt=stt, llm=ScriptedLlm([]), tts=ScriptedTts())
    await ws.push(start_message())
    assert await socket.wait_for_start(timeout=2)
    task = asyncio.create_task(pipeline.run())
    for _ in range(25):  # 500 ms of caller audio
        await ws.push(l16_media([800] * 320))
    for _ in range(60):
        if stt.appended:
            break
        await asyncio.sleep(0.05)
    assert stt.appended, "caller audio never reached STT"
    assert all(len(chunk) % 2 == 0 for chunk in stt.appended)
    heard = np.concatenate([np.frombuffer(c, dtype="<i2") for c in stt.appended])
    assert int(np.abs(heard).max()) > 500, "decoded as the wrong endianness would look like noise"

    await ws.push({"event": "stop", "stream_id": "stream-1", "stop": {"call_control_id": "ccid-1"}})
    await asyncio.wait_for(task, timeout=5)
    await socket.close()
