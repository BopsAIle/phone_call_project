# Pipeline S2S — Speech-to-speech, data nhà hàng/menu bơm thẳng vào message

Tài liệu **ý định thiết kế** cho một pipeline thứ hai, chạy song song với cascade
(v1 hiện tại / v2 trong [new_pipeline.md](new_pipeline.md)). Mục tiêu: đọc xong là
hiểu *vì sao*, *bơm data thế nào*, *tool nào còn / bỏ*, và *code sẽ nằm ở đâu* —
chưa implement trong lượt này.

Tài liệu này **không thay** cascade. Hợp đồng WebSocket với frontend / backend điện
thoại **không đổi**.

Bổ sung, không thay thế:

- [documents/ai-pipeline.md](documents/ai-pipeline.md) — spec audio, resample, barge-in
- [documents/backend_contract/ai-bridge-contract.md](documents/backend_contract/ai-bridge-contract.md) — wire PCM + JSON
- [new_pipeline.md](new_pipeline.md) — cascade v2 (Redis, DTMF, hangup)
- [documents/order-api-contract.md](documents/order-api-contract.md) — API menu / đơn

---

## Mục lục

- [0. Một câu tóm tắt](#0-một-câu-tóm-tắt)
- [1. Vì sao thêm pipeline này](#1-vì-sao-thêm-pipeline-này)
- [2. Khác cascade ở chỗ nào](#2-khác-cascade-ở-chỗ-nào)
- [3. Ý tưởng cốt lõi: data là message, không phải tool tra cứu](#3-ý-tưởng-cốt-lõi-data-là-message-không-phải-tool-tra-cứu)
- [4. Sơ đồ](#4-sơ-đồ)
- [5. Model và session Realtime](#5-model-và-session-realtime)
- [6. Bơm data vào cuộc hội thoại](#6-bơm-data-vào-cuộc-hội-thoại)
- [7. Câu chào nguyên văn](#7-câu-chào-nguyên-văn)
- [8. Tool còn lại (chỉ ghi, không đọc catalog)](#8-tool-còn-lại-chỉ-ghi-không-đọc-catalog)
- [9. Đường audio, VAD, barge-in](#9-đường-audio-vad-barge-in)
- [10. State động (giỏ, chi nhánh khóa, intent)](#10-state-động-giỏ-chi-nhánh-khóa-intent)
- [11. Snapshot isolation](#11-snapshot-isolation)
- [12. Hợp đồng frontend — không đổi](#12-hợp-đồng-frontend--không-đổi)
- [13. Chọn pipeline lúc chạy](#13-chọn-pipeline-lúc-chạy)
- [14. Rủi ro và cách giữ an toàn](#14-rủi-ro-và-cách-giữ-an-toàn)
- [15. Kế hoạch code (khi làm)](#15-kế-hoạch-code-khi-làm)
- [16. Test dự kiến](#16-test-dự-kiến)
- [17. Việc cố ý không làm trong pipeline này](#17-việc-cố-ý-không-làm-trong-pipeline-này)

---

## 0. Một câu tóm tắt

Một cuộc gọi = **một session Realtime speech-to-speech** (`gpt-realtime-2.1` hoặc
mini). PCM người gọi vào, PCM agent ra. Lúc `session.init`, ta lấy snapshot nhà
hàng + toàn bộ menu các chi nhánh đang hoạt động, rồi **nhồi vào một message data
đóng băng** — đúng kiểu v1 đang nhồi tên chi nhánh vào system prompt — để model
trả lời "có món gì / chi nhánh nào" **không cần** `search_menu` / `list_menu`.
Tool chỉ còn việc **ghi**: khóa chi nhánh, sửa giỏ, tạo bàn, tạo đơn.

---

## 1. Vì sao thêm pipeline này

Cascade (STT → Chat Completions → TTS) đang đúng với nghiệp vụ: câu chào nguyên
văn, tool chặt, rẻ, từng tầng thay được. [new_pipeline.md §2.1](new_pipeline.md)
nói rõ vì sao v2 **không** chuyển sang S2S.

S2S vẫn đáng có, vì ba lý do cascade không giải được:

1. **Độ trễ cảm nhận.** Cascade cộng VAD + STT cuối + LLM câu đầu + TTS byte đầu
   (~1.3–2.5 s, [new_pipeline.md §2.3](new_pipeline.md)). S2S nghe và nói trên
   cùng một model; âm đầu tiên thường về dưới 500–800 ms sau khi khách ngừng nói.
2. **Giọng tự nhiên hơn.** Không cắt câu ở dấu chấm rồi synth từng khúc `tts-1`.
   Ngắt, ậm ừ, ngữ điệu theo ngữ cảnh nằm trong model.
3. **Hỏi menu / chi nhánh không tốn vòng tool.** Với cascade, "có phở không" bắt
   buộc `search_menu` → matcher LLM phụ → mới nói. Với S2S, món đã nằm trong
   message data; model đọc rồi nói luôn. Đây là chỗ **đổi kiến trúc data**, không
   chỉ đổi model.

Cascade vẫn là mặc định production cho đến khi S2S chứng minh ổn định trên cuộc
gọi thật (câu chào pháp lý, không bịa món, không POST đơn kép).

---

## 2. Khác cascade ở chỗ nào


| Hạng mục                         | Cascade v1 / v2                                              | S2S (pipeline này)                                                                 |
| -------------------------------- | ------------------------------------------------------------ | ---------------------------------------------------------------------------------- |
| Đường tiếng                      | STT Realtime (transcription) → Chat Completions → HTTP TTS   | Một session Realtime **voice-agent** (`session.type = "realtime"`)                 |
| Model nói                        | `tts-1` / `tts-1-hd`                                         | Giọng của `gpt-realtime-2.1` (vd. `marin`)                                         |
| Nhà hàng / chi nhánh vào context | Nhồi vào `history[0]` system prompt (`build_system_prompt`)  | Nhồi vào **một message data** lúc init, đóng băng                                  |
| Menu vào context                 | Lazy: `list_menu` / `search_menu` GET khi khách hỏi          | **Eager:** lấy hết menu chi nhánh active lúc init, nhồi cùng message data          |
| Tool đọc catalog                 | `resolve_branch`, `search_menu`, `list_menu`                 | **Bỏ** `search_menu`, `list_menu`. Khóa chi nhánh vẫn qua tool ghi (validate id)   |
| Tool ghi                         | `add_to_cart`, `create_booking`, `create_order`, …           | Giữ nguyên tập ghi; id món / chi nhánh **phải** thuộc snapshot                     |
| Câu chào disclosure              | TTS nguyên văn                                               | Vẫn TTS nguyên văn (HTTP), rồi mới để S2S nói các lượt sau — xem §7                |
| History LLM                      | `CallSession.history` ta tự giữ                              | OpenAI giữ conversation; ta giữ **bản sao text** (transcript) để log / debug       |
| Barge-in                         | Ta tự `response.cancel` logic + `interrupt` sau audio cuối   | Realtime có `interrupt_response`; ta **vẫn** gửi `{"event":"interrupt"}` đúng hợp đồng |
| Wire `/v1/bridge`                | PCM 16 kHz + `session.init` + `interrupt`                    | **Y nguyên**                                                                       |


Không đụng Redis / DTMF / hangup của v2. Nếu v2 đã có cache, S2S **đọc snapshot
cùng nguồn** lúc init. Nếu chưa có Redis, S2S gọi HTTP như v1 — chỉ là gọi *sớm
và đủ* (nhà hàng + mọi menu), không gọi giữa lượt nói.

---

## 3. Ý tưởng cốt lõi: data là message, không phải tool tra cứu

### 3.1 Cascade đang làm gì với "data"

Trong v1, sau `_load_catalog`, `refresh_system_prompt()` nhồi danh mục vào
`history[0]`:

```python
# llm/stream.py — ý, không copy nguyên prompt
parts.append("Tên chi nhánh được phép đọc:")
parts.append(_catalog_lines(branches))   # chỉ tên
parts.append("Địa chỉ nội bộ — CẤM đọc trừ khi khách hỏi:")
parts.append(_catalog_addresses_private(branches))
```

Menu **không** đi đường đó. Menu vào context gián tiếp qua kết quả tool
`search_menu` / `list_menu`. Mỗi lần khách hỏi món là thêm một vòng LLM + (thường)
một GET HTTP.

### 3.2 S2S làm gì

Cùng một động tác "nhồi text vào đầu hội thoại", nhưng **mở rộng sang menu**, và
tách thành **hai lớp** để không viết đè snapshot khi giỏ hàng đổi:

```
┌─────────────────────────────────────────────────────────────┐
│ session.instructions          ← hành vi + state ĐỘNG         │
│   persona, locale, TZ, luật nói, giỏ hiện tại, chi nhánh khóa│
│   (được session.update khi state đổi)                        │
├─────────────────────────────────────────────────────────────┤
│ conversation item "DATA"      ← snapshot TĨNH, tạo 1 lần     │
│   nhà hàng, chi nhánh, thực đơn từng chi nhánh               │
│   (không bao giờ sửa giữa cuộc gọi)                          │
└─────────────────────────────────────────────────────────────┘
```

Đó là nghĩa của "bơm trực tiếp vào message giống như data ấy":

- **Giống v1:** catalog là text trong message, model đọc chứ không GET lúc đang nói.
- **Khác v1:** menu cũng vào message đó; không còn tool "đi lấy thực đơn".

Tool lúc này giống database write, không giống search.

### 3.3 Vì sao không nhồi hết vào `instructions`

`session.update({ instructions })` sẽ được gọi lại mỗi khi khóa chi nhánh / đổi
giỏ / đổi intent (tương đương `refresh_system_prompt()`). Nếu DATA nằm trong
instructions, mỗi lần update ta phải gửi lại cả thực đơn — tốn token, dễ lệch
snapshot nếu lỡ build từ cache mới.

DATA là `conversation.item.create` một lần. Lần `session.update` sau chỉ gửi
đoạn state ngắn (§10).

Nếu Realtime GA từ chối `role: "system"` trên conversation item (một số phiên bản
chỉ nhận `user` / `assistant`), fallback: ghép DATA vào `instructions` **lần đầu**,
và các lần `session.update` sau chỉ thay phần sau marker `---STATE---` — phần
trước marker (DATA) copy nguyên từ bản đã gửi lúc init, không đọc lại Redis.

---

## 4. Sơ đồ

```
 frontend / backend điện thoại
        │  WS PCM16 16 kHz + session.init   (không đổi)
        ▼
 AI Bridge
        │
        │  session.init
        │     1) TTS greeting nguyên văn → PCM 16k ra socket
        │     2) song song: snapshot nhà hàng + menu mọi chi nhánh
        │     3) mở Realtime voice-agent
        │     4) session.update (instructions hành vi)
        │     5) conversation.item.create (message DATA)
        │     6) conversation.item.create (assistant text = đúng câu greeting)
        │
 PCM 16k ──upsample──▶ 24k ── input_audio_buffer.append
        │
        │  VAD / semantic turn
        │     model nói ── response.output_audio.delta (PCM 24k)
        │                    ──downsample──▶ PCM 16k ra socket
        │     model gọi tool ghi ── ta chạy ── function_call_output
        │
 Redis / HTTP catalog   (chỉ lúc init, không trên đường nóng)
 Backend REST           (chỉ khi create_booking / create_order)
```

Hai kết nối OpenAI **không** tồn tại cùng lúc trên một cuộc gọi:

- Cascade: Realtime transcription + HTTP Chat + HTTP TTS.
- S2S: Realtime voice-agent. HTTP TTS chỉ dùng **vài giây đầu** cho câu chào.

---

## 5. Model và session Realtime

### 5.1 Model

| Biến                    | Mặc định                 | Ghi chú                                      |
| ----------------------- | ------------------------ | -------------------------------------------- |
| `OPENAI_S2S_MODEL`      | `gpt-realtime-2.1-mini`  | Rẻ, đủ FAQ / đọc menu / slot đơn giản        |
| (override khi cần)      | `gpt-realtime-2.1`       | Tool phức tạp, khách nói vòng, lý luận hơn   |
| `OPENAI_S2S_VOICE`      | `marin`                  | Khác `OPENAI_TTS_VOICE` của cascade          |
| `OPENAI_S2S_REASONING`  | `low`                    | Realtime 2 có `reasoning.effort`; `low` cho thoại |


Mini là mặc định vì cuộc gọi nhà hàng: đọc món, hỏi slot, gọi 1–2 tool ghi. Full
model để A/B khi mini bịa món hoặc quên khóa chi nhánh.

Session Realtime tối đa **60 phút** — đủ cho cuộc gọi này.

### 5.2 `session.update` lúc nối

Kết nối WebSocket server-to-server tới `/v1/realtime` (không WebRTC — audio đã
đi qua bridge). Sau `session.created`:

```python
{
  "type": "session.update",
  "session": {
    "type": "realtime",
    "model": "gpt-realtime-2.1-mini",
    "output_modalities": ["audio"],
    "instructions": "<hành vi + STATE, xem §6.2 và §10>",
    "audio": {
      "input": {
        "format": {"type": "audio/pcm", "rate": 24000},
        "transcription": {"model": "gpt-4o-mini-transcribe", "language": "vi"},
        "turn_detection": {
          "type": "server_vad",
          "threshold": 0.5,
          "prefix_padding_ms": 300,
          "silence_duration_ms": 450,
          "create_response": True,       # bật SAU khi greeting TTS xong
          "interrupt_response": True,
        },
      },
      "output": {
        "format": {"type": "audio/pcm", "rate": 24000},
        "voice": "marin",
      },
    },
    "tools": [ /* chỉ tool ghi, §8 */ ],
  },
}
```

`create_response: False` trong lúc TTS đang đọc câu chào, để model không nói đè.
Sau greeting: `session.update` bật `create_response: True`.

Transcript input bật để log và để debug (không dùng cho LLM — model nghe audio
thật). Cùng STT model với cascade cho log dễ so.

Ban đầu **không** dùng `semantic_vad`. Cascade đang `server_vad` 450 ms; giữ vậy
để so độ trễ công bằng. Sau khi S2S ổn, A/B `semantic_vad`.

---

## 6. Bơm data vào cuộc hội thoại

### 6.1 Lúc nào lấy data

Ngay khi nhận `session.init` (có `toNumber`), **song song với TTS greeting**:

1. Snapshot nhà hàng theo hotline — Redis nếu v2 đã có, không thì
   `GET /restaurants/by-hotline/{digits}` như v1.
2. Lọc chi nhánh `status == "active"`.
3. **Eager menu:** với mỗi chi nhánh, `GET /menu/branch/{branchId}` (hoặc cache
   `aibridge:catalog:gN:menu:{id}`). Chạy song song (`asyncio.gather`), không
   tuần tự.
4. Một chi nhánh → tự `select_branch` như v1, không hỏi.
5. Build text DATA → `conversation.item.create`.
6. Gắn vào `CallSession` (RAM) để tool ghi validate id.

Greeting TTS **không chờ** bước 3. Khách nghe chào trong lúc menu đang nạp. Nếu
khách nói trước khi DATA item được tạo: giữ audio trong buffer (như `_MAX_PENDING_STT_BYTES`
hiện tại), chỉ `append` lên Realtime sau khi DATA đã vào conversation. Không để
model trả lời khi chưa có thực đơn — đó là lúc nó hay bịa món.

### 6.2 Message DATA — format

Một item, role system (hoặc developer), content text. Không JSON thô — model đọc
text có cấu trúc tốt hơn, và ta kiểm soát được chỗ nào được đọc ra miệng.

```
<DATA snapshot, đóng băng suốt cuộc gọi. Không đọc UUID ra miệng.>

Nhà hàng: Phở Thìn
Hotline: 1900636886

## Chi nhánh được phép nói tên
- Quận 1
- Quận 3
- Hà Nội

## Địa chỉ nội bộ — CẤM đọc khi kể tên hay hỏi khách chọn.
## Chỉ đọc khi khách hỏi địa chỉ / ở đâu.
- Quận 1: 12 Nguyễn Huệ; 08:00–22:00
- Quận 3: 45 Võ Văn Tần; 08:00–22:00
- Hà Nội: 8 Hàng Bông; 08:00–21:30

## Thực đơn theo chi nhánh
### Quận 1
- Phở bò [id=itm_aaa] — 65000 VND — có
- Bún chả [id=itm_bbb] — 70000 VND — có
- Trà đá [id=itm_ccc] — 5000 VND — hết

### Quận 3
- Phở bò [id=itm_ddd] — 65000 VND — có
…

### Hà Nội
…
```

Quy tắc trong cùng message (và nhắc lại trong instructions):

- Đọc **tên món, giá, còn/hết**. Không đọc `id=…`.
- Chỉ khẳng định món thuộc **chi nhánh đang khóa**. Chưa khóa thì hỏi chi nhánh
  trước, không đọc menu lẫn của ba quán.
- Không bịa món ngoài list. Không có trong list = không bán.
- `hết` = nói hết, không cho vào giỏ.

Id để trong ngoặc `id=` vì tool `add_to_cart` bắt buộc `menu_item_id` thuộc
snapshot. Model thấy id trong DATA nên không cần `search_menu` trả id. Ta **vẫn
validate** id trước khi ghi giỏ — prompt không phải luật.

### 6.3 Builder

Module mới `llm/data_message.py` (tách khỏi `build_system_prompt` của cascade):

```python
def build_data_message(
    restaurant: Restaurant | None,
    menus_by_branch_id: dict[str, list[MenuItem]],
    *,
    restaurant_missing: bool,
) -> str: ...
```

| Tình huống                         | Nội dung DATA                                      |
| ---------------------------------- | -------------------------------------------------- |
| Tra hotline được, có menu          | Đủ khối nhà hàng + chi nhánh + thực đơn            |
| Tra được nhà hàng, một chi nhánh GET menu lỗi | Vẫn ghi chi nhánh; khối menu ghi `(chưa tải được thực đơn chi nhánh X)` |
| `restaurant_missing`               | Một câu: không tra được nhà hàng; cấm bịa          |

Tên hàm cố ý khác `build_system_prompt`: cascade không gọi file này.

### 6.4 Giới hạn kích thước

Menu nhà hàng Việt điển hình (vài chục đến ~200 món × vài chi nhánh) nằm trong
context 128k. Vẫn đặt trần để cuộc gọi không nổ token:

| Ngưỡng                         | Hành vi                                                              |
| ------------------------------ | -------------------------------------------------------------------- |
| Món `available=false`          | Vẫn đưa vào, gắn `hết` — khách hỏi "còn phở không" cần câu thật      |
| `description` dài              | Cắt 80 ký tự; thoại không cần mô tả đầy đủ                           |
| Tổng món mọi chi nhánh > 250   | Prefetch **không** nhồi hết. DATA lúc init chỉ nhà hàng + chi nhánh. Khi `lock_branch` xong, `conversation.item.create` thêm một message `DATA-MENU` chỉ của chi nhánh đó |
| Một chi nhánh > 150 món        | Bỏ description, chỉ `tên — giá — có/hết — id`                        |


Trần 250 là để không nhồi 3 chi nhánh × 200 món. Hầu hết quán local không chạm.

### 6.5 Event tạo item

```python
{
  "type": "conversation.item.create",
  "item": {
    "type": "message",
    "role": "system",
    "content": [{"type": "input_text", "text": data_text}],
  },
}
```

Không `response.create` sau item này — DATA không phải để model đọc thành tiếng.

---

## 7. Câu chào nguyên văn

Disclosure "đây là trợ lý tự động" là yêu cầu pháp lý. S2S hay diễn lại. Cascade
thắng ở điểm này vì greeting chỉ là chuỗi đưa vào TTS.

**Quyết định:** S2S **không** để Realtime nói câu chào.

Trình tự:

1. `ensure_intent_greeting()` như hiện tại (hoặc menu 3 phím nếu v2 đã có).
2. HTTP TTS (`tts/openai_tts.py` hiện có) → PCM 16 kHz ra socket. `playing=true`.
3. Realtime đã connect; DATA item đã vào; `create_response` vẫn `false`.
4. `conversation.item.create` một assistant **text** đúng nguyên văn greeting, để
   model biết mình "đã nói" và không chào lại.
5. Bật `create_response: true`. State `LISTENING`.

Nếu khách barge-in lúc chào: giữ đúng hợp đồng hiện tại — `interrupt` sau frame
cuối, hủy TTS, **không** bật S2S response cho đến khi DATA sẵn (nếu chưa). Lượt
nói của khách được append bình thường.

Không hybrid giữa chừng: sau greeting, mọi câu sau đều từ `response.output_audio.delta`.
Không xen HTTP TTS vào giữa cuộc gọi — hai giọng khác nhau là trải nghiệm tệ.

---

## 8. Tool còn lại (chỉ ghi, không đọc catalog)

### 8.1 Bỏ

| Tool            | Lý do bỏ                                                                      |
| --------------- | ----------------------------------------------------------------------------- |
| `search_menu`   | Món + id đã trong DATA. Matcher LLM phụ (~300–600 ms) đúng là thứ S2S muốn tránh |
| `list_menu`     | "Có món gì" đọc từ DATA. Instructions: đọc vài tên, không đọc hết             |


Không bỏ `resolve_branch` kiểu "để model tự khóa bằng lời". Tên chi nhánh tiếng
Việt (HCM / Sài Gòn / Quận 3) vẫn cần matcher. Đổi thành tool **khóa**, không
phải tool **tìm trong catalog** — catalog đã có trong DATA.

### 8.2 Giữ / đổi nhẹ


| Tool                 | Vai trò trong S2S                                                                 | Khác cascade                                      |
| -------------------- | --------------------------------------------------------------------------------- | ------------------------------------------------- |
| `lock_branch`        | Đổi tên từ `resolve_branch`: nhận `spoken_name` nguyên văn, matcher trên snapshot, khóa nếu `match`+`high` | Cùng matcher `booking/matcher.py`                 |
| `confirm_branch`     | Khách chọn khi ambiguous                                                          | Không đổi                                         |
| `add_to_cart`        | `menu_item_id` phải ∈ menu của chi nhánh **đã khóa** trong snapshot               | Không còn yêu cầu "phải gọi search_menu trước"    |
| `update_cart`        | Như v1                                                                            | Không đổi                                         |
| `remove_from_cart`   | Như v1                                                                            | Không đổi                                         |
| `set_fulfillment`    | pickup / delivery + địa chỉ                                                       | Không đổi                                         |
| `save_order_details` | Ghi slot ngay khi khách nói                                                       | Không đổi                                         |
| `create_booking`     | POST đặt bàn; `restaurant_id`/`branch_id` từ state                                | Không đổi; chống POST kép như v2 §7.6             |
| `create_order`       | POST đơn; giỏ từ state                                                            | Không đổi                                         |


`restaurant_id` / `branch_id` **không** là đối số — cùng lý do [new_pipeline.md §7.4](new_pipeline.md).
Model có thể thấy id món trong DATA vì phải truyền vào `add_to_cart`; id chi nhánh
không cần nằm trong miệng tool.

### 8.3 Vòng tool trên Realtime

Khác cascade (`stream_sentences` 12 vòng Chat Completions):

```
response.done
  output[].type == "function_call"
    → chạy Python
    → conversation.item.create { type: "function_call_output", call_id, output: json }
    → response.create          # model nói tiếp / gọi tool tiếp
```

`should_abort()` / `generation_id`: nếu barge-in giữa lúc tool chạy, **không**
`response.create` sau output; tool `create_*` đã `POST` thì không rollback (giống
cascade). Tool chưa `POST` thì trả `interrupted` và dừng.

Trần 12 vòng tool / lượt giữ nguyên. Chạm trần → log WARNING, nói câu xin lỗi
ngắn bằng cách `response.create` với instructions "xin lỗi, thử lại", không im.

### 8.4 Prompt tool (rút)

Instructions S2S **không** còn đoạn "BẮT BUỘC gọi search_menu trước khi khẳng định
có món". Thay bằng:

- Có món / giá / hết: chỉ nói khi dòng đó nằm trong DATA của chi nhánh đang khóa.
- Thêm giỏ: gọi `add_to_cart` với đúng `id=` trong DATA. Id không có trong snapshot
  → tool trả `unknown_item`, nói không có món đó.
- Chưa khóa chi nhánh: không `add_to_cart`. Hỏi chi nhánh, gọi `lock_branch`.

---

## 9. Đường audio, VAD, barge-in

### 9.1 Sample rate — giữ như v1

| Chặng                    | Rate    | Encoding                    |
| ------------------------ | ------- | --------------------------- |
| Bridge hai chiều         | 16 kHz  | PCM16 LE mono               |
| Realtime S2S in / out    | 24 kHz  | PCM16, base64 trên event OpenAI |


Tái sử dụng `audio/resample.py`. Không đưa mu-law / 8 kHz vào AI Bridge.

Input: binary WS → upsample → `input_audio_buffer.append`.
Output: `response.output_audio.delta` (base64) → decode → downsample →
`OutboundGate.send_audio`. Không pace, không cắt sample 16-bit xuyên frame.

### 9.2 Barge-in và hợp đồng `interrupt`

Realtime tự hủy response khi VAD thấy khách nói (`interrupt_response: true`).
**Không đủ** cho frontend: player phía client vẫn còn queue PCM cũ.

Giữ đúng [hợp đồng §6.3](documents/backend_contract/ai-bridge-contract.md):

1. Ngừng gửi delta của response cũ (`generation_id` tăng — delta cũ bị drop).
2. Trong lock của `OutboundGate`: gửi hết frame đã quyết định gửi, rồi
   `{"event":"interrupt"}`.
3. `abort_and_interrupt()` hiện tại vẫn dùng được; `abort_work` là "ngừng forward
   audio S2S", không phải hủy HTTP TTS.

Không gửi `interrupt` nếu chưa từng gửi audio của lượt đó (giống v1).

### 9.3 `generation_id` trên S2S

Mỗi `response.created` gắn `response_id`. Ta map `generation_id` (số nội bộ
bridge) ↔ `response_id`. Delta chỉ forward khi khớp generation hiện tại.
`speech_started` → `begin_generation()` → mọi delta cũ thành stale.

---

## 10. State động (giỏ, chi nhánh khóa, intent)

DATA đóng băng. State đổi thì **không** sửa DATA item.

Mỗi lần tool ghi thành công (và khi DTMF chọn dịch vụ, nếu v2 đã có):

```
session.update({
  instructions: build_s2s_instructions(...)  # hành vi cố định + khối STATE
})
```

Khối STATE ngắn, ví dụ:

```
---STATE---
Chi nhánh đang khóa: Quận 3
Intent: order | fulfillment: delivery
Giỏ: 2 Phở bò (ít hành), 65000 VND × 2
Địa chỉ giao: (chưa có)
Đặt bàn đã tạo: không | Đơn món đã tạo: không
```

Cùng nguồn sự thật với `CallSession` (RAM). Instructions không chứa list món —
món ở DATA.

`build_s2s_instructions()` sống trong `llm/s2s_prompt.py`, **không** reuse nguyên
`build_system_prompt()` vì file đó đầy lệnh "gọi search_menu". Copy luật nói
(không markdown, một-hai câu mỗi lượt, không đọc UUID, HCM = Hồ Chí Minh, địa chỉ
cấm đọc lúc kể tên).

---

## 11. Snapshot isolation

Cùng luật [new_pipeline.md §9](new_pipeline.md): đọc catalog **một lần** lúc init.

- DATA message soạn từ snapshot RAM, không soạn từ Redis live.
- `lock_branch` / `add_to_cart` validate trên `CallSession.branches` /
  `CallSession.menus_by_branch_id` của cuộc gọi đó.
- Syncer Redis đổi generation giữa cuộc gọi: cuộc gọi này không thấy.
- POST bị backend từ chối (chi nhánh vừa đóng): xin lỗi theo ngữ cảnh, không
  refresh DATA giữa cuộc gọi.

Khác v2 một điểm: menu **eager**, nên miss cache lúc init phải GET hết trước khi
cho model nói. Degrade: một chi nhánh GET lỗi thì khối menu chi nhánh đó ghi
"chưa tải được"; các chi nhánh khác vẫn dùng. Không fail cả cuộc gọi.

---

## 12. Hợp đồng frontend — không đổi

Endpoint vẫn `ws://…/v1/bridge`. Auth Bearer / `?token=` như cũ.

| Hướng        | Frame  | Payload                                      |
| ------------ | ------ | -------------------------------------------- |
| Client → AI  | Text   | `session.init`                               |
| Client → AI  | Binary | PCM16 16 kHz                                 |
| Client → AI  | Text   | `dtmf` nếu v2 đã có — S2S nhận được thì inject user text "Khách ấn phím N" rồi `response.create` |
| AI → Client  | Binary | PCM16 16 kHz                                 |
| AI → Client  | Text   | `{"event":"interrupt"}`                      |
| AI → Client  | Text   | `order.created` khi POST đơn 2xx             |


Frontend demo không cần biết đang chạy cascade hay S2S. Không Twilio, không
WebRTC tới OpenAI từ browser.

---

## 13. Chọn pipeline lúc chạy

Thêm biến, **không** phá mặc định cascade:

```
PIPELINE_MODE=cascade    # mặc định
# PIPELINE_MODE=s2s

OPENAI_S2S_MODEL=gpt-realtime-2.1-mini
OPENAI_S2S_VOICE=marin
OPENAI_S2S_REASONING=low
```

Cùng `app.py`, cùng `/v1/bridge`. `CallPipeline` nhận strategy:

- `CascadePipeline` — code hiện tại (`stt/realtime.py` transcription + `llm/stream.py` + TTS)
- `S2SPipeline` — `stt/s2s_realtime.py` (tên mới, voice-agent)

Factory đọc `settings.pipeline_mode`. Test mặc định cascade. Test S2S dùng fake
Realtime voice-agent (không cần key).

Không auto-fallback S2S → cascade giữa cuộc gọi (hai giọng, hai history). Nếu
S2S connect fail lúc init: log lỗi, TTS một câu xin lỗi, đóng socket — hoặc (tùy
cờ `S2S_FALLBACK_CASCADE=true`) mở cascade **trước khi** gửi greeting. Cờ mặc
định `false` cho đến khi fallback được test.

---

## 14. Rủi ro và cách giữ an toàn

Đây là lý do S2S chưa phải mặc định.

| Rủi ro                                      | Cách xử lý trong ý định này                                                                 |
| ------------------------------------------- | ------------------------------------------------------------------------------------------- |
| Model diễn lại câu chào, mất disclosure     | Greeting = HTTP TTS; Realtime `create_response=false` tới khi chào xong (§7)                |
| Bịa món / bịa giá                           | DATA đóng băng + `add_to_cart` reject id lạ + instructions cấm nói món ngoài list           |
| Đọc UUID / id ra miệng                      | Prompt cấm; id trong DATA chỉ dạng `[id=…]`; nếu transcript output chứa UUID thì log WARNING (không cắt audio đang phát) |
| Đọc địa chỉ lúc kể chi nhánh                | Giữ hai khối tên vs địa chỉ nội bộ như v1                                                   |
| POST đơn / bàn hai lần                      | Cờ state + tool `already_created` không POST lần hai (v2 §7.6)                              |
| Chọn món chi nhánh A khi đang khóa B        | `add_to_cart` chỉ nhận id ∈ menu chi nhánh đã khóa                                          |
| Menu quá lớn, model lẫn món                 | Trần §6.4; sau khi khóa có thể (tùy chọn, bước sau) thu DATA-MENU còn một chi nhánh        |
| Giọng TTS chào ≠ giọng S2S                  | Chấp nhận vài giây đầu. Không trộn TTS giữa cuộc gọi. Voice S2S chọn gần giọng `nova` nếu được |
| `interrupt_response` nuốt `interrupt` JSON  | Vẫn tự gửi JSON theo hợp đồng; không tin OpenAI lo phía client                              |
| Chi phí audio token                         | Mini mặc định; DATA ~vài nghìn token/cuộc; theo dõi `/health` sau này                       |


Matcher chi nhánh **giữ**. S2S giỏi nghe, không thay cho `lock_branch`.

---

## 15. Kế hoạch code (khi làm)

Chưa làm trong lượt viết tài liệu này. Thứ tự khi implement — mỗi bước không phá
cascade:

```
phone_call_project/
|-- llm/
|   |-- data_message.py      # MỚI  build_data_message
|   `-- s2s_prompt.py        # MỚI  build_s2s_instructions (hành vi + STATE)
|-- stt/
|   `-- s2s_realtime.py      # MỚI  voice-agent: append, audio delta, tool events
|-- bridge/
|   |-- pipeline_s2s.py      # MỚI  greeting TTS + inject DATA + forward audio
|   `-- server.py            # SỬA  factory theo PIPELINE_MODE
|-- config.py                # SỬA  pipeline_mode, OPENAI_S2S_*
|-- .env.example             # SỬA  comment các biến trên
`-- tests/
    `-- test_s2s_pipeline.py # MỚI  fake realtime, inject DATA, interrupt, tool ghi
```

Tái sử dụng không copy: `audio/resample.py`, `tts/openai_tts.py` (greeting),
`booking/client.py`, `order/client.py`, `booking/matcher.py`, `turn/barge_in.py`,
`bridge/protocol.py`, frontend.

`CallSession` thêm `menus_by_branch_id: dict[str, list[MenuItem]]` (cascade có thể
bỏ trống). Không nhét logic S2S vào `llm/stream.py`.

Thứ tự:

1. `build_data_message` + test snapshot → text (nhà hàng thiếu, menu cắt trần, khối địa chỉ riêng).
2. Fake `S2SRealtimeClient` + test: DATA item được create trước audio user; greeting không qua S2S.
3. Tool ghi: `add_to_cart` id lạ fail; id đúng chi nhánh khóa pass; `search_menu` không đăng ký.
4. Nối `PIPELINE_MODE=s2s` vào server; test WS hồi quy cascade vẫn pass khi mode mặc định.
5. Cuộc gọi tay trên frontend demo, so latency và lỗi bịa món với cascade.

---

## 16. Test dự kiến

Giữ nguyên tắc hiện tại: pytest **không** cần key OpenAI, không cần mạng.

- DATA: ba chi nhánh × vài món → text có đủ tên, có `id=`, địa chỉ không nằm trong khối "được phép nói tên".
- `restaurant_missing` → DATA là câu cấm bịa, không có bảng món.
- Trần 250 món → init không chứa thực đơn; sau `lock_branch` có item `DATA-MENU` một chi nhánh.
- Greeting: fake TTS được gọi; fake S2S **không** `response.create` trước `greeting_done`.
- Sau greeting: có assistant item text === chuỗi greeting.
- User audio không `append` trước khi DATA item ack.
- `add_to_cart` id không thuộc snapshot → `unknown_item`, không đụng giỏ.
- `add_to_cart` đúng id nhưng sai chi nhánh khóa → fail.
- Barge-in: `generation_id` tăng, `interrupt` sau bytes đã gửi, delta response cũ không ra WS.
- `PIPELINE_MODE=cascade` (mặc định): không import / không connect voice-agent.

---

## 17. Việc cố ý không làm trong pipeline này

- Không thay cascade, không đổi mặc định production.
- Không WebRTC từ browser tới OpenAI.
- Không SIP Realtime.
- Không bỏ matcher chi nhánh.
- Không để S2S tự POST HTTP — mọi ghi đi qua tool Python.
- Không RAG, không chuyển lễ tân (cùng phạm vi v1).
- Không sửa frontend trừ khi sau này DTMF v2 cần inject (event đã có thì chỉ server).

---

## Liên quan

- [new_pipeline.md](new_pipeline.md) — cascade v2; S2S đọc cùng cache nếu đã có
- [documents/ai-pipeline.md](documents/ai-pipeline.md) — PCM, resample, state machine
- [documents/backend_contract/ai-bridge-contract.md](documents/backend_contract/ai-bridge-contract.md)
- [llm/stream.py](llm/stream.py) — chỗ v1 đang nhồi chi nhánh vào system prompt (mẫu cho DATA message)
- [stt/realtime.py](stt/realtime.py) — Realtime **transcription** hiện tại; S2S là session type khác, file khác
