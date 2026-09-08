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
    assert "tối nay" in prompt
    assert "tomorrow" in prompt


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
    assert "tiền mặt khi nhận" in prompt
    assert "Không đọc phí giao hàng" in prompt
    assert "save_order_details" in prompt
    assert "giờ nhận hàng" in prompt
    assert "ngày lấy món" in prompt
    assert "số điện thoại người nhận" in prompt


def test_system_prompt_asks_branch_before_menu_when_unlocked() -> None:
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
    )
    assert "Không gọi search_menu" in prompt
    assert "hỏi trước chi nhánh" in prompt
    assert "chỉ đọc tên" in prompt
    assert "đọc tên và địa chỉ đang hoạt động" not in prompt
    assert "quận 3" in prompt


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
    assert "chỉ đọc tên" in prompt
    assert "CẤM đọc" in prompt
    assert "12 Nguyễn Trãi" in prompt
    assert "56 Liễu Giai" in prompt
    assert "chỉ tên và địa chỉ" not in prompt
    assert "HCM" in prompt
    assert "Hồ Chí Minh" in prompt
    names_block, _, rest = prompt.partition("Tên chi nhánh được phép đọc")
    assert "12 Nguyễn Trãi" not in names_block
    speakable, _, private = rest.partition("Địa chỉ nội bộ")
    assert "Minh Khai" in speakable
    assert "12 Nguyễn Trãi" not in speakable
    assert "12 Nguyễn Trãi" in private


def test_system_prompt_asks_booking_or_takeaway_when_intent_unknown() -> None:
    prompt = build_system_prompt(
        store_name="LongWang",
        timezone="UTC",
        locale="vi",
    )
    assert "bạn muốn đặt bàn hay mang về" in prompt
    assert "Không mở đầu bằng câu hỏi lựa chọn" not in prompt
    assert "menu phím" not in prompt


def test_system_prompt_awaiting_dtmf_does_not_ask_verbally() -> None:
    prompt = build_system_prompt(
        store_name="LongWang",
        timezone="UTC",
        locale="vi",
        awaiting_choice=True,
    )
    assert "đang nghe menu phím" in prompt
    assert "nếu khách chưa nói rõ muốn gì" not in prompt


def test_system_prompt_after_dtmf_booking_skips_service_question() -> None:
    prompt = build_system_prompt(
        store_name="LongWang",
        timezone="UTC",
        locale="vi",
        catalog_loaded=True,
        intent="booking",
        service_choice="1",
    )
    assert "phím 1" in prompt
    assert "Không hỏi lại loại dịch vụ" in prompt
    assert "nếu khách chưa nói rõ muốn gì" not in prompt
    assert "bạn muốn đặt bàn hay mang về" not in prompt


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
    assert "phím 2" in prompt
    assert "Không hỏi lại giao hàng hay mang về" in prompt
    assert "Hình thức: đến lấy tại chi nhánh" in prompt


def test_system_prompt_does_not_reask_intent_when_booking() -> None:
    prompt = build_system_prompt(
        store_name="LongWang",
        timezone="UTC",
        locale="vi",
        intent="booking",
        catalog_loaded=True,
    )
    assert "Người gọi hiện đang đặt bàn." in prompt
    assert "nếu khách chưa nói rõ muốn gì" not in prompt


def test_system_prompt_lists_missing_order_slots() -> None:
    prompt = build_system_prompt(
        store_name="LongWang",
        timezone="UTC",
        locale="vi",
        catalog_loaded=True,
        fulfillment="delivery",
        delivery_address="12 Nguyen Trai",
        order_status="Thông tin đơn còn thiếu: tên người đặt, số điện thoại người đặt. Hỏi tiếp: hỏi tên người đặt.",
    )
    assert "còn thiếu: tên người đặt" in prompt
    assert "Hỏi tiếp: hỏi tên người đặt" in prompt
