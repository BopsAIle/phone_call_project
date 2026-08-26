from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from bridge.server import create_app
from config import Settings
from tests.fakes import FakeSTT, ScriptedLlm, ScriptedTts


def _app():
    return create_app(
        Settings(ai_bridge_token="secret", openai_api_key=""),
        stt_factory=FakeSTT,
        llm=ScriptedLlm([]),
        tts=ScriptedTts(),
    )


def test_health() -> None:
    with TestClient(_app()) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


def test_bridge_requires_bearer() -> None:
    with TestClient(_app()) as client:
        with pytest.raises(Exception):
            with client.websocket_connect("/v1/bridge"):
                pass


def test_bridge_accepts_bearer_and_greeting() -> None:
    with TestClient(_app()) as client:
        with client.websocket_connect("/v1/bridge", headers={"Authorization": "Bearer secret"}) as ws:
            ws.send_text(
                '{"event":"session.init","callId":"c1","storeName":"X","timezone":"UTC",'
                '"locale":"en","greeting":"Hello from the assistant."}'
            )
            audio = ws.receive_bytes()
            assert len(audio) >= 2
            assert len(audio) % 2 == 0


def test_bridge_accepts_query_token() -> None:
    """Browsers cannot set Authorization on WebSocket; demo UI uses ?token=."""
    with TestClient(_app()) as client:
        with client.websocket_connect("/v1/bridge?token=secret") as ws:
            ws.send_text(
                '{"event":"session.init","callId":"c1","storeName":"X","timezone":"UTC",'
                '"locale":"en","greeting":"Hello from the assistant."}'
            )
            audio = ws.receive_bytes()
            assert len(audio) >= 2
            assert len(audio) % 2 == 0


def test_health_allows_browser_origin() -> None:
    with TestClient(_app()) as client:
        response = client.get("/health", headers={"Origin": "http://localhost:5173"})
        assert response.status_code == 200
        assert response.headers.get("access-control-allow-origin") == "*"
