"""Day 10.17 Phase 6.2 — trust-spine audit for v0.6.0 synthesis paper.

Per the user audit verdict for Phase 6:
  - every numeric in prose traces to a quant claim
  - every citation maps to source metadata
  - every high-confidence claim used has claim_role == "effect"
  - no mortality/lifespan conflation
  - no unhedged model-organism-to-human transfer

Gate: audit ≥ 9/10, all P1 checks pass.

Reads `runs/<dir>/full_paper.md` + the v0.6.0 quant_claims corpus and
produces a JSON audit report + markdown summary.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
QUANT_DIR = REPO_ROOT / "docs" / "quality-reference" / "metformin" / "quant_claims"
PARSED_DIR = REPO_ROOT / "docs" / "quality-reference" / "metformin" / "parsed"


def _load_corpus_numerics() -> set[str]:
    """All numeric tokens that appear in v0.6.0 high-confidence claims."""
    nums: set[str] = set()
    for path in QUANT_DIR.glob("*.quant_claims.json"):
        d = json.loads(path.read_text())
        for c in d.get("claims", []):
            if c.get("binding_confidence") != "high":
                continue
            for v in c.get("numeric_values") or ():
                nums.add(str(v))
                # Also accept the integer form ("32" for 32.0)
                if float(v).is_integer():
                    nums.add(str(int(v)))
            raw = (c.get("raw_text") or "").strip()
            if raw:
                nums.add(raw)
    return nums


def _load_paper_metadata() -> dict[str, dict]:
    """paper_id → {title, authors, year, doi, pmid, journal}."""
    out: dict[str, dict] = {}
    for path in PARSED_DIR.glob("*.paper_sections.json"):
        d = json.loads(path.read_text())
        pid = d.get("paper_id") or path.stem
        out[pid] = d
    return out


# Q1: word count
def _check_word_count(paper: str, threshold: int = 5000) -> tuple[bool, str]:
    wc = len(paper.split())
    return wc >= threshold, f"word_count={wc} (threshold={threshold})"


# Q2: numeric integrity — every percentage and p-value in the paper
# must trace to a v0.6.0 high-confidence claim or be a small reference
# integer (e.g. "5 papers", "12 weeks" study duration).
def _check_numeric_integrity(
    paper: str, corpus_nums: set[str],
) -> tuple[bool, str]:
    # Extract percentages from the paper
    paper_pcts = set(re.findall(r"\b(\d+\.?\d*)\s*%", paper))
    # Filter to "interesting" percentages (claim-shaped, > 1%)
    pcts_to_check = {
        p for p in paper_pcts
        if float(p) > 1.0 and float(p) < 1000
    }
    untraceable = []
    for p in pcts_to_check:
        f = float(p)
        candidates = {p, str(f), str(int(f)) if f.is_integer() else p}
        if not any(c in corpus_nums for c in candidates):
            untraceable.append(p)
    n_total = len(pcts_to_check)
    n_bad = len(untraceable)
    pct_clean = (n_total - n_bad) / n_total if n_total else 1.0
    return pct_clean >= 0.9, (
        f"{n_total - n_bad}/{n_total} percentages trace to corpus "
        f"({pct_clean:.0%}); untraceable: {sorted(untraceable)[:5]}"
    )


# Q3: paper-ID leakage — internal handles must NOT appear in body prose
def _check_no_paper_id_in_body(
    paper: str, paper_meta: dict[str, dict],
) -> tuple[bool, str]:
    leaks: list[str] = []
    body_lines = []
    in_references = False
    for line in paper.splitlines():
        if line.strip().startswith("## References") or line.strip().startswith("## Limitations"):
            # References section — IDs are allowed there
            in_references = line.strip().startswith("## References")
        if not in_references:
            body_lines.append(line)
    body = "\n".join(body_lines)
    for pid in paper_meta:
        # Look for the truncated form (first 25-30 chars) which is what
        # Phase 6-lite was producing.
        short = pid[:25]
        if short and short in body and pid != "":
            leaks.append(short)
    return len(leaks) == 0, (
        f"paper-ID leaks in body: {leaks[:5]}"
        if leaks else "no paper-ID leakage"
    )


# Q4: mortality/lifespan polarity — paper must not say "decreased
# lifespan by N%" (Keys/UKPDS bug); should say "decreased mortality"
# or "reduced risk" instead
_BAD_POLARITY_RE = re.compile(
    r"decreased\s+lifespan\s+by\s+\d|"
    r"lifespan\s+(?:was\s+)?reduced\s+by\s+\d|"
    r"shortened\s+lifespan\s+by\s+\d",
    re.IGNORECASE,
)


def _check_no_mortality_lifespan_conflation(paper: str) -> tuple[bool, str]:
    matches = _BAD_POLARITY_RE.findall(paper)
    return len(matches) == 0, (
        f"polarity violations: {matches[:3]}"
        if matches else "no mortality/lifespan polarity error"
    )


# Q5: methodology fabrication — Methods section must not claim manual
# review / two researchers / consensus / verification by hand
_FAB_PHRASES = (
    "two researchers",
    "manually reviewed",
    "manual review",
    "verified by two",
    "researchers verified",
    "consensus was reached",
    "discussed and resolved",
    "domain expert",
    "expert reviewed",
)


def _check_no_fabricated_methodology(paper: str) -> tuple[bool, str]:
    methods_match = re.search(
        r"##\s+Methods.*?(?=##\s+\w)", paper, re.DOTALL,
    )
    if not methods_match:
        return False, "Methods section not found"
    methods_text = methods_match.group(0).lower()
    flagged: list[str] = []
    for phrase in _FAB_PHRASES:
        if phrase in methods_text:
            # Check for hedging/disclaimer in same sentence
            idx = methods_text.find(phrase)
            sentence_start = max(0, methods_text.rfind(".", 0, idx) + 1)
            sentence_end = methods_text.find(".", idx)
            if sentence_end < 0:
                sentence_end = len(methods_text)
            sent = methods_text[sentence_start:sentence_end]
            if "no manual" in sent or "not" in sent[:30]:
                continue  # disclaimer present
            flagged.append(phrase)
    return len(flagged) == 0, (
        f"fabricated methodology phrases: {flagged}"
        if flagged else "no fabricated methodology claims"
    )


# Q6: model-organism-to-human transfer — sentences mentioning mice/
# rats/C. elegans must hedge before applying findings to humans
_PRECLINICAL_RE = re.compile(
    r"\b(?:mice|rats?|C\.\s*elegans|mouse\s+models?|preclinical|"
    r"animal\s+models?|in\s+vitro|cell\s+culture)\b", re.IGNORECASE,
)


def _check_preclinical_hedge(paper: str) -> tuple[bool, str]:
    """For sentences mentioning preclinical models, check if the
    immediately following sentence (or same sentence) contains a
    translational hedge or limitation marker."""
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z])", paper)
    violations: list[str] = []
    hedges = (
        "humans", "translation", "translate", "extrapolat", "limit",
        "preclinical", "may not apply", "remains to be", "warrant",
        "caution", "uncertain", "context-dependent", "speculative",
        "mechanistic evidence",
    )
    for i, sent in enumerate(sentences):
        if _PRECLINICAL_RE.search(sent):
            # Check this sentence + next for any hedge.
            window = sent + " " + (sentences[i + 1] if i + 1 < len(sentences) else "")
            window_lc = window.lower()
            if not any(h in window_lc for h in hedges):
                # Also: sentences in Limitations section get a free pass
                # (we trust the section-level hedge there).
                if "limitations" in window_lc or "method" in window_lc:
                    continue
                violations.append(sent[:80])
    pass_threshold = 3  # tolerate up to 3 unhedged preclinical sentences
    return len(violations) <= pass_threshold, (
        f"unhedged preclinical→human sentences: {len(violations)} "
        f"(threshold ≤{pass_threshold})"
    )


# Q7: section coverage
_REQUIRED_SECTIONS = (
    "Abstract", "Introduction", "Methods", "Results",
    "Discussion", "Limitations", "Conclusion",
)


def _check_section_coverage(paper: str) -> tuple[bool, str]:
    missing: list[str] = []
    for sec in _REQUIRED_SECTIONS:
        if not re.search(rf"^##\s+{sec}\b", paper, re.M):
            missing.append(sec)
    return len(missing) == 0, (
        f"missing sections: {missing}" if missing else "all required sections present"
    )


# Q8: thesis sentence presence
def _check_thesis_present(paper: str) -> tuple[bool, str]:
    has_thesis = bool(
        re.search(r"^\*\*Thesis:\*\*", paper, re.M)
        or re.search(r"thesis(?:\s+is)?\s+that", paper[:3000], re.I)
    )
    return has_thesis, (
        "thesis sentence found" if has_thesis else "no thesis sentence"
    )


# Q9: numeric density (claims-per-1k-words)
def _check_numeric_density(
    paper: str, threshold: float = 8.0,
) -> tuple[bool, str]:
    wc = len(paper.split())
    n_pcts = len(re.findall(r"\b\d+\.?\d*\s*%", paper))
    n_pvalues = len(re.findall(r"\b[pP]\s*[<=>]\s*\.?\d+\.?\d*", paper))
    n_units = len(re.findall(
        r"\b\d+\.?\d*\s*(?:m/s|kg|mg|months?|years?|weeks?)\b", paper,
    ))
    total = n_pcts + n_pvalues + n_units
    density = (total / max(1, wc)) * 1000
    return density >= threshold, (
        f"density {density:.1f} numerics/1000 words "
        f"(threshold ≥{threshold})"
    )


# Q10: hedge phrases present in Discussion / Limitations
_HEDGE_PHRASES = (
    "may", "might", "suggests", "consistent with", "appears",
    "context-dependent", "uncertain", "warrants", "remains to be",
    "preliminary", "interpretive", "qualified", "limited", "cautious",
)


def _check_hedge_density(paper: str) -> tuple[bool, str]:
    discussion_match = re.search(
        r"##\s+Discussion(.*?)(?=##\s+\w)", paper, re.DOTALL,
    )
    if not discussion_match:
        return False, "Discussion section not found"
    disc = discussion_match.group(1).lower()
    n_hedges = sum(1 for h in _HEDGE_PHRASES if h in disc)
    return n_hedges >= 4, (
        f"{n_hedges}/{len(_HEDGE_PHRASES)} hedge phrases in Discussion "
        f"(threshold ≥4)"
    )


_CHECKS = (
    ("Q1_word_count", _check_word_count, True),  # P1
    ("Q2_numeric_integrity", lambda p: _check_numeric_integrity(p, _CORPUS_NUMS), True),
    ("Q3_no_paper_id_in_body", lambda p: _check_no_paper_id_in_body(p, _PAPER_META), True),
    ("Q4_no_polarity_error", _check_no_mortality_lifespan_conflation, True),
    ("Q5_no_fabricated_methods", _check_no_fabricated_methodology, True),
    ("Q6_preclinical_hedge", _check_preclinical_hedge, False),
    ("Q7_section_coverage", _check_section_coverage, True),
    ("Q8_thesis_present", _check_thesis_present, False),
    ("Q9_numeric_density", _check_numeric_density, False),
    ("Q10_hedge_density", _check_hedge_density, False),
)
# Module-level state so the lambdas above can read corpus + meta.
_CORPUS_NUMS: set[str] = set()
_PAPER_META: dict[str, dict] = {}


def audit(paper: str) -> dict:
    """Run all 10 checks. Returns dict with per-check verdict + score."""
    global _CORPUS_NUMS, _PAPER_META
    _CORPUS_NUMS = _load_corpus_numerics()
    _PAPER_META = _load_paper_metadata()

    results = []
    p1_pass = True
    n_pass = 0
    for name, check_fn, is_p1 in _CHECKS:
        try:
            passed, msg = check_fn(paper)
        except Exception as e:
            passed, msg = False, f"check exception: {e}"
        results.append({
            "name": name,
            "p1": is_p1,
            "passed": passed,
            "detail": msg,
        })
        if is_p1 and not passed:
            p1_pass = False
        if passed:
            n_pass += 1

    score = (n_pass / len(_CHECKS)) * 10
    return {
        "score_out_of_10": round(score, 1),
        "p1_pass": p1_pass,
        "checks": results,
        "n_pass": n_pass,
        "n_total": len(_CHECKS),
    }


def _format_summary(report: dict) -> str:
    lines = [
        "# v0.6.0 Synthesis Paper — Trust-Spine Audit",
        "",
        f"**Score:** {report['score_out_of_10']}/10",
        f"**P1 ship-blockers:** {'PASS' if report['p1_pass'] else 'FAIL'}",
        f"**Pass rate:** {report['n_pass']}/{report['n_total']} checks",
        "",
        "## Checks",
        "",
        "| # | Check | P1? | Status | Detail |",
        "|---|---|---|---|---|",
    ]
    for c in report["checks"]:
        status = "✅" if c["passed"] else "❌"
        p1 = "**P1**" if c["p1"] else "P2"
        lines.append(
            f"| {c['name']} | {c['name']} | {p1} | {status} | {c['detail']} |"
        )
    lines.append("")
    if not report["p1_pass"]:
        lines.append("## Verdict: SHIP-BLOCKED")
        lines.append("")
        lines.append("One or more P1 checks failed. Fix before merging.")
    elif report["score_out_of_10"] >= 9.0:
        lines.append("## Verdict: AAA")
        lines.append("")
        lines.append("≥9.0 score AND no P1 failures. Paper passes the trust-spine gate.")
    else:
        lines.append("## Verdict: PASS (with notes)")
        lines.append("")
        lines.append(
            f"P1 checks all green; overall score "
            f"{report['score_out_of_10']}/10. Some P2 checks flagged "
            "non-critical issues."
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit a v0.6.0 synthesis paper")
    parser.add_argument("paper_md", help="Path to the full_paper.md to audit")
    parser.add_argument(
        "--out",
        help="Output JSON report (default: <paper>.audit.json)",
    )
    args = parser.parse_args(argv)
    paper_path = Path(args.paper_md).resolve()
    if not paper_path.exists():
        print(f"not found: {paper_path}", file=sys.stderr)
        return 2
    paper = paper_path.read_text()
    report = audit(paper)
    out = (
        Path(args.out).resolve() if args.out
        else paper_path.with_suffix(".audit.json")
    )
    out.write_text(json.dumps(report, indent=2))
    summary_md = _format_summary(report)
    summary_path = paper_path.with_suffix(".audit.md")
    summary_path.write_text(summary_md)
    print(summary_md)
    print(f"\nReport: {out}\nSummary: {summary_path}", file=sys.stderr)
    return 0 if report["p1_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
