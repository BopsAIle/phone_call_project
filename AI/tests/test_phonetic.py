"""The phonetic net: what a non-native caller sounds like vs what the menu says."""

from __future__ import annotations

import pytest

from stt.phonetic import ACCEPT_SCORE, confident_pick, rank, similarity, skeleton, strip_marks

MENU = [
    "Chicken Zinger Combo",
    "Spring Rolls",
    "Iced Lemon Tea",
    "Grilled Pork Chop",
    "Beef Noodle Soup",
    "Fried Chicken Wings",
    "Caesar Salad",
    "Peach Tea",
    "Cheeseburger",
    "French Fries",
    "Mushroom Risotto",
    "Vanilla Milkshake",
]


class _Item:
    def __init__(self, name: str) -> None:
        self.id = name.lower().replace(" ", "-")
        self.name = name


ITEMS = [_Item(name) for name in MENU]


def test_strip_marks():
    assert strip_marks("Jalapeño") == "Jalapeno"


def test_vowels_do_not_decide():
    """The whole point: the consonant frame survives what the vowels lose."""
    assert skeleton("chicken singer combo") == skeleton("Chicken Zinger Combo")


@pytest.mark.parametrize(
    "spoken,expected",
    [
        ("chicken singer combo", "Chicken Zinger Combo"),
        ("sprink rol", "Spring Rolls"),
        ("ice lemon tee", "Iced Lemon Tea"),
        ("gril pork chop", "Grilled Pork Chop"),
        ("beef nudel sup", "Beef Noodle Soup"),
        ("fry chicken wing", "Fried Chicken Wings"),
        ("sesar salat", "Caesar Salad"),
        ("peach t", "Peach Tea"),
        ("chis burger", "Cheeseburger"),
        ("french fry", "French Fries"),
        ("mushroom risoto", "Mushroom Risotto"),
        ("vanila mil sek", "Vanilla Milkshake"),
    ],
)
def test_accented_spelling_still_picks_the_right_dish(spoken: str, expected: str) -> None:
    picked = confident_pick(rank(spoken, ITEMS))
    assert picked is not None, f"{spoken!r} fell through to the LLM"
    assert picked.name == expected


@pytest.mark.parametrize(
    "spoken",
    ["pizza", "coca cola", "table for four", "do you have pho", "hello can you hear me"],
)
def test_nothing_is_invented_for_off_menu_speech(spoken: str) -> None:
    assert confident_pick(rank(spoken, ITEMS)) is None


def test_hamburger_does_not_become_cheeseburger():
    """They share a real substring, so only the absolute floor stops this one."""
    assert similarity("hamburger", "Cheeseburger") < ACCEPT_SCORE
    assert confident_pick(rank("hamburger", ITEMS)) is None


def test_near_tie_defers_instead_of_guessing():
    items = [_Item("Peach Tea"), _Item("Peach Tee")]
    assert confident_pick(rank("peach tea", items)) is None


def test_rank_is_capped_and_ordered():
    scored = rank("caesar salad", ITEMS, top=3)
    assert len(scored) == 3
    assert scored[0][1].name == "Caesar Salad"
    assert scored[0][0] >= scored[1][0] >= scored[2][0]


def test_empty_input_scores_zero():
    assert similarity("", "Caesar Salad") == 0.0
    assert confident_pick(rank("", ITEMS)) is None
