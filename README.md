# kr-law-mcp

국가법령정보센터(법제처) Open API로 대한민국 **현행 법령**(법률·대통령령·총리령·부령)을 검색하고 조문을 조회하는 MCP 서버입니다. 로컬 stdio로 동작합니다.

## 준비

1. https://open.law.go.kr 에서 OPEN API를 신청해 인증값(OC)을 발급받습니다.
2. 같은 사이트에서 **이 서버를 실행할 PC의 IP 주소나 도메인을 등록**합니다. 등록하지 않으면 모든 호출이 "사용자 정보 검증에 실패하였습니다" 오류로 끝납니다.
3. [uv](https://docs.astral.sh/uv/)를 설치합니다.

## Claude Code에 등록

```bash
claude mcp add kr-law -e LAW_OC=<발급받은_OC> -- uv --directory /Users/xavierchae/dev/kr-law-mcp run kr-law-mcp
```

Claude Desktop은 `claude_desktop_config.json`에 다음을 추가합니다.

```json
{
  "mcpServers": {
    "kr-law": {
      "command": "uv",
      "args": ["--directory", "/Users/xavierchae/dev/kr-law-mcp", "run", "kr-law-mcp"],
      "env": { "LAW_OC": "<발급받은_OC>" }
    }
  }
}
```

## 도구

| 도구 | 용도 |
|---|---|
| `search_laws` | 법령명 또는 본문 검색, 법령 종류 필터 |
| `get_law_overview` | 기본정보와 목차(편·장·절, 조 제목) |
| `get_law_articles` | 조문 원문 범위 조회, 부칙·별표 선택 포함 |
| `get_article` | 특정 조·항·호·목 조회 |

모든 도구의 `law` 인자에는 정식 명칭 외에 약칭이나 일부 단어도 쓸 수 있습니다. 예: `생명윤리법`, `근기법 시행령`, `개인정보보호법`, 법령ID `001706`. 입력과 다른 법령으로 해석하면 응답 첫 줄에 해석 결과를 표시하고, 하나로 정하지 못하면 후보 목록을 돌려줍니다.

## 환경변수

| 이름 | 설명 |
|---|---|
| `LAW_OC` | 필수. 발급받은 OC 인증값 |
| `LAW_API_BASE` | 선택. 기본값 `https://www.law.go.kr/DRF` |

## 개발

```bash
uv sync
uv run pytest                      # 단위 테스트 (HTTP 모킹)
LAW_OC=<키> uv run pytest -m live  # 실제 API 호출 테스트
uv run ruff check src tests
LAW_OC=<키> npx @modelcontextprotocol/inspector uv run kr-law-mcp   # MCP Inspector
```

설계는 [docs/PLAN.md](docs/PLAN.md), 진행 기록은 [docs/DEVLOG.md](docs/DEVLOG.md)에 있습니다.
