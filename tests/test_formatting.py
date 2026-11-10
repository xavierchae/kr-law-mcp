from kr_law_mcp.formatting import fmt_date, format_articles, law_url
from kr_law_mcp.parsing import parse_law_document
from tests.conftest import load


def test_fmt_date():
    assert fmt_date("20240917") == "2024. 9. 17."
    assert fmt_date("") == ""


def test_law_url_encodes_korean():
    assert (
        law_url("민법", "제750조")
        == "https://www.law.go.kr/%EB%B2%95%EB%A0%B9/%EB%AF%BC%EB%B2%95/%EC%A0%9C750%EC%A1%B0"
    )


def test_truncation_hint():
    doc = parse_law_document(load("synthetic_law_small.json"))
    out = format_articles(doc, None, None, include_addenda=True, max_chars=150)
    assert "제1조(목적)" in out
    assert "from_article='제2조'" in out
    assert "### 부칙" not in out


def test_first_article_always_shown_even_if_long():
    doc = parse_law_document(load("synthetic_law_small.json"))
    out = format_articles(doc, (3, 0), None, include_addenda=False, max_chars=10)
    assert "제3조(위원회의 설치)" in out


def test_heading_whitespace_collapsed():
    from kr_law_mcp.formatting import render_article
    from kr_law_mcp.models import Article

    heading = Article(number=1, branch=0, is_article=False, title="", text="제3장 유류분\n  <신설 1977.12.31>")
    assert render_article(heading) == "#### 제3장 유류분 <신설 1977.12.31>"
