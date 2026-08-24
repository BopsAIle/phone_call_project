"""Local browser phone UI. Conversation requests are forwarded to the voice agent."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from apps.browser_sim.sim import BROWSER_HTML_PATH, browser_page_url
from shared.config import get_settings

## Do các request là độc lập với nhau, nên FastAPI có thể xây dựng 1 nơi có thể dùng chung là app.state
#app.state cho phép các HTTP request vốn độc lập với nhau chia sẻ các dữ liệu/resource ở cấp application.
@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    voice = httpx.AsyncClient(base_url=settings.voice_agent_url.rstrip("/"), timeout=120.0)
    app.state.settings = settings
    app.state.voice = voice
    yield
    await voice.aclose()


app = FastAPI(title="Browser Phone Simulator", version="0.1.0", lifespan=lifespan)


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
        "role": "browser-simulator",
        "page": browser_page_url(settings),
        "voice_agent": settings.voice_agent_url,
        "booking_api": settings.booking_api_url,
    }


@app.get("/")
@app.get("/browser")
def browser_phone() -> FileResponse:
    if not BROWSER_HTML_PATH.exists():
        raise HTTPException(status_code=404, detail="Browser simulator page missing")
    return FileResponse(BROWSER_HTML_PATH, media_type="text/html; charset=utf-8")


@app.post("/browser/voice")
async def browser_voice(body: BrowserStartRequest, request: Request) -> dict[str, Any]:
    return await _forward(request, "/browser/voice", body.model_dump())


@app.post("/browser/{session_id}/utterance")
async def browser_utterance(
    session_id: str,
    body: BrowserUtteranceRequest,
    request: Request,
) -> dict[str, Any]:
    return await _forward(request, f"/browser/{session_id}/utterance", body.model_dump())


async def _forward(request: Request, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    voice: httpx.AsyncClient = request.app.state.voice
    settings = request.app.state.settings
    try:
        response = await voice.post(path, json=payload)
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Voice agent unreachable at {settings.voice_agent_url}: {exc}",
        ) from exc
    if response.status_code >= 400:
        detail: Any
        try:
            detail = response.json()
        except ValueError:
            detail = response.text
        raise HTTPException(status_code=response.status_code, detail=detail)
    return response.json()


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "apps.browser_sim.server:app",
        host="0.0.0.0",
        port=settings.browser_sim_port,
    )
