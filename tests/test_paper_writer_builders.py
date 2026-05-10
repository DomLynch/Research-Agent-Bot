"""Tests for agent/paper_writer_builders.py — Day 10.17 Fix C.3.

The builders take parsed LLM JSON envelopes and turn them into
SynthesisSection objects. The LLM occasionally emits malformed
receipt IDs (e.g. "cfab-01" instead of "cfab-c01") in the
`receipt_ids` field of a paragraph. Pre-fix, those typos rendered
verbatim into the paper's `_Cited:` footer and triggered Q9 (which
was non-load-bearing, so the artifact still shipped). Reviewer
prescription: prevent-by-design — repair plausibly-typo'd receipt
IDs at the builder layer via stdlib difflib fuzzy match. Drop IDs
that don't fuzzy-match any valid receipt.
"""
from __future__ import annotations

from agent.paper_writer_builders import (
    build_anchored_from_parsed,
    build_results_from_parsed,
    build_scoped_from_parsed,
)
from agent.synthesis_schemas import ReceiptSummary


def _accepted(
    rid: str,
    *,
    p_values: tuple[str, ...] = (),
    outcome_class: str = "muscle_function",
) -> ReceiptSummary:
    return ReceiptSummary(
        receipt_id=rid, receipt_path=f"runs/{rid}", topic="metformin",
        thesis_text=f"thesis for {rid}",
        spar_verdict="accept_clean",
        n_claims=1, n_failed_traces=0, canonical_trial_id=None,
        evidence_tier="A1", directness="direct",
        outcome_class=outcome_class, effect_direction="negative",
        p_values=p_values, population_summary="older adults",
    )


# ============================================================
# Day 10.17 Fix C.3 — Receipt-ID typo repair
# ============================================================
# Empirical bug from the 18:27 ship-criterion-met run: brief's
# _Cited: footer rendered "cfab-01" (the LLM dropped the 'c' prefix
# in the receipt_ids JSON field). The body's inline citation was
# correct (cfab-c01); only the structured field was off-by-one. Q9
# caught this but was non-load-bearing, so the artifact shipped
# with a broken citation chain. Fix C.3 repairs at the builder
# layer.


def test_anchored_repairs_receipt_id_with_one_char_typo() -> None:
    """LLM emits 'cfab-01' in receipt_ids; the closest valid id is
    'metformin-multi-001-cfab-c01' — stdlib difflib should snap to
    it. The repaired _Cited: footer must show the corrected id."""
    accepted = [_accepted("metformin-multi-001-cfab-c01", p_values=("p=0.005",))]
    parsed = {
        "paragraphs": [
            {
                "text": "Direct trial reported reductions at p=0.005.",
                "receipt_ids": ["metformin-multi-001-cfab-01"],  # typo
            },
        ],
    }
    section = build_anchored_from_parsed(
        parsed, name="results", heading="## Results", accepted=accepted,
    )
    assert section is not None
    body = section.body_md
    assert "metformin-multi-001-cfab-c01" in body  # repaired
    # The malformed form must NOT appear anywhere
    assert "cfab-01`" not in body  # in `_Cited:` footer
    assert "[metformin-multi-001-cfab-01]" not in body
    # And the anchor should carry the corrected id
    assert section.anchors[0].receipt_ids == ("metformin-multi-001-cfab-c01",)


def test_scoped_repairs_receipt_id_with_one_char_typo() -> None:
    """Same fix in the scoped builder (Background, Discussion, etc.).
    Text must satisfy the SCOPED validator: topic alias ≥2x + hedge
    phrase per paragraph."""
    accepted = [_accepted("metformin-multi-001-cfab-c01")]
    parsed = {
        "paragraphs": [
            {
                "text": (
                    "Metformin may modulate metabolic pathways in this "
                    "corpus, although the metformin evidence appears "
                    "to be limited to mechanistic data."
                ),
                "receipt_ids": ["metformin-multi-001-cfab-01"],  # typo
            },
        ],
    }
    section = build_scoped_from_parsed(
        parsed, name="background", heading="## Background",
        topic="metformin", accepted=accepted,
    )
    assert section is not None
    body = section.body_md
    assert "metformin-multi-001-cfab-c01" in body
    assert "cfab-01`" not in body


def test_scoped_accepts_prose_topic_alias_for_underscore_topic() -> None:
    """Topic ids are file-safe, but manuscripts use prose labels.
    `intermittent_fasting` must validate against `intermittent fasting`.
    """
    parsed = {"paragraphs": [{
        "text": (
            "Intermittent fasting may improve cardiometabolic outcomes, "
            "but intermittent fasting remains context-dependent."
        ),
        "receipt_ids": [],
    }]}
    section = build_scoped_from_parsed(
        parsed, name="discussion", heading="## Discussion",
        topic="intermittent_fasting", accepted=[_accepted("r1")],
    )
    assert section is not None


def test_anchored_drops_fabricated_receipt_id_with_no_close_match() -> None:
    """LLM hallucinates a totally fake id ('metformin-fake-cluster-99').
    No valid id is within fuzzy-match distance, so the id gets dropped
    from receipt_ids. The paragraph ends up uncited and the existing
    anchored validator drops it → section returns None.

    Day 10.17 Fix C.3 reviewer pin: assertion is `is None` not
    `is None or fabricated-not-in-body` — the loose form would
    silently pass a regression where a fabricated id rendered next
    to a hallucinated valid id."""
    accepted = [_accepted("metformin-multi-001-cfab-c01", p_values=("p=0.005",))]
    parsed = {
        "paragraphs": [
            {
                "text": "Trial finding cited at p=0.005.",
                "receipt_ids": ["metformin-fake-cluster-99"],  # fabricated
            },
        ],
    }
    section = build_anchored_from_parsed(
        parsed, name="results", heading="## Results", accepted=accepted,
    )
    assert section is None


def test_anchored_keeps_correct_receipt_id_unchanged() -> None:
    """Sanity: when the LLM emits the right id, the builder doesn't
    touch it."""
    accepted = [_accepted("metformin-multi-001-cfab-c01", p_values=("p=0.005",))]
    parsed = {
        "paragraphs": [
            {
                "text": "Trial finding cited at p=0.005.",
                "receipt_ids": ["metformin-multi-001-cfab-c01"],
            },
        ],
    }
    section = build_anchored_from_parsed(
        parsed, name="results", heading="## Results", accepted=accepted,
    )
    assert section is not None
    assert section.anchors[0].receipt_ids == ("metformin-multi-001-cfab-c01",)


def test_anchored_repair_handles_mixed_correct_and_typo_ids() -> None:
    """Paragraph cites two ids: one correct, one typo. The typo is
    repaired; the correct one stays. Final receipt_ids list contains
    both real ids."""
    accepted = [
        _accepted("metformin-multi-001-cfab-c01", p_values=("p=0.005",)),
        _accepted("metformin-multi-001-cfab-c04"),
    ]
    parsed = {
        "paragraphs": [
            {
                "text": "Two-receipt sentence at p=0.005.",
                "receipt_ids": [
                    "metformin-multi-001-cfab-c01",  # correct
                    "metformin-multi-001-cfab-04",   # typo
                ],
            },
        ],
    }
    section = build_anchored_from_parsed(
        parsed, name="results", heading="## Results", accepted=accepted,
    )
    assert section is not None
    rids = section.anchors[0].receipt_ids
    assert "metformin-multi-001-cfab-c01" in rids
    assert "metformin-multi-001-cfab-c04" in rids
    assert "metformin-multi-001-cfab-04" not in rids


def test_results_drops_receipt_from_wrong_outcome_subsection() -> None:
    accepted = [
        _accepted(
            "walton-2019",
            p_values=("p=0.003",),
            outcome_class="muscle_function",
        ),
        _accepted(
            "kim-2020",
            p_values=("p=0.01",),
            outcome_class="cardiometabolic",
        ),
    ]
    parsed = {
        "subsections": [
            {
                "heading": "Cardiometabolic Outcomes",
                "paragraphs": [
                    {
                        "text": "Walton reports p=0.003.",
                        "receipt_ids": ["walton-2019"],
                    },
                    {
                        "text": "Kim reports p=0.01.",
                        "receipt_ids": ["kim-2020"],
                    },
                ],
            },
        ],
    }

    section = build_results_from_parsed(parsed, accepted=accepted)

    assert section is not None
    assert "Kim reports" in section.body_md
    assert "Walton reports" not in section.body_md
