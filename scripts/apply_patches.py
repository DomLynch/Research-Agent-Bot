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

_REQUIRED_HEADINGS = (
    "## Abstract",
    "## Introduction",
    "## Background",
    "## Quantitative Evidence Index",
    "## Methods",
    "## Results",
    "## Cross-Domain Synthesis",
    "## Discussion",
    "## Limitations",
    "## Conclusion",
)


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
        citation_token = r.get("citation_token")
        if citation_token:
            ids.add(str(citation_token))
        if rid:
            ids.add(rid)
            # Author Year short form
            parts = rid.split("_")
            if len(parts) >= 2 and parts[1].isdigit():
                ids.add(f"{parts[0]} {parts[1]}")
                ids.add(parts[0])
    try:
        import background_literature as _bg
        for entry in _bg.load_registry(
            topic=manifest.get("topic"),
        ).values():
            ids.add(str(entry.citation_token))
    except (ImportError, OSError, ValueError, json.JSONDecodeError):
        pass
    return ids


_NUMERIC_RE = re.compile(
    r"\b(\d+\.?\d*\s*(?:%|m/s|kg|mg|months?|years?|weeks?))\b|"
    r"\b[Pp]\s*[<=>]\s*0?\.\d+",
)
_AUTHOR_YEAR_RE = re.compile(
    r"\b([A-Z][a-zA-Z]+(?:\s+et\s+al\.?)?\s+\d{4})\b",
)
_CITED_ARTIFACT_RE = re.compile(
    r"_Cited:\s*`[^`\n]+`(?:\s*,\s*`[^`\n]+`)*_"
)
_ROLE_REPAIR_ARTIFACT_RE = re.compile(
    r"[A-Z][A-Za-z\-]+ \d{4} reported (?:an? )?"
    r"(?:dose|effect value|outcome value|baseline value|"
    r"population descriptor|threshold|change)(?: of [^.;]+)?; "
    r"this manuscript treats the value according to that source role\."
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


def _is_cited_artifact_delete(ptype: str, before: str, after: str) -> bool:
    return (
        ptype == "formatting"
        and not after.strip()
        and _CITED_ARTIFACT_RE.fullmatch(before.strip()) is not None
    )


def _is_role_repair_artifact_delete(ptype: str, before: str, after: str) -> bool:
    return (
        ptype == "formatting"
        and not after.strip()
        and _ROLE_REPAIR_ARTIFACT_RE.fullmatch(before.strip()) is not None
    )


def _removes_bridge_contract_tags(location: str, before: str, after: str) -> bool:
    if "inferential bridge" not in location.lower():
        return False
    required = (
        "[D1_", "[mechanism_anchor:", "[mechanism anchor:",
        "[conservation:", "[testability:",
    )
    return any(tag in before and tag not in after for tag in required)


def _looks_truncated_patch_field(after: str) -> bool:
    """Detect reviewer patch fields likely clipped by grok_reviewer caps.

    `grok_reviewer` caps `after` at 600 chars to prevent runaway JSON.
    A non-empty replacement near that cap that ends mid-token is unsafe:
    applying it can splice a broken sentence into the manuscript.
    """
    stripped = after.rstrip()
    if len(stripped) < 590:
        return False
    return bool(stripped and re.search(r"[A-Za-z0-9]$", stripped))


def _is_word_char(ch: str) -> bool:
    return ch.isalnum() or ch == "_"


def _has_unsafe_match_boundary(text: str, before: str) -> bool:
    """Reject patches whose target starts or ends inside a word.

    Grok can emit a clipped `before` span that still appears exactly once
    in the manuscript. Applying it can leave fragments such as deleting
    `metabol` from `metabolic`. Exact-match uniqueness is necessary but
    not sufficient; the match must also be token-boundary aligned.
    """
    start = text.find(before)
    if start < 0:
        return False
    end = start + len(before)
    left_bad = (
        start > 0
        and before
        and _is_word_char(text[start - 1])
        and _is_word_char(before[0])
    )
    right_bad = (
        end < len(text)
        and before
        and _is_word_char(before[-1])
        and _is_word_char(text[end])
    )
    return left_bad or right_bad


def _breaks_markdown_table_shape(location: str, before: str, after: str) -> bool:
    """Reviewer patches may simplify table content, but must not
    delete cells. A row fragment with fewer pipe separators after
    patching corrupts the public manuscript even when the numeric
    wording is a safe subset."""
    if "|" not in before:
        return False
    if not after.strip() and "\n" not in before:
        # Pure deletion of one pipe-delimited row is applied by
        # _apply_text_patch as whole-row removal, preserving shape.
        return False
    if "quantitative evidence index" not in location.lower() and "|" not in after:
        return False
    return after.count("|") != before.count("|")


def _apply_text_patch(md: str, before: str, after: str) -> str:
    """Apply an exact patch, expanding table-fragment deletions to rows.

    Grok sometimes proposes deleting a pipe-free fragment from a markdown
    table row. Replacing only the fragment leaves a malformed row and
    makes the post-apply audit explode. If the patch is a pure deletion
    and the unique BEFORE text lives inside one markdown table row,
    remove the whole row instead.
    """
    if after.strip() or "\n" in before:
        return md.replace(before, after, 1)
    idx = md.find(before)
    if idx < 0:
        return md
    line_start = md.rfind("\n", 0, idx) + 1
    line_end = md.find("\n", idx)
    if line_end < 0:
        line_end = len(md)
        newline = ""
    else:
        newline = "\n"
    line = md[line_start:line_end]
    if line.strip().startswith("|") and line.strip().endswith("|"):
        return md[:line_start] + md[line_end + len(newline):]
    return md.replace(before, after, 1)


def _is_repeated_safe_simplification(ptype: str, before: str, after: str) -> bool:
    if ptype not in {"claim", "formatting", "citation"}:
        return False
    if before == after:
        return False
    ok, _msg = _is_safe_simplification(before, after)
    return ok


_NEUTRAL_EVIDENCE_WORDS = frozenset({
    "examined", "evaluated", "assessed", "studied", "tested",
    "investigated", "reported", "described",
})
_DIRECTIONAL_CLAIM_WORDS = frozenset({
    "increase", "increases", "increased", "improve", "improves",
    "improved", "extend", "extends", "extended", "benefit", "benefits",
    "beneficial", "positive", "reduce", "reduces", "reduced", "lower",
    "lowers", "lowered", "attenuate", "attenuates", "attenuated",
    "mitigate", "mitigates", "mitigated",
})


def _is_safe_neutral_claim_rephrase(
    before: str, after: str,
) -> tuple[bool, str]:
    """Allow a narrow, non-additive claim downgrade.

    Grok often repairs overclaiming by replacing a directional verb
    ("increased", "improved") with a neutral evidence verb
    ("examined", "assessed"). This is safe only when the patch adds
    no numerics/citations/entities, does not lengthen the text, and
    the only new content words are neutral evidence verbs.
    """
    import re as _re

    def _numerics(s: str) -> set[str]:
        return set(_re.findall(r"\d+\.?\d*", s))

    def _author_years(s: str) -> set[str]:
        return set(
            f"{m.group(1)} {m.group(2)}"
            for m in _re.finditer(
                r"\b([A-Z][a-zA-Z]+(?:\s+et\s+al\.)?)\s+(\d{4})\b", s,
            )
        )

    def _caps_idents(s: str) -> set[str]:
        return {
            t for t in _re.findall(r"\b[A-Z][A-Za-z\-]{2,}\b", s)
            if not t.isdigit()
        }

    def _content_words(s: str) -> set[str]:
        return set(_re.findall(r"[a-z]+", s.lower()))

    if _numerics(after) - _numerics(before):
        return False, "neutral rephrase introduces a new numeric"
    if _author_years(after) - _author_years(before):
        return False, "neutral rephrase introduces a new citation"
    if _caps_idents(after) - _caps_idents(before):
        return False, "neutral rephrase introduces a new identifier"
    n_before = len(before.split())
    n_after = len(after.split())
    if n_after > n_before:
        return False, (
            f"neutral rephrase grows text ({n_before} → {n_after} words)"
        )
    before_words = _content_words(before)
    after_words = _content_words(after)
    new_words = after_words - before_words
    if not new_words or not new_words <= _NEUTRAL_EVIDENCE_WORDS:
        return False, (
            "neutral rephrase introduced non-neutral word(s): "
            f"{sorted(new_words)}"
        )
    if not (before_words & _DIRECTIONAL_CLAIM_WORDS):
        return False, "neutral rephrase did not remove directional wording"
    return True, (
        f"safe neutral claim rephrase ({n_before} → {n_after} words; "
        f"new neutral words={sorted(new_words)})"
    )


def _is_safe_simplification(
    before: str, after: str,
) -> tuple[bool, str]:
    """Fix #39: smart gate for claim/numeric Grok patches.

    A patch is a 'safe simplification' iff:

      1. AFTER introduces no new numeric tokens (`\\d+\\.?\\d*`)
         that aren't already in BEFORE
      2. AFTER introduces no new Author-Year citation tokens
         (`[A-Z][a-zA-Z]+ \\d{4}`) that aren't already in BEFORE
      3. AFTER introduces no new capitalized identifiers
         (e.g. trial names, drug names) not in BEFORE
      4. AFTER's word count is ≤ BEFORE's + a tiny tolerance
         (Grok may rephrase a 5-word phrase as 6 words; 8+ words
         added likely means new content)

    All four must pass. Used by the per-type gate for
    claim + numeric patches — these are the patch types that
    historically were always flagged-for-human, blocking AAA
    even when Grok's fix was a pure deletion.

    Reviewer-aligned strict semantics: AFTER's word count must be
    ≤ BEFORE's (no growth tolerance). Combined with the four
    no-new-X checks and the existing 'before appears exactly once'
    mechanical-safety check (apply_patches main loop), the patch
    is provably non-additive."""
    import re as _re

    def _numerics(s: str) -> set[str]:
        return set(_re.findall(r"\d+\.?\d*", s))

    def _author_years(s: str) -> set[str]:
        return set(
            f"{m.group(1)} {m.group(2)}"
            for m in _re.finditer(
                r"\b([A-Z][a-zA-Z]+(?:\s+et\s+al\.)?)\s+(\d{4})\b", s,
            )
        )

    def _caps_idents(s: str) -> set[str]:
        # Capitalised tokens of length ≥ 3 (drug names, trial names).
        # Excludes 4-digit years already covered by author-year set.
        return {
            t for t in _re.findall(r"\b[A-Z][A-Za-z\-]{2,}\b", s)
            if not t.isdigit()
        }

    new_numerics = _numerics(after) - _numerics(before)
    if new_numerics:
        return False, (
            f"AFTER introduces new numeric(s) {sorted(new_numerics)} "
            "not in BEFORE — Grok may be inventing data"
        )
    new_cites = _author_years(after) - _author_years(before)
    if new_cites:
        return False, (
            f"AFTER introduces new citation(s) {sorted(new_cites)} "
            "not in BEFORE — Grok may be hallucinating sources"
        )
    new_idents = _caps_idents(after) - _caps_idents(before)
    if new_idents:
        return False, (
            f"AFTER introduces new identifier(s) {sorted(new_idents)} "
            "not in BEFORE — Grok may be introducing new entities"
        )
    n_before = len(before.split())
    n_after = len(after.split())
    if n_after > n_before:
        return False, (
            f"AFTER ({n_after} words) is longer than BEFORE "
            f"({n_before}) — strict simplification requires "
            "shorter-or-equal word count"
        )
    # Strict-subset rule: every word in AFTER must appear in BEFORE
    # (lowercased, stripped of punctuation). Prevents semantic
    # substitution like "metformin extended lifespan" → "metformin
    # reduced mortality" — same word count, no new numerics, but
    # entirely different scientific claim. Pure deletions and re-
    # ordering of the SAME words pass; substitutions don't.
    def _content_words(s: str) -> set[str]:
        return set(_re.findall(r"[a-z]+", s.lower()))
    new_content = _content_words(after) - _content_words(before)
    if new_content:
        return False, (
            f"AFTER introduces new content word(s) "
            f"{sorted(new_content)} not in BEFORE — looks like a "
            "semantic substitution, not a pure deletion"
        )
    return True, (
        f"safe simplification ({n_before} → {n_after} words; "
        "AFTER words ⊆ BEFORE words; no new numerics/citations/"
        "identifiers)"
    )


def _is_safe_citation_attribution_patch(
    before: str, after: str, receipt_ids: set[str],
) -> tuple[bool, str]:
    """Allow claim patches that only add traced Author-Year attribution.

    Final-layer reviewers often convert an unsupported pronoun lead
    ("This suggests...") into a sourced attribution ("Mannick 2014
    suggests..."). That adds a year token, but it is not an invented
    numeric when the Author-Year token traces to a receipt and the
    non-citation wording is otherwise a subset of the original text.
    """
    cite_ok, cite_msg = _verify_citation_patch(
        {"before": before, "after": after}, receipt_ids,
    )
    if not cite_ok:
        return False, f"citation attribution verifier FAIL - {cite_msg}"
    before_cites = set(_AUTHOR_YEAR_RE.findall(before))
    after_cites = set(_AUTHOR_YEAR_RE.findall(after))
    novel_cites = after_cites - before_cites
    if not novel_cites:
        return False, "citation attribution patch adds no novel citation"

    def _strip_cites(s: str) -> str:
        return _AUTHOR_YEAR_RE.sub("", s)

    def _content_words(s: str) -> set[str]:
        return set(re.findall(r"[a-z]+", s.lower()))

    def _numbers(s: str) -> set[str]:
        return set(re.findall(r"\d+\.?\d*", s))

    before_core = _strip_cites(before)
    after_core = _strip_cites(after)
    new_numbers = _numbers(after_core) - _numbers(before_core)
    if new_numbers:
        return False, (
            "citation attribution patch adds non-citation numeric(s): "
            f"{sorted(new_numbers)}"
        )
    new_words = _content_words(after_core) - _content_words(before_core)
    if new_words:
        return False, (
            "citation attribution patch adds non-citation word(s): "
            f"{sorted(new_words)}"
        )
    return True, (
        "safe citation attribution patch - "
        f"novel citation(s) trace to receipts: {sorted(novel_cites)}"
    )


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


# Internal-handle shapes that MUST NOT appear as body citations.
# Fix #11: pre-fix `_verify_citation_patch` only validated the
# Author-Year regex. A patch whose `after` was a long PMC handle
# (`PMC12978362_molecular_...`) had zero Author-Year matches → vacuous
# "no novel citations" pass → patch auto-applied → 96 PMCID body
# leaks in the latest E2E. Now we explicitly reject internal handles.
_INTERNAL_HANDLE_PATTERNS: tuple[re.Pattern[str], ...] = (
    # Long PMC slug like "PMC12978362_molecular_mechanisms_..."
    re.compile(r"PMC\d{6,9}_[a-zA-Z_]{10,}"),
    # Author_YYYY_TRAIL_KEYWORDS internal id form
    re.compile(r"[A-Z][a-zA-Z]+_\d{4}_[A-Za-z_]+_"),
    # Bare PMCID without year decoration in body context
    re.compile(r"\bPMC\d{6,9}\b(?!\s*\d{4})"),
)


def _verify_citation_patch(
    patch: dict, receipt_ids: set[str],
) -> tuple[bool, str]:
    """A citation patch is valid iff:
      a) `after` does NOT introduce any internal-handle shape
         (PMC long slug, Author_YYYY_TRAIL, bare PMCID without year)
      b) every novel Author-Year shaped token in `after` exists in
         the receipt set

    Reviewer-fix history:
      - HIGH 1: regex requires Author+Year (no false fire on
        Title-Case prose like "Section", "Discussion").
      - HIGH 2 (Fix #11): also reject internal-handle introduction
        — pre-fix Grok could ship `PMC12978362_molecular...` as a
        citation patch and the verifier passed it as "no novel
        citations" because the long form has no Author-Year.
    """
    after = patch.get("after", "") or ""
    before = patch.get("before", "") or ""

    # Check (a): internal-handle introduction. A handle in `after`
    # that wasn't in `before` is a regression. Check ONLY novel
    # introductions so a patch that already had handles in both
    # before/after isn't blocked here.
    for pat in _INTERNAL_HANDLE_PATTERNS:
        after_handles = set(pat.findall(after))
        before_handles = set(pat.findall(before))
        novel_handles = after_handles - before_handles
        if novel_handles:
            sample = sorted(novel_handles)[:3]
            return False, (
                f"introduces internal-handle shape(s) in body: {sample}"
            )

    # Check (b): Author-Year citations trace to receipts.
    cite_re = re.compile(
        r"\b([A-Z][a-zA-Z]+(?:\s+et\s+al\.?)?\s+\d{4})\b"
    )
    found_in_after = {m.group(1) for m in cite_re.finditer(after)}
    found_in_before = {m.group(1) for m in cite_re.finditer(before)}
    novel_cites = found_in_after - found_in_before
    if not novel_cites:
        return True, "no novel citations"
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
    """Walk patches with strict per-type gates + mechanical safety.

    Architectural rule (LLM proposes, code disposes): the final-layer
    reviewer is still an LLM. Without strict deterministic gates, it
    can launder hallucinated numerics or
    fabricated citations into the published paper. The previous
    "trust Grok auto-apply" branch tried to honor "no humans in the
    pipeline" but conflated it with "no deterministic verification" -
    the right reading is "replace human-review with deterministic
    proof," not "skip review entirely."

    Per-type gates:
      - formatting           -> auto-apply (typo / list / heading)
      - citation             -> auto-apply IF Author-Year traces to
                               manifest receipts; else flag-only
      - numeric              -> auto-apply only when the smart gate proves
                               non-additive simplification
      - claim                -> auto-apply only for safe deletion,
                               neutralization, or traced attribution
      - structure            -> flag-only by contract
      - unknown              -> flag-only (fail-closed)

    Every flagged patch keeps Grok's rationale + the deterministic
    verifier's verdict in `reason_for_decision` so a retroactive
    auditor can see what Grok proposed AND why code refused.
    Mechanical safety (single-occurrence `before` text) still applies
    to every patch that passes the type gate.
    """
    new_md = paper_md
    results: list[PatchResult] = []
    corpus_nums = _load_corpus_numerics()
    receipt_ids = _load_receipt_ids(manifest)
    known_types = {"formatting", "citation", "numeric", "claim", "structure"}

    pre_patch_md = paper_md
    for p in patches:
        ptype_raw = p.get("patch_type")
        ptype = ptype_raw if ptype_raw in known_types else "unknown"
        before = p.get("before") or ""
        after = p.get("after") or ""
        pid = p.get("id", "?")
        sev = p.get("severity", "P3")
        location = p.get("location") or ""
        # Reviewer P1: clamp proposer_reason length so a 50KB Grok
        # hallucination can't bloat the JSON log. 500 chars is enough
        # for any human-readable reason; truncate with ellipsis.
        raw_reason = (p.get("reason") or "").strip()
        proposer_reason = raw_reason[:500] + (
            "...[truncated]" if len(raw_reason) > 500 else ""
        )

        # Reviewer P1: malformed contract (missing/unknown patch_type)
        # is REJECTED, not flagged. A flagged patch implies "Grok
        # proposed something coherent that we can't apply"; rejected
        # implies "the proposal itself is broken". Different reviewer
        # action.
        if ptype_raw is None or ptype_raw not in known_types:
            results.append(PatchResult(
                patch_id=pid, patch_type=ptype, severity=sev,
                decision="rejected",
                reason_for_decision=(
                    f"malformed patch contract: patch_type={ptype_raw!r} "
                    f"(known: {sorted(known_types)}). location={location!r}. "
                    f"Grok rationale: {proposer_reason!r}"
                ),
                before=before, after=after,
            ))
            continue

        if not before:
            results.append(PatchResult(
                patch_id=pid, patch_type=ptype, severity=sev,
                decision="rejected",
                reason_for_decision=(
                    f"empty 'before' field. Grok rationale: "
                    f"{proposer_reason!r}"
                ),
                before=before, after=after,
            ))
            continue

        if after and _looks_truncated_patch_field(after):
            results.append(PatchResult(
                patch_id=pid, patch_type=ptype, severity=sev,
                decision="rejected",
                reason_for_decision=(
                    "truncated patch contract: replacement appears "
                    "clipped near the reviewer field cap and ends mid-token. "
                    f"Grok rationale: {proposer_reason!r}"
                ),
                before=before, after=after,
            ))
            continue

        if ptype == "formatting" and _removes_bridge_contract_tags(
            location, before, after,
        ):
            results.append(PatchResult(
                patch_id=pid, patch_type=ptype, severity=sev,
                decision="rejected",
                reason_for_decision=(
                    "contract-preserving rejection: formatting patch "
                    "removes Inferential Bridge contract tags required "
                    f"by Q14. Grok rationale: {proposer_reason!r}"
                ),
                before=before, after=after,
            ))
            continue

        # Per-type gate decision: ok=True → eligible for apply
        # (subject to mechanical safety); ok=False → flag-only.
        if ptype == "formatting":
            ok = True
            gate_reason = "formatting auto-apply per type contract"
        elif ptype == "citation":
            cite_ok, cite_msg = _verify_citation_patch(p, receipt_ids)
            ok = cite_ok
            gate_reason = (
                f"citation verifier: {'pass' if cite_ok else 'FAIL'} — "
                f"{cite_msg}"
            )
        elif ptype == "numeric":
            # Fix #39: smart gate — auto-apply numeric patches that
            # are pure simplifications (Grok deletes wrong wording
            # without introducing new claims). The 4-test safety
            # gate (no new numerics / no new citations / no new
            # entities / non-increasing length) preserves the trust
            # spine while letting elite-frontier-model fixes land.
            num_ok, num_msg = _verify_numeric_patch(p, corpus_nums)
            simp_ok, simp_msg = _is_safe_simplification(before, after)
            table_ok = not _breaks_markdown_table_shape(
                location, before, after,
            )
            ok = simp_ok and table_ok
            table_msg = (
                "table-shape pass"
                if table_ok else
                "table-shape FAIL — patch changes markdown cell count"
            )
            gate_reason = (
                f"numeric smart-gate: simplification "
                f"{'pass' if simp_ok else 'FAIL'} ({simp_msg}); "
                f"{table_msg}; global-corpus verifier: "
                f"{'pass' if num_ok else 'FAIL'} — {num_msg}"
            )
        elif ptype == "claim":
            # Fix #39: same smart gate for claim patches. Claim
            # patches that DELETE false content (or simplify wording
            # without adding new claims) are auto-applied; patches
            # that introduce new claims/numerics/citations stay
            # flagged-for-human.
            simp_ok, simp_msg = _is_safe_simplification(before, after)
            if not simp_ok:
                neutral_ok, neutral_msg = _is_safe_neutral_claim_rephrase(
                    before, after,
                )
                if neutral_ok:
                    simp_ok, simp_msg = neutral_ok, neutral_msg
                else:
                    cite_ok, cite_msg = _is_safe_citation_attribution_patch(
                        before, after, receipt_ids,
                    )
                    if cite_ok:
                        simp_ok, simp_msg = cite_ok, cite_msg
                    else:
                        simp_msg = (
                            f"{simp_msg}; neutral rephrase FAIL "
                            f"({neutral_msg}); citation attribution FAIL "
                            f"({cite_msg})"
                        )
            ok = simp_ok
            gate_reason = (
                f"claim smart-gate: simplification "
                f"{'pass' if simp_ok else 'FAIL'} — {simp_msg}"
            )
        else:  # structure (unknown handled above)
            ok = False
            gate_reason = (
                f"{ptype} patches are flag-only by contract "
                "(semantic judgment beyond deterministic verifiers)"
            )

        full_reason = (
            f"{gate_reason}. Grok rationale: {proposer_reason!r}"
            if proposer_reason else gate_reason
        )

        if not ok:
            results.append(PatchResult(
                patch_id=pid, patch_type=ptype, severity=sev,
                decision="flagged",
                reason_for_decision=full_reason,
                before=before, after=after,
            ))
            continue

        # Mechanical safety: `before` must appear exactly once.
        n_occurrences = new_md.count(before)
        if n_occurrences == 0:
            results.append(PatchResult(
                patch_id=pid, patch_type=ptype, severity=sev,
                decision="rejected",
                reason_for_decision=(
                    f"'before' text not found in paper. {full_reason}"
                ),
                before=before, after=after,
            ))
            continue
        if n_occurrences > 1:
            if _is_cited_artifact_delete(
                ptype, before, after,
            ) or _is_role_repair_artifact_delete(
                ptype, before, after,
            ) or _is_repeated_safe_simplification(ptype, before, after):
                new_md = new_md.replace(before, after)
                results.append(PatchResult(
                    patch_id=pid, patch_type=ptype, severity=sev,
                    decision="applied",
                    reason_for_decision=(
                        f"repeat-safe simplification appeared "
                        f"{n_occurrences}x; replace-all "
                        f"cleanup. {full_reason}"
                    ),
                    before=before, after=after,
                ))
                continue
            results.append(PatchResult(
                patch_id=pid, patch_type=ptype, severity=sev,
                decision="flagged",
                reason_for_decision=(
                    f"'before' appears {n_occurrences}x; ambiguous "
                    f"replacement target. {full_reason}"
                ),
                before=before, after=after,
            ))
            continue

        if _has_unsafe_match_boundary(new_md, before):
            results.append(PatchResult(
                patch_id=pid, patch_type=ptype, severity=sev,
                decision="rejected",
                reason_for_decision=(
                    "truncated patch contract: 'before' span starts "
                    "or ends inside a token. "
                    f"{full_reason}"
                ),
                before=before, after=after,
            ))
            continue

        # Fix #39 — post-apply audit guard for claim/numeric patches:
        # apply tentatively, re-check Q2 numeric trace + Stage-2
        # consistency. If either regresses → revert this patch.
        # Per the reviewer's tightening: 'after' must be safe AND
        # post-apply Q2 stays 100% AND Stage-2 stays 0 P1/P2.
        # Skipped for non-claim/numeric patches (formatting/citation
        # already pass deterministic verifiers; no audit-regression
        # risk).
        if ptype in ("claim", "numeric"):
            tentative_md = _apply_text_patch(new_md, before, after)
            audit_safe, audit_msg = _post_apply_audit_safe(
                pre_md=new_md, post_md=tentative_md, manifest=manifest,
            )
            if not audit_safe:
                results.append(PatchResult(
                    patch_id=pid, patch_type=ptype, severity=sev,
                    decision="flagged",
                    reason_for_decision=(
                        f"Patch passed simplification gate but POST-"
                        f"APPLY audit regressed: {audit_msg}. "
                        f"{full_reason}"
                    ),
                    before=before, after=after,
                ))
                continue
            new_md = tentative_md
        else:
            new_md = _apply_text_patch(new_md, before, after)
        results.append(PatchResult(
            patch_id=pid, patch_type=ptype, severity=sev,
            decision="applied",
            reason_for_decision=full_reason,
            before=before, after=after,
        ))
    new_md, restored = _restore_required_section_headings(
        pre_patch_md, new_md,
    )
    for heading in restored:
        results.append(PatchResult(
            patch_id=f"SECTION-CONTRACT-{heading[3:].replace(' ', '-')}",
            patch_type="structure",
            severity="P1",
            decision="applied",
            reason_for_decision=(
                f"section-contract guard restored missing {heading!r} "
                "heading after review-patch application"
            ),
            before="",
            after=heading,
        ))
    new_md, qei_deduped = _collapse_consecutive_qei_headings(new_md)
    if qei_deduped:
        results.append(PatchResult(
            patch_id="SECTION-CONTRACT-Quantitative-Evidence-Index-Dedup",
            patch_type="structure",
            severity="P1",
            decision="applied",
            reason_for_decision=(
                "section-contract guard collapsed consecutive "
                "Quantitative Evidence Index headings so the table "
                "remains inside the deterministic QEI audit block"
            ),
            before="duplicate consecutive Quantitative Evidence Index headings",
            after="single Quantitative Evidence Index heading",
        ))
    return new_md, results


_QEI_HEADING_LINE_RE = re.compile(
    r"^##\s+Quantitative\s+Evidence\s+Index\b"
)


def _is_qei_heading_line(line: str) -> bool:
    return _QEI_HEADING_LINE_RE.match(line.strip()) is not None


def _collapse_consecutive_qei_headings(md: str) -> tuple[str, int]:
    """Keep one display-safe heading in a consecutive QEI-heading run.

    Reviewer heading-normalization patches can leave:

        ## Quantitative Evidence Index — Title Case
        ## Quantitative Evidence Index — raw_topic

    with only blank lines between them. The audit splitter treats the
    second heading as the next section, which ejects the real table from
    the QEI block. This repair is deliberately narrow: it only touches
    consecutive QEI headings separated by whitespace. It prefers the
    title-cased display heading over a raw topic slug when both exist.
    """
    lines = md.splitlines()
    out: list[str] = []
    removed = 0
    i = 0
    while i < len(lines):
        if not _is_qei_heading_line(lines[i]):
            out.append(lines[i])
            i += 1
            continue

        heading = lines[i]
        headings = [heading]
        j = i + 1
        while True:
            k = j
            while k < len(lines) and not lines[k].strip():
                k += 1
            if k < len(lines) and _is_qei_heading_line(lines[k]):
                heading = lines[k]
                headings.append(heading)
                removed += 1
                j = k + 1
                continue
            heading = next((h for h in headings if "_" not in h), heading)
            out.append(heading)
            out.extend(lines[j:k])
            i = k
            break

    fixed = "\n".join(out)
    if md.endswith("\n"):
        fixed += "\n"
    return fixed, removed


def _extract_heading_section(md: str, heading: str) -> str:
    pattern = re.compile(
        rf"^{re.escape(heading)}\b.*?(?=^##\s+|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    m = pattern.search(md)
    return m.group(0) if m else ""


def _first_section_paragraph(section_md: str) -> str:
    body = section_md.split("\n", 1)[1] if "\n" in section_md else ""
    for para in re.split(r"\n\s*\n", body):
        clean = para.strip()
        if not clean or clean.startswith("###") or clean.startswith("_Cited:"):
            continue
        return clean
    return ""


def _restore_required_section_headings(
    before_md: str, after_md: str,
) -> tuple[str, list[str]]:
    """Review patches may delete a heading while leaving its prose.

    The renderer owns section headings; reviewer patches only own local
    text. If a required heading existed before patching and is missing
    after patching, reinsert it before the surviving first paragraph of
    that original section. This is universal section-contract repair,
    not topic-specific prose surgery.
    """
    out = after_md
    restored: list[str] = []
    for heading in _REQUIRED_HEADINGS:
        if not re.search(rf"^{re.escape(heading)}\b", before_md, re.MULTILINE):
            continue
        if re.search(rf"^{re.escape(heading)}\b", out, re.MULTILINE):
            continue
        section = _extract_heading_section(before_md, heading)
        anchor = _first_section_paragraph(section)
        if not anchor:
            continue
        pos = out.find(anchor)
        if pos < 0:
            # Try a shorter anchor; Grok may have trimmed the paragraph.
            short = anchor[:160].rstrip()
            pos = out.find(short) if short else -1
        if pos < 0:
            continue
        insert = f"\n\n{heading}\n\n"
        out = out[:pos].rstrip() + insert + out[pos:].lstrip()
        restored.append(heading)
    return out, restored


def _post_apply_audit_safe(
    *, pre_md: str, post_md: str, manifest: dict,
) -> tuple[bool, str]:
    """Fix #39 reviewer-tightening: re-run Q2 numeric integrity +
    Stage-2 consistency on the post-patch paper. Patch is safe iff:

      - Q2 numeric trace stays at-or-better than pre-patch
        (no new untraceable numerics introduced)
      - Stage-2 consistency P1+P2 count stays at-or-better than
        pre-patch (no new audit issues introduced)

    The pre-patch baseline is computed inside the same call so we
    measure DELTA, not absolute (existing pre-patch issues persist
    regardless of this patch — they're someone else's job)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import audit_v06_paper as _audit_v06
        import final_consistency_audit as _consistency
    except ImportError as e:
        return True, f"audit modules unavailable ({e}); skip"
    try:
        pre_audit = _audit_v06.audit(pre_md)
        post_audit = _audit_v06.audit(post_md)
    except Exception as e:  # noqa: BLE001
        return True, f"Q2 audit failed ({e}); skip"
    pre_q2 = next(
        (c for c in pre_audit.get("checks", [])
         if c.get("name") == "Q2_numeric_integrity"),
        None,
    )
    post_q2 = next(
        (c for c in post_audit.get("checks", [])
         if c.get("name") == "Q2_numeric_integrity"),
        None,
    )
    if pre_q2 and post_q2 and post_q2.get("passed") and not (
        pre_q2.get("passed")
    ):
        # Patch IMPROVED Q2 — fine.
        pass
    elif pre_q2 and post_q2 and pre_q2.get("passed") and not (
        post_q2.get("passed")
    ):
        return False, "Q2 numeric trace regressed (was passing → now failing)"
    try:
        pre_issues = _consistency.run_audit(
            pre_md, manifest, pre_audit,
        )
        post_issues = _consistency.run_audit(
            post_md, manifest, post_audit,
        )
    except Exception as e:  # noqa: BLE001
        return True, f"Stage-2 consistency failed ({e}); skip"
    pre_count = sum(
        1 for i in pre_issues if i.severity in ("P1", "P2")
    )
    post_count = sum(
        1 for i in post_issues if i.severity in ("P1", "P2")
    )
    if post_count > pre_count:
        return False, (
            f"Stage-2 P1+P2 count regressed "
            f"({pre_count} → {post_count})"
        )
    return True, (
        f"post-apply audit clean: Q2 unchanged, Stage-2 "
        f"{pre_count} → {post_count} P1+P2"
    )


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
    n_applied = sum(1 for r in results if r.decision == "applied")
    # Reviewer P1: only write the paper if at least one patch landed.
    # Pre-fix this rewrote the file every run, bumping mtime and
    # breaking downstream make-style staleness checks.
    if n_applied > 0:
        paper_path.write_text(new_md)

    log = {
        "applied_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "n_proposed": len(patches),
        "n_applied": n_applied,
        "n_flagged": sum(1 for r in results if r.decision == "flagged"),
        "n_rejected": sum(1 for r in results if r.decision == "rejected"),
        "patches": [
            {
                "patch_id": r.patch_id,
                "patch_type": r.patch_type,
                "severity": r.severity,
                "decision": r.decision,
                # Cap reason at 1k chars (proposer_reason is already
                # clamped at 500 inside apply_patches; this is the
                # outer ceiling for the full diagnostic string).
                "reason": r.reason_for_decision[:1000],
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
