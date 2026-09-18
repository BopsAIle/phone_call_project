# 13 — Telnyx: cuộc gọi thật

Thư mục: `AI/telephony/telnyx/`. Bật bằng `TELNYX_ENABLED=true`.

## Telnyx là gì trong dự án này

Telnyx là nhà mạng VoIP. Họ cho bạn một số điện thoại thật; khi ai đó gọi vào, họ gửi
**webhook HTTP** báo cho bạn biết, và mở một **WebSocket** đẩy âm thanh hai chiều.

## Luồng đầy đủ một cuộc gọi

```
1. Khách bấm số
       │
2. Telnyx ──POST /telnyx/webhook  {event_type: "call.initiated"}──> AI Bridge
       │                                     AI gọi ngược: answer(call_control_id)
       │
3. Telnyx ──POST /telnyx/webhook  {event_type: "call.answered"}───> AI Bridge
       │                                     AI gọi ngược: streaming_start(stream_url=wss://...)
       │
4. Telnyx ──WS /telnyx/media  connected → start → media… → dtmf → stop──> AI Bridge
       │
5. TelnyxCallSocket giả dạng socket bridge → CallPipeline chạy y hệt như thường
```

Mã: `AI/telephony/telnyx/routes.py` (webhook + WS), `stream.py` (socket giả),
`api.py` (gọi ngược Telnyx), `signature.py` (xác minh chữ ký), `codec.py` (âm thanh).

## Bảo mật hai kiểu cho hai kênh

**Webhook HTTP** — Telnyx ký bằng **Ed25519**. `verify_webhook()` kiểm tra chữ ký
(header `telnyx-signature-ed25519`) và dấu thời gian (`telnyx-timestamp`, cửa sổ
`TELNYX_WEBHOOK_TOLERANCE_SECONDS`, mặc định 300 giây). Sai chữ ký → HTTP 401.

**Media WebSocket** — Telnyx **không ký** kênh này. Nên token đi trong URL:

```python
stream_url = "wss://host/telnyx/media?token=<TELNYX_STREAM_TOKEN>"
```

Sai token → đóng socket với code 1008.

### Vì sao webhook luôn trả 200

```python
# Always 200 on a signed webhook: a non-2xx makes Telnyx retry, and a
# retry of call.answered would try to start a second stream.
return _ok()
```

Chữ ký đã đúng thì dù xử lý bên trong có hỏng cũng trả 200. Trả lỗi là Telnyx gửi lại, và
một lần gửi lại `call.answered` sẽ mở **stream thứ hai** cho cùng cuộc gọi.

## `TelnyxCallSocket` — mảnh ghép thiết kế hay nhất

`CallPipeline` chỉ hỏi socket của nó đúng **bốn** thứ: `receive`, `send_bytes`,
`send_text`, `close`. `TelnyxCallSocket` cài đúng bốn cái đó.

```
Telnyx WS  --JSON/base64 L16-->  TelnyxCallSocket  --PCM16-LE 24 kHz-->  CallPipeline
           <--JSON/base64 L16--                    <--PCM16-LE 24 kHz--
```

Kết quả: **`AI/bridge/session.py` không có một dòng nào biết Telnyx tồn tại.** Muốn thêm
Twilio hay Vonage sau này, viết thêm một class socket giả là xong.

Nó cũng **tự sinh sự kiện `session.init`** từ dữ liệu trong frame `start` của Telnyx
(số gọi đến, số gọi đi) cộng với các giá trị mặc định trong `.env`
(`TELNYX_DEFAULT_STORE_NAME`, `TELNYX_DEFAULT_LOCALE`, `TELNYX_GREETING`…). Pipeline nhận
được `session.init` y như từ một client bridge bình thường.

`wait_for_start()` chặn cho tới khi Telnyx gửi frame `start` — frame đó mới mang số điện
thoại và codec. Không đợi là không biết đang nói chuyện với ai.

## Âm thanh: cái bẫy lớn nhất dự án

`AI/telephony/telnyx/codec.py` mở đầu bằng cảnh báo:

> Two traps live here, both silent if you get them wrong.

**Bẫy 1 — endianness.** RFC 2586 nói L16 là *network byte order* (big-endian). Bridge,
OpenAI và `soxr` đều dùng little-endian. Thiếu byteswap **không phải là lỗi** — nó là
**tiếng rè trắng**. Swap khi không nên swap cũng cho ra y hệt tiếng rè trắng, và không
có exception nào được ném.

```python
TELNYX_L16_BYTESWAP=false
# RFC nói big-endian, NHƯNG Telnyx thực tế gửi little-endian.
# Đã kiểm chứng bằng cuộc gọi thật: để true -> tiếng rè trắng cả hai chiều.
```

Ghi nhớ: **tiếng rè trắng ⇒ lật cờ này**.

**Bẫy 2 — mẫu bị cắt đôi.** Cả byteswap lẫn resample đều cần **mẫu 16 bit nguyên vẹn**.
Chunk kết thúc giữa một mẫu phải mang byte lẻ sang chunk sau (`even_pcm16` + `leftover`).

### Chuyển đổi tần số

```
vào:  Telnyx L16 @ 16 kHz  → byteswap → StreamResampler(16000→24000) → PCM16-LE 24 kHz
ra:   PCM16-LE 24 kHz      → StreamResampler(24000→16000) → byteswap → frame 20 ms
```

`StreamResampler` (`AI/audio/resample.py`) dùng `soxr` chất lượng `HQ` và **giữ trạng
thái** giữa các chunk, nên ranh giới chunk không kêu lách cách.

### Vì sao frame 20 ms

Telnyx nhận frame từ 20 ms tới 30 giây. Dự án chọn mức thấp nhất: frame càng ngắn thì
lệnh `clear` lúc barge-in càng vứt đi ít tiếng đã lỡ nằm trong buffer.

## Cúp máy êm — cơ chế `mark`

Khi AI muốn kết thúc, không thể cúp ngay: Telnyx còn đang phát nốt những frame đã nhận.

```python
CALL_END_MARK = "ai-bridge-call-end"
```

`_drain_then_hangup()` gửi một `mark` sau frame cuối, rồi **đợi Telnyx báo lại đã phát
tới mark đó** (tối đa `TELNYX_MARK_TIMEOUT_SECONDS`, mặc định 20 giây), sau đó mới gọi
hangup.

## Cần một địa chỉ công khai

Telnyx không gọi được vào `localhost`. Hai lựa chọn đang dùng:

- **ngrok trong Docker** — bật khi `.env` gốc có `NGROK_AUTHTOKEN`.
  Inspector: http://localhost:4040
- **Cloudflare tunnel** — `https://aiapi.jupiter-ai.pro` → `127.0.0.1:8071`

Cấu hình trên portal Telnyx (Call Control App `AI Bridge Dev`):
webhook `https://<host>/telnyx/webhook`.
Trong `AI/.env`: `TELNYX_STREAM_URL=wss://<host>/telnyx/media`.

> **Sai lầm kinh điển:** `TELNYX_STREAM_URL` trỏ vào một tunnel đã chết. Webhook vẫn tới
> (vì webhook dùng URL khác), cuộc gọi vẫn được nhấc, nhưng **không có tiếng nào cả**.

`AI_BRIDGE_HOST=127.0.0.1` là đủ khi tunnel chạy cùng máy. Chỉ đổi sang `0.0.0.0` khi
dùng **container ngrok** — container gọi qua `host.docker.internal:8071`.

## Kiểm tra không tốn tiền

```bash
./scripts/telnyx-test.sh
```

Ba mục phải xanh:

| Mục | Kỳ vọng |
| --- | --- |
| `/health` | 200 |
| `/telnyx/webhook` | **401** khi gửi không ký — chứng tỏ xác minh chữ ký đang chạy |
| `/telnyx/media` | **403/1008** khi sai token |

Đặt cuộc gọi thật (tốn tiền): `./scripts/telnyx-test.sh --dial +84xxxxxxxxx`

Gọi thử bằng softphone SIP (Zoiper): host `sip.telnyx.com`, thông tin SIP Connection lấy
ở portal. Chi tiết trong `AI/RUNBOOK.md`.

## Thử offline

`AI/examples/webhook_demo/` mô phỏng Telnyx ngay trên máy: `keygen.py` sinh cặp khóa
Ed25519, `fake_telnyx.py` gửi webhook đã ký, `webhook_server.py` là server nhận mẫu.
Không cần tài khoản Telnyx, không tốn tiền.

## Tiếp theo

→ [14 — Cache Redis & đồng bộ](14-cache-va-sync.md)
