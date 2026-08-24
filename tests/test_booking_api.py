from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from apps.booking_api.main import app
from apps.booking_api.store import store

client = TestClient(app)
VN = ZoneInfo("Asia/Ho_Chi_Minh")


def _tomorrow():
    return datetime.now(VN).date() + timedelta(days=1)


def test_create_session_prefills_caller_id():
    response = client.post(
        "/v1/call-sessions",
        json={"call_sid": "CA123", "from_number": "+84901234567", "multi_branch": True},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["slots"]["phone"] == "+84901234567"
    assert body["slots"]["source"] == "Phone AI"
    assert body["call_sid"] == "CA123"


def test_patch_slots_and_availability_full():
    day = _tomorrow()
    store.occupancy[("quan-1", day.isoformat(), "19:00:00")] = 40
    session_id = client.post("/v1/call-sessions", json={"call_sid": "CA1"}).json()["id"]
    patched = client.patch(
        f"/v1/call-sessions/{session_id}/slots",
        json={"guest_count": 4, "date": day.isoformat(), "time": "19:00:00", "branch": "Quan 1"},
    )
    assert patched.status_code == 200
    assert patched.json()["session"]["slots"]["branch"] == "quan-1"

    avail = client.post(
        "/v1/availability/check",
        json={
            "session_id": session_id,
            "guest_count": 4,
            "date": day.isoformat(),
            "time": "19:00:00",
            "branch": "quan-1",
        },
    )
    assert avail.status_code == 200
    body = avail.json()
    assert body["available"] is False
    assert body["alternatives"]


def test_christmas_seed_is_full_without_date_patch():
    avail = client.post(
        "/v1/availability/check",
        json={
            "guest_count": 4,
            "date": "2026-12-24",
            "time": "19:00:00",
            "branch": "quan-1",
        },
    )
    assert avail.status_code == 200
    assert avail.json()["available"] is False


def test_create_booking_and_recording():
    day = _tomorrow()
    session_id = client.post(
        "/v1/call-sessions",
        json={"call_sid": "CA9", "from_number": "0909999999"},
    ).json()["id"]
    client.patch(
        f"/v1/call-sessions/{session_id}/slots",
        json={
            "guest_count": 2,
            "date": day.isoformat(),
            "time": "18:00:00",
            "branch": "quan-1",
            "customer_name": "Lan",
            "notes": "sinh nhat",
        },
    )
    rec = client.patch(
        "/v1/recordings/by-call/CA9",
        json={"recording_id": "RE123"},
    )
    assert rec.json()["recording_id"] == "RE123"

    created = client.post(
        "/v1/bookings",
        json={"session_id": session_id, "recording_id": "RE123"},
    )
    assert created.status_code == 200
    body = created.json()
    assert body["source"] == "Phone AI"
    assert body["recording_id"] == "RE123"
    assert body["id"].startswith("BK-")
    assert store.remaining("quan-1", day, time(18, 0)) == 38


def test_transfer_endpoint():
    session_id = client.post("/v1/call-sessions", json={"call_sid": "CA8"}).json()["id"]
    transferred = client.post(
        f"/v1/call-sessions/{session_id}/transfer",
        json={"reason": "guest_requested_human", "summary": "4 khach"},
    )
    assert transferred.json()["status"] == "transferred"
    assert transferred.json()["transfer_reason"] == "guest_requested_human"


def test_booking_rejected_when_missing_fields():
    session_id = client.post("/v1/call-sessions", json={"call_sid": "CA0"}).json()["id"]
    response = client.post("/v1/bookings", json={"session_id": session_id})
    assert response.status_code == 400
    assert "missing_fields" in response.json()["detail"]
