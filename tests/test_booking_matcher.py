from __future__ import annotations

import json
from types import SimpleNamespace

from booking.matcher import OpenAiBranchMatcher, coerce_match_result
from booking.models import Branch

Q1 = Branch(id="q1", name="Chi nhánh Quận 1", address="Nguyễn Huệ, Quận 1")
Q2 = Branch(id="q2", name="Chi nhánh Quận 2", address="Thủ Thiêm, Quận 2")
Q3 = Branch(id="q3", name="Chi nhánh Quận 3", address="Võ Văn Tần, Quận 3")
DISTRICT_BRANCHES = [Q1, Q2, Q3]


class _FakeChatClient:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls: list[dict] = []
        self.chat = SimpleNamespace(completions=self)

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps(self.payload, ensure_ascii=False)
                    )
                )
            ]
        )


def test_coerce_uses_branch_id_from_list() -> None:
    result = coerce_match_result(
        {
            "status": "match",
            "branch_id": "q3",
            "index": 3,
            "confidence": "high",
            "confirm_name": "Chi nhánh Quận 3",
        },
        DISTRICT_BRANCHES,
    )
    assert result.status == "match"
    assert result.branch_id == "q3"
    assert result.confidence == "high"


def test_coerce_recovers_match_from_list_index_when_id_is_wrong() -> None:
    result = coerce_match_result(
        {
            "status": "match",
            "branch_id": "not-in-catalog",
            "index": 3,
            "confidence": "high",
            "confirm_name": "Chi nhánh Quận 3",
        },
        DISTRICT_BRANCHES,
    )
    assert result.status == "match"
    assert result.branch_id == "q3"


def test_coerce_recovers_match_from_confirm_name() -> None:
    result = coerce_match_result(
        {
            "status": "match",
            "branch_id": "invented",
            "confidence": "high",
            "confirm_name": "Chi nhánh Quận 3",
        },
        DISTRICT_BRANCHES,
    )
    assert result.status == "match"
    assert result.branch_id == "q3"


def test_coerce_unknown_store_is_none() -> None:
    result = coerce_match_result({"status": "none"}, DISTRICT_BRANCHES)
    assert result.status == "none"
    assert result.branch_id == ""


async def test_openai_matcher_sends_list_and_spoken_name_to_llm() -> None:
    client = _FakeChatClient(
        {
            "status": "match",
            "branch_id": "q3",
            "index": 3,
            "confidence": "high",
            "confirm_name": "Chi nhánh Quận 3",
        }
    )
    matcher = OpenAiBranchMatcher(client, "gpt-test")
    result = await matcher.match("tôi muốn chọn chi nhánh quận 3", DISTRICT_BRANCHES)
    assert result.status == "match"
    assert result.branch_id == "q3"
    assert len(client.calls) == 1
    user = client.calls[0]["messages"][1]["content"]
    assert "tôi muốn chọn chi nhánh quận 3" in user
    assert "Chi nhánh Quận 1" in user
    assert "Chi nhánh Quận 2" in user
    assert "Chi nhánh Quận 3" in user
    assert "q3" in user


def test_expand_hcm_means_ho_chi_minh() -> None:
    from booking.matcher import expand_place_aliases

    assert expand_place_aliases("chi nhánh HCM") == "chi nhánh Hồ Chí Minh"
    assert expand_place_aliases("chi nhánh hcm") == "chi nhánh Hồ Chí Minh"
    assert expand_place_aliases("TP HCM") == "thành phố Hồ Chí Minh"
    assert expand_place_aliases("TP.HCM") == "thành phố Hồ Chí Minh"
    assert expand_place_aliases("TPHCM") == "thành phố Hồ Chí Minh"
    assert expand_place_aliases("H C M") == "Hồ Chí Minh"
    assert expand_place_aliases("hát xì em") == "Hồ Chí Minh"
    assert expand_place_aliases("Sài Gòn") == "Hồ Chí Minh"
    assert expand_place_aliases("tôi muốn chọn chi nhánh quận 3") == (
        "tôi muốn chọn chi nhánh quận 3"
    )


def test_named_hcm_wins_over_address_containing_hcm() -> None:
    from booking.matcher import match_named_hcm_branch

    hcm = Branch(id="hcm", name="Chi nhánh HCM", address="Quận 1")
    q1 = Branch(id="q1", name="Chi nhánh Quận 1", address="Nguyễn Huệ, HCM")
    hn = Branch(id="hn", name="Chi nhánh Hà Nội", address="Minh Khai, Hà Nội")
    result = match_named_hcm_branch("tôi muốn chi nhánh HCM", [q1, hn, hcm])
    assert result is not None
    assert result.status == "match"
    assert result.branch_id == "hcm"
    assert result.confidence == "high"


async def test_named_hcm_branch_skips_llm() -> None:
    client = _FakeChatClient({"status": "none"})
    hcm = Branch(id="hcm", name="Chi nhánh Hồ Chí Minh", address="Quận 1")
    hn = Branch(id="hn", name="Chi nhánh Hà Nội", address="Minh Khai, Hà Nội")
    matcher = OpenAiBranchMatcher(client, "gpt-test")
    result = await matcher.match("tôi muốn chọn chi nhánh HCM", [hn, hcm])
    assert result.status == "match"
    assert result.branch_id == "hcm"
    assert client.calls == []


async def test_openai_matcher_expands_hcm_alias_for_llm_when_name_has_no_hcm() -> None:
    client = _FakeChatClient(
        {
            "status": "match",
            "branch_id": "q1",
            "index": 1,
            "confidence": "high",
            "confirm_name": "Chi nhánh Quận 1",
        }
    )
    q1 = Branch(id="q1", name="Chi nhánh Quận 1", address="Nguyễn Huệ, HCM")
    matcher = OpenAiBranchMatcher(client, "gpt-test")
    result = await matcher.match("tôi muốn chọn chi nhánh HCM", [q1])
    assert result.status == "match"
    assert result.branch_id == "q1"
    assert len(client.calls) == 1
    user = client.calls[0]["messages"][1]["content"]
    assert "tôi muốn chọn chi nhánh HCM" in user
    assert "Hồ Chí Minh" in user
    system = client.calls[0]["messages"][0]["content"]
    assert "HCM" in system
    assert "Hồ Chí Minh" in system
