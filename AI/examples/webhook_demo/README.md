# Webhook là gì — demo chạy được

Bốn file nhỏ, tự chạy độc lập, không đụng vào pipeline audio thật. Mục tiêu:
hiểu webhook trước, rồi mới đọc `telephony/telnyx/` khỏi ngợp.

## 1. Định nghĩa

**Webhook = HTTP callback.** Thay vì ta liên tục hỏi Telnyx "có cuộc gọi nào
chưa?" (polling), ta đưa cho Telnyx một URL. Khi có việc xảy ra, **Telnyx chủ
động POST vào URL đó**. Chiều gọi bị đảo: server của ta trở thành client của
sự kiện.

| | Polling | Webhook |
| --- | --- | --- |
| Ai mở kết nối | Ta hỏi Telnyx | Telnyx gọi ta |
| Độ trễ | Bằng chu kỳ hỏi | Gần như tức thì |
| Điều kiện | Không cần gì | Ta **phải** có URL công khai trên Internet |

Điều kiện cuối là lý do dev cần `ngrok` khi test ở máy local.

## 2. Webhook dùng làm gì trong dự án này

Một cuộc gọi đến đi qua **hai đường khác nhau**, đừng lẫn:

- `POST /telnyx/webhook` — **sự kiện điều khiển cuộc gọi**. HTTP, rời rạc, mỗi
  sự kiện một request: máy đang đổ chuông, đã nhấc, đã cúp.
- `WSS /telnyx/media` — **dòng audio**. WebSocket, mở liên tục suốt cuộc gọi.

Webhook chính là thứ *khởi động* đường audio kia:

```
1. Khách bấm số
2. Telnyx  --POST webhook: call.initiated-->  ta
3. ta      --POST API: answer-------------->  Telnyx     (nhấc máy)
4. Telnyx  --POST webhook: call.answered--->  ta
5. ta      --POST API: streaming_start----->  Telnyx     (kèm stream_url)
6. Telnyx  --WSS /telnyx/media------------->  ta         (audio bắt đầu chảy)
7. Telnyx  --POST webhook: call.hangup----->  ta
```

Bước 2/4/7 là webhook (Telnyx → ta). Bước 3/5 là REST API (ta → Telnyx). Hai
chiều này **dùng hai cơ chế xác thực khác nhau**: webhook xác thực bằng chữ ký
Ed25519, còn ta gọi API thì xác thực bằng `Authorization: Bearer <API_KEY>`.

## 3. Hai vấn đề mọi webhook đều phải giải

**(a) URL công khai → ai cũng POST được.** Không kiểm chữ ký thì người lạ bắt
được hệ thống nhấc máy và mở stream, tiêu tiền trên tài khoản Telnyx của bạn.
Telnyx ký mỗi request bằng Ed25519:

```
chuỗi được ký = f"{telnyx-timestamp}|" + raw_body
```

Chú ý **raw body** — phải ký/kiểm trên đúng chuỗi byte truyền đi. Parse JSON ra
rồi serialize lại để kiểm là lỗi kinh điển (đổi dấu cách, đổi thứ tự key là
chữ ký hỏng). `timestamp` nằm trong phần được ký nên không sửa được, và ta từ
chối timestamp quá cũ để chặn replay.

**(b) Webhook được gửi lại (retry).** Telnyx coi non-2xx là thất bại và gửi
lại. Nên khi chữ ký đã hợp lệ thì **luôn trả 200**, kể cả xử lý bên trong lỗi:
một lần gửi lại `call.answered` sẽ cố mở stream thứ hai, mà Telnyx chỉ cho một
stream mỗi cuộc gọi. Lỗi thì log, đừng trả lỗi về.

## 4. Chạy demo

```bash
cd examples/webhook_demo
python keygen.py                                       # tạo cặp khóa giả lập

# 3 terminal riêng:
python -m uvicorn fake_telnyx:app   --port 9090        # Telnyx giả
python -m uvicorn webhook_server:app --port 8080       # server của ta
python place_call.py                                   # giả lập cuộc gọi đến
```

Kết quả mong đợi ở terminal `place_call.py`:

```
[GỬI  ] call.initiated     -> HTTP 200 {"ok":true}
[GỬI  ] call.answered      -> HTTP 200 {"ok":true}
[GỬI  ] call.hangup        -> HTTP 200 {"ok":true}
```

và ở terminal Telnyx giả:

```
[TELNYX] nhận lệnh 'answer' cho ccid=v3:demo-call-abc123
[TELNYX] nhận lệnh 'streaming_start' cho ccid=v3:demo-call-abc123
         sẽ mở WebSocket tới wss://demo.example.com/telnyx/media?token=demo-token
```

Xem lại toàn bộ lệnh đã nhận: `curl http://127.0.0.1:9090/commands`

Thử ca tấn công — sửa nội dung sau khi ký:

```bash
python place_call.py --tamper     # -> HTTP 401 invalid_signature
```

## 5. Map sang code thật

| File demo | File thật | Khác nhau chỗ nào |
| --- | --- | --- |
| `webhook_server.py` :: `webhook()` | [routes.py](../../telephony/telnyx/routes.py) `POST /telnyx/webhook` | Bản thật đọc config từ `.env`, lọc `direction != "incoming"`, log kỹ hơn |
| `webhook_server.py` :: `verify()` | [signature.py](../../telephony/telnyx/signature.py) `verify_webhook` | Giống hệt về thuật toán; bản thật tách ra để test riêng |
| `webhook_server.py` :: `telnyx_command()` | [api.py](../../telephony/telnyx/api.py) `TelnyxClient` | Bản thật dùng 1 `AsyncClient` dùng chung cả process, có xử lý lỗi 422 |
| `fake_telnyx.py` | (không có — là Telnyx thật) | — |
| *(không có trong demo)* | [stream.py](../../telephony/telnyx/stream.py) `TelnyxCallSocket` | Phần audio: WebSocket `/telnyx/media`, cái mà `streaming_start` khởi động |

Đọc tiếp: [telnyx-integration.md](../../documents/telnyx-integration.md) cho
kiến trúc, [telnyx-setup.md](../../documents/telnyx-setup.md) cho cách cấu hình
URL webhook trên portal, và `tests/test_telnyx.py` cho các ca kiểm chữ ký.
