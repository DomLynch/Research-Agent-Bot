#!/usr/bin/env python3
"""End-to-end fixture/live proof runner for configured research topics."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import dataclasses

from agent.citation_trace import registry_ids_for
from agent.evidence_cards import bundle
from agent.llm_client import CostLedger, build_extract_chain, build_judge_chain
from agent.orchestrator import RunReceipts, run_proof, run_proof_multi_receipt
from agent.retrieve import normalize_and_dedup, retrieve
from agent.settings import load_settings
from agent.sources._base import SourceClient
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
from agent.synthesis_writer import filter_accepted
from agent.synthesis_audit import (
    DAY10_SCORE_FLOOR,
    Q_LOAD_BEARING_IDS,
    audit_synthesis_paper,
)
from agent.synthesis_schemas import (
    ReceiptSummary,
    SynthesisPaper,
    assert_synthesis_invariants,
)
from agent.paper_writer import render_full_paper
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
    """Retrieve broadly plus one focused query per canonical trial."""
    sources_clients: list[SourceClient] = [
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
    """The item cap cannot retain every canonical trial."""


def _ranked_for_extraction(
    items: list[EvidenceItem],
    max_items: int | None,
    *,
    pack: TopicPack,
) -> list[EvidenceItem]:
    """Cap by canonical pin, role, tier, then source reference."""
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
    """Render repo paths relatively and external paths absolutely."""
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


# --- Best-of-N helpers (Day 9.2) -----------------------------------------
#
# At MiniMax temperature 0 the trust spine is principled but not deterministic
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
    """Rank attempts by verdict, gate status, trace failures, and depth."""
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
    """Resolve an override or create a collision-resistant run path."""
    if override is not None:
        return Path(override).expanduser().resolve()
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=f"{topic}-{proof}-{ts}-", dir=RUNS_DIR))


async def _run(args: argparse.Namespace) -> int:
    cfg = _TOPIC_CONFIG[args.topic]
    topic_pack_path = REPO_ROOT / "topic_packs" / cfg["pack"]
    # Day 10.13 — `--canonical-corpus` swaps the noisy 40-source fixture
    # for the predeclared 7-paper Quality Reference Corpus
    # (`tests/fixtures/<topic>_canonical/`). The corpus is committed
    # ahead of any run; SPAR fates of all 7 papers are reported, no
    # papers are added or removed after the fact.
    if args.canonical_corpus:
        fixtures_dir = REPO_ROOT / "tests" / "fixtures" / f"{args.topic}_canonical"
        if not fixtures_dir.exists():
            print(
                f"ERROR: --canonical-corpus requested but no canonical "
                f"fixture exists at {fixtures_dir}. Run the canonical "
                f"fetcher to populate it (see "
                f"docs/quality-reference/{args.topic}/README.md).",
                file=sys.stderr,
            )
            return 2
    else:
        fixtures_dir = REPO_ROOT / "tests" / "fixtures" / cfg["fixtures"]
    proof = cfg["proof"]
    domain = cfg["domain"]
    criteria = cfg["criteria"]

    print("=" * 70)
    print(f"Proof {proof} — end-to-end {args.topic} run")
    print("=" * 70)

    pack = load_topic_pack(topic_pack_path)
    print(f"Topic pack: {pack.topic} ({len(pack.aliases)} aliases, "
          f"{len(pack.canonical_trials)} canonical trials)")
    print(f"Mode: {'LIVE retrieve' if args.live else 'fixture replay'}")
    print(f"Trace backend: {os.environ.get('TRACE_BACKEND', 'fixture')}")
    print()

    if not args.retrieve_only:
        settings = load_settings()
        extract_chain = build_extract_chain(settings)
        judge_chain = build_judge_chain(settings)
        if not any(spec.api_key for spec in extract_chain):
            print("ERROR: no API keys for fact extraction.", file=sys.stderr)
            return 2
        if not settings.openrouter_api_key and not settings.minimax_api_key:
            print("ERROR: no API keys for SPAR judges.", file=sys.stderr)
            return 2
        if not settings.openrouter_api_key:
            print("WARN: only MiniMax will run in the SPAR chain.", file=sys.stderr)

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
    t1 = time.perf_counter()
    items = bundle(
        sources, abstracts,
        topic=args.topic, domain=domain,
        raw_signals=raw_signals,
        topic_pack=pack,
    )
    t_bundle = time.perf_counter() - t1
    role_counts = Counter(it.role for it in items)
    print(f"Bundle: {len(items)} items {dict(sorted(role_counts.items()))}")
    if args.retrieve_only:
        canonical_hits = []
        for trial in pack.canonical_trials:
            match = next((item for item in items if trial.id.upper() in registry_ids_for(item)), None)
            if match is not None:
                canonical_hits.append({
                    "id": trial.id, "name": trial.name,
                    "role": match.role, "tier": match.tier,
                })
        baseline_dir = RUNS_DIR / "e2e-baselines"
        baseline_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        payload = {
            "topic": args.topic,
            "domain": domain,
            "criteria": criteria,
            "captured_at_utc": stamp,
            "n_sources": len(sources),
            "by_adapter": dict(by_adapter),
            "role_distribution": dict(role_counts),
            "tier_distribution": dict(Counter(it.tier for it in items)),
            "direct_count": sum(it.direct for it in items),
            "strict_count": sum(it.strict for it in items),
            "perf_sec": {"retrieve": t_retrieve, "bundle": t_bundle},
            "canonical_hits": canonical_hits,
            "sources": [dataclasses.asdict(source) for source in sources],
        }
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", delete=False, dir=baseline_dir,
            prefix=f"{args.topic}-{stamp}-", suffix=".json",
        ) as handle:
            json.dump(payload, handle, indent=2, default=str)
            baseline_path = Path(handle.name)
        print(f"Baseline: {_format_path(baseline_path)}")
        if len(sources) < args.min_sources:
            print(
                f"ERROR: retrieved {len(sources)} sources; floor is {args.min_sources}.",
                file=sys.stderr,
            )
            return 1
        return 0

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

    # Day 10.8b: multi-receipt mode short-circuits the best-of loop —
    # one extract, then one receipt per cohesive cluster. Output dir is
    # always a fresh timestamped <topic>-multi-001-... so callers don't
    # accidentally clobber a single-receipt run with a multi-receipt one.
    if args.multi_receipt:
        return await _run_multi_receipt(
            args, selected,
            domain=domain, pack=pack,
            extract_chain=extract_chain, judge_chain=judge_chain,
        )

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


# --- Day 10.8b multi-receipt flow -----------------------------------------


async def _run_multi_receipt(
    args: argparse.Namespace,
    selected: list,
    *,
    domain: str,
    pack: TopicPack,
    extract_chain,
    judge_chain,
) -> int:
    """Day 10.8b multi-receipt mode: one extract, N per-cluster receipts.

    The synthesis layer's cross-source ≥3-unique-trials gate cannot
    trip on a single-receipt run because the compiler picks ONE cluster.
    Multi-receipt mode iterates clusters, producing one receipt set per
    cluster under cluster_NN/ subdirs of a single parent run dir.
    """
    proof = "multi-001"
    override = args.output_dir
    output_dir = _resolve_output_dir(override, topic=args.topic, proof=proof)
    submission_id = output_dir.name
    force_overwrite = override is not None

    print()
    print("=" * 70)
    print(f"Multi-receipt mode → {_format_path(output_dir)}")
    if args.max_clusters is not None:
        print(f"  --max-clusters cap: {args.max_clusters}")
    print("=" * 70)

    t1 = time.perf_counter()
    try:
        per_cluster: tuple[RunReceipts, ...] = await run_proof_multi_receipt(
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
            seed=args.seed,
            max_clusters=args.max_clusters,
        )
    except Exception as exc:  # noqa: BLE001
        elapsed = time.perf_counter() - t1
        print(
            f"ERROR: multi-receipt run failed after {elapsed:.1f}s: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 3

    elapsed = time.perf_counter() - t1
    print(f"\nEmitted {len(per_cluster)} cluster receipts in {elapsed:.1f}s")
    accepted = 0
    for paths in per_cluster:
        md = json.loads(paths.run_metadata.read_text())
        verdict = md["spar_verdict"]
        if verdict.startswith("accept"):
            accepted += 1
        print(
            f"  {paths.output_dir.name}: verdict={verdict} "
            f"claims={md['n_claims']} "
            f"failed_traces={md['n_failed_traces']}"
        )
    if per_cluster:
        last_cost = json.loads(per_cluster[-1].cost_log.read_text())
        print(
            f"\nTotal cost (extract + all SPAR): "
            f"${last_cost['total_usd']:.6f}"
        )
    print(
        f"\nNext step: synthesize across these {accepted} accepted "
        f"receipts:\n"
        f"  python -m scripts.e2e_metformin_proof_001 "
        f"--synthesize {output_dir} --topic {args.topic}"
    )
    print("=" * 70)
    return 0 if accepted >= MIN_UNIQUE_TRIALS_FOR_SYNTHESIS else 1


# --- Day 10 synthesis flow -------------------------------------------------


def _discover_receipt_dirs(root: Path) -> list[Path]:
    """Find child directories containing the required receipt files."""
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
    """Aggregate claim receipts into an audited synthesis paper."""
    print("=" * 70)
    print("Day 10 — Synthesis paper engine")
    print("=" * 70)

    settings = load_settings()
    judge_chain = build_judge_chain(settings)
    if not any(spec.api_key for spec in judge_chain):
        print(
            "ERROR: no API keys for synthesis LLM calls. Set MINIMAX_API_KEY "
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

    # Day 10.10 reviewer P1 — TRUST-SPINE ORDERING:
    # SPAR is the gate. The cross-source synthesis count must be
    # computed over the SPAR-ACCEPTED slice only. SPAR-rejected
    # receipts will be quarantined in a transparency section but
    # cannot contribute to the cross-source gate count or to the
    # thesis tournament's input.
    accepted_deduped = list(filter_accepted(deduped))
    n_rejected = len(deduped) - len(accepted_deduped)
    print(f"SPAR adjudication: {len(accepted_deduped)} accepted, "
          f"{n_rejected} rejected (rejected receipts will be quarantined, "
          f"not cited as evidence)")

    # Cross-source gate counts unique trials AMONG ACCEPTED RECEIPTS only.
    unique_trial_count = count_unique_trials(accepted_deduped)
    print(f"Unique canonical trials/sources in ACCEPTED corpus: "
          f"{unique_trial_count}")
    if unique_trial_count < MIN_UNIQUE_TRIALS_FOR_SYNTHESIS:
        print(
            f"\nERROR: ACCEPTED corpus has {unique_trial_count} unique "
            f"canonical trial(s)/source(s); cross-source synthesis "
            f"requires ≥{MIN_UNIQUE_TRIALS_FOR_SYNTHESIS}. "
            f"({len(deduped)} deduped receipts total, "
            f"{n_rejected} rejected by SPAR.) "
            f"Day 10.10 trust-spine ordering: synthesis cannot run "
            f"on a corpus where SPAR rejected most receipts. To proceed, "
            f"either (a) re-run the receipt pipeline with --best-of N to "
            f"raise the SPAR pass rate, (b) curate a richer corpus, or "
            f"(c) accept that this corpus does not support cross-source "
            f"synthesis.",
            file=sys.stderr,
        )
        return 2
    # Hand the accepted set forward to thesis tournament + writer.
    # The full deduped set is still passed to evidence_summary, SPAR
    # adjudication, references, and the rejected_evidence quarantine
    # section so audit transparency is preserved.
    full_deduped = tuple(deduped)
    summaries = accepted_deduped

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
        # Thesis tournament sees ACCEPTED receipts only (trust-spine).
        thesis = await synthesize_thesis(
            summaries, matrix,
            chain=judge_chain, topic=topic,
            ledger=synthesis_ledger, seed=args.seed,
        )
        print(f"\nThesis: {thesis.text}")
        print(f"  picker: {thesis.picker_rationale}")

        # Renderer sees the FULL deduped corpus so the evidence_summary
        # table, SPAR adjudication, references, and the rejected_evidence
        # quarantine section can list every receipt for transparency.
        # Internally render_synthesis_paper applies filter_accepted to
        # the thesis-aligned sections (tensions / synthesis / limitations
        # / direct_evidence / indirect_evidence) per Day 10.10
        # trust-spine ordering.
        paper = await render_synthesis_paper(
            full_deduped, matrix, thesis,
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

    # Day 10.16 — render the FULL PAPER alongside the brief. The brief
    # is the structured-evidence layer (auditable, anchored bullets);
    # the full paper is the publishable artifact (5-15k words,
    # multi-section, tiered validation per section). Both written
    # to the same submission directory so reviewers can see the
    # evidence layer underneath the prose.
    full_paper_md, full_paper_sections = await render_full_paper(
        # Pass the FULL deduped corpus (accepted + rejected) so the
        # references_full section can list everything and the
        # quarantined-discussion path in Limitations sees the rejected
        # set. The renderer applies filter_accepted internally for the
        # ANCHORED LLM sections per Day 10.10 trust-spine ordering.
        full_deduped, matrix, thesis,
        topic=topic, submission_id=submission_id,
        chain=judge_chain, ledger=synthesis_ledger, seed=args.seed,
    )

    # Day 10.17 Fix B — claim-strength repair pass. Scans the full
    # paper for sentences citing tier-C / mechanistic receipts that
    # use causal verbs without an epistemic hedge, and prepends
    # "Evidence suggests that " to each violation. Every repair is
    # logged for audit trail. Anti-gaming: Q11 ship-blocks if repair
    # count exceeds the threshold (default 8), so the system can fix
    # small numbers of violations but cannot launder a wholly-
    # overclaimed paper.
    from agent.paper_writer_claim_repair import repair_claim_strength
    accepted_for_repair = list(filter_accepted(full_deduped))
    full_paper_md, repair_log = repair_claim_strength(
        full_paper_md, accepted_for_repair,
    )
    print(f"Claim-strength repair: {len(repair_log)} sentence(s) repaired")

    # Stage 5: audit. Day 10.17 Phase 1.5 — audit the FULL PAPER body
    # with the FULL CORPUS (accepted + rejected). The brief audit was
    # missing two things:
    #   (1) Q1/Q5/Q7/Q8/Q9/Q10 scan body_md but the brief body is much
    #       smaller than the full paper, so overclaim / typo / leakage
    #       in full_paper.md slipped through unnoticed.
    #   (2) Q8 (rejected-evidence leakage) needs rejected receipts to
    #       know what to flag — the brief audit was passed only
    #       accepted summaries so Q8 always N/A'd.
    # The hybrid audit_target keeps the brief's structured sections
    # (Q3 needs them for the synthesis-section anchor check) but
    # routes body scans to the full paper.
    audit_target = SynthesisPaper(
        submission_id=paper.submission_id,
        topic=paper.topic,
        thesis=paper.thesis,
        matrix=paper.matrix,
        sections=paper.sections,  # brief sections — Q3 anchor check
        body_md=full_paper_md,    # full paper — Q1/Q5/Q7/Q8/Q9/Q10 scan
        render_version=paper.render_version,
    )
    audit = audit_synthesis_paper(audit_target, full_deduped)

    # Stage 6: write all artifacts atomically
    paper_path = output_dir / "paper_synthesis.md"
    paper_path.write_text(paper.body_md, encoding="utf-8")
    full_paper_path = output_dir / "full_paper.md"
    full_paper_path.write_text(full_paper_md, encoding="utf-8")
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
    # Day 10.17 Fix B — save the repair log so reviewers can audit
    # every sentence the deterministic pass mutated. Empty list when
    # no repairs were needed.
    (output_dir / "claim_strength_repairs.json").write_text(
        json.dumps(
            [dataclasses.asdict(r) for r in repair_log], indent=2,
        ), encoding="utf-8",
    )
    # Day 10.9 reviewer P2: surface the cross-source proof fields so a
    # reviewer can verify the gate from this artifact alone, without
    # recomputing from receipt_summaries.json.
    canonical_ncts = sorted({
        s.canonical_trial_id.upper()
        for s in summaries if s.canonical_trial_id
    })
    n_untrialed = sum(1 for s in summaries if not s.canonical_trial_id)
    n_unique_source_units = count_unique_trials(summaries)
    rejected_thesis = [
        {
            "text": c.text[:160],
            "n_receipts_referenced": len(c.receipt_ids_referenced),
            "n_tensions_addressed": len(c.tensions_addressed),
        }
        for c in thesis.rejected_candidates
    ]
    (output_dir / "synthesis_metadata.json").write_text(
        json.dumps({
            "submission_id": submission_id,
            "topic": topic,
            "n_receipts": len(summaries),
            "n_unique_source_units": n_unique_source_units,
            "n_unique_canonical_trials": len(canonical_ncts),
            "canonical_trial_ids": canonical_ncts,
            "n_untrialed_sources": n_untrialed,
            "n_non_orthogonal_tensions": len(non_orth),
            "thesis_text": thesis.text,
            "thesis_picker_rationale": thesis.picker_rationale,
            "n_rejected_thesis_candidates": len(rejected_thesis),
            "rejected_thesis_candidates": rejected_thesis,
            "audit_score": audit.score,
            "audit_notes": audit.notes,
            "n_claim_strength_repairs": len(repair_log),
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
    full_paper_words = len(full_paper_md.split())
    print(f"  full_paper:         {full_paper_words:,} words "
          f"({full_paper_words // 250} pages-ish)")
    print(f"\nReceipts: {_format_path(output_dir)}/")
    for name in (
        "paper_synthesis.md", "full_paper.md",
        "synthesis_quality_audit.json",
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
        "--retrieve-only", action="store_true",
        help="Run the live adapter+bundle smoke without LLM credentials.",
    )
    parser.add_argument(
        "--min-sources", type=int, default=12,
        help="Minimum deduplicated sources required by --retrieve-only.",
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
             "temperature 0 + same seed + same prompt, MiniMax + OpenRouter "
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
        "--canonical-corpus", action="store_true",
        help="Day 10.13 — load ONLY the predeclared 7-paper Quality "
             "Reference Corpus from tests/fixtures/<topic>_canonical/ "
             "(skip the noisy 40-source retrieval). Implements the "
             "reviewer's predeclared-benchmark discipline: corpus is "
             "fixed before the run; SPAR fates of all 7 papers are "
             "reported transparently. Mutually exclusive with --live.",
    )
    parser.add_argument(
        "--multi-receipt", action="store_true",
        help="Day 10.8b multi-receipt mode: extract facts ONCE, then "
             "fan out per cohesive cluster — emit one Proof 001 receipt "
             "set per cluster under runs/<topic>-multi-001-<UTC>/cluster_NN/. "
             "Produces a multi_receipt_manifest.json. The synthesis layer "
             "(--synthesize) can then point at the parent dir and consume "
             "N independent receipts, finally letting the cross-source "
             "≥3-unique-trials gate fire on a single corpus run. "
             "Mutually exclusive with --best-of and --synthesize.",
    )
    parser.add_argument(
        "--max-clusters", type=int, default=None,
        help="With --multi-receipt: cap the number of cluster receipts "
             "emitted to the top-N (best-first by canonical/directness/"
             "tier/size). Default: emit all clusters.",
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
    if args.retrieve_only and not args.live:
        print("ERROR: --retrieve-only requires --live.", file=sys.stderr)
        return 2
    if args.canonical_corpus and args.live:
        print(
            "ERROR: --canonical-corpus and --live are mutually exclusive. "
            "Canonical corpus is a fixed, predeclared fixture; live mode "
            "retrieves dynamically. Pick one.",
            file=sys.stderr,
        )
        return 2
    if args.synthesize and args.multi_receipt:
        print(
            "ERROR: --synthesize and --multi-receipt are mutually exclusive. "
            "Multi-receipt is the producer (emits N receipts); synthesize "
            "is the consumer (loads N receipts). Run them as two steps.",
            file=sys.stderr,
        )
        return 2
    if args.multi_receipt and args.best_of != 1:
        print(
            "ERROR: --multi-receipt and --best-of are mutually exclusive. "
            "Multi-receipt fans out per cluster; best-of fans out per "
            "attempt. Pick one.",
            file=sys.stderr,
        )
        return 2
    if args.synthesize:
        return asyncio.run(_run_synthesize(args))
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
