from __future__ import annotations

import os
import time
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
    result = response.json()
    sub_id = result.get("submission", {}).get("id")

    # process intake → review → editorial pipeline
    if sub_id:
        for _ in range(6):
            try:
                job = httpx.post(f"{url.rstrip('/')}/jobs/run-once", timeout=120).json()
                if job.get("completed", 0) == 0:
                    break
                time.sleep(1)
            except Exception:
                break
        try:
            decision = httpx.get(f"{url.rstrip('/')}/submissions/{sub_id}/decision", timeout=10).json()
            result["decision"] = decision
        except Exception as exc:
            result["decision"] = {"status": "error", "error": str(exc)}

    return result
