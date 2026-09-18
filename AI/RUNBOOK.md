# Runbook — chạy lại toàn bộ hệ thống và gọi thử

Checklist khởi động lại từ máy đã tắt, tới lúc nói chuyện được với AI qua điện thoại.

- Thiết lập Telnyx lần đầu (mua số, tạo application): [documents/telnyx-setup.md](documents/telnyx-setup.md)
- Chi tiết backend/frontend: [run_fe_be.md](run_fe_be.md)

Tài liệu này giả định mọi thứ **đã cấu hình xong** và chỉ cần bật lại.

---

## Cấu hình đang chạy

| Hạng mục | Giá trị |
| --- | --- |
| Số Telnyx | `+1 773 302 2476` |
| Hotline trong DB | `17733022476` (chỉ chữ số, có mã quốc gia `1`) |
| Call Control App | `AI Bridge Dev`, Webhook **API v2** |
| Webhook URL | `https://aiapi.jupiter-ai.pro/telnyx/webhook` |
| Stream URL | `wss://aiapi.jupiter-ai.pro/telnyx/media` |
| SIP connection | `Forward Only`, user `4mgtb3k0duz6` |
| Database | `restaurant_ai` trong container `ai_receptionist_db`, user `receptionist` |

`aiapi.jupiter-ai.pro` là tunnel trỏ về **chính máy dev này**, cổng `127.0.0.1:8071`
(khớp `AI_BRIDGE_PORT` trong `AI/.env`). Vì vậy webhook và stream chỉ chạy khi máy bật
và tunnel còn sống; đổi cổng AI thì phải sửa cổng đích của tunnel cho khớp.
Ngrok (`ngrok http 8071`) chỉ còn là phương án dự phòng — nếu dùng thì phải sửa **cả hai**
chỗ: `TELNYX_STREAM_URL` trong `.env` và Webhook URL trên portal Telnyx.

---

## Khởi động — 4 terminal

### 1. Hạ tầng Docker

```powershell
docker start ai_receptionist_db
docker start aibridge-redis
docker ps --filter name=ai_receptionist_db --filter name=aibridge-redis
```

Đợi `ai_receptionist_db` đạt `healthy`.

> Đừng dùng `docker compose` cho `ai_receptionist_db` — container này mồ côi,
> thư mục compose sinh ra nó (`D:\phone_call_project`) đã bị xóa. Chi tiết và
> lệnh dựng lại thủ công nằm trong [run_fe_be.md](run_fe_be.md).

### 2. NestJS API

```powershell
cd D:\phonecall\restaurant-backend
npm run start:dev
```

Chờ dòng `Ứng dụng đang chạy tại: http://localhost:8070`.

### 3. React dashboard

```powershell
cd D:\phonecall\restaurant-frontend
npm run dev
```

### 4. Đường ra internet (tunnel)

Cấu hình đang dùng: `aiapi.jupiter-ai.pro` → `127.0.0.1:8071` (không cần chạy gì thêm trên
máy). Kiểm tra tunnel sống:

```bash
curl -s https://aiapi.jupiter-ai.pro/health
```

Phương án dự phòng (nếu phải dùng ngrok):

```powershell
ngrok http 8071
```

Phải thấy `https://caregiver-trustable-speech.ngrok-free.dev -> http://localhost:8071`,
rồi đổi `TELNYX_STREAM_URL` trong `.env` và Webhook URL trên portal Telnyx cho khớp.

### 5. AI Bridge

Chạy **sau** NestJS, để bridge sync được catalog ngay lúc khởi động.

```powershell
cd D:\phonecall\phone_call_project
.venv\Scripts\Activate.ps1
python app.py
```

---

## Kiểm tra trước khi gọi

```powershell
curl http://127.0.0.1:8070/restaurants/by-hotline/17733022476
curl http://127.0.0.1:8071/health
curl https://aiapi.jupiter-ai.pro/health
```

Ba dòng log bắt buộc phải có khi `app.py` khởi động:

```
Telnyx routes mounted: POST /telnyx/webhook, WS /telnyx/media
Cache swap ... (restaurants=1, branches=5, hotlines=1)
Application startup complete.
```

`/health` phải trả `"cache": {"enabled": true, "ready": true, "degraded": false}`.

| Thấy gì | Nghĩa là |
| --- | --- |
| `"enabled": false` | Redis chưa chạy → `docker start aibridge-redis` |
| `"ready": false` | NestJS chưa chạy, hoặc sai `RESTAURANT_API_BASE` |
| thiếu dòng `Telnyx routes mounted` | `TELNYX_ENABLED` chưa là `true` |

Nếu vừa sửa dữ liệu nhà hàng trên dashboard, ép bridge nạp lại thay vì chờ 300 giây:

```powershell
curl -X POST http://127.0.0.1:8071/internal/sync/refresh -H "Authorization: Bearer <AI_BRIDGE_TOKEN>"
```

---

## Gọi thử bằng Zoiper

**Web Dialer trên portal Telnyx không dùng được.** Nút gọi luôn bị khóa vì nó chỉ
liệt kê Caller ID Number thuộc connection đang chọn, mà số `+17733022476` lại gán
cho `AI Bridge Dev` chứ không phải `Forward Only`. Đừng gán số sang `Forward Only`
để chữa — làm vậy cuộc gọi đến sẽ không vào được pipeline AI nữa.

Cấu hình Zoiper (một lần):

```
Domain / Host : sip.telnyx.com
Username      : 4mgtb3k0duz6
Password      : (lấy ở Portal > Voice > SIP Connections > Forward Only)
Transport     : SIP UDP, hoặc SIP TCP nếu UDP không được
```

> Không chọn **SIP TLS** (cần Zoiper PRO trả phí) và không chọn **IAX UDP**
> (giao thức Asterisk, Telnyx không dùng).
>
> Mật khẩu SIP là bí mật — không ghi vào file nào được commit.

Gọi tới `17733022476`. Cách gọi thử cho ra kết quả đọc được:

1. Giữ máy **ít nhất 15 giây**. Lời chào dài ~8 giây, cúp sớm là không nghe hết.
2. **Im lặng** cho tới khi AI nói xong, tránh kích hoạt barge-in.
3. Nói rõ và đủ to bằng **tiếng Anh** (`TELNYX_DEFAULT_LOCALE=en`), ví dụ
   *"I want to book a table"*.
4. Đợi thêm 5 giây rồi mới cúp.

---

## Log của một cuộc gọi thành công

```
Telnyx call.initiated ccid=... from=4mgtb3k0duz6@sip.telnyx.com to=+17733022476
Telnyx call.answered ccid=...; starting stream
WebSocket /telnyx/media?token=... [accepted]
Telnyx stream connected version=1.0.0
Telnyx start stream=... encoding=L16 in_rate=16000 out_rate=16000
Hotline catalog ... restaurant='Nhà hàng A' branches=5
Realtime transcription connected
POST https://api.openai.com/v1/audio/speech "HTTP/1.1 200 OK"
Người gọi: <câu bạn vừa nói>
Telnyx stream stop ... media_in=328 media_out=416
```

Bốn chỉ dấu quan trọng nhất:

| Dấu hiệu | Ý nghĩa |
| --- | --- |
| `restaurant='Nhà hàng A'` | hotline khớp, AI biết đang trực cho quán nào |
| `media_out` > 0 | AI thật sự có phát tiếng ra |
| `Người gọi: <chữ có nghĩa>` | STT nghe được giọng bạn |
| `peak` không phải `32768` liên tục | audio vào không bị hỏng |

---

## Chẩn đoán nhanh

| Triệu chứng | Nguyên nhân |
| --- | --- |
| **Tiếng rè trắng cả hai chiều**, không lỗi nào báo | `TELNYX_L16_BYTESWAP` sai. Telnyx gửi **little-endian**, phải để `false`. Xem mục dưới. |
| Gọi vào, log trống trơn | `python app.py` chưa chạy, hoặc ngrok chết, hoặc số chưa gán vào `AI Bridge Dev` |
| `Rejecting Telnyx webhook` / HTTP 401 | `TELNYX_PUBLIC_KEY` sai hoặc trống |
| `media_out=0`, lời chào bị cắt ngay | barge-in do audio vào bão hòa (`peak=32768`) |
| `Người gọi: .` (chỉ dấu chấm) | STT nhận được rác, không phải giọng nói |
| `Hotline catalog not found` | hotline trong DB không khớp. Phải là `17733022476`, chỉ chữ số |
| WebSocket bị đóng `1008 Unauthorized` | `TELNYX_STREAM_TOKEN` trong `.env` khác token trong `TELNYX_STREAM_URL` |
| Traceback `422 Call has already ended` | Vô hại. App cúp máy sau khi người gọi đã cúp; lỗi đã được bắt |
| Traceback Redis lúc khởi động | Vô hại, đã được bắt. Tìm `Application startup complete` phía dưới |
| `password authentication failed for user "postgres"` | Backend dùng user sai. Phải là `receptionist`/`receptionist` |

---

## Về `TELNYX_L16_BYTESWAP`

RFC 2586 quy định L16 là network byte order (big-endian), và code mặc định theo
chuẩn đó. **Telnyx thực tế gửi little-endian.**

Đã kiểm chứng bằng cuộc gọi thật ngày 16/09/2026: để `true` thì `swap16` phá dữ
liệu ở cả hai chiều — người gọi nghe tiếng rè trắng, còn STT nhận được rác biên
độ cực đại (`peak=32768` ngay frame đầu, phiên âm ra đúng một dấu chấm).

```
TELNYX_L16_BYTESWAP=false
```

Lỗi này **không ném exception ở đâu cả**, nên đừng tìm nó trong traceback. Triệu
chứng duy nhất là âm thanh.

---

## Dừng

```powershell
# NestJS / Vite / ngrok / app.py: Ctrl+C trong terminal tương ứng
docker stop ai_receptionist_db aibridge-redis
```

Tắt container không mất dữ liệu. Data chỉ mất khi xóa volume
`phone_call_project_postgres_data`.

Nếu Ctrl+C không dứt điểm (tiến trình `nest start --watch` hay chiếm lại cổng):

```powershell
netstat -ano | findstr ":8070 :3070 :8071"
taskkill /PID <pid> /T /F
```
