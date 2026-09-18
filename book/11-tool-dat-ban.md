# 11 — Tool đặt bàn

Files: `AI/booking/tools.py`, `AI/booking/client.py`, `AI/booking/matcher.py`,
`AI/booking/models.py`.

## "Tool" là gì

Tool (function calling) là cách LLM **làm việc thật** thay vì chỉ nói. Ta mô tả cho model
một hàm bằng JSON Schema; khi model quyết định cần dùng, nó trả về tên hàm + đối số;
code Python chạy hàm đó và trả kết quả về cho model đi tiếp.

Trong dự án này, tool được đăng ký trong `_run_reply()`:

```python
tools = BOOKING_TOOLS + ORDER_TOOLS          # 3 + 8 = 11 tool
kwargs["execute_tool"] = self._execute_tool  # cầu nối tới BookingTools / OrderTools
```

Mọi tool đều trả về **một chuỗi JSON**, và LLM đọc chuỗi đó như kết quả.

## Ba tool đặt bàn

| Tool | Làm gì |
| --- | --- |
| `resolve_branch(spoken_name)` | So lời khách nói với danh sách chi nhánh của cuộc gọi này |
| `confirm_branch(branch_id)` | Khóa chi nhánh sau khi khách xác nhận |
| `create_booking(...)` | Ghi đơn đặt bàn xuống backend |

### `resolve_branch` — quy trình ba tầng

Không gọi thẳng LLM ngay. Thứ tự rẻ-trước-đắt-sau:

```
1. Chuẩn hóa bí danh địa danh   (regex, ~0 ms)
      "TP HCM", "TPHCM", "Sài Gòn", "hát xê em" → "Hồ Chí Minh"
2. Khớp phiên âm                (stt/phonetic.py, vài µs)
      trúng với điểm ≥ 0.75 và hơn á quân 0.20 → xong, không gọi LLM
3. LLM matcher                  (OpenAiBranchMatcher, một round-trip)
      trả về: status = match | ambiguous | none, kèm confidence
```

Kết quả trả cho LLM:

- `match` + `high` → tự khóa chi nhánh
- `match` + `low`, hoặc `ambiguous` → trả danh sách ứng viên, prompt bắt AI hỏi lại rồi
  gọi `confirm_branch`
- `none` → trả `available_branches`, prompt bắt AI nói "chỗ đó không phải của chúng tôi"
  và đọc tên các chi nhánh thật

Matcher chỉ được chọn **trong danh sách gửi kèm request** — system prompt của matcher ghi
rõ *"Do not search restaurants outside the list"*. Đây là rào chắn chống bịa.

### Cửa chắn rẻ trước matcher

Trong `_run_reply()` có một tối ưu:

```python
if (chưa khóa chi nhánh và có nhiều hơn 1 chi nhánh
    and looks_like_branch_mention(text, branches)):
        await self._booking.resolve_branch(text)     # khóa trước, trong cùng lượt
```

`looks_like_branch_mention()` là kiểm tra chuỗi rẻ tiền. Không có dấu hiệu nào chỉ tới
chi nhánh thì bỏ qua hẳn một lần gọi OpenAI nối tiếp trước lượt nói chính — tiết kiệm cả
tiền lẫn độ trễ.

### `create_booking` — bảo vệ nhiều lớp

Đọc `AI/booking/tools.py:369`. Trước khi gửi bất cứ thứ gì đi:

| Kiểm tra | Trả về khi hỏng |
| --- | --- |
| Có nhà hàng không | `{"ok": false, "error": "no_restaurant"}` |
| Đã khóa chi nhánh chưa | `{"ok": false, "error": "no_branch"}` |
| Đã tạo đơn trong cuộc gọi này rồi? | `{"ok": true, "already_created": true}` |
| Thiếu trường nào | `{"ok": false, "error": "missing_fields", "fields": [...]}` |
| `party_size` hợp lệ (1–50) | `{"ok": false, "error": "invalid_party_size"}` |

**Phân biệt "số điện thoại sai" và "chưa cho số".** Nếu khách *có* đưa số nhưng số đó
không dùng được, tool trả `invalid_phone` kèm `next_step: "ask the caller to say the
number again, digit by digit"` — chứ không trả `missing_fields`. Lý do ghi trong comment:
`missing_fields` khiến model hỏi lại từ đầu như chưa từng hỏi, và đến lần thứ ba thì khách
phát điên.

**`use_caller_number: true`** → lấy số **từ nhà mạng** (`session.from_number`), không dùng
chuỗi model tự gõ lại. Con người đọc nhầm số, model nghe nhầm số; số của nhà mạng thì
không.

**`customer_response`** là một tham số thú vị: model phải kèm **một câu ngắn nói ngay lúc
này** trong khi request đang bay (*"Alright, I am placing that order now."*). Schema ghi rõ
dưới ~12 từ, thì hiện tại, và **tuyệt đối không được nói là đã thành công** — vì lúc đó
chưa ai biết kết quả.

**Chống trùng đơn.** `call_id` được gửi kèm body. POST bị timeout rồi gửi lại cũng chỉ ra
một đơn duy nhất.

## Chuẩn hóa ngày giờ

Người nói không đọc `YYYY-MM-DD`. `AI/booking/tools.py` có sẵn:

- `normalize_booking_date("tomorrow", tz)` → ngày mai **theo múi giờ nhà hàng**
- `normalize_booking_time("7 PM")` → `"19:00"`
- `resolve_booking_when(date, time, tz)` — ghép cả hai, xử lý cả trường hợp model nhét
  giờ vào ô ngày
- `normalize_customer_phone()` — dọn số điện thoại

System prompt cũng bảo model tự quy đổi, nhưng tool vẫn chuẩn hóa lần nữa. Hai lớp: model
có thể sai, tool thì tất định.

## Gửi xuống BE — `AI/booking/client.py`

```python
async def create_booking(self, body):
    result = await self._post_booking("/bookings/ai", _ai_booking_body(body))
    if result.ok:
        return result
    logger.warning("POST /bookings/ai failed; falling back to POST /bookings")
    return await self._post_booking("/bookings", _public_booking_body(body))
```

Có **đường dự phòng**: endpoint chuyên cho AI hỏng thì thử endpoint công khai với body
khác. Hai hàm `_ai_booking_body` / `_public_booking_body` dựng đúng hình dạng cho từng
endpoint.

`find_by_hotline()` thì **thử lại một lần** khi lỗi mạng (ngủ 0,8 giây), vì nó chạy ngay
đầu cuộc gọi và hỏng là mất cả cuộc gọi.

## Mô hình dữ liệu — `AI/booking/models.py`

```python
@dataclass Restaurant:  id, name, status, branches: list[Branch]
@dataclass Branch:      id, name, address, phone, opening_time, closing_time, status
@dataclass MatchResult: status, branch_id, confidence, confirm_name
```

Chi nhánh không `active` bị lọc ngay ở `restaurant_from_api()` — chúng không bao giờ lọt
vào cuộc gọi.

## Tiếp theo

→ [12 — Tool đặt món](12-tool-dat-mon.md)
