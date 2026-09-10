"""LLM judges which in-memory branch the caller meant."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional, Protocol

from booking.models import Branch, MatchResult

logger = logging.getLogger(__name__)

_PLACE_ALIASES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\btp\.?\s*hcm\b", re.IGNORECASE), "thành phố Hồ Chí Minh"),
    (re.compile(r"\btphcm\b", re.IGNORECASE), "thành phố Hồ Chí Minh"),
    (re.compile(r"hát\s*x[eêèéìíỉĩị]\s*em", re.IGNORECASE), "Hồ Chí Minh"),
    (re.compile(r"ách\s*x[eêèéìíỉĩịy]\s*em", re.IGNORECASE), "Hồ Chí Minh"),
    (re.compile(r"sài\s*gòn", re.IGNORECASE), "Hồ Chí Minh"),
    (re.compile(r"sai\s*gon", re.IGNORECASE), "Hồ Chí Minh"),
    (re.compile(r"\bh[\s.\-]*c[\s.\-]*m\b", re.IGNORECASE), "Hồ Chí Minh"),
)

_HCM_IN_TEXT = re.compile(r"hồ chí minh|\bhcm\b", re.IGNORECASE)

_MATCH_SYSTEM = (
    "You may only choose from the branch list sent with this request. Do not search restaurants outside the list. "
    "Prefer matching the branch NAME (and name_for_match). Use the address only when the name is not enough. "
    "HCM, TP HCM, TPHCM, and Saigon mean Ho Chi Minh. "
    "If the spoken words are HCM / Ho Chi Minh and exactly one branch has HCM or Ho Chi Minh in its NAME, "
    "choose that branch — do not choose another branch just because its address contains HCM. "
    "If the spoken words point to one item (for example 'I want the district 3 branch' when the list has "
    "District 1, District 2, District 3) then status=match and pick that item. "
    "District numbers must match exactly: District 3 is not District 1, District 13, or District 30. "
    "status=ambiguous if two or more items are about equally close. "
    "status=none only when no item relates to the spoken words. "
    "Return JSON with keys: status, branch_id, index, confidence, confirm_name. "
    "branch_id must be an id from the list or null. "
    "index is the 1-based index of the chosen item, or null. "
    "confidence is high or low. "
    "confirm_name is the exact name from the list, or empty. "
    "If ambiguous, add candidate_ids with ids from the list."
)


def expand_place_aliases(spoken: str) -> str:
    """HCM / TP HCM / Sài Gòn → Hồ Chí Minh so the matcher can compare with catalog names."""
    text = spoken or ""
    for pattern, replacement in _PLACE_ALIASES:
        text = pattern.sub(replacement, text)
    return text


def _name_refers_to_hcm(text: str) -> bool:
    raw = text or ""
    if _HCM_IN_TEXT.search(raw):
        return True
    return "hồ chí minh" in expand_place_aliases(raw).casefold()


def match_named_hcm_branch(spoken: str, branches: list[Branch]) -> Optional[MatchResult]:
    """If the caller said HCM and exactly one branch is named HCM / Hồ Chí Minh, lock that name."""
    if not _name_refers_to_hcm(spoken):
        return None
    hits = [branch for branch in branches if _name_refers_to_hcm(branch.name)]
    if len(hits) == 1:
        branch = hits[0]
        return MatchResult(
            status="match",
            branch_id=branch.id,
            confidence="high",
            confirm_name=branch.name,
        )
    if len(hits) > 1:
        return MatchResult(
            status="ambiguous",
            confidence="low",
            candidate_ids=tuple(branch.id for branch in hits),
        )
    return None


_TOKEN_SPLIT = re.compile(r"[^\w]+", re.UNICODE)
_GENERIC_TOKENS = frozenset(
    {
        "chi",
        "nhánh",
        "nhanh",
        "quận",
        "quan",
        "tôi",
        "toi",
        "mình",
        "minh",
        "cho",
        "muốn",
        "muon",
        "chọn",
        "chon",
        "cái",
        "cai",
        "gần",
        "gan",
        "branch",
        "please",
        "like",
        "the",
        "and",
        "for",
    }
)


def match_unique_branch_name(spoken: str, branches: list[Branch]) -> Optional[MatchResult]:
    """Lock when the caller names one branch uniquely (e.g. 'KFC'). No LLM."""
    spoken_cf = (spoken or "").strip().casefold()
    if not spoken_cf or not branches:
        return None
    hits: list[Branch] = []
    for branch in branches:
        name_cf = (branch.name or "").strip().casefold()
        if not name_cf:
            continue
        if name_cf == spoken_cf or name_cf in spoken_cf:
            hits.append(branch)
            continue
        if len(spoken_cf) >= 3 and spoken_cf not in _GENERIC_TOKENS and spoken_cf in name_cf:
            hits.append(branch)
    if not hits:
        tokens = [
            token
            for token in _TOKEN_SPLIT.split(spoken_cf)
            if len(token) >= 3 and token not in _GENERIC_TOKENS
        ]
        for token in tokens:
            token_hits = [
                branch
                for branch in branches
                if token in (branch.name or "").casefold()
            ]
            if len(token_hits) == 1:
                hits = token_hits
                break
    if len(hits) == 1:
        branch = hits[0]
        return MatchResult(
            status="match",
            branch_id=branch.id,
            confidence="high",
            confirm_name=branch.name,
        )
    if len(hits) > 1:
        return MatchResult(
            status="ambiguous",
            confidence="low",
            candidate_ids=tuple(branch.id for branch in hits),
        )
    return None


class BranchMatcher(Protocol):
    async def match(self, spoken_name: str, branches: list[Branch]) -> MatchResult:
        ...


def _parse_index(payload: dict[str, Any], count: int) -> Optional[int]:
    raw = payload.get("index")
    if raw is None:
        raw = payload.get("list_index")
    try:
        idx = int(raw)
    except (TypeError, ValueError):
        return None
    if 1 <= idx <= count:
        return idx - 1
    if 0 <= idx < count:
        return idx
    return None


def _branch_by_confirm_name(confirm_name: str, branches: list[Branch]) -> Optional[Branch]:
    needle = (confirm_name or "").strip().casefold()
    if not needle:
        return None
    exact = [branch for branch in branches if branch.name.casefold() == needle]
    if len(exact) == 1:
        return exact[0]
    contained = [
        branch
        for branch in branches
        if needle in f"{branch.name} {branch.address}".casefold()
    ]
    if len(contained) == 1:
        return contained[0]
    return None


def coerce_match_result(payload: Any, branches: list[Branch]) -> MatchResult:
    catalog = {b.id: b for b in branches}
    if not isinstance(payload, dict):
        return MatchResult(status="none")
    status = str(payload.get("status") or "none").strip().lower()
    if status not in {"match", "ambiguous", "none"}:
        status = "none"
    raw_id = payload.get("branch_id")
    branch_id = str(raw_id).strip() if raw_id else ""
    confidence = str(payload.get("confidence") or "low").strip().lower()
    if confidence not in {"high", "low"}:
        confidence = "low"
    confirm_name = str(payload.get("confirm_name") or "").strip()

    if status == "match":
        branch = catalog.get(branch_id)
        if branch is None:
            idx = _parse_index(payload, len(branches))
            if idx is not None:
                branch = branches[idx]
        if branch is None:
            branch = _branch_by_confirm_name(confirm_name, branches)
        if branch is None:
            return MatchResult(status="none")
        return MatchResult(
            status="match",
            branch_id=branch.id,
            confidence=confidence,
            confirm_name=confirm_name or branch.name,
        )

    candidate_ids: list[str] = []
    raw_candidates = payload.get("candidate_ids") or payload.get("candidates") or []
    if isinstance(raw_candidates, list):
        for item in raw_candidates:
            cid = ""
            if isinstance(item, str):
                cid = item.strip()
            elif isinstance(item, dict):
                cid = str(item.get("id") or item.get("branch_id") or "").strip()
            if cid and cid in catalog and cid not in candidate_ids:
                candidate_ids.append(cid)
    return MatchResult(
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


def _catalog_for_judge(branches: list[Branch]) -> list[dict[str, Any]]:
    return [
        {
            "index": i,
            "id": branch.id,
            "name": branch.name,
            "name_for_match": expand_place_aliases(branch.name),
            "address": branch.address,
        }
        for i, branch in enumerate(branches, start=1)
    ]


class OpenAiBranchMatcher:
    def __init__(self, client: Any, model: str) -> None:
        self._client = client
        self._model = model

    async def match(self, spoken_name: str, branches: list[Branch]) -> MatchResult:
        spoken = (spoken_name or "").strip()
        if not spoken or not branches:
            return MatchResult(status="none")
        named = match_named_hcm_branch(spoken, branches)
        if named is not None:
            return named
        unique = match_unique_branch_name(spoken, branches)
        if unique is not None:
            return unique
        catalog = _catalog_for_judge(branches)
        expanded = expand_place_aliases(spoken)
        user = (
            "Branch list (choose only from here):\n"
            f"{json.dumps(catalog, ensure_ascii=False)}\n"
            f"Caller said: {spoken}\n"
        )
        if expanded != spoken:
            user += f"Expanded place alias: {expanded}\n"
        user += "Decide which item in the list matches the branch the caller named."
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
            logger.exception("Branch matcher LLM failed spoken=%r", spoken[:80])
            return MatchResult(status="none")
        return coerce_match_result(payload, branches)


class ScriptedBranchMatcher:
    """Test double: map spoken_name → MatchResult."""

    def __init__(self, by_spoken: dict[str, MatchResult] | None = None) -> None:
        self.by_spoken = by_spoken or {}
        self.calls: list[str] = []

    async def match(self, spoken_name: str, branches: list[Branch]) -> MatchResult:
        self.calls.append(spoken_name)
        if spoken_name in self.by_spoken:
            return self.by_spoken[spoken_name]
        lowered = spoken_name.strip().lower()
        for key, result in self.by_spoken.items():
            if key.strip().lower() == lowered:
                return result
        return MatchResult(status="none")
