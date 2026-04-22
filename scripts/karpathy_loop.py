"""Karpathy loop harness — local scoring against gold fixtures.

Snapshots composite_score (plus 4 sub-metrics) for every gold topic.
Subcommands:
  snapshot  — score all topics, write timestamped JSON
  diff      — compare two snapshots
  report    — pretty-print a diff
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
REPO_ROOT = _HERE.parent
TOPICS_DIR = REPO_ROOT / "tests" / "golden" / "topics"
FIXTURES_DIR = REPO_ROOT / "tests" / "golden" / "fixtures"
SNAPSHOTS_DIR = _HERE / "karpathy-loop" / "snapshots"
DIFFS_DIR = _HERE / "karpathy-loop" / "diffs"

# ── Scoring functions (re-implemented from tests/golden/harness.py) ─────────

_STOPWORDS = {"and", "in", "for", "of", "the", "with", "on", "to", "a", "an"}
_SYNONYMS = {"rapamycin": ["sirolimus"], "metformin": ["glucophage"]}

_POSITIVE_KW = {
    "suggest", "suggests", "suggested", "could", "may", "might", "can",
    "demonstrate", "demonstrates", "demonstrated", "shows", "indicates",
    "support", "supports", "supported", "effective", "efficacy",
    "improved", "improvement", "reduces", "reducing", "reduction",
    "increases", "increasing", "beneficial", "benefit", "positive",
    "favorable", "associated", "implicated", "linked", "helps", "impact",
}
_NEGATIVE_PHRASES = {
    "no evidence", "no benefit", "no improvement", "no advantage",
    "ineffective", "harmful",
    "does not reduce", "does not significantly reduce", "not supported",
    "not supported by", "no significant benefit", "no significant effect",
    "no effect on",
}
_CAVEAT_KW = {
    "limited", "preliminary", "preliminarily", "caution",
    "mixed", "heterogeneous", "inconsistent", "uncertain", "unclear",
    "insufficient", "needed", "required", "requires", "promising",
    "investigational", "varies", "however", "lacks", "gap", "gaps",
}

_ABBREVIATIONS = {
    "rcts": "trial", "rct": "trial", "trials": "trial", "studies": "study",
    "efficacy": "efficac", "effectiveness": "efficac", "efficacious": "efficac",
    "heterogen": "heterogen", "heterogeneous": "heterogen", "heterogeneity": "heterogen",
    "small": "small", "limited": "limited",
    "long-term": "longterm", "long-duration": "longterm", "longterm": "longterm",
    "safety": "safety", "adverse": "safety", "toxicity": "safety",
    "dosing": "dose", "doses": "dose", "dose": "dose",
    "regimens": "regimen", "regimen": "regimen",
    "biomarker": "biomarker", "biomarkers": "biomarker",
    "clinical": "clinical", "outcomes": "outcome", "outcome": "outcome",
    "intervention": "intervention", "interventions": "intervention",
    "duration": "duration", "durations": "duration",
    "sample": "sample", "samples": "sample",
    "size": "size", "sizes": "size",
    "human": "human", "population": "population", "populations": "population",
    "lack": "absent", "absence": "absent", "scarcity": "absent", "insufficient": "absent",
    "placebo": "placebo", "controlled": "controlled", "comparator": "controlled",
    "months": "month", "month": "month", "weeks": "week", "week": "week",
    "healthspan": "healthspan", "aging": "aging", "age": "age",
    "generalizability": "generaliz",
}

_NUMERIC_CLAIM_RE = re.compile(
    r"\d+(?:\.\d+)?\s*(?:%|ppm|mg|fold|x|years?|months?|days?|patients?|subjects?|participants?|kg|mg/kg|ug|L|mL|nM|uM|uL|mmHg|bpm)"
)


def _normalize_doi(doi: str) -> str:
    """Strip https://doi.org/ prefix and lowercase."""
    doi = doi.lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if doi.startswith(prefix):
            doi = doi[len(prefix):]
    return doi.strip()


def _classify_direction(text: str) -> str:
    """Classify text direction into one of 6 conclusion_direction values."""
    t = text.lower()
    words = set(re.sub(r"[^\w\s]", "", w) for w in t.split())
    pos_count = sum(1 for kw in _POSITIVE_KW if kw in words)
    neg_count = sum(1 for phrase in _NEGATIVE_PHRASES if phrase in t)
    caveat_count = sum(1 for kw in _CAVEAT_KW if kw in words)

    if pos_count > 0 and neg_count > 0:
        if neg_count >= 2 and neg_count * 2 >= pos_count:
            return "negative_with_caveats" if caveat_count > 0 else "negative"
        return "mixed"
    if pos_count > 0 and neg_count == 0 and caveat_count == 0:
        return "positive"
    if pos_count > 0 and caveat_count > 0:
        return "positive_with_caveats"
    if neg_count > 0 and pos_count == 0 and caveat_count == 0:
        return "negative"
    if neg_count > 0 and caveat_count > 0:
        return "negative_with_caveats"
    if caveat_count > 2:
        return "mixed"
    return "insufficient_evidence"


def _direction_distance(d1: str, d2: str) -> float:
    """0.0 = same, 0.5 = off-by-one-confidence-level, 1.0 = completely different."""
    order = [
        "negative", "negative_with_caveats", "insufficient_evidence",
        "mixed", "positive_with_caveats", "positive",
    ]
    try:
        i1, i2 = order.index(d1), order.index(d2)
        diff = abs(i1 - i2)
        if diff == 0:
            return 0.0
        if diff == 1:
            return 0.5
        return 1.0
    except ValueError:
        return 1.0


def study_overlap(draft: dict, gold: dict) -> float:
    """Fraction of gold.included_dois that appear in draft.source_bundle."""
    source_bundle = draft.get("source_bundle", [])
    draft_dois: set[str] = set()
    for entry in source_bundle:
        doi = entry.get("doi") or ""
        if doi:
            draft_dois.add(_normalize_doi(doi))
    if not draft_dois:
        return 0.0
    gold_dois = gold.get("included_dois", [])
    matched = sum(1 for gd in gold_dois if _normalize_doi(gd) in draft_dois)
    return matched / len(gold_dois) if gold_dois else 0.0


def direction_agreement(draft: dict, gold: dict) -> float:
    """Classify draft direction, compare to gold.conclusion_direction."""
    sections = draft.get("sections", {})
    findings = sections.get("Key Findings", "") or ""
    conclusion = sections.get("Conclusion", "") or ""
    combined = f"{findings} {conclusion}"
    draft_dir = _classify_direction(combined)
    gold_dir = gold.get("conclusion_direction", "insufficient_evidence")
    dist = _direction_distance(draft_dir, gold_dir)
    return 1.0 - dist


def _normalize_token(token: str) -> str:
    """Map common abbreviations and inflections to canonical forms."""
    clean = re.sub(r"[^\w]", "", token.lower().strip())
    if clean in _ABBREVIATIONS:
        return _ABBREVIATIONS[clean]
    if clean.endswith("s") and clean[:-1] in _ABBREVIATIONS:
        return _ABBREVIATIONS[clean[:-1]]
    return clean


def _jaccard_similarity(text1: str, text2: str) -> float:
    """Word-level similarity with abbreviation normalization (recall-oriented)."""
    tokens1 = set(_normalize_token(w) for w in text1.lower().split())
    tokens2 = set(_normalize_token(w) for w in text2.lower().split())
    tokens1.discard("")
    tokens2.discard("")
    if not tokens2:
        return 0.0
    if not tokens1 and not tokens2:
        return 0.0
    overlap = len(tokens1 & tokens2)
    return overlap / len(tokens2)


def limitation_overlap(draft: dict, gold: dict) -> float:
    """Bag-of-word Jaccard between draft Limitations and each gold limitation."""
    sections = draft.get("sections", {})
    draft_limitations = sections.get("Limitations", "") or ""
    gold_limitations = gold.get("limitations", [])
    if not gold_limitations:
        return 0.0
    matched = sum(
        1 for gl in gold_limitations
        if _jaccard_similarity(draft_limitations, gl) >= 0.25
    )
    return matched / len(gold_limitations)


def _extract_numbers(text: str) -> set[str]:
    return set(_NUMERIC_CLAIM_RE.findall(text.lower()))


def _evidence_contains_number(evidence_excerpts: list[str], number_str: str) -> bool:
    for excerpt in evidence_excerpts:
        if number_str in excerpt.lower():
            return True
    return False


def quantitative_fidelity(draft: dict, gold: dict) -> float:
    """Measure quantitative rigor of the draft's Key Findings."""
    sections = draft.get("sections", {})
    findings = sections.get("Key Findings", "") or ""
    numeric_claims = _extract_numbers(findings)
    if not numeric_claims:
        return 0.5
    source_bundle = draft.get("source_bundle", [])
    evidence_excerpts = [str(e.get("excerpt", "")) for e in source_bundle]
    supported = sum(
        1 for num in numeric_claims
        if _evidence_contains_number(evidence_excerpts, num)
    )
    return supported / len(numeric_claims)


def composite_score(draft: dict, gold: dict) -> float:
    """Weighted composite: study=0.10, quant=0.40, direction=0.30, limitation=0.20."""
    return (
        0.10 * study_overlap(draft, gold)
        + 0.40 * quantitative_fidelity(draft, gold)
        + 0.30 * direction_agreement(draft, gold)
        + 0.20 * limitation_overlap(draft, gold)
    )


# ── Helpers ──────────────────────────────────────────────────────────────────

def _git_sha() -> str:
    try:
        import subprocess
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        return result.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def load_topics(topics_dir: Path) -> dict[str, dict]:
    """Return {slug: gold_dict} for every topic JSON."""
    topics = {}
    for p in sorted(topics_dir.glob("*.json")):
        topics[p.stem] = json.loads(p.read_text())
    return topics


def load_fixtures(fixtures_dir: Path) -> dict[str, dict]:
    """Return {slug: draft_dict} for every *_draft.json fixture."""
    fixtures = {}
    for p in sorted(fixtures_dir.glob("*_draft.json")):
        slug = p.stem.removesuffix("_draft")
        fixtures[slug] = json.loads(p.read_text())
    return fixtures


def score_topic(draft: dict, gold: dict) -> dict[str, float]:
    """Compute all 5 metrics for one topic."""
    return {
        "study_overlap": round(study_overlap(draft, gold), 4),
        "direction_agreement": round(direction_agreement(draft, gold), 4),
        "limitation_overlap": round(limitation_overlap(draft, gold), 4),
        "quantitative_fidelity": round(quantitative_fidelity(draft, gold), 4),
        "composite_score": round(composite_score(draft, gold), 4),
    }


# ── Subcommands ──────────────────────────────────────────────────────────────

def cmd_snapshot(args: argparse.Namespace) -> int:
    topics = load_topics(Path(args.topics_dir))
    fixtures = load_fixtures(Path(args.fixtures_dir))

    shared = sorted(set(topics) & set(fixtures))
    if not shared:
        print("ERROR: No matching topic/fixture pairs found.", file=sys.stderr)
        return 1

    results = {}
    for slug in shared:
        metrics = score_topic(fixtures[slug], topics[slug])
        results[slug] = metrics

    avg = {
        k: round(sum(r[k] for r in results.values()) / len(results), 4)
        for k in next(iter(results.values()))
    }

    snapshot = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "git_sha": _git_sha(),
        "topics": results,
        "averages": avg,
    }

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"{ts}_snapshot.json"
    out_path.write_text(json.dumps(snapshot, indent=2) + "\n")

    return 0


def cmd_diff(args: argparse.Namespace) -> int:
    before = json.loads(Path(args.before).read_text())
    after = json.loads(Path(args.after).read_text())

    b_topics = before.get("topics", {})
    a_topics = after.get("topics", {})
    all_slugs = sorted(set(b_topics) | set(a_topics))

    topic_diffs = {}
    for slug in all_slugs:
        b = b_topics.get(slug, {})
        a = a_topics.get(slug, {})
        all_keys = sorted(set(b) | set(a))
        topic_diffs[slug] = {k: round(a.get(k, 0) - b.get(k, 0), 4) for k in all_keys}

    avg_diff = {}
    b_avg = before.get("averages", {})
    a_avg = after.get("averages", {})
    for k in sorted(set(b_avg) | set(a_avg)):
        avg_diff[k] = round(a_avg.get(k, 0) - b_avg.get(k, 0), 4)

    diff = {
        "before_ts": before.get("timestamp", ""),
        "after_ts": after.get("timestamp", ""),
        "before_sha": before.get("git_sha", ""),
        "after_sha": after.get("git_sha", ""),
        "topics": topic_diffs,
        "average_delta": avg_diff,
    }

    DIFFS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = DIFFS_DIR / f"{ts}_diff.json"
    out_path.write_text(json.dumps(diff, indent=2) + "\n")
    print(str(out_path))
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    diff = json.loads(Path(args.diff).read_text())

    print("Karpathy Loop Report")
    print(f"  Before: {diff.get('before_sha', '?')}  ({diff.get('before_ts', '?')})")
    print(f"  After:  {diff.get('after_sha', '?')}  ({diff.get('after_ts', '?')})")
    print()

    topic_diffs = diff.get("topics", {})
    if not topic_diffs:
        print("  No topic diffs found.")
        return 0

    print(f"  {'Topic':<30} {'Composite':>9} {'Study':>7} {'Quant':>7} {'Dir':>7} {'Limit':>7}")
    print(f"  {'-'*30} {'-'*9} {'-'*7} {'-'*7} {'-'*7} {'-'*7}")

    improved = 0
    regressed = 0
    for slug in sorted(topic_diffs):
        d = topic_diffs[slug]
        cs = d.get("composite_score", 0)
        marker = ""
        if cs > 0.005:
            marker = " ↑"
            improved += 1
        elif cs < -0.005:
            marker = " ↓"
            regressed += 1
        print(
            f"  {slug:<30} {cs:>+9.4f} "
            f"{d.get('study_overlap', 0):>+7.4f} "
            f"{d.get('quantitative_fidelity', 0):>+7.4f} "
            f"{d.get('direction_agreement', 0):>+7.4f} "
            f"{d.get('limitation_overlap', 0):>+7.4f}{marker}"
        )

    print()
    avg = diff.get("average_delta", {})
    print("  Average delta:")
    print(f"    composite_score:          {avg.get('composite_score', 0):+.4f}")
    print(f"    study_overlap:            {avg.get('study_overlap', 0):+.4f}")
    print(f"    quantitative_fidelity:    {avg.get('quantitative_fidelity', 0):+.4f}")
    print(f"    direction_agreement:      {avg.get('direction_agreement', 0):+.4f}")
    print(f"    limitation_overlap:       {avg.get('limitation_overlap', 0):+.4f}")
    print()
    print(f"  Improved: {improved}  Regressed: {regressed}  Unchanged: {len(topic_diffs) - improved - regressed}")
    return 0


# ── CLI ──────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Karpathy loop harness — score gold topics before/after changes."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    snap = sub.add_parser("snapshot", help="Score all gold topics and save snapshot")
    snap.add_argument("--topics-dir", default=str(TOPICS_DIR))
    snap.add_argument("--fixtures-dir", default=str(FIXTURES_DIR))
    snap.add_argument("--output-dir", default=str(SNAPSHOTS_DIR))
    snap.set_defaults(func=cmd_snapshot)

    diff = sub.add_parser("diff", help="Compare two snapshots")
    diff.add_argument("before", help="Path to earlier snapshot JSON")
    diff.add_argument("after", help="Path to later snapshot JSON")
    diff.set_defaults(func=cmd_diff)

    rpt = sub.add_parser("report", help="Pretty-print a diff")
    rpt.add_argument("diff", help="Path to diff JSON")
    rpt.set_defaults(func=cmd_report)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
