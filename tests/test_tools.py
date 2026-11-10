"""End-to-end tool tests with the HTTP layer mocked by respx."""

import httpx
import pytest
import respx

from kr_law_mcp import server
from kr_law_mcp.client import DEFAULT_BASE_URL
from tests.conftest import load
from tests.fakes import ABBREVIATIONS, LAWS

SEARCH_URL = f"{DEFAULT_BASE_URL}/lawSearch.do"
SERVICE_URL = f"{DEFAULT_BASE_URL}/lawService.do"


def _row(x):
    return {
        "법령ID": x.law_id,
        "법령명한글": x.name,
        "법령약칭명": x.abbreviation,
        "법령구분명": x.kind,
        "소관부처명": x.ministry,
        "시행일자": "20250101",
        "공포일자": "20240101",
        "공포번호": "1",
    }


def _search(request: httpx.Request) -> httpx.Response:
    params = request.url.params
    if params.get("target") == "lsAbrv":
        return httpx.Response(200, json={"LawSearch": {"totalCnt": "2", "law": [_row(x) for x in ABBREVIATIONS]}})
    query = params.get("query", "")
    hits = [_row(x) for x in LAWS if query in x.name]
    return httpx.Response(200, json={"LawSearch": {"totalCnt": str(len(hits)), "page": "1", "law": hits}})


def _service(request: httpx.Request) -> httpx.Response:
    law_id = request.url.params.get("ID")
    if law_id == "001823":
        return httpx.Response(200, json=load("synthetic_law_building_art3.json"))
    if law_id == "009999":
        return httpx.Response(200, json=load("synthetic_law_small.json"))
    return httpx.Response(200, json={"Law": "일치하는 법령이 없습니다. 법령명을 확인하여 주십시오."})


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("LAW_OC", "tester")
    monkeypatch.delenv("LAW_API_BASE", raising=False)
    with respx.mock(assert_all_called=False) as mock:
        mock.get(SEARCH_URL).mock(side_effect=_search)
        mock.get(SERVICE_URL).mock(side_effect=_service)
        yield mock


async def test_get_article_down_to_mok(api):
    out = await server.get_article("건축법", "제3조", paragraph=1, item="2", subitem="다")
    assert "「건축법」 제3조(적용 제외) 제1항제2호다목" in out
    assert "다. 플랫폼" in out
    assert "운전보안시설" not in out
    assert "출처: 국가법령정보센터 「건축법」" in out
    sent = [c.request.url.params for c in api.calls if c.request.url.path.endswith("lawService.do")]
    assert sent[0]["JO"] == "000300" and sent[0]["target"] == "eflaw" and sent[0]["OC"] == "tester"


async def test_get_article_branch_item(api):
    out = await server.get_article("건축법", "3", item="2의2")
    assert "제2호의2" in out and "고속도로 통행료" in out


async def test_get_article_whole(api):
    out = await server.get_article("001823", "제3조")
    assert "① 다음 각 호" in out and "  2. 철도나" in out and "    가. 운전보안시설" in out
    assert "② 「국토의 계획" in out
    assert "법령명 해석" not in out


async def test_get_article_missing_paragraph(api):
    out = await server.get_article("건축법", "제3조", paragraph=5)
    assert "제5항이 없습니다" in out and "제1항, 제2항" in out


async def test_get_article_missing_mok(api):
    out = await server.get_article("건축법", "제3조", paragraph=1, item="2", subitem="라")
    assert "라목이 없습니다" in out and "가, 나, 다" in out


async def test_get_article_bad_number(api):
    out = await server.get_article("건축법", "삼조")
    assert "조문 번호를 해석할 수 없습니다" in out


async def test_get_article_interprets_abbreviation(api):
    out = await server.get_article("생명윤리법", "2", item="2")
    assert "> 법령명 해석: '생명윤리법' → 「생명윤리 및 안전에 관한 법률」" in out
    assert '2. "연구대상자"' in out


async def test_get_article_article_not_in_response(api):
    out = await server.get_article("생명윤리법", "제99조")
    assert "제99조가 없습니다" in out


async def test_unknown_law_lists_nothing(api):
    out = await server.get_article("존재하지않는법령이름", "1")
    assert "찾지 못했습니다" in out


async def test_ambiguous_law_lists_candidates(api):
    out = await server.get_law_overview("복지법")
    assert "하나로 특정되지 않았습니다" in out and "아동복지법" in out


async def test_overview(api):
    out = await server.get_law_overview("생명윤리법")
    assert "## 생명윤리 및 안전에 관한 법률" in out
    assert "**제1장 총칙**" in out and "- 제2조의2(기본 원칙)" in out
    assert "조문 4개" in out and "부칙 1개" in out and "별표·서식 1개" in out


async def test_articles_range_with_heading(api):
    out = await server.get_law_articles("생명윤리법", from_article="제2조의2", to_article="3")
    assert "제2조의2(기본 원칙)" in out
    assert "#### 제2장 국가생명윤리심의위원회" in out
    assert "제1조(목적)" not in out
    assert "제2조(정의)" not in out


async def test_articles_with_addenda(api):
    out = await server.get_law_articles("생명윤리법", include_addenda=True)
    assert "### 부칙" in out and "공포 후 6개월" in out
    assert "과태료의 부과기준 (https://www.law.go.kr/LSW/flDownload.do?flSeq=1)" in out


async def test_articles_bad_range(api):
    assert "뒤에 있습니다" in await server.get_law_articles("민법", "5", "2")


async def test_search_laws_table(api):
    out = await server.search_laws("근로기준법")
    assert "총 3건" in out and "| 근로기준법 시행령 |" in out


async def test_search_laws_kind_filter(api):
    out = await server.search_laws("근로기준법", law_kind="대통령령")
    assert "| 근로기준법 시행령 |" in out and "| 근로기준법 |" not in out


async def test_search_laws_fallback_variant(api):
    out = await server.search_laws("개인정보보호법")
    assert "그대로는 결과가 없어" in out and "| 개인정보 보호법 |" in out


async def test_missing_oc(monkeypatch):
    monkeypatch.delenv("LAW_OC", raising=False)
    out = await server.search_laws("민법")
    assert "LAW_OC" in out


async def test_auth_error_message(monkeypatch):
    monkeypatch.setenv("LAW_OC", "bad")
    with respx.mock:
        respx.get(SEARCH_URL).respond(
            200, json={"result": "사용자 정보 검증에 실패하였습니다.", "msg": "IP주소 및 도메인주소를 등록해 주세요."}
        )
        out = await server.search_laws("민법")
    assert "사용자 정보 검증에 실패" in out and "등록해 주세요" in out


async def test_non_json_response(monkeypatch):
    monkeypatch.setenv("LAW_OC", "x")
    with respx.mock:
        respx.get(SEARCH_URL).respond(200, text="<html>error</html>")
        out = await server.search_laws("민법")
    assert "JSON 아님" in out


async def test_tools_registered():
    tools = {t.name for t in await server.mcp.list_tools()}
    assert tools == {"search_laws", "get_law_overview", "get_law_articles", "get_article"}
