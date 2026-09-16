"""Thin async client for the Telnyx Call Control v2 commands this bridge issues."""

from __future__ import annotations

import base64
import json
import logging
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

DEFAULT_API_BASE = "https://api.telnyx.com/v2"


def encode_client_state(payload: dict[str, Any]) -> str:
    """Telnyx round-trips client_state, but only as base64."""
    return base64.b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode()


def decode_client_state(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        return json.loads(base64.b64decode(raw).decode())
    except Exception:
        return {}


class TelnyxClient:
    """Answer, stream, and hang up calls. One client per process."""

    def __init__(
        self,
        api_key: str,
        *,
        api_base: str = DEFAULT_API_BASE,
        timeout: float = 10.0,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self._timeout = timeout
        self._client = client
        self._owns_client = client is None

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def _command(self, call_control_id: str, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not call_control_id:
            raise ValueError("call_control_id is required")
        url = f"{self.api_base}/calls/{call_control_id}/actions/{action}"
        http = await self._http()
        response = await http.post(
            url,
            json={k: v for k, v in payload.items() if v is not None},
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
        )
        if response.status_code >= 400:
            # A hangup on an already-dead call is normal; do not shout about it.
            level = logging.INFO if response.status_code == 422 else logging.ERROR
            logger.log(level, "Telnyx %s failed status=%s body=%s", action, response.status_code, response.text[:400])
            response.raise_for_status()
        try:
            return response.json()
        except Exception:
            return {}

    async def answer(self, call_control_id: str, *, client_state: str | None = None) -> dict[str, Any]:
        return await self._command(call_control_id, "answer", {"client_state": client_state})

    async def start_streaming(
        self,
        call_control_id: str,
        *,
        stream_url: str,
        stream_track: str = "inbound_track",
        stream_codec: str = "L16",
        bidirectional_mode: str = "rtp",
        bidirectional_codec: str = "L16",
        bidirectional_sampling_rate: int = 16000,
        client_state: str | None = None,
    ) -> dict[str, Any]:
        return await self._command(
            call_control_id,
            "streaming_start",
            {
                "stream_url": stream_url,
                "stream_track": stream_track,
                "stream_codec": stream_codec,
                "stream_bidirectional_mode": bidirectional_mode,
                "stream_bidirectional_codec": bidirectional_codec,
                "stream_bidirectional_sampling_rate": bidirectional_sampling_rate,
                "client_state": client_state,
            },
        )

    async def hangup(self, call_control_id: str, *, client_state: str | None = None) -> dict[str, Any]:
        return await self._command(call_control_id, "hangup", {"client_state": client_state})

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
        self._client = None
