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
    assert fallback_phrase("de") == fallback_phrase("en")
    assert fallback_phrase("vi") == fallback_phrase("en")
    assert fallback_phrase("fr") == fallback_phrase("en")


def test_system_prompt_uses_store_and_timezone() -> None:
    prompt = build_system_prompt(
        store_name="Bella Vista",
        timezone="Europe/Berlin",
        locale="de",
    )
    assert "Bella Vista" in prompt
    assert "Europe/Berlin" in prompt
    assert "Speak English only" in prompt
    assert "tomorrow" in prompt
    assert "Never speak Vietnamese" in prompt


def test_system_prompt_covers_booking_and_order_when_catalog_loaded() -> None:
    from booking.models import Branch

    prompt = build_system_prompt(
        store_name="LongWang",
        timezone="UTC",
        locale="vi",
        branches=[Branch(id="mk", name="Minh Khai")],
        catalog_loaded=True,
        cart_summary="2 Phở bò",
        fulfillment="delivery",
        delivery_address="12 Nguyen Trai",
    )
    assert "create_booking" in prompt
    assert "create_order" in prompt
    assert "search_menu" in prompt
    assert "list_menu" in prompt
    assert "2 Phở bò" in prompt
    assert "12 Nguyen Trai" in prompt
    assert "cash on delivery" in prompt
    assert "Do not read delivery fees" in prompt
    assert "save_order_details" in prompt
    assert "drop-off time" in prompt
    assert "pickup date" in prompt
    assert "recipient phone" in prompt


def test_system_prompt_asks_which_branch_when_unlocked() -> None:
    from booking.models import Branch

    prompt = build_system_prompt(
        store_name="LongWang",
        timezone="UTC",
        locale="vi",
        branches=[
            Branch(id="mk", name="Minh Khai", address="Minh Khai"),
            Branch(id="bd", name="Ba Đình", address="Ba Đình"),
        ],
        catalog_loaded=True,
        service_choice="3",
    )
    assert "Do not call search_menu" in prompt
    assert "In this same turn also ask which branch they want" in prompt
    assert "Do not ask for a branch first" not in prompt
    assert "names only" in prompt
    assert "district 3" in prompt


def test_system_prompt_skips_branch_question_for_a_sole_branch() -> None:
    from booking.models import Branch

    prompt = build_system_prompt(
        store_name="LongWang",
        timezone="UTC",
        locale="vi",
        branches=[Branch(id="mk", name="Minh Khai", address="Minh Khai")],
        catalog_loaded=True,
        service_choice="3",
    )
    assert "Do not ask for a branch first" in prompt
    assert "In this same turn also ask which branch they want" not in prompt


def test_system_prompt_keeps_address_for_followup_but_does_not_read_it() -> None:
    from booking.models import Branch

    prompt = build_system_prompt(
        store_name="LongWang",
        timezone="UTC",
        locale="vi",
        branches=[
            Branch(id="mk", name="Minh Khai", address="12 Nguyễn Trãi"),
            Branch(id="bd", name="Ba Đình", address="56 Liễu Giai"),
        ],
        catalog_loaded=True,
    )
    assert "names only" in prompt
    assert "NEVER read" in prompt
    assert "12 Nguyễn Trãi" in prompt
    assert "56 Liễu Giai" in prompt
    assert "HCM" in prompt
    assert "Ho Chi Minh" in prompt
    names_block, _, rest = prompt.partition("Branch names you may read aloud")
    assert "12 Nguyễn Trãi" not in names_block
    speakable, _, private = rest.partition("Internal addresses")
    assert "Minh Khai" in speakable
    assert "12 Nguyễn Trãi" not in speakable
    assert "12 Nguyễn Trãi" in private


def test_system_prompt_asks_booking_or_takeaway_when_intent_unknown() -> None:
    prompt = build_system_prompt(
        store_name="LongWang",
        timezone="UTC",
        locale="vi",
    )
    assert "book a table or order takeaway" in prompt
    assert "keypad menu" not in prompt


def test_system_prompt_awaiting_dtmf_does_not_ask_verbally() -> None:
    prompt = build_system_prompt(
        store_name="LongWang",
        timezone="UTC",
        locale="vi",
        awaiting_choice=True,
    )
    assert "hearing the keypad menu" in prompt
    assert "if the caller has not said what they want" not in prompt


def test_system_prompt_after_dtmf_booking_skips_service_question() -> None:
    prompt = build_system_prompt(
        store_name="LongWang",
        timezone="UTC",
        locale="vi",
        catalog_loaded=True,
        intent="booking",
        service_choice="1",
    )
    assert "key 1" in prompt
    assert "Do not ask again which service" in prompt
    assert "if the caller has not said what they want" not in prompt
    assert "book a table or order takeaway" not in prompt
    assert "Please say your name, address, phone number, and what you want for the table booking." in prompt
    assert "Do not ask for a branch first" in prompt


def test_system_prompt_dtmf_pickup_does_not_reask_fulfillment() -> None:
    prompt = build_system_prompt(
        store_name="LongWang",
        timezone="UTC",
        locale="vi",
        catalog_loaded=True,
        intent="order",
        service_choice="2",
        fulfillment="pickup",
    )
    assert "key 2" in prompt
    assert "Do not ask again whether this is delivery or pickup" in prompt
    assert "Fulfillment: pickup at the selected branch" in prompt
    assert "Please say your name, address, phone number, and what food you would like." in prompt
    assert "Do not ask for a branch first" in prompt


def test_system_prompt_does_not_reask_intent_when_booking() -> None:
    prompt = build_system_prompt(
        store_name="LongWang",
        timezone="UTC",
        locale="vi",
        intent="booking",
        catalog_loaded=True,
    )
    assert "The caller is currently booking a table." in prompt
    assert "if the caller has not said what they want" not in prompt
    assert "table-booking request" in prompt


def test_system_prompt_skips_intake_after_booking_created() -> None:
    prompt = build_system_prompt(
        store_name="LongWang",
        timezone="UTC",
        locale="vi",
        catalog_loaded=True,
        intent="booking",
        service_choice="1",
        booking_created=True,
    )
    assert "key 1" in prompt
    assert "Please say your name" not in prompt


def test_system_prompt_lists_missing_order_slots() -> None:
    prompt = build_system_prompt(
        store_name="LongWang",
        timezone="UTC",
        locale="vi",
        catalog_loaded=True,
        fulfillment="delivery",
        delivery_address="12 Nguyen Trai",
        order_status="Order details still missing: orderer name, orderer phone number. Ask next: ask for orderer name.",
    )
    assert "still missing: orderer name" in prompt
    assert "Ask next: ask for orderer name" in prompt
