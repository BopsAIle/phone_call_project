# 14 — Cache Redis & đồng bộ catalog

Files: `AI/cache/redis_store.py` (444 dòng), `AI/sync/poller.py`, `AI/sync/models.py`.

## Vấn đề

Đầu mỗi cuộc gọi, AI phải biết: nhà hàng nào ứng với số này, có những chi nhánh nào, thực
đơn ra sao. Gọi HTTP sang BE mỗi lần thì:

- Tốn 50–200 ms ngay lúc nhạy cảm nhất (khách vừa nhấc máy)
- BE sập là mọi cuộc gọi sập theo

Nên có một **snapshot trong Redis**, làm mới định kỳ ở tác vụ nền.

> **Hoàn toàn tùy chọn.** `REDIS_URL` rỗng ⇒ không cache, không syncer, mọi thứ chạy như
> phiên bản đầu, chỉ là mỗi lần phải hỏi BE. Đây là chủ ý: không mặc định trỏ vào
> `localhost`, tránh phụ thuộc ngầm.

## Vì sao cần "generation"

Cách ngây thơ: ghi đè từng key khi dữ liệu đổi. Vấn đề: trong lúc ghi đè, một cuộc gọi
đang chạy có thể đọc được **nửa cũ nửa mới** — thấy chi nhánh mới nhưng thực đơn cũ.

Cách của dự án: mỗi lần đồng bộ ghi vào **một không gian key hoàn toàn mới** ("generation"),
rồi **đổi con trỏ** một phát duy nhất.

```
aibridge:catalog:gen              ← bộ đếm
aibridge:catalog:pointer          ← trỏ tới generation đang phục vụ
aibridge:catalog:<gen>:version    ← vân tay nội dung
aibridge:catalog:<gen>:hotline:<digits>
aibridge:catalog:<gen>:menu:<branch_id>
aibridge:catalog:<gen>:index
aibridge:sync:lock                ← khóa ghi
```

`swap_generation()` ghi đủ generation mới rồi mới dời pointer. Cuộc gọi hoặc thấy toàn bộ
snapshot cũ, hoặc toàn bộ snapshot mới — không bao giờ thấy nửa vời.

### Ghim generation cho từng cuộc gọi

```python
async def _pin_cache_generation(self):
    self.session.cache_generation = await self._cache.current_generation()
```

Một cuộc gọi **ghim** generation ở lần đọc đầu tiên và dùng nó suốt cuộc gọi. Syncer có
đổi pointer giữa chừng cũng không làm thực đơn nhảy giữa câu.

`CACHE_GENERATION_TTL` (mặc định 10800 giây = 3 giờ) là hạn dùng của một generation cũ —
đủ dài để không xóa nhầm snapshot mà một cuộc gọi đang dở dang còn đang dùng.

## Syncer nền — `AI/sync/poller.py`

```python
async def run_forever(self):
    while True:
        locked = await self._acquire_lock()     # nhiều instance chỉ một cái ghi
        if not locked: sleep ngắn; continue
        try:
            payload = await self._fetch()       # GET /restaurants + GET /branches
            await self._commit(payload)
            self._delay = self._interval        # 300 giây
        except SyncUnavailable:
            self.degraded = True
            self._delay = min(self._delay * 2, self._max_backoff)   # tối đa 2400 giây
        await sleep(self._delay)
```

Ba cơ chế đáng chú ý:

- **Khóa ghi** (`aibridge:sync:lock`, TTL 60 giây). Chạy nhiều instance AI Bridge cùng
  lúc thì chỉ một cái được ghi; những cái khác đọc snapshot chung.
- **Backoff nhân đôi.** BE sập → 300 → 600 → 1200 → 2400 giây, thay vì đập cửa liên tục.
  BE sống lại thì trở về nhịp thường ngay.
- **Cờ `degraded`.** Hiện ra ở `/health` để bạn nhìn thấy mà không phải đọc log.

### Vân tay nội dung — `catalog_version()`

`AI/sync/models.py` băm nội dung catalog (chi nhánh + món + nhà hàng đã sắp xếp) thành một
chuỗi version. Nội dung không đổi ⇒ version không đổi ⇒ khỏi ghi generation mới. Tiết kiệm
cả I/O lẫn chỗ trong Redis.

## Trong một cuộc gọi

```
_load_catalog()
  ├─ _restaurant_from_cache()           ← Redis, đã ghim generation
  └─ nếu miss → RestaurantClient.find_by_hotline()   ← HTTP tới BE
                 └─ ghi ngược vào cache (CACHE_TTL_SECONDS, mặc định 600 giây)
```

Thực đơn cũng vậy: `OrderTools._ensure_menu()` → session → Redis → HTTP, và HTTP thành
công thì ghi ngược (`_write_through_menu`).

Mọi thao tác cache đều bọc `try/except`: Redis hỏng thì log rồi đi tiếp bằng HTTP.
**Cache không bao giờ được làm chết cuộc gọi.**

## Nhìn tình trạng cache

```bash
curl http://127.0.0.1:8071/health
```

```json
{
  "status": "ok",
  "cache": {
    "enabled": true,        // REDIS_URL có đặt không
    "ready": true,          // đã có snapshot hợp lệ chưa
    "degraded": false,      // syncer có đang lỗi không
    "generation": "g42",
    "version": "…",
    "restaurants": 3, "hotlines": 5, "menus": 7,
    "last_sync_at": "2026-09-18T02:31:00Z",
    "last_sync_error": null,
    "next_poll_in_s": 240
  }
}
```

## Ép đồng bộ ngay

```bash
curl -X POST http://127.0.0.1:8071/internal/sync/refresh \
     -H "Authorization: Bearer $AI_BRIDGE_TOKEN"
```

Dùng khi bạn vừa sửa thực đơn trên dashboard và muốn AI thấy ngay, không đợi hết 300 giây.
Không có token → 401. Syncer đang tắt → 503.

## Tiếp theo

→ [15 — Backend NestJS](15-backend-nestjs.md)
