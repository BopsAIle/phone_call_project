# 06 — Vòng đời một cuộc gọi

File: `AI/bridge/session.py` (1401 dòng — file quan trọng nhất repo).

## Ba class trong file này

| Class | Vai trò |
| --- | --- |
| `CallSession` | **Dữ liệu**: trạng thái, lịch sử hội thoại, giỏ hàng, chi nhánh đã chọn… |
| `CallPipeline` | **Điều phối**: nhận sự kiện, quyết định làm gì, quản lý task |
| `TurnPlayer` | **Phát tiếng** cho một lượt nói: tổng hợp song song, gửi tuần tự |

Tách `CallSession` khỏi `CallPipeline` là có chủ ý: các tool (`BookingTools`,
`OrderTools`) và `TurnPlayer` chỉ cần `session`, không cần biết gì về WebSocket.

## Máy trạng thái

```
                      ┌───────┐
                      │ INIT  │   chờ sự kiện session.init
                      └───┬───┘
                          v
                    ┌──────────┐
                    │ GREETING │  đang phát lời chào
                    └────┬─────┘
                         v
    ┌──────────────> ┌───────────┐
    │                │ LISTENING │  chờ khách nói / bấm phím
    │                └─────┬─────┘
    │                      v  (STT chốt lượt)
    │                ┌──────────┐
    │                │ THINKING │  LLM đang stream, có thể gọi tool
    │                └────┬─────┘
    │                     v  (câu đầu tiên đã ra dây)
    │                ┌──────────┐
    └────────────────│ SPEAKING │
                     └────┬─────┘
                          │  khách nói đè lên
                          v
                    ┌──────────┐
                    │ BARGE_IN │ ──> LISTENING  (xem chương 10)
                    └──────────┘

    bất cứ lúc nào ──> CLOSED
```

Enum ở `CallState`. Lưu ý: `BARGE_IN` chỉ tồn tại trong tích tắc — `abort_and_interrupt()`
đặt nó rồi chuyển ngay về `Listening` trong cùng một khối lock.

## Vòng lặp chính: `CallPipeline.run()`

```python
async def run(self):
    self._stt_start_task = asyncio.create_task(self._start_stt())   # mở STT song song
    try:
        while not self.session.closed:
            message = await self.websocket.receive()
            if message["type"] == "websocket.disconnect": break
            if message.get("bytes") is not None:
                → PCM của khách → đẩy sang STT
            elif message.get("text") is not None:
                → sự kiện JSON → self.on_control(text)
    finally:
        await self.shutdown()
```

Một socket duy nhất mang **hai loại frame**: frame nhị phân là âm thanh, frame text là
sự kiện điều khiển JSON. Tách chúng ở đúng chỗ này.

STT được mở **song song** chứ không chờ: âm thanh đến trước khi STT sẵn sàng sẽ được đệm
tạm (tối đa ~2 giây, `_MAX_PENDING_STT_BYTES`) rồi xả một lượt khi kết nối lên.

## Các sự kiện trên dây

Định nghĩa ở `AI/bridge/protocol.py`.

**Client → AI Bridge:**

| Sự kiện | Ý nghĩa |
| --- | --- |
| *(frame nhị phân)* | PCM16-LE, 24 kHz, mono — tiếng của khách |
| `session.init` | mở cuộc gọi: `callId`, `storeName`, `timezone`, `locale`, `greeting`, `toNumber`, `fromNumber` |
| `dtmf` | khách bấm phím: `{"event":"dtmf","digit":"2"}` |

**AI Bridge → Client:**

| Sự kiện | Ý nghĩa |
| --- | --- |
| *(frame nhị phân)* | PCM16-LE 24 kHz — tiếng AI |
| `interrupt` | xóa ngay hàng phát: khách vừa cắt lời |
| `transcript` | `status: started \| completed` (+ `text`) — cho UI demo |
| `agent.speech` | câu AI vừa nói — cho UI demo |
| `order.created` | đơn đã tạo, kèm chi tiết — cho UI demo |
| `call.end` | AI chủ động kết thúc cuộc gọi |

Ba sự kiện `transcript` / `agent.speech` / `order.created` là **tùy chọn**: backend thoại
thật có thể bỏ qua, chúng tồn tại cho UI demo hiển thị.

## Định dạng âm thanh trên dây

```python
SAMPLE_RATE  = 24_000     # Hz
CHANNELS     = 1
SAMPLE_WIDTH = 2          # PCM16 little-endian
FRAME_MS     = 100
FRAME_BYTES  = 4_800
```

Vì sao 24 kHz? Vì đó là tần số OpenAI Realtime nhận và TTS sinh ra. Chọn 24 kHz cho cả
sợi dây nghĩa là đường tiếng khách đi thẳng tới STT và tiếng AI đi thẳng ra client
**không phải resample lần nào**. Chỉ Telnyx (16 kHz) mới cần chuyển đổi, và việc đó nằm
gọn trong `AI/telephony/telnyx/codec.py`.

## Chuỗi sự kiện đầy đủ của một cuộc gọi

### 1. `session.init` → `on_control()`

```
session.apply_init(payload)
  ├─ ghi callId, storeName, timezone, locale, toNumber, fromNumber
  ├─ ensure_intent_greeting(): thêm menu bấm phím vào lời chào nếu chưa có
  │                             (và thêm thông báo ghi âm nếu CALL_RECORD_DIR bật)
  ├─ history = [lời chào]
  └─ refresh_system_prompt()
      │
      ├─> tạo task nền _load_catalog()
      ├─> _push_stt_context()
      └─> _run_greeting()
```

### 2. `_load_catalog()` — chạy nền, không chặn lời chào

Tra nhà hàng theo **số khách đã gọi vào** (`toNumber`): thử Redis trước, không có thì
`GET /restaurants/by-hotline/:hotline`. Nếu nhà hàng chỉ có **một chi nhánh** thì khóa
luôn chi nhánh đó — khỏi hỏi khách. Sau đó nạp sẵn thực đơn (`_preload_menu`) và đẩy tên
món vào STT làm gợi ý (`_push_stt_context`).

Nạp thực đơn **trước khi khách nói tên món** là chủ ý: nếu đợi LLM gọi `search_menu` mới
nạp thì đã muộn một lượt — tên món chưa kịp vào STT lúc cần nhất.

Không tra được nhà hàng ⇒ `restaurant_missing = True`, và system prompt chuyển sang chế độ
"tôi không tra cứu được, xin lỗi" thay vì bịa ra chi nhánh.

### 3. `_run_greeting()`

Cắt lời chào thành từng câu (`split_spoken_sentences`), đưa qua `TurnPlayer`. Nếu lời chào
có menu bấm phím thì hẹn giờ `DTMF_MENU_TIMEOUT_SECONDS` — hết giờ mà khách không bấm thì
AI chuyển sang hỏi bằng lời.

### 4. Khách nói → callback từ STT

`CallPipeline` chính là handler của STT (nó có đủ `on_speech_started`,
`on_speech_stopped`, `on_transcript_delta`, `on_transcript_completed`,
`on_transcript_failed`).

```
on_speech_started()      → nếu AI đang nói: BARGE-IN (chương 10)
on_speech_stopped()      → ghi mốc thời gian, để đo độ trễ
on_transcript_completed(text)
      ├─ ghi transcript vào call log
      ├─ nếu đang chờ bấm phím: hủy chờ
      ├─ nếu AI đang bận: barge-in trước
      └─ _spawn(_run_reply(text))
```

### 5. `_run_reply(user_text)` — trái tim của một lượt

```
begin_generation()                      # tăng generation_id, xem chương 10
state = THINKING
await self._catalog_task                # chắc chắn catalog đã nạp xong
session.repair_history()                # chữa lịch sử hỏng từ lượt trước
TurnTimer(...)                          # bắt đầu đo độ trễ
history.append({"role":"user", ...})

[cửa chắn rẻ] nếu khách có vẻ nhắc tới chi nhánh và chưa khóa chi nhánh nào
              → gọi trước resolve_branch, tiết kiệm một lượt

async for sentence in llm.stream_sentences(history, ..., tools=..., execute_tool=...):
      await player.speak_sentence(sentence)      # phát ngay, không đợi hết câu trả lời

await player.finish()
_maybe_schedule_hangup()                # nếu vừa tạo xong đơn thì hẹn cúp máy
```

### 6. Tự cúp máy

Sau khi tạo đơn thành công **và** đã nói xong câu chốt, `_maybe_schedule_hangup()` hẹn một
task. Task đó **không cúp ngay**: nó ước lượng client còn bao nhiêu giây âm thanh trong
hàng đợi (`remaining_playback_seconds`), ngủ đúng chừng đó, rồi mới gửi `call.end` và đóng
socket. Cúp sớm là khách bị cắt giữa câu cảm ơn.

Nếu khách nói thêm trước khi hết giờ, `_cancel_hangup()` hủy — log ghi
*"Hủy cúp máy: khách còn muốn nói tiếp"*.

### 7. `shutdown()`

Dọn theo đúng thứ tự: hủy task hẹn giờ → đánh dấu `closed` → đóng file ghi âm →
**đẩy nốt transcript lên BE** → hủy `TurnPlayer` → hủy task đang chạy → đóng STT.

## Bấm phím (DTMF)

```python
SERVICE_BY_DIGIT = {
    "1": ("booking", ""),          # đặt bàn
    "2": ("order", "pickup"),      # lấy tại quán
    "3": ("order", "delivery"),    # giao hàng
}
```

`on_dtmf()` xử lý mấy tình huống thực tế:

- **Chống dội phím**: cùng một phím trong `DTMF_DEBOUNCE_MS` (500 ms) thì bỏ qua.
- **Đang tạo đơn thì bỏ qua phím**: tránh phá ngang một `create_order` đang bay.
- **Phím sai**: nhắc lại menu, tối đa `DTMF_MAX_INVALID` (2) lần rồi thôi.
- **Phím đúng**: `apply_service_choice()` đặt intent + fulfillment, cập nhật system prompt,
  rồi chạy `_run_reply()` với một câu giả lập như *"I pressed 2, order for pickup."* để LLM
  có ngữ cảnh mà đi tiếp.

## Tiếp theo

→ [07 — Nghe: STT](07-nghe-stt.md)
