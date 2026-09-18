# 12 — Tool đặt món

Files: `AI/order/tools.py` (1053 dòng — file tool lớn nhất), `AI/order/client.py`,
`AI/order/matcher.py`, `AI/order/models.py`.

## Tám tool

| Tool | Làm gì |
| --- | --- |
| `list_menu()` | Lấy thực đơn của chi nhánh đã khóa |
| `search_menu(spoken_name)` | Khớp tên món khách nói với thực đơn |
| `add_to_cart(menu_item_id, quantity, note?)` | Thêm vào giỏ |
| `update_cart(...)` | Đổi số lượng / ghi chú một dòng |
| `remove_from_cart(...)` | Bỏ một dòng |
| `set_fulfillment(fulfillment, address?)` | Chọn `delivery` hoặc `pickup` |
| `save_order_details(...)` | Lưu tên, SĐT, ngày, giờ, ghi chú, địa chỉ — **lưu ngay khi nghe được** |
| `create_order(...)` | Ghi đơn xuống backend |

## Luồng điển hình

```
khách bấm 2/3  hoặc nói "tôi muốn đặt món"
      │
      ├─ chưa khóa chi nhánh?  → resolve_branch (chương 11)
      │
      ├─ "có món gì?"          → list_menu → đọc VÀI tên, không đọc hết
      ├─ "cho tôi Caesar salad" → search_menu → add_to_cart
      ├─ "thêm một cái nữa"     → update_cart
      │
      ├─ set_fulfillment("pickup")
      ├─ save_order_details(name=..., phone=..., date=..., time=...)
      │
      ├─ AI đọc lại toàn bộ đơn, chờ khách đồng ý
      └─ create_order → POST /menu/takeout/ai hoặc /menu/delivery/ai
```

## `search_menu` — bốn tầng

Giống `resolve_branch`, rẻ trước đắt sau:

```
1. So khớp chính xác sau chuẩn hóa       (_normalize_item_name)
2. Khớp phiên âm                         (stt/phonetic.py)
3. LLM matcher                           (OpenAiMenuMatcher)
4. _recover_menu_item()                  cứu vãn lần cuối
```

`OpenAiMenuMatcher` có prompt riêng dạy nó bỏ qua từ chỉ số lượng: *"two peach teas",
"two pho bowls"* → khớp món, không khớp "two". Nó trả về `status` (`match` /
`ambiguous` / `none`), `menu_item_id`, `confidence` (`high` / `low`), `confirm_name`.

`_looks_like_menu_browse()` phát hiện khách đang **hỏi xem có gì** chứ không gọi một món
cụ thể ("what do you have", "menu") — lúc đó gọi `search_menu` là vô nghĩa.

Prompt có một luật cứu tình huống bế tắc: *"If search_menu returns none twice in a row,
stop asking them to repeat themselves: call list_menu and read a few dish names."*

## Nạp thực đơn và cache

`_ensure_menu()` theo thứ tự:

1. `session.menu` (đã nạp trong cuộc gọi này)
2. Redis (`_menu_from_cache`)
3. `GET /menu/branch/:branchId` — rồi ghi ngược vào Redis (`_write_through_menu`)

`preload_menu()` được `CallPipeline._load_catalog()` gọi ngay khi biết chi nhánh, **trước
khi** khách kịp nói tên món. Comment giải thích: `OrderTools` chỉ nạp thực đơn khi LLM gọi
`search_menu` — tức là **sau** khi khách đã nói tên món một lượt. Nạp sớm là cách duy nhất
để tên món kịp vào gợi ý STT trước lúc cần.

Chỉ món `available` mới lọt qua `menu_item_from_api()`.

## Giỏ hàng

```python
@dataclass CartLine:  menu_item_id, name, quantity, note, price, currency
```

`_find_cart_index()` có một chi tiết tinh tế:

```python
if len(matches) == 1:  return matches[0]
if not matches:        return -1
return -2   # cùng một món trên hai dòng với ghi chú khác nhau
```

`-2` nghĩa là **"hỏi lại khách"**. Sửa bừa một trong hai dòng là âm thầm sửa nhầm đơn.

## `order_missing_fields()` — bộ đếm còn thiếu gì

Hàm này là bộ não theo dõi tiến độ đơn hàng:

```python
missing = []
if giỏ rỗng:                          missing.append("items")
if chưa chọn delivery/pickup:         missing.append("fulfillment")
elif delivery mà chưa có địa chỉ:     missing.append("delivery_address")
if chưa có tên:                       missing.append("customer_name")
if chưa có SĐT:                       missing.append("customer_phone")
if ngày không đúng YYYY-MM-DD:        missing.append("booking_date")
if chưa có giờ:                       missing.append("booking_time")
```

Kết quả đi vào `order_status_prompt()` → nhét thẳng vào system prompt mỗi lượt, kèm hai
dòng dạng:

```
Order details still missing: orderer phone number, pickup time.
Ask next: ask for orderer phone number.
```

`_missing_spoken()` dịch tên trường sang **lời người nói được**: `booking_time` thành
"drop-off time" nếu giao hàng, "pickup time" nếu lấy tại quán. AI không bao giờ đọc tên
trường kỹ thuật cho khách.

## `create_order` — các lớp chắn

| Kiểm tra | Trả về |
| --- | --- |
| Có nhà hàng | `no_restaurant` |
| Có chi nhánh (tự khóa nếu chỉ có một) | `no_branch` + danh sách chi nhánh |
| Đã tạo rồi | `{"ok": true, "already_created": true}` |
| Giỏ rỗng | `empty_cart` |
| Trường sai định dạng | `invalid_fields` + `next_step` |
| Chưa chọn delivery/pickup | `no_fulfillment` |
| Giao hàng mà thiếu địa chỉ | `no_delivery_address` |
| Thiếu tên/SĐT/ngày/giờ | `missing_fields` + danh sách |

Một lỗi đã từng xảy ra và được comment lại ngay trong code: `create_order` **bỏ qua**
danh sách `invalid` do `_apply_order_details()` trả về. Hậu quả: một số điện thoại hoặc
ngày sai truyền vào đây bị lặng lẽ phớt lờ, đơn đi ra với **giá trị cũ**, trong khi model
tin rằng nó vừa cập nhật thành công.

Có cả một trường hợp đặc biệt được xử lý riêng: `use_caller_number` thất bại vì nhà mạng
không cho số, nhưng khách đã đọc số từ trước → dùng số cũ thay vì báo lỗi.

## Gửi xuống BE

```python
if fulfillment == "delivery":  path = "/menu/delivery/ai"
else:                          path = "/menu/takeout/ai"
```

Body chung: `restaurant_id`, `branch_id`, `customer_name`, `customer_phone`,
`booking_date`, `booking_time`, `items: [{menu_item_id, quantity}]`, `note?`, `call_id`.
Riêng delivery thêm: `delivery_address`, `delivery_phone`, `delivery_fee: 0`,
`estimated_delivery_time`.

Ghi chú của từng dòng giỏ hàng được gộp vào `note` chung (`_merged_note`), vì API của BE
chỉ có một trường ghi chú cho cả đơn.

## Sự kiện `order.created`

Sau khi `create_order` thành công, `CallPipeline._notify_order_created()` bắn một sự kiện
JSON ra socket kèm đầy đủ chi tiết đơn (tên khách, SĐT, chi nhánh, giỏ hàng, tổng tiền,
địa chỉ giao…). UI demo dùng nó để hiện thông báo; backend thoại thật có thể bỏ qua.

## Thanh toán

Prompt nói rõ: tiền mặt khi nhận hàng hoặc khi tới lấy. **Không bao giờ hỏi số thẻ.**

## Tiếp theo

→ [13 — Telnyx: cuộc gọi thật](13-telnyx.md)
