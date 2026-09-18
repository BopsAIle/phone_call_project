# 17 — Log, đo lường, ghi âm

Ba hệ thống quan sát khác nhau, phục vụ ba mục đích khác nhau.

| Hệ thống | File | Trả lời câu hỏi |
| --- | --- | --- |
| Nhật ký cuộc gọi | `AI/calls/` | *Cuộc gọi đó hai bên đã nói gì?* |
| Đo độ trễ | `AI/obs/timing.py` | *Một lượt mất bao lâu, chậm ở chặng nào?* |
| Ghi âm | `AI/audio/recorder.py` | *STT có nghe đúng không?* |

## 1. Nhật ký cuộc gọi — `AI/calls/`

Bật/tắt bằng `CALL_LOG_ENABLED` (mặc định `true`).

### Vì sao không lưu thẳng `session.history`

Comment trong `calls/logger.py` giải thích rõ: `history` lẫn JSON kết quả tool, lời nhắc
hệ thống, và **những câu model định nói nhưng bị cắt trước khi ra loa**.

Thứ đáng lưu là thứ **hai bên thật sự đã nghe**, nên transcript được nhặt ở đúng hai chỗ:

- **Câu khách nói** — khi STT chốt lượt (`on_transcript_completed`)
- **Câu AI nói** — khi **byte tiếng đầu tiên của câu đó đã ra dây** (`TurnPlayer._sender_loop`)

Ngoài ra kết quả tool cũng được ghi với `role = "tool"` để tra soát.

### Gửi theo lô, chạy nền

```python
_BATCH_SIZE = 10
_FLUSH_SECONDS = 30.0
_MAX_CONTENT_CHARS = 8000
```

Đủ 10 câu hoặc quá 30 giây thì đẩy một lô lên BE. **Mọi thao tác mạng chạy ở task nền và
nuốt lỗi** — cuộc gọi không bao giờ được chậm hay chết vì việc ghi nhật ký.

### Vòng đời

```
_load_catalog() xong  → POST /calls/ai/start        (đã biết nhà hàng)
trong cuộc gọi        → POST /calls/ai/:id/messages (theo lô)
shutdown()            → POST /calls/ai/:id/end      (kèm nốt lô cuối)
```

Body của `/end` mang: `status`, `ended_at`, `duration_seconds`, `intent` (`booking` /
`pickup` / `delivery` / `unknown`), `branch_id`, và **`booking_id` / `order_id`** — đây là
sợi dây nối cuộc gọi với đơn hàng, để khách khiếu nại thì tra ngược được.

## 2. Đo độ trễ — `AI/obs/timing.py`

### Vấn đề nó giải

Trước module này, cả repo chỉ có ba chỗ gọi `time.monotonic()` và **không chỗ nào đo
pipeline**. Nghĩa là không ai trả lời được "một lượt mất bao lâu" hay "sửa xong có nhanh
hơn không".

### Hai quyết định thiết kế

**Package lá, không import gì trong repo.** `bridge` đã import `llm`; nếu `llm` import
ngược `bridge` là vòng tròn. `obs/` không phụ thuộc ai nên mọi tầng dùng được.

**Truyền bằng `contextvars`, không sửa chữ ký hàm.** Giá trị `ContextVar` được **sao sang
task con lúc `create_task`**, nên đồng hồ đặt trong `_run_reply()` tự nhìn thấy được từ
các task TTS mà `TurnPlayer` sinh ra. Không phải luồn tham số qua bốn tầng, và các fake
trong test không phải đổi gì.

Đó cũng là lý do `TurnTimer` được tạo **trong** `_run_reply()` chứ không phải trong
`on_transcript_completed()` — phải đúng chỗ để các task con kế thừa được context.

### API

```python
mark_first("llm_ttft_ms")    # mốc đầu tiên thắng
put_value("tools", "...")    # gắn một giá trị
add_ms("tool_ms", 123.4)     # cộng dồn
bump("llm_rounds")           # đếm
```

Tất cả đều **no-op** khi không có đồng hồ nào đang chạy — gọi ở đâu cũng an toàn.

### Các mốc được đo

| Mốc | Ý nghĩa |
| --- | --- |
| `stt_ms` | từ lúc khách ngừng nói đến khi có transcript |
| `llm_ttft_ms` | token đầu tiên từ LLM |
| `llm_ttfs_ms` | **câu** đầu tiên hoàn chỉnh từ LLM |
| `tts_ttfb_ms` | byte âm thanh đầu tiên từ TTS |
| **`first_audio_ms`** | **khách ngừng nói → nghe thấy tiếng** ← con số quan trọng nhất |
| `tool_ms`, `llm_rounds`, `tools` | thời gian chạy tool, số vòng, tên tool |
| `prompt_tokens`, `cached_tokens` | chi phí và tỉ lệ trúng cache của OpenAI |

### Dạng log

Một lượt = **một dòng**, định dạng `k=v` cách nhau bởi khoảng trắng — grep được, script
bóc được, không cần parse JSON:

```
TURN call=abc123def456 gen=3 stt_ms=812 llm_ttft_ms=402 llm_ttfs_ms=655 tts_ttfb_ms=180 first_audio_ms=1104 llm_rounds=2 tool_ms=243 tools=search_menu,add_to_cart
```

### Tổng hợp

```bash
cd AI
.venv/bin/python app.py 2>&1 | tee app.log
.venv/bin/python scripts/turn_stats.py app.log
.venv/bin/python scripts/turn_stats.py app.log --call abc123def456
```

Chỉ dùng thư viện chuẩn, đọc được cả stdin (`-`).

## 3. Ghi âm — `AI/audio/recorder.py`

Mặc định **tắt**. Bật bằng:

```bash
CALL_RECORD_DIR=/duong/dan/nao/do
CALL_RECORD_MAX_SECONDS=600
```

Chuỗi rỗng là **toàn bộ công tắc**: `CallRecorder.maybe()` trả `None` và mọi lời gọi thành
no-op.

### Ghi ở đâu trong pipeline

Vòi ghi đặt tại chỗ âm thanh **được trao cho STT**, không phải chỗ Telnyx giao hàng. Lý
do: thứ đáng đánh giá chính là thứ STT đã nghe. Điểm đó cũng phủ luôn cả socket
`/v1/bridge` lẫn UI demo trình duyệt.

### Sản phẩm

- `<stamp>-<call_id>.wav` — mono PCM16 24 kHz
- `<stamp>-<call_id>.jsonl` — các mốc kèm **offset byte**:
  `speech_started`, `transcript`, `agent`

Offset byte là thứ cho phép cắt một file dài thành từng clip theo lượt, rồi nạp vào
`scripts/stt_eval.py`.

### ⚠️ Nghĩa vụ pháp lý

Bật ghi âm thì **lời chào tự động thêm câu thông báo**:

```python
RECORDING_NOTICE_EN = "This call is recorded for quality purposes."
```

Và nó được đặt **trước** menu bấm phím — khách bấm phím trong lúc nghe menu thì phải đã
nghe thông báo rồi. Xem `ensure_intent_greeting()` trong `AI/bridge/session.py`.

## 4. Log thường

Mức log đặt bằng `LOG_LEVEL`. Vài dòng đáng grep:

| Chuỗi | Ý nghĩa |
| --- | --- |
| `Người gọi:` | transcript khách đã chốt |
| `Người gọi (đang nói):` | transcript tạm, khi khách còn đang nói |
| `AI:` | câu AI vừa phát ra dây |
| `TURN ` | dòng đo độ trễ |
| `barge-in generation_id=` | khách vừa cắt lời |
| `Mic PCM` | thống kê âm thanh vào (bytes, peak) — hữu ích khi "không nghe thấy gì" |
| `Hotline catalog` | tra nhà hàng thành công/thất bại |
| `Telnyx routes mounted` | Telnyx đã bật |

`_note_inbound_pcm()` in mức đỉnh tín hiệu mỗi ~2 giây. `peak` quanh 0 nghĩa là **micro
đang câm** — vấn đề nằm ở client hoặc codec, không phải ở STT.

## Tiếp theo

→ [18 — Kiểm thử](18-kiem-thu.md)
