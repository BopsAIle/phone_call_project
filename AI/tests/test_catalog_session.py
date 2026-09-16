from __future__ import annotations

import json

from fakeredis.aioredis import FakeRedis
from order.matcher import ScriptedMenuMatcher
from order.models import MenuItem, MenuMatchResult
from order.tools import OrderTools

from booking.models import Branch, Restaurant
from bridge.session import CallPipeline, CallSession
from cache.redis_store import CatalogCache, GenerationPayload
from tests.fakes import FakeOrderClient, FakeRestaurantClient, FakeSTT, ScriptedLlm, ScriptedTts

Q1 = Branch(id="q1", name="Quận 1", address="12 Lê Lợi")
Q3 = Branch(id="q3", name="Quận 3")
HN = Branch(id="hn", name="Hà Nội")
PHO = MenuItem(id="pho-bo", name="Phở bò", price=55000, unit="tô")

_PHO_MATCH = MenuMatchResult(
    status="match",
    menu_item_id="pho-bo",
    confidence="high",
    confirm_name="Phở bò",
)

INIT = {
    "event": "session.init",
    "callId": "c-cache",
    "storeName": "Placeholder",
    "timezone": "UTC",
    "locale": "vi",
    "greeting": "Xin chào.",
    "toNumber": "1900636886",
}


def _restaurant(*branches: Branch, name: str = "Bella Vista") -> Restaurant:
    return Restaurant(id="rest-1", name=name, phone="1900636886", branches=list(branches))


def _cache() -> CatalogCache:
    return CatalogCache(FakeRedis(decode_responses=True))


def _pipeline(cache: CatalogCache | None = None, restaurant_client=None, order_client=None) -> CallPipeline:
    return CallPipeline(
        object(),
        stt=FakeSTT(),
        llm=ScriptedLlm([]),
        tts=ScriptedTts(),
        restaurant_client=restaurant_client,
        order_client=order_client,
        catalog_cache=cache,
        cache_ttl=600,
    )


async def test_catalog_cache_hit_skips_http() -> None:
    cache = _cache()
    await cache.swap_generation(
        GenerationPayload(by_hotline={"1900636886": _restaurant(Q1)}, menus={}),
        "v1",
    )
    http = FakeRestaurantClient(result=_restaurant(Q1, Q3, name="Should not use"))
    pipeline = _pipeline(cache, restaurant_client=http)
    pipeline.session.apply_init(INIT)
    await pipeline._load_catalog()

    assert http.lookups == []
    assert pipeline.session.restaurant_name == "Bella Vista"
    assert [b.id for b in pipeline.session.branches] == ["q1"]
    assert pipeline.session.selected_branch_id == "q1"
    assert pipeline.session.cache_generation == "g1"
    assert pipeline.session.catalog_ready is True
    assert pipeline.session.restaurant_missing is False


async def test_catalog_cache_miss_http_and_write_through() -> None:
    cache = _cache()
    restaurant = _restaurant(Q1)
    http = FakeRestaurantClient(result=restaurant)
    pipeline = _pipeline(cache, restaurant_client=http)
    pipeline.session.apply_init(INIT)
    await pipeline._load_catalog()

    assert http.lookups == ["1900636886"]
    cached = await cache.get_restaurant("1900636886")
    assert cached is not None
    assert cached.name == "Bella Vista"
    assert pipeline.session.restaurant_name == "Bella Vista"
    assert pipeline.session.cache_generation == "g1"


async def test_snapshot_prompt_unchanged_after_cache_swap() -> None:
    cache = _cache()
    await cache.swap_generation(
        GenerationPayload(by_hotline={"1900636886": _restaurant(Q1, Q3, HN)}, menus={}),
        "v1",
    )
    pipeline = _pipeline(cache, restaurant_client=FakeRestaurantClient())
    pipeline.session.apply_init(INIT)
    await pipeline._load_catalog()
    prompt = pipeline.session.history[0]["content"]
    assert "Quận 3" in prompt
    pinned = pipeline.session.cache_generation
    assert pinned == "g1"

    await cache.swap_generation(
        GenerationPayload(by_hotline={"1900636886": _restaurant(Q1, HN, name="Bella New")}, menus={}),
        "v2",
    )
    assert pipeline.session.history[0]["content"] == prompt
    assert [b.id for b in pipeline.session.branches] == ["q1", "q3", "hn"]
    assert (await cache.get_restaurant("1900636886")).name == "Bella New"
    old = await cache.get_restaurant("1900636886", generation=pinned)
    assert old is not None
    assert [b.id for b in old.branches] == ["q1", "q3", "hn"]


async def test_list_menu_cache_hit_skips_http() -> None:
    cache = _cache()
    await cache.swap_generation(
        GenerationPayload(by_hotline={"1900636886": _restaurant(Q1)}, menus={"q1": [PHO]}),
        "v1",
    )
    session = CallSession()
    session.apply_restaurant(_restaurant(Q1))
    session.catalog_ready = True
    session.select_branch("q1")
    session.cache_generation = "g1"
    client = FakeOrderClient(menu=[MenuItem(id="other", name="Other")])
    tools = OrderTools(session, client, ScriptedMenuMatcher(), cache=cache)
    payload = json.loads(await tools.execute("list_menu", "{}"))
    assert client.menu_lookups == []
    assert payload["ok"] is True
    assert session.menu[0].name == "Phở bò"


async def test_list_menu_cache_miss_http_and_write_through() -> None:
    cache = _cache()
    session = CallSession()
    session.apply_restaurant(_restaurant(Q1))
    session.catalog_ready = True
    session.select_branch("q1")
    client = FakeOrderClient(menu=[PHO])
    tools = OrderTools(
        session,
        client,
        ScriptedMenuMatcher({"phở bò": _PHO_MATCH}),
        cache=cache,
        cache_ttl=600,
    )
    payload = json.loads(await tools.execute("search_menu", json.dumps({"spoken_name": "phở bò"})))
    assert client.menu_lookups == [("rest-1", "q1")]
    assert payload["status"] == "match"
    cached = await cache.get_menu("q1")
    assert cached is not None
    assert cached[0].name == "Phở bò"


async def test_cache_read_error_falls_back_to_http() -> None:
    class BoomCache:
        async def current_generation(self) -> str:
            raise OSError("redis down")

        async def get_restaurant(self, *args, **kwargs):
            raise OSError("redis down")

        async def put_restaurant(self, *args, **kwargs):
            raise OSError("redis down")

    restaurant = _restaurant(Q1)
    http = FakeRestaurantClient(result=restaurant)
    pipeline = _pipeline(BoomCache(), restaurant_client=http)
    pipeline.session.apply_init(INIT)
    await pipeline._load_catalog()
    assert http.lookups == ["1900636886"]
    assert pipeline.session.restaurant_name == "Bella Vista"
    assert pipeline.session.catalog_ready is True
