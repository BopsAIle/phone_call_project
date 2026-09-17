# Tính năng Takeout (Mang về) - Hướng dẫn đầy đủ

## 📋 Tổng quan

Feature takeout cho phép khách hàng gọi lễ tân AI để đặt đồ ăn mang về thay vì ăn tại chỗ. Hệ thống sẽ:
- Quản lý menu items cho từng chi nhánh
- Tạo booking với loại TAKEOUT
- Lưu chi tiết order items (số lượng, giá)
- Tính tổng giá tự động

---

## 🏗️ Cấu trúc dữ liệu

### 1. **Booking Entity** (cập nhật)
```sql
ALTER TABLE bookings ADD COLUMN booking_type ENUM('dine_in', 'takeout', 'delivery') DEFAULT 'dine_in';
ALTER TABLE bookings ADD COLUMN total_price DECIMAL(10,2);
ALTER TABLE bookings MODIFY party_size INT NULL;
```

**Fields mới:**
- `booking_type` - Loại booking (DINE_IN, TAKEOUT, DELIVERY)
- `total_price` - Tổng giá tiền
- `party_size` - Giờ nullable (không cần cho TAKEOUT)

### 2. **MenuItem Entity** (tạo mới)
```sql
CREATE TABLE menu_items (
  id UUID PRIMARY KEY,
  branch_id UUID NOT NULL,
  name VARCHAR(255) NOT NULL,
  description TEXT,
  price DECIMAL(10,2) NOT NULL,
  status ENUM('available', 'unavailable', 'sold_out') DEFAULT 'available',
  quantity_available INT DEFAULT 1000,
  created_at TIMESTAMP,
  updated_at TIMESTAMP,
  FOREIGN KEY (branch_id) REFERENCES branches(id) ON DELETE CASCADE
);
```

### 3. **OrderItem Entity** (tạo mới)
```sql
CREATE TABLE order_items (
  id UUID PRIMARY KEY,
  booking_id UUID NOT NULL,
  menu_item_id UUID NOT NULL,
  quantity INT NOT NULL,
  unit_price DECIMAL(10,2) NOT NULL,
  subtotal DECIMAL(10,2) NOT NULL,
  created_at TIMESTAMP,
  updated_at TIMESTAMP,
  FOREIGN KEY (booking_id) REFERENCES bookings(id) ON DELETE CASCADE,
  FOREIGN KEY (menu_item_id) REFERENCES menu_items(id) ON DELETE CASCADE
);
```

---

## 🔌 API Endpoints

### Menu Management

#### 1. Tạo Menu Item
```http
POST /menu
Content-Type: application/json

{
  "branch_id": "uuid",
  "name": "Phở bò",
  "description": "Phở bò tươi, nước dùng thơm ngon",
  "price": 45000,
  "status": "available",
  "quantity_available": 100
}
```

**Response (201):**
```json
{
  "id": "uuid",
  "branch_id": "uuid",
  "name": "Phở bò",
  "description": "Phở bò tươi...",
  "price": 45000,
  "status": "available",
  "quantity_available": 100,
  "created_at": "2024-08-25T12:00:00Z",
  "updated_at": "2024-08-25T12:00:00Z"
}
```

#### 2. Lấy Menu của Chi nhánh
```http
GET /menu/branch/{branchId}
```

**Response (200):**
```json
[
  {
    "id": "uuid",
    "name": "Phở bò",
    "price": 45000,
    "status": "available",
    "quantity_available": 100
  },
  {
    "id": "uuid",
    "name": "Cơm tấm",
    "price": 35000,
    "status": "available",
    "quantity_available": 50
  }
]
```

#### 3. Cập nhật Menu Item
```http
PATCH /menu/{menuItemId}
Content-Type: application/json

{
  "status": "sold_out",
  "quantity_available": 0
}
```

#### 4. Xóa Menu Item
```http
DELETE /menu/{menuItemId}
```

---

### Takeout Booking

#### 1. Tạo Đơn Mang Về (từ AI Voice)
```http
POST /menu/takeout/ai
Content-Type: application/json

{
  "restaurant_id": "uuid",
  "branch_id": "uuid",
  "customer_name": "Nguyễn Văn A",
  "customer_phone": "0123456789",
  "booking_date": "2024-08-25",
  "booking_time": "12:30",
  "items": [
    {
      "menu_item_id": "uuid",
      "quantity": 2
    },
    {
      "menu_item_id": "uuid",
      "quantity": 1
    }
  ],
  "note": "Không ớt, thêm cơm chiên"
}
```

**Response (201):**
```json
{
  "id": "booking-uuid",
  "restaurant_id": "uuid",
  "branch_id": "uuid",
  "customer_name": "Nguyễn Văn A",
  "phone_number": "0123456789",
  "booking_date": "2024-08-25",
  "booking_time": "12:30",
  "booking_type": "takeout",
  "total_price": 125000,
  "note": "Không ớt, thêm cơm chiên",
  "source": "phone_ai",
  "status": "pending",
  "order_items": [
    {
      "id": "order-item-uuid",
      "booking_id": "booking-uuid",
      "menu_item_id": "uuid",
      "quantity": 2,
      "unit_price": 45000,
      "subtotal": 90000
    },
    {
      "id": "order-item-uuid",
      "booking_id": "booking-uuid",
      "menu_item_id": "uuid",
      "quantity": 1,
      "unit_price": 35000,
      "subtotal": 35000
    }
  ]
}
```

#### 2. Lấy Chi tiết Order Items
```http
GET /menu/order/{bookingId}/items
```

**Response (200):**
```json
[
  {
    "id": "order-item-uuid",
    "booking_id": "booking-uuid",
    "menu_item_id": "uuid",
    "quantity": 2,
    "unit_price": 45000,
    "subtotal": 90000,
    "menu_item": {
      "id": "uuid",
      "name": "Phở bò",
      "price": 45000,
      "status": "available"
    }
  }
]
```

---

## 🎯 Flow hoạt động

### 1. Khách hàng gọi đặt hàng mang về

```
Khách hàng gọi
    ↓
AI lấy thông tin (số điện thoại chi nhánh)
    ↓
API GET /restaurants/by-hotline/:hotline → Lấy restaurant_id
    ↓
API GET /restaurants/{id}/branches → Lấy danh sách branches
    ↓
AI gợi ý: "Chọn chi nhánh nào?"
    ↓
Khách chọn → AI lấy menu
    ↓
API GET /menu/branch/{branchId} → Lấy danh sách items
    ↓
AI gợi ý menu cho khách
    ↓
Khách chọn items
    ↓
API POST /menu/takeout/ai → Tạo booking
    ↓
Booking được tạo, status = PENDING
    ↓
Nhà hàng xác nhận qua admin dashboard
```

---

## 📝 Validation Rules

### Khi tạo Takeout Booking:

1. ✅ Restaurant phải ACTIVE
2. ✅ Branch phải ACTIVE
3. ✅ Branch phải thuộc Restaurant
4. ✅ Booking date không được trong quá khứ
5. ✅ Booking date tối đa 3 tháng tới
6. ✅ Booking time phải nằm trong giờ mở cửa chi nhánh
7. ✅ Items list không được rỗng
8. ✅ Tất cả menu items phải tồn tại
9. ✅ Menu items phải AVAILABLE (không SOLD_OUT)
10. ✅ Quantity phải ≤ quantity_available của item

### Validation lỗi:

```
400 - Chi nhánh hiện không hoạt động
400 - Không thể đặt hàng cho ngày trong quá khứ
400 - Chi nhánh chỉ mở cửa từ HH:MM đến HH:MM
400 - Phải có ít nhất 1 item trong đơn hàng
404 - Menu item không được tìm thấy
400 - {name} hiện không khả dụng (trạng thái: unavailable)
400 - {name} chỉ còn X phần
```

---

## 🔄 Workflow Update Booking

### Thay đổi trạng thái booking:
```
PENDING → CONFIRMED (Nhà hàng xác nhận)
       → CANCELLED (Khách hủy)

CONFIRMED → COMPLETED (Khách lấy hàng)
         → CANCELLED (Hủy trước khi lấy)
         → NO_SHOW (Khách không đến lấy)

CANCELLED/COMPLETED/NO_SHOW → (Không thay đổi được)
```

### Update booking:
```http
PATCH /bookings/{bookingId}
Content-Type: application/json

{
  "status": "confirmed",
  "note": "Chuẩn bị hàng rồi"
}
```

---

## 🛠️ Code Structure

```
src/menu/
├── entities/
│   ├── menu-item.entity.ts          # MenuItem model
│   └── order-item.entity.ts         # OrderItem model
├── dto/
│   ├── create-menu-item.dto.ts      # DTO tạo menu
│   └── create-takeout-booking.dto.ts # DTO tạo takeout
├── menu.repository.ts               # Menu CRUD
├── order-item.repository.ts         # OrderItem CRUD
├── menu.service.ts                  # Business logic
├── menu.controller.ts               # API endpoints
└── menu.module.ts                   # Module registration

src/bookings/
├── entities/
│   └── booking.entity.ts            # Cập nhật: +booking_type, +total_price, party_size nullable
├── bookings.service.ts              # Cập nhật: +createFromDto()
└── dto/
    └── create-booking.dto.ts        # Cập nhật: +booking_type field
```

---

## 💾 Migration Commands (TypeORM)

```bash
# Generate migration
npm run typeorm migration:generate -- -n AddTakeoutFields

# Run migration
npm run typeorm migration:run

# Revert migration
npm run typeorm migration:revert
```

**Auto-sync option:** File config/database.config.ts có `synchronize: true`, nên entity thay đổi sẽ tự sync với DB (dev only).

---

## 🧪 Testing Flow

### 1. Tạo menu items
```bash
curl -X POST http://localhost:8080/menu \
  -H "Content-Type: application/json" \
  -d '{
    "branch_id": "branch-uuid",
    "name": "Phở bò",
    "price": 45000,
    "status": "available",
    "quantity_available": 50
  }'
```

### 2. Lấy menu
```bash
curl http://localhost:8080/menu/branch/{branchId}
```

### 3. Tạo takeout booking
```bash
curl -X POST http://localhost:8080/menu/takeout/ai \
  -H "Content-Type: application/json" \
  -d '{
    "restaurant_id": "rest-uuid",
    "branch_id": "branch-uuid",
    "customer_name": "Nguyễn Văn A",
    "customer_phone": "0123456789",
    "booking_date": "2024-08-25",
    "booking_time": "12:30",
    "items": [
      {"menu_item_id": "item-uuid-1", "quantity": 2},
      {"menu_item_id": "item-uuid-2", "quantity": 1}
    ],
    "note": "Không ớt"
  }'
```

### 4. Lấy order items
```bash
curl http://localhost:8080/menu/order/{bookingId}/items
```

---

## ❗ Lưu ý quan trọng

1. **Database Migration**: Chạy migration để thêm columns vào bookings table trước khi deploy
2. **Party Size**: Với DINE_IN vẫn bắt buộc, TAKEOUT không bắt buộc
3. **Total Price**: Tự động tính từ items, không cần input
4. **Source**: Tất cả takeout bookings từ AI sẽ có source = PHONE_AI
5. **Duplicate Check**: Vẫn kiểm tra duplicate dựa trên phone + time + branch
6. **TypeORM**: Entities đã config `synchronize: true` ở database.config.ts

---

## 📞 Hỗ trợ

Cần thêm feature gì không?
- Giao hàng (DELIVERY)?
- Quản lý tài xế?
- Tracking real-time?
- Payment integration?

Hãy ping để discuss! 🚀
