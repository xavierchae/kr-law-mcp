"""Resolve loose law names ("생명윤리법", "근기법 시행령", "개인정보보호법") to a law.

Strategy (no caching, a handful of API calls per resolution):
1. Expand the input: known alias -> full name, split off a 시행령/시행규칙
   suffix, strip a trailing "법"/"법률"/"에 관한 법률" to get a core keyword.
2. Search the API with the full input, then with progressively looser variants,
   stopping as soon as a confident match appears.
3. If still unresolved, fetch the official abbreviation list and retry with
   the full names whose 약칭 matches.
4. Score every candidate and either pick a clear winner or return candidates.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from rapidfuzz import fuzz

from .aliases import ALIASES
from .client import LawApiClient
from .models import LawSummary

_LAW_SUFFIXES = ("에관한특별법", "에관한특례법", "에관한법률", "특별법", "특례법", "법률", "법")

CONFIDENT = 80.0
MIN_GAP = 10.0
MIN_CANDIDATE = 40.0
MAX_SEARCH_CALLS = 4


def normalize(text: str) -> str:
    """Remove whitespace, brackets and middle dots for comparison."""
    return re.sub(r"[\s「」『』\"'·ㆍ・]", "", text).lower()


@dataclass
class ParsedQuery:
    raw: str
    base: str  # input without 시행령/시행규칙 suffix, alias-expanded
    sub: str  # "시행령", "시행규칙" or ""
    core: str  # base without trailing 법/법률, whitespace-free
    tokens: list[str]
    alias_target: str = ""

    @property
    def full(self) -> str:
        return f"{self.base} {self.sub}".strip()


_SUB_RE = re.compile(r"^(.*?)\s*(시행령|시행규칙)$")


def parse_query(raw: str) -> ParsedQuery:
    text = re.sub(r"[「」『』]", "", raw).strip()
    sub = ""
    m = _SUB_RE.match(text)
    if m and m.group(1).strip():
        text, sub = m.group(1).strip(), m.group(2)
    alias_target = ALIASES.get(normalize(text), "")
    base = alias_target or text
    core = normalize(base)
    for suffix in _LAW_SUFFIXES:
        if core.endswith(suffix) and len(core) > len(suffix) + 1:
            core = core[: -len(suffix)]
            break
    tokens = [t for t in re.split(r"\s+", base) if t]
    return ParsedQuery(raw=raw, base=base, sub=sub, core=core, tokens=tokens, alias_target=alias_target)


def _split_name(name: str) -> tuple[str, str]:
    """ "근로기준법 시행령" -> ("근로기준법", "시행령")."""
    m = _SUB_RE.match(name.strip())
    if m and m.group(1).strip():
        return m.group(1).strip(), m.group(2)
    return name, ""


def score(candidate: LawSummary, q: ParsedQuery) -> float:
    """Heuristic 0-100 relevance of ``candidate`` for query ``q``."""
    name_n = normalize(candidate.name)
    abbr_n = normalize(candidate.abbreviation)
    raw_n = normalize(q.raw)
    full_n = normalize(q.full)
    base_n = normalize(q.base)
    cand_base, cand_sub = _split_name(candidate.name)
    cand_base_n = normalize(cand_base)

    if raw_n in (name_n, abbr_n) or full_n == name_n:
        return 100.0

    if base_n == cand_base_n or (abbr_n and base_n == abbr_n):
        s = 95.0
    elif q.core and cand_base_n.startswith(q.core):
        s = 85.0
    elif q.tokens and all(normalize(t) in name_n for t in q.tokens):
        s = 75.0
    elif q.core and q.core in name_n:
        s = 70.0
    else:
        s = 0.7 * max(
            fuzz.partial_ratio(q.core or base_n, cand_base_n),
            fuzz.token_set_ratio(q.base, cand_base),
            fuzz.ratio(base_n, abbr_n) if abbr_n else 0,
        )

    if q.sub:
        s += 0.0 if cand_sub == q.sub else -40.0
    elif cand_sub:
        s -= 15.0
    return max(0.0, min(s, 99.0))


@dataclass
class Resolution:
    law: LawSummary | None
    candidates: list[tuple[LawSummary, float]] = field(default_factory=list)
    query: ParsedQuery | None = None

    @property
    def interpreted(self) -> bool:
        """True when the picked law's name differs from what the user typed."""
        if not self.law or not self.query:
            return False
        return normalize(self.law.name) != normalize(self.query.raw)


def kind_rank(kind: str) -> int:
    """Prefer 헌법 > 법률 > 대통령령 > 총리령 > ○○부령 > others (e.g. 대법원규칙)."""
    for rank_, name in enumerate(("헌법", "법률", "대통령령", "총리령")):
        if kind == name:
            return rank_
    return 4 if kind.endswith("부령") else 9


def _sort_key(item: tuple[LawSummary, float]) -> tuple[float, int, int]:
    law, s = item
    return (-s, kind_rank(law.kind), len(law.name))


def rank(candidates: dict[str, LawSummary], q: ParsedQuery) -> list[tuple[LawSummary, float]]:
    scored = [(c, score(c, q)) for c in candidates.values()]
    return sorted(scored, key=_sort_key)


def _is_confident(ranked: list[tuple[LawSummary, float]]) -> bool:
    if not ranked or ranked[0][1] < CONFIDENT:
        return False
    return len(ranked) == 1 or ranked[0][1] - ranked[1][1] >= MIN_GAP


def search_variants(q: ParsedQuery) -> list[str]:
    """Search strings to try, most specific first, de-duplicated."""
    variants = [q.raw.strip(), q.full, q.base]
    if q.core:
        variants.append(q.core)
        if len(q.core) > 4:
            variants.append(q.core[:4])
    if len(q.tokens) > 1:
        variants.append(max(q.tokens, key=len))
    seen: set[str] = set()
    out: list[str] = []
    for v in variants:
        v = v.strip()
        if len(v) >= 2 and v not in seen:
            seen.add(v)
            out.append(v)
    return out


async def resolve_law(client: LawApiClient, raw: str) -> Resolution:
    """Resolve ``raw`` (name, abbreviation, partial words) to a current law."""
    q = parse_query(raw)
    candidates: dict[str, LawSummary] = {}

    def add(items: list[LawSummary]) -> None:
        for item in items:
            known = candidates.get(item.law_id)
            if known is None:
                candidates[item.law_id] = item
            elif item.abbreviation and not known.abbreviation:
                known.abbreviation = item.abbreviation

    ranked: list[tuple[LawSummary, float]] = []
    for variant in search_variants(q)[:MAX_SEARCH_CALLS]:
        add((await client.search_laws(variant, display=100)).items)
        ranked = rank(candidates, q)
        if _is_confident(ranked):
            return Resolution(law=ranked[0][0], candidates=ranked[:5], query=q)

    # Official 약칭 list: map abbreviation -> full name, then search full names.
    base_n = normalize(q.base)
    abbreviations = await client.list_abbreviations()
    hits = [
        a
        for a in abbreviations
        if a.abbreviation
        and (normalize(a.abbreviation) == base_n or fuzz.ratio(normalize(a.abbreviation), base_n) >= 90)
    ]
    for hit in hits[:2]:
        target = f"{hit.name} {q.sub}".strip()
        found = (await client.search_laws(target, display=100)).items
        for item in found:
            if normalize(_split_name(item.name)[0]) == normalize(hit.name):
                item.abbreviation = item.abbreviation or hit.abbreviation
        add(found)
    if hits:
        # Score as if the user had typed the official full name.
        q_full = parse_query(f"{hits[0].name} {q.sub}".strip())
        q_full.raw = raw
        ranked = rank(candidates, q_full)
        q = q_full
    else:
        ranked = rank(candidates, q)

    if _is_confident(ranked):
        return Resolution(law=ranked[0][0], candidates=ranked[:5], query=q)
    return Resolution(
        law=None,
        candidates=[(c, s) for c, s in ranked if s >= MIN_CANDIDATE][:5],
        query=q,
    )
