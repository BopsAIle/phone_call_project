# 15 — Backend NestJS

Thư mục `BE/`. Cổng **8070**. Swagger: http://localhost:8070/api-docs

## Đây là gì

Một REST API nhà hàng bình thường, **không biết gì về thoại**. Nó phục vụ hai khách hàng:
dashboard FE và AI Bridge. Cả hai đều chỉ nói HTTP với nó.

Stack: NestJS 12 + TypeORM + PostgreSQL + Swagger + class-validator.

> **Lưu ý về phiên bản:** mọi gói `@nestjs/*` phải **cùng major** (đang là 12.x). Lệch
> major làm app crash ngay lúc khởi động với `ERR_MODULE_NOT_FOUND:
> @nestjs/common/internal`. Sau khi pull code: `cd BE && npm install`.

## Bootstrap — `src/main.ts`

```typescript
app.enableCors({ origin: corsOrigins, ... });     // CORS_ORIGIN, nhiều origin cách bởi dấu phẩy
app.useGlobalPipes(new ValidationPipe({
  whitelist: true,              // cắt trường không khai báo trong DTO
  forbidNonWhitelisted: true,   // hoặc thẳng tay 400 nếu có trường thừa
  transform: true,              // tự ép kiểu theo DTO
}));
SwaggerModule.setup('api-docs', app, document);
await app.listen(process.env.PORT ?? 8070);
```

`forbidNonWhitelisted: true` đáng nhớ: **một trường thừa trong body là HTTP 400**. Đây là
lý do `AI/calls/client.py` in cả thân lỗi khi gặp 4xx — thông báo của ValidationPipe chỉ
hữu ích khi bạn nhìn thấy nó.

## Cấu trúc module

Năm module nghiệp vụ, mỗi module cùng một bộ file:

```
restaurants/  branches/  bookings/  menu/  calls/
    ├── *.controller.ts     route HTTP + Swagger
    ├── *.service.ts        nghiệp vụ
    ├── *.repository.ts     truy vấn TypeORM
    ├── *.module.ts         khai báo DI
    ├── entities/*.ts       bảng database
    └── dto/*.ts            kiểm tra dữ liệu vào
```

Cộng thêm `common/` (filter lỗi + interceptor) và `config/database.config.ts`.

## Interceptor toàn cục bọc mọi response

`TransformInterceptor` bọc **mọi** response thành:

```json
{
  "success": true,
  "message": "Yêu cầu thành công",
  "data": { ... },
  "timestamp": "2026-09-18T02:31:00.000Z",
  "path": "/restaurants"
}
```

Đó là lý do phía AI có hàm `unwrap_data()` (`AI/booking/client.py`): mọi client phải bóc
lớp `data` ra. FE cũng làm tương tự trong `FE/src/api/`.

Ngoài ra: `LoggingInterceptor` (log request) và `AllExceptionsFilter` (chuẩn hóa lỗi).

## Bảy bảng dữ liệu

```
restaurants ──1:N──> branches ──1:N──> menu_items
     │                   │
     └───────┬───────────┘
             v
         bookings ──1:N──> order_items ──N:1──> menu_items

         calls ──1:N──> call_messages
```

| Bảng | Nội dung chính |
| --- | --- |
| `restaurants` | `id`, `name`, `phone` (hotline), `status` |
| `branches` | `id`, `restaurant_id`, `name`, `address`, `phone`, `opening_time`, `closing_time`, `status` |
| `menu_items` | `id`, `branch_id`, `name`, `description`, `price`, `status`, `quantity_available` |
| `bookings` | đơn đặt bàn **và** đơn món — xem dưới |
| `order_items` | `booking_id`, `menu_item_id`, `quantity`, `unit_price`, `subtotal` |
| `calls` | nhật ký một cuộc gọi AI |
| `call_messages` | từng câu trong cuộc gọi |

### `bookings` gánh cả ba loại đơn

Một bảng duy nhất, phân biệt bằng `booking_type`:

| Cột | Ghi chú |
| --- | --- |
| `booking_type` | `DINE_IN` (đặt bàn) / `TAKEOUT` (lấy tại quán) / `DELIVERY` (giao hàng) |
| `source` | mặc định `PHONE_AI` — đơn từ tổng đài AI |
| `status` | `PENDING` → … |
| `call_id` | **nối ngược về cuộc gọi đã tạo ra đơn này** |
| `order_code` | `ORD-20260918-<branch>-0001`, sinh bởi `OrderCodeUtil` |
| `customer_name`, `phone_number`, `party_size`, `booking_date`, `booking_time`, `note` | chung |
| `delivery_address`, `delivery_phone`, `delivery_fee`, `estimated_delivery_time`, `actual_delivery_time`, `shipper_status` | riêng giao hàng |

Cột `call_id` là thứ cho phép tra ngược: khách khiếu nại đơn nào thì mở được đúng
transcript cuộc gọi đó.

### `calls` + `call_messages`

`calls` giữ metadata: `call_id` (id do AI sinh), `restaurant_id`, `branch_id`,
`from_number`, `to_number`, `locale`, `status`, `intent`, `booking_id`, `order_id`,
`started_at`, `ended_at`, `duration_seconds`, `end_reason`.

`call_messages` giữ transcript: `sequence`, `role` (`user` / `assistant` / `tool`),
`content`, `tool_name`, `spoken_at`.

## Các endpoint dành riêng cho AI

Nhận ra chúng nhờ hậu tố `/ai`:

| Endpoint | Ai gọi |
| --- | --- |
| `GET /restaurants/by-hotline/:hotline` | AI, đầu mỗi cuộc gọi |
| `POST /bookings/ai` | AI, `create_booking` |
| `POST /menu/takeout/ai` | AI, `create_order` (pickup) |
| `POST /menu/delivery/ai` | AI, `create_order` (delivery) |
| `POST /calls/ai/start` | AI, khi biết được nhà hàng |
| `POST /calls/ai/:id/messages` | AI, theo lô 10 câu hoặc mỗi 30 giây |
| `POST /calls/ai/:id/end` | AI, lúc `shutdown()` |

Chúng tồn tại riêng vì dữ liệu AI gửi khác dữ liệu form trên dashboard (ví dụ có
`call_id`, không có những trường mà nhân viên phải nhập tay).

### `POST /calls/ai/start` là idempotent

```typescript
const existing = await this.repository.findByCallId(dto.call_id);
if (existing) return existing;      // AI thử lại khi mạng chập chờn
```

Cùng logic chống trùng như `call_id` trong body tạo đơn: mạng chập chờn, gửi lại, vẫn chỉ
một bản ghi.

## Danh sách endpoint đầy đủ

```
GET    /restaurants                     POST   /restaurants
GET    /restaurants/:id                 PATCH  /restaurants/:id
GET    /restaurants/:id/branches        DELETE /restaurants/:id
GET    /restaurants/by-hotline/:hotline

GET    /branches                        POST   /branches
GET    /branches/:id                    PATCH  /branches/:id
GET    /branches/restaurant/:id/count   DELETE /branches/:id

GET    /bookings                        POST   /bookings
GET    /bookings/stats                  POST   /bookings/ai
GET    /bookings/:id                    PATCH  /bookings/:id
GET    /bookings/branch/:id/date/:date  DELETE /bookings/:id

GET    /menu/:id                        POST   /menu
GET    /menu/branch/:branchId           PATCH  /menu/:id
GET    /menu/order/:bookingId/items     DELETE /menu/:id
POST   /menu/takeout/ai                 PATCH  /menu/takeout/:bookingId/confirm
POST   /menu/delivery/ai                PATCH  /menu/delivery/:bookingId/confirm

GET    /calls                           POST   /calls/ai/start
GET    /calls/:id                       POST   /calls/ai/:id/messages
GET    /calls/by-call-id/:callId        POST   /calls/ai/:id/end
```

Bản đầy đủ có schema: mở Swagger tại `/api-docs`.

## Database

`synchronize: true` trong `src/config/database.config.ts`: TypeORM **tự tạo/sửa bảng** theo
entity mỗi lần khởi động. Tiện cho dev, **nguy hiểm cho production** (có thể mất dữ liệu).
Lên production phải chuyển sang migration.

`DB_SSL=true` cho Postgres cloud (Neon…), `false` cho Docker local.

## ⚠️ Không có xác thực

NestJS ở đây **không có guard, không JWT, không đăng nhập**. Ai gọi được API là đọc/ghi
được mọi thứ. Chấp nhận được khi chạy local; **không** khi mở ra Internet. Nếu mở qua
tunnel, hãy bật Cloudflare Access (Zero Trust) cho hostname, hoặc chỉ mở khi đang test.

## Tiếp theo

→ [16 — Frontend dashboard](16-frontend-dashboard.md)
