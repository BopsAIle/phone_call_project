"""Gom transcript trong RAM rồi đẩy lên BE theo lô.

Vì sao không lấy thẳng `session.history`: nó lẫn JSON của tool, lời nhắc hệ thống, và
những câu model *định* nói nhưng bị ngắt trước khi ra loa. Thứ đáng lưu là thứ hai bên
thật sự đã nghe, nên transcript được nhặt ở hai chỗ:

- câu khách nói: khi STT chốt lượt
- câu AI nói: khi byte tiếng đầu tiên của câu đó **đã ra dây**

Mọi thao tác mạng chạy ở task nền và nuốt lỗi: cuộc gọi không bao giờ được chậm hay chết
vì việc ghi nhật ký.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"
ROLE_TOOL = "tool"

_MAX_CONTENT_CHARS = 8000  # cột text, nhưng đừng để một kết quả tool khổng lồ lọt vào
_BATCH_SIZE = 10
_FLUSH_SECONDS = 30.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class CallLogger:
    """Một bộ gom cho một cuộc gọi."""

    def __init__(
        self,
        client: Any,
        *,
        batch_size: int = _BATCH_SIZE,
        flush_seconds: float = _FLUSH_SECONDS,
    ) -> None:
        self._client = client
        self._batch_size = max(1, int(batch_size))
        self._flush_seconds = max(1.0, float(flush_seconds))
        self._record_id: str = ""
        self._pending: list[dict[str, Any]] = []
        self._sequence = 0
        self._started = False
        self._closed = False
        self._lock = asyncio.Lock()
        self._timer: Optional[asyncio.Task] = None
        self._tasks: set[asyncio.Task] = set()

    @property
    def record_id(self) -> str:
        return self._record_id

    @property
    def enabled(self) -> bool:
        return self._client is not None and not self._closed

    def start(self, body: dict[str, Any]) -> None:
        """Mở bản ghi ở task nền. Không chờ: lời chào không được đợi BE."""
        if not self.enabled or self._started:
            return
        self._started = True
        self._spawn(self._start_now(body))

    async def _start_now(self, body: dict[str, Any]) -> None:
        try:
            record_id = await self._client.start(body)
        except Exception:
            logger.warning("Không mở được bản ghi cuộc gọi", exc_info=True)
            return
        if not record_id:
            return
        self._record_id = record_id
        logger.info("Bản ghi cuộc gọi %s", record_id)
        # Những câu đã nói trước khi BE trả id vẫn nằm trong hàng đợi, đẩy luôn.
        await self._flush_if_due(force=False)

    def note(self, role: str, content: str, *, tool_name: str = "") -> None:
        if not self.enabled:
            return
        text = (content or "").strip()
        if not text:
            return
        if len(text) > _MAX_CONTENT_CHARS:
            text = text[:_MAX_CONTENT_CHARS] + "…"
        entry: dict[str, Any] = {
            "sequence": self._sequence,
            "role": role,
            "content": text,
            "spoken_at": _now_iso(),
        }
        if tool_name:
            entry["tool_name"] = tool_name[:100]
        self._sequence += 1
        self._pending.append(entry)
        self._arm_timer()
        if len(self._pending) >= self._batch_size:
            self._spawn(self._flush_if_due(force=True))

    def _arm_timer(self) -> None:
        if self._timer is not None and not self._timer.done():
            return
        self._timer = self._spawn(self._tick())

    async def _tick(self) -> None:
        try:
            await asyncio.sleep(self._flush_seconds)
        except asyncio.CancelledError:
            return
        await self._flush_if_due(force=True)

    async def _flush_if_due(self, *, force: bool) -> None:
        if not self.enabled or not self._record_id:
            return
        async with self._lock:
            if not self._pending:
                return
            if not force and len(self._pending) < self._batch_size:
                return
            batch, self._pending = self._pending, []
            try:
                ok = await self._client.append_messages(self._record_id, batch)
            except Exception:
                ok = False
                logger.warning("Đẩy transcript thất bại", exc_info=True)
            if not ok:
                # Trả lại đầu hàng đợi để lần cúp máy còn cơ hội gửi lại.
                self._pending = batch + self._pending

    async def finish(self, body: dict[str, Any]) -> None:
        """Chốt cuộc gọi: gửi nốt transcript còn lại cùng metadata kết thúc."""
        if not self.enabled:
            return
        self._closed = True
        if self._timer is not None and not self._timer.done():
            self._timer.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._timer
        for task in list(self._tasks):
            if task.done():
                continue
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await asyncio.wait_for(asyncio.shield(task), timeout=2)
        if not self._record_id:
            logger.info("Cuộc gọi kết thúc trước khi mở được bản ghi; bỏ %s lượt", len(self._pending))
            return
        payload = dict(body)
        if self._pending:
            payload["messages"] = self._pending
            self._pending = []
        try:
            await self._client.end(self._record_id, payload)
        except Exception:
            logger.warning("Chốt bản ghi cuộc gọi thất bại", exc_info=True)

    def _spawn(self, coro: Any) -> asyncio.Task:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task
