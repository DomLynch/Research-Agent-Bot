"""Audit final manuscript artifacts for deterministic consistency defects."""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from direction_consistency import (
    abstract_direction_mismatches,
    metadata_prose_direction_mismatches,
    outcome_prose_direction_mismatches,
)
from agent.statistical_consistency import significance_wording_mismatch
from revision_coverage import APPRAISAL_RATINGS, appraisal_kinds

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
        str(r.get("receipt_id", "")).strip()
        for r in manifest.get("receipts", [])
        if isinstance(r, dict) and str(r.get("receipt_id", "")).strip()
    }
    missing_receipt_ids = sum(
        1 for r in manifest.get("receipts", [])
        if isinstance(r, dict) and not str(r.get("receipt_id", "")).strip()
    )
    if missing_receipt_ids:
        issues.append(ConsistencyIssue(
            id="C01-manifest-receipt-id-missing",
            severity="P2",
            issue_type="manifest_receipt_id_missing",
            auto_fixable=False,
            evidence=f"{missing_receipt_ids} receipt row(s) lack receipt_id",
            suggested_fix=(
                "Populate receipt_id in manifest rows when available. "
                "Advisory only; missing IDs must not crash or block publication."
            ),
        ))

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
    methods_body = re.sub(
        r"^###\s+What did NOT run\b.*?(?=^### |\Z)",
        "",
        methods_body,
        flags=re.DOTALL | re.MULTILINE,
    )
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


def _check_abstract_results_direction_consistency(
    paper: str, manifest: dict,
) -> list[ConsistencyIssue]:
    issues: list[ConsistencyIssue] = []
    for idx, mismatch in enumerate(abstract_direction_mismatches(paper, manifest), start=1):
        outcome = mismatch["outcome"]
        issues.append(ConsistencyIssue(
            id=f"C18-abstract-results-direction-{idx}",
            severity="P2",
            issue_type="abstract_results_direction_consistency",
            auto_fixable=True,
            evidence=(
                f"{outcome}: abstract={mismatch['abstract']} "
                f"results={mismatch['results']}"
            ),
            suggested_fix=(
                "Rewrite the Abstract direction-summary sentence from "
                "manifest receipt direction counts. Advisory only; never "
                "blocks publication."
            ),
        ))
    return issues


def _check_metadata_prose_direction_consistency(
    paper: str, manifest: dict,
) -> list[ConsistencyIssue]:
    issues: list[ConsistencyIssue] = []
    for idx, mismatch in enumerate(metadata_prose_direction_mismatches(paper, manifest), start=1):
        issues.append(ConsistencyIssue(
            id=f"C19-metadata-prose-direction-{idx}",
            severity="P2",
            issue_type="metadata_prose_direction_consistency",
            auto_fixable=False,
            evidence=mismatch["evidence"],
            suggested_fix=(
                f"Align prose direction for {mismatch['source']} with "
                f"metadata direction={mismatch['metadata']} rather than "
                f"prose={mismatch['prose']}. Advisory only; never blocks "
                "publication."
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


# --- Certification-integrity checks (2026-06-12) -------------------------
# Universal, cross-artifact checks that defend the certification surface: the
# "0 gate failures" stamp must never sit on top of (a) a citation dated in the
# future, (b) a named appraisal framework that was never run, (c) a
# "no <category> sources" claim the classification contradicts, or (d) a source
# count that disagrees across artifacts. Topic-agnostic — no domain vocabulary;
# categories and counts are read from the run's own manifest/registry.

# Formal appraisal frameworks a manuscript may *name*. Naming one asserts it
# was applied, which requires a populated appraisal artifact. A paper that
# names none simply never trips this check (works for any domain).
_APPRAISAL_FRAMEWORKS = ("RoB-2", "RoB 2", "ROBINS-I", "AMSTAR-2", "AMSTAR 2", "GRADE")


def _check_future_dated_citations(
    registry: dict | None, *, current_year: int,
) -> list[ConsistencyIssue]:
    """A cited source cannot be published after the run. Catches mis-parsed or
    fabricated publication years (e.g. 'Pragmatic 2035'). Reads source_year
    from the citation registry — the authoritative year field."""
    issues: list[ConsistencyIssue] = []
    rows = registry.values() if isinstance(registry, dict) else []
    for row in rows:
        if not isinstance(row, dict):
            continue
        year = row.get("source_year")
        if isinstance(year, int) and year > current_year:
            cite = str(
                row.get("body_citation") or row.get("reference_id")
                or row.get("receipt_id") or "source"
            )
            issues.append(ConsistencyIssue(
                id=f"C20-future-citation-{cite[:24].replace(' ', '_')}",
                severity="P1",
                issue_type="future_dated_citation",
                auto_fixable=False,
                evidence=f"{cite}: source_year={year} > run year {current_year}",
                suggested_fix=(
                    f"Citation '{cite}' is dated {year}, after the run year "
                    f"{current_year}. Correct the source year or drop the source; "
                    "a future-dated citation must never pass certification."
                ),
            ))
    return issues


def _appraisal_is_backed(paper: str, run_dir: Path | None, frameworks: set[str]) -> bool:
    """Require populated matching appraisal rows or an in-paper ratings table."""
    required, backed = {"grade" if name.casefold() == "grade" else "risk" for name in frameworks}, set[str]()
    if run_dir is not None:
        # rglob, not glob: the pipeline writes risk_of_bias.json to the run root
        # _organize_run_artifacts may relocate backing artifacts into audit/.
        for p in run_dir.rglob("*.json"):
            if not re.search(r"risk[_-]?of[_-]?bias|appraisal|grade[_-]?assessment", p.name, re.IGNORECASE):
                continue
            try:
                data = json.loads(p.read_text())
            except (OSError, ValueError):
                continue
            rows, grade = data if isinstance(data, list) else data.get("rows") if isinstance(data, dict) else None, p.name.casefold() == "grade_assessment.json"
            fields = ("final_certainty", "starting_certainty") if grade else ("overall_rating", "rating", "judgment")
            if isinstance(rows, list) and rows and all(isinstance(row, dict) and str(next((row.get(field) for field in fields if row.get(field)), "")).casefold().replace("_", " ") in APPRAISAL_RATINGS["grade" if grade else "risk"] for row in rows):
                backed.add("grade" if grade else "risk")
    section = re.search(
        r"(?im)^#{2,4}\s+(?:risk[ -]of[ -]bias|quality appraisal).*?(?=^#{2,4}\s|\Z)",
        paper, re.DOTALL,
    )
    if section:
        # Count only non-separator table rows: a header + >=1 data row means a
        # populated appraisal. An empty scaffold (header + `|---|`) does not.
        if sum(1 for row in re.findall(r"^\s*\|.*\|\s*$", section.group(0), re.MULTILINE) if not re.fullmatch(r"\s*\|[\s:|-]+\|\s*", row)) >= 2:
            backed.add("risk")
    return required <= backed


def _check_unbacked_appraisal_claim(
    paper: str, run_dir: Path | None,
) -> list[ConsistencyIssue]:
    """Naming a formal risk-of-bias / quality-appraisal framework asserts it
    was applied. Require backing — a populated risk-of-bias sidecar OR an
    in-paper appraisal table — else the methodology claim is unbacked."""
    scope = re.split(r"^##\s+References\b", paper, maxsplit=1, flags=re.M | re.I)[0]
    named = sorted({
        fw for fw in _APPRAISAL_FRAMEWORKS
        if fw != "GRADE" and re.search(rf"\b{re.escape(fw)}\b", scope, re.IGNORECASE)
    })
    if appraisal_kinds(scope)[1]:
        named.append("GRADE")
    if not named:
        return []
    if _appraisal_is_backed(paper, run_dir, set(named)):
        return []
    return [ConsistencyIssue(
        id="C21-unbacked-appraisal-claim",
        severity="P1",
        issue_type="unbacked_appraisal_claim",
        auto_fixable=False,
        evidence=f"names {', '.join(named)} but provides no populated appraisal (no ratings table or sidecar)",
        suggested_fix=(
            f"Populate a risk-of-bias / quality-appraisal artifact (one row per "
            f"source) or remove the {', '.join(named)} claim. A named appraisal "
            "framework must be backed by an actual appraisal."
        ),
    )]


def _check_source_classification_claims(
    paper: str, manifest: dict,
) -> list[ConsistencyIssue]:
    """A 'no <category> sources' claim must agree with the manifest's own
    classification. Universal: the category set is read from the receipts'
    directness values, never a hardcoded domain list."""
    receipts = [r for r in manifest.get("receipts", []) if isinstance(r, dict)]
    present = {str(r.get("directness") or "").lower() for r in receipts}
    present.discard("")
    if not present:
        return []
    issues: list[ConsistencyIssue] = []
    patterns = (
        re.compile(r"\bno\s+([a-z][a-z-]+)\s+(?:sources?|studies)\b", re.IGNORECASE),
        re.compile(
            r"\bno\s+sources?\s+(?:were\s+)?classified\s+(?:primarily\s+)?as\s+([a-z][a-z-]+)",
            re.IGNORECASE,
        ),
    )
    for pat in patterns:
        for m in pat.finditer(paper):
            category = m.group(1).lower()
            if category in present:
                n = sum(
                    1 for r in receipts
                    if str(r.get("directness") or "").lower() == category
                )
                issues.append(ConsistencyIssue(
                    id=f"C22-classification-claim-{m.start()}",
                    severity="P2",
                    issue_type="source_classification_claim_contradiction",
                    auto_fixable=False,
                    evidence=paper[max(0, m.start() - 20):m.end() + 20].strip()[:200],
                    suggested_fix=(
                        f"Prose claims no '{category}' sources, but the "
                        f"classification table has {n}. Align the claim with the table."
                    ),
                ))
    return issues


def _check_source_count_consistency(
    paper: str, manifest: dict,
) -> list[ConsistencyIssue]:
    """The 'included/retained' source count stated in prose must equal the
    manifest receipt count (catches the 56-vs-59 cross-artifact drift class).
    Only the *included* count is compared — 'identified/screened' search yield
    is legitimately larger and is excluded."""
    n_receipts = manifest.get("n_receipts")
    if not isinstance(n_receipts, int) or n_receipts <= 0:
        n_receipts = len([r for r in manifest.get("receipts", []) if isinstance(r, dict)])
    if not n_receipts:
        return []
    issues: list[ConsistencyIssue] = []
    pat = re.compile(
        r"\b(\d{1,4})\s+(?:sources?|studies|papers|references|receipts)\s+"
        r"(?:were\s+)?(?:included|retained|synthesi[sz]ed|admitted)\b",
        re.IGNORECASE,
    )
    for m in pat.finditer(paper):
        stated = int(m.group(1))
        if stated != n_receipts:
            issues.append(ConsistencyIssue(
                id=f"C23-source-count-{m.start()}",
                severity="P2",
                issue_type="source_count_inconsistency",
                auto_fixable=False,
                evidence=paper[max(0, m.start() - 20):m.end() + 20].strip()[:200],
                suggested_fix=(
                    f"Prose states {stated} included sources but the manifest has "
                    f"{n_receipts} receipts; reconcile to a single number."
                ),
            ))
    return issues


# Review markers (the source IS a secondary synthesis) vs primary-study
# markers. Review markers WIN: a meta-analysis *of* randomized trials
# legitimately names RCTs in its title, so a trial mention does not make a
# source primary. This inverse-aware rule is why the naive "title says trial ->
# not a review" check would mis-flag the meta-analyses that dominate
# evidence-map corpora. Universal study-design vocabulary, no topic terms.
_REVIEW_TITLE_RE = re.compile(
    r"\b(systematic review|meta-?analys(?:is|es)?|umbrella review|"
    r"scoping review|pooled analys(?:is|es)?|narrative review|review of)\b",
    re.IGNORECASE,
)
_PRIMARY_TITLE_RE = re.compile(
    r"\b(randomi[sz]ed controlled trial|\bRCT\b|controlled clinical (?:study|trial)|"
    r"double-blind|placebo-controlled|crossover trial|cohort study)\b", re.IGNORECASE,
)


def _check_directness_coding(manifest: dict) -> list[ConsistencyIssue]:
    """A source's coded `directness` must agree with what its title says it is.
    Flags two real mis-codings: a review-titled source coded `direct`, or a
    primary-study-titled source (with NO review markers) coded `review`. Review
    markers win so meta-analyses of RCTs stay `review` and are not mis-flagged."""
    issues: list[ConsistencyIssue] = []
    for r in manifest.get("receipts", []):
        if not isinstance(r, dict):
            continue
        title = str(r.get("source_title") or r.get("body_citation") or "")
        if not title:
            continue
        d = str(r.get("directness") or "").lower()
        is_review = bool(_REVIEW_TITLE_RE.search(title))
        is_primary = bool(_PRIMARY_TITLE_RE.search(title))
        problem = ""
        if d == "direct" and is_review:
            problem = "review-titled source coded directness=direct"
        elif d == "review" and is_primary and not is_review:
            problem = f"primary-study-titled source coded directness={d}"
        if problem:
            issues.append(ConsistencyIssue(
                id=f"C24-directness-{str(r.get('receipt_id'))[:24]}",
                severity="P2",
                issue_type="directness_coding_mismatch",
                auto_fixable=False,
                evidence=f"{problem}: {title[:120]}",
                suggested_fix=(
                    "Reconcile the primary/review role with the source's study design; "
                    "review markers (systematic review / meta-analysis) win over "
                    "a trial mention."
                ),
            ))
    return issues


def _check_outcome_direction_overclaim(
    paper: str, manifest: dict,
) -> list[ConsistencyIssue]:
    """C20: prose that overclaims an outcome class's direction relative to its
    receipts' coded effect_direction ("positive for both" / "no source reported
    null or negative" when the class contains a null/negative receipt) is a hard
    prose-vs-data contradiction. Unlike the advisory per-token C19, this is a
    publish blocker (P1) — the verifiable record must not refute the narrative."""
    issues: list[ConsistencyIssue] = []
    for idx, mismatch in enumerate(
        outcome_prose_direction_mismatches(paper, manifest), start=1,
    ):
        issues.append(ConsistencyIssue(
            id=f"C20-outcome-direction-overclaim-{idx}",
            severity="P1",
            issue_type="outcome_direction_overclaim",
            auto_fixable=False,
            evidence=mismatch["evidence"],
            suggested_fix=(
                f"Prose for the {mismatch['outcome']} outcome class overstates "
                f"direction ({mismatch['claim']}) versus its receipts "
                f"(directions: {mismatch['directions']}). Restate to match the "
                "coded effect_direction — acknowledge the null/negative source — "
                "before publication."
            ),
        ))
    return issues


def _check_prose_data_coherence(paper: str) -> list[ConsistencyIssue]:
    """Flag weak significance language with p<0.01, plus an unqualified
    non-significant label with p<0.05. Explicit multiplicity thresholds are
    exempt because a nominal p<0.05 can correctly miss an adjusted threshold.
    For example, "a marginal adiponectin signal (P<0.001)" is contradictory;
    this is the prose-vs-data incoherence flagged on the null-coded Tavakoli
    receipt. Effect-SIZE words (modest/small) are intentionally excluded — a
    small effect can be highly significant. Flag-only (P2). Universal —
    statistical English only, no topic/author terms."""
    body = re.split(r"(?im)^##\s+References\b", paper, maxsplit=1)[0]
    out: list[ConsistencyIssue] = []
    seen: set[str] = set()
    for sentence in re.split(r"(?<=[.!?])\s+", body):
        if not significance_wording_mismatch(sentence):
            continue
        key = sentence.strip()[:80]
        if key in seen:
            continue
        seen.add(key)
        out.append(ConsistencyIssue(
            id="C22-prose-data-incoherence",
            severity="P2",
            issue_type="prose_data_incoherence",
            auto_fixable=False,
            evidence=f"significance qualifier contradicts its p-value in one sentence: {key}",
            suggested_fix=(
                "Align the significance label with the reported p-value, or state "
                "the adjusted threshold that makes the comparison non-significant."
            ),
        ))
    return out


def run_audit(
    paper_md: str, manifest: dict, audit: dict, audit_md_text: str = "",
    *, registry: dict | None = None, run_dir: Path | None = None,
    current_year: int | None = None,
) -> list[ConsistencyIssue]:
    issues: list[ConsistencyIssue] = []
    year = current_year if current_year is not None else datetime.now(timezone.utc).year
    # Load the citation registry from the run dir when the caller didn't pass
    # one, so pipeline call sites only need to thread `run_dir`.
    if registry is None and run_dir is not None:
        try:
            registry = json.loads((run_dir / "citation_registry.json").read_text())
        except (OSError, ValueError):
            registry = None
    issues.extend(_check_future_dated_citations(registry, current_year=year))
    issues.extend(_check_unbacked_appraisal_claim(paper_md, run_dir))
    issues.extend(_check_prose_data_coherence(paper_md))
    issues.extend(_check_source_classification_claims(paper_md, manifest))
    issues.extend(_check_source_count_consistency(paper_md, manifest))
    issues.extend(_check_directness_coding(manifest))
    issues.extend(_check_manifest_paper_consistency(paper_md, manifest))
    issues.extend(_check_stale_methods(paper_md, manifest))
    issues.extend(_check_stale_spar_in_prose(paper_md, manifest))  # Fix #29
    issues.extend(_check_internal_tier_labels_in_prose(paper_md))  # Fix #33
    issues.extend(_check_duplicate_references(paper_md))
    issues.extend(_check_malformed_headers(paper_md))
    issues.extend(_check_repair_artifacts(paper_md))
    issues.extend(_check_audit_verdict_gate(audit, audit_md_text))
    issues.extend(_check_abstract_results_direction_consistency(
        paper_md, manifest,
    ))
    issues.extend(_check_metadata_prose_direction_consistency(
        paper_md, manifest,
    ))
    issues.extend(_check_outcome_direction_overclaim(paper_md, manifest))
    issues.extend(_check_broken_paper_id_citations(paper_md))
    issues.extend(_check_surface_polish(paper_md))  # Fix #13
    issues.extend(_check_background_lit_unsourced(paper_md, manifest))  # Fix #16
    issues.extend(_check_surface_render_lint(paper_md))  # Fix #22
    issues.extend(_check_change_value_misread(paper_md, manifest))  # Fix #37
    issues.extend(_check_change_value_anaphor_misread(  # Fix #54
        paper_md, manifest,
    ))
    issues.extend(_check_change_value_paragraph_threshold(  # Fix #58
        paper_md, manifest,
    ))
    issues.extend(_check_abstract_over_grouping(paper_md, manifest))  # Fix #38
    issues.extend(_check_numeric_role_guard(  # 2026-05-05 universal
        paper_md, manifest, run_dir=run_dir,
    ))
    return issues


# Universal Numeric Role Guard (2026-05-05): catches three classes of
# numeric-misinterpretation in prose that earlier point-fixes
# (#54/#57/#58/#58c) addressed only as specific patterns. See
# scripts/numeric_role_guard.py for the full rule set:
#   - arithmetic_violation: 'X below Y' when X > Y (or vice versa)
#   - role_mismatch: change-score compared to absolute threshold
#   - malformed_subject: 'the X group <verb> ... for the X group <was>'
#     repair-artifact pattern
def _check_numeric_role_guard(
    paper_md: str, manifest: dict | None = None, *, run_dir: Path | None = None,
) -> list[ConsistencyIssue]:
    import json as _json
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from numeric_role_guard import scan_paper as _scan

    # Slice 7 step 1: also feed manifest + bg_lit + quant_claims_dir
    # so the source-context drift check runs in addition to the
    # arithmetic / role / malformed checks. Best-effort: when
    # any of the registries are missing, drift simply doesn't fire
    # (fail-soft, no false positives).
    repo = Path(__file__).resolve().parent.parent
    bg_lit_path = repo / "docs" / "background_literature.json"
    bg_lit_registry: dict | None = None
    if bg_lit_path.exists():
        try:
            bg_lit_registry = _json.loads(bg_lit_path.read_text())
        except (OSError, ValueError):
            bg_lit_registry = None
    # Try to find a manifest sitting next to the paper. The audit
    # is invoked from various places; if manifest isn't readily
    # available, drift defers silently.
    manifest_obj: dict | None = manifest
    quant_claims_dir = None
    if run_dir is not None:
        snapshot_quant = run_dir / "revision_evidence_snapshot" / "quant_claims"
        if snapshot_quant.is_dir():
            quant_claims_dir = snapshot_quant
    # Topic resolution: prefer the explicit manifest topic so standalone
    # re-audits use the same quant_claims pool as the run. Fall back to
    # run_v06_synthesis's active topic during live orchestration.
    topic = None
    if isinstance(manifest_obj, dict):
        topic = manifest_obj.get("topic")
    if topic and quant_claims_dir is None:
        quant_claims_dir = (
            repo / "docs" / "quality-reference" / str(topic)
            / "quant_claims"
        )
    try:
        sys.path.insert(0, str(repo / "scripts"))
        import run_v06_synthesis as _orch
        active_topic = getattr(_orch, "_ACTIVE_TOPIC", None)
        if quant_claims_dir is None and active_topic:
            quant_claims_dir = (
                repo / "docs" / "quality-reference" / active_topic
                / "quant_claims"
            )
            mf_obj = getattr(_orch, "_ACTIVE_MANIFEST", None)
            if manifest_obj is None and isinstance(mf_obj, dict):
                manifest_obj = mf_obj
    except (ImportError, AttributeError):
        pass

    out: list[ConsistencyIssue] = []
    for issue in _scan(
        paper_md,
        manifest=manifest_obj,
        bg_lit_registry=bg_lit_registry,
        quant_claims_dir=quant_claims_dir,
    ):
        out.append(ConsistencyIssue(
            id=f"C14-numeric-role-{abs(hash(issue.sentence)) % 99999:05d}",
            severity=issue.severity,
            issue_type=issue.issue_type,
            evidence=issue.sentence[:200],
            suggested_fix=issue.suggested_fix,
            auto_fixable=issue.severity == "P1",
        ))
    return out


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
            "sentence_fragment_single_letter",
            "sentence_fragment_lowercase_start",
            "sentence_fragment_spliced_word",
            "sentence_fragment_lowercase_line_start",
            "blank_table_row",
            "malformed_table_row",
            "unterminated_paragraph",
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


def _check_background_lit_unsourced(
    paper_md: str,
    manifest: dict | None = None,
) -> list[ConsistencyIssue]:
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
        repo = Path(__file__).resolve().parent.parent
        topic = (manifest or {}).get("topic") if isinstance(manifest, dict) else None
        quant_claims_dir = (
            repo / "docs" / "quality-reference" / str(topic) / "quant_claims"
            if topic else None
        )
        unsourced = _bg.find_unsourced_background_uses(
            paper_md,
            registry,
            manifest=manifest,
            quant_claims_dir=quant_claims_dir,
        )
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

# "Witham et al. 2025 (2025)" → duplicate citation year artifact.
_DUPLICATE_CITATION_YEAR_RE = re.compile(
    r"\b([A-Z][a-zA-Z]+(?:\s+et\s+al\.)?)\s+(\d{4})\s+\(\2\)"
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
    haystack = "\n".join(
        line for line in haystack.splitlines()
        if not re.match(r"^\s{4,}\S", line)
    )

    # Malformed words
    for kind, pat in _MALFORMED_WORD_PATTERNS:
        for m in pat.finditer(haystack):
            # Uppercase acronyms/cert labels such as AAA are intentional,
            # not misspelled prose tokens.
            if m.group(0).isupper():
                continue
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

    # Duplicate citation year
    for m in _DUPLICATE_CITATION_YEAR_RE.finditer(haystack):
        issues.append(ConsistencyIssue(
            id=f"C08-dup-cite-year-{m.start()}",
            severity="P2",
            issue_type="duplicate_citation_year",
            auto_fixable=True,
            evidence=haystack[max(0, m.start() - 20):m.end() + 20],
            suggested_fix=(
                f"`{m.group(1)} {m.group(2)} ({m.group(2)})` → "
                f"`{m.group(1)} {m.group(2)}`"
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
        r"\b(\w{3,})[ \t]+\1\b", haystack, re.IGNORECASE,
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
    registry_path = paper_path.parent / "citation_registry.json"
    registry: dict = (
        json.loads(registry_path.read_text()) if registry_path.exists() else {}
    )

    issues = run_audit(
        paper, manifest, audit, audit_md_text,
        registry=registry, run_dir=paper_path.parent,
    )
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
_CHANGE_SPEED_VALUE_RE = re.compile(r"\b\d+(?:\.\d+)?\s*m/s\b", re.IGNORECASE)
_ABSOLUTE_VALUE_PHRASES = (
    # Threshold-comparison patterns
    "falls below", "below the", "above the", "below clinically",
    "below threshold", "below thresholds", "remained below",
    "below clinically meaningful", "below clinically significant",
    "fell below", "below the cutoff", "below the cut-off",
    "below the threshold",
    # Absolute-value framing
    "value of", "level of", "absolute",
    # Inferred-meaning verbs
    "indicates", "signals", "reflects",
)
# Refactor 2026-05-04 / Fix #57: change-word PROXIMITY requirement.
# A misread can hide a change-word elsewhere in a long sentence
# (e.g. "no change in frailty classification, AND walk speed was
# reported at 0.13 m/s, which remained below clinical thresholds").
# The change-word "no change" applies to FRAILTY, not the 0.13 m/s
# walk-speed value. The change-word must be NEAR the numeric to
# count as a proper hedge.
_CHANGE_WORD_PROXIMITY_CHARS = 40  # ±40 chars around the numeric


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
            # change-words PROXIMITY-CLOSE to the numeric.
            #
            # Fix #57: proximity check. A long sentence may have a
            # change-word that applies to a DIFFERENT metric ("no
            # change in frailty classification, and walk speed was
            # reported at 0.13 m/s, which remained below..."). The
            # change-word must be within ±40 chars of the numeric
            # to count as a hedge for THIS numeric.
            has_absolute = any(
                p in sent_lc for p in _ABSOLUTE_VALUE_PHRASES
            )
            num_idx = sent_lc.find(numeric.lower())
            window_start = max(0, num_idx - _CHANGE_WORD_PROXIMITY_CHARS)
            window_end = min(
                len(sent_lc),
                num_idx + len(numeric) + _CHANGE_WORD_PROXIMITY_CHARS,
            )
            window = sent_lc[window_start:window_end]
            has_change = any(w in window for w in change_words)
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


# Fix #58: PARAGRAPH-level threshold-comparison detector.
#
# Reviewer feedback after Fix #57: "the detector must catch any
# sentence/paragraph where 0.13 m/s is compared to 0.8 m/s,
# 0.6 m/s, threshold, frailty, or mobility limitation, regardless
# of wording."
#
# Where C13 (Fix #37) is per-sentence and Fix #54 (C13b) is
# cross-sentence anaphoric, Fix #58 (C13c) is paragraph-scoped:
# if a corpus-known change-numeric appears ANYWHERE in a paragraph
# AND the paragraph ALSO contains a threshold-comparison marker,
# the paragraph as a whole risks misreading the change-value as
# absolute.
#
# This is the strictest of the three checks. It will flag some
# legitimate paragraphs (false positives) — that's the trade. The
# previous false-negatives leaked a P1 misread despite C13 + Fix
# #54; reviewer demanded the broader net.

_THRESHOLD_MARKERS = (
    # Explicit threshold/cutoff terms (precise — these always
    # signal comparison-to-norm framing)
    "threshold", "thresholds", "cutoff", "cut-off", "cut off",
    "clinical threshold", "clinically meaningful threshold",
    "minimal clinically important", "frailty threshold",
    "frailty cutoff", "mobility limitation",
    "mobility-limitation",
    # Common comparator gait-speed values in metformin/aging papers
    # (exact numeric strings, no false-positive risk)
    "0.8 m/s", "0.6 m/s", "0.5 m/s", "1.0 m/s", "0.78 m/s",
    # Comparison-structure phrases (require below/above/compared)
    "below the cutoff", "below clinical", "below normative",
    "below the normative", "fall below", "falls below",
    "remained below", "compared to the threshold",
    "compared to clinical",
)
# Refactor 2026-05-04 / Fix #58 follow-up: removed bare 'frailty'
# from the marker list. 'Frailty' as a topic word (in trial-
# enrollment descriptions like 'frail or sarcopenic adults') was
# false-positive flagging paragraphs that didn't actually compare
# numerics to thresholds. The 'frailty threshold' / 'frailty
# cutoff' compound forms ARE markers (those imply comparison);
# the bare word is not.


def _check_change_value_paragraph_threshold(
    paper_md: str, manifest: dict,
) -> list[ConsistencyIssue]:
    """Fix #58 (C13c): flag paragraphs where a corpus change-numeric
    co-occurs with any threshold-comparison marker.

    The change-numeric is treated as MISREAD-RISK regardless of
    wording — broader net than C13 / Fix #54. Severity P1, NOT
    auto-fixable (the rewrite is non-trivial; flagging surfaces
    it to the agent for explicit handling).

    Reviewer rationale: 0.13 m/s vs 0.8 m/s threshold IS the
    clinical-significance question. If a paragraph juxtaposes the
    corpus's change-value with the field's gait-speed threshold,
    the paragraph IS making a comparison whether the wording says
    so explicitly or not."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import run_v06_synthesis as _orch
        quant_dir = _orch.QUANT_DIR
    except (ImportError, AttributeError):
        return []
    if not quant_dir.exists():
        return []
    # Build the change-numeric set (corpus high-conf + change-word
    # in source sentence).
    change_numerics: set[str] = set()
    change_value_words: dict[str, set[str]] = {}
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
            if change_hits:
                change_numerics.add(raw)
                change_value_words.setdefault(raw, set()).update(
                    change_hits
                )
    if not change_numerics:
        return []
    issues: list[ConsistencyIssue] = []
    paragraphs = paper_md.split("\n\n")
    # Extract unit from a change-numeric, e.g. "0.13 m/s" → "m/s"
    unit_re = re.compile(r"\d+\.?\d*\s*([a-zA-Z/μ]+)")
    for para in paragraphs:
        para_lc = para.lower()
        # Skip tables (per Fix #21 follow-up convention)
        lines = [ln for ln in para.splitlines() if ln.strip()]
        if lines and (
            sum(1 for ln in lines if ln.lstrip().startswith("|"))
            / len(lines) >= 0.5
        ):
            continue
        # Skip section headers + Limitations (Limitations explicitly
        # discusses the change-as-change framing — that's allowed)
        if "## limitations" in para_lc:
            continue
        for numeric in change_numerics:
            if numeric not in para:
                continue
            # Refactor 2026-05-04 / Fix #58 follow-up: require the
            # change-numeric to share a UNIT with a threshold-marker
            # in the paragraph. Without this, p-values (0.05) and
            # p-value 'thresholds' (statistical-significance) get
            # falsely flagged. Only flag if the change-numeric has
            # an explicit unit (m/s, kg, mg, etc.) AND the paragraph
            # contains a threshold-marker that includes that unit.
            num_unit_m = unit_re.search(numeric)
            if not num_unit_m:
                continue  # no unit — not a comparable measurement
            num_unit = num_unit_m.group(1).lower()
            # Skip p-values (no unit, but caught above)
            # Build "unit-compatible threshold markers": markers that
            # contain the same unit OR generic explicit-comparison
            # phrases ('below the cutoff', 'fall below').
            generic_comparison_phrases = (
                "below the cutoff", "below clinical",
                "below normative", "below the normative",
                "fall below", "falls below", "remained below",
                "compared to the threshold",
                "compared to clinical",
                "minimal clinically important",
            )
            has_unit_match = any(
                num_unit in m.lower()
                for m in _THRESHOLD_MARKERS
                if num_unit in m.lower()
            )
            has_generic_comparison = any(
                p in para_lc for p in generic_comparison_phrases
            )
            if not (has_unit_match and has_generic_comparison):
                # Tighter: require BOTH a unit-matched threshold
                # marker (e.g. "0.8 m/s") AND a comparison phrase
                # ("fall below", "below clinical")
                # Check if a unit-matched threshold marker is present
                unit_matched_in_para = any(
                    m in para_lc and num_unit in m.lower()
                    for m in _THRESHOLD_MARKERS
                )
                if not unit_matched_in_para:
                    continue
            has_threshold = True
            if not has_threshold:
                continue
            # Does the paragraph repeatedly affirm the change-word
            # framing (e.g. "the change of X" or "improvement of X")?
            # If the change-word is within ±60 chars of the numeric
            # at least once, the paragraph is hedging properly.
            num_idx = para_lc.find(numeric.lower())
            window_start = max(0, num_idx - 60)
            window_end = min(
                len(para_lc), num_idx + len(numeric) + 60,
            )
            window = para_lc[window_start:window_end]
            # Refactor 2026-05-04: accept ANY word from the GLOBAL
            # _CHANGE_WORDS set within ±60 chars of the numeric.
            # Corpus-source-specific subset was too strict — Witham's
            # source used 'improvement'/'difference', but writer's
            # natural prose says 'change of 0.13 m/s'. 'Change' is in
            # _CHANGE_WORDS but wasn't in Witham's specific set, so
            # the proximity check missed the legitimate hedge.
            if any(w in window for w in _CHANGE_WORDS):
                continue
            # Pull source-specific words for the message context only
            change_words = change_value_words.get(numeric, set())
            # Hits: this paragraph juxtaposes a change-numeric with
            # a threshold marker, with no nearby change-word hedge.
            snippet = para.strip()[:240]
            issues.append(ConsistencyIssue(
                id=f"C13c-paragraph-threshold-{hash(para) & 0xffffff}",
                severity="P1",
                issue_type="change_value_paragraph_threshold",
                auto_fixable=True,  # Fix #58 ships an auto-strip
                evidence=snippet,
                suggested_fix=(
                    f"Paragraph juxtaposes change-numeric "
                    f"{numeric!r} with threshold-comparison "
                    f"language without naming it as a "
                    f"change/difference value within "
                    f"±60 chars. The corpus says this numeric is "
                    f"a change/improvement value (context word(s): "
                    f"{sorted(change_words)}). Auto-strip removes "
                    f"the threshold-comparison sentence(s) from "
                    f"the paragraph; the change-numeric sentence "
                    f"is preserved."
                ),
            ))
            break  # one finding per paragraph
    return issues


# Fix #54: cross-sentence anaphoric misread detection.
#
# C13 (Fix #37) is per-sentence: it catches "0.13 m/s improvement"
# rendered as "value of 0.13 m/s, below threshold". But the reviewer
# caught a CROSS-SENTENCE variant in fix53-verify line 156 that
# slipped through:
#
#   Sentence A: "...placebo group showing no change in walk speed
#                 (0.13 m/s)..."   [has "change" word → C13 clears]
#   Sentence B: "This walk speed value is below the 0.8 m/s
#                 threshold..."   [no 0.13 m/s → C13 doesn't check]
#
# The misread is the implicit anaphoric reference: "this walk speed
# value" refers back to (0.13 m/s), and the threshold-comparison
# treats it as absolute. Fix #54 detects this paragraph-level pattern.
#
# Anaphora cues: "this <noun> value/figure/number/result/measurement"
# Threshold cues: "below the <number>", "above the <number>",
#                 "threshold", "cutoff", "cut-off", "frailty"

_ANAPHOR_RE = re.compile(
    r"\bthis\s+\w+(?:\s+\w+)?\s+"
    r"(?:value|figure|number|result|measurement|score|level|rate)"
    r"\b",
    re.IGNORECASE,
)
# Looser threshold pattern that catches "below the threshold" phrasing
# even when the number doesn't immediately follow "below".
_THRESHOLD_KEYWORD_RE = re.compile(
    r"\b(?:below\s+(?:the|a)\s+\d|"
    r"above\s+(?:the|a)\s+\d|"
    r"threshold|cutoff|cut-off|"
    r"frailty\s+(?:threshold|cutoff)|"
    r"clinically\s+meaningful)\b",
    re.IGNORECASE,
)


def _check_change_value_anaphor_misread(
    paper_md: str, manifest: dict,
) -> list[ConsistencyIssue]:
    """Fix #54: detect cross-sentence anaphoric misreads of
    change-value numerics.

    Walks paragraph-by-paragraph. For each paragraph that contains
    a known change-value numeric (per the corpus), checks subsequent
    sentences for anaphoric reference + threshold-comparison
    phrasing. Flags as P1 when found — the implicit interpretation
    treats the change as an absolute value.

    The reviewer-flagged exemplar:
      'walk speed (0.13 m/s)... This walk speed value is below the
       0.8 m/s threshold...'
    is two sentences; sentence 1 has 'change' so per-sentence C13
    clears it; sentence 2 has no 0.13 m/s so C13 never inspects it.
    Fix #54 spans the boundary."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import run_v06_synthesis as _orch
        quant_dir = _orch.QUANT_DIR
    except (ImportError, AttributeError):
        return []
    if not quant_dir.exists():
        return []
    # Build the same change-value map as C13 (Fix #37).
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
            if change_hits:
                change_value_map.setdefault(raw, set()).update(change_hits)
    if not change_value_map:
        return []
    issues: list[ConsistencyIssue] = []
    sent_split = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")
    paragraphs = paper_md.split("\n\n")
    for para in paragraphs:
        para_stripped = para.strip()
        # Skip tables (many rows starting with `|`).
        lines = [ln for ln in para_stripped.splitlines() if ln.strip()]
        if lines and (
            sum(1 for ln in lines if ln.lstrip().startswith("|"))
            / len(lines) >= 0.5
        ):
            continue
        # Skip code blocks
        if para_stripped.startswith("```"):
            continue
        sentences = sent_split.split(para_stripped)
        if len(sentences) < 2:
            continue
        # Find sentences that contain change-value numerics
        change_sent_indices: dict[str, int] = {}
        for i, sent in enumerate(sentences):
            sent_lc = sent.lower()
            for numeric in change_value_map:
                if numeric in sent and numeric not in change_sent_indices:
                    change_sent_indices[numeric] = i
            change_hits = {w for w in _CHANGE_WORDS if w in sent_lc}
            if change_hits:
                for numeric in _CHANGE_SPEED_VALUE_RE.findall(sent):
                    change_sent_indices.setdefault(numeric, i)
                    change_value_map.setdefault(numeric, set()).update(change_hits)
        if not change_sent_indices:
            continue
        # Now look at subsequent sentences for anaphor + threshold
        for i, sent in enumerate(sentences):
            sent_lc = sent.lower()
            # Must come AFTER a change-numeric sentence
            earlier_numerics = [
                n for n, idx in change_sent_indices.items()
                if idx < i
            ]
            if not earlier_numerics:
                continue
            # Anaphoric reference + threshold-comparison both present
            has_anaphor = bool(_ANAPHOR_RE.search(sent))
            has_threshold = bool(_THRESHOLD_KEYWORD_RE.search(sent))
            if not (has_anaphor and has_threshold):
                continue
            # And must not contain the change-word itself (defence:
            # "this represents a change of X below threshold" is fine)
            change_words = set()
            for n in earlier_numerics:
                change_words.update(change_value_map[n])
            if any(w in sent_lc for w in change_words):
                continue
            snippet = sent.strip()[:220]
            numerics_str = ", ".join(repr(n) for n in earlier_numerics)
            issues.append(ConsistencyIssue(
                id=f"C13b-anaphor-misread-{hash(sent) & 0xffffff}",
                severity="P1",
                issue_type="change_value_anaphor_misread",
                auto_fixable=True,  # Fix #54 ships an auto-strip
                evidence=snippet,
                suggested_fix=(
                    f"Sentence anaphorically refers back to a "
                    f"change-value numeric ({numerics_str}) from an "
                    f"earlier sentence in the same paragraph and "
                    f"treats it as an absolute value via "
                    f"threshold-comparison phrasing. The corpus "
                    f"source describes the numeric as a change/"
                    f"improvement/difference, not an absolute. Fix "
                    f"#54: rewrite to 'change in <metric>' or strip "
                    f"the threshold-comparison sentence."
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
