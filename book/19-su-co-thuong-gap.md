# 19 — Sự cố thường gặp

Bảng tra nhanh. Mỗi mục: triệu chứng → nguyên nhân hay gặp → cách sửa.

## Khởi động

### `make dev` từ chối chạy, in ra PID

Cổng 3070/8070/8071 đang bị chiếm. Đây là **tính năng**, không phải lỗi — nếu để Vite/Nest
tự nhảy cổng, chúng từng đè lên nhau gây `EADDRINUSE` khó tìm.

```bash
make stop           # dọn tiến trình của repo này
kill <PID>          # hoặc giết thủ công nếu là project khác
```

### `pip install` cài vào Python hệ thống

Bạn dùng `source .venv/bin/activate` và nó lỗi âm thầm. Gọi thẳng đường dẫn:

```bash
.venv/bin/python -m pip install -r requirements.txt
```

### BE crash: `ERR_MODULE_NOT_FOUND: @nestjs/common/internal`

Các gói `@nestjs/*` lệch major (ví dụ `@nestjs/core@12` với `@nestjs/common@11`).

```bash
cd BE && npm install
```

### Sửa `vite.config.ts` mà không có tác dụng

`FE/vite.config.js` tồn tại song song (bản do `tsc -b` sinh ra) và **Vite nạp `.js` trước
`.ts`**. Phải sửa cả hai file.

## AI Bridge

### Mọi kết nối WebSocket bị từ chối (1008)

`AI_BRIDGE_TOKEN` rỗng trong `AI/.env`. Log sẽ có:
`AI_BRIDGE_TOKEN is empty; every /v1/bridge handshake will be rejected`.

Không có chế độ "mở toang" — token rỗng là chặn hết.

### Trình duyệt không kết nối được nhưng curl thì được

Trình duyệt **không gắn được header `Authorization`** vào WebSocket. Dùng query:

```
ws://127.0.0.1:8071/v1/bridge?token=<AI_BRIDGE_TOKEN>
```

### STT/LLM/TTS chết ngay

`OPENAI_API_KEY` rỗng. Log: `OPENAI_API_KEY is empty; STT/LLM/TTS will fail on live calls`.

### `Turn detection is not supported for this transcription model`

`OPENAI_STT_MODEL` đang là `gpt-live-transcribe`. Pipeline này **bắt buộc** cần server VAD
(cho barge-in và cho việc chốt lượt). Đổi về:

```bash
OPENAI_STT_MODEL=gpt-4o-transcribe
```

## Âm thanh

### Tiếng rè trắng cả hai chiều, không lỗi nào được báo

**Sai endianness L16.** RFC 2586 nói big-endian, nhưng Telnyx thực tế gửi little-endian.
Lật cờ:

```bash
TELNYX_L16_BYTESWAP=false
```

Nhớ dấu hiệu này — swap sai và không swap cho ra **hệt nhau**, và không exception nào
được ném.

### Webhook tới nhưng không có tiếng nào

`TELNYX_STREAM_URL` trỏ vào tunnel đã chết. Webhook dùng URL khác nên vẫn tới, cuộc gọi
vẫn được nhấc, nhưng media stream không kết nối được.

Kiểm tra host công khai còn sống, rồi cập nhật:

```bash
TELNYX_STREAM_URL=wss://<host-dang-song>/telnyx/media
```

### AI không nghe thấy gì

Grep log:

```
Mic PCM ... bytes=... peak=...
```

- `peak` quanh 0 → **micro câm**, vấn đề ở client hoặc codec, không phải ở STT
- Không có dòng nào → không frame âm thanh nào tới; kiểm tra client có gửi frame nhị phân
  không
- `PCM arrived before session.init` → client gửi tiếng trước khi gửi `session.init`; socket
  vẫn mở nhưng **thiếu lời chào và ngữ cảnh cửa hàng**

### AI tự cắt lời chính nó

Bạn đang test bằng loa ngoài. Tiếng AI lọt vào micro, VAD báo `speech_started`, barge-in
kích hoạt. **Đeo tai nghe.**

## Hội thoại

### AI nói "không tra cứu được chi nhánh"

`restaurant_missing = True`. Vài nguyên nhân:

- `session.init` gửi `toNumber` rỗng → log: `Hotline catalog skipped: empty toNumber`
- Không có nhà hàng nào trong BE khớp số đó
- Nhà hàng có `status != "active"`
- BE không phản hồi → log: `Hotline lookup error`

Thử tay: `curl http://127.0.0.1:8070/restaurants/by-hotline/<so>`

### AI xin lỗi mãi một câu suốt cuộc gọi

Lịch sử hội thoại hỏng: một message `assistant` mang `tool_calls` không được theo ngay bởi
kết quả tool → API trả 400 ở **mọi** lượt sau.

Đã có hai lớp chữa (`commit_tool_round` + `repair_tool_sequence`). Nếu vẫn gặp, grep:

```
Repaired malformed tool sequence in history
```

và xem `AI/llm/history.py`. Chi tiết: [chương 08](08-nghi-llm.md).

### AI nói đã đặt bàn nhưng database trống

Kiểm tra theo thứ tự:

1. `create_booking` có trả `ok: true` không (grep `Create booking ... succeeded`)
2. `finish_reason == "length"` — model bị cắt cụt, mất luôn lời gọi tool. Xem `max_tokens`.
3. Prompt nói rõ *không được nói thành công khi chưa có `ok: true`* — nếu model vẫn làm sai
   thì cần siết prompt.

### STT nghe sai tên món liên tục

Theo thứ tự:

1. Thực đơn đã nạp chưa? Grep `STT context updated callId=... keywords=<n>`. `n = 0` nghĩa
   là chưa có tên món nào được đẩy vào STT.
2. Chi nhánh đã khóa chưa? Chưa khóa thì chưa nạp được thực đơn.
3. Ghi âm rồi đo: bật `CALL_RECORD_DIR`, chạy `AI/scripts/stt_eval.py`.
4. Cân nhắc `TRANSCRIPTION_DELAY = "medium"` trong `AI/stt/realtime.py` (mặc định `"low"`).

### AI cắt lời khách giữa chừng

`STT_SILENCE_DURATION_MS` quá thấp. Mặc định 800 ms là **có chủ đích** — mốc cũ 450 ms cắt
vụn câu của người nói không phải bản ngữ. Đừng hạ khi chưa chạy `scripts/turn_stats.py`
trước và sau để có số đo.

### Bấm phím không ăn

- Đang có `create_booking` / `create_order` bay → phím bị bỏ qua có chủ đích
  (grep `Ignoring dtmf during create`)
- Bấm cùng phím trong 500 ms → chống dội (`DTMF_DEBOUNCE_MS`)
- Phím ngoài 1/2/3 quá 2 lần → thôi nhắc menu (`DTMF_MAX_INVALID`)

### Máy cúp quá sớm, khách bị cắt giữa câu

`CALL_END_GRACE_MS` (mặc định 300). Xem `remaining_playback_seconds()` trong
[chương 09](09-noi-tts.md).

## Cache & dữ liệu

### Sửa thực đơn trên dashboard mà AI không thấy

Snapshot Redis làm mới mỗi `SYNC_POLL_SECONDS` (mặc định 300 giây). Ép ngay:

```bash
curl -X POST http://127.0.0.1:8071/internal/sync/refresh \
     -H "Authorization: Bearer $AI_BRIDGE_TOKEN"
```

### `/health` báo `"degraded": true`

Syncer không kéo được catalog từ BE. Xem `last_sync_error` trong cùng response. Nó đang
backoff nhân đôi (tối đa `SYNC_MAX_BACKOFF_SECONDS = 2400`). BE sống lại thì tự trở về
nhịp thường.

### Cache hỏng làm chết cuộc gọi?

Không nên. Mọi thao tác cache đều bọc `try/except` và rơi về HTTP. Nếu thấy cuộc gọi chết
vì Redis, đó là **bug** — báo lại.

## Backend

### HTTP 400 mà không hiểu vì sao

`ValidationPipe` bật `forbidNonWhitelisted: true`: **một trường thừa trong body là 400**.
Đọc thân lỗi — nó nói rõ trường nào. `AI/calls/client.py` in sẵn thân lỗi vì lý do này.

### Mất dữ liệu sau khi đổi entity

`synchronize: true` khiến TypeORM tự sửa schema mỗi lần khởi động. Tiện cho dev, nguy hiểm
thật sự. Lên production phải chuyển sang migration.

## Cần thêm

- Vận hành cuộc gọi thật: `AI/RUNBOOK.md`
- Lịch sử sửa lỗi: `AI/documents/Repair_bug .md`
- Cải thiện STT: `AI/documents/stt-accuracy-playbook.md`
- Cấu hình Telnyx: `AI/documents/telnyx-setup.md`

## Tiếp theo

→ [20 — Thuật ngữ](20-thuat-ngu.md)
