"""Fix #3: citation_registry — eliminate PMCID body leaks BY
CONSTRUCTION rather than post-hoc cleanup. Discriminating tests
isolate each substitution path."""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import citation_registry as cr  # noqa: E402


@dataclass
class _FakeReceipt:
    receipt_id: str
    source_year: int | None = None
    source_doi: str | None = None
    source_pmid: str | None = None
    source_pmcid: str | None = None
    source_journal: str | None = None
    title: str | None = None


def test_author_year_receipt_id_yields_clean_citation() -> None:
    """`Walton_2019_MASTERS_metformin_blunts_resistance_hy` →
    `Walton 2019` — strip the trial + descriptive suffix."""
    citation = cr._body_citation_for("Walton_2019_MASTERS_metformin_blunts")
    assert citation == "Walton 2019"


def test_pmcid_receipt_id_yields_compact_handle_with_year() -> None:
    """`PMC12978362_molecular_mechanisms_of_metformin_acti` →
    `PMC12978362 2026` (NOT the long descriptive slug). This is the
    asymmetric high-leverage fix: pre-fix the writer received the
    long form and emitted it in body prose."""
    citation = cr._body_citation_for(
        "PMC12978362_molecular_mechanisms_of_metformin_acti",
        source_year=2026,
    )
    assert citation == "PMC12978362 2026"


def test_pmcid_receipt_id_falls_back_to_year_in_id() -> None:
    """If source_year is missing, extract a 4-digit year from the
    receipt_id slug (many PMC handles include the year)."""
    citation = cr._body_citation_for(
        "PMC12978362_molecular_mechanisms_of_metformin_acti_2026",
    )
    assert citation == "PMC12978362 2026"


def test_validate_body_citation_catches_long_pmcid_slug() -> None:
    """The whole point of the gate: the long PMCID descriptive form
    MUST be caught as a leak."""
    leaks = cr.validate_body_citation(
        "PMC12978362_molecular_mechanisms_of_metformin_acti"
    )
    assert leaks


def test_validate_body_citation_catches_long_author_year_slug() -> None:
    leaks = cr.validate_body_citation(
        "Walton_2019_MASTERS_metformin_blunts_"
    )
    assert leaks


def test_validate_body_citation_passes_clean_forms() -> None:
    """Clean forms must NOT be flagged."""
    assert cr.validate_body_citation("Walton 2019") == []
    assert cr.validate_body_citation("PMC12978362 2026") == []
    assert cr.validate_body_citation("Smith et al. 2026") == []


def test_build_registry_raises_on_internal_leak() -> None:
    """If a receipt produces a body_citation that matches a blocked
    pattern (regression in _body_citation_for), build_registry raises
    so the pipeline can't ship with a leak baked into the registry."""

    # Inject a contrived receipt that defeats the heuristic. This test
    # depends on _body_citation_for being defensible — if a future
    # heuristic change emits a long form, this test must catch it.
    # We monkey-patch _body_citation_for to a deliberately-broken impl.
    def _broken(receipt_id: str, source_year: int | None = None) -> str:
        return receipt_id  # returns the raw long handle — should fail
    real_fn = cr._body_citation_for
    cr._body_citation_for = _broken
    try:
        receipts = [_FakeReceipt(
            receipt_id="PMC12978362_molecular_mechanisms_of_metformin",
            source_year=2026,
        )]
        with pytest.raises(ValueError, match="blocked pattern"):
            cr.build_registry(receipts)
    finally:
        cr._body_citation_for = real_fn


def test_substitute_receipt_ids_replaces_full_handle() -> None:
    """Belt-and-braces: any leaked long handle in the rendered paper
    gets substituted with the registry's body_citation."""
    receipts = [_FakeReceipt(
        receipt_id="PMC12978362_molecular_mechanisms_of_metformin_acti",
        source_year=2026,
    )]
    registry = cr.build_registry(receipts)
    paper = (
        "## Discussion\n\n"
        "The PMC12978362_molecular_mechanisms_of_metformin_acti finding "
        "was striking.\n"
    )
    out = cr.substitute_receipt_ids(paper, registry)
    assert "PMC12978362 2026" in out
    assert "PMC12978362_molecular" not in out


def test_substitute_receipt_ids_handles_truncations() -> None:
    """The writer / post-processor sometimes truncates long handles to
    20-30 chars; the substitution loop covers those variants."""
    receipts = [_FakeReceipt(
        receipt_id="Walton_2019_MASTERS_metformin_blunts_resistance_hy",
        source_year=2019,
    )]
    registry = cr.build_registry(receipts)
    paper = (
        "Discussion of Walton_2019_MASTERS_metformin_b (truncated form) "
        "and Walton_2019_MASTERS (shorter still)."
    )
    out = cr.substitute_receipt_ids(paper, registry)
    assert "Walton_2019_MASTERS" not in out
    assert out.count("Walton 2019") >= 1


def test_transform_receipts_replaces_receipt_id_for_writer() -> None:
    """The writer iterates over receipts and emits receipt_id verbatim.
    transform_receipts_for_writer rewrites receipt_id BEFORE the writer
    sees it — so PMCID body leaks become structurally impossible."""

    # Fake a frozen ReceiptSummary-like object that supports
    # dataclasses.replace. Must use a real frozen dataclass for replace
    # to work.
    @dataclass(frozen=True)
    class _Receipt:
        receipt_id: str
        source_year: int | None = None
        source_doi: str | None = None
        source_pmid: str | None = None
        source_pmcid: str | None = None
        source_journal: str | None = None
        title: str | None = None

    receipts = [_Receipt(
        receipt_id="PMC12978362_molecular_mechanisms_of_metformin",
        source_year=2026,
    )]
    registry = cr.build_registry(receipts)
    transformed = cr.transform_receipts_for_writer(receipts, registry)
    # Writer-facing receipt_id is the clean body_citation
    assert transformed[0].receipt_id == "PMC12978362 2026"
    # Original list untouched (frozen, by construction)
    assert receipts[0].receipt_id.startswith("PMC12978362_molecular")


def test_reference_id_stable_across_runs() -> None:
    """R01, R02, ... assignment is positional and deterministic. Runs
    over the same receipt list produce the same reference_ids."""
    receipts = [
        _FakeReceipt(receipt_id="Walton_2019_MASTERS"),
        _FakeReceipt(receipt_id="Konopka_2019_metformin"),
        _FakeReceipt(receipt_id="Witham_2025_MET_PREVENT"),
    ]
    r1 = cr.build_registry(receipts)
    r2 = cr.build_registry(receipts)
    assert r1["Walton_2019_MASTERS"].reference_id == "R01"
    assert r1["Konopka_2019_metformin"].reference_id == "R02"
    assert r1["Witham_2025_MET_PREVENT"].reference_id == "R03"
    assert r1 == r2


def test_citation_entry_is_frozen_kw_only() -> None:
    """CitationEntry is frozen+slots+kw_only per project rule."""
    e = cr.CitationEntry(
        receipt_id="X", body_citation="X 2020", reference_id="R01",
    )
    with pytest.raises(Exception):  # FrozenInstanceError
        e.body_citation = "mutated"
    # kw_only: positional construction must fail
    with pytest.raises(TypeError):
        cr.CitationEntry("X", "X 2020", "R01")  # type: ignore[call-arg]


def test_substitute_idempotent_on_already_clean_paper() -> None:
    """A paper with no internal leaks is unchanged by substitution."""
    receipts = [_FakeReceipt(receipt_id="Walton_2019_MASTERS",
                              source_year=2019)]
    registry = cr.build_registry(receipts)
    clean_paper = "## Discussion\n\nThe Walton 2019 trial showed ...\n"
    out = cr.substitute_receipt_ids(clean_paper, registry)
    assert out == clean_paper


# ----- Reviewer-fix discriminating tests (post-2x review) ---------------


def test_multi_word_surname_van_de_werf_extracted() -> None:
    """Pre-fix `Van_de_Werf_2019_...` produced `'Van 2019'` (dropped
    `_de_Werf`). Now token-based extraction finds the year and treats
    everything before as the multi-word surname."""
    citation = cr._body_citation_for("Van_de_Werf_2019_metformin_trial")
    assert citation == "Van de Werf 2019"


def test_apostrophe_surname_o_brien_extracted() -> None:
    """Pre-fix `O'Brien_2019_...` did not match `[A-Z][a-zA-Z]+_\\d{4}`
    (apostrophe not in the class). Now any token shape works."""
    citation = cr._body_citation_for("O'Brien_2019_metformin_trial")
    assert citation == "O'Brien 2019"


def test_hyphenated_surname_smith_jones_extracted() -> None:
    citation = cr._body_citation_for("Smith-Jones_2019_metformin_trial")
    assert citation == "Smith-Jones 2019"


def test_lowercase_surname_normalized() -> None:
    """Lowercase paper_id sources should produce title-cased citations."""
    citation = cr._body_citation_for("walton_2019_masters_metformin")
    assert citation == "Walton 2019"


def test_short_surname_wu_2024_with_short_trail() -> None:
    """`Wu_2024_T2D` (11 chars total) — pre-fix the 8-char floor on
    variants dropped the bare `Wu_2024` (7 chars), leaving leaks
    uncovered. Now floor is 5; `Wu_2024` is in variants."""
    receipts = [_FakeReceipt(receipt_id="Wu_2024_T2D", source_year=2024)]
    registry = cr.build_registry(receipts)
    paper = "## Discussion\n\nWu_2024_T2D and Wu_2024 both leak.\n"
    out = cr.substitute_receipt_ids(paper, registry)
    assert "Wu_2024_T2D" not in out
    assert "Wu_2024" not in out
    assert out.count("Wu 2024") >= 2


def test_cross_receipt_collision_drops_ambiguous_variant() -> None:
    """Pre-fix: two receipts with shared prefix `Walton_2019_*` would
    collide — `Walton_2019` variant could substitute into either's
    occurrence. Now the cross-receipt collision check drops the
    ambiguous variant."""
    receipts = [
        _FakeReceipt(
            receipt_id="Walton_2019_MASTERS_metformin_blunts",
            source_year=2019,
        ),
        _FakeReceipt(
            receipt_id="Walton_2019_PHOENIX_resistance_training",
            source_year=2019,
        ),
    ]
    registry = cr.build_registry(receipts)
    # Paper has the bare ambiguous prefix — it's a leak we CAN'T resolve
    # safely (which Walton 2019 paper?), so substitution must NOT fire.
    paper = "## Discussion\n\nThe Walton_2019 finding was striking.\n"
    out = cr.substitute_receipt_ids(paper, registry)
    # The ambiguous bare prefix stays unsubstituted (it's a real leak,
    # but auto-resolving would silently misattribute).
    assert "Walton_2019 " in out  # space-suffix preserved
    # The full receipt_ids ARE unambiguous → still substituted
    paper2 = (
        "## Discussion\n\n"
        "The Walton_2019_MASTERS_metformin_blunts trial vs "
        "Walton_2019_PHOENIX_resistance_training contrast.\n"
    )
    out2 = cr.substitute_receipt_ids(paper2, registry)
    assert "Walton_2019_MASTERS_metformin_blunts" not in out2
    assert "Walton_2019_PHOENIX_resistance_training" not in out2


def test_extract_year_picks_plausible_year_not_n_value() -> None:
    """`PMC12978362_metformin_n=2018_subjects_outcomes_2026` — the
    `2018` is a sample size, the `2026` is the publication year.
    Last-plausible-year wins."""
    year = cr._extract_year_from_id(
        "PMC12978362_metformin_n_2018_subjects_outcomes_2026"
    )
    assert year == 2026


def test_extract_year_rejects_implausible_years() -> None:
    """A 4-digit number outside 1990-2100 is not a publication year."""
    assert cr._extract_year_from_id("PMC123_n_3500_subjects") is None
    assert cr._extract_year_from_id("PMC123_n_1850_subjects") is None


def test_validate_body_citation_catches_bare_handles() -> None:
    """Bare `Walton_2019` (no trailing) and bare `PMC12978362` (no
    year) ARE leaks. Pre-fix the patterns required trailing keywords."""
    assert cr.validate_body_citation("Walton_2019")
    assert cr.validate_body_citation("PMC12978362")


def test_build_registry_raises_on_empty_receipt_id() -> None:
    """An empty receipt_id is malformed; can't key the registry by it."""
    receipts = [_FakeReceipt(receipt_id="")]
    with pytest.raises(ValueError, match="empty receipt_id"):
        cr.build_registry(receipts)


# ----- Fix #9 reviewer-P1: PMCID year-lookahead ------------------------


def test_bare_pmcid_in_body_gets_year_decorated() -> None:
    """Fix #9: pre-fix the self-substitution guard skipped variants
    contained in their body_citation. So `(PMC12978362)` in body never
    got rewritten to `(PMC12978362 2026)` — 96 such leaks in the
    latest E2E paper. Now: regex with negative-year-lookahead applies
    the substitution while leaving already-decorated forms alone."""
    receipts = [_FakeReceipt(
        receipt_id="PMC12978362_molecular_mechanisms_of_metformin",
        source_year=2026,
    )]
    registry = cr.build_registry(receipts)
    paper = (
        "## Discussion\n\n"
        "The bare handle (PMC12978362) appears here. The decorated "
        "form (PMC12978362 2026) appears here too. Both should end "
        "up as the decorated form.\n"
    )
    out = cr.substitute_receipt_ids(paper, registry)
    # Bare → decorated
    assert "(PMC12978362 2026)" in out
    # Pre-decorated → unchanged (no double-apply)
    assert "(PMC12978362 2026 2026)" not in out
    # Count the decorated form: should appear EXACTLY twice (once
    # from the bare leak that was rewritten, once from the original
    # pre-decorated reference).
    assert out.count("(PMC12978362 2026)") == 2


def test_pre_decorated_pmcid_is_not_double_substituted() -> None:
    """Discrim: a paper containing only the pre-decorated form should
    be unchanged (year-lookahead correctly suppresses substitution)."""
    receipts = [_FakeReceipt(
        receipt_id="PMC12978362_molecular_mechanisms_of_metformin",
        source_year=2026,
    )]
    registry = cr.build_registry(receipts)
    paper = "## Discussion\n\nThe (PMC12978362 2026) finding was striking.\n"
    out = cr.substitute_receipt_ids(paper, registry)
    assert out == paper  # no change


def test_walton_2019_clean_text_no_double_apply() -> None:
    """Walton 2019 sanity: clean prose 'The Walton 2019 trial showed'
    must not become 'The Walton 2019 2019 trial showed' — the year-
    lookahead protects this case too."""
    receipts = [_FakeReceipt(
        receipt_id="Walton_2019_MASTERS_metformin_blunts",
        source_year=2019,
    )]
    registry = cr.build_registry(receipts)
    clean_paper = "## Discussion\n\nThe Walton 2019 trial showed effects.\n"
    out = cr.substitute_receipt_ids(clean_paper, registry)
    assert out == clean_paper


def test_walton_alone_in_body_gets_year_decorated() -> None:
    """If the writer emits bare 'Walton' in body prose (not followed
    by 2019), substitute to 'Walton 2019'. This was previously
    blocked by the self-substitution guard."""
    receipts = [_FakeReceipt(
        receipt_id="Walton_2019_MASTERS_metformin_blunts",
        source_year=2019,
    )]
    registry = cr.build_registry(receipts)
    paper = "## Discussion\n\nWalton showed effects in the MASTERS trial.\n"
    out = cr.substitute_receipt_ids(paper, registry)
    # Bare 'Walton' → 'Walton 2019'
    assert "Walton 2019 showed effects" in out


def test_year_suffix_after_helper_extracts_correct_year() -> None:
    assert cr._year_suffix_after("PMC12978362", "PMC12978362 2026") == "2026"
    assert cr._year_suffix_after("Walton", "Walton 2019") == "2019"
    # Non-trailing-year shapes return ""
    assert cr._year_suffix_after("Walton", "Walton et al. 2019") == ""
    assert cr._year_suffix_after("PMC12978362", "PMC12978362") == ""
    assert cr._year_suffix_after("X", "Y") == ""  # no prefix match


def test_transform_matrix_in_lockstep_with_receipts() -> None:
    """P1 reviewer fix: the matrix must be transformed alongside
    receipts. Otherwise the writer's anchor-validator sees transformed
    receipt_ids in writer_receipts but original handles in
    matrix.receipts and trips invariant checks."""

    @dataclass(frozen=True)
    class _Receipt:
        receipt_id: str
        source_year: int | None = None
        source_doi: str | None = None
        source_pmid: str | None = None
        source_pmcid: str | None = None
        source_journal: str | None = None
        title: str | None = None

    @dataclass(frozen=True)
    class _Tension:
        receipt_a_id: str
        receipt_b_id: str
        kind: str = "agreement"
        outcome_class: str = "longevity"
        summary: str = ""
        severity: int = 0

    @dataclass(frozen=True)
    class _Matrix:
        receipts: tuple
        pairs: tuple

    receipts = [
        _Receipt(receipt_id="Walton_2019_MASTERS", source_year=2019),
        _Receipt(receipt_id="PMC12978362_molecular_metformin",
                 source_year=2026),
    ]
    matrix = _Matrix(
        receipts=tuple(receipts),
        pairs=(_Tension(
            receipt_a_id="Walton_2019_MASTERS",
            receipt_b_id="PMC12978362_molecular_metformin",
        ),),
    )
    registry = cr.build_registry(receipts)
    new_matrix = cr.transform_matrix_for_writer(matrix, registry)
    # Transformed receipts inside matrix
    assert new_matrix.receipts[0].receipt_id == "Walton 2019"
    assert new_matrix.receipts[1].receipt_id == "PMC12978362 2026"
    # Pair refs rewritten too
    assert new_matrix.pairs[0].receipt_a_id == "Walton 2019"
    assert new_matrix.pairs[0].receipt_b_id == "PMC12978362 2026"
    # Original matrix untouched (frozen)
    assert matrix.receipts[0].receipt_id == "Walton_2019_MASTERS"
