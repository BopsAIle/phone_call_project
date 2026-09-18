"""Keyword/prompt context handed to the STT session, and the payload it produces."""

from __future__ import annotations

from stt.context import MAX_KEYWORDS, MAX_PROMPT_CHARS, build_keywords, build_prompt
from stt.realtime import RealtimeTranscriptionClient


class _Named:
    def __init__(self, name: str) -> None:
        self.name = name


def test_store_branches_then_dishes():
    keywords = build_keywords(
        "Downtown Grill",
        [_Named("Riverside"), _Named("Airport")],
        [_Named("Caesar Salad")],
    )
    assert keywords[:3] == ["Downtown Grill", "Riverside", "Airport"]
    assert "Caesar Salad" in keywords


def test_rare_words_get_their_own_hint():
    """Callers shorten names, and the rare word is the one STT gets wrong."""
    keywords = build_keywords(menu_items=[_Named("Chicken Zinger Combo")])
    assert "Chicken Zinger Combo" in keywords
    assert "Zinger" in keywords
    # "chicken" and "combo" are words the model already knows cold.
    assert "Chicken" not in keywords
    assert "Combo" not in keywords


def test_forbidden_characters_and_duplicates_are_dropped():
    keywords = build_keywords(
        "A<B>C",
        [_Named("Riverside"), _Named("riverside")],
        [_Named("")],
    )
    assert keywords[0] == "ABC"
    assert keywords.count("Riverside") == 1
    assert "" not in keywords


def test_keyword_ceiling_is_respected():
    items = [_Named(f"Dish Number {n} Speciality") for n in range(200)]
    assert len(build_keywords("Store", menu_items=items)) == MAX_KEYWORDS


def test_prompt_describes_the_recording_not_a_command():
    prompt = build_prompt("Downtown Grill")
    assert "Downtown Grill" in prompt
    assert "transcribe" not in prompt.lower()


def test_prompt_carries_the_catalog_for_models_without_keywords():
    """gpt-4o-transcribe has no `keywords` field; the prompt is the only channel."""
    prompt = build_prompt("Downtown Grill", ["Chicken Zinger Combo", "Caesar Salad"])
    assert "Chicken Zinger Combo" in prompt
    assert "Caesar Salad" in prompt


def test_prompt_stays_within_its_ceiling():
    names = [f"Dish Number {n} Speciality" for n in range(80)]
    prompt = build_prompt("Store", names)
    assert len(prompt) <= MAX_PROMPT_CHARS
    # Whole names only — never a name cut in half.
    listed = prompt.split("names: ", 1)[1].rstrip(".").split(", ")
    assert all(item in names for item in listed)


def test_old_model_still_receives_the_prompt():
    client = RealtimeTranscriptionClient(None, "gpt-4o-transcribe")
    client._prompt = "Phone call. Expect these branch and dish names: Caesar Salad."
    transcription = client._session_payload()["audio"]["input"]["transcription"]
    assert "Caesar Salad" in transcription["prompt"]
    assert "keywords" not in transcription


def _payload(model: str, **kwargs):
    client = RealtimeTranscriptionClient(None, model, **kwargs)
    return client, client._session_payload()["audio"]["input"]["transcription"]


def test_new_model_sends_languages_never_language():
    """The API rejects a payload carrying both."""
    _, transcription = _payload("gpt-live-transcribe")
    assert transcription["languages"] == ["en"]
    assert "language" not in transcription


def test_old_model_falls_back_to_singular_language():
    _, transcription = _payload("gpt-4o-transcribe")
    assert transcription["language"] == "en"
    assert "languages" not in transcription
    assert "keywords" not in transcription


def test_keywords_reach_the_payload_after_a_context_update():
    client = RealtimeTranscriptionClient(None, "gpt-live-transcribe")
    client._prompt = "Phone call to the restaurant Downtown Grill."
    client._keywords = ["Caesar Salad"]
    transcription = client._session_payload()["audio"]["input"]["transcription"]
    assert transcription["keywords"] == ["Caesar Salad"]
    assert transcription["prompt"].startswith("Phone call")


def test_rejected_field_is_dropped_from_later_payloads():
    """One unsupported hint must not cost us transcription for the whole call."""
    client = RealtimeTranscriptionClient(None, "gpt-live-transcribe")
    client._keywords = ["Caesar Salad"]
    client._unsupported.add("delay")
    transcription = client._session_payload()["audio"]["input"]["transcription"]
    assert "delay" not in transcription
    assert transcription["keywords"] == ["Caesar Salad"]


def test_custom_language_list_is_honoured():
    _, transcription = _payload("gpt-live-transcribe", languages=("en", "de"))
    assert transcription["languages"] == ["en", "de"]


async def test_update_context_without_connection_still_stores_values():
    client = RealtimeTranscriptionClient(None, "gpt-live-transcribe")
    await client.update_context(prompt="ctx", keywords=["Zinger"])
    assert client._keywords == ["Zinger"]
    assert client._prompt == "ctx"
