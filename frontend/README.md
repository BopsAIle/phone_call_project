# Frontend thu âm — demo trình duyệt cho AI Bridge

Folder này **tách khỏi** pipeline Python. Nó giả lập phía “backend điện thoại”: mở micro, gửi PCM 16 kHz lên `/v1/bridge`, phát audio agent, và xóa hàng phát khi nhận `interrupt`.

Không đụng Twilio / mu-law. Dùng tai nghe khi test — loa máy sẽ lọt mic và dễ kích barge-in giả.

```
Trình duyệt (folder này)  --WebSocket PCM16 16 kHz-->  AI Bridge (python app.py)
```

## Chạy

Cần **hai process**: server AI và UI.

### 1. Server AI (repo gốc)

Trong `phone_call_project/`:

```bash
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

Điền `OPENAI_API_KEY` và `AI_BRIDGE_TOKEN` trong `.env`, rồi:

```bash
python app.py
```

Health: `http://127.0.0.1:8080/health`

### 2. UI thu âm (folder này)

```bash
cd frontend
copy .env.example .env
```

Trong `frontend/.env`, đặt `VITE_AI_BRIDGE_TOKEN` **trùng** `AI_BRIDGE_TOKEN` của server. URL mặc định: `ws://127.0.0.1:8080/v1/bridge`.

```bash
npm install
npm run dev
```

Mở `http://localhost:5173`. Dán token nếu chưa có trong `.env`, nhấn **Kiểm tra /health**, rồi **Gọi**. Cho phép micro. Agent đọc câu chào, sau đó nói bình thường.

Trình duyệt **không** gắn được header `Authorization` trên WebSocket, nên UI gửi token qua `?token=` (server đã nhận cả header Bearer lẫn query).

## Wire

Khớp [hợp đồng AI Bridge](../documents/backend_contract/ai-bridge-contract.md):

| Hướng | Frame | Nội dung |
| --- | --- | --- |
| UI → AI | Text | `session.init` (`callId`, `storeName`, `timezone`, `locale`, `greeting`) |
| UI → AI | Binary | PCM16 LE mono 16 kHz, ~100 ms / 3200 byte |
| AI → UI | Binary | PCM agent, cùng định dạng |
| AI → UI | Text | `{"event":"interrupt"}` khi barge-in — UI dừng playback ngay |

Micro máy thường 44.1/48 kHz; `src/pcm.ts` resample tuyến tính xuống 16 kHz rồi đóng frame 3200 byte.

## Cấu trúc

```
frontend/
|-- index.html
|-- src/
|   |-- main.ts        # Nút Gọi/Cúp, form, nhật ký
|   |-- bridge.ts      # WebSocket + session.init
|   |-- capture.ts     # getUserMedia + AudioWorklet
|   |-- playback.ts    # Hàng đợi PCM + flush khi interrupt
|   |-- pcm.ts         # Resample / PCM16 / frame 100 ms
|   |-- protocol.ts    # Hằng số wire
|   `-- viz.ts         # Vòng sóng mic (xanh) / agent (đồng)
`-- vite.config.ts     # Proxy /v1/bridge và /health (tuỳ chọn)
```

Có thể để URL là `/v1/bridge` để đi qua proxy Vite thay vì nối thẳng cổng 8080.

## Phạm vi

**Có:** thu mic, chào, hội thoại giọng, barge-in, mute, đổi token/URL/câu chào trên UI.

**Không có:** Twilio, đặt bàn, transcript trên màn hình (hợp đồng v1 không gửi text).
