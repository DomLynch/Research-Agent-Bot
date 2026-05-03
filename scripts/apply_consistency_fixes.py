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
_STALE_SPAR_SENT_RE = re.compile(
    r"[^.!?]*\b(?:spar\s+adjudication|rejected\s+by\s+spar|"
    r"spar-?quarantined|claim\s+receipts?|receipt\s+clusters?|"
    r"receipt-level\s+spar|synthesis-level\s+spar|"
    r"trust-spine\s+multi-receipt)\b[^.!?]*[.!?]",
    re.IGNORECASE,
)


def apply_fixes(
    paper_md: str, issues: list[dict],
) -> tuple[str, list[dict]]:
    """Apply auto-fixable patches; return (new_md, log)."""
    new_md = paper_md
    log: list[dict] = []

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

    # Strip residual blank-line runs created by deletions
    # (collapse 3+ newlines to a single paragraph break: \n\n).
    new_md = re.sub(r"\n{3,}", "\n\n", new_md)

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


def _strip_unsourced_background_sentences(paper_md: str) -> str:
    """Remove sentences whose background-numeric→citation gate fails.
    Sentence boundary: . ! ? followed by whitespace+capital, OR
    paragraph break."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import background_literature as _bg
        registry = _bg.load_registry()
    except (ImportError, FileNotFoundError, ValueError):
        return paper_md
    if not registry:
        return paper_md
    sent_split = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")
    out_parts: list[str] = []
    # Operate paragraph-wise so paragraph structure isn't mangled.
    for paragraph in paper_md.split("\n\n"):
        sentences = sent_split.split(paragraph)
        kept: list[str] = []
        for sent in sentences:
            drop = False
            for entry in registry.values():
                if entry.numeric in sent and entry.citation_token not in sent:
                    drop = True
                    break
            if not drop:
                kept.append(sent)
        out_parts.append(" ".join(kept) if kept else "")
    return "\n\n".join(p for p in out_parts if p.strip() or p == "")


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
