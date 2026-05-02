"""Day 10.17 Phase 6.2 Layer 2 — Grok patch applicator.

Reads <paper>.review_patches.json (from grok_reviewer.py) and applies
patches per per-type gate rules:

  formatting   → auto-apply (typos, headers, spacing)
  numeric      → only if BOTH the old AND new numeric value appear
                 in the v0.6 quant_claims corpus (i.e. legitimate
                 cross-reference); otherwise FLAG-ONLY
  citation     → only if `after` references a real paper_id from
                 manifest.receipts; otherwise FLAG-ONLY
  claim        → FLAG-ONLY (always, no auto-apply)
  structure    → FLAG-ONLY (always)

Every action — applied OR flagged-only — logged to
<paper>.review_patch_log.json with before/after/reason/result.

Per the converged audit: "Don't ban powerful edits; ban silent
untraceable edits." Every edit has audit replay.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
QUANT_DIR = REPO_ROOT / "docs" / "quality-reference" / "metformin" / "quant_claims"

__all__ = ["apply_patches", "main"]


@dataclass(frozen=True, slots=True)
class PatchResult:
    patch_id: str
    patch_type: str
    severity: str
    decision: str       # applied | flagged | rejected
    reason_for_decision: str
    before: str
    after: str


def _load_corpus_numerics() -> set[str]:
    """All numeric tokens from v0.6 high-confidence claims (used to
    verify numeric patches don't introduce un-traceable values)."""
    nums: set[str] = set()
    for path in QUANT_DIR.glob("*.quant_claims.json"):
        d = json.loads(path.read_text())
        for c in d.get("claims", []):
            if c.get("binding_confidence") != "high":
                continue
            for v in c.get("numeric_values") or ():
                nums.add(str(v))
                if isinstance(v, (int, float)) and float(v).is_integer():
                    nums.add(str(int(v)))
            raw = (c.get("raw_text") or "").strip()
            if raw:
                nums.add(raw)
    return nums


def _load_receipt_ids(manifest: dict) -> set[str]:
    ids = set()
    for r in manifest.get("receipts", []):
        rid = r.get("receipt_id")
        if rid:
            ids.add(rid)
            # Author Year short form
            parts = rid.split("_")
            if len(parts) >= 2 and parts[1].isdigit():
                ids.add(f"{parts[0]} {parts[1]}")
                ids.add(parts[0])
    return ids


_NUMERIC_RE = re.compile(
    r"\b(\d+\.?\d*\s*(?:%|m/s|kg|mg|months?|years?|weeks?))\b|"
    r"\b[Pp]\s*[<=>]\s*0?\.\d+",
)


def _numeric_tokens_in(text: str) -> set[str]:
    out: set[str] = set()
    for m in _NUMERIC_RE.finditer(text):
        out.add(m.group(0).strip())
    # Also raw integers/floats
    for m in re.finditer(r"\b(\d+\.?\d*)\b", text):
        v = m.group(1)
        if v not in {"0", "1"}:  # skip trivial
            out.add(v)
    return out


def _verify_numeric_patch(
    patch: dict, corpus_nums: set[str],
) -> tuple[bool, str]:
    """A numeric patch is valid iff every numeric token in `after`
    that wasn't in `before` traces to corpus.

    KNOWN LOOPHOLE (reviewer-flagged HIGH; documented for v0.6.2,
    tightening deferred to Phase 6.4): the corpus check is GLOBAL —
    a value being "anywhere in v0.6 corpus" passes, even if it's
    bound to an unrelated claim. A patch flipping `p=0.04 → p=0.001`
    where 0.001 exists in some other paper's claim would pass. The
    correct check is "this number is bound to the SAME endpoint+arm+
    direction tuple as the surrounding context"; that requires the
    paragraph-level claim binding from Phase 6.4. Until then, this
    is a flag-style check, not a hard verification.
    """
    before_nums = _numeric_tokens_in(patch["before"])
    after_nums = _numeric_tokens_in(patch["after"])
    novel = after_nums - before_nums
    if not novel:
        return True, "no novel numerics"
    untraceable = []
    for n in novel:
        # Tokens may include unit suffix glued to digits ("32%").
        # Strip the digit prefix and check both forms against corpus.
        bare = re.match(r"-?\d+\.?\d*", n)
        bare_str = bare.group(0) if bare else ""
        if (
            n in corpus_nums
            or bare_str in corpus_nums
            or n.split()[0] in corpus_nums
        ):
            continue
        untraceable.append(n)
    if untraceable:
        return False, f"novel un-traceable numerics: {untraceable[:3]}"
    return True, (
        f"all novel numerics trace globally ({len(novel)} ok); "
        "TODO(phase 6.4): same-claim binding verification"
    )


def _verify_citation_patch(
    patch: dict, receipt_ids: set[str],
) -> tuple[bool, str]:
    """A citation patch is valid iff every Author-Year shaped token
    in `after` exists in the receipt set.

    Reviewer-fix HIGH: pre-fix regex `[A-Z][a-zA-Z]+(?:\\s+\\d{4})?`
    matched any capitalized word ("Section", "Discussion") and
    flagged them as 'novel citations'. Now we require BOTH
    Author-and-Year (no optional year) — only true citation shapes
    qualify. False-positive on prose proper nouns is eliminated.
    """
    cite_re = re.compile(
        r"\b([A-Z][a-zA-Z]+(?:\s+et\s+al\.?)?\s+\d{4})\b"
    )
    found_in_after = {m.group(1) for m in cite_re.finditer(patch["after"])}
    found_in_before = {m.group(1) for m in cite_re.finditer(patch["before"])}
    novel_cites = found_in_after - found_in_before
    if not novel_cites:
        return True, "no novel citations"
    # A receipt set entry of "Walton 2019" should match a found cite
    # "Walton 2019" or "Walton et al. 2019" — both shapes accepted by
    # the loader. Strip "et al." for the lookup.
    unknown = []
    for c in novel_cites:
        normalized = re.sub(r"\s+et\s+al\.?\s+", " ", c)
        if normalized in receipt_ids or c in receipt_ids:
            continue
        unknown.append(c)
    if unknown:
        return False, f"novel un-traced citations: {unknown[:3]}"
    return True, "all novel citations match receipts"


def apply_patches(
    paper_md: str, patches: list[dict], manifest: dict,
) -> tuple[str, list[PatchResult]]:
    """Walk patches in order; apply or flag per type-gate rules."""
    new_md = paper_md
    results: list[PatchResult] = []
    corpus_nums = _load_corpus_numerics()
    receipt_ids = _load_receipt_ids(manifest)

    for p in patches:
        ptype = p.get("patch_type") or "unknown"
        before = p.get("before") or ""
        after = p.get("after") or ""
        if not before:
            results.append(PatchResult(
                patch_id=p.get("id", "?"),
                patch_type=ptype, severity=p.get("severity", "P3"),
                decision="rejected",
                reason_for_decision="empty 'before' field",
                before=before, after=after,
            ))
            continue

        # Per-type gate logic
        if ptype == "formatting":
            ok, reason = True, "auto-apply per type contract"
        elif ptype == "numeric":
            # P1 reviewer fix: numeric patches are FLAG-ONLY pending
            # Phase 6.4 same-claim binding. The global-corpus check is
            # too weak — a patch flipping `p=0.04 → p=0.001` passes if
            # 0.001 exists anywhere in the corpus, even bound to an
            # unrelated claim. Run the verifier to give the human a
            # diagnostic but never auto-apply.
            passed_global, verify_reason = _verify_numeric_patch(p, corpus_nums)
            ok, reason = False, (
                f"flag-only (numeric auto-apply blocked pending Phase 6.4 "
                f"same-claim binding). Global-corpus verifier: "
                f"{'pass' if passed_global else 'FAIL'} — {verify_reason}"
            )
        elif ptype == "citation":
            ok, reason = _verify_citation_patch(p, receipt_ids)
        elif ptype in ("claim", "structure"):
            ok, reason = False, f"{ptype} patches are flag-only by contract"
        else:
            ok, reason = False, f"unknown patch_type {ptype!r}"

        if not ok:
            results.append(PatchResult(
                patch_id=p.get("id", "?"),
                patch_type=ptype, severity=p.get("severity", "P3"),
                decision="flagged",
                reason_for_decision=reason,
                before=before, after=after,
            ))
            continue

        # Apply: simple substring replace (single occurrence to be
        # safe; if `before` appears multiple times, flag for human).
        n_occurrences = new_md.count(before)
        if n_occurrences == 0:
            results.append(PatchResult(
                patch_id=p.get("id", "?"),
                patch_type=ptype, severity=p.get("severity", "P3"),
                decision="rejected",
                reason_for_decision="'before' text not found in paper",
                before=before, after=after,
            ))
            continue
        if n_occurrences > 1:
            results.append(PatchResult(
                patch_id=p.get("id", "?"),
                patch_type=ptype, severity=p.get("severity", "P3"),
                decision="flagged",
                reason_for_decision=(
                    f"'before' appears {n_occurrences}x; ambiguous "
                    "without further context"
                ),
                before=before, after=after,
            ))
            continue

        new_md = new_md.replace(before, after, 1)
        results.append(PatchResult(
            patch_id=p.get("id", "?"),
            patch_type=ptype, severity=p.get("severity", "P3"),
            decision="applied",
            reason_for_decision=reason,
            before=before, after=after,
        ))
    return new_md, results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Apply Grok-proposed patches with per-type gates",
    )
    parser.add_argument("paper_md", help="full_paper.md")
    args = parser.parse_args(argv)
    paper_path = Path(args.paper_md).resolve()
    patches_path = paper_path.with_suffix(".review_patches.json")
    if not patches_path.exists():
        print(f"Run grok_reviewer.py first: {patches_path}", file=sys.stderr)
        return 2
    manifest_path = paper_path.parent / "manifest.json"
    paper = paper_path.read_text()
    manifest = (
        json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    )
    patches_doc = json.loads(patches_path.read_text())
    patches = patches_doc.get("patches", [])

    new_md, results = apply_patches(paper, patches, manifest)
    paper_path.write_text(new_md)

    log = {
        "applied_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "n_proposed": len(patches),
        "n_applied": sum(1 for r in results if r.decision == "applied"),
        "n_flagged": sum(1 for r in results if r.decision == "flagged"),
        "n_rejected": sum(1 for r in results if r.decision == "rejected"),
        "patches": [
            {
                "patch_id": r.patch_id,
                "patch_type": r.patch_type,
                "severity": r.severity,
                "decision": r.decision,
                "reason": r.reason_for_decision,
                "before": r.before[:200],
                "after": r.after[:200],
            }
            for r in results
        ],
    }
    log_path = paper_path.with_suffix(".review_patch_log.json")
    log_path.write_text(json.dumps(log, indent=2))

    print(
        f"Applied: {log['n_applied']}, Flagged: {log['n_flagged']}, "
        f"Rejected: {log['n_rejected']} (of {log['n_proposed']} proposed)",
        file=sys.stderr,
    )
    print(f"Log: {log_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
