# Tích hợp Telnyx (Call Control v2 + Media Streaming)

Cho phép người gọi PSTN gọi thẳng vào số Telnyx và nói chuyện với pipeline AI
sẵn có. **Không sửa một dòng nào** trong `bridge/session.py`, `llm/`, `tts/`,
`stt/`, `booking/`, `order/`.

---

## 1. Ý tưởng: adapter hình dạng socket

`CallPipeline` chỉ hỏi socket của nó đúng bốn thứ: `receive`, `send_bytes`,
`send_text`, `close`. `TelnyxCallSocket` đáp ứng đúng bốn thứ đó — nên với
pipeline, Telnyx trông y hệt một backend điện thoại nói đúng hợp đồng cũ.

```
Nguoi goi PSTN
      |
      v
   Telnyx  --- POST /telnyx/webhook ---> answer, streaming_start   (HTTP, ky Ed25519)
      |
      `--- WSS /telnyx/media  <JSON + base64 L16 16 kHz>
                  |
                  v
          TelnyxCallSocket        <-- day la toan bo phan moi
           |            ^
           | PCM16-LE   | PCM16-LE
           | 24 kHz     | 24 kHz
           v            |
            CallPipeline (khong doi)
                  |
          STT -> LLM -> TTS
```

## 2. Vòng đời một cuộc gọi

| # | Bên nào | Việc gì |
| --- | --- | --- |
| 1 | Telnyx → ta | `POST /telnyx/webhook` với `call.initiated` |
| 2 | ta → Telnyx | `answer` (nhấc máy) |
| 3 | Telnyx → ta | `call.answered` |
| 4 | ta → Telnyx | `streaming_start` trỏ về `TELNYX_STREAM_URL` |
| 5 | Telnyx → ta | mở WSS `/telnyx/media`, gửi `connected` rồi `start` |
| 6 | adapter | Dựng `session.init` từ `start` (`to` → `toNumber`) và đẩy vào pipeline |
| 7 | pipeline | Phát lời chào (đã tự ghép menu DTMF), rồi nghe |
| 8 | hai chiều | `media` ↔ `media`; `dtmf`; `clear` khi bị ngắt lời |
| 9 | kết thúc | Pipeline gửi `call.end` → adapter gửi `mark`, đợi echo, rồi `hangup` |

## 3. Ba điểm kỹ thuật dễ sai

**L16 là big-endian.** RFC 2586 quy định network byte order; pipeline, OpenAI
và `soxr` đều dùng little-endian. Thiếu byteswap thì **không có lỗi nào báo** —
chỉ ra tiếng ồn trắng. Xử lý ở `telephony/telnyx/codec.py:swap16`.

**Byteswap và resample đều cần nguyên mẫu 16-bit.** Một chunk kết thúc giữa
mẫu phải mang byte lẻ sang chunk sau, nếu không mọi mẫu phía sau lệch một byte.

**Đuôi audio nằm trong bộ lọc soxr.** `soxr` giữ lại khoảng một độ dài filter.
Nếu chỉ xả buffer mà không đóng stream thì cuối mỗi lượt nói bị cắt cụt.
`OutboundTranscoder.flush()` đóng stream rồi tạo lại cho lượt sau.

## 4. Barge-in và cúp máy

Đường `/v1/bridge` phải **ước lượng** khi nào client phát xong. Telnyx thì biết
thật, nên adapter dùng luôn:

- **Ngắt lời:** pipeline gửi `interrupt` → adapter gửi `{"event":"clear"}`,
  Telnyx xóa ngay buffer chưa phát, đồng thời reset bộ resample chiều ra để
  lượt mới không thừa hưởng đuôi của lượt bị ngắt.
- **Cúp máy:** pipeline gửi `call.end` → adapter xả đuôi, gửi
  `{"event":"mark","mark":{"name":"ai-bridge-call-end"}}`, đợi Telnyx echo lại
  (nghĩa là đã phát hết), rồi mới gọi `hangup`. Quá `TELNYX_MARK_TIMEOUT_SECONDS`
  thì cúp luôn để không treo cuộc gọi.

## 5. Bảo mật

| Đường | Cách bảo vệ |
| --- | --- |
| `POST /telnyx/webhook` | Chữ ký Ed25519 (`telnyx-signature-ed25519` + `telnyx-timestamp`), chống replay theo cửa sổ thời gian. Sai chữ ký → 401. |
| `WSS /telnyx/media` | `?token=` so khớp `TELNYX_STREAM_TOKEN`. Telnyx **không** ký WebSocket nên đây là cách duy nhất. |

Webhook đã ký thì **luôn trả 200**, kể cả khi xử lý lỗi: non-2xx khiến Telnyx
gửi lại, và một lần gửi lại `call.answered` sẽ cố mở stream thứ hai (Telnyx chỉ
cho một stream mỗi cuộc gọi).

## 6. Cấu hình

Bật bằng `TELNYX_ENABLED=true`. Mặc định **tắt** — không bật thì service chạy y
hệt trước đây. `BRIDGE_ENABLED=false` để gỡ `/v1/bridge` khi chỉ chạy Telnyx.

Toàn bộ biến môi trường nằm trong [.env.example](../.env.example), phần
`--- Telnyx Call Control v2 + Media Streaming ---`. Bốn biến bắt buộc:

```
TELNYX_ENABLED=true
TELNYX_API_KEY=KEY...                       # Portal > API Keys
TELNYX_PUBLIC_KEY=...                       # Portal > Keys & Credentials (base64 Ed25519)
TELNYX_STREAM_URL=wss://<host>/telnyx/media
TELNYX_STREAM_TOKEN=<chuoi ngau nhien>
```

## 7. Còn phải làm bên Telnyx

Phần này nằm ngoài repo, làm trên portal Telnyx: mua số, tạo Call Control
Application, gán số vào app, lấy khóa Ed25519, mở đường ra internet bằng ngrok.

Hướng dẫn thao tác từng bước — kèm cách gọi thử không tốn cước quốc tế và bảng
tra sự cố — nằm ở **[telnyx-setup.md](telnyx-setup.md)**.

## 8. Giới hạn đã biết

- **Chỉ gọi vào.** Gọi ra chưa làm (cần thêm lệnh `dial` + xử lý máy bận /
  hộp thư thoại).
- **Lời chào là chung, không có tên quán.** Đổi lại là phát ngay khi nhấc máy;
  tên quán được nạp song song qua `toNumber` và LLM dùng từ lượt sau.
- **Telnyx chỉ cho một stream mỗi cuộc gọi**, nên không fork thêm để ghi âm
  riêng bằng đường này.
- `transcript` / `agent.speech` / `order.created` chỉ dành cho UI demo — Telnyx
  không có chỗ nhận, nên adapter chỉ ghi log.

## 9. File liên quan

| File | Việc |
| --- | --- |
| [telephony/telnyx/codec.py](../telephony/telnyx/codec.py) | L16 big-endian ↔ PCM16-LE 24 kHz, đóng khung 20 ms |
| [telephony/telnyx/stream.py](../telephony/telnyx/stream.py) | `TelnyxCallSocket` — socket ảo cho `CallPipeline` |
| [telephony/telnyx/routes.py](../telephony/telnyx/routes.py) | `POST /telnyx/webhook`, `WSS /telnyx/media` |
| [telephony/telnyx/api.py](../telephony/telnyx/api.py) | `answer`, `streaming_start`, `hangup` |
| [telephony/telnyx/signature.py](../telephony/telnyx/signature.py) | Xác thực Ed25519 |
| [tests/test_telnyx.py](../tests/test_telnyx.py) | 26 test: codec, chữ ký, socket ảo, toàn tuyến qua pipeline thật |
