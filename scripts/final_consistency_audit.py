"""Day 10.17 Phase 6.2 Layer 1 — deterministic final-consistency audit.

The 3 converged audits caught issues that the local-pattern audit
(scripts/audit_v06_paper.py) missed because they're cross-artifact
consistency problems:

  * "Methods says 7 papers accepted, body says MET-PREVENT rejected"
    — manifest ↔ paper contradiction
  * "Audit verdict says AAA but Q9 failed"
    — verdict gate logic
  * "Duplicate References block (writer-rendered + post-processed)"
    — formatting / pipeline contract
  * "### ### malformed headers"
    — formatting
  * "(potentially) inline repair artifacts"
    — stale Phase 2 patches
  * "Methods describes SPAR but no SPAR ran in this run"
    — stale boilerplate

Per the converged reviewer plan: code catches structured consistency
problems perfectly; LLM is downstream. This script is Layer 1 — runs
on (paper, manifest, audit) and emits a list of typed inconsistencies.

Output: <paper>.consistency.json (list of issues + auto-fixable flag)
        <paper>.consistency.md   (markdown summary)

Per-issue contract:
  {
    "id": "C01",
    "severity": "P1" | "P2",
    "issue_type": "manifest_contradiction" | "stale_method" | ...,
    "auto_fixable": bool,
    "evidence": "<paper text snippet that triggered it>",
    "suggested_fix": "<deterministic patch description>",
  }

Exits 0 if no P1 issues; 1 otherwise.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

__all__ = ["ConsistencyIssue", "run_audit", "main"]


@dataclass(frozen=True, slots=True)
class ConsistencyIssue:
    id: str
    severity: str        # "P1" | "P2"
    issue_type: str
    auto_fixable: bool
    evidence: str        # the offending paper substring (≤200 chars)
    suggested_fix: str   # imperative sentence describing the patch


# --- Stale Methods phrases ----------------------------------------------
# Phrases the v0.6 adapter MUST NOT carry over from agent/paper_writer.py
# templates that were written for the SPAR/multi-receipt pipeline.
_STALE_METHOD_PHRASES = (
    "spar adjudication",
    "spar rejected",
    "spar quarantined",
    "rejected by spar",
    "spar-quarantined",
    "claim receipts",
    "receipt cluster",
    "receipt-level spar",
    "synthesis-level spar",
    "trust-spine multi-receipt",
)


# --- Repair artifacts ---------------------------------------------------
# Phase 2 / v0.5 inline hedge insertions that read awkward in finished
# prose. The repair pass is fine while drafting; final output should
# replace inline (potentially) with sentence-level hedging.
_REPAIR_ARTIFACT_PATTERNS = (
    r"\(potentially\)",
    r"\bevidence\s+suggests\s+that\s+evidence\s+suggests\s+that",  # double prefix
)


def _section_heading_anchor(name: str) -> re.Pattern[str]:
    return re.compile(rf"^##\s+{re.escape(name)}\b", re.MULTILINE)


def _check_manifest_paper_consistency(
    paper: str, manifest: dict,
) -> list[ConsistencyIssue]:
    """The manifest says N papers accepted; the paper text must not
    contradict that count or specifically reject any accepted paper."""
    issues: list[ConsistencyIssue] = []
    accepted_ids = {
        r["receipt_id"] for r in manifest.get("receipts", [])
    }

    # Build short forms (e.g. "Witham 2025") from accepted receipt_ids
    short_forms_to_id: dict[str, str] = {}
    for rid in accepted_ids:
        parts = rid.split("_")
        if len(parts) >= 2 and parts[1].isdigit():
            short = f"{parts[0]} {parts[1]}"
            short_forms_to_id[short] = rid
            short_forms_to_id[parts[0]] = rid  # bare surname

    # Issue: paper text claims an accepted paper was REJECTED by SPAR.
    # Sentence-bounded scan: for each rejection-marker, find its
    # containing sentence and look for any short_form mention. Avoids
    # the greedy-match bug where the prefix `[A-Z][a-zA-Z]+` swallowed
    # an unrelated heading word.
    rejection_marker_re = re.compile(
        r"(?:was\s+rejected\b|rejected\s+by\s+SPAR|SPAR-quarantined|"
        r"did\s+not\s+pass\s+SPAR|quarantined\s+by\s+SPAR)",
        re.IGNORECASE,
    )
    # Reviewer-fix HIGH 2/3: only flag if the short_form appears
    # within a tight ~80-char window of the rejection marker AND
    # without an intervening clause break. "While Walton was rejected
    # by SPAR, Witham 2025 demonstrated..." pre-fix wrongly tagged
    # Witham. Clause-break heuristic: comma followed by either a
    # capital-letter proper-noun (new clause subject) or a
    # connector word; full stop / semicolon also count.
    _CLAUSE_BREAK_RE = re.compile(
        # comma + whitespace + (capital-starting word OR connector)
        r",\s+(?=[A-Z][a-z]|and\b|but\b|while\b|although\b|"
        r"whereas\b|however\b)|"
        r"\.\s+|;\s+",
    )
    for m in rejection_marker_re.finditer(paper):
        # Look ±80 chars around the marker for short_form mentions,
        # but stop at any intervening clause break.
        before_window = paper[max(0, m.start() - 80):m.start()]
        after_window = paper[m.end():min(len(paper), m.end() + 80)]
        # Trim before_window at the LAST clause break (we want the
        # text adjacent to the marker, not text from a prior clause).
        breaks_before = list(_CLAUSE_BREAK_RE.finditer(before_window))
        if breaks_before:
            before_window = before_window[breaks_before[-1].end():]
        # Trim after_window at the FIRST clause break.
        first_break_after = _CLAUSE_BREAK_RE.search(after_window)
        if first_break_after:
            after_window = after_window[:first_break_after.start()]
        clause = before_window + paper[m.start():m.end()] + after_window
        for short_form in short_forms_to_id:
            if re.search(rf"\b{re.escape(short_form)}\b", clause):
                issues.append(ConsistencyIssue(
                    id=f"C01-{m.start()}",
                    severity="P1",
                    issue_type="accepted_paper_called_rejected",
                    auto_fixable=True,
                    evidence=clause.strip()[:200],
                    suggested_fix=(
                        f"Remove SPAR-rejected language for {short_form} "
                        f"(manifest lists it as accepted)."
                    ),
                ))
                break  # one issue per marker
    return issues


def _check_stale_methods(paper: str, manifest: dict) -> list[ConsistencyIssue]:
    """Methods MUST NOT mention SPAR/receipt-cluster machinery if the
    actual run used the v0.6 quant-claim adapter (no SPAR)."""
    issues: list[ConsistencyIssue] = []
    # Reviewer-fix MEDIUM 1: lookahead must include `|\Z` so a paper
    # ending on Methods/References still scopes correctly. Pre-fix
    # fell back to `paper` (whole document) and false-flagged any
    # SPAR mention in Discussion as a Methods issue.
    methods_match = re.search(
        r"##\s+Methods(.*?)(?=^##\s+\w|\Z)", paper,
        flags=re.DOTALL | re.MULTILINE,
    )
    methods_body = methods_match.group(1) if methods_match else ""
    method_lc = methods_body.lower()

    # If manifest writer_path mentions paper_writer.py (NOT spar/synthesis),
    # then SPAR-language in Methods is stale.
    writer_path = (manifest.get("writer_path") or "").lower()
    spar_ran = "spar" in writer_path

    if not spar_ran:
        for phrase in _STALE_METHOD_PHRASES:
            # Reviewer-fix MEDIUM 3: emit one issue PER occurrence
            # with idx-suffixed id (was sharing id when same phrase
            # appeared twice).
            for m in re.finditer(re.escape(phrase), method_lc):
                idx = m.start()
                snippet = methods_body[max(0, idx - 40):idx + len(phrase) + 40]
                issues.append(ConsistencyIssue(
                    id=f"C02-{phrase[:20].replace(' ', '_')}-{idx}",
                    severity="P1",
                    issue_type="stale_method_boilerplate",
                    auto_fixable=True,
                    evidence=snippet,
                    suggested_fix=(
                        f"Remove '{phrase}' from Methods — no SPAR ran "
                        f"in this v0.6 adapter run."
                    ),
                ))
    return issues


def _check_duplicate_references(paper: str) -> list[ConsistencyIssue]:
    """At most one '## References' section is allowed.

    The deterministic fixer in `apply_consistency_fixes.py` removes
    the FIRST block (assumed writer-rendered with internal handles)
    and keeps the LAST block (assumed post-processed Author-Year).
    The audit's `suggested_fix` text matches that behavior.
    """
    issues: list[ConsistencyIssue] = []
    matches = list(_section_heading_anchor("References").finditer(paper))
    if len(matches) > 1:
        for m in matches[:-1]:
            snippet = paper[m.start():m.start() + 80]
            issues.append(ConsistencyIssue(
                id=f"C03-dup-refs-{m.start()}",
                severity="P1",
                issue_type="duplicate_section",
                auto_fixable=True,
                evidence=snippet,
                suggested_fix=(
                    "Remove this earlier References section; keep ONLY "
                    "the last (post-processor's deterministic Author-Year "
                    "block)."
                ),
            ))
    return issues


def _check_malformed_headers(paper: str) -> list[ConsistencyIssue]:
    """Markdown headers like '### ### Foo' or '## ##' are bugs."""
    issues: list[ConsistencyIssue] = []
    bad_re = re.compile(r"^(#{2,4})\s+#{2,4}\s", re.MULTILINE)
    for m in bad_re.finditer(paper):
        issues.append(ConsistencyIssue(
            id=f"C04-{m.start()}",
            severity="P2",
            issue_type="malformed_header",
            auto_fixable=True,
            evidence=paper[m.start():m.start() + 60],
            suggested_fix=(
                "Replace double-hash header marker with single-tier '###'."
            ),
        ))
    return issues


def _check_repair_artifacts(paper: str) -> list[ConsistencyIssue]:
    """Inline (potentially) and similar Phase-2 repair artifacts."""
    issues: list[ConsistencyIssue] = []
    for pattern in _REPAIR_ARTIFACT_PATTERNS:
        for m in re.finditer(pattern, paper, re.IGNORECASE):
            issues.append(ConsistencyIssue(
                id=f"C05-{m.start()}",
                severity="P2",
                issue_type="repair_artifact",
                auto_fixable=True,
                evidence=paper[max(0, m.start() - 30):m.end() + 30],
                suggested_fix=(
                    "Remove the inline (potentially) artifact; if the "
                    "sentence needs hedging, add 'Evidence suggests that ' "
                    "at the sentence start instead."
                ),
            ))
    return issues


def _check_audit_verdict_gate(
    audit: dict, audit_md_text: str = "",
) -> list[ConsistencyIssue]:
    """The audit summary file must NOT call a paper 'AAA' if any check
    failed. Trust-Spine Pass is allowed when score ≥9 + no P1 fail but
    some P2 failed.

    `audit_md_text` is the existing audit.md content; if it already
    says 'Trust-Spine Pass', the rename has happened and we don't
    re-flag (avoids endless self-trigger after fixer runs)."""
    issues: list[ConsistencyIssue] = []
    n_total = audit.get("n_total") or 0
    n_pass = audit.get("n_pass") or 0
    p1_pass = audit.get("p1_pass", False)
    score = audit.get("score_out_of_10") or 0
    if n_total and n_pass < n_total:
        if score >= 9.0 and p1_pass:
            already_renamed = "Trust-Spine Pass" in audit_md_text
            if not already_renamed:
                issues.append(ConsistencyIssue(
                    id="C06-verdict-rename",
                    severity="P2",
                    issue_type="audit_verdict_overclaim",
                    auto_fixable=True,
                    evidence=(
                        f"score={score} p1_pass={p1_pass} "
                        f"pass_rate={n_pass}/{n_total}"
                    ),
                    suggested_fix=(
                        "Audit summary should say 'Trust-Spine Pass' "
                        "(P1 clean + score ≥9, but some P2 checks failed). "
                        "Reserve 'AAA Paper' for all-green."
                    ),
                ))
    return issues


def _check_broken_paper_id_citations(paper: str) -> list[ConsistencyIssue]:
    """Truncated paper_ids leaking into prose (e.g. 'Walton_2019_MASTERS_').
    These are signs the citation post-processor missed a span."""
    issues: list[ConsistencyIssue] = []
    bad_re = re.compile(r"\b([A-Z][a-zA-Z]+_\d{4}_[A-Za-z_]+_)\b")
    for m in bad_re.finditer(paper):
        snippet = paper[max(0, m.start() - 30):m.end() + 30]
        # Allow inside References (quoted), reject in body
        # Detect by checking if we're inside a "## References" section.
        before = paper[:m.start()]
        last_h2 = before.rfind("\n## ")
        if last_h2 >= 0:
            heading_line = before[last_h2:].split("\n", 2)[1]
            if "References" in heading_line:
                continue
        issues.append(ConsistencyIssue(
            id=f"C07-{m.start()}",
            severity="P1",
            issue_type="paper_id_in_body",
            auto_fixable=False,  # needs receipt list to map to Author Year
            evidence=snippet,
            suggested_fix=(
                f"Replace truncated paper_id '{m.group(1)}' with a "
                "proper Author Year citation (post-processor may have "
                "missed this span)."
            ),
        ))
    return issues


def run_audit(
    paper_md: str, manifest: dict, audit: dict, audit_md_text: str = "",
) -> list[ConsistencyIssue]:
    issues: list[ConsistencyIssue] = []
    issues.extend(_check_manifest_paper_consistency(paper_md, manifest))
    issues.extend(_check_stale_methods(paper_md, manifest))
    issues.extend(_check_duplicate_references(paper_md))
    issues.extend(_check_malformed_headers(paper_md))
    issues.extend(_check_repair_artifacts(paper_md))
    issues.extend(_check_audit_verdict_gate(audit, audit_md_text))
    issues.extend(_check_broken_paper_id_citations(paper_md))
    return issues


def _format_summary(issues: list[ConsistencyIssue]) -> str:
    if not issues:
        return (
            "# Final Consistency Audit\n\n"
            "**No consistency issues found.** Paper, manifest, and audit "
            "report are mutually consistent. Layer 2 (LLM reviewer) can "
            "now run."
        )
    n_p1 = sum(1 for i in issues if i.severity == "P1")
    n_p2 = sum(1 for i in issues if i.severity == "P2")
    lines = [
        "# Final Consistency Audit",
        "",
        f"**Issues found: {len(issues)} ({n_p1} P1, {n_p2} P2)**",
        "",
        f"**Verdict: {'SHIP-BLOCKED' if n_p1 else 'PASS WITH NOTES'}**",
        "",
        "| ID | Severity | Type | Auto-fix? | Evidence | Fix |",
        "|---|---|---|---|---|---|",
    ]
    for i in issues:
        ev = i.evidence[:60].replace("|", "\\|").strip()
        lines.append(
            f"| {i.id} | {i.severity} | {i.issue_type} | "
            f"{'✓' if i.auto_fixable else '✗'} | "
            f"`{ev}` | {i.suggested_fix} |"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Layer 1 deterministic final-consistency audit",
    )
    parser.add_argument("paper_md", help="Path to full_paper.md")
    parser.add_argument(
        "--manifest", help="Path to manifest.json (default: <run_dir>/manifest.json)",
    )
    parser.add_argument(
        "--audit",
        help="Path to audit.json (default: <paper>.audit.json)",
    )
    args = parser.parse_args(argv)
    paper_path = Path(args.paper_md).resolve()
    if not paper_path.exists():
        print(f"not found: {paper_path}", file=sys.stderr)
        return 2
    paper = paper_path.read_text()
    manifest_path = (
        Path(args.manifest).resolve() if args.manifest
        else paper_path.parent / "manifest.json"
    )
    audit_path = (
        Path(args.audit).resolve() if args.audit
        else paper_path.with_suffix(".audit.json")
    )
    manifest: dict = (
        json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    )
    audit: dict = (
        json.loads(audit_path.read_text()) if audit_path.exists() else {}
    )
    audit_md_path = paper_path.with_suffix(".audit.md")
    audit_md_text = (
        audit_md_path.read_text() if audit_md_path.exists() else ""
    )

    issues = run_audit(paper, manifest, audit, audit_md_text)
    out_json = paper_path.with_suffix(".consistency.json")
    out_md = paper_path.with_suffix(".consistency.md")
    out_json.write_text(json.dumps(
        {"n_issues": len(issues), "issues": [asdict(i) for i in issues]},
        indent=2,
    ))
    out_md.write_text(_format_summary(issues))
    print(_format_summary(issues))
    n_p1 = sum(1 for i in issues if i.severity == "P1")
    return 0 if n_p1 == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
