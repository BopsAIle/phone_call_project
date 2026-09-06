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
    "Bạn chỉ được chọn trong list chi nhánh được gửi kèm. Không tìm nhà hàng ngoài list. "
    "Ưu tiên khớp TÊN chi nhánh (và name_for_match). Địa chỉ chỉ dùng khi tên không đủ phân biệt. "
    "HCM, TP HCM, TPHCM, Sài Gòn nghĩa là Hồ Chí Minh. "
    "Nếu lời nói là HCM / Hồ Chí Minh và có đúng một chi nhánh có HCM hoặc Hồ Chí Minh trong TÊN, "
    "chọn chi nhánh đó — không chọn chi nhánh khác chỉ vì địa chỉ chứa HCM. "
    "Nếu lời nói chỉ một mục (ví dụ 'tôi muốn chọn chi nhánh quận 3' khi list có "
    "Quận 1, Quận 2, Quận 3) thì status=match, lấy đúng mục đó. "
    "Số quận phải khớp chính xác: Quận 3 không phải Quận 1, Quận 13, hay Quận 30. "
    "status=ambiguous nếu hai mục trở lên gần như nhau. "
    "status=none chỉ khi không mục nào liên quan tới lời nói. "
    "Trả JSON với khóa: status, branch_id, index, confidence, confirm_name. "
    "branch_id phải là id trong list hoặc null. "
    "index là số thứ tự 1-based của mục được chọn, hoặc null. "
    "confidence là high hoặc low. "
    "confirm_name là tên đúng trong list, hoặc để trống. "
    "Nếu ambiguous, thêm candidate_ids là các id trong list."
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
        catalog = _catalog_for_judge(branches)
        expanded = expand_place_aliases(spoken)
        user = (
            "List chi nhánh (chỉ được chọn từ đây):\n"
            f"{json.dumps(catalog, ensure_ascii=False)}\n"
            f"Lời người gọi: {spoken}\n"
        )
        if expanded != spoken:
            user += f"Viết tắt địa danh đã mở rộng: {expanded}\n"
        user += "Hãy đánh giá mục nào trong list giống với chi nhánh người gọi nói."
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
