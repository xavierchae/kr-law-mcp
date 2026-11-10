"""Render parsed law data as Markdown for LLM consumption."""

from __future__ import annotations

from urllib.parse import quote

from .models import Article, LawDocument, LawInfo, LawSummary, SearchResult
from .parsing import article_label

DEFAULT_MAX_CHARS = 40_000
LAW_WEB_BASE = "https://www.law.go.kr"


def fmt_date(value: str) -> str:
    """'20240917' -> '2024. 9. 17.'; anything else is returned unchanged."""
    v = value.strip()
    if len(v) == 8 and v.isdigit():
        return f"{int(v[:4])}. {int(v[4:6])}. {int(v[6:])}."
    return v


def law_url(name: str, article: str | None = None) -> str:
    path = f"/법령/{name}" + (f"/{article}" if article else "")
    return LAW_WEB_BASE + quote(path)


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ") or "-"


def _one_line(text: str) -> str:
    return " ".join(text.split())


def _indent(text: str, prefix: str) -> str:
    return "\n".join(prefix + line.strip() for line in text.splitlines() if line.strip())


def interpretation_note(raw: str, law_name: str) -> str:
    return f"> 법령명 해석: '{raw}' → 「{law_name}」\n\n"


def source_line(info: LawInfo, article: str | None = None) -> str:
    when = f"시행 {fmt_date(info.effective_date)}" if info.effective_date else "현행"
    return f"출처: 국가법령정보센터 「{info.name}」({when}) {law_url(info.name, article)}"


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------


def format_search(result: SearchResult, query: str, page_size: int, note: str = "") -> str:
    if not result.items:
        return (
            f"'{query}'에 해당하는 현행법령을 찾지 못했습니다. "
            "다른 검색어나 본문검색(search_in='body')을 시도해 보세요."
        )
    lines = [note] if note else []
    pages = max(1, -(-result.total // page_size))
    lines.append(f"**'{query}' 검색 결과**: 총 {result.total}건 (페이지 {result.page}/{pages})\n")
    lines.append("| 법령명 | 약칭 | 종류 | 법령ID | 소관부처 | 시행일 | 공포일(번호) |")
    lines.append("|---|---|---|---|---|---|---|")
    for law in result.items:
        lines.append(
            f"| {_cell(law.name)} | {_cell(law.abbreviation)} | {_cell(law.kind)} | {law.law_id} "
            f"| {_cell(law.ministry)} | {fmt_date(law.effective_date)} "
            f"| {fmt_date(law.promulgation_date)} ({law.promulgation_no or '-'}) |"
        )
    lines.append("\n법령ID나 법령명을 get_law_overview / get_article의 law 인자로 사용하세요.")
    return "\n".join(lines)


def format_candidates(raw: str, candidates: list[tuple[LawSummary, float]]) -> str:
    if not candidates:
        return (
            f"'{raw}'에 해당하는 현행법령을 찾지 못했습니다. "
            "search_laws로 검색해 정확한 법령명이나 법령ID를 확인하세요."
        )
    lines = [
        f"'{raw}'에 해당하는 법령이 하나로 특정되지 않았습니다. "
        "아래 후보 중 하나의 법령ID 또는 정확한 법령명을 law 인자로 다시 지정하세요.\n",
        "| 법령명 | 약칭 | 종류 | 법령ID |",
        "|---|---|---|---|",
    ]
    for law, _ in candidates:
        lines.append(f"| {_cell(law.name)} | {_cell(law.abbreviation)} | {_cell(law.kind)} | {law.law_id} |")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# law body
# ---------------------------------------------------------------------------


def format_info(info: LawInfo) -> str:
    rows = [
        ("법령명", info.name),
        ("약칭", info.abbreviation),
        ("법령ID", info.law_id),
        ("종류", info.kind),
        ("소관부처", info.ministry),
        ("시행일", fmt_date(info.effective_date)),
        (
            "공포일(번호)",
            f"{fmt_date(info.promulgation_date)} (제{info.promulgation_no}호)"
            if info.promulgation_no
            else fmt_date(info.promulgation_date),
        ),
        ("제개정구분", info.revision_type),
    ]
    return "\n".join(f"- **{k}**: {v}" for k, v in rows if v)


def render_article(article: Article) -> str:
    """Full text of one 조 (or a 편·장·절 heading)."""
    if not article.is_article:
        return f"#### {_one_line(article.text or article.title)}"
    parts: list[str] = []
    if article.text:
        parts.append(_indent(article.text, ""))
    for p in article.paragraphs:
        if p.text:
            parts.append(_indent(p.text, ""))
        for item in p.items:
            if item.text:
                parts.append(_indent(item.text, "  "))
            for sub in item.subitems:
                if sub.text:
                    parts.append(_indent(sub.text, "    "))
    if not parts:
        parts.append(f"{article.label}({article.title})" if article.title else article.label)
    return "\n".join(parts)


def format_overview(doc: LawDocument, max_chars: int = DEFAULT_MAX_CHARS, note: str = "") -> str:
    lines = [note + f"## {doc.info.name}", format_info(doc.info), "", "### 목차"]
    count = sum(1 for a in doc.articles if a.is_article)
    toc: list[str] = []
    for a in doc.articles:
        if a.is_article:
            toc.append(f"- {a.label}" + (f"({a.title})" if a.title else ""))
        else:
            toc.append(f"\n**{_one_line(a.text or a.title)}**")
    body = "\n".join(toc).strip() or "(조문 목록 없음)"
    if len(body) > max_chars:
        body = body[:max_chars].rsplit("\n", 1)[0] + "\n… (목차가 길어 일부 생략)"
    lines.append(body)
    extras = [f"조문 {count}개"]
    if doc.addenda:
        extras.append(f"부칙 {len(doc.addenda)}개")
    if doc.appendices:
        extras.append(f"별표·서식 {len(doc.appendices)}개")
    lines += [
        "",
        f"({', '.join(extras)}. 조문 본문은 get_article 또는 get_law_articles로 조회)",
        "",
        source_line(doc.info),
    ]
    return "\n".join(lines)


def format_articles(
    doc: LawDocument,
    start: tuple[int, int] | None,
    end: tuple[int, int] | None,
    include_addenda: bool,
    max_chars: int = DEFAULT_MAX_CHARS,
    note: str = "",
) -> str:
    header = note + f"## {doc.info.name}\n"
    chunks: list[str] = []
    size = len(header)
    pending_headings: list[str] = []
    truncated_at: str | None = None
    shown = 0

    for a in doc.articles:
        if not a.is_article:
            pending_headings.append(render_article(a))
            continue
        key = (a.number, a.branch)
        if start and key < start:
            pending_headings.clear()
            continue
        if end and key > end:
            break
        block = "\n\n".join(pending_headings + [render_article(a)])
        if shown and size + len(block) > max_chars:
            truncated_at = a.label
            break
        pending_headings.clear()
        chunks.append(block)
        size += len(block) + 2
        shown += 1

    if not chunks:
        rng = f"{article_label(*start) if start else '처음'} ~ {article_label(*end) if end else '끝'}"
        return f"「{doc.info.name}」에서 {rng} 범위의 조문을 찾지 못했습니다. get_law_overview로 목차를 확인하세요."

    out = header + "\n\n".join(chunks)
    if truncated_at:
        out += (
            f"\n\n… 출력 길이 제한으로 여기서 끊었습니다. "
            f"이어서 보려면 from_article='{truncated_at}'로 다시 조회하세요."
        )
    elif include_addenda and doc.addenda:
        add_parts = []
        for ad in doc.addenda:
            head = f"#### 부칙 <{fmt_date(ad.promulgation_date)} 제{ad.promulgation_no}호>"
            add_parts.append(f"{head}\n{ad.text}")
        addenda_text = "\n\n### 부칙\n\n" + "\n\n".join(add_parts)
        if size + len(addenda_text) > max_chars:
            addenda_text = addenda_text[: max(0, max_chars - size)] + "\n… (부칙이 길어 일부 생략)"
        out += addenda_text
    if include_addenda and doc.appendices and not truncated_at:
        out += "\n\n### 별표·서식\n" + "\n".join(
            f"- {ap.title or ap.kind}" + (f" ({LAW_WEB_BASE}{ap.file_link})" if ap.file_link else "")
            for ap in doc.appendices
        )
    return out + "\n\n" + source_line(doc.info)


def format_single_article(doc: LawDocument, article: Article, selection: str, body: str, note: str = "") -> str:
    title = f"{article.label}" + (f"({article.title})" if article.title else "")
    head = f"{note}## 「{doc.info.name}」 {title}"
    if selection:
        head += f" {selection}"
    meta = []
    if article.effective_date:
        meta.append(f"조문 시행일 {fmt_date(article.effective_date)}")
    lines = [head]
    if meta:
        lines.append(f"({', '.join(meta)})")
    lines += ["", body, "", source_line(doc.info, article.label)]
    return "\n".join(lines)
