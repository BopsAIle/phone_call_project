"""Parse restaurant + branch + menu snapshots for Redis catalog cache."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from booking.client import normalize_hotline, restaurant_from_api, unwrap_data
from booking.models import Restaurant
from cache.redis_store import GenerationPayload
from order.client import menu_item_from_api
from order.models import MenuItem


@dataclass(frozen=True)
class SyncPayload:
    """Snapshot sẵn sàng đưa vào CatalogCache."""

    version: str
    by_hotline: Mapping[str, Restaurant]
    menus: Mapping[str, Sequence[MenuItem]] = field(default_factory=dict)

    def to_generation(self) -> GenerationPayload:
        return GenerationPayload(by_hotline=self.by_hotline, menus=self.menus)


def _as_hotline_list(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        values = [raw]
    elif isinstance(raw, list):
        values = [str(item) for item in raw]
    else:
        return []
    digits: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = normalize_hotline(value)
        if not key or key in seen:
            continue
        seen.add(key)
        digits.append(key)
    return digits


def _as_mapping_list(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if isinstance(raw, dict):
        return [raw]
    return []


def _branch_restaurant_id(branch: dict[str, Any]) -> str:
    rid = str(branch.get("restaurant_id") or "").strip()
    if rid:
        return rid
    nested = branch.get("restaurant")
    if isinstance(nested, dict):
        return str(nested.get("id") or "").strip()
    return ""


def _menus_for_restaurant(item: dict[str, Any], restaurant: Restaurant) -> dict[str, list[MenuItem]]:
    raw_menus = item.get("menus")
    if not isinstance(raw_menus, dict):
        return {}
    active_ids = {branch.id for branch in restaurant.branches}
    menus: dict[str, list[MenuItem]] = {}
    for raw_id, raw_items in raw_menus.items():
        branch_id = str(raw_id or "").strip()
        if not branch_id or branch_id not in active_ids:
            continue
        if not isinstance(raw_items, list):
            continue
        parsed: list[MenuItem] = []
        seen: set[str] = set()
        for raw_item in raw_items:
            menu_item = menu_item_from_api(raw_item) if isinstance(raw_item, dict) else None
            if menu_item is None or menu_item.id in seen:
                continue
            seen.add(menu_item.id)
            parsed.append(menu_item)
        menus[branch_id] = parsed
    return menus


def catalog_version(
    restaurants: Sequence[dict[str, Any]],
    branches: Sequence[dict[str, Any]],
    menus: Mapping[str, Sequence[Any]],
) -> str:
    """Hash ổn định từ list NestJS — thay cho /api/v1/sync/check-version."""
    rest = sorted(
        (
            {
                "id": str(item.get("id") or ""),
                "name": str(item.get("name") or ""),
                "phone": str(item.get("phone") or ""),
                "status": str(item.get("status") or ""),
                "updated_at": str(item.get("updated_at") or ""),
            }
            for item in restaurants
        ),
        key=lambda row: row["id"],
    )
    branch_fp = sorted(
        (
            {
                "id": str(item.get("id") or ""),
                "restaurant_id": _branch_restaurant_id(item),
                "name": str(item.get("name") or ""),
                "status": str(item.get("status") or ""),
                "updated_at": str(item.get("updated_at") or ""),
            }
            for item in branches
        ),
        key=lambda row: row["id"],
    )
    menu_fp = {
        str(branch_id): [
            {
                "id": str(item.get("id") or item.get("menu_item_id") or ""),
                "name": str(item.get("name") or ""),
                "price": item.get("price"),
                "status": str(item.get("status") or ""),
                "updated_at": str(item.get("updated_at") or ""),
            }
            for item in items
            if isinstance(item, dict)
        ]
        for branch_id, items in sorted(menus.items(), key=lambda pair: str(pair[0]))
    }
    blob = json.dumps(
        {"b": branch_fp, "m": menu_fp, "r": rest},
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def parse_sync_payload(raw: Any) -> SyncPayload | None:
    """Unwrap `data`, lọc restaurant/branch active, normalize hotline.

    JSON không phải object → None. Restaurant thiếu id / không active bị bỏ.
    Branch inactive đã bị restaurant_from_api lọc. menus là tùy chọn.
    """
    data = unwrap_data(raw)
    if not isinstance(data, dict):
        return None
    version = str(data.get("version") or "").strip()
    raw_restaurants = data.get("restaurants") or []
    if not isinstance(raw_restaurants, list):
        raw_restaurants = []

    by_hotline: dict[str, Restaurant] = {}
    menus: dict[str, list[MenuItem]] = {}
    for item in raw_restaurants:
        if not isinstance(item, dict):
            continue
        restaurant = restaurant_from_api(item)
        if restaurant is None:
            continue
        if restaurant.status != "active":
            continue
        hotlines = _as_hotline_list(item.get("hotlines"))
        phone = normalize_hotline(restaurant.phone)
        if phone and phone not in hotlines:
            hotlines.append(phone)
        for digits in hotlines:
            by_hotline[digits] = restaurant
        menus.update(_menus_for_restaurant(item, restaurant))
    return SyncPayload(version=version, by_hotline=by_hotline, menus=menus)


def _records(raw: Any) -> list[dict[str, Any]]:
    return _as_mapping_list(unwrap_data(raw))


def assemble_catalog(
    restaurants: Any,
    branches: Any,
    menus: Mapping[str, Any] | None = None,
) -> SyncPayload:
    """Ghép GET /restaurants + GET /branches + GET /menu/branch/{id} thành snapshot Redis.

    Nest không bọc branches/menus trong từng restaurant — list riêng, gắn theo id.
    """
    rest_list = _records(restaurants)
    branch_list = _records(branches)

    menu_map: dict[str, list[dict[str, Any]]] = {}
    for bid, items in (menus or {}).items():
        key = str(bid or "").strip()
        if not key:
            continue
        menu_map[key] = _as_mapping_list(items)

    by_id: dict[str, dict[str, Any]] = {}
    for item in rest_list:
        rid = str(item.get("id") or "").strip()
        if not rid:
            continue
        packed = dict(item)
        packed["branches"] = []
        packed["menus"] = {}
        by_id[rid] = packed

    for branch in branch_list:
        rid = _branch_restaurant_id(branch)
        nested = branch.get("restaurant")
        if rid and rid not in by_id and isinstance(nested, dict) and nested.get("id"):
            packed = dict(nested)
            packed["branches"] = []
            packed["menus"] = {}
            by_id[rid] = packed
        if not rid or rid not in by_id:
            continue
        by_id[rid]["branches"].append(branch)
        bid = str(branch.get("id") or "").strip()
        if bid and bid in menu_map:
            by_id[rid]["menus"][bid] = menu_map[bid]

    version = catalog_version(rest_list, branch_list, menu_map)
    parsed = parse_sync_payload({"version": version, "restaurants": list(by_id.values())})
    if parsed is None:
        return SyncPayload(version=version, by_hotline={}, menus={})
    return parsed
