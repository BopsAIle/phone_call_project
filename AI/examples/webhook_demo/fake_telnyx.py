"""Bước 2: TELNYX GIẢ — vừa là nhà mạng gửi webhook, vừa là REST API nhận lệnh.

Hai vai, tương ứng hai chiều giao tiếp:

  Vai A (server, chạy nền): nhận lệnh answer / streaming_start / hangup từ ta.
  Vai B (CLI `place_call.py`): ký và bắn webhook sang ta.

Chạy vai A:  uvicorn fake_telnyx:app --port 9090
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request

app = FastAPI(title="Webhook demo - Telnyx gia lap")

# Nhật ký lệnh đã nhận, để test khẳng định được "server đã gọi answer chưa".
commands: list[dict[str, Any]] = []


@app.post("/v2/calls/{call_control_id}/actions/{action}")
async def command(call_control_id: str, action: str, request: Request) -> dict[str, Any]:
    body = await request.json()
    commands.append({"call_control_id": call_control_id, "action": action, "body": body})
    print(f"[TELNYX] nhận lệnh '{action}' cho ccid={call_control_id}")
    if action == "streaming_start":
        print(f"         sẽ mở WebSocket tới {body.get('stream_url')}")
    # Telnyx thật trả về một result object; ở đây chỉ cần 200.
    return {"data": {"result": "ok"}}


@app.get("/commands")
async def list_commands() -> dict[str, Any]:
    return {"commands": commands}
