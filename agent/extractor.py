from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from agent.fulltext import entry_identity
from agent.provider import MimoClient


EXTRACTOR_VERSION = "tier1.5-v1"


def _clean(value: Any, *, limit: int = 1200) -> str:
    return " ".join(str(value or "").split()).strip()[:limit]


def _cache_path(cache_dir: Path, entry: dict[str, Any], version: str) -> Path:
    identity = f"{version}:{entry_identity(entry)}"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return cache_dir / f"{digest}.json"


def _normalize_effect(raw: Any) -> dict[str, str]:
    effect = raw if isinstance(raw, dict) else {}
    return {
        "outcome": _clean(effect.get("outcome"), limit=160),
        "metric": _clean(effect.get("metric"), limit=40),
        "value": _clean(effect.get("value"), limit=40),
        "ci_low": _clean(effect.get("ci_low"), limit=40),
        "ci_high": _clean(effect.get("ci_high"), limit=40),
        "p_value": _clean(effect.get("p_value"), limit=40),
        "n": _clean(effect.get("n"), limit=40),
        "source_span": _clean(effect.get("source_span"), limit=320),
    }


def _normalize_payload(payload: dict[str, Any], *, version: str) -> dict[str, Any]:
    effects = payload.get("effects")
    return {
        "primary_outcome": _clean(payload.get("primary_outcome"), limit=200),
        "population": _clean(payload.get("population"), limit=200),
        "intervention": _clean(payload.get("intervention"), limit=200),
        "comparator": _clean(payload.get("comparator"), limit=160),
        "methods_summary": _clean(payload.get("methods_summary"), limit=260),
        "risk_of_bias": _clean(payload.get("risk_of_bias"), limit=200),
        "effects": [_normalize_effect(item) for item in effects if isinstance(item, dict)][:3] if isinstance(effects, list) else [],
        "extractor_version": version,
        "source_doi": _clean(payload.get("source_doi"), limit=256),
    }


def _has_signal(extraction: dict[str, Any]) -> bool:
    return bool(
        extraction.get("population")
        or extraction.get("intervention")
        or extraction.get("primary_outcome")
        or extraction.get("effects")
        or extraction.get("methods_summary")
    )


class StructuredExtractor:
    def __init__(self, *, cache_dir: str | Path, provider: Any, version: str = EXTRACTOR_VERSION) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.provider = provider
        self.version = version

    @classmethod
    def from_env(cls, *, cache_dir: str | Path) -> "StructuredExtractor":
        builder = MimoClient.from_env()
        if isinstance(builder, MimoClient):
            from agent.moa_spar_bridge import MoaSparBridgeClient

            return cls(cache_dir=cache_dir, provider=MoaSparBridgeClient.from_env(builder=builder))
        return cls(cache_dir=cache_dir, provider=builder)

    def extract(self, entry: dict[str, Any]) -> dict[str, Any] | None:
        cache_path = _cache_path(self.cache_dir, entry, self.version)
        if cache_path.exists():
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            return cached if cached.get("found") else None
        full_text = _clean(entry.get("full_text"), limit=12000)
        if not full_text:
            cache_path.write_text(json.dumps({"found": False, "reason": "no_full_text"}), encoding="utf-8")
            return None
        sections = entry.get("full_text_sections") or {}
        result = _clean(sections.get("results"), limit=4000)
        methods = _clean(sections.get("methods"), limit=3000)
        discussion = _clean(sections.get("discussion"), limit=2000)
        system_prompt = (
            "You extract structured study facts from a single biomedical paper. "
            "Return JSON only. Be conservative. If a field is not supported, return an empty string. "
            "For effects, include only claims explicitly stated in the provided text and copy a short verbatim source_span."
        )
        user_prompt = (
            f"Title: {_clean(entry.get('title'), limit=240)}\n"
            f"DOI: {_clean(entry.get('doi'), limit=256)}\n"
            f"Abstract: {_clean(entry.get('excerpt'), limit=1200)}\n"
            f"Methods: {methods or 'n/a'}\n"
            f"Results: {result or 'n/a'}\n"
            f"Discussion: {discussion or 'n/a'}\n\n"
            "Return exactly this JSON shape: "
            "{primary_outcome, population, intervention, comparator, methods_summary, risk_of_bias, "
            "effects:[{outcome, metric, value, ci_low, ci_high, p_value, n, source_span}], source_doi}."
        )
        payload, _ = self.provider.complete_json(system_prompt=system_prompt, user_prompt=user_prompt)
        extraction = _normalize_payload(payload, version=self.version)
        if not _has_signal(extraction):
            cache_path.write_text(json.dumps({"found": False, "reason": "empty_extraction"}), encoding="utf-8")
            return None
        wrapped = {"found": True, **extraction}
        cache_path.write_text(json.dumps(wrapped, indent=2), encoding="utf-8")
        return wrapped

    def enrich_entries(self, entries: list[dict[str, Any]], *, limit: int = 6) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        enriched: list[dict[str, Any]] = []
        attempted = 0
        found = 0
        for entry in entries:
            cloned = dict(entry)
            if attempted < limit and cloned.get("full_text") and cloned.get("source_type") in {"pubmed", "openalex", "rxiv"}:
                attempted += 1
                try:
                    extraction = self.extract(cloned)
                except Exception:
                    extraction = None
                if extraction:
                    found += 1
                    cloned["extraction"] = extraction
            enriched.append(cloned)
        return enriched, {"attempted": attempted, "found": found, "version": self.version}
