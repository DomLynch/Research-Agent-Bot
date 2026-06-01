"""Source adapter contract and shared helpers."""
from __future__ import annotations

import html
import re
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
    """GET + parse JSON, fail-soft on transport/status/parse failure."""
    try:
        response = await client.get(
            url, params=params, headers=headers, timeout=timeout,
        )
    except httpx.HTTPError:
        return None
    if response.status_code in (401, 403, 429):
        return None
    if response.status_code >= 500 or response.status_code != 200:
        return None
    try:
        return response.json()
    except ValueError:
        return None


async def safe_get_text(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = _DEFAULT_TIMEOUT,
) -> str | None:
    """GET raw text body, fail-soft for XML/Atom adapters."""
    try:
        response = await client.get(
            url, params=params, headers=headers, timeout=timeout,
        )
    except httpx.HTTPError:
        return None
    if response.status_code in (401, 403, 429):
        return None
    if response.status_code >= 500 or response.status_code != 200:
        return None
    return response.text or None


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
