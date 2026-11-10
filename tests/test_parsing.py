import pytest

from kr_law_mcp.parsing import (
    as_list,
    encode_unit,
    item_number,
    paragraph_number,
    parse_article_no,
    parse_law_document,
    parse_search,
    subitem_key,
    text_of,
)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("제750조", (750, 0)),
        ("750", (750, 0)),
        ("750조", (750, 0)),
        ("제10조의2", (10, 2)),
        ("10조의2", (10, 2)),
        ("10의2", (10, 2)),
        ("10-2", (10, 2)),
        (" 제 10 조 의 2 ", (10, 2)),
        (3, (3, 0)),
    ],
)
def test_parse_article_no(raw, expected):
    assert parse_article_no(raw) == expected


@pytest.mark.parametrize("raw", ["", "abc", "제조", "0", "제1항"])
def test_parse_article_no_rejects(raw):
    with pytest.raises(ValueError):
        parse_article_no(raw)


def test_encode_unit():
    assert encode_unit(2) == "000200"
    assert encode_unit(10, 2) == "001002"
    assert encode_unit(750) == "075000"


@pytest.mark.parametrize(
    "raw, expected", [("①", 1), ("⑩", 10), ("⑳", 20), ("㉑", 21), ("3", 3), ("제2항", 2), ("", None)]
)
def test_paragraph_number(raw, expected):
    assert paragraph_number(raw) == expected


@pytest.mark.parametrize(
    "raw, expected", [("2.", (2, 0)), ("2의2.", (2, 2)), ("제3호", (3, 0)), ("2", (2, 0)), ("x", None)]
)
def test_item_number(raw, expected):
    assert item_number(raw) == expected


def test_subitem_key():
    assert subitem_key("다.") == "다"
    assert subitem_key("다목") == "다"
    assert subitem_key("가") == "가"


def test_as_list_and_text_of():
    assert as_list(None) == []
    assert as_list({"a": 1}) == [{"a": 1}]
    assert as_list([1, 2]) == [1, 2]
    assert text_of([["a"], ["b", " c "]]) == "a\nb\nc"
    assert text_of({"content": "법률", "법종구분코드": "A0002"}) == "법률"


def test_parse_search_single_dict(fixture):
    result = parse_search(fixture("synthetic_search_single.json"))
    assert result.total == 1
    assert len(result.items) == 1
    law = result.items[0]
    assert (law.law_id, law.name, law.kind, law.ministry) == ("001706", "민법", "법률", "법무부")


def test_parse_search_empty():
    assert parse_search({"LawSearch": {"totalCnt": "0", "page": "1"}}).items == []


def test_parse_law_document(fixture):
    doc = parse_law_document(fixture("synthetic_law_small.json"))
    assert doc.info.name == "생명윤리 및 안전에 관한 법률"
    assert doc.info.kind == "법률"
    assert doc.info.ministry == "보건복지부"
    headings = [a for a in doc.articles if not a.is_article]
    assert [h.text for h in headings] == ["제1장 총칙", "제2장 국가생명윤리심의위원회"]
    art22 = next(a for a in doc.articles if (a.number, a.branch) == (2, 2))
    assert art22.label == "제2조의2"
    assert "존중되어야 한다." in art22.text
    art2 = next(a for a in doc.articles if a.is_article and (a.number, a.branch) == (2, 0))
    assert art2.paragraphs[0].no == ""
    assert len(art2.paragraphs[0].items) == 2
    assert "공포 후 6개월" in doc.addenda[0].text
    assert doc.appendices[0].title == "과태료의 부과기준"


def test_parse_law_document_missing():
    with pytest.raises(ValueError):
        parse_law_document({"LawService": {}})


# --- real captures (tests/fixtures/real_*.json, OC scrubbed) -----------------


def test_real_search_list(fixture):
    result = parse_search(fixture("real_search_minbeop.json"))
    assert result.total == len(result.items) == 6
    minbeop = next(i for i in result.items if i.name == "민법")
    assert (minbeop.law_id, minbeop.kind, minbeop.ministry) == ("001706", "법률", "법무부")
    assert any(i.kind == "법무부령" for i in result.items)  # 시행규칙 kind carries the ministry


def test_real_search_empty(fixture):
    # 약칭 "생명윤리법" is not matched by 법령명 search
    result = parse_search(fixture("real_search_saengmyeong.json"))
    assert result.total == 0 and result.items == []


def test_real_abbreviations(fixture):
    items = parse_search(fixture("real_abbreviations_sample.json")).items
    assert ("생명윤리 및 안전에 관한 법률", "생명윤리법") in {(i.name, i.abbreviation) for i in items}


def test_real_article_single_dict(fixture):
    doc = parse_law_document(fixture("real_building_art3.json"))
    assert doc.info.name == "건축법" and doc.info.kind == "법률" and doc.info.ministry == "국토교통부"
    (art,) = doc.articles  # 조문단위 is a dict when JO is given
    assert art.label == "제3조" and art.title == "적용 제외"
    assert [paragraph_number(p.no) for p in art.paragraphs] == [1, 2, 3]
    item2 = art.paragraphs[0].items[1]
    assert [subitem_key(s.no) for s in item2.subitems] == ["가", "나", "다", "라"]
