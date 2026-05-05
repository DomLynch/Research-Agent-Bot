"""Corpus Expansion Mode — Wave 7 reviewer fix (2026-05-05).

When a synthesis run lands below the certification floor, "Trust-Spine
Pass" alone is a dead-end signal: the operator sees "below floor" but
has no actionable next step. This module turns every failed verdict
into a structured corpus-expansion to-do list so the next run targets
the gap directly.

Universal across topics: pure manifest signals + frozen thresholds.
No drug names, no per-topic logic, no LLM calls. The reviewer
(internal or external) can read `corpus_gaps` to understand why the
verdict is below AAA and `expansion_targets` to know which corpus
operations would close the gap.

Returned as tuples (not lists) so they slot into the frozen+slots
UnifiedVerdict dataclass without violating immutability.
"""
from __future__ import annotations

from typing import Any

# Outcome diversity floor: one-class corpora can't surface
# non-orthogonal tensions and rarely earn AAA.
_MIN_OUTCOME_CLASSES = 3
# Direct-evidence floor: at least 2 receipts with directness="direct"
# (RCT / pragmatic trial). Otherwise the synthesis leans on reviews.
_MIN_DIRECT_RECEIPTS = 2
# Tier floor: at least 2 receipts at A1/A2 tier.
_MIN_HIGH_TIER_RECEIPTS = 2
# Single-paper dominance ceiling: no paper may contribute more than
# this fraction of receipts (else corpus is shallow / over-relying).
_MAX_SINGLE_PAPER_DOMINANCE = 0.4


def _bucket(receipts: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """Tally outcome_class / evidence_tier / directness."""
    out: dict[str, dict[str, int]] = {
        "outcome_class": {}, "evidence_tier": {}, "directness": {},
    }
    for r in receipts:
        for key in out:
            v = (r.get(key) or "").strip() or "unspecified"
            out[key][v] = out[key].get(v, 0) + 1
    return out


def compute_corpus_gaps(
    manifest: dict[str, Any],
    *,
    min_receipts: int,
    min_claims: int,
    min_tensions: int,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Returns (gaps, targets).

    `gaps` — human-readable diagnosis (one bullet per gap).
    `targets` — imperative to-dos paired 1:1 with gaps (operator
                action that would close the gap).

    Both empty when corpus already meets all gates."""
    n_rec = int(manifest.get("n_receipts", 0))
    n_claims = int(manifest.get("n_high_confidence_claims_total", 0))
    n_tens = int(manifest.get("n_non_orthogonal_tensions", 0))
    receipts = manifest.get("receipts") or []
    buckets = _bucket(receipts)

    gaps: list[str] = []
    targets: list[str] = []

    # ---- Quantity gaps ------------------------------------------
    if n_rec < min_receipts:
        delta = min_receipts - n_rec
        gaps.append(
            f"Receipts: {n_rec}/{min_receipts} (short by {delta})"
        )
        targets.append(
            f"Add ≥{delta} more topic-fit receipts via "
            f"`scripts/seed_topic_corpus.py --topic <T> "
            f"--max-papers {max(20, delta * 4)}`."
        )
    if n_claims < min_claims:
        delta = min_claims - n_claims
        gaps.append(
            f"High-confidence claims: {n_claims}/{min_claims} "
            f"(short by {delta})"
        )
        targets.append(
            f"Re-run extraction on existing parsed papers and/or "
            f"expand corpus; need ≥{delta} more bound numeric claims."
        )
    if n_tens < min_tensions:
        delta = min_tensions - n_tens
        gaps.append(
            f"Non-orthogonal tensions: {n_tens}/{min_tensions} "
            f"(short by {delta})"
        )
        targets.append(
            f"Add receipts that contradict or complicate existing "
            f"findings; need ≥{delta} more cross-receipt tensions."
        )

    # ---- Quality gaps (only when we have any receipts) ----------
    if receipts:
        oc = buckets["outcome_class"]
        if len(oc) < _MIN_OUTCOME_CLASSES:
            gaps.append(
                f"Outcome diversity: only {len(oc)} classes "
                f"({', '.join(sorted(oc))}); floor "
                f"{_MIN_OUTCOME_CLASSES}"
            )
            targets.append(
                "Broaden retrieval queries to capture complementary "
                "endpoints (additional outcome classes)."
            )

        n_direct = buckets["directness"].get("direct", 0)
        if n_direct < _MIN_DIRECT_RECEIPTS:
            gaps.append(
                f"Direct-evidence receipts: {n_direct}/"
                f"{_MIN_DIRECT_RECEIPTS} (have only reviews/"
                f"indirect/mechanistic)"
            )
            targets.append(
                f"Add ≥{_MIN_DIRECT_RECEIPTS - n_direct} direct "
                f"trial/RCT receipts (ClinicalTrials.gov, pragmatic-"
                f"trial queries)."
            )

        n_high = sum(
            buckets["evidence_tier"].get(t, 0) for t in ("A1", "A2")
        )
        if n_high < _MIN_HIGH_TIER_RECEIPTS:
            gaps.append(
                f"A-tier receipts: {n_high}/{_MIN_HIGH_TIER_RECEIPTS} "
                f"(corpus leans on B/C tier)"
            )
            targets.append(
                f"Add ≥{_MIN_HIGH_TIER_RECEIPTS - n_high} A1/A2 "
                f"sources (Cochrane review / large RCT / pragmatic "
                f"trial)."
            )

        if n_rec >= 3:
            paper_counts: dict[str, int] = {}
            for r in receipts:
                pid = (
                    r.get("receipt_id") or r.get("paper_id") or "_"
                )
                paper_counts[pid] = paper_counts.get(pid, 0) + 1
            top_id, top_n = max(
                paper_counts.items(), key=lambda kv: kv[1],
            )
            if top_n / max(n_rec, 1) > _MAX_SINGLE_PAPER_DOMINANCE:
                gaps.append(
                    f"Single-paper dominance: '{top_id}' contributes "
                    f"{top_n}/{n_rec} receipts (>40%)"
                )
                targets.append(
                    "Diversify retrieval — current corpus is "
                    "over-reliant on one source."
                )

    return tuple(gaps), tuple(targets)


def format_expansion_section(
    gaps: tuple[str, ...], targets: tuple[str, ...],
) -> str:
    """Markdown block appended to `final_verdict.md` when gaps exist.

    Pairs gap-with-target so an operator sees diagnosis + action
    side-by-side. Empty string when both inputs are empty (caller
    can `+= format_expansion_section(...)` unconditionally)."""
    if not gaps and not targets:
        return ""
    lines = ["", "## Corpus Expansion To-Do", ""]
    lines.append(
        "Pipeline ran cleanly but the corpus is below the "
        "certification floor. Each gap below maps to a concrete "
        "expansion operation; the next run after closing them "
        "should clear AAA without prompt-side changes.",
    )
    lines.append("")
    n = max(len(gaps), len(targets))
    for i in range(n):
        gap = gaps[i] if i < len(gaps) else ""
        tgt = targets[i] if i < len(targets) else ""
        lines.append(f"- **Gap:** {gap}")
        if tgt:
            lines.append(f"  - **Action:** {tgt}")
    lines.append("")
    return "\n".join(lines)


__all__ = ["compute_corpus_gaps", "format_expansion_section"]
