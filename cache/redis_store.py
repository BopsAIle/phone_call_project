"""Redis catalog cache: generation + pointer layout (pipeline v2 §5.5)."""

from __future__ import annotations

from redis.asyncio import Redis
## Redis giống như 1 tủ khóa lớn, nhiều người dùng chung
#  aibridge là tên của tủ khóa mình đang dùng để không nhầm với app khác
DEFAULT_NAMESPACE = "aibridge"
## DEFAULT_GENERATION_TTL làthời gian mỗi key Redis có thể gắn hạn sử dụng. Hết hạn thì Redis xóa
## 10800 giây = 3 giờ
#Ví dụ như cuộc gọi đang dùng snapshot này, nhưng ta lại xóa đi vì cho rằng snapshot này không còn sử dụng được nữa
#Điều này nguy hiểm vì cuộc gọi đang dở dang
DEFAULT_GENERATION_TTL = 10800


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
