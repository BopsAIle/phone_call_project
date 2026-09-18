"""Build the `prompt` / `keywords` context the STT session is biased with.

The catalog already knows every dish this restaurant sells. Until we hand those
names to the transcription model, it is guessing them from sound alone — and a
non-native caller saying "Chicken Zinger Combo" gives it very little to go on.
`keywords` are hints, not forced output: the model only emits one when the audio
actually contains it.
"""

from __future__ import annotations

from typing import Any, Iterable

from stt.phonetic import strip_marks

# OpenAI publishes no hard cap. These are our own ceilings: a session.update that
# is rejected costs us the whole context, so stay well inside anything plausible.
MAX_KEYWORDS = 80
MAX_KEYWORD_CHARS = 40
# `prompt` is the only biasing channel on the gpt-4o-transcribe family, so the
# catalog goes in there as prose. Keep it short: no published limit, and a bloated
# prompt dilutes the names that matter.
MAX_PROMPT_CHARS = 800
MAX_PROMPT_NAMES = 40

# Each keyword must be a single-line literal without these characters.
_FORBIDDEN = str.maketrans({"<": None, ">": None, "\r": None, "\n": None})

# Words the model already knows cold. As keywords they only crowd out the rare
# ones that actually need the hint.
_TOO_COMMON = frozenset(
    {
        "combo", "set", "large", "small", "regular", "special", "fresh", "grilled",
        "fried", "chicken", "beef", "pork", "fish", "rice", "noodle", "noodles",
        "soup", "salad", "tea", "coffee", "juice", "water", "sauce", "cheese",
    }
)
# Below this length a word is rarely the one being misheard.
_RARE_WORD_MIN = 6


def _clean(raw: str) -> str:
    return " ".join((raw or "").translate(_FORBIDDEN).split())[:MAX_KEYWORD_CHARS]


def build_keywords(
    store_name: str = "",
    branches: Iterable[Any] | None = None,
    menu_items: Iterable[Any] | None = None,
    limit: int = MAX_KEYWORDS,
) -> list[str]:
    """Store, branches, then dishes — most specific to this call first.

    Each dish also contributes its rare words on their own ("Zinger" out of
    "Chicken Zinger Combo"): callers shorten names, and the rare word is exactly
    the one STT gets wrong.
    """
    out: list[str] = []
    seen: set[str] = set()

    def push(raw: str) -> None:
        """Add one keyword. Skipping a blank or a duplicate must not stop the rest."""
        if len(out) >= limit:
            return
        text = _clean(raw)
        if not text:
            return
        key = strip_marks(text).lower()
        if key in seen:
            return
        seen.add(key)
        out.append(text)

    push(store_name)
    for branch in branches or []:
        push(str(getattr(branch, "name", "") or ""))
    for item in menu_items or []:
        if len(out) >= limit:
            break
        name = str(getattr(item, "name", "") or "")
        push(name)
        for word in name.split():
            if len(word) >= _RARE_WORD_MIN and word.lower() not in _TOO_COMMON:
                push(word)
    return out[:limit]


def build_prompt(store_name: str = "", keywords: Iterable[str] | None = None) -> str:
    """Context about the recording, not an instruction to the model.

    OpenAI documents `prompt` as "free-form context about the recording" — telling
    it to "transcribe accurately" just burns tokens. The catalog names belong here
    for `gpt-4o-transcribe`, which has no `keywords` field; models that do take
    keywords get the same names through that channel as well.
    """
    name = _clean(store_name) or "a restaurant"
    text = (
        f"Phone call to the restaurant {name}. "
        "The caller books a table or orders food for pickup or delivery. "
        "The caller may be a non-native English speaker with a strong accent."
    )
    names = [item for item in (keywords or []) if item][:MAX_PROMPT_NAMES]
    if names:
        text += " Expect these branch and dish names: " + ", ".join(names) + "."
    if len(text) <= MAX_PROMPT_CHARS:
        return text
    # Trim whole names rather than cutting one in half mid-word.
    while names and len(text) > MAX_PROMPT_CHARS:
        names.pop()
        text = text[: text.index(" Expect these branch and dish names:")]
        if names:
            text += " Expect these branch and dish names: " + ", ".join(names) + "."
    return text[:MAX_PROMPT_CHARS]
