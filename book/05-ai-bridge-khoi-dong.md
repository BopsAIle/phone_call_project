# 05 — AI Bridge khởi động

Chương này lần theo đúng thứ tự code chạy, từ lúc bạn gõ `python app.py` đến lúc một
cuộc gọi được nhận.

## Bước 1 — `app.py`

File điểm vào chỉ 25 dòng (`AI/app.py`):

```python
settings = load_settings()          # đọc .env → một object Settings
logging.basicConfig(...)            # cấu hình log theo LOG_LEVEL
app = create_app(settings)          # dựng FastAPI app

if __name__ == "__main__":
    uvicorn.run("app:app", host=settings.ai_bridge_host, port=settings.ai_bridge_port)
```

Vì uvicorn được gọi bằng chuỗi `"app:app"`, thư mục làm việc **phải** là `AI/`.

## Bước 2 — `load_settings()` (`AI/config.py`)

Đọc mọi biến môi trường một lần, ép kiểu, và đặt giá trị mặc định. Đây là **nơi duy nhất**
trong repo đọc `os.getenv` cho cấu hình — phần còn lại nhận object `Settings`.

Các giá trị mặc định đáng chú ý đều có comment giải thích *vì sao* ngay trong file, ví dụ
vì sao `stt_silence_duration_ms` là 800 chứ không phải 450.

## Bước 3 — `create_app()` (`AI/bridge/server.py`)

Đây là **composition root**: nơi duy nhất tạo ra các đối tượng dịch vụ và nối chúng lại.

```
create_app(settings)
 ├─ cảnh báo nếu thiếu AI_BRIDGE_TOKEN hoặc OPENAI_API_KEY
 ├─ tạo AsyncOpenAI client  (dùng chung cho STT, LLM, TTS)
 ├─ tạo OpenAiLlm, OpenAiTts, RestaurantClient, OrderClient,
 │        OpenAiBranchMatcher, OpenAiMenuMatcher, CallLogClient
 ├─ cất tất cả vào app.state
 ├─ định nghĩa build_pipeline(socket)  ← hàm tạo một cuộc gọi
 └─ khai báo route:
      GET  /health
      POST /internal/sync/refresh
      WS   /v1/bridge          (nếu BRIDGE_ENABLED)
      POST /telnyx/webhook     (nếu TELNYX_ENABLED)
      WS   /telnyx/media       (nếu TELNYX_ENABLED)
```

### `app.state` là gì

`app.state` là "túi đồ" của FastAPI gắn vào object `app`, sống suốt đời tiến trình.
Restart là mất; tạo lại ở `create_app()`. Trong dự án này nó giữ: `openai_client`, `llm`,
`tts`, `stt_factory`, `restaurant_client`, `order_client`, hai matcher, `call_log_client`,
`catalog_cache`, `catalog_syncer`, và hàm `build_pipeline`.

### Vì sao mọi thứ đều có thể tiêm vào (inject)

Chữ ký của `create_app` nhận cả chục tham số tùy chọn (`llm=`, `tts=`, `stt_factory=`,
`restaurant_client=`…). Không phải để cấu hình lúc chạy thật — mà để **test** thay chúng
bằng đối tượng giả. Xem `AI/tests/fakes.py` và [chương 18](18-kiem-thu.md).

## Bước 4 — `lifespan`: cache và đồng bộ

Trước khi nhận request đầu tiên, FastAPI chạy hàm `lifespan`:

1. Nếu `REDIS_URL` có giá trị → tạo `CatalogCache`, kết nối (có timeout).
   Lỗi ở bước này **không làm chết app**: nó log rồi chạy tiếp không cache.
2. Nếu có cache và `SYNC_ENABLED` → tạo `CatalogSyncer`.
3. Gọi `syncer.warm_once()` — kéo catalog lần đầu, có timeout.
4. Tạo task nền `syncer.run_forever()` để định kỳ kéo lại.
5. Khi app tắt: hủy task, đóng syncer, đóng Redis, đóng Telnyx client.

Nguyên tắc xuyên suốt: **cache là tiện nghi, không phải điều kiện sống**. Redis chết thì
cuộc gọi vẫn chạy, chỉ là mỗi lần phải hỏi BE qua HTTP. Chi tiết:
[chương 14](14-cache-va-sync.md).

## Bước 5 — Một kết nối tới

### Đường `/v1/bridge`

```python
@app.websocket("/v1/bridge")
async def bridge(websocket):
    if not _bearer_authorized(websocket, token):
        await websocket.close(code=1008, reason="Unauthorized"); return
    await websocket.accept()
    pipeline = build_pipeline(websocket)
    await pipeline.run()
```

Xác thực chấp nhận **hai dạng** token, vì hai loại client khác nhau:

- Header `Authorization: Bearer <token>` — backend thoại tự viết gửi được.
- Query `?token=<token>` — trình duyệt **không** gắn được header vào WebSocket, nên
  UI demo phải dùng cách này.

Token rỗng ⇒ từ chối mọi kết nối (không có chế độ "mở toang").

### Đường Telnyx

Xem [chương 13](13-telnyx.md). Điểm chung: cả hai cuối cùng đều gọi
`build_pipeline(socket)` rồi `await pipeline.run()`.

## Bước 6 — `build_pipeline()`

```python
def build_pipeline(socket):
    return CallPipeline(
        socket,
        stt=app.state.stt_factory(),     # MỘT kết nối STT MỚI cho mỗi cuộc gọi
        llm=app.state.llm,               # dùng chung
        tts=app.state.tts,               # dùng chung
        restaurant_client=..., order_client=..., matcher=..., menu_matcher=...,
        catalog_cache=..., call_log_client=...,
        # + các tham số tinh chỉnh lấy từ settings
    )
```

Điểm cần nhớ: **STT là per-call, LLM/TTS là dùng chung**. STT là một kết nối WebSocket
stateful tới OpenAI, mỗi cuộc gọi phải có riêng. LLM và TTS là client HTTP không trạng
thái, dùng chung được.

## Sơ đồ tóm tắt

```
python app.py
   │
   ├─ load_settings()  ──────────────────────> Settings (từ .env)
   │
   └─ create_app(settings)
        ├─ tạo client dùng chung  ──────────>  app.state
        ├─ lifespan: Redis + syncer
        └─ routes
             │
   [một cuộc gọi tới]
             │
             └─ build_pipeline(socket) ──> CallPipeline(...) ──> .run()
                                                                    │
                                                            [chương 06]
```

## Tiếp theo

→ [06 — Vòng đời một cuộc gọi](06-vong-doi-cuoc-goi.md)
