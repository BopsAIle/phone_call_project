"""Background catalog poller: Nest restaurants/branches/menu → Redis generation."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from booking.client import unwrap_data
from cache.redis_store import CatalogCache
from sync.models import SyncPayload, assemble_catalog

logger = logging.getLogger(__name__)

_RESTAURANTS_PATH = "/restaurants"
_BRANCHES_PATH = "/branches"
_DEFAULT_LOCK_TTL = 60

SleepFn = Callable[[float], Awaitable[None]]


class SyncUnavailable(Exception):
    """Backend catalog HTTP failed or payload không dùng được."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CatalogSyncer:
    """Background worker: GET list NestJS, ghi snapshot restaurant + menu vào Redis."""

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
            payload = await self._fetch_payload()
            if payload is None:
                self.degraded = True
                self.last_sync_error = "sync_unavailable"
                return False
            await self._commit(payload)
            return True
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.last_sync_error = str(exc)
            logger.warning("warm_once failed: %s", exc)
            return False

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
                        logger.info("Catalog endpoints available again; leaving degrade mode")
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self.last_sync_error = str(exc)
                    logger.warning("Catalog probe failed (%s); retry in %ss", exc, self._delay)
                continue
            try:
                payload = await self._fetch_payload()
                if payload is None:
                    self.degraded = True
                    self.last_sync_error = "sync_unavailable"
                    self._delay = min(self._delay * 2, self._max_backoff)
                    logger.warning("Catalog 404; degrade, retry in %ss", self._delay)
                    continue
                cached = await self._cache.get_version()
                if payload.version == cached:
                    logger.debug("Cache still current (version=%s); skip write", payload.version)
                    self.version = payload.version
                    self._delay = float(self._interval)
                    continue
                logger.info(
                    "Catalog changed: %s → %s; swapping Redis",
                    cached or self.version,
                    payload.version,
                )
                await self._commit(payload)
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

    async def _commit(self, payload: SyncPayload) -> None:
        await self._cache.swap_generation(payload.to_generation(), payload.version)
        self.version = payload.version
        self.degraded = False
        self.last_sync_at = _utcnow()
        self.last_sync_error = None
        self._delay = float(self._interval)
        logger.info(
            "Catalog synced version=%s hotlines=%s menus=%s",
            payload.version,
            len(payload.by_hotline),
            len(payload.menus),
        )

    async def _acquire_lock(self) -> bool:
        return await self._cache.try_acquire_writer_lock(self._instance_id, self._lock_ttl)

    async def _probe_endpoints(self) -> bool:
        restaurants = await self._fetch_list(_RESTAURANTS_PATH, required=True)
        return restaurants is not None

    async def _fetch_payload(self) -> SyncPayload | None:
        restaurants = await self._fetch_list(_RESTAURANTS_PATH, required=True)
        if restaurants is None:
            return None
        branches = await self._fetch_list(_BRANCHES_PATH, required=False) or []
        menus = await self._fetch_menus(branches)
        return assemble_catalog(restaurants, branches, menus)

    async def _fetch_menus(self, branches: list[Any]) -> dict[str, list[Any]]:
        ids: list[str] = []
        for branch in branches:
            if not isinstance(branch, dict):
                continue
            if str(branch.get("status") or "active").strip() != "active":
                continue
            branch_id = str(branch.get("id") or "").strip()
            if not branch_id:
                continue
            ids.append(branch_id)
        if not ids:
            return {}
        results = await asyncio.gather(*[self._fetch_menu_items(branch_id) for branch_id in ids])
        return {branch_id: items for branch_id, items in zip(ids, results)}

    async def _fetch_menu_items(self, branch_id: str) -> list[Any]:
        try:
            items = await self._fetch_list(f"/menu/branch/{branch_id}", required=False)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Menu fetch failed for branch %s: %s", branch_id, exc)
            return []
        return items or []

    async def _fetch_list(self, path: str, *, required: bool) -> list[Any] | None:
        response = await self._http.get(f"{self._base}{path}")
        if response.status_code == 404:
            return None if required else []
        if response.status_code >= 400:
            raise SyncUnavailable(f"http_{response.status_code}")
        try:
            payload = response.json()
        except Exception as exc:
            raise SyncUnavailable("invalid_json") from exc
        data = unwrap_data(payload)
        if data is None:
            return []
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return [data]
        raise SyncUnavailable("invalid_list")
