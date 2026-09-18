# 02 — Kiến trúc & cổng

## Sơ đồ tổng

```
                     ┌──────────────────────────────┐
  Nhân viên  ──────> │  FE  :3070  (React + Vite)   │
                     └──────────────┬───────────────┘
                                    │ HTTP /api  (proxy Vite)
                                    v
                     ┌──────────────────────────────┐        ┌──────────────────┐
                     │  BE  :8070  (NestJS)         │ <────> │ Postgres :5433   │
                     │  Swagger: /api-docs          │        └──────────────────┘
                     └──────────────┬───────────────┘
                                    ^ HTTP (tra cứu + ghi đơn + lưu transcript)
                                    │
                     ┌──────────────┴───────────────┐        ┌──────────────────┐
  Telnyx ──ngrok──>  │  AI Bridge :8071 (FastAPI)   │ <────> │ Redis :6379      │
  (cuộc gọi thật)    │  /health · /v1/bridge        │        │ (cache catalog)  │
                     │  /telnyx/webhook · /media    │        └──────────────────┘
                     └──────────────┬───────────────┘
                                    │ WebSocket (OpenAI Realtime / HTTPS)
                                    v
                            OpenAI: STT · LLM · TTS
```

## Bảng cổng

| Dịch vụ | Thư mục | Cổng | URL kiểm tra |
| --- | --- | --- | --- |
| Dashboard React | `FE/` | **3070** | http://localhost:3070 |
| API NestJS | `BE/` | **8070** | http://localhost:8070/api-docs |
| AI Bridge | `AI/` | **8071** | http://127.0.0.1:8071/health |
| PostgreSQL (Docker) | gốc repo | 5433 | trong container vẫn là 5432 |
| Redis (Docker) | gốc repo | 6379 | `redis://127.0.0.1:6379/0` |
| ngrok inspector (Docker) | gốc repo | 4040 | http://localhost:4040 |
| UI demo thoại (tùy chọn) | `AI/frontend/` | 5173 | http://localhost:5173 |

Bộ cổng 3070/8070/8071 được chọn cố ý để tránh đụng 3000/3001/8080 — những cổng
hay bị project khác trên cùng máy chiếm.

## Ai gọi ai

**FE → BE.** Chỉ một chiều, qua HTTP. FE gọi đường dẫn tương đối `/api/...`; Vite proxy
chuyển tiếp sang `http://localhost:8070` và cắt tiền tố `/api`
(xem `FE/vite.config.ts`).

**AI Bridge → BE.** Cũng chỉ một chiều, qua HTTP. Các endpoint AI dùng:

| Mục đích | Request | Code gọi |
| --- | --- | --- |
| Tìm nhà hàng theo hotline | `GET /restaurants/by-hotline/:hotline` | `AI/booking/client.py` |
| Lấy thực đơn chi nhánh | `GET /menu/branch/:branchId` | `AI/order/client.py` |
| Tạo đơn đặt bàn | `POST /bookings/ai` (dự phòng: `POST /bookings`) | `AI/booking/client.py` |
| Tạo đơn lấy tại quán | `POST /menu/takeout/ai` | `AI/order/client.py` |
| Tạo đơn giao hàng | `POST /menu/delivery/ai` | `AI/order/client.py` |
| Mở bản ghi cuộc gọi | `POST /calls/ai/start` | `AI/calls/client.py` |
| Thêm transcript | `POST /calls/ai/:id/messages` | `AI/calls/client.py` |
| Đóng bản ghi cuộc gọi | `POST /calls/ai/:id/end` | `AI/calls/client.py` |
| Đồng bộ catalog nền | `GET /restaurants`, `GET /branches` | `AI/sync/poller.py` |

**BE không bao giờ gọi AI Bridge.** Quan hệ một chiều này giữ cho BE hoàn toàn không
biết gì về thoại — nó chỉ là một API nhà hàng bình thường.

**Telnyx → AI Bridge.** Nhà mạng gọi vào qua Internet, nên cần một địa chỉ công khai:
ngrok (hoặc Cloudflare tunnel) chuyển tiếp về `127.0.0.1:8071`. Xem
[chương 13](13-telnyx.md).

## Hai đường vào AI Bridge

AI Bridge chấp nhận cuộc gọi theo **hai cách khác nhau**, và cả hai đều đi vào cùng một
lõi xử lý:

| Đường | Endpoint | Ai dùng | Bật/tắt |
| --- | --- | --- | --- |
| WebSocket "bridge" | `WS /v1/bridge` | UI demo trình duyệt, backend thoại tự viết | `BRIDGE_ENABLED` |
| Telnyx Media Stream | `POST /telnyx/webhook` + `WS /telnyx/media` | Cuộc gọi điện thoại thật | `TELNYX_ENABLED` |

Mấu chốt thiết kế: `AI/telephony/telnyx/stream.py` có class `TelnyxCallSocket` **giả dạng**
một WebSocket bridge (chỉ cần 4 phương thức: `receive`, `send_bytes`, `send_text`,
`close`). Nhờ vậy `AI/bridge/session.py` — nơi chứa toàn bộ logic cuộc gọi —
**không có một dòng code nào biết Telnyx tồn tại**.

## Hạ tầng Docker

`docker-compose.yml` ở gốc repo chạy ba container:

- `ai_receptionist_db` — Postgres 16, dữ liệu nằm trong volume `postgres_data`
- `aibridge-redis` — Redis 7, cache catalog cho AI (tùy chọn, xem [chương 14](14-cache-va-sync.md))
- `aibridge-ngrok` — chỉ bật khi có `NGROK_AUTHTOKEN` (profile `ngrok`)

## Tiếp theo

→ [03 — Chạy thử lần đầu](03-chay-thu-lan-dau.md)
