"""Source adapter contract and shared helpers.

Every adapter implements `SourceClient`. Adapters are stateless and DO NOT
own their own httpx client — retrieve.py owns a single shared
`httpx.AsyncClient` and passes it in. This reuses TCP connections and
avoids socket exhaustion under fan-out.
"""
from __future__ import annotations

import html
import re
from typing import Protocol

import httpx

from agent.types import RawHit

USER_AGENT = "research-agent/1.0 (+https://research-agent.domlynch.com)"


_HTML_TAG_RE = re.compile(
    r"</?(?:i|b|sup|sub|u|em|strong|br|p|span|div|tt|small|big)"
    r"(?:\s[^>]*)?/?>",
    re.IGNORECASE,
)


def clean_text(value: object, *, limit: int = 1600) -> str:
    """Strip recognized HTML tags, decode entities, collapse whitespace.

    Earlier versions stripped anything between '<' and '>', which destroyed
    inequalities ('p<0.05' became 'p') and broke the outcome-regex matcher
    that depends on that exact form. This now strips ONLY known formatting
    tags so 'p<0.05' and 'x>2' survive as written.
    """
    text = str(value or "")
    text = _HTML_TAG_RE.sub("", text)
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
