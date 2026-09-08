"""Accept the telephony WebSocket, authenticate, and split binary PCM from JSON control."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from openai import AsyncOpenAI

from bridge.session import CallPipeline
from cache.redis_store import CatalogCache
from config import Settings, load_settings
from booking.client import RestaurantClient
from booking.matcher import OpenAiBranchMatcher
from llm.stream import OpenAiLlm
from order.client import OrderClient
from order.matcher import OpenAiMenuMatcher
from stt.realtime import RealtimeTranscriptionClient
from sync.poller import CatalogSyncer
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


def _http_bearer_authorized(authorization: str | None, token: str) -> bool:
    if not token:
        return False
    return (authorization or "").strip() == f"Bearer {token}"


def _iso_z(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    text = value.isoformat()
    if text.endswith("+00:00"):
        return text[:-6] + "Z"
    return text


def _empty_cache_block(*, enabled: bool = False, degraded: bool = False) -> dict[str, Any]:
    return {
        "enabled": enabled, # có đang bật cấu hình cache Redis hay không?   
        "ready": False, # cache đã có dữ liệu hợp lệ hưa
        "degraded": degraded, # syncer đang bị lỗi hay không?
        "generation": "", # generation hiện tại(phiên bản snapshot dữ liệu đang phục vụ)
        "version": "", # version của generation
        "restaurants": 0, # số lượng restaurant 
        "hotlines": 0, # số lượng hotline
        "menus": 0, # số lượng menu
        "last_sync_at": None, # thời gian sync gần nhất
        "last_sync_error": None, # lỗi sync gần nhất
        "next_poll_in_s": None, # thời gian đến lần sync tiếp theo
    }


async def _cache_health(cache: Any, syncer: Any) -> dict[str, Any]:
    if cache is None:
        return _empty_cache_block(enabled=False, degraded=bool(getattr(syncer, "degraded", False)))
    block = _empty_cache_block(enabled=True)
    try:
        stats = await cache.stats()
    except Exception:
        logger.warning("Cache stats failed", exc_info=True)
        stats = {}
    block["ready"] = bool(stats.get("generation"))
    block["generation"] = str(stats.get("generation") or "")
    block["version"] = str(stats.get("version") or "")
    for key in ("restaurants", "hotlines", "menus"):
        try:
            block[key] = int(stats.get(key) or 0)
        except (TypeError, ValueError):
            block[key] = 0
    if syncer is not None:
        block["degraded"] = bool(getattr(syncer, "degraded", False))
        block["last_sync_at"] = _iso_z(getattr(syncer, "last_sync_at", None))
        block["last_sync_error"] = getattr(syncer, "last_sync_error", None)
        next_poll = getattr(syncer, "next_poll_seconds", None)
        block["next_poll_in_s"] = int(next_poll) if next_poll is not None else None
    return block


def create_app(
    settings: Optional[Settings] = None,
    *,
    stt_factory: Optional[Callable[[], Any]] = None,
    llm: Any = None,
    tts: Any = None,
    openai_client: Any = None,
    restaurant_client: Any = None,
    matcher: Any = None,
    order_client: Any = None,
    menu_matcher: Any = None,
    catalog_cache: Any = None,
    catalog_syncer: Any = None,
) -> FastAPI:
    settings = settings or load_settings()
    if not settings.ai_bridge_token:
        logger.error("AI_BRIDGE_TOKEN is empty; every /v1/bridge handshake will be rejected")
    if not settings.openai_api_key:
        logger.error("OPENAI_API_KEY is empty; STT/LLM/TTS will fail on live calls")

    injected_cache = catalog_cache
    injected_syncer = catalog_syncer

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        cache = injected_cache
        syncer = injected_syncer
        created_cache = False
        created_syncer = False
        task = None
        if cache is None and settings.redis_url:
            try:
                cache = CatalogCache.from_url(
                    settings.redis_url,
                    namespace=settings.redis_namespace,
                    generation_ttl=settings.cache_generation_ttl,
                )
                created_cache = True
            except Exception:
                logger.exception("Redis client create failed; running without cache")
                cache = None
        if created_cache and cache is not None:
            try:
                await asyncio.wait_for(cache.connect(), timeout=max(settings.sync_timeout, 1))
            except Exception:
                logger.exception("Redis connect failed; running without cache")
                with contextlib.suppress(Exception):
                    await cache.aclose()
                cache = None
        if cache is not None and syncer is None and settings.sync_enabled:
            syncer = CatalogSyncer(
                cache=cache,
                base_url=settings.sync_api_base or settings.restaurant_api_base,
                timeout=settings.sync_timeout,
                interval=settings.sync_poll_seconds,
                max_backoff=settings.sync_max_backoff_seconds,
            )
            created_syncer = True
        app.state.catalog_cache = cache
        app.state.catalog_syncer = syncer

        if syncer is not None:
            try:
                await asyncio.wait_for(syncer.warm_once(), timeout=settings.sync_timeout)
            except Exception:
                logger.exception("Cache warm-up failed; continuing in degrade mode")
            task = asyncio.create_task(syncer.run_forever(), name="catalog-sync")
        try:
            yield
        finally:
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            if created_syncer and syncer is not None:
                with contextlib.suppress(Exception):
                    await syncer.aclose()
            if created_cache and cache is not None:
                with contextlib.suppress(Exception):
                    await cache.aclose()

    app = FastAPI(title="AI Bridge", version="2.0.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )
    app.state.settings = settings
    app.state.catalog_cache = None
    app.state.catalog_syncer = None

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
    if restaurant_client is None:
        restaurant_client = RestaurantClient(settings.restaurant_api_base)
    if matcher is None and openai_client is not None:
        matcher = OpenAiBranchMatcher(openai_client, settings.openai_model)
    if order_client is None:
        order_client = OrderClient(settings.restaurant_api_base)
    if menu_matcher is None and openai_client is not None:
        menu_matcher = OpenAiMenuMatcher(openai_client, settings.openai_model)
    app.state.stt_factory = stt_factory or default_stt_factory
    app.state.llm = llm
    app.state.tts = tts  # tts: 1 client tts được tạo ra từ openai_client
    app.state.restaurant_client = restaurant_client
    app.state.branch_matcher = matcher
    app.state.order_client = order_client
    app.state.menu_matcher = menu_matcher

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "cache": await _cache_health(
                getattr(app.state, "catalog_cache", None),
                getattr(app.state, "catalog_syncer", None),
            ),
        }

    @app.post("/internal/sync/refresh")
    async def refresh_sync(authorization: Optional[str] = Header(default=None)) -> dict[str, Any]:
        if not _http_bearer_authorized(authorization, settings.ai_bridge_token):
            raise HTTPException(status_code=401, detail="Unauthorized")
        syncer = getattr(app.state, "catalog_syncer", None)
        if syncer is None:
            raise HTTPException(status_code=503, detail="sync_disabled")
        try:
            ok = await syncer.warm_once()
        except Exception:
            logger.exception("Manual catalog refresh failed")
            raise HTTPException(status_code=500, detail="refresh_failed")
        return {
            "ok": bool(ok),
            "degraded": bool(getattr(syncer, "degraded", False)),
            "version": getattr(syncer, "version", "") or "",
            "error": getattr(syncer, "last_sync_error", None),
        }


## Khởi tạo kết nối websocket, so sánh header Authorization với token trong config
## Gọi Call Pipeline 
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
            websocket,
            stt=stt,
            llm=app.state.llm,
            tts=app.state.tts,
            restaurant_client=app.state.restaurant_client,
            matcher=app.state.branch_matcher,
            order_client=app.state.order_client,
            menu_matcher=app.state.menu_matcher,
            catalog_cache=getattr(app.state, "catalog_cache", None),
            cache_ttl=settings.cache_ttl_seconds,
            call_end_grace_ms=settings.call_end_grace_ms,
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
