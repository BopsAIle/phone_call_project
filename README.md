# phone_call_project

Monorepo gồm ba phần độc lập: **AI Bridge** (Python/FastAPI + WebSocket, xử lý cuộc gọi),
**BE** (NestJS + Postgres/TypeORM, nghiệp vụ nhà hàng/booking/order) và **FE** (React + Vite, dashboard).

```
Browser ──> FE :3070 ──> BE :8070 ──> Postgres :5433
AI Bridge :8071 ────────> BE :8070            (đặt bàn / đặt món)
Telnyx ──> ngrok ──> AI Bridge :8071          (cuộc gọi thật)
```

## Dịch vụ & cổng

| Dịch vụ | Thư mục | Cổng | URL |
| --- | --- | --- | --- |
| Dashboard React + Vite | `FE/` | **3070** | http://localhost:3070 |
| API NestJS (+ Swagger) | `BE/` | **8070** | http://localhost:8070/api-docs |
| AI Bridge (FastAPI + WebSocket) | `AI/` | **8071** | http://127.0.0.1:8071/health · `ws://127.0.0.1:8071/v1/bridge` |
| PostgreSQL (Docker) | root | 5433 | trong container là 5432 |
| Redis (Docker) | root | 6379 | `redis://127.0.0.1:6379/0` |
| ngrok inspector (Docker) | root | 4040 | http://localhost:4040 |
| UI demo thoại (tùy chọn) | `AI/frontend/` | 5173 | http://localhost:5173 |

Cổng 3070/8070/8071 được chọn để không đụng các cổng 3000/3001/8080 hay bị project khác trên máy chiếm.

## Yêu cầu

Node 22 · Python 3.12 · Docker (Docker Desktop / Colima / OrbStack). Không cần cài ngrok — nó chạy trong Docker.

## Chạy nhanh (khuyến nghị)

```bash
make setup    # cài deps BE/FE/AI + tạo .env từ .env.example (chạy 1 lần, nhớ điền key)
make dev      # Docker (Postgres+Redis+ngrok) -> BE -> FE -> AI, log gộp 1 terminal, PID ghi vào .dev.pids
make check    # curl thử BE / FE / AI (+ ngrok nếu bật)
make stop     # dừng Docker + mọi tiến trình của repo (không đụng tiến trình khác)
make logs     # xem log Docker
make clean    # xoá node_modules / .venv (giữ data Postgres)
```

`make dev` **từ chối chạy** nếu cổng 3070/8070/8071 đang bị chiếm — nó in ra PID đang giữ cổng để bạn xử lý trước.
Ctrl+C trong `make dev` là dừng sạch cả cụm.

## Chạy từng phần (thủ công)

Chạy **theo đúng thứ tự** này, mỗi phần một terminal:

```bash
# 1) Hạ tầng: Postgres 5433 + Redis 6379
make infra

# 2) BE — phải lên trước AI (AI sync catalog từ BE lúc khởi động)
cd BE && npm install && npm run start:dev
#    -> log: "Ứng dụng đang chạy tại: http://localhost:8070"  · Swagger: /api-docs

# 3) FE
cd FE && npm install && npm run dev
#    -> mở http://localhost:3070

# 4) AI Bridge — chỉ chạy sau khi BE đã lên
cd AI
python3 -m venv .venv                                # chỉ lần đầu (máy này KHÔNG có lệnh `python`)
.venv/bin/python -m pip install -r requirements.txt  # lần đầu, hoặc khi requirements.txt đổi
.venv/bin/python app.py                              # -> http://127.0.0.1:8071/health
```

Gọi thẳng `.venv/bin/python` thay vì `source .venv/bin/activate` để không phụ thuộc shell, và để chắc chắn
`pip`/`python` luôn trỏ vào venv (activate lỗi âm thầm sẽ cài nhầm vào môi trường hệ thống).
`app.py` phải chạy với thư mục làm việc là `AI/` vì nó khởi động uvicorn bằng `"app:app"`.

## Kiểm tra nhanh

```bash
make check                              # BE / FE / AI / ngrok
curl http://127.0.0.1:8070/api-docs     # BE Swagger
curl http://127.0.0.1:8071/health       # AI -> {"status":"ok"}
```

## Biến môi trường

| File | Biến quan trọng | Ghi chú |
| --- | --- | --- |
| `.env` (root) | `NGROK_AUTHTOKEN`, `NGROK_DOMAIN` | cho `docker-compose.yml` (postgres, redis, ngrok) |
| `BE/.env` | `PORT=8070`, `CORS_ORIGIN=http://localhost:3070`, `DB_*` (port 5433) | `CORS_ORIGIN` nhận nhiều origin, ngăn cách bởi dấu phẩy |
| `FE/.env` | `VITE_API_URL=/api` | đường dẫn tương đối, request đi qua proxy của Vite (`/api` → `http://localhost:8070`) |
| `AI/.env` | `AI_BRIDGE_HOST`, `AI_BRIDGE_PORT=8071`, `RESTAURANT_API_BASE=http://127.0.0.1:8070`, `OPENAI_API_KEY`, `AI_BRIDGE_TOKEN`, `REDIS_URL`, `TELNYX_*` | thiếu `OPENAI_API_KEY` thì STT/LLM/TTS fail; thiếu `AI_BRIDGE_TOKEN` thì mọi kết nối WS bị từ chối |

## Gọi thử cuộc gọi thật (Telnyx)

Đường công khai đang dùng: `https://aiapi.jupiter-ai.pro` → tunnel → `127.0.0.1:8071` (AI Bridge).
Telnyx gọi vào Call Control App `AI Bridge Dev`, webhook `https://aiapi.jupiter-ai.pro/telnyx/webhook`.

1. AI Bridge phải chạy ở 8071 và đã sync catalog từ BE 8070 (log: `Telnyx routes mounted`, `Catalog synced`).
2. `TELNYX_STREAM_URL` trong `AI/.env` phải trỏ **đúng host công khai đang sống**:
   `wss://aiapi.jupiter-ai.pro/telnyx/media`. Trỏ vào tunnel đã chết thì webhook vẫn tới nhưng **không có tiếng**.
3. `AI_BRIDGE_HOST=127.0.0.1` là đủ vì tunnel chạy cùng máy; chỉ đổi `0.0.0.0` nếu dùng **container ngrok**
   (container gọi qua `host.docker.internal:8071`).
4. Kiểm tra toàn tuyến không tốn tiền: `./scripts/telnyx-test.sh` — cả 3 mục `/health`,
   `/telnyx/webhook` (401 khi không ký), `/telnyx/media` (403 khi sai token) phải xanh.
5. Gọi thử bằng softphone SIP — **Zoiper**: host `sip.telnyx.com`, user `4mgtb3k0duz6`, mật khẩu lấy ở
   Portal > Voice > SIP Connections > `Forward Only`, transport SIP UDP → bấm `17733022476`.
   Chi tiết cách gọi và đọc log: [AI/RUNBOOK.md](AI/RUNBOOK.md).

## Đổi cổng thì sửa đồng bộ

| Thành phần | File | Biến |
| --- | --- | --- |
| FE listen | `FE/vite.config.ts` **và** `FE/vite.config.js` | `server.port` |
| FE → BE | `FE/.env`, `FE/.env.example`, `FE/src/api/axios.ts` (fallback), proxy `/api` trong `vite.config.*` | `VITE_API_URL` |
| BE listen | `BE/.env`, `BE/.env.example`, `BE/src/main.ts` (fallback) | `PORT` |
| BE cho phép FE | `BE/.env` | `CORS_ORIGIN` |
| AI listen | `AI/.env`, `AI/.env.example`, `AI/config.py` (default) | `AI_BRIDGE_PORT` |
| AI → BE | `AI/.env`, `AI/config.py`, `AI/booking/client.py`, `AI/order/client.py` | `RESTAURANT_API_BASE` |
| ngrok → AI | `docker-compose.yml`, `scripts/docker-up.sh` | `AI_BRIDGE_PORT` |

Hai cái bẫy đã từng gây lỗi thật:

- `FE/vite.config.js` là bản `tsc -b` sinh ra từ `vite.config.ts`, và **Vite nạp `.js` trước `.ts`** —
  sửa mỗi `.ts` sẽ không có tác dụng.
- Không có `strictPort: true` thì Vite **tự nhảy sang cổng kế tiếp** khi cổng đích bận, và đã từng đè lên
  cổng của NestJS gây `EADDRINUSE`. `make check`/`make dev` đọc cổng BE/FE trực tiếp từ `BE/.env` và
  `vite.config.ts` nên không bị lệch khi bạn đổi cổng.

## Truy cập từ xa qua Cloudflare tunnel

| Host công khai | Tunnel tới | Dịch vụ |
| --- | --- | --- |
| `callphone.jupiter-ai.pro` | `127.0.0.1:3070` | Dashboard FE (Vite dev server) |
| `aiapi.jupiter-ai.pro` | `127.0.0.1:8071` | AI Bridge (webhook + media WS của Telnyx) |

Hai điều bắt buộc để FE chạy được qua tunnel:

1. **`server.allowedHosts`** trong `FE/vite.config.ts` **và** `vite.config.js` phải chứa domain.
   Vite 5 chặn Host lạ để chống DNS-rebinding; thiếu sẽ báo
   `Blocked request. This host ("...") is not allowed`. Tiền tố `.` khớp cả domain gốc lẫn mọi subdomain
   (đang khai báo `['.jupiter-ai.pro', 'callphone.jupiter-ai.pro']`).
2. **`VITE_API_URL=/api`** trong `FE/.env`. Nếu để URL tuyệt đối kiểu `http://localhost:8070`, người truy
   cập từ xa sẽ gọi vào **chính máy họ**. Đi qua `/api` thì trình duyệt gọi cùng origin → Vite proxy sang
   BE 8070, **không cần CORS**.

⚠️ **Cảnh báo bảo mật**: dev server Vite **không có đăng nhập** và NestJS **không có guard/JWT** — ai biết
domain đều vào được dashboard và gọi được API đọc/ghi dữ liệu (restaurants, bookings, menu). Nên bật
**Cloudflare Access** (Zero Trust) cho hostname, hoặc chỉ mở tunnel khi đang test.

## Ghi chú

- BE dùng bộ NestJS **12.x**: mọi gói `@nestjs/*` phải cùng major. Lệch major (ví dụ `@nestjs/core@12` đi với
  `@nestjs/common@11`) làm app crash ngay lúc khởi động với `ERR_MODULE_NOT_FOUND: @nestjs/common/internal`.
  Sau khi pull code hoặc đổi dependency: `cd BE && npm install`.
- `AI/run_fe_be.md` được viết khi FE và BE còn là repo riêng (đường dẫn Windows `D:\...`): đọc `BE/` và `FE/` thay cho các đường dẫn đó.
- `AI/frontend/` là UI demo thoại chạy riêng ở cổng 5173, không thuộc luồng dashboard chính.
- `AI/examples/webhook_demo/` là demo webhook độc lập ở cổng 8080.
