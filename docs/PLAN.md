# kr-law-mcp 개발 계획

> 최초 작성 2026-11-09. 구현 중 바뀐 내용은 본문에 반영하고 이유는 [DEVLOG.md](DEVLOG.md)에 기록한다.

## Context
국가법령정보센터(법제처) Open API로 **현행 법령을 검색하고 본문·조문을 조회**하는 MCP 서버를 새로 만든다. 목적은 Claude 등 LLM이 "민법 제750조", "근로기준법 연차휴가 규정" 같은 질문에 정확한 현행 조문을 근거로 답하게 하는 것이다. 작업 디렉터리 `/Users/xavierchae/dev/kr-law-mcp`는 현재 비어 있으므로 처음부터 만든다.

## 확정된 요구사항
| 항목 | 결정 |
|---|---|
| 언어 | Python 3.12, 공식 `mcp` SDK 2.x의 `MCPServer` (1.x의 FastMCP가 2.x에서 이름 변경) |
| 전송 | 로컬 stdio (Claude Code/Desktop에서 실행) |
| 1차 기능 | 현행법령 검색·본문 조회, 조문 단위(조·항·호·목) 조회 |
| 대상 | 법률·대통령령(시행령)·부령(시행규칙) 등 현행법령 전체, 종류 필터는 옵션 |
| 응답 | 정리된 마크다운 텍스트 |
| 패키징 | uv 로컬 프로젝트, `uv run kr-law-mcp` |
| 캐싱 | 없음 (매번 실시간 호출) |
| 인증 | 발급받은 OC 키를 환경변수 `LAW_OC`로 주입. 호출하는 PC의 IP/도메인을 open.law.go.kr에 등록해야 함 |
| 범위 밖 | 연혁·신구법 비교, 행정규칙·자치법규·판례, HTTP 전송, PyPI 배포 |

## 사용할 법제처 API (시행일 기준 `eflaw`를 기본으로 사용)
"현행"은 오늘 시행 중인 법령이므로 공포일 기준(`law`)이 아니라 시행일 기준(`eflaw`)을 쓴다. 공포 후 시행 전인 개정은 `nw=3`(현행)으로 제외한다.

| 용도 | 요청 |
|---|---|
| 목록 검색 | `GET https://www.law.go.kr/DRF/lawSearch.do?OC=&target=eflaw&type=JSON&query=&search=1\|2&nw=3&knd=&display=&page=` |
| 본문(전체 또는 1개 조) | `GET https://www.law.go.kr/DRF/lawService.do?OC=&target=eflaw&type=JSON&ID=<법령ID>[&JO=6자리]` |
| 조항호목 (대안) | `target=eflawjosub&ID=&JO=&HANG=&HO=&MOK=` |
| 약칭 목록 | `GET .../lawSearch.do?OC=&target=lsAbrv&type=JSON` (검색어 없이 전체 목록, `stdDt`/`endDt`로 등록일 필터만 가능) |

- `JO`, `HANG`, `HO`는 6자리(번호 4자리 + 가지번호 2자리). 예: 제10조의2 → `001002`. `MOK`은 한글 한 글자(가, 나, …).
- `ID`로 조회하면 현행 본문이 반환되고 `efYd`는 무시된다.
- 조문 단위 조회는 **본문 API에 `JO`를 넣어 한 조만 받은 뒤 항·호·목을 로컬에서 잘라내는 방식**을 기본으로 한다. 호출 경로가 하나로 줄고 `eflawjosub`의 `efYd` 필수 여부 같은 불확실성을 피한다. Step 1 스파이크에서 문제가 있으면 `eflawjosub`로 전환한다.

## 법령명 유사 매칭 (`resolver.py`)
정식 명칭이 아니어도 법령을 찾게 한다. 예: "생명윤리법" → 「생명윤리 및 안전에 관한 법률」, "근기법 시행령" → 「근로기준법 시행령」, "개인정보 보호" → 「개인정보 보호법」.

**후보 수집** (캐싱 없음 결정에 따라 요청마다 수행, 최대 3~4회 API 호출)
1. 입력을 그대로 `query`로 검색.
2. 공식 약칭이 아닌 관용 약칭(근기법, 산안법, 중처법 등)은 `aliases.py`의 정적 별칭표로 먼저 정식 명칭으로 바꾼다.
3. 변형 검색으로도 확정되지 않으면 법제처 **법령명 약칭 조회 API**(`lsAbrv`) 전체 목록에서 약칭을 대조하고, 일치한 정식 명칭으로 다시 검색한다. 목록이 크므로 마지막 단계에서만 호출한다.
4. 쿼리 변형 재검색 (실제 순서는 1 → 4 → 3).
   - 공백 제거·삽입 변형 ("개인정보보호법" ↔ "개인정보 보호법").
   - 접미어 분리: "법", "법률", "에 관한 법률", "시행령", "시행규칙". "생명윤리법" → 핵심어 "생명윤리"로 검색.
   - 하위법령 접미어는 따로 보관했다가 후보 필터에 사용 ("근기법 시행령" → 핵심어 "근기법"으로 본법을 찾은 뒤 「근로기준법 시행령」 선택).

**순위 결정** (점수 높은 순)
1. 법령명 또는 약칭 완전 일치 (공백 무시)
2. 입력의 하위법령 접미어와 법령종류가 일치
3. 핵심어가 법령명의 접두어
4. 핵심어 토큰이 법령명에 모두 포함
5. 문자열 유사도 (`rapidfuzz`의 partial/token ratio, 공백 제거 후 비교)
6. 동점이면 법률 > 대통령령 > 부령 순, 그다음 짧은 이름 우선

**결과 처리**
- 1위 점수가 임계값 이상이고 2위와 차이가 충분하면 그 법령을 자동 선택한다. 응답 머리에 "「생명윤리 및 안전에 관한 법률」로 해석함"을 표시해 오매칭을 사용자가 바로 알아챌 수 있게 한다.
- 애매하면 상위 5개 후보(법령명, 약칭, 종류, 법령ID)를 반환하고 `law`에 법령ID나 정확한 이름을 다시 넣으라고 안내한다.
- `search_laws`에도 같은 변형·순위 로직을 적용해, API가 0건을 돌려줘도 변형 쿼리 결과를 보여준다.

Step 1 스파이크에서 다음을 확인한다. 기본 검색 `query`가 약칭에도 걸리는지, 약칭 조회 API의 정확한 target 코드와 파라미터, 부분 일치 동작 방식.

## MCP 도구 설계 (4개)
모든 도구는 `law` 인자로 **법령명·약칭·일부 단어·법령ID 중 무엇이든** 받는다. 숫자면 법령ID로 바로 쓰고, 그 외에는 위 유사 매칭으로 법령을 결정한다.

1. **`search_laws(query, search_in="name"|"body", law_kind=None, page=1, page_size=20)`**
   - 결과: 법령명, 약칭, 법령ID, 법령종류, 소관부처, 시행일자, 공포일자·번호를 마크다운 표로 반환. 총 건수와 페이지 표시.
   - `law_kind`는 응답의 `법령구분명`으로 로컬 필터링한다. `knd` 코드표가 가이드에 공개되어 있지 않기 때문이다.
2. **`get_law_overview(law)`**
   - 기본정보(법령명, ID, 종류, 소관부처, 시행일, 공포일·번호, 제개정구분)와 **목차**(편·장·절 제목 + 조번호·조제목)를 반환.
   - 목차는 `조문여부`가 "전문"인 항목(편장절 제목)과 "조문"인 항목을 구분해 만든다.
   - 큰 법령 전문을 한 번에 넣지 않고 LLM이 필요한 조를 고르게 하는 진입점이다.
3. **`get_law_articles(law, from_article=None, to_article=None, include_addenda=False)`**
   - 지정 범위의 조문 전문을 마크다운으로 반환. 범위 미지정 시 전체.
   - 출력 상한(기본 약 40,000자)을 넘으면 잘라내고 "다음은 `from_article=제N조`로 이어서 조회" 안내를 붙인다.
   - `include_addenda=True`면 부칙 포함. 별표는 제목과 다운로드 링크(`https://www.law.go.kr` + `별표서식파일링크`)만 표시.
4. **`get_article(law, article, paragraph=None, item=None, subitem=None)`**
   - 예: `get_article("건축법", "제3조", paragraph=1, item=2, subitem="다")`.
   - `article`은 "제10조의2", "10조의2", "10의2", "10-2" 모두 허용.
   - 조 제목·시행일자와 함께 지정 단위만 반환하고, 출처 표기(법령명, 시행일, 법령 링크)를 붙인다.

## 프로젝트 구조
```
kr-law-mcp/
├── pyproject.toml          # uv, 의존성: mcp, httpx, rapidfuzz / dev: pytest, pytest-asyncio, respx, ruff
├── README.md               # OC 발급·설정, Claude Code/Desktop 등록 방법
├── CLAUDE.md
├── docs/
│   ├── PLAN.md             # 이 계획서 사본. 설계가 바뀌면 함께 갱신
│   └── DEVLOG.md           # 개발 일지. 날짜별 작업·결정·API 확인 결과·남은 과제
├── src/kr_law_mcp/
│   ├── __init__.py
│   ├── server.py           # FastMCP 인스턴스, 4개 도구 등록, main() 엔트리포인트
│   ├── client.py           # LawApiClient: httpx.AsyncClient, OC 주입, 타임아웃·재시도, 오류 판별
│   ├── models.py           # 응답 정규화 dataclass (LawSummary, LawInfo, Article, Paragraph, Item, SubItem)
│   ├── parsing.py          # 조문번호 파싱/6자리 인코딩, JSON 정규화(단건 dict ↔ list), 법령종류 코드 매핑
│   ├── aliases.py          # 관용 약칭 → 정식 법령명 정적 표
│   ├── resolver.py         # 법령명 유사 매칭 (쿼리 변형, 약칭 조회, 후보 순위)
│   └── formatting.py       # 마크다운 렌더링, 길이 상한 처리
└── tests/
    ├── fixtures/           # 실제 API 응답 JSON 저장본 (민법, 건축법, 근로기준법 등)
    ├── test_parsing.py
    ├── test_resolver.py    # 약칭·일부 단어·하위법령 접미어 매칭 사례
    ├── test_formatting.py
    ├── test_tools.py       # respx로 HTTP 모킹, 도구 단위 테스트
    └── test_live.py        # @pytest.mark.live, LAW_OC 있을 때만 실제 호출
```

## 구현 시 유의점
- **JSON 정규화**: 법제처 JSON은 항목이 하나면 dict, 여러 개면 list로 오는 경우가 많다. `as_list()` 헬퍼로 모든 반복 필드를 통일한다.
- **오류 판별**: 잘못된 OC나 미등록 상태에서는 HTTP 200에 HTML 또는 오류 메시지가 오기도 한다. Content-Type과 본문을 확인해 `LawApiError`로 바꾸고, 도구는 사용자가 이해할 수 있는 한국어 메시지를 반환한다.
- **`LAW_OC` 미설정** 시 서버 시작은 허용하되 도구 호출에서 설정 방법을 안내한다.
- **조문내용 텍스트**에는 "제750조(불법행위의 내용) …"처럼 조 제목이 이미 들어 있는 경우가 있으므로 중복 출력하지 않는다. 항 번호는 ①②처럼 원문 기호를 유지한다.
- stdio 서버이므로 로그는 반드시 stderr로만 출력한다.
- 기본 URL은 `https://www.law.go.kr/DRF`로 두고 환경변수 `LAW_API_BASE`로 바꿀 수 있게 한다.

## 계획서·개발 일지 관리
- 구현 첫 단계에서 이 계획서를 `docs/PLAN.md`로 복사하고, 빈 `docs/DEVLOG.md`를 만든다.
- 각 단계를 마칠 때마다 `docs/DEVLOG.md`에 날짜별 항목을 추가한다. 항목은 "한 일", "결정·변경 사항과 이유", "API 확인 결과", "남은 과제"로 나눈다.
- 설계가 바뀌면 `docs/PLAN.md`도 수정하고, 일지에 무엇을 왜 바꿨는지 남긴다.
- CLAUDE.md에 "작업 후 DEVLOG 갱신" 규칙을 적어 이후 세션에서도 유지되게 한다.

## 진행 순서
1. **문서 준비**: `docs/PLAN.md` 복사, `docs/DEVLOG.md` 첫 항목 작성.
2. **API 스파이크**: 실제 OC로 민법·건축법·근로기준법·근로기준법 시행령·생명윤리법을 호출해 JSON 구조를 확인하고 `tests/fixtures/`에 저장. 확인 항목은 dict/list 혼재, `조문여부` 값, 가지조문 표현, 항·호·목 중첩 형태, 오류 응답 형태, `JO` 지정 시 응답 구조, 약칭 검색 동작. 결과는 DEVLOG에 기록.
3. uv 프로젝트 생성, `pyproject.toml`과 엔트리포인트(`kr-law-mcp = "kr_law_mcp.server:main"`) 설정.
4. `parsing.py`와 테스트 (조문번호 파서, 정규화).
5. `client.py` (검색·본문·약칭 조회 메서드, 오류 처리).
6. `resolver.py`와 테스트 (유사 매칭).
7. `formatting.py`와 픽스처 기반 테스트.
8. `server.py`에 4개 도구 구현.
9. README와 CLAUDE.md 작성.

단계마다 DEVLOG를 갱신한다.

## 검증
- 단위 테스트: `uv run pytest` (live 제외), 린트: `uv run ruff check`.
- 실제 호출: `LAW_OC=<키> uv run pytest -m live`.
- MCP Inspector: `LAW_OC=<키> npx @modelcontextprotocol/inspector uv run kr-law-mcp`로 4개 도구를 직접 호출.
- Claude Code 연동:
  ```
  claude mcp add kr-law -e LAW_OC=<키> -- uv --directory /Users/xavierchae/dev/kr-law-mcp run kr-law-mcp
  ```
  이후 다음 질문으로 끝까지 확인한다.
  - "민법 제750조 보여줘" → `get_article`이 정확한 조문 반환
  - "건축법 제3조제1항제2호다목" → 목 단위까지 반환
  - "근로기준법 시행령에서 연차 관련 조문 찾아줘" → `search_laws`(본문검색) 후 `get_law_overview`, `get_article` 연쇄
  - "생명윤리법 제2조" → 「생명윤리 및 안전에 관한 법률」로 해석했다는 표시와 함께 조문 반환
  - "개인정보보호법", "근기법 시행령"처럼 공백·약칭이 섞인 입력 → 올바른 법령으로 해석
  - "보호법"처럼 애매한 입력 → 후보 목록 반환
  - 존재하지 않는 법령명, 잘못된 조번호 → 친절한 오류 메시지
- 작업이 끝나면 `docs/DEVLOG.md`에 모든 단계 기록이 있는지 확인한다.
