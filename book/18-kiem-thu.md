# 18 — Kiểm thử

## Chạy test

```bash
cd AI
.venv/bin/python -m pytest              # toàn bộ 30 file
.venv/bin/python -m pytest tests/test_session.py -v
.venv/bin/python -m pytest -k barge_in
```

Cấu hình ở `AI/pytest.ini`:

```ini
[pytest]
asyncio_mode = auto     # không cần @pytest.mark.asyncio trên từng test
testpaths = tests
pythonpath = .
```

Bên BE: `cd BE && npm test` (Jest, file `*.spec.ts`). Hiện chỉ có
`app.controller.spec.ts` — phần lớn kiểm thử của dự án nằm ở AI.

## 30 file test, nhóm theo chủ đề

| Nhóm | File |
| --- | --- |
| **Vòng đời cuộc gọi** | `test_session.py`, `test_bridge_ws.py`, `test_server_lifespan.py`, `test_call_end.py` |
| **Nghe (STT)** | `test_stt_realtime.py`, `test_stt_context.py`, `test_phonetic.py` |
| **Nghĩ (LLM)** | `test_llm_stream.py`, `test_aggregator.py`, `test_history_repair.py` |
| **Nói / cắt lời** | `test_tts.py`, `test_barge_in.py`, `test_resample.py` |
| **Đặt bàn** | `test_booking_tools.py`, `test_booking_client.py`, `test_booking_matcher.py`, `test_booking_session.py` |
| **Đặt món** | `test_order_tools.py`, `test_order_client.py`, `test_order_session.py` |
| **Cache & đồng bộ** | `test_catalog_cache.py`, `test_catalog_session.py`, `test_sync_poller.py` |
| **Điện thoại** | `test_telnyx.py`, `test_dtmf.py` |
| **Quan sát** | `test_timing.py`, `test_call_log.py`, `test_recorder.py` |

## Cách test một thứ vốn cần mạng

Không test nào gọi OpenAI, Telnyx hay Postgres thật. `AI/tests/fakes.py` cung cấp bản giả
cho mọi thứ:

| Fake | Thay cho |
| --- | --- |
| `FakeBridgeSocket` | WebSocket — có `push_text()`, `push_bytes()`, và list `sent` để kiểm tra |
| `FakeSTT` | `RealtimeTranscriptionClient` — bạn tự gọi `handler.on_transcript_completed(...)` |
| `ScriptedLlm` | LLM — trả về đúng dãy câu bạn viết sẵn |
| `ScriptedTts` / `SlowTts` | TTS — `SlowTts` cố tình chậm để test barge-in |

Cache Redis dùng `fakeredis` (có trong `requirements.txt`), nên `test_catalog_cache.py`
chạy được mà không cần Redis thật.

## Một bài test mẫu

```python
INIT = {"event": "session.init", "callId": "clx8k2...", "storeName": "Bella Vista",
        "timezone": "Europe/Berlin", "locale": "en", "greeting": "Thanks for calling..."}

async def _start_pipeline(ws, stt, llm, tts):
    pipeline = CallPipeline(ws, stt=stt, llm=llm, tts=tts)
    task = asyncio.create_task(pipeline.run())
    await asyncio.sleep(0.02)
    return pipeline, task

async def test_something(...):
    ws, stt, llm, tts = FakeBridgeSocket(), FakeSTT(), ScriptedLlm([...]), ScriptedTts()
    pipeline, task = await _start_pipeline(ws, stt, llm, tts)
    await ws.push_text(json.dumps(INIT))
    await stt.handler.on_transcript_completed("I want a table for two")
    ...
    assert ("text", '{"event":"interrupt"}') in ws.sent
    await _stop(ws, task)
```

Mẫu chung: **bơm sự kiện vào, kiểm tra `ws.sent`**. Vì `CallPipeline` chỉ biết về socket
qua bốn phương thức, việc thay nó bằng đồ giả là dễ.

Cũng chính vì thế `create_app()` nhận cả chục tham số tiêm — không phải để cấu hình lúc
chạy thật, mà để test thay được mọi thành phần.

## Hàm thuần: nơi test rẻ và đáng nhất

Vài chỗ trong repo được tách thành hàm thuần **cố tình để dễ test**:

- `is_sentence_boundary(punct, head, gap, nxt)` → `test_aggregator.py`
  (`19.000`, `Mr. Smith`, `No. 106` …)
- `repair_tool_sequence(messages)` → `test_history_repair.py`
- `TurnTimer.record()` → `test_timing.py` — trả dict, không phụ thuộc logger
- `normalize_booking_date` / `_time` / `resolve_booking_when` → `test_booking_tools.py`
- `similarity()` trong `stt/phonetic.py` → `test_phonetic.py`

Comment ngay trong code nói rõ ý đồ này, ví dụ ở `is_sentence_boundary`:
*"Pure and tiny on purpose: this is the piece worth unit-testing, and the streaming buffer
around it should stay dumb."*

## Viết thêm test

1. Thêm file vào `AI/tests/`, đặt tên `test_*.py`.
2. `async def test_...` — `asyncio_mode = auto` lo phần còn lại.
3. Dùng fake trong `tests/fakes.py`; thiếu thì thêm vào đó thay vì tự chế trong file test.
4. Sửa hành vi thì thêm test **chứng minh lỗi cũ**, đừng chỉ test đường đi đúng.

## Kiểm tra thủ công không thay được test tự động

Một số thứ chỉ lộ ra khi chạy thật:

| Cần kiểm | Cách |
| --- | --- |
| Toàn tuyến còn sống | `make check` |
| Đường Telnyx (không tốn tiền) | `./scripts/telnyx-test.sh` |
| Hội thoại thật, barge-in | UI demo `AI/frontend/` (**đeo tai nghe**) |
| Chất lượng STT | `AI/scripts/stt_eval.py` trên clip ghi âm |
| Độ trễ | `AI/scripts/turn_stats.py` trên log |
| Cuộc gọi điện thoại thật | softphone Zoiper → xem `AI/RUNBOOK.md` |

## Tiếp theo

→ [19 — Sự cố thường gặp](19-su-co-thuong-gap.md)
