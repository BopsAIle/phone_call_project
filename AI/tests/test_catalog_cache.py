## Test các hàm trong redis_store.py
from __future__ import annotations

from fakeredis.aioredis import FakeRedis

from booking.models import Branch, Restaurant
from cache.redis_store import CatalogCache, GenerationPayload
from order.models import MenuItem

_TTL_GENERATION = 10800

_TTL_WRITE_THROUGH = 600 


def _restaurant(name: str = "Bella Vista", extra_branch: bool = False) -> Restaurant:
    branches = [Branch(id="q1", name="Quận 1", address="12 Lê Lợi")]
    if extra_branch:
        branches.append(Branch(id="q3", name="Quận 3"))
    return Restaurant(id="rest-1", name=name, phone="1900636886", branches=branches)


def _menu() -> list[MenuItem]:
    return [MenuItem(id="m1", name="Phở bò", price=65000, unit="tô")]


def _payload(restaurant: Restaurant | None = None) -> GenerationPayload:
    restaurant = restaurant or _restaurant()
    return GenerationPayload(
        by_hotline={"1900636886": restaurant, "02839123456": restaurant},
        menus={"q1": _menu()},
    )


def _cache() -> tuple[CatalogCache, FakeRedis]:
    redis = FakeRedis(decode_responses=True)
    return CatalogCache(redis, generation_ttl=_TTL_GENERATION), redis


async def test_swap_generation_writes_keys_sets_ttl_and_flips_pointer() -> None:
    cache, redis = _cache()
    await cache.swap_generation(_payload(), "hash-v1")

    assert await redis.get("aibridge:catalog:pointer") == "g1"
    assert int(await redis.get("aibridge:catalog:generation")) == 1
    assert await redis.get("aibridge:catalog:g1:version") == "hash-v1"
    assert await cache.get_version() == "hash-v1"

    restaurant = await cache.get_restaurant("1900-636-886")
    assert restaurant is not None
    assert restaurant.name == "Bella Vista"
    assert [b.id for b in restaurant.branches] == ["q1"]

    other = await cache.get_restaurant("02839123456")
    assert other is not None and other.id == "rest-1"

    items = await cache.get_menu("q1")
    assert items is not None and items[0].name == "Phở bò"

    stats = await cache.stats()
    assert stats["generation"] == "g1"
    assert stats["version"] == "hash-v1"
    assert stats["restaurants"] == 1
    assert stats["hotlines"] == 2
    assert stats["menus"] == 1

    assert await redis.ttl("aibridge:catalog:g1:version") > 10700
    assert await redis.ttl("aibridge:catalog:g1:hotline:1900636886") > 10700
    assert await redis.ttl("aibridge:catalog:g1:menu:q1") > 10700
    assert await redis.ttl("aibridge:catalog:g1:index") > 10700
    assert await redis.ttl("aibridge:catalog:pointer") == -1


async def test_swap_flips_pointer_only_after_pipeline() -> None:
    cache, redis = _cache()
    events: list[str] = []
    orig_pipeline = redis.pipeline
    orig_set = redis.set

    def pipeline(*args, **kwargs):
        pipe = orig_pipeline(*args, **kwargs)
        orig_execute = pipe.execute

        async def execute(*exec_args, **exec_kwargs):
            events.append("pipeline")
            assert await redis.get("aibridge:catalog:pointer") is None
            return await orig_execute(*exec_args, **exec_kwargs)

        pipe.execute = execute
        return pipe

    async def tracking_set(name, value, *args, **kwargs):
        events.append(f"set:{name}")
        return await orig_set(name, value, *args, **kwargs)

    redis.pipeline = pipeline  # type: ignore[method-assign]
    redis.set = tracking_set  # type: ignore[method-assign]

    await cache.swap_generation(_payload(), "hash-v1")

    assert events[0] == "pipeline"
    assert events.index("pipeline") < events.index("set:aibridge:catalog:pointer")
    assert await redis.get("aibridge:catalog:pointer") == "g1"


async def test_reader_on_old_generation_still_complete_after_swap() -> None:
    cache, redis = _cache()
    await cache.swap_generation(_payload(_restaurant("Bella")), "v1")
    pinned = await cache.current_generation()
    assert pinned == "g1"

    await cache.swap_generation(_payload(_restaurant("Bella New", extra_branch=True)), "v2")
    assert await redis.get("aibridge:catalog:pointer") == "g2"
    assert (await cache.get_restaurant("1900636886")).name == "Bella New"
    assert len((await cache.get_restaurant("1900636886")).branches) == 2

    old = await cache.get_restaurant("1900636886", generation=pinned)
    assert old is not None
    assert old.name == "Bella"
    assert [b.id for b in old.branches] == ["q1"]
    old_menu = await cache.get_menu("q1", generation=pinned)
    assert old_menu is not None and old_menu[0].id == "m1"
    assert await redis.get("aibridge:catalog:g1:hotline:02839123456")
    assert await redis.get("aibridge:catalog:g1:index")
    assert await redis.get("aibridge:catalog:g1:version") == "v1"


async def test_corrupt_json_returns_none_without_raising() -> None:
    cache, redis = _cache()
    await cache.swap_generation(_payload(), "v1")

    await redis.set("aibridge:catalog:g1:hotline:1900636886", "{not-json")
    assert await cache.get_restaurant("1900636886") is None

    await redis.set("aibridge:catalog:g1:menu:q1", '{"oops": true}')
    assert await cache.get_menu("q1") is None

    await redis.set("aibridge:catalog:g1:hotline:1900636886", "[]")
    assert await cache.get_restaurant("1900636886") is None

    await redis.set("aibridge:catalog:g1:index", "not-json")
    stats = await cache.stats()
    assert stats["generation"] == "g1"
    assert stats["restaurants"] == 0


async def test_write_through_uses_short_ttl_and_does_not_break_generation() -> None:
    cache, redis = _cache()
    await cache.swap_generation(_payload(), "v1")
    pointer = await redis.get("aibridge:catalog:pointer")
    version_ttl_before = await redis.ttl("aibridge:catalog:g1:version")

    extra = Restaurant(id="rest-2", name="Other", branches=[Branch(id="hn", name="Hà Nội")])
    await cache.put_restaurant("0987654321", extra, ttl=_TTL_WRITE_THROUGH)
    await cache.put_menu("hn", _menu(), ttl=_TTL_WRITE_THROUGH)

    assert await redis.get("aibridge:catalog:pointer") == pointer
    assert await cache.get_version() == "v1"
    assert int(await redis.get("aibridge:catalog:generation")) == 1
    assert (await cache.get_restaurant("1900636886")).name == "Bella Vista"
    assert (await cache.get_restaurant("0987654321")).name == "Other"
    assert await cache.get_menu("hn") is not None

    write_ttl = await redis.ttl("aibridge:catalog:g1:hotline:0987654321")
    assert 1 <= write_ttl <= _TTL_WRITE_THROUGH
    assert await redis.ttl("aibridge:catalog:g1:menu:hn") <= _TTL_WRITE_THROUGH
    assert await redis.ttl("aibridge:catalog:g1:version") >= version_ttl_before - 2
    assert await redis.ttl("aibridge:catalog:g1:hotline:1900636886") > 10700
