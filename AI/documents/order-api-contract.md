# Hợp đồng API thực đơn và đơn hàng (phone AI)

**Trạng thái:** khớp Swagger backend — `GET /menu/branch/{branchId}`, `POST /menu/delivery/ai`, `POST /menu/takeout/ai`  
**Chủ sở hữu (khi implement):** team backend nhà hàng  
**Client AI:** [`order/client.py`](../order/client.py)  
**Base URL:** cùng `RESTAURANT_API_BASE` với đặt bàn

Tài liệu này mô tả path/body mà process AI **đang gọi**. Khi API thật khác tên field, chỉ sửa `order/client.py` (và file này). Tên tool LLM không đổi.

Thanh toán v1: **COD** (trả khi nhận / lúc lấy). AI không thu thẻ trên điện thoại. AI **không** gọi `PATCH .../confirm` và **không** trừ kho.

Chi nhánh lấy từ catalog hotline cuộc gọi (`GET /restaurants/by-hotline/{digits}`), khóa bằng `resolve_branch` / `confirm_branch`. Không GET menu và không POST đơn khi chưa có `branch_id`.

---

## 1. Lấy thực đơn

Một path, bắt buộc `branchId` đã khóa:

`GET /menu/branch/{branchId}`

Thiếu `branch_id` → không HTTP; tool trả `{ ok: false, error: "no_branch" }`. Không fallback `/restaurants/.../menu` hay `/menus`. 404 / mạng / JSON hỏng: tool báo lỗi, AI không bịa menu.

Bọc `{ "success": true, "data": ... }` vẫn parse (giống booking). `data` có thể là mảng món, hoặc object có `items` / `menu` / `products`.

Mỗi món (map theo `CreateMenuItemDto` + id NestJS):

| Field | Bắt buộc | Ghi chú |
| --- | --- | --- |
| `id` hoặc `menu_item_id` | có | UUID/catalog id; AI không bịa |
| `name` | có | Tên đọc cho khách |
| `price` | không | Số; thiếu thì AI không đọc tiền |
| `currency` | không | Mặc định `VND` |
| `category` | không | |
| `description` | không | |
| `status` | không | `available` → còn bán; `unavailable` / `sold_out` → không cho thêm giỏ |
| `quantity_available` | không | `0` → coi như hết |
| `available` | không | Boolean cũ nếu không có `status`; mặc định còn bán |
| `unit` | không | Ví dụ `tô`, `ly` |

Món thiếu `id` hoặc `name` bị bỏ.

---

## 2. Tạo đơn

Chọn path theo hình thức nhận **trong session**, không fallback:

| Hình thức | Path |
| --- | --- |
| Giao hàng (`delivery`) | `POST /menu/delivery/ai` |
| Mang về (`pickup`) | `POST /menu/takeout/ai` |

Body chung (id lấy từ RAM session, không tin UUID do LLM bịa). `OrderItemDto` chỉ có `menu_item_id` + `quantity` — không có note từng dòng. Ghi chú dòng giỏ gộp vào `note` đơn.

```json
{
  "restaurant_id": "...",
  "branch_id": "...",
  "customer_name": "...",
  "customer_phone": "0901234567",
  "booking_date": "2026-09-04",
  "booking_time": "18:30",
  "items": [{ "menu_item_id": "...", "quantity": 2 }],
  "note": "ít cay; thêm tương"
}
```

Thêm khi delivery (`CreateDeliveryBookingDto`):

| Field | Ghi chú |
| --- | --- |
| `delivery_address` | Bắt buộc |
| `delivery_phone` | = `customer_phone` nếu khách không nêu số khác |
| `delivery_fee` | `0` — AI không tính phí ship; field API bắt buộc. Không đọc ra miệng |
| `estimated_delivery_time` | Cùng `booking_time` |

Pickup **không gửi** field delivery.

AI thu thập đúng field DTO, từng mục một, rồi mới POST. Không bịa. Tool `save_order_details` lưu dần vào RAM; `create_order` từ chối nếu còn thiếu.

**Cả hai hình thức (bắt buộc):**

| Field | Câu hỏi miệng |
| --- | --- |
| Chi nhánh | Khóa trước (`resolve_branch` / `confirm_branch`). Một chi nhánh: tự khóa |
| `items` | Món + số lượng qua `search_menu` / `add_to_cart` |
| `customer_name` | Tên người đặt |
| `customer_phone` | Số điện thoại người đặt |
| `booking_date` | Giao: ngày giao. Mang về: ngày lấy. `YYYY-MM-DD` |
| `booking_time` | Giao: giờ nhận hàng. Mang về: giờ lấy. `HH:MM` |
| `note` | Tùy chọn. Ghi chú dòng giỏ gộp vào đây |

**Chỉ giao hàng** (`CreateDeliveryBookingDto`):

| Field | Câu hỏi miệng |
| --- | --- |
| `delivery_address` | Địa chỉ giao, bắt buộc, qua `set_fulfillment` |
| `delivery_phone` | SĐT người nhận nếu khác số đặt; không khác thì = `customer_phone` |
| `delivery_fee` | AI **không** hỏi; luôn gửi `0` |
| `estimated_delivery_time` | AI **không** hỏi; = `booking_time` |

Thứ tự hỏi: món → giao hay mang về → (nếu giao: địa chỉ, SĐT nhận nếu khác) → tên → SĐT đặt → ngày → giờ → ghi chú. Đọc lại đủ field rồi mới `create_order`.

Response 2xx: `{ "data": { "id": "..." } }` hoặc object đơn. HTTP ≥ 400 / mạng: `{ ok: false }` — AI **không** nói đã đặt xong. 2xx → AI Bridge gửi `order.created` trên WebSocket (demo UI hiện “Đã đặt hàng thành công”).

---

## 3. Không nằm trong v1

- `PATCH /menu/delivery/{id}/confirm` / `PATCH /menu/takeout/{id}/confirm`
- Thanh toán thẻ / QR / trả trước
- Sửa hoặc hủy đơn sau khi API đã nhận
- Tính phí ship thật (gửi `0`)
