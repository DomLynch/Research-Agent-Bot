"""Read-only cross-topic run aggregator.

Loads finalized synthesis run artifacts and builds a field-level manifest.
This module does not re-score, promote, or synthesize claims.
"""
from __future__ import annotations

import json
import re
from collections.abc import Iterable
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

Eligibility = Literal[
    "full_aaa_primary", "analytical_support", "scoped_support", "excluded",
]


@dataclass(frozen=True, slots=True)
class TopicRunSummary:
    topic: str
    run_id: str
    run_path: str
    eligibility: Eligibility
    verdict: str
    maturity_level: int
    maturity_label: str
    certification_track: str
    journal_ready: bool
    n_receipts: int
    n_high_confidence_claims: int
    n_tensions: int
    directness_mix: dict[str, int]
    evidence_tier_mix: dict[str, int]
    effect_direction_mix: dict[str, int]
    outcome_effects: dict[str, dict[str, int]]
    outcome_domains: tuple[str, ...]
    citation_keys: tuple[str, ...]
    exclusion_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class FieldManifest:
    topics: tuple[TopicRunSummary, ...]
    unique_citation_count: int
    duplicate_citation_keys: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "topics": [t.to_dict() for t in self.topics],
            "unique_citation_count": self.unique_citation_count,
            "duplicate_citation_keys": list(self.duplicate_citation_keys),
        }


def build_field_manifest(run_dirs: tuple[str | Path, ...]) -> FieldManifest:
    topics = tuple(load_topic_run_summary(Path(p)) for p in run_dirs)
    counts = Counter(key for topic in topics for key in topic.citation_keys)
    return FieldManifest(
        topics=topics,
        unique_citation_count=len(counts),
        duplicate_citation_keys=tuple(sorted(k for k, n in counts.items() if n > 1)),
    )


def load_topic_run_summary(run_dir: Path) -> TopicRunSummary:
    run_id = run_dir.name
    topic = _topic_from_run_id(run_id)
    verdict_path = run_dir / "full_paper.final_verdict.json"
    manifest_path = run_dir / "manifest.json"
    registry_path = run_dir / "citation_registry.json"
    missing = [
        path.name for path in (verdict_path, manifest_path, registry_path)
        if not path.exists()
    ]
    if missing:
        return _excluded(run_dir, topic, f"missing artifacts: {', '.join(missing)}")

    verdict = _read_json(verdict_path)
    manifest = _read_json(manifest_path)
    registry = _read_json(registry_path)
    receipts = manifest.get("receipts", [])
    return TopicRunSummary(
        topic=topic,
        run_id=run_id,
        run_path=str(run_dir),
        eligibility=_eligibility(verdict),
        verdict=str(verdict.get("verdict", "")),
        maturity_level=int(verdict.get("maturity_level") or 0),
        maturity_label=str(verdict.get("maturity_label", "")),
        certification_track=str(verdict.get("certification_track", "")),
        journal_ready=bool(verdict.get("journal_ready")),
        n_receipts=int(manifest.get("n_receipts") or len(receipts)),
        n_high_confidence_claims=int(
            manifest.get("n_high_confidence_claims_total") or 0
        ),
        n_tensions=int(manifest.get("n_non_orthogonal_tensions") or 0),
        directness_mix=_count_field(receipts, "directness"),
        evidence_tier_mix=_count_field(receipts, "evidence_tier"),
        effect_direction_mix=_count_field(receipts, "effect_direction"),
        outcome_effects=_outcome_effects(receipts),
        outcome_domains=tuple(sorted(_nonempty(r.get("outcome_class") for r in receipts))),
        citation_keys=tuple(sorted(_citation_keys(registry))),
        exclusion_reason=None,
    )


def _eligibility(verdict: dict[str, Any]) -> Eligibility:
    if verdict.get("verdict") != "AAA":
        return "excluded"
    track = str(verdict.get("certification_track", ""))
    level = int(verdict.get("maturity_level") or 0)
    if "SCOP" in track:
        return "scoped_support"
    if level >= 5 and verdict.get("journal_ready"):
        return "full_aaa_primary"
    if level >= 4:
        return "analytical_support"
    return "scoped_support"


def _excluded(run_dir: Path, topic: str, reason: str) -> TopicRunSummary:
    return TopicRunSummary(
        topic=topic,
        run_id=run_dir.name,
        run_path=str(run_dir),
        eligibility="excluded",
        verdict="",
        maturity_level=0,
        maturity_label="",
        certification_track="",
        journal_ready=False,
        n_receipts=0,
        n_high_confidence_claims=0,
        n_tensions=0,
        directness_mix={},
        evidence_tier_mix={},
        effect_direction_mix={},
        outcome_effects={},
        outcome_domains=(),
        citation_keys=(),
        exclusion_reason=reason,
    )


def _topic_from_run_id(run_id: str) -> str:
    match = re.match(r"^synthesis-(.+?)-v\d+", run_id)
    return match.group(1) if match else run_id


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _count_field(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    return dict(Counter(str(row.get(field) or "unknown") for row in rows))


def _outcome_effects(rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    out: dict[str, Counter[str]] = {}
    for row in rows:
        outcome = str(row.get("outcome_class") or "unknown")
        effect = str(row.get("effect_direction") or "unknown")
        out.setdefault(outcome, Counter())[effect] += 1
    return {outcome: dict(counts) for outcome, counts in out.items()}


def _citation_keys(registry: dict[str, dict[str, Any]]) -> set[str]:
    keys: set[str] = set()
    for receipt_id, row in registry.items():
        key = (
            row.get("source_doi")
            or row.get("source_pmid")
            or row.get("source_pmcid")
            or receipt_id
        )
        keys.add(str(key).lower())
    return keys


def _nonempty(values: object) -> set[str]:
    if not isinstance(values, Iterable) or isinstance(values, (str, bytes)):
        return {str(values)} if values else set()
    return {str(v) for v in values if v}
