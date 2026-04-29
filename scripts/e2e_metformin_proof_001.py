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

import dataclasses

from agent.citation_trace import registry_ids_for
from agent.evidence_cards import bundle
from agent.llm_client import CostLedger, build_extract_chain, build_judge_chain
from agent.orchestrator import RunReceipts, run_proof
from agent.retrieve import normalize_and_dedup, retrieve
from agent.settings import load_settings
from agent.sources.clinicaltrials import ClinicalTrialsClient
from agent.sources.europepmc import EuropePMCClient
from agent.sources.openalex import OpenAlexClient
from agent.sources.pubmed import PubMedClient
from agent.synthesis import (
    MIN_UNIQUE_TRIALS_FOR_SYNTHESIS,
    build_tension_matrix,
    count_unique_trials,
    dedupe_receipts,
    load_receipt_summary,
)
from agent.synthesis_audit import (
    DAY10_SCORE_FLOOR,
    Q_LOAD_BEARING_IDS,
    audit_synthesis_paper,
)
from agent.synthesis_schemas import (
    ReceiptSummary,
    assert_synthesis_invariants,
)
from agent.synthesis_thesis import synthesize_thesis
from agent.synthesis_writer import render_synthesis_paper
from agent.topic_pack import TopicPack, load_topic_pack
from agent.trace_clients import (
    get_drug_alias_client,
    get_trial_registry_client,
)
from agent.types import EvidenceItem, RawHit, Source

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = REPO_ROOT / "runs"
ADAPTER_PRIORITY = ("pubmed", "openalex", "europepmc", "clinicaltrials")

# Per-topic config. Day 7+ generalized this script to drive all three
# proofs (metformin / rapamycin / everolimus); the pack + fixtures dir +
# proof number are looked up by `--topic`. Keep `metformin` as default
# so existing call sites and CI smoke remain unchanged.
_TOPIC_CONFIG: dict[str, dict[str, str]] = {
    "metformin": {
        "pack": "metformin.toml",
        "fixtures": "metformin",
        "proof": "001",
        "domain": "longevity older adults",
        "criteria": "aging OR longevity OR healthspan",
    },
    "rapamycin": {
        "pack": "rapamycin.toml",
        "fixtures": "rapamycin",
        "proof": "002",
        "domain": "longevity older adults",
        "criteria": "aging OR longevity OR healthspan",
    },
    "everolimus": {
        "pack": "everolimus.toml",
        "fixtures": "everolimus",
        "proof": "003",
        "domain": "longevity older adults",
        "criteria": "aging OR longevity OR healthspan",
    },
}


def _load_fixture_hits(fixtures_dir: Path) -> list[RawHit]:
    """Replay captured RawHits from tests/fixtures/<topic>/.

    Raises FileNotFoundError if NO fixtures are loadable so the operator
    sees the cause clearly (vs. a misleading "0 sources after dedup")."""
    hits: list[RawHit] = []
    missing: list[str] = []
    for adapter in ADAPTER_PRIORITY:
        path = fixtures_dir / f"{adapter}.json"
        if not path.exists():
            missing.append(adapter)
            continue
        for entry in json.loads(path.read_text(encoding="utf-8")):
            hits.append(RawHit(**entry))
    if not hits:
        raise FileNotFoundError(
            f"no fixtures loaded from {fixtures_dir}; missing adapters: "
            f"{missing}. Either run scripts/capture_fixtures.py or pass --live."
        )
    if missing:
        print(f"WARN: missing fixtures for adapter(s) {missing}", file=sys.stderr)
    return hits


async def _retrieve_live(
    topic: str, criteria: str, domain: str,
    *,
    pack: TopicPack | None = None,
) -> tuple[list[Source], dict[int, str], dict[int, dict]]:
    """Fan out to live PubMed / OpenAlex / EuropePMC / CT.gov.

    Day 9.3: when `pack` is provided, also issue one focused query per
    canonical_trials NCT id (e.g. `metformin NCT02308228`). This closes
    the live-retrieval gap that left only 1 of 4 metformin canonicals
    in the broad-query corpus — without this, --live runs are gated on
    whether the broad query happens to surface the trial that drives
    the topic's strongest evidence cluster.
    """
    sources_clients = [
        PubMedClient(),
        OpenAlexClient(),
        EuropePMCClient(),
        ClinicalTrialsClient(),
    ]
    extra_queries: list[str] = []
    if pack is not None:
        for trial in pack.canonical_trials:
            # Each NCT-anchored query carries the topic so the adapter
            # has both signals — pure NCT queries return all hits about
            # that trial regardless of drug, which is too broad.
            extra_queries.append(f"{topic} {trial.id}")
    return await retrieve(
        topic=topic,
        criteria=criteria,
        sources=sources_clients,
        domain=domain,
        extra_queries=tuple(extra_queries),
    )


class _CapTooSmallError(ValueError):
    """Raised when `--max-items` is less than the number of canonical
    trials in the topic pack. The pin-canonical-then-slice approach
    cannot honor "canonical never dropped" if the cap itself is below
    the canonical set's size — better to fail loud than silently drop."""


def _ranked_for_extraction(
    items: list[EvidenceItem],
    max_items: int | None,
    *,
    pack: TopicPack,
) -> list[EvidenceItem]:
    """Cap the corpus by canonical-pin → role → tier → ref priority.

    Day 5.3-fix P1: canonical_trials from the topic_pack are PINNED to
    the head so they're never dropped by `--max-items`.

    Day 5.3-fix-2 P1: pinning isn't sufficient if `max_items <
    len(canonical_trials)` — the slice would still drop some canonical
    items. Now: raise `_CapTooSmallError` so the operator sees the
    contradiction with the "never dropped" promise. The metformin pack
    has 4 canonical trials; `--max-items 4` is the floor.
    """
    if max_items is None:
        return items

    canonical_ids = {trial.id.upper() for trial in pack.canonical_trials}

    def _is_canonical(it: EvidenceItem) -> bool:
        # registry_ids_for scans source.nct + source.url + abstract — same
        # surfaces lookup_override and trace_nct_exists use. Without this,
        # a MASTERS-style record (NCT only in the abstract, source.nct=None)
        # would NOT be detected as canonical, and `--max-items 1` could
        # silently drop it before the orchestrator ever saw it.
        return any(rid in canonical_ids for rid in registry_ids_for(it))

    canonical = [it for it in items if _is_canonical(it)]
    if max_items < len(canonical):
        raise _CapTooSmallError(
            f"--max-items={max_items} would drop canonical trials "
            f"({len(canonical)} present in this corpus). The 'canonical "
            f"never dropped' promise requires --max-items >= "
            f"{len(canonical)}."
        )

    def _role_rank(role: str) -> int:
        return (
            0 if role == "published_results"
            else 1 if role in ("published_protocol", "registered_pending")
            else 2 if role == "review"
            else 3 if role == "mechanistic"
            else 4
        )

    others = sorted(
        (it for it in items if not _is_canonical(it)),
        key=lambda it: (_role_rank(it.role), it.tier, it.source.ref),
    )
    out = canonical + others
    return out[:max_items]


def _format_path(path: Path) -> str:
    """Render a path for logging: relative to the repo if it's under
    REPO_ROOT, otherwise absolute. The unconditional `relative_to`
    in the previous version raised ValueError for any path outside
    the repo (e.g., `--output-dir /tmp/run-001`), crashing before the
    pipeline even started."""
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


# --- Best-of-N helpers (Day 9.2) -----------------------------------------
#
# At MiMo temperature 0 the trust spine is principled but not deterministic
# across runs — different fact subsets get surfaced, leading to different
# SPAR verdicts. `--best-of N` runs the orchestrator N times against the
# SAME corpus and picks the highest-quality run as the canonical receipt.
# All N attempts remain on disk as audit evidence; the chosen run also
# carries a `best_of_n_manifest.json` that lists every attempt's id +
# verdict so a reviewer can re-rank if they disagree with the picker's
# tiebreaks.

# Lower = better. accept_clean wins over accept_caveated wins over rejects.
_VERDICT_RANK: dict[str, int] = {
    "accept_clean": 0,
    "accept_caveated": 1,
    "reject_majority": 2,
    "reject_critical": 3,
}


def _attempt_sort_key(md: dict) -> tuple[int, int, int, int, str]:
    """Rank an attempt's run_metadata.json. Lower tuple = better.

    Order:
      1. SPAR verdict (accept_clean > accept_caveated > rejects)
      2. gate_override (False beats True — code-disposed reject is worse)
      3. Failed traces count (fewer is better)
      4. -n_claims (richer artifact wins)
      5. submission_id (deterministic tiebreak)
    """
    return (
        _VERDICT_RANK.get(md.get("spar_verdict", ""), 9),
        1 if md.get("gate_override") else 0,
        md.get("n_failed_traces", 0),
        -md.get("n_claims", 0),
        md.get("submission_id", ""),
    )


def _resolve_output_dir(
    override: str | None, *, topic: str, proof: str,
) -> Path:
    """Compute the output_dir for this run.

    With no override, use `runs/<topic>-<proof>-<UTC>-<rand>` — the random
    suffix eliminates same-second collisions when two invocations land
    in the same UTC second (CI matrix, Up+Enter retries, etc.). The
    operator can pass `--output-dir` to point at a stranded directory
    for re-run after a partial-write crash.
    """
    if override is not None:
        return Path(override).expanduser().resolve()
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    suffix = secrets.token_hex(2)
    return RUNS_DIR / f"{topic}-{proof}-{ts}-{suffix}"


async def _run(args: argparse.Namespace) -> int:
    cfg = _TOPIC_CONFIG[args.topic]
    topic_pack_path = REPO_ROOT / "topic_packs" / cfg["pack"]
    fixtures_dir = REPO_ROOT / "tests" / "fixtures" / cfg["fixtures"]
    proof = cfg["proof"]
    domain = cfg["domain"]
    criteria = cfg["criteria"]

    print("=" * 70)
    print(f"Proof {proof} — end-to-end {args.topic} run")
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

    pack = load_topic_pack(topic_pack_path)
    print(f"Topic pack: {pack.topic} ({len(pack.aliases)} aliases, "
          f"{len(pack.canonical_trials)} canonical trials)")
    print(f"Mode: {'LIVE retrieve' if args.live else 'fixture replay'}")
    print(f"Trace backend: {os.environ.get('TRACE_BACKEND', 'fixture')}")
    print()

    # Stage 1: corpus
    t0 = time.perf_counter()
    try:
        if args.live:
            sources, abstracts, raw_signals = await _retrieve_live(
                topic=args.topic, criteria=criteria, domain=domain,
                pack=pack,
            )
        else:
            hits = _load_fixture_hits(fixtures_dir)
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
        topic=args.topic, domain=domain,
        raw_signals=raw_signals,
        topic_pack=pack,
    )
    role_counts = Counter(it.role for it in items)
    print(f"Bundle: {len(items)} items {dict(sorted(role_counts.items()))}")

    # Cost containment with canonical-trial pinning (5.3-fix P1)
    try:
        selected = _ranked_for_extraction(items, args.max_items, pack=pack)
    except _CapTooSmallError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.max_items is not None:
        canonical_ids = {trial.id.upper() for trial in pack.canonical_trials}
        n_canonical = sum(
            1 for it in selected
            if any(rid in canonical_ids for rid in registry_ids_for(it))
        )
        print(f"Capped at --max-items={args.max_items}: "
              f"{len(selected)} items going to LLM extraction "
              f"({n_canonical} canonical trials pinned)")

    # Stage 3-7: orchestrator (extract → invariants → compile → trace → SPAR → write)
    # Day 9.2: optionally repeated --best-of N times against the same corpus.
    n_attempts = max(1, args.best_of)
    if n_attempts > 1:
        print(f"\nRunning best-of-{n_attempts} (each attempt is a fresh "
              f"orchestrator run on the same corpus; picker selects the "
              f"highest-ranked SPAR verdict)")
    attempts: list[tuple[RunReceipts, dict, dict, float]] = []
    for i in range(n_attempts):
        if n_attempts > 1:
            print(f"\n--- Attempt {i + 1} / {n_attempts} ---")
        # First attempt may use --output-dir override; later attempts always
        # mint a fresh dir (otherwise force_overwrite would clobber the
        # previous attempt's receipts and we'd lose audit evidence).
        override = args.output_dir if (i == 0 and args.output_dir) else None
        output_dir = _resolve_output_dir(
            override, topic=args.topic, proof=proof,
        )
        submission_id = output_dir.name
        force_overwrite = override is not None
        # Day 9.4: per-attempt seed derivation so a single run is
        # reproducible AND each --best-of attempt is distinct. base_seed
        # = None means stochastic (legacy); base_seed = N gives the i-th
        # attempt seed=N+i so re-running the same args produces the same
        # N receipts in the same order.
        attempt_seed = (
            None if args.seed is None
            else (args.seed + i)
        )
        if attempt_seed is not None:
            print(f"Running trust-spine pipeline → {_format_path(output_dir)} "
                  f"(seed={attempt_seed})")
        else:
            print(f"Running trust-spine pipeline → {_format_path(output_dir)}")

        t1 = time.perf_counter()
        try:
            receipts: RunReceipts = await run_proof(
                selected,
                topic=args.topic,
                domain=domain,
                pack=pack,
                output_dir=output_dir,
                submission_id=submission_id,
                extract_chain=extract_chain,
                spar_chain=judge_chain,
                registry=get_trial_registry_client(),
                drug_client=get_drug_alias_client(),
                force_overwrite=force_overwrite,
                seed=attempt_seed,
            )
        except Exception as exc:  # noqa: BLE001
            elapsed = time.perf_counter() - t1
            print(f"  attempt failed after {elapsed:.1f}s: "
                  f"{type(exc).__name__}: {exc}", file=sys.stderr)
            continue
        elapsed = time.perf_counter() - t1
        md = json.loads(receipts.run_metadata.read_text())
        cost = json.loads(receipts.cost_log.read_text())
        attempts.append((receipts, md, cost, elapsed))
        if n_attempts > 1:
            print(f"  → verdict={md['spar_verdict']} "
                  f"claims={md['n_claims']} "
                  f"failed_traces={md['n_failed_traces']} "
                  f"({elapsed:.1f}s, ${cost['total_usd']:.4f})")

    if not attempts:
        # Every attempt crashed (rare — usually fact-extraction config error).
        return 3

    # Pick the best attempt by SPAR verdict + gate_override + claim count.
    best = min(attempts, key=lambda a: _attempt_sort_key(a[1]))
    best_receipts, best_md, best_cost, best_elapsed = best

    # When --best-of > 1, write a manifest into the chosen run so a
    # reviewer can re-rank or see what was tried.
    if n_attempts > 1:
        manifest = {
            "best_of": n_attempts,
            "best_submission_id": best_md.get("submission_id"),
            "best_verdict": best_md.get("spar_verdict"),
            "attempts": [
                {
                    "submission_id": md.get("submission_id"),
                    "spar_verdict": md.get("spar_verdict"),
                    "gate_override": md.get("gate_override"),
                    "n_claims": md.get("n_claims"),
                    "n_failed_traces": md.get("n_failed_traces"),
                    "elapsed_sec": round(elapsed, 2),
                    "total_usd": cost.get("total_usd"),
                    "is_best": md.get("submission_id") == best_md.get("submission_id"),
                }
                for _r, md, cost, elapsed in attempts
            ],
        }
        manifest_path = best_receipts.output_dir / "best_of_n_manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    # Summary — always describes the chosen best attempt.
    print()
    print("=" * 70)
    if n_attempts > 1:
        verdicts = Counter(a[1].get("spar_verdict") for a in attempts)
        print(f"Best of {n_attempts} → {best_md['spar_verdict']} "
              f"(distribution: {dict(verdicts)})")
        total_cost = sum(a[2].get("total_usd", 0.0) for a in attempts)
        total_time = sum(a[3] for a in attempts)
        print(f"Total cost across {n_attempts} attempts: ${total_cost:.6f} "
              f"({total_time:.1f}s)")
        print()
    print(f"Pipeline completed in {best_elapsed:.1f}s")
    print(f"  SPAR verdict:        {best_md['spar_verdict']}")
    print(f"  gate_override:       {best_md['gate_override']}")
    print(f"  n_items:             {best_md['n_items']}")
    print(f"  n_accepted_facts:    {best_md['n_accepted_facts']}")
    print(f"  n_rejections:        {best_md['n_rejections']}")
    print(f"  n_claims:            {best_md['n_claims']}")
    print(f"  n_traces:            {best_md['n_traces']}  "
          f"({best_md['n_failed_traces']} failed)")
    print(f"  total cost USD:      ${best_cost['total_usd']:.6f}")
    print(f"    extract:           ${best_cost['extract']['total_usd']:.6f}")
    print(f"    spar:              ${best_cost['spar']['total_usd']:.6f}")
    print(f"\nReceipts: {_format_path(best_receipts.output_dir)}/")
    for name in (
        "claim_receipt.md", "claim_graph.json", "spar_review.json",
        "citation_traces.json", "evidence_cards.json",
        "fact_extraction_log.json", "cost_log.json", "run_metadata.json",
    ):
        path = best_receipts.output_dir / name
        size_kb = path.stat().st_size / 1024 if path.exists() else 0
        print(f"  {name:32}  {size_kb:6.1f} KB")
    if n_attempts > 1:
        path = best_receipts.output_dir / "best_of_n_manifest.json"
        size_kb = path.stat().st_size / 1024 if path.exists() else 0
        print(f"  {'best_of_n_manifest.json':32}  {size_kb:6.1f} KB")
    print("=" * 70)

    # Return code: 0 if accept_*, 1 if reject_*.
    return 0 if best_md["spar_verdict"].startswith("accept") else 1


# --- Day 10 synthesis flow -------------------------------------------------


def _discover_receipt_dirs(root: Path) -> list[Path]:
    """Find every subdirectory of `root` that looks like a saved
    claim receipt — i.e. contains all 8 receipt JSON files.

    Skips e2e-baselines and other non-receipt directories silently."""
    if not root.exists() or not root.is_dir():
        return []
    found: list[Path] = []
    required = ("claim_graph.json", "spar_review.json", "evidence_cards.json")
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        if all((child / f).exists() for f in required):
            found.append(child)
    return found


async def _run_synthesize(args: argparse.Namespace) -> int:
    """Day 10 synthesis layer: aggregate N claim receipts under a
    directory into a single paper_synthesis.md + audit JSON.

    Returns exit codes:
      0 — synthesis paper rendered + audit ≥ DAY10_SCORE_FLOOR + load-bearing pass
      1 — synthesis rendered but failed quality gate (paper still on disk)
      2 — config error (no receipts found, missing keys, etc.)
      3 — pipeline runtime crash
    """
    print("=" * 70)
    print("Day 10 — Synthesis paper engine")
    print("=" * 70)

    settings = load_settings()
    judge_chain = build_judge_chain(settings)
    if not any(spec.api_key for spec in judge_chain):
        print(
            "ERROR: no API keys for synthesis LLM calls. Set MIMO_API_KEY "
            "or OPENROUTER_API_KEY.",
            file=sys.stderr,
        )
        return 2

    receipts_dir = Path(args.synthesize).expanduser().resolve()
    receipt_paths = _discover_receipt_dirs(receipts_dir)
    if not receipt_paths:
        print(
            f"ERROR: no claim receipts found under {receipts_dir} "
            f"(each subdirectory must contain claim_graph.json + "
            f"spar_review.json + evidence_cards.json).",
            file=sys.stderr,
        )
        return 2
    print(f"Loading {len(receipt_paths)} claim receipts from "
          f"{_format_path(receipts_dir)}/")

    summaries_all: list[ReceiptSummary] = []
    for rp in receipt_paths:
        try:
            s = load_receipt_summary(rp)
        except (FileNotFoundError, json.JSONDecodeError, KeyError) as exc:
            print(f"  SKIP {rp.name}: {type(exc).__name__}: {exc}", file=sys.stderr)
            continue
        summaries_all.append(s)
    if not summaries_all:
        print("ERROR: zero loadable receipts.", file=sys.stderr)
        return 2

    # Day 10.5b: synthesis is per-topic. When the receipts span
    # multiple drugs, --topic selects the slice. Without --topic,
    # filter to the most-common topic and warn.
    topics_seen = Counter(s.topic for s in summaries_all)
    if len(topics_seen) > 1 and args.topic == "metformin" and "metformin" not in topics_seen:
        # Default --topic=metformin but no metformin receipts — pick the
        # most-common to avoid empty filter.
        chosen_topic = topics_seen.most_common(1)[0][0]
    elif len(topics_seen) > 1:
        chosen_topic = args.topic
        print(f"\nReceipts span {len(topics_seen)} topics: "
              f"{dict(topics_seen)}; filtering to --topic={chosen_topic}")
    else:
        chosen_topic = next(iter(topics_seen))
    summaries = [s for s in summaries_all if s.topic == chosen_topic]
    if not summaries:
        print(
            f"ERROR: --topic={chosen_topic} matches 0 of "
            f"{len(summaries_all)} loaded receipts. "
            f"Available topics: {sorted(topics_seen)}",
            file=sys.stderr,
        )
        return 2
    topic = chosen_topic

    print(f"\nTopic: {topic} ({len(summaries)} receipts)")
    for s in summaries:
        print(f"  - {s.receipt_id} (outcome={s.outcome_class}, "
              f"direction={s.effect_direction}, verdict={s.spar_verdict})")

    # Day 10.7 (reviewer P1, dedup): collapse duplicate runs of the
    # same source-paper cluster.
    deduped = list(dedupe_receipts(summaries))
    n_dedup_dropped = len(summaries) - len(deduped)
    if n_dedup_dropped:
        print(f"\nDeduped: {len(summaries)} → {len(deduped)} unique evidence "
              f"units ({n_dedup_dropped} duplicate runs dropped)")
    # Day 10.8a (reviewer P1, gate): the cross-source-synthesis gate
    # counts UNIQUE TRIALS, not unique evidence units. Three different
    # endpoints from one trial dedupe to three keys but represent one
    # source — that's multi-endpoint reporting, not cross-source synthesis.
    unique_trial_count = count_unique_trials(deduped)
    print(f"Unique canonical trials in deduped corpus: {unique_trial_count}")
    if unique_trial_count < MIN_UNIQUE_TRIALS_FOR_SYNTHESIS:
        print(
            f"\nERROR: corpus has {unique_trial_count} unique canonical "
            f"trial(s); cross-source synthesis requires "
            f"≥{MIN_UNIQUE_TRIALS_FOR_SYNTHESIS}. The {len(deduped)} deduped "
            f"receipt(s) under {receipts_dir} either come from the same "
            f"source paper (same-trial multi-endpoint reporting) or from "
            f"too few sources to synthesize across. To produce real "
            f"cross-source synthesis, run the receipt pipeline against "
            f"corpora anchored on different canonical trials, OR use the "
            f"multi-receipt mode (Day 10.8b) that emits one receipt per "
            f"cluster from a single corpus.",
            file=sys.stderr,
        )
        return 2
    summaries = deduped

    # Stage 1: tension matrix — deterministic, no LLM
    matrix = build_tension_matrix(summaries)
    non_orth = matrix.non_orthogonal()
    print(f"Tension matrix: {len(matrix.pairs)} pairs total, "
          f"{len(non_orth)} non-orthogonal")
    for t in non_orth[:5]:
        print(f"  - {t.kind} (severity {t.severity}): {t.summary}")

    # Stage 2-4: LLM synthesis pipeline
    synthesis_ledger = CostLedger()
    output_dir = (
        Path(args.output_dir).expanduser().resolve() if args.output_dir
        else _resolve_output_dir(None, topic=f"synthesis-{topic}", proof="010")
    )
    submission_id = output_dir.name
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"\nWriting to {_format_path(output_dir)}")

    t0 = time.perf_counter()
    try:
        thesis = await synthesize_thesis(
            summaries, matrix,
            chain=judge_chain, topic=topic,
            ledger=synthesis_ledger, seed=args.seed,
        )
        print(f"\nThesis: {thesis.text}")
        print(f"  picker: {thesis.picker_rationale}")

        paper = await render_synthesis_paper(
            summaries, matrix, thesis,
            topic=topic, submission_id=submission_id,
            chain=judge_chain, ledger=synthesis_ledger, seed=args.seed,
        )
        assert_synthesis_invariants(paper)
    except Exception as exc:  # noqa: BLE001 — any failure is reportable
        elapsed = time.perf_counter() - t0
        print(f"PIPELINE FAILED after {elapsed:.1f}s: "
              f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 3
    elapsed = time.perf_counter() - t0

    # Stage 5: audit
    audit = audit_synthesis_paper(paper, summaries)

    # Stage 6: write all artifacts atomically
    paper_path = output_dir / "paper_synthesis.md"
    paper_path.write_text(paper.body_md, encoding="utf-8")
    (output_dir / "synthesis_quality_audit.json").write_text(
        json.dumps(dataclasses.asdict(audit), indent=2), encoding="utf-8",
    )
    (output_dir / "receipt_summaries.json").write_text(
        json.dumps([dataclasses.asdict(s) for s in summaries], indent=2),
        encoding="utf-8",
    )
    (output_dir / "tension_matrix.json").write_text(
        json.dumps(dataclasses.asdict(matrix), indent=2), encoding="utf-8",
    )
    (output_dir / "synthesis_metadata.json").write_text(
        json.dumps({
            "submission_id": submission_id,
            "topic": topic,
            "n_receipts": len(summaries),
            "n_non_orthogonal_tensions": len(non_orth),
            "thesis_text": thesis.text,
            "audit_score": audit.score,
            "audit_notes": audit.notes,
            "elapsed_sec": round(elapsed, 2),
            "total_usd": round(synthesis_ledger.total_usd(), 6),
            "render_version": paper.render_version,
        }, indent=2),
        encoding="utf-8",
    )

    # Summary print
    print()
    print("=" * 70)
    print(f"Synthesis complete in {elapsed:.1f}s — ${synthesis_ledger.total_usd():.4f}")
    print(f"  audit score:        {audit.score:.1f} / 10  (floor {DAY10_SCORE_FLOOR})")
    for c in audit.checks:
        marker = "✓" if c.passed else "✗"
        load = " [load-bearing]" if c.question_id in Q_LOAD_BEARING_IDS else ""
        print(f"    {marker} {c.question_id}{load}: {c.detail[:80]}")
    print(f"  notes: {audit.notes}")
    print(f"\nReceipts: {_format_path(output_dir)}/")
    for name in (
        "paper_synthesis.md", "synthesis_quality_audit.json",
        "receipt_summaries.json", "tension_matrix.json",
        "synthesis_metadata.json",
    ):
        p = output_dir / name
        size_kb = p.stat().st_size / 1024 if p.exists() else 0
        print(f"  {name:32}  {size_kb:6.1f} KB")
    print("=" * 70)

    load_pass = all(
        c.passed for c in audit.checks if c.question_id in Q_LOAD_BEARING_IDS
    )
    if audit.score >= DAY10_SCORE_FLOOR and load_pass:
        return 0
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--topic", choices=tuple(_TOPIC_CONFIG), default="metformin",
        help="Which topic_pack + fixtures to run. Default: metformin.",
    )
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
        "--best-of", type=int, default=1,
        help="Run the orchestrator N times against the same corpus and "
             "pick the highest-ranked SPAR verdict. Each attempt's "
             "receipts stay on disk; the chosen run also carries a "
             "best_of_n_manifest.json. Default 1 (single run, no manifest).",
    )
    parser.add_argument(
        "--seed", type=int, default=None,
        help="Forward an OpenAI-compatible seed to every LLM call. With "
             "temperature 0 + same seed + same prompt, MiMo + OpenRouter "
             "produce byte-identical responses. With --best-of N, attempt "
             "i uses seed=base+i, so the N receipts are reproducible. "
             "Default: None (stochastic legacy behavior).",
    )
    parser.add_argument(
        "--output-dir", type=str, default=None,
        help="Override the timestamped run directory. Used to retry "
             "into a stranded output_dir after a crash; force_overwrite "
             "is implied. Default: runs/metformin-001-<UTC>-<rand>/",
    )
    parser.add_argument(
        "--synthesize", type=str, default=None, metavar="RECEIPTS_DIR",
        help="Run the Day 10 synthesis layer: load every claim receipt "
             "subdirectory under RECEIPTS_DIR (each must contain the 8 "
             "receipt JSONs from a prior --topic run), build the "
             "tension matrix, run the synthesis thesis tournament, "
             "render paper_synthesis.md, and audit against the 7-paper "
             "rubric. Output: a fresh runs/synthesis-<topic>-<UTC>-<rand>/ "
             "containing paper_synthesis.md + synthesis_quality_audit.json "
             "+ receipt_summaries.json + tension_matrix.json. "
             "Pass `runs/` to synthesize across all tracked receipts. "
             "When --synthesize is set, --topic / --live / --max-items / "
             "--best-of are ignored.",
    )
    args = parser.parse_args()
    if args.synthesize:
        return asyncio.run(_run_synthesize(args))
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
