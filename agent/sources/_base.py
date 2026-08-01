"""Source adapter contract and shared helpers."""
from __future__ import annotations

import html
import re
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from agent.types import RawHit

SourceStatus = str


@dataclass(frozen=True, slots=True)
class SourceResult:
    hits: list[RawHit]
    status: SourceStatus
    error: str = ""


class SourceProviderError(RuntimeError):
    """Typed provider failure; never confused with a valid empty result."""

    def __init__(self, status: SourceStatus, detail: str) -> None:
        super().__init__(detail)
        self.status = status


_PROVIDER_FAILURE: ContextVar[tuple[SourceStatus, str] | None] = ContextVar(
    "source_provider_failure", default=None,
)


def reset_source_provider_status() -> None:
    _PROVIDER_FAILURE.set(None)


def record_source_provider_failure(status: SourceStatus, detail: str) -> None:
    _PROVIDER_FAILURE.set((status, detail))


def source_provider_status() -> tuple[SourceStatus, str] | None:
    return _PROVIDER_FAILURE.get()

USER_AGENT = "research-agent/1.0 (+https://research-agent.domlynch.com)"

# Default request timeout for all source adapters — long enough for slow
# API endpoints (NCBI on bad days, OpenAIRE), short enough that one stuck
# source doesn't strand the whole aggregator fan-out.
_DEFAULT_TIMEOUT = 20.0


async def safe_get_json(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = _DEFAULT_TIMEOUT,
) -> dict[str, Any] | None:
    """GET + parse JSON; record provider failures and preserve fail-soft IO."""
    try:
        response = await client.get(
            url, params=params, headers=headers, timeout=timeout,
        )
    except httpx.HTTPError as exc:
        record_source_provider_failure(
            "transport_error", f"{type(exc).__name__}: {exc}",
        )
        return None
    if response.status_code in (401, 403):
        record_source_provider_failure("auth_failed", f"HTTP {response.status_code}")
        return None
    if response.status_code == 429:
        record_source_provider_failure("rate_limited", "HTTP 429")
        return None
    if response.status_code >= 500:
        record_source_provider_failure("server_error", f"HTTP {response.status_code}")
        return None
    if response.status_code != 200:
        record_source_provider_failure("http_error", f"HTTP {response.status_code}")
        return None
    try:
        data = response.json()
    except ValueError as exc:
        record_source_provider_failure(
            "bad_json", f"{type(exc).__name__}: {exc}",
        )
        return None
    if not isinstance(data, dict):
        record_source_provider_failure(
            "bad_shape", f"JSON root is {type(data).__name__}, not object",
        )
        return None
    return data


async def safe_get_text(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = _DEFAULT_TIMEOUT,
) -> str | None:
    """GET raw text body; record provider failures and preserve fail-soft IO."""
    try:
        response = await client.get(
            url, params=params, headers=headers, timeout=timeout,
        )
    except httpx.HTTPError as exc:
        record_source_provider_failure(
            "transport_error", f"{type(exc).__name__}: {exc}",
        )
        return None
    if response.status_code in (401, 403):
        record_source_provider_failure("auth_failed", f"HTTP {response.status_code}")
        return None
    if response.status_code == 429:
        record_source_provider_failure("rate_limited", "HTTP 429")
        return None
    if response.status_code >= 500:
        record_source_provider_failure("server_error", f"HTTP {response.status_code}")
        return None
    if response.status_code != 200:
        record_source_provider_failure("http_error", f"HTTP {response.status_code}")
        return None
    if not response.text:
        record_source_provider_failure("empty_body", "HTTP 200 empty body")
        return None
    return response.text


# Inline formatting tags — '<sup>13</sup>C' should become '13C', not '13 C'.
_HTML_INLINE_RE = re.compile(
    r"</?(?:i|b|sup|sub|u|em|strong|tt|small|big|italic|bold|monospace)"
    r"(?:\s[^>]*)?/?>",
    re.IGNORECASE,
)
# Block-level / structural tags — '<h4>Methods</h4>METFORAGING' must become
# 'Methods METFORAGING' so the LLM doesn't read concatenated heading-then-
# body as a single token. Without this, the LLM read EuropePMC's section
# headings as part of the surrounding sentence ('We aimed to test...' under
# <h4>Background</h4>) and described a published RCT as if it were a
# planned trial — triggering the results-described-as-pending QA gate.
_HTML_BLOCK_RE = re.compile(
    r"</?(?:h[1-6]|p|br|span|div|sec|title|article-title|abstract|abstracttext"
    r"|list|list-item|item|label|xref|fn|ext-link|inline-formula"
    r"|disp-formula|caption)"
    r"(?:\s[^>]*)?/?>",
    re.IGNORECASE,
)


def clean_text(value: object, *, limit: int = 1600) -> str:
    """Strip recognized HTML / JATS tags and collapse whitespace."""
    text = str(value or "")
    text = _HTML_INLINE_RE.sub("", text)
    text = _HTML_BLOCK_RE.sub(" ", text)
    text = html.unescape(text)
    return " ".join(text.split()).strip()[:limit]


def normalize_doi(value: object) -> str | None:
    """Return canonical lowercase DOI with protocol/scheme stripped."""
    text = clean_text(value, limit=256).lower()
    if not text:
        return None
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:", "doi.org/"):
        if text.startswith(prefix):
            text = text[len(prefix):]
    return text.strip() or None


class SourceClient(Protocol):
    """Adapter contract. Every adapter is one of these."""

    name: str

    async def search(
        self,
        client: httpx.AsyncClient,
        query: str,
        *,
        limit: int,
    ) -> list[RawHit]: ...
