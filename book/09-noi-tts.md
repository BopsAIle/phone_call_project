# 09 — Nói: TTS (Text to Speech)

Files: `AI/tts/openai_tts.py`, `TurnPlayer` trong `AI/bridge/session.py`,
`OutboundGate` trong `AI/turn/barge_in.py`.

## Mục tiêu: nghe thấy tiếng càng sớm càng tốt

Chỉ số đáng quan tâm nhất cả pipeline là **`first_audio_ms`**: từ lúc khách ngừng nói đến
lúc byte tiếng đầu tiên ra dây. Mọi thứ trong chương này tồn tại để giảm con số đó.

## Tầng 1 — `OpenAiTts.stream_pcm16()`

```python
async with client.audio.speech.with_streaming_response.create(
        model="tts-1", voice="nova", input=text, response_format="pcm") as response:
    async for chunk in response.iter_bytes(chunk_size=1024):
        if should_abort(): return
        yield even_pcm16(chunk, leftover)
```

Ba quyết định:

- **`response_format="pcm"`** — OpenAI TTS sinh ra PCM 24 kHz gốc, đúng bằng tần số của
  sợi dây. Không phải resample lần nào, không mất chất lượng, không tốn CPU.
- **`chunk_size=1024`** (~21 ms âm thanh). Comment ghi rõ: 4096 (~85 ms) làm chậm lần
  `yield` đầu tiên sau TTFB. Chỉnh qua `TTS_CHUNK_BYTES`.
- **`even_pcm16(chunk, leftover)`** — một chunk có thể kết thúc giữa một mẫu 16 bit. Byte
  lẻ được giữ lại cho chunk sau, nếu không sẽ lệch pha và ra tiếng rè.

`_supports_instructions()` xử lý một chi tiết API: `tts-1` / `tts-1-hd` **từ chối** tham
số `instructions`, còn `gpt-4o-*-tts` thì nhận.

## Tầng 2 — `TurnPlayer`: tổng hợp song song, gửi tuần tự

Đây là mấu chốt. Nếu tổng hợp lần lượt từng câu, câu 2 phải đợi câu 1 phát xong mới bắt
đầu gọi API — lãng phí cả trăm mili giây mỗi câu.

```
LLM ──câu 1──> speak_sentence() ──> task TTS 1 ──> queue 1 ─┐
    ──câu 2──> speak_sentence() ──> task TTS 2 ──> queue 2 ─┤ _sender_loop
    ──câu 3──> speak_sentence() ──> task TTS 3 ──> queue 3 ─┘  đọc TUẦN TỰ
                                                                     │
                                                                     v
                                                              OutboundGate
```

- Mỗi câu tạo **một task tổng hợp riêng**, chạy song song ngay khi LLM nhả ra câu đó.
- Nhưng có **một `_sender_loop` duy nhất** đọc các queue **đúng thứ tự** — nên thứ tự câu
  nói ra không bao giờ đảo.

### `note_spoken()` chỉ gọi khi byte đầu tiên đã ra dây

```python
if first:
    self.session.note_spoken(text)      # câu này khách THẬT SỰ nghe thấy
    first = False
    logger.info("AI: %s", text)
    await self._notify_spoken(text)
```

Câu bị barge-in giết trước khi ra dây **không bao giờ tới đây**. Đúng như mong muốn:
transcript phải là **thứ đã nói ra**, không phải thứ model định nói.

### `finish()` và `abort()`

- `finish()` — đẩy sentinel `None` vào queue, đợi sender xong, đợi hết task tổng hợp, rồi
  `commit_partial_assistant()` ghi cả lượt vào lịch sử hội thoại và chuyển về `LISTENING`.
- `abort()` — hủy mọi task tổng hợp và sender ngay lập tức.

### `should_abort()`

```python
return self._aborted or self.session.generation_id != self.generation_id or self.session.closed
```

`TurnPlayer` nhớ `generation_id` lúc nó được tạo. Chỉ cần session tăng số đó (barge-in),
mọi thứ của player này lập tức thành "hàng cũ". Xem [chương 10](10-barge-in.md).

## Tầng 3 — `OutboundGate`: một cửa duy nhất ra socket

```python
async def send_audio(self, generation_id, pcm) -> bool:
    async with self.lock:
        if self.session.closed or self.session.generation_id != generation_id:
            return False                       # thế hệ cũ: vứt
        await self.websocket.send_bytes(pcm)
        if self.first_frame_at is None:
            self.first_frame_at = time.monotonic()
            mark_first("first_audio_ms")       # ← chỉ số quan trọng nhất
        self.bytes_sent += len(pcm)
        self.session.mark_audio_sent()
        return True
```

Mọi thứ đi ra socket — âm thanh nhị phân, frame text `interrupt`, các sự kiện JSON — đều
phải qua **cùng một `asyncio.Lock`**. Đó là điều làm cho lời hứa của barge-in thành sự
thật: khi barge-in giành được lock, mọi frame âm thanh đã giao cho writer đều đã ra dây,
và **không frame cũ nào có thể đi sau `interrupt`**.

## Ước lượng client còn bao nhiêu tiếng chưa phát

```python
def remaining_playback_seconds(gate, grace_ms) -> float:
    audio_seconds = gate.bytes_sent / BYTES_PER_SECOND
    elapsed = time.monotonic() - gate.first_frame_at
    return max(0.0, audio_seconds - elapsed) + LEAD_SECONDS + grace_ms / 1000.0
```

Server đã **gửi** xong không có nghĩa khách đã **nghe** xong — âm thanh còn nằm trong
buffer của client. Hàm này quy đổi số byte đã gửi thành giây, trừ đi thời gian đã trôi, và
cộng thêm `LEAD_SECONDS = 0.06` phòng hờ.

Dùng ở hai chỗ: hẹn giờ cúp máy sau câu chốt (chương 06), và hẹn giờ chờ khách bấm phím
sau khi đọc xong menu.

## Tiếp theo

→ [10 — Barge-in: khách cắt lời](10-barge-in.md)
