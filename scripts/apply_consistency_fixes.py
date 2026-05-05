"""Day 10.17 Phase 6.2 Layer 1 — deterministic fixer.

Reads <paper>.consistency.json (from final_consistency_audit.py) and
applies fixes for issues marked auto_fixable. Per fix type:

  duplicate_section          → remove all but the first ## References
  malformed_header           → '### ### Foo' → '### Foo'
  repair_artifact            → strip ' (potentially)' inline marker
                                 (no replacement — sentence-level hedges
                                 already exist elsewhere in the prose)
  stale_method_boilerplate   → strip the offending paragraph from Methods
                                 OR replace with a v0.6 adapter sentence
                                 (handled paragraph-by-paragraph)
  audit_verdict_overclaim    → rewrite audit.md verdict heading
  paper_id_in_body           → flag-only (needs receipt list, deferred to
                                 Layer 2 / Grok or human review)

Every fix logged to <paper>.fixed_log.json.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

__all__ = ["apply_fixes", "main"]


_POTENTIALLY_RE = re.compile(r"\s*\(potentially\)", re.IGNORECASE)
_DOUBLE_HASH_RE = re.compile(r"^(#{2,4})\s+#{2,4}\s+", re.MULTILINE)
# Sentences that contain stale-SPAR phrases — strip the entire sentence.
# Fix #29: extended phrase set per reviewer — "spar quarantine"
# (noun form), "spar-rejected", "rejected evidence" added.
# Phrases like bare "quarantined" are too broad to ban
# unconditionally; the regex below pairs them with SPAR context.
_STALE_SPAR_SENT_RE = re.compile(
    r"[^.!?]*\b(?:spar\s+adjudication|rejected\s+by\s+spar|"
    r"spar-?rejected|spar-?quarantined?|spar\s+quarantine|"
    r"rejected\s+evidence|"
    r"claim\s+receipts?|receipt\s+clusters?|"
    r"receipt-level\s+spar|synthesis-level\s+spar|"
    r"trust-spine\s+multi-receipt)\b[^.!?]*[.!?]",
    re.IGNORECASE,
)


_DEPTH_PROTECTED_SECTIONS = {
    # Sections whose post-strip word count is policed by Fix #53
    # depth-preservation guard. Floors are SAFETY MARGINS above the
    # audit thresholds (Q11=800, Q12=800), so a tiny drift below
    # margin doesn't immediately break the audit gate. Limitations
    # + Conclusion added per reviewer request — they're analytical-
    # core too and easy strip-targets when claim-strength repair
    # fires on hedged language.
    "Discussion": 850,            # Q11 audit floor 800 + 50 margin
    "Cross-Domain Synthesis": 850,  # Q12 audit floor 800 + 50 margin
    "Limitations": 200,           # analytical-core, not Q-gated
    "Conclusion": 150,            # analytical-core, not Q-gated
}


def _section_word_count(paper: str, heading: str) -> int:
    """Word count for one ## heading section (header line excluded)."""
    m = re.search(
        rf"^##\s+{re.escape(heading)}(.*?)(?=^##\s+\w|\Z)",
        paper, re.DOTALL | re.MULTILINE,
    )
    if not m:
        return 0
    return len(m.group(1).split())


def _extract_section(paper: str, heading: str) -> tuple[int, int, str]:
    """Return (start_offset, end_offset, body) of a ## heading
    section. Used by Fix #53 to roll back over-aggressive strips."""
    m = re.search(
        rf"^##\s+{re.escape(heading)}(.*?)(?=^##\s+\w|\Z)",
        paper, re.DOTALL | re.MULTILINE,
    )
    if not m:
        return -1, -1, ""
    return m.start(), m.end(), m.group(0)


def apply_fixes(
    paper_md: str, issues: list[dict],
) -> tuple[str, list[dict]]:
    """Apply auto-fixable patches; return (new_md, log).

    Fix #53: snapshots Discussion, Cross-Domain Synthesis,
    Limitations + Conclusion BEFORE any strip pass runs. After all
    strips, if a protected section has dropped below its safety-
    margin floor (Discussion/CD: 850 = Q11/Q12 800 + 50 margin;
    Limitations: 200; Conclusion: 150), the section is restored to
    its pre-strip state. Trust-spine deletion safety +
    analytical-depth preservation."""
    new_md = paper_md
    log: list[dict] = []
    # Snapshot for Fix #53 depth-preservation guard
    pre_strip_sections: dict[str, str] = {}
    for heading in _DEPTH_PROTECTED_SECTIONS:
        _s, _e, body = _extract_section(new_md, heading)
        if body:
            pre_strip_sections[heading] = body

    # 1. Strip (potentially) inline artifacts (highest count, run first).
    pot_count_before = len(_POTENTIALLY_RE.findall(new_md))
    new_md = _POTENTIALLY_RE.sub("", new_md)
    if pot_count_before:
        log.append({
            "fix_type": "repair_artifact",
            "n_changes": pot_count_before,
            "description": "stripped ' (potentially)' inline artifacts",
        })

    # 2. Fix '### ###' / '## ##' malformed headers.
    bad_hdr_count = len(_DOUBLE_HASH_RE.findall(new_md))
    new_md = _DOUBLE_HASH_RE.sub(r"\1 ", new_md)
    if bad_hdr_count:
        log.append({
            "fix_type": "malformed_header",
            "n_changes": bad_hdr_count,
            "description": "collapsed '### ###' / '## ##' to single tier",
        })

    # 3. Strip stale-SPAR sentences from Methods.
    stale_matches = list(_STALE_SPAR_SENT_RE.finditer(new_md))
    if stale_matches:
        # Replace each sentence with a single-line v0.6 disclaimer (only
        # for the first occurrence; subsequent ones are simply removed).
        # Avoid blacklisted phrase 'SPAR adjudication' so the same
        # consistency audit doesn't re-flag this disclaimer on the
        # next run. Use 'multi-receipt adjudication pipeline'.
        replacement = (
            "This synthesis used the v0.6 quant-claim adapter "
            "(scripts/run_v06_synthesis.py); no multi-receipt "
            "adjudication pipeline ran."
        )
        # Reviewer-fix HIGH 1: mutable-default lambda was sharing
        # state across apply_fixes() invocations. Use a local closure.
        state = {"first": True}

        def _replace_stale(_m: "re.Match[str]") -> str:
            return replacement if state.pop("first", False) else ""

        new_md = _STALE_SPAR_SENT_RE.sub(_replace_stale, new_md)
        log.append({
            "fix_type": "stale_method_boilerplate",
            "n_changes": len(stale_matches),
            "description": (
                "stripped SPAR/receipt-cluster sentences from Methods; "
                "first occurrence replaced with v0.6 adapter disclaimer"
            ),
        })

    # 4. Dedupe '## References' (keep first).
    refs_pattern = re.compile(
        r"^##\s+References\b.*?(?=^##\s+\w|\Z)",
        re.DOTALL | re.MULTILINE,
    )
    refs_matches = list(refs_pattern.finditer(new_md))
    if len(refs_matches) > 1:
        # Keep the LAST one (post-processed Author-Year) — drop earlier.
        # The post-processor's References has cleaner Author-Year format.
        first_match = refs_matches[0]
        new_md = (
            new_md[:first_match.start()]
            + new_md[first_match.end():]
        )
        log.append({
            "fix_type": "duplicate_section",
            "n_changes": 1,
            "description": (
                "removed first References block (writer-rendered); kept "
                "deterministic post-processed Author-Year block"
            ),
        })

    # 5. Fix #18c: citation-order auto-fix.
    # `Konopka 2019 et al.` → `Konopka et al. 2019`. Common LLM
    # generation artifact. Safe deterministic regex sub.
    cite_order_re = re.compile(
        r"\b([A-Z][a-zA-Z]+)\s+(\d{4})\s+et\s+al\.?",
    )
    cite_order_count = len(cite_order_re.findall(new_md))
    if cite_order_count:
        new_md = cite_order_re.sub(r"\1 et al. \2", new_md)
        log.append({
            "fix_type": "broken_citation_order",
            "n_changes": cite_order_count,
            "description": (
                "rewrote 'Author YYYY et al.' → 'Author et al. YYYY' "
                "(canonical scholarly citation order)"
            ),
        })

    # 6. Fix #18b: strip sentences containing background-literature
    # numerics WITHOUT their canonical citation token in the same
    # sentence. Stage-2 audit flags these as P1; the writer should
    # have included the citation per its prompt rule (Fix #17). We
    # remove the offending sentence rather than ship an unsourced
    # numeric — the surrounding paragraph still reads coherently
    # because the preceding/following sentences carry the argument.
    bg_strip_count = _strip_unsourced_background_sentences_inplace(
        new_md, log,
    )
    if bg_strip_count > 0:
        new_md = _strip_unsourced_background_sentences(new_md)

    # 6b. Fix #46: strip sentences flagged as change-value misread
    # (C13). The corpus says X is an improvement/change/difference
    # value; the writer rendered it as an absolute below a threshold.
    # Pure deletion of the offending sentence (analogous to Fix #18b
    # for unsourced background numerics). Numeric is corpus-traced
    # (Q2 untouched); only the misread sentence is lost. The writer's
    # surrounding prose carries the rest of the argument.
    new_md, n_misread_stripped = _strip_change_value_misread_sentences(
        new_md,
    )
    if n_misread_stripped:
        log.append({
            "fix_type": "change_value_misread_strip",
            "n_changes": n_misread_stripped,
            "description": (
                "stripped sentences containing change-value numerics "
                "(e.g. 0.13 m/s 'improvement') rendered as absolute "
                "values below thresholds (Fix #46 / C13 auto-fix)"
            ),
        })

    # 6c. Fix #54: strip cross-sentence anaphoric misreads. C13's
    # per-sentence detection misses 'This walk speed value is below
    # 0.8 m/s threshold' because that sentence has no 0.13 m/s; the
    # change-numeric is in the PRECEDING sentence. Fix #54 strips
    # the threshold-comparison sentence (the misread carrier), not
    # the corpus-traced numeric sentence (which is fine).
    new_md, n_anaphor_stripped = _strip_change_value_anaphor_sentences(
        new_md,
    )
    if n_anaphor_stripped:
        log.append({
            "fix_type": "change_value_anaphor_strip",
            "n_changes": n_anaphor_stripped,
            "description": (
                "stripped cross-sentence anaphoric misreads — "
                "sentences referring back to a change-value numeric "
                "('this walk speed value...') and treating it as "
                "absolute via threshold-comparison phrasing "
                "(Fix #54 / C13b auto-fix)"
            ),
        })

    # 6d. Fix #58 (C13c): strip threshold-comparison sentences
    # from paragraphs that juxtapose a corpus change-numeric with
    # threshold language. Reviewer's stronger requirement: catch
    # ANY paragraph where the change-value is compared to a
    # threshold, regardless of wording. The strip removes the
    # threshold-comparison sentence(s); the change-numeric
    # sentence stays.
    new_md, n_para_stripped = (
        _strip_change_value_paragraph_threshold_sentences(new_md)
    )
    if n_para_stripped:
        log.append({
            "fix_type": "change_value_paragraph_threshold_strip",
            "n_changes": n_para_stripped,
            "description": (
                "stripped threshold-comparison sentences from "
                "paragraphs that juxtaposed a corpus change-numeric "
                "(e.g. 0.13 m/s) with threshold language without "
                "the change-framing in proximity (Fix #58 / C13c "
                "auto-fix)"
            ),
        })

    # 7. Fix #22: strip orphan / consecutive `_Cited:` blocks.
    # Stage-2 surface-render-lint flags these as P2 with
    # auto_fixable=True. Strip is safe by construction (no anchor
    # sentence was lost — the surrounding prose either survives or
    # the cite was already credited via the preceding cite block).
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import surface_render_lint as _srl
        new_md, n_orphan_stripped = _srl.strip_orphan_citation_blocks(
            new_md,
        )
        if n_orphan_stripped > 0:
            log.append({
                "fix_type": "surface_orphan_cite_strip",
                "n_changes": n_orphan_stripped,
                "description": (
                    "stripped orphan / consecutive `_Cited:` blocks "
                    "that had no anchor sentence (Fix #22 surface lint)"
                ),
            })
        # Fix #52: strip sentence fragments (single-letter starts +
        # lowercase preposition starts) left behind by upstream
        # auto-strips. Pure deletion; the fragment is by construction
        # broken/meaningless.
        new_md, n_fragments_stripped = _srl.strip_sentence_fragments(
            new_md,
        )
        if n_fragments_stripped > 0:
            log.append({
                "fix_type": "surface_sentence_fragment_strip",
                "n_changes": n_fragments_stripped,
                "description": (
                    "stripped broken sentence fragments (single-letter "
                    "starts like 'e when paired' or lowercase-"
                    "preposition starts like 'on 2019 in...') left "
                    "behind by upstream auto-strips (Fix #52)"
                ),
            })
    except ImportError:
        pass

    # 8a. Fix #33: replace internal tier labels with human-readable
    # equivalents. Defence-in-depth — the writer's prompt humanises
    # these labels (Fix #33 in agent/paper_writer.py) but Grok
    # patches or LLM creativity can still leak them.
    _TIER_LABEL_HUMAN: dict[str, str] = {
        "A1_clinical_RCT": "RCT (clinical)",
        "A2_human_mechanistic": "RCT (mechanistic)",
        "B1_review": "review/meta-analysis",
        "B2_observational": "observational",
        "C1_preclinical": "preclinical",
        "C2_in_vitro": "in-vitro",
    }
    n_tier_relabel = 0
    for raw, human in _TIER_LABEL_HUMAN.items():
        n = new_md.count(raw)
        if n:
            new_md = new_md.replace(raw, human)
            n_tier_relabel += n
    if n_tier_relabel:
        log.append({
            "fix_type": "internal_tier_label_relabel",
            "n_changes": n_tier_relabel,
            "description": (
                "replaced internal tier labels (A1_clinical_RCT, "
                "C1_preclinical, etc.) with human-readable equivalents "
                "(Fix #33 defence-in-depth)"
            ),
        })

    # 8. Collapse mid-line double spaces to single space.
    # Stage-2 C08 flags these as P2 auto_fixable; before this fix the
    # auto-fixer had no implementation, so the issues survived to
    # final consistency.json and tripped the no-regression gate
    # (consistency_count regression). Conservative pattern matches
    # 2+ spaces NOT at line start (line-start indentation is
    # legitimate in markdown bullets / cite blocks) AND NOT preceded
    # by a newline.
    double_space_re = re.compile(r"(?<=\S)  +(?=\S)")
    n_collapsed = len(double_space_re.findall(new_md))
    if n_collapsed:
        new_md = double_space_re.sub(" ", new_md)
        log.append({
            "fix_type": "double_space_collapse",
            "n_changes": n_collapsed,
            "description": (
                "collapsed mid-line double spaces to single space "
                "(Stage-2 C08 was flagging without auto-fix)"
            ),
        })

    # Fix #56: strip internal pipeline metadata from prose body.
    # The writer's title block produces a '**Submission:**
    # `synthesis-metformin-v06-...`' line that's machine-friendly but
    # publication-noise — reviewer flagged it as 'too much internal
    # pipeline language'. The run-tag belongs in the supplement /
    # reproducibility appendix (manifest.json), not the prose.
    submission_re = re.compile(
        r"^\*\*Submission:\*\*\s*`[^`]+`\s*\n+",
        re.MULTILINE,
    )
    n_submission = len(submission_re.findall(new_md))
    if n_submission:
        new_md = submission_re.sub("", new_md)
        log.append({
            "fix_type": "internal_pipeline_metadata_strip",
            "n_changes": n_submission,
            "description": (
                "stripped '**Submission:** `synthesis-...`' run-tag "
                "from title block — internal pipeline metadata "
                "belongs in manifest.json/supplement, not prose "
                "(Fix #56 / cert old-defect scan)"
            ),
        })

    # Strip residual blank-line runs created by deletions
    # (collapse 3+ newlines to a single paragraph break: \n\n).
    new_md = re.sub(r"\n{3,}", "\n\n", new_md)

    # Fix #53: depth-preservation guard — restore protected sections
    # if the cumulative strips above pushed Discussion / Cross-Domain
    # / Limitations / Conclusion below their safety-margin floors.
    # The analytical-depth backstop: trust-spine deletions are
    # correct individually but can collectively over-aggress on the
    # analytical-core sections (clean-repro showed Q12 dropping from
    # 930 → 582 words after auto-strips). Only restores when:
    #   (a) a snapshot was taken (section existed pre-strip), AND
    #   (b) the post-strip count is BELOW the floor, AND
    #   (c) the pre-strip count was ABOVE the floor (i.e. this
    #       regression was strip-caused, not writer-caused).
    # If the writer never produced enough words, the original
    # depth-floor failure is preserved — Fix #53 rolls back over-
    # aggressive strips, not writer shortfalls. Section heading
    # vanishing entirely (e.g. SPAR-strip ate a header line) is
    # handled by re-extracting after restore — the snapshot
    # preserves the heading.
    for heading, floor in _DEPTH_PROTECTED_SECTIONS.items():
        if heading not in pre_strip_sections:
            continue
        post_count = _section_word_count(new_md, heading)
        if post_count >= floor:
            continue  # still above floor — strips were safe
        pre_count = len(pre_strip_sections[heading].split())
        if pre_count < floor:
            continue  # was already below floor — not strip-caused
        # Strips pushed a previously-deep section below its floor.
        # Restore the snapshot.
        s, e, _body = _extract_section(new_md, heading)
        if s < 0:
            continue  # heading vanished entirely — can't restore
        new_md = new_md[:s] + pre_strip_sections[heading] + new_md[e:]
        log.append({
            "fix_type": "depth_preservation_restore",
            "n_changes": 1,
            "description": (
                f"restored '{heading}' section to pre-strip state "
                f"({post_count} → {pre_count} words; cumulative "
                f"auto-strips would have dropped it below the "
                f"depth-safety floor of {floor}; Fix #53 depth guard "
                "reverted strips on this section)"
            ),
        })
        # Re-collapse blank-line runs in case restoration mismatched.
        new_md = re.sub(r"\n{3,}", "\n\n", new_md)

    # Fix #53b (Refactor 2026-05-04): re-strip unsourced bg-lit
    # AFTER depth-preservation restore. The restore can re-introduce
    # bg-lit-unsourced sentences that the strip just removed, leading
    # to a Stage-2 P1 SHIP-BLOCKER even though the strip "fired".
    # Apply just the bg-lit strip again post-restore. If this re-
    # strip pushes a section below its floor again, the depth-floor
    # failure is honest (we can't have BOTH no-unsourced-bg-lit AND
    # 850-word Discussion if the only way to fill 850 is via
    # unsourced bg-lit). Q11/Q12 P2 is preferable to C09 P1.
    n_re_stripped = _strip_unsourced_background_sentences_inplace(
        new_md, [],
    )
    if n_re_stripped:
        new_md = _strip_unsourced_background_sentences(new_md)
        log.append({
            "fix_type": "background_lit_unsourced_restrip_post_depth",
            "n_changes": n_re_stripped,
            "description": (
                "re-stripped bg-lit-unsourced sentences after Fix #53 "
                "depth-preservation restore re-introduced them. "
                "Choosing C09-clean over Q11/Q12-depth — P1 cleanliness "
                "trumps P2 depth (Fix #53b)"
            ),
        })

    # Fix #53c (2026-05-04): re-strip cosmetic '(potentially)' inline
    # repair-artifacts AFTER depth-preservation. The restore can put
    # them back if the protected section dropped below its floor;
    # losing 16 chars of artifact never threatens a 850-word floor,
    # so this re-strip is unconditionally safe. Without this re-pass
    # the C05 P2 issue resurfaces in the final consistency audit even
    # though the strip "fired" earlier.
    pot_re_count = len(_POTENTIALLY_RE.findall(new_md))
    if pot_re_count:
        new_md = _POTENTIALLY_RE.sub("", new_md)
        log.append({
            "fix_type": "repair_artifact_restrip_post_depth",
            "n_changes": pot_re_count,
            "description": (
                "re-stripped '(potentially)' inline artifacts after "
                "Fix #53 depth-preservation restore re-introduced "
                "them. Cosmetic strip; safe to re-apply unconditionally "
                "(Fix #53c)"
            ),
        })

    # Universal Numeric Role Guard auto-fix (2026-05-05): strip P1
    # sentences flagged for arithmetic_violation or role_mismatch.
    # Catches the metformin '0.13 m/s falls at or below 0.1 m/s'
    # pattern and the 'duplicate-subject group' repair artifact.
    # See scripts/numeric_role_guard.py.
    try:
        from numeric_role_guard import (
            scan_paper as _scan, auto_strip_offending_sentences as _strip,
        )
    except ImportError:
        _scan = None
    if _scan is not None:
        nrg_issues = _scan(new_md)
        if nrg_issues:
            new_md, n_stripped = _strip(new_md, nrg_issues)
            if n_stripped:
                log.append({
                    "fix_type": "numeric_role_guard_strip",
                    "n_changes": n_stripped,
                    "description": (
                        "stripped sentences flagged by Numeric Role "
                        "Guard (arithmetic violation, role mismatch, "
                        "or malformed-subject repair artifact). "
                        "Universal class-level fix subsuming "
                        "Fixes #54/#57/#58/#58c."
                    ),
                })

    return new_md, log


def _strip_unsourced_background_sentences_inplace(
    paper_md: str, log: list[dict],
) -> int:
    """Count + log unsourced background numerics; returns count.
    Separate from the actual strip so the log accurately reports
    BEFORE-state count even after the strip. Caller does the strip
    via _strip_unsourced_background_sentences()."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import background_literature as _bg
        registry = _bg.load_registry()
        unsourced = _bg.find_unsourced_background_uses(paper_md, registry)
    except (ImportError, FileNotFoundError, ValueError):
        return 0
    if not unsourced:
        return 0
    log.append({
        "fix_type": "background_lit_unsourced_strip",
        "n_changes": len(unsourced),
        "description": (
            "stripped sentences containing background-lit numerics "
            "without their required canonical citation in the same "
            "sentence"
        ),
    })
    return len(unsourced)


def _strip_change_value_misread_sentences(
    paper_md: str,
) -> tuple[str, int]:
    """Fix #46: strip sentences whose change-value numeric is
    rendered as absolute. Mirrors the audit's
    _check_change_value_misread but performs the deletion. Safe by
    construction: numerics are corpus-traced (Q2 untouched), only
    interpretation-broken sentences disappear.

    Returns (new_md, n_stripped). Iterates per-paragraph: builds the
    same change_value_map the audit uses, splits paragraphs into
    sentences, drops any sentence with the change-numeric paired with
    absolute-value phrasing AND missing the source's change-words."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import audit_v06_paper as _audit
        change_value_map: dict[str, set[str]] = {}
        if not _audit.QUANT_DIR.exists():
            return paper_md, 0
        for qf in _audit.QUANT_DIR.glob("*.quant_claims.json"):
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
                from final_consistency_audit import _CHANGE_WORDS
                hits = {w for w in _CHANGE_WORDS if w in sent_lc}
                if hits:
                    change_value_map.setdefault(raw, set()).update(hits)
    except (ImportError, OSError, ValueError):
        return paper_md, 0
    if not change_value_map:
        return paper_md, 0
    from final_consistency_audit import _ABSOLUTE_VALUE_PHRASES
    sent_split = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")
    n_stripped = 0
    out_parts: list[str] = []
    for paragraph in paper_md.split("\n\n"):
        # Skip markdown tables (don't strip table rows).
        lines = [ln for ln in paragraph.splitlines() if ln.strip()]
        if lines and (
            sum(1 for ln in lines if ln.lstrip().startswith("|"))
            / len(lines) >= 0.5
        ):
            out_parts.append(paragraph)
            continue
        sentences = sent_split.split(paragraph)
        kept: list[str] = []
        for sent in sentences:
            sent_lc = sent.lower()
            should_drop = False
            for numeric, change_words in change_value_map.items():
                if numeric not in sent:
                    continue
                has_absolute = any(
                    p in sent_lc for p in _ABSOLUTE_VALUE_PHRASES
                )
                # Fix #57: PROXIMITY check — change-word must be
                # within ±40 chars of the numeric to count.
                # Defends against long sentences where a change-
                # word for a DIFFERENT metric ("no change in
                # frailty, and walk speed was 0.13 m/s") falsely
                # cleared the numeric.
                from final_consistency_audit import (
                    _CHANGE_WORD_PROXIMITY_CHARS,
                )
                num_idx = sent_lc.find(numeric.lower())
                window_start = max(
                    0, num_idx - _CHANGE_WORD_PROXIMITY_CHARS,
                )
                window_end = min(
                    len(sent_lc),
                    num_idx + len(numeric)
                    + _CHANGE_WORD_PROXIMITY_CHARS,
                )
                window = sent_lc[window_start:window_end]
                has_change = any(w in window for w in change_words)
                if has_absolute and not has_change:
                    should_drop = True
                    n_stripped += 1
                    break
            if not should_drop:
                kept.append(sent)
        out_parts.append(" ".join(kept) if kept else "")
    new_md = "\n\n".join(p for p in out_parts if p.strip() or p == "")
    new_md = re.sub(r"\n{3,}", "\n\n", new_md)
    return new_md, n_stripped


def _strip_change_value_anaphor_sentences(
    paper_md: str,
) -> tuple[str, int]:
    """Fix #54: strip cross-sentence anaphoric misreads.

    Mirrors final_consistency_audit._check_change_value_anaphor_misread
    but performs the deletion. For each paragraph that contains a
    change-value numeric followed by a sentence that combines an
    anaphoric reference ('this walk speed value', 'the figure', etc.)
    with threshold-comparison phrasing ('below the 0.8 m/s threshold',
    'below the cutoff', 'frailty threshold'), the threshold-sentence
    is dropped. The change-numeric sentence stays — it's the
    misreading sentence (B) we lose, not the corpus-traced one (A).
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import audit_v06_paper as _audit
        if not _audit.QUANT_DIR.exists():
            return paper_md, 0
        from final_consistency_audit import (
            _CHANGE_WORDS, _ANAPHOR_RE, _THRESHOLD_KEYWORD_RE,
        )
        change_value_map: dict[str, set[str]] = {}
        for qf in _audit.QUANT_DIR.glob("*.quant_claims.json"):
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
                hits = {w for w in _CHANGE_WORDS if w in sent_lc}
                if hits:
                    change_value_map.setdefault(raw, set()).update(hits)
    except (ImportError, OSError, ValueError):
        return paper_md, 0
    if not change_value_map:
        return paper_md, 0
    sent_split = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")
    n_stripped = 0
    out_paragraphs: list[str] = []
    for para in paper_md.split("\n\n"):
        # Skip tables.
        lines = [ln for ln in para.splitlines() if ln.strip()]
        if lines and (
            sum(1 for ln in lines if ln.lstrip().startswith("|"))
            / len(lines) >= 0.5
        ):
            out_paragraphs.append(para)
            continue
        sentences = sent_split.split(para)
        if len(sentences) < 2:
            out_paragraphs.append(para)
            continue
        # Map: numeric → first sentence index containing it
        change_sent_indices: dict[str, int] = {}
        for i, sent in enumerate(sentences):
            for numeric in change_value_map:
                if numeric in sent and numeric not in change_sent_indices:
                    change_sent_indices[numeric] = i
        if not change_sent_indices:
            out_paragraphs.append(para)
            continue
        kept_sentences: list[str] = []
        for i, sent in enumerate(sentences):
            sent_lc = sent.lower()
            earlier_numerics = [
                n for n, idx in change_sent_indices.items() if idx < i
            ]
            should_drop = False
            if earlier_numerics:
                has_anaphor = bool(_ANAPHOR_RE.search(sent))
                has_threshold = bool(_THRESHOLD_KEYWORD_RE.search(sent))
                if has_anaphor and has_threshold:
                    change_words: set[str] = set()
                    for n in earlier_numerics:
                        change_words.update(change_value_map[n])
                    if not any(w in sent_lc for w in change_words):
                        should_drop = True
                        n_stripped += 1
            if not should_drop:
                kept_sentences.append(sent)
        out_paragraphs.append(
            " ".join(kept_sentences) if kept_sentences else ""
        )
    new_md = "\n\n".join(p for p in out_paragraphs if p.strip() or p == "")
    new_md = re.sub(r"\n{3,}", "\n\n", new_md)
    return new_md, n_stripped


def _strip_change_value_paragraph_threshold_sentences(
    paper_md: str,
) -> tuple[str, int]:
    """Fix #58 (C13c) auto-strip: in paragraphs flagged as
    juxtaposing a change-numeric with threshold language, remove
    the threshold-comparison sentence(s). Keeps the sentence(s)
    containing the change-numeric (those are corpus-traced and
    legitimate; the misread is in the comparison framing).

    Strategy: for each paragraph, build the change-numeric set and
    threshold-marker set. If a paragraph has both AND lacks the
    nearby change-word hedge, strip the sentence(s) that contain
    threshold markers but DO NOT contain the change-numeric (those
    are pure threshold-comparison sentences). Sentences with the
    change-numeric stay (they're the corpus evidence)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import audit_v06_paper as _audit
        if not _audit.QUANT_DIR.exists():
            return paper_md, 0
        from final_consistency_audit import (
            _CHANGE_WORDS,
            _THRESHOLD_MARKERS,
        )
        change_value_map: dict[str, set[str]] = {}
        for qf in _audit.QUANT_DIR.glob("*.quant_claims.json"):
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
                hits = {w for w in _CHANGE_WORDS if w in sent_lc}
                if hits:
                    change_value_map.setdefault(raw, set()).update(hits)
    except (ImportError, OSError, ValueError):
        return paper_md, 0
    if not change_value_map:
        return paper_md, 0
    sent_split = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")
    n_stripped = 0
    out_paragraphs: list[str] = []
    for para in paper_md.split("\n\n"):
        para_lc = para.lower()
        # Skip tables
        lines = [ln for ln in para.splitlines() if ln.strip()]
        if lines and (
            sum(1 for ln in lines if ln.lstrip().startswith("|"))
            / len(lines) >= 0.5
        ):
            out_paragraphs.append(para)
            continue
        # Skip Limitations section (legitimate change-framing)
        if "## limitations" in para_lc:
            out_paragraphs.append(para)
            continue
        # Find change-numerics in the paragraph
        present_numerics = [
            n for n in change_value_map if n in para
        ]
        if not present_numerics:
            out_paragraphs.append(para)
            continue
        has_threshold = any(
            m in para_lc for m in _THRESHOLD_MARKERS
        )
        if not has_threshold:
            out_paragraphs.append(para)
            continue
        # Check if any change-numeric has a nearby change-word hedge.
        # If yes → paragraph is fine, keep as-is.
        any_hedged = False
        for numeric in present_numerics:
            num_idx = para_lc.find(numeric.lower())
            window = para_lc[
                max(0, num_idx - 60):
                min(len(para_lc), num_idx + len(numeric) + 60)
            ]
            change_words = change_value_map[numeric]
            if any(w in window for w in change_words):
                any_hedged = True
                break
        if any_hedged:
            out_paragraphs.append(para)
            continue
        # Strip threshold-comparison sentences (those with a
        # threshold marker but NOT the change-numeric).
        sentences = sent_split.split(para)
        kept: list[str] = []
        for sent in sentences:
            sent_lc = sent.lower()
            has_marker = any(
                m in sent_lc for m in _THRESHOLD_MARKERS
            )
            has_numeric = any(
                n in sent for n in present_numerics
            )
            if has_marker and not has_numeric:
                # Pure threshold-comparison sentence — strip
                n_stripped += 1
                continue
            kept.append(sent)
        out_paragraphs.append(
            " ".join(kept) if kept else ""
        )
    new_md = "\n\n".join(
        p for p in out_paragraphs if p.strip() or p == ""
    )
    new_md = re.sub(r"\n{3,}", "\n\n", new_md)
    return new_md, n_stripped


def _strip_unsourced_background_sentences(paper_md: str) -> str:
    """Remove sentences whose background-numeric→citation gate fails.

    Fix #19: ITERATIVE strip until stable (a single pass can leave
    survivors when multiple background numerics share a sentence or
    when paragraph-wise splitting differs from the audit's sentence
    splitter). Caps at 5 iterations to avoid pathological loops."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import background_literature as _bg
        registry = _bg.load_registry()
    except (ImportError, FileNotFoundError, ValueError):
        return paper_md
    if not registry:
        return paper_md

    sent_split = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")

    def _is_markdown_table_paragraph(paragraph: str) -> bool:
        """A markdown table paragraph has lines that mostly start with
        `|` (table rows). The whole paragraph is structured data, not
        prose — strip-by-sentence would treat the table as one
        sentence and drop the entire table when ANY background numeric
        appears anywhere in it. Tables are deterministic and Q9-counted
        carriers; we DON'T want them stripped."""
        lines = [ln for ln in paragraph.splitlines() if ln.strip()]
        if not lines:
            return False
        n_table_lines = sum(1 for ln in lines if ln.lstrip().startswith("|"))
        return n_table_lines / len(lines) >= 0.5

    def _one_pass(text: str) -> str:
        out_parts: list[str] = []
        for paragraph in text.split("\n\n"):
            # Fix #21 follow-up: skip markdown tables — Table 5 surfaces
            # corpus numerics (some of which match background_literature
            # entries like '7%' or '0.8 m/s') without citation tokens
            # in the same cell. Stripping the whole table for that
            # would tank Q9 density and remove load-bearing structured
            # evidence. The numerics in tables ARE authorised: they
            # come from the corpus's quant_claims, not from the LLM's
            # training-data world knowledge.
            if _is_markdown_table_paragraph(paragraph):
                out_parts.append(paragraph)
                continue
            sentences = sent_split.split(paragraph)
            kept: list[str] = []
            for sent in sentences:
                drop = False
                for entry in registry.values():
                    if (
                        entry.numeric in sent
                        and entry.citation_token not in sent
                    ):
                        drop = True
                        break
                if not drop:
                    kept.append(sent)
            out_parts.append(" ".join(kept) if kept else "")
        return "\n\n".join(p for p in out_parts if p.strip() or p == "")

    out = paper_md
    for _ in range(5):
        nxt = _one_pass(out)
        if nxt == out:
            break
        out = nxt
    return out


def fix_audit_verdict(audit_md: str) -> tuple[str, list[dict]]:
    """Rename audit verdict heading from 'AAA' to 'Trust-Spine Pass'
    when score≥9 + P1 clean but some P2 failed."""
    log: list[dict] = []
    new = audit_md
    # Only rename if both signals are present in the file
    if "## Verdict: AAA" in new and "❌" in new:
        new = new.replace(
            "## Verdict: AAA",
            "## Verdict: Trust-Spine Pass",
        )
        new = new.replace(
            "≥9.0 score AND no P1 failures. Paper passes the trust-spine gate.",
            "≥9.0 score AND no P1 failures, but one or more P2 quality "
            "checks flagged issues. 'AAA Paper' is reserved for "
            "all-green.",
        )
        log.append({
            "fix_type": "audit_verdict_overclaim",
            "n_changes": 1,
            "description": (
                "renamed verdict 'AAA' → 'Trust-Spine Pass' "
                "(P2 check failed)"
            ),
        })
    return new, log


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Apply deterministic fixes from final_consistency_audit",
    )
    parser.add_argument("paper_md", help="full_paper.md to fix")
    args = parser.parse_args(argv)
    paper_path = Path(args.paper_md).resolve()
    if not paper_path.exists():
        print(f"not found: {paper_path}", file=sys.stderr)
        return 2
    consistency_path = paper_path.with_suffix(".consistency.json")
    if not consistency_path.exists():
        print(
            "Run scripts/final_consistency_audit.py first to generate "
            f"{consistency_path}",
            file=sys.stderr,
        )
        return 2

    issues_doc = json.loads(consistency_path.read_text())
    paper = paper_path.read_text()
    fixed, log = apply_fixes(paper, issues_doc.get("issues", []))
    paper_path.write_text(fixed)

    # Also fix the audit.md verdict
    audit_md_path = paper_path.with_suffix(".audit.md")
    if audit_md_path.exists():
        audit_md = audit_md_path.read_text()
        new_audit, audit_log = fix_audit_verdict(audit_md)
        audit_md_path.write_text(new_audit)
        log.extend(audit_log)

    log_path = paper_path.with_suffix(".fixed_log.json")
    log_path.write_text(json.dumps({"fixes_applied": log}, indent=2))
    print(
        f"Fixed: {paper_path}\n"
        f"Log: {log_path}\n"
        f"Total fix categories applied: {len(log)}",
        file=sys.stderr,
    )
    for entry in log:
        print(
            f"  - {entry['fix_type']}: {entry['n_changes']} change(s) "
            f"— {entry['description']}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
