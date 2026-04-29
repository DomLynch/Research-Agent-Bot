"""Q3 invariant helpers for synthesis_writer (Day 10.16e).

Day 10.16d audit ship-blocked on Q3-mohammed-direct-vs-indirect:
the brief's Synthesis section produced no paragraph that integrated
direct + mechanistic receipts. The audit catches this, but only at
the END — too late to retry. Day 10.16e moves the check inside the
writer so the LLM gets a chance to fix its output before the audit
runs.

Why a separate module: keeps `synthesis_writer.py` under the 600
per-file cloc cap (raised once already; the project's hard rule is
extract-not-grow when a file would tip over).
"""
from __future__ import annotations

from collections.abc import Sequence

from agent.synthesis_schemas import ReceiptSummary, SynthesisSection

__all__ = [
    "Q3_TRANSITION_PHRASES",
    "synthesis_has_mixed_directness_anchor",
    "q3_retry_user_prompt",
    "SYNTHESIS_Q3_RETRY_BUDGET",
]


# Mirrors agent/synthesis_audit.py::_TRANSITION_PHRASES verbatim.
# Kept in sync deliberately rather than imported to avoid a writer→
# audit cycle. If audit's list changes, update here too.
Q3_TRANSITION_PHRASES = (
    "mechanistically",
    "in vitro",
    "preclinically",
    "in contrast",
    "however,",
    "by contrast",
    # Day 10.16f — see synthesis_audit.py for the rationale; both lists
    # MUST stay in lockstep (test_transition_phrases_match_audit_set).
    "consequently,",
    "therefore,",
    # Day 10.16g — full canonical-discourse-marker expansion.
    "ultimately,",
    "thus,",
    "conversely,",
    "nevertheless,",
    "nonetheless,",
)


# Max LLM retries when the Q3 invariant fails on the first attempt.
# Mirrors paper_writer's SECTION_RETRY_BUDGET=1 — a model that
# under-integrates twice in a row is unlikely to do better on
# attempt 3, and the LLM budget is finite.
SYNTHESIS_Q3_RETRY_BUDGET = 1


def _normalize(text: str) -> str:
    return " ".join(text.replace("·", ".").split()).lower()


def synthesis_has_mixed_directness_anchor(
    section: SynthesisSection, receipts: Sequence[ReceiptSummary],
) -> bool:
    """Q3 invariant: when the corpus has both `direct` and (`mechanistic`
    or `indirect`) receipts, at least one synthesis anchor must cite
    BOTH a direct AND a mechanistic/indirect receipt in its
    `receipt_ids` list AND start with a transition phrase.

    Returns True if the invariant is satisfied OR not applicable
    (uniform-directness corpus). Returns False only when the corpus
    is mixed-directness but the section has no integrating paragraph.
    """
    by_id = {r.receipt_id: r for r in receipts}
    corpus_dirs = {r.directness for r in receipts}
    has_mixed_corpus = "direct" in corpus_dirs and (
        "mechanistic" in corpus_dirs or "indirect" in corpus_dirs
    )
    if not has_mixed_corpus:
        return True
    for anchor in section.anchors:
        dirs = {
            by_id[rid].directness
            for rid in anchor.receipt_ids
            if rid in by_id
        }
        is_mixed = "direct" in dirs and (
            "mechanistic" in dirs or "indirect" in dirs
        )
        if not is_mixed:
            continue
        sentence_norm = _normalize(anchor.sentence)
        if any(t in sentence_norm for t in Q3_TRANSITION_PHRASES):
            return True
    return False


def q3_retry_user_prompt(
    base_user_prompt: str, receipts: Sequence[ReceiptSummary],
) -> str:
    """Build an explicit Q3-correction nudge appended to the base user
    prompt. Names the actual receipt IDs by directness so the LLM has
    no excuse for picking same-directness pairs again."""
    direct_ids = [
        r.receipt_id for r in receipts if r.directness == "direct"
    ]
    mech_ids = [
        r.receipt_id for r in receipts
        if r.directness in ("mechanistic", "indirect")
    ]
    return (
        base_user_prompt
        + "\n\nQ3 RETRY GUIDANCE: the previous attempt produced no "
        "mixed-directness sentence. The audit will REJECT this paper. "
        "You MUST include at least one sentence that cites BOTH a "
        f"DIRECT receipt ({', '.join(direct_ids) or '(none)'}) AND a "
        f"MECHANISTIC/INDIRECT receipt ({', '.join(mech_ids) or '(none)'}) "
        "in the SAME `receipt_ids` list, AND that sentence MUST start "
        "with one of these transition phrases (case-insensitive): "
        "'Mechanistically,', 'Preclinically,', 'In vitro,', "
        "'In contrast,', 'However,', 'By contrast,', 'Consequently,', "
        "'Therefore,', 'Ultimately,', 'Thus,', 'Conversely,', "
        "'Nevertheless,', 'Nonetheless,'. Re-write ALL synthesis "
        "sentences now — every mixed-directness sentence (any sentence "
        "whose receipt_ids list contains both a direct and a "
        "mechanistic/indirect id) must begin with one of these phrases. "
        "The audit checks every such sentence, not just the first."
    )
