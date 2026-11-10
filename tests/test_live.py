"""Live checks against law.go.kr. Run with: LAW_OC=<key> uv run pytest -m live

Requires an issued OC key AND this machine's IP/domain registered on
open.law.go.kr; otherwise the API answers "사용자 정보 검증에 실패하였습니다".
Set SAVE_FIXTURES=1 to write raw responses to tests/fixtures/real_*.json.
"""

import json
import os
import re
from pathlib import Path

import pytest

from kr_law_mcp import server
from kr_law_mcp.client import LawApiClient

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not os.environ.get("LAW_OC"), reason="LAW_OC not set"),
]

FIXTURES = Path(__file__).parent / "fixtures"


async def _save(name: str, endpoint: str, params: dict) -> None:
    if not os.environ.get("SAVE_FIXTURES"):
        return
    async with LawApiClient() as client:
        data = await client._get(endpoint, params)
    if name == "abbreviations_sample":  # full list is ~2.7k rows / 2 MB
        rows = data["LawSearch"]["law"]
        data["LawSearch"]["law"] = [r for r in rows if "생명윤리" in r["법령명한글"]] + rows[:3]
    text = json.dumps(data, ensure_ascii=False, indent=2)
    # The API echoes the caller's OC inside 법령상세링크; never write it to disk.
    text = re.sub(r"OC=[^&\"]*", "OC=test", text)
    (FIXTURES / f"real_{name}.json").write_text(text, encoding="utf-8")


async def test_capture_fixtures():
    await _save("search_minbeop", "lawSearch.do", {"target": "eflaw", "query": "민법", "nw": 3, "display": 100})
    await _save("search_saengmyeong", "lawSearch.do", {"target": "eflaw", "query": "생명윤리법", "nw": 3})
    await _save("abbreviations_sample", "lawSearch.do", {"target": "lsAbrv"})
    await _save("building_art3", "lawService.do", {"target": "eflaw", "ID": "001823", "JO": "000300"})


async def test_civil_code_750():
    out = await server.get_article("민법", "제750조")
    assert "불법행위" in out and "출처: 국가법령정보센터 「민법」" in out


async def test_building_act_mok():
    out = await server.get_article("건축법", "제3조", paragraph=1, item="2", subitem="다")
    assert "다목" in out and "다." in out


async def test_bioethics_abbreviation():
    out = await server.get_article("생명윤리법", "제2조")
    assert "생명윤리 및 안전에 관한 법률" in out


@pytest.mark.parametrize("raw", ["개인정보보호법", "근기법 시행령", "근로기준법 시행규칙"])
async def test_loose_names_resolve(raw):
    out = await server.get_law_overview(raw)
    assert "### 목차" in out, out[:500]


async def test_body_search():
    out = await server.search_laws("연차 유급휴가", search_in="body", law_kind="법률")
    assert "근로기준법" in out
