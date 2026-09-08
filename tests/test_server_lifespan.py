from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from bridge.server import create_app
from config import Settings
from tests.fakes import FakeSTT, ScriptedLlm, ScriptedTts


def _settings(**kwargs) -> Settings:
    values = dict(
        ai_bridge_token="secret",
        openai_api_key="",
        redis_url="",
        sync_enabled=True,
        sync_timeout=2,
    )
    values.update(kwargs)
    return Settings(**values)


def _app(**kwargs):
    return create_app(
        kwargs.pop("settings", _settings()),
        stt_factory=FakeSTT,
        llm=ScriptedLlm([]),
        tts=ScriptedTts(),
        **kwargs,
    )


class _FailingCache:
    async def connect(self) -> None:
        raise OSError("redis down")

    async def aclose(self) -> None:
        pass


class _StubCache:
    def __init__(self, stats: dict | None = None) -> None:
        self._stats = stats or {
            "generation": "",
            "version": "",
            "restaurants": 0,
            "hotlines": 0,
            "menus": 0,
        }

    async def connect(self) -> None:
        return None

    async def aclose(self) -> None:
        return None

    async def stats(self) -> dict:
        return dict(self._stats)


class _FakeSyncer:
    def __init__(self, *, ok: bool = True, degraded: bool = False, version: str = "hash-v1") -> None:
        self.ok = ok
        self.degraded = degraded
        self.version = version
        self.last_sync_at = None
        self.last_sync_error = None if ok else "fetch_failed"
        self.warm_calls = 0
        self.closed = False
        self.next_poll_seconds = 300

    async def warm_once(self) -> bool:
        self.warm_calls += 1
        return self.ok

    async def run_forever(self) -> None:
        try:
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            raise

    async def aclose(self) -> None:
        self.closed = True


def test_empty_redis_url_starts_without_cache() -> None:
    app = _app(settings=_settings(redis_url="", sync_enabled=True))
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["cache"]["enabled"] is False
        assert body["cache"]["ready"] is False
        assert app.state.catalog_cache is None
        assert app.state.catalog_syncer is None


def test_bad_redis_connect_app_still_starts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "bridge.server.CatalogCache.from_url",
        classmethod(lambda cls, *args, **kwargs: _FailingCache()),
    )
    app = _app(settings=_settings(redis_url="redis://127.0.0.1:1", sync_enabled=True))
    with TestClient(app) as client:
        body = client.get("/health").json()
        assert body["status"] == "ok"
        assert body["cache"]["enabled"] is False
        assert app.state.catalog_cache is None
        assert app.state.catalog_syncer is None


def test_sync_disabled_skips_background_syncer() -> None:
    cache = _StubCache()
    app = _app(
        settings=_settings(redis_url="redis://unused", sync_enabled=False),
        catalog_cache=cache,
    )
    with TestClient(app) as client:
        body = client.get("/health").json()
        assert body["status"] == "ok"
        assert body["cache"]["enabled"] is True
        assert body["cache"]["ready"] is False
        assert app.state.catalog_cache is cache
        assert app.state.catalog_syncer is None
        refresh = client.post(
            "/internal/sync/refresh",
            headers={"Authorization": "Bearer secret"},
        )
        assert refresh.status_code == 503


def test_health_cache_block_when_warm() -> None:
    cache = _StubCache(
        {
            "generation": "g1",
            "version": "hash-v1",
            "restaurants": 1,
            "hotlines": 1,
            "menus": 0,
        }
    )
    syncer = _FakeSyncer()
    app = _app(
        settings=_settings(sync_enabled=True),
        catalog_cache=cache,
        catalog_syncer=syncer,
    )
    with TestClient(app) as client:
        body = client.get("/health").json()
        assert body["status"] == "ok"
        cache_block = body["cache"]
        assert cache_block["enabled"] is True
        assert cache_block["ready"] is True
        assert cache_block["generation"] == "g1"
        assert cache_block["version"] == "hash-v1"
        assert cache_block["restaurants"] == 1
        assert cache_block["hotlines"] == 1
        assert cache_block["degraded"] is False
        assert cache_block["next_poll_in_s"] == 300
        assert syncer.warm_calls == 1


def test_refresh_requires_bearer() -> None:
    app = _app(catalog_syncer=_FakeSyncer())
    with TestClient(app) as client:
        assert client.post("/internal/sync/refresh").status_code == 401
        ok = client.post(
            "/internal/sync/refresh",
            headers={"Authorization": "Bearer secret"},
        )
        assert ok.status_code == 200
        assert ok.json()["ok"] is True
        assert ok.json()["version"] == "hash-v1"


def test_create_app_from_url_failure_does_not_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args, **_kwargs):
        raise OSError("bad redis url")

    monkeypatch.setattr("bridge.server.CatalogCache.from_url", boom)
    app = _app(settings=_settings(redis_url="redis://not-a-host:6379", sync_enabled=True))
    with TestClient(app) as client:
        body = client.get("/health").json()
        assert body["status"] == "ok"
        assert body["cache"]["enabled"] is False
