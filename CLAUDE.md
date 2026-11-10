# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A local stdio MCP server (Python 3.12, `mcp` SDK 2.x) that looks up Korean statutes currently in force through the 국가법령정보센터 Open API (open.law.go.kr). It exposes four read-only tools: `search_laws`, `get_law_overview`, `get_law_articles`, and `get_article`. All tools return Markdown text, not structured output.

## Commands

```bash
uv sync                                    # install deps
uv run pytest                              # unit tests (HTTP mocked; live tests excluded by default)
uv run pytest tests/test_resolver.py::test_interpreted_flag   # single test (-k on Korean param ids does not match; use function names)
LAW_OC=<key> uv run pytest -m live         # real API calls
LAW_OC=<key> SAVE_FIXTURES=1 uv run pytest -m live -k capture   # save real responses to tests/fixtures/real_*.json
uv run ruff check src tests && uv run ruff format src tests
uv run kr-law-mcp                          # run the server on stdio
```

Real API calls need both an OC key in `LAW_OC` and the caller's IP/domain registered on open.law.go.kr. On this machine `LAW_OC` is exported from `~/.zshrc`, which the Claude Code Bash tool does not source, so wrap live runs as `zsh -ic 'uv run pytest -m live'`. Never print the key; the API also echoes it inside `법령상세링크` in search results. Without the registration, every call returns HTTP 200 with `{"result": "사용자 정보 검증에 실패하였습니다.", "msg": ...}`.

## Architecture

The request flow is `server.py` tool → `resolver.py` (law name → 법령ID) → `client.py` (HTTP) → `parsing.py` (JSON → `models.py` dataclasses) → `formatting.py` (Markdown).

- **API targets.** Everything uses the 시행일 기준 `target=eflaw`. Search adds `nw=3` (현행 only). Body lookups use `lawService.do` with `ID`, and a single 조 is fetched with `JO` as a 6-digit code (`encode_unit`: 제10조의2 → `001002`). 항·호·목 are selected locally in `server._select` rather than via `eflawjosub`.
- **Loose JSON.** The API returns a dict for one element and a list for many, and text fields may be strings, nested lists, or `{"content": ...}` dicts. Always go through `parsing.as_list` and `parsing.text_of` instead of indexing raw responses.
- **Name resolution** (`resolver.resolve_law`) tries, in order: the input as typed, the static alias table in `aliases.py` (informal shorthand like 근기법), whitespace/suffix variants of the query, and finally the full official abbreviation list (`target=lsAbrv`, which has no query parameter, so it is called last). Candidates are scored by `resolver.score` and auto-picked only when confident and clearly ahead of the runner-up; otherwise the tool returns a candidate table. A trailing 시행령/시행규칙 in the input is split off and used to prefer the matching subordinate law.
- **Errors.** `LawApiError` (client) and `ToolFailure` (server) carry user-facing Korean messages. Tools catch them and return the message as text instead of raising.
- **No caching** is a deliberate product decision. Each tool call makes fresh requests.
- **Logging** must go to stderr only (stdio transport). The httpx logger is held at WARNING because its INFO lines include the OC key in the URL.

## Tests

`tests/fakes.py` holds an in-memory law table. `FakeClient` serves the resolver tests and the respx side effects in `test_tools.py` from it. Its name search is a space-sensitive substring match, a pessimistic guess at the real API. Fixtures named `synthetic_*.json` were written by hand from the API guide's field names and are not real captures. See `tests/fixtures/README.md`.

## Project docs: keep them updated

- `docs/PLAN.md` is the agreed design. When the design changes, edit it.
- `docs/DEVLOG.md` is the development journal. After each work session, append a dated entry with 한 일, 결정·변경과 이유, API 확인 결과, and 남은 과제. The open items about unverified API behavior are tracked there.
