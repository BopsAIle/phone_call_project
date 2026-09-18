# 04 — Bản đồ thư mục

Chương này để bạn biết **mở file nào** khi cần sửa một thứ cụ thể.

## Gốc repo

```
phone_call_project/
├── AI/                 lõi xử lý cuộc gọi (Python)
├── BE/                 API nhà hàng (NestJS)
├── FE/                 dashboard (React)
├── book/               tài liệu bạn đang đọc
├── scripts/            dev.sh, stop.sh, check.sh, docker-up.sh, telnyx-test.sh
├── docker-compose.yml  Postgres + Redis + ngrok
├── Makefile            make dev / setup / check / stop / logs / clean
└── README.md           bản tóm tắt vận hành
```

## `AI/` — chi tiết

Đây là phần lớn nhất và đáng đọc nhất (~8.800 dòng Python).

```
AI/
├── app.py              điểm vào: nạp Settings, tạo app, chạy uvicorn      (25 dòng)
├── config.py           TOÀN BỘ biến môi trường, một class Settings       (151)
├── requirements.txt
│
├── bridge/             ← LÕI
│   ├── server.py       tạo FastAPI app, xác thực, khai báo route         (349)
│   ├── session.py      máy trạng thái một cuộc gọi — file quan trọng nhất (1401)
│   └── protocol.py     định dạng wire: PCM 24 kHz + sự kiện JSON         (173)
│
├── stt/                NGHE
│   ├── realtime.py     kết nối OpenAI Realtime transcription + VAD       (361)
│   ├── context.py      dựng prompt/keywords từ tên món của nhà hàng      (113)
│   └── phonetic.py     khớp phiên âm khi STT nghe sai                    (116)
│
├── llm/                NGHĨ
│   ├── stream.py       system prompt + stream theo câu + vòng gọi tool   (722)
│   └── history.py      sửa lịch sử hội thoại bị hỏng                     (76)
│
├── tts/openai_tts.py   NÓI: văn bản → PCM                                (83)
├── turn/barge_in.py    OutboundGate + trình tự cắt lời                   (137)
│
├── booking/            nghiệp vụ ĐẶT BÀN
│   ├── tools.py        3 tool cho LLM                                    (466)
│   ├── client.py       HTTP tới BE                                       (213)
│   ├── matcher.py      LLM chọn chi nhánh khách muốn                     (475)
│   └── models.py       Restaurant, Branch                                (48)
│
├── order/              nghiệp vụ ĐẶT MÓN
│   ├── tools.py        8 tool cho LLM                                    (1053)
│   ├── client.py       HTTP tới BE                                       (260)
│   ├── matcher.py      LLM khớp tên món                                  (158)
│   └── models.py       MenuItem, CartLine                                (52)
│
├── telephony/telnyx/   CUỘC GỌI THẬT
│   ├── routes.py       POST /telnyx/webhook, WS /telnyx/media            (161)
│   ├── stream.py       TelnyxCallSocket — giả dạng socket bridge         (350)
│   ├── codec.py        L16 big-endian ↔ PCM16-LE 24 kHz                  (114)
│   ├── signature.py    xác minh chữ ký Ed25519 của webhook               (61)
│   └── api.py          gọi ngược Telnyx: answer, stream, hangup          (108)
│
├── cache/redis_store.py    snapshot catalog trong Redis                  (444)
├── sync/poller.py          tác vụ nền kéo catalog từ BE                  (227)
├── calls/                  logger.py + client.py: lưu transcript lên BE
├── audio/                  resample.py (16↔24 kHz) + recorder.py (ghi WAV)
├── obs/timing.py           đo độ trễ từng chặng một lượt nói             (127)
│
├── scripts/            stt_eval.py (đo STT), turn_stats.py (đo độ trễ)
├── tests/              30 file pytest
├── frontend/           UI demo thu âm trong trình duyệt (TypeScript)
├── examples/webhook_demo/  mô phỏng Telnyx offline
└── documents/          ghi chép thiết kế, hợp đồng API, playbook
```

### Ba file nên đọc trước

1. **`AI/bridge/session.py`** — mọi thứ hội tụ ở đây. Class `CallSession` giữ trạng thái,
   `CallPipeline` điều phối, `TurnPlayer` phát tiếng.
2. **`AI/llm/stream.py`** — hàm `build_system_prompt()` là nơi "tính cách" và toàn bộ luật
   nghiệp vụ của AI được viết ra bằng tiếng Anh.
3. **`AI/config.py`** — bảng tra mọi thứ có thể chỉnh được.

## `BE/src/` — chi tiết

NestJS chia theo module, mỗi module một thư mục cùng bộ file:

```
BE/src/
├── main.ts             bootstrap, CORS, ValidationPipe, Swagger
├── app.module.ts       ghép các module + TypeORM + interceptor toàn cục
├── config/database.config.ts
├── common/             filter lỗi, interceptor log, interceptor bọc response
│
├── restaurants/        nhà hàng      ─┐
├── branches/           chi nhánh      │  mỗi module:
├── bookings/           đặt bàn        ├─ *.controller.ts   route HTTP
├── menu/               món + đơn hàng │  *.service.ts      nghiệp vụ
└── calls/              nhật ký gọi   ─┘  *.repository.ts   truy vấn DB
                                          entities/*.ts     bảng
                                          dto/*.ts          kiểm tra dữ liệu vào
```

## `FE/src/` — chi tiết

```
FE/src/
├── App.tsx             router + theme Ant Design
├── api/                axios instance + hàm gọi từng nhóm endpoint
├── hooks/              useRestaurants, useBranches, useBookings, useMenu (react-query)
├── pages/              Dashboard, Restaurants, Branches, Bookings, Menu, Orders
├── components/         MainLayout, LoadingSpinner
└── types/              kiểu TypeScript khớp với entity của BE
```

## Tôi muốn sửa X, mở file nào?

| Muốn sửa | Mở |
| --- | --- |
| Lời chào, luật ứng xử của AI | `AI/llm/stream.py` → `build_system_prompt()` |
| Menu bấm phím 1/2/3 | `AI/bridge/protocol.py` → `SERVICE_BY_DIGIT` + `SERVICE_MENU_EN` trong `llm/stream.py` |
| Thêm một tool mới cho LLM | `AI/booking/tools.py` hoặc `AI/order/tools.py` |
| Độ nhạy cắt lượt / barge-in | `AI/stt/realtime.py` → `VAD`, và `AI/turn/barge_in.py` |
| Giọng nói, tốc độ phát | `AI/tts/openai_tts.py` + `TTS_CHUNK_BYTES` |
| Thêm cột vào bảng đơn hàng | `BE/src/bookings/entities/booking.entity.ts` + DTO tương ứng |
| Thêm trang dashboard | `FE/src/pages/` + route trong `FE/src/App.tsx` |
| Cổng, timeout, cờ bật/tắt | `AI/config.py` + file `.env` tương ứng |

## Tiếp theo

→ [05 — AI Bridge khởi động](05-ai-bridge-khoi-dong.md)
