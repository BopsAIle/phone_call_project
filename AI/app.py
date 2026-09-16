"""AI bridge process: PCM in → STT → LLM → TTS → PCM out."""

from __future__ import annotations

import logging

import uvicorn

from bridge.server import create_app
from config import load_settings

settings = load_settings()
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
app = create_app(settings)

if __name__ == "__main__":
    uvicorn.run(
        "app:app",
        host=settings.ai_bridge_host,
        port=settings.ai_bridge_port,
        reload=False,
    )
