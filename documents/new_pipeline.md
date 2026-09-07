# Pipeline v2 — Cascade + Function Calling + Cache đồng bộ nền (Redis)

Tài liệu thiết kế **chi tiết** cho AI Bridge sau nâng cấp. Mục tiêu: đọc xong là code được, không phải
đoán. Mỗi quyết định đều kèm lý do và kèm hệ quả nếu làm sai.

Tài liệu này bổ sung, không thay thế:

- [documents/ai-pipeline.md](documents/ai-pipeline.md) — spec audio và state machine hiện hành
- [documents/backend_contract/ai-bridge-contract.md](documents/backend_contract/ai-bridge-contract.md) — wire protocol WebSocket
- [documents/order-api-contract.md](documents/order-api-contract.md) — API menu và đơn hàng

> **Frontend giữ nguyên kiến trúc.** Không Twilio, không mu-law, không frame 20 ms, không route
> `/ws/voice`. Client vẫn là [`frontend/`](frontend/) (trình duyệt thu micro) hoặc bất kỳ backend nào
> nói đúng hợp đồng hiện tại.
>
> Ngoại lệ duy nhất của v2: frontend **thêm một keypad ba nút** để khách chọn dịch vụ bằng phím
> (§7.1). Đây là phần cộng thêm, không phá gì đang có — client không có keypad vẫn chạy đúng như v1.

---

## Mục lục

- [0. Từ vựng](#0-từ-vựng)
- [1. Bối cảnh: v1 đang làm gì và đau ở đâu](#1-bối-cảnh-v1-đang-làm-gì-và-đau-ở-đâu)
- [2. Kiến trúc cốt lõi](#2-kiến-trúc-cốt-lõi)
- [3. Hợp đồng với frontend (không đổi)](#3-hợp-đồng-với-frontend-không-đổi)
- [4. Đường audio, chi tiết từng tầng](#4-đường-audio-chi-tiết-từng-tầng)
- [5. Đồng bộ hóa cache bằng background polling](#5-đồng-bộ-hóa-cache-bằng-background-polling)
- [6. Luồng một cuộc gọi, theo timeline](#6-luồng-một-cuộc-gọi-theo-timeline)
- [7. Chọn dịch vụ bằng phím, function calling và slot](#7-chọn-dịch-vụ-bằng-phím-function-calling-và-slot)
- [8. Đóng luồng sau câu chốt](#8-đóng-luồng-sau-câu-chốt)
- [9. Snapshot isolation](#9-snapshot-isolation)
- [10. Xử lý lỗi](#10-xử-lý-lỗi)
- [11. VAD và barge-in](#11-vad-và-barge-in)
- [12. Cấu hình](#12-cấu-hình)
- [13. Kế hoạch code](#13-kế-hoạch-code)
- [14. Test](#14-test)
- [15. Vận hành và gỡ lỗi](#15-vận-hành-và-gỡ-lỗi)

---

## 0. Từ vựng

Đọc phần này trước, vì các mục sau dùng lại liên tục.


| Thuật ngữ                   | Nghĩa trong repo này                                                                                                                             |
| --------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Cascade**                 | STT, LLM, TTS là ba dịch vụ rời, nối tiếp nhau. Ngược với *speech-to-speech* (một model nghe và nói trực tiếp).                                  |
| **Slot**                    | Một trường thông tin cần thu từ khách (tên, SĐT, chi nhánh…). "Slot filling" là quá trình hỏi cho đủ.                                            |
| **Tool / Function Calling** | LLM không trả lời bằng chữ mà yêu cầu chạy một hàm Python. Kết quả hàm được nhồi lại vào hội thoại để LLM đọc.                                   |
| **Turn (lượt)**             | Một vòng: khách nói → AI trả lời xong. Đánh dấu bằng `generation_id`.                                                                            |
| `**generation_id**`         | Số nguyên tăng dần trong `CallSession`. Mọi task LLM/TTS mang theo số này; số đổi nghĩa là task đó *stale* và phải chết. Đây là cơ chế hủy lượt. |
| **Barge-in**                | Khách nói chen khi AI đang nói. AI phải im ngay và bỏ luôn câu đang dở.                                                                          |
| **VAD**                     | Voice Activity Detection. Ở đây do OpenAI Realtime làm phía server (`server_vad`), phát sự kiện `speech_started` / `speech_stopped`.             |
| **Snapshot**                | Bản copy dữ liệu danh mục lấy một lần lúc bắt đầu cuộc gọi, đóng băng suốt cuộc gọi.                                                             |
| **Generation (cache)**      | Một phiên bản trọn vẹn của cache trong Redis, đánh số `g1`, `g2`… Con trỏ `pointer` chỉ vào generation đang hoạt động.                           |
| **Write-through**           | Đọc miss cache → gọi HTTP → ghi kết quả vào cache luôn để lần sau hit.                                                                           |
| **Degrade mode**            | Chế độ chạy thiếu tính năng nhưng không chết: Redis hỏng, hoặc backend chưa có endpoint sync.                                                    |
| **DTMF**                    | Tín hiệu khách ấn phím trên điện thoại. Ở repo này AI Bridge **không** giải mã tone — client gửi thẳng event JSON `{"event":"dtmf","digit":"1"}`. |
| **IVR menu**                | Câu chào đọc các lựa chọn kèm số phím ("đặt bàn ấn 1…"). Ở v2 nó thay câu hỏi "đặt bàn hay mang về" của v1.                                      |


---

## 1. Bối cảnh: v1 đang làm gì và đau ở đâu

### 1.1 v1 hoạt động thế nào

Mỗi cuộc gọi, sau khi nhận `session.init`, `CallPipeline` spawn một task đi lấy danh mục:

```570:576:bridge/session.py
    async def _run_reply(self, user_text: str) -> None:
        self.session.begin_generation()
        self.session.state = CallState.THINKING
        task = self._catalog_task
        if task is not None:
            try:
                await task
```

Task đó gọi `GET /restaurants/by-hotline/{digits}` (`booking/client.py`), lọc chi nhánh `status == "active"`,
rồi nhồi tên chi nhánh vào system prompt.

Điểm cần chú ý ở dòng code trên: **lượt trả lời đầu tiên phải `await` task danh mục**. Nghĩa là nếu
backend chậm, khách nói câu đầu x`ong vẫn phải chờ HTTP xong mới nghe AI trả lời.`

### `1.2 Ba vấn đề`

1. **Độ trễ phụ thuộc backend.** Backend đang host trên Render; cold start có thể vài giây. Với cuộc gọi thoại, 2 giây im lặng đã là khó chịu, 5 giây là khách tưởng máy hỏng. Mà danh mục chi nhánh gần như **không đổi** — tra lại mỗi cuộc gọi là trả giá vô ích.
2. **Backend chết là AI mất tính năng.** Không có danh mục thì `restaurant_missing = True`, AI chỉ còn biết xin lỗi, dù dữ liệu đó vừa lấy thành công 30 giây trước.
3. **Context có thể đổi giữa cuộc gọi.** `refresh_system_prompt()` bị gọi khi catalog task xong. Nếu sau này thêm cơ chế cập nhật dữ liệu, prompt của cuộc gọi đang chạy có nguy cơ bị viết lại giữa hội thoại — LLM sẽ nói mâu thuẫn với chính nó.

### 1.3 v2 sửa gì


| Hạng mục              | v1 (hiện tại)                                     | v2 (đích)                                               |
| --------------------- | ------------------------------------------------- | ------------------------------------------------------- |
| Nguồn danh mục        | HTTP đồng bộ, trong luồng cuộc gọi                | Redis warm sẵn; HTTP chỉ là fallback                    |
| Ai đi lấy dữ liệu     | Chính cuộc gọi                                    | Tiến trình nền, chu kỳ 5–10 phút                        |
| Độ trễ trước lượt đầu | RTT backend (0.3 s → vài giây)                    | Đọc Redis, cỡ 1–5 ms                                    |
| Backend chết          | Mất tính năng ngay                                | Vẫn chạy bằng cache cũ                                  |
| Ổn định context       | Prompt refresh nhiều lần                          | Snapshot khóa suốt cuộc gọi                             |
| Kết thúc cuộc gọi     | Client tự cúp                                     | AI chủ động đóng socket sau câu chốt                    |
| Chọn loại dịch vụ    | Hỏi bằng lời "đặt bàn hay mang về", rồi hỏi thêm pickup/delivery | Menu 3 phím: 1 đặt bàn, 2 đến lấy, 3 giao tận nơi. Đường nói vẫn giữ làm fallback |
| Wire protocol         | `session.init`, PCM, `interrupt`, `order.created` | Y nguyên, thêm `dtmf` (client → AI) và `call.end` (tùy chọn, tương thích ngược) |
| Frontend              | Gọi / Cúp / Tắt mic                               | Thêm keypad 3 nút (§7.1.10)                              |


---

## 2. Kiến trúc cốt lõi

### 2.1 Vì sao Cascade chứ không speech-to-speech

Speech-to-speech (Realtime API nói trực tiếp) nghe tự nhiên hơn và độ trễ thấp hơn, nhưng ở nghiệp vụ
này ta cần ba thứ mà cascade cho dễ hơn nhiều:

- **Kiểm soát tuyệt đối câu chào.** Câu chào phải phát **nguyên văn** vì nó chứa disclosure "đây là trợ lý tự động" — yêu cầu pháp lý. Cascade thì câu chào chỉ là một chuỗi đưa vào TTS.
- **Tool calling nghiêm ngặt.** Ta cần cấm AI bịa chi nhánh và bịa món. Với Chat Completions, ta kiểm soát được `tools`, `tool_choice`, và đọc/ghi từng message trong history.
- **Rẻ và thay thế được từng tầng.** Đổi TTS, đổi model LLM, đổi STT — mỗi cái độc lập.

Giá phải trả là độ trễ cộng dồn (§2.3) và phải tự làm barge-in (§11).

### 2.2 Sơ đồ tổng thể

```
                        AI Bridge (FastAPI, 1 process, chạy 24/7)
                        ┌────────────────────────────────────────────────┐
 frontend/ (browser)    │  LUỒNG CUỘC GỌI (mỗi kết nối một instance)     │
 hoặc backend điện thoại│  ┌──────────────────────────────────────────┐  │
        │               │  │ /v1/bridge → CallPipeline                │  │
        │  WS PCM16 16k │  │   PCM 16k ──upsample──→ 24k → STT + VAD  │  │
        └──────────────────→│   transcript cuối → LLM (11 tools)       │  │
        ←──────────────────│   câu → TTS 24k ──downsample──→ PCM 16k  │  │
           PCM + JSON    │  │   CallSession = snapshot + history       │  │
                         │  └──────────┬───────────────────────────────┘  │
                         │             │ đọc MỘT LẦN lúc session.init     │
                         │       ┌─────▼──────┐                           │
                         │       │   Redis    │ danh mục + menu           │
                         │       └─────▲──────┘                           │
                         │             │ ghi (atomic swap, §5.5)          │
                         │  ┌──────────┴───────────────────────────────┐  │
                         │  │ LUỒNG NỀN: CatalogSyncer (asyncio task)  │  │
                         │  └──────────┬───────────────────────────────┘  │
                         └─────────────┼──────────────────────────────────┘
                                       │ GET polling            POST chốt đơn
                                       ▼                        ▼
                              Backend Server REST (phone-call-project)
                                       │
                                       ▼
                                  PostgreSQL
```

Hai luồng **không chia sẻ lock nào**:

- Luồng cuộc gọi: chỉ `GET` Redis, đúng một lần mỗi cuộc gọi.
- Luồng nền: chỉ `SET` Redis, mỗi 5 phút, và chỉ khi dữ liệu thật sự đổi.

Vì thế polling chậm hay backend timeout không bao giờ chen vào đường audio. Đây là mục đích chính của
thiết kế: **tách hoàn toàn đường dữ liệu khỏi đường tiếng nói**.

### 2.3 Ngân sách độ trễ

Con số dưới đây là mục tiêu, đo từ lúc khách ngừng nói tới lúc nghe âm đầu tiên của AI:


| Chặng                   | Thời gian      | Ghi chú                                                                                                          |
| ----------------------- | -------------- | ---------------------------------------------------------------------------------------------------------------- |
| VAD chờ im lặng         | 450 ms         | `silence_duration_ms` trong `stt/realtime.py`. Đây là chặng lớn nhất và **cố ý** — hạ xuống là AI ngắt lời khách |
| STT trả transcript cuối | 100–300 ms     | Sau khi VAD chốt lượt                                                                                            |
| Đọc snapshot (v2)       | 0 ms           | Đã nằm trong RAM của `CallSession` từ lúc init                                                                   |
| LLM token đầu           | 300–700 ms     | `gpt-4o-mini`, stream                                                                                            |
| LLM đủ một câu          | +100–400 ms    | `SentenceAggregator` flush ở `.` `?` `!` `…` newline                                                             |
| TTS byte đầu            | 300–600 ms     | HTTP TTS, `tts-1`                                                                                                |
| Downsample + gửi        | < 5 ms         | soxr, chunk 1024 byte                                                                                            |
| **Tổng**                | **~1.3–2.5 s** |                                                                                                                  |


Nếu có tool call, cộng thêm mỗi vòng tool: một lượt LLM nữa (~400 ms) + thời gian chạy tool. Đây là lý do
phải cắt HTTP khỏi đường nóng: một `GET /restaurants/by-hotline` chậm 3 giây sẽ đội tổng lên gần 5 giây.

`resolve_branch` và `search_menu` gọi thêm một lượt LLM phụ (matcher, `temperature=0`) — cộng 300–600 ms.
Chấp nhận được vì nó đổi lấy việc AI không bịa chi nhánh.

Ngược lại, chọn dịch vụ bằng phím (§7.1) **bỏ hẳn** ba chặng đầu của bảng trên: không chờ VAD, không STT,
không cần LLM suy ý định. Từ lúc ấn phím tới lúc AI nói câu tiếp theo chỉ còn LLM + TTS, khoảng 0.6–1.1 s.

---

## 3. Hợp đồng với frontend (không đổi)

Phần này viết lại cho đủ, để khi code v2 không ai vô tình phá nó.

### 3.1 Handshake và auth

Endpoint: `ws://<host>:8080/v1/bridge` (local) hoặc `wss://<host>/v1/bridge` (deploy).

```27:34:bridge/server.py
def _bearer_authorized(websocket: WebSocket, token: str) -> bool:
    if not token:
        return False
    header = websocket.headers.get("authorization") or ""
    if header.strip() == f"Bearer {token}":
        return True
    query_token = websocket.query_params.get("token") or ""
    return query_token == token
```

Hai đường vào token là **có chủ ý**: backend server gửi được header `Authorization`, nhưng
`new WebSocket()` trong trình duyệt **không** cho gắn header, nên demo browser phải dùng `?token=`.
Token rỗng hoặc sai → close code `1008`.

### 3.2 Frame trên socket


| Hướng       | Loại frame | Nội dung                                                  |
| ----------- | ---------- | --------------------------------------------------------- |
| Client → AI | Text       | JSON `session.init` (một lần, ngay sau khi mở)            |
| Client → AI | Binary     | PCM16 LE mono 16 kHz, ~100 ms = 3200 byte mỗi frame       |
| Client → AI | Text       | `{"event":"dtmf","digit":"1"}` **mới ở v2** — khách ấn phím chọn dịch vụ |
| AI → Client | Binary     | PCM16 LE mono 16 kHz, audio agent                         |
| AI → Client | Text       | `{"event":"interrupt"}` khi barge-in                      |
| AI → Client | Text       | `{"event":"order.created", …}` khi tạo đơn món thành công |
| AI → Client | Text       | `{"event":"call.end", …}` **mới ở v2**, tùy chọn          |


Hằng số: 16 000 Hz × 1 channel × 2 byte = **32 000 byte/giây**. Nhớ số này, §8 dùng để tính thời gian chờ.

### 3.3 `session.init`

```json
{
  "event": "session.init",
  "callId": "call_1a2b3c",
  "storeName": "Bella Vista",
  "toNumber": "1900636886",
  "timezone": "Asia/Ho_Chi_Minh",
  "locale": "vi",
  "greeting": "Xin chào, cảm ơn bạn đã gọi Bella Vista. Đây là trợ lý tự động. Để đặt bàn, bạn ấn phím 1. Để đặt đồ ăn rồi đến lấy, bạn ấn phím 2. Để đặt đồ ăn giao tận nơi, bạn ấn phím 3."
}
```

Ý nghĩa từng field:

- `callId` — chỉ để khớp log. Không dùng để resume; socket đứt là session mới, history rỗng.
- `toNumber` — **hotline khách gọi vào**. Đây là khóa tra danh mục. `normalize_hotline()` bỏ hết ký tự không phải chữ số, nên `+84 1900 636 886` và `1900636886` là một.
- `timezone` — IANA. Dùng để đổi "ngày mai" thành `YYYY-MM-DD`. Sai timezone là đặt bàn sai ngày.
- `locale` — `vi` / `en` / `de`. Truyền xuống STT (`language`), TTS, và prompt.
- `greeting` — phát **nguyên văn**, không paraphrase. Ở v2, `ensure_intent_greeting()` thêm **khối menu ba phím** (§7.1) nếu locale `vi` mà câu chào client gửi chưa có menu. Client gửi sẵn menu thì dùng nguyên văn của client.

### 3.4 Điều khách hàng frontend đã làm sẵn

Đọc `frontend/src/main.ts` để không code trùng:

- `onPcm` → `player.enqueue(bytes)`, hiện "Agent đang nói".
- `onInterrupt` → `player.interrupt()` xóa queue audio ngay.
- `onOrderCreated` → hiện banner đơn hàng.
- `onClose` → `endCall(false)`: dừng mic, gỡ analyser, hiện "Đã cúp".
- Event lạ → bỏ qua im lặng (theo hợp đồng §9). Vì thế thêm `call.end` **không** phá client cũ.

Điểm cuối cùng rất quan trọng cho §8: **client đã tự cúp khi socket đóng**, nên AI chỉ cần đóng socket
là cuộc gọi kết thúc, không cần sửa frontend.

Phần **duy nhất** phải thêm vào frontend ở v2 là keypad ba nút gửi event `dtmf` — chi tiết ở §7.1.

---

## 4. Đường audio, chi tiết từng tầng

Phần này mô tả code đang chạy. v2 không đổi gì ở đây, nhưng phải hiểu để không phá khi thêm cache và
thêm cơ chế cúp máy.

### 4.1 Vào: 16 kHz → 24 kHz

OpenAI Realtime nhận PCM 24 kHz; client gửi 16 kHz. Hai cái bẫy:

**Bẫy 1 — cắt giữa một sample.** PCM16 là 2 byte mỗi sample. Frame đến có thể lẻ byte (nhất là qua
proxy). Cắt sai một byte thì toàn bộ phần sau bị dịch, nghe thành tiếng rít.

```12:20:audio/resample.py
def even_pcm16(data: bytes, leftover: bytearray) -> bytes:
    """Return a whole-sample PCM16 buffer; stash a trailing odd byte if any."""
    if leftover:
        data = bytes(leftover) + data
        leftover.clear()
    if len(data) % 2:
        leftover.append(data[-1])
        data = data[:-1]
    return data
```

Byte lẻ được **giữ lại** để ghép với frame sau, không bị bỏ.

**Bẫy 2 — resample không trạng thái.** Resample từng chunk độc lập tạo tiếng "click" ở mỗi biên chunk,
vì filter không biết đuôi chunk trước. `StreamResampler` bọc `soxr.ResampleStream` (quality `HQ`) để giữ
trạng thái filter xuyên chunk.

### 4.2 Buffer khi STT chưa kết nối xong

STT mở WebSocket tới OpenAI mất vài trăm ms. Trong lúc đó audio khách đã chảy vào. Bỏ đi thì mất đầu câu.

`_send_to_stt()` giải quyết: chưa ready thì tích vào `_pending_24k`, ready thì flush trước rồi append tiếp
— **giữ đúng thứ tự**. Trần buffer:

```24:25:bridge/session.py
# ~2 s of 24 kHz PCM16 if STT is still connecting
_MAX_PENDING_STT_BYTES = BRIDGE_RATE * 2 * 3  # 16k→24k ≈ 3/2, times 2 bytes, ~2 s
```

96 000 byte ≈ 2 giây audio 24 kHz. Quá trần thì **bỏ phần cũ nhất** (và bỏ số byte chẵn, lại là bẫy 1).
Bỏ cũ chứ không bỏ mới, vì cái mới là cái khách vừa nói.

### 4.3 STT và cấu hình VAD

```18:23:stt/realtime.py
VAD = {
    "type": "server_vad",
    "threshold": 0.5,
    "prefix_padding_ms": 300,
    "silence_duration_ms": 450,
}
```

- `threshold: 0.5` — độ nhạy. Thấp hơn thì tiếng ồn quán bị coi là tiếng nói (AI tự ngắt lời mình); cao hơn thì khách nói nhỏ bị bỏ.
- `prefix_padding_ms: 300` — gửi kèm 300 ms **trước** lúc phát hiện tiếng nói, để không mất phụ âm đầu ("bốn" thành "ốn").
- `silence_duration_ms: 450` — im 450 ms là hết lượt.

> **Lệch tài liệu:** README và `documents/ai-pipeline.md` ghi 800 ms, code là 450 ms. Code là nguồn sự
> thật. Khi làm v2, sửa lại tài liệu cũ hoặc sửa code — nhưng phải khớp nhau. 450 ms cho cảm giác nhanh
> nhưng dễ ngắt lời người nói chậm; nếu khách hàng phàn nàn "AI cắt lời", nâng lên 600–800 ms là chỗ tinh chỉnh đầu tiên.

Session gửi lên OpenAI (`_session_payload`): `type: "transcription"`, format `audio/pcm` rate `24000`,
`transcription.model` từ `OPENAI_STT_MODEL`, `language` = 2 ký tự đầu của locale. Model này **không nói** —
chỉ phiên âm.

Có fallback: nếu model từ chối `turn_detection`, `_maybe_fallback_session()` chuyển sang session
`type: "realtime"` với `create_response: false` và `interrupt_response: false`, tức là vẫn có VAD nhưng
model vẫn tuyệt đối không sinh tiếng.

Sự kiện quan tâm: `speech_started` (→ barge-in), `speech_stopped`, `…transcription.delta` (chỉ log),
`…transcription.completed` (→ chạy lượt), `…transcription.failed` (→ coi như transcript rỗng, AI nói câu
"chưa nghe rõ").

### 4.4 LLM và cắt câu

`OpenAiLlm.stream_sentences()`: `temperature=0.7`, `max_tokens=400`, `tool_choice="auto"`, tối đa
`_MAX_TOOL_ROUNDS = 12` vòng tool mỗi lượt.

`SentenceAggregator` flush khi gặp `.` `?` `!` `…` hoặc newline, và **có lookahead một ký tự**: chỉ cắt khi
thấy ký tự không phải khoảng trắng sau dấu câu. Lý do: `"19.000 đồng"` và `"Anh A."` — cắt ngay ở dấu chấm
sẽ tạo câu vụn và TTS đọc rời rạc. **Không bao giờ cắt ở dấu phẩy** — cắt ở phẩy làm giọng đọc bị ngắt cụt,
nghe như robot.

Vì sao cắt câu mà không chờ hết câu trả lời: để TTS bắt đầu synth câu 1 trong lúc LLM còn đang sinh câu 2.
Đây là chỗ tiết kiệm được nhiều nhất trong ngân sách độ trễ.

### 4.5 Ra: TTS 24 kHz → 16 kHz, phát theo thứ tự

`TurnPlayer` synth **song song**, gửi **tuần tự**:

- Mỗi câu được `asyncio.create_task` riêng để synth (song song, nhanh).
- Nhưng `_sender_loop` đọc từ queue theo đúng thứ tự câu, nên audio ra không bị đảo.
- `TTS_CHUNK_BYTES` mặc định 1024 byte ≈ 32 ms audio 16 kHz. Chunk nhỏ thì phản hồi nhanh, chunk lớn thì ít overhead.
- Mọi lần gửi đi qua `OutboundGate.send_audio(generation_id, pcm)`. Nếu `generation_id` đã đổi (barge-in), hàm trả `False` và audio bị bỏ — không có frame nào của lượt cũ lọt ra.

---

## 5. Đồng bộ hóa cache bằng background polling

### 5.1 Nguyên tắc

Ba câu, đọc kỹ:

1. **Luồng cuộc gọi không bao giờ chờ backend** (trừ lúc `POST` chốt đơn, vốn là hành động khách đã đồng ý và có thể nói "chờ em một chút").
2. **Redis là cache, không phải database.** Mất toàn bộ Redis chỉ làm hệ thống chậm lại về mức v1, không mất tính năng.
3. **Không bao giờ để reader thấy trạng thái nửa vời.** Đây là lý do dùng generation + con trỏ (§5.5).

### 5.2 Gắn vào FastAPI lifespan

`create_app()` hiện tại tạo client rồi nhét vào `app.state`. v2 thêm `lifespan` — hook chạy khi Uvicorn
khởi động và khi tắt:

```python
# bridge/server.py
import asyncio
import contextlib
from contextlib import asynccontextmanager

def create_app(settings=None, *, catalog_cache=None, catalog_syncer=None, **deps) -> FastAPI:
    settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        cache = catalog_cache
        syncer = catalog_syncer
        task = None
        if cache is None and settings.redis_url:
            cache = CatalogCache.from_url(
                settings.redis_url,
                namespace=settings.redis_namespace,
                generation_ttl=settings.cache_generation_ttl,
            )
        if cache is not None and syncer is None and settings.sync_enabled:
            syncer = CatalogSyncer(
                cache=cache,
                base_url=settings.sync_api_base or settings.restaurant_api_base,
                timeout=settings.sync_timeout,
                interval=settings.sync_poll_seconds,
                max_backoff=settings.sync_max_backoff_seconds,
            )
        app.state.catalog_cache = cache
        app.state.catalog_syncer = syncer

        if syncer is not None:
            # Warm lần đầu: CHẶN startup, nhưng không được làm chết startup.
            try:
                await asyncio.wait_for(syncer.warm_once(), timeout=settings.sync_timeout)
            except Exception:
                logger.exception("Cache warm-up thất bại; chạy tiếp ở degrade mode")
            task = asyncio.create_task(syncer.run_forever(), name="catalog-sync")
        try:
            yield
        finally:
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            if syncer is not None:
                await syncer.aclose()
            if cache is not None:
                await cache.aclose()

    app = FastAPI(title="AI Bridge", version="2.0.0", lifespan=lifespan)
    ...
```

Bốn ràng buộc, mỗi cái có lý do:


| Ràng buộc                                                 | Vì sao                                                                                                          |
| --------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| `warm_once()` bọc `try/except`                            | Backend chết lúc deploy không được làm server không lên được. AI vẫn phải trả lời điện thoại, dù ở degrade mode |
| `warm_once()` bọc `wait_for`                              | Không để startup treo vô hạn nếu backend nhận TCP nhưng không trả response                                      |
| `catalog_cache` / `catalog_syncer` là tham số inject được | Test không cần Redis thật, không cần mạng (§14)                                                                 |
| `SYNC_ENABLED=false` bỏ hẳn task nền                      | Dev không phải chạy Redis; và là công tắc tắt nhanh khi sự cố                                                   |


### 5.3 `CatalogSyncer` — logic đầy đủ

```python
# sync/poller.py — cấu trúc gợi ý
class CatalogSyncer:
    def __init__(self, *, cache, base_url, timeout, interval, max_backoff):
        self._cache = cache
        self._base = base_url.rstrip("/")
        self._http = httpx.AsyncClient(timeout=timeout)
        self._interval = interval
        self._max_backoff = max_backoff
        self._delay = interval          # delay hiện tại, tăng khi lỗi
        self.degraded = False           # backend chưa có endpoint /sync/*
        self.last_sync_at = None
        self.last_sync_error = None
        self.version = ""

    async def warm_once(self) -> bool:
        """Kéo full payload và swap vào Redis. Trả True nếu cache dùng được."""
        version = await self._fetch_version()
        if version is None:                     # 404 → backend chưa có endpoint
            self.degraded = True
            return False
        payload = await self._fetch_payload()
        if payload is None:
            self.last_sync_error = "fetch_failed"
            return False
        await self._cache.swap_generation(payload, version)
        self.version = version
        self.last_sync_at = utcnow()
        self.last_sync_error = None
        return True

    async def run_forever(self) -> None:
        while True:
            await asyncio.sleep(self._delay)
            if self.degraded:               # chỉ dựa vào write-through, thỉnh thoảng thử lại
                self._delay = min(self._delay * 2, self._max_backoff)
                if await self._probe_endpoints():
                    self.degraded = False
                    self._delay = self._interval
                continue
            try:
                remote = await self._fetch_version()
                if remote is None:
                    raise SyncUnavailable()
                if remote == await self._cache.get_version():
                    logger.debug("Cache còn mới (version=%s); bỏ qua vòng này", remote)
                    self._delay = self._interval
                    continue
                logger.info("Cache đổi: %s → %s; kéo payload mới", self.version, remote)
                payload = await self._fetch_payload()
                if payload is None:
                    raise SyncUnavailable()
                await self._cache.swap_generation(payload, remote)
                self.version = remote
                self.last_sync_at = utcnow()
                self.last_sync_error = None
                self._delay = self._interval
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_sync_error = str(exc)
                self._delay = min(self._delay * 2, self._max_backoff)
                logger.warning("Sync lỗi (%s); thử lại sau %ss, vẫn dùng cache cũ", exc, self._delay)
```

Bốn hành vi bắt buộc:

- **Backoff nhân đôi, có trần.** Backend chết 2 giờ thì đừng đập nó 24 lần/giờ. 300 s → 600 → 1200 → 2400 (trần). Thành công thì reset về `interval`.
- **Cache cũ vẫn hợp lệ.** Không có `DEL` khi lỗi. Danh mục chi nhánh đổi vài lần mỗi tháng; dữ liệu 5 phút — hay thậm chí 5 giờ — tuổi vẫn đúng.
- **Chỉ ghi khi parse xong toàn bộ.** Parse trước, ghi sau. Payload méo một nửa thì bỏ cả vòng, đừng ghi một nửa.
- **Idempotent.** Gọi `warm_once()` lúc nào cũng an toàn. Dùng cho endpoint admin `POST /internal/sync/refresh` (bảo vệ bằng cùng bearer token) để ép sync ngay khi vừa thêm chi nhánh, không phải chờ 5 phút.

`**asyncio.CancelledError` phải `raise` lại**, không được bắt vào nhánh `except Exception` chung — nếu
không thì shutdown treo vì task không chịu chết.

### 5.4 Endpoint backend cần có


| Method | Path                         | Trả về                                             | Yêu cầu                                                                                            |
| ------ | ---------------------------- | -------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| GET    | `/api/v1/sync/check-version` | `{"version": "<hash>", "updated_at": "<ISO8601>"}` | **Phải rẻ.** Một query `MAX(updated_at)` hoặc hash cache sẵn. Đây là request gọi thường xuyên nhất |
| GET    | `/api/v1/sync/branches`      | Toàn bộ restaurant + branch (+ menu nếu muốn)      | Gọi 5 phút một lần, hoặc thưa hơn nhiều                                                            |


`version` là chuỗi tùy ý, AI Bridge chỉ so sánh bằng `==`. Backend có thể dùng:

- `md5` của `(restaurant_id, branch_id, name, address, status, updated_at)` toàn bảng, hoặc
- `MAX(updated_at)` của các bảng liên quan (đơn giản hơn, nhưng không phát hiện được xóa hàng nếu không soft-delete).

Payload `/api/v1/sync/branches` gợi ý:

```json
{
  "version": "8f2c4b1e9a…",
  "updated_at": "2026-09-07T04:10:11Z",
  "restaurants": [
    {
      "id": "b3f1…",
      "name": "Bella Vista",
      "phone": "1900636886",
      "hotlines": ["1900636886", "02839123456"],
      "status": "active",
      "branches": [
        {
          "id": "c7a2…",
          "name": "Bella Vista Quận 1",
          "address": "12 Lê Lợi, Quận 1",
          "opening_time": "09:00",
          "closing_time": "22:00",
          "status": "active"
        }
      ],
      "menus": {
        "c7a2…": [
          {"id": "m1", "name": "Phở bò", "price": 65000, "currency": "VND",
           "category": "Món chính", "unit": "tô", "status": "available"}
        ]
      }
    }
  ]
}
```

Quy tắc parse (giữ đúng logic v1 để không lệch hành vi, xem `booking/client.py`):

- Branch bỏ nếu thiếu `id` hoặc `name`, hoặc `status != "active"`.
- Restaurant bỏ nếu thiếu `id`, hoặc `status` có giá trị khác `active`.
- Món coi là hết hàng nếu `quantity_available == 0`, hoặc `status` ∈ {`unavailable`, `sold_out`, `sold-out`}.
- `hotlines` map nhiều số về một restaurant. Mọi số đều `normalize_hotline()` (chỉ giữ chữ số) trước khi làm khóa.
- Payload có thể bọc trong `{"data": …}` — dùng lại `unwrap_data()`.

`menus` là **tùy chọn**. Có thì warm luôn menu, `list_menu` trả kết quả tức thì. Không có thì menu vẫn
lấy lazy qua `GET /menu/branch/{branch_id}` như v1, rồi write-through vào cache.

### 5.5 Layout key Redis và atomic swap

**Không sửa key tại chỗ.** Mỗi lần sync ghi một generation mới rồi lật con trỏ:

```
aibridge:catalog:generation                → 7                (bộ đếm, INCR)
aibridge:catalog:pointer                   → "g7"             (generation đang hoạt động)
aibridge:catalog:g7:version                → "8f2c4b1e9a…"
aibridge:catalog:g7:hotline:1900636886     → JSON restaurant snapshot (branches đã lọc active)
aibridge:catalog:g7:hotline:02839123456    → JSON (cùng restaurant, hotline thứ hai)
aibridge:catalog:g7:menu:c7a2…             → JSON list MenuItem
aibridge:catalog:g7:index                  → JSON meta {"restaurants": 12, "hotlines": 15}
```

Trình tự ghi:

```
1)  g = INCR aibridge:catalog:generation                    → 7
2)  pipeline:
      SET aibridge:catalog:g7:version  "<hash>"   EX 10800
      SET aibridge:catalog:g7:hotline:1900636886  "<json>"  EX 10800
      SET aibridge:catalog:g7:menu:c7a2…          "<json>"  EX 10800
      … (toàn bộ payload)
      SET aibridge:catalog:g7:index    "<json>"   EX 10800
    EXEC
3)  SET aibridge:catalog:pointer "g7"                       ← ĐIỂM ĐỔI TRẠNG THÁI
4)  (không xóa g6; nó tự hết hạn theo TTL)
```

Reader luôn làm hai bước: `GET pointer` → đọc key theo generation đó.

### 5.6 Vì sao generation + pointer, không phải lock

Giả sử ta ghi thẳng vào `aibridge:catalog:hotline:*`. Race condition cụ thể:

```
t0  Cuộc gọi A: GET hotline:1900636886  → thấy restaurant có 3 chi nhánh, snapshot xong
t1  Syncer:     ghi hotline:1900636886  (chi nhánh Quận 3 vừa đóng, còn 2)
t2  Cuộc gọi A: GET menu:<id Quận 3>    → MISS, vì syncer đã xóa
    → A có chi nhánh Quận 3 trong prompt, nhưng không có menu. AI mời khách chọn
      chi nhánh rồi báo "không có món nào" — nghe như hệ thống hỏng.
```

Với generation + pointer: cuộc gọi A đọc `pointer` một lần được `g6`, rồi đọc mọi thứ trong `g6`. Syncer
ghi vào `g7` và lật con trỏ. A vẫn thấy `g6` **đầy đủ và nhất quán** đến hết cuộc gọi. Cuộc gọi B bắt đầu
sau t1 đọc `g7`, thấy dữ liệu mới. Không ai thấy trạng thái nửa vời, và **reader không cần lock nào**.

Lock chỉ cần cho **writer**, và chỉ khi chạy nhiều instance (§5.9).

Ràng buộc: `CACHE_GENERATION_TTL` phải **dài hơn cuộc gọi dài nhất** cộng biên an toàn. Cuộc gọi đặt bàn
dài 10 phút là nhiều; TTL 3 giờ (10800 s) là thoải mái. TTL quá ngắn thì cuộc gọi đang chạy bị mất
generation giữa đường → menu miss → rơi về HTTP (vẫn chạy, nhưng chậm).

### 5.7 Đường đọc trong luồng cuộc gọi

```python
# cache/redis_store.py — chữ ký gợi ý
class CatalogCache:
    async def get_restaurant(self, hotline_digits: str) -> Restaurant | None: ...
    async def get_menu(self, branch_id: str) -> list[MenuItem] | None: ...
    async def put_restaurant(self, hotline_digits: str, r: Restaurant, ttl: int) -> None: ...
    async def put_menu(self, branch_id: str, items: list[MenuItem], ttl: int) -> None: ...
    async def swap_generation(self, payload: SyncPayload, version: str) -> None: ...
    async def get_version(self) -> str: ...
    async def stats(self) -> dict: ...
```

Trả về `Restaurant` / `MenuItem` — **đúng dataclass** trong `booking/models.py` và `order/models.py`, không
phải dict thô. Parse ở tầng cache, để prompt builder và tool không bao giờ phải chạm JSON.

`CallPipeline._load_catalog()` đổi thành ba bậc:

```python
async def _load_catalog(self) -> None:
    try:
        if not self.session.to_number:
            self.session.restaurant_missing = True
            logger.warning("Hotline catalog skipped: empty toNumber %s", self.session.tag)
            return

        # Bậc 1 — cache. Đường nhanh, cỡ ms.
        restaurant = None
        if self._cache is not None:
            try:
                restaurant = await self._cache.get_restaurant(self.session.to_number)
            except Exception:
                logger.warning("Cache read lỗi %s; rơi về HTTP", self.session.tag, exc_info=True)

        # Bậc 2 — HTTP như v1, rồi write-through.
        if restaurant is None and self._restaurant is not None:
            result = await self._restaurant.find_by_hotline(self.session.to_number)
            restaurant = result.restaurant
            if restaurant is not None and self._cache is not None:
                with contextlib.suppress(Exception):
                    await self._cache.put_restaurant(
                        self.session.to_number, restaurant, ttl=self._cache_ttl
                    )

        # Bậc 3 — không có gì: prompt chuyển sang chế độ xin lỗi.
        if restaurant is None:
            self.session.restaurant_missing = True
            return

        self.session.apply_restaurant(restaurant)
        if len(self.session.branches) == 1:
            self.session.select_branch(self.session.branches[0].id)
    except Exception:
        logger.exception("Hotline catalog failed %s", self.session.tag)
        self.session.restaurant_missing = True
    finally:
        self.session.catalog_ready = True
        self.session.refresh_system_prompt()
```

Ba điểm không được bỏ:

- `**finally` luôn set `catalog_ready` và refresh prompt.** `_run_reply` `await` task này; task chết mà không set cờ là cuộc gọi treo im lặng.
- **Mọi lỗi Redis đều bị nuốt** (log rồi đi tiếp). Redis không phải hard dependency.
- **Auto-lock chi nhánh khi chỉ có một chi nhánh active.** Đừng hỏi khách chọn khi chỉ có một lựa chọn.

Menu đi đường tương tự trong `order/tools.py`: cache → `GET /menu/branch/{id}` → write-through.

### 5.8 Degrade mode

Hai kiểu degrade, xử lý khác nhau:


| Tình huống                       | Phát hiện                   | Hành vi                                                                                                                                                                        |
| -------------------------------- | --------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Backend chưa có `/api/v1/sync/*` | `check-version` trả 404     | `degraded = True`. Tắt polling danh mục toàn cục. Cache chỉ hoạt động write-through với `CACHE_TTL_SECONDS` (mặc định 600 s). Định kỳ probe lại endpoint, có thì bật full mode |
| Redis không tới được             | Exception lúc connect / đọc | `catalog_cache = None` hoặc mọi đọc trả `None`. Toàn hệ thống chạy đúng như v1                                                                                                 |


Ở degrade write-through, **vẫn có lợi**: cuộc gọi đầu tiên tới một hotline trả giá HTTP, các cuộc gọi sau
trong 10 phút đọc cache. Với hotline có lưu lượng, gần như mọi cuộc gọi đều hit.

### 5.9 Nhiều instance AI server

Mọi instance đều **đọc** được cache; chỉ một instance nên **ghi**:

```
SET aibridge:sync:lock <instance_id> NX EX 60     # thử giành quyền writer
→ OK   : là writer vòng này. PEXPIRE gia hạn mỗi 20 s trong lúc sync
→ nil  : bỏ qua vòng này, chỉ đọc cache do writer ghi
```

Không giành được lock **không** phải lỗi — log `DEBUG` là đủ.

Muốn tách hẳn khỏi process AI: chuyển `CatalogSyncer` thành Celery task với `beat` interval 5 phút, broker
RabbitMQ. `CatalogCache` và luồng cuộc gọi **không đổi một dòng** — chúng chỉ biết Redis, không biết ai ghi.
Nên làm asyncio trước, đổi sang Celery khi thật sự cần nhiều instance.

### 5.10 Quan sát

`GET /health` mở rộng, giữ tương thích ngược (`status` vẫn là `"ok"`):

```json
{
  "status": "ok",
  "cache": {
    "enabled": true,
    "ready": true,
    "degraded": false,
    "generation": "g7",
    "version": "8f2c4b1e9a…",
    "restaurants": 12,
    "hotlines": 15,
    "menus": 23,
    "last_sync_at": "2026-09-07T04:10:11Z",
    "last_sync_error": null,
    "next_poll_in_s": 214
  }
}
```

Frontend hiện tại chỉ đọc `response.ok`, nên thêm field không phá gì.

Quy ước log:


| Mức       | Khi nào                                                                            |
| --------- | ---------------------------------------------------------------------------------- |
| `DEBUG`   | Version không đổi, bỏ qua vòng polling; không giành được lock writer               |
| `INFO`    | Version đổi và swap thành công (kèm generation cũ → mới, số restaurant, số branch) |
| `WARNING` | Sync lỗi, đang backoff; cache read lỗi và rơi về HTTP                              |
| `ERROR`   | Warm lần đầu thất bại; parse payload sai cấu trúc                                  |


**Không log payload đầy đủ** — nó chứa địa chỉ chi nhánh và đầy log. Log số lượng, không log nội dung.

---

## 6. Luồng một cuộc gọi, theo timeline

### 6.1 Timeline

```
t=0      Client mở WS /v1/bridge?token=…
         → _bearer_authorized() OK → accept()
         → spawn task _start_stt() (mở Realtime tới OpenAI, ~200-500 ms)

t≈5ms    Client gửi session.init (JSON)
         → apply_init(): lưu callId/storeName/timezone/locale
         → normalize_hotline(toNumber) → "1900636886"
         → greeting vào history[0] dạng assistant
         → build_system_prompt() lần đầu (chưa có danh mục)
         → spawn task _load_catalog()
         → spawn task _run_greeting()

t≈8ms    _load_catalog: GET pointer → "g7"
                        GET g7:hotline:1900636886 → HIT
         → apply_restaurant(): branches = [Quận 1, Quận 3, Hà Nội]
         → catalog_ready = True, refresh_system_prompt()
         ⇒ TOÀN BỘ mất ~3 ms. v1 chỗ này mất 300 ms → vài giây.

t≈10ms   _run_greeting: begin_generation() → gen=1, state=GREETING
         → awaiting_choice = True
         → TTS synth 4 câu: disclosure + 3 lựa chọn phím

t≈400ms  Frame PCM đầu tiên của câu chào ra client
         → mark_audio_sent(): playing=True, state=SPEAKING

t≈5s     Khách ấn phím 1 GIỮA LÚC AI còn đang đọc lựa chọn thứ ba
         → client: player.interrupt() ngay (im tức thì, không chờ server)
         → client gửi {"event":"dtmf","digit":"1"}
         → server: generation_id++ → gửi interrupt trong lock → cancel task menu
         → apply_service_choice("1"): intent="booking", awaiting_choice=False
         → refresh_system_prompt(): BỎ khối hỏi loại dịch vụ
         → gen=2, state=THINKING
         ⇒ Tiết kiệm cả một vòng VAD 450 ms + STT + LLM so với hỏi bằng lời.

t≈5.6s   LLM sinh câu: "Dạ đặt bàn. Mình có chi nhánh Quận 1, Quận 3 và Hà Nội.
                        Anh muốn đặt ở đâu ạ?"
         → aggregator cắt câu → TTS song song → gửi tuần tự

t≈6.1s   Audio ra client → phát xong → state=LISTENING

         (Nếu khách KHÔNG ấn phím: hết menu → hẹn timeout
          DTMF_MENU_TIMEOUT_SECONDS tính từ lúc audio phát xong.
          Timeout nổ → awaiting_choice=False → AI hỏi bằng lời như v1.)

t≈8s     Khách: "Quận 3 nhé"
         → STT: speech_started (AI đang im, không cần barge-in)
         → im 450 ms → transcription.completed

t≈8.5s   on_transcript_completed(text)
         → begin_generation() → gen=3, state=THINKING
         → await _catalog_task (đã xong từ t=8ms, trả ngay)
         → history.append({"role":"user","content":"Quận 3 nhé"})
         → LLM stream với 11 tools

t≈9s     LLM gọi tool: resolve_branch(spoken_name="Quận 3 nhé")
         → OpenAiBranchMatcher: LLM phụ, temperature=0, json_object
         → {"status":"match","branch_id":"c7a2…","confidence":"high"}
         → select_branch() khóa chi nhánh, refresh prompt
         → kết quả tool vào history dạng role:"tool"

t≈9.6s   LLM vòng 2: "Dạ chi nhánh Quận 3. Anh cho em tên và số điện thoại ạ?"
         → TTS → audio ra client → phát xong → LISTENING
```

### 6.2 Ví dụ hội thoại đầy đủ, kèm trace

Kịch bản: đặt bàn, khách đổi ý giữa đường.


| Ai    | Nội dung                                                                                             | Việc xảy ra bên trong                                                                                                                                 |
| ----- | ---------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| AI    | "Xin chào, cảm ơn bạn đã gọi Bella Vista. Đây là trợ lý tự động. Để đặt bàn, bạn ấn phím 1. Để đặt đồ ăn rồi đến lấy, bạn ấn phím 2. Để đặt đồ ăn giao tận nơi, bạn ấn phím 3." | `greeting` nguyên văn, cắt thành 4 câu. `awaiting_choice=True`, `intent=""`                                                                            |
| Khách | *ấn phím 1 khi AI mới đọc tới lựa chọn thứ hai*                                                      | DTMF-as-barge-in (§7.1.6): `interrupt` → `service_choice="1"`, `intent="booking"`. Prompt bỏ khối hỏi loại dịch vụ                                    |
| AI    | "Dạ đặt bàn. Mình có chi nhánh Quận 1, Quận 3 và Hà Nội. Anh muốn đặt ở đâu ạ?"                      | Đọc **chỉ tên** từ snapshot. Địa chỉ là dữ liệu nội bộ, cấm đọc lúc này                                                                               |
| Khách | "Cầu Giấy đi."                                                                                       | `resolve_branch("Cầu Giấy đi")` → `{"status":"none"}` — không có chi nhánh nào tên Cầu Giấy                                                           |
| AI    | "Dạ mình chưa có chi nhánh ở Cầu Giấy. Hiện có Quận 1, Quận 3 và Hà Nội ạ."                          | Tool trả `none` → **không** được bịa. Nêu lại tên thật                                                                                                |
| Khách | "Vậy Quận 3."                                                                                        | `resolve_branch("Vậy Quận 3")` → `match`, `high` → `select_branch()` khóa, `menu`+`cart` reset                                                        |
| AI    | "Dạ chi nhánh Quận 3. Anh cho em tên và số điện thoại ạ?"                                            | Slot 2 xong, sang slot 3+4                                                                                                                            |
| Khách | "Nam, 0901234567."                                                                                   | Slot 3, 4 vào đối số `create_booking` sau này                                                                                                         |
| AI    | "Dạ anh Nam. Mấy người và mấy giờ ạ?"                                                                | Slot phụ của nhánh đặt bàn                                                                                                                            |
| Khách | "4 người, 7 giờ tối mai."                                                                            | `party_size=4`. `"7 giờ tối mai"` → `resolve_booking_when()` → `booking_date` = ngày mai theo `Asia/Ho_Chi_Minh`, `booking_time="19:00"`              |
| AI    | "Em xác nhận: anh Nam, 0901234567, 4 người, 19 giờ ngày 08/09 tại Quận 3. Đúng không ạ?"             | **Đọc lại trước khi gọi tool.** Bắt buộc                                                                                                              |
| Khách | *chen ngang giữa câu* "À không, chuyển qua Quận 1 cho anh."                                          | `speech_started` → barge-in: `generation_id++`, gửi `interrupt`, commit phần đã nói, hủy task                                                         |
| AI    | "Dạ, đổi sang Quận 1. Vẫn 4 người 19 giờ ngày 08/09 phải không ạ?"                                   | `resolve_branch("Quận 1")` → khóa lại. Slot tên/SĐT/giờ **giữ nguyên**, khách không phải khai lại                                                     |
| Khách | "Đúng rồi."                                                                                          |                                                                                                                                                       |
| AI    | *(im lặng ~0.8 s)*                                                                                   | `create_booking(customer_name="Nam", phone_number="0901234567", party_size=4, booking_date="2026-09-08", booking_time="19:00")` → `POST /bookings/ai` |
| AI    | "Em đã đặt xong bàn cho anh tại chi nhánh Quận 1, 19 giờ ngày 08/09. Cảm ơn anh đã gọi Bella Vista." | Tool trả `ok:true` → `booking_created=True`. **Chỉ giờ mới được nói "đã đặt xong"**                                                                   |
| —     | *socket đóng, client cúp máy*                                                                        | §8: chờ grace cho audio phát hết → `close(1000)`                                                                                                      |


Chú ý hai chỗ dễ code sai:

1. Sau `resolve_branch` trả `none`, LLM **rất muốn** nói "Dạ được, chi nhánh Cầu Giấy ạ". Prompt cấm chuyện này, và đó là lý do bắt buộc gọi tool **trước khi** khẳng định.
2. Sau barge-in đổi chi nhánh, các slot khác phải sống sót. Chỉ `menu` và `cart` bị reset (vì món phụ thuộc chi nhánh), tên/SĐT/giờ thì không.

---

## 7. Chọn dịch vụ bằng phím, function calling và slot

### 7.1 Menu chọn dịch vụ bằng phím (DTMF)

#### 7.1.1 Vì sao đổi từ hỏi bằng lời sang ấn phím

Slot "loại dịch vụ" khác mọi slot còn lại: nó có **tập giá trị đóng, chỉ ba lựa chọn**. Tên khách thì vô
hạn khả năng nên buộc phải nghe; loại dịch vụ thì không.

| Lý do | Cụ thể |
| --- | --- |
| Chính xác 100% | Phím `2` là pickup, không có cách nào hiểu sai. Còn "mang về" và "giao về nhà" thì STT nghe nhầm được, và bản thân khách cũng nói không rõ |
| Nhanh hơn ~2 giây | Bỏ được cả một vòng VAD 450 ms + STT + LLM + TTS ở lượt đầu (xem ngân sách §2.3) |
| Bỏ được một lượt hỏi thêm | v1: khách nói "đặt đồ ăn" → AI vẫn phải hỏi "anh đến lấy hay giao tận nơi ạ?". v2: phím 2 và 3 đã phân biệt sẵn |
| Rẻ hơn | Ít một lượt LLM và một lượt TTS mỗi cuộc gọi |

Đánh đổi: khách phải rời tai khỏi điện thoại để ấn, và một số người không thích IVR. Vì thế **đường nói
vẫn giữ nguyên** — không ấn phím thì sau timeout AI hỏi bằng lời như v1 (§7.1.5).

#### 7.1.2 Câu chào mới

```
Xin chào, cảm ơn bạn đã gọi Bella Vista. Đây là trợ lý tự động.
Để đặt bàn, bạn ấn phím 1.
Để đặt đồ ăn rồi đến lấy, bạn ấn phím 2.
Để đặt đồ ăn giao tận nơi, bạn ấn phím 3.
```

Ba chi tiết không được làm khác:

- **Disclosure đứng trước menu.** Câu "đây là trợ lý tự động" phải phát trước, không được chèn vào giữa hay sau menu.
- **Mỗi lựa chọn là một câu riêng, kết thúc bằng dấu chấm.** `SentenceAggregator` sẽ cắt thành bốn câu, TTS synth bốn lần và có nhịp nghỉ tự nhiên giữa các lựa chọn. Viết menu thành một câu dài thì TTS đọc liền một hơi, khách không kịp nhớ phím nào.
- **Số đứng ở cuối câu.** "Để đặt bàn, bạn ấn phím 1" tốt hơn "Ấn phím 1 để đặt bàn", vì thông tin cuối câu là thứ khách còn giữ trong đầu khi tay đang tìm phím.

`ensure_intent_greeting()` đổi tương ứng: thay vì thêm `"Bạn muốn đặt bàn hay mang về ạ?"`, nó thêm khối
`SERVICE_MENU_VI` (và `SERVICE_MENU_EN` cho locale `en`), và chỉ thêm khi câu chào client gửi chưa chứa menu.

#### 7.1.3 Ánh xạ phím

| Phím | Dịch vụ | State sau khi nhận |
| --- | --- | --- |
| `1` | Đặt bàn | `intent="booking"`, `fulfillment=""` |
| `2` | Đặt đồ ăn, đến lấy | `intent="order"`, `fulfillment="pickup"` |
| `3` | Đặt đồ ăn, giao tận nơi | `intent="order"`, `fulfillment="delivery"` |
| `0` | Dành cho chuyển lễ tân — **hoãn**, v2 coi như phím sai | không đổi |
| `4`–`9`, `*`, `#` | Không hợp lệ | không đổi, tăng `invalid_digit_count` |

Phím `2` và `3` **đặt luôn `fulfillment`**, nên đường DTMF không cần gọi `set_fulfillment`. Tool đó vẫn
giữ, vì khách còn đổi ý giữa cuộc gọi bằng lời ("à cho anh giao tận nơi luôn").

Phím sai: AI đọc lại **menu ngắn** ("Dạ mình chưa nhận được. Đặt bàn ấn 1, đến lấy ấn 2, giao tận nơi ấn
3 ạ."), tối đa hai lần. Lần thứ ba thì thôi ấn phím, chuyển sang hỏi bằng lời — đừng bắt khách ấn mãi.

#### 7.1.4 Event trên wire

Client → AI, text frame:

```json
{"event":"dtmf","digit":"1","callId":"call_1a2b3c"}
```

| Quy tắc | Lý do |
| --- | --- |
| AI Bridge **không** giải mã tone DTMF | Trình duyệt có nút nên gửi JSON trực tiếp. Backend điện thoại thật giải mã RFC 2833 hoặc tone in-band rồi gửi **cùng** JSON này. Giữ đúng nguyên tắc: telephony thuộc về backend, AI Bridge chỉ thấy JSON và PCM |
| `digit` là chuỗi **một** ký tự trong `0123456789*#` | Chuỗi nhiều ký tự (`"12"`) → log `WARNING`, bỏ qua. Không tự tách thành hai lần ấn |
| `callId` tùy chọn, chỉ để khớp log | Session đã biết mình là cuộc gọi nào |
| Không có event AI → client cho việc này | Menu do TTS đọc. Client không cần biết menu gồm gì |
| Client không gửi `dtmf` → luồng hỏi bằng lời chạy y như v1 | Tương thích ngược hai chiều: client cũ + server mới, và client mới + server cũ (server cũ bỏ qua event lạ) |

Bổ sung vào `bridge/protocol.py`:

```python
EVENT_DTMF = "dtmf"
VALID_DTMF_DIGITS = frozenset("0123456789*#")
SERVICE_BY_DIGIT = {
    "1": ("booking", ""),
    "2": ("order", "pickup"),
    "3": ("order", "delivery"),
}

@dataclass(frozen=True)
class DtmfDigit:
    digit: str
    call_id: str = ""
```

#### 7.1.5 State machine

Thêm vào `CallSession`:

```python
service_choice: str = ""        # "" | "1" | "2" | "3"
awaiting_choice: bool = False   # đang chờ khách ấn phím
invalid_digit_count: int = 0
last_digit_at: float = 0.0      # cho debounce
```

```
Init ──session.init──> Greeting
                       (TTS đọc menu; awaiting_choice = True)
                                │
        ┌───────────────────────┼────────────────────────┬──────────────────────┐
        │ dtmf hợp lệ           │ dtmf sai               │ timeout              │ khách NÓI
        ▼                       ▼                        ▼                      ▼
  hủy timeout            đọc lại menu ngắn        awaiting_choice=False   xử lý như lượt
  apply_service_choice() (tối đa 2 lần)           AI hỏi bằng lời         thường; LLM tự
  refresh prompt         vẫn awaiting             (đường v1)              suy intent (v1)
  → Thinking → nói
    câu tiếp của nhánh
```

Ba điểm dễ code sai:

- **`awaiting_choice` chỉ điều khiển menu và timeout, không điều khiển việc nhận phím.** Phím được nhận **suốt cuộc gọi**, kể cả sau khi đã chọn và sau khi đã tạo đơn (§7.1.8). Đừng viết `if not awaiting_choice: return` ở đầu `on_dtmf()`.
- **Timeout đếm từ lúc TTS phát *xong* menu**, không phải từ lúc bắt đầu đọc. Menu dài ~8 giây; đếm từ đầu thì timeout nổ trước khi khách nghe hết lựa chọn thứ ba. Đặt hẹn trong `TurnPlayer.finish()` của lượt greeting, cộng thêm phần audio còn trong buffer client (dùng lại công thức `remaining_playback_seconds` ở §8.2).
- **Khách nói thay vì ấn phím vẫn phải chạy được.** Không được chặn transcript khi `awaiting_choice = True`. Khách nói "cho tôi đặt bàn" thì LLM suy ra `intent` như v1, và `awaiting_choice` tắt.

#### 7.1.6 DTMF là một dạng barge-in

Khách rất hay ấn phím ngay khi nghe "để đặt bàn, bạn ấn phím 1", không chờ đọc hết menu. AI phải im
**ngay lập tức**, đúng như barge-in bằng giọng:

```
1) Lấy outbound.lock
2) generation_id += 1                      → TTS menu đang dở thành stale
3) Gửi {"event":"interrupt"} TRONG lock     → client xóa queue audio
4) commit_partial_assistant()              → history khớp phần khách đã nghe
5) Nhả lock, rồi mới cancel task menu
6) apply_service_choice(digit) → refresh_system_prompt()
7) Spawn lượt mới: AI nói câu tiếp theo của nhánh đã chọn
```

Khác barge-in bằng giọng ở **đúng một điểm**: không chờ VAD, không chờ transcript. Phím là tín hiệu tức
thì và chắc chắn, nên xử lý ngay khi parse xong JSON.

Dùng lại `abort_and_interrupt()` với `abort_work` là task menu — **không** viết lại logic barge-in. Mọi
ràng buộc thứ tự ở §11.2 vẫn áp dụng nguyên vẹn, đặc biệt là "gửi `interrupt` trong lock".

Phía client, nút bấm nên gọi `player.interrupt()` **local ngay khi ấn**, không chờ `interrupt` từ server.
Tiết kiệm một RTT và khách cảm nhận nút "ăn" ngay — đây là khác biệt giữa cảm giác mượt và cảm giác lag.

#### 7.1.7 Debounce và đổi ý

| Tình huống | Xử lý |
| --- | --- |
| Ấn cùng phím nhiều lần trong `DTMF_DEBOUNCE_MS` (500 ms) | Bỏ các lần sau. Chống double-click ở browser và chống tone bị nhân bản ở telephony |
| Ấn phím khác sau khi đã chọn, **chưa** tạo đơn | **Cho đổi.** Apply lại `intent`/`fulfillment`, **giữ** tên, SĐT, chi nhánh đã thu. Reset `cart` nếu đổi từ `order` sang `booking` |
| Ấn phím của nhánh **chưa** tạo, sau khi nhánh kia đã tạo (đã đặt bàn → ấn `2`/`3`) | **Nhận.** Đổi `intent`, mở nhánh thứ hai trong cùng cuộc gọi, giữ tên/SĐT/chi nhánh đã thu. Xem §7.1.8 |
| Ấn phím của nhánh **đã** tạo (đã đặt bàn → ấn `1` lại) | Không tạo lần hai. AI xác nhận lại đơn đã ghi; tool trả `already_created` (§7.6) |
| Ấn phím giữa lúc đang chạy tool create | Bỏ qua. Hủy giữa lúc `POST` là mở đường cho đơn kép — xem §10.4 |

Đổi từ `2` sang `3` (pickup → delivery) thì phải hỏi địa chỉ, và prompt **tự biết** vì
`fulfillment="delivery"` mà `delivery_address` rỗng. Không cần code riêng cho nhánh này.

#### 7.1.8 Phím là tín hiệu ý định, không phải lệnh tạo đơn

Đây là điểm dễ nhầm nhất của cả mục 7.1, nên tách ra nói rõ.

**Phím chỉ set `intent` và `fulfillment`. Phím không bao giờ trực tiếp gọi tool create.** Vì thế cho phép
ấn phím ở bất kỳ lúc nào trong cuộc gọi là **an toàn**, kể cả sau khi đã tạo đơn: nó chỉ chuyển hướng hội
thoại, còn việc chống tạo trùng vẫn nằm nguyên ở ba lớp bảo vệ của §7.6 (cờ state, prompt, và tool tự chặn).

Vì sao nên cho phép: phím là **tín hiệu ý định chính xác hơn lời nói**. Khách vừa đặt bàn xong rồi nói "à
cho anh đặt món luôn" thì LLM phải suy từ transcript — mà transcript có thể sai, và "đặt món" còn chưa rõ
là đến lấy hay giao tận nơi. Khách ấn phím `3` thì ta biết chắc chắn: đơn giao hàng. Đúng cái slot mà lời
nói hay gây nhầm nhất lại là cái phím giải quyết gọn nhất.

Lợi ích kèm theo: chuyển nhánh mà **giữ nguyên tên, số điện thoại và chi nhánh** đã thu ở nhánh đầu. Khách
không phải khai lại lần thứ hai — đây là điểm khách hay phàn nàn nhất khi làm hai việc trong một cuộc gọi.

Prompt v1 đã cho phép sẵn hai nhánh trong một cuộc gọi ("Cuộc gọi này đã tạo đặt bàn… Vẫn có thể nhận đơn
món nếu chưa tạo"), nên đường phím **không cần thêm luật prompt nào** — chỉ set `intent` rồi refresh.

Hai hệ quả phải xử lý khi code:

- **Đang chờ cúp máy mà khách ấn phím → hủy cúp** (§8.4). Sau câu chốt đặt bàn, khách ấn `3` là muốn đặt món tiếp; cúp máy lúc đó là mất một đơn.
- **Đơn món thứ hai trong cùng cuộc gọi vẫn ngoài phạm vi v2.** `order_created` chặn `create_order` lần hai, nên đã tạo đơn pickup rồi ấn `3` thì AI chỉ xác nhận lại đơn cũ, không tạo đơn giao mới. Đây là hạn chế đã biết; muốn hỗ trợ thì phải cho `order_created` thành danh sách đơn, và đó là việc của v3.

#### 7.1.9 Ảnh hưởng tới system prompt

`build_system_prompt()` nhận thêm `service_choice`, và bốn trạng thái cho ra bốn prompt khác nhau:

| Trạng thái | Prompt |
| --- | --- |
| Đã chọn phím | **Bỏ hẳn** khối "hỏi khách muốn đặt bàn hay mang về". Thêm: "Khách đã chọn *đặt bàn* bằng phím 1. Không hỏi lại loại dịch vụ. Đi thẳng vào bước tiếp theo." |
| Phím `2` / `3` | `fulfillment` đã set → prompt ghi "Hình thức: đến lấy tại chi nhánh" hoặc "Hình thức: giao tận nơi, cần địa chỉ", và **không** hỏi lại pickup/delivery |
| Chưa chọn, chưa timeout | "Khách đang nghe menu phím. Nếu khách nói thay vì ấn phím, suy ra dịch vụ từ lời họ và tiếp tục." |
| Đã timeout | Dùng đúng prompt v1: hỏi bằng lời |

Cắt một câu hỏi khỏi hội thoại nghĩa là cắt một vòng STT + LLM + TTS, và cắt luôn một chỗ có thể hiểu sai.
Đó là giá trị thật của IVR ở đây, không phải chuyện "nghe chuyên nghiệp hơn".

#### 7.1.10 Frontend: keypad ba nút

Thêm một hàng nút cạnh Gọi / Cúp / Tắt mic:

```
[ 1  Đặt bàn ]   [ 2  Đến lấy ]   [ 3  Giao hàng ]
```

| Yêu cầu | Chi tiết |
| --- | --- |
| Chỉ bật khi đang gọi | `disabled = !live`, giống `muteBtn` / `hangBtn` trong `setLiveUi()` |
| Im ngay khi ấn | `player.interrupt()` **trước** khi gửi, không chờ server |
| Gửi event | `bridge.sendDtmf("1")` → `{"event":"dtmf","digit":"1","callId":…}` |
| Ghi log UI | `log("Đã ấn phím 1 — Đặt bàn", "ok")`, và `setStatus()` cho khách thấy phản hồi tức thì |
| Phím tắt bàn phím | `1` / `2` / `3` khi đang gọi. **Phải bỏ qua** khi focus đang ở `input` / `textarea`, nếu không thì gõ số điện thoại vào form sẽ bắn DTMF |
| Đánh dấu lựa chọn | `aria-pressed="true"` trên nút đang chọn. Vẫn cho ấn nút khác để đổi ý |
| Không cần keypad 0–9 đầy đủ | Ba nút đủ cho nghiệp vụ. Muốn test nhánh phím sai thì thêm tạm một nút `9` |

File phải sửa: `frontend/index.html` (khối keypad), `frontend/src/styles.css`,
`frontend/src/main.ts` (handler + phím tắt), `frontend/src/bridge.ts` (`sendDtmf`),
`frontend/src/protocol.ts` (`EVENT_DTMF`, type payload).

`sendDtmf` bám đúng khuôn `sendPcm` / `sendInit` đang có:

```typescript
sendDtmf(digit: string): void {
  if (this.ws?.readyState !== WebSocket.OPEN) return;
  this.ws.send(JSON.stringify({ event: EVENT_DTMF, digit }));
}
```

#### 7.1.11 Đo lường

Ba chỉ số cho biết menu có thật sự tốt hơn không:

- **Tỉ lệ ấn phím so với nói.** Ấn thấp nghĩa là menu đọc quá dài, quá nhanh, hoặc khách không tin là ấn được.
- **Tỉ lệ phím sai.** Cao nghĩa là nhãn lựa chọn chưa rõ (ví dụ khách không phân biệt "đến lấy" và "mang về").
- **Tỉ lệ rơi về hỏi bằng lời do timeout.** Cao nghĩa là `DTMF_MENU_TIMEOUT_SECONDS` quá ngắn.

### 7.2 Bốn slot lõi

LLM hỏi **1–2 câu mỗi lượt**, không đọc tên field, không bịa:


| #   | Slot          | Field trong `CallSession`                                 | Ghi vào bằng                                    |
| --- | ------------- | --------------------------------------------------------- | ----------------------------------------------- |
| 1   | Loại dịch vụ  | `service_choice`, `intent` (`booking`/`order`), `fulfillment` (`pickup`/`delivery`) | **Phím 1/2/3** (§7.1); hoặc suy từ lời khách + `set_fulfillment` nếu khách không ấn |
| 2   | Chi nhánh     | `selected_branch_id`, `selected_branch_name`              | `resolve_branch` → `confirm_branch`             |
| 3   | Tên khách     | đối số `create_*`, hoặc `order_customer_name`             | `save_order_details` / đối số `create_*`        |
| 4   | Số điện thoại | đối số `create_*`, hoặc `order_customer_phone`            | `save_order_details` / đối số `create_*`        |


Slot phụ theo nhánh:

- **Đặt bàn**: `party_size` (1–50), `booking_date` (`YYYY-MM-DD` theo TZ nhà hàng), `booking_time` (`HH:MM`), `note` tùy chọn.
- **Đặt món**: giỏ hàng (≥ 1 dòng), `booking_date`, `booking_time`, `delivery_address` **bắt buộc** nếu `delivery`, `delivery_phone` nếu người nhận khác người đặt.

### 7.3 Toàn bộ 11 tool

**Đặt bàn** — `booking/tools.py`:


| Tool             | Đối số                                                                                 | Trả về                                                                                                                          | Ghi chú                                                            |
| ---------------- | -------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------ |
| `resolve_branch` | `spoken_name` (**nguyên văn lời khách**)                                               | `status` (`match`/`ambiguous`/`none`), `locked`, `confidence`, `confirm_name`, `branch_id`, `available_branches`, `candidates?` | Tự khóa chi nhánh nếu `match` + `high`                             |
| `confirm_branch` | `branch_id`                                                                            | `ok`, `locked`, `confirm_name`                                                                                                  | `branch_id` **phải** từ `resolve_branch`. ID lạ → `unknown_branch` |
| `create_booking` | `customer_name`, `phone_number`, `party_size`, `booking_date`, `booking_time`, `note?` | `ok` + chi tiết, hoặc `error`                                                                                                   | `restaurant_id`/`branch_id` lấy từ state, **không** là đối số      |


**Đặt món** — `order/tools.py`:


| Tool                 | Đối số                                                                                          | Ghi chú                                                                                        |
| -------------------- | ----------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| `search_menu`        | `spoken_name`                                                                                   | Bắt buộc trước khi khẳng định có món. Nhận ra câu "có món gì" và tự chuyển sang chế độ browse  |
| `list_menu`          | (không)                                                                                         | Khi khách hỏi thực đơn. Trả tối đa 12 món + cờ `truncated`                                     |
| `add_to_cart`        | `menu_item_id`, `quantity` (1–50), `note?`                                                      | `menu_item_id` **phải** từ `search_menu`                                                       |
| `update_cart`        | `menu_item_id`, `quantity`, `note?`                                                             | Dòng phải đã có trong giỏ                                                                      |
| `remove_from_cart`   | `menu_item_id`, `note?`                                                                         |                                                                                                |
| `set_fulfillment`    | `fulfillment` (`delivery`/`pickup`), `delivery_address?`, `delivery_phone?`                     | Địa chỉ **bắt buộc** khi `delivery`                                                            |
| `save_order_details` | `customer_name?`, `phone_number?`, `booking_date?`, `booking_time?`, `note?`, `delivery_phone?` | Gọi **ngay** khi khách nêu, đừng chờ tới lúc tạo đơn — barge-in không làm mất thông tin đã lưu |
| `create_order`       | `customer_name`, `phone_number`, `booking_date`, `booking_time`, `note?`, `delivery_phone?`     | Giỏ, `restaurant_id`, `branch_id` từ state                                                     |


### 7.4 Vì sao `restaurant_id` và `branch_id` không phải đối số

Nếu để LLM truyền UUID, sớm muộn nó sẽ bịa một UUID trông hợp lệ, và ta `POST` vào backend một
`branch_id` không tồn tại (hoặc tệ hơn: của nhà hàng khác). Lấy từ state có ba lợi ích:

1. Không thể bịa — giá trị chỉ vào state qua `select_branch()`, mà hàm đó chỉ nhận id có trong snapshot.
2. LLM không cần "nhớ" UUID xuyên nhiều lượt, tiết kiệm token và giảm ảo giác.
3. UUID không bao giờ vào prompt để bị đọc ra miệng ("Dạ chi nhánh c7a2 f4b1…").

Cùng lý do đó: `available_branches` trong kết quả tool chỉ chứa `branch_id` + `name`, không có địa chỉ.
Địa chỉ chỉ nằm trong một khối prompt riêng ghi rõ "cấm đọc trừ khi khách hỏi".

### 7.5 Vòng lặp tool trong LLM

`OpenAiLlm.stream_sentences()` chạy tối đa `_MAX_TOOL_ROUNDS = 12` vòng mỗi lượt:

```
vòng 1: stream chat
        ├─ có content → aggregator cắt câu → yield ra TurnPlayer → TTS
        └─ có tool_calls → gom delta (id, name, arguments là chuỗi ghép dần)
        stream hết
        nếu không có tool_call → return (lượt xong)
        nếu có:
          history.append({"role":"assistant","content":None,"tool_calls":[…]})
          với mỗi call:  chạy tool → history.append({"role":"tool","tool_call_id":…,"content":json})
vòng 2: stream chat lại với history đã có kết quả tool
        …
```

Chi tiết dễ bỏ sót:

- `**arguments` đến từng mảnh.** Phải ghép (`slot["arguments"] += …`) rồi mới `json.loads`. Parse mảnh lẻ là `JSONDecodeError`.
- `**should_abort()` được kiểm ở mọi vòng.** Barge-in giữa lúc chạy tool thì tool sau nhận `{"ok":false,"error":"interrupted"}` và vòng lặp dừng.
- **Nếu có tool_call thì phần text dư (`remainder`) bị bỏ.** Vì đó thường là văn bản nửa vời trước khi model quyết định gọi tool.
- **Chạm trần 12 vòng → log `WARNING` và không nói gì.** Không nên xảy ra; nếu thấy trong log là dấu hiệu prompt bị lặp vòng (ví dụ tool luôn trả lỗi và LLM cứ thử lại).

### 7.6 Chống tạo đơn hai lần

Ba lớp bảo vệ, cần cả ba:

1. **Cờ state**: `booking_created` / `order_created` set sau khi HTTP thành công.
2. **Prompt**: đã tạo rồi thì prompt ghi rõ "không gọi `create_booking` nữa".
3. **Tool tự chặn**: LLM vẫn cố gọi thì tool trả `{"ok":true,"already_created":true}` và **không** `POST` lần hai.

Lớp 3 là lớp thật sự an toàn — prompt là gợi ý, code là luật.

---

## 8. Đóng luồng sau câu chốt

### 8.1 Vấn đề

Sau khi câu chốt phát xong, AI nên tự kết thúc. Nhưng **không được đóng socket ngay khi frame PCM cuối
rời khỏi server**.

Lý do nằm ở frontend:

```59:65:frontend/src/playback.ts
    const now = this.context.currentTime;
    if (this.nextTime < now + LEAD_SECONDS) {
      this.nextTime = now + LEAD_SECONDS;
    }
    source.start(this.nextTime);
    this.nextTime += buffer.duration;
    this.queuedSeconds = Math.max(0, this.nextTime - now);
```

`PcmPlayer` xếp audio vào tương lai (lead 60 ms) và có thể còn vài trăm ms trong queue. Khi socket đóng,
`onClose` → `endCall(false)` → `player.interrupt()` → `**source.stop()` cho mọi node đang chờ**. Kết quả:
khách nghe "Em đã đặt xong bàn cho anh tại chi nh—" *cạch*.

Đây là loại bug rất khó chẩn đoán qua log, vì phía server mọi thứ đều "đã gửi thành công".

### 8.2 Giải pháp: grace period tính theo byte đã gửi

`OutboundGate` đếm thêm hai giá trị:

```python
class OutboundGate:
    def __init__(self, websocket, session):
        ...
        self.bytes_sent = 0
        self.first_frame_at: float | None = None

    async def send_audio(self, generation_id: int, pcm: bytes) -> bool:
        ...
        async with self.lock:
            if self.session.closed or self.session.generation_id != generation_id:
                return False
            await self.websocket.send_bytes(pcm)
            if self.first_frame_at is None:
                self.first_frame_at = time.monotonic()
            self.bytes_sent += len(pcm)
            self.session.mark_audio_sent()
            return True
```

Thời gian còn phải chờ:

```python
BYTES_PER_SECOND = 32_000     # 16 kHz × 1 channel × 2 byte
LEAD_SECONDS = 0.06           # khớp LEAD_SECONDS của PcmPlayer

def remaining_playback_seconds(gate, grace_ms: int) -> float:
    if gate.first_frame_at is None:
        return 0.0
    audio_seconds = gate.bytes_sent / BYTES_PER_SECOND
    elapsed = time.monotonic() - gate.first_frame_at
    return max(0.0, audio_seconds - elapsed) + LEAD_SECONDS + grace_ms / 1000
```

Trực giác: ta đã gửi `bytes_sent` byte, tương đương `audio_seconds` giây tiếng. Đã trôi `elapsed` giây từ
frame đầu. Phần chưa phát là hiệu số. Cộng lead của player và một margin (`CALL_END_GRACE_MS`, mặc định
300 ms) cho jitter mạng.

Công thức này **ước lượng dư an toàn**: nếu mạng chậm làm frame đến muộn, `elapsed` lớn hơn thực tế đã
phát, nên ta chờ *ít* hơn cần thiết. Đó là lý do phải có margin. Muốn chắc chắn hơn thì để client gửi
ack "đã phát xong" — nhưng như thế phải sửa frontend, mà yêu cầu là giữ nguyên frontend.

### 8.3 Trình tự đóng

```
1) TurnPlayer.finish()          — mọi câu đã synth xong và đã gửi hết
2) Kiểm tra điều kiện kết thúc  — booking_created hoặc order_created, và
                                  LLM vừa nói câu chốt (không còn slot nào cần hỏi)
3) send_json({"event":"call.end","reason":"completed","callId":…})    (tùy chọn)
4) grace = remaining_playback_seconds(outbound, CALL_END_GRACE_MS)
   await asyncio.sleep(grace)          ← trong lúc này VẪN nghe khách (§8.4)
5) await websocket.close(code=1000, reason="completed")
6) shutdown()                   — đóng STT, cancel task, giải phóng session
```

Frontend **không cần sửa** một dòng: `onClose` đã dừng mic và hiện "Đã cúp". Nếu muốn UI đẹp hơn thì thêm
nhánh `call.end` trong `frontend/src/bridge.ts` để đổi status trước khi socket đóng — thuần cosmetic.

### 8.4 Khách nói tiếp trong lúc chờ

Trong `grace`, nếu VAD bắn `speech_started` thì **hủy đóng máy**:

```python
self._hangup_task = asyncio.create_task(self._hangup_after_playback())

# trong on_speech_started() VÀ trong on_dtmf(), trước khi barge-in:
if self._hangup_task is not None and not self._hangup_task.done():
    self._hangup_task.cancel()
    self._hangup_task = None
    logger.info("Hủy cúp máy: khách còn muốn nói tiếp %s", self.session.tag)
```

Không có nhánh này thì khách hỏi thêm "À em ơi, có chỗ đậu xe không?" ngay sau câu cảm ơn sẽ bị cúp giữa
câu. Đây là trải nghiệm tệ nhất trong toàn hệ thống, vì khách không biết mình bị cúp hay máy hỏng.

**Phím cũng hủy cúp máy, không chỉ giọng nói.** Khách vừa đặt bàn xong, nghe câu cảm ơn rồi ấn `3` để đặt
món giao tận nơi — cúp máy lúc đó là mất hẳn một đơn hàng. Vì thế `on_dtmf()` phải hủy `_hangup_task`
giống hệt `on_speech_started()` (§7.1.8).

### 8.5 Khi nào **không** đóng

- `create_booking` / `create_order` trả lỗi → **không** đóng. Còn phải xin lỗi và đề xuất phương án khác (§10).
- Khách đặt bàn xong nhưng chưa xong đơn món (hoặc ngược lại) → chưa đóng. Cuộc gọi có thể làm cả hai; prompt đã cho phép.
- Khách còn câu hỏi → chưa đóng.
- Khách ấn phím trong lúc chờ cúp → **không** đóng, mở nhánh dịch vụ theo phím vừa ấn (§7.1.8).

Điều kiện đóng nên **hẹp và rõ**: đã tạo được ít nhất một đơn, LLM vừa phát câu chốt, và không có tool
call nào đang chờ. Thà không cúp (client tự cúp như v1) hơn là cúp sai lúc.

---

## 9. Snapshot isolation

### 9.1 Luật

Đọc Redis **một lần duy nhất** lúc `session.init`, giữ trong `CallSession` của riêng cuộc gọi đó. Sync nền
cập nhật Redis giữa cuộc gọi thì **không** được sửa system prompt đang chạy.

### 9.2 Vì sao — ví dụ hỏng cụ thể

```
t0   Cuộc gọi bắt đầu. Snapshot: [Quận 1, Quận 3, Hà Nội]
t1   AI: "Mình có chi nhánh Quận 1, Quận 3 và Hà Nội. Anh muốn đặt ở đâu ạ?"
t2   Syncer swap cache: Quận 3 vừa bị đóng. Giờ chỉ còn [Quận 1, Hà Nội]
t3   Khách: "Quận 3 nhé."
     ── NẾU prompt bị refresh theo cache mới ──
     resolve_branch("Quận 3") → none
     AI: "Dạ mình không có chi nhánh ở Quận 3."
     ⇒ AI vừa tự phủ định câu nó nói 20 giây trước. Khách nghĩ AI bị lỗi,
       hoặc tệ hơn, nghĩ mình bị lừa.
```

Với snapshot isolation, cuộc gọi này vẫn dùng `[Quận 1, Quận 3, Hà Nội]` tới lúc kết thúc. Nếu Quận 3 đã
đóng thật, `POST` sẽ bị backend từ chối, và ta xử lý bằng câu xin lỗi có ngữ cảnh (§10) — nghe hợp lý hơn
nhiều: "Dạ chi nhánh Quận 3 vừa hết chỗ ạ, anh chuyển sang Quận 1 được không?"

**Backend là nơi validate cuối.** AI chỉ cần nhất quán với chính nó.

### 9.3 Checklist thực thi


| Việc                                                                                                             | Vì sao                                                    |
| ---------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------- |
| `CallSession.branches` là bản copy (`list(restaurant.branches)`), không phải reference vào object cache          | Cache swap không được sửa dữ liệu cuộc gọi đang chạy      |
| `Branch`, `Restaurant`, `MenuItem` là `@dataclass(frozen=True)`                                                  | Immutable — không ai sửa được nhầm, kể cả code tool       |
| `refresh_system_prompt()` **chỉ** gọi khi state cuộc gọi đổi (chọn chi nhánh, đổi giỏ, đổi intent, tạo xong đơn) | Không bao giờ refresh vì cache đổi                        |
| `CACHE_GENERATION_TTL` dài hơn cuộc gọi dài nhất                                                                 | Generation không bị hết hạn giữa cuộc gọi                 |
| `branch_id` đã chốt vẫn dùng để `POST` dù backend đã đóng chi nhánh                                              | Backend từ chối thì xử theo §10, không tự đoán trước      |
| Đọc `pointer` một lần, cache lại trong session                                                                   | Đọc menu ở lượt thứ 5 vẫn phải cùng generation với lượt 1 |


Điểm cuối quan trọng và dễ quên: menu được lấy **lazy** (khi khách hỏi món), tức là sau `session.init` khá
lâu. Nếu lúc đó mới `GET pointer` thì có thể ra generation khác với generation của danh mục chi nhánh. Vì
thế `CallSession` phải giữ generation đã chọn, và mọi lần đọc cache sau đó đều dùng nó.

---

## 10. Xử lý lỗi

### 10.1 Luật vàng

> **Không bao giờ nói "đã đặt xong" khi tool chưa trả `ok: true`.**

Đây là lỗi tệ nhất có thể xảy ra: khách tin là có bàn, đến quán thì không có gì. Ba lớp bảo vệ ở §7.6
tồn tại vì lý do này.

### 10.2 Tool không được raise

Mọi tool trả về **JSON có `ok`**, kể cả khi hỏng. `BookingTools.execute()` đã bọc `try/except` tổng và trả
`{"ok": false, "error": "tool_failed"}`. Giữ nguyên nguyên tắc đó cho code mới: exception lọt lên
`stream_sentences` sẽ giết cả lượt, khách nghe im lặng hoàn toàn — không có gì tệ hơn im lặng trong cuộc gọi.

### 10.3 Bảng lỗi → câu nói


| Tình huống          | `error`                        | AI nên nói                                                                                               |
| ------------------- | ------------------------------ | -------------------------------------------------------------------------------------------------------- |
| Hết bàn / quá tải   | `full` hoặc message từ backend | "Dạ chi nhánh này đang hết bàn giờ đó, anh muốn đổi giờ hay sang chi nhánh khác ạ?"                      |
| Món hết hàng        | `sold_out`                     | "Dạ món đó vừa hết ạ, em đổi sang… được không?"                                                          |
| Thiếu field         | `missing_fields` + `fields[]`  | Hỏi đúng mục còn thiếu, **bằng lời thường**. Không đọc "booking_time"                                    |
| `party_size` sai    | `invalid_party_size`           | "Dạ mình cho em biết mấy người ạ?"                                                                       |
| Network / timeout   | `network`                      | "Dạ hệ thống em đang chậm, anh giữ máy một chút…" rồi thử lại **đúng một lần**                           |
| Hotline không map   | `no_restaurant`                | Nói không tra được chi nhánh, **không bịa địa điểm**. Prompt đã có nhánh này trong `build_system_prompt` |
| Chi nhánh chưa khóa | `no_branch`                    | Quay lại hỏi chi nhánh                                                                                   |
| `branch_id` lạ      | `unknown_branch`               | Hỏi lại chi nhánh, nêu tên thật từ `available_branches`                                                  |
| Đã tạo rồi          | `already_created`              | "Dạ đơn của anh em đã ghi rồi ạ." Không tạo lần hai                                                      |
| Ấn phím không hợp lệ | (không phải lỗi tool)         | Đọc lại menu ngắn, tối đa 2 lần, rồi chuyển sang hỏi bằng lời (§7.1.3)                                   |


Trong mọi trường hợp lỗi: **giữ nguyên các slot đã thu**. Khách không bao giờ phải khai lại tên và số
điện thoại chỉ vì backend lỗi. Đây là lý do `save_order_details` được gọi ngay khi khách nêu, không chờ
tới lúc tạo đơn.

### 10.4 Ma trận retry


| Thao tác                      | Retry?                | Cách                                                                               |
| ----------------------------- | --------------------- | ---------------------------------------------------------------------------------- |
| `GET /restaurants/by-hotline` | Có, 1 lần             | Đã có: `await asyncio.sleep(0.8)` giữa hai lần thử                                 |
| `GET /menu/branch/{id}`       | Có, 1 lần             | Đọc, an toàn khi lặp                                                               |
| `GET /api/v1/sync/*`          | Có, backoff nhân đôi  | Luồng nền, không ai chờ                                                            |
| `POST /bookings/ai`           | **Không** retry blind | Đã có fallback sang `POST /bookings` — đó là *fallback endpoint*, không phải retry |
| `POST /menu/*/ai`             | **Không**             | Nguy cơ đơn kép                                                                    |


Lý do không retry `POST`: timeout **không** có nghĩa là request thất bại. Có thể backend đã ghi đơn rồi
mới đứt kết nối. Retry là tạo hai bàn cho một khách. Đúng cách là trả lỗi cho LLM, để nó hỏi khách, và
nếu cần thì để nhân viên kiểm tra. Muốn retry an toàn thì backend phải hỗ trợ idempotency key (ví dụ nhận
`callId` làm khóa chống trùng) — chưa có thì đừng retry.

### 10.5 Lỗi ở tầng cache


| Lỗi                                     | Xử lý                                                                  | Có ảnh hưởng cuộc gọi? |
| --------------------------------------- | ---------------------------------------------------------------------- | ---------------------- |
| Redis connect thất bại lúc startup      | Log `ERROR`, `catalog_cache = None`                                    | Không. Chạy như v1     |
| Redis timeout lúc đọc                   | Log `WARNING`, coi như miss, rơi về HTTP                               | Không, chỉ chậm hơn    |
| `pointer` trỏ vào generation đã hết hạn | Coi như miss, rơi về HTTP; log `WARNING` (dấu hiệu TTL quá ngắn)       | Không                  |
| JSON trong Redis parse lỗi              | Coi như miss, log `ERROR` (dấu hiệu format đổi mà chưa bump namespace) | Không                  |
| Backend trả payload sai cấu trúc        | Không swap, giữ generation cũ, log `ERROR`                             | Không                  |


Toàn bộ bảng này chỉ có một cột "Không" — đó chính là tiêu chí thiết kế. Nếu có tình huống cache lỗi mà
làm cuộc gọi hỏng, thiết kế sai chỗ đó.

---

## 11. VAD và barge-in

### 11.1 Vì sao đây là phần tinh tế nhất

Barge-in là chỗ khách **sửa ý định**, tức là chỗ thông tin quan trọng nhất xuất hiện:

> AI: "Anh đặt ở Cầu Giấy…" — Khách chen: "À không, chuyển qua Quận 1 cho anh."

Nếu AI nói tiếp trong lúc khách nói, hai giọng đè nhau và STT nghe cả hai (nếu mic không có echo
cancellation tốt) → transcript rác → AI hiểu sai. Nếu AI im nhưng vẫn "nhớ" là mình đã nói hết câu, history
lệch với thực tế khách nghe → AI tưởng đã xác nhận Cầu Giấy.

### 11.2 Trình tự bắt buộc

Đúng thứ tự trong `turn/barge_in.py` (hợp đồng §6.3):

```76:93:turn/barge_in.py
async def abort_and_interrupt(
    *,
    session: SessionLike,
    outbound: OutboundGate,
    abort_work: Callable[[], Awaitable[None] | None],
) -> int:
    """Run the required barge-in sequence and return the new generation_id.

    1. Bump generation_id so in-flight LLM/TTS become stale.
    2. Do not send any more audio of the aborted turn.
    3. Send interrupt after the last binary frame already sent.
    4. Cancel local work *after* releasing the send lock (must not take it).
    5. Caller keeps appending user PCM to STT.
    """
    async with outbound.lock:
        session.generation_id += 1
        session.playing = False
        session.state = "BargeIn"
```

Giải thích từng bước:

1. **Lấy `outbound.lock` trước.** Đây là điểm cốt lõi. Lock này serialize mọi lần gửi. Khi barge-in giữ được lock, mọi frame audio *đã đưa cho writer* đều đã ra khỏi socket, và **không frame stale nào có thể chen vào sau**.
2. `**generation_id += 1`.** Mọi `should_abort()` trong LLM stream và TTS task lập tức trả `True`. `send_audio()` với generation cũ trả `False` và audio bị bỏ.
3. **Gửi `interrupt` *trong* lock.** Nếu gửi ngoài lock, một frame audio của lượt cũ có thể ra sau `interrupt` → client đã xóa queue rồi lại nhận thêm tiếng của câu vừa bị hủy.
4. `**commit_partial_assistant()**` — ghi vào history **đúng phần đã phát**, không phải toàn bộ câu đã synth. LLM phải biết khách nghe được tới đâu.
5. **Nhả lock rồi mới cancel task local.** `abort_work()` không được lấy lại lock — sẽ deadlock.
6. **Tiếp tục append PCM khách vào STT.** Không mất một frame nào; câu khách đang nói phải nguyên vẹn.

### 11.3 Ai kích hoạt barge-in

`on_speech_started()` chỉ barge-in khi AI đang chiếm lượt:

```484:493:bridge/session.py
    async def on_speech_started(self) -> None:
        async with self._turn_lock:
            if self.session.closed or self.session.state in (CallState.CLOSED, CallState.BARGE_IN, CallState.LISTENING):
                return
            if (
                self.session.state in (CallState.GREETING, CallState.THINKING, CallState.SPEAKING)
                or self.session.playing
                or (self._work_task is not None and not self._work_task.done())
            ):
                await self._barge_in()
```

Ba điều kiện `or` là ba trạng thái "AI đang chiếm lượt": đang nói (`GREETING`/`SPEAKING`), đang suy nghĩ
(`THINKING` — chưa ra tiếng nhưng LLM đang chạy, phải hủy), hoặc còn task nền chưa xong. Ở `LISTENING` thì
khách nói là bình thường, không phải chen ngang.

`on_transcript_completed()` cũng kiểm tra `busy` và barge-in nếu cần — bắt trường hợp `speech_started` bị
mất (mạng, hoặc VAD fallback không phát sự kiện đó).

Ở v2 có **nguồn kích hoạt thứ ba**: event `dtmf`. Khách ấn phím giữa lúc AI đọc menu là chuyện thường
xuyên, và phải xử lý ngay chứ không chờ VAD. Chi tiết ở §7.1.6 — dùng lại đúng `abort_and_interrupt()`,
chỉ khác ở chỗ không cần transcript.

### 11.4 Ràng buộc kèm theo


| Ràng buộc                                                            | Vì sao                                                                                                 |
| -------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| Client nhận `interrupt` phải xóa queue audio                         | `PcmPlayer.interrupt()` đã đúng. Không xóa thì AI vẫn nói tiếp vài trăm ms sau khi bị ngắt             |
| Chỉ commit phần **đã phát**, không commit câu đã synth mà chưa gửi   | History phải khớp với những gì khách thực sự nghe                                                      |
| Slot đã khóa vẫn ghi đè được                                         | Khách đổi chi nhánh sau `confirm_branch` → `select_branch()` reset `menu` và `cart`, giữ các slot khác |
| Đang trong grace chờ cúp máy mà nghe tiếng khách → hủy cúp           | §8.4                                                                                                   |
| Event `dtmf` cũng phải đi qua `_turn_lock` và `outbound.lock`         | Phím và giọng đến cùng lúc không được chạy hai lượt song song (§7.1.6)                                |
| `_turn_lock` bọc cả `on_speech_started` và `on_transcript_completed` | Hai sự kiện đến gần nhau không được chạy hai lượt song song                                            |


### 11.5 Chỗ tinh chỉnh

`silence_duration_ms` là núm xoay quan trọng nhất:


| Giá trị               | Hệ quả                                                                                            |
| --------------------- | ------------------------------------------------------------------------------------------------- |
| 300 ms                | Rất nhanh, nhưng AI ngắt lời khách giữa câu khi họ ngừng để suy nghĩ ("Cho tôi… ừm… bàn 4 người") |
| **450 ms** (hiện tại) | Cân bằng, hơi nghiêng về nhanh                                                                    |
| 700–800 ms            | An toàn cho người nói chậm; cảm giác AI "chậm hiểu"                                               |


Nếu phản hồi từ người dùng thật là "AI cắt lời tôi", đây là chỗ sửa đầu tiên, không phải prompt.

---

## 12. Cấu hình

Thêm vào `config.py` và `.env.example`:


| Biến                       | Mặc định                   | Ý nghĩa                                                                                          |
| -------------------------- | -------------------------- | ------------------------------------------------------------------------------------------------ |
| `REDIS_URL`                | `redis://127.0.0.1:6379/0` | Trống → chạy không cache (đúng như v1)                                                           |
| `REDIS_NAMESPACE`          | `aibridge`                 | Prefix key. Tách dev/staging/prod trên cùng Redis. **Bump khi đổi format JSON trong cache**      |
| `SYNC_ENABLED`             | `true`                     | `false` để tắt hẳn luồng nền (dev, test, hoặc tắt nhanh khi sự cố)                               |
| `SYNC_POLL_SECONDS`        | `300`                      | Chu kỳ `check-version`. 5 phút là hợp lý cho dữ liệu đổi vài lần/tháng                           |
| `SYNC_TIMEOUT`             | `10`                       | Timeout HTTP của **luồng sync**. Khác timeout 30 s của luồng cuộc gọi — sync không được treo lâu |
| `SYNC_API_BASE`            | = `RESTAURANT_API_BASE`    | Cho phép trỏ sync sang host nội bộ, nhanh hơn public URL                                         |
| `SYNC_MAX_BACKOFF_SECONDS` | `2400`                     | Trần backoff (40 phút) khi backend lỗi liên tục                                                  |
| `CACHE_GENERATION_TTL`     | `10800`                    | TTL generation (3 giờ). **Phải dài hơn cuộc gọi dài nhất**                                       |
| `CACHE_TTL_SECONDS`        | `600`                      | TTL entry write-through ở degrade mode                                                           |
| `CALL_END_GRACE_MS`        | `300`                      | Margin cộng vào thời gian chờ trước khi đóng socket                                              |
| `DTMF_MENU_TIMEOUT_SECONDS` | `7`                       | Chờ khách ấn phím, đếm từ lúc menu phát **xong**. Hết giờ → hỏi bằng lời (§7.1.5)                |
| `DTMF_DEBOUNCE_MS`         | `500`                      | Bỏ qua cùng một phím ấn lặp trong khoảng này (§7.1.7)                                            |
| `DTMF_MAX_INVALID`         | `2`                        | Số lần đọc lại menu khi khách ấn phím sai, trước khi chuyển sang hỏi bằng lời                    |


Biến v1 giữ nguyên: `OPENAI_API_KEY`, `OPENAI_MODEL`, `OPENAI_STT_MODEL`, `OPENAI_TTS_MODEL`,
`OPENAI_TTS_VOICE`, `TTS_CHUNK_BYTES`, `AI_BRIDGE_TOKEN`, `AI_BRIDGE_HOST`, `AI_BRIDGE_PORT`,
`LOG_LEVEL`, `RESTAURANT_API_BASE`.

`requirements.txt` thêm:

```
redis>=5.0.0        # client asyncio nằm trong redis.asyncio, KHÔNG cần aioredis
fakeredis>=2.0.0    # chỉ cho test, hoặc tự viết fake in-memory
```

---

## 13. Kế hoạch code

### 13.1 File

```
phone_call_project/
|-- cache/
|   |-- __init__.py
|   `-- redis_store.py       # MỚI  CatalogCache: get/put restaurant+menu, swap_generation, stats
|-- sync/
|   |-- __init__.py
|   |-- models.py            # MỚI  SyncPayload + parser cho /api/v1/sync/branches
|   `-- poller.py            # MỚI  CatalogSyncer: warm_once, run_forever, backoff, leader lock
|-- bridge/
|   |-- server.py            # SỬA  lifespan, /health mở rộng, truyền cache vào CallPipeline
|   |-- protocol.py          # SỬA  EVENT_CALL_END, EVENT_DTMF, SERVICE_BY_DIGIT, DtmfDigit
|   `-- session.py           # SỬA  _load_catalog 3 bậc; hangup sau câu chốt; hủy hangup khi khách nói;
|                            #      service_choice + on_dtmf + timeout menu
|-- llm/
|   `-- stream.py            # SỬA  SERVICE_MENU_VI/EN; build_system_prompt nhận service_choice
|-- order/
|   `-- tools.py             # SỬA  list_menu/search_menu đọc cache trước
|-- turn/
|   `-- barge_in.py          # SỬA  OutboundGate đếm bytes_sent, first_frame_at
|-- config.py                # SỬA  biến ở §12
|-- requirements.txt         # SỬA  redis, fakeredis
|-- frontend/
|   |-- index.html           # SỬA  khối keypad 3 nút
|   `-- src/
|       |-- protocol.ts      # SỬA  EVENT_DTMF + type payload
|       |-- bridge.ts        # SỬA  sendDtmf()
|       |-- main.ts          # SỬA  handler nút, phím tắt 1/2/3, trạng thái aria-pressed
|       `-- styles.css       # SỬA  style keypad
`-- tests/
    |-- test_catalog_cache.py  # MỚI
    |-- test_sync_poller.py    # MỚI
    |-- test_call_end.py       # MỚI
    `-- test_dtmf.py           # MỚI
```

### 13.2 Thứ tự làm

Mỗi bước tự chạy được, tự test được, và **không phá v1**. Không nhảy bước.


| Bước | Việc                                                                               | Xong khi                                                                                                                          |
| ---- | ---------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| 1    | `cache/redis_store.py` + test với fake in-memory. **Chưa** nối vào server          | Test pass: swap generation, pointer lật đúng, reader thấy dữ liệu nhất quán, TTL được set                                         |
| 2    | `sync/models.py` + `sync/poller.py` + test với `httpx.MockTransport`. **Chưa** nối | Test pass: version không đổi → không ghi; đổi → swap; 404 → degraded; lỗi → backoff nhân đôi có trần; `CancelledError` thoát sạch |
| 3    | `lifespan` trong `bridge/server.py`, `/health` mở rộng                             | Server lên được với `REDIS_URL` sai; `SYNC_ENABLED=false` chạy đúng như v1; `/health` trả block `cache`                           |
| 4    | `_load_catalog` 3 bậc + menu đọc cache. **Bước duy nhất chạm luồng cuộc gọi**      | Test cũ vẫn pass nguyên; test mới: cache hit không gọi HTTP, cache miss có gọi HTTP và write-through                              |
| 5    | `OutboundGate` đếm byte; hangup sau câu chốt; hủy hangup khi khách nói             | Test: grace tính đúng theo byte; `speech_started` trong grace hủy được cúp máy; lỗi `POST` thì **không** cúp                      |
| 6    | Menu phím: `EVENT_DTMF` + `on_dtmf` + `service_choice` + prompt + timeout          | Test: phím 1/2/3 set đúng intent/fulfillment; phím giữa lúc đọc menu gửi `interrupt`; phím sai đọc lại menu; timeout rơi về hỏi bằng lời; phím sau khi tạo đơn bị bỏ |
| 7    | Keypad frontend + `sendDtmf`                                                        | Ấn nút khi đang gọi thì AI im ngay và trả lời đúng nhánh; phím tắt không bắn khi đang focus ô text; nút disable khi chưa gọi |


Bước 1–3 hoàn toàn không chạm luồng cuộc gọi, nên deploy được sớm và quan sát cache warm trước khi để cuộc
gọi thật dựa vào nó. Đây là cách giảm rủi ro: khi tới bước 4, ta đã biết cache đúng.

Bước 6 và 7 độc lập hoàn toàn với 1–5 (không liên quan cache), nên làm song song được nếu có hai người.
Nhưng **6 phải xong trước 7**: keypad gửi event mà server chưa hiểu thì chỉ nhận được log `WARNING`.

---

## 14. Test

`pytest` hiện tại chạy **không cần key OpenAI** (fake STT/LLM/TTS trong `tests/fakes.py`). Giữ đúng tính
chất đó — test cần key hoặc cần mạng là test sẽ bị bỏ chạy, rồi thành vô dụng.


| Nguyên tắc                          | Cách làm                                                                |
| ----------------------------------- | ----------------------------------------------------------------------- |
| Không test nào cần Redis thật       | `fakeredis`, hoặc tự viết class implement đúng interface `CatalogCache` |
| Không test nào gọi mạng             | `httpx.MockTransport` cho `CatalogSyncer`                               |
| Không test nào cần `sleep` thật dài | Inject `interval` nhỏ, hoặc inject hàm `sleep` giả                      |


Test mới cần có:

`**test_catalog_cache.py**`

- `swap_generation` ghi đủ key, set TTL, lật pointer **sau** khi ghi xong.
- Reader giữ generation cũ vẫn đọc được đầy đủ sau khi swap (đây là test snapshot isolation ở tầng cache).
- JSON lỗi → trả `None`, không raise.
- `put_restaurant` write-through dùng TTL ngắn, không phá generation.

`**test_sync_poller.py**`

- Version không đổi → **không** có lệnh ghi nào.
- Version đổi → swap đúng payload mới.
- `check-version` trả 404 → `degraded = True`, không crash.
- Lỗi network liên tiếp → delay nhân đôi, chạm trần thì dừng tăng.
- `warm_once` thất bại → không raise ra ngoài lifespan.
- `task.cancel()` → thoát sạch, không treo.

`**test_call_end.py**`

- Grace tính đúng: gửi N byte → chờ ≈ N/32000 giây (+ lead + margin).
- `speech_started` trong grace → hủy cúp máy, quay lại `LISTENING`.
- `create_booking` lỗi → **không** cúp máy.
- Socket đóng với code `1000` và `shutdown()` được gọi.

`**test_dtmf.py**`

- Phím `1` → `intent="booking"`; phím `2` → `intent="order"`, `fulfillment="pickup"`; phím `3` → `fulfillment="delivery"`.
- Phím đến giữa lúc đang phát menu → `generation_id` tăng, có gửi `{"event":"interrupt"}`, và `interrupt` đi **sau** frame audio cuối.
- Phím sai (`7`) → không đổi state, `invalid_digit_count` tăng, AI đọc lại menu; lần thứ ba thì `awaiting_choice=False`.
- Cùng một phím ấn hai lần trong `DTMF_DEBOUNCE_MS` → chỉ xử lý một lần.
- Đổi phím trước khi tạo đơn → intent đổi, tên và SĐT đã thu **vẫn còn**.
- Phím `3` sau khi `booking_created=True` → `intent="order"`, `fulfillment="delivery"`, và tên/SĐT/chi nhánh **vẫn còn** (§7.1.8).
- Phím `1` sau khi `booking_created=True` → **không** `POST` lần hai; `create_booking` trả `already_created`.
- Phím trong lúc chờ cúp máy → `_hangup_task` bị hủy, socket **không** đóng.
- Timeout: không ấn phím → sau `DTMF_MENU_TIMEOUT_SECONDS` thì `awaiting_choice=False` và prompt quay về bản hỏi bằng lời.
- Khách **nói** thay vì ấn khi `awaiting_choice=True` → transcript vẫn được xử lý bình thường.
- `{"event":"dtmf","digit":"12"}` và `digit` rỗng → bỏ qua, không crash.

**Test hồi quy** (quan trọng nhất, vì đây là chỗ dễ vô tình phá v1):

- `REDIS_URL` sai → server vẫn lên, cuộc gọi vẫn đặt bàn được qua HTTP fallback.
- `SYNC_ENABLED=false` → hành vi giống v1 từng bit.
- Client **không** gửi `dtmf` bao giờ → luồng hỏi loại dịch vụ bằng lời vẫn hoạt động đầy đủ.
- **Snapshot isolation ở tầng session**: cache swap giữa cuộc gọi → `history[0]["content"]` (system prompt) của cuộc gọi đó **không đổi**.

---

## 15. Vận hành và gỡ lỗi

### 15.1 Chạy local

```powershell
# 1. Redis (Docker)
docker run -d --name aibridge-redis -p 6379:6379 redis:7-alpine

# 2. AI Bridge
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env      # điền OPENAI_API_KEY, AI_BRIDGE_TOKEN, REDIS_URL
python app.py

# 3. Frontend (terminal khác)
cd frontend
copy .env.example .env      # VITE_AI_BRIDGE_TOKEN trùng AI_BRIDGE_TOKEN
npm install
npm run dev
```

Không có Redis cũng chạy được: để `REDIS_URL` trống hoặc `SYNC_ENABLED=false`.

### 15.2 Kiểm tra cache bằng redis-cli

```bash
redis-cli GET  aibridge:catalog:pointer                        # → "g7"
redis-cli GET  aibridge:catalog:g7:version
redis-cli TTL  aibridge:catalog:g7:hotline:1900636886          # còn bao nhiêu giây
redis-cli KEYS "aibridge:catalog:g7:*"                         # chỉ dùng khi debug, KEYS chặn Redis
redis-cli --scan --pattern "aibridge:catalog:g7:*"             # an toàn hơn KEYS
```

### 15.3 Bảng triệu chứng → nguyên nhân


| Triệu chứng                         | Nguyên nhân khả năng cao                                                          | Kiểm tra                                                                                              |
| ----------------------------------- | --------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| Câu chào chậm vài giây              | Cache miss, đang đi HTTP                                                          | `/health` → `cache.ready`; log có `Hotline lookup` không                                              |
| AI nói "không tra được chi nhánh"   | `toNumber` không map, hoặc restaurant `status != active`                          | `redis-cli GET aibridge:catalog:g7:hotline:<digits>`; kiểm tra `toNumber` trong `session.init`        |
| Câu cuối bị cắt cụt                 | Grace quá ngắn, hoặc đóng socket trước khi audio phát hết                         | Tăng `CALL_END_GRACE_MS`; kiểm tra `bytes_sent` trong log                                             |
| AI ngắt lời khách                   | `silence_duration_ms` quá thấp                                                    | Nâng lên 600–800 ms                                                                                   |
| AI nói tiếp sau khi bị ngắt         | `interrupt` gửi ngoài lock, hoặc client không xóa queue                           | Xem thứ tự ở §11.2; kiểm tra `PcmPlayer.interrupt()` được gọi                                         |
| AI đọc địa chỉ khi kể tên chi nhánh | Địa chỉ lọt vào khối prompt sai                                                   | Kiểm tra `_catalog_lines` (chỉ tên) và `_catalog_addresses_private` (khối riêng, có cảnh báo cấm đọc) |
| Cache không cập nhật                | Backend `check-version` trả version cũ, hoặc syncer đang backoff, hoặc `degraded` | `/health` → `last_sync_at`, `last_sync_error`, `degraded`                                             |
| Đơn bị tạo hai lần                  | Có retry `POST` ở đâu đó                                                          | §10.4 — tuyệt đối không retry `POST`                                                                  |
| Sau deploy AI nói dữ liệu cũ        | `REDIS_NAMESPACE` chưa bump khi đổi format JSON                                   | Bump namespace, hoặc `POST /internal/sync/refresh`                                                    |
| Ấn phím nhưng AI vẫn đọc tiếp menu  | Client không gọi `player.interrupt()` local, hoặc server không nhận `dtmf`        | Log server có `dtmf digit=` không; kiểm tra `EVENT_DTMF` khớp hai phía                                |
| Ấn phím nhưng AI vẫn hỏi lại loại dịch vụ | `refresh_system_prompt()` chưa gọi sau `apply_service_choice()`             | In `history[0]["content"]`, xem còn khối "đặt bàn hay mang về" không                                  |
| Gõ số điện thoại vào form thì AI đổi dịch vụ | Phím tắt 1/2/3 không loại trừ `input`/`textarea`                       | Kiểm tra `event.target` trong handler keydown (§7.1.10)                                                |
| AI đọc menu xong rồi im luôn        | Timeout menu chưa hẹn, hoặc hẹn từ lúc bắt đầu đọc nên đã nổ mất                  | Xác nhận timeout hẹn trong `TurnPlayer.finish()` của lượt greeting (§7.1.5)                           |


### 15.4 Chỉ số nên theo dõi


| Chỉ số                                                               | Ngưỡng báo động                                |
| -------------------------------------------------------------------- | ---------------------------------------------- |
| Tỉ lệ cache hit lúc `session.init`                                   | < 90% → kiểm tra `hotlines` trong payload sync |
| Thời gian từ transcript cuối → frame audio đầu                       | p95 > 2.5 s                                    |
| `last_sync_error` khác `null` liên tục                               | > 30 phút                                      |
| Số lần `POST` tạo đơn thất bại                                       | Tăng bất thường → backend có vấn đề            |
| Số lần chạm `_MAX_TOOL_ROUNDS`                                       | > 0 → prompt đang lặp vòng                     |
| Số cuộc gọi cúp máy mà `booking_created`/`order_created` đều `false` | Cao → điều kiện đóng luồng quá rộng            |
| Tỉ lệ khách ấn phím so với nói                                       | < 50% → menu đọc quá dài hoặc quá nhanh        |
| Tỉ lệ ấn phím sai                                                    | Cao → nhãn lựa chọn chưa rõ                    |
| Tỉ lệ timeout menu, rơi về hỏi bằng lời                              | Cao → `DTMF_MENU_TIMEOUT_SECONDS` quá ngắn     |


---

## Liên quan

- [documents/ai-pipeline.md](documents/ai-pipeline.md) — spec audio, resample, state machine, thứ tự barge-in
- [documents/backend_contract/ai-bridge-contract.md](documents/backend_contract/ai-bridge-contract.md) — wire protocol WebSocket
- [documents/order-api-contract.md](documents/order-api-contract.md) — API menu và đơn hàng
- [README.md](README.md) — cách chạy, biến môi trường v1
- [frontend/README.md](frontend/README.md) — demo browser; v2 chỉ thêm keypad 3 nút (§7.1.10)

