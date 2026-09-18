# 05a — asyncio dễ hiểu (đọc trước khi vào code AI)

Toàn bộ AI Bridge chạy trên `asyncio`. Nếu bạn chưa quen, phần code sẽ trông như ma
thuật. Chương này giải thích **đúng những khái niệm mà repo này dùng**, bằng ví dụ lấy
thẳng từ code. Không cần biết trước gì cả.

## Vấn đề mà asyncio giải

Trong một cuộc gọi, cùng một lúc có **rất nhiều việc đang chờ**:

- chờ khách nói tiếp
- chờ OpenAI trả về chữ đã nghe được
- chờ OpenAI viết câu trả lời
- chờ OpenAI tổng hợp giọng nói
- chờ BE trả về thực đơn
- chờ đủ 7 giây xem khách có bấm phím không

Cách cũ là mỗi việc một **luồng** (thread). Nhưng để ý: chín phần mười thời gian là
**ngồi chờ mạng**, không phải tính toán. Chờ thì không cần một luồng riêng.

`asyncio` dùng **một luồng duy nhất** và một cuốn sổ ghi "ai đang chờ cái gì". Khi một
việc phải chờ, nó **trả quyền điều khiển lại**, và luồng đó đi làm việc khác ngay.

> **Ví von:** một nhân viên phục vụ giỏi. Anh ta không đứng im nhìn nồi nước sôi. Anh bật
> bếp, quay sang lau bàn, nghe chuông thì quay lại. Một người làm được việc của năm người
> — **miễn là phần lớn thời gian là chờ**.

## `async def` và `await`

```python
async def get_menu():          # hàm này CÓ THỂ tạm dừng giữa chừng
    data = await http.get(...)  # "tạm dừng ở đây, gọi tôi lại khi có kết quả"
    return data
```

Hai điều cần nhớ:

1. Gọi `get_menu()` **chưa chạy gì cả**. Nó trả về một "lời hứa" (coroutine). Phải `await`
   hoặc đưa vào task thì nó mới chạy.
2. Mỗi chữ `await` là **một điểm nhường lượt**. Giữa hai chữ `await`, code chạy liền
   mạch, không ai chen ngang được.

Điều số 2 quan trọng hơn bạn nghĩ, và cả một class trong repo dựa vào nó:

```python
def commit_tool_round(self, group: list[dict[str, Any]]) -> None:
    """Append a whole tool round in one go.

    Synchronous on purpose: the event loop cannot interleave inside `extend`, so a
    tool_calls message can never be separated from its replies.
    """
    self.history.extend(group)
```

Hàm này **cố tình không có `async`**. Vì không có `await` nào bên trong, không gì có thể
chen vào giữa. Đó chính là thứ đảm bảo lịch sử hội thoại không bị xé đôi.
→ [ch.08](08-nghi-llm.md)

## Task — việc chạy nền

`await` là "chờ cho xong rồi đi tiếp". Nhưng nhiều khi ta muốn "cứ chạy đi, tôi làm việc
khác":

```python
self._stt_start_task = asyncio.create_task(self._start_stt(), name="stt-start")
```

Đây là dòng đầu tiên của `CallPipeline.run()`. Mở kết nối STT tới OpenAI mất vài trăm mili
giây. Nếu `await` ở đây, cuộc gọi đứng im chừng đó. `create_task` nói: *bắt đầu đi, tôi
vào vòng lặp nhận tin nhắn ngay*.

Repo này tạo task ở những chỗ sau:

| Task | Vì sao chạy nền |
| --- | --- |
| `stt-start` | mở socket STT, không được chặn cuộc gọi |
| `catalog` | tra nhà hàng từ BE/Redis, chạy song song với lời chào |
| `call-work` | một lượt nói của AI (LLM + TTS) |
| `turn-sender` | vòng lặp đẩy âm thanh ra dây |
| `tts-sentence` | tổng hợp giọng cho **từng câu**, nhiều task song song |
| `dtmf-timeout` | đếm ngược chờ khách bấm phím |
| `call-hangup` | đợi phát hết tiếng rồi mới cúp máy |

**Đặt tên task** (`name="..."`) không phải để trang trí: khi có lỗi, tên hiện trong log và
bạn biết ngay task nào chết.

## Hủy task — `cancel()`

Task chạy nền thì cũng phải giết được. Khách cắt lời thì lượt nói cũ phải dừng:

```python
def _spawn(self, coro: Any) -> None:
    previous = self._work_task
    if previous is not None and not previous.done():
        previous.cancel()                       # giết lượt cũ
    self._work_task = asyncio.create_task(coro, name="call-work")
```

`cancel()` ném một `CancelledError` **vào bên trong** task, đúng tại chỗ nó đang `await`.
Nên code muốn dọn dẹp tử tế phải bắt nó:

```python
except asyncio.CancelledError:
    await player.abort()        # tắt tiếng đã
    raise                       # RỒI ném tiếp — không được nuốt
```

> **Luật bất di bất dịch:** bắt `CancelledError` để dọn dẹp thì được, nhưng **phải `raise`
> lại**. Nuốt nó đi là task trở thành zombie, không ai giết được nữa.

Mẫu "hủy rồi chờ nó chết hẳn" xuất hiện khắp `shutdown()`:

```python
task.cancel()
try:
    await task                                  # chờ nó thật sự dừng
except (asyncio.CancelledError, Exception):
    pass
```

## `shield()` — lá chắn cho việc không được phép hủy

Đây là chỗ hay nhất trong repo.

Khách cắt lời trong lúc `create_order` đang gửi lên server. Hủy task nghĩa là **mất đơn
hàng dù khách đã xác nhận**. Nhưng vẫn phải tắt tiếng ngay.

```python
if self._create_in_flight:
    logger.info("Barge-in while creating; waiting for the tool %s", self.session.tag)
    try:
        await asyncio.wait_for(asyncio.shield(work), _CREATE_GRACE_SECONDS)   # 20 giây
    except asyncio.TimeoutError:
        logger.warning("Create did not finish in %ss; cancelling", _CREATE_GRACE_SECONDS)
if not work.done():
    work.cancel()
```

- `shield(work)` — "nếu tôi bị hủy, **đừng** hủy lây sang `work`"
- `wait_for(..., 20)` — nhưng cũng không chờ quá 20 giây
- Tiếng đã tắt từ trước đó rồi, bằng một cơ chế khác ([ch.10](10-barge-in.md))

## `Lock` — cửa một người qua

Một luồng duy nhất **không** có nghĩa là không có tranh chấp. Giữa hai chữ `await`, một
task khác có thể xen vào và làm rối thứ tự.

```python
class OutboundGate:
    def __init__(self, websocket, session):
        self.lock = asyncio.Lock()

    async def send_audio(self, generation_id, pcm) -> bool:
        async with self.lock:                    # xếp hàng ở đây
            ...
            await self.websocket.send_bytes(pcm)
```

Mọi thứ đi ra socket đều qua cái lock này. Nhờ vậy, khi barge-in giành được lock, nó chắc
chắn rằng **mọi frame âm thanh trước đó đã ra dây**, và không frame cũ nào có thể đi sau
lệnh `interrupt`.

Repo còn một lock nữa: `self._turn_lock` trong `CallPipeline`, ngăn hai sự kiện cùng
chuyển lượt một lúc (ví dụ STT chốt câu đúng lúc khách bấm phím).

## `Queue` — băng chuyền giữa hai task

```python
self._sentence_qs: asyncio.Queue = asyncio.Queue()
```

`TurnPlayer` dùng queue để nối **nhiều task tổng hợp giọng** với **một task gửi**:

```
câu 1 → task TTS 1 → queue 1 ┐
câu 2 → task TTS 2 → queue 2 ├→ _sender_loop đọc TUẦN TỰ → socket
câu 3 → task TTS 3 → queue 3 ┘
```

Tổng hợp chạy song song (nhanh), nhưng gửi thì tuần tự (đúng thứ tự câu). Queue là thứ
làm được cả hai.

**Sentinel `None`** là quy ước "hết hàng":

```python
async def finish(self):
    await self._sentence_qs.put(None)    # báo sender: không còn câu nào nữa
    await self._sender
```

## `ContextVar` — biến đi theo task con

Bình thường muốn truyền thứ gì đó xuống sâu, bạn phải thêm tham số cho từng hàm. Rất
phiền khi phải xuyên bốn tầng.

`ContextVar` là biến gắn theo **ngữ cảnh thực thi**, và giá trị của nó được **sao sang task
con** lúc `create_task`:

```python
_current: ContextVar[Optional["TurnTimer"]] = ContextVar("turn_timer", default=None)

def mark_first(name: str) -> None:
    timer = _current.get()
    if timer is not None:      # không có đồng hồ nào -> không làm gì
        timer.first(name)
```

Nhờ vậy `obs/timing.py` không phải import gì trong repo, và các hàm như
`mark_first("first_audio_ms")` gọi được từ bất cứ tầng nào mà không đổi chữ ký hàm.

> **Trạng thái hiện tại:** các lời gọi `mark_first` / `bump` / `put_value` vẫn nằm trong
> `turn/barge_in.py`, `tts/openai_tts.py`, `llm/stream.py`, nhưng **không có chỗ nào tạo
> `TurnTimer`** trong pipeline nữa. Nên chúng đang là no-op. Xem
> [ch.17](17-log-do-luong-ghi-am.md).

## `try / finally` — dọn dẹp chắc chắn

```python
async def run(self) -> None:
    ...
    try:
        while not self.session.closed:
            ...
    finally:
        await self.shutdown()      # LUÔN chạy: lỗi, hủy, hay thoát bình thường
```

Trong hệ thống có task chạy nền, quên dọn là rò rỉ: socket không đóng, task chạy mãi,
tiền OpenAI vẫn trôi.

## Bẫy thường gặp

| Bẫy | Hậu quả | Cách tránh |
| --- | --- | --- |
| Quên `await` | Hàm không chạy, không báo lỗi | Python cảnh báo "coroutine was never awaited" |
| Nuốt `CancelledError` | Task không giết được | Luôn `raise` lại |
| Gọi hàm chặn (`time.sleep`, `requests`) | **Đứng cả server** | Dùng `asyncio.sleep`, `httpx.AsyncClient` |
| Giữ lock lúc `await` việc lâu | Mọi thứ khác xếp hàng theo | Thả lock trước (xem `abort_and_interrupt`) |
| `create_task` rồi quên giữ tham chiếu | Task có thể bị dọn rác giữa chừng | Gán vào `self._xxx_task` |

## Đủ rồi, vào code thôi

Bạn đã có đủ để đọc `AI/bridge/session.py`. Khi thấy `create_task`, nghĩ "việc này chạy
nền". Khi thấy `async with self.lock`, nghĩ "xếp hàng ở đây". Khi thấy `shield`, nghĩ
"cái này không được phép chết giữa chừng".

## Tiếp theo

→ [06 — Vòng đời một cuộc gọi](06-vong-doi-cuoc-goi.md)
