"""Fix #6: deterministic 3-table renderer (included studies, endpoint
evidence, evidence limitations). Discriminating tests isolate each
table's structure + edge cases."""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import table_renderer as tr  # noqa: E402


@dataclass
class _FakeReceipt:
    receipt_id: str
    evidence_tier: str = "A1"
    directness: str = "direct"
    outcome_class: str = "longevity"
    effect_direction: str = "positive"
    population_summary: str | None = "older adults, n=120"
    canonical_trial_id: str | None = "NCT01234567"


def test_table_1_renders_one_row_per_receipt() -> None:
    receipts = [
        _FakeReceipt(receipt_id="Walton 2019", outcome_class="muscle_function",
                     effect_direction="negative"),
        _FakeReceipt(receipt_id="Witham 2025", outcome_class="frailty",
                     effect_direction="null"),
    ]
    md = tr.render_table_1_included_studies(receipts)
    assert "Walton 2019" in md and "Witham 2025" in md
    assert "## Table 1" in md
    assert "negative" in md and "null" in md


def test_table_1_extracts_n_from_population_summary() -> None:
    """n=120 in population_summary → `n=120` in N column.
    Fix #21 follow-up: render with `n=` prefix so Q9 numeric-density
    check (regex `\\b[nN]\\s*=\\s*\\d+`) counts it. Bare `120` would
    leave per-study sample sizes uncounted."""
    receipts = [_FakeReceipt(
        receipt_id="X 2020",
        population_summary="older adults, n=120",
    )]
    md = tr.render_table_1_included_studies(receipts)
    assert "n=120" in md


def test_table_1_n_column_omits_prefix_for_dash() -> None:
    """When N is unknown (`—`), do NOT render `n=—` — that's both
    ugly and would fool Q9 with a non-digit. Stays as `—`."""
    receipts = [_FakeReceipt(
        receipt_id="Y 2021",
        population_summary=None,  # → ('—', '—')
    )]
    md = tr.render_table_1_included_studies(receipts)
    assert "n=—" not in md
    # Bare dash still appears (in N column)
    assert "—" in md


def test_table_2_one_row_per_study_when_no_p_values() -> None:
    """Fix #21 reshape: Table 2 is now per (study × p-value). When a
    study has no p-values it still gets ONE row with `—` so the
    reader sees the gap. Previous Fix #6 layout aggregated by
    outcome_class — see test_table_2_one_row_per_study_p_value below
    for the dense per-(study × p-value) row count."""
    receipts = [
        _FakeReceipt(receipt_id="A 2020", outcome_class="longevity"),
        _FakeReceipt(receipt_id="B 2021", outcome_class="longevity"),
        _FakeReceipt(receipt_id="C 2022", outcome_class="frailty"),
    ]
    md = tr.render_table_2_endpoint_evidence(receipts)
    # Three studies, no p_values defined → 3 rows with '—' p/CI
    for rid in ("A 2020", "B 2021", "C 2022"):
        assert rid in md
    assert "## Table 2" in md
    # 2 study rows for longevity, 1 for frailty (each row contains
    # the endpoint name twice — once in Endpoint col, once in
    # Interpretation col 'improves longevity').
    longevity_rows = [
        ln for ln in md.split("\n") if "longevity" in ln and "|" in ln
    ]
    frailty_rows = [
        ln for ln in md.split("\n") if "frailty" in ln and "|" in ln
    ]
    assert len(longevity_rows) == 2
    assert len(frailty_rows) == 1


def test_table_2_one_row_per_study_p_value() -> None:
    """Fix #21 dense layout: a study with K p-values contributes K
    rows. Two studies with 2 + 1 p-values → 3 data rows total."""
    @dataclass
    class _R:
        receipt_id: str
        evidence_tier: str = "A1"
        directness: str = "direct"
        outcome_class: str = "longevity"
        effect_direction: str = "positive"
        p_values: tuple[str, ...] = ()
        population_summary: str | None = None
        canonical_trial_id: str | None = None
        n_claims: int = 0
    receipts = [
        _R(receipt_id="A 2020", p_values=("p < 0.001", "p = 0.04")),
        _R(receipt_id="B 2021", p_values=("p = 0.02",)),
    ]
    md = tr.render_table_2_endpoint_evidence(receipts)
    # 2 + 1 = 3 study-rows. Each p-value appears verbatim in own row.
    assert "p < 0.001" in md
    assert "p = 0.04" in md
    assert "p = 0.02" in md
    # Study A appears in 2 rows; B in 1
    a_rows = [ln for ln in md.split("\n") if "A 2020" in ln and "|" in ln]
    b_rows = [ln for ln in md.split("\n") if "B 2021" in ln and "|" in ln]
    assert len(a_rows) == 2
    assert len(b_rows) == 1


def test_table_2_includes_interpretation_column() -> None:
    """Each row carries a templated plain-English interpretation
    derived from (direction × outcome_class) so a reader can scan
    the column without needing the schema docs."""
    receipts = [
        _FakeReceipt(
            receipt_id="A 2020", outcome_class="muscle_function",
            effect_direction="negative",
        ),
    ]
    md = tr.render_table_2_endpoint_evidence(receipts)
    assert "worsens muscle_function" in md


def test_table_3_assigns_per_domain_grades_by_tier() -> None:
    """Fix #14: per-domain RoB. A1 → mostly low; B2 → high confounding
    + n/a blinding; C1 → low allocation, n/a blinding/confounding."""
    receipts = [
        _FakeReceipt(receipt_id="A 2020", evidence_tier="A1"),
        _FakeReceipt(receipt_id="B 2021", evidence_tier="B2"),
        _FakeReceipt(receipt_id="C 2022", evidence_tier="C1"),
    ]
    md = tr.render_table_3_evidence_limitations(receipts)
    # A1 RCT: low allocation + low blinding
    a_line = [ln for ln in md.split("\n") if "A 2020" in ln][0]
    assert "low" in a_line
    # B2 cohort: n/a blinding (not meaningful); high confounding
    b_line = [ln for ln in md.split("\n") if "B 2021" in ln][0]
    assert "n/a" in b_line
    assert "high" in b_line
    # C1 preclinical: low allocation, n/a confounding control
    c_line = [ln for ln in md.split("\n") if "C 2022" in ln][0]
    assert "n/a" in c_line


def test_table_3_includes_direction_specific_note() -> None:
    """Null/mixed direction triggers a direction-specific note in
    the 'effect direction notes' column."""
    receipts = [
        _FakeReceipt(receipt_id="X 2020", effect_direction="null"),
        _FakeReceipt(receipt_id="Y 2021", effect_direction="mixed"),
        _FakeReceipt(receipt_id="Z 2022", effect_direction="positive"),
    ]
    md = tr.render_table_3_evidence_limitations(receipts)
    assert "did not reach significance" in md
    assert "internal contradiction" in md


def test_render_all_tables_returns_empty_on_empty_receipts() -> None:
    """No receipts → no tables (orchestrator must skip insertion)."""
    assert tr.render_all_tables([]) == ""


def test_render_all_tables_concatenates_four_tables() -> None:
    """Fix #21: render_all_tables emits Tables 1-4 (Tables 1-3 follow
    the asymmetric-fix reviewer spec; Table 4 is the supplemental
    Cochrane RoB-2 / ROBINS-I roll-up retained from Fix #14)."""
    receipts = [_FakeReceipt(receipt_id="X 2020")]
    md = tr.render_all_tables(receipts)
    for tbl in ("## Table 1", "## Table 2", "## Table 3", "## Table 4"):
        assert tbl in md


def test_aggregate_net_direction_handles_mixed_correctly() -> None:
    """Any single 'mixed' → roll-up is 'mixed'."""
    receipts = [
        _FakeReceipt(receipt_id="A 2020", effect_direction="positive"),
        _FakeReceipt(receipt_id="B 2021", effect_direction="mixed"),
    ]
    assert tr._aggregate_net_direction(receipts) == "mixed"


def test_aggregate_net_direction_all_null() -> None:
    """All 'null' → roll-up is 'null' (not 'mixed')."""
    receipts = [
        _FakeReceipt(receipt_id="A 2020", effect_direction="null"),
        _FakeReceipt(receipt_id="B 2021", effect_direction="null"),
    ]
    assert tr._aggregate_net_direction(receipts) == "null"


def test_aggregate_net_direction_pos_neg_split_is_mixed() -> None:
    """Positive vs negative → mixed (cross-paper conflict)."""
    receipts = [
        _FakeReceipt(receipt_id="A 2020", effect_direction="positive"),
        _FakeReceipt(receipt_id="B 2021", effect_direction="negative"),
    ]
    assert tr._aggregate_net_direction(receipts) == "mixed"


def test_table_3_handles_unknown_tier() -> None:
    """An unknown-tier receipt gets the 'unknown' rationale in Table 3,
    not a crash or empty cell."""
    receipts = [_FakeReceipt(
        receipt_id="X 2020", evidence_tier="unknown",
    )]
    md = tr.render_table_3_evidence_limitations(receipts)
    assert "unknown" in md.lower()


def test_table_1_handles_missing_population_gracefully() -> None:
    """No population_summary → '—' in N column and pop column."""
    receipts = [_FakeReceipt(
        receipt_id="X 2020", population_summary=None,
    )]
    md = tr.render_table_1_included_studies(receipts)
    # Should not crash; should render the row
    assert "X 2020" in md


# ----- Fix #12: evidence-table completion (p-value + n claims columns) -


def test_table_1_includes_representative_p_value_column() -> None:
    """Fix #12: surface deterministic p-values from receipts into Table
    1 → boosts Q9 numeric density without prose bloat."""
    @dataclass
    class _R:
        receipt_id: str = "Walton 2019"
        evidence_tier: str = "A1"
        directness: str = "direct"
        outcome_class: str = "muscle_function"
        effect_direction: str = "negative"
        population_summary: str | None = "older adults, n=120"
        canonical_trial_id: str | None = "NCT01234567"
        p_values: tuple[str, ...] = ("p < 0.001", "p = 0.04")
        n_claims: int = 17

    receipts = [_R()]
    md = tr.render_table_1_included_studies(receipts)
    assert "Representative p-value" in md  # column header
    assert "p < 0.001" in md  # first p-value selected
    assert "n claims" in md  # column header
    assert "17" in md  # n_claims rendered


def test_table_1_falls_back_to_dash_when_no_p_value() -> None:
    """Receipt without p_values → '—' in p-value column (no fabrication)."""
    @dataclass
    class _R:
        receipt_id: str = "Y 2021"
        evidence_tier: str = "B1"
        directness: str = "review"
        outcome_class: str = "longevity"
        effect_direction: str = "unclear"
        population_summary: str | None = None
        canonical_trial_id: str | None = None
        p_values: tuple[str, ...] = ()  # empty
        n_claims: int = 0

    md = tr.render_table_1_included_studies([_R()])
    # Row exists; p-value cell is dash
    assert "Y 2021" in md
    # Count the dashes in the row to confirm presence
    walton_lines = [
        line for line in md.split("\n")
        if "Y 2021" in line and "|" in line
    ]
    assert walton_lines
    # At least 2 dashes (p-value + trial_id at minimum)
    assert walton_lines[0].count("—") >= 2


def test_representative_p_value_picks_smallest_not_first() -> None:
    """Reviewer P2: pre-fix returned the FIRST non-empty p-value
    (iteration-order dependent → non-deterministic). Now picks the
    SMALLEST (most-significant) one, which is what a clinician would
    cite as 'representative.'"""
    @dataclass
    class _R:
        p_values: tuple[str, ...] = ("p = 0.04", "p < 0.001", "p = 0.02")

    # Smallest is 0.001 → "p < 0.001" wins, NOT first ("p = 0.04")
    assert tr._representative_p_value(_R()) == "p < 0.001"


def test_representative_p_value_falls_back_to_first_when_unparseable() -> None:
    @dataclass
    class _R:
        p_values: tuple[str, ...] = ("not a p", "still not", "p = 0.02")

    # First parseable is "p = 0.02" → wins (only parseable one)
    assert tr._representative_p_value(_R()) == "p = 0.02"


def test_representative_p_value_helper_returns_dash_when_empty() -> None:
    @dataclass
    class _R:
        p_values: tuple[str, ...] = ()

    assert tr._representative_p_value(_R()) == "—"


def test_n_claims_helper_renders_int() -> None:
    @dataclass
    class _R:
        n_claims: int = 42

    assert tr._n_claims(_R()) == "42"


def test_n_claims_helper_returns_dash_for_zero_or_missing() -> None:
    @dataclass
    class _R:
        n_claims: int = 0

    assert tr._n_claims(_R()) == "—"


# ----- Reviewer-fix v2 discriminating tests (post-2x review on Fix #6) -


def test_n_extraction_handles_range() -> None:
    """`n=120-150` → '120-150' in N column (not just '120')."""
    n, pop = tr._split_population_n("older adults, n=120-150")
    assert n == "120-150"
    assert pop == "older adults"


def test_n_extraction_handles_reversed_order() -> None:
    """`n=120, older adults` (n= first) → ('120', 'older adults').
    Pre-fix this leaked 'n=120' into the population column."""
    n, pop = tr._split_population_n("n=120, older adults")
    assert n == "120"
    assert pop == "older adults"
    assert "n=" not in pop


def test_n_extraction_sums_treatment_plus_placebo() -> None:
    """`n=120 (treatment), n=60 (placebo)` → 180 (sum of arms)."""
    n, pop = tr._split_population_n(
        "older adults, n=120 (treatment), n=60 (placebo)"
    )
    assert n == "180"
    assert pop == "older adults"


def test_n_extraction_returns_dash_when_no_n() -> None:
    """Population string without `n=` → '—' in N column."""
    n, pop = tr._split_population_n("older adults")
    assert n == "—"
    assert pop == "older adults"


def test_n_extraction_handles_empty_or_dash() -> None:
    assert tr._split_population_n("") == ("—", "—")
    assert tr._split_population_n("—") == ("—", "—")
    assert tr._split_population_n(None) == ("—", "—")  # type: ignore[arg-type]


def test_row_escapes_pipe_newline_backtick() -> None:
    """Reviewer-fix P1: pipes/newlines/backticks in cell content
    must NOT break markdown table parsing."""
    out = tr._row("a | b", "line1\nline2", "code `block`")
    assert "\n" not in out  # newline collapsed
    assert "\\|" in out     # pipe escaped
    assert "\\`" in out     # backtick escaped
    # Output is a single line with proper cell separators
    assert out.count("|") >= 4  # 4 separators for 3 cells


def test_aggregator_returns_uniform_value_for_all_same_direction() -> None:
    """Reviewer-fix P1 #4: all-mixed → 'mixed', all-null → 'null',
    all-positive → 'positive'. Uniform handling, not special-cased."""
    receipts_mixed = [_FakeReceipt(receipt_id=f"X {i}",
                                    effect_direction="mixed")
                      for i in range(3)]
    assert tr._aggregate_net_direction(receipts_mixed) == "mixed"
    receipts_pos = [_FakeReceipt(receipt_id=f"Y {i}",
                                  effect_direction="positive")
                    for i in range(3)]
    assert tr._aggregate_net_direction(receipts_pos) == "positive"


def test_table_2_columns_match_user_spec() -> None:
    """Fix #21: Table 2 column headers match the asymmetric-fix
    reviewer spec — Endpoint | Study | p/CI | Direction | Directness
    | Tier | Interpretation."""
    receipts = [_FakeReceipt(receipt_id="X 2020")]
    md = tr.render_table_2_endpoint_evidence(receipts)
    for col in (
        "Endpoint", "Study", "p/CI", "Direction",
        "Directness", "Tier", "Interpretation",
    ):
        assert col in md, f"missing column: {col}"


def test_table_3_includes_per_domain_caveat() -> None:
    """Fix #14: caveat above Table 3 acknowledges per-domain grades
    are tier-derived, NOT extracted from source PDFs."""
    receipts = [_FakeReceipt(receipt_id="X 2020", evidence_tier="A1")]
    md = tr.render_table_3_evidence_limitations(receipts)
    assert "Cochrane" in md or "rob-2" in md.lower()
    assert "ROBINS-I" in md  # observational equivalent named


def test_table_3_has_seven_rob_domain_columns() -> None:
    """Fix #14: Table 3 header has 7 RoB domains + Citation + Tier +
    Effect direction notes = 10 columns total."""
    receipts = [_FakeReceipt(receipt_id="X 2020", evidence_tier="A1")]
    md = tr.render_table_3_evidence_limitations(receipts)
    for domain in (
        "Allocation", "Blinding", "Attrition",
        "Outcome measurement", "Reporting",
        "Confounding control", "Generalizability",
    ):
        assert domain in md, f"missing column: {domain}"


def test_rob_domains_helper_returns_7_grades() -> None:
    """The internal _rob_domains helper returns exactly 7 grades per
    tier (matches the column count)."""
    for tier in ("A1", "A2", "B1", "B2", "C1", "C2", "unknown"):
        domains = tr._rob_domains(tier)
        assert len(domains) == 7, f"tier {tier} has {len(domains)} grades"


def test_b2_observational_has_na_for_blinding() -> None:
    """Discrim: blinding domain not meaningful for observational
    cohorts → 'n/a', not a fake 'low/high' grade.

    Fix #24/#26: Table 4 layout updated — Tool column now at index 2,
    so RoB domains shift one position right. Layout:
    Citation | Tier | Tool | Allocation | Blinding | Attrition |
    OutcomeMeasure | Reporting | Confounding | Generalizability |
    Overall RoB | Weight in synthesis | note. Blinding now index 4."""
    receipts = [_FakeReceipt(receipt_id="X 2020", evidence_tier="B2")]
    md = tr.render_table_3_evidence_limitations(receipts)
    line = [ln for ln in md.split("\n") if "X 2020" in ln][0]
    cells = [c.strip() for c in line.split("|") if c.strip()]
    assert cells[4] == "n/a"


def test_a1_rct_has_low_allocation_and_blinding() -> None:
    """A1 RCT: randomization + blinding are typically rigorous.
    Fix #24/#26: Allocation is index 3, Blinding is index 4."""
    receipts = [_FakeReceipt(receipt_id="W 2019", evidence_tier="A1")]
    md = tr.render_table_3_evidence_limitations(receipts)
    line = [ln for ln in md.split("\n") if "W 2019" in ln][0]
    cells = [c.strip() for c in line.split("|") if c.strip()]
    assert cells[3] == "low"  # Allocation
    assert cells[4] == "low"  # Blinding


def test_render_all_tables_includes_pointer_sentence() -> None:
    """Reviewer-fix P2: pointer sentence at the top so prose has a
    natural reference site for the structured evidence."""
    receipts = [_FakeReceipt(receipt_id="X 2020")]
    md = tr.render_all_tables(receipts)
    assert "Structured Evidence Tables" in md
    assert "referenced throughout" in md.lower() or "tables" in md.lower()


def test_render_all_tables_pointer_explains_table_layout() -> None:
    """Fix #21: pointer block at the top names the table layout (1-3
    follow the Researka v1 schema; 4 is supplemental). Replaces the
    Fix #6 footnote that explained Table 2 aggregate semantics —
    Table 2 is no longer an aggregator under the new spec."""
    receipts = [_FakeReceipt(receipt_id="X 2020")]
    md = tr.render_all_tables(receipts)
    assert "Researka v1 schema" in md
    assert "supplemental" in md.lower()


# ----- 2nd-pass reviewer fix tests (post second 2x review on Fix #6) ----


def test_n_extraction_subset_does_not_overcount() -> None:
    """2nd-pass reviewer P1 #1: '(subset analysis, n=15)' is a subgroup
    annotation, NOT an arm. Pre-fix this summed to 135 (120+15);
    arm-context detection now picks the largest single value."""
    n, pop = tr._split_population_n(
        "older adults, n=120 (subset analysis, n=15)"
    )
    assert n == "120"
    # Largest match wins because no arm-context surrounds either
    # value; subgroup pattern correctly handled.


def test_n_extraction_followup_does_not_overcount() -> None:
    """`n=120, follow-up n=80` — 80 is the subset who returned at
    month 12, NOT a separate arm. Largest single wins."""
    n, _ = tr._split_population_n("n=120, follow-up n=80")
    assert n == "120"


def test_n_extraction_arm_context_still_sums() -> None:
    """Arm-keyword nearby on BOTH matches → sum (the canonical
    treatment + placebo pattern)."""
    n, _ = tr._split_population_n(
        "older adults, n=120 (treatment), n=60 (placebo)"
    )
    assert n == "180"


def test_n_extraction_arm_context_with_intervention_keyword() -> None:
    """`intervention` and `control` are also arm-context keywords."""
    n, _ = tr._split_population_n(
        "n=80 intervention arm, n=80 control arm"
    )
    assert n == "160"


def test_n_extraction_range_plus_other_marks_with_sentinel() -> None:
    """2nd-pass reviewer P1 #2: when range + multi values coexist, do
    not silently drop. Annotate the largest with `(+ranges)` so the
    reader sees the loss."""
    n, _ = tr._split_population_n("n=120 + n=60-80 (subgroup)")
    assert "120" in n
    assert "ranges" in n.lower() or "+" in n


def test_n_extraction_pop_label_picks_longest_segment() -> None:
    """2nd-pass reviewer P2: comma-segment-zero issue. With n= mid-
    string, the FIRST comma segment may be truncated. Picking the
    longest non-empty segment preserves the qualifier."""
    n, pop = tr._split_population_n(
        "older adults, n=120, with diabetes"
    )
    assert n == "120"
    # Longest non-empty segment after stripping n= is "with diabetes"
    # (13 chars) vs "older adults" (12 chars). The qualifier wins.
    assert pop == "with diabetes"


def test_replace_paper_ids_uses_registry_when_provided() -> None:
    """2nd-pass reviewer P1 #3: registry-aware substitution prevents
    body prose / tables / references drift."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(
        Path(__file__).resolve().parent.parent / "scripts"
    ))
    import run_v06_synthesis as orch  # noqa: E402
    import citation_registry as cr  # noqa: E402

    @dataclass
    class _SchemaReceipt:
        receipt_id: str
        source_year: int | None = None
        source_doi: str | None = None
        source_pmid: str | None = None
        source_pmcid: str | None = None
        source_journal: str | None = None
        source_title: str | None = None
        source_venue: str | None = None
        title: str | None = None
        topic: str = "metformin"
        thesis_text: str = "..."
        spar_verdict: str = "accept_clean"
        n_claims: int = 1
        n_failed_traces: int = 0
        canonical_trial_id: str | None = None
        evidence_tier: str = "A1"
        directness: str = "direct"
        outcome_class: str = "longevity"
        effect_direction: str = "positive"
        p_values: tuple = ()
        receipt_path: str = ""
        population_summary: str | None = None

    receipts = [_SchemaReceipt(
        receipt_id="PMC12978362_molecular_mechanisms_of_metformin",
        source_year=2026,
    )]
    registry = cr.build_registry(receipts)
    paper = (
        "## Discussion\n\n"
        "The PMC12978362_molecular_mechanisms_of_metformin paper "
        "showed effects.\n"
    )
    out = orch._replace_paper_ids_with_author_year(
        paper, receipts, registry=registry,
    )
    # Body prose should now contain the registry's body_citation
    # (PMC12978362 2026), NOT the raw long handle.
    assert "PMC12978362 2026" in out
    assert "PMC12978362_molecular" not in out


def test_replace_paper_ids_falls_back_when_no_registry() -> None:
    """Backward compat: registry=None preserves legacy behaviour
    (uses _author_year_for_receipt)."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(
        Path(__file__).resolve().parent.parent / "scripts"
    ))
    import run_v06_synthesis as orch  # noqa: E402

    @dataclass
    class _Receipt:
        receipt_id: str = "Walton_2019_MASTERS_metformin"
        source_year: int | None = 2019

    paper = "Walton_2019_MASTERS_metformin showed muscle blunting."
    # No registry → falls back to _author_year_for_receipt → "Walton 2019"
    out = orch._replace_paper_ids_with_author_year(
        paper, [_Receipt()], registry=None,
    )
    assert "Walton 2019" in out


def test_aggregator_handles_null_plus_unclear_mix() -> None:
    """2nd-pass reviewer P3: [null, unclear, null] → not all-uniform,
    not mixed, no positive/negative → returns 'unclear'."""
    receipts = [
        _FakeReceipt(receipt_id="A 2020", effect_direction="null"),
        _FakeReceipt(receipt_id="B 2021", effect_direction="unclear"),
        _FakeReceipt(receipt_id="C 2022", effect_direction="null"),
    ]
    assert tr._aggregate_net_direction(receipts) == "unclear"


# ============ Fix #21 — new asymmetric-fix table tests =================


def test_table_1_includes_design_column() -> None:
    """Fix #21: Design column derived from evidence_tier so reader
    sees study type at a glance ('RCT (clinical)' vs 'Preclinical
    (animal/in vitro)') without memorising A1/A2/B/C codes."""
    receipts = [_FakeReceipt(receipt_id="W 2019", evidence_tier="A1")]
    md = tr.render_table_1_included_studies(receipts)
    assert "Design" in md
    assert "RCT (clinical)" in md


def test_design_from_tier_maps_each_canonical_tier() -> None:
    """Discrim: every canonical tier has a human-readable design."""
    cases = {
        "A1": "RCT (clinical)",
        "A2": "RCT (mechanistic)",
        "B1": "Review / meta-analysis",
        "B2": "Observational",
        "C1": "Preclinical (animal/in vitro)",
        "C2": "Preclinical (cell-only)",
        "mixed": "Mixed cluster",
    }
    for tier, label in cases.items():
        assert tr._design_from_tier(tier) == label


def test_design_from_tier_handles_none_and_unknown() -> None:
    """None / empty / unknown tier → '—' or echo, never crash."""
    assert tr._design_from_tier(None) == "—"
    assert tr._design_from_tier("") == "—"
    assert tr._design_from_tier("zzz") == "zzz"  # echo unknown for visibility


def test_table_3_tensions_renders_one_row_per_pair() -> None:
    """Fix #21 NEW Table 3: one row per non-orthogonal Tension. With
    a 3-pair matrix we get 3 data rows (matching the corpus tension
    count for the metformin run)."""
    @dataclass
    class _Tension:
        receipt_a_id: str
        receipt_b_id: str
        kind: str
        outcome_class: str
        summary: str
        severity: int

    @dataclass
    class _Matrix:
        pairs_data: list

        def non_orthogonal(self):
            return self.pairs_data

    pairs = [
        _Tension("A", "B", "directionality_disagreement",
                 "muscle_function", "A says +, B says -", 5),
        _Tension("C", "D", "tier_mismatch",
                 "frailty", "RCT vs animal-only", 3),
        _Tension("E", "F", "directness_mismatch",
                 "longevity", "human vs preclinical", 2),
    ]
    md = tr.render_table_3_cross_domain_tensions(_Matrix(pairs))
    assert "## Table 3" in md
    assert "Cross-Domain Tensions" in md
    # Each pair surfaces both receipt ids and the kind label
    for rid in ("A", "B", "C", "D", "E", "F"):
        assert rid in md
    assert "directionality_disagreement" in md
    assert "tier_mismatch" in md
    # Severity 5 / 3 / 2 surfaced as raw numerics (Q9 density carrier)
    for sev in ("5", "3", "2"):
        assert sev in md


def test_table_3_tensions_handles_none_matrix() -> None:
    """Defensive: None matrix → header + 'no matrix supplied' row,
    never a crash."""
    md = tr.render_table_3_cross_domain_tensions(None)
    assert "## Table 3" in md
    assert "no matrix supplied" in md


def test_table_3_tensions_handles_empty_pairs() -> None:
    """Empty non_orthogonal() → header + 'no non-orthogonal' row."""
    @dataclass
    class _Matrix:
        def non_orthogonal(self):
            return []
    md = tr.render_table_3_cross_domain_tensions(_Matrix())
    assert "no non-orthogonal" in md.lower()


def test_table_3_tensions_implication_uses_severity_label() -> None:
    """Severity ≥ 4 → 'load-bearing'; ≥ 2 → 'notable'; else 'minor'.
    Reader-friendly without dropping the raw number."""
    @dataclass
    class _T:
        receipt_a_id: str = "A"
        receipt_b_id: str = "B"
        kind: str = "directionality_disagreement"
        outcome_class: str = "x"
        summary: str = "y"
        severity: int = 5

    @dataclass
    class _M:
        pairs: tuple
        def non_orthogonal(self):
            return list(self.pairs)
    md_high = tr.render_table_3_cross_domain_tensions(_M((_T(severity=5),)))
    assert "load-bearing" in md_high
    md_mid = tr.render_table_3_cross_domain_tensions(_M((_T(severity=2),)))
    assert "notable" in md_mid
    md_low = tr.render_table_3_cross_domain_tensions(_M((_T(severity=1),)))
    assert "minor" in md_low


def test_table_4_renames_evidence_limitations() -> None:
    """Fix #21: per-domain RoB (formerly Table 3) is now Table 4
    (supplemental) to make room for the cross-domain tensions table
    at slot 3. Heading updated; backward-compat alias preserved."""
    receipts = [_FakeReceipt(receipt_id="X 2020", evidence_tier="A1")]
    md = tr.render_table_4_evidence_limitations(receipts)
    assert "## Table 4 (supplemental)" in md
    assert "Per-Domain Risk of Bias" in md
    # Same caveat preserved
    assert "Cochrane" in md or "ROBINS-I" in md


def test_render_table_3_evidence_limitations_alias_works() -> None:
    """Backward-compat: Fix #14 callers using the old name still work
    (the alias points at render_table_4_evidence_limitations)."""
    receipts = [_FakeReceipt(receipt_id="X 2020", evidence_tier="A1")]
    md_old = tr.render_table_3_evidence_limitations(receipts)
    md_new = tr.render_table_4_evidence_limitations(receipts)
    assert md_old == md_new


def test_render_all_tables_threads_matrix_into_table_3() -> None:
    """Sanity: when render_all_tables receives a matrix, Table 3 sees
    it (renders the tension rows, not the 'no matrix supplied' line)."""
    @dataclass
    class _T:
        receipt_a_id: str = "A"
        receipt_b_id: str = "B"
        kind: str = "tier_mismatch"
        outcome_class: str = "longevity"
        summary: str = "RCT vs animal"
        severity: int = 3

    @dataclass
    class _M:
        def non_orthogonal(self):
            return [_T()]
    receipts = [_FakeReceipt(receipt_id="X 2020")]
    md = tr.render_all_tables(receipts, _M())
    assert "tier_mismatch" in md
    assert "no matrix supplied" not in md


def test_render_all_tables_omits_matrix_handles_none_gracefully() -> None:
    """Backward-compat: render_all_tables(receipts) with no matrix
    arg defaults to None and Table 3 reports 'no matrix supplied'."""
    receipts = [_FakeReceipt(receipt_id="X 2020")]
    md = tr.render_all_tables(receipts)
    assert "## Table 3" in md
    assert "no matrix supplied" in md


# ============ Fix #21 follow-up — Table 5 numeric index ================


def test_table_5_renders_top_n_claims_per_paper() -> None:
    """Table 5: surfaces top-N quantitative claims per paper. With 5
    p-value claims for one paper, top_n=3 yields exactly 3 rows."""
    claims = {
        "Walton 2019": [
            {"claim_id": "p1", "claim_type": "p_value",
             "raw_text": "p < 0.001", "source_section": "results",
             "units": ""},
            {"claim_id": "u1", "claim_type": "unit_value",
             "raw_text": "850 mg", "source_section": "methods",
             "units": "mg"},
            {"claim_id": "pct1", "claim_type": "percentage",
             "raw_text": "30%", "source_section": "results",
             "units": ""},
        ],
    }
    receipts = [_FakeReceipt(receipt_id="Walton 2019")]
    md = tr.render_table_5_numeric_index(receipts, claims, top_n=3)
    assert "## Table 5" in md
    assert "p < 0.001" in md
    assert "850 mg" in md
    assert "30%" in md
    assert "Walton 2019" in md


def test_table_5_prefers_one_of_each_claim_type() -> None:
    """When a paper has many claims of one type and few of others,
    Table 5 picks one per type before doubling up — varied surface."""
    claims = {
        "Walton 2019": [
            {"claim_id": f"p{i}", "claim_type": "p_value",
             "raw_text": f"p = 0.0{i}", "source_section": "results",
             "units": ""}
            for i in range(10)  # 10 p_values
        ] + [
            {"claim_id": "u1", "claim_type": "unit_value",
             "raw_text": "850 mg", "source_section": "methods",
             "units": "mg"},
        ],
    }
    receipts = [_FakeReceipt(receipt_id="Walton 2019")]
    md = tr.render_table_5_numeric_index(receipts, claims, top_n=2)
    # Top-2 should include 1 p_value + 1 unit_value (varied) — NOT 2 p_values
    assert "850 mg" in md
    assert "Methods" in md or "methods" in md


def test_table_5_handles_no_claims_dict() -> None:
    """No claims dict → header + placeholder row, no crash."""
    receipts = [_FakeReceipt(receipt_id="X 2020")]
    md = tr.render_table_5_numeric_index(receipts, None)
    assert "## Table 5" in md
    assert "no claims index supplied" in md


def test_table_5_handles_empty_claims_dict() -> None:
    """Empty dict → header + 'no claims found' row."""
    receipts = [_FakeReceipt(receipt_id="X 2020")]
    md = tr.render_table_5_numeric_index(receipts, {})
    assert "## Table 5" in md
    # Empty dict triggers the "no claims index supplied" branch
    assert "no claims" in md.lower()


def test_table_5_sample_size_claim_renders_with_n_prefix() -> None:
    """Q9 numeric-density requires `n=NN` form. Sample-size claims
    must render with the prefix even when raw_text is just '120'."""
    claims = {
        "Walton 2019": [
            {"claim_id": "n1", "claim_type": "sample_size",
             "raw_text": "120", "source_section": "abstract",
             "units": ""},
        ],
    }
    receipts = [_FakeReceipt(receipt_id="Walton 2019")]
    md = tr.render_table_5_numeric_index(receipts, claims, top_n=1)
    assert "n=120" in md


def test_table_5_format_claim_value_handles_units_already_in_raw() -> None:
    """When raw_text already includes units (e.g. '850 mg'), don't
    duplicate them in the rendered cell."""
    claim = {"raw_text": "850 mg", "units": "mg",
             "claim_type": "unit_value"}
    out = tr._format_claim_value(claim)
    assert out == "850 mg"  # no duplication


def test_render_all_tables_threads_claims_to_table_5() -> None:
    """Sanity: render_all_tables passes claims_by_citation through
    to Table 5; the claims surface in the rendered output."""
    receipts = [_FakeReceipt(receipt_id="X 2020")]
    claims = {
        "X 2020": [
            {"claim_id": "p1", "claim_type": "p_value",
             "raw_text": "p < 0.05", "source_section": "abstract",
             "units": ""},
        ],
    }
    md = tr.render_all_tables(receipts, None, claims)
    assert "## Table 5" in md
    assert "p < 0.05" in md
    # Pointer block names Table 5 too
    assert "Table 5" in md.split("Structured Evidence Tables")[1][:600]


# ============ Fix #24 + #26 — RoB tool + overall + weight ==============


def test_table_4_includes_tool_column() -> None:
    """Fix #26: Tool column names the RoB framework (Cochrane RoB-2,
    ROBINS-I, SYRCLE, AMSTAR-2) so reviewers see what was applied."""
    receipts = [
        _FakeReceipt(receipt_id="A1 2020", evidence_tier="A1"),
        _FakeReceipt(receipt_id="B2 2020", evidence_tier="B2"),
        _FakeReceipt(receipt_id="C1 2020", evidence_tier="C1"),
        _FakeReceipt(receipt_id="B1 2020", evidence_tier="B1"),
    ]
    md = tr.render_table_4_evidence_limitations(receipts)
    assert "Tool" in md
    assert "Cochrane RoB-2" in md       # A1 RCT
    assert "ROBINS-I" in md             # B2 observational
    assert "SYRCLE" in md               # C1 preclinical
    assert "AMSTAR-2" in md             # B1 review


def test_overall_rob_high_when_load_bearing_domain_high() -> None:
    """Worst-of semantics: any 'high' on allocation/blinding/attrition/
    outcome bumps the overall RoB to 'high'."""
    # Pretend a tier has high blinding (index 1)
    domains = ("low", "high", "low", "low", "low", "low", "moderate")
    assert tr._overall_rob(domains) == "high"


def test_overall_rob_plurality_otherwise() -> None:
    """When no load-bearing domain is high, overall is the plurality
    grade across non-`n/a` domains."""
    domains = ("low", "low", "moderate", "low", "low", "low", "moderate")
    assert tr._overall_rob(domains) == "low"


def test_overall_rob_handles_all_na() -> None:
    """All-`n/a` domains → overall = 'n/a'."""
    domains = ("n/a",) * 7
    assert tr._overall_rob(domains) == "n/a"


def test_weight_in_synthesis_load_bearing_for_a1_direct() -> None:
    """Fix #24: A1 + direct + low RoB → load-bearing."""
    weight = tr._weight_in_synthesis("A1", "direct", "low")
    assert "load-bearing" in weight


def test_weight_in_synthesis_mechanistic_for_a2_or_a1_mech() -> None:
    """Mechanistic label applies to A2 RCTs and A1 with mechanistic
    directness (e.g. MILES)."""
    a2 = tr._weight_in_synthesis("A2", "direct", "low")
    a1_mech = tr._weight_in_synthesis("A1", "mechanistic", "low")
    assert "mechanistic" in a2
    assert "mechanistic" in a1_mech


def test_weight_in_synthesis_supporting_for_b1_review() -> None:
    """B1 systematic reviews → supporting weight."""
    weight = tr._weight_in_synthesis("B1", "review", "moderate")
    assert "supporting" in weight


def test_weight_in_synthesis_high_rob_overrides_to_hypothesis_generating() -> None:
    """Even an A1 RCT with high overall RoB → hypothesis-generating.
    A reviewer should see immediately that the trust collapses to
    'use cautiously' when RoB is bad."""
    weight = tr._weight_in_synthesis("A1", "direct", "high")
    assert "hypothesis-generating" in weight
    assert "high RoB" in weight


def test_weight_in_synthesis_handles_unknown_tier() -> None:
    """Unknown tier → unweighted (defensive — never crashes)."""
    weight = tr._weight_in_synthesis("zzz", "indirect", "low")
    assert "unweighted" in weight


def test_table_4_includes_overall_rob_and_weight_columns() -> None:
    """End-to-end: Table 4 surfaces both new columns in its rows."""
    receipts = [
        _FakeReceipt(receipt_id="Walton 2019", evidence_tier="A1",
                     directness="direct"),
        _FakeReceipt(receipt_id="MILES 2018", evidence_tier="A2",
                     directness="direct"),
    ]
    md = tr.render_table_4_evidence_limitations(receipts)
    assert "Overall RoB" in md
    assert "Weight in synthesis" in md
    # Walton should show load-bearing weight; MILES should show mechanistic
    walton_row = [ln for ln in md.split("\n") if "Walton 2019" in ln][0]
    miles_row = [ln for ln in md.split("\n") if "MILES 2018" in ln][0]
    assert "load-bearing" in walton_row
    assert "mechanistic" in miles_row


def test_table_4_caveat_mentions_synthesis_weight() -> None:
    """The caveat above the table must explain what 'Weight in
    synthesis' means so a reader understands the column is a
    derived qualitative weighting, not Cochrane judgement."""
    receipts = [_FakeReceipt(receipt_id="X 2020", evidence_tier="A1")]
    md = tr.render_table_4_evidence_limitations(receipts)
    assert "Weight in synthesis" in md
    assert "tier × directness × overall RoB" in md or (
        "qualitative weighting" in md
    )
