#!/usr/bin/env python3
"""Tóm tắt các dòng TURN trong log thành số liệu độ trễ.

    .venv/bin/python scripts/turn_stats.py app.log
    .venv/bin/python app.py 2>&1 | tee app.log      # rồi chạy lệnh trên
    .venv/bin/python scripts/turn_stats.py app.log --call abc123def456

Chỉ dùng thư viện chuẩn. Đọc được cả stdin:  ... | python scripts/turn_stats.py -

Con số đáng nhìn trước tiên là `first_audio_ms`: từ lúc khách ngừng nói đến lúc nghe
thấy tiếng. Mọi chỉ số khác chỉ giải thích vì sao nó lớn.
"""

from __future__ import annotations

import argparse
import re
import sys
from typing import Any, Iterator

TURN_RE = re.compile(r"\bTURN ((?:[\w.]+=\S+\s*)+)")
# Thứ tự hiển thị: đi từ đầu vào đến đầu ra, để đọc là thấy thời gian trôi đi đâu.
ORDER = [
    "stt_ms",
    "llm_ttft_ms",
    "llm_ttfs_ms",
    "tool_ms",
    "tts_ttfb_ms",
    "first_audio_ms",
    "llm_rounds",
    "prompt_tokens",
    "cached_tokens",
]


def parse_turns(lines: Iterator[str]) -> list[dict[str, Any]]:
    turns: list[dict[str, Any]] = []
    for line in lines:
        match = TURN_RE.search(line)
        if not match:
            continue
        row: dict[str, Any] = {}
        for pair in match.group(1).split():
            if "=" not in pair:
                continue
            key, _, value = pair.partition("=")
            try:
                row[key] = int(value)
            except ValueError:
                try:
                    row[key] = float(value)
                except ValueError:
                    row[key] = value
        if row:
            turns.append(row)
    return turns


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * pct)))
    return ordered[index]


def numeric_keys(turns: list[dict[str, Any]]) -> list[str]:
    keys = {k for row in turns for k, v in row.items() if isinstance(v, (int, float))}
    keys.discard("gen")
    ranked = [k for k in ORDER if k in keys]
    return ranked + sorted(keys - set(ranked))


def summarize(turns: list[dict[str, Any]]) -> None:
    if not turns:
        print("Không thấy dòng TURN nào. Log có được ghi ở mức INFO không?")
        return
    calls = {row.get("call") for row in turns if row.get("call")}
    print(f"{len(turns)} lượt nói trong {len(calls) or 1} cuộc gọi\n")
    header = f"{'chỉ số':<16}{'n':>5}{'trung vị':>11}{'p90':>9}{'p95':>9}{'max':>9}"
    print(header)
    print("-" * len(header))
    for key in numeric_keys(turns):
        values = [float(row[key]) for row in turns if isinstance(row.get(key), (int, float))]
        if not values:
            continue
        print(
            f"{key:<16}{len(values):>5}{percentile(values, 0.5):>11.0f}"
            f"{percentile(values, 0.9):>9.0f}{percentile(values, 0.95):>9.0f}{max(values):>9.0f}"
        )
    cached = [row for row in turns if "cached_tokens" in row]
    if cached:
        hits = sum(1 for row in cached if row["cached_tokens"] > 0)
        print(
            f"\nBộ nhớ đệm prompt trúng {hits}/{len(cached)} lượt."
            + ("  <- 0 nghĩa là việc tách prompt chưa xong" if hits == 0 else "")
        )


def detail(turns: list[dict[str, Any]], call: str) -> None:
    rows = [row for row in turns if str(row.get("call", "")) == call]
    if not rows:
        print(f"Không có lượt nào của cuộc gọi {call}")
        return
    for row in rows:
        bits = [f"{k}={row[k]}" for k in numeric_keys(rows) if k in row]
        tools = row.get("tools")
        if tools:
            bits.append(f"tools={tools}")
        print(f"  gen={row.get('gen', '-')}  " + "  ".join(bits))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("logfile", nargs="?", default="-", help="file log, hoặc - để đọc stdin")
    parser.add_argument("--call", default="", help="in chi tiết từng lượt của một cuộc gọi")
    args = parser.parse_args()

    if args.logfile == "-":
        turns = parse_turns(sys.stdin)
    else:
        with open(args.logfile, "r", encoding="utf-8", errors="replace") as handle:
            turns = parse_turns(handle)

    if args.call:
        detail(turns, args.call)
    else:
        summarize(turns)


if __name__ == "__main__":
    main()
