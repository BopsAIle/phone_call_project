from __future__ import annotations

import json

from booking.matcher import ScriptedBranchMatcher, coerce_match_result
from booking.models import Branch, MatchResult, Restaurant
from booking.tools import BookingTools, normalize_booking_date, normalize_booking_time, resolve_booking_when
from bridge.session import CallSession
from tests.fakes import FakeRestaurantClient

MINH_KHAI = Branch(id="mk", name="Chi nhánh Minh Khai", address="Minh Khai, Hà Nội")
BA_DINH = Branch(id="bd", name="Chi nhánh Ba Đình", address="Ba Đình, Hà Nội")
LONGWANG = Restaurant(
    id="rest-1",
    name="Nhà hàng LongWang",
    phone="1900636886",
    branches=[MINH_KHAI, BA_DINH],
)

_BOOKING_ARGS = {
    "customer_name": "Nguyễn Văn A",
    "phone_number": "0123456789",
    "party_size": 4,
    "booking_date": "2026-08-28",
    "booking_time": "19:30",
    "note": "Yêu cầu bàn gần cửa sổ",
}


def _session_with_catalog() -> CallSession:
    session = CallSession()
    session.apply_restaurant(LONGWANG)
    session.catalog_ready = True
    return session


def test_coerce_minh_khai_match() -> None:
    result = coerce_match_result(
        {
            "status": "match",
            "branch_id": "mk",
            "confidence": "high",
            "confirm_name": "Chi nhánh Minh Khai",
        },
        [MINH_KHAI, BA_DINH],
    )
    assert result.status == "match"
    assert result.branch_id == "mk"
    assert result.confidence == "high"


def test_coerce_unknown_store_is_none() -> None:
    result = coerce_match_result({"status": "none"}, [MINH_KHAI, BA_DINH])
    assert result.status == "none"
    assert result.branch_id == ""


def test_coerce_hallucinated_id_is_none() -> None:
    result = coerce_match_result(
        {"status": "match", "branch_id": "not-in-catalog", "confidence": "high"},
        [MINH_KHAI, BA_DINH],
    )
    assert result.status == "none"


def test_normalize_booking_time() -> None:
    assert normalize_booking_time("19:30") == "19:30"
    assert normalize_booking_time("9:05") == "09:05"
    assert normalize_booking_time("19:30:00") == "19:30"
    assert normalize_booking_time("7:30pm") == "19:30"
    assert normalize_booking_time("7:30 PM") == "19:30"
    assert normalize_booking_time("12:00 am") == "00:00"
    assert normalize_booking_time("99:00") is None


def test_normalize_booking_date_tomorrow() -> None:
    from datetime import datetime, timedelta, timezone as dt_timezone

    expected = (datetime.now(dt_timezone.utc).date() + timedelta(days=1)).isoformat()
    assert normalize_booking_date("tomorrow", "UTC") == expected
    assert normalize_booking_date("Tomorrow", "UTC") == expected
    assert normalize_booking_date("tommorw", "UTC") == expected
    assert normalize_booking_date("ngày mai", "UTC") == expected
    assert normalize_booking_date("mai", "UTC") == expected
    today = datetime.now(dt_timezone.utc).date().isoformat()
    assert normalize_booking_date("today", "UTC") == today
    assert normalize_booking_date("2026-09-04", "UTC") == "2026-09-04"
    assert normalize_booking_date("xyz", "UTC") is None


def test_resolve_booking_when_tomorrow_with_clock() -> None:
    from datetime import datetime, timedelta, timezone as dt_timezone

    expected = (datetime.now(dt_timezone.utc).date() + timedelta(days=1)).isoformat()
    date, time = resolve_booking_when("tomorrow", "7:30pm", "UTC")
    assert date == expected
    assert time == "19:30"
    date, time = resolve_booking_when("tomorrow 19:30", "", "UTC")
    assert date == expected
    assert time == "19:30"
    date, time = resolve_booking_when("", "tomorrow", "UTC")
    assert date == expected
    assert time is None


async def test_resolve_branch_locks_minh_khai() -> None:
    session = _session_with_catalog()
    matcher = ScriptedBranchMatcher(
        {
            "Minh Khai": MatchResult(
                status="match",
                branch_id="mk",
                confidence="high",
                confirm_name="Chi nhánh Minh Khai",
            )
        }
    )
    tools = BookingTools(session, FakeRestaurantClient(), matcher)
    payload = json.loads(await tools.execute("resolve_branch", json.dumps({"spoken_name": "Minh Khai"})))
    assert payload["status"] == "match"
    assert payload["locked"] is True
    assert payload["branch_id"] == "mk"
    assert session.selected_branch_id == "mk"
    assert session.selected_branch_name == "Chi nhánh Minh Khai"


async def test_resolve_branch_unknown_store_does_not_lock() -> None:
    session = _session_with_catalog()
    tools = BookingTools(session, FakeRestaurantClient(), ScriptedBranchMatcher())
    payload = json.loads(
        await tools.execute("resolve_branch", json.dumps({"spoken_name": "cửa hàng A"}))
    )
    assert payload["status"] == "none"
    assert payload["locked"] is False
    assert session.selected_branch_id == ""
    names = {row["name"] for row in payload["available_branches"]}
    assert "Chi nhánh Minh Khai" in names


async def test_resolve_branch_locks_when_llm_picks_quan_3_from_list() -> None:
    session = CallSession()
    session.apply_restaurant(
        Restaurant(
            id="rest-1",
            name="Nhà hàng LongWang",
            phone="1900636886",
            branches=[
                Branch(id="q1", name="Chi nhánh Quận 1", address="Quận 1"),
                Branch(id="q2", name="Chi nhánh Quận 2", address="Quận 2"),
                Branch(id="q3", name="Chi nhánh Quận 3", address="Quận 3"),
            ],
        )
    )
    session.catalog_ready = True
    matcher = ScriptedBranchMatcher(
        {
            "tôi muốn chọn chi nhánh quận 3": MatchResult(
                status="match",
                branch_id="q3",
                confidence="high",
                confirm_name="Chi nhánh Quận 3",
            )
        }
    )
    tools = BookingTools(session, FakeRestaurantClient(), matcher)
    payload = json.loads(
        await tools.execute(
            "resolve_branch",
            json.dumps({"spoken_name": "tôi muốn chọn chi nhánh quận 3"}),
        )
    )
    assert matcher.calls == ["tôi muốn chọn chi nhánh quận 3"]
    assert payload["status"] == "match"
    assert payload["locked"] is True
    assert payload["branch_id"] == "q3"
    assert session.selected_branch_id == "q3"
    assert session.selected_branch_name == "Chi nhánh Quận 3"


async def test_confirm_branch_rejects_unknown_id() -> None:
    session = _session_with_catalog()
    tools = BookingTools(session, FakeRestaurantClient(), ScriptedBranchMatcher())
    payload = json.loads(await tools.execute("confirm_branch", json.dumps({"branch_id": "invented"})))
    assert payload["ok"] is False
    assert payload["error"] == "unknown_branch"
    assert session.selected_branch_id == ""


async def test_create_booking_uses_ram_ids_and_phone_ai_source() -> None:
    session = _session_with_catalog()
    session.select_branch("mk")
    client = FakeRestaurantClient()
    tools = BookingTools(session, client, ScriptedBranchMatcher())
    hallucinated = {
        **_BOOKING_ARGS,
        "restaurant_id": "hallucinated-rest",
        "branch_id": "hallucinated-branch",
        "source": "website",
        "status": "pending",
    }
    payload = json.loads(await tools.execute("create_booking", json.dumps(hallucinated)))
    assert payload["ok"] is True
    assert len(client.created) == 1
    body = client.created[0]
    assert body["restaurant_id"] == "rest-1"
    assert body["branch_id"] == "mk"
    assert body["customer_name"] == "Nguyễn Văn A"
    assert body["customer_phone"] == "0123456789"
    assert body["party_size"] == 4
    assert body["booking_date"] == "2026-08-28"
    assert body["booking_time"] == "19:30"
    assert body["note"] == "Yêu cầu bàn gần cửa sổ"
    assert "status" not in body
    assert "source" not in body
    assert session.booking_created is True


async def test_create_booking_accepts_tomorrow() -> None:
    from datetime import datetime, timedelta, timezone as dt_timezone

    session = _session_with_catalog()
    session.select_branch("mk")
    session.timezone = "UTC"
    client = FakeRestaurantClient()
    tools = BookingTools(session, client, ScriptedBranchMatcher())
    payload = json.loads(
        await tools.execute(
            "create_booking",
            json.dumps({**_BOOKING_ARGS, "booking_date": "tomorrow"}),
        )
    )
    expected = (datetime.now(dt_timezone.utc).date() + timedelta(days=1)).isoformat()
    assert payload["ok"] is True
    assert payload["booking_date"] == expected
    assert client.created[0]["booking_date"] == expected


async def test_create_booking_rejects_without_branch() -> None:
    session = _session_with_catalog()
    client = FakeRestaurantClient()
    tools = BookingTools(session, client, ScriptedBranchMatcher())
    payload = json.loads(await tools.execute("create_booking", json.dumps(_BOOKING_ARGS)))
    assert payload == {"ok": False, "error": "no_branch"}
    assert client.created == []


async def test_create_booking_rejects_missing_restaurant() -> None:
    session = CallSession()
    session.restaurant_missing = True
    client = FakeRestaurantClient()
    tools = BookingTools(session, client, ScriptedBranchMatcher())
    payload = json.loads(await tools.execute("create_booking", json.dumps(_BOOKING_ARGS)))
    assert payload == {"ok": False, "error": "no_restaurant"}
    assert client.created == []
