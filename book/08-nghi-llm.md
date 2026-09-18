# 08 — Nghĩ: LLM

Files: `AI/llm/stream.py` (722 dòng), `AI/llm/history.py`.

## Ba việc file này làm

1. **Dựng system prompt** — toàn bộ "luật chơi" của AI (`build_system_prompt`).
2. **Stream câu trả lời theo từng câu** — để phát tiếng sớm (`SentenceAggregator`).
3. **Chạy vòng gọi tool** — LLM gọi hàm, nhận kết quả, nói tiếp (`stream_sentences`).

## 1. System prompt

`build_system_prompt()` không phải một chuỗi cố định — nó được **dựng lại mỗi khi trạng
thái đổi** (`session.refresh_system_prompt()`), từ hàng chục mảnh ghép lại tùy tình huống.

Nó nhận vào: tên cửa hàng, múi giờ, danh sách chi nhánh, chi nhánh đã khóa chưa, intent,
đã tạo đơn chưa, tóm tắt giỏ hàng, hình thức nhận hàng, thực đơn đã nạp chưa, khách bấm
phím gì, số khách đang gọi từ…

### Các luật đáng chú ý

**Ngôn ngữ.** *"Speak English only. Never speak Vietnamese or any other language."*
Lặp lại nhiều lần vì model hay trôi theo ngôn ngữ của khách.

**Thời gian.** Prompt nhét sẵn giờ địa phương hiện tại và tên múi giờ IANA, kèm luật:
*"tonight", "tomorrow", "today" dùng múi giờ đó, không phải đồng hồ server*.

**Không đọc thứ máy móc.** *"Never read UUIDs, JSON, or tool names aloud."* và
*"Do not use markdown"*.

**Địa chỉ chi nhánh là thông tin nội bộ.** Prompt chia rõ hai danh sách: tên chi nhánh
(được đọc) và địa chỉ (chỉ đọc khi khách hỏi thẳng). Lý do: đọc cả địa chỉ lúc liệt kê
tên làm cuộc gọi dài lê thê.

**Xử lý HCM.** Có hẳn một đoạn: *HCM, TP HCM, TPHCM, Saigon đều là Ho Chi Minh; khớp
chi nhánh có tên HCM, đừng khớp chi nhánh khác chỉ vì địa chỉ nó chứa chữ HCM.*

**Không được nói dối.** Lặp lại cho cả hai luồng:
*"Do not say the table is booked unless create_booking returns ok true."*

**Số điện thoại người gọi.** Khi có `caller_number`, prompt đổi hẳn chiến thuật: đọc ngược
từng chữ số cho khách xác nhận (*"0 9 1 2 3 4 5…"*), tuyệt đối không bắt khách đọc số của
chính họ. Khách đồng ý ⇒ gọi tool với `use_caller_number: true`, để **số thật từ nhà mạng**
được dùng chứ không phải chuỗi model gõ lại.

**Hỏi gộp một lần.** `INTAKE_BOOKING` / `INTAKE_ORDER` ép AI hỏi *tên + địa chỉ + số điện
thoại + yêu cầu* trong **một câu**, thay vì tra khảo từng trường một. Lượt sau chỉ hỏi
cái còn thiếu.

## 2. Cắt câu — `SentenceAggregator`

Tại sao cần: nếu đợi LLM trả lời xong mới tổng hợp giọng, khách phải chờ toàn bộ câu trả
lời. Cắt theo câu thì câu đầu tiên đã ra loa trong khi model còn đang viết câu thứ hai.

Chỗ khó duy nhất là **dấu chấm**. `is_sentence_boundary()` là một hàm thuần, nhỏ, dễ test:

| Trường hợp | Kết quả |
| --- | --- |
| `? ! … \n` | luôn kết câu |
| `...` | không cắt (vẫn trong chuỗi dấu chấm) |
| `19.000`, `1.5`, `$19.99` | không cắt (dấu phân cách số) |
| `Mr. Smith`, `Dr. Lee` | không cắt (danh sách `_TITLES`) |
| `No. 106 Hoang Quoc Viet` | không cắt — nhưng `No. I mean yes.` **có** cắt |
| `A. Nguyen` | không cắt (chữ cái đơn viết hoa) |
| `press 1. To order` | cắt |

Comment trong code nói rõ vì sao danh sách viết tắt phải ngắn: thêm `st`, `co`, `min` sẽ
nuốt mất những dấu chấm kết câu thật.

**Không bao giờ cắt ở dấu phẩy.** Câu quá vụn nghe như máy nói lắp.

## 3. Vòng gọi tool — `stream_sentences()`

```python
for _round in range(_MAX_TOOL_ROUNDS):          # tối đa 12 vòng
    stream = await client.chat.completions.create(
        model=..., messages=working, stream=True,
        temperature=0.7, max_tokens=700,
        tools=tools, tool_choice="auto",
        stream_options={"include_usage": True},
    )
    async for chunk in stream:
        if should_abort(): return               # barge-in: thoát ngay
        → gom content thành câu  → yield từng câu
        → gom tool_calls thành từng lời gọi hoàn chỉnh

    nếu không có tool_call:  kết thúc
    nếu có:  chạy tool → thêm kết quả vào messages → vòng tiếp
```

### `max_tokens=700`

Đủ chỗ cho một câu đọc lại toàn bộ đơn **cộng** một lời gọi `create_*`. Cắt cụt ở đây là
mất lời gọi tool — nghĩa là khách nghe "đã đặt xong" mà database trống.

### Barge-in ở mức stream

`should_abort()` được kiểm tra ở **mọi chunk**. Nhưng có ngoại lệ quan trọng:

```python
_UNINTERRUPTIBLE_TOOLS = frozenset({"create_booking", "create_order"})
```

Hai tool này là **lần ghi duy nhất** xuống backend. Cắt ngang chúng là mất đơn dù khách đã
xác nhận. Chi tiết cơ chế ở [chương 10](10-barge-in.md).

### Một vòng tool phải được ghi nguyên khối

Đây là lỗi đắt giá mà code chữa lại. API Chat Completions bắt buộc: một message
`assistant` mang `tool_calls` **phải** được theo ngay bởi đúng một message `tool` cho mỗi
call id. Sai là HTTP 400.

Trước kia generator ghi thẳng vào `session.history` qua các điểm `await`, nên barge-in có
thể chèn một message `assistant` vào **giữa** `tool_calls` và kết quả của nó. Và vì lịch sử
không bao giờ được dựng lại, **một vòng hỏng là đầu độc mọi lượt sau** — khách nghe đúng
một câu xin lỗi lặp lại mãi mà không hiểu vì sao.

Hai lớp bảo vệ hiện nay:

1. `stream_sentences` gom cả vòng tool rồi trao lại qua `on_tool_round` → bên nhận là
   `session.commit_tool_round()`, một lệnh `list.extend` **đồng bộ**, vòng lặp sự kiện
   không xen vào giữa được.
2. `AI/llm/history.py` → `repair_tool_sequence()` chữa lịch sử **đã** hỏng: kéo kết quả
   lạc chỗ về đúng lời gọi, tự sinh kết quả thiếu (`{"ok":false,"error":"interrupted"}`),
   bỏ kết quả mồ côi. Được gọi ở đầu mỗi `_run_reply()`; không có gì hỏng thì nó là no-op.

### Khi model không nói gì

- `finish_reason == "length"` → bị cắt cụt, lời gọi tool đã mất.
- Model trả về rỗng → nói `GIVE_UP_PHRASE`:
  *"Sorry, I'm having trouble with that right now. Could you say that again?"*

Câu này **cố ý khác** với `FALLBACK_PHRASES` (*"Sorry, I didn't catch that"*). Lỗi là của
hệ thống, không phải khách nghe nhầm — đổ lỗi cho khách chỉ khiến họ lặp lại vào một lượt
vốn đã hỏng sẵn.

### Theo dõi cache của OpenAI

`stream_options: {"include_usage": True}` làm OpenAI gửi chunk usage cuối stream (chunk
này có `choices` rỗng). `_note_usage()` lấy ra `cached_tokens` — **cách duy nhất** biết bộ
nhớ đệm prompt có trúng hay không, mà điều đó ảnh hưởng trực tiếp tới chi phí và độ trễ.

## Tiếp theo

→ [09 — Nói: TTS](09-noi-tts.md)
