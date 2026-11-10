"""kr-law-mcp: MCP server for 현행법령 lookup via the 국가법령정보센터 Open API."""

from __future__ import annotations

import logging
import sys

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from .client import LawApiClient, LawApiError
from .formatting import (
    DEFAULT_MAX_CHARS,
    format_articles,
    format_candidates,
    format_overview,
    format_search,
    format_single_article,
    interpretation_note,
    render_article,
)
from .models import Article, Item, LawSummary, Paragraph, SearchResult
from .parsing import (
    article_label,
    encode_unit,
    item_number,
    paragraph_number,
    parse_article_no,
    subitem_key,
)
from .resolver import parse_query, rank, resolve_law, search_variants

logger = logging.getLogger("kr_law_mcp")

INSTRUCTIONS = """\
대한민국 현행 법령(법률·대통령령·총리령·부령 등)을 국가법령정보센터 Open API로 조회합니다.
- law 인자에는 정식 법령명, 약칭(예: 생명윤리법, 근기법 시행령), 일부 단어, 법령ID 모두 쓸 수 있습니다.
- 특정 조문은 get_article, 법령 구조 파악은 get_law_overview, 여러 조문 원문은 get_law_articles를 쓰세요.
- 답변에 법령을 인용할 때는 도구 응답의 출처 줄(법령명, 시행일)을 함께 밝히세요.
"""

READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=True, idempotent_hint=True)

mcp = MCPServer("kr-law", instructions=INSTRUCTIONS)


class ToolFailure(Exception):
    """Carries a user-facing message back to the tool caller."""


def _client() -> LawApiClient:
    return LawApiClient()


async def _resolve(client: LawApiClient, law: str) -> tuple[str, str]:
    """Return (법령ID, interpretation note) for a loose ``law`` reference."""
    ref = law.strip()
    if not ref:
        raise ToolFailure("law 인자가 비어 있습니다. 법령명이나 법령ID를 입력하세요.")
    if ref.isdigit():
        return ref.zfill(6), ""
    res = await resolve_law(client, ref)
    if res.law is None:
        raise ToolFailure(format_candidates(ref, res.candidates))
    note = interpretation_note(ref, res.law.name) if res.interpreted else ""
    return res.law.law_id, note


def _find_paragraph(article: Article, paragraph: int) -> Paragraph:
    for p in article.paragraphs:
        if paragraph_number(p.no) == paragraph:
            return p
    numbered = [p for p in article.paragraphs if paragraph_number(p.no)]
    if paragraph == 1 and not numbered and article.paragraphs:
        return article.paragraphs[0]
    available = ", ".join(f"제{paragraph_number(p.no)}항" for p in numbered) or "없음(단일 항)"
    raise ToolFailure(f"{article.label}에 제{paragraph}항이 없습니다. (있는 항: {available})")


def _find_item(article: Article, paragraphs: list[Paragraph], item: str) -> tuple[Paragraph, Item]:
    wanted = item_number(item)
    if wanted is None:
        raise ToolFailure(f"호 번호를 해석할 수 없습니다: {item!r} (예: 2, '2의2')")
    matches = [(p, i) for p in paragraphs for i in p.items if item_number(i.no) == wanted]
    if not matches:
        raise ToolFailure(f"{article.label}에서 해당 호({item})를 찾지 못했습니다.")
    if len(matches) > 1:
        raise ToolFailure(f"{article.label}의 여러 항에 같은 호 번호가 있습니다. paragraph 인자로 항을 지정하세요.")
    return matches[0]


def _select(article: Article, paragraph: int | None, item: str | None, subitem: str | None) -> tuple[str, str]:
    """Return (selection label, rendered body) for the requested 항·호·목."""
    if paragraph is None and item is None and subitem is None:
        return "", render_article(article)
    if subitem is not None and item is None:
        raise ToolFailure("목(subitem)을 지정하려면 호(item)도 함께 지정해야 합니다.")

    label = ""
    paragraphs = article.paragraphs
    if paragraph is not None:
        para = _find_paragraph(article, paragraph)
        paragraphs = [para]
        label += f"제{paragraph}항"
        if item is None:
            lines = [para.text] if para.text else []
            for i in para.items:
                lines.append("  " + i.text)
                lines += ["    " + s.text for s in i.subitems]
            return label, "\n".join(lines)

    assert item is not None
    _, it = _find_item(article, paragraphs, item)
    num, branch = item_number(item) or (0, 0)
    label += f"제{num}호" + (f"의{branch}" if branch else "")
    if subitem is None:
        return label, "\n".join([it.text] + ["  " + s.text for s in it.subitems])

    key = subitem_key(subitem)
    for s in it.subitems:
        if subitem_key(s.no) == key:
            return label + f"{key}목", s.text
    available = ", ".join(subitem_key(s.no) for s in it.subitems) or "없음"
    raise ToolFailure(f"{article.label} {label}에 {key}목이 없습니다. (있는 목: {available})")


def _filter_kind(result: SearchResult, law_kind: str | None) -> SearchResult:
    if not law_kind:
        return result
    items = [i for i in result.items if law_kind.strip() in i.kind or law_kind.strip() in i.name]
    return SearchResult(total=len(items), page=result.page, items=items)


@mcp.tool(annotations=READ_ONLY, structured_output=False)
async def search_laws(
    query: str,
    search_in: str = "name",
    law_kind: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> str:
    """현행법령을 검색합니다.

    Args:
        query: 검색어. 법령명 일부나 약칭도 됩니다 (예: "생명윤리법", "개인정보 보호").
        search_in: "name"이면 법령명 검색, "body"면 조문 본문 검색.
        law_kind: 결과를 법령 종류로 거름 (예: "법률", "대통령령", "총리령", "부령").
        page: 페이지 번호 (1부터).
        page_size: 페이지당 건수 (최대 100).
    """
    page_size = max(1, min(page_size, 100))
    body = search_in.strip().lower() == "body"
    try:
        async with _client() as client:
            result = await client.search_laws(query, body_search=body, page=page, display=page_size)
            note = ""
            if not body and page == 1 and not result.items:
                # Loose name: fall back to the resolver's query variants.
                q = parse_query(query)
                merged: dict[str, LawSummary] = {}
                for variant in search_variants(q)[1:4]:
                    for law in (await client.search_laws(variant, display=page_size)).items:
                        merged.setdefault(law.law_id, law)
                    if merged:
                        note = f"> '{query}' 그대로는 결과가 없어 '{variant}'(으)로 검색했습니다.\n"
                        break
                ranked = [law for law, _ in rank(merged, q)]
                result = SearchResult(total=len(ranked), page=1, items=ranked[:page_size])
            result = _filter_kind(result, law_kind)
            return format_search(result, query, page_size, note)
    except LawApiError as exc:
        return str(exc)


@mcp.tool(annotations=READ_ONLY, structured_output=False)
async def get_law_overview(law: str) -> str:
    """법령의 기본정보(시행일, 소관부처 등)와 목차(편·장·절, 조 제목)를 조회합니다.

    큰 법령은 전문 대신 이 도구로 구조를 먼저 보고 필요한 조문만 get_article로 조회하세요.

    Args:
        law: 법령명, 약칭, 일부 단어 또는 법령ID (예: "민법", "생명윤리법", "근기법 시행령", "001706").
    """
    try:
        async with _client() as client:
            law_id, note = await _resolve(client, law)
            doc = await client.get_law(law_id)
            return format_overview(doc, note=note)
    except (LawApiError, ToolFailure) as exc:
        return str(exc)


@mcp.tool(annotations=READ_ONLY, structured_output=False)
async def get_law_articles(
    law: str,
    from_article: str | None = None,
    to_article: str | None = None,
    include_addenda: bool = False,
) -> str:
    """법령의 조문 원문을 범위로 조회합니다. 범위를 생략하면 처음부터 끝까지 (길면 잘림).

    Args:
        law: 법령명, 약칭, 일부 단어 또는 법령ID.
        from_article: 시작 조 (예: "제1조", "10의2"). 생략 시 처음부터.
        to_article: 끝 조 (포함). 생략 시 끝까지.
        include_addenda: True면 부칙과 별표·서식 목록도 포함.
    """
    try:
        start = parse_article_no(from_article) if from_article else None
        end = parse_article_no(to_article) if to_article else None
    except ValueError as exc:
        return str(exc)
    if start and end and start > end:
        return "from_article이 to_article보다 뒤에 있습니다."
    try:
        async with _client() as client:
            law_id, note = await _resolve(client, law)
            doc = await client.get_law(law_id)
            return format_articles(doc, start, end, include_addenda, DEFAULT_MAX_CHARS, note)
    except (LawApiError, ToolFailure) as exc:
        return str(exc)


@mcp.tool(annotations=READ_ONLY, structured_output=False)
async def get_article(
    law: str,
    article: str,
    paragraph: int | None = None,
    item: str | None = None,
    subitem: str | None = None,
) -> str:
    """특정 조문(조·항·호·목)의 현행 원문을 조회합니다.

    예: 건축법 제3조제1항제2호다목 → law="건축법", article="제3조", paragraph=1, item="2", subitem="다".

    Args:
        law: 법령명, 약칭, 일부 단어 또는 법령ID (예: "민법", "생명윤리법").
        article: 조 번호 (예: "제750조", "750", "제10조의2", "10의2").
        paragraph: 항 번호 (예: 1).
        item: 호 번호 (예: "2", "2의2").
        subitem: 목 (예: "가", "다").
    """
    try:
        number, branch = parse_article_no(article)
    except ValueError as exc:
        return str(exc)
    try:
        async with _client() as client:
            law_id, note = await _resolve(client, law)
            doc = await client.get_law(law_id, article=encode_unit(number, branch))
            match = next(
                (a for a in doc.articles if a.is_article and (a.number, a.branch) == (number, branch)),
                None,
            )
            if match is None:
                label = article_label(number, branch)
                return f"「{doc.info.name}」에 {label}가 없습니다. get_law_overview로 목차를 확인하세요."
            selection, body = _select(match, paragraph, item and str(item), subitem)
            return format_single_article(doc, match, selection, body, note)
    except (LawApiError, ToolFailure) as exc:
        return str(exc)


def main() -> None:
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    mcp.run("stdio")


if __name__ == "__main__":
    main()
