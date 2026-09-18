from __future__ import annotations

import logging

from obs.timing import (
    TurnTimer,
    add_ms,
    bump,
    format_record,
    mark_first,
    put_value,
    set_timer,
)
from scripts.turn_stats import parse_turns, percentile


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_marks_are_milliseconds_since_t0() -> None:
    clock = FakeClock()
    timer = TurnTimer("call-1", clock=clock)
    clock.advance(0.812)
    timer.first("stt_ms")
    clock.advance(0.430)
    timer.first("llm_ttft_ms")
    record = timer.record()
    assert record["call"] == "call-1"
    assert record["stt_ms"] == 812
    assert record["llm_ttft_ms"] == 1242


def test_earliest_mark_wins() -> None:
    clock = FakeClock()
    timer = TurnTimer(clock=clock)
    clock.advance(0.2)
    timer.first("tts_ttfb_ms")
    clock.advance(1.0)
    timer.first("tts_ttfb_ms")  # chunk thứ hai không được ghi đè
    assert timer.record()["tts_ttfb_ms"] == 200


def test_t0_can_be_the_moment_the_caller_stopped_speaking() -> None:
    clock = FakeClock()
    clock.advance(5.0)
    timer = TurnTimer(t0=100.0, clock=clock)
    timer.first("stt_ms")
    assert timer.record()["stt_ms"] == 5000


def test_sums_and_counts() -> None:
    timer = TurnTimer()
    timer.add("tool_ms", 120.4)
    timer.add("tool_ms", 300.2)
    timer.count("llm_rounds")
    timer.count("llm_rounds")
    record = timer.record()
    assert record["tool_ms"] == 421
    assert record["llm_rounds"] == 2


def test_missing_metrics_are_simply_absent() -> None:
    assert TurnTimer().record() == {}


def test_module_helpers_are_silent_without_a_timer() -> None:
    set_timer(None)
    mark_first("llm_ttft_ms")  # không được ném lỗi
    put_value("tools", "search_menu")
    add_ms("tool_ms", 5)
    bump("llm_rounds")


def test_module_helpers_reach_the_current_timer() -> None:
    clock = FakeClock()
    timer = TurnTimer(clock=clock)
    set_timer(timer)
    try:
        clock.advance(0.25)
        mark_first("llm_ttft_ms")
        put_value("tools", "search_menu,add_to_cart")
        bump("llm_rounds", 2)
        record = timer.record()
    finally:
        set_timer(None)
    assert record["llm_ttft_ms"] == 250
    assert record["tools"] == "search_menu,add_to_cart"
    assert record["llm_rounds"] == 2


def test_line_format_is_greppable_key_values() -> None:
    line = format_record({"call": "abc", "stt_ms": 812, "tools": "a,b"})
    assert line == "call=abc stt_ms=812 tools=a,b"


def test_spaces_never_break_the_key_value_format() -> None:
    assert format_record({"note": "hai tô phở"}) == "note=hai_tô_phở"


def test_emit_writes_one_turn_line(caplog) -> None:
    log = logging.getLogger("test.timing")
    timer = TurnTimer("abc")
    timer.put("stt_ms", 812)
    with caplog.at_level(logging.INFO, logger="test.timing"):
        timer.emit(log)
    assert len(caplog.records) == 1
    assert caplog.records[0].getMessage().startswith("TURN call=abc")


# --- script tổng hợp ---


def test_turn_stats_parses_the_line_the_pipeline_writes() -> None:
    lines = [
        "2026-09-18 10:00:00 INFO bridge.session: TURN call=abc gen=7 stt_ms=812 "
        "llm_ttft_ms=430 first_audio_ms=1104 llm_rounds=2 tools=search_menu,add_to_cart "
        "cached_tokens=3584",
        "một dòng log không liên quan",
        "TURN call=abc gen=8 stt_ms=700 first_audio_ms=980 llm_rounds=1 cached_tokens=0",
    ]
    turns = parse_turns(iter(lines))
    assert len(turns) == 2
    assert turns[0]["call"] == "abc"
    assert turns[0]["stt_ms"] == 812
    assert turns[0]["tools"] == "search_menu,add_to_cart"
    assert turns[1]["first_audio_ms"] == 980


def test_percentile_picks_a_real_sample() -> None:
    values = [100.0, 200.0, 300.0, 400.0, 500.0]
    assert percentile(values, 0.5) == 300.0
    assert percentile(values, 0.9) == 500.0
    assert percentile([], 0.5) == 0.0
