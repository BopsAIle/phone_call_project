# 20 — Thuật ngữ

Tra nhanh những từ xuất hiện khắp repo.

## Thoại & âm thanh

**STT** (Speech to Text) — chuyển tiếng nói thành văn bản. Ở đây: OpenAI Realtime
transcription. → [ch.07](07-nghe-stt.md)

**TTS** (Text to Speech) — chuyển văn bản thành tiếng nói. Ở đây: OpenAI `tts-1`, giọng
`nova`. → [ch.09](09-noi-tts.md)

**VAD** (Voice Activity Detection) — máy dò xem có ai đang nói không. Quyết định lúc nào
một lượt nói kết thúc. Dự án dùng `server_vad` của OpenAI.

**Barge-in** — khách nói đè lên lúc AI đang nói. AI phải im ngay.
→ [ch.10](10-barge-in.md)

**DTMF** — tiếng "tút tút" khi bấm phím điện thoại. Ở đây: 1 = đặt bàn, 2 = lấy tại quán,
3 = giao hàng.

**PCM** — âm thanh số thô, không nén. **PCM16** = mỗi mẫu 16 bit.
**PCM16-LE** = little-endian (byte thấp trước). Dự án dùng PCM16-LE mono 24 kHz trên dây.

**L16** — tên gọi PCM16 trong thế giới VoIP. RFC 2586 nói nó là **big-endian**, nhưng
Telnyx thực tế gửi little-endian. → [ch.13](13-telnyx.md)

**Sample rate** — số mẫu mỗi giây. 24.000 Hz trên dây bridge, 16.000 Hz với Telnyx.

**Resample** — đổi sample rate. Dự án dùng `soxr` chất lượng HQ, giữ trạng thái giữa các
chunk để không kêu lách cách.

**Endianness** — thứ tự byte trong một số nhiều byte. Sai là **tiếng rè trắng, không báo
lỗi**.

**Frame** — một khối âm thanh nhỏ. 100 ms (4.800 byte) trên dây bridge; 20 ms ra Telnyx.

## AI & LLM

**LLM** (Large Language Model) — ở đây là `gpt-4o-mini` qua Chat Completions.

**System prompt** — chỉ dẫn đặt trước hội thoại, định nghĩa AI là ai và phải làm gì. Dự án
**dựng lại** nó mỗi khi trạng thái đổi. → [ch.08](08-nghi-llm.md)

**Tool / function calling** — cách LLM gọi hàm thật thay vì chỉ nói. Dự án có 11 tool.
→ [ch.11](11-tool-dat-ban.md), [ch.12](12-tool-dat-mon.md)

**Tool round** — một vòng: model gọi tool → code chạy → kết quả về → model nói tiếp. Tối
đa 12 vòng mỗi lượt.

**Streaming** — nhận câu trả lời từng mảnh thay vì đợi trọn gói. Cho phép phát tiếng sớm.

**TTFT / TTFB** — Time To First Token / First Byte. Hai mốc đo độ trễ.

**Token** — đơn vị văn bản mà model tính tiền. `cached_tokens` = số token trúng bộ nhớ
đệm của OpenAI (rẻ hơn và nhanh hơn).

**Temperature** — độ ngẫu nhiên của model. Ở đây 0.7.

## Kiến trúc dự án

**AI Bridge** — dịch vụ Python xử lý cuộc gọi (thư mục `AI/`, cổng 8071).

**BE** — API NestJS (cổng 8070). **FE** — dashboard React (cổng 3070).

**Bridge protocol** — quy ước một WebSocket mang cả PCM nhị phân lẫn sự kiện JSON.
→ `AI/bridge/protocol.py`

**`CallPipeline`** — class điều phối một cuộc gọi. **`CallSession`** — dữ liệu trạng thái
của cuộc gọi đó. **`TurnPlayer`** — bộ phát tiếng cho một lượt nói.

**`generation_id`** — số đếm lượt nói. Tăng nó lên là mọi thứ đang bay của lượt cũ tự vô
hiệu. Nền tảng của barge-in.

**`OutboundGate`** — cửa duy nhất ra socket, có lock, nên `interrupt` luôn đi đúng sau
frame âm thanh cuối cùng.

**Catalog** — dữ liệu nhà hàng: nhà hàng, chi nhánh, thực đơn.

**Generation (Redis)** — một snapshot catalog trọn vẹn. Đổi pointer một phát để cuộc gọi
không bao giờ đọc phải nửa cũ nửa mới. → [ch.14](14-cache-va-sync.md)

**Hotline** — số điện thoại nhà hàng. Là khóa để tra ra nhà hàng nào từ `toNumber`.

**Fulfillment** — hình thức nhận hàng: `pickup` (lấy tại quán) hoặc `delivery` (giao).

**Intent** — khách muốn gì: `booking` (đặt bàn) hoặc `order` (đặt món).

## Điện thoại

**Telnyx** — nhà mạng VoIP dự án đang dùng.

**Call Control** — API của Telnyx để điều khiển cuộc gọi (nhấc máy, mở stream, cúp máy).

**Media Streaming** — WebSocket hai chiều của Telnyx chở âm thanh.

**Webhook** — HTTP POST nhà mạng gửi để báo sự kiện (`call.initiated`, `call.answered`,
`call.hangup`).

**Ed25519** — thuật toán chữ ký Telnyx dùng để ký webhook.

**`call_control_id`** — định danh một cuộc gọi phía Telnyx.

**`mark`** — cơ chế của Telnyx để biết đã phát tới điểm nào trong âm thanh. Dùng để cúp
máy êm.

**ngrok / Cloudflare tunnel** — tạo địa chỉ công khai trỏ về máy local, để nhà mạng gọi
vào được.

**SIP / softphone** — giao thức và phần mềm gọi điện qua Internet. Zoiper là softphone
dùng để test.

## Kỹ thuật chung

**WebSocket** — kết nối hai chiều giữ mở, khác HTTP request-response.

**`asyncio`** — thư viện bất đồng bộ của Python. Toàn bộ AI Bridge chạy trên nó.

**Task** — một coroutine đang chạy nền. Dự án tạo và hủy nhiều task (STT, catalog, hangup,
TTS từng câu).

**`ContextVar`** — biến gắn theo ngữ cảnh thực thi, **được sao sang task con** lúc
`create_task`. Là cách `TurnTimer` tới được các task TTS mà không phải sửa chữ ký hàm.

**Idempotent** — chạy nhiều lần cho cùng kết quả. `POST /calls/ai/start` và việc gửi kèm
`call_id` khi tạo đơn đều dựa vào tính chất này để chống trùng khi mạng chập chờn.

**DTO** (Data Transfer Object) — class mô tả và kiểm tra dữ liệu vào ở NestJS.

**TypeORM** — ORM của BE, ánh xạ class TypeScript thành bảng Postgres.

**`synchronize: true`** — TypeORM tự sửa schema theo entity mỗi lần khởi động. Tiện cho
dev, **nguy hiểm cho production**.

**TanStack Query (react-query)** — thư viện quản lý dữ liệu server ở FE: cache, loading,
tự làm mới sau khi ghi.

**WER** (Word Error Rate) — tỉ lệ từ sai, dùng chấm chất lượng STT.

## Hết

Quay lại [mục lục](README.md).
