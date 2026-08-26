from __future__ import annotations

from llm.stream import SentenceAggregator, build_system_prompt, fallback_phrase


def test_flush_on_period_with_lookahead() -> None:
    agg = SentenceAggregator()
    assert agg.push("Hello.") == []
    assert agg.push(" Next") == ["Hello."]
    assert agg.flush() == "Next"


def test_does_not_flush_on_comma() -> None:
    agg = SentenceAggregator()
    assert agg.push("Hello, there, friend") == []
    assert agg.flush() == "Hello, there, friend"


def test_question_exclaim_ellipsis_newline() -> None:
    agg = SentenceAggregator()
    assert agg.push("Ready?") == []
    assert agg.push(" Go!") == ["Ready?"]
    assert agg.push(" Wait…")[0] == "Go!"
    assert agg.push("\nMore")[0] == "Wait…"
    assert agg.flush() == "More"


def test_fallback_locale() -> None:
    assert "again" in fallback_phrase("en").lower()
    assert "wiederholen" in fallback_phrase("de").lower()
    assert fallback_phrase("fr") == fallback_phrase("en")


def test_system_prompt_uses_store_and_timezone() -> None:
    prompt = build_system_prompt(
        store_name="Bella Vista",
        timezone="Europe/Berlin",
        locale="de",
    )
    assert "Bella Vista" in prompt
    assert "Europe/Berlin" in prompt
    assert "de" in prompt
    assert "tonight" in prompt
