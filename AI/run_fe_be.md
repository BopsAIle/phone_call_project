# Chạy backend NestJS + frontend React trên local

> **Cập nhật:** từ nhánh `dev`, FE và BE đã được gộp vào cùng repo này ở `FE/` và `BE/` (AI Bridge nằm ở `AI/`). Các đường dẫn `restaurant-backend` / `restaurant-frontend` bên dưới tương ứng với `BE/` và `FE/`.

Hai nhánh này **không nằm trong thư mục AI Bridge**. Chúng được checkout ra thư mục cạnh `phone_call_project`:

| Dự án | Nhánh Git | Thư mục |
| --- | --- | --- |
| API NestJS (thay Render) | `mhoan` | `D:\phonecall\restaurant-backend` |
| Dashboard React | `feature/react-frontend` | `D:\phonecall\restaurant-frontend` |

AI Bridge (repo này) gọi API local qua `RESTAURANT_API_BASE=http://127.0.0.1:8070`.

```
Trình duyệt dashboard  -->  React :3070  -->  NestJS :8070  -->  Postgres Docker :5433
AI Bridge (Python :8071)  ---------------------------------^
        |
        +--> Redis Docker :6379 (cache catalog)
```

| Dịch vụ | Cổng | URL |
| --- | --- | --- |
| React dashboard | 3070 | http://localhost:3070 |
| NestJS API | 8070 | http://localhost:8070 |
| Swagger | 8070 | http://localhost:8070/api-docs |
| PostgreSQL | 5433 | `localhost:5433` (trong container là 5432) |
| Redis | 6379 | `redis://127.0.0.1:6379/0` |
| AI Bridge | 8071 | `ws://127.0.0.1:8071/v1/bridge` |

Cổng **8070** (API) tách khỏi **8071** (AI Bridge) để chạy cùng lúc. Cổng **5433** tránh đụng Postgres khác đang chiếm 5432.
FE **3070** → NestJS **8070** → Postgres **5433**, AI Bridge **8071**. `strictPort: true` trong `FE/vite.config.ts` giữ Vite không tự nhảy cổng sang cổng của BE.

---

## Dữ liệu đang lưu ở đâu?

**PostgreSQL trên Docker**, không còn Render.

Container giữ cổng 5433 là **`ai_receptionist_db`**:

- Container: `ai_receptionist_db` (image `postgres:16-alpine`, `restart: unless-stopped`)
- Host từ máy: `localhost:5433`
- Ổ dữ liệu: Docker named volume `phone_call_project_postgres_data`

> ⚠️ **Container này mồ côi.** Docker ghi nó thuộc compose project `D:\phone_call_project`, nhưng **thư mục đó đã bị xóa** — không còn `docker-compose.yml` nào sinh ra nó. Vì vậy mọi lệnh `docker compose` đều vô dụng với nó; chỉ quản lý được bằng `docker start` / `docker stop` theo tên.
>
> Nếu lỡ `docker rm ai_receptionist_db`, **không có compose file để dựng lại**. Volume `phone_call_project_postgres_data` vẫn còn data, tạo lại thủ công bằng:
>
> ```powershell
> docker run -d --name ai_receptionist_db --restart unless-stopped `
>   -p 5433:5432 `
>   -e POSTGRES_DB=ai_receptionist `
>   -e POSTGRES_USER=receptionist `
>   -e POSTGRES_PASSWORD=receptionist `
>   -v phone_call_project_postgres_data:/var/lib/postgresql/data `
>   postgres:16-alpine
> ```

Container này chứa **hai database tách biệt**:

| Database | User / password | Schema | Thuộc app nào |
| --- | --- | --- | --- |
| `restaurant_ai` | `receptionist` / `receptionist` | `restaurants`, `branches`, `menu_items`, `bookings`, `order_items` (snake_case, TypeORM) | NestJS trong `restaurant-backend` |
| `ai_receptionist` | `receptionist` / `receptionist` | `Booking`, `Call`, `Store`, `Utterance` (PascalCase, Prisma) | App cũ ở `D:\phone_call_project` |

> **Không trỏ NestJS vào `ai_receptionist`.** NestJS bật `synchronize: true`, nó sẽ tự tạo 5 bảng snake_case chen vào cạnh các bảng Prisma và gây xung đột khi Prisma migrate. Luôn dùng `DB_NAME=restaurant_ai`.

Role `postgres` **không tồn tại** trong instance này — user duy nhất là `receptionist`.

Tắt container **không xóa data**. Data chỉ mất khi xóa volume:

```powershell
docker volume rm phone_call_project_postgres_data
```

Xem data:

```powershell
docker exec -it ai_receptionist_db psql -U receptionist -d restaurant_ai
```

Trong `psql`: `\dt` liệt kê bảng; `SELECT * FROM restaurants;` xem nhà hàng.

`.env` backend (`DB_SSL=false`) trỏ đúng instance Docker này, không còn Neon/Render.

### Container `restaurant-ai-postgres` đã ngừng dùng

`D:\phonecall\restaurant-backend\docker-compose.yml` định nghĩa container `restaurant-ai-postgres` cũng map `5433:5432`. Container này **không còn được dùng** vì `ai_receptionist_db` đã giữ cổng 5433 trước.

Nếu chạy `docker compose up -d` trong `restaurant-backend`, container sẽ báo `Started` nhưng Docker **không publish được cổng** (kiểm chứng: `docker port restaurant-ai-postgres` trả về rỗng). Mọi kết nối tới `localhost:5433` vẫn rơi vào `ai_receptionist_db`. Đây là nguồn gốc của lỗi gây nhầm lẫn:

```
error: password authentication failed for user "postgres"
```

Lỗi này **không phải sai password** — mà là đang gõ cửa nhầm database.

Dữ liệu cũ trong `restaurant-ai-postgres` đã được `pg_dump` chuyển sang `restaurant_ai` của `ai_receptionist_db`. Volume cũ `restaurant-backend_restaurant_pgdata` vẫn còn nguyên nếu cần quay lại.

Nên tắt hẳn để khỏi nhầm:

```powershell
docker stop restaurant-ai-postgres
```

---

## Yêu cầu

- Node.js (đã dùng v24) + npm
- Docker Desktop đang chạy

Lần đầu (đã làm rồi thì bỏ qua `npm install`):

```powershell
cd D:\phonecall\restaurant-backend
copy .env.example .env
npm install

cd D:\phonecall\restaurant-frontend
npm install
```

`.env` backend phải là:

```
PORT=8070
DB_HOST=127.0.0.1
DB_PORT=5433
DB_USERNAME=receptionist
DB_PASSWORD=receptionist
DB_NAME=restaurant_ai
DB_SSL=false
```

> Dùng `127.0.0.1` chứ không phải `localhost`. Trên Windows có `wslrelay.exe` nghe `[::1]:5433`, mà Node 17+ ưu tiên IPv6 — `localhost` có thể resolve sang một Postgres khác trong WSL.

Frontend cần file `.env`:

```
VITE_API_URL=http://localhost:8070
```

---

## Chạy

Mở **3 terminal**.

### 1. Postgres + Redis

```powershell
docker start ai_receptionist_db
docker start aibridge-redis
```

Kiểm tra:

```powershell
docker ps --filter name=ai_receptionist_db --filter name=aibridge-redis
docker exec -it aibridge-redis redis-cli ping    # mong đợi: PONG
```

Đợi `ai_receptionist_db` đạt trạng thái `healthy`.

Redis là tuỳ chọn — thiếu thì AI Bridge vẫn chạy nhưng không có cache, log sẽ in traceback dài kèm dòng `Redis connect failed; running without cache`. Đó là cảnh báo đã được bắt, **không phải crash**.

Nếu chưa có container Redis:

```powershell
docker run -d --name aibridge-redis -p 6379:6379 redis:7-alpine
```

### 2. NestJS API

```powershell
cd D:\phonecall\restaurant-backend
npm run start:dev
```

Log thành công: `Ứng dụng đang chạy tại: http://localhost:8070`.

### 3. React dashboard

```powershell
cd D:\phonecall\restaurant-frontend
npm run dev
```

Mở http://localhost:3070.

### 4. (Tuỳ chọn) AI Bridge

Trong `phone_call_project/.env` phải có:

```
RESTAURANT_API_BASE=http://127.0.0.1:8070
REDIS_URL=redis://127.0.0.1:6379/0
```

```powershell
cd D:\phonecall\phone_call_project
.venv\Scripts\Activate.ps1
python app.py
```

Kiểm tra AI Bridge đã nối được backend:

```powershell
curl http://127.0.0.1:8071/health
```

Mong đợi `"cache": {"enabled": true, "ready": true, "degraded": false}` kèm số `restaurants` / `hotlines` khớp dữ liệu trên dashboard. Nếu thấy `"enabled": false` thì Redis chưa chạy; nếu `ready: false` thì NestJS chưa chạy hoặc sai `RESTAURANT_API_BASE`.

---

## Dừng

- NestJS / Vite: `Ctrl+C` trong terminal tương ứng
- Postgres (giữ data):

```powershell
docker stop ai_receptionist_db
```

Bật lại: `docker start ai_receptionist_db`.

---

## Gặp lỗi thường gặp

| Hiện tượng | Cách xử lý |
| --- | --- |
| `password authentication failed for user "postgres"` | `.env` backend còn dùng user cũ. Đổi thành `receptionist` / `receptionist`. Role `postgres` không tồn tại trong `ai_receptionist_db`. |
| `password authentication failed` dù `.env` đã đúng | Đang tới nhầm Postgres. Chạy `docker ps --format "{{.Names}}\t{{.Ports}}" \| findstr 5433` xem container nào thật sự giữ cổng. |
| `ECONNREFUSED` cổng 5433 | `docker start ai_receptionist_db` (đừng dùng `docker compose`, container này mồ côi) |
| Cổng 5433 vẫn LISTENING nhưng không kết nối được | Binding "ma" của Docker Desktop còn sót sau khi container chết. Kiểm tra bằng `docker ps`, đừng tin `netstat`. |
| API fail vì SSL | `DB_SSL=false` trong `.env` backend |
| Cổng 8070/3070 đã chiếm | Đóng process cũ (Ctrl+C), hoặc đổi `PORT` / Vite `port` rồi sửa `VITE_API_URL` và `CORS_ORIGIN` |
| Dashboard trống | DB mới; tạo restaurant trên UI |
| AI Bridge không đặt bàn / đặt món | API chưa chạy, hoặc hotline không khớp nhà hàng trong DB |
| AI Bridge log traceback Redis lúc khởi động | Chỉ là cảnh báo. Chạy `docker start aibridge-redis` nếu muốn có cache. |
