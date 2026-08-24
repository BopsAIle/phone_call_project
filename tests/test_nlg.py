from datetime import timedelta

from shared.models import BookingSlots

from apps.voice_agent.nlg import opening_line, question_for


def test_opening_mentions_caller_id_when_phone_known():
    plain = opening_line()
    with_phone = opening_line(BookingSlots(phone="0901111114"))
    assert "tên" in plain
    assert with_phone != plain
    assert "số máy" in with_phone


def test_guest_count_question_uses_name():
    line = question_for("guest_count", slots=BookingSlots(customer_name="Lan", phone="0901"))
    assert "Lan" in line
    assert "người" in line


def test_name_question_acknowledges_party_already_given():
    line = question_for(
        "customer_name",
        slots=BookingSlots(guest_count=4),
    )
    assert "4" in line or "bàn" in line
    assert "tên" in line


def test_time_question_uses_tomorrow(today):
    tomorrow = today + timedelta(days=1)
    line = question_for(
        "time",
        slots=BookingSlots(guest_count=4, date=tomorrow, customer_name="Lan"),
    )
    assert "ngày mai" in line
    assert "4" in line


def test_time_question_picks_up_evening_from_user_text(today):
    tomorrow = today + timedelta(days=1)
    line = question_for(
        "time",
        slots=BookingSlots(guest_count=2, date=tomorrow),
        last_user_text="hai nguoi toi mai",
    )
    assert "buổi tối" in line


def test_branch_question_uses_datetime(today):
    from datetime import time

    line = question_for(
        "branch",
        slots=BookingSlots(guest_count=2, date=today, time=time(19, 0)),
    )
    assert "19:00" in line
    assert "Quận 1" in line
    assert "Thảo Điền" in line


def test_birthday_note_changes_party_question():
    line = question_for(
        "guest_count",
        slots=BookingSlots(customer_name="Lan", notes="sinh nhat"),
    )
    assert "nhân dịp" in line
    assert "người" in line
