# AI Bridge - pipeline giọng nói cho cuộc gọi điện thoại

Dịch vụ WebSocket nhận audio người gọi (PCM) và trả audio agent (PCM). Backend điện thoại (Twilio) **không** thấy OpenAI, resample, hay lịch sử LLM - chỉ thấy socket mô tả trong [hợp đồng AI Bridge](documents/backend_contract/ai-bridge-contract.md).

v1 sở hữu **audio vào -> audio ra**. Đặt bàn và đặt món (ship/mang về) chạy in-process; RAG và chuyển lễ tân vẫn hoãn.

```
Nguoi goi PSTN  <->  Twilio (8 kHz mu-law)  <->  Backend dien thoai  <->  AI Bridge
                                                                        PCM16 24 kHz WebSocket
```

Sơ đồ: người gọi PSTN nối Twilio, Twilio nối backend điện thoại, backend nối AI Bridge (repo này) bằng PCM16 24 kHz trên WebSocket.

---

## Tổng quan luồng

Pipeline **cascaded** (nối tầng): Realtime API chỉ dùng cho STT + VAD. LLM và TTS là HTTP riêng - không dùng speech-to-speech.

```
PCM 24 kHz (nguoi goi)
        |
        v  (khong resample: wire da 24 kHz)
   OpenAI Realtime STT  (server_vad, 800 ms im lang)
        |  transcript cuoi
        v
   Chat Completions     (gpt-4o-mini, stream)
        |  flush tung cau (. ? ! ... xuong dong, khong o dau phay)
        v
   OpenAI TTS           (pcm 24 kHz)
        |  (khong downsample: gui thang ra wire)
        v
PCM 24 kHz (agent)  ->  backend
```

### Vòng đời một cuộc gọi

1. Backend mở WebSocket tới `/v1/bridge` kèm `Authorization: Bearer <token>`.
2. Gửi `session.init` (JSON): `callId`, `storeName`, `timezone`, `locale`, `greeting`.
3. AI nói **nguyên văn** `greeting` qua TTS - câu này mang disclosure trợ lý tự động.
4. Audio người gọi chảy liên tục vào STT. Khi VAD thấy hết lượt -> transcript cuối -> LLM -> TTS từng câu.
5. Nếu người gọi nói **trong lúc** agent đang chào / suy nghĩ / nói: barge-in. Abort LLM/TTS cũ, gửi `{"event":"interrupt"}` **sau** frame audio cuối đã gửi, rồi nghe lượt mới.
6. Backend đóng socket khi cuộc gọi kết thúc. Session và kết nối Realtime bị giải phóng. v1 **không** resume - reconnect là session mới, history rỗng.

Wire trên socket chỉ có hai loại frame:

| Hướng | Frame | Nội dung |
| --- | --- | --- |
| Backend -> AI | Text | JSON `session.init` |
| Backend -> AI | Binary | Audio người gọi, PCM16 LE mono 24 kHz, ~100 ms / 4800 byte |
| AI -> Backend | Binary | Audio agent, cùng định dạng |
| AI -> Backend | Text | `{"event":"interrupt"}` khi barge-in |

Auth: Bearer token lúc handshake. Endpoint: `ws://<host>:8071/v1/bridge` (local) / `wss://<host>/v1/bridge` (deploy).

Chi tiết state machine, resample, và thứ tự barge-in: [documents/ai-pipeline.md](documents/ai-pipeline.md).

**Gọi thẳng qua Telnyx** (không cần backend điện thoại riêng): bật `TELNYX_ENABLED=true`.
Kiến trúc ở [documents/telnyx-integration.md](documents/telnyx-integration.md), các bước
thiết lập trên portal ở [documents/telnyx-setup.md](documents/telnyx-setup.md).

---

## Cấu trúc thư mục

```
phone_call_project/
|-- app.py                 # Entrypoint uvicorn; tao FastAPI app
|-- config.py              # Settings tu bien moi truong
|-- requirements.txt
|-- pytest.ini
|-- .env.example
|
|-- bridge/
|   |-- server.py          # Accept WS, auth Bearer, /health, /v1/bridge
|   `-- session.py         # State machine cuoc goi, greeting, LLM->TTS, barge-in
|
|-- audio/
|   `-- resample.py        # Util resample PCM16 (vd narrowband <-> 24 kHz), frame tron sample
|
|-- stt/
|   `-- realtime.py        # OpenAI Realtime transcription + server_vad
|
|-- llm/
|   `-- stream.py          # Chat stream + sentence aggregator + system prompt
|
|-- tts/
|   `-- openai_tts.py      # TTS PCM 24 kHz -> thang ra wire (khong downsample)
|
|-- turn/
|   `-- barge_in.py        # Abort viec stale; interrupt sau audio da gui cuoi
|
|-- booking/               # Dat ban: resolve_branch, create_booking
|-- order/                 # Dat mon: menu, gio hang, create_order
|-- calls/                 # Luu thong tin cuoc goi + transcript len BE
|-- obs/                   # Do do tre tung chang (mot dong TURN moi luot)
|
|-- tests/                 # Unit + WS tests voi fake STT/LLM/TTS
|
`-- documents/
    |-- ai-pipeline.md     # Spec pipeline (team AI)
    |-- order-api-contract.md
    `-- backend_contract/
        `-- ai-bridge-contract.md
```

| Module | Trách nhiệm |
| --- | --- |
| `bridge/server.py` | Handshake, Bearer, phân binary vs text |
| `bridge/session.py` | State, history, `generation_id`, `playing` |
| `audio/resample.py` | Đổi sample rate, không cắt sample 16-bit xuyên frame |
| `stt/realtime.py` | Transcription + sự kiện VAD (`speech_started` -> barge-in) |
| `llm/stream.py` | Stream chat, cắt câu sang TTS |
| `tts/openai_tts.py` | Synth PCM 24 kHz, yield chunk (khớp wire, không downsample) |
| `turn/barge_in.py` | Đảm bảo thứ tự hợp đồng mục 6.3: `interrupt` sau audio cuối |
| `telephony/telnyx/` | Adapter Telnyx: webhook Call Control + media stream → CallPipeline |
| `booking/` | Tool đặt bàn + HTTP booking |
| `order/` | Tool giỏ hàng / đơn ship-mang về + HTTP menu/orders |
| `calls/` | Gom transcript trong RAM, đẩy lên BE theo lô; lỗi không bao giờ làm hỏng cuộc gọi |
| `obs/timing.py` | Đồng hồ mỗi lượt nói; `scripts/turn_stats.py` tổng hợp ra p50/p90/p95 |
| `audio/recorder.py` | Ghi âm tiếng người gọi để dựng bộ đo STT (mặc định TẮT) |
| `llm/history.py` | Giữ sổ hội thoại đúng hình dạng API chấp nhận; tự chữa nếu lệch |

---

## Cách chạy

Yêu cầu: Python 3.11+ (khuyến nghị 3.12).

### 1. Cài đặt

```bash
python -m venv .venv

# Windows (PowerShell)
.venv\Scripts\Activate.ps1

# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### 2. Cấu hình

```bash
cp .env.example .env
```

Điền tối thiểu:

| Biến | Ý nghĩa |
| --- | --- |
| `OPENAI_API_KEY` | Key OpenAI - thiếu thì STT/LLM/TTS fail trên cuộc gọi thật |
| `AI_BRIDGE_TOKEN` | Bearer token backend phải gửi lúc handshake - trống thì mọi kết nối bị từ chối |

Tùy chọn: `OPENAI_MODEL`, `OPENAI_STT_MODEL`, `OPENAI_TTS_MODEL` (mặc định `tts-1`; `tts-1-hd` nếu cần chất hơn), `OPENAI_TTS_VOICE`, `TTS_CHUNK_BYTES` (mặc định `1024`), `AI_BRIDGE_HOST` (mặc định `0.0.0.0`), `AI_BRIDGE_PORT` (mặc định `8071`), `LOG_LEVEL`, `RESTAURANT_API_BASE` (mặc định `http://127.0.0.1:8070` — NestJS local, đặt bàn / đặt món).

### 3. Chạy server

```bash
python app.py
```

Hoặc:

```bash
uvicorn app:app --host 0.0.0.0 --port 8071
```

- Health: `GET http://localhost:8071/health` -> `{"status":"ok"}`
- Bridge: `ws://localhost:8071/v1/bridge` với header `Authorization: Bearer <AI_BRIDGE_TOKEN>`

Backend điện thoại (`phone_call_project_viet`) gọi tới socket này. Trong `.env` của backend:

```ini
AI_BRIDGE_URL=ws://127.0.0.1:8071/v1/bridge
AI_BRIDGE_TOKEN=<trùng AI_BRIDGE_TOKEN của repo này>
```

Mỗi cuộc gọi mở một WebSocket, gửi `session.init` (kèm `locale: "vi"`), rồi PCM 24 kHz hai chiều.

### 4. Test

Không cần key OpenAI - test dùng fake STT/LLM/TTS:

```bash
pytest
```

---

## Phạm vi v1

**Có:** STT + VAD, câu chào nguyên văn, LLM + history trong RAM, TTS, barge-in `interrupt`.

**Không có:** Twilio / mu-law / frame 20 ms (backend sở hữu), persist transcript về backend, RAG, chuyển lễ tân. Đặt bàn và đặt đơn hàng nhà hàng qua HTTP in-process, không qua WebSocket.

Socket đứt = session mới. `callId` chỉ để khớp log.

---

## Demo thu âm (frontend)

Folder [`frontend/`](frontend/) tách khỏi Python: trình duyệt thu micro, gửi PCM 24 kHz tới `/v1/bridge`, phát audio agent.

```bash
cd frontend
copy .env.example .env
# VITE_AI_BRIDGE_TOKEN trùng AI_BRIDGE_TOKEN
npm install
npm run dev
```

Chi tiết: [frontend/README.md](frontend/README.md). Trình duyệt gửi token bằng `?token=` vì WebSocket trên browser không gắn được header `Authorization`.

---

## Đo độ trễ

Mỗi lượt nói ghi một dòng `TURN` ở mức INFO:

```
TURN call=abc123 gen=7 stt_ms=812 llm_ttft_ms=430 llm_ttfs_ms=512 tts_ttfb_ms=190
     first_audio_ms=1104 llm_rounds=2 tool_ms=640 tools=search_menu,add_to_cart
     cached_tokens=3584 prompt_tokens=4102
```

Con số đáng nhìn trước tiên là **`first_audio_ms`** — từ lúc khách ngừng nói đến lúc nghe thấy tiếng.
Mọi chỉ số khác chỉ giải thích vì sao nó lớn.

```bash
.venv/bin/python app.py 2>&1 | tee app.log
.venv/bin/python scripts/turn_stats.py app.log              # p50 / p90 / p95 từng chặng
.venv/bin/python scripts/turn_stats.py app.log --call abc123 # chi tiết từng lượt
```

`cached_tokens = 0` ở mọi lượt nghĩa là bộ nhớ đệm prompt của OpenAI không trúng lần nào.

## Dựng bộ dữ liệu đo STT

`scripts/stt_eval.py` đã sẵn sàng nhưng cần audio thật. Bật ghi âm để gom:

```bash
CALL_RECORD_DIR=audio/recordings .venv/bin/python app.py    # mặc định TẮT
```

Khi bật, lời chào **tự thêm câu thông báo ghi âm** cho người gọi. File ghi âm nằm trong
`.gitignore` — đừng gỡ ra.

```bash
.venv/bin/python scripts/split_call.py audio/recordings/<tên>.wav
# nghe lại, sửa các file .txt.auto cho đúng, đổi đuôi thành .txt
.venv/bin/python scripts/stt_eval.py --prompt "$(...)"      # xem stt/context.build_prompt
```

Chỉ đoạn nào có `.txt` (do người xác nhận) mới vào bộ đo. Theo playbook §7.4: **ưu tiên tỉ lệ
nghe đúng tên món hơn tỉ lệ lỗi chữ tổng thể**, và luôn xem kèm tỉ lệ nhận nhầm.

## Lưu trữ cuộc gọi

`CALL_LOG_ENABLED=true` (mặc định) đẩy thông tin cuộc gọi và transcript lên BE:

| Endpoint | Lúc nào |
| --- | --- |
| `POST /calls/ai/start` | đầu cuộc gọi, sau khi tra được nhà hàng — idempotent theo `call_id` |
| `POST /calls/ai/{id}/messages` | theo lô trong lúc gọi (10 lượt hoặc 30 giây) |
| `POST /calls/ai/{id}/end` | lúc cúp máy, kèm lô còn lại |
| `GET /calls/{id}` | đọc lại kèm transcript — dùng khi khách khiếu nại đơn |

Transcript lấy từ thứ **hai bên thật sự đã nghe**, không phải `session.history`: câu AI chỉ được
ghi khi byte tiếng đầu tiên đã ra dây. Mọi lời gọi chạy ở task nền và nuốt lỗi — BE sập thì cuộc
gọi vẫn chạy bình thường, chỉ là không có transcript.

`call_id` cũng được gửi kèm mỗi lần tạo đơn làm **khoá chống trùng**: POST bị timeout rồi gửi lại
cũng chỉ ra một đơn.
