"""Bước 3: giả lập một cuộc gọi đến — ký và bắn 3 webhook theo đúng thứ tự thật.

Chạy:  python place_call.py
       python place_call.py --tamper    (thử sửa body sau khi ký -> phải bị 401)
"""

from __future__ import annotations

import argparse
import base64
import json
import time
from pathlib import Path
from typing import Any

import httpx
from nacl.signing import SigningKey

WEBHOOK_URL = "http://127.0.0.1:8080/telnyx/webhook"
CALL_CONTROL_ID = "v3:demo-call-abc123"

PRIVATE_KEY = json.loads(Path(__file__).with_name("demo_keys.json").read_text())["private_key"]


def sign_and_post(event_type: str, payload: dict[str, Any], *, tamper: bool = False) -> None:
    """Đóng gói envelope đúng hình dạng Telnyx, ký, rồi POST."""
    envelope = {"data": {"event_type": event_type, "id": "evt-demo", "payload": payload}}
    # Quan trọng: ký trên ĐÚNG chuỗi byte sẽ gửi đi. Serialize lại một lần nữa
    # sau khi ký là nguồn lỗi chữ ký kinh điển (dấu cách, thứ tự key đổi).
    body = json.dumps(envelope, separators=(",", ":")).encode()
    timestamp = str(int(time.time()))

    signing_key = SigningKey(base64.b64decode(PRIVATE_KEY))
    signature = signing_key.sign(f"{timestamp}|".encode() + body).signature

    if tamper:
        # Kẻ tấn công chen vào giữa, đổi nội dung nhưng không có private key.
        body = body.replace(b"demo-call-abc123", b"demo-call-HACKED")

    response = httpx.post(
        WEBHOOK_URL,
        content=body,
        headers={
            "Content-Type": "application/json",
            "telnyx-signature-ed25519": base64.b64encode(signature).decode(),
            "telnyx-timestamp": timestamp,
        },
        timeout=10.0,
    )
    print(f"[GỬI  ] {event_type:18s} -> HTTP {response.status_code} {response.text}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tamper", action="store_true", help="sửa body sau khi ký")
    args = parser.parse_args()

    if args.tamper:
        sign_and_post("call.initiated", {"call_control_id": CALL_CONTROL_ID, "direction": "incoming"}, tamper=True)
        return

    # Đúng trình tự một cuộc gọi đến thật.
    sign_and_post("call.initiated", {
        "call_control_id": CALL_CONTROL_ID,
        "direction": "incoming",
        "from": "+4915112345678",
        "to": "+4930123456",
    })
    time.sleep(0.3)
    sign_and_post("call.answered", {"call_control_id": CALL_CONTROL_ID})
    time.sleep(0.3)
    sign_and_post("call.hangup", {"call_control_id": CALL_CONTROL_ID, "hangup_cause": "normal_clearing"})


if __name__ == "__main__":
    main()
