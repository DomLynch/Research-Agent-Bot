"""Extraction queue + funnel telemetry — Slice 8 step C
(2026-05-05).

End-game synthesis funnel:

  retrieved → classified_keep → extracted → SPAR_accepted →
  clustered → synthesized

This module is the bridge between corpus_pipeline (which classifies
metadata and produces a CorpusManifest) and the deterministic
quant_claim_extract.py CPU work. Only papers in the keep pool
(core_on_thesis + background_mechanism + adjacent_clinical) enter
the extraction queue. reject + off_thesis never see CPU.

Funnel telemetry:
  ExtractionFunnel carries per-stage counts that the dashboard
  surfaces (Slice 8 step F). Every transition writes a sidecar
  manifest so an interrupted pull is recoverable + auditable.

Universal across topics + domains. Pure-Python orchestrator;
quant_claim_extract.py runs as a subprocess for each kept paper.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent.corpus_pipeline import CorpusEntry, CorpusManifest


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    """Per-paper extraction outcome."""
    paper_id: str
    status: str       # 'extracted' | 'cached' | 'failed' | 'skipped'
    n_claims: int
    error: str | None = None


@dataclass(slots=True)
class ExtractionFunnel:
    """End-to-end funnel: retrieved → classified → extracted →
    SPAR accepted → clustered → synthesized.

    Every stage is a counter. The dashboard renders these directly.
    Slice 8 step F also surfaces them per-topic in the living
    corpus dashboard."""
    topic: str
    retrieved: int = 0
    classified_keep: int = 0
    classified_drop: int = 0
    extracted_ok: int = 0
    extracted_cached: int = 0
    extracted_failed: int = 0
    spar_accepted: int = 0       # filled by synthesis stage later
    clustered_into_n: int = 0    # filled by clusterer (Slice 8 D)
    synthesized: int = 0         # 1 if a paper.md was produced
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "stages": {
                "retrieved": self.retrieved,
                "classified_keep": self.classified_keep,
                "classified_drop": self.classified_drop,
                "extracted_ok": self.extracted_ok,
                "extracted_cached": self.extracted_cached,
                "extracted_failed": self.extracted_failed,
                "spar_accepted": self.spar_accepted,
                "clustered_into_n": self.clustered_into_n,
                "synthesized": self.synthesized,
            },
            "notes": list(self.notes),
        }


def run_extraction_queue(
    manifest: CorpusManifest, *,
    parsed_dir: Path, quant_dir: Path,
    extractor_script: Path,
    funnel: ExtractionFunnel | None = None,
    max_workers: int = 4,
) -> tuple[list[ExtractionResult], ExtractionFunnel]:
    """Run quant_claim_extract on every kept entry's parsed_sections
    file. Caches: an entry whose target quant_claims.json already
    exists is skipped (status='cached'). Failed extracts are
    recorded but don't kill the queue.

    Universal: works for any topic + domain. The extractor itself
    is domain-agnostic deterministic regex extraction.
    """
    f = funnel or ExtractionFunnel(topic=manifest.topic)
    f.retrieved = manifest.funnel.get("retrieved", 0)
    f.classified_keep = manifest.funnel.get("classified_keep", 0)
    f.classified_drop = manifest.funnel.get("classified_drop", 0)
    results: list[ExtractionResult] = []
    quant_dir.mkdir(parents=True, exist_ok=True)
    for entry in manifest.kept():
        paper_id = entry.classification.paper_id
        # Look up parsed_sections file. Filename pattern:
        # <paper_id>.paper_sections.json — paper_id may contain
        # path-illegal chars depending on extractor; treat the doi
        # or pmid form too.
        candidate_files = [
            parsed_dir / f"{paper_id}.paper_sections.json",
        ]
        # Also accept slugged forms used by fetch_oa_corpus.py
        for p in parsed_dir.glob("*.paper_sections.json"):
            if (
                paper_id and paper_id in p.name
            ):
                candidate_files.append(p)
                break
        sections_path = next(
            (c for c in candidate_files if c.exists()), None,
        )
        if sections_path is None:
            results.append(ExtractionResult(
                paper_id=paper_id, status="skipped", n_claims=0,
                error="no parsed_sections file found",
            ))
            continue
        target = quant_dir / (
            sections_path.stem.replace(".paper_sections", "")
            + ".quant_claims.json"
        )
        if target.exists():
            # Cached: count claims for the funnel
            n = _count_claims(target)
            results.append(ExtractionResult(
                paper_id=paper_id, status="cached", n_claims=n,
            ))
            f.extracted_cached += 1
            continue
        # Run the extractor as a subprocess. Universal — same script
        # for every topic / domain.
        try:
            subprocess.run(
                [
                    "python3", str(extractor_script),
                    str(sections_path), "--out", str(target),
                ],
                check=True, capture_output=True, timeout=60,
            )
            n = _count_claims(target)
            results.append(ExtractionResult(
                paper_id=paper_id, status="extracted", n_claims=n,
            ))
            f.extracted_ok += 1
        except (subprocess.CalledProcessError,
                subprocess.TimeoutExpired, OSError) as e:
            results.append(ExtractionResult(
                paper_id=paper_id, status="failed", n_claims=0,
                error=f"{type(e).__name__}: {str(e)[:120]}",
            ))
            f.extracted_failed += 1
    return results, f


def _count_claims(quant_path: Path) -> int:
    """Read a quant_claims.json file and count claims. Returns 0
    on read errors (best-effort telemetry)."""
    try:
        data = json.loads(quant_path.read_text())
    except (OSError, ValueError):
        return 0
    return len(data.get("claims") or [])


def write_funnel_sidecar(
    funnel: ExtractionFunnel, *, out_path: Path,
) -> None:
    """Persist the funnel manifest JSON. Dashboard reads this per-
    topic to render the end-to-end pipeline view."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(funnel.to_dict(), indent=2))


__all__ = [
    "ExtractionFunnel", "ExtractionResult",
    "run_extraction_queue", "write_funnel_sidecar",
]
