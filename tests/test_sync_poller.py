from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest
from fakeredis.aioredis import FakeRedis

from cache.redis_store import CatalogCache, GenerationPayload
from sync.models import parse_sync_payload
from sync.poller import CatalogSyncer

_BASE = "https://example.test"


def _restaurant_body(
    *,
    name: str = "Bella Vista",
    status: str = "active",
    extra_branch: bool = False,
) -> dict[str, Any]:
    branches = [
        {
            "id": "q1",
            "name": "Quận 1",
            "address": "12 Lê Lợi",
            "opening_time": "09:00",
            "closing_time": "22:00",
            "status": "active",
        },
        {"id": "dead", "name": "Closed", "status": "inactive"},
    ]
    if extra_branch:
        branches.append({"id": "q3", "name": "Quận 3", "status": "active"})
    return {
        "id": "rest-1",
        "name": name,
        "phone": "1900-636-886",
        "hotlines": ["1900636886", "+02839123456"],
        "status": status,
        "branches": branches,
        "menus": {
            "q1": [
                {
                    "id": "m1",
                    "name": "Phở bò",
                    "price": 65000,
                    "currency": "VND",
                    "unit": "tô",
                    "status": "available",
                }
            ],
            "dead": [{"id": "m2", "name": "Hidden", "price": 1}],
        },
    }


def _branches_payload(version: str = "hash-v1", **kwargs: Any) -> dict[str, Any]:
    return {
        "version": version,
        "updated_at": "2026-09-07T04:10:11Z",
        "restaurants": [_restaurant_body(**kwargs)],
    }


class _SleepUntil:
    """Record delays; raise CancelledError after `cycles` sleeps (so that many work loops run)."""

    def __init__(self, cycles: int) -> None:
        self.delays: list[float] = []
        self._cycles = cycles
        self._n = 0

    async def __call__(self, delay: float) -> None:
        self._n += 1
        if self._n > self._cycles:
            raise asyncio.CancelledError
        self.delays.append(delay)


def _cache() -> CatalogCache:
    return CatalogCache(FakeRedis(decode_responses=True))


def _syncer(
    handler,
    cache: CatalogCache | None = None,
    *,
    sleep: _SleepUntil | None = None,
    instance_id: str = "writer-1",
    interval: int = 300,
    max_backoff: int = 2400,
) -> tuple[CatalogSyncer, CatalogCache]:
    cache = cache or _cache()
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=5)
    syncer = CatalogSyncer(
        cache=cache,
        base_url=_BASE,
        timeout=5,
        interval=interval,
        max_backoff=max_backoff,
        http=http,
        sleep=sleep,
        instance_id=instance_id,
    )
    return syncer, cache


def test_parse_unwraps_filters_active_and_normalizes_hotline() -> None:
    parsed = parse_sync_payload({"success": True, "data": _branches_payload()})
    assert parsed is not None
    assert parsed.version == "hash-v1"
    assert set(parsed.by_hotline) == {"1900636886", "02839123456"}
    restaurant = parsed.by_hotline["1900636886"]
    assert restaurant.name == "Bella Vista"
    assert [branch.id for branch in restaurant.branches] == ["q1"]
    assert "q1" in parsed.menus
    assert parsed.menus["q1"][0].name == "Phở bò"
    assert "dead" not in parsed.menus

    inactive = parse_sync_payload(_branches_payload(status="inactive"))
    assert inactive is not None
    assert inactive.by_hotline == {}
    assert inactive.menus == {}

    assert parse_sync_payload("nope") is None


async def test_version_unchanged_skips_write() -> None:
    cache = _cache()
    parsed = parse_sync_payload(_branches_payload("hash-v1"))
    assert parsed is not None
    await cache.swap_generation(parsed.to_generation(), "hash-v1")
    writes = {"swap": 0}
    orig = cache.swap_generation

    async def counting_swap(payload: GenerationPayload, version: str) -> None:
        writes["swap"] += 1
        await orig(payload, version)

    cache.swap_generation = counting_swap  # type: ignore[method-assign]
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path.endswith("/check-version"):
            return httpx.Response(200, json={"version": "hash-v1"})
        raise AssertionError(f"unexpected {request.url.path}")

    syncer, _ = _syncer(handler, cache, sleep=_SleepUntil(1))
    with pytest.raises(asyncio.CancelledError):
        await syncer.run_forever()
    assert writes["swap"] == 0
    assert await cache.get_version() == "hash-v1"
    assert int(await cache._redis.get("aibridge:catalog:generation")) == 1
    assert paths == ["/api/v1/sync/check-version"]
    assert not syncer.degraded


async def test_version_change_swaps_new_payload() -> None:
    cache = _cache()
    first = parse_sync_payload(_branches_payload("hash-v1", name="Bella"))
    assert first is not None
    await cache.swap_generation(first.to_generation(), "hash-v1")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/check-version"):
            return httpx.Response(200, json={"data": {"version": "hash-v2"}})
        if request.url.path.endswith("/branches"):
            return httpx.Response(
                200,
                json=_branches_payload("hash-v2", name="Bella New", extra_branch=True),
            )
        raise AssertionError(f"unexpected {request.url.path}")

    syncer, cache = _syncer(handler, cache, sleep=_SleepUntil(1))
    with pytest.raises(asyncio.CancelledError):
        await syncer.run_forever()

    restaurant = await cache.get_restaurant("1900-636-886")
    assert restaurant is not None
    assert restaurant.name == "Bella New"
    assert [branch.id for branch in restaurant.branches] == ["q1", "q3"]
    assert await cache.get_version() == "hash-v2"
    assert await cache.current_generation() == "g2"
    assert syncer.version == "hash-v2"
    assert syncer.last_sync_error is None
    assert syncer.last_sync_at is not None


async def test_check_version_404_sets_degraded_without_crash() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "not found"})

    syncer, cache = _syncer(handler)
    assert await syncer.warm_once() is False
    assert syncer.degraded is True
    assert await cache.get_version() == ""
    assert syncer.last_sync_error == "sync_unavailable"

    sleep = _SleepUntil(1)
    syncer._sleep = sleep
    with pytest.raises(asyncio.CancelledError):
        await syncer.run_forever()
    assert syncer.degraded is True
    assert sleep.delays[0] == 300
    assert syncer.next_poll_seconds == 600


async def test_network_errors_double_delay_until_cap() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("backend down", request=request)

    sleep = _SleepUntil(5)
    syncer, cache = _syncer(handler, sleep=sleep, interval=300, max_backoff=2400)
    with pytest.raises(asyncio.CancelledError):
        await syncer.run_forever()
    assert sleep.delays == [300, 600, 1200, 2400, 2400]
    assert syncer.next_poll_seconds == 2400
    assert syncer.last_sync_error
    assert await cache.get_version() == ""


async def test_warm_once_failure_does_not_raise() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    syncer, _ = _syncer(handler)
    assert await syncer.warm_once() is False
    assert syncer.last_sync_error


async def test_cancel_exits_cleanly() -> None:
    started = asyncio.Event()

    async def hanging_sleep(delay: float) -> None:
        started.set()
        await asyncio.Event().wait()

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("should not fetch after cancel")

    syncer, _ = _syncer(handler, sleep=hanging_sleep)
    task = asyncio.create_task(syncer.run_forever())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_missing_lock_skips_write() -> None:
    cache = _cache()
    await cache._redis.set("aibridge:sync:lock", "other-instance", ex=60)
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return httpx.Response(200, json={"version": "hash-v9"})

    syncer, cache = _syncer(handler, cache, sleep=_SleepUntil(1), instance_id="writer-2")
    with pytest.raises(asyncio.CancelledError):
        await syncer.run_forever()
    assert paths == []
    assert await cache.get_version() == ""
