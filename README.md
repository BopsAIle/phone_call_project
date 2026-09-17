# phone_call_project

Monorepo gồm ba phần, mỗi phần là một project độc lập nằm trong thư mục riêng:

| Thư mục | Nội dung | Nguồn gốc (nhánh cũ) | Cổng mặc định |
| --- | --- | --- | --- |
| `AI/` | AI Bridge (Python, FastAPI + WebSocket) xử lý cuộc gọi | `7-test_quantify_speech` | 8080 |
| `BE/` | API NestJS (Postgres/TypeORM) cho nhà hàng, booking, order | `mhoan` | 3001 |
| `FE/` | Dashboard React + Vite | `feature/react-frontend` | 3000 |

## Chạy nhanh

```bash
make dev      # cài deps lần đầu, bật Docker (Postgres+Redis), rồi chạy BE, FE, ngrok, AI trong 1 terminal
make check    # curl /health các service
make stop     # tắt Docker + service của repo (không đụng tiến trình khác)
make setup    # chỉ cài deps + tạo .env từ .env.example
```

Yêu cầu: Node 22, Python 3.12, Docker Desktop (hoặc Colima / OrbStack). Không cần cài ngrok, nó chạy trong Docker.

**Bật ngrok để Telnyx gọi vào**: mở file `.env` ở root (được tạo từ `.env.example`), điền `NGROK_AUTHTOKEN`
và `NGROK_DOMAIN` (static domain của tài khoản ngrok của bạn), rồi `make dev`. Domain phải trùng với
`TELNYX_STREAM_URL` trong `AI/.env` và Webhook URL trên portal Telnyx. Inspector: http://localhost:4040.
`make dev` sẽ từ chối chạy nếu cổng 3000/3001/8080 đang bị chiếm bởi tiến trình khác.
Chi tiết checklist gọi thử và chẩn đoán: [AI/RUNBOOK.md](AI/RUNBOOK.md).

## Chạy từng phần (thủ công)

```bash
# BE
cd BE && npm install && npm run start:dev

# FE
cd FE && npm install && npm run dev

# AI
cd AI && python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt && python app.py
```

Chi tiết cấu hình, biến môi trường, Docker Postgres/Redis: xem `AI/run_fe_be.md` và `AI/RUNBOOK.md`.
Lưu ý `AI/run_fe_be.md` được viết khi FE và BE còn là repo riêng, đường dẫn trong đó cần đọc là `BE/` và `FE/`.
