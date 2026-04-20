from __future__ import annotations

import os
from typing import Any

import httpx


def submit(artifact: dict[str, Any], *, base_url: str | None = None) -> dict[str, Any]:
    url = base_url or os.getenv("RESEARKA_URL", "http://localhost:8000")
    payload = {
        "title": artifact["title"],
        "abstract": artifact["abstract"],
        "sections": artifact.get("sections", {}),
        "source_bundle": [
            {k: v for k, v in entry.items() if k in ("title", "evidence_type", "year", "url", "doi", "relevance")}
            for entry in artifact.get("source_bundle", [])
        ],
        "author_agent_id": os.getenv("AGENT_ID", "research-agent-bot"),
        "domain_slug": artifact.get("domain_slug", "general"),
        "core_claims_resolved": True,
    }
    response = httpx.post(f"{url.rstrip('/')}/submissions", json=payload, timeout=30)
    response.raise_for_status()
    return response.json()
