# Chạy backend NestJS + frontend React trên local

Hai nhánh này **không nằm trong thư mục AI Bridge**. Chúng được checkout ra thư mục cạnh `phone_call_project`:

| Dự án | Nhánh Git | Thư mục |
| --- | --- | --- |
| API NestJS (thay Render) | `mhoan` | `D:\phonecall\restaurant-backend` |
| Dashboard React | `feature/react-frontend` | `D:\phonecall\restaurant-frontend` |

AI Bridge (repo này) gọi API local qua `RESTAURANT_API_BASE=http://127.0.0.1:3001`.

```
Trình duyệt dashboard  -->  React :3000  -->  NestJS :3001  -->  Postgres Docker :5433
AI Bridge (Python :8080)  ---------------------------------^
```

| Dịch vụ | Cổng | URL |
| --- | --- | --- |
| React dashboard | 3000 | http://localhost:3000 |
| NestJS API | 3001 | http://localhost:3001 |
| Swagger | 3001 | http://localhost:3001/api-docs |
| PostgreSQL | 5433 | `localhost:5433` (trong container là 5432) |
| AI Bridge | 8080 | `ws://127.0.0.1:8080/v1/bridge` |

Cổng **3001** (API) tách khỏi **8080** (AI Bridge) để chạy cùng lúc. Cổng **5433** tránh đụng Postgres khác đang chiếm 5432.

---

## Dữ liệu đang lưu ở đâu?

**Có — PostgreSQL trên Docker Compose**, không còn Render.

- File compose: `D:\phonecall\restaurant-backend\docker-compose.yml`
- Container: `restaurant-ai-postgres` (image `postgres:16-alpine`)
- Database: `restaurant_ai`
- User / password: `postgres` / `postgres`
- Host từ máy: `localhost:5433`
- Ổ dữ liệu: Docker named volume `restaurant-backend_restaurant_pgdata`  
  (map vào `/var/lib/postgresql/data` trong container)

Tắt container **không xóa data**. Data mất khi xóa volume:

```powershell
docker compose -f D:\phonecall\restaurant-backend\docker-compose.yml down -v
```

Lần đầu database trống. NestJS bật `synchronize: true` nên bảng được tạo tự động khi API start. Tạo nhà hàng / chi nhánh / menu trên dashboard (http://localhost:3000). Hotline của nhà hàng phải trùng số mà frontend thoại gửi.

Xem data:

```powershell
docker exec -it restaurant-ai-postgres psql -U postgres -d restaurant_ai
```

Trong `psql`: `\dt` liệt kê bảng; `SELECT * FROM restaurants;` xem nhà hàng.

`.env` backend (`DB_SSL=false`) trỏ đúng instance Docker này, không còn Neon/Render.

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

Frontend cần file `.env`:

```
VITE_API_URL=http://localhost:3001
```

---

## Chạy

Mở **3 terminal**. Docker Compose chỉ chạy Postgres, không chạy NestJS.

### 1. Postgres

```powershell
cd D:\phonecall\restaurant-backend
docker compose up -d
docker compose ps
```

Đợi `healthy`.

### 2. NestJS API

```powershell
cd D:\phonecall\restaurant-backend
npm run start:dev
```

Log thành công: `Ứng dụng đang chạy tại: http://localhost:3001`.

### 3. React dashboard

```powershell
cd D:\phonecall\restaurant-frontend
npm run dev
```

Mở http://localhost:3000.

### 4. (Tuỳ chọn) AI Bridge

Trong `phone_call_project/.env` phải có:

```
RESTAURANT_API_BASE=http://127.0.0.1:3001
```

```powershell
cd D:\phonecall\phone_call_project
.venv\Scripts\Activate.ps1
python app.py
```

---

## Dừng

- NestJS / Vite: `Ctrl+C` trong terminal tương ứng
- Postgres (giữ data):

```powershell
cd D:\phonecall\restaurant-backend
docker compose stop
```

Bật lại: `docker compose up -d`.

---

## Gặp lỗi thường gặp

| Hiện tượng | Cách xử lý |
| --- | --- |
| `ECONNREFUSED` cổng 5433 | `docker compose up -d` trong `restaurant-backend` |
| API fail vì SSL | `DB_SSL=false` trong `.env` backend |
| Cổng 3000/3001 đã chiếm | Đóng process cũ, hoặc đổi `PORT` / Vite `port` rồi sửa `VITE_API_URL` |
| Dashboard trống | DB mới; tạo restaurant trên UI |
| AI Bridge không đặt bàn / đặt món | API chưa chạy, hoặc hotline không khớp nhà hàng trong DB |
