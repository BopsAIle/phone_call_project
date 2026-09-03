"""Client for the restaurant server.

The endpoint **files a request** for staff to act on; it does not reserve a table
or accept an order. A human calls the customer back to confirm availability.
Nothing here may be described to the caller as a confirmation.

Because a duplicate is a staff notification seen twice rather than a double
booking, a single retry is safe. Send the idempotency key anyway where the
server honours it.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional, Protocol

import httpx

logger = logging.getLogger(__name__)

# Change these two lines when the endpoint's real routes are known.
PATHS = {"booking": "/bookings", "delivery": "/delivery-orders"}

RETRYABLE_STATUS = frozenset({408, 429, 500, 502, 503, 504})


class StoreApiValidationError(Exception):
    """4xx. The server rejected the content; the model can fix it and retry."""


class StoreApiUncertain(Exception):
    """Timeout or 5xx after a retry. It may or may not have landed.

    The agent must claim neither success nor failure to the caller.
    """


class StoreApi(Protocol):
    async def submit_request(
        self,
        kind: str,
        payload: dict[str, Any],
        *,
        idempotency_key: str,
        call_id: str,
    ) -> dict[str, Any]:
        ...


class StubStoreApi:
    """In-memory stand-in. Records submissions so tests can assert on them."""

    def __init__(self, fail_with: Optional[Exception] = None, delay: float = 0.0) -> None:
        self.submitted: list[dict[str, Any]] = []
        self.fail_with = fail_with
        self.delay = delay

    async def submit_request(
        self,
        kind: str,
        payload: dict[str, Any],
        *,
        idempotency_key: str,
        call_id: str,
    ) -> dict[str, Any]:
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail_with is not None:
            raise self.fail_with
        self.submitted.append(
            {
                "kind": kind,
                "payload": payload,
                "idempotency_key": idempotency_key,
                "call_id": call_id,
            }
        )
        return {"request_id": f"stub-{len(self.submitted)}", "status": "pending_staff_callback"}


class HttpStoreApi:
    def __init__(
        self,
        base_url: str,
        token: str = "",
        timeout: float = 5.0,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._timeout = timeout
        self._transport = transport  # test seam

    async def submit_request(
        self,
        kind: str,
        payload: dict[str, Any],
        *,
        idempotency_key: str,
        call_id: str,
    ) -> dict[str, Any]:
        path = PATHS.get(kind)
        if path is None:
            raise StoreApiValidationError(f"unknown request kind {kind!r}")
        headers = {"Idempotency-Key": idempotency_key}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        body = {"callId": call_id, **payload}

        last_error: Exception = StoreApiUncertain("no attempt made")
        async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
            # One retry only, and only for outcomes that are ambiguous anyway.
            for attempt in (1, 2):
                try:
                    response = await client.post(self._base_url + path, json=body, headers=headers)
                except httpx.TimeoutException as exc:
                    last_error = StoreApiUncertain(f"timeout: {exc}")
                except httpx.HTTPError as exc:
                    last_error = StoreApiUncertain(f"transport: {exc}")
                else:
                    if response.status_code < 400:
                        return _decode(response)
                    if response.status_code in RETRYABLE_STATUS:
                        last_error = StoreApiUncertain(f"status {response.status_code}")
                    else:
                        raise StoreApiValidationError(
                            f"status {response.status_code}: {response.text[:200]}"
                        )
                if attempt == 1:
                    logger.warning("store api attempt 1 failed callId=%s (%s)", call_id, last_error)
                    await asyncio.sleep(0.25)
        raise last_error


def _decode(response: httpx.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError:
        return {"status": "accepted"}
    return data if isinstance(data, dict) else {"status": "accepted", "response": data}
