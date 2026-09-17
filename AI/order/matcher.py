"""AI fuzzy-match of a spoken dish name against the in-memory menu."""

from __future__ import annotations

import json
import logging
from typing import Any, Protocol

from order.models import MenuItem, MenuMatchResult

logger = logging.getLogger(__name__)

_MATCH_SYSTEM = (
    "You match a spoken food or drink name against the restaurant menu. "
    "The speaker may mispronounce, drop diacritics, or include a quantity "
    "('two peach teas', 'two pho bowls'). Ignore quantity words; match the dish. "
    "Return JSON only with keys: status, menu_item_id, confidence, confirm_name. "
    "status is match, ambiguous, or none. "
    "menu_item_id must be an id from the catalog or null. "
    "confidence is high or low. "
    "Use match+high only when one catalog item clearly matches. "
    "Use match+low if one candidate seems right but should be confirmed. "
    "Use ambiguous if two or more items could match. "
    "Use none if the spoken name is not on the menu (do not invent dishes). "
    "confirm_name is the catalog name to read back, or empty."
)


class MenuMatcher(Protocol):
    async def match(self, spoken_name: str, items: list[MenuItem]) -> MenuMatchResult:
        ...


def coerce_menu_match(payload: Any, items: list[MenuItem]) -> MenuMatchResult:
    catalog = {item.id: item for item in items}
    if not isinstance(payload, dict):
        return MenuMatchResult(status="none")
    status = str(payload.get("status") or "none").strip().lower()
    if status not in {"match", "ambiguous", "none"}:
        status = "none"
    raw_id = payload.get("menu_item_id") or payload.get("item_id") or payload.get("id")
    menu_item_id = str(raw_id).strip() if raw_id else ""
    confidence = str(payload.get("confidence") or "low").strip().lower()
    if confidence not in {"high", "low"}:
        confidence = "low"
    confirm_name = str(payload.get("confirm_name") or "").strip()

    if status == "match":
        if menu_item_id not in catalog:
            return MenuMatchResult(status="none")
        item = catalog[menu_item_id]
        return MenuMatchResult(
            status="match",
            menu_item_id=item.id,
            confidence=confidence,
            confirm_name=confirm_name or item.name,
        )

    candidate_ids: list[str] = []
    raw_candidates = payload.get("candidate_ids") or payload.get("candidates") or []
    if isinstance(raw_candidates, list):
        for entry in raw_candidates:
            cid = ""
            if isinstance(entry, str):
                cid = entry.strip()
            elif isinstance(entry, dict):
                cid = str(
                    entry.get("id") or entry.get("menu_item_id") or entry.get("item_id") or ""
                ).strip()
            if cid and cid in catalog and cid not in candidate_ids:
                candidate_ids.append(cid)
    return MenuMatchResult(
        status=status if status in {"ambiguous", "none"} else "none",
        confidence=confidence,
        confirm_name=confirm_name,
        candidate_ids=tuple(candidate_ids),
    )


def _parse_json_object(text: str) -> Any:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            return json.loads(raw[start : end + 1])
        raise


class OpenAiMenuMatcher:
    def __init__(self, client: Any, model: str) -> None:
        self._client = client
        self._model = model

    async def match(self, spoken_name: str, items: list[MenuItem]) -> MenuMatchResult:
        spoken = (spoken_name or "").strip()
        if not spoken or not items:
            return MenuMatchResult(status="none")
        catalog = [
            {
                "id": item.id,
                "name": item.name,
                "category": item.category,
                "description": item.description,
                "available": item.available,
            }
            for item in items
        ]
        user = (
            f"Spoken name: {spoken}\n"
            f"Catalog: {json.dumps(catalog, ensure_ascii=False)}"
        )
        try:
            completion = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": _MATCH_SYSTEM},
                    {"role": "user", "content": user},
                ],
                temperature=0,
                max_tokens=250,
                response_format={"type": "json_object"},
            )
            content = ""
            choices = getattr(completion, "choices", None) or []
            if choices:
                message = getattr(choices[0], "message", None)
                content = (getattr(message, "content", None) or "") if message else ""
            payload = _parse_json_object(content)
        except Exception:
            logger.exception("Menu matcher LLM failed spoken=%r", spoken[:80])
            return MenuMatchResult(status="none")
        return coerce_menu_match(payload, items)


class ScriptedMenuMatcher:
    """Test double: map spoken_name → MenuMatchResult."""

    def __init__(self, by_spoken: dict[str, MenuMatchResult] | None = None) -> None:
        self.by_spoken = by_spoken or {}
        self.calls: list[str] = []

    async def match(self, spoken_name: str, items: list[MenuItem]) -> MenuMatchResult:
        self.calls.append(spoken_name)
        if spoken_name in self.by_spoken:
            return self.by_spoken[spoken_name]
        lowered = spoken_name.strip().lower()
        for key, result in self.by_spoken.items():
            if key.strip().lower() == lowered:
                return result
        return MenuMatchResult(status="none")
