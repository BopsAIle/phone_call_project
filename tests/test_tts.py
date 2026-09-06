from __future__ import annotations

from config import Settings, load_settings
from tts.openai_tts import OpenAiTts, _supports_instructions


class _FakeStreamResponse:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks
        self.iter_chunk_size: int | None = None

    async def iter_bytes(self, chunk_size: int | None = None):
        self.iter_chunk_size = chunk_size
        for chunk in self._chunks:
            yield chunk

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeStreaming:
    def __init__(self, chunks: list[bytes]) -> None:
        self.calls: list[dict] = []
        self.response = _FakeStreamResponse(chunks)

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class _FakeClient:
    def __init__(self, chunks: list[bytes] | None = None) -> None:
        pcm = chunks if chunks is not None else [b"\x00\x01" * 1200]
        self.streaming = _FakeStreaming(pcm)
        self.audio = type("Audio", (), {})()
        self.audio.speech = type("Speech", (), {})()
        self.audio.speech.with_streaming_response = self.streaming


def test_settings_default_to_fast_phone_tts() -> None:
    s = Settings()
    assert s.openai_tts_model == "tts-1"
    assert s.tts_chunk_bytes == 1024


def test_load_settings_reads_tts_env(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_TTS_MODEL", "tts-1-hd")
    monkeypatch.setenv("TTS_CHUNK_BYTES", "512")
    s = load_settings()
    assert s.openai_tts_model == "tts-1-hd"
    assert s.tts_chunk_bytes == 512


def test_instructions_only_on_gpt4o_tts() -> None:
    assert not _supports_instructions("tts-1")
    assert not _supports_instructions("tts-1-hd")
    assert _supports_instructions("gpt-4o-mini-tts")
    assert _supports_instructions("gpt-4o-tts")


async def test_tts1_omits_instructions_and_reads_small_chunks() -> None:
    client = _FakeClient()
    tts = OpenAiTts(client, "tts-1", "nova", chunk_bytes=1024)
    out = b""
    async for pcm in tts.stream_pcm16("Xin chào quý khách.", "vi", lambda: False):
        out += pcm
    assert client.streaming.calls
    kwargs = client.streaming.calls[0]
    assert kwargs["model"] == "tts-1"
    assert kwargs["voice"] == "nova"
    assert kwargs["input"] == "Xin chào quý khách."
    assert kwargs["response_format"] == "pcm"
    assert "instructions" not in kwargs
    assert client.streaming.response.iter_chunk_size == 1024
    assert len(out) >= 2
    assert len(out) % 2 == 0


async def test_gpt4o_mini_tts_sends_short_instructions() -> None:
    client = _FakeClient()
    tts = OpenAiTts(client, "gpt-4o-mini-tts", "nova")
    async for _ in tts.stream_pcm16("Hello.", "en", lambda: False):
        pass
    kwargs = client.streaming.calls[0]
    assert kwargs["instructions"] == "Phone, en."
    assert len(kwargs["instructions"]) < 40


async def test_empty_text_skips_http() -> None:
    client = _FakeClient()
    tts = OpenAiTts(client, "tts-1", "nova")
    chunks = [pcm async for pcm in tts.stream_pcm16("   ", "vi", lambda: False)]
    assert chunks == []
    assert client.streaming.calls == []
