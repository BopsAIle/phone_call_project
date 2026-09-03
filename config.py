"""Runtime settings for the AI bridge process."""

from __future__ import annotations

import os

from dotenv import load_dotenv
from pydantic import BaseModel, Field


class Settings(BaseModel):
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_stt_model: str = "gpt-4o-mini-transcribe"
    openai_tts_model: str = "gpt-4o-mini-tts"
    openai_tts_voice: str = "nova"
    ai_bridge_token: str = ""
    ai_bridge_host: str = "0.0.0.0"
    ai_bridge_port: int = 8080
    log_level: str = "INFO"
    tts_chunk_bytes: int = Field(default=4096, ge=2)
    # Restaurant server that receives booking / delivery requests for staff to
    # act on. Empty URL means the bridge runs against an in-memory stub.
    store_api_url: str = ""
    store_api_token: str = ""
    store_api_timeout: float = Field(default=5.0, gt=0)


def load_settings() -> Settings:
    load_dotenv()
    return Settings(
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        openai_stt_model=os.getenv("OPENAI_STT_MODEL", "gpt-4o-mini-transcribe"),
        openai_tts_model=os.getenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts"),
        openai_tts_voice=os.getenv("OPENAI_TTS_VOICE", "nova"),
        ai_bridge_token=os.getenv("AI_BRIDGE_TOKEN", ""),
        ai_bridge_host=os.getenv("AI_BRIDGE_HOST", "0.0.0.0"),
        ai_bridge_port=int(os.getenv("AI_BRIDGE_PORT", "8080")),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        store_api_url=os.getenv("STORE_API_URL", ""),
        store_api_token=os.getenv("STORE_API_TOKEN", ""),
        store_api_timeout=float(os.getenv("STORE_API_TIMEOUT", "5.0")),
    )
