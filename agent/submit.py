from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import httpx


def _fingerprint(artifact: dict[str, Any]) -> str:
    topic = str(artifact.get("title", "")).lower().strip()
    domain = str(artifact.get("domain_slug", "")).lower().strip()
    bundle = artifact.get("source_bundle", [])
    top_keys = []
    for e in bundle[:3]:
        key = e.get("doi") or e.get("url") or str(e.get("title", ""))[:60]
        if key:
            top_keys.append(str(key).lower().strip())
    raw = f"{topic}|{domain}|{'|'.join(sorted(top_keys))}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _find_previous(fingerprint: str, run_dir: str = "runs") -> dict[str, Any] | None:
    runs_path = Path(run_dir)
    if not runs_path.exists():
        return None
    for f in sorted(runs_path.glob("*.json"), reverse=True):
        if f.name.endswith(".raw.json"):
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if data.get("fingerprint") == fingerprint and data.get("submission", {}).get("submission", {}).get("id"):
            return data
    return None


def submit(artifact: dict[str, Any], *, base_url: str | None = None, run_dir: str = "runs") -> dict[str, Any]:
    fp = _fingerprint(artifact)
    prev = _find_previous(fp, run_dir)
    if prev:
        return {"duplicate": True, "fingerprint": fp, "previous_submission_id": prev["submission"]["submission"]["id"], "previous_decision": prev.get("submission", {}).get("decision")}

    url = (base_url or os.getenv("RESEARKA_URL", "")).rstrip("/")
    if not url:
        return {"error": "no RESEARKA_URL configured"}
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
    response = httpx.post(f"{url}/submissions", json=payload, timeout=30, headers={"Idempotency-Key": fp})
    response.raise_for_status()
    result = response.json()
    result["decision"] = {"status": "queued"}
    result["fingerprint"] = fp
    return result


def check_decision(submission_id: str, *, base_url: str | None = None) -> dict[str, Any]:
    url = (base_url or os.getenv("RESEARKA_URL", "")).rstrip("/")
    if not url:
        return {"status": "error", "error": "no RESEARKA_URL"}
    try:
        decision = httpx.get(f"{url}/submissions/{submission_id}/decision", timeout=10).json()
        if decision.get("decision") == "accept":
            try:
                pubs = httpx.get(f"{url}/publications", timeout=10).json()
                for pub in pubs.get("publications", []):
                    if pub.get("parent_object_id") == submission_id:
                        decision["publication_id"] = pub["id"]
                        break
            except Exception:
                pass
        return decision
    except Exception as exc:
        return {"status": "error", "error": str(exc)}
