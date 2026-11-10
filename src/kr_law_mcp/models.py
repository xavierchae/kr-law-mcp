"""Normalized data models for 법제처 Open API responses."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class LawSummary:
    """One row of a 법령 목록 search (lawSearch.do)."""

    law_id: str
    name: str
    abbreviation: str = ""
    kind: str = ""
    ministry: str = ""
    effective_date: str = ""
    promulgation_date: str = ""
    promulgation_no: str = ""
    revision_type: str = ""
    mst: str = ""


@dataclass
class SearchResult:
    total: int
    page: int
    items: list[LawSummary]


@dataclass
class SubItem:
    """목 (가., 나., ...)."""

    no: str
    text: str


@dataclass
class Item:
    """호 (1., 2., 2의2., ...)."""

    no: str
    text: str
    subitems: list[SubItem] = field(default_factory=list)


@dataclass
class Paragraph:
    """항 (①, ②, ...). ``no`` is empty for single-paragraph articles."""

    no: str
    text: str
    items: list[Item] = field(default_factory=list)


@dataclass
class Article:
    """One 조문단위. ``is_article`` is False for 편·장·절 headings (조문여부=전문)."""

    number: int
    branch: int
    is_article: bool
    title: str
    text: str
    effective_date: str = ""
    paragraphs: list[Paragraph] = field(default_factory=list)

    @property
    def label(self) -> str:
        from .parsing import article_label

        return article_label(self.number, self.branch)


@dataclass
class Addendum:
    """부칙단위."""

    promulgation_date: str
    promulgation_no: str
    text: str


@dataclass
class Appendix:
    """별표단위 (metadata only)."""

    no: str
    branch: str
    kind: str
    title: str
    file_link: str = ""
    pdf_link: str = ""


@dataclass
class LawInfo:
    """기본정보."""

    law_id: str
    name: str
    abbreviation: str = ""
    kind: str = ""
    ministry: str = ""
    effective_date: str = ""
    promulgation_date: str = ""
    promulgation_no: str = ""
    revision_type: str = ""


@dataclass
class LawDocument:
    info: LawInfo
    articles: list[Article] = field(default_factory=list)
    addenda: list[Addendum] = field(default_factory=list)
    appendices: list[Appendix] = field(default_factory=list)
