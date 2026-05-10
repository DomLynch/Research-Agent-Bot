"""Synapse (Sage Bionetworks) adapter.

Endpoint: POST https://repo-prod.prod.sagebase.org/repo/v1/search

Auth: SYNAPSE_AUTH_TOKEN env var (Personal Access Token).
Free; create at https://accounts.synapse.org/authenticated/personalaccesstokens
Scopes needed: view, download.

Synapse hosts biomedical research PROJECTS + datasets — AMP-AD,
MODEL-AD, PsychENCODE, HTAN. Hits returned here are projects / files /
folders, not papers. Useful for surfacing aging-research consortium
data alongside paper hits; the aggregator dedups by URL/DOI.

Fail-soft: missing token, network error, non-200, or parse failure all
return an empty list (the aggregator continues with the other sources).
"""
from __future__ import annotations

import os
from typing import Any

import httpx

from agent.sources._base import USER_AGENT, clean_text
from agent.types import RawHit

SYNAPSE_BASE = "https://repo-prod.prod.sagebase.org/repo/v1"
SEARCH_URL = f"{SYNAPSE_BASE}/search"
ENTITY_URL_TPL = "https://www.synapse.org/Synapse:{syn_id}"

# Most-cited geroscience consortium projects worth surfacing when matched.
# Not enforced — just here as a reference for the database dev curating
# the bulk-ingest list.
KEY_AGING_PROJECTS = (
    "syn2580853",   # AMP-AD (Alzheimer's)
    "syn5550404",   # MODEL-AD (mouse aging models)
    "syn4921369",   # PsychENCODE
    "syn23448901",  # AD Knowledge Portal
)


def _auth_token() -> str | None:
    token = os.environ.get("SYNAPSE_AUTH_TOKEN")
    return token.strip() if token else None


class SynapseClient:
    """Source adapter for the Synapse search endpoint."""

    name = "synapse"

    async def search(
        self,
        client: httpx.AsyncClient,
        query: str,
        *,
        limit: int,
    ) -> list[RawHit]:
        token = _auth_token()
        if not token:
            return []
        headers = {
            "Authorization": f"Bearer {token}",
            "User-Agent": USER_AGENT,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        body = {
            "queryTerm": [clean_text(query, limit=300)],
            "size": max(1, min(limit, 100)),
        }
        try:
            response = await client.post(
                SEARCH_URL, json=body, headers=headers, timeout=20.0,
            )
        except httpx.HTTPError:
            return []
        if response.status_code in (401, 403, 429):
            return []
        # Synapse search returns 201 (treats the query as a created resource);
        # accept both 200 and 201 to be tolerant of contract drift.
        if response.status_code not in (200, 201):
            return []
        try:
            data = response.json()
        except ValueError:
            return []
        hits = data.get("hits") if isinstance(data, dict) else None
        if not isinstance(hits, list):
            return []
        return [
            hit for hit in (self._parse_hit(h) for h in hits) if hit is not None
        ]

    def _parse_hit(self, hit: Any) -> RawHit | None:
        if not isinstance(hit, dict):
            return None
        syn_id = hit.get("id") or hit.get("entity_id") or ""
        title = clean_text(hit.get("name") or hit.get("title"), limit=300)
        if not title:
            return None
        # Synapse's `description` is the closest analog to an abstract;
        # falls back to entity-type label so the aggregator never sees
        # an empty abstract.
        description = clean_text(hit.get("description") or "", limit=2000)
        if not description:
            entity_type = (hit.get("node_type") or "").replace("entity.", "") or "synapse_entity"
            description = f"Synapse {entity_type}: {title}."
        url = ENTITY_URL_TPL.format(syn_id=syn_id) if syn_id else ""
        year = self._extract_year(hit)
        return RawHit(
            source="synapse",
            title=title,
            abstract=description,
            year=year,
            url=url,
            doi=None,
            pmid=None,
            nct=None,
            venue="Synapse",
            raw={"synapse_id": syn_id, "node_type": hit.get("node_type")},
        )

    @staticmethod
    def _extract_year(hit: dict[str, Any]) -> int | None:
        # Synapse search returns `created_on` / `modified_on` as epoch SECONDS
        # (verified live 2026-05-09: e.g. 1376581601 → 2013-08-15).
        from datetime import UTC, datetime
        for key in ("created_on", "modified_on"):
            value = hit.get(key)
            if isinstance(value, int) and value > 0:
                try:
                    return datetime.fromtimestamp(value, tz=UTC).year
                except (OSError, ValueError, OverflowError):
                    continue
        return None
