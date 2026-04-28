#!/usr/bin/env python3
"""Proof 001 — first end-to-end metformin run.

Drives the full Day 4-5 trust-spine pipeline against a real (or replayed)
metformin corpus and emits the 8 mandatory receipts to
`runs/metformin-001-<UTC>-<rand>/`. This is the live counterpart to
`tests/test_e2e_proof_001_fixture.py`, which proves the same pipeline
works under pure fixture replay.

Modes:
  --live              Hit real PubMed / OpenAlex / EuropePMC /
                      ClinicalTrials.gov adapters. Default replays the
                      captured fixture corpus from
                      `tests/fixtures/metformin/`.
  --max-items N       Cap items sent to the LLM (cost containment).
                      Default: no cap. **Canonical trials (per the
                      topic_pack) are PINNED to the top of the
                      selection so MASTERS / TAME / etc. are never
                      dropped by the cap.**
  --output-dir PATH   Override the timestamped output directory. Used
                      to retry a partial run after a crash; the
                      orchestrator's force_overwrite flag is honored.

LLM chains:
  Fact extraction:  MiMo V2.5 Pro → Mistral Small (fallback)
  SPAR judges:      Gemma 4 31B → MiMo V2.5 Pro → Mistral Small

Trace clients: fixture by default; pass `TRACE_BACKEND=http` env var to
hit live CT.gov / ChEMBL / Europe PMC.

Cost: ~$0.005-0.01 per full run (1 fact-extract per item + 3 SPAR
judges). Use `--max-items` to cap items if running on many.

Exit codes:
  0    accept_clean / accept_caveated
  1    reject_majority / reject_critical (full audit still produced)
  2    config error (missing keys, bad args, fixture load failure)
  3    pipeline runtime error (orchestrator raised mid-run)

Usage:
    .venv/bin/python -m scripts.e2e_metformin_proof_001
    .venv/bin/python -m scripts.e2e_metformin_proof_001 --live
    .venv/bin/python -m scripts.e2e_metformin_proof_001 --max-items 5
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from agent.evidence_cards import bundle
from agent.llm_client import build_extract_chain, build_judge_chain
from agent.orchestrator import RunReceipts, run_proof
from agent.retrieve import normalize_and_dedup, retrieve
from agent.settings import load_settings
from agent.sources.clinicaltrials import ClinicalTrialsClient
from agent.sources.europepmc import EuropePMCClient
from agent.sources.openalex import OpenAlexClient
from agent.sources.pubmed import PubMedClient
from agent.topic_pack import TopicPack, load_topic_pack
from agent.trace_clients import (
    get_drug_alias_client,
    get_trial_registry_client,
)
from agent.types import EvidenceItem, RawHit, Source

REPO_ROOT = Path(__file__).resolve().parent.parent
TOPIC_PACK_PATH = REPO_ROOT / "topic_packs" / "metformin.toml"
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "metformin"
RUNS_DIR = REPO_ROOT / "runs"
ADAPTER_PRIORITY = ("pubmed", "openalex", "europepmc", "clinicaltrials")


def _load_fixture_hits() -> list[RawHit]:
    """Replay the captured metformin RawHits from tests/fixtures.

    Raises FileNotFoundError if NO fixtures are loadable so the operator
    sees the cause clearly (vs. a misleading "0 sources after dedup")."""
    hits: list[RawHit] = []
    missing: list[str] = []
    for adapter in ADAPTER_PRIORITY:
        path = FIXTURES_DIR / f"{adapter}.json"
        if not path.exists():
            missing.append(adapter)
            continue
        for entry in json.loads(path.read_text(encoding="utf-8")):
            hits.append(RawHit(**entry))
    if not hits:
        raise FileNotFoundError(
            f"no fixtures loaded from {FIXTURES_DIR}; missing adapters: "
            f"{missing}. Either run scripts/capture_fixtures.py or pass --live."
        )
    if missing:
        print(f"WARN: missing fixtures for adapter(s) {missing}", file=sys.stderr)
    return hits


async def _retrieve_live() -> tuple[list[Source], dict[int, str], dict[int, dict]]:
    """Fan out to live PubMed / OpenAlex / EuropePMC / CT.gov."""
    sources_clients = [
        PubMedClient(),
        OpenAlexClient(),
        EuropePMCClient(),
        ClinicalTrialsClient(),
    ]
    return await retrieve(
        topic="metformin",
        criteria="aging OR longevity OR healthspan",
        sources=sources_clients,
        domain="longevity older adults",
    )


def _ranked_for_extraction(
    items: list[EvidenceItem],
    max_items: int | None,
    *,
    pack: TopicPack,
) -> list[EvidenceItem]:
    """Cap the corpus by canonical-pin → role → tier → ref priority.

    Day 5.3-fix P1: canonical_trials from the topic_pack are PINNED to
    the head of the list so MASTERS / TAME / etc. are never dropped by
    `--max-items`. The remaining items sort by role priority
    (published_results > protocol > review > mechanistic), tier, then
    ref for stable ordering.
    """
    if max_items is None:
        return items
    canonical_ids = {trial.id for trial in pack.canonical_trials}

    def _role_rank(role: str) -> int:
        return (
            0 if role == "published_results"
            else 1 if role in ("published_protocol", "registered_pending")
            else 2 if role == "review"
            else 3 if role == "mechanistic"
            else 4
        )

    def _is_canonical(it: EvidenceItem) -> bool:
        return bool(it.source.nct) and it.source.nct in canonical_ids

    canonical = [it for it in items if _is_canonical(it)]
    others = sorted(
        (it for it in items if not _is_canonical(it)),
        key=lambda it: (_role_rank(it.role), it.tier, it.source.ref),
    )
    out = canonical + others
    return out[:max_items]


def _resolve_output_dir(override: str | None) -> Path:
    """Compute the output_dir for this run.

    With no override, use `runs/metformin-001-<UTC>-<rand>` — the random
    suffix eliminates same-second collisions when two invocations land
    in the same UTC second (CI matrix, Up+Enter retries, etc.). The
    operator can pass `--output-dir` to point at a stranded directory
    for re-run after a partial-write crash.
    """
    if override is not None:
        return Path(override).expanduser().resolve()
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    suffix = secrets.token_hex(2)
    return RUNS_DIR / f"metformin-001-{ts}-{suffix}"


async def _run(args: argparse.Namespace) -> int:
    print("=" * 70)
    print("Proof 001 — first end-to-end metformin run")
    print("=" * 70)

    settings = load_settings()
    extract_chain = build_extract_chain(settings)
    judge_chain = build_judge_chain(settings)

    # Validate keys BEFORE the expensive retrieve+bundle phase.
    if not any(spec.api_key for spec in extract_chain):
        print(
            "ERROR: no API keys for fact extraction. Set MIMO_API_KEY "
            "(MiMo primary) or OPENROUTER_API_KEY (Mistral fallback).",
            file=sys.stderr,
        )
        return 2
    if not settings.openrouter_api_key and not settings.mimo_api_key:
        print(
            "ERROR: no API keys for SPAR judges. Set OPENROUTER_API_KEY "
            "(for Gemma judge + Mistral fallback) AND/OR MIMO_API_KEY.",
            file=sys.stderr,
        )
        return 2
    if not settings.openrouter_api_key:
        print(
            "WARN: OPENROUTER_API_KEY not set — Gemma judge AND Mistral "
            "fallback will be skipped; only MiMo will fire in the SPAR "
            "chain. Set OPENROUTER_API_KEY for the full chain.",
            file=sys.stderr,
        )

    pack = load_topic_pack(TOPIC_PACK_PATH)
    print(f"Topic pack: {pack.topic} ({len(pack.aliases)} aliases, "
          f"{len(pack.canonical_trials)} canonical trials)")
    print(f"Mode: {'LIVE retrieve' if args.live else 'fixture replay'}")
    print(f"Trace backend: {os.environ.get('TRACE_BACKEND', 'fixture')}")
    print()

    # Stage 1: corpus
    t0 = time.perf_counter()
    try:
        if args.live:
            sources, abstracts, raw_signals = await _retrieve_live()
        else:
            hits = _load_fixture_hits()
            sources, abstracts, raw_signals = normalize_and_dedup(hits)
    except (FileNotFoundError, json.JSONDecodeError, TypeError) as exc:
        print(f"ERROR: corpus load failed: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return 2
    t_retrieve = time.perf_counter() - t0
    if not sources:
        print("ERROR: zero sources after retrieve+dedup.", file=sys.stderr)
        return 2
    by_adapter = Counter(s.source for s in sources)
    print(f"Retrieve+dedup: {len(sources)} sources in {t_retrieve:.2f}s")
    for adapter, n in sorted(by_adapter.items()):
        print(f"  {adapter:18} {n}")

    # Stage 2: bundle
    items = bundle(
        sources, abstracts,
        topic="metformin", domain="longevity older adults",
        raw_signals=raw_signals,
        topic_pack=pack,
    )
    role_counts = Counter(it.role for it in items)
    print(f"Bundle: {len(items)} items {dict(sorted(role_counts.items()))}")

    # Cost containment with canonical-trial pinning (5.3-fix P1)
    selected = _ranked_for_extraction(items, args.max_items, pack=pack)
    if args.max_items is not None:
        canonical_ids = {trial.id for trial in pack.canonical_trials}
        n_canonical = sum(
            1 for it in selected
            if it.source.nct and it.source.nct in canonical_ids
        )
        print(f"Capped at --max-items={args.max_items}: "
              f"{len(selected)} items going to LLM extraction "
              f"({n_canonical} canonical trials pinned)")

    # Stage 3-7: orchestrator (extract → invariants → compile → trace → SPAR → write)
    output_dir = _resolve_output_dir(args.output_dir)
    submission_id = output_dir.name  # path's leaf doubles as the submission id
    force_overwrite = args.output_dir is not None  # only relevant when reusing a dir
    print(f"\nRunning trust-spine pipeline → {output_dir.relative_to(REPO_ROOT)}")
    print()

    t1 = time.perf_counter()
    try:
        receipts: RunReceipts = await run_proof(
            selected,
            topic="metformin",
            domain="longevity older adults",
            pack=pack,
            output_dir=output_dir,
            submission_id=submission_id,
            extract_chain=extract_chain,
            spar_chain=judge_chain,
            registry=get_trial_registry_client(),
            drug_client=get_drug_alias_client(),
            force_overwrite=force_overwrite,
        )
    except Exception as exc:  # noqa: BLE001 — surface anything in the pipeline
        elapsed = time.perf_counter() - t1
        print(f"PIPELINE FAILED after {elapsed:.1f}s: "
              f"{type(exc).__name__}: {exc}", file=sys.stderr)
        # Exit code 3 — distinct from SPAR rejection (1) and config error (2).
        return 3
    elapsed = time.perf_counter() - t1

    # Summary
    md = json.loads(receipts.run_metadata.read_text())
    cost = json.loads(receipts.cost_log.read_text())
    print("=" * 70)
    print(f"Pipeline completed in {elapsed:.1f}s")
    print(f"  SPAR verdict:        {md['spar_verdict']}")
    print(f"  gate_override:       {md['gate_override']}")
    print(f"  n_items:             {md['n_items']}")
    print(f"  n_accepted_facts:    {md['n_accepted_facts']}")
    print(f"  n_rejections:        {md['n_rejections']}")
    print(f"  n_claims:            {md['n_claims']}")
    print(f"  n_traces:            {md['n_traces']}  ({md['n_failed_traces']} failed)")
    print(f"  total cost USD:      ${cost['total_usd']:.6f}")
    print(f"    extract:           ${cost['extract']['total_usd']:.6f}")
    print(f"    spar:              ${cost['spar']['total_usd']:.6f}")
    print(f"\nReceipts: {receipts.output_dir.relative_to(REPO_ROOT)}/")
    for name in (
        "paper.md", "claim_graph.json", "spar_review.json",
        "citation_traces.json", "evidence_cards.json",
        "fact_extraction_log.json", "cost_log.json", "run_metadata.json",
    ):
        path = receipts.output_dir / name
        size_kb = path.stat().st_size / 1024 if path.exists() else 0
        print(f"  {name:32}  {size_kb:6.1f} KB")
    print("=" * 70)

    # Return code: 0 if accept_*, 1 if reject_* (still produces full audit)
    return 0 if md["spar_verdict"].startswith("accept") else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live", action="store_true",
        help="Hit live PubMed/OpenAlex/EuropePMC/CT.gov adapters "
             "(default: replay captured fixtures).",
    )
    parser.add_argument(
        "--max-items", type=int, default=None,
        help="Cap items sent to the LLM extractor (cost containment). "
             "Canonical trials from the topic_pack are pinned to the "
             "head and never dropped by the cap.",
    )
    parser.add_argument(
        "--output-dir", type=str, default=None,
        help="Override the timestamped run directory. Used to retry "
             "into a stranded output_dir after a crash; force_overwrite "
             "is implied. Default: runs/metformin-001-<UTC>-<rand>/",
    )
    args = parser.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
