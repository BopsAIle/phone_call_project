"""Accept the telephony WebSocket, authenticate, and split binary PCM from JSON control."""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from openai import AsyncOpenAI

from agents.registry import build_registry
from bridge.session import CallPipeline
from config import Settings, load_settings
from llm.stream import OpenAiLlm
from stt.realtime import RealtimeTranscriptionClient
from tools.store_api import HttpStoreApi, StubStoreApi
from tts.openai_tts import OpenAiTts

logger = logging.getLogger(__name__)

# token: phía AI giữ
# websocket: kết nối /v1/bridge kèm token. Telephony backend gửi header
# Authorization. Trình duyệt không gắn được header đó — nhận thêm ?token=.
def _bearer_authorized(websocket: WebSocket, token: str) -> bool:
    if not token:
        return False
    header = websocket.headers.get("authorization") or ""
    if header.strip() == f"Bearer {token}":
        return True
    query_token = websocket.query_params.get("token") or ""
    return query_token == token


def create_app(
    settings: Optional[Settings] = None,
    *,
    stt_factory: Optional[Callable[[], Any]] = None,
    llm: Any = None,
    tts: Any = None,
    openai_client: Any = None,
    store_api: Any = None,
) -> FastAPI:
    settings = settings or load_settings()
    if not settings.ai_bridge_token:
        logger.error("AI_BRIDGE_TOKEN is empty; every /v1/bridge handshake will be rejected")
    if not settings.openai_api_key:
        logger.error("OPENAI_API_KEY is empty; STT/LLM/TTS will fail on live calls")
    app = FastAPI(title="AI Bridge", version="1.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "OPTIONS"],
        allow_headers=["*"],
    )
    app.state.settings = settings

    if openai_client is None and settings.openai_api_key:
        openai_client = AsyncOpenAI(api_key=settings.openai_api_key)
    app.state.openai_client = openai_client

    if llm is None and openai_client is not None:
        llm = OpenAiLlm(openai_client, settings.openai_model)
    if tts is None and openai_client is not None:
        tts = OpenAiTts(
            openai_client,
            settings.openai_tts_model,
            settings.openai_tts_voice,
            chunk_bytes=settings.tts_chunk_bytes,
        )

    def default_stt_factory() -> RealtimeTranscriptionClient:
        return RealtimeTranscriptionClient(openai_client, settings.openai_stt_model)
    #app.state là túi đựng của FastAPI, gắn vào object app, sống suốt lúc server chạy.
    # Restart process thì mất, tạo lại lúc create_app().
    app.state.stt_factory = stt_factory or default_stt_factory
    app.state.llm = llm
    app.state.tts = tts # tts: 1 client tts được tạo ra từ openai_client

    if store_api is None:
        if settings.store_api_url:
            store_api = HttpStoreApi(
                settings.store_api_url,
                settings.store_api_token,
                timeout=settings.store_api_timeout,
            )
        else:
            logger.error("STORE_API_URL is empty; booking requests will be filed nowhere")
            store_api = StubStoreApi()
    # One registry for the process: tools are stateless, per-call state lives on
    # the session the ToolContext carries.
    app.state.tools = build_registry(store_api)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.websocket("/v1/bridge")
    async def bridge(websocket: WebSocket) -> None:
        token = settings.ai_bridge_token
        if not _bearer_authorized(websocket, token):
            logger.error("Rejecting bridge handshake: missing or invalid Bearer token")
            await websocket.close(code=1008, reason="Unauthorized")
            return
        await websocket.accept()
        stt = app.state.stt_factory()
        pipeline = CallPipeline(
            websocket, stt=stt, llm=app.state.llm, tts=app.state.tts, tools=app.state.tools
        )
        try:
            await pipeline.run()
        except WebSocketDisconnect:
            logger.info("Backend closed the bridge socket")
        except Exception:
            logger.exception("Bridge pipeline crashed")
            try:
                await websocket.close(code=1011, reason="Internal error")
            except Exception:
                pass

    return app
