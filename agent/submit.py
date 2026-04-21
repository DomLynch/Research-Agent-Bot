from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

import httpx

_INJECTION_PATTERNS = (
    r"ignore previous instructions",
    r"you are now",
    r"system prompt",
    r"reveal your",
    r"act as",
    r"do not follow",
    r"new instructions",
    r"override",
    r"jailbreak",
    r"prompt injection",
    r"disregard.*above",
    r"<\|im_start\|>",
    r"<\|im_end\|>",
    r"BEGINCHAT",
    r"ENDCHAT",
)
_INJECTION_RE = re.compile("|".join(_INJECTION_PATTERNS), re.IGNORECASE)

_TONE_POSITIVE = {"promising", "robust", "significant", "effective", "novel", "validated", "strong"}
_TONE_NEGATIVE = {"limited", "small", "inconclusive", "unclear", "weak", "insufficient", "heterogeneous"}


def _tone_rating(text: str) -> float:
    lower = text.lower()
    pos = sum(1 for w in _TONE_POSITIVE if w in lower)
    neg = sum(1 for w in _TONE_NEGATIVE if w in lower)
    total = pos + neg
    if total == 0:
        return 0.5
    return round(pos / total, 2)


def _quality_gate(artifact: dict[str, Any]) -> str | None:
    bundle = artifact.get("source_bundle", [])
    if len(bundle) < 12:
        return f"bundle_too_small:{len(bundle)}"

    for entry in bundle:
        title = str(entry.get("title") or "")
        if title and _INJECTION_RE.search(title):
            return "injection_detected"

    titles = [str(e.get("title") or "") for e in bundle]
    titled_pct = sum(1 for t in titles if t.strip()) / len(titles)
    if titled_pct < 0.60:
        return f"low_title_precision:{titled_pct:.2f}"

    tones = [_tone_rating(t) for t in titles]
    avg_tone = sum(tones) / len(tones)
    if avg_tone < 0.70:
        return f"low_tone:{avg_tone:.2f}"

    return None


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
    gate_reason = _quality_gate(artifact)
    if gate_reason:
        return {"gate_blocked": True, "reason": gate_reason}

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
    response = httpx.post(f"{url}/submissions", json=payload, timeout=30, headers={"Idempotency-Key": fp, "X-Api-Key": os.getenv("RESEARKA_V2_API_KEY", "")})
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
        headers = {"X-Api-Key": os.getenv("RESEARKA_V2_API_KEY", "")}
        decision = httpx.get(f"{url}/submissions/{submission_id}/decision", timeout=10, headers=headers).json()
        if decision.get("decision") == "accept":
            try:
                pubs = httpx.get(f"{url}/publications", timeout=10, headers=headers).json()
                for pub in pubs.get("publications", []):
                    if pub.get("parent_object_id") == submission_id:
                        decision["publication_id"] = pub["id"]
                        break
            except Exception:
                pass
        return decision
    except Exception as exc:
        return {"status": "error", "error": str(exc)}
