"""Parse GET /api/v1/sync/branches into restaurant + menu snapshots."""
## sync/models.py : nhiệm vụ là biến JSON thô từ backend thành cấu trúc sẵn sàng nhét vào Redis

from __future__ import annotations

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
    """Kết quả parse /api/v1/sync/branches, sẵn sàng đưa vào CatalogCache."""

    #version: version của dữ liệu
    version: str
    # Dictionary tra cứu từ sđt -> Restaurant. Cuộc gọi đến số nào thì biết ngay nhà hàng nào 
    by_hotline: Mapping[str, Restaurant]
    #menus: thực đơn của từng chi nhánh . Dạng dictionary branch_id -> list[MenuItem]
    menus: Mapping[str, Sequence[MenuItem]] = field(default_factory=dict)

    def to_generation(self) -> GenerationPayload:
        return GenerationPayload(by_hotline=self.by_hotline, menus=self.menus)

## Nhận field hotline từ JSON thô và chuyển thành list sđt đã chuẩn hóa 
#-> Chuẩn hóa sđt
#Backend gửi hotline rất tuỳ tiện — có nơi "0912-345-678", có nơi "+84912345678"-> _as_hotline_list chuyển thành list sđt đã chuẩn hóa
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

# parse phần "menus" của một nhà hàng (JSON dạng { branch_id: [menu items] }) thành dict[branch_id → list[MenuItem]]
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

"""
1.unwrap_data(raw) — backend gói dữ liệu trong { "data": {...} }; hàm này bóc ra. JSON không phải object → return None (Syncer sẽ coi là fetch_failed).
2.Đọc version — dùng để so sánh với cache lần sau.
3.Duyệt từng restaurant:
      restaurant_from_api(item) — parse + tự động lọc branch inactive (comment ở docstring nói rõ).
      Bỏ luôn nhà hàng status != "active".
      Ghép hotline: hotlines khai báo + trường phone chính → merge lại (không trùng).
      Mọi hotline đều trỏ đến cùng một Restaurant — nên cuộc gọi vào số nào của nhà hàng đó cũng lookup được.
4.Gom menus từ _menus_for_restaurant.
5.Đóng gói thành SyncPayload.
"""

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
