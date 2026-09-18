"""Đo độ trễ từng chặng của một lượt nói, ghi ra một dòng log duy nhất.

Trước module này không có gì đo được: cả repo chỉ có ba chỗ gọi `time.monotonic()` và
không chỗ nào đo pipeline. Nghĩa là không ai trả lời được "một lượt mất bao lâu" hay
"sửa xong có nhanh hơn không".

Hai quyết định đáng nói:

- **Package lá, không import gì trong repo.** `bridge` đã gọi `llm`; nếu `llm` gọi ngược
  lại `bridge` là vòng tròn import. `obs/` không phụ thuộc ai nên mọi tầng dùng được.
- **Truyền bằng `contextvars`, không sửa chữ ký hàm.** Giá trị của ContextVar được sao
  sang task con lúc `create_task`, nên đồng hồ đặt trong `_run_reply` tự nhìn thấy được
  từ các task TTS mà `TurnPlayer` sinh ra. Không phải luồn tham số qua bốn tầng, và các
  fake trong test không phải đổi gì.
"""

from __future__ import annotations

import time
from contextvars import ContextVar
from typing import Any, Callable, Optional

_current: ContextVar[Optional["TurnTimer"]] = ContextVar("turn_timer", default=None)


class TurnTimer:
    def __init__(
        self,
        tag: str = "",
        *,
        t0: Optional[float] = None,
        clock: Callable[[], float] = time.monotonic,
        fields: Optional[dict[str, Any]] = None,
    ) -> None:
        self._clock = clock
        self.t0 = t0 if t0 is not None else clock()
        self.tag = tag
        self._marks: dict[str, float] = {}
        self._values: dict[str, Any] = dict(fields or {})
        self._sums: dict[str, float] = {}
        self._counts: dict[str, int] = {}

    # --- ghi nhận ---

    def first(self, name: str) -> None:
        """Mốc sớm nhất thắng: chặng nào cũng chỉ quan tâm lần đầu tiên."""
        if name not in self._marks:
            self._marks[name] = (self._clock() - self.t0) * 1000.0

    def put(self, name: str, value: Any) -> None:
        self._values[name] = value

    def add(self, name: str, ms: float) -> None:
        self._sums[name] = self._sums.get(name, 0.0) + ms

    def count(self, name: str, n: int = 1) -> None:
        self._counts[name] = self._counts.get(name, 0) + n

    def elapsed_ms(self) -> float:
        return (self._clock() - self.t0) * 1000.0

    # --- đọc ra ---

    def record(self) -> dict[str, Any]:
        """Thuần, không phụ thuộc log — đây là thứ test kiểm tra."""
        out: dict[str, Any] = {}
        if self.tag:
            out["call"] = self.tag
        out.update(self._values)
        for name, ms in self._marks.items():
            out[name] = round(ms)
        for name, ms in self._sums.items():
            out[name] = round(ms)
        out.update(self._counts)
        return out

    def emit(self, log: Any) -> None:
        record = self.record()
        if not record:
            return
        log.info("TURN %s", format_record(record))


def format_record(record: dict[str, Any]) -> str:
    """k=v cách nhau bằng khoảng trắng — grep được, script bóc được, không cần JSON."""
    parts = []
    for key, value in record.items():
        text = str(value)
        if " " in text:
            text = text.replace(" ", "_")
        parts.append(f"{key}={text}")
    return " ".join(parts)


# --- API cấp module: no-op khi không có đồng hồ nào đang chạy ---


def set_timer(timer: Optional[TurnTimer]) -> Any:
    return _current.set(timer)


def get_timer() -> Optional[TurnTimer]:
    return _current.get()


def mark_first(name: str) -> None:
    timer = _current.get()
    if timer is not None:
        timer.first(name)


def put_value(name: str, value: Any) -> None:
    timer = _current.get()
    if timer is not None:
        timer.put(name, value)


def add_ms(name: str, ms: float) -> None:
    timer = _current.get()
    if timer is not None:
        timer.add(name, ms)


def bump(name: str, n: int = 1) -> None:
    timer = _current.get()
    if timer is not None:
        timer.count(name, n)
