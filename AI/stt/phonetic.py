"""Phonetic fallback for non-native speech: match a mangled STT string to a catalog name.

STT hands us what the caller *sounded* like, not what they meant: "chicken singer
combo" for "Chicken Zinger Combo", "sesar salat" for "Caesar Salad". Text distance
alone does not bridge that, because the vowels are exactly what a non-native speaker
gets wrong. So we drop the vowels and fold consonants into classes (p/b, s/z, l/r,
k/g), then compare what is left.

Stdlib only, microseconds per call, deterministic — it runs before the LLM matcher
and keeps easy cases from ever costing a round trip.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any, Callable, Iterable

# Accept a phonetic hit only above this score, AND only when it beats the runner-up
# by this margin. Measured on the eval set in documents/stt-accuracy-playbook.md:
# every true hit scored >= 0.82, every non-menu phrase scored <= 0.67 ("hamburger"
# against "Cheeseburger" — they share a real substring, so no phonetic tweak fixes
# it; only the absolute floor does).
ACCEPT_SCORE = 0.75
ACCEPT_MARGIN = 0.20

_DIGRAPHS = [
    ("sch", "S"), ("tch", "S"), ("ph", "F"), ("th", "T"), ("ch", "S"),
    ("sh", "S"), ("ck", "K"), ("qu", "K"), ("ng", "N"), ("gh", "K"),
]
_CLASS = {
    "b": "P", "p": "P",
    "d": "T", "t": "T",
    "c": "K", "k": "K", "g": "K", "q": "K",
    "f": "F", "v": "F", "w": "F",
    "s": "S", "z": "S", "x": "S", "j": "S",
    "m": "N", "n": "N",
    "l": "L", "r": "L",
    "h": "", "y": "",
}
_VOWELS = set("aeiou")


def strip_marks(text: str) -> str:
    """'Jalapeño' -> 'Jalapeno'. An English menu still borrows accented names."""
    nfd = unicodedata.normalize("NFD", text or "")
    return "".join(ch for ch in nfd if unicodedata.category(ch) != "Mn")


def normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", strip_marks((text or "").lower())).strip()


def _drop_coda_glides(norm: str) -> str:
    """Non-rhotic + dropped codas: vowel + r/w/y -> vowel ('burger' ~ 'burga')."""
    return re.sub(r"([aeiou])[rwy]+", r"\1", norm)


def skeleton(text: str) -> str:
    """Consonant skeleton: digraphs first, then per-letter classes, vowels dropped."""
    norm = _drop_coda_glides(normalize(text).replace(" ", ""))
    for src, dst in _DIGRAPHS:
        norm = norm.replace(src, dst.lower() + "\x00")
    out: list[str] = []
    for ch in norm:
        if ch == "\x00" or ch in _VOWELS:
            continue
        out.append(ch if ch.isupper() else _CLASS.get(ch, ch.upper()))
    squashed: list[str] = []
    for ch in out:  # collapse doubles: "PP" -> "P"
        if ch and (not squashed or squashed[-1] != ch):
            squashed.append(ch)
    return "".join(squashed)


def similarity(spoken: str, name: str) -> float:
    """0..1. Text distance leads; the skeleton only *rescues* a bad spelling."""
    a_txt, b_txt = normalize(spoken), normalize(name)
    if not a_txt or not b_txt:
        return 0.0
    text_ratio = SequenceMatcher(None, a_txt, b_txt).ratio()
    a_sk, b_sk = skeleton(spoken), skeleton(name)
    if not a_sk or not b_sk:
        return text_ratio
    skel_ratio = SequenceMatcher(None, a_sk, b_sk).ratio()
    # A 2-class skeleton ("KN") collides with half the menu, so short skeletons
    # get little say; only names with real consonant structure can be rescued.
    short = min(len(a_sk), len(b_sk))
    weight = 0.0 if short < 3 else (0.45 if short < 4 else 0.6)
    return max(text_ratio, (1 - weight) * text_ratio + weight * skel_ratio)


def rank(
    spoken: str,
    items: Iterable[Any],
    key: Callable[[Any], str] = lambda item: getattr(item, "name", ""),
    top: int = 8,
) -> list[tuple[float, Any]]:
    """[(score, item)] sorted best first, capped at `top`."""
    scored = [(similarity(spoken, key(item)), item) for item in items]
    scored.sort(key=lambda row: row[0], reverse=True)
    return scored[:top]


def confident_pick(scored: list[tuple[float, Any]]) -> Any | None:
    """The one clear winner, or None when it is close enough to need arbitration.

    Only call this on an extracted name ("caesar salat"), never on a whole
    sentence — sentence-length input makes the skeletons collide.
    """
    if not scored or scored[0][0] < ACCEPT_SCORE:
        return None
    if len(scored) > 1 and scored[0][0] - scored[1][0] < ACCEPT_MARGIN:
        return None
    return scored[0][1]
