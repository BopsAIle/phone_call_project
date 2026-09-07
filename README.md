# AI Bridge - pipeline giọng nói cho cuộc gọi điện thoại

Dịch vụ WebSocket nhận audio người gọi (PCM) và trả audio agent (PCM). Backend điện thoại (Twilio) **không** thấy OpenAI, resample, hay lịch sử LLM - chỉ thấy socket mô tả trong [hợp đồng AI Bridge](documents/backend_contract/ai-bridge-contract.md).

v1 sở hữu **audio vào -> audio ra**. Đặt bàn và đặt món (ship/mang về) chạy in-process; RAG và chuyển lễ tân vẫn hoãn.

```
Nguoi goi PSTN  <->  Twilio (8 kHz mu-law)  <->  Backend dien thoai  <->  AI Bridge
                                                                        PCM16 16 kHz WebSocket
```

Sơ đồ: người gọi PSTN nối Twilio, Twilio nối backend điện thoại, backend nối AI Bridge (repo này) bằng PCM16 16 kHz trên WebSocket.

---

## Tổng quan luồng

Pipeline **cascaded** (nối tầng): Realtime API chỉ dùng cho STT + VAD. LLM và TTS là HTTP riêng - không dùng speech-to-speech.

```
PCM 16 kHz (nguoi goi)
        |
        v  upsample 16 kHz -> 24 kHz
   OpenAI Realtime STT  (server_vad, 800 ms im lang)
        |  transcript cuoi
        v
   Chat Completions     (gpt-4o-mini, stream)
        |  flush tung cau (. ? ! ... xuong dong, khong o dau phay)
        v
   OpenAI TTS           (pcm 24 kHz)
        |  downsample 24 kHz -> 16 kHz
        v
PCM 16 kHz (agent)  ->  backend
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
| Backend -> AI | Binary | Audio người gọi, PCM16 LE mono 16 kHz, ~100 ms / 3200 byte |
| AI -> Backend | Binary | Audio agent, cùng định dạng |
| AI -> Backend | Text | `{"event":"interrupt"}` khi barge-in |

Auth: Bearer token lúc handshake. Endpoint: `ws://<host>:8080/v1/bridge` (local) / `wss://<host>/v1/bridge` (deploy).

Chi tiết state machine, resample, và thứ tự barge-in: [documents/ai-pipeline.md](documents/ai-pipeline.md).

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
|   `-- resample.py        # 16 kHz <-> 24 kHz, frame tron sample PCM16
|
|-- stt/
|   `-- realtime.py        # OpenAI Realtime transcription + server_vad
|
|-- llm/
|   `-- stream.py          # Chat stream + sentence aggregator + system prompt
|
|-- tts/
|   `-- openai_tts.py      # TTS PCM 24 kHz -> downsample 16 kHz
|
|-- turn/
|   `-- barge_in.py        # Abort viec stale; interrupt sau audio da gui cuoi
|
|-- booking/               # Dat ban: resolve_branch, create_booking
|-- order/                 # Dat mon: menu, gio hang, create_order
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
| `tts/openai_tts.py` | Synth PCM, downsample, yield chunk |
| `turn/barge_in.py` | Đảm bảo thứ tự hợp đồng mục 6.3: `interrupt` sau audio cuối |
| `booking/` | Tool đặt bàn + HTTP booking |
| `order/` | Tool giỏ hàng / đơn ship-mang về + HTTP menu/orders |

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

Tùy chọn: `OPENAI_MODEL`, `OPENAI_STT_MODEL`, `OPENAI_TTS_MODEL` (mặc định `tts-1`; `tts-1-hd` nếu cần chất hơn), `OPENAI_TTS_VOICE`, `TTS_CHUNK_BYTES` (mặc định `1024`), `AI_BRIDGE_HOST` (mặc định `0.0.0.0`), `AI_BRIDGE_PORT` (mặc định `8080`), `LOG_LEVEL`, `RESTAURANT_API_BASE` (mặc định `http://127.0.0.1:3001` — NestJS local, đặt bàn / đặt món).

### 3. Chạy server

```bash
python app.py
```

Hoặc:

```bash
uvicorn app:app --host 0.0.0.0 --port 8080
```

- Health: `GET http://localhost:8080/health` -> `{"status":"ok"}`
- Bridge: `ws://localhost:8080/v1/bridge` với header `Authorization: Bearer <AI_BRIDGE_TOKEN>`

Backend điện thoại (`phone_call_project_viet`) gọi tới socket này. Trong `.env` của backend:

```ini
AI_BRIDGE_URL=ws://127.0.0.1:8080/v1/bridge
AI_BRIDGE_TOKEN=<trùng AI_BRIDGE_TOKEN của repo này>
```

Mỗi cuộc gọi mở một WebSocket, gửi `session.init` (kèm `locale: "vi"`), rồi PCM 16 kHz hai chiều.

### 4. Test

Không cần key OpenAI - test dùng fake STT/LLM/TTS:

```bash
pytest
```

---

## Phạm vi v1

**Có:** STT + VAD, câu chào nguyên văn, LLM + history trong RAM, TTS, resample, barge-in `interrupt`.

**Không có:** Twilio / mu-law / frame 20 ms (backend sở hữu), persist transcript về backend, RAG, chuyển lễ tân. Đặt bàn và đặt đơn hàng nhà hàng qua HTTP in-process, không qua WebSocket.

Socket đứt = session mới. `callId` chỉ để khớp log.

---

## Demo thu âm (frontend)

Folder [`frontend/`](frontend/) tách khỏi Python: trình duyệt thu micro, gửi PCM 16 kHz tới `/v1/bridge`, phát audio agent.

```bash
cd frontend
copy .env.example .env
# VITE_AI_BRIDGE_TOKEN trùng AI_BRIDGE_TOKEN
npm install
npm run dev
```

Chi tiết: [frontend/README.md](frontend/README.md). Trình duyệt gửi token bằng `?token=` vì WebSocket trên browser không gắn được header `Authorization`.
