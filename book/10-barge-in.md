# 10 — Barge-in: khách cắt lời

File chính: `AI/turn/barge_in.py` (137 dòng).

## Vấn đề

AI đang đọc một danh sách dài. Khách sốt ruột chen vào: *"Thôi, cho tôi món đầu tiên."*

Hệ thống phải:

1. **Im ngay lập tức** — không phát thêm một frame nào.
2. Bảo client **xóa hàng phát** đang có sẵn trong buffer của nó.
3. **Vứt bỏ** phần LLM đang viết và phần TTS đang tổng hợp.
4. **Nhưng**: nếu đang có một `create_order` bay tới backend, tuyệt đối **không** hủy nó.
5. Ghi vào lịch sử đúng phần AI **đã kịp nói ra**, không phải phần nó định nói.
6. Vẫn tiếp tục đẩy tiếng khách sang STT trong suốt quá trình.

## Chìa khóa: `generation_id`

Mỗi lượt nói của AI mang một số nguyên tăng dần. `begin_generation()` tăng nó lên.

```python
class TurnPlayer:
    def __init__(self, session, ...):
        self.generation_id = session.generation_id     # chụp lại lúc sinh ra

    def should_abort(self):
        return self._aborted \
            or self.session.generation_id != self.generation_id \
            or self.session.closed
```

Chỉ cần **tăng một con số**, mọi thứ đang bay của lượt cũ tự biết mình đã lỗi thời:

- `TurnPlayer.should_abort()` → ngừng tổng hợp, ngừng gửi
- `OutboundGate.send_audio()` → trả về `False`, vứt frame
- `stream_sentences(..., should_abort)` → thoát generator
- `_run_reply()` → `if self.session.generation_id != gen: return`

Không cần truyền cờ hủy qua bốn tầng hàm.

## Trình tự chuẩn — `abort_and_interrupt()`

```python
async with outbound.lock:                 # ① giành cửa ra
    session.generation_id += 1            # ② mọi thứ đang bay thành hàng cũ
    session.playing = False
    session.state = "BargeIn"
    await outbound._send_interrupt_locked()   # ③ gửi interrupt SAU frame cuối
    outbound.reset_playback_clock()
    session.state = "Listening"

result = abort_work()                     # ④ hủy task — NGOÀI lock
if asyncio.iscoroutine(result): await result

session.commit_partial_assistant()        # ⑤ ghi đúng phần đã nói
```

Thứ tự này không tùy tiện:

- **② và ③ trong cùng một lock.** Nhờ vậy `interrupt` chắc chắn đi **sau** frame âm thanh
  cuối cùng và **trước** mọi frame còn lại — mà mọi frame còn lại thì đã bị ② vô hiệu hóa.
- **④ ra ngoài lock.** Việc hủy task có thể phải `await` khá lâu (xem dưới); giữ lock suốt
  thời gian đó sẽ chặn cả những thứ không liên quan.
- **⑤ sau ④.** Một tool tạo đơn có thể còn đang bay, và vòng tool của nó phải nằm trong
  lịch sử **trước** câu nói thông báo nó. Ghi ở đây cũng cho transcript đúng thứ tự khách
  đã trải nghiệm. An toàn ngoài lock, vì bước ② đã khiến `send_audio` trả `False`, nên
  không có `note_spoken` muộn nào chen vào được.

## Ngoại lệ: đang tạo đơn

Trong `CallPipeline._barge_in()`:

```python
if self._create_in_flight:
    # POST tạo booking/order đã trên đường bay.
    # Hủy ở đây là mất đơn dù khách đã xác nhận.
    logger.info("Barge-in while creating; waiting for the tool %s", self.session.tag)
    try:
        await asyncio.wait_for(asyncio.shield(work), _CREATE_GRACE_SECONDS)   # 20 giây
    except asyncio.TimeoutError:
        logger.warning("Create did not finish in %ss; cancelling", _CREATE_GRACE_SECONDS)
if not work.done():
    work.cancel()
```

Đọc kỹ: **tiếng vẫn tắt ngay** (bước ② đã xong từ trước). Chỉ có **task** là được sống
thêm tối đa 20 giây để `create_*` kịp hoàn tất. Vì `generation_id` đã đổi, lượt nói đó tự
`return` ngay sau khi tool xong — nó không nói thêm câu nào.

`_create_in_flight` được bật/tắt trong `_execute_tool()`:

```python
creating = name in {"create_booking", "create_order"}
if creating: self._create_in_flight = True
try:
    ...
finally:
    if creating: self._create_in_flight = False
```

Cùng cờ này cũng khiến DTMF bị bỏ qua trong lúc tạo đơn.

## Ai kích hoạt barge-in

```python
async def on_speech_started(self):
    await self._cancel_hangup()                  # khách còn muốn nói → đừng cúp
    await self._notify_transcript("started")
    async with self._turn_lock:
        if state in (CLOSED, BARGE_IN, LISTENING): return   # đang rảnh, không cần
        if state in (GREETING, THINKING, SPEAKING) or playing or work đang chạy:
            await self._barge_in()
```

`_turn_lock` là một `asyncio.Lock` riêng, ngăn hai luồng cùng chuyển lượt một lúc (ví dụ
STT chốt transcript đúng lúc khách bấm phím).

Ba nơi gọi `_barge_in()`: `on_speech_started`, `on_transcript_completed` (khi AI vẫn
đang bận), và `on_dtmf`.

## Phía client làm gì

Client — UI demo, backend thoại, hay `TelnyxCallSocket` — nhận frame text:

```json
{"event":"interrupt"}
```

và phải **xóa sạch hàng phát ngay lập tức**. Với Telnyx, `TelnyxCallSocket.send_text()`
dịch nó thành lệnh `clear` của Telnyx Media Streaming.

Đây cũng là lý do frame gửi ra Telnyx được giữ ngắn (20 ms): frame càng ngắn, lệnh `clear`
càng vứt đi ít tiếng đã lỡ nằm trong buffer.

## Thử nghiệm thủ công

Khi test bằng UI demo trong `AI/frontend/`, **dùng tai nghe**. Phát loa ngoài thì tiếng AI
lọt vào micro, VAD báo `speech_started`, và bạn sẽ thấy AI tự cắt lời chính mình.

Test tự động: `AI/tests/test_barge_in.py`.

## Tiếp theo

→ [11 — Tool đặt bàn](11-tool-dat-ban.md)
