"""HTTP client cho việc lưu trữ cuộc gọi.

POST /calls/ai/start · POST /calls/ai/{id}/messages · POST /calls/ai/{id}/end

Nguyên tắc xuyên suốt module này: **lưu trữ không bao giờ được làm hỏng cuộc gọi.** Mọi
hàm trả về None khi lỗi thay vì ném ra ngoài; BE sập thì cuộc gọi vẫn chạy, chỉ là không
có transcript.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from booking.client import unwrap_data

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://127.0.0.1:8070"
# Ngắn hơn hẳn 30 s của booking/order: đây là đường phụ, không ai chờ nó.
_DEFAULT_TIMEOUT = 5.0


class CallLogClient:
    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        *,
        timeout: float = _DEFAULT_TIMEOUT,
        http: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self._base = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self._owns_http = http is None
        self._http = http or httpx.AsyncClient(timeout=timeout)

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def start(self, body: dict[str, Any]) -> Optional[str]:
        """Trả về id bản ghi, hoặc None nếu không lưu được."""
        data = await self._post("/calls/ai/start", body)
        if not isinstance(data, dict):
            return None
        record_id = str(data.get("id") or "").strip()
        if not record_id:
            logger.warning("Call log start trả về payload không có id")
            return None
        return record_id

    async def append_messages(self, record_id: str, messages: list[dict[str, Any]]) -> bool:
        if not record_id or not messages:
            return False
        data = await self._post(f"/calls/ai/{record_id}/messages", {"messages": messages})
        return data is not None

    async def end(self, record_id: str, body: dict[str, Any]) -> bool:
        if not record_id:
            return False
        data = await self._post(f"/calls/ai/{record_id}/end", body)
        return data is not None

    async def _post(self, path: str, body: dict[str, Any]) -> Optional[Any]:
        url = f"{self._base}{path}"
        try:
            response = await self._http.post(url, json=body)
        except Exception as exc:
            logger.warning("Call log %s thất bại: %s", path, exc)
            return None
        if response.status_code >= 400:
            # Đọc cả thân lỗi: ValidationPipe của BE bật forbidNonWhitelisted, nên một
            # trường thừa cũng ra 400, và thông báo của nó chỉ đúng chỗ khi in ra.
            detail = ""
            try:
                detail = str(response.json())[:300]
            except Exception:
                detail = response.text[:300]
            logger.warning("Call log %s HTTP %s: %s", path, response.status_code, detail)
            return None
        try:
            return unwrap_data(response.json())
        except Exception:
            return {}
