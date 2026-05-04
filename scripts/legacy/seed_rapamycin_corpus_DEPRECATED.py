"""DEPRECATED — moved to scripts/legacy/ on 2026-05-04.

Use the generic seeder instead:
    python scripts/seed_topic_corpus.py --topic rapamycin

This file is kept for archaeological reference. Do NOT extend or
import from it. The corpus seeding logic is now topic-agnostic and
lives in scripts/seed_topic_corpus.py + agent/sources/aggregator.py;
the rapamycin-specific data (search queries, canonical RCTs,
background numerics) lives in topic_packs/rapamycin.toml.

If you want to add a NEW topic, write topic_packs/<topic>.toml and
run scripts/seed_topic_corpus.py --topic <X>. Do NOT copy this file.

Below this line is the ORIGINAL docstring + code, untouched, for
reference only.
================================================================

Proof 002 — rapamycin corpus seeding (Workstream C).

Two phases:

  --triage   Read 67 cards from prior pipeline run, score + rank
             them, write top-N candidate list. NO LLM cost. Outputs
             docs/quality-reference/rapamycin/_triage.json for human
             review before --extract.

  --extract  For each triaged paper:
             1. Resolve identifier → PMCID via Europe PMC DOI lookup
             2. Fetch full-text JATS XML via fetch_oa_corpus.py
                (free Europe PMC API)
             3. Run quant_claim_extract.py (deterministic regex,
                no LLM cost)
             4. Move artifacts to docs/quality-reference/rapamycin/
                {quant_claims,parsed}/
             Effectively FREE — only API calls + local regex. The
             only LLM cost is the eventual synthesis run (~$0.04).

The triage exists so a human (or Claude) can review the candidate
list BEFORE LLM extraction spends money. The script prints the
top-N to stderr in a human-scannable form; the JSON file is the
machine-readable contract for --extract.

Selection criteria for top-15 (priority order):
  1. ALL A1/A2 cards with direct=True (load-bearing RCTs/observational)
  2. A1/A2 registered_pending on canonical NCTs (PEARL, RAP-AD, etc.)
  3. B-tier rapamycin-direct results/protocols (ranked by venue+year)
  4. C-tier preclinical lifespan papers (Harrison 2009, ITP, etc.)
  5. Optional: highly-cited mechanism papers if slot still open

Hard exclusions: cards where the abstract does NOT mention rapamycin
or sirolimus — the prior pipeline's retrieval pulled some adjacent
mTOR-adjacent papers (alpha-ketoglutarate, young plasma transfusion
trials etc.) that are off-topic for a rapamycin corpus.

Usage:
  python scripts/seed_rapamycin_corpus.py --triage
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
SEED_CARDS = REPO / "runs" / "rapamycin-002-2026-04-28T19-03-28Z-4ab9" \
    / "evidence_cards.json"
OUT_DIR = REPO / "docs" / "quality-reference" / "rapamycin"

# Canonical NCTs from topic_packs/rapamycin.toml — pin these even if
# the abstract scoring is weak.
PINNED_NCTS = {
    "NCT04488601",  # PEARL
    "NCT01649960",  # RAP-CAD (Konopka)
    "NCT04629495",  # RAP-AD
    "NCT04994561",  # VIAging
    "NCT02874924",  # mTOR + metabolism elderly
    "NCT05237687",  # Sirolimus + functional decline
}

# Off-topic NCTs / titles found in the seed pool (alpha-ketoglutarate,
# young plasma, etc.) — exclude these even if tier looks attractive.
EXCLUDE_NCTS = {
    "NCT05706389",  # alpha-ketoglutarate
    "NCT03353597",  # young plasma transfusion
    "NCT05924295",  # ketone metabolism
    "NCT06789900",  # everolimus + bone (everolimus, not rapamycin)
}

# Keyword anchors. Card abstract must contain ≥1 to be considered
# rapamycin-direct (drops topic-adjacent noise).
TOPIC_KEYWORDS = {
    "rapamycin", "sirolimus", "rapamune", "mtor inhibitor",
    "mtorc1 inhibitor", "rad001",
}


def _is_topic_direct(card: dict[str, Any]) -> bool:
    """Cheap topic filter — abstract must mention rapamycin/sirolimus
    by name. Prior pipeline retrieval pulled some neighbours; this
    filter drops them."""
    abstract = (card.get("abstract") or "").lower()
    title = (card.get("source", {}).get("title") or "").lower()
    blob = abstract + " " + title
    return any(kw in blob for kw in TOPIC_KEYWORDS)


def _score(card: dict[str, Any]) -> int:
    """Higher = more important. Used after pinning + filtering to
    rank residual candidates for the remaining slots."""
    tier = card.get("tier", "")
    direct = card.get("direct", False)
    role = card.get("role", "")
    design = card.get("design", "")
    # Tier weight
    tier_w = {"A1": 100, "A2": 80, "B": 40, "C": 10}.get(tier, 0)
    # Direct bonus
    direct_w = 30 if direct is True else 0
    # Role weight
    role_w = {
        "published_results": 20,
        "registered_pending": 12,
        "published_protocol": 8,
        "mechanistic": 4,
    }.get(role, 0)
    # Design weight
    design_w = {
        "rct": 15, "observational": 10, "registry": 5,
        "protocol": 5, "mechanistic": 2,
    }.get(design, 0)
    # Year recency (capped)
    year = card.get("source", {}).get("year") or 0
    year_w = max(0, min(10, year - 2015))
    return tier_w + direct_w + role_w + design_w + year_w


def _paper_id(card: dict[str, Any], idx: int) -> str:
    """Synthesise a stable paper_id for the corpus filenames."""
    src = card.get("source", {})
    title = (src.get("title") or "").strip()
    year = src.get("year") or "YYYY"
    nct = src.get("nct")
    if nct:
        return f"{nct}_{year}"
    # First word of title + year
    first_word = "".join(c for c in title.split()[0] if c.isalnum()) \
        if title else "Paper"
    return f"{first_word}_{year}_{idx:02d}"


def triage(top_n: int = 15) -> dict[str, Any]:
    """Run the triage. Returns the result dict + writes JSON to
    OUT_DIR / '_triage.json'."""
    if not SEED_CARDS.exists():
        raise FileNotFoundError(
            f"seed evidence_cards not found: {SEED_CARDS}"
        )
    cards: list[dict[str, Any]] = json.loads(SEED_CARDS.read_text())
    n_total = len(cards)

    # 1. Hard exclusions (off-topic NCTs, missing rapamycin mention)
    candidates: list[dict[str, Any]] = []
    n_off_topic = 0
    n_excluded_nct = 0
    for c in cards:
        nct = c.get("source", {}).get("nct")
        if nct in EXCLUDE_NCTS:
            n_excluded_nct += 1
            continue
        if not _is_topic_direct(c):
            n_off_topic += 1
            continue
        candidates.append(c)
    n_after_filter = len(candidates)

    # 2. Pinned NCTs (canonical trials always go in regardless of
    # ranking — these are the moat per topic_packs/rapamycin.toml)
    pinned: list[dict[str, Any]] = []
    pinned_ncts_seen: set[str] = set()
    for c in candidates:
        nct = c.get("source", {}).get("nct")
        if nct in PINNED_NCTS and nct not in pinned_ncts_seen:
            pinned.append(c)
            pinned_ncts_seen.add(nct)

    # 3. Rank remaining and fill to top_n
    pinned_ids = {id(c) for c in pinned}
    remaining = [c for c in candidates if id(c) not in pinned_ids]
    remaining.sort(key=_score, reverse=True)
    fill_n = max(0, top_n - len(pinned))
    selection = pinned + remaining[:fill_n]

    # 4. Stamp paper_id on each
    selected: list[dict[str, Any]] = []
    for idx, c in enumerate(selection):
        record = {
            "paper_id": _paper_id(c, idx),
            "tier": c.get("tier"),
            "direct": c.get("direct"),
            "role": c.get("role"),
            "design": c.get("design"),
            "score": _score(c),
            "pinned": id(c) in pinned_ids,
            "source": c.get("source", {}),
            "abstract": c.get("abstract", ""),
        }
        selected.append(record)

    result = {
        "topic": "rapamycin",
        "seed_cards_path": str(
            SEED_CARDS.relative_to(REPO)
        ),
        "n_total": n_total,
        "n_excluded_nct": n_excluded_nct,
        "n_off_topic": n_off_topic,
        "n_after_filter": n_after_filter,
        "n_pinned": len(pinned),
        "n_selected": len(selected),
        "top_n_target": top_n,
        "selected": selected,
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / "_triage.json"
    out_path.write_text(json.dumps(result, indent=2))
    return result


def _print_summary(result: dict[str, Any]) -> None:
    print(f"=== Rapamycin Corpus Triage ===", file=sys.stderr)
    print(
        f"Seed cards:      {result['n_total']}\n"
        f"Excluded NCTs:   {result['n_excluded_nct']} "
        "(off-topic, e.g. alpha-ketoglutarate, young plasma)\n"
        f"Off-topic skip:  {result['n_off_topic']} "
        "(no rapamycin/sirolimus mention)\n"
        f"After filter:    {result['n_after_filter']}\n"
        f"Pinned NCTs:     {result['n_pinned']}\n"
        f"Selected:        {result['n_selected']} "
        f"(target: top {result['top_n_target']})",
        file=sys.stderr,
    )
    print("\n--- Selected papers ---", file=sys.stderr)
    for i, p in enumerate(result["selected"], 1):
        s = p["source"]
        title = s.get("title", "?")[:75]
        year = s.get("year", "?")
        nct = s.get("nct", "")
        nct_s = f" {nct}" if nct else ""
        pin = "📌" if p["pinned"] else "  "
        print(
            f"  {pin} {i:2d}. [{p['tier']}|{p['design']}|"
            f"direct={p['direct']}|score={p['score']}]{nct_s}",
            file=sys.stderr,
        )
        print(f"       {title} ({year})", file=sys.stderr)


def _resolve_pmcid_via_europepmc(
    identifier: dict[str, Any],
) -> str | None:
    """Resolve a paper's source identifier (DOI / PMID / NCT) to a
    PMCID via Europe PMC search. Returns None if no PMC full-text
    is available (e.g. trial-only NCTs)."""
    import urllib.request
    import urllib.parse

    doi = identifier.get("doi")
    pmid = identifier.get("pmid")
    if not (doi or pmid):
        return None
    query_parts = []
    if doi:
        query_parts.append(f"DOI:{doi}")
    if pmid:
        query_parts.append(f"EXT_ID:{pmid}")
    query = " OR ".join(query_parts)
    url = (
        "https://www.ebi.ac.uk/europepmc/webservices/rest/search?"
        f"query={urllib.parse.quote(query)}"
        "&format=json&pageSize=1"
    )
    try:
        req = urllib.request.Request(
            url, headers={
                "User-Agent": "researka-rapamycin-corpus/0.1"
            },
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.load(r)
    except Exception as e:  # network / parse / timeout
        print(
            f"  ! resolve fail (doi={doi}): {e}",
            file=sys.stderr,
        )
        return None
    hits = data.get("resultList", {}).get("result", [])
    if not hits:
        return None
    pmcid = hits[0].get("pmcid")
    return pmcid


def extract(top_n: int = 15) -> dict[str, Any]:
    """Phase 2 of corpus seeding: resolve identifiers → PMCIDs →
    fetch full text via Europe PMC → extract quant claims via
    deterministic regex. All free except API rate limits.

    Returns {'attempted': N, 'pmcid_resolved': N, 'fetched': N,
             'extracted': N, 'failures': [...]}."""
    import subprocess
    triage_path = OUT_DIR / "_triage.json"
    if not triage_path.exists():
        raise FileNotFoundError(
            f"run --triage first to produce {triage_path}"
        )
    triage_doc = json.loads(triage_path.read_text())
    selected = triage_doc.get("selected", [])[:top_n]

    parsed_dir = OUT_DIR / "parsed"
    quant_dir = OUT_DIR / "quant_claims"
    parsed_dir.mkdir(parents=True, exist_ok=True)
    quant_dir.mkdir(parents=True, exist_ok=True)

    result = {
        "attempted": len(selected),
        "pmcid_resolved": 0,
        "fetched": 0,
        "extracted": 0,
        "failures": [],
        "papers": [],
    }
    pmcids_to_fetch = []
    paper_id_for_pmcid: dict[str, str] = {}

    print(
        f"=== Resolving identifiers → PMCIDs ({len(selected)} "
        "papers) ===",
        file=sys.stderr,
    )
    for p in selected:
        paper_id = p["paper_id"]
        identifier = {
            "doi": p["source"].get("doi"),
            "pmid": p["source"].get("pmid"),
            "nct": p["source"].get("nct"),
        }
        if not (identifier["doi"] or identifier["pmid"]):
            print(
                f"  - {paper_id}: no DOI/PMID (likely trial-only) — "
                "skip",
                file=sys.stderr,
            )
            result["failures"].append({
                "paper_id": paper_id,
                "reason": "no DOI/PMID (trial-only)",
            })
            continue
        pmcid = _resolve_pmcid_via_europepmc(identifier)
        if pmcid:
            print(
                f"  ✓ {paper_id}: {pmcid}",
                file=sys.stderr,
            )
            pmcids_to_fetch.append(pmcid)
            paper_id_for_pmcid[pmcid] = paper_id
            result["pmcid_resolved"] += 1
        else:
            print(
                f"  - {paper_id}: PMCID not found in Europe PMC",
                file=sys.stderr,
            )
            result["failures"].append({
                "paper_id": paper_id,
                "reason": "no PMCID (closed-access)",
            })

    if not pmcids_to_fetch:
        print(
            "No PMCIDs resolved; nothing to fetch.",
            file=sys.stderr,
        )
        out_path = OUT_DIR / "_extract_report.json"
        out_path.write_text(json.dumps(result, indent=2))
        return result

    # Fetch full text via fetch_oa_corpus.py
    print(
        f"\n=== Fetching {len(pmcids_to_fetch)} papers from "
        "Europe PMC ===",
        file=sys.stderr,
    )
    cmd = [
        "python3", str(REPO / "scripts" / "fetch_oa_corpus.py"),
        "--pmcids", ",".join(pmcids_to_fetch),
        "--out-dir", str(parsed_dir),
    ]
    try:
        subprocess.run(cmd, check=True, cwd=REPO)
    except subprocess.CalledProcessError as e:
        print(f"fetch_oa_corpus failed: {e}", file=sys.stderr)
        result["failures"].append({
            "paper_id": "BATCH",
            "reason": f"fetch_oa_corpus exit {e.returncode}",
        })

    # Count fetched paper_sections.json files
    fetched_files = list(parsed_dir.glob("*.paper_sections.json"))
    result["fetched"] = len(fetched_files)

    # Run quant_claim_extract.py on each
    print(
        f"\n=== Extracting quant claims from "
        f"{result['fetched']} papers ===",
        file=sys.stderr,
    )
    for pf in fetched_files:
        target_qf = quant_dir / (
            pf.stem.replace(".paper_sections", "")
            + ".quant_claims.json"
        )
        if target_qf.exists():
            print(
                f"  ✓ {pf.stem}: already extracted, skip",
                file=sys.stderr,
            )
            result["extracted"] += 1
            continue
        cmd = [
            "python3",
            str(REPO / "scripts" / "quant_claim_extract.py"),
            str(pf),
            "--out", str(target_qf),
        ]
        try:
            subprocess.run(cmd, check=True, cwd=REPO)
            result["extracted"] += 1
            print(
                f"  ✓ {pf.stem}: → {target_qf.name}",
                file=sys.stderr,
            )
        except subprocess.CalledProcessError as e:
            print(
                f"  ! {pf.stem}: extract failed ({e})",
                file=sys.stderr,
            )
            result["failures"].append({
                "paper_id": pf.stem,
                "reason": f"quant_claim_extract exit {e.returncode}",
            })

    # Write report
    out_path = OUT_DIR / "_extract_report.json"
    out_path.write_text(json.dumps(result, indent=2))
    return result


def _print_extract_summary(result: dict[str, Any]) -> None:
    print(
        f"\n=== Rapamycin Corpus Extract Summary ===\n"
        f"Attempted:       {result['attempted']}\n"
        f"PMCID resolved:  {result['pmcid_resolved']}\n"
        f"Full-text fetch: {result['fetched']}\n"
        f"Quant extracted: {result['extracted']}\n"
        f"Failures:        {len(result['failures'])}",
        file=sys.stderr,
    )
    if result["failures"]:
        print("\nFailures:", file=sys.stderr)
        for f in result["failures"]:
            print(
                f"  - {f['paper_id']}: {f['reason']}",
                file=sys.stderr,
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Seed the rapamycin corpus (Proof 002 Workstream C)",
    )
    parser.add_argument(
        "--triage", action="store_true",
        help="Triage the 67 seed cards → top-N candidates "
             "(no LLM cost). Outputs _triage.json for review.",
    )
    parser.add_argument(
        "--extract", action="store_true",
        help="Resolve PMCIDs + fetch full text + extract quant "
             "claims. Free (Europe PMC API + deterministic regex). "
             "Requires _triage.json from a prior --triage run.",
    )
    parser.add_argument(
        "--top-n", type=int, default=15,
        help="Number of papers to select / extract (default: 15)",
    )
    args = parser.parse_args(argv)

    if args.triage and args.extract:
        # Run triage first, then extract
        triage_result = triage(top_n=args.top_n)
        _print_summary(triage_result)
        extract_result = extract(top_n=args.top_n)
        _print_extract_summary(extract_result)
        return 0

    if args.triage:
        result = triage(top_n=args.top_n)
        _print_summary(result)
        print(
            f"\nWrote {OUT_DIR / '_triage.json'}",
            file=sys.stderr,
        )
        return 0

    if args.extract:
        result = extract(top_n=args.top_n)
        _print_extract_summary(result)
        return 0

    parser.error("--triage or --extract (or both) required")


if __name__ == "__main__":
    sys.exit(main())
