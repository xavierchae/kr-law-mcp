"""In-memory stand-in for LawApiClient used by resolver/tool tests.

Name search is modeled pessimistically as a plain, space-sensitive substring
match on 법령명한글 (the real API's matching rules are still to be confirmed).
"""

from kr_law_mcp.models import LawSummary, SearchResult


def law(law_id, name, kind="법률", abbr=""):
    return LawSummary(law_id=law_id, name=name, kind=kind, abbreviation=abbr, ministry="부처")


LAWS = [
    law("001706", "민법"),
    law("001823", "건축법"),
    law("002118", "건축법 시행령", "대통령령"),
    law("001872", "근로기준법"),
    law("003893", "근로기준법 시행령", "대통령령"),
    law("007364", "근로기준법 시행규칙", "부령"),
    law("011357", "개인정보 보호법"),
    law("011468", "개인정보 보호법 시행령", "대통령령"),
    law("009999", "생명윤리 및 안전에 관한 법률"),
    law("010001", "생명윤리 및 안전에 관한 법률 시행령", "대통령령"),
    law("001111", "아동복지법"),
    law("002222", "장애인복지법"),
    law("003333", "청소년 보호법"),
    law("004444", "소비자 보호법 같은 가상의 법률"),
    law("005555", "가정폭력방지 및 피해자보호 등에 관한 법률"),
]

ABBREVIATIONS = [
    law("009999", "생명윤리 및 안전에 관한 법률", abbr="생명윤리법"),
    law("005555", "가정폭력방지 및 피해자보호 등에 관한 법률", abbr="가정폭력방지법"),
]


class FakeClient:
    def __init__(self, laws=None, abbreviations=None):
        self.laws = laws if laws is not None else LAWS
        self.abbreviations = abbreviations if abbreviations is not None else ABBREVIATIONS
        self.queries: list[str] = []
        self.abbr_calls = 0

    async def search_laws(self, query, *, body_search=False, page=1, display=20):
        self.queries.append(query)
        hits = [
            LawSummary(**vars(x)) for x in self.laws if query in x.name
        ]  # copies, so the resolver may annotate them
        for h in hits:
            h.abbreviation = ""  # search rows in tests carry no 약칭
        return SearchResult(total=len(hits), page=page, items=hits[:display])

    async def list_abbreviations(self):
        self.abbr_calls += 1
        return [LawSummary(**vars(x)) for x in self.abbreviations]
