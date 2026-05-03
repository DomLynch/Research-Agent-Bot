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
    "spar quarantine",        # Fix #29: noun form — "SPAR quarantine process"
    "spar-rejected",          # Fix #29: hyphenated rejected
    "rejected by spar",
    "rejected evidence",      # Fix #29: bare phrase
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

    # Build short forms (e.g. "Witham 2025") from accepted receipt_ids.
    # P1 reviewer fix: also extract trial-acronym short forms (e.g.
    # "MET-PREVENT" from Witham_2025_MET_PREVENT_metformin_trial,
    # "MASTERS" from Walton_2019_MASTERS_metformin_blunts_resistance_hy).
    # Pre-fix, "MET-PREVENT was rejected by SPAR" missed the gate
    # entirely because MET-PREVENT was not in short_forms_to_id.
    short_forms_to_id: dict[str, str] = {}
    for rid in accepted_ids:
        parts = rid.split("_")
        if len(parts) >= 2 and parts[1].isdigit():
            short_forms_to_id[f"{parts[0]} {parts[1]}"] = rid
            short_forms_to_id[parts[0]] = rid  # bare surname
        # Trial acronyms: collect consecutive ALL-CAPS tokens after
        # Author_Year. Stops at the first lowercase token. Add the
        # acronym in three glue forms (hyphen / underscore / space)
        # since prose can use any of them.
        caps_run: list[str] = []
        for tok in parts[2:]:
            if tok.isupper() and len(tok) >= 2:
                caps_run.append(tok)
            else:
                break
        if caps_run:
            for tok in caps_run:
                short_forms_to_id[tok] = rid
            if len(caps_run) >= 2:
                for sep in ("-", "_", " "):
                    short_forms_to_id[sep.join(caps_run)] = rid

    # Issue: paper text claims an accepted paper was REJECTED by SPAR.
    # P1 reviewer fix: scope the scan to the FULL SENTENCE containing
    # the rejection marker (not ±80 chars). Pre-fix, "Witham 2025's
    # MET-PREVENT trial showed positive outcomes; later, MET-PREVENT
    # was rejected by SPAR" missed the gate when the trial-name
    # mention sat outside the 80-char window.
    rejection_marker_re = re.compile(
        r"(?:was\s+rejected\b|rejected\s+by\s+SPAR|SPAR-quarantined|"
        r"did\s+not\s+pass\s+SPAR|quarantined\s+by\s+SPAR)",
        re.IGNORECASE,
    )
    # Sentence boundary: . ! ? then space + capital, or paragraph
    # break, or new heading line. Conservative — favors larger scope.
    _SENTENCE_BREAK_RE = re.compile(r"[.!?]\s+(?=[A-Z])|\n\n+|\n#")
    # Clause-break trim retained from the prior heuristic to keep the
    # "While Walton was rejected by SPAR, Witham 2025 demonstrated..."
    # false-positive suppressed (we don't want to flag Witham just
    # because it shares a sentence with a Walton rejection). Only the
    # comma+new-subject pattern is needed now — sentence-scope above
    # already handles full-stops and paragraph breaks. Pre-fix the
    # heuristic also split on `;` and `.`, which cut out long-distance
    # earlier-in-sentence references that the P1 fix needs to catch.
    _CLAUSE_BREAK_RE = re.compile(
        r",\s+(?=[A-Z][a-z]|and\b|but\b|while\b|although\b|"
        r"whereas\b|however\b)",
    )
    for m in rejection_marker_re.finditer(paper):
        # Sentence-scope: find last sentence-break before marker, first
        # sentence-break after.
        sent_start = 0
        for sb in _SENTENCE_BREAK_RE.finditer(paper[:m.start()]):
            sent_start = sb.end()
        sb_after = _SENTENCE_BREAK_RE.search(paper, m.end())
        sent_end = sb_after.start() if sb_after else len(paper)
        before_window = paper[sent_start:m.start()]
        after_window = paper[m.end():sent_end]
        # Clause-break trim within the sentence: keeps subject of the
        # rejection clause adjacent to the marker; drops sibling
        # clauses that name unrelated accepted papers.
        breaks_before = list(_CLAUSE_BREAK_RE.finditer(before_window))
        if breaks_before:
            before_window = before_window[breaks_before[-1].end():]
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
    """Internal handles leaking into prose. Two shapes:
      a) Truncated Author_Year_TRIAL_keyword_ ids (post-processor miss)
      b) PMCID handles like "PMC12978362 2026" (P2 reviewer fix:
         pre-fix only the Author_Year shape was caught, so internal
         corpus identifiers passed straight through as fake citations).
    """
    issues: list[ConsistencyIssue] = []
    patterns: tuple[tuple[str, re.Pattern], ...] = (
        (
            "truncated_author_year_id",
            re.compile(r"\b([A-Z][a-zA-Z]+_\d{4}_[A-Za-z_]+_)\b"),
        ),
        (
            "pmcid_in_body",
            re.compile(r"\b(PMC\d{7,9}(?:\s+\d{4})?)\b"),
        ),
    )
    for kind, bad_re in patterns:
        for m in bad_re.finditer(paper):
            snippet = paper[max(0, m.start() - 30):m.end() + 30]
            # Allow inside ## References (proper bibliographic context).
            before = paper[:m.start()]
            last_h2 = before.rfind("\n## ")
            if last_h2 >= 0:
                heading_line = before[last_h2:].split("\n", 2)[1]
                if "References" in heading_line:
                    continue
            # Allow inside `_Cited:_` italicized citation blocks. The
            # writer emits these per-section to attribute claims to
            # specific receipts; PMCID handles ARE the proper cite for
            # PMC-only papers (no Author Year exists). The leak gate
            # only matters for body prose like "Recent work by PMC...".
            line_start = paper.rfind("\n", 0, m.start()) + 1
            line_end = paper.find("\n", m.end())
            if line_end < 0:
                line_end = len(paper)
            line = paper[line_start:line_end]
            if "_Cited:" in line:
                continue
            issues.append(ConsistencyIssue(
                id=f"C07-{kind}-{m.start()}",
                severity="P1" if kind == "truncated_author_year_id" else "P2",
                issue_type=kind,
                auto_fixable=False,
                evidence=snippet,
                suggested_fix=(
                    f"Replace internal handle '{m.group(1)}' with a "
                    "proper Author Year citation (post-processor may "
                    "have missed this span)."
                ),
            ))
    return issues


def run_audit(
    paper_md: str, manifest: dict, audit: dict, audit_md_text: str = "",
) -> list[ConsistencyIssue]:
    issues: list[ConsistencyIssue] = []
    issues.extend(_check_manifest_paper_consistency(paper_md, manifest))
    issues.extend(_check_stale_methods(paper_md, manifest))
    issues.extend(_check_stale_spar_in_prose(paper_md, manifest))  # Fix #29
    issues.extend(_check_internal_tier_labels_in_prose(paper_md))  # Fix #33
    issues.extend(_check_duplicate_references(paper_md))
    issues.extend(_check_malformed_headers(paper_md))
    issues.extend(_check_repair_artifacts(paper_md))
    issues.extend(_check_audit_verdict_gate(audit, audit_md_text))
    issues.extend(_check_broken_paper_id_citations(paper_md))
    issues.extend(_check_surface_polish(paper_md))  # Fix #13
    issues.extend(_check_background_lit_unsourced(paper_md))  # Fix #16
    issues.extend(_check_surface_render_lint(paper_md))  # Fix #22
    issues.extend(_check_change_value_misread(paper_md, manifest))  # Fix #37
    issues.extend(_check_abstract_over_grouping(paper_md, manifest))  # Fix #38
    return issues


# Fix #33: pipeline-internal tier labels that must NOT appear in
# rendered prose. The writer's prompt now humanises them (Fix #33
# in agent/paper_writer.py) but a defence-in-depth Stage-2 check
# catches any that slip through (e.g. via Grok patches).
_INTERNAL_TIER_LABEL_RE = re.compile(
    r"\b(?:A1_clinical_RCT|A2_human_mechanistic|"
    r"B1_review|B2_observational|"
    r"C1_preclinical|C2_in_vitro)\b"
)


def _check_internal_tier_labels_in_prose(
    paper: str,
) -> list[ConsistencyIssue]:
    """Fix #33: paper-tier internal labels (A1_clinical_RCT, etc.)
    must NOT appear in rendered prose. They're machine artefacts
    from the writer's receipt-context block; reviewer flagged them
    as obvious 'AI article' tells. Severity P2 (cosmetic but
    public-review-blocking), auto-fixable (we replace with a
    human-readable equivalent)."""
    issues: list[ConsistencyIssue] = []
    for m in _INTERNAL_TIER_LABEL_RE.finditer(paper):
        label = m.group(0)
        snippet = paper[max(0, m.start() - 40):m.end() + 40]
        issues.append(ConsistencyIssue(
            id=f"C12-tier-leak-{m.start()}",
            severity="P2",
            issue_type="internal_tier_label_in_prose",
            auto_fixable=True,
            evidence=snippet.strip()[:200],
            suggested_fix=(
                f"Internal tier label {label!r} leaked into prose; "
                "replace with human-readable study-design phrase "
                "(e.g. 'RCT (clinical/functional endpoint)' for "
                "A1_clinical_RCT)."
            ),
        ))
    return issues


def _check_stale_spar_in_prose(
    paper: str, manifest: dict,
) -> list[ConsistencyIssue]:
    """Fix #29: SPAR-language must NOT leak into ANY section when the
    actual run used the v0.6 quant-claim adapter (no SPAR ran). The
    pre-existing _check_stale_methods scopes only to the Methods
    section — but reviewer caught 'SPAR quarantine process' in the
    Limitations section. This check scans every section EXCEPT
    Methods (which the other check handles) so we don't double-flag."""
    issues: list[ConsistencyIssue] = []
    writer_path = (manifest.get("writer_path") or "").lower()
    if "spar" in writer_path:
        return issues
    # Strip out the Methods body so we don't double-flag with the
    # existing _check_stale_methods.
    paper_excluding_methods = re.sub(
        r"##\s+Methods.*?(?=^##\s+\w|\Z)", "",
        paper, flags=re.DOTALL | re.MULTILINE,
    )
    paper_lc = paper_excluding_methods.lower()
    for phrase in _STALE_METHOD_PHRASES:
        for m in re.finditer(re.escape(phrase), paper_lc):
            idx = m.start()
            snippet = paper_excluding_methods[
                max(0, idx - 40):idx + len(phrase) + 40
            ]
            issues.append(ConsistencyIssue(
                id=f"C11-{phrase[:20].replace(' ', '_')}-{idx}",
                severity="P1",
                issue_type="stale_spar_in_prose",
                auto_fixable=True,  # apply_consistency_fixes strips
                evidence=snippet.strip()[:200],
                suggested_fix=(
                    f"Replace SPAR-language sentence containing "
                    f"{phrase!r} with v0.6 corpus-only phrasing "
                    "('candidate sources not represented in the "
                    "quant-claim corpus')."
                ),
            ))
    return issues


def _check_surface_render_lint(paper_md: str) -> list[ConsistencyIssue]:
    """C10 (Fix #22): catch the surface-render artifacts that the
    Stage-2 audit historically missed but a human reader notices —
    orphan `_Cited:` blocks, consecutive cite blocks, abstract
    citation-only paragraphs, sentence-end author-year fragments.

    Severity: P2 (orphan/consecutive/abstract are auto-fixable;
    sentence-end author-year is flag-only — needs Layer-2 stylistic
    judgement to rewrite cleanly)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import surface_render_lint as _srl
    except ImportError:
        return []
    findings = _srl.run_surface_lint(paper_md)
    issues: list[ConsistencyIssue] = []
    for f in findings:
        # Auto-fixable: orphan + consecutive + abstract-cite-only all
        # collapse to "strip the cite block" (apply_consistency_fixes
        # calls strip_orphan_citation_blocks). Sentence-end author-
        # year is flag-only.
        is_auto = f.kind in (
            "orphan_cite", "consecutive_cites", "abstract_cite_only",
        )
        issues.append(ConsistencyIssue(
            id=f"C10-{f.kind}-L{f.line_no}",
            severity="P2",
            issue_type=f"surface_render_{f.kind}",
            auto_fixable=is_auto,
            evidence=f.evidence,
            suggested_fix=f.suggested_fix,
        ))
    return issues


def _check_background_lit_unsourced(paper_md: str) -> list[ConsistencyIssue]:
    """C09 (Fix #16): every background-literature numeric used in the
    paper MUST have its canonical citation token in the same sentence.

    Background-lit numerics are admitted to Q2 (extending corpus-only
    trace) — but admission is conditional on attribution. Without this
    check, the writer could use '0.8 m/s' freely and Q2 would pass
    silently. This Stage-2 P1 check enforces the attribution contract."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import background_literature as _bg
        registry = _bg.load_registry()
        unsourced = _bg.find_unsourced_background_uses(paper_md, registry)
    except (ImportError, FileNotFoundError, ValueError):
        return []
    issues: list[ConsistencyIssue] = []
    for numeric, citation_token, snippet in unsourced:
        issues.append(ConsistencyIssue(
            id=f"C09-bglit-unsourced-{numeric}",
            severity="P1",  # P1: unsourced background = trust-spine breach
            issue_type="background_lit_unsourced",
            # Fix #18b: auto_fixable=True — apply_consistency_fixes
            # strips the offending sentence rather than ship-block
            # forever on a writer-prompt miss.
            auto_fixable=True,
            evidence=snippet,
            suggested_fix=(
                f"Background-literature value {numeric!r} used without "
                f"citation. Add '({citation_token})' to the sentence "
                "OR remove the value."
            ),
        ))
    return issues


# ----- C08: surface polish (Fix #13) -----------------------------------
# Catches reviewer-flagged "PhD polish" defects: malformed words,
# duplicated phrases, double spaces, broken citation ordering, empty
# `_Cited:_` blocks. Lightweight regex pass — 0 LLM calls.

# Patterns that indicate a malformed/typo word. Limited to obvious
# joins/hallucinations to avoid false-positives on real prose.
_MALFORMED_WORD_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    # `geroprotectied` (real example from prior reviewer feedback) —
    # adjective ending in `ied` without `f`/`r` stem is unusual.
    ("misformed-suffix-ied", re.compile(
        r"\b\w+(?<!fied)(?<!ried)(?<!died)(?<!tied)(?<!plied)"
        r"(?<!plied)(?<!plied)ectied\b"
    )),
    # Triple-letter run inside a word (typo signal). Excludes spans
    # adjacent to `-` or `/` or contained in submission-ID-like
    # contexts (where 'aaa' could appear in run names like
    # 'synthesis-metformin-v06-aaa-push-...').
    ("triple-letter-run", re.compile(
        r"(?<![\-_/])\b[a-z]*([a-z])\1\1[a-z]*\b(?![\-_/])",
        re.IGNORECASE,
    )),
)

# "Konopka 2019 et al." → should be "Konopka et al. 2019"
_BROKEN_CITATION_ORDER_RE = re.compile(
    r"\b([A-Z][a-zA-Z]+)\s+(\d{4})\s+et\s+al\.?",
)

# Empty `_Cited:_` block — `_Cited: _` or `_Cited:_` with nothing
# between colon and closing underscore.
_EMPTY_CITED_BLOCK_RE = re.compile(r"_Cited:\s*_")

# Double-or-more spaces in body prose (excluding code blocks).
_DOUBLE_SPACE_RE = re.compile(r"(?<!\n)  +(?!\n)")


def _check_surface_polish(paper_md: str) -> list[ConsistencyIssue]:
    """C08: surface-polish defects that break PhD-paper feel."""
    issues: list[ConsistencyIssue] = []

    # Strip fenced code blocks before scanning so triple-letter runs
    # in code samples don't false-fire.
    haystack = re.sub(r"```.*?```", "", paper_md, flags=re.DOTALL)

    # Malformed words
    for kind, pat in _MALFORMED_WORD_PATTERNS:
        for m in pat.finditer(haystack):
            issues.append(ConsistencyIssue(
                id=f"C08-malformed-{m.start()}",
                severity="P2",
                issue_type="malformed_word",
                auto_fixable=False,
                evidence=haystack[max(0, m.start() - 20):m.end() + 20],
                suggested_fix=(
                    f"Likely typo / generated artifact ({kind}): "
                    f"{m.group(0)!r}"
                ),
            ))

    # Broken citation order
    for m in _BROKEN_CITATION_ORDER_RE.finditer(haystack):
        author, year = m.group(1), m.group(2)
        issues.append(ConsistencyIssue(
            id=f"C08-cite-order-{m.start()}",
            severity="P2",
            issue_type="broken_citation_order",
            auto_fixable=True,
            evidence=haystack[max(0, m.start() - 20):m.end() + 20],
            suggested_fix=(
                f"`{author} {year} et al.` → `{author} et al. {year}`"
            ),
        ))

    # Empty `_Cited:_` blocks
    for m in _EMPTY_CITED_BLOCK_RE.finditer(haystack):
        issues.append(ConsistencyIssue(
            id=f"C08-empty-cited-{m.start()}",
            severity="P2",
            issue_type="empty_cited_block",
            auto_fixable=True,
            evidence=haystack[max(0, m.start() - 20):m.end() + 20],
            suggested_fix="Empty _Cited:_ block — remove or populate.",
        ))

    # Double spaces in prose
    for m in _DOUBLE_SPACE_RE.finditer(haystack):
        issues.append(ConsistencyIssue(
            id=f"C08-double-space-{m.start()}",
            severity="P2",
            issue_type="double_space",
            auto_fixable=True,
            evidence=haystack[max(0, m.start() - 20):m.end() + 20],
            suggested_fix="Collapse multiple spaces to single space.",
        ))

    # Duplicated adjacent phrase ("the the", "of of", "is is" etc.)
    # — common LLM-generation artifact.
    for m in re.finditer(
        r"\b(\w{3,})\s+\1\b", haystack, re.IGNORECASE,
    ):
        word = m.group(1).lower()
        # Whitelist legitimate doublings ("had had", "that that").
        if word in {"had", "that", "what", "which"}:
            continue
        # Suppress when SECOND occurrence is followed by hyphen — the
        # 'over' in 'regex over over-claimed' is grammatical (preposition
        # then hyphenated adjective). Same for 'after after-effects' etc.
        after_match = haystack[m.end():m.end() + 1]
        if after_match == "-":
            continue
        issues.append(ConsistencyIssue(
            id=f"C08-dup-phrase-{m.start()}",
            severity="P2",
            issue_type="duplicated_phrase",
            auto_fixable=True,
            evidence=haystack[max(0, m.start() - 20):m.end() + 20],
            suggested_fix=f"Duplicated word `{m.group(1)}`.",
        ))

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


# Fix #37: change-value misread detection.
#
# The Witham/MET-PREVENT paper says "improvement in 4-m walk speed of
# 0.13 m/s with metformin"; the writer interpreted that 0.13 m/s as
# an ABSOLUTE walking speed below the 0.8 m/s frailty threshold.
# That's a load-bearing scientific misinterpretation.
#
# Detect by: scan corpus quant_claims for high-conf numerics whose
# source-sentence context contains a change-word ("change",
# "improvement", "increase", "decrease", "difference", "delta",
# "reduction", "rise"). Tag those numerics as change-value-only.
# Then scan the paper for sentences containing the numeric AND
# absolute-value language ("below", "above", "value of", "level of",
# "falls below threshold") AND NOT containing the change-word.
# Flag as P1 — the value cannot be safely re-attributed without
# changing scientific meaning.

_CHANGE_WORDS = (
    "change", "improvement", "increase", "decrease", "difference",
    "delta", "reduction", "rise", "decline", "gain",
)
_ABSOLUTE_VALUE_PHRASES = (
    "falls below", "below the", "above the",
    "value of", "level of",
    "absolute", "indicates", "signals",
)


def _check_change_value_misread(
    paper_md: str, manifest: dict,
) -> list[ConsistencyIssue]:
    """Fix #37: catch numerics described as absolute values when the
    corpus says they're CHANGE/improvement/difference values.
    Severity P1, NOT auto-fixable (requires Grok or human rewrite).

    Empirically: Witham's '0.13 m/s improvement' was rendered as
    'gait speed was 0.13 m/s, below the 0.8 m/s threshold' — a
    direct misinterpretation that a senior reviewer catches in
    seconds. Detection is one-shot deterministic over corpus
    source-sentence context."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        # Pull QUANT_DIR from the orchestrator (topic-aware).
        import run_v06_synthesis as _orch
        quant_dir = _orch.QUANT_DIR
    except (ImportError, AttributeError):
        return []
    if not quant_dir.exists():
        return []
    # Build {numeric_string: {change_words_in_source}} for high-conf
    # claims across the corpus.
    change_value_map: dict[str, set[str]] = {}
    for qf in quant_dir.glob("*.quant_claims.json"):
        try:
            data = json.loads(qf.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        for c in data.get("claims", []):
            if c.get("binding_confidence") != "high":
                continue
            raw = (c.get("raw_text") or "").strip()
            if not raw:
                continue
            sent_lc = (c.get("sentence") or "").lower()
            change_hits = {w for w in _CHANGE_WORDS if w in sent_lc}
            if not change_hits:
                continue
            change_value_map.setdefault(raw, set()).update(change_hits)
    if not change_value_map:
        return []
    issues: list[ConsistencyIssue] = []
    sent_split = re.compile(r"(?<=[.!?])\s+(?=[A-Z])|\n\n+")
    sentences = sent_split.split(paper_md)
    for sent in sentences:
        sent_lc = sent.lower()
        for numeric, change_words in change_value_map.items():
            if numeric not in sent:
                continue
            # Sentence is a misread iff it contains absolute-value
            # phrasing AND does NOT contain any of the source's
            # change-words.
            has_absolute = any(
                p in sent_lc for p in _ABSOLUTE_VALUE_PHRASES
            )
            has_change = any(w in sent_lc for w in change_words)
            if has_absolute and not has_change:
                snippet = sent.strip()[:200]
                issues.append(ConsistencyIssue(
                    id=f"C13-change-misread-{hash(sent) & 0xffffff}",
                    severity="P1",
                    issue_type="change_value_misread",
                    auto_fixable=False,
                    evidence=snippet,
                    suggested_fix=(
                        f"Numeric {numeric!r} is a change/improvement "
                        f"value in the corpus source (context word(s): "
                        f"{sorted(change_words)}); paper renders it "
                        f"as an absolute value. Rewrite to "
                        f"acknowledge it is a change/difference."
                    ),
                ))
    return issues


# Fix #38: abstract over-attribution detection.
#
# The abstract said "Keys 2025, Patel 2026, and Henney 2025 each
# reporting mortality reductions in the range of 16–42%". Henney
# (PMC12803636) has zero high-confidence percentage claims — the
# attribution is wrong.
#
# Detect by: scan the Abstract section for sentences containing
# multiple Author-Year tokens AND a numeric/range. For each cited
# receipt, verify its high-conf claims contain the numeric. If a
# cited receipt does NOT carry the numeric, flag the over-attribution.

_AUTHOR_YEAR_RE = re.compile(
    r"\b([A-Z][a-zA-Z]+(?:\s+et\s+al\.)?)\s+(\d{4})\b"
)
_PERCENT_RANGE_RE = re.compile(
    r"\b(\d+\.?\d*)\s*[–-]\s*(\d+\.?\d*)\s*%"
)


def _check_abstract_over_grouping(
    paper_md: str, manifest: dict,
) -> list[ConsistencyIssue]:
    """Fix #38: catch abstract sentences that group multiple
    Author-Year citations under a numeric range when one of the
    cited receipts doesn't carry the numeric. Severity P1, not
    auto-fixable (requires receipt-by-receipt rewrite)."""
    abstract_match = re.search(
        r"##\s+Abstract(.*?)(?=^##\s+\w|\Z)",
        paper_md, re.DOTALL | re.MULTILINE,
    )
    if not abstract_match:
        return []
    abstract = abstract_match.group(1)

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import run_v06_synthesis as _orch
        import citation_registry as _cr
        quant_dir = _orch.QUANT_DIR
        parsed_dir = _orch.PARSED_DIR
    except (ImportError, AttributeError):
        return []
    if not quant_dir.exists():
        return []
    # Build the same body_citation mapping the writer + tables use,
    # so 'Henney 2025' in prose maps back to the right receipt_id
    # (e.g. PMC12803636_synergistic_associations_...).
    paper_meta_by_id: dict[str, dict] = {}
    if parsed_dir.exists():
        for path in parsed_dir.glob("*.paper_sections.json"):
            try:
                d = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            pid = d.get("paper_id") or path.stem
            paper_meta_by_id[pid] = d
    # Mock-receipt list for citation_registry — the registry only
    # needs receipt_id + a few source_* fields to derive
    # body_citation, all of which we can pull from paper_meta or
    # the manifest's receipts list.
    from dataclasses import dataclass

    @dataclass(frozen=True)
    class _MR:
        receipt_id: str
        source_year: int | None = None
        source_doi: str | None = None
        source_pmid: str | None = None
        source_pmcid: str | None = None
        source_journal: str | None = None
        title: str | None = None

    mock_receipts = []
    for rec in manifest.get("receipts") or []:
        rid = rec.get("receipt_id", "")
        if not rid:
            continue
        meta = paper_meta_by_id.get(rid, {})
        mock_receipts.append(_MR(
            receipt_id=rid,
            source_year=meta.get("year"),
            source_doi=meta.get("doi"),
            source_pmid=meta.get("pmid"),
            source_pmcid=meta.get("pmcid"),
            source_journal=meta.get("journal"),
            title=meta.get("title"),
        ))
    try:
        registry = _cr.build_registry(
            mock_receipts, paper_meta_by_id=paper_meta_by_id,
        )
    except Exception:  # noqa: BLE001
        return []
    # Build {body_citation: set_of_high_conf_percent_strings}
    citation_to_percents: dict[str, set[str]] = {}
    for raw_id, entry in registry.items():
        body_cite = entry.body_citation
        qf = quant_dir / f"{raw_id}.quant_claims.json"
        if not qf.exists():
            citation_to_percents.setdefault(body_cite, set())
            continue
        try:
            data = json.loads(qf.read_text())
        except (OSError, json.JSONDecodeError):
            citation_to_percents.setdefault(body_cite, set())
            continue
        pcts: set[str] = set()
        for c in data.get("claims", []):
            if c.get("binding_confidence") != "high":
                continue
            if c.get("claim_type") == "percentage":
                raw = (c.get("raw_text") or "").strip()
                if raw:
                    pcts.add(raw)
        citation_to_percents[body_cite] = pcts
    if not citation_to_percents:
        return []
    issues: list[ConsistencyIssue] = []
    sent_split = re.compile(r"(?<=[.!?])\s+(?=[A-Z])|\n\n+")
    for sent in sent_split.split(abstract):
        # Citations cited in this sentence — match against the
        # body_citation forms in our map.
        cited = {
            cite for cite in citation_to_percents
            if cite in sent
        }
        # Sentence-level over-grouping requires ≥2 distinct citations
        if len(cited) < 2:
            continue
        # Range or percent in the same sentence
        ranges = _PERCENT_RANGE_RE.findall(sent)
        if not ranges:
            continue
        # For each cited receipt: do its high-conf percent claims
        # cover the numeric range? Crude check: the receipt must
        # have at least ONE percent claim. If it has none, it's
        # being over-grouped (the writer attributed a percent to a
        # paper that has no percent claims).
        empty_cites = [
            c for c in cited if not citation_to_percents.get(c)
        ]
        if not empty_cites:
            continue
        snippet = sent.strip()[:200]
        for empty_cite in empty_cites:
            issues.append(ConsistencyIssue(
                id=(
                    f"C14-abstract-overgroup-"
                    f"{empty_cite.replace(' ', '_')}-"
                    f"{hash(sent) & 0xffffff}"
                ),
                severity="P1",
                issue_type="abstract_over_grouping",
                auto_fixable=False,
                evidence=snippet,
                suggested_fix=(
                    f"Abstract sentence groups {sorted(cited)} under "
                    f"a numeric range {ranges[0]} but {empty_cite!r} "
                    f"has no high-confidence percentage claims in its "
                    f"corpus quant_claims. Narrow the attribution to "
                    f"only the receipts that carry the numeric."
                ),
            ))
    return issues


if __name__ == "__main__":
    sys.exit(main())
