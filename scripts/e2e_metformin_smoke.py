"""Day 2.5b — LIVE-API metformin retrieval smoke (opt-in, network-dependent).

Calls real PubMed / OpenAlex / EuropePMC / ClinicalTrials.gov endpoints via
the existing `agent.retrieve.retrieve()` and runs the result through
`agent.evidence_cards.bundle()` with the metformin topic_pack. Saves a
JSON baseline to `runs/e2e-baselines/metformin-<UTC-timestamp>.json` so
future runs can be diffed.

Why a script and not a pytest test:
- Real API responses change daily (papers added, retracted, re-classified).
  A test asserting specific counts would become flaky immediately.
- Pytest CI shouldn't depend on network. The deterministic E2E test
  (tests/test_e2e_metformin.py) replays captured fixtures for that.
- This script is the OPT-IN counterpart: run it manually when you want a
  fresh baseline, fixture refresh, or live-API regression check.

Usage:
    python -m scripts.e2e_metformin_smoke
    python -m scripts.e2e_metformin_smoke --topic rapamycin --domain "longevity older adults"

Exits 0 on success, non-zero if retrieval surfaces fewer than the minimum
sources (default 12 — matches Day 2 done-when criterion).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from agent.evidence_cards import bundle
from agent.retrieve import retrieve
from agent.sources.clinicaltrials import ClinicalTrialsClient
from agent.sources.europepmc import EuropePMCClient
from agent.sources.openalex import OpenAlexClient
from agent.sources.pubmed import PubMedClient
from agent.topic_pack import load_topic_pack

REPO_ROOT = Path(__file__).resolve().parent.parent
TOPIC_PACK_PATH = REPO_ROOT / "topic_packs" / "metformin.toml"
BASELINES_DIR = REPO_ROOT / "runs" / "e2e-baselines"


async def _run_smoke(topic: str, domain: str, criteria: str, min_sources: int) -> int:
    pack = load_topic_pack(TOPIC_PACK_PATH)
    print(f"Topic pack loaded: {pack.topic} (aliases: {len(pack.aliases)}, "
          f"canonical_trials: {len(pack.canonical_trials)})")

    sources_clients = [
        PubMedClient(),
        OpenAlexClient(),
        EuropePMCClient(),
        ClinicalTrialsClient(),
    ]

    print(f"\nFan-out against {len(sources_clients)} live adapters for topic={topic!r}...")
    t0 = time.perf_counter()
    sources, abstracts, raw_signals = await retrieve(
        topic=topic, criteria=criteria,
        sources=sources_clients,
        domain=domain,
    )
    t_retrieve = time.perf_counter() - t0

    if not sources:
        print("ERROR: zero sources retrieved. Check network / API endpoints.",
              file=sys.stderr)
        return 2

    by_adapter = Counter(s.source for s in sources)
    print(f"  retrieved in {t_retrieve:.2f}s — {len(sources)} unique sources")
    for adapter, n in by_adapter.most_common():
        print(f"    {adapter:18}  {n}")

    print("\nClassifying via bundle() with topic_pack override active...")
    t1 = time.perf_counter()
    items = bundle(
        sources, abstracts,
        topic=topic, domain=domain,
        raw_signals=raw_signals,
        topic_pack=pack,
    )
    t_bundle = time.perf_counter() - t1
    print(f"  classified in {t_bundle*1000:.1f} ms")

    role_counts = Counter(it.role for it in items)
    tier_counts = Counter(it.tier for it in items)
    direct = sum(1 for it in items if it.direct)
    strict = sum(1 for it in items if it.strict)

    print(f"\nrole distribution:    {dict(role_counts)}")
    print(f"tier distribution:    {dict(tier_counts)}")
    print(f"direct + strict:      {direct} / {strict}")

    canonical_hits = []
    for trial in pack.canonical_trials:
        match = next((it for it in items if it.source.nct == trial.id
                       or trial.id in (it.abstract or "")), None)
        if match:
            canonical_hits.append((trial.id, trial.name, match.role, match.tier))

    if canonical_hits:
        print(f"\ncanonical NCTs surfaced ({len(canonical_hits)} of {len(pack.canonical_trials)}):")
        for nct_id, name, role, tier in canonical_hits:
            override = pack.lookup_role_override(nct_id)
            pinned = " (pinned via override)" if override and override.role == role else ""
            print(f"  {nct_id:18}  {name:14}  role={role:20} tier={tier}{pinned}")
    else:
        print("\nWARNING: no canonical NCTs surfaced. Topic-pack registry overrides "
              "had nothing to pin. Live API may have changed query semantics.")

    BASELINES_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = BASELINES_DIR / f"{topic}-{ts}.json"
    baseline = {
        "topic": topic,
        "domain": domain,
        "criteria": criteria,
        "captured_at_utc": ts,
        "n_sources": len(sources),
        "by_adapter": dict(by_adapter),
        "role_distribution": dict(role_counts),
        "tier_distribution": dict(tier_counts),
        "direct_count": direct,
        "strict_count": strict,
        "perf_sec": {"retrieve": t_retrieve, "bundle": t_bundle},
        "canonical_hits": [
            {"id": nct_id, "name": name, "role": role, "tier": tier}
            for nct_id, name, role, tier in canonical_hits
        ],
        "sources": [
            {
                "ref": s.ref, "title": s.title, "year": s.year,
                "source": s.source, "doi": s.doi, "pmid": s.pmid,
                "nct": s.nct, "venue": s.venue,
            }
            for s in sources
        ],
    }
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(baseline, fh, indent=2, default=str)
    print(f"\nbaseline written: {out_path.relative_to(REPO_ROOT)}")

    if len(sources) < min_sources:
        print(f"\nFAIL: {len(sources)} sources < min {min_sources} (Day 2 ship "
              f"criterion). Live API regression suspected.", file=sys.stderr)
        return 1

    print(f"\nPASS: {len(sources)} sources ≥ {min_sources}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="e2e_metformin_smoke",
        description="Live-API smoke test against the metformin retrieval pipeline.",
    )
    parser.add_argument("--topic", default="metformin")
    parser.add_argument("--domain", default="longevity older adults")
    parser.add_argument("--criteria", default="")
    parser.add_argument("--min-sources", type=int, default=12,
                        help="Day 2 done-when threshold (default 12).")
    args = parser.parse_args(argv)
    return asyncio.run(_run_smoke(args.topic, args.domain, args.criteria,
                                  args.min_sources))


if __name__ == "__main__":
    raise SystemExit(main())
