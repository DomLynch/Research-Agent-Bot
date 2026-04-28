#!/usr/bin/env python3
"""Day 3 — Opt-in LIVE smoke for the LLM fact-extraction stage.

Loads the captured metformin fixture bundle (so retrieve / sources don't
hit the network — that's covered by `e2e_metformin_smoke.py`) and runs
the Day 3.2c LLM extractor against it with REAL API calls, then feeds
the output through the deterministic compiler. Prints accepted facts
+ rejections + the ClaimGraph thesis pick + a cost summary.

This is the live counterpart to `tests/test_e2e_day3_pipeline.py`,
which uses hand-curated facts to keep CI network-free + key-free.
Run this script after a reviewer round, after a prompt change, or
when you suspect a model regression — it's the only path that
actually exercises the LLM-to-Fact contract end-to-end.

Requires (extractor falls back through chain if some are missing):
  MIMO_API_KEY      — primary
  OPENROUTER_API_KEY — fallback for Mistral

Cost budget: ~$0.001-$0.003 per metformin run (depends on how many
published_results items the bundle surfaces — typically 6-10).

Usage:
    python -m scripts.e2e_day3_pipeline
    python -m scripts.e2e_day3_pipeline --max-items 3   # cheaper
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from agent.compiler import compile_claim_graph, compile_claims
from agent.evidence_cards import bundle
from agent.fact_extractor import extract_facts_from_bundle
from agent.llm_client import CostLedger, build_extract_chain
from agent.retrieve import normalize_and_dedup
from agent.settings import load_settings
from agent.topic_pack import TopicPack, load_topic_pack
from agent.types import EvidenceItem, RawHit

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "metformin"
TOPIC_PACK = ROOT / "topic_packs" / "metformin.toml"
ADAPTER_PRIORITY = ("pubmed", "openalex", "europepmc", "clinicaltrials")


def _load_bundle() -> tuple[list[EvidenceItem], TopicPack]:
    """Replay the captured metformin fixtures through Day 2 (deterministic).

    No network for the retrieve/dedup/bundle stages — those are covered
    by separate smokes. This script's job is the LLM stage.
    """
    pack = load_topic_pack(TOPIC_PACK)
    hits: list[RawHit] = []
    for adapter in ADAPTER_PRIORITY:
        for entry in json.loads((FIXTURES / f"{adapter}.json").read_text()):
            hits.append(RawHit(**entry))
    sources, abstracts, raw_signals = normalize_and_dedup(hits)
    items = bundle(
        sources, abstracts,
        topic="metformin", domain="longevity older adults",
        raw_signals=raw_signals, topic_pack=pack,
    )
    return items, pack


def _filter_for_extraction(items: list[EvidenceItem], max_items: int | None) -> list[EvidenceItem]:
    """Restrict to items the LLM extractor will actually process.

    `extract_facts_from_item` skips off_domain pre-call. published_results
    + protocol-role + review + mechanistic all run. To keep cost bounded
    in a smoke test, optionally cap at N items, prioritizing
    published_results (the most informative).
    """
    extractable = [it for it in items if it.role != "off_domain"]
    if max_items is None:
        return extractable
    by_role_priority = sorted(
        extractable,
        key=lambda it: (
            0 if it.role == "published_results"
            else 1 if it.role in ("published_protocol", "registered_pending")
            else 2 if it.role == "review"
            else 3,
            it.tier,  # A1 < A2 < B < C lexical
            it.source.ref,
        ),
    )
    return by_role_priority[:max_items]


async def _run(max_items: int | None) -> int:
    print("=" * 70)
    print("Day 3 LIVE smoke — LLM fact extraction → ClaimGraph compile")
    print("=" * 70)

    settings = load_settings()
    chain = build_extract_chain(settings)
    if not any(spec.api_key for spec in chain):
        print(
            "ERROR: no API keys set. Need MIMO_API_KEY or OPENROUTER_API_KEY.",
            file=sys.stderr,
        )
        return 2

    items, pack = _load_bundle()
    print(f"loaded bundle:        {len(items)} items")

    selected = _filter_for_extraction(items, max_items)
    role_counts = Counter(it.role for it in selected)
    print(f"extractable selected: {len(selected)} ({dict(role_counts)})")
    if max_items is not None:
        print(f"  (capped at --max-items={max_items} for cost containment)")
    print()

    ledger = CostLedger()
    accepted, rejected = await extract_facts_from_bundle(
        selected, pack=pack, chain=chain, ledger=ledger,
    )

    print(f"accepted facts: {len(accepted)}")
    print(f"rejections:     {len(rejected)}")
    print()

    if accepted:
        print("--- ACCEPTED ---")
        for f in accepted[:10]:
            est = f"  estimate={f.estimate!r}" if f.estimate else ""
            pv = f"  p={f.p_value!r}" if f.p_value else ""
            print(f"  ref={f.ref} kind={f.kind}: {f.claim[:120]!r}{est}{pv}")
        if len(accepted) > 10:
            print(f"  ... +{len(accepted) - 10} more")
        print()

    if rejected:
        print("--- REJECTED (sample) ---")
        reason_counts: Counter[str] = Counter(r.reason for r in rejected)
        for reason, count in reason_counts.most_common():
            print(f"  {reason}: {count}")
        print()

    # Compile ClaimGraph from accepted facts
    if accepted:
        try:
            claims = compile_claims(accepted, items)
            graph = compile_claim_graph(claims)
            print(f"compiled ClaimGraph: {len(claims)} claims; thesis={graph.thesis_claim_id}")
        except Exception as exc:  # noqa: BLE001 — surface anything that breaks
            print(f"compile FAILED: {type(exc).__name__}: {exc}")

    cost = ledger.to_dict()
    print()
    print("--- COST ---")
    print(f"total: ${cost['total_usd']:.6f}")
    print(f"by model: {cost['by_model']}")
    print(f"calls: {len(cost['calls'])}")

    # Save baseline
    out_dir = ROOT / "runs"
    out_dir.mkdir(exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    out_path = out_dir / f"day3-baseline-{ts}.json"
    out_path.write_text(json.dumps({
        "timestamp": ts,
        "n_items_selected": len(selected),
        "n_accepted_facts": len(accepted),
        "n_rejected": len(rejected),
        "rejection_reasons": dict(Counter(r.reason for r in rejected)),
        "cost": cost,
        "thesis_claim_id": (graph.thesis_claim_id if accepted else None),
    }, indent=2))
    print(f"\nbaseline saved to: {out_path.relative_to(ROOT)}")
    print("=" * 70)
    return 0 if accepted else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--max-items", type=int, default=None,
        help="Cap items sent to the LLM (cheaper; default: all extractable).",
    )
    args = parser.parse_args()
    return asyncio.run(_run(args.max_items))


if __name__ == "__main__":
    sys.exit(main())
