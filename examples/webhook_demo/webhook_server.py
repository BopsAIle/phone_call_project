"""Bước 1: SERVER CỦA TA — cái nhận webhook.

Đây là bản rút gọn của telephony/telnyx/routes.py, bỏ hết phần audio để chỉ còn
lại đúng cơ chế webhook:

    nhận POST  ->  kiểm chữ ký  ->  đọc event_type  ->  gọi ngược API  ->  trả 200

Chạy:  uvicorn webhook_server:app --port 8080
"""

from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Request, Response
from nacl.signing import VerifyKey

# --- Cấu hình. Ngoài đời những giá trị này đến từ .env qua config.Settings ---
PUBLIC_KEY = json.loads(Path(__file__).with_name("demo_keys.json").read_text())["public_key"]
TELNYX_API_BASE = "http://127.0.0.1:9090/v2"   # thật: https://api.telnyx.com/v2
API_KEY = "demo-api-key"                        # thật: TELNYX_API_KEY
STREAM_URL = "wss://demo.example.com/telnyx/media?token=demo-token"
TOLERANCE_SECONDS = 300

SIGNATURE_HEADER = "telnyx-signature-ed25519"
TIMESTAMP_HEADER = "telnyx-timestamp"

app = FastAPI(title="Webhook demo - phía nhận")


class SignatureError(ValueError):
    """Request này không phải do Telnyx gửi, hoặc gửi quá lâu rồi."""


def verify(body: bytes, signature_b64: str | None, timestamp: str | None) -> None:
    """Vì sao phải có hàm này: URL webhook nằm công khai trên Internet. Không
    kiểm chữ ký thì bất kỳ ai cũng POST vào được và bắt hệ thống nhấc máy,
    mở stream, tiêu tiền trên tài khoản Telnyx của bạn."""
    if not signature_b64 or not timestamp:
        raise SignatureError("thiếu header chữ ký")
    try:
        sent_at = int(timestamp)
    except (TypeError, ValueError):
        raise SignatureError("timestamp hỏng")
    # Chống replay: kẻ tấn công bắt được 1 request hợp lệ cũng không phát lại
    # được mãi, vì timestamp nằm trong phần được ký nên sửa là hỏng chữ ký.
    if abs(time.time() - sent_at) > TOLERANCE_SECONDS:
        raise SignatureError("timestamp ngoài cửa sổ cho phép (replay?)")
    signed = f"{timestamp}|".encode() + body   # đúng công thức Telnyx quy định
    try:
        VerifyKey(base64.b64decode(PUBLIC_KEY)).verify(signed, base64.b64decode(signature_b64))
    except Exception as exc:
        raise SignatureError("chữ ký không khớp") from exc


async def telnyx_command(call_control_id: str, action: str, payload: dict[str, Any]) -> None:
    """Chiều NGƯỢC LẠI của webhook: ta chủ động gọi REST API của Telnyx."""
    url = f"{TELNYX_API_BASE}/calls/{call_control_id}/actions/{action}"
    async with httpx.AsyncClient(timeout=10.0) as http:
        response = await http.post(url, json=payload, headers={"Authorization": f"Bearer {API_KEY}"})
    print(f"    -> POST {action}  (Telnyx trả {response.status_code})")


@app.post("/telnyx/webhook")
async def webhook(request: Request) -> Response:
    body = await request.body()

    try:
        verify(body, request.headers.get(SIGNATURE_HEADER), request.headers.get(TIMESTAMP_HEADER))
    except SignatureError as exc:
        print(f"[TỪ CHỐI 401] {exc}")
        return Response(status_code=401, content='{"error":"invalid_signature"}',
                        media_type="application/json")

    data = (await request.json()).get("data") or {}
    event_type = str(data.get("event_type") or "")
    payload = data.get("payload") or {}
    ccid = str(payload.get("call_control_id") or "")
    print(f"[NHẬN ] {event_type:18s} ccid={ccid}")

    if event_type == "call.initiated":
        # Cuộc gọi đang đổ chuông. Bảo Telnyx nhấc máy hộ.
        await telnyx_command(ccid, "answer", {})
    elif event_type == "call.answered":
        # Đã nhấc máy. Bảo Telnyx đẩy audio sang WebSocket của ta.
        await telnyx_command(ccid, "streaming_start", {
            "stream_url": STREAM_URL,
            "stream_track": "inbound_track",
            "stream_codec": "L16",
        })
    elif event_type == "call.hangup":
        print(f"    -> cuộc gọi kết thúc, cause={payload.get('hangup_cause')}")
    else:
        print("    -> event không quan tâm, bỏ qua")

    # LUÔN trả 200 khi chữ ký hợp lệ. Non-2xx khiến Telnyx gửi lại, và một lần
    # gửi lại call.answered sẽ cố mở stream thứ hai -> lỗi.
    return Response(status_code=200, content='{"ok":true}', media_type="application/json")
