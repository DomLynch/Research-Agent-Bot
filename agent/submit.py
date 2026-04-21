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

_STOPWORDS = {"and", "in", "for", "of", "the", "with", "on", "to", "a", "an"}


def _topic_tokens(title: str) -> list[str]:
    return [t for t in re.sub(r"[^a-z0-9 ]", " ", title.lower()).split() if t not in _STOPWORDS and len(t) > 2]


def _quality_gate(artifact: dict[str, Any], *, current_year: int | None = None, topic: str = "") -> str | None:
    bundle = artifact.get("source_bundle", [])
    if len(bundle) < 12:
        return f"bundle_too_small:{len(bundle)}"

    for entry in bundle:
        title = str(entry.get("title") or "")
        if title and _INJECTION_RE.search(title):
            return "injection_detected"

    # topic_precision: % of bundle titles sharing >=1 token with the *topic*
    # Falls back to artifact title prefix if topic is empty.
    # This prevents gaming via generic tokens like "rapid", "evidence", "synthesis".
    if not topic:
        raw_title = str(artifact.get("title", ""))
        # Strip the "Rapid Evidence Synthesis: " prefix so common words don't inflate hits
        raw_title = re.sub(r"^rapid evidence synthesis:\s*", "", raw_title, flags=re.IGNORECASE)
        topic = raw_title
    tokens = _topic_tokens(topic)
    if tokens:
        hits = sum(
            1 for e in bundle
            if any(t in str(e.get("title") or "").lower() for t in tokens)
        )
        topic_prec = hits / len(bundle)
        if topic_prec < 0.40:
            return f"low_topic_precision:{topic_prec:.2f}"

    # recent_ratio: % of sources from last 5 years
    if current_year is None:
        from datetime import datetime, timezone
        current_year = datetime.now(timezone.utc).year
    recent_threshold = current_year - 5
    recent = sum(
        1 for e in bundle
        if isinstance(e.get("year"), int) and e["year"] >= recent_threshold
    )
    recent_ratio = recent / len(bundle)
    if recent_ratio < 0.50:
        return f"low_recent_ratio:{recent_ratio:.2f}"

    # source_mix: at least 1 review-type source
    reviews = sum(1 for e in bundle if e.get("evidence_type") == "review")
    if reviews < 1:
        return "no_review_sources"

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
            {**{k: v for k, v in entry.items() if k in ("title", "evidence_type", "year", "url", "doi", "relevance")},
             **({"card": entry["card"]} if "card" in entry else {})}
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
