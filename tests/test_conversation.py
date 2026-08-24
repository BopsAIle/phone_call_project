from datetime import time

from apps.booking_api.store import store
from apps.voice_agent.extractor import fold_vi


async def test_happy_path_books_table(engine, tomorrow):
    start = await engine.start(call_sid="CA-happy", from_number="+84901234567")
    session_id = start.session.id
    assert start.action == "ask"
    assert start.session.slots.phone == "+84901234567"

    packed = (
        f"4 nguoi ngay mai 19 gio quan 1 ten Nguyen An"
    )
    result = await engine.handle_user_turn(session_id, packed)
    assert result.session.slots.guest_count == 4
    assert result.session.slots.date == tomorrow
    assert result.session.slots.time == time(19, 0)
    assert result.session.slots.branch == "quan-1"
    assert result.session.slots.customer_name == "Nguyen An"
    assert result.action == "confirm"
    assert "Nguyen An" in result.assistant_text

    booked = await engine.handle_user_turn(session_id, "chot giup em")
    assert booked.action == "booked"
    assert booked.booking_id
    assert booked.booking_id.startswith("BK-")


async def test_full_slot_suggests_alternatives_then_rebooks(engine, tomorrow):
    store.occupancy[("quan-1", tomorrow.isoformat(), "19:00:00")] = 40
    start = await engine.start(call_sid="CA-full", from_number="0902222333")
    session_id = start.session.id
    result = await engine.handle_user_turn(
        session_id,
        "4 nguoi ngay mai 19 gio quan 1 ten Lan",
    )
    assert result.action == "suggest_alternatives"
    assert result.availability is not None
    assert result.availability.available is False
    assert result.availability.alternatives

    follow = await engine.handle_user_turn(session_id, "18 gio")
    assert follow.session.slots.time == time(18, 0)
    assert follow.action == "confirm"

    booked = await engine.handle_user_turn(session_id, "duoc")
    assert booked.action == "booked"


async def test_transfer_when_guest_asks_for_staff(engine):
    start = await engine.start(call_sid="CA-staff", from_number="0901111111")
    result = await engine.handle_user_turn(start.session.id, "Cho toi gap nhan vien")
    assert result.action == "transfer"
    assert result.transfer_reason == "guest_requested_human"
    assert result.session.status == "transferred"
    assert "nhan vien" in fold_vi(result.assistant_text)


async def test_transfer_complex_event(engine):
    start = await engine.start(call_sid="CA-event", from_number="0901111112")
    result = await engine.handle_user_turn(
        start.session.id, "Toi muon dat tiec cuoi set menu 80 nguoi"
    )
    assert result.action == "transfer"
    assert result.transfer_reason in {"complex_event", "large_party"}


async def test_faq_hours_uses_rag_not_availability(engine):
    start = await engine.start(call_sid="CA-faq", from_number="0901111113")
    result = await engine.handle_user_turn(start.session.id, "Nha hang mo cua luc may gio?")
    assert result.action == "faq"
    assert result.rag_hits
    assert "11:00" in result.assistant_text
    assert result.availability is None


async def test_asks_one_missing_field_at_a_time(engine):
    start = await engine.start(call_sid="CA-step", from_number="0901111114")
    assert start.missing_fields[0] == "customer_name"
    assert "số máy" in start.assistant_text
    result = await engine.handle_user_turn(start.session.id, "ten Lan")
    assert result.action == "ask"
    assert result.session.slots.customer_name == "Lan"
    assert result.missing_fields[0] == "guest_count"
    assert "Lan" in result.assistant_text
    assert "người" in result.assistant_text.lower()


async def test_name_question_follows_party_already_given(engine):
    start = await engine.start(call_sid="CA-ack-name", from_number="0901111199")
    result = await engine.handle_user_turn(start.session.id, "4 nguoi ngay mai")
    assert result.session.slots.guest_count == 4
    assert result.missing_fields[0] == "customer_name"
    assert "4" in result.assistant_text
    assert "tên" in result.assistant_text
