"""Runtime settings for the AI bridge process."""

from __future__ import annotations

import os

from dotenv import load_dotenv
from pydantic import BaseModel, Field

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}
_DEFAULT_API_BASE = "http://127.0.0.1:3001"


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    value = raw.strip().lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    return default


class Settings(BaseModel):
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_stt_model: str = "gpt-4o-mini-transcribe"
    openai_tts_model: str = "tts-1"
    openai_tts_voice: str = "nova"
    ai_bridge_token: str = ""
    ai_bridge_host: str = "0.0.0.0"
    ai_bridge_port: int = 8080
    log_level: str = "INFO"
    tts_chunk_bytes: int = Field(default=1024, ge=2)
    restaurant_api_base: str = _DEFAULT_API_BASE
    # Empty REDIS_URL → no cache / no syncer (v1 behavior). Opt-in; do not default to localhost.
    redis_url: str = ""
    redis_namespace: str = "aibridge"
    sync_enabled: bool = True
    sync_poll_seconds: int = Field(default=300, ge=1)
    sync_timeout: int = Field(default=10, ge=1)
    sync_api_base: str = _DEFAULT_API_BASE
    sync_max_backoff_seconds: int = Field(default=2400, ge=1)
    cache_generation_ttl: int = Field(default=10800, ge=1)
    cache_ttl_seconds: int = Field(default=600, ge=1)
    call_end_grace_ms: int = Field(default=300, ge=0)
    dtmf_menu_timeout_seconds: int = Field(default=7, ge=1)
    dtmf_debounce_ms: int = Field(default=500, ge=0)
    dtmf_max_invalid: int = Field(default=2, ge=0)


def load_settings() -> Settings:
    load_dotenv()
    restaurant_api_base = os.getenv("RESTAURANT_API_BASE", _DEFAULT_API_BASE).strip()
    return Settings(
        openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip(),
        openai_stt_model=os.getenv("OPENAI_STT_MODEL", "gpt-4o-mini-transcribe").strip(),
        openai_tts_model=os.getenv("OPENAI_TTS_MODEL", "tts-1").strip(),
        openai_tts_voice=os.getenv("OPENAI_TTS_VOICE", "nova").strip(),
        ai_bridge_token=os.getenv("AI_BRIDGE_TOKEN", "").strip(),
        ai_bridge_host=os.getenv("AI_BRIDGE_HOST", "0.0.0.0").strip(),
        ai_bridge_port=int(os.getenv("AI_BRIDGE_PORT", "8080")),
        log_level=os.getenv("LOG_LEVEL", "INFO").strip(),
        tts_chunk_bytes=int(os.getenv("TTS_CHUNK_BYTES", "1024")),
        restaurant_api_base=restaurant_api_base,
        redis_url=os.getenv("REDIS_URL", "").strip(),
        redis_namespace=os.getenv("REDIS_NAMESPACE", "aibridge").strip() or "aibridge",
        sync_enabled=_env_bool("SYNC_ENABLED", True),
        sync_poll_seconds=int(os.getenv("SYNC_POLL_SECONDS", "300")),
        sync_timeout=int(os.getenv("SYNC_TIMEOUT", "10")),
        sync_api_base=os.getenv("SYNC_API_BASE", "").strip() or restaurant_api_base,
        sync_max_backoff_seconds=int(os.getenv("SYNC_MAX_BACKOFF_SECONDS", "2400")),
        cache_generation_ttl=int(os.getenv("CACHE_GENERATION_TTL", "10800")),
        cache_ttl_seconds=int(os.getenv("CACHE_TTL_SECONDS", "600")),
        call_end_grace_ms=int(os.getenv("CALL_END_GRACE_MS", "300")),
        dtmf_menu_timeout_seconds=int(os.getenv("DTMF_MENU_TIMEOUT_SECONDS", "7")),
        dtmf_debounce_ms=int(os.getenv("DTMF_DEBOUNCE_MS", "500")),
        dtmf_max_invalid=int(os.getenv("DTMF_MAX_INVALID", "2")),
    )
