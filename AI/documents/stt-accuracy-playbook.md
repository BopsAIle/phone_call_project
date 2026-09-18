# STT nghe sai — chẩn đoán và cách sửa

Tài liệu điều tra: **vì sao transcript ra chữ hoàn toàn sai** dù người gọi đọc tên món gần đúng,
và tên món đó **đã nằm trong database**. Mỗi nguyên nhân đều trỏ tới dòng code thật; mỗi cách sửa
đều kèm patch và cách đo.

**Giả định đã chốt:**

- Database chứa tên món / chi nhánh **tiếng Anh**. Không có từ tiếng Việt trong catalog.
- Hội thoại diễn ra bằng **tiếng Anh**.
- Người gọi **không phải bản xứ** — phát âm lệch chuẩn. Đây là ca thường, không phải ngoại lệ.
- Kênh vào là **điện thoại gọi tới, qua Telnyx Media Streaming** — L16 16 kHz, track `inbound_track`
  ([config.py:70-72](config.py#L70-L72)). Demo browser chỉ còn là công cụ dev. Mọi nguyên nhân và
  cách sửa chỉ đúng trên đường browser đã được gỡ khỏi tài liệu này.

Bổ sung cho:

- [documents/contextual_stt_cách_2_cb746c43.md](documents/contextual_stt_cách_2_cb746c43.md) — kế hoạch pipeline Cách 2 (prompt + keywords)
- [documents/so_sanh_kien_truc_nhan_dang_giong_noi.md](documents/so_sanh_kien_truc_nhan_dang_giong_noi.md) — so sánh Cách 1 / Cách 2
- [documents/ai-pipeline.md](documents/ai-pipeline.md) — spec audio + state machine

---

## Mục lục

- [0. Kết luận ngắn](#0-kết-luận-ngắn)
- [1. Năm nguyên nhân tìm thấy trong code](#1-năm-nguyên-nhân-tìm-thấy-trong-code)
- [2. Tầng 1 — đổi model và sửa cấu hình STT (30 phút)](#2-tầng-1--đổi-model-và-sửa-cấu-hình-stt-30-phút)
- [3. Tầng 2 — nhồi từ vựng từ database vào lúc nghe](#3-tầng-2--nhồi-từ-vựng-từ-database-vào-lúc-nghe)
- [4. Tầng 3 — lưới ngữ âm sau STT](#4-tầng-3--lưới-ngữ-âm-sau-stt)
- [5. Tầng 4 — sửa đường audio và VAD](#5-tầng-4--sửa-đường-audio-và-vad)
- [6. Tầng 5 — UX khi vẫn nghe sai](#6-tầng-5--ux-khi-vẫn-nghe-sai)
- [7. Đo lường: đừng sửa mù](#7-đo-lường-đừng-sửa-mù)
- [8. Chi phí](#8-chi-phí)
- [9. Thứ tự triển khai đề xuất](#9-thứ-tự-triển-khai-đề-xuất)
- [10. Nguồn](#10-nguồn)

---

## 0. Kết luận ngắn

Menu tiếng Anh, hội thoại tiếng Anh, `language: "en"` — vậy cấu hình ngôn ngữ **không sai**. Vấn đề
nằm ở ba chỗ khác, và chúng cộng dồn:

> 1. Đang dùng model STT thế hệ cũ, yếu nhất ở đúng thứ bạn cần: **giọng không bản xứ**.
> 2. STT **không hề biết** quán bán gì, dù toàn bộ tên món đã nằm sẵn trong database.
> 3. Sau STT không có lưới lọc ngữ âm — chuỗi sai đi thẳng vào matcher LLM, rác vào rác ra.

Người không bản xứ đọc "Chicken Zinger Combo" → model trả "chicken singer combo". Với model text, hai
chuỗi đó khác nhau. Về **âm**, chúng gần như trùng. Không có ai trong pipeline làm cầu nối đó.

Bốn đòn theo thứ tự hiệu quả / công sức:

| # | Việc | Công sức | Kỳ vọng |
|---|---|---|---|
| 1 | Bơm tên món/chi nhánh từ DB vào `prompt` của STT | 1 ngày | Giải đúng bài "keyword đã có trong database" |
| 2 | Ở lại `gpt-4o-transcribe`, **không** đổi sang `gpt-live-transcribe` | 5 phút | Xem 1.1 — model mới không có VAD |
| 3 | Lưới ngữ âm sau STT (không thêm thư viện) | 0.5 ngày | 14/14 trong bộ test dựng sẵn (mục 4.3) |
| 4 | Nới VAD + khai báo `noise_reduction` cho kênh điện thoại | 30 phút | Hết cụt câu giữa chừng |

---

## 1. Năm nguyên nhân tìm thấy trong code

### 1.1 Model mới nghe hay hơn nhưng **không dùng được ở đây**

Đây là chỗ bản đầu của tài liệu này đoán sai, và chỉ vỡ ra khi gọi thật vào API.

Trước hết, một quả mìn im lặng đã gỡ: [config.py](config.py#L30) mặc định
`gpt-4o-mini-transcribe` trong khi `.env` đặt `gpt-4o-transcribe` — ai chạy thiếu `.env` rơi về model
yếu nhất mà không biết. Hai chỗ giờ đã cùng là `gpt-4o-transcribe`.

Doc OpenAI khuyên `gpt-live-transcribe` cho streaming, và nó **thật sự** nhận `keywords`. Nhưng đo
trực tiếp bằng API key của dự án, với chính payload pipeline này gửi:

| Model | `turn_detection` (server VAD) | `keywords` | `prompt` |
|---|---|---|---|
| `gpt-4o-transcribe` | ✅ | ❌ | ✅ |
| `gpt-4o-mini-transcribe` | ✅ | ❌ | ✅ |
| `gpt-live-transcribe` | ❌ | ✅ | ✅ |

Lỗi trả về nguyên văn khi bật VAD với model mới:

```
Turn detection is not supported for this transcription model.
  param: session.audio.input.turn_detection
```

Không lách được bằng cách đổi session sang kiểu `realtime`:

```
Passing a realtime session update to a transcription session is not allowed.
```

Pipeline này sống bằng VAD: `speech_started` kích hoạt barge-in
([session.py](bridge/session.py#L695)), `speech_stopped` chốt lượt. Bỏ VAD thì phải tự dò tiếng nói ở
client và tự gọi `input_audio_buffer.commit()` — cấu phần mới, rủi ro cao, vượt xa "chỉnh cấu hình".

**Kết luận: ở lại `gpt-4o-transcribe`.** Nó không có `keywords`, nhưng **có `prompt`** — và đó chính
là kênh nhồi từ vựng mục 3 dùng. Chỉ quay lại `gpt-live-transcribe` khi nào ta tự commit buffer.

> Bài học: doc của nhà cung cấp mô tả từng API, không mô tả **tổ hợp** API. Đo tổ hợp mình định dùng
> trước khi đổi kiến trúc theo nó.

### 1.2 STT mù tịt về quán này bán gì

Hôm nay không có `prompt`, không có `keywords`. STT chỉ "nghe tiếng thành chữ" rồi mới đưa cho LLM.
Menu chỉ được nạp **sau** khi LLM gọi `search_menu` ([order/tools.py:609](order/tools.py#L609)) — tức
là đúng lúc khách nói tên món lần đầu thì STT chưa biết gì về menu.

Bạn có sẵn "Chicken Zinger Combo" trong DB. STT không hề được cho biết. Đây là lãng phí lớn nhất của
kiến trúc hiện tại: catalog nằm ngay đó, nhưng chỉ được dùng **sau** khi chữ đã sai.

Đây cũng chính là điểm yếu của Cách 1 mô tả trong
[so_sanh_kien_truc_nhan_dang_giong_noi.md](documents/so_sanh_kien_truc_nhan_dang_giong_noi.md):
*error propagation* — STT sai nặng thì LLM ở bước sau không đủ dữ liệu để khôi phục.

### 1.3 Sau STT không có lưới lọc — rác vào, rác ra

[order/matcher.py:97-140](order/matcher.py#L97-L140) là matcher LLM thuần: đưa chuỗi khách nói +
catalog JSON cho `gpt-4o-mini` rồi hỏi "món nào". Không có bước so khớp **ngữ âm** nào.

Khi STT trả "sesar salat", LLM phải tự đoán ra "Caesar Salad" từ khoảng cách chữ. Đôi khi được, đôi
khi không — và khi không, khách nghe "Xin lỗi, chúng tôi không có món đó" trong khi món ấy nằm ngay
trên menu.

Một hàm ~60 dòng không cần thư viện ngoài giải đúng lớp lỗi này, deterministic và test được (mục 4).

### 1.4 VAD cắt câu quá sớm

[stt/realtime.py:18-23](stt/realtime.py#L18-L23):

```python
VAD = {
    "type": "server_vad",
    "threshold": 0.3,
    "prefix_padding_ms": 300,
    "silence_duration_ms": 450,
}
```

`silence_duration_ms: 450` là ngưỡng cho người bản xứ nói trôi chảy. Người nói tiếng Anh không phải
tiếng mẹ đẻ **ngập ngừng giữa câu** — dừng lại để lắp từ, nhất là trước tên món dài ("I want... ừm...
the grilled pork chop"). 450 ms im lặng → VAD chốt lượt → model transcribe một mẩu cụt ("I want") →
phần còn lại thành lượt khác, thiếu ngữ cảnh → đoán sai.

Càng ít ngữ cảnh, model càng phải đoán. Mẩu 2 từ là điều kiện tệ nhất cho mọi ASR.

`threshold: 0.3` cũng thấp (mặc định OpenAI là 0.5) → tiếng ồn/quạt/TTS rò cũng mở lượt, tạo transcript rác.

### 1.5 Đường điện thoại chưa được khai báo với STT — và băng thông của nó rất hẹp

Hai chuyện khác nhau, cùng nằm trên một sợi dây.

**Chưa khai báo.** `"noise_reduction": None` từng không nói gì với OpenAI về nguồn audio. Trên đường điện thoại thì không có ai lọc trước cả: L16 của carrier đi
thẳng vào STT. Cách sửa ở mục 5.1.

**Băng thông hẹp là trần cứng.** Telnyx stream L16 16 kHz ([config.py:72](config.py#L72)), rồi
[telephony/telnyx/codec.py](telephony/telnyx/codec.py) resample lên 24 kHz cho OpenAI. Nhưng resample
**không tạo thêm thông tin**: nếu chặng gọi là PSTN/G.711 thì nội dung thật vẫn nằm gọn trong dải
~300–3400 Hz.

Chỗ đau: năng lượng phân biệt các âm xát /s/, /f/, /θ/ nằm phần lớn **trên 4 kHz** — đúng phần mà
đường điện thoại đã cắt trước khi ta chạm vào (/ʃ/ thấp hơn, ~2–4 kHz, nên sống sót tốt hơn). Vì thế
"three" / "free", "mouth" / "mouse", "Fries" / "rice" khó trên điện thoại hơn hẳn trên micro laptop.
Và nó **cộng dồn** với mục 1.1: giọng không bản xứ vốn phát âm mấy âm này đã yếu, giờ bị kênh truyền
xén nốt.

Băng thông thì không sửa được. Nhưng biết nó tồn tại thì đổi thứ tự ưu tiên:

- Giữ `TELNYX_BIDI_SAMPLING_RATE=16000` ([config.py:72](config.py#L72)). Hạ xuống 8000 cho nhẹ băng
  thông là tự bắn vào chân — với chặng VoIP wideband, 16 kHz mang thêm tín hiệu thật.
- Mục 3 (`keywords`) và mục 4 (lưới ngữ âm) **quan trọng hơn trên điện thoại** so với trên browser:
  chúng bù đúng cái mà kênh truyền lấy mất. Khi tín hiệu âm học không đủ để phân biệt, phải bù bằng
  tri thức về việc quán này bán gì.

### 1.6 Một ghi chú nhỏ: `del locale`

[stt/realtime.py](stt/realtime.py) từng vứt bỏ `locale` rồi ghim `language: "en"`:

```python
def _session_payload(self, locale: str | None) -> dict[str, Any]:
    del locale  # pinned to English regardless of session locale
```

Với triển khai chỉ tiếng Anh, **cái này đúng** — không phải bug. Hai thứ ăn theo nó thì là code chết,
và **đã dọn**:

- `_session_payload` không còn nhận `locale`; `update_language()` đã được thay bằng `update_context()`
  (mục 3.2), thứ thật sự có việc để làm.
- Câu `"The caller may speak Vietnamese. Understand them, but always reply in English."` đã gỡ khỏi
  [llm/stream.py](llm/stream.py) — nó dạy LLM chấp nhận đầu vào mà STT không bao giờ tạo ra.

---

## 2. Tầng 1 — sửa cấu hình STT (30 phút)

Patch cho [stt/realtime.py](stt/realtime.py). Giữ nguyên kiến trúc, chỉ đổi payload.

```python
# stt/realtime.py

VAD = {
    "type": "server_vad",
    "threshold": 0.45,           # 0.3 → 0.45: bớt mở lượt vì tiếng ồn
    "prefix_padding_ms": 400,    # 300 → 400: giữ trọn âm tiết đầu
    "silence_duration_ms": 800,  # 450 → 800: cho người nói chậm kịp nghĩ
}

# Nhánh model mới giữ lại cho ngày ta tự commit buffer (1.1); hôm nay
# production chạy nhánh dưới.
NEW_MODELS = frozenset({"gpt-transcribe", "gpt-live-transcribe"})


def _session_payload(self) -> dict[str, Any]:
    transcription: dict[str, Any] = {"model": self._model}
    if self._model in NEW_MODELS:
        # "languages" và "language" loại trừ nhau — gửi cả hai là bị từ chối.
        transcription["languages"] = list(self._languages)
        transcription["delay"] = "low"
        transcription["keywords"] = self._keywords
    else:
        transcription["language"] = self._languages[0]
    transcription["prompt"] = self._prompt   # kênh nhồi từ vựng của gpt-4o-transcribe
    return {
        "type": "transcription",
        "audio": {
            "input": {
                "format": {"type": "audio/pcm", "rate": 24000},
                "transcription": transcription,
                "turn_detection": dict(VAD),
                "noise_reduction": {"type": "near_field"},   # mục 5.1
            }
        },
    }
```

`.env`:

```bash
OPENAI_STT_MODEL=gpt-4o-transcribe
OPENAI_STT_LANGUAGES=en
```

Và sửa default trong [config.py:30](config.py#L30) cho khớp.

Khi model từ chối một field tuỳ chọn (`delay`, `keywords`, `prompt`, `languages`), client bỏ đúng
field đó rồi gửi lại thay vì để cả session chết — xem `_maybe_drop_unsupported` trong
[stt/realtime.py](stt/realtime.py). Riêng `turn_detection` bị từ chối thì không cứu được: client log
một dòng ERROR nói thẳng phải đổi `OPENAI_STT_MODEL`, vì không VAD nghĩa là không có transcript nào cả.

> **Nếu menu có tên món nước ngoài** (Risotto, Croissant, Jalapeño, Pho): cân nhắc thêm ngôn ngữ gốc
> vào `OPENAI_STT_LANGUAGES`. Nhưng đo trước — thêm ngôn ngữ cũng cho model một lối thoát để gán nhầm
> câu tiếng Anh ngắn. Với danh từ riêng lẻ tẻ, `prompt` (mục 3) là công cụ đúng hơn.

### Các tham số, đúng như SDK khai báo

SDK đã cài (`openai 3.14.1`), file `openai/types/realtime/audio_transcription_param.py`:

| Field | Ý nghĩa | Ghi chú |
|---|---|---|
| `model` | `gpt-live-transcribe`, `gpt-transcribe`, `gpt-4o-transcribe`, `whisper-1`, … | |
| `languages` | Danh sách ISO-639-1 khả dĩ | **Chỉ** model mới. Cấm gửi cùng `language` |
| `language` | Một ngôn ngữ duy nhất | Model cũ |
| `keywords` | Chuỗi literal cần ưu tiên | **Chỉ** `gpt-transcribe` / `gpt-live-transcribe` |
| `prompt` | Bối cảnh tự do ("A customer support call about…") | Không phải chỗ ra lệnh |
| `delay` | `minimal` / `low` / `medium` / `high` / `xhigh` | Chậm hơn = chính xác hơn |

Lưu ý: docstring của SDK ghi `delay` "only supported with `gpt-realtime-whisper` in GA Realtime
sessions", còn guide realtime-transcription lại đưa `delay` trong ví dụ `gpt-live-transcribe`.
Hai nguồn lệch nhau → **gửi thử, bắt `error` event, bỏ field nếu bị từ chối**; đừng để cả session
chết vì một field.

### `delay` đánh đổi gì

Guide nói thẳng: delay thấp → partial ra sớm; delay cao → model có thêm audio trước khi phát chữ,
**word error rate tốt hơn**. Hotline đã chấp nhận độ trễ TTS vài trăm ms, nên `low` → `medium` là
đánh đổi đáng cân nhắc nếu vẫn sai. Với giọng không bản xứ, thêm ngữ cảnh âm thanh giúp nhiều hơn
bình thường: model có thêm âm tiết để suy ra từ mà người nói đang cố đọc.

---

## 3. Tầng 2 — nhồi từ vựng từ database vào lúc nghe

Đây là câu trả lời trực tiếp cho *"keyword đã có trong database phát âm khá giống"*.

### 3.1 `prompt` khác `keywords`

Theo doc OpenAI:

- **`prompt`** — "free-form context about the recording, such as its topic or setting".
  Ví dụ của họ: `"A customer support call about a premium plan and account AC-42."`
- **`keywords`** — "literal terms that may appear in the audio, such as product names, medications,
  or acronyms". Và: *"Keywords are hints, not required output. The transcript should include a
  keyword only when the audio contains it."*

Ràng buộc format (từ cookbook migration): mỗi keyword là **một dòng literal**, không chứa `<`, `>`,
CR, LF.

> **Trên `gpt-4o-transcribe` thì `prompt` là kênh duy nhất** — model này không có field `keywords`
> (1.1). Nên tên món đi vào `prompt` dưới dạng văn xuôi: *"Expect these branch and dish names: …"*.
> Đây đúng là cách OpenAI mô tả `prompt` cho họ `gpt-4o-transcribe` ("a free text string, for example
> 'expect words related to technology'"). `build_keywords` vẫn sinh danh sách tên như cũ; nó vừa nạp
> vào `prompt`, vừa sẵn sàng cho field `keywords` nếu sau này đổi model.
>
> Giới hạn tự đặt: 40 tên, 800 ký tự. Prompt phình ra thì chính những cái tên cần nhấn lại bị loãng.

Ví dụ JSON đúng chuẩn từ guide (model mới — tham khảo, không phải cấu hình đang chạy):

```json
{
  "type": "session.update",
  "session": {
    "type": "transcription",
    "audio": {
      "input": {
        "format": { "type": "audio/pcm", "rate": 24000 },
        "transcription": {
          "model": "gpt-live-transcribe",
          "prompt": "A customer support call about a premium plan and account AC-42.",
          "keywords": ["premium plan", "AC-42", "billing"],
          "languages": ["en", "fr"],
          "delay": "low"
        },
        "turn_detection": null
      }
    }
  }
}
```

Áp vào hotline của bạn:

```python
"prompt": "Phone call to the restaurant Downtown Grill. The caller books a table "
          "or orders food for pickup or delivery. The caller may be a non-native "
          "English speaker.",
"keywords": ["Downtown Grill", "Chicken Zinger Combo", "Spring Rolls", "Caesar Salad"],
```

### 3.2 Bài toán gà–trứng: menu về muộn hơn câu nói

Thứ tự thật trong code hôm nay:

| Mốc | Có gì | Nguồn |
|---|---|---|
| t0 | WebSocket mở, STT start | [bridge/session.py:452](bridge/session.py#L452) |
| t1 | `session.init` → `storeName`, `locale`, `toNumber` | [bridge/protocol.py](bridge/protocol.py) |
| t2 | Catalog nhà hàng + chi nhánh | [`_load_catalog`](bridge/session.py#L597) |
| t3 | Menu — **chỉ khi** LLM gọi `search_menu` | [`_ensure_menu`](order/tools.py#L609) |
| t4 | Khách nói tên món | … đã xảy ra **trước** t3 |

Nếu chỉ nạp keyword sau lần `search_menu` đầu tiên thì **đúng câu cần nhất lại chưa có keyword**.
Cách chữa: **preload menu ngay khi khóa được chi nhánh**, rồi `session.update` lại khối
`transcription`. Quán một chi nhánh (đa số) khóa được ngay ở t2.

`RealtimeTranscriptionClient` đã có sẵn chỗ để làm việc này —
[`update_language`](stt/realtime.py#L134) chính là một `session.update` giữa cuộc gọi (và hiện là hàm
chết, xem 1.7). Đổi nó thành `update_context(keywords=..., prompt=...)`:

```python
async def update_context(self, *, prompt: str = "", keywords: list[str] | None = None) -> None:
    if not self._connection or self.closed:
        return
    self._prompt = prompt or self._prompt
    self._keywords = keywords if keywords is not None else self._keywords
    try:
        await self._connection.session.update(session=self._session_payload(None))
        logger.info(
            "STT context updated callId=%s keywords=%s", self._call_id, len(self._keywords)
        )
    except Exception:
        # Update hỏng thì GIỮ session cũ. Không được để cuộc gọi chết vì một field.
        logger.exception("STT session.update(context) failed callId=%s", self._call_id)
```

### 3.3 Chọn keyword nào — và bỏ cái nào

OpenAI không công bố giới hạn cứng về số lượng. Trần an toàn tự đặt:

- **≤ 80 keyword**, mỗi cái ≤ 40 ký tự.
- Ưu tiên: tên quán → tên chi nhánh → tên món của **chi nhánh đã khóa** (không nhồi menu mọi chi nhánh).
- **Bỏ**: UUID, giá, địa chỉ đầy đủ, mô tả món. Không ai đọc UUID vào điện thoại.
- **Tách tên món dài**: "Chicken Zinger Combo" nên đi kèm "Zinger" — khách thường gọi tắt, và từ hiếm
  nhất trong tên (ở đây là "Zinger") chính là từ STT hay nghe sai nhất.
- Sanitize: bỏ `<`, `>`, `\r`, `\n`; gộp khoảng trắng; dedupe không phân biệt hoa thường.

```python
# stt/context.py (file mới)
_FORBIDDEN = str.maketrans({"<": None, ">": None, "\r": None, "\n": None})

# Từ quá phổ biến thì làm keyword vô nghĩa — model đã biết chúng rồi.
_TOO_COMMON = {"combo", "set", "large", "small", "chicken", "beef", "rice", "tea", "coffee"}


def build_keywords(store_name: str, branches, menu_items, limit: int = 80) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()

    def push(raw: str) -> None:
        text = " ".join((raw or "").translate(_FORBIDDEN).split())[:40]
        if not text or text.lower() in seen:
            return
        seen.add(text.lower())
        out.append(text)

    push(store_name)
    for branch in branches or []:
        push(getattr(branch, "name", ""))
    for item in menu_items or []:
        name = getattr(item, "name", "")
        push(name)
        # Từ hiếm trong tên món là thứ STT hay nghe sai nhất: "Zinger", "Risotto".
        for word in name.split():
            if len(word) >= 6 and word.lower() not in _TOO_COMMON:
                push(word)
        if len(out) >= limit:
            break
    return out[:limit]
```

`prompt` giữ ngắn, mô tả **bối cảnh** chứ không ra lệnh:

```python
def build_prompt(store_name: str) -> str:
    name = store_name or "a restaurant"
    return (
        f"Phone call to the restaurant {name}. "
        "The caller books a table or orders food for pickup or delivery. "
        "The caller may be a non-native English speaker with a strong accent."
    )
```

> Đừng viết `"transcribe accurately"` hay `"fix spelling"` vào `prompt`. Doc nói rõ đây là *bối cảnh
> bản ghi*, không phải instruction. Viết lệnh vào đó chỉ tốn token.

### 3.4 Sửa tại chỗ hay tách pipeline?

[documents/contextual_stt_cách_2_cb746c43.md](documents/contextual_stt_cách_2_cb746c43.md) đã chọn
**tách pipeline** (`PIPELINE_MODE=contextual_stt`, file `stt/contextual.py` mới, không đụng
`stt/realtime.py`) để rollback và A/B dễ.

Đánh giá lại trong bối cảnh "production đang nghe sai": cách tách vẫn đúng **nếu** bạn cần A/B có
kiểm soát. Nhưng nếu chất lượng hiện tại đã không dùng được, thì một `if self._model in _NEW_MODELS`
ngay trong file cũ (mục 2) rẻ hơn nhiều so với dựng pipeline song song — rollback chỉ là đổi lại
`OPENAI_STT_MODEL` trong `.env`.

Đề xuất: **sửa tại chỗ + công tắc env**, để dành việc tách pipeline cho lúc thử kiến trúc S2S.

---

## 4. Tầng 3 — lưới ngữ âm sau STT

Keyword biasing là *hint*, không phải bảo đảm. Vẫn cần lưới chặn cuối, và lưới này **không cần thư
viện ngoài, không gọi API, chạy trong micro giây, test được**.

### 4.1 Ý tưởng

So khớp theo **khung phụ âm** thay vì theo chữ. Người học tiếng Anh có tập lỗi rất đều, bất kể tiếng
mẹ đẻ nào:

| Hiện tượng | Ví dụ |
|---|---|
| Lẫn phụ âm cùng nhóm | p/b, t/d, k/g, s/z, f/v, l/r |
| Rụng phụ âm cuối và cụm phụ âm | "fries" → "fry", "wings" → "wing", "iced" → "ice" |
| `th` thành `t` hoặc `s` | "smoothie" → "smootie" |
| Không phân biệt /r/ cuối (non-rhotic) | "burger" → "burga" |
| Nguyên âm trôi dạt hoàn toàn | "Caesar" → "sesar", "Zinger" → "singer" |

Nên: bỏ hết nguyên âm, gộp phụ âm về **lớp**, rồi so hai khung bằng `difflib`. Nguyên âm là thứ người
không bản xứ sai nhiều nhất, nên vứt chúng đi là bước đầu tiên đúng đắn.

### 4.2 Code (đã chạy thật, stdlib thuần)

```python
"""stt/phonetic.py — khung phụ âm cho giọng không bản xứ. Không thêm dependency."""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

_DIGRAPHS = [
    ("sch", "S"), ("tch", "S"), ("ph", "F"), ("th", "T"), ("ch", "S"),
    ("sh", "S"), ("ck", "K"), ("qu", "K"), ("ng", "N"), ("gh", "K"),
]
_CLASS = {
    "b": "P", "p": "P",
    "d": "T", "t": "T",
    "c": "K", "k": "K", "g": "K", "q": "K",
    "f": "F", "v": "F", "w": "F",
    "s": "S", "z": "S", "x": "S", "j": "S",
    "m": "N", "n": "N",
    "l": "L", "r": "L",
    "h": "", "y": "",
}
_VOWELS = set("aeiou")


def strip_marks(text: str) -> str:
    """'Jalapeño' -> 'Jalapeno'. Menu tiếng Anh vẫn mượn dấu từ tiếng khác."""
    nfd = unicodedata.normalize("NFD", text or "")
    return "".join(ch for ch in nfd if unicodedata.category(ch) != "Mn")


def normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", strip_marks((text or "").lower())).strip()


def _drop_coda_glides(norm: str) -> str:
    """Non-rhotic + rụng đuôi: nguyên âm + r/w/y -> nguyên âm ('burger' ~ 'burga')."""
    return re.sub(r"([aeiou])[rwy]+", r"\1", norm)


def skeleton(text: str) -> str:
    norm = _drop_coda_glides(normalize(text).replace(" ", ""))
    for src, dst in _DIGRAPHS:
        norm = norm.replace(src, dst.lower() + "\x00")
    out: list[str] = []
    for ch in norm:
        if ch == "\x00" or ch in _VOWELS:
            continue
        out.append(ch if ch.isupper() else _CLASS.get(ch, ch.upper()))
    squashed: list[str] = []
    for ch in out:                      # gộp lặp: "PP" -> "P"
        if ch and (not squashed or squashed[-1] != ch):
            squashed.append(ch)
    return "".join(squashed)


def similarity(spoken: str, name: str) -> float:
    """0..1. Khoảng cách chữ là chính; khung phụ âm chỉ để CỨU chuỗi viết sai."""
    a_txt, b_txt = normalize(spoken), normalize(name)
    if not a_txt or not b_txt:
        return 0.0
    text_ratio = SequenceMatcher(None, a_txt, b_txt).ratio()
    a_sk, b_sk = skeleton(spoken), skeleton(name)
    if not a_sk or not b_sk:
        return text_ratio
    skel_ratio = SequenceMatcher(None, a_sk, b_sk).ratio()
    # Khung 2 ký tự ("KN") đụng nửa menu, nên khung ngắn ít quyền biểu quyết.
    short = min(len(a_sk), len(b_sk))
    weight = 0.0 if short < 3 else (0.45 if short < 4 else 0.6)
    return max(text_ratio, (1 - weight) * text_ratio + weight * skel_ratio)


def rank(spoken: str, items, key=lambda item: item.name, top: int = 8):
    """[(score, item)] giảm dần."""
    scored = [(similarity(spoken, key(item)), item) for item in items]
    scored.sort(key=lambda row: row[0], reverse=True)
    return scored[:top]
```

### 4.3 Kết quả đo thật

Menu giả: `["Chicken Zinger Combo", "Spring Rolls", "Iced Lemon Tea", "Grilled Pork Chop",
"Beef Noodle Soup", "Fried Chicken Wings", "Caesar Salad", "Peach Tea", "Cheeseburger",
"French Fries", "Mushroom Risotto", "Vanilla Milkshake"]`. Đầu vào là **chuỗi STT sai** đúng kiểu
giọng không bản xứ tạo ra:

| STT trả về | Khớp ra | Điểm | Cách biệt hạng 2 |
|---|---|---|---|
| `chicken singer combo` | Chicken Zinger Combo | 0.98 | 0.42 |
| `sprink rol` | Spring Rolls | 0.83 | 0.33 |
| `spring rol please` | Spring Rolls | 0.85 | 0.35 |
| `ice lemon tee` | Iced Lemon Tea | 0.89 | 0.31 |
| `gril pork chop` | Grilled Pork Chop | 0.92 | 0.53 |
| `grill pok chop` | Grilled Pork Chop | 0.92 | 0.50 |
| `beef nudel sup` | Beef Noodle Soup | 0.92 | 0.46 |
| `fry chicken wing` | Fried Chicken Wings | 0.87 | 0.26 |
| `sesar salat` | Caesar Salad | 0.82 | 0.30 |
| `peach t` | Peach Tea | 0.93 | 0.50 |
| `chis burger` | Cheeseburger | 0.88 | 0.43 |
| `french fry` | French Fries | 0.88 | 0.42 |
| `mushroom risoto` | Mushroom Risotto | 0.99 | 0.41 |
| `vanila mil sek` | Vanilla Milkshake | 0.87 | 0.35 |

**14/14 đúng**, điểm thấp nhất 0.82, cách biệt thấp nhất 0.26.

Còn với thứ *không có* trên menu:

| Khách nói | Hạng 1 | Điểm | Cách biệt |
|---|---|---|---|
| `hamburger` | Cheeseburger | **0.67** | **0.35** |
| `coca cola` | Caesar Salad | 0.48 | 0.13 |
| `hello can you hear me` | Iced Lemon Tea | 0.45 | 0.08 |
| `table for four` | Grilled Pork Chop | 0.45 | 0.05 |
| `do you have pho` | Beef Noodle Soup | 0.32 | 0.01 |
| `pizza` | Peach Tea | 0.29 | 0.05 |

> **`hamburger` → Cheeseburger là false positive thật.** Điểm 0.67 với cách biệt 0.35 sẽ lọt qua nếu
> bạn chỉ dùng luật cách-biệt. Chúng *thật sự* gần nhau về âm — đây không phải lỗi thuật toán mà là
> bản chất bài toán. Bắt buộc phải có **ngưỡng điểm tuyệt đối**.

Ngưỡng an toàn theo số liệu trên: **`ACCEPT = 0.75`, `MARGIN = 0.20`**.

- Mọi ca đúng: điểm ≥ 0.82, cách biệt ≥ 0.26 → qua hết.
- Mọi ca sai: điểm ≤ 0.67 → chặn hết, kể cả `hamburger`.

Khoảng 0.67–0.82 là vùng đệm. Nếu menu thật có cả "Hamburger" lẫn "Cheeseburger", lưới ngữ âm **phải**
trả `ambiguous` và để agent hỏi lại — đó là hành vi đúng, không phải thất bại.

> **Giới hạn phải biết.** Các số trên đạt được khi chấm **cụm tên món đã được LLM tách ra**
> (`spoken_name` mà `search_menu` nhận), không phải cả câu. Chấm nguyên câu thì khung phụ âm trùng
> lung tung và false positive tăng vọt. **Chỉ chạy lưới này trên `spoken_name`.**

### 4.4 Gắn vào đâu

Trong [`search_menu`](order/tools.py#L660), **trước** khi gọi matcher LLM:

```python
from stt.phonetic import rank

ACCEPT, MARGIN = 0.75, 0.20      # xem 4.3 — thấp hơn là nhận nhầm "hamburger"

async def search_menu(self, spoken_name: str) -> dict[str, Any]:
    ...
    scored = rank(spoken, items)
    if scored and scored[0][0] >= ACCEPT and (
        len(scored) == 1 or scored[0][0] - scored[1][0] >= MARGIN
    ):
        item = scored[0][1]
        logger.info("Phonetic hit %r -> %s (%.2f)", spoken, item.name, scored[0][0])
        return {"status": "match", "confidence": "high", "confirm_name": item.name,
                "menu_item_id": item.id, ...}
    # Không chắc: vẫn hỏi LLM, NHƯNG chỉ đưa top-8 ứng viên gần âm nhất.
    matched = await self._matcher.match(spoken, [item for _, item in scored])
```

Hai lợi ích:

1. Ca dễ được trả lời trong micro giây, không tốn một lượt LLM.
2. Ca khó vẫn dùng LLM, nhưng catalog đưa vào prompt đã được **lọc theo âm** — LLM chọn giữa 8 món
   gần âm thay vì 200 món, chính xác hơn và rẻ hơn nhiều.

Làm tương tự cho chi nhánh: [booking/matcher.py:295](booking/matcher.py#L295) — file này đã có sẵn
`match_unique_branch_name` so theo chữ; thêm tầng ngữ âm vào cùng chỗ đó.

### 4.5 Test

```python
# tests/test_phonetic.py
import pytest
from stt.phonetic import rank, similarity

MENU_NAMES = ["Chicken Zinger Combo", "Spring Rolls", "Caesar Salad",
              "Cheeseburger", "Mushroom Risotto", "French Fries"]

@pytest.mark.parametrize("spoken,name", [
    ("chicken singer combo", "Chicken Zinger Combo"),
    ("sesar salat", "Caesar Salad"),
    ("sprink rol", "Spring Rolls"),
    ("mushroom risoto", "Mushroom Risotto"),
    ("french fry", "French Fries"),
])
def test_accent_hits(spoken, name):
    best = max((similarity(spoken, n), n) for n in MENU_NAMES)
    assert best[1] == name
    assert best[0] >= 0.75              # phải qua được ngưỡng ACCEPT

def test_hamburger_is_rejected():
    """Không có Hamburger trên menu: Cheeseburger gần nhưng phải dưới ngưỡng."""
    assert similarity("hamburger", "Cheeseburger") < 0.75
```

---

## 5. Tầng 4 — sửa đường audio và VAD

### 5.1 Khai báo `noise_reduction` cho kênh điện thoại

`"noise_reduction": None` từng bỏ trống một hint mà đường điện thoại hoàn toàn trả lời được. Giờ
[stt/realtime.py](stt/realtime.py) gửi `near_field` qua hằng `NOISE_REDUCTION`:

```python
"noise_reduction": {"type": "near_field"},   # khách áp máy vào tai — mặc định hợp lý
# "far_field" nếu nhiều khách bật loa ngoài, gọi trong xe, gọi từ chỗ ồn
```

Khác với demo browser, ở đây ta **không chọn được micro của khách**: cùng một hotline sẽ có cả người
áp máy lẫn người bật loa ngoài trong xe. Nên:

1. Chọn theo đa số thực tế của hotline, đo bằng harness mục 7 trên **bản ghi cuộc gọi thật**.
2. Nếu hai nhóm chênh nhau rõ rệt, đây là tham số đáng đặt theo từng cuộc gọi — nhưng chỉ làm sau khi
   có số, đừng làm trước.

> **Đừng port gating echo từ demo browser sang.** Trên đường Telnyx không có vòng lặp loa→mic:
> `telnyx_stream_track: "inbound_track"` ([config.py:70](config.py#L70)), và `_on_media` trong
> [telephony/telnyx/stream.py](telephony/telnyx/stream.py) bỏ thẳng track `outbound` — *"our own audio
> echoed back; never feed it to STT"*. Echo đã bị chặn ở tầng đúng. Thêm một lớp bịt mic phía trên chỉ
> làm mất đầu câu của khách và giết barge-in.

### 5.2 VAD

Đã nêu ở mục 2. Bổ sung: nếu vẫn bị cắt câu, cân nhắc `semantic_vad` (SDK có hỗ trợ,
`realtime_audio_input_turn_detection_param.py`) — nó chốt lượt theo *ngữ nghĩa đã trọn ý* chứ không
theo mốc im lặng cố định. Hợp với người không bản xứ, vốn ngắt nghỉ không theo nhịp câu tiếng Anh.

---

## 6. Tầng 5 — UX khi vẫn nghe sai

Không ASR nào đạt 100%. Thiết kế để **sai vẫn cứu được**:

- **Đọc lại để xác nhận khi điểm thấp.** Matcher đã trả `confidence: high|low` — khi `low`, bắt
  agent hỏi lại một câu ngắn ("You want the *Caesar Salad*, is that right?") thay vì im lặng thêm vào
  giỏ. Vùng 0.67–0.82 ở mục 4.3 chính là vùng phải hỏi.
- **Hai lần liên tiếp không khớp → đọc menu.** `list_menu` đã sẵn; thêm luật vào system prompt:
  sau 2 lần `status: none`, đọc 5 món phổ biến nhất để khách chọn.
- **DTMF cho việc dễ sai nhất.** Số điện thoại, số người, số lượng — bấm phím luôn đúng hơn đọc, và
  trên điện thoại thật thì bàn phím đã nằm sẵn trong tay khách. Đường đi đã thông: Telnyx bắn sự kiện
  `dtmf` → [stream.py](telephony/telnyx/stream.py) → `EVENT_DTMF` →
  [session.py:1011](bridge/session.py#L1011), kèm sẵn debounce, timeout menu và ngưỡng bấm sai. Việc
  còn lại chỉ là dạy prompt biết lúc nào nên mời khách bấm phím.
- **Nói chậm lại và dùng câu ngắn.** Người không bản xứ nghe agent cũng khó như agent nghe họ. Câu
  agent càng ngắn, khách trả lời càng gọn, ASR càng dễ.
- **Đừng để lượt trống trôi qua.** [session.py:723](bridge/session.py#L723) đã log `"Người gọi:
  (trống — STT không ra chữ)"`. Lượt trống nên kích hoạt một câu gợi ý ("Sorry, I didn't catch that"),
  không nên im.

---

## 7. Đo lường: đừng sửa mù

Mọi thay đổi ở trên đều có thể làm tệ đi. Cần con số.

### 7.1 Log partial (đã bật)

[stt/realtime.py](stt/realtime.py#L236-L243) giờ in transcript đang chạy ở mức INFO:

```
INFO stt.realtime Người gọi (đang nói): I'd like a table for
INFO stt.realtime Người gọi (STT) callId=abc123: I'd like a table for two.
```

Nhìn chuỗi partial biết được model **đang phân vân** ở đâu — thường chỗ nó đổi ý giữa chừng chính là
chỗ thiếu keyword.

### 7.2 Bộ test 20–30 câu

Thu từ chính người dùng thật (hoặc đồng nghiệp nói giọng tương tự):

```
audio/eval/
  001.wav   001.txt   # "I'd like two chicken zinger combos"
  002.wav   002.txt   # "a table for four at seven pm"
  ...
```

Yêu cầu: PCM16 mono 24 kHz, và **phải thu qua đúng đường Telnyx thật** — gọn nhất là dump khối
`pcm24` mà `_on_media` trong [telephony/telnyx/stream.py](telephony/telnyx/stream.py) đẩy vào bridge.
Thu bằng micro laptop rồi đem đi đo là tự lừa mình: bản ghi sạch làm *mọi* model trông giỏi hơn thực
tế, rồi bạn chọn model theo một kênh truyền mà mình không hề chạy. Trộn ba nhóm, mỗi nhóm ~1/3:

1. **Giọng bản xứ** — chuẩn tham chiếu, để biết trần trên ở đâu.
2. **Giọng không bản xứ** (giọng của bạn và người dùng thật) — ca thật đang hỏng.
3. **Câu khó có chủ đích**: tên món dài, tên món hiếm ("Zinger", "Risotto"), câu một từ ("Yes", "Two").

### 7.3 Script so model

```python
# scripts/stt_eval.py  (chạy: .venv/bin/python scripts/stt_eval.py)
import asyncio, base64, pathlib, wave
from openai import AsyncOpenAI

MODELS = ["gpt-4o-mini-transcribe", "gpt-4o-transcribe", "gpt-live-transcribe"]
KEYWORDS = ["Chicken Zinger Combo", "Zinger", "Mushroom Risotto", "Caesar Salad"]

async def run(client, model, pcm, keywords):
    transcription = {"model": model}
    if model in {"gpt-transcribe", "gpt-live-transcribe"}:
        transcription |= {"languages": ["en"], "keywords": keywords}
    else:
        transcription["language"] = "en"
    out = []
    async with client.realtime.connect(extra_query={"intent": "transcription"}) as conn:
        await conn.session.update(session={
            "type": "transcription",
            "audio": {"input": {
                "format": {"type": "audio/pcm", "rate": 24000},
                "transcription": transcription,
                "turn_detection": {"type": "server_vad", "silence_duration_ms": 800},
            }},
        })
        for i in range(0, len(pcm), 9600):                 # ~200 ms
            await conn.input_audio_buffer.append(audio=base64.b64encode(pcm[i:i+9600]).decode())
        await conn.input_audio_buffer.commit()
        async for event in conn:
            if "transcription.completed" in getattr(event, "type", ""):
                out.append(getattr(event, "transcript", ""))
                break
    return " ".join(out)

async def main():
    client = AsyncOpenAI()
    for wav_path in sorted(pathlib.Path("audio/eval").glob("*.wav")):
        with wave.open(str(wav_path)) as w:
            pcm = w.readframes(w.getnframes())
        truth = wav_path.with_suffix(".txt").read_text().strip()
        print(f"\n{wav_path.name}  truth: {truth!r}")
        for model in MODELS:
            for kw in ([], KEYWORDS):
                text = await run(client, model, pcm, kw)
                print(f"  {model:26} {'kw' if kw else '  '}  {text!r}")

asyncio.run(main())
```

### 7.4 Chỉ số cần theo

| Chỉ số | Cách tính | Vì sao |
|---|---|---|
| **WER** | `editdistance(hyp, ref) / len(ref)` theo từ | Chỉ số chuẩn, nhưng không phản ánh cái đau thật |
| **Keyword recall** | % câu mà tên món đúng xuất hiện trong transcript | **Đây mới là cái quyết định đơn có đặt được không** |
| **Match rate** | % `search_menu` trả `status: match` | Đo end-to-end sau cả lưới ngữ âm |
| **False match rate** | % `match` chọn sai món | Ngưỡng ở 4.3 tồn tại vì chỉ số này; đừng chỉ tối ưu match rate |
| **Turn fragmentation** | số lượt `completed` / số câu thật | Bắt lỗi VAD cắt câu (mục 1.4) |

WER giảm 3% mà keyword recall tăng 30% thì đó là thắng lớn — ưu tiên chỉ số thứ hai. Và luôn theo dõi
**false match rate** song song: nới ngưỡng thì match rate tăng, nhưng khách nhận nhầm món.

---

## 8. Chi phí

Theo các nguồn tổng hợp giá (tháng 9/2026):

| Model | Giá / phút audio | Ghi chú |
|---|---|---|
| `gpt-live-transcribe` | ~$0.017 (~$1/giờ) | Streaming, nhận `keywords` |
| `gpt-4o-transcribe` | ~$0.006 | Đang dùng |
| `gpt-transcribe` | ~$0.0045 | File, không hợp realtime |

Đắt hơn ~2.8× so với hiện tại. Đổi lại: mỗi cuộc gọi hỏng vì nghe sai tên món tốn nhiều hơn thế rất
nhiều — thêm lượt LLM, thêm TTS, khách bực, đơn sai. Với cuộc gọi 3 phút, chênh lệch là **khoảng
$0.03**.

Lưới ngữ âm (mục 4) còn **tiết kiệm** tiền: mỗi lần khớp trong bộ nhớ là một lần không gọi
`gpt-4o-mini` cho matcher.

> Giá từ nguồn tổng hợp bên thứ ba, không phải bảng giá chính thức trong tay tôi — kiểm tra lại trên
> trang pricing của OpenAI trước khi đưa vào dự toán.

---

## 9. Trạng thái triển khai

Toàn bộ phần code trong tài liệu này đã được implement. 251 test pass.

| Bước | Việc | Trạng thái |
|---|---|---|
| 1 | Harness đo: [scripts/stt_eval.py](scripts/stt_eval.py) | ✅ script sẵn sàng — **cần bạn thu `audio/eval/*.wav`** |
| 2 | VAD 0.45 / 400 / 800 ms, `languages`, `noise_reduction: near_field`, sửa default lệch | ✅ [stt/realtime.py](stt/realtime.py), [config.py](config.py) |
| 3 | A/B `delay`, `near_field` vs `far_field` | ⏳ cần bản ghi cuộc gọi thật |
| 4 | [stt/context.py](stt/context.py) + `update_context`, đẩy context ở init → catalog → menu | ✅ [bridge/session.py](bridge/session.py) |
| 5 | [stt/phonetic.py](stt/phonetic.py) gắn vào `search_menu`, `add_to_cart`, matcher chi nhánh | ✅ |
| 6 | Luật đọc lại xác nhận khi confidence thấp | ✅ [llm/stream.py](llm/stream.py) |
| 7 | Dọn `del locale` / `update_language` chết và câu "may speak Vietnamese" | ✅ |

Thêm ngoài kế hoạch, vì đo mới lộ ra:

- **Preload menu ngay khi khóa được chi nhánh** ([bridge/session.py](bridge/session.py)). Không có nó
  thì tên món chỉ tới STT **sau** khi khách đã gọi món — tức là muộn đúng một lượt. Đổi lại: mỗi cuộc
  gọi tốn thêm một lần đọc menu, kể cả cuộc gọi chỉ đặt bàn.
- **Bỏ field bị từ chối rồi gửi lại** thay vì để cả session STT chết vì một tham số.
- **Không đổi sang `gpt-live-transcribe`** — xem 1.1.

Còn lại cho bạn: **bước 1 và 3**. Không có baseline thì không biết thay đổi nào giúp, cái nào hại —
và với ASR, cảm giác chủ quan sai rất thường xuyên.

---

## 10. Nguồn

- [Realtime transcription — OpenAI](https://developers.openai.com/api/docs/guides/realtime-transcription) — payload `session.update`, `prompt` / `keywords` / `languages` / `delay`, sự kiện delta & completed
- [Transcription — OpenAI](https://developers.openai.com/api/docs/guides/transcription) — "prompt là bối cảnh, keywords là thuật ngữ literal; keywords là hint chứ không ép output"
- [Migrate from Whisper to GPT-Transcribe / GPT-Live-Transcribe](https://developers.openai.com/cookbook/examples/migrating_from_whisper_to_gpt_transcribe) — cấm gửi cả `language` lẫn `languages`; ràng buộc ký tự của keyword
- [GPT-Live-Transcribe — OpenAI models](https://developers.openai.com/api/docs/models/gpt-live-transcribe)
- [Introducing GPT-transcribe and GPT-live-transcribe in Microsoft Foundry](https://techcommunity.microsoft.com/blog/azure-ai-foundry-blog/introducing-gpt-transcribe-and-gpt-live-transcribe-in-microsoft-foundry/4541740) — cải thiện ở giọng có accent, audio đa ngôn ngữ, câu ngắn, danh từ riêng
- [GPT-Transcribe vs GPT-Live-Transcribe: API & Pricing — CometAPI](https://www.cometapi.com/gpt-transcribe-vs-gpt-live-transcribe/) và [OpenAI Transcription Pricing — costgoat](https://costgoat.com/pricing/openai-transcription) — bảng giá tham khảo
- SDK đã cài trong `.venv` (`openai 3.14.1`): `openai/types/realtime/audio_transcription_param.py`, `realtime_transcription_session_audio_input_turn_detection_param.py` — nguồn chuẩn nhất cho tên field và giá trị hợp lệ
