"""Pure helpers: article-number parsing and JSON normalization.

The 법제처 JSON output is loosely typed: a repeated element is a dict when there
is one occurrence and a list otherwise, and text fields may be a string, a list
of (lists of) strings, or a dict with a ``content`` key. Everything here
tolerates those shapes so the rest of the code can work with plain types.
"""

from __future__ import annotations

import re
from typing import Any

from .models import (
    Addendum,
    Appendix,
    Article,
    Item,
    LawDocument,
    LawInfo,
    LawSummary,
    Paragraph,
    SearchResult,
    SubItem,
)

# ---------------------------------------------------------------------------
# Generic JSON helpers
# ---------------------------------------------------------------------------


def as_list(value: Any) -> list[Any]:
    """Return ``value`` as a list (None -> [], dict/str -> [value])."""
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return value
    return [value]


def text_of(value: Any) -> str:
    """Flatten a text-ish JSON value into a single stripped string."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        if "content" in value:
            return text_of(value["content"])
        return ""
    if isinstance(value, list):
        parts = [text_of(v) for v in value]
        return "\n".join(p for p in parts if p)
    return str(value).strip()


def _field(d: dict[str, Any], *keys: str) -> str:
    """First non-empty text among ``keys``."""
    for key in keys:
        if key in d:
            text = text_of(d[key])
            if text:
                return text
    return ""


# ---------------------------------------------------------------------------
# Article / unit numbers
# ---------------------------------------------------------------------------

_ARTICLE_RE = re.compile(r"^제?\s*(\d+)\s*조?\s*(?:(?:의|-|_)\s*(\d+))?$")
_ITEM_RE = re.compile(r"^제?\s*(\d+)\s*호?\s*(?:(?:의|-|_)\s*(\d+))?\.?$")
_LEADING_NUM_RE = re.compile(r"^\s*(\d+)\s*(?:의\s*(\d+))?")


def parse_article_no(value: str | int) -> tuple[int, int]:
    """Parse "제10조의2", "10조의2", "10의2", "10-2", "750" -> (number, branch)."""
    text = str(value).strip().replace(" ", "")
    m = _ARTICLE_RE.match(text)
    if not m:
        raise ValueError(f"조문 번호를 해석할 수 없습니다: {value!r} (예: '제750조', '10조의2')")
    number = int(m.group(1))
    branch = int(m.group(2)) if m.group(2) else 0
    if number <= 0:
        raise ValueError(f"조문 번호는 1 이상이어야 합니다: {value!r}")
    return number, branch


def encode_unit(number: int, branch: int = 0) -> str:
    """Encode to the API's 6-digit JO/HANG/HO format: 10조의2 -> '001002'."""
    return f"{number:04d}{branch:02d}"


def article_label(number: int, branch: int = 0) -> str:
    return f"제{number}조의{branch}" if branch else f"제{number}조"


_CIRCLED_RANGES = [
    (0x2460, 1, 20),  # ①..⑳
    (0x3251, 21, 35),  # ㉑..㉟
    (0x32B1, 36, 50),  # ㊱..㊿
]


def circled_to_int(ch: str) -> int | None:
    if len(ch) != 1:
        return None
    code = ord(ch)
    for start, first, last in _CIRCLED_RANGES:
        if start <= code <= start + (last - first):
            return first + (code - start)
    return None


def paragraph_number(value: str | int) -> int | None:
    """Parse a 항번호 such as "①", "1", "제1항" -> 1."""
    text = str(value).strip().replace(" ", "")
    if not text:
        return None
    circled = circled_to_int(text[0])
    if circled is not None:
        return circled
    m = re.match(r"^제?(\d+)항?\.?$", text)
    return int(m.group(1)) if m else None


def item_number(value: str | int) -> tuple[int, int] | None:
    """Parse a 호번호 such as "2.", "2의2.", "제2호" -> (2, 0) / (2, 2)."""
    text = str(value).strip().replace(" ", "")
    if not text:
        return None
    m = _ITEM_RE.match(text)
    if m:
        return int(m.group(1)), int(m.group(2)) if m.group(2) else 0
    m = _LEADING_NUM_RE.match(text)
    if m:
        return int(m.group(1)), int(m.group(2)) if m.group(2) else 0
    return None


def subitem_key(value: str) -> str:
    """Normalize a 목번호: "다.", "다목", "다" -> "다"."""
    text = str(value).strip().replace(" ", "").rstrip(".")
    if text.endswith("목") and len(text) > 1:
        text = text[:-1]
    return text


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def _search_root(data: dict[str, Any]) -> dict[str, Any]:
    if "LawSearch" in data and isinstance(data["LawSearch"], dict):
        return data["LawSearch"]
    if len(data) == 1:
        (only,) = data.values()
        if isinstance(only, dict):
            return only
    return data


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(text_of(value) or default)
    except ValueError:
        return default


def parse_law_summary(row: dict[str, Any]) -> LawSummary:
    return LawSummary(
        law_id=_field(row, "법령ID"),
        mst=_field(row, "법령일련번호"),
        name=_field(row, "법령명한글", "법령명"),
        abbreviation=_field(row, "법령약칭명"),
        kind=_field(row, "법령구분명"),
        ministry=_field(row, "소관부처명"),
        effective_date=_field(row, "시행일자"),
        promulgation_date=_field(row, "공포일자"),
        promulgation_no=_field(row, "공포번호"),
        revision_type=_field(row, "제개정구분명"),
    )


def parse_search(data: dict[str, Any]) -> SearchResult:
    root = _search_root(data)
    rows = [r for r in as_list(root.get("law")) if isinstance(r, dict)]
    items = [parse_law_summary(r) for r in rows]
    return SearchResult(
        total=_to_int(root.get("totalCnt"), len(items)),
        page=_to_int(root.get("page"), 1),
        items=[i for i in items if i.law_id and i.name],
    )


def _parse_paragraph(p: dict[str, Any]) -> Paragraph:
    items: list[Item] = []
    for h in as_list(p.get("호")):
        if not isinstance(h, dict):
            continue
        subitems = [
            SubItem(no=_field(m, "목번호"), text=_field(m, "목내용"))
            for m in as_list(h.get("목"))
            if isinstance(m, dict)
        ]
        items.append(Item(no=_field(h, "호번호"), text=_field(h, "호내용"), subitems=subitems))
    return Paragraph(no=_field(p, "항번호"), text=_field(p, "항내용"), items=items)


def parse_article(unit: dict[str, Any]) -> Article:
    paragraphs = [_parse_paragraph(p) for p in as_list(unit.get("항")) if isinstance(p, dict)]
    return Article(
        number=_to_int(unit.get("조문번호")),
        branch=_to_int(unit.get("조문가지번호")),
        is_article=_field(unit, "조문여부") != "전문",
        title=_field(unit, "조문제목"),
        text=_field(unit, "조문내용"),
        effective_date=_field(unit, "조문시행일자"),
        paragraphs=paragraphs,
    )


def parse_law_document(data: dict[str, Any]) -> LawDocument:
    """Parse a lawService.do (target=eflaw/law) JSON body."""
    law = data.get("법령")
    if not isinstance(law, dict):
        raise ValueError("응답에 '법령' 항목이 없습니다.")
    basic = law.get("기본정보") or {}
    info = LawInfo(
        law_id=_field(basic, "법령ID"),
        name=_field(basic, "법령명_한글", "법령명한글"),
        abbreviation=_field(basic, "법령명약칭"),
        kind=_field(basic, "법종구분"),
        ministry=_field(basic, "소관부처명", "소관부처"),
        effective_date=_field(basic, "시행일자"),
        promulgation_date=_field(basic, "공포일자"),
        promulgation_no=_field(basic, "공포번호"),
        revision_type=_field(basic, "제개정구분"),
    )
    articles = [parse_article(u) for u in as_list((law.get("조문") or {}).get("조문단위")) if isinstance(u, dict)]
    addenda = [
        Addendum(
            promulgation_date=_field(u, "부칙공포일자"),
            promulgation_no=_field(u, "부칙공포번호"),
            text=_field(u, "부칙내용"),
        )
        for u in as_list((law.get("부칙") or {}).get("부칙단위"))
        if isinstance(u, dict)
    ]
    appendices = [
        Appendix(
            no=_field(u, "별표번호"),
            branch=_field(u, "별표가지번호"),
            kind=_field(u, "별표구분"),
            title=_field(u, "별표제목"),
            file_link=_field(u, "별표서식파일링크"),
            pdf_link=_field(u, "별표서식PDF파일링크"),
        )
        for u in as_list((law.get("별표") or {}).get("별표단위"))
        if isinstance(u, dict)
    ]
    return LawDocument(info=info, articles=articles, addenda=addenda, appendices=appendices)
