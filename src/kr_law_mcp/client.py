"""Async client for the 국가법령정보센터 Open API (https://open.law.go.kr)."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx

from .models import LawDocument, LawSummary, SearchResult
from .parsing import parse_law_document, parse_search

logger = logging.getLogger(__name__)
# httpx logs full request URLs (including the OC key) at INFO; keep it quiet
# no matter who configures logging.
logging.getLogger("httpx").setLevel(logging.WARNING)

DEFAULT_BASE_URL = "https://www.law.go.kr/DRF"
DEFAULT_TIMEOUT = 20.0

OC_MISSING_MESSAGE = (
    "법제처 Open API 인증값(OC)이 설정되지 않았습니다. "
    "MCP 서버 실행 환경에 LAW_OC 환경변수를 설정하세요. "
    "(발급: https://open.law.go.kr → OPEN API 신청)"
)


class LawApiError(Exception):
    """Raised for any failure talking to, or understanding, the API."""


class LawApiClient:
    """Thin wrapper over lawSearch.do / lawService.do returning parsed models.

    Use as an async context manager, or call :meth:`aclose` when done.
    """

    def __init__(
        self,
        oc: str | None = None,
        base_url: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.oc = oc if oc is not None else os.environ.get("LAW_OC", "")
        self.base_url = (base_url or os.environ.get("LAW_API_BASE") or DEFAULT_BASE_URL).rstrip("/")
        self._http = http_client or httpx.AsyncClient(
            timeout=timeout,
            headers={"User-Agent": "kr-law-mcp/0.1"},
            follow_redirects=True,
        )

    async def __aenter__(self) -> LawApiClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    # -- low level ---------------------------------------------------------

    async def _get(self, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self.oc:
            raise LawApiError(OC_MISSING_MESSAGE)
        query = {"OC": self.oc, "type": "JSON", **{k: v for k, v in params.items() if v not in (None, "")}}
        url = f"{self.base_url}/{endpoint}"
        last_exc: Exception | None = None
        for attempt in range(2):
            try:
                resp = await self._http.get(url, params=query)
            except httpx.TransportError as exc:
                last_exc = exc
                logger.warning("law.go.kr request failed (attempt %d): %s", attempt + 1, exc)
                continue
            if resp.status_code >= 500 and attempt == 0:
                logger.warning("law.go.kr returned %d, retrying", resp.status_code)
                continue
            return self._decode(resp)
        raise LawApiError(f"국가법령정보센터 API에 연결하지 못했습니다: {last_exc}")

    @staticmethod
    def _decode(resp: httpx.Response) -> dict[str, Any]:
        if resp.status_code != 200:
            raise LawApiError(f"국가법령정보센터 API 오류 (HTTP {resp.status_code}).")
        try:
            data = resp.json()
        except (json.JSONDecodeError, ValueError):
            snippet = resp.text.strip().replace("\n", " ")[:200]
            raise LawApiError(f"API 응답을 해석할 수 없습니다 (JSON 아님): {snippet}") from None
        if not isinstance(data, dict):
            raise LawApiError("API 응답 형식이 예상과 다릅니다.")
        # Auth/validation failures come back as HTTP 200 {"result": ..., "msg": ...}.
        if "result" in data and "msg" in data and len(data) <= 3:
            raise LawApiError(f"국가법령정보센터 API 오류: {data['result']} {data['msg']}".strip())
        return data

    # -- endpoints ---------------------------------------------------------

    async def search_laws(
        self,
        query: str,
        *,
        body_search: bool = False,
        page: int = 1,
        display: int = 20,
    ) -> SearchResult:
        """현행법령(시행일 기준) 목록 검색. ``nw=3`` restricts to laws in force."""
        data = await self._get(
            "lawSearch.do",
            {
                "target": "eflaw",
                "query": query,
                "search": 2 if body_search else 1,
                "nw": 3,
                "page": page,
                "display": max(1, min(display, 100)),
            },
        )
        return parse_search(data)

    async def list_abbreviations(self) -> list[LawSummary]:
        """법령명 약칭 전체 목록 (target=lsAbrv)."""
        data = await self._get("lawSearch.do", {"target": "lsAbrv"})
        return parse_search(data).items

    async def get_law(self, law_id: str, *, article: str | None = None) -> LawDocument:
        """현행법령(시행일 기준) 본문. ``article`` is a 6-digit JO code to fetch one 조."""
        data = await self._get(
            "lawService.do",
            {"target": "eflaw", "ID": law_id, "JO": article},
        )
        try:
            return parse_law_document(data)
        except ValueError:
            raise LawApiError(f"법령ID {law_id}에 해당하는 현행법령을 찾을 수 없습니다.") from None
