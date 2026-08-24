from datetime import date, time

from shared.models import BookingSlots, SlotDelta
from shared.slots import (
    apply_delta,
    has_availability_keys,
    missing_fields,
    normalize_branch,
    touches_availability_keys,
)


def test_missing_fields_order_multi_branch():
    slots = BookingSlots()
    assert missing_fields(slots, multi_branch=True) == [
        "customer_name",
        "phone",
        "guest_count",
        "date",
        "time",
        "branch",
    ]


def test_phone_from_caller_id_not_missing():
    slots = BookingSlots(phone="+84901234567")
    assert "phone" not in missing_fields(slots, multi_branch=True)


def test_single_branch_skips_branch():
    slots = BookingSlots(
        guest_count=2,
        date=date(2026, 8, 21),
        time=time(19, 0),
        customer_name="An",
        phone="0901111111",
    )
    assert missing_fields(slots, multi_branch=False) == []
    assert has_availability_keys(slots, multi_branch=False)


def test_availability_keys_need_branch_when_multi():
    slots = BookingSlots(guest_count=2, date=date(2026, 8, 21), time=time(19, 0))
    assert not has_availability_keys(slots, multi_branch=True)
    slots.branch = "quan-1"
    assert has_availability_keys(slots, multi_branch=True)


def test_normalize_branch_aliases():
    assert normalize_branch("Quận 1") == "quan-1"
    assert normalize_branch("thao dien") == "thao-dien"


def test_apply_delta_and_touch_keys():
    slots = BookingSlots()
    delta = SlotDelta(guest_count=4, branch="quan 1")
    assert touches_availability_keys(delta)
    updated = apply_delta(slots, delta)
    assert updated.guest_count == 4
    assert updated.branch == "quan-1"
    assert updated.source == "Phone AI"
