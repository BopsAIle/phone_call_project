# Tài liệu API — Phone AI đặt bàn nhà hàng

Hệ thống gồm **3 service HTTP** (FastAPI). Voice agent gọi Booking API; trình duyệt máy ảo gọi Browser sim, rồi Browser sim chuyển tiếp sang Voice agent.

| Service | Cổng mặc định | Base URL local | Vai trò |
| --- | ---: | --- | --- |
| Voice agent | 8000 | `http://127.0.0.1:8000` | Hội thoại (chữ / LLM + STT/TTS), RAG, điều phối đặt bàn |
| Booking API | 8001 | `http://127.0.0.1:8001` | Session, slot, chỗ ngồi, mã đặt bàn (store **in-memory**) |
| Browser simulator | 8002 | `http://127.0.0.1:8002` | Trang UI điện thoại; proxy `/browser/*` sang cổng 8000 |

Swagger Booking API: `http://127.0.0.1:8001/docs`. Contract YAML: `specs/openapi.yaml` (một phần endpoint; file này mô tả **đúng code hiện tại**).

Mọi request/response JSON dùng UTF-8. Thời gian trong model Pydantic: `date` = `YYYY-MM-DD`, `time` = `HH:MM:SS`, datetime = ISO 8601 UTC.

---

## Luồng tổng thể

```
Khách (trình duyệt :8002)
    │  POST /browser/voice
    │  POST /browser/{session_id}/utterance
    ▼
Browser sim (:8002)  ──forward──►  Voice agent (:8000)
                                       │
                                       │  /v1/call-sessions, /slots, /availability,
                                       │  /bookings, /transfer, /transcript, ...
                                       ▼
                                 Booking API (:8001)
```

- **API chữ** (`POST /text/start` → `POST /text/{id}/turn` trên cổng 8000) dùng `DialogEngine`: extract heuristic, không gọi OpenAI cho từng lượt.
- **API trình duyệt** (`POST /browser/voice` → `POST /browser/{id}/utterance`) dùng GPT (tool calling) + STT/TTS khi khách nói.

Store Booking API **mất hết khi restart process**. Session hội thoại LLM trên Voice agent cũng chỉ nằm RAM (`BrowserChatStore`).

---

## Quy tắc nghiệp vụ dùng chung

| Quy tắc | Chi tiết |
| --- | --- |
| Chi nhánh | `quan-1` (Quận 1, 40 chỗ, 22 Đồng Khởi) và `thao-dien` (Thảo Điền, 24 chỗ, 115 Nguyễn Văn Hưởng) |
| Alias chi nhánh | Ví dụ: `Quận 1`, `q1`, `Đồng Khởi` → `quan-1`; `Thảo Điền`, `q2` → `thao-dien` |
| Giờ nhận khách | **11:00–22:00** (cả hai đầu mốc đều hợp lệ) |
| Làm tròn giờ | Phút `< 30` → `:00`; phút `≥ 30` → `:30`. Ví dụ `19:15` → `19:00`, `19:40` → `19:30` |
| Số khách kiểm chỗ | `1`–`20` (`MAX_PARTY`) |
| Nhóm lớn | `guest_count > 12` → chuyển lễ tân (`large_party`) |
| Slot bắt buộc | `customer_name`, `phone`, `guest_count`, `date`, `time`; thêm `branch` nếu `multi_branch=true` |
| Nguồn booking | Mặc định `"Phone AI"` |
| Dữ liệu seed | `quan-1` ngày `2026-12-24` 19:00 hết chỗ (40/40); 18:00 đã chiếm 10; 20:00 đã chiếm 8 |

Thứ tự hỏi slot khi còn thiếu (reception): tên → SĐT → số khách → ngày → giờ → chi nhánh.

---

## Mô hình dữ liệu dùng chung

### `BookingSlots`

Thông tin đặt bàn gắn trên session.

| Trường | Kiểu | Mô tả |
| --- | --- | --- |
| `guest_count` | `int \| null` | Số khách |
| `date` | `date \| null` | Ngày đến |
| `time` | `time \| null` | Giờ đến (sau khi PATCH sẽ bị bucket `:00`/`:30`) |
| `branch` | `string \| null` | Mã chi nhánh: `quan-1` hoặc `thao-dien` |
| `customer_name` | `string \| null` | Tên khách |
| `phone` | `string \| null` | Số điện thoại |
| `notes` | `string \| null` | Ghi chú (sinh nhật, trẻ em, …) |
| `source` | `string` | Mặc định `"Phone AI"` |

### `SlotDelta`

Cùng các trường slot ở trên, **tất cả optional**. Chỉ field `!= null` mới được ghi đè. Dùng cho `PATCH .../slots`.

### `CallSession`

| Trường | Kiểu | Mô tả |
| --- | --- | --- |
| `id` | `string` (UUID) | ID session |
| `call_sid` | `string \| null` | ID cuộc gọi (Twilio-like hoặc `CA-browser-...`) |
| `from_number` | `string \| null` | Số gọi đến (raw) |
| `recording_id` | `string \| null` | ID file ghi âm (nếu có) |
| `multi_branch` | `bool` | `true`: bắt buộc hỏi chi nhánh |
| `slots` | `BookingSlots` | Slot hiện tại |
| `transcript` | `TranscriptTurn[]` | Nhật ký hội thoại |
| `availability_fail_count` | `int` | Số lần kiểm chỗ **thất bại** (tăng khi `POST /v1/availability/check` trả `available=false` và có `session_id`) |
| `stt_fail_count` | `int` | (trên session; Voice agent còn đếm fail STT riêng trong RAM) |
| `transferred` | `bool` | Đã chuyển lễ tân |
| `transfer_reason` | `string \| null` | Lý do chuyển |
| `booking_id` | `string \| null` | Mã bàn nếu đã đặt |
| `status` | enum | `collecting` → `ready_to_confirm` → `booked` \| `transferred` |
| `created_at` | datetime UTC | Thời điểm tạo |

### `TranscriptTurn`

| Trường | Kiểu | Mô tả |
| --- | --- | --- |
| `role` | `"user"` \| `"assistant"` \| `"system"` | Người nói |
| `content` | `string` | Nội dung |
| `ts` | datetime UTC | Thời điểm (tự gán nếu client không gửi) |

### `AvailabilityResponse`

| Trường | Kiểu | Mô tả |
| --- | --- | --- |
| `available` | `bool` | Còn đủ chỗ cho `guest_count` |
| `guest_count` | `int` | Số khách đã kiểm |
| `date` | `date` | Ngày đã kiểm (không đổi) |
| `time` | `time` | Giờ **đã bucket** |
| `branch` | `string` | Mã chi nhánh đã chuẩn hóa |
| `remaining_seats` | `int` | Chỗ còn lại = capacity − occupancy |
| `alternatives` | `TimeAlternative[]` | Tối đa **3** khung gợi ý (chỉ khi hết chỗ) |
| `message` | `string` | `"Còn chỗ."` hoặc `"Hết chỗ khung giờ này."` (+ số gợi ý) |

`TimeAlternative`: `{ date, time, branch }`.

Thuật toán gợi ý (cùng số khách, bỏ qua đúng khung đang hết): lần lượt thử **−60, +60, −30, +30, −120, +120 phút** cùng chi nhánh → **ngày hôm sau cùng giờ** → **chi nhánh kia cùng ngày/giờ**. Bỏ khung ngoài 11:00–22:00.

### `BookingRecord`

| Trường | Kiểu | Mô tả |
| --- | --- | --- |
| `id` | `string` | `BK-` + 8 hex viết hoa, ví dụ `BK-A1B2C3D4` |
| `session_id` | `string` | Session nguồn |
| `slots` | `BookingSlots` | Snapshot lúc xác nhận |
| `transcript` | `TranscriptTurn[]` | Bản ghi cuộc gọi |
| `recording_id` | `string \| null` | File ghi âm |
| `source` | `string` | Nguồn tạo |
| `created_at` | datetime UTC | Thời điểm tạo |

---

# 1. Booking API — cổng 8001

Backend “nhà hàng”: lưu session, occupancy, booking **trong RAM**. Voice agent và test gọi trực tiếp các endpoint này.

---

## `GET /health`

Kiểm tra process còn sống.

**Đầu vào:** không.

**Đầu ra `200`:**

```json
{ "status": "ok" }
```

**Xử lý:** trả cố định, không đụng store.

---

## `POST /v1/call-sessions`

Tạo session cuộc gọi mới. Voice agent gọi khi khách nhấc máy hoặc bắt đầu chat chữ.

### Đầu vào (JSON body)

| Trường | Kiểu | Bắt buộc | Mặc định | Ý nghĩa |
| --- | --- | --- | --- | --- |
| `call_sid` | `string \| null` | không | `null` | Định danh cuộc gọi |
| `from_number` | `string \| null` | không | `null` | Caller ID |
| `recording_id` | `string \| null` | không | `null` | Ghi âm sẵn (hiếm) |
| `multi_branch` | `bool` | không | `true` | Có hỏi chi nhánh hay không |

Ví dụ:

```json
{
  "call_sid": "CA-browser-abc123",
  "from_number": "+84901234567",
  "multi_branch": true
}
```

### Đầu ra `200` — `CallSession`

Session mới, `status = "collecting"`, `id` = UUID.

### Cách xử lý

1. Sinh `id = uuid4()`.
2. Tạo `BookingSlots()` rỗng.
3. Nếu `multi_branch === false` → gán sẵn `slots.branch = "quan-1"`.
4. Chuẩn hóa caller ID (`_usable_caller_id`):
   - Bỏ nếu rỗng.
   - Chỉ giữ ký tự số và `+`; nếu còn **dưới 8 ký tự** → không dùng.
   - Bỏ nếu `from_number` bắt đầu `client:` (browser WebRTC giả).
   - Bỏ nếu `anonymous` / `restricted`.
   - Ngược lại gán `slots.phone = from_number` (nguyên chuỗi gốc).
5. Lưu `store.sessions[id] = session` và trả về.

Không tạo occupancy, không tạo booking.

---

## `GET /v1/call-sessions/{session_id}`

Đọc session hiện tại.

### Đầu vào

| Vị trí | Tên | Kiểu | Bắt buộc |
| --- | --- | --- | --- |
| path | `session_id` | UUID string | có |

### Đầu ra

- `200`: `CallSession`
- `404`: `{ "detail": "Session not found" }`

### Cách xử lý

Tra `store.sessions`. Không đổi trạng thái.

---

## `PATCH /v1/call-sessions/{session_id}/slots`

Ghi **delta** slot từ lượt nói hiện tại (chỉ field được gửi). Voice agent / tool `update_slots` gọi endpoint này.

### Đầu vào

**Path:** `session_id`.

**Body `SlotDelta`** — mọi field optional:

```json
{
  "guest_count": 4,
  "date": "2026-08-25",
  "time": "19:15:00",
  "branch": "Quận 1",
  "customer_name": "Lan",
  "phone": "0901234567",
  "notes": "sinh nhật"
}
```

### Đầu ra `200` — `SlotPatchResponse`

| Trường | Kiểu | Ý nghĩa |
| --- | --- | --- |
| `session` | `CallSession` | Session sau khi (hoặc trước khi) merge |
| `missing_fields` | `string[]` | Slot còn thiếu, theo thứ tự hỏi |
| `validation_errors` | `string[]` | Lỗi tiếng Việt nếu delta không hợp lệ |
| `should_transfer` | `bool` | `true` nếu số khách `> 12` |
| `transfer_reason` | `string \| null` | `"large_party"` khi cần chuyển |

### Cách xử lý

1. Lấy session; `404` nếu không có.
2. **Validate + chuẩn hóa** delta (`_normalize_delta`). Nếu **có lỗi**, **không ghi slot**, trả session cũ kèm `validation_errors`:
   - `guest_count < 1` → `"So khach phai lon hon 0."`
   - `date` trước **hôm nay** theo `Asia/Ho_Chi_Minh` → `"Ngày đặt không được ở quá khứ."`
   - `time` bị bucket rồi kiểm 11:00–22:00; ngoài khung → `"Giờ đến ngoài khung mở cửa 11:00–22:00."`
   - `branch` không map được vào `quan-1` / `thao-dien` → `"Chi nhánh không hợp lệ."`; nếu hợp lệ thì ghi **mã chuẩn**.
3. Nếu hợp lệ: `slots = apply_delta(slots, delta)` (chỉ ghi field có giá trị; `branch` chuẩn hóa lần nữa).
4. Nếu `guest_count > 12` → `should_transfer=true`, `transfer_reason="large_party"` (**chưa** đổi `status`; Voice agent mới gọi `/transfer`).
5. Tính `missing_fields` theo `multi_branch`.

**Lưu ý:** endpoint này **không** kiểm chỗ. Occupancy chỉ đổi khi tạo booking thành công.

---

## `POST /v1/availability/check`

Kiểm tra còn đủ ghế cho một khung (sau khi đã bucket giờ).

### Đầu vào (JSON)

| Trường | Kiểu | Bắt buộc | Ý nghĩa |
| --- | --- | --- | --- |
| `guest_count` | `int` | có | Số khách |
| `date` | `date` | có | Ngày |
| `time` | `time` | có | Giờ (sẽ bucket) |
| `branch` | `string` | có | Tên hoặc mã chi nhánh |
| `session_id` | `string \| null` | không | Nếu có: cập nhật đếm fail / status session |

```json
{
  "session_id": "…uuid…",
  "guest_count": 4,
  "date": "2026-12-24",
  "time": "19:00:00",
  "branch": "quan-1"
}
```

### Đầu ra

- `200`: `AvailabilityResponse`
- `400`: chi nhánh lạ — `"Unknown branch: …"`
- `400`: `guest_count` không thuộc 1–20 — `"guest_count must be 1-20"`

### Cách xử lý

1. `normalize_branch(branch)`; phải thuộc `BRANCHES`.
2. `check_availability`:
   - Bucket `time`.
   - `remaining = capacity − occupancy[(branch, date, time)]`.
   - `available = remaining >= guest_count`.
   - Nếu hết chỗ: tính tối đa 3 `alternatives`.
3. **Side-effect trên session** (chỉ khi `session_id` tồn tại trong store):
   - `available === false` → `availability_fail_count += 1`.
   - `available === true` **và** session đã đủ key chỗ (`guest_count`, `date`, `time`, `branch` nếu multi) **và** không còn `missing_fields` → `status = "ready_to_confirm"`.

Không trừ ghế ở bước này.

---

## `POST /v1/bookings`

Tạo booking sau khi khách **xác nhận** tóm tắt. Trừ occupancy ngay.

### Đầu vào (JSON)

| Trường | Kiểu | Bắt buộc | Mặc định | Ý nghĩa |
| --- | --- | --- | --- | --- |
| `session_id` | `string` | **có** | | Session nguồn |
| `slots` | `BookingSlots \| null` | không | dùng `session.slots` | Override slot |
| `transcript` | `TranscriptTurn[]` | không | `session.transcript` | Override transcript |
| `recording_id` | `string \| null` | không | `session.recording_id` | File ghi âm |
| `source` | `string` | không | `"Phone AI"` | Nguồn |

Tối thiểu:

```json
{ "session_id": "…uuid…" }
```

### Đầu ra

- `200`: `BookingRecord` (tạo mới **hoặc** trả booking cũ nếu session đã có `booking_id` — idempotent)
- `400`: `{ "detail": { "missing_fields": ["phone", …] } }`
- `404`: session không tồn tại
- `409`: `"Session already transferred"`
- `409`: `{ "detail": { "message": "No availability", "availability": { … } } }`

### Cách xử lý

1. Lấy session; `404` nếu thiếu.
2. `slots = body.slots hoặc session.slots`. Nếu còn `missing_fields` → `400`.
3. Nếu `session.transferred` → `409` (không đặt sau khi đã chuyển máy).
4. Nếu `session.booking_id` đã có → **trả booking cũ**, không trừ ghế lần hai.
5. Kiểm chỗ lại với `check_availability`. Nếu `available === false` → `409` kèm payload availability.
6. Sinh `id = BK-` + 8 hex uppercase.
7. Lưu `BookingRecord`; `store.add_occupancy(branch, date, bucket_time(time), guest_count)`.
8. Gán `session.booking_id`, `session.status = "booked"`, đồng bộ `recording_id` và `transcript`.

`branch` rỗng thì dùng `quan-1`.

---

## `POST /v1/call-sessions/{session_id}/transfer`

Đánh dấu session đã chuyển lễ tân. **Không** tạo booking.

### Đầu vào

**Path:** `session_id`.

**Body:**

| Trường | Kiểu | Bắt buộc | Ý nghĩa |
| --- | --- | --- | --- |
| `reason` | `string` | **có** | Mã lý do máy (xem bảng dưới) |
| `summary` | `string \| null` | không | Tóm tắt để gắn transcript |

```json
{ "reason": "guest_requested_human", "summary": "4 khách tối nay" }
```

### Đầu ra

- `200`: `CallSession` với `transferred=true`, `status="transferred"`, `transfer_reason=reason`
- `404`: không có session

### Cách xử lý

Ghi flag chuyển máy. Nếu có `summary`, append turn `role=system`, `content="transfer: {summary}"`.

Lý do thường gặp:

| `reason` | Khi nào |
| --- | --- |
| `large_party` | `guest_count > 12` |
| `guest_requested_human` | Khách xin gặp người / chuyển máy |
| `complex_event` | Tiệc cưới, sự kiện, set menu |
| `complex_request` | Dị ứng, khiếu nại, hoặc pattern chuyển máy khác |
| `invoice_request` | Xuất hóa đơn công ty |
| `unknown_policy` | FAQ không có trong knowledge (nhánh chữ) |
| `availability_exhausted` | Hết chỗ lặp lại, khách không nhận khung khác |
| `stt_failures` | Nhiều lượt không nghe được (nhánh chữ) |

---

## `PATCH /v1/call-sessions/{session_id}/recording`

Gắn `recording_id` theo session.

### Đầu vào

**Path:** `session_id`.

**Body:** `{ "recording_id": "RE123" }` (`recording_id` bắt buộc).

### Đầu ra

- `200`: `CallSession` đã cập nhật
- `404`: không có session

### Cách xử lý

Ghi `session.recording_id`. Không đụng booking (trừ khi booking đã copy id này lúc tạo).

---

## `PATCH /v1/recordings/by-call/{call_sid}`

Giống trên nhưng tìm session theo `call_sid` (webhook ghi âm Twilio-style).

### Đầu vào

**Path:** `call_sid` (string, ví dụ `CA9`).

**Body:** `{ "recording_id": "RE123" }`.

### Đầu ra

- `200`: session khớp **đầu tiên** (duyệt `store.sessions.values()`)
- `404`: `{ "detail": "Call session not found" }`

### Cách xử lý

Linear scan; gán `recording_id`; dừng ở session đầu tiên có `call_sid` trùng.

---

## `POST /v1/call-sessions/{session_id}/transcript`

Thêm một lượt vào nhật ký. Voice agent gọi mỗi câu khách / trợ lý.

### Đầu vào

**Path:** `session_id`.

**Body:**

| Trường | Kiểu | Bắt buộc | Ý nghĩa |
| --- | --- | --- | --- |
| `role` | `string` | có | Nên là `user` / `assistant` / `system` |
| `content` | `string` | có | Nội dung |

```json
{ "role": "user", "content": "Em đặt bàn 4 người tối nay." }
```

### Đầu ra

- `200`: `CallSession` (transcript dài thêm 1 phần tử, `ts` UTC tự gán)
- `404`: không có session

### Cách xử lý

`session.transcript.append(TranscriptTurn(...))`. Không parse slot.

---

## `GET /v1/branches`

Danh sách chi nhánh cho client/agent.

**Đầu vào:** không.

**Đầu ra `200`:**

```json
{
  "multi_branch": true,
  "branches": {
    "quan-1": {
      "name": "Quận 1",
      "capacity": 40,
      "address": "22 Đồng Khởi, Quận 1"
    },
    "thao-dien": {
      "name": "Thảo Điền",
      "capacity": 24,
      "address": "115 Nguyễn Văn Hưởng, Thảo Điền"
    }
  }
}
```

**Xử lý:** trả hằng `BRANCHES` trong store. Không đọc session.

---

# 2. Voice agent — cổng 8000

Orchestrator hội thoại. Khi start process: tạo `BackendClient` → Booking API, nạp knowledge RAG, `DialogEngine`, `BrowserChatStore`.

Biến môi trường quan trọng: `BOOKING_API_URL` (mặc định `http://127.0.0.1:8001`), `OPENAI_API_KEY` (cần cho nhánh browser LLM/STT/TTS).

---

## `GET /health`

### Đầu ra `200`

```json
{
  "status": "ok",
  "role": "voice-agent",
  "booking_api": "http://127.0.0.1:8001",
  "browser_voice": "/browser/voice",
  "browser_utterance": "/browser/{session_id}/utterance"
}
```

Không ping Booking API; chỉ báo config.

---

## `POST /text/start`

Bắt đầu hội thoại **chữ** (heuristic, không LLM). Dùng để test dialog hoặc client text-only.

### Đầu vào (JSON)

| Trường | Kiểu | Mặc định | Ý nghĩa |
| --- | --- | --- | --- |
| `call_sid` | `string \| null` | `"text-local"` | ID cuộc gọi |
| `from_number` | `string \| null` | `null` | Prefill SĐT nếu hợp lệ |

```json
{ "call_sid": "text-local", "from_number": "0901234567" }
```

### Đầu ra `200` — payload lượt (`_turn_payload`)

| Trường | Kiểu | Ý nghĩa |
| --- | --- | --- |
| `assistant_text` | `string` | Câu chào / hỏi tiếp |
| `action` | `string` | Ở start luôn `"ask"` |
| `session_id` | `string` | UUID Booking API |
| `missing_fields` | `string[]` | Slot còn thiếu |
| `booking_id` | `null` | Chưa đặt |
| `transfer_reason` | `null` | |
| `rag_hits` | `[]` | |
| `slots` | object | JSON `BookingSlots` |
| `availability` | `null` | |

### Cách xử lý (`DialogEngine.start`)

1. `POST /v1/call-sessions` với `multi_branch` từ settings.
2. Sinh câu mở (`opening_line`) — chào + hỏi field đầu tiên còn thiếu (thường là tên; nếu đã có SĐT từ caller ID thì hỏi tên).
3. `POST .../transcript` role `assistant`.
4. `GET` session rồi trả payload.

---

## `POST /text/{session_id}/turn`

Một lượt khách (text). Engine extract slot, gọi Booking API, RAG, có thể đặt bàn hoặc chuyển máy.

### Đầu vào

**Path:** `session_id` (UUID đã tạo bởi `/text/start` hoặc `/v1/call-sessions`).

**Body:** `{ "text": "…" }` — `text` bắt buộc (string; rỗng vẫn 200, xem dưới).

### Đầu ra `200`

Cùng schema `_turn_payload`. `action` có thể là:

| `action` | Ý nghĩa |
| --- | --- |
| `ask` | Hỏi slot tiếp theo |
| `repeat` | Không nghe / text rỗng, xin nhắc lại |
| `faq` | Trả lời knowledge rồi hỏi tiếp |
| `confirm` | Đủ slot + còn chỗ; đọc tóm tắt chờ khách xác nhận |
| `suggest_alternatives` | Hết chỗ; đọc khung thay thế |
| `booked` | Đã `POST /v1/bookings` |
| `transfer` | Đã `POST .../transfer` |

`availability` khác `null` khi vừa kiểm chỗ. `rag_hits` là đoạn FAQ nói được. `booking_id` khi `action=booked`. `transfer_reason` khi `action=transfer`.

Lỗi HTTP: nếu Booking API lỗi (session 404, …) client httpx `raise_for_status` → FastAPI 500 (không bọc 404 riêng trên route này).

### Cách xử lý (`DialogEngine.handle_user_turn`) — thứ tự

1. `GET` session; ghi transcript `user`.
2. **Text rỗng:** tăng bộ đếm STT trong RAM. Đủ `max_stt_fail_turns` (mặc định 3) → transfer `stt_failures`. Chưa đủ → `action=repeat`, câu xin nói lại.
3. **Escalation** (trừ `large_party` — xử lý sau khi có slot): gặp người, sự kiện, hóa đơn, dị ứng, … → `/transfer`.
4. Nếu câu giống FAQ → RAG (`knowledge/*.md`).
5. Nếu `status == ready_to_confirm` **và** khách xác nhận (`is_confirm`) → `POST /v1/bookings` → `action=booked`.
6. Extract `SlotDelta` từ text; nếu có field → `PATCH .../slots`.
   - Có `validation_errors` → nói lỗi, `action=ask`, **không** merge.
   - `should_transfer` → transfer `large_party`.
7. `guest_count > 12` → transfer.
8. Nếu đủ key chỗ **và** (delta đụng `guest_count/date/time/branch` **hoặc** lần đầu đủ key khi đang `collecting`) → `POST /v1/availability/check`.
   - Hết chỗ → nói alternatives, `action=suggest_alternatives`. Có thể transfer `availability_exhausted` nếu fail_count ≥ 2.
9. Còn `missing_fields` → hỏi field đầu; nếu FAQ thì `faq_then_question`. FAQ không hit knowledge → transfer `unknown_policy`.
10. Đủ slot: kiểm chỗ lần nữa nếu chưa có kết quả; còn chỗ → tóm tắt, `action=confirm`.
11. Mọi câu trợ lý đều `POST .../transcript` role `assistant`.

---

## `POST /browser/voice`

Nhấc máy trên UI trình duyệt: tạo session Booking + lịch sử LLM + TTS câu chào.

### Đầu vào (JSON)

| Trường | Kiểu | Mặc định | Ý nghĩa |
| --- | --- | --- | --- |
| `call_sid` | `string \| null` | tự sinh `CA-browser-` + 12 hex | ID cuộc gọi giả |
| `from_number` | `string \| null` | `null` | Caller ID (thường không dùng được vì `client:`) |

```json
{ "call_sid": null, "from_number": null }
```

### Đầu ra `200` — `BrowserTurnResult.as_payload()`

| Trường | Kiểu | Ý nghĩa |
| --- | --- | --- |
| `assistant_text` | `string` | Câu chào |
| `user_text` | `null` | Chưa có lượt khách |
| `audio_b64` | `string \| null` | MP3 base64 (TTS); `null` nếu thiếu API key / TTS lỗi |
| `audio_format` | `"mp3"` | |
| `session_id` | `string` | UUID Booking API — dùng cho utterance tiếp theo |
| `call_sid` | `string` | SID đã gán |
| `action` | `"ask"` | |
| `booking_id` | `null` | |
| `transfer_reason` | `null` | |
| `ended` | `false` | |
| `slots` | object | Slot hiện tại |

### Cách xử lý (`start_browser_call`)

1. `call_sid = body.call_sid hoặc CA-browser-…`.
2. `POST /v1/call-sessions` (`multi_branch` từ settings).
3. `BrowserChatStore.start(session_id)`: system prompt + context “hôm nay” + câu chào assistant.
4. Song song: append transcript assistant + `synthesize_speech` (OpenAI TTS, cache LRU 32 câu).
5. Trả payload. **Phải** gọi endpoint này trước `/utterance` vì history LLM chỉ tồn tại trên process 8000.

---

## `POST /browser/{session_id}/utterance`

Một lượt khách: **gõ chữ** và/hoặc **audio** (STT). LLM được phép gọi tool booking.

### Đầu vào

**Path:** `session_id` — UUID đã nhận từ `/browser/voice` (**không** dùng session chỉ tạo bằng `/text/start`: history LLM sẽ 404).

**Body:**

| Trường | Kiểu | Mặc định | Ý nghĩa |
| --- | --- | --- | --- |
| `text` | `string \| null` | `null` | Câu đã gõ. Nếu có, **không** cần STT |
| `audio_b64` | `string \| null` | `null` | Audio raw encode Base64 (webm/ogg/…) |
| `audio_filename` | `string` | `"speech.webm"` | Tên file giả cho OpenAI STT |

Chữ:

```json
{ "text": "Tên Lan, 4 người, tối nay 7 giờ Quận 1" }
```

Giọng nói:

```json
{ "audio_b64": "<base64>", "audio_filename": "speech.webm" }
```

Có thể gửi cả hai: **ưu tiên `text` đã strip**; chỉ STT khi `text` rỗng và có `audio_b64`.

### Đầu ra

- `200`: cùng schema browser payload. `user_text` = câu (sau STT nếu nói). `audio_b64` **chỉ có khi lượt đến từ voice** (`audio_b64` request khác rỗng) — lượt gõ **cố ý bỏ TTS** để UI không chờ. `ended=true` khi `status` là `booked` hoặc `transferred`.
- `404`: `{ "detail": "Browser call session not found" }` — không có history trong `BrowserChatStore` (sai id, hoặc voice-agent đã restart).

### Cách xử lý (`handle_browser_utterance`)

1. Lấy history; thiếu → `KeyError` → 404.
2. `GET` session Booking API. Nếu đã `booked` / `transferred` → trả câu cố định, `ended=true`, **không** gọi LLM.
3. Resolve `user_text`: text hoặc STT (`gpt-4o-mini-transcribe`, `language=vi`).
4. Nếu vẫn rỗng: `action=repeat`, câu xin nhắc; TTS chỉ khi đó là lượt voice.
5. Append transcript `user` + đẩy message user vào history LLM.
6. `run_browser_llm_turn`: tối đa **8 vòng** Chat Completions + tools (`update_slots`, `search_knowledge`, `confirm_booking`, `transfer_to_staff`). Tool độc lập chạy song song theo stage: slots/RAG trước → confirm → transfer.
7. Ghi transcript assistant. Voice: TTS câu trả lời. Text: không TTS.
8. Đồng bộ `slots`, `booking_id`, `ended` từ session backend.

Chi tiết tool (không phải HTTP public, nhưng là “cách xử lý” của utterance):

| Tool | Việc làm phía backend |
| --- | --- |
| `update_slots` | Parse delta → `DialogEngine.apply_slot_delta` → `PATCH .../slots` rồi `POST /v1/availability/check` nếu đủ key chỗ |
| `search_knowledge` | RAG; **cấm** suy ra còn/hết bàn từ tài liệu |
| `confirm_booking` | Nếu còn missing → `{ ok: false }`; không thì `POST /v1/bookings` |
| `transfer_to_staff` | `POST .../transfer`; utterance trả `TRANSFER_LINE` và `ended=true` |

---

# 3. Browser simulator — cổng 8002

UI tĩnh + **proxy**. Không giữ session booking; mọi state hội thoại nằm ở Voice agent + Booking API.

Cấu hình: `VOICE_AGENT_URL` (mặc định `http://127.0.0.1:8000`), timeout HTTP **120s**.

---

## `GET /health`

```json
{
  "status": "ok",
  "role": "browser-simulator",
  "page": "http://127.0.0.1:8002/browser",
  "voice_agent": "http://127.0.0.1:8000",
  "booking_api": "http://127.0.0.1:8001"
}
```

`page` lấy từ `BROWSER_SIM_BASE_URL` + `/browser`. Không kiểm tra service kia có sống không.

---

## `GET /` và `GET /browser`

Trả file HTML máy ảo: `apps/browser_sim/static/browser.html`.

- `200`: `text/html; charset=utf-8`
- `404`: `{ "detail": "Browser simulator page missing" }` nếu file không tồn tại

Không có body. Trình duyệt sau đó tự `POST /browser/voice` và `/browser/{id}/utterance` **cùng origin 8002**.

---

## `POST /browser/voice`

### Đầu vào / đầu ra

Giống hệt Voice agent `POST /browser/voice` (cùng schema request/response).

### Cách xử lý

`_forward`: `POST {VOICE_AGENT_URL}/browser/voice` với JSON body.

- Voice agent **không kết nối được** → `502` `{ "detail": "Voice agent unreachable at …: …" }`
- Voice agent trả ≥ 400 → **giữ nguyên status**, `detail` = JSON hoặc text của phía kia
- Thành công → JSON nguyên vẹn từ cổng 8000

---

## `POST /browser/{session_id}/utterance`

### Đầu vào / đầu ra

Giống Voice agent `POST /browser/{session_id}/utterance`.

### Cách xử lý

Forward `POST {VOICE_AGENT_URL}/browser/{session_id}/utterance`. Cùng quy tắc 502 / passthrough lỗi.

---

# 4. Chuỗi gọi điển hình

## A. Đặt bàn trên trình duyệt (gõ chữ)

1. Mở `GET http://127.0.0.1:8002/browser`.
2. `POST :8002/browser/voice` `{}`  
   → 8000 tạo session 8001 + TTS chào (UI có thể bỏ audio nếu không nói).
3. Lặp `POST :8002/browser/{session_id}/utterance` `{ "text": "…" }`  
   LLM gọi `update_slots` / FAQ / lúc khách đồng ý thì `confirm_booking`.
4. Khi `ended=true` và `booking_id` dạng `BK-…` → xong.

## B. API chữ (không LLM)

```http
POST http://127.0.0.1:8000/text/start
Content-Type: application/json

{}
```

```http
POST http://127.0.0.1:8000/text/{session_id}/turn
Content-Type: application/json

{ "text": "Tôi tên Lan, 2 người, ngày mai 6 giờ tối chi nhánh Quận 1, sđt 0901111222" }
```

Lặp đến `action=confirm`, rồi gửi lượt xác nhận (`dạ đúng ạ` / tương đương) để `action=booked`.

## C. Gọi thẳng Booking API (bỏ qua hội thoại)

```http
POST /v1/call-sessions          → session_id
PATCH /v1/call-sessions/{id}/slots   (đủ 6 field)
POST /v1/availability/check
POST /v1/bookings               { "session_id": "…" }
```

---

# 5. Mã lỗi HTTP tóm tắt

| Service | Mã | Khi nào |
| --- | ---: | --- |
| Mọi service | 200 | Thành công (kể cả tạo session/booking — không dùng 201) |
| Booking | 400 | Chi nhánh lạ, `guest_count` ngoài 1–20, booking thiếu field |
| Booking | 404 | Session / `call_sid` không có |
| Booking | 409 | Đã transfer; hoặc hết chỗ lúc tạo booking |
| Voice `/browser/.../utterance` | 404 | Không có history LLM cho `session_id` |
| Browser sim | 502 | Không nối được Voice agent |
| Browser sim | 4xx/5xx | Copy status từ Voice agent |

Lỗi validate JSON (thiếu field bắt buộc, sai kiểu) do FastAPI/Pydantic: **422** Unprocessable Entity.

---

# 6. File liên quan trong repo

| File | Nội dung |
| --- | --- |
| `apps/booking_api/main.py` | Route Booking API |
| `apps/booking_api/availability.py` | Bucket giờ, remaining, alternatives |
| `apps/booking_api/store.py` | RAM store, capacity, seed 24/12/2026 |
| `apps/voice_agent/server.py` | Route 8000 |
| `apps/voice_agent/dialog_engine.py` | Logic `/text/*` |
| `apps/voice_agent/backend_client.py` | HTTP client tới 8001 |
| `apps/browser_sim/server.py` | Route 8002 + proxy |
| `apps/browser_sim/sim.py` | LLM tools, STT/TTS, history |
| `shared/models.py` | Schema Pydantic |
| `shared/slots.py` | Alias chi nhánh, missing fields |
| `specs/openapi.yaml` | Contract rút gọn (thiếu một số route thực tế) |
| `knowledge/` | Tài liệu RAG (giờ mở cửa, hủy, gửi xe, …) |
