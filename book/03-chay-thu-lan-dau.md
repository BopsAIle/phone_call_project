# 03 — Chạy thử lần đầu

## Cần có sẵn

- **Node 22**
- **Python 3.12** — trên máy dev hiện tại lệnh là `python3`, **không có** `python`
- **Docker** (Docker Desktop / Colima / OrbStack)
- Một **OpenAI API key** — thiếu nó thì STT/LLM/TTS đều chết

Không cần cài ngrok: nó chạy trong Docker.

## Cách nhanh nhất

```bash
make setup    # cài deps BE/FE/AI + tạo 4 file .env từ .env.example
make dev      # Docker -> BE -> FE -> AI, log gộp một terminal
make check    # curl thử từng service
make stop     # dừng tất cả
```

Sau `make setup`, **mở từng file `.env` và điền key thật** — đặc biệt là
`AI/.env` (`OPENAI_API_KEY`, `AI_BRIDGE_TOKEN`).

`make dev` **từ chối chạy** nếu cổng 3070/8070/8071 đang bị chiếm, và in ra PID đang giữ
cổng. Đây là chủ ý: nếu để Vite/Nest tự nhảy cổng khác, nó từng đè lên cổng của dịch vụ
kia và gây lỗi khó tìm. Ctrl+C trong `make dev` dừng sạch cả cụm.

Các target khác: `make infra` (chỉ Docker), `make logs`, `make clean`.

## Chạy tay từng phần

Thứ tự **bắt buộc** — AI đồng bộ catalog từ BE lúc khởi động:

```bash
# 1) Hạ tầng
make infra

# 2) BE (phải lên trước AI)
cd BE && npm install && npm run start:dev
#    log: "Ứng dụng đang chạy tại: http://localhost:8070"

# 3) FE
cd FE && npm install && npm run dev
#    mở http://localhost:3070

# 4) AI Bridge
cd AI
python3 -m venv .venv                                # chỉ lần đầu
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python app.py                              # http://127.0.0.1:8071/health
```

Hai lưu ý dễ vấp:

- Gọi thẳng `.venv/bin/python`, **đừng** `source .venv/bin/activate`. Activate lỗi âm
  thầm sẽ khiến `pip` cài vào Python hệ thống.
- `app.py` phải chạy với thư mục làm việc là `AI/`, vì nó khởi động uvicorn bằng chuỗi
  `"app:app"`.

## Bốn file `.env`

| File | Biến quan trọng | Ghi chú |
| --- | --- | --- |
| `.env` (gốc) | `NGROK_AUTHTOKEN`, `NGROK_DOMAIN` | chỉ cho `docker-compose.yml` |
| `BE/.env` | `PORT=8070`, `CORS_ORIGIN`, `DB_*` (cổng 5433) | `CORS_ORIGIN` nhận nhiều origin, cách nhau dấu phẩy |
| `FE/.env` | `VITE_API_URL=/api` | đường dẫn tương đối để đi qua proxy Vite |
| `AI/.env` | `OPENAI_API_KEY`, `AI_BRIDGE_TOKEN`, `RESTAURANT_API_BASE`, `TELNYX_*` | file dài nhất, xem bảng dưới |

### Các biến `AI/.env` đáng nhớ

Đọc định nghĩa đầy đủ ở `AI/config.py` (class `Settings`). Nhóm chính:

| Nhóm | Biến | Mặc định | Ý nghĩa |
| --- | --- | --- | --- |
| OpenAI | `OPENAI_API_KEY` | *(rỗng)* | thiếu là STT/LLM/TTS chết |
| | `OPENAI_MODEL` | `gpt-4o-mini` | model hội thoại |
| | `OPENAI_STT_MODEL` | `gpt-4o-transcribe` | **đừng** đổi sang `gpt-live-transcribe` (xem ch.07) |
| | `OPENAI_TTS_MODEL` / `_VOICE` | `tts-1` / `nova` | giọng nói |
| Bảo mật | `AI_BRIDGE_TOKEN` | *(rỗng)* | thiếu là **mọi** kết nối `/v1/bridge` bị từ chối |
| Mạng | `AI_BRIDGE_HOST` / `_PORT` | `0.0.0.0` / `8071` | |
| | `RESTAURANT_API_BASE` | `http://127.0.0.1:8070` | địa chỉ BE |
| Cache | `REDIS_URL` | *(rỗng)* | **rỗng = tắt cache và tắt syncer**, chạy như v1 |
| Hội thoại | `STT_SILENCE_DURATION_MS` | `800` | chờ im lặng bao lâu thì chốt lượt |
| | `DTMF_MENU_TIMEOUT_SECONDS` | `7` | chờ khách bấm phím bao lâu |
| Telnyx | `TELNYX_ENABLED` | `false` | để `false` là chạy y như chưa có Telnyx |
| Ghi nhận | `CALL_LOG_ENABLED` | `true` | lưu transcript lên BE |
| | `CALL_RECORD_DIR` | *(rỗng)* | rỗng = **không** ghi âm; bật thì lời chào tự thêm thông báo ghi âm |

## Kiểm tra

```bash
make check                              # BE / FE / AI / ngrok
curl http://127.0.0.1:8070/api-docs     # Swagger của BE
curl http://127.0.0.1:8071/health       # -> {"status":"ok","cache":{...}}
```

`/health` của AI trả về cả khối `cache` cho biết Redis có bật không, snapshot catalog
đã sẵn sàng chưa, lần đồng bộ gần nhất lúc nào — rất hữu ích khi debug.

## Thử nói chuyện mà không cần điện thoại

`AI/frontend/` là một UI demo chạy trong trình duyệt: nó mở micro, đẩy PCM 24 kHz lên
`/v1/bridge`, phát tiếng AI trả về, và xóa hàng phát khi nhận sự kiện `interrupt`.

```bash
cd AI/frontend && npm install && npm run dev   # http://localhost:5173
```

**Dùng tai nghe.** Phát loa ngoài thì tiếng AI lọt vào micro và tự kích barge-in giả.

## Tiếp theo

→ [04 — Bản đồ thư mục](04-ban-do-thu-muc.md)
