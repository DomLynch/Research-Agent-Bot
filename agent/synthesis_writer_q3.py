"""Q3 directness checks inside the writer allow bounded retry before the final audit."""
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
    # Day 10.17 Fix C.2 — see synthesis_audit.py for rationale; both
    # lists MUST stay in lockstep (test_transition_phrases_match_audit_set).
    "the tension between",
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
    """Mirror synthesis_audit Q3: mixed-directness corpora need a mixed anchor, and every mixed anchor needs a transition. Uniform corpora pass vacuously."""
    by_id = {r.receipt_id: r for r in receipts}
    corpus_dirs = {r.directness for r in receipts}
    has_mixed_corpus = "direct" in corpus_dirs and (
        "mechanistic" in corpus_dirs or "indirect" in corpus_dirs
    )
    if not has_mixed_corpus:
        return True
    mixed_count = 0
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
        mixed_count += 1
        sentence_norm = _normalize(anchor.sentence)
        if not any(t in sentence_norm for t in Q3_TRANSITION_PHRASES):
            return False
    # corpus mixed but synthesis has no integrating anchor → fail
    return mixed_count > 0


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
        + "\n\nQ3 RETRY GUIDANCE: the previous attempt produced "
        "mixed-directness sentences that did not start with an "
        "approved cross-class transition. The audit will REJECT "
        "this paper. Required fix:\n\n"
        "1. Every sentence whose `receipt_ids` list contains BOTH a "
        f"DIRECT receipt ({', '.join(direct_ids) or '(none)'}) AND a "
        f"MECHANISTIC/INDIRECT receipt ({', '.join(mech_ids) or '(none)'}) "
        "MUST begin with one of these accepted markers (case-insensitive):\n"
        "   'Mechanistically,', 'Preclinically,', 'In vitro,',\n"
        "   'In contrast,', 'However,', 'By contrast,',\n"
        "   'Consequently,', 'Therefore,', 'Ultimately,', 'Thus,',\n"
        "   'Conversely,', 'Nevertheless,', 'Nonetheless,',\n"
        "   'The tension between' (use ONLY when explicitly naming\n"
        "   a cross-class tension as the subject of the sentence)\n\n"
        "2. CONCRETE EXAMPLES of FAIL vs PASS shapes:\n"
        "   FAIL: 'Metformin appears to modulate metabolic and "
        "nonmetabolic pathways.' (no transition; generic claim)\n"
        "   FAIL: 'Furthermore, the drug acts on multiple targets.' "
        "(additive transition, not cross-class)\n"
        "   PASS: 'Mechanistically, metformin modulates pathways, "
        "but the clinical RCT shows reduced muscle gain.'\n"
        "   PASS: 'However, the preclinical longevity signal contrasts "
        "with the clinical muscle suppression.'\n"
        "   PASS: 'The tension between systemic metabolic benefit "
        "and localized muscle cost remains unresolved.'\n\n"
        "3. The audit checks EVERY mixed-directness sentence, not "
        "just the first. Re-write all synthesis sentences now."
    )
