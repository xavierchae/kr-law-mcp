import pytest

from kr_law_mcp.resolver import normalize, parse_query, resolve_law
from tests.fakes import FakeClient


def test_normalize():
    assert normalize("개인정보 보호법") == normalize("개인정보보호법")
    assert normalize("「민법」") == "민법"


@pytest.mark.parametrize(
    "raw, base, sub, core",
    [
        ("민법", "민법", "", "민법"),
        ("근로기준법 시행령", "근로기준법", "시행령", "근로기준"),
        ("근기법시행령", "근로기준법", "시행령", "근로기준"),
        ("생명윤리법", "생명윤리 및 안전에 관한 법률", "", "생명윤리및안전"),
        ("건축법 시행규칙", "건축법", "시행규칙", "건축"),
        ("「청소년 보호법」", "청소년 보호법", "", "청소년보호"),
    ],
)
def test_parse_query(raw, base, sub, core):
    q = parse_query(raw)
    assert (q.base, q.sub, q.core) == (base, sub, core)


@pytest.mark.parametrize(
    "raw, expected_id",
    [
        ("민법", "001706"),
        ("건축법", "001823"),  # not 건축법 시행령
        ("건축법 시행령", "002118"),
        ("근로기준법 시행규칙", "007364"),
        ("근기법", "001872"),  # informal alias
        ("근기법 시행령", "003893"),
        ("개인정보보호법", "011357"),  # spacing differs from 「개인정보 보호법」
        ("개인정보보호법 시행령", "011468"),
        ("생명윤리법", "009999"),
        ("생명윤리", "009999"),
        ("가정폭력방지법", "005555"),  # official 약칭 list only (not in alias table)
    ],
)
async def test_resolve(raw, expected_id):
    res = await resolve_law(FakeClient(), raw)
    assert res.law is not None, res.candidates
    assert res.law.law_id == expected_id


async def test_exact_name_needs_one_call():
    client = FakeClient()
    res = await resolve_law(client, "민법")
    assert res.law.law_id == "001706"
    assert client.queries == ["민법"]
    assert client.abbr_calls == 0
    assert not res.interpreted


async def test_interpreted_flag():
    res = await resolve_law(FakeClient(), "생명윤리법")
    assert res.interpreted


async def test_ambiguous_returns_candidates():
    res = await resolve_law(FakeClient(), "복지법")
    assert res.law is None
    names = {c.name for c, _ in res.candidates}
    assert {"아동복지법", "장애인복지법"} <= names


async def test_unknown_returns_nothing():
    res = await resolve_law(FakeClient(), "존재하지않는법령이름")
    assert res.law is None
    assert res.candidates == []


def test_kind_rank():
    from kr_law_mcp.resolver import kind_rank

    assert (
        kind_rank("법률")
        < kind_rank("대통령령")
        < kind_rank("총리령")
        < kind_rank("고용노동부령")
        < kind_rank("대법원규칙")
    )
