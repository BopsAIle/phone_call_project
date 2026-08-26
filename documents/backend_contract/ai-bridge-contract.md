# AI Bridge — Hợp đồng tích hợp

**Trạng thái:** nháp — team AI đã đề xuất câu trả lời [CONFIRM] ngày 2026-08-25
**Chủ sở hữu:** team backend (repo này) · team AI
**Cập nhật lần cuối:** 2026-08-25

Tài liệu này định nghĩa giao thức wire giữa backend điện thoại AI Receptionist
và dịch vụ giọng nói của team AI. Hai bên implement theo tài liệu này. Nếu
code và tài liệu lệch nhau, **sửa tài liệu này** — team AI làm theo hợp đồng
và không xem được repo này.

Câu trả lời [CONFIRM] của team AI ghi xen trong bài dưới dạng **Team AI:**
và ở [§10](#10-câu-hỏi-mở). Backend vẫn cần ack các mục sở hữu chung
(transcript, đặt bàn). Process phía AI nằm ở
[ai-pipeline.md](../ai-pipeline.md).

---

## 1. Phạm vi — ai sở hữu gì

```mermaid
flowchart LR
    Caller["Người gọi PSTN"] <--> Twilio
    Twilio <-->|"8 kHz mu-law, 20 ms"| Backend["Backend điện thoại"]
    Backend <-->|"16 kHz PCM16 WebSocket"| AI["Dịch vụ AI"]
```

### Team AI sở hữu

- Speech-to-text, gồm cả **voice activity detection**
- Language model / suy luận
- Text-to-speech
- **Chia lượt nói** — quyết khi người gọi nói xong và khi nào trả lời
- **Câu chào** — nói lúc đầu cuộc gọi
- Trạng thái hội thoại và lịch sử

### Backend sở hữu

- Điện thoại Twilio: voice webhook, TwiML, và socket Media Streams
- Đổi codec: mu-law ↔ PCM, resample 8 kHz ↔ 16 kHz
- Cắt frame: đúng frame 20 ms Twilio yêu cầu
- **Buffer phát của Twilio** — kể cả flush khi barge-in
- Bản ghi cuộc gọi trong database

### Team AI không đụng

- Bất cứ thứ gì hình dạng Twilio. Bạn không thấy mu-law, `streamSid`, hay
  frame 20 ms.
- Nhịp phát lại. Gửi audio khi sinh ra; backend pace giúp.

### Backend không đụng

- VAD thứ hai. Xem [§7](#7-vì-sao-sự-kiện-interrupt-thuộc-về-bạn).

---

## 2. Vận chuyển

| | |
|---|---|
| Protocol | WebSocket (`wss://`) |
| Ai gọi | **Backend gọi ra** tới dịch vụ AI |
| Socket | **Một socket / một cuộc gọi**, mở khi cuộc gọi kết nối, đóng khi kết thúc |
| Auth | Token Bearer trong header `Authorization` lúc handshake. **Team AI: đồng ý.** |
| URL | Team AI cung cấp; backend lưu `AI_BRIDGE_URL`. Placeholder trước khi deploy: `wss://<host>/v1/bridge`. **Team AI: đồng ý.** |

### Loại frame

Kết nối mang hai loại frame WebSocket; loại frame phân biệt chúng. Không
envelope, không length prefix, không base64. **Team AI: đồng ý.**

| Loại frame WebSocket | Mang |
|---|---|
| **Binary** | Byte audio thô — PCM16 mono 16 kHz, little-endian |
| **Text** | Message điều khiển JSON (xem [§4](#4-tham-chiếu-message)) |

Cố ý như vậy. Base64-trong-JSON tốn thêm ~33% băng thông và một bước decode
trên đường ~32 KB/s mỗi cuộc gọi mỗi chiều. Mọi thư viện WebSocket đều lộ
loại frame trực tiếp, nên tách audio khỏi control là kiểm tra field, không
phải parse.

### Reconnect

- Backend reconnect với backoff khi đóng bất ngờ: **200 ms, 500 ms, 1000 ms**,
  rồi bỏ cuộc và để cuộc gọi chạy không agent.
- Audio người gọi tới lúc socket chết được buffer, cap **~2 giây**, cũ nhất
  drop trước. Xem [§9](#9-các-trường-hợp-lỗi).
- Reconnect bắt đầu **session mới**. Gửi lại `session.init`. **Team AI: v1
  không resume.** State hội thoại bị bỏ. `callId` chỉ để khớp log. Socket
  đứt thì cuộc hội thoại đó kết thúc đối với agent.

---

## 3. Vòng đời session

```
Backend                                   Dịch vụ AI
   │                                          │
   ├── WebSocket connect ────────────────────►│
   │                                          │
   ├── {"event":"session.init", ...} ────────►│   frame text
   │                                          │
   │◄──────────── audio (câu chào) ───────────┤   frame binary
   │                                          │
   ├── audio (người gọi) ────────────────────►│   frame binary
   │◄──────────── audio (trả lời) ────────────┤   frame binary
   │                                          │
   │◄──────────── {"event":"interrupt"} ──────┤   frame text, khi barge-in
   │                                          │
   ├── WebSocket close ──────────────────────►│   người gọi cúp máy
```

1. **Mở.** Backend kết nối khi Twilio báo cuộc gọi đã bắt đầu.
2. **Init.** Backend gửi ngay `session.init` kèm context cửa hàng. Audio
   có thể chảy hai chiều ngay sau đó — backend không chờ acknowledgement.
3. **Chào.** Dịch vụ AI nói trước, dùng đúng text greeting được gửi.
4. **Hội thoại.** Audio hai chiều đến khi cuộc gọi kết thúc.
5. **Đóng.** Backend đóng socket khi người gọi cúp hoặc Twilio kết thúc
   stream. Dịch vụ AI coi close là cuối cùng và giải phóng session.

**Nếu dịch vụ AI đóng trước**, backend coi là lỗi, thử reconnect theo
[§2](#2-vận-chuyển), người gọi nghe im lặng đến khi phục hồi. Chỉ đóng khi
thật sự lỗi.

**Nếu `session.init` không bao giờ được xử lý**, dịch vụ AI vẫn nên nhận
audio thay vì báo lỗi — nhưng thiếu greeting và context cửa hàng, tức cuộc
gọi hỏng. Log thật to cả hai phía.

---

## 4. Tham chiếu message

### Backend → AI

#### `session.init` (frame text)

Gửi một lần, ngay sau khi socket mở.

```json
{
  "event": "session.init",
  "callId": "clx8k2p9v0000abcd1234efgh",
  "storeName": "Bella Vista",
  "timezone": "Europe/Berlin",
  "locale": "en",
  "greeting": "Thanks for calling Bella Vista. This is an automated assistant — how can I help you today?"
}
```

| Field | Kiểu | Ghi chú |
|---|---|---|
| `callId` | string | Id cuộc gọi nội bộ của chúng tôi. Dùng khớp log; đây là khóa đối chiếu được. |
| `storeName` | string | Tên nhà hàng, đưa vào prompt. |
| `timezone` | string | Vùng IANA, ví dụ `Europe/Berlin`. Cần để “tối nay” và “ngày mai” tính theo đồng hồ cửa hàng, không theo server. |
| `locale` | `"en"` \| `"de"` | Ngôn ngữ cuộc gọi này. |
| `greeting` | string | Đúng text nói đầu tiên. Cấu hình theo cửa hàng; không diễn lại — câu này mang disclosure trợ lý tự động bắt buộc pháp lý. |

#### Audio (frame binary)

Audio người gọi. PCM16 mono 16 kHz, little-endian. ~100 ms mỗi frame
(3.200 byte). Xem [§5](#5-định-dạng-audio).

### AI → Backend

#### Audio (frame binary)

Audio agent. Cùng định dạng. Kích thước tùy ý — backend cắt lại. Gửi khi
sinh ra; không pace, không pad.

#### `interrupt` (frame text)

```json
{ "event": "interrupt" }
```

Gửi khi VAD của bạn phát hiện người gọi nói trong lúc đang phát câu trả
lời. Yêu cầu ở [§6](#6-team-ai-phải-đảm-bảo).

**Team AI: v1 không cần control message khác.** Wire chỉ audio cộng
`interrupt`. Không thêm `response.start` / `response.end` hay `transcript`
ở v1. Đặt bàn và chuyển lễ tân ở ngoài socket này đến khi đổi hợp đồng
sau (xem [§10](#10-câu-hỏi-mở)).

---

## 5. Định dạng audio

**Cả hai chiều: 16 kHz, PCM16 (signed 16-bit), mono, little-endian.**

Không header, không container — sample thô. Một frame binary là số nguyên
sample; không bao giờ cắt một sample xuyên hai frame.

| | Giá trị |
|---|---|
| Sample rate | 16.000 Hz |
| Encoding | PCM16 signed, little-endian |
| Channels | 1 (mono) |
| Byte mỗi giây | 32.000 |
| Kích thước frame Backend → AI | ~100 ms = 1.600 sample = **3.200 byte**. **Team AI: chấp nhận.** |
| Kích thước frame AI → Backend | Tùy ý. Backend cắt lại thành 20 ms của Twilio. |

### Về kích thước batch 100 ms

Backend gộp audio người gọi thành frame ~100 ms thay vì gửi từng frame
20 ms của Twilio — 50 message WebSocket nhỏ mỗi giây mỗi cuộc gọi là
overhead thừa.

**Nhưng chỗ này nằm ngay trước VAD của bạn, do đó trước độ nhạy barge-in.**
Nếu 100 ms quá thô, nói để chúng tôi hạ; phía chúng tôi chỉ tốn thêm
message. **Team AI: 100 ms chấp nhận được.** VAD chạy phía AI (OpenAI
`server_vad`); 100 ms thêm tối đa ~100 ms vào barge-in. Đừng hạ trừ khi
cuộc gọi thật cho thấy đó là nút thắt.

### Ghi chú về chất lượng audio

Người gọi tới qua PSTN dạng G.711 mu-law 8 kHz. **Không có nội dung audio
trên 4 kHz** — mạng điện thoại không mang nó. Backend upsample lên 16 kHz
bằng bộ lọc chống alias vì bạn xin input 16 kHz, nhưng không thêm thông
tin. Đừng kỳ vọng giọng wideband, và đừng tune model trên audio studio
16 kHz rồi cho rằng kết quả chuyển được.

Ngược lại cũng vậy: thứ bạn gửi bị downsample xuống 8 kHz và encode mu-law
trước khi tới người gọi. Synth trên 8 kHz là công vô ích ở đầu này.

---

## 6. Team AI phải đảm bảo

Đây là yêu cầu, không phải gợi ý. Mỗi mục có failure mode cụ thể.

### 6.1 Gửi `interrupt` khi người gọi nói đè agent

Ngay lúc VAD phát hiện tiếng người gọi **trong khi đang phát câu trả lời**,
gửi `{"event":"interrupt"}`.

*Vì sao:* backend không phát hiện được. Xem
[§7](#7-vì-sao-sự-kiện-interrupt-thuộc-về-bạn).

*Nếu không:* agent nói đè người gọi hết phần còn lại của câu — có thể vài
giây. Người gọi cảm giác agent bỏ qua họ.

### 6.2 Abort câu đang chạy và không gửi thêm audio của câu đó

Khi interrupt, dừng generate và dừng gửi audio của câu bị bỏ.

*Nếu không:* backend flush buffer Twilio khi nhận `interrupt` của bạn, rồi
lập tức đổ đầy lại bằng audio cũ bạn vẫn đang stream. Kết quả tệ hơn không
có barge-in — câu trả lời giật rồi chạy tiếp.

### 6.3 Gửi `interrupt` *sau* frame audio cuối của câu bị abort

Thứ tự quan trọng, và đó là chi tiết khiến implement đơn giản vẫn đúng.

WebSocket đảm bảo thứ tự message trên một kết nối. Nếu `interrupt` là thứ
**cuối** gửi cho lượt bỏ, thì mọi thứ tới sau thuộc lượt mới, không mơ hồ.
Backend không cần turn ID, số sequence, hay cửa sổ discard.

*Nếu gửi sớm* — trước các frame đã xếp trong writer — các frame đó tới sau
khi backend đã flush, và bị phát như đầu câu “mới”. Cuộc gọi nghe hỏng
tinh vi, rất khó lần từ log của hai phía.

### 6.4 Nói câu chào khi `session.init`

Dùng đúng `greeting` và `locale` được gửi. Nói nguyên văn.

*Nếu không:* cuộc gọi mở bằng im lặng, người gọi thường cúp trong vài giây.
Text greeting còn mang disclosure trợ lý tự động bắt buộc, nên diễn lại là
vấn đề tuân thủ, không phải lựa chọn văn phong.

### 6.5 Gửi audio đủ liên tục để không đói playback

Một khi câu trả lời bắt đầu, giữ backend có audio. Khoảng trống dài hơn
lead time audio của bạn thành dropout giữa từ, nghe được.

Bạn **không** cần pace realtime — gửi nhanh hơn realtime nếu được. Backend
buffer và Twilio phát đúng tốc độ.

---

## 7. Vì sao sự kiện `interrupt` thuộc về bạn

Đây là yêu cầu trông như thể để được ở một trong hai phía. Không thể, và
lý do đáng ghi lại để khỏi đem ra tranh lại.

**Bạn đã tính sẵn tín hiệu này.** “STT” gồm hai phần: VAD quyết “các byte
này là tiếng người, không phải nhiễu”, và transcriber. VAD của bạn cho biết
lượt người gọi đã *hết* — nhờ đó bạn biết lúc nào chạy model. Cùng VAD đó
bắn *trong lúc đang phát câu trả lời* **chính là** barge-in. Cùng một tín
hiệu, đã nằm trong process của bạn. Gửi đi chỉ là một `send()`, không phải
một tính năng.

**Backend không tính được.** VAD đã rời repo này cùng module STT. Backend
chỉ còn byte audio thô. Ho, cửa đóng, tivi, và “khoan, thực ra—” đều không
phân biệt được nếu không có VAD.

**Backend không được dựng lại một cái.** Hai VAD nghĩa là hai nguồn sự thật
về “người gọi có đang nói”, và chúng *sẽ* lệch — backend flush vì một tiếng
ho trong lúc bạn còn generate, hoặc bạn abort trong lúc backend còn phát.
Lớp bug đó chỉ tái hiện trên cuộc gọi thật và rất khổ để chẩn từ log hai
phía.

**Và chỉ backend mới tác động được.** Audio đã đưa cho Twilio nằm trong
buffer Twilio và phát bất kể hai bên làm gì tiếp theo. Thứ duy nhất làm
rỗng nó là message `clear` trên socket Twilio, mà chỉ backend nắm.

Vậy: **kiến thức ở phía bạn, cơ cấu chấp hành ở phía chúng tôi.** Một
message nối khoảng trống đó.

### Timeline cụ thể

```
t=0.0s   Bạn gửi 6 s audio trả lời. Backend chuyển hết sang Twilio.
t=0.2s   Twilio đã xếp 6 s và bắt đầu phát. Hai socket lúc này idle.
t=2.0s   Người gọi bắt đầu nói. VAD của bạn bắn.
         Bạn dừng generate — nhưng 4 s audio đã nằm trong buffer Twilio.
         ── không có {"event":"interrupt"} ──
t=6.0s   Người gọi đã nghe agent nói đè họ suốt 4 giây.
```

---

## 8. Ngân sách latency — số chúng tôi đã đo

Giao lại để khỏi phải phát hiện lần nữa. Đây là số từ implement mà tích hợp
này thay thế, đo trên cuộc gọi thật tháng 8/2026.

| Giai đoạn | Đã đo |
|---|---|
| Cửa sổ im lặng server-VAD trước hết lượt | 800 ms |
| `speech_stopped` → nhận transcript cuối | 300–600 ms |
| LLM: request → **câu hoàn chỉnh** đầu tiên | 400–900 ms |
| TTS: request → byte audio đầu | 300–600 ms |
| **Tổng, từ cuối người gọi → audio agent đầu** | **~1,9–3,0 s** |

### Điều chúng tôi học được

- **Cửa sổ im lặng VAD chiếm phần lớn.** Đó là hạng lớn nhất. Chọn 800 ms
  vì 500 ms cắt *"Hello, my name is Anna. Can I book a table for two
  people?"* thành ba lượt riêng ở chỗ ngắt hơi dấu phẩy. Tune cái này là
  núm có leverage cao nhất, và đánh đổi trực tiếp với việc cắt người đang
  dừng để nghĩ.

- **Cắt TTS ở ranh giới câu, không đợi hết completion.** Chờ hết completion
  tốn ~2,5 s tới audio đầu; flush câu đầu ngay khi đủ tốn ~0,8 s, vì TTS
  synth câu một trong lúc model còn viết câu hai. Đây là win lớn nhất có
  được, khoảng ~1,7 s.

- **Metric là thời gian tới audio đầu, không phải tổng thời gian hoàn tất.**
  Câu trả lời bắt đầu sau 800 ms rồi mất 6 s để xong nghe nhanh hơn rõ rệt
  so với câu bắt đầu sau 2,5 s rồi xong sau 4 s.

- **Cẩn thận thời gian tới *câu* đầu vs thời gian tới token đầu.** Không
  cùng một số, khoảng cách khoảng 15–25 token generate.

- **Audio điện thoại decode theo cụm thô hơn audio studio.** Đừng tune
  timeout trên file test chất lượng cao đẩy nhanh; cuộc gọi thật pace
  20 ms và hành xử khác.

---

## 9. Các trường hợp lỗi

| Tình huống | Việc backend làm | Việc cần từ bạn |
|---|---|---|
| Socket AI đứt | Reconnect backoff 200/500/1000 ms rồi bỏ. Audio người gọi buffer, cap ~2 s, cũ nhất drop trước. | Nhận `session.init` mới khi reconnect. **Team AI: không resume** — history rỗng, chào lại. |
| Dịch vụ AI đọc chậm | Backend cap queue outbound và drop audio **cũ nhất** trước. | Không cần gì — nhưng hãy kỳ vọng audio người gọi bạn nhận bị hổng nếu bạn stall. |
| Không có audio nào từ AI | Cuộc gọi vẫn mở; người gọi nghe im lặng. Log lỗi. | Gửi *cái gì đó* — kể cả câu lỗi nói thành tiếng còn hơn im lặng. |
| Control message sai dạng | Log rồi bỏ qua; socket **không** bị cắt. | Không cần gì. |
| Người gọi cúp máy | Đóng socket ngay. | Giải phóng session; không reconnect. |

Hành vi queue có bound quan trọng: **audio bạn nhận có thể bị hổng nếu bạn
stall**, vì audio cũ transcribe muộn còn tệ hơn thiếu một từ — nó tới sau
khi hội thoại đã đi tiếp.

---

## 10. Câu hỏi mở

Câu trả lời team AI dưới đây **đề xuất ngày 2026-08-25**. Backend vẫn cần
ack các mục sở hữu chung. Spec process AI:
[Pipeline giọng nói AI](../ai-pipeline.md).

| # | Câu hỏi | Chủ sở hữu | Trạng thái | Team AI trả lời |
|---|---|---|---|---|
| 1 | Xác nhận frame binary cho audio / frame text cho JSON (§2) | Team AI | **Đề xuất** | **Đồng ý.** Binary = PCM16 16 kHz thô. Text = JSON điều khiển. Không envelope, không base64 trên socket này. |
| 2 | Xác nhận URL WebSocket và schema auth (§2) | Team AI | **Đề xuất** | **Bearer** trong `Authorization` lúc handshake. URL do team AI cấp, backend lưu `AI_BRIDGE_URL`. Placeholder: `wss://<host>/v1/bridge` đến khi host được deploy. |
| 3 | State hội thoại có resume được sau socket đứt, khóa theo `callId` không? (§2) | Team AI | **Đề xuất** | **v1 không resume.** Reconnect + `session.init` mới = history rỗng và chào lại. `callId` chỉ khớp log. State sống trong RAM và chết cùng socket hoặc process. |
| 4 | Batch input ~100 ms có chấp nhận được, khi nó nằm trước VAD của bạn? (§5) | Team AI | **Đề xuất** | **Có.** VAD là OpenAI `server_vad` phía AI. 100 ms thêm tối đa ~100 ms vào barge-in. Giữ frame 3.200 byte. |
| 5 | Có cần control message thêm không? (§4) | Cả hai | **Đề xuất (v1)** | **v1: chỉ `interrupt`.** Không `response.start` / `response.end`. Không `transcript` trên wire. Event `transfer` sẽ là đổi hợp đồng sau nếu cần chuyển lễ tân. |
| 6 | **Transcript.** Hợp đồng hiện audio-only nên backend không persist text hội thoại. Bảng `Utterance` đã đúng nhưng sẽ trống. Nếu cần transcript để review, analytics, hay tách đặt bàn, nói ngay — thêm control message `transcript` rẻ lúc này và khó về sau. | Cả hai | **Đề xuất (v1)** | AI giữ transcript **trong RAM** chỉ cho LLM. **Không** thêm control message `transcript` ở v1. Xem lại nếu review/analytics cần text phía backend. |
| 7 | **Đặt bàn.** Hệ thống đang hướng tới tool-calling để lấy chi tiết reservation. Ai sở hữu phần đó, và booking vào database của chúng tôi thế nào? Hợp đồng này chưa phủ. | Cả hai | **Hoãn** | **Ngoài đường audio v1.** Context LLM là `session.init` (`storeName`, `timezone`, `locale`, `greeting`) cộng history trong RAM. Tool đặt bàn (`check_availability`, `create_booking`, …) là hook sau trong process AI và không đổi giao thức wire này. |

---

## Liên quan

- [Pipeline giọng nói AI](../ai-pipeline.md) — STT → LLM → TTS nối tầng phía
  AI, resample, thứ tự barge-in, và phạm vi v1.
- [Phase 1 — Đường audio](../features/phase-1-audio-path.md) — codec mu-law,
  resampler, và gateway Twilio Media Streams vẫn ở phía backend.
- [Phase 3 — Agent nói](../features/phase-3-llm-tts-loop.md) — pipeline mà
  tích hợp này thay thế, gồm cắt câu và barge-in mô tả ở §8.
