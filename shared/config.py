from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_stt_model: str = "gpt-4o-mini-transcribe"
    openai_tts_model: str = "gpt-4o-mini-tts"
    openai_tts_voice: str = "nova"

    booking_api_url: str = "http://127.0.0.1:8001"
    voice_agent_url: str = "http://127.0.0.1:8000"
    browser_sim_port: int = 8002
    browser_sim_base_url: str = "http://127.0.0.1:8002"
    multi_branch: bool = True

    knowledge_dir: str = str(REPO_ROOT / "knowledge")
    chroma_path: str = str(REPO_ROOT / ".chroma")
    use_chroma: bool = False

    max_stt_fail_turns: int = 3
    large_party_threshold: int = 12
    opening_hour: int = 11
    closing_hour: int = 22

    @field_validator(
        "openai_api_key",
        "voice_agent_url",
        "browser_sim_base_url",
        mode="before",
    )
    @classmethod
    def strip_env_value(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().strip('"').strip("'")
        return value


def get_settings() -> Settings:
    return Settings()
