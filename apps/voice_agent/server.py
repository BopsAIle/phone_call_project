from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

from apps.browser_sim.sim import (
    BrowserChatStore,
    handle_browser_utterance,
    start_browser_call,
)
from apps.voice_agent.backend_client import BackendClient
from apps.voice_agent.dialog_engine import DialogEngine
from apps.voice_agent.rag import KnowledgeRetriever
from shared.config import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    backend = BackendClient(settings.booking_api_url)
    rag = KnowledgeRetriever(use_chroma=settings.use_chroma)
    rag.ingest()
    engine = DialogEngine(backend, rag, multi_branch=settings.multi_branch)
    app.state.settings = settings
    app.state.backend = backend
    app.state.rag = rag
    app.state.engine = engine
    app.state.browser_chats = BrowserChatStore()
    yield
    await backend.aclose()


app = FastAPI(title="Restaurant Voice Agent", version="0.1.0", lifespan=lifespan)


class TextStartRequest(BaseModel):
    call_sid: str | None = "text-local"
    from_number: str | None = None


class TextTurnRequest(BaseModel):
    text: str


class BrowserStartRequest(BaseModel):
    call_sid: str | None = None
    from_number: str | None = None


class BrowserUtteranceRequest(BaseModel):
    text: str | None = None
    audio_b64: str | None = None
    audio_filename: str = "speech.webm"


@app.get("/health")
def health(request: Request) -> dict[str, Any]:
    settings = request.app.state.settings
    return {
        "status": "ok",
        "role": "voice-agent",
        "booking_api": settings.booking_api_url,
        "browser_voice": "/browser/voice",
        "browser_utterance": "/browser/{session_id}/utterance",
    }


@app.post("/text/start")
async def text_start(body: TextStartRequest, request: Request) -> dict[str, Any]:
    engine: DialogEngine = request.app.state.engine
    result = await engine.start(call_sid=body.call_sid, from_number=body.from_number)
    return _turn_payload(result)


@app.post("/text/{session_id}/turn")
async def text_turn(session_id: str, body: TextTurnRequest, request: Request) -> dict[str, Any]:
    engine: DialogEngine = request.app.state.engine
    result = await engine.handle_user_turn(session_id, body.text)
    return _turn_payload(result)


@app.post("/browser/voice")
async def browser_voice(body: BrowserStartRequest, request: Request) -> dict[str, Any]:
    result = await start_browser_call(
        engine=request.app.state.engine,
        chats=request.app.state.browser_chats,
        settings=request.app.state.settings,
        from_number=body.from_number,
        call_sid=body.call_sid,
    )
    return result.as_payload()


@app.post("/browser/{session_id}/utterance")
async def browser_utterance(
    session_id: str,
    body: BrowserUtteranceRequest,
    request: Request,
) -> dict[str, Any]:
    try:
        result = await handle_browser_utterance(
            engine=request.app.state.engine,
            chats=request.app.state.browser_chats,
            settings=request.app.state.settings,
            session_id=session_id,
            text=body.text,
            audio_b64=body.audio_b64,
            audio_filename=body.audio_filename,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Browser call session not found") from None
    return result.as_payload()


def _turn_payload(result: Any) -> dict[str, Any]:
    return {
        "assistant_text": result.assistant_text,
        "action": result.action,
        "session_id": result.session.id,
        "missing_fields": result.missing_fields,
        "booking_id": result.booking_id,
        "transfer_reason": result.transfer_reason,
        "rag_hits": result.rag_hits,
        "slots": result.session.slots.model_dump(mode="json"),
        "availability": result.availability.model_dump(mode="json") if result.availability else None,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("apps.voice_agent.server:app", host="0.0.0.0", port=8000)
