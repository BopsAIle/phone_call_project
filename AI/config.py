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
    # Legacy /v1/bridge socket (telephony backend + browser demo). Off = Telnyx only.
    bridge_enabled: bool = True
    # --- Telnyx Call Control v2 + Media Streaming ---
    telnyx_enabled: bool = False
    telnyx_api_key: str = ""
    telnyx_api_base: str = "https://api.telnyx.com/v2"
    telnyx_public_key: str = ""  # base64 Ed25519, from the Telnyx portal
    telnyx_webhook_tolerance_seconds: int = Field(default=300, ge=0)
    telnyx_stream_url: str = ""  # wss://<public-host>/telnyx/media
    telnyx_stream_token: str = ""  # appended as ?token= ; Telnyx does not sign the WS
    telnyx_stream_codec: str = "L16"
    telnyx_stream_track: str = "inbound_track"
    telnyx_bidi_codec: str = "L16"
    telnyx_bidi_sampling_rate: int = Field(default=16_000, ge=8_000)
    telnyx_frame_ms: int = Field(default=20, ge=20)
    telnyx_default_locale: str = "en"
    telnyx_default_timezone: str = "UTC"
    telnyx_default_store_name: str = ""
    telnyx_greeting: str = "Hello, you have reached our automated assistant."
    telnyx_mark_timeout_seconds: float = Field(default=20.0, gt=0)
    # RFC 2586 says L16 is big-endian; set false if the carrier sends little-endian
    # (symptom: white noise both directions, no error anywhere).
    telnyx_l16_byteswap: bool = True


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
        bridge_enabled=_env_bool("BRIDGE_ENABLED", True),
        telnyx_enabled=_env_bool("TELNYX_ENABLED", False),
        telnyx_api_key=os.getenv("TELNYX_API_KEY", "").strip(),
        telnyx_api_base=os.getenv("TELNYX_API_BASE", "https://api.telnyx.com/v2").strip(),
        telnyx_public_key=os.getenv("TELNYX_PUBLIC_KEY", "").strip(),
        telnyx_webhook_tolerance_seconds=int(os.getenv("TELNYX_WEBHOOK_TOLERANCE_SECONDS", "300")),
        telnyx_stream_url=os.getenv("TELNYX_STREAM_URL", "").strip(),
        telnyx_stream_token=os.getenv("TELNYX_STREAM_TOKEN", "").strip(),
        telnyx_stream_codec=os.getenv("TELNYX_STREAM_CODEC", "L16").strip() or "L16",
        telnyx_stream_track=os.getenv("TELNYX_STREAM_TRACK", "inbound_track").strip() or "inbound_track",
        telnyx_bidi_codec=os.getenv("TELNYX_BIDI_CODEC", "L16").strip() or "L16",
        telnyx_bidi_sampling_rate=int(os.getenv("TELNYX_BIDI_SAMPLING_RATE", "16000")),
        telnyx_frame_ms=int(os.getenv("TELNYX_FRAME_MS", "20")),
        telnyx_default_locale=os.getenv("TELNYX_DEFAULT_LOCALE", "en").strip() or "en",
        telnyx_default_timezone=os.getenv("TELNYX_DEFAULT_TIMEZONE", "UTC").strip() or "UTC",
        telnyx_default_store_name=os.getenv("TELNYX_DEFAULT_STORE_NAME", "").strip(),
        telnyx_greeting=os.getenv(
            "TELNYX_GREETING", "Hello, you have reached our automated assistant."
        ).strip(),
        telnyx_mark_timeout_seconds=float(os.getenv("TELNYX_MARK_TIMEOUT_SECONDS", "20")),
        telnyx_l16_byteswap=_env_bool("TELNYX_L16_BYTESWAP", True),
    )
