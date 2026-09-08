"""Background catalog poller: check-version → swap Redis generation."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Optional

import httpx

from booking.client import unwrap_data
from cache.redis_store import CatalogCache
from sync.models import SyncPayload, parse_sync_payload

logger = logging.getLogger(__name__)

_CHECK_VERSION_PATH = "/api/v1/sync/check-version"
_BRANCHES_PATH = "/api/v1/sync/branches"
_DEFAULT_LOCK_TTL = 60

SleepFn = Callable[[float], Awaitable[None]]


class SyncUnavailable(Exception):
    """Backend chưa có /api/v1/sync/* hoặc payload không dùng được."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)

## Vai trò của CatalogSyncer là 1 background worker chuyên đi đồng bộ dữ liệu danh mục từ backend vào Redis cache.
class CatalogSyncer:
    def __init__(
        self,
        *,
        cache: CatalogCache,
        base_url: str,
        timeout: float = 10,
        interval: int = 300,
        max_backoff: int = 2400,
        http: Optional[httpx.AsyncClient] = None,
        sleep: Optional[SleepFn] = None,
        instance_id: Optional[str] = None,
        lock_ttl: int = _DEFAULT_LOCK_TTL,
    ) -> None:
        self._cache = cache
        self._base = (base_url or "").rstrip("/")
        self._owns_http = http is None
        self._http = http or httpx.AsyncClient(timeout=timeout)
        self._interval = max(int(interval), 1)
        self._max_backoff = max(int(max_backoff), 1)
        self._delay = float(self._interval)
        self._sleep: SleepFn = sleep or asyncio.sleep
        self._instance_id = (instance_id or uuid.uuid4().hex).strip()
        self._lock_ttl = max(int(lock_ttl), 1)
        self.degraded = False
        self.last_sync_at: datetime | None = None
        self.last_sync_error: str | None = None
        self.version = ""

    @property
    def next_poll_seconds(self) -> int:
        return int(self._delay)

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

## Server chỉ gọi warm_once khi khởi động, và chỉ 1 lần. Nếu không có dữ liệu, trả về False.
## hoặc warrm_once được gọi khi người dùng nhập
    async def warm_once(self) -> bool:
        """Kéo full payload và swap vào Redis. Trả True nếu cache dùng được. Không raise."""
        try:
            if not await self._acquire_lock():
                logger.debug("Warm skip: not writer")
                cached = await self._cache.get_version()
                if cached:
                    self.version = cached
                    return True
                return False
            version = await self._fetch_version()
            if version is None:
                self.degraded = True
                self.last_sync_error = "sync_unavailable"
                return False
            payload = await self._fetch_payload()
            if payload is None:
                self.last_sync_error = "fetch_failed"
                return False
            await self._cache.swap_generation(payload.to_generation(), version)
            self.version = version
            self.degraded = False
            self.last_sync_at = _utcnow()
            self.last_sync_error = None
            self._delay = float(self._interval)
            return True
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.last_sync_error = str(exc)
            logger.warning("warm_once failed: %s", exc)
            return False

## Vòng lặp hỏi backend để lấy verison mới của dữu liệu
#Nếu version mới hơn version hiện tại, thì lấy payload mới và swap vào Redis.
# Nếu version giống nhau, thì skip.
    async def run_forever(self) -> None:
        while True:
            await self._sleep(self._delay)
            try:
                locked = await self._acquire_lock()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("Writer lock failed; skip this cycle", exc_info=True)
                continue
            if not locked:
                logger.debug("Sync skip: not writer")
                continue
            if self.degraded:
                self._delay = min(self._delay * 2, self._max_backoff)
                try:
                    if await self._probe_endpoints():
                        self.degraded = False
                        self._delay = float(self._interval)
                        logger.info("Sync endpoints available again; leaving degrade mode")
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self.last_sync_error = str(exc)
                    logger.warning("Sync probe failed (%s); retry in %ss", exc, self._delay)
                continue
            try:
                remote = await self._fetch_version()
                if remote is None:
                    self.degraded = True
                    self.last_sync_error = "sync_unavailable"
                    self._delay = min(self._delay * 2, self._max_backoff)
                    logger.warning("Sync 404; degrade, retry in %ss", self._delay)
                    continue
                cached = await self._cache.get_version()
                if remote == cached:
                    logger.debug("Cache still current (version=%s); skip write", remote)
                    self.version = remote
                    self._delay = float(self._interval)
                    continue
                logger.info("Cache changed: %s → %s; fetching payload", cached or self.version, remote)
                payload = await self._fetch_payload()
                if payload is None:
                    raise SyncUnavailable("fetch_failed")
                await self._cache.swap_generation(payload.to_generation(), remote)
                self.version = remote
                self.last_sync_at = _utcnow()
                self.last_sync_error = None
                self.degraded = False
                self._delay = float(self._interval)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_sync_error = str(exc)
                self._delay = min(self._delay * 2, self._max_backoff)
                logger.warning(
                    "Sync failed (%s); retry in %ss, keeping previous cache",
                    exc,
                    self._delay,
                )

    async def _acquire_lock(self) -> bool:
        return await self._cache.try_acquire_writer_lock(self._instance_id, self._lock_ttl)

    async def _probe_endpoints(self) -> bool:
        return await self._fetch_version() is not None

    async def _fetch_version(self) -> str | None:
        response = await self._http.get(f"{self._base}{_CHECK_VERSION_PATH}")
        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            raise SyncUnavailable(f"http_{response.status_code}")
        try:
            payload = response.json()
        except Exception as exc:
            raise SyncUnavailable("invalid_json") from exc
        data = unwrap_data(payload)
        if not isinstance(data, dict):
            raise SyncUnavailable("invalid_version")
        version = str(data.get("version") or "").strip()
        if not version:
            raise SyncUnavailable("missing_version")
        return version

    async def _fetch_payload(self) -> SyncPayload | None:
        response = await self._http.get(f"{self._base}{_BRANCHES_PATH}")
        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            raise SyncUnavailable(f"http_{response.status_code}")
        try:
            raw = response.json()
        except Exception as exc:
            raise SyncUnavailable("invalid_json") from exc
        return parse_sync_payload(raw)
