"""HTTP webhook + media WebSocket that make a Telnyx number talk to the pipeline.

Inbound call, end to end:

    1. Telnyx  --POST /telnyx/webhook  call.initiated-->  answer
    2. Telnyx  --POST /telnyx/webhook  call.answered -->  streaming_start(stream_url=...)
    3. Telnyx  --WS   /telnyx/media    connected/start/media/dtmf/stop
    4. TelnyxCallSocket fakes a bridge socket; CallPipeline runs unchanged.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlencode, urlparse, urlunparse

from fastapi import APIRouter, FastAPI, Request, Response, WebSocket

from config import Settings
from telephony.telnyx.api import TelnyxClient
from telephony.telnyx.signature import SIGNATURE_HEADER, TIMESTAMP_HEADER, SignatureError, verify_webhook
from telephony.telnyx.stream import TelnyxCallSocket

logger = logging.getLogger(__name__)


def stream_url_with_token(stream_url: str, token: str) -> str:
    """Telnyx does not sign the media WebSocket, so the token rides in the URL."""
    if not token or not stream_url:
        return stream_url
    parts = urlparse(stream_url)
    query = f"{parts.query}&{urlencode({'token': token})}" if parts.query else urlencode({"token": token})
    return urlunparse(parts._replace(query=query))


def build_telnyx_router(app: FastAPI, settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/telnyx", tags=["telnyx"])

    if not settings.telnyx_api_key:
        logger.error("TELNYX_API_KEY is empty; answer/streaming_start/hangup will all fail")
    if not settings.telnyx_public_key:
        logger.error("TELNYX_PUBLIC_KEY is empty; every webhook will be rejected as unsigned")
    if not settings.telnyx_stream_url:
        logger.error("TELNYX_STREAM_URL is empty; Telnyx has nowhere to stream the audio")

    client = TelnyxClient(settings.telnyx_api_key, api_base=settings.telnyx_api_base)
    app.state.telnyx_client = client

    @router.post("/webhook")
    async def webhook(request: Request) -> Response:
        body = await request.body()
        try:
            verify_webhook(
                body=body,
                signature_b64=request.headers.get(SIGNATURE_HEADER),
                timestamp=request.headers.get(TIMESTAMP_HEADER),
                public_key_b64=settings.telnyx_public_key,
                tolerance_seconds=settings.telnyx_webhook_tolerance_seconds,
            )
        except SignatureError as exc:
            logger.warning("Rejecting Telnyx webhook: %s", exc)
            return Response(status_code=401, content='{"error":"invalid_signature"}', media_type="application/json")

        try:
            envelope = await request.json()
        except Exception:
            logger.warning("Telnyx webhook body was not JSON")
            return _ok()

        data = (envelope or {}).get("data") or {}
        event_type = str(data.get("event_type") or "")
        payload = data.get("payload") or {}
        await _handle_event(event_type, payload)
        # Always 200 on a signed webhook: a non-2xx makes Telnyx retry, and a
        # retry of call.answered would try to start a second stream.
        return _ok()

    async def _handle_event(event_type: str, payload: dict[str, Any]) -> None:
        call_control_id = str(payload.get("call_control_id") or "")
        if event_type == "call.initiated":
            if str(payload.get("direction") or "") != "incoming":
                logger.info("Ignoring outbound call.initiated ccid=%s", call_control_id)
                return
            logger.info(
                "Telnyx call.initiated ccid=%s from=%s to=%s",
                call_control_id,
                payload.get("from") or "-",
                payload.get("to") or "-",
            )
            try:
                await client.answer(call_control_id)
            except Exception:
                logger.exception("Telnyx answer failed ccid=%s", call_control_id)
            return

        if event_type == "call.answered":
            url = stream_url_with_token(settings.telnyx_stream_url, settings.telnyx_stream_token)
            logger.info("Telnyx call.answered ccid=%s; starting stream", call_control_id)
            try:
                await client.start_streaming(
                    call_control_id,
                    stream_url=url,
                    stream_track=settings.telnyx_stream_track,
                    stream_codec=settings.telnyx_stream_codec,
                    bidirectional_codec=settings.telnyx_bidi_codec,
                    bidirectional_sampling_rate=settings.telnyx_bidi_sampling_rate,
                )
            except Exception:
                logger.exception("Telnyx streaming_start failed ccid=%s", call_control_id)
            return

        if event_type in {"streaming.failed", "call.streaming.failed"}:
            logger.error("Telnyx streaming failed ccid=%s payload=%s", call_control_id, payload)
            return

        if event_type == "call.hangup":
            logger.info(
                "Telnyx call.hangup ccid=%s cause=%s",
                call_control_id,
                payload.get("hangup_cause") or "-",
            )
            return

        logger.debug("Unhandled Telnyx webhook %s ccid=%s", event_type, call_control_id)

    @router.websocket("/media")
    async def media(websocket: WebSocket) -> None:
        expected = settings.telnyx_stream_token
        if expected and websocket.query_params.get("token") != expected:
            logger.error("Rejecting Telnyx media socket: bad or missing token")
            await websocket.close(code=1008, reason="Unauthorized")
            return
        await websocket.accept()
        socket = TelnyxCallSocket(
            websocket,
            telnyx_client=client,
            out_rate=settings.telnyx_bidi_sampling_rate,
            frame_ms=settings.telnyx_frame_ms,
            store_name=settings.telnyx_default_store_name,
            locale=settings.telnyx_default_locale,
            greeting=settings.telnyx_greeting,
            timezone=settings.telnyx_default_timezone,
            mark_timeout=settings.telnyx_mark_timeout_seconds,
            byteswap=settings.telnyx_l16_byteswap,
        )
        if not await socket.wait_for_start():
            await socket.close(code=1002, reason="no start event")
            return
        pipeline = app.state.build_pipeline(socket)
        try:
            await pipeline.run()
        except Exception:
            logger.exception("Telnyx pipeline crashed %s", socket.tag)
        finally:
            await socket.close()

    return router


def _ok() -> Response:
    return Response(status_code=200, content='{"ok":true}', media_type="application/json")
