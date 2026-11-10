# Fixtures

- `synthetic_*.json`: hand-written from the field names in the open.law.go.kr
  API guides. They cover shapes the real captures do not (편·장·절 headings,
  가지조문, 부칙, 별표, single-paragraph articles with 호 directly under 항).
- `real_*.json`: captured with `LAW_OC=<key> SAVE_FIXTURES=1 uv run pytest -m live -k capture`.
  The API echoes the caller's OC inside `법령상세링크`; the capture helper
  rewrites it to `OC=test`. Check with `grep -l "$LAW_OC" tests/fixtures/*.json`
  before committing. The abbreviation list is trimmed to a few rows (the full
  list is ~2.7k rows / 2 MB).
