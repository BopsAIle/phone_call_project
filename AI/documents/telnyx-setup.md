# Thiết lập Telnyx từ số 0

Hướng dẫn thao tác trên portal Telnyx để có một cuộc gọi thật chạy qua pipeline.
Phần kiến trúc và lý do thiết kế nằm ở [telnyx-integration.md](telnyx-integration.md).

Giao diện portal Telnyx có thể đổi tên menu theo thời gian. Tên ô dưới đây là
tên tại thời điểm viết — nếu không thấy, tìm theo từ khóa tiếng Anh in kèm.

---

## 0. Lộ trình hai giai đoạn

Dự án nhắm thị trường Đức (`Europe/Berlin`, `locale: "de"`), nhưng **không nên
bắt đầu bằng số Đức**. Số Đức đòi địa chỉ Đức, hóa đơn điện nước, và người mua
phải đang ở Đức — chưa làm được thì cả dự án đứng.

| | Giai đoạn test (bây giờ) | Giai đoạn production (sau) |
| --- | --- | --- |
| Số | Mỹ, ~1 USD/tháng | Đức, đăng ký theo địa chỉ nhà hàng |
| Giấy tờ | Không cần giấy tờ vùng miền | ID/đăng ký kinh doanh + hóa đơn điện nước |
| Chờ duyệt | Tới 48 giờ nếu phải lên Level 2 (xem 1.0) | ~72 giờ |
| Ai gọi vào | Đội dev, qua Web Dialer | Khách Đức, qua điện thoại thật |

**Code không đổi một dòng nào khi chuyển giai đoạn.** Số điện thoại chỉ là một
chuỗi trong dữ liệu nhà hàng; `_load_catalog` trong [bridge/session.py](../bridge/session.py)
tra nhà hàng theo số bị gọi, không quan tâm số đó ở nước nào.

---

## 1. Mua số điện thoại

### 1.0 Kiểm tra tài khoản trước — bước này quyết định mọi thứ

Telnyx **không cho mọi tài khoản mua mọi số**. Ràng buộc theo cấp tài khoản, và
nó quyết định bạn mua được số nước nào:

| Cấp | Mua được gì |
| --- | --- |
| **Trial** | Đúng **1 số local của nước đăng ký tài khoản**, tính cả đời tài khoản. Có 5 USD credit. Số bị **thu hồi sau 30 ngày** nếu không nâng cấp. Gọi chỉ tới/từ số đã xác minh. |
| **Level 1** (tự có sau khi xác nhận email) | Số local **của nước mình**. Không mua được số quốc tế. Không mua được toll-free. |
| **Level 2** | Số quốc tế, gọi quốc tế, không còn giới hạn đặt số. |

**Đội ở Việt Nam, tài khoản đăng ký tại Việt Nam, đang Level 1 → không mua được
số Mỹ.** Chỉ mua được số Việt Nam, mà số Việt Nam khoảng 35 USD/tháng và cần
giấy tờ.

Xem cấp hiện tại ở **Account Settings → Verifications**.

### 1.1 Lên Level 2 nếu cần

Điều kiện:

1. Đang ở Level 1.
2. Điền số liên hệ và tên công ty ở **Account Settings → Profile**.
3. Có phương thức thanh toán trong **Billing**.

Rồi vào **Account Settings → Verifications** → mở mục Level 2 → điền form →
**Request Level 2 Verification**.

Duyệt **tới 48 giờ**. Chỉ chủ tổ chức (organization owner) mới thấy mục này.

> Thêm thẻ thanh toán dù sao cũng phải làm: tài khoản trial bị **thu hồi số sau
> 30 ngày** nếu không nâng cấp, và không nạp tiền được vào tài khoản Freemium.

### 1.2 Chọn nước

**Test: số Mỹ**, khoảng 1 USD/tháng, không cần giấy tờ vùng miền — nhưng cần
Level 2 nếu tài khoản không đăng ký ở Mỹ (xem 1.0).

Đừng mua số Việt Nam dù đội đang ở Việt Nam — khoảng **35 USD/tháng**, gấp ~35
lần số Mỹ, lại vẫn phải nộp giấy tờ. Không đáng, vì phần lớn việc test sẽ không
gọi qua mạng điện thoại thật (xem [mục 2](#2-gọi-thử-mà-không-tốn-cước-quốc-tế)).

**Production: bắt buộc số Đức.** Khách Đức gọi vào số `+1` phải trả cước quốc
tế và sẽ nghĩ là lừa đảo.

### 1.2b Thao tác mua

1. Portal → **Numbers** → **My Numbers** → **Buy Number** (hoặc **Search Numbers**).
2. Đặt bộ lọc:
   - **Country**: United States
   - **Type**: Local
   - **Features**: chọn **Voice** (không cần SMS/MMS cho dự án này)
   - **Search By**: Area Code, rồi nhập mã vùng bất kỳ — `212` New York,
     `415` San Francisco. Với việc test thì mã vùng nào cũng như nhau.
3. Chọn một số → **Add to Cart**.
4. Trong giỏ, kiểm tra **phí kích hoạt một lần** và **phí hàng tháng** trước khi
   thanh toán. Giỏ hàng có ô gán Connection — **để trống**, vì Call Control
   Application chưa tạo. Gán sau ở [bước 4](#4-gán-số-vào-application).
5. Thanh toán.

> **Mua rồi không hoàn tiền.** Kiểm giá và đúng loại số trước khi bấm.

Sau khi mua, số xuất hiện ở **Numbers → My Numbers**, và trạng thái đơn hàng ở
trang **Orders**. Số chưa làm được gì cho tới [bước 4](#4-gán-số-vào-application).

### 1.3 Ba loại số Đức, khi tới lúc

| Loại | Đầu số | Ai trả cước | Ghi chú |
| --- | --- | --- | --- |
| Địa phương | `030` Berlin, `089` München… | Khách, giá nội hạt | Hợp lý nhất. Địa chỉ đăng ký phải đúng vùng đó. |
| Toàn quốc | `032` | Khách | Không ràng buộc vùng, tiện cho chuỗi nhiều chi nhánh. Người Đức ít quen. |
| Miễn phí | `0800` | **Quán trả** | Telnyx bắt buộc là doanh nghiệp. Cân nhắc vì cước đổ về quán. |

Số ở Berlin, Frankfurt, Hamburg, München dài 10 chữ số (không tính số 0 đầu);
thành phố khác 11 chữ số.

Giấy tờ cần cho số Đức: địa chỉ Đức khớp vùng đầu số, hóa đơn điện/nước/gas
không quá 3 tháng, hộ chiếu hoặc giấy đăng ký kinh doanh Đức, mẫu đăng ký có
chữ ký. Chỉ nhận **bản scan**. Duyệt khoảng 72 giờ.

> **Cân nhắc cho production:** thay vì mua số mới, có thể **chuyển số sẵn có của
> quán** sang Telnyx (porting). Quán đã in số đó lên menu, biển hiệu, Google
> Maps — cho họ số mới là bắt họ đổi hết và mất khách gọi lại. Port chậm hơn
> (thường vài tuần) và giấy tờ nhiều hơn, nhưng đúng bản chất hơn.

---

## 2. Gọi thử mà không tốn cước quốc tế

Đây là phần tiết kiệm nhất, nên đọc trước khi bắt đầu test.

### 2.1 Web Dialer — cách chính

Portal Telnyx có sẵn một bàn phím gọi trong trình duyệt. Gọi thẳng vào số của
mình, không cần điện thoại, không cước quốc tế.

Tìm ở phần **Debugging** / **Tools** trong portal. Nhập số của mình, bấm gọi.

Dùng nó cho 90% việc test: webhook có tới không, AI có chào không, ngắt lời có
nhạy không, bấm phím có ăn không.

### 2.2 Softphone — khi cần test từ điện thoại

Khi cần nhiều người cùng test, hoặc muốn nghe trên loa điện thoại thật:

1. Portal → **Voice** → **SIP Connections** → tạo một connection kiểu
   **Credentials**.
2. Lấy username + password tự sinh (nên đổi mật khẩu).
3. Cài Zoiper hoặc Linphone trên máy/điện thoại, đăng nhập bằng thông tin đó.
4. Gọi vào số Telnyx của mình. Cuộc gọi đi trong mạng Telnyx (on-net), tính theo
   bảng giá của tài khoản chứ không phải cước quốc tế.

### 2.3 Điện thoại thật — chỉ khi nghiệm thu

Gọi bằng SIM thật từ Việt Nam sang số Mỹ tốn cước quốc tế. Chỉ làm khi cần kiểm
chứng chất lượng âm thanh qua mạng điện thoại thật, không dùng để debug hằng ngày.

---

## 3. Tạo Call Control Application

Đây là thứ nối số điện thoại với server của mình. Chưa có nó thì Telnyx không
biết gửi tin về đâu.

**Làm bước 5 (ngrok) trước** nếu chưa có domain — ô Webhook URL cần địa chỉ thật.

1. Portal → **Voice** → **Call Control** → **Create Application**.
2. Điền:

| Ô | Giá trị | Vì sao |
| --- | --- | --- |
| App Name | `AI Bridge Dev` | Tên nội bộ, đặt gì cũng được |
| Webhook URL | `https://<host>/telnyx/webhook` | Nơi Telnyx báo "có người gọi". Phải `https`, không được `localhost` |
| **Webhook API Version** | **API v2** | **Quan trọng nhất.** v1 gửi định dạng khác, code sẽ không hiểu |
| Webhook Failover URL | để trống | Chưa cần |
| Webhook Timeout | mặc định | |

3. Lưu lại.

> Nếu chọn nhầm **API v1**, webhook vẫn tới nhưng nội dung khác hoàn toàn —
> `data.event_type` không tồn tại, hệ thống sẽ bỏ qua mọi cuộc gọi mà không báo
> lỗi rõ ràng. Nếu thấy log im lặng, kiểm tra ô này đầu tiên.

---

## 4. Gán số vào application

Mua số và tạo app vẫn chưa nối với nhau. Phải gán thủ công.

1. Portal → **Numbers** → **My Numbers**.
2. Bấm vào số vừa mua.
3. Ô **Connection / Application**: chọn `AI Bridge Dev` vừa tạo.
4. Lưu.

Bỏ sót bước này là lỗi phổ biến nhất: gọi vào số thì đổ chuông rồi ngắt, và
**server không nhận được gì cả** — vì Telnyx không biết số đó thuộc app nào.

---

## 5. Lấy khóa kiểm tra chữ ký

Telnyx ký tên lên mọi tin nhắn gửi về. Không có khóa này thì mọi webhook bị từ
chối với lỗi 401.

1. Portal → **Account Settings** → **Keys & Credentials**.
2. Tìm mục **Public Key** (khóa Ed25519, dạng base64).
3. Copy → điền vào `TELNYX_PUBLIC_KEY`.

Cùng trang đó có **API Key** (dạng `KEY...`) → điền vào `TELNYX_API_KEY`. Hai
thứ khác nhau, đừng nhầm:

- **API Key** — để mình gọi Telnyx (nhấc máy, mở stream, cúp máy). Là **bí mật**.
- **Public Key** — để mình kiểm tra Telnyx. Không phải bí mật, nhưng sai là hỏng hết.

---

## 6. Mở đường ra internet bằng ngrok

Telnyx không gọi được vào `localhost`, và bắt buộc TLS hợp lệ. Máy dev cần một
địa chỉ công khai.

```bash
ngrok http 8080
```

Ngrok in ra một dòng kiểu:

```
Forwarding   https://a1b2-c3d4.ngrok-free.app -> http://localhost:8080
```

Lấy domain đó dùng cho hai chỗ, **khác giao thức**:

| Chỗ dùng | Giá trị |
| --- | --- |
| Webhook URL (bước 3) | `https://a1b2-c3d4.ngrok-free.app/telnyx/webhook` |
| `TELNYX_STREAM_URL` | `wss://a1b2-c3d4.ngrok-free.app/telnyx/media` |

> Domain ngrok miễn phí **đổi mỗi lần khởi động lại**. Đổi là phải sửa cả hai
> chỗ trên. Nếu test nhiều ngày, cân nhắc domain cố định của ngrok hoặc deploy
> lên một server thật.

---

## 7. Điền cấu hình

Vào `.env` (xem mẫu đầy đủ ở [.env.example](../.env.example)):

```bash
TELNYX_ENABLED=true
TELNYX_API_KEY=KEY0197...                  # buoc 5
TELNYX_PUBLIC_KEY=x9Kq...                  # buoc 5
TELNYX_STREAM_URL=wss://a1b2-c3d4.ngrok-free.app/telnyx/media   # buoc 6
TELNYX_STREAM_TOKEN=                       # tu sinh, xem duoi
```

Sinh token ngẫu nhiên cho đường audio:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Token này không lấy ở đâu cả — mình tự đặt. Telnyx không ký đường WebSocket audio,
nên đây là cách duy nhất chặn người lạ nối vào.

Giai đoạn production Đức, đổi thêm:

```bash
TELNYX_DEFAULT_LOCALE=de
TELNYX_DEFAULT_TIMEZONE=Europe/Berlin
TELNYX_GREETING=<cau chao tieng Duc>
```

---

## 8. Chạy và kiểm tra

Ba cửa sổ terminal:

```bash
# 1 — server
python app.py

# 2 — duong ra internet
ngrok http 8080

# 3 — kiem tra server song
curl http://localhost:8080/health
```

Khi khởi động, log phải có dòng:

```
Telnyx routes mounted: POST /telnyx/webhook, WS /telnyx/media
```

Không thấy dòng này nghĩa là `TELNYX_ENABLED` chưa bật.

Giờ gọi vào số bằng Web Dialer. Log phải chạy theo đúng thứ tự này:

```
Telnyx call.initiated ccid=... from=... to=...
Telnyx call.answered ccid=...; starting stream
Telnyx stream connected version=1.0.0
Telnyx start stream=... from=... to=... encoding=L16 in_rate=16000 out_rate=16000
session.init callId=... store=... locale=en to=...
Mic PCM first frame ...
```

Và trong tai nghe: AI đọc lời chào kèm menu bấm phím.

---

## 9. Hỏng ở đâu thì tìm ở đâu

| Triệu chứng | Nguyên nhân thường gặp |
| --- | --- |
| Gọi vào đổ chuông rồi ngắt, **log trống trơn** | Chưa gán số vào application (bước 4) |
| Log `Rejecting Telnyx webhook: ...` | `TELNYX_PUBLIC_KEY` sai hoặc để trống |
| Log `... timestamp outside tolerance` | Đồng hồ máy dev lệch. Bật đồng bộ giờ tự động |
| Webhook tới nhưng không có gì xảy ra | Chọn nhầm **API v1**. Sửa ở bước 3 |
| `streaming_start failed` | `TELNYX_STREAM_URL` sai, còn `http`/`ws` thay vì `https`/`wss`, hoặc ngrok đã đổi domain |
| Kết nối audio bị từ chối | `TELNYX_STREAM_TOKEN` trong `.env` khác token trong `TELNYX_STREAM_URL` |
| Nghe thấy **tiếng rè trắng** | Codec không phải L16. Xem log dòng `Telnyx is streaming ...` |
| AI im re, log không có `Mic PCM` | `stream_track` sai, hoặc Telnyx đang gửi track `outbound` |
| AI nói nhưng nói lố khi bị ngắt lời | Kiểm tra log có dòng `Telnyx clear sent (barge-in)` không |
| Cúp máy quá sớm, cụt câu cuối | Xem log `Telnyx never echoed the call-end mark`. Tăng `TELNYX_MARK_TIMEOUT_SECONDS` |

---

## 10. Trước khi lên production

- [ ] Có số Đức, đăng ký theo địa chỉ nhà hàng (hoặc đã port số cũ của quán)
- [ ] Thay ngrok bằng domain thật, chứng chỉ TLS hợp lệ
- [ ] Số đó đã nằm trong dữ liệu nhà hàng để `_load_catalog` tra ra đúng quán
- [ ] `TELNYX_DEFAULT_LOCALE=de`, `TELNYX_DEFAULT_TIMEZONE=Europe/Berlin`, lời chào tiếng Đức
- [ ] Đặt cảnh báo chi phí — phần tốn nhất là OpenAI (STT + LLM + TTS chạy suốt cuộc gọi), không phải Telnyx
- [ ] Gọi thử bằng SIM Đức thật, nghe chất lượng qua mạng điện thoại thật
- [ ] Nếu chỉ chạy Telnyx, đặt `BRIDGE_ENABLED=false` để gỡ `/v1/bridge`
