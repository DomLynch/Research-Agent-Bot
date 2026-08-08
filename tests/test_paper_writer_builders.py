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
from agent.synthesis_schemas import OutcomeClass, ReceiptSummary


def _accepted(
    rid: str,
    *,
    outcome_class: OutcomeClass = "muscle_function",
    p_values: tuple[str, ...] = (),
    thesis_text: str | None = None,
) -> ReceiptSummary:
    return ReceiptSummary(
        receipt_id=rid, receipt_path=f"runs/{rid}", topic="metformin",
        thesis_text=thesis_text or f"thesis for {rid}",
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


def test_scoped_requires_anchor_for_prose_topic_alias() -> None:
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
    assert section is None


def test_scoped_accepts_anchored_prose_topic_alias() -> None:
    parsed = {"paragraphs": [{
        "text": (
            "Intermittent fasting may improve cardiometabolic outcomes, "
            "but intermittent fasting remains context-dependent."
        ),
        "receipt_ids": ["r1"],
    }]}
    section = build_scoped_from_parsed(
        parsed, name="discussion", heading="## Discussion",
        topic="intermittent_fasting", accepted=[_accepted("r1")],
    )
    assert section is not None


def test_scoped_numeric_forms_must_exist_in_anchored_corpus() -> None:
    numeric_text = (
        "The trial enrolled n = 120 at age 65, used 10 mg for 12 weeks, "
        "and reported mean 4.2."
    )
    accepted = [_accepted("r1", thesis_text=numeric_text)]
    parsed = {"paragraphs": [{
        "text": (
            "Metformin may remain uncertain after n = 120 participants at age 65 "
            "used 10 mg for 12 weeks and metformin produced mean 4.2."
        ),
        "receipt_ids": ["r1"],
    }]}
    assert build_scoped_from_parsed(
        parsed, name="discussion", heading="## Discussion",
        topic="metformin", accepted=accepted,
    ) is not None

    parsed["paragraphs"][0]["text"] = (
        "Metformin may remain uncertain when metformin uses 20 mg for 12 weeks."
    )
    assert build_scoped_from_parsed(
        parsed, name="discussion", heading="## Discussion",
        topic="metformin", accepted=accepted,
    ) is None


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


def test_results_builder_keeps_paragraphs_inside_same_outcome_section() -> None:
    accepted = [
        _accepted("r-immune", outcome_class="immune"),
        _accepted("r-frailty", outcome_class="frailty"),
    ]
    parsed = {
        "subsections": [
            {
                "outcome_class": "immune",
                "heading": "Immune Outcomes",
                "paragraphs": [
                    {
                        "text": "Immune findings are mixed across the corpus.",
                        "receipt_ids": ["r-immune", "r-frailty"],
                    },
                ],
            },
        ],
    }

    section = build_results_from_parsed(parsed, accepted=accepted)

    assert section is not None
    # "immune" canonicalizes to immune_inflammation (merged singleton classes).
    assert "### Immune and Inflammation Outcomes" in section.body_md
    immune_body = section.body_md.split("### Immune and Inflammation Outcomes", 1)[1].split("###", 1)[0]
    assert "`r-immune`" in immune_body
    assert "`r-frailty`" not in immune_body


def test_results_builder_backfills_missing_outcome_sections() -> None:
    accepted = [
        _accepted("r-cardio", outcome_class="cardiometabolic"),
        _accepted("r-frailty", outcome_class="frailty"),
    ]
    parsed = {
        "subsections": [
            {
                "outcome_class": "cardiometabolic",
                "heading": "Cardiometabolic Outcomes",
                "paragraphs": [
                    {
                        "text": "Cardiometabolic findings are bounded.",
                        "receipt_ids": ["r-cardio"],
                    },
                ],
            },
        ],
    }

    section = build_results_from_parsed(parsed, accepted=accepted)

    assert section is not None
    assert "### Cardiometabolic Outcomes" in section.body_md
    assert "### Frailty Outcomes" in section.body_md
    frailty_body = section.body_md.split("### Frailty Outcomes", 1)[1]
    assert "`r-frailty`" in frailty_body


def test_results_builder_merges_duplicate_llm_outcome_subsections() -> None:
    accepted = [_accepted("r-immune", outcome_class="immune")]
    parsed = {
        "subsections": [
            {
                "outcome_class": "immune",
                "heading": "Immune Outcomes",
                "paragraphs": [
                    {"text": "Immune first paragraph.", "receipt_ids": ["r-immune"]},
                ],
            },
            {
                "outcome_class": "immune",
                "heading": "Immune Outcomes",
                "paragraphs": [
                    {"text": "Immune second paragraph.", "receipt_ids": ["r-immune"]},
                ],
            },
        ],
    }

    section = build_results_from_parsed(parsed, accepted=accepted)

    assert section is not None
    assert section.body_md.count("### Immune and Inflammation Outcomes") == 1
    assert "Immune first paragraph." in section.body_md
    assert "Immune second paragraph." in section.body_md


def test_calendar_year_is_not_treated_as_a_fabricated_numeric() -> None:
    """Years are bibliographic context, not quantitative claims.

    A bare four-digit year can never appear in a receipt's numeric set, so
    rejecting on it discarded every paragraph that dated a study. On a live run
    all 5 cross-domain paragraphs failed on '2025'/'2015', so the writer emitted
    a ~15-word placeholder for every LLM section.
    """
    from agent.paper_writer_builders import _check_anchored_paragraph

    ok, reason = _check_anchored_paragraph(
        "A 2025 randomized trial reported the endpoint.",
        ["r1"], {"r1"}, set(),
    )
    assert ok, f"year must not be a fabricated numeric (got {reason})"


def test_untraceable_statistic_is_still_rejected() -> None:
    """The fabrication guard must survive the year exemption."""
    from agent.paper_writer_builders import _check_anchored_paragraph

    ok, reason = _check_anchored_paragraph(
        "The intervention reduced the endpoint by 42.7%.",
        ["r1"], {"r1"}, set(),
    )
    assert not ok and "novel_numeric" in reason, reason
