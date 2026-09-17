"""Redis catalog cache: generation + pointer layout (pipeline v2 §5.5)."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field

from redis.asyncio import Redis

from booking.client import normalize_hotline, restaurant_from_api
from booking.models import Restaurant
from order.client import menu_item_from_api
from order.models import MenuItem
## Redis giống như 1 tủ khóa lớn, nhiều người dùng chung
#  aibridge là tên của tủ khóa mình đang dùng để không nhầm với app khác
DEFAULT_NAMESPACE = "aibridge"
## DEFAULT_GENERATION_TTL làthời gian mỗi key Redis có thể gắn hạn sử dụng. Hết hạn thì Redis xóa
## 10800 giây = 3 giờ
#Ví dụ như cuộc gọi đang dùng snapshot này, nhưng ta lại xóa đi vì cho rằng snapshot này không còn sử dụng được nữa
#Điều này nguy hiểm vì cuộc gọi đang dở dang
DEFAULT_GENERATION_TTL = 10800

logger = logging.getLogger(__name__)

#GenerationPayload giống như 1 đối tượng lưu trữ các thông tin về restaurant, menu
@dataclass(frozen=True)
class GenerationPayload:
    """Thùng hàng đã parse xong, sẵn sàng ghi thành một generation Redis.

    Cache không gọi API, không parse JSON HTTP. Syncer (bước sau) lọc restaurant
    active, normalize hotline, rồi nhét vào đây.

    by_hotline: số điện thoại (chỉ chữ số) → Restaurant. Một nhà hàng có thể
                gắn nhiều số, cùng object ghi hai key.
    menus:      id chi nhánh → danh sách món. Không có thì swap không ghi menu
                (menu vẫn lấy lazy + write-through sau).
    """

    by_hotline: Mapping[str, Restaurant]
    menus: Mapping[str, Sequence[MenuItem]] = field(default_factory=dict)


def _dump_restaurant(restaurant: Restaurant) -> str:
    """Đổi object Restaurant (Python) thành chuỗi JSON để Redis lưu được.

    Redis không hiểu dataclass, chỉ lưu chữ. asdict → dict, json.dumps → chuỗi.
    ensure_ascii=False giữ tiếng Việt ("Phở"), không biến thành \\u....
    """
    return json.dumps(asdict(restaurant), ensure_ascii=False)


def _dump_menu(items: Sequence[MenuItem]) -> str:
    """Đổi list MenuItem thành chuỗi JSON (một mảng) để Redis lưu được."""
    return json.dumps([asdict(item) for item in items], ensure_ascii=False)


def _load_json(raw: object) -> object | None:
    """Parse chuỗi Redis thành dict/list. JSON hỏng hoặc không phải chữ → None, không raise."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _load_restaurant(raw: object) -> Restaurant | None:
    """Chuỗi JSON Redis → Restaurant. Sai kiểu / thiếu id / JSON gãy → None.

    Dùng restaurant_from_api (cùng luật lọc branch active như HTTP v1).
    """
    data = _load_json(raw)
    if not isinstance(data, dict):
        return None
    try:
        return restaurant_from_api(data)
    except Exception:
        return None


def _load_menu(raw: object) -> list[MenuItem] | None:
    """Chuỗi JSON Redis → list MenuItem. Không phải mảng / JSON gãy → None.

    Phần tử hỏng bị bỏ; mảng rỗng hợp lệ trả [].
    """
    data = _load_json(raw)
    if not isinstance(data, list):
        return None
    try:
        items: list[MenuItem] = []
        for item in data:
            parsed = menu_item_from_api(item) if isinstance(item, dict) else None
            if parsed is not None:
                items.append(parsed)
        return items
    except Exception:
        return None


## CatalogCache giống như 1 đối tượng lưu trữ các thông tin về menu, hotline, index, version của 1 nhà hàng
#Khi nào cần lấy từ Redis thì sẽ gọi đến CatalogCache
#
# Ví dụ snapshot g1 (pointer = "g1"):
#   Key Redis                                    Giá trị (ý nghĩa)
#   aibridge:catalog:pointer                     "g1" — biển “đang dùng”
#   aibridge:catalog:generation                  1 — bộ đếm
#   aibridge:catalog:g1:version                  "hash-v1"
#   aibridge:catalog:g1:hotline:1900636886       JSON của Restaurant
#   aibridge:catalog:g1:hotline:02839123456      cùng JSON Restaurant đó
#   aibridge:catalog:g1:menu:q1                  JSON mảng món
#   aibridge:catalog:g1:index                    {"restaurants":1,"hotlines":2,"menus":1}
class CatalogCache:
    """Người giữ chìa Redis: đọc/ghi danh mục nhà hàng (restaurant + menu).

    Redis là tủ. Object này biết key nào, ghi thế nào. Một process = một
    CatalogCache, cuộc gọi và syncer dùng chung.

    Đọc: GET pointer → "g7" → đọc key trong g7. Không đọc lung tung key cũ/mới.
    Ghi full: swap_generation (bộ mới rồi mới lật pointer).
    Ghi lẻ: put_* write-through, không lật pointer.
    """

    def __init__(
        self,
        redis: Redis,
        *,
        namespace: str = DEFAULT_NAMESPACE,
        generation_ttl: int = DEFAULT_GENERATION_TTL,
    ) -> None:
        """Gắn một client Redis đã tạo sẵn.

        redis: kết nối (thật hoặc FakeRedis khi test).
        namespace: tiền tố key, mặc định "aibridge".
        generation_ttl: hạn bộ snapshot (giây), mặc định 10800 = 3 giờ.
        """
        self._redis = redis
        self._ns = namespace.strip() or DEFAULT_NAMESPACE
        self._generation_ttl = generation_ttl

    @classmethod
    def from_url(
        cls,
        url: str,
        *,
        namespace: str = DEFAULT_NAMESPACE,
        generation_ttl: int = DEFAULT_GENERATION_TTL,
    ) -> CatalogCache:
        """Tạo CatalogCache từ REDIS_URL, ví dụ redis://127.0.0.1:6379/0.

        decode_responses=True: GET trả str, không phải bytes — khớp json.loads.
        """
        client = Redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=1,
        )
        return cls(client, namespace=namespace, generation_ttl=generation_ttl)

    async def connect(self) -> None:
        """Ping Redis. Fail ở đây thì lifespan sẽ bỏ cache, chạy như v1."""
        await self._redis.ping()

    async def aclose(self) -> None:
        """Đóng kết nối khi server tắt (gọi trong lifespan)."""
        await self._redis.aclose()

    async def swap_generation(self, payload: GenerationPayload, version: str) -> None:
        """Cất bộ snapshot mới vào Redis, rồi mới bảo mọi người lấy bộ mới.

        Không sửa tại chỗ bộ đang dùng (g6). Photocopy bộ g7, xong mới đổi biển.

        Thứ tự bắt buộc — đảo là cuộc gọi có thể thấy nửa cũ nửa mới:
          1) INCR bộ đếm → số 7, đặt tên "g7"
          2) Pipeline SET toàn bộ key g7 (version, hotline, menu, index) + TTL 3 giờ
          3) Mới SET pointer = "g7"  ← đây mới là lúc cuộc gọi mới thấy dữ liệu mới

        Pipeline lỗi thì pointer vẫn trỏ g6. Bộ cũ không xóa, tự hết hạn theo TTL.

        payload: dữ liệu đã parse (hotline → Restaurant, branch → menu).
        version: hash từ backend, để lần sau so "có đổi không".
        """
        n = int(await self._redis.incr(self._generation_counter_key()))
        generation = self._generation_label(n)
        ttl = self._generation_ttl
        previous = await self._redis.get(self._pointer_key())

        by_hotline = {
            str(digits).strip(): restaurant
            for digits, restaurant in payload.by_hotline.items()
            if str(digits or "").strip()
        }
        menus = {
            str(branch_id).strip(): items
            for branch_id, items in (payload.menus or {}).items()
            if str(branch_id or "").strip()
        }
        by_id = {restaurant.id: restaurant for restaurant in by_hotline.values()}
        #Đóng gói 1 chuỗi JSON chứa số lượng restaurant, hotline, menu
        index = json.dumps(
            {
                "restaurants": len(by_id),
                "hotlines": len(by_hotline),
                "menus": len(menus),
            },
            ensure_ascii=False,
        )
        # Khởi tạo hàng đợi(các lệnh thêm vào Redis sẽ được thêm lần lượt)
        pipe = self._redis.pipeline()
        #Lệnh lưu version vào Redis sẽ được thêm vào hàng đợi pipe
        pipe.set(self._version_key(generation), version, ex=ttl)
        #Lệnh lưu restaurant vào Redis sẽ được thêm vào hàng đợi pipe
        for digits, restaurant in by_hotline.items():
            pipe.set(
                self._hotline_key(generation, digits),
                _dump_restaurant(restaurant),
                ex=ttl,
            )
        for branch_id, items in menus.items():
            pipe.set(self._menu_key(generation, branch_id), _dump_menu(items), ex=ttl)
        pipe.set(self._index_key(generation), index, ex=ttl)
        await pipe.execute()
        #Cập nhật pointer sang generation mới
        await self._redis.set(self._pointer_key(), generation)

        logger.info(
            "Cache swap %s → %s (version=%s, restaurants=%s, branches=%s, hotlines=%s)",
            previous or "-",
            generation,
            version,
            len(by_id),
            sum(len(restaurant.branches) for restaurant in by_id.values()),
            len(by_hotline),
        )

    async def current_generation(self) -> str:
        """Đọc biển "đang dùng" (pointer), ví dụ "g7". Chưa từng swap → chuỗi rỗng.

        Session sẽ gọi một lần lúc bắt đầu cuộc gọi rồi giữ số này,
        để lượt sau (menu) vẫn đọc đúng bộ cũ dù sync đã lật sang g8.
        """
        raw = await self._redis.get(self._pointer_key())
        return str(raw).strip() if raw else ""

### Lấy chuỗi giá trị version gắn liền với generation( generation có thể là hiện tại hoặc được chỉ định)
    async def get_version(self) -> str:
        """Hash version của bộ đang trỏ. Syncer so với backend: trùng thì không ghi lại.

        Chưa có cache → "" (không khớp hash thật, lần sau sẽ swap).
        """
        generation = await self.current_generation()
        if not generation:
            return ""
        raw = await self._redis.get(self._version_key(generation))
        return str(raw) if raw else ""

    async def get_restaurant(
        self,
        hotline_digits: str,
        generation: str | None = None,
    ) -> Restaurant | None:
        """Lấy nhà hàng theo số hotline. Miss / JSON hỏng → None (không raise).

        Mặc định đọc generation mà pointer đang trỏ.
        Truyền generation="g6" thì đọc đúng bộ g6 — snapshot isolation:
        cuộc gọi đã chốt g6 không bị kéo sang g7 giữa chừng.

        hotline được normalize (chỉ giữ chữ số) cho khớp "1900-636-886" với "1900636886".
        """
        digits = normalize_hotline(hotline_digits)
        if not digits:
            return None
        gen = await self._resolve_generation(generation)
        if not gen:
            return None
        raw = await self._redis.get(self._hotline_key(gen, digits))
        return _load_restaurant(raw)

    async def get_menu(
        self,
        branch_id: str,
        generation: str | None = None,
    ) -> list[MenuItem] | None:
        """Lấy menu theo id chi nhánh. None = miss; [] = có key nhưng không món.

        Cũng nhận generation để đọc đúng bộ snapshot của cuộc gọi (menu lấy lazy,
        sau session.init khá lâu — nếu lúc đó GET pointer có thể ra generation mới).
        """
        branch_id = str(branch_id or "").strip()
        if not branch_id:
            return None
        gen = await self._resolve_generation(generation)
        if not gen:
            return None
        raw = await self._redis.get(self._menu_key(gen, branch_id))
        return _load_menu(raw)

    async def put_restaurant(
        self,
        hotline_digits: str,
        restaurant: Restaurant,
        ttl: int,
    ) -> None:
        """Write-through: cache miss → HTTP xong ghi lại Redis cho lần sau.

        Khác swap_generation: chỉ SET một key, TTL ngắn (thường 600s),
        KHÔNG INCR, KHÔNG lật pointer. Bộ g7 đang dùng vẫn nguyên.

        Dùng khi backend chưa có /sync/* (degrade): cuộc gọi đầu trả giá HTTP,
        các cuộc sau trong vài phút đọc cache.
        """
        digits = normalize_hotline(hotline_digits)
        if not digits:
            return
        generation = await self._generation_for_write()
        await self._redis.set(
            self._hotline_key(generation, digits),
            _dump_restaurant(restaurant),
            ex=max(int(ttl), 1),
        )

    async def put_menu(
        self,
        branch_id: str,
        items: list[MenuItem],
        ttl: int,
    ) -> None:
        """Write-through menu, cùng luật put_restaurant: không phá generation đang dùng."""
        branch_id = str(branch_id or "").strip()
        if not branch_id:
            return
        generation = await self._generation_for_write()
        await self._redis.set(
            self._menu_key(generation, branch_id),
            _dump_menu(items),
            ex=max(int(ttl), 1),
        )

    async def stats(self) -> dict:
        """Số liệu cho GET /health: generation, version, số restaurant/hotline/menu.

        Index JSON hỏng thì counts = 0, vẫn trả generation/version, không raise.
        """
        generation = await self.current_generation()
        if not generation:
            return {
                "generation": "",
                "version": "",
                "restaurants": 0,
                "hotlines": 0,
                "menus": 0,
            }
        version = await self._redis.get(self._version_key(generation))
        restaurants = hotlines = menus = 0
        index = _load_json(await self._redis.get(self._index_key(generation)))
        if isinstance(index, dict):
            try:
                restaurants = int(index.get("restaurants") or 0)
                hotlines = int(index.get("hotlines") or 0)
                menus = int(index.get("menus") or 0)
            except (TypeError, ValueError):
                pass
        return {
            "generation": generation,
            "version": str(version) if version else "",
            "restaurants": restaurants,
            "hotlines": hotlines,
            "menus": menus,
        }

    async def _resolve_generation(self, generation: str | None) -> str:
        """Chọn generation để đọc: caller chỉ định thì dùng, không thì lấy pointer hiện tại."""
        if generation and str(generation).strip():
            return str(generation).strip()
        return await self.current_generation()

    async def _generation_for_write(self) -> str:
        """Generation để write-through: có pointer thì ghi vào đó (không lật biển).

        Chưa có pointer (lần ghi đầu, chưa từng sync): INCR tạo g1, SET pointer NX
        (chỉ ghi nếu chưa có biển — tránh đè pointer mà swap vừa lật).
        """
        generation = await self.current_generation()
        if generation:
            return generation
        n = int(await self._redis.incr(self._generation_counter_key()))
        generation = self._generation_label(n)
        await self._redis.set(self._pointer_key(), generation, nx=True)
        return await self.current_generation() or generation

    def _catalog(self, *parts: str) -> str:
        """Ghép key Redis: namespace + catalog + các phần. Ví dụ aibridge:catalog:pointer."""
        return ":".join((self._ns, "catalog", *parts))

    def _generation_counter_key(self) -> str:
        """Bộ đếm số generation. INCR mỗi lần swap. Ví dụ aibridge:catalog:generation → 7."""
        return self._catalog("generation")

    def _pointer_key(self) -> str:
        """Biển 'đang dùng'. GET ra 'g7' rồi đọc mọi key trong g7."""
        return self._catalog("pointer")

    @staticmethod
    def _generation_label(n: int) -> str:
        """Số 7 → nhãn 'g7' dùng trong mọi key của bộ snapshot đó."""
        return f"g{n}"

    def _version_key(self, generation: str) -> str:
        """Key hash version, ví dụ aibridge:catalog:g7:version."""
        return self._catalog(generation, "version")

    def _hotline_key(self, generation: str, digits: str) -> str:
        """Key nhà hàng theo hotline, ví dụ aibridge:catalog:g7:hotline:1900636886."""
        return self._catalog(generation, "hotline", digits)

    def _menu_key(self, generation: str, branch_id: str) -> str:
        """Key menu theo chi nhánh, ví dụ aibridge:catalog:g7:menu:c7a2."""
        return self._catalog(generation, "menu", branch_id)

    def _index_key(self, generation: str) -> str:
        """Key meta đếm số lượng (cho /health), ví dụ aibridge:catalog:g7:index."""
        return self._catalog(generation, "index")

    def _lock_key(self) -> str:
        """Leader lock giữa nhiều instance: aibridge:sync:lock."""
        return f"{self._ns}:sync:lock"

    async def try_acquire_writer_lock(self, owner: str, ttl: int = 60) -> bool:
        """SET NX EX. True = được ghi vòng này. False = instance khác đang ghi, không phải lỗi."""
        owner = str(owner or "").strip()
        if not owner:
            return False
        ttl = max(int(ttl), 1)
        key = self._lock_key()
        acquired = await self._redis.set(key, owner, nx=True, ex=ttl)
        if acquired:
            return True
        current = await self._redis.get(key)
        if str(current or "") == owner:
            await self._redis.expire(key, ttl)
            return True
        return False
