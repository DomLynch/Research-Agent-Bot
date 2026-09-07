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

from dataclasses import replace

from agent.paper_writer_builders import (
    _materialize_inline_receipts,
    build_anchored_from_parsed,
    build_results_from_parsed,
    build_scoped_from_parsed,
    citation_only_repair_eligible,
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
    accepted = [_accepted(
        "metformin-multi-001-cfab-c01",
        p_values=("p=0.005",),
        thesis_text="Trial - source excerpts: Direct trial reported reductions at p=0.005.",
    )]
    parsed = {
        "paragraphs": [
            {
                "text": "Direct trial reported reductions at p=0.005 [metformin-multi-001-cfab-c01].",
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


def test_cross_domain_rejects_partial_sentence_records() -> None:
    reasons: list[str] = []
    section = build_anchored_from_parsed(
        {"paragraphs": [
            {"paragraph_index": 1, "text": "Davies improved [r-a].", "receipt_ids": ["r-a"]},
            {"paragraph_index": 1, "text": "Khamis remained null.", "receipt_ids": ["r-b"]},
        ]},
        name="cross_domain_synthesis", heading="## Cross-Domain Synthesis",
        accepted=[_accepted("r-a"), _accepted("r-b")], rejection_reasons=reasons,
    )
    assert section is None
    assert "invalid_sentence_record_contract" in reasons

def test_cross_domain_requires_sentence_record_indices() -> None:
    reasons: list[str] = []
    section = build_anchored_from_parsed(
        {"paragraphs": [{"text": "Davies improved [r-a].", "receipt_ids": ["r-a"]}]},
        name="cross_domain_synthesis", heading="## Cross-Domain Synthesis",
        accepted=[_accepted("r-a")], rejection_reasons=reasons,
    )
    assert section is None
    assert reasons == ["invalid_sentence_record_contract"]


def test_cross_domain_requires_inline_ids_to_match_sentence_metadata() -> None:
    reasons: list[str] = []
    section = build_anchored_from_parsed(
        {"paragraphs": [{
            "paragraph_index": 1,
            "text": "Davies improved [r-a].",
            "receipt_ids": ["r-a", "r-b"],
        }]},
        name="cross_domain_synthesis", heading="## Cross-Domain Synthesis",
        accepted=[_accepted("r-a"), _accepted("r-b")], rejection_reasons=reasons,
    )
    assert section is None
    assert "invalid_sentence_record_contract" in reasons

    reasons.clear()
    section = build_anchored_from_parsed(
        {"paragraphs": [
            {
                "paragraph_index": group,
                "text": "Davies improved [r-a].",
                "receipt_ids": ["r-a"],
            }
            for group in range(1, 5)
            for _ in range(6)
        ]},
        name="cross_domain_synthesis", heading="## Cross-Domain Synthesis",
        accepted=[_accepted("r-a")], rejection_reasons=reasons,
    )
    assert section is None
    assert "invalid_sentence_record_contract" in reasons


def test_cross_domain_normalizes_metadata_and_drops_invalid_records() -> None:
    accepted = [
        _accepted("r-a"),
        _accepted("r-b", outcome_class="frailty"),
    ]
    paragraphs = [
        {
            "paragraph_index": group,
            "text": (
                "Direct evidence supports change [r-a]."
                if row % 2 else
                "Frailty evidence remains uncertain [r-b]."
            ),
            "receipt_ids": ["r-a" if row % 2 else "r-b"],
        }
        for group in range(1, 7)
        for row in range(1, 7)
    ]
    section = build_anchored_from_parsed(
        {"paragraphs": paragraphs},
        name="cross_domain_synthesis", heading="## Cross-Domain Synthesis",
        accepted=accepted,
    )
    assert section is not None

    for text, receipt_ids, expected_reason in (
        ("Mismatched citation claim [r-a].", ["r-b"], "missing_inline_anchor"),
        ("Fabricated citation claim [r-a] [fabricated].", ["r-a"], "invalid_sentence_record_contract"),
        ("", ["r-a"], "empty_paragraph"),
    ):
        paragraphs[0].update(text=text, receipt_ids=receipt_ids)
        reasons: list[str] = []
        repaired = build_anchored_from_parsed(
            {"paragraphs": paragraphs},
            name="cross_domain_synthesis", heading="## Cross-Domain Synthesis",
            accepted=accepted, rejection_reasons=reasons,
        )
        assert repaired is not None
        assert not any(anchor.sentence == text for anchor in repaired.anchors)
        assert expected_reason in reasons

    paragraphs[0].update(
        text="Outlier group claim [r-a].", receipt_ids=["r-a"], paragraph_index=999,
    )
    reasons = []
    repaired = build_anchored_from_parsed(
        {"paragraphs": paragraphs}, name="cross_domain_synthesis",
        heading="## Cross-Domain Synthesis", accepted=accepted,
        rejection_reasons=reasons,
    )
    assert repaired is not None
    assert not any(anchor.sentence == "Outlier group claim [r-a]." for anchor in repaired.anchors)

    paragraphs[0].update(text="", receipt_ids=["r-a"], paragraph_index=1)
    for index in (8, 16, 24):
        paragraphs[index].update(text="", receipt_ids=["r-a"])
    reasons = []
    assert build_anchored_from_parsed(
        {"paragraphs": paragraphs},
        name="cross_domain_synthesis", heading="## Cross-Domain Synthesis",
        accepted=accepted, rejection_reasons=reasons,
    ) is not None
    assert reasons.count("empty_paragraph") == 4
def test_cross_domain_requires_four_to_six_balanced_paragraph_groups() -> None:
    reasons: list[str] = []
    section = build_anchored_from_parsed(
        {"paragraphs": [
            {
                "paragraph_index": 1,
                "text": "Davies improved [r-a].",
                "receipt_ids": ["r-a"],
            }
            for _ in range(24)
        ]},
        name="cross_domain_synthesis", heading="## Cross-Domain Synthesis",
        accepted=[_accepted("r-a")], rejection_reasons=reasons,
    )
    assert section is None
    assert "invalid_sentence_record_contract" in reasons


def test_cross_domain_recovers_valid_sentences_from_bad_grouping() -> None:
    accepted = [_accepted("r-a"), _accepted("r-b", outcome_class="frailty")]
    section = build_anchored_from_parsed(
        {"paragraphs": [
            {
                "paragraph_index": 1,
                "text": "Direct evidence supports change [r-a]." if row % 2
                else "Frailty evidence remains uncertain [r-b].",
                "receipt_ids": ["r-a" if row % 2 else "r-b"],
            }
            for row in range(36)
        ]},
        name="cross_domain_synthesis", heading="## Cross-Domain Synthesis",
        accepted=accepted,
    )
    assert section is not None
    assert len(section.anchors) == 36
    assert section.body_md.count("_Cited:") == 4


def test_cross_domain_recovery_keeps_24_sentence_floor() -> None:
    accepted = [_accepted("r-a"), _accepted("r-b", outcome_class="frailty")]
    section = build_anchored_from_parsed(
        {"paragraphs": [
            {
                "paragraph_index": 1,
                "text": "Direct evidence supports change [r-a]." if row % 2
                else "Frailty evidence remains uncertain [r-b].",
                "receipt_ids": ["r-a" if row % 2 else "r-b"],
            }
            for row in range(20)
        ]},
        name="cross_domain_synthesis", heading="## Cross-Domain Synthesis",
        accepted=accepted,
    )
    assert section is None


def test_cross_domain_retains_four_valid_groups_when_one_group_is_invalid() -> None:
    accepted = [_accepted("r-a"), _accepted("r-b", outcome_class="frailty")]
    paragraphs = [
        {
            "paragraph_index": group,
            "text": (
                "Grounded evidence supports change [r-a]." if row % 2
                else "Frailty evidence remains uncertain [r-b]."
            ),
            "receipt_ids": ["r-a" if row % 2 else "r-b"],
        }
        for group in range(1, 6)
        for row in range(1, 7)
    ]
    for entry in paragraphs[-6:]:
        entry["text"] = "Single-source sentence [r-a]."
        entry["receipt_ids"] = ["r-a"]
    section = build_anchored_from_parsed(
        {"paragraphs": paragraphs}, name="cross_domain_synthesis",
        heading="## Cross-Domain Synthesis", accepted=accepted,
    )
    assert section is not None
    assert len(section.anchors) == 24
    assert "Single-source sentence" not in section.body_md


def test_cross_domain_rejects_indexed_multi_sentence_records() -> None:
    reasons: list[str] = []
    section = build_anchored_from_parsed(
        {"paragraphs": [{
            "paragraph_index": 1,
            "text": "Davies improved [r-a]. Khamis remained null [r-b].",
            "receipt_ids": ["r-a", "r-b"],
        }]},
        name="cross_domain_synthesis", heading="## Cross-Domain Synthesis",
        accepted=[_accepted("r-a"), _accepted("r-b")], rejection_reasons=reasons,
    )
    assert section is None
    assert "invalid_sentence_record_contract" in reasons

    reasons.clear()
    section = build_anchored_from_parsed(
        {"paragraphs": [{
            "paragraph_index": 1,
            "text": "Davies improved [r-a].\u201d Khamis remained null [r-b].",
            "receipt_ids": ["r-a", "r-b"],
        }]},
        name="cross_domain_synthesis", heading="## Cross-Domain Synthesis",
        accepted=[_accepted("r-a"), _accepted("r-b")], rejection_reasons=reasons,
    )
    assert section is None
    assert "invalid_sentence_record_contract" in reasons


def test_multi_sentence_paragraph_can_receive_citation_only_repair() -> None:
    section = build_anchored_from_parsed(
        {"paragraphs": [{
            "text": "Evidence remains limited. Interpretation remains cautious.",
            "receipt_ids": ["r-a"],
        }]},
        name="abstract", heading="## Abstract",
        accepted=[_accepted("r-a")],
    )
    assert section is not None
    assert "Evidence remains limited [r-a]. Interpretation remains cautious [r-a]." in section.body_md

    for ambiguous in ("A. Smith observed change.", "Dr.\nSmith observed change.", "Results varied, e.g., by subgroup.", "Dose was given i.v.\nbefore sampling."):
        assert _materialize_inline_receipts(ambiguous, ["r-a"]) == ambiguous
        assert not citation_only_repair_eligible({"text": ambiguous, "receipt_ids": ["r-a"]})

    rows = [{"text": "Evidence remains bounded [r-a].", "receipt_ids": ["r-a"], "paragraph_index": group}
            for group in range(1, 5) for _ in range(4)]
    rows[-1]["text"] = "The accepted p=0.05 result remains bounded [r-a]."
    grouped = build_anchored_from_parsed(
        {"paragraphs": rows}, name="limitations_full", heading="## Limitations",
        accepted=[_accepted("r-a", p_values=("p=0.05",))],
    )
    assert grouped is not None and grouped.body_md.count("_Cited:") == 4
    assert "p=0.05" not in grouped.body_md and len(grouped.anchors) == 15
    assert build_anchored_from_parsed(
        {"text": "Evidence remains limited. Interpretation remains cautious.", "receipt_ids": ["r-a"], "paragraph_index": 1},
        name="limitations_full", heading="## Limitations", accepted=[_accepted("r-a")],
    ) is None


def test_scoped_repairs_receipt_id_with_one_char_typo() -> None:
    """Same fix in the scoped builder (Background, Discussion, etc.).
    Text must satisfy the section-level topic and hedge contract."""
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


def test_scoped_applies_topic_and_hedge_contract_across_section() -> None:
    parsed = {"paragraphs": [
        {"text": "Metformin evidence is receipt grounded.", "receipt_ids": ["r1"]},
        {"text": "Metformin may remain context dependent.", "receipt_ids": ["r1"]},
    ]}
    section = build_scoped_from_parsed(
        parsed, name="background", heading="## Background",
        topic="metformin", accepted=[_accepted("r1")],
    )
    assert section is not None
    parsed["paragraphs"][1]["text"] = "The evidence remains descriptive."
    assert build_scoped_from_parsed(
        parsed, name="background", heading="## Background",
        topic="metformin", accepted=[_accepted("r1")],
    ) is None


def test_scoped_failures_explain_the_actual_retry_contract() -> None:
    from agent.paper_writer_prompts import cross_domain_retry_prompt

    for text, ids, expected, guidance in (
        ("BNT162b2 evidence remains uncertain.", ["r1"], "topic_alias_under_count:", "TOPIC RETRY REQUIRED"),
        ("BNT162b2 evidence concerns BNT162b2.", ["r1"], "missing_hedge_phrase", "UNCERTAINTY RETRY REQUIRED"),
        ("BNT162b2 may inform BNT162b2 research.", [], "no_accepted_anchor:", "CITATION RETRY REQUIRED"),
    ):
        receipt = _accepted("r1", thesis_text="Test source - source excerpts: " + text)
        reasons: list[str] = []
        section = build_scoped_from_parsed(
            {"paragraphs": [{"text": text, "receipt_ids": ids}]},
            name="conclusion", heading="## Conclusion", topic="bnt162b2_vaccine_effects",
            accepted=[receipt], rejection_reasons=reasons,
        )
        assert section is None and any(reason.startswith(expected) for reason in reasons)
        assert guidance in cross_domain_retry_prompt("base", "conclusion", reasons)

    reasons = []
    assert build_scoped_from_parsed(
        {"paragraphs": []}, name="conclusion", heading="## Conclusion",
        topic="bnt162b2_vaccine_effects", accepted=[], rejection_reasons=reasons,
    ) is None
    assert reasons == ["empty_or_invalid_paragraphs"]


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
    accepted = [_accepted(
        "metformin-multi-001-cfab-c01",
        p_values=("p=0.005",),
        thesis_text="Trial - source excerpts: Glycemic biomarker trajectory declined at p=0.005.",
    )]
    parsed = {
        "paragraphs": [
            {
                "text": "Glycemic biomarker trajectory declined at p=0.005 [metformin-multi-001-cfab-c01].",
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
    accepted = [_accepted(
        "metformin-multi-001-cfab-c01",
        p_values=("p=0.005",),
        thesis_text="Trial - source excerpts: Glycemic biomarker trajectory declined at p=0.005.",
    )]
    from agent.paper_writer_builders import _check_anchored_paragraph
    for invalid in ("Metadata-only claim.", f"Unanchored claim. Anchored [{accepted[0].receipt_id}].", f"Wrong prefix [{accepted[0].receipt_id}0].", f"Anchored [{accepted[0].receipt_id}]. \"Unanchored.\"", f"Anchored [{accepted[0].receipt_id}]. **Unanchored.**", f"Anchored [{accepted[0].receipt_id}]. lowercase unanchored.", f"\"Anchored [{accepted[0].receipt_id}].\" Unanchored.", f"**Anchored [{accepted[0].receipt_id}].** Unanchored.", f"`Anchored [{accepted[0].receipt_id}].` Unanchored.", f"The evidence [{accepted[0].receipt_id}] was grade A. Unsupported.", f"The intervention [{accepted[0].receipt_id}] was vitamin C. Unsupported.", f"The finding [{accepted[0].receipt_id}] was reported by Smith et al. Unsupported.", f"The sponsor [{accepted[0].receipt_id}] was Acme Inc. Unsupported.", f"The finding [{accepted[0].receipt_id}] was reported by Smith et al. BMI increased.", f"The sponsor [{accepted[0].receipt_id}] was Acme Inc. RCT evidence was absent.", f"The source [{accepted[0].receipt_id}] named the Dept. DNA evidence was absent.", f"The setting [{accepted[0].receipt_id}] was U.S. RCT evidence was absent.", f"Participants were enrolled in the U.S. The FDA guidance supported this [{accepted[0].receipt_id}].", f"The drug was administered i.v. The PK profile supported this [{accepted[0].receipt_id}].", f"The finding was reported by Smith et al. [{accepted[0].receipt_id}] Another finding was unsupported."):
        ok, reason = _check_anchored_paragraph(invalid, [accepted[0].receipt_id], {accepted[0].receipt_id}, set())
        assert not ok and "missing_inline_anchor" in reason
    cross_paragraph = f"The setting was U.S.\n\nRCT evidence was absent [{accepted[0].receipt_id}]."
    assert not _check_anchored_paragraph(cross_paragraph, [accepted[0].receipt_id], {accepted[0].receipt_id}, set())[0]
    et_al_paragraph = f"The endpoint improved according to Smith et al.\n\nthis separate paragraph contains [{accepted[0].receipt_id}]."
    assert not _check_anchored_paragraph(et_al_paragraph, [accepted[0].receipt_id], {accepted[0].receipt_id}, set())[0]
    for valid in (f"Doctor Smith reported the result [{accepted[0].receipt_id}].", f"Figure 1 reports the result [{accepted[0].receipt_id}].", f"Equation 2 reports the result [{accepted[0].receipt_id}]."):
        assert _check_anchored_paragraph(valid, [accepted[0].receipt_id], {accepted[0].receipt_id}, {"1", "2"})[0]
    for valid in (f"Outcomes included for example BMI and LDL [{accepted[0].receipt_id}].", f"Figure S1 reports the result [{accepted[0].receipt_id}].", f"Equation A1 defines the result [{accepted[0].receipt_id}]."):
        assert _check_anchored_paragraph(valid, [accepted[0].receipt_id], {accepted[0].receipt_id}, {"1"})[0]
    for valid in (f"The United States cohort reported the result [{accepted[0].receipt_id}].", f"The intravenous route reported the result [{accepted[0].receipt_id}]."):
        assert _check_anchored_paragraph(valid, [accepted[0].receipt_id], {accepted[0].receipt_id}, set())[0]
    for valid in (f"The United States FDA guidance supported the result [{accepted[0].receipt_id}].", f"The United States Food and Drug Administration supported the result [{accepted[0].receipt_id}].", f"The intravenous PK profile supported the result [{accepted[0].receipt_id}].", f"Outcomes included for example α-tocopherol [{accepted[0].receipt_id}]."):
        assert _check_anchored_paragraph(valid, [accepted[0].receipt_id], {accepted[0].receipt_id}, set())[0]
    parsed = {
        "paragraphs": [
            {
                "text": "Glycemic biomarker trajectory declined at p=0.005 [metformin-multi-001-cfab-c01].",
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
        _accepted(
            "metformin-multi-001-cfab-c01",
            p_values=("p=0.005",),
            thesis_text="Trial - source excerpts: Glycemic biomarker trajectory declined at p=0.005.",
        ),
        _accepted(
            "metformin-multi-001-cfab-c04",
            thesis_text="Trial - source excerpts: Glycemic biomarker trajectory declined at p=0.005.",
        ),
    ]
    parsed = {
        "paragraphs": [
            {
                "text": "Glycemic biomarker trajectory declined at p=0.005 [metformin-multi-001-cfab-c01] [metformin-multi-001-cfab-c04].",
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
        replace(
            _accepted("r-animal", outcome_class="cardiometabolic"),
            directness="mechanistic", population_summary="mice",
        ),
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
    assert "### Animal/Preclinical Context Outcomes" in section.body_md
    assert "### Frailty Outcomes" in section.body_md
    assert "`r-animal`" not in section.body_md.split("### Cardiometabolic Outcomes", 1)[1].split("###", 1)[0]
    frailty_body = section.body_md.split("### Frailty Outcomes", 1)[1]
    assert "`r-frailty`" in frailty_body


def test_results_builder_merges_duplicate_llm_outcome_subsections() -> None:
    accepted = [_accepted(
        "r-immune",
        outcome_class="immune",
        thesis_text="Study - source excerpts: Immune first paragraph. Immune second paragraph.",
    )]
    parsed = {
        "subsections": [
            {
                "outcome_class": "immune",
                "heading": "Immune Outcomes",
                "paragraphs": [
                    {"text": "Immune first paragraph [r-immune].", "receipt_ids": ["r-immune"]},
                ],
            },
            {
                "outcome_class": "immune",
                "heading": "Immune Outcomes",
                "paragraphs": [
                    {"text": "Immune second paragraph [r-immune].", "receipt_ids": ["r-immune"]},
                ],
            },
        ],
    }

    section = build_results_from_parsed(parsed, accepted=accepted)

    assert section is not None
    assert section.body_md.count("### Immune and Inflammation Outcomes") == 1
    assert "Immune first paragraph [r-immune]." in section.body_md
    assert "Immune second paragraph [r-immune]." in section.body_md


def _grounded_receipt(thesis: str | None = None) -> ReceiptSummary:
    return replace(
        _accepted(
            "r-cardio", outcome_class="cardiometabolic",
            thesis_text=thesis or (
                "Trial - source excerpts: Metformin treatment reduced fasting glucose "
                "among adults with type 2 diabetes during follow-up."
            ),
        ),
        source_title="Metformin fasting glucose trial",
    )


def _results_payload(text: str, receipt_ids: list[str] | None = None) -> dict:
    return {"subsections": [{"outcome_class": "cardiometabolic", "paragraphs": [
        {"text": text, "receipt_ids": receipt_ids or ["r-cardio"]},
    ]}]}


def test_writer_builders_enforce_mapped_source_grounding() -> None:
    for text in (
        "The intervention showed a strong protective effect against pancreatic cancer and supports "
        "broad use for cancer chemoprevention [r-cardio].",
        "Among adults with type 2 diabetes, metformin treatment increased fasting glucose during "
        "follow-up [r-cardio].",
        "Metformin prevented pancreatic cancer [r-cardio].",
        "Metformin treatment reduced fasting glucose during follow-up and prevented pancreatic "
        "cancer [r-cardio].",
        "Metformin treatment reduced fasting glucose during follow-up and lowered cancer mortality "
        "[r-cardio].",
        "Metformin treatment reduced fasting glucose during follow-up and raised cancer mortality "
        "[r-cardio].",
        "Metformin treatment reduced fasting glucose during follow-up and cut cancer mortality "
        "[r-cardio].",
    ):
        reasons: list[str] = []
        assert build_results_from_parsed(
            _results_payload(text), accepted=[_grounded_receipt()], rejection_reasons=reasons,
        ) is None
        assert reasons == ["source_grounding:r-cardio"]

    grounded = build_results_from_parsed(_results_payload(
        "Among adults with type 2 diabetes, metformin treatment reduced fasting glucose during "
        "follow-up [r-cardio].",
    ), accepted=[_grounded_receipt()])
    assert grounded is not None and "reduced fasting glucose" in grounded.body_md

    reasons = []
    assert build_results_from_parsed(_results_payload(
        "Metformin treatment reduced fasting glucose among adults with diabetes during clinical "
        "follow-up [r-cardio].",
    ), accepted=[_grounded_receipt("Trial title only")], rejection_reasons=reasons) is None
    assert reasons == ["source_grounding:r-cardio"]


def test_source_grounding_accepts_bounded_quantitative_paraphrase_without_title_splicing() -> None:
    kelly = replace(
        _grounded_receipt(
            "A Randomized Controlled Trial of Liraglutide for Adolescents with Obesity - source excerpts: "
            "More participants in the liraglutide group than placebo had gastrointestinal adverse events "
            "(81 of 125 [64.8%] vs 46 of 126 [36.5%])."
        ),
        receipt_id="r-kelly", source_title="A Randomized Controlled Trial of Liraglutide for Adolescents with Obesity",
        population_summary="adults", directness="direct", outcome_class="safety",
    )
    assert build_results_from_parsed(_results_payload(
        "In a randomized trial of adolescents with obesity, gastrointestinal adverse events occurred in "
        "64.8% (81 of 125) of liraglutide-treated participants compared with 36.5% (46 of 126) in the "
        "placebo group [r-kelly].", ["r-kelly"],
    ), accepted=[kelly]) is not None

    spliced = replace(_grounded_receipt(
        "Trial - source excerpts: Metformin reduced fasting glucose by 50% among adults."
    ), source_title="Metformin pancreatic cancer trial")
    assert build_results_from_parsed(_results_payload(
        "Metformin reduced pancreatic cancer by 50% among adults [r-cardio]."
    ), accepted=[spliced]) is None
    assert build_results_from_parsed(_results_payload(
        "In pancreatic cancer, metformin reduced pancreatic cancer by 50% among adults [r-cardio]."
    ), accepted=[spliced]) is None


def test_source_grounding_checks_leading_clause_citation_identity_and_scope() -> None:
    glucose = _grounded_receipt()
    cancer = replace(
        _grounded_receipt("Trial - source excerpts: Metformin lowered cancer mortality during follow-up."),
        receipt_id="r-cancer", source_title="Metformin cancer mortality trial",
    )
    pediatric = replace(
        _grounded_receipt("Trial - source excerpts: LDL cholesterol declined among children with type 1 diabetes."),
        receipt_id="r-pediatric", source_title="Pediatric LDL trial",
    )
    spliced = _grounded_receipt(
        "Trial - source excerpts: Metformin reduced fasting glucose among adults. "
        "LDL cholesterol declined among children with type 1 diabetes."
    )
    mouse = _grounded_receipt(
        "Trial - source excerpts: Metformin reduced fasting glucose in mice."
    )
    title_endpoint = replace(
        glucose, source_title="Metformin pancreatic cancer trial",
    )
    mixed_species = _grounded_receipt(
        "Trial - source excerpts: Metformin reduced fasting glucose in a mouse model of human diabetes."
    )
    mixed_direction = _grounded_receipt(
        "Trial - source excerpts: Pancreatic cancer increased among adults while fasting glucose decreased among adults."
    )
    for text, accepted in (
        ("Metformin raised cancer mortality and reduced fasting glucose [r-cardio].", [glucose]),
        ("Metformin treatment reduced fasting insulin among children with diabetes [r-cardio].", [glucose]),
        ("Metformin reduced fasting glucose in mice [r-cardio].", [glucose]),
        ("Metformin reduced fasting glucose in boys [r-cardio].", [glucose]),
        ("Metformin reduced fasting glucose in men [r-cardio].", [glucose]),
        ("Metformin reduced fasting glucose among adults [r-cardio].", [mouse]),
        ("Mortality and fasting glucose decreased among adults [r-cardio].", [glucose]),
        ("Pancreatic cancer risk remains uncertain [r-cardio].", [glucose]),
        ("Metformin reduced pancreatic cancer [r-cardio].", [title_endpoint]),
        ("Metformin reduced fasting glucose in a human model of diabetes [r-cardio].", [mixed_species]),
        ("Pancreatic cancer and fasting glucose decreased among adults [r-cardio].", [mixed_direction]),
        ("Metformin reduced fasting glucose among children with type 1 diabetes [r-cardio] [r-pediatric].", [glucose, pediatric]),
        ("Metformin reduced fasting glucose among children with type 1 diabetes [r-cardio].", [spliced]),
        ("Metformin reduced fasting glucose [r-cancer] and lowered cancer mortality [r-cardio].", [glucose, cancer]),
    ):
        reasons: list[str] = []
        ids = [receipt.receipt_id for receipt in accepted]
        assert build_results_from_parsed(
            _results_payload(text, ids), accepted=accepted, rejection_reasons=reasons,
        ) is None
        assert reasons and reasons[0].startswith("source_grounding:")
    for conjunction in ("and", "although", "but", "while", "whereas", "yet", ":"):
        opposed = _grounded_receipt(
            "Trial - source excerpts: Fasting glucose decreased among adults "
            f"{conjunction} cancer mortality increased among adults."
        )
        assert build_results_from_parsed(_results_payload(
            "Cancer mortality decreased among adults [r-cardio].",
        ), accepted=[opposed]) is None
    conclusion = build_scoped_from_parsed(
        {"paragraphs": [{
            "text": (
                "Evidence suggests metformin treatment reduced fasting glucose among adults with "
                "type 2 diabetes, while clinical significance for metformin remains uncertain."
            ),
            "receipt_ids": ["r-cardio"],
        }, {
            "text": "Metformin prevented pancreatic cancer, although metformin remains uncertain.",
            "receipt_ids": ["r-cardio"],
        }]},
        name="conclusion", heading="## Conclusion", topic="metformin",
        accepted=[_grounded_receipt()],
    )
    assert conclusion is not None and "pancreatic cancer" not in conclusion.body_md
    assert build_results_from_parsed(_results_payload(
        "Metformin may have reduced fasting glucose [r-cardio].",
    ), accepted=[glucose]) is not None
    assert build_results_from_parsed(_results_payload(
        "Metformin appeared to have reduced fasting glucose [r-cardio].",
    ), accepted=[glucose]) is not None
    assert build_results_from_parsed(_results_payload(
        "Metformin seems to have reduced fasting glucose [r-cardio].",
    ), accepted=[glucose]) is not None
    adult_patients = _grounded_receipt(
        "Trial - source excerpts: Metformin reduced fasting glucose in adult patients."
    )
    assert build_results_from_parsed(_results_payload(
        "Metformin reduced fasting glucose among adults [r-cardio].",
    ), accepted=[adult_patients]) is not None
    coordinated = _grounded_receipt(
        "Trial - source excerpts: Morbidity and mortality decreased among adults."
    )
    assert build_results_from_parsed(_results_payload(
        "Mortality and morbidity decreased among adults [r-cardio].",
    ), accepted=[coordinated]) is not None
    three_endpoints = _grounded_receipt(
        "Trial - source excerpts: Morbidity, mortality, and fasting glucose decreased among adults."
    )
    assert build_results_from_parsed(_results_payload(
        "Fasting glucose, morbidity, and mortality decreased among adults [r-cardio].",
    ), accepted=[three_endpoints]) is not None
    opposed_list = _grounded_receipt(
        "Trial - source excerpts: Morbidity increased, mortality and fasting glucose decreased among adults."
    )
    assert build_results_from_parsed(_results_payload(
        "Morbidity, mortality, and fasting glucose decreased among adults [r-cardio].",
    ), accepted=[opposed_list]) is None
    reasons = []
    abstract = build_anchored_from_parsed(
        {"paragraphs": [
            {
                "text": (
                    "Among adults with type 2 diabetes, metformin treatment reduced fasting "
                    "glucose during follow-up [r-cardio]."
                ),
                "receipt_ids": ["r-cardio"],
            },
            {
                "text": (
                    "The intervention showed a strong protective effect against pancreatic cancer "
                    "and supports broad use for chemoprevention [r-cardio]."
                ),
                "receipt_ids": ["r-cardio"],
            },
        ]},
        name="abstract", heading="## Abstract", accepted=[_grounded_receipt()],
        rejection_reasons=reasons,
    )
    assert abstract is not None
    assert "reduced fasting glucose" in abstract.body_md
    assert "pancreatic cancer" not in abstract.body_md
    assert reasons == ["source_grounding:r-cardio"]

def test_calendar_year_is_not_treated_as_a_fabricated_numeric() -> None:
    """Years are bibliographic context, not quantitative claims.

    A bare four-digit year can never appear in a receipt's numeric set, so
    rejecting on it discarded every paragraph that dated a study. On a live run
    all 5 cross-domain paragraphs failed on '2025'/'2015', so the writer emitted
    a ~15-word placeholder for every LLM section.
    """
    from agent.paper_writer_builders import _check_anchored_paragraph

    ok, reason = _check_anchored_paragraph(
        "Smith et al. (2025) reported the endpoint [r1].",
        ["r1"], {"r1"}, set(),
    )
    assert ok, f"year must not be a fabricated numeric (got {reason})"


def test_calendar_year_exemption_does_not_hide_sample_sizes() -> None:
    """Four-digit counts remain quantitative even when they resemble years."""
    from agent.paper_writer_builders import (
        _check_anchored_paragraph,
        _check_scoped_paragraph,
    )

    anchored_ok, anchored_reason = _check_anchored_paragraph(
        "The analysis used data from 2025 participants [r1].",
        ["r1"], {"r1"}, set(),
    )
    assert not anchored_ok and "novel_numeric" in anchored_reason

    scoped_ok, scoped_reason = _check_scoped_paragraph(
        "Metformin may remain uncertain because metformin included 2015 patients.",
        ["r1"], {"r1"}, set(),
    )
    assert not scoped_ok and "novel_numeric" in scoped_reason


def test_untraceable_statistic_is_still_rejected() -> None:
    """The fabrication guard must survive the year exemption."""
    from agent.paper_writer_builders import _check_anchored_paragraph

    ok, reason = _check_anchored_paragraph(
        "The intervention reduced the endpoint by 42.7% [r1].",
        ["r1"], {"r1"}, set(),
    )
    assert not ok and "novel_numeric" in reason, reason


def test_anchored_repairs_uniquely_supported_numeric_receipt() -> None:
    wrong = _accepted("wrong", thesis_text="Konwar reported gastrointestinal adverse events.")
    right = _accepted(
        "right",
        thesis_text=(
            "Kelly trial - source excerpts: Kelly reported gastrointestinal adverse events in 81 of 125 participants "
            "(64.8%) versus 46 of 126 controls (36.5%; 95% CI 30-40)."
        ),
    )
    parsed = {"paragraphs": [{
        "text": "Kelly reported gastrointestinal adverse events in 36.5% of controls [95% CI 30-40] [wrong].",
        "receipt_ids": ["wrong"],
    }]}

    section = build_anchored_from_parsed(
        parsed, name="abstract", heading="## Abstract", accepted=[wrong, right],
    )

    assert section is not None
    assert section.anchors[0].receipt_ids == ("right",)
    assert "[95% CI 30-40]" in section.body_md
    repaired = build_anchored_from_parsed(
        {"paragraphs": [{
            "text": "Kelly reported gastrointestinal adverse events in 36.5% of controls [wrong] [fabricated].",
            "receipt_ids": ["wrong", "fabricated"],
        }]},
        name="abstract", heading="## Abstract", accepted=[wrong, right],
    )
    assert repaired is not None and "fabricated" not in repaired.body_md
    assert repaired.body_md.count("[right]") == 1
    duplicate = replace(right, receipt_id="duplicate")
    assert build_anchored_from_parsed(
        parsed, name="abstract", heading="## Abstract", accepted=[wrong, right, duplicate],
    ) is None
    assert build_anchored_from_parsed(
        {"paragraphs": [{"text": "Figure 1 reports the result [wrong].", "receipt_ids": ["wrong"]}]},
        name="abstract", heading="## Abstract", accepted=[wrong, replace(right, thesis_text="Figure 1 reports the result.")],
    ) is None


def test_writer_word_count_matches_the_gate() -> None:
    """The retry loop must optimise the number the gate enforces.

    section_word_count used to count split() over text still carrying the
    per-paragraph "_Cited: `id`_" markers the builder appends, while the gate
    counts \\b\\w+\\b over full_paper.md after render strips them. On a live run
    the writer saw 964 words and stopped retrying; the gate saw 680 against an
    850 floor and failed the manuscript.
    """
    import re as _re

    from agent.paper_writer import _strip_rendered_citation_markers as _strip
    from agent.paper_writer_helpers import section_word_count
    from agent.synthesis_schemas import SynthesisSection

    body = "## Cross-Domain Synthesis\n\n"
    for _ in range(5):
        body += "Liraglutide reduced the endpoint in the pooled analysis. " * 4 + "\n\n"
        body += "  _Cited: `cfab-c01`, `cfab-c02`, `cfab-c03`_\n\n"

    writer = section_word_count(
        SynthesisSection(name="cross_domain_synthesis", body_md=body, anchors=()),
    )
    match = _re.search(
        r"^##\s+Cross-Domain Synthesis\b.*?\n(.*?)\Z", _strip(body), _re.M | _re.S,
    )
    assert match is not None
    gate = len(_re.findall(r"\b\w+\b", match.group(1)))
    assert writer == gate, f"writer {writer} != gate {gate}"


def test_bare_single_paragraph_is_accepted() -> None:
    """The model sometimes returns ONE paragraph unwrapped.

    Observed live: keys=["receipt_ids", "tension_kind", "text"]. Reading only
    "paragraphs" yielded zero entries, the builder returned None, and the
    section fell back to a ~15-word placeholder that cannot meet any word floor.
    """
    from agent.paper_writer_builders import _paragraph_list

    bare = {"text": "Liraglutide reduced the endpoint.", "receipt_ids": ["r1"],
            "tension_kind": "none"}
    assert _paragraph_list(bare) == [bare]

    wrapped = {"paragraphs": [{"text": "x", "receipt_ids": ["r1"]}]}
    assert _paragraph_list(wrapped) == wrapped["paragraphs"]

    assert _paragraph_list({"unrelated": 1}) == []


def test_scoped_builder_accepts_bare_single_paragraph() -> None:
    """The scoped builder must consume the shared bare-paragraph envelope."""
    parsed = {
        "text": (
            "Metformin may affect metabolic pathways, although metformin "
            "remains uncertain in this evidence base."
        ),
        "receipt_ids": ["r1"],
    }

    section = build_scoped_from_parsed(
        parsed,
        name="discussion",
        heading="## Discussion",
        topic="metformin",
        accepted=[_accepted("r1")],
    )

    assert section is not None
    assert "Metformin may affect metabolic pathways" in section.body_md


def test_enrolment_numerics_from_population_summary_are_traceable() -> None:
    """A sample size stated in the source must not read as fabricated.

    population_summary is source-derived, but was excluded from the accepted
    numeric set, so a paragraph citing the enrolment count was rejected with
    novel_numeric even though the value traced to a receipt.
    """
    from agent.paper_writer_builders import _accepted_numeric_tokens, _check_anchored_paragraph
    from agent.synthesis_schemas import ReceiptSummary

    r = ReceiptSummary(
        receipt_id="r1", receipt_path="/tmp/r1", topic="t", thesis_text="No numbers here.",
        spar_verdict="accept_clean", n_claims=1, n_failed_traces=0, canonical_trial_id=None,
        evidence_tier="A1", directness="direct", outcome_class="cardiometabolic",
        effect_direction="null", p_values=(), population_summary="adults, n=125",
    )
    assert "n=125" in _accepted_numeric_tokens([r])
    ok, reason = _check_anchored_paragraph(
        "The trial enrolled n=125 participants [r1].", ["r1"], {"r1"}, _accepted_numeric_tokens([r]),
    )
    assert ok, reason
