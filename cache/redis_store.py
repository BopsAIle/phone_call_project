"""Redis catalog cache: generation + pointer layout (pipeline v2 §5.5)."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field

from redis.asyncio import Redis

from booking.models import Restaurant
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
    """Parsed catalog ready to write as one Redis generation.

    Syncer (bước 2) sẽ dựng object này từ API; cache không parse HTTP JSON.
    """

    by_hotline: Mapping[str, Restaurant]
    menus: Mapping[str, Sequence[MenuItem]] = field(default_factory=dict)

# Biến Object restaurant được lưu trữ dưới dạng JSON
def _dump_restaurant(restaurant: Restaurant) -> str:
    return json.dumps(asdict(restaurant), ensure_ascii=False)

# Biến Object menu được lưu trữ dưới dạng JSON
def _dump_menu(items: Sequence[MenuItem]) -> str:
    return json.dumps([asdict(item) for item in items], ensure_ascii=False)


## CatalogCache giống như 1 đối tượng lưu trữ các thông tin về menu, hotline, index, version của 1 nhà hàng
#Khi nào cần lấy từ Redis thì sẽ gọi đến CatalogCache
class CatalogCache:
    """Redis-backed restaurant/menu cache. Readers follow pointer → generation keys.

    Key layout (namespace default ``aibridge``)::

        aibridge:catalog:generation            counter (INCR)
        aibridge:catalog:pointer               active generation, e.g. "g7"
        aibridge:catalog:g7:version
        aibridge:catalog:g7:hotline:<digits>
        aibridge:catalog:g7:menu:<branch_id>
        aibridge:catalog:g7:index
    """

    def __init__(
        self,
        redis: Redis,
        *,
        namespace: str = DEFAULT_NAMESPACE,
        generation_ttl: int = DEFAULT_GENERATION_TTL,
    ) -> None:
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
        client = Redis.from_url(url, decode_responses=True)
        return cls(client, namespace=namespace, generation_ttl=generation_ttl)

    async def connect(self) -> None:
        await self._redis.ping()

    async def aclose(self) -> None:
        await self._redis.aclose()

#hàm này cất bộ snapshot mới vào Redis, rồi mới bảo mọi người: từ giờ lấy bộ mới.
#Bước 1: Tạo generation mới
#Bước 2: Lưu thông tin mới vào Redis
#Bước 3: Cập nhật pointer
    async def swap_generation(self, payload: GenerationPayload, version: str) -> None:
        """Write a full snapshot, then flip the pointer.

        Order is mandatory: INCR → pipeline SET+TTL → SET pointer last.
        Readers never see a half-written generation.
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
        index = json.dumps(
            {
                "restaurants": len(by_id),
                "hotlines": len(by_hotline),
                "menus": len(menus),
            },
            ensure_ascii=False,
        )

        pipe = self._redis.pipeline()
        pipe.set(self._version_key(generation), version, ex=ttl)
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

    def _catalog(self, *parts: str) -> str:
        return ":".join((self._ns, "catalog", *parts))

    def _generation_counter_key(self) -> str:
        return self._catalog("generation")

    def _pointer_key(self) -> str:
        return self._catalog("pointer")

    @staticmethod
    def _generation_label(n: int) -> str:
        return f"g{n}"

    def _version_key(self, generation: str) -> str:
        return self._catalog(generation, "version")

    def _hotline_key(self, generation: str, digits: str) -> str:
        return self._catalog(generation, "hotline", digits)

    def _menu_key(self, generation: str, branch_id: str) -> str:
        return self._catalog(generation, "menu", branch_id)

    def _index_key(self, generation: str) -> str:
        return self._catalog(generation, "index")
