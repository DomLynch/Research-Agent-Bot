"""Tests for agent/citation_trace.py — the moat orchestrator.

Each per-check trace function gets:
- A positive test (real evidence → passed=True)
- A negative test (planted failure shape → passed=False)

Plus orchestrator tests that compose multiple checks and end-to-end tests
that load the planted-failure fixtures and assert the right TraceType
catches each case.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from agent.citation_trace import (
    summary,
    trace_alias_match,
    trace_claim,
    trace_claim_graph,
    trace_nct_exists,
    trace_numeric_in_text,
    trace_p_value_in_text,
    trace_percentage_in_text,
    trace_role_match,
)
from agent.schemas import Claim, ClaimGraph
from agent.topic_pack import TopicPack, load_topic_pack
from agent.trace_clients import (
    FixtureDrugAliasClient,
    FixtureTrialRegistryClient,
)
from agent.types import EvidenceItem, Source

METFORMIN_PATH = Path(__file__).parent.parent / "topic_packs" / "metformin.toml"


@pytest.fixture(scope="module")
def metformin_pack() -> TopicPack:
    return load_topic_pack(METFORMIN_PATH)


@pytest.fixture(scope="module")
def registry() -> FixtureTrialRegistryClient:
    return FixtureTrialRegistryClient()


@pytest.fixture(scope="module")
def drug_client() -> FixtureDrugAliasClient:
    return FixtureDrugAliasClient()


def _src(ref: int = 1, nct: str | None = None) -> Source:
    return Source(ref=ref, title="", year=2024, url="", source="pubmed", nct=nct)


def _item(
    *,
    ref: int = 1,
    role: str = "published_results",
    design: str = "rct",
    tier: str = "A1",
    direct: bool = True,
    nct: str | None = None,
    abstract: str = "",
) -> EvidenceItem:
    return EvidenceItem(
        source=_src(ref, nct=nct), abstract=abstract,
        design=design, role=role, tier=tier,  # type: ignore[arg-type]
        direct=direct, strict=True,
    )


def _claim(
    *,
    cid: str = "C01",
    text: str = "metformin blunts hypertrophy.",
    refs: tuple[int, ...] = (1,),
    directness: str = "direct",
) -> Claim:
    return Claim(
        claim_id=cid, text=text, claim_type="efficacy",
        supporting_refs=refs, opposing_refs=(),
        directness=directness,  # type: ignore[arg-type]
        evidence_tier="A1", confidence="high", attack_surface=(),
    )


# --- trace_nct_exists -----------------------------------------------------


def test_trace_nct_exists_pass_for_real_nct(
    registry: FixtureTrialRegistryClient,
) -> None:
    """MASTERS NCT02308228 is in the fixture registry."""
    claim = _claim()
    item = _item(nct="NCT02308228")  # role=published_results, has_results=True
    traces = list(trace_nct_exists(claim, item, registry))
    assert len(traces) == 1
    rec = traces[0]
    assert rec.passed is True
    assert rec.trace_type == "nct_exists"
    assert "NCT02308228" in rec.detail


def test_trace_nct_exists_planted_case_2(
    registry: FixtureTrialRegistryClient,
) -> None:
    """Planted case 2: fabricated NCT99999999."""
    claim = _claim()
    item = _item(nct="NCT99999999")
    traces = list(trace_nct_exists(claim, item, registry))
    assert len(traces) == 1 and traces[0].passed is False
    assert "not found" in traces[0].detail.lower()


def test_trace_nct_exists_yields_nothing_when_no_registry_id(
    registry: FixtureTrialRegistryClient,
) -> None:
    """**Design decision (documented):** when no registry ID is found on
    any surface (source.nct, ISRCTN-in-URL, NCT-in-abstract), the
    generator yields NOTHING — empty iterator, not a synthetic failure
    trace.

    Rationale: trace_nct_exists is one of several trace types the
    orchestrator runs per item. An item without a registry ID is not
    contradictory by itself — it just means *this* check has nothing
    to verify. Other traces (role_match, alias_match, p_value_in_text,
    percentage_in_text) still run and gate the claim. The orchestrator
    composes the gates; trace_nct_exists doesn't.

    Trade-off: an item that *should* have a registry ID but doesn't
    won't fail here. Upstream (`evidence_cards.bundle()` + the topic
    pack's role assignment) is responsible for ensuring published_results
    items carry an NCT or equivalent. If they don't, the bundle invariant
    in types.py catches it before this stage runs.
    """
    claim = _claim()
    item = _item(nct=None)
    assert list(trace_nct_exists(claim, item, registry)) == []


def test_trace_nct_exists_yields_nothing_when_abstract_has_prose_but_no_registry_id(
    registry: FixtureTrialRegistryClient,
) -> None:
    """Boundary check on yield-zero: empty *output* requires empty
    *registry IDs*, NOT empty *abstract*. An abstract with substantive
    prose but no NCT/ISRCTN must still yield nothing — the check is
    'no IDs to trace', not 'no text at all'."""
    claim = _claim()
    item = _item(
        nct=None,
        abstract=(
            "Metformin reduced HbA1c by 0.5% over 12 weeks in a "
            "randomized cohort. No registration ID was reported."
        ),
    )
    assert list(trace_nct_exists(claim, item, registry)) == []


# --- P1.1 + P1.2 regression tests (reviewer fixes) ------------------------


def test_trace_nct_exists_fails_when_published_results_has_no_results(
    registry: FixtureTrialRegistryClient,
) -> None:
    """P1.1: TAME (NCT04264897) registry says has_results=False. If
    upstream classified the cite as role='published_results', the trace
    must fail — that's the protocol-as-results contradiction caught at
    the trace layer (4th defense for case 1)."""
    claim = _claim()
    # Construct an EvidenceItem with role='published_results' citing TAME
    # — this is the contradiction shape: registry says recruiting/no
    # results but the pipeline classified the cite as a results-paper.
    item = _item(role="published_results", nct="NCT04264897")
    traces = list(trace_nct_exists(claim, item, registry))
    assert len(traces) == 1
    assert traces[0].passed is False
    assert "has_results=False" in traces[0].detail
    assert "Protocol-as-results" in traces[0].detail


def test_trace_nct_exists_passes_when_role_protocol_and_no_results(
    registry: FixtureTrialRegistryClient,
) -> None:
    """The complementary half of P1.1: when the role correctly says
    registered_pending and the registry agrees has_results=False, the
    trace passes (registry just records the pending status)."""
    claim = _claim()
    item = _item(role="registered_pending", nct="NCT04264897")
    traces = list(trace_nct_exists(claim, item, registry))
    assert len(traces) == 1 and traces[0].passed is True


def test_trace_nct_exists_finds_nct_in_abstract(
    registry: FixtureTrialRegistryClient,
) -> None:
    """P1.2: live MASTERS shape — source.nct=None but NCT02308228 in
    abstract. The trace must still be emitted."""
    claim = _claim()
    item = _item(
        nct=None,
        abstract="ClinicalTrials.gov Identifier: NCT02308228.",
    )
    traces = list(trace_nct_exists(claim, item, registry))
    assert len(traces) == 1
    assert traces[0].passed is True
    assert "NCT02308228" in traces[0].detail


def test_trace_nct_exists_finds_isrctn_in_url(
    registry: FixtureTrialRegistryClient,
) -> None:
    """ISRCTN in URL also fires (MET-PREVENT shape)."""
    claim = _claim()
    item = _item(
        nct=None,
        # _item helper doesn't take url, build directly
    )
    item = EvidenceItem(
        source=Source(
            ref=1, title="", year=2024,
            url="https://www.isrctn.com/ISRCTN29932357",
            source="pubmed", nct=None,
        ),
        abstract="",
        design="rct", role="published_results", tier="A1",
        direct=True, strict=True,
    )
    traces = list(trace_nct_exists(claim, item, registry))
    assert len(traces) == 1 and traces[0].passed is True
    assert "ISRCTN29932357" in traces[0].detail


def test_trace_nct_exists_emits_one_per_id_when_multiple(
    registry: FixtureTrialRegistryClient,
) -> None:
    """Multiple NCTs across surfaces → multiple traces. Order: source.nct
    first, then URL, then abstract."""
    claim = _claim()
    item = EvidenceItem(
        source=Source(
            ref=1, title="", year=2024, url="",
            source="pubmed", nct="NCT02308228",  # MASTERS
        ),
        abstract="See also NCT01765946 (MILES).",  # MILES NCT
        design="rct", role="published_results", tier="A1",
        direct=True, strict=True,
    )
    traces = list(trace_nct_exists(claim, item, registry))
    assert len(traces) == 2
    # First trace: from source.nct
    assert "NCT02308228" in traces[0].detail
    # Second: from abstract
    assert "NCT01765946" in traces[1].detail


def test_trace_nct_exists_dedupes_repeated_id() -> None:
    """Same NCT in source.nct AND abstract → emit once (deduped)."""
    registry = FixtureTrialRegistryClient()
    claim = _claim()
    item = EvidenceItem(
        source=Source(
            ref=1, title="", year=2024, url="",
            source="pubmed", nct="NCT02308228",
        ),
        abstract="ClinicalTrials.gov Identifier: NCT02308228.",
        design="rct", role="published_results", tier="A1",
        direct=True, strict=True,
    )
    traces = list(trace_nct_exists(claim, item, registry))
    assert len(traces) == 1, f"expected one trace, got {len(traces)}"


# --- trace_role_match -----------------------------------------------------


def test_trace_role_match_pass_for_aligned_claim() -> None:
    """Direct claim with at least one direct evidence item."""
    claim = _claim(directness="direct")
    items = {1: _item(role="published_results", direct=True)}
    rec = trace_role_match(claim, items)
    assert rec.passed is True
    assert rec.trace_type == "role_match"


def test_trace_role_match_fails_when_direct_claim_has_no_direct_evidence() -> None:
    claim = _claim(directness="direct")
    items = {1: _item(role="mechanistic", direct=False)}
    rec = trace_role_match(claim, items)
    assert rec.passed is False
    assert "DIRECTNESS_MISMATCH" in rec.detail or "directness" in rec.detail.lower()


def test_trace_role_match_passes_for_non_direct_claims() -> None:
    """Non-direct claims have no analogous constraint."""
    claim = _claim(directness="indirect")
    items = {1: _item(role="review", direct=False)}
    rec = trace_role_match(claim, items)
    assert rec.passed is True


# --- trace_p_value_in_text ------------------------------------------------


def test_trace_p_value_pass_for_matching_pvalue() -> None:
    claim = _claim(text="Reduced muscle mass (p=0.003).")
    item = _item(abstract="Placebo gained more lean mass (p=0.003).")
    traces = list(trace_p_value_in_text(claim, item))
    assert len(traces) == 1 and traces[0].passed is True


def test_trace_p_value_planted_case_3_inflated() -> None:
    """Claim cites p<0.001 but source has p=0.08."""
    claim = _claim(text="Reported significant attenuation of VO2max (p<0.001).")
    item = _item(abstract="Metformin attenuated VO2max (p=0.08).")
    traces = list(trace_p_value_in_text(claim, item))
    assert len(traces) == 1 and traces[0].passed is False
    assert "p<0.001" in traces[0].detail
    assert traces[0].source_excerpt is not None  # excerpt populated on fail


def test_trace_p_value_emits_one_per_pvalue() -> None:
    """A claim with two p-values → two traces."""
    claim = _claim(text="VO2max (p=0.08) and insulin (p=0.02).")
    item = _item(abstract="VO2max (p=0.08) and insulin (p=0.02).")
    traces = list(trace_p_value_in_text(claim, item))
    assert len(traces) == 2
    assert all(t.passed for t in traces)


def test_trace_p_value_no_pvalues_yields_nothing() -> None:
    claim = _claim(text="No statistical reporting in this claim.")
    item = _item(abstract="Some abstract.")
    traces = list(trace_p_value_in_text(claim, item))
    assert traces == []


# --- trace_percentage_in_text --------------------------------------------


def test_trace_percentage_pass_for_matching_percentage() -> None:
    claim = _claim(text="Mortality decreased by 30%.")
    item = _item(abstract="30% reduction in mortality observed.")
    traces = list(trace_percentage_in_text(claim, item))
    assert len(traces) == 1 and traces[0].passed is True


def test_trace_percentage_fails_when_not_in_source() -> None:
    """Claim cites 30%, source says 22%."""
    claim = _claim(text="Mortality decreased by 30%.")
    item = _item(abstract="22% reduction in mortality.")
    traces = list(trace_percentage_in_text(claim, item))
    assert len(traces) == 1 and traces[0].passed is False
    assert "30%" in traces[0].detail


def test_trace_percentage_handles_decimals() -> None:
    claim = _claim(text="Improved by 1.5%.")
    item = _item(abstract="Treatment yielded 1.5% improvement.")
    traces = list(trace_percentage_in_text(claim, item))
    assert traces and traces[0].passed is True


# --- trace_numeric_in_text (Day 9.1) --------------------------------------


def test_trace_numeric_pearl_eta_squared_unicode_middledot_pass() -> None:
    """PEARL trial regression: claim cites ηp² values in ASCII, source
    abstract uses Lancet middle-dot. Unicode normalization must let them
    trace. This is the exact case that drove rapamycin's 1/4 accept rate
    at temperature 0 — auditor was correctly flagging "untraced numeric"
    on every run."""
    claim = _claim(text="Lean tissue mass (ηp2 = 0.202) and pain (ηp2 = 0.168) improved.")
    item = _item(abstract=(
        "Lean tissue mass (ηp2 = 0·202, p = 0·013) and self-reported pain "
        "(ηp2 = 0·168, p = 0·015) improved significantly for women using "
        "10 mg rapamycin"
    ))
    traces = list(trace_numeric_in_text(claim, item))
    assert len(traces) == 2
    assert all(t.passed for t in traces)
    assert "0.202" in traces[0].detail
    assert "0.168" in traces[1].detail


def test_trace_numeric_protector_or_with_brackets_pass() -> None:
    """PROTECTOR regression: source uses bracketed OR form `odds ratio
    [OR] 0·601 [90% CI 0·391-0·922]`; claim uses naked `OR 0.601`.
    Bare-value substring fallback must catch this."""
    claim = _claim(text="OR 0.601 (90% CI 0.391-0.922) for laboratory-confirmed RTIs.")
    item = _item(abstract=(
        "treatment group (34 [19%] of 176) compared with the pooled placebo "
        "group (50 [28%] of 180; odds ratio [OR] 0·601 [90% CI 0·391-0·922]; "
        "p=0·02)"
    ))
    traces = list(trace_numeric_in_text(claim, item))
    assert traces, "OR + CI must be detected"
    assert all(t.passed for t in traces), [t.detail for t in traces]


def test_trace_numeric_fabricated_hr_fails() -> None:
    """Hostile case: claim invents `HR 5.0`; source has `HR 0.79`.
    Must fail. This is the planted-failure analogue for case 3 (inflated
    p-value), now extended to effect-size statistics."""
    claim = _claim(text="Metformin reduced mortality (HR 5.0).")
    item = _item(abstract="Metformin reduced mortality (HR 0.79; 95% CI 0.66-0.95).")
    traces = list(trace_numeric_in_text(claim, item))
    assert traces and not traces[0].passed
    assert "HR 5.0" in traces[0].detail


def test_trace_numeric_no_numerics_in_claim_yields_nothing() -> None:
    """No false positives: a claim with no detectable effect-size token
    must yield zero traces — not a synthetic 'pass' that blesses claims
    without numerics."""
    claim = _claim(text="Metformin improved overall outcomes.")
    item = _item(abstract="Metformin improved overall outcomes significantly.")
    traces = list(trace_numeric_in_text(claim, item))
    assert traces == []


def test_trace_numeric_hazard_ratio_aHR_pass() -> None:
    """Adjusted HR (aHR) is a separate alternation in the regex; verify
    it traces correctly."""
    claim = _claim(text="aHR 0.85 for cardiovascular events.")
    item = _item(abstract="adjusted HR (aHR 0.85; 95% CI 0.78-0.92) for CV events")
    traces = list(trace_numeric_in_text(claim, item))
    assert traces and traces[0].passed


def test_trace_numeric_ci_range_pass() -> None:
    """95% CI range expression must trace as a single unit."""
    claim = _claim(text="The 95% CI 0.66-0.95 excluded null.")
    item = _item(abstract="95% CI 0.66-0.95 indicated a protective effect")
    traces = list(trace_numeric_in_text(claim, item))
    assert traces and traces[0].passed


def test_trace_numeric_wired_into_trace_claim(
    metformin_pack: TopicPack,
    registry: FixtureTrialRegistryClient,
    drug_client: FixtureDrugAliasClient,
) -> None:
    """The orchestrator (`trace_claim`) must call trace_numeric_in_text —
    otherwise the new trace doesn't reach the citation_traces.json
    receipt. Discriminating test: claim has an HR, abstract has the same
    HR, expect at least one numeric_in_text trace in the output."""
    claim = _claim(
        text="Metformin reduced mortality (HR 0.79; 95% CI 0.66-0.95).",
        refs=(1,),
    )
    item = _item(
        ref=1,
        abstract="Metformin reduced mortality (HR 0.79; 95% CI 0.66-0.95) over 5 years.",
    )
    items_by_ref = {1: item}
    traces = trace_claim(
        claim, items_by_ref, metformin_pack,
        registry=registry, drug_client=drug_client,
    )
    numeric_traces = [t for t in traces if t.trace_type == "numeric_in_text"]
    assert numeric_traces, "trace_claim must emit numeric_in_text traces"
    assert all(t.passed for t in numeric_traces)


# --- trace_alias_match ----------------------------------------------------


def test_trace_alias_match_planted_case_4_glufomin(
    metformin_pack: TopicPack,
    drug_client: FixtureDrugAliasClient,
) -> None:
    """Glufomin is not in compounds/ fixture → drift caught."""
    claim = _claim(text="Glufomin reduced incident frailty by 20%.")
    traces = list(trace_alias_match(claim, metformin_pack, drug_client))
    drift = [t for t in traces if not t.passed]
    assert drift, "Glufomin should fail alias_match"
    assert "Glufomin" in drift[0].detail


def test_trace_alias_match_passes_for_known_canonical(
    metformin_pack: TopicPack,
    drug_client: FixtureDrugAliasClient,
) -> None:
    """A non-topic drug name that IS in the alias registry should pass."""
    claim = _claim(text="In a comparison with Glucophage, the trial enrolled adults.")
    traces = list(trace_alias_match(claim, metformin_pack, drug_client))
    # Glucophage is in the metformin pack alias list, so alias_match skips it
    # entirely (already validated). Test passes by emitting no failed alias trace.
    assert all(t.passed for t in traces), traces


def test_trace_alias_match_skips_pack_aliases(
    metformin_pack: TopicPack,
    drug_client: FixtureDrugAliasClient,
) -> None:
    """Topic-pack aliases are pre-validated and skipped to avoid noise."""
    claim = _claim(text="Glucophage and metformin were compared.")
    traces = list(trace_alias_match(claim, metformin_pack, drug_client))
    candidates = {t.detail.split("'")[1] for t in traces if "'" in t.detail}
    # Glucophage is a pack alias (case-insensitive); should be skipped
    assert "Glucophage" not in candidates


def test_trace_alias_match_filters_stopwords(
    metformin_pack: TopicPack,
    drug_client: FixtureDrugAliasClient,
) -> None:
    """Common false positives (Trial, Study, Older) don't fire."""
    claim = _claim(text="The Trial in Older Adults found Reduced mortality.")
    traces = list(trace_alias_match(claim, metformin_pack, drug_client))
    # All these words are in the stopword list — no alias_match traces should
    # emerge for them.
    candidates = [t for t in traces if t.trace_type == "alias_match"]
    for t in candidates:
        for noise in ("Trial", "Older", "Study", "Reduced"):
            assert noise not in t.detail, (
                f"stopword {noise!r} should not appear in alias_match trace"
            )


def test_trace_alias_match_skips_canonical_trial_names(
    metformin_pack: TopicPack,
    drug_client: FixtureDrugAliasClient,
) -> None:
    """P1.3: MASTERS, TAME, MILES, MET-PREVENT in claim prose are TRIAL
    acronyms, not drug names. Must NOT fire alias drift even though they
    look like capitalized drug-name-shape tokens."""
    claim = _claim(
        text="MASTERS demonstrated muscle blunting; TAME is in progress.",
    )
    traces = list(trace_alias_match(claim, metformin_pack, drug_client))
    drift = [t for t in traces if not t.passed]
    for t in drift:
        for trial_name in ("MASTERS", "TAME", "MILES", "PREVENT"):
            assert trial_name not in t.detail, (
                f"canonical trial token {trial_name!r} false-flagged as "
                f"drug drift: {t.detail!r}"
            )


def test_trace_alias_match_skips_met_prevent_fragments(
    metformin_pack: TopicPack,
    drug_client: FixtureDrugAliasClient,
) -> None:
    """The MET-PREVENT name has multi-word capitalized fragments. Each
    fragment ('MET' is too short for the regex; 'PREVENT' qualifies)
    should be skipped via the trial-name token set."""
    claim = _claim(text="PREVENT was completed in 2022.")
    traces = list(trace_alias_match(claim, metformin_pack, drug_client))
    drift = [t for t in traces if not t.passed]
    assert all("PREVENT" not in t.detail for t in drift), (
        f"PREVENT (fragment of MET-PREVENT) false-flagged: {[t.detail for t in drift]}"
    )


def test_trace_alias_match_lowercase_verb_does_not_enter_candidate_loop(
    metformin_pack: TopicPack,
    drug_client: FixtureDrugAliasClient,
) -> None:
    """Verb-boundary documentation: lowercase verbs that happen to share
    spelling with trial fragments ('prevent' as English verb vs. PREVENT
    fragment of MET-PREVENT) are NEVER candidates. The drug-name regex
    `\\b[A-Z][a-zA-Z]{3,}\\b` requires a capital first letter, so prose
    like 'metformin can prevent inflammation' has zero candidates → the
    trial-token skip is moot for that token. This is the boundary between
    'verb prevent' (no-op) and 'PREVENT shorthand' (skipped via trial
    token set) — both arrive at the same correct outcome via different
    paths."""
    claim = _claim(text="metformin can prevent further complications.")
    traces = list(trace_alias_match(claim, metformin_pack, drug_client))
    # No drift traces emitted because the only word that could match a
    # trial fragment is 'prevent' (lowercase) and the regex doesn't
    # consider it a candidate at all.
    assert all("prevent" not in t.detail.lower() for t in traces if not t.passed), (
        f"lowercase verb 'prevent' should never enter the candidate loop: "
        f"{[t.detail for t in traces if not t.passed]}"
    )


def test_trace_alias_match_uppercase_non_trial_word_still_flagged(
    metformin_pack: TopicPack,
    drug_client: FixtureDrugAliasClient,
) -> None:
    """Boundary documentation: the trial-fragment skip is *narrow*. A
    capitalized word that ISN'T a trial fragment (and isn't a known
    alias / stopword) still flows to the drug-alias lookup. No global
    skip just because a word starts with a capital letter.

    This proves the skip doesn't over-suppress — only words explicitly
    in `_trial_name_tokens(pack)` get the bypass. 'Glufomin' (the case 4
    planted-failure drug-drift example) starts with a capital, isn't a
    trial fragment, isn't a metformin alias, isn't a stopword → reaches
    the drug client → returns None (not in ChEMBL) → drift trace fires.

    Combined design rationale (with the fragment-skip test above): we
    accept the false-negative risk that a fake drug named after a trial
    fragment ('Prevent') would slip past, in exchange for the
    false-positive cost of flagging legitimate trial shorthand
    ('PREVENT showed lower mortality') in real prose. Trial shorthand
    is far more common than fake-drug-as-trial-fragment attacks."""
    claim = _claim(
        text="Glufomin is presented as a metformin equivalent for diabetes.",
    )
    traces = list(trace_alias_match(claim, metformin_pack, drug_client))
    drift = [t for t in traces if not t.passed]
    assert any("Glufomin" in t.detail for t in drift), (
        f"capitalized non-trial-fragment 'Glufomin' must reach drug client: "
        f"got {[t.detail for t in traces]}"
    )


# --- trace_claim orchestrator --------------------------------------------


def test_trace_claim_emits_role_match_first(
    metformin_pack: TopicPack,
    registry: FixtureTrialRegistryClient,
    drug_client: FixtureDrugAliasClient,
) -> None:
    claim = _claim()
    items = {1: _item(role="published_results", abstract="(p=0.04)")}
    traces = trace_claim(
        claim, items, metformin_pack,
        registry=registry, drug_client=drug_client,
    )
    assert traces[0].trace_type == "role_match"


def test_trace_claim_records_unresolvable_ref(
    metformin_pack: TopicPack,
    registry: FixtureTrialRegistryClient,
    drug_client: FixtureDrugAliasClient,
) -> None:
    """A claim referencing a missing ref should emit a failed trace."""
    claim = _claim(refs=(99,))
    items: dict[int, EvidenceItem] = {}  # ref 99 not present
    traces = trace_claim(
        claim, items, metformin_pack,
        registry=registry, drug_client=drug_client,
    )
    failures = [t for t in traces if not t.passed]
    assert any("not present" in t.detail for t in failures)


def test_trace_claim_e2e_planted_case_2(
    metformin_pack: TopicPack,
    registry: FixtureTrialRegistryClient,
    drug_client: FixtureDrugAliasClient,
) -> None:
    """E2E: planted fabricated NCT shows up as a failed nct_exists trace."""
    claim = _claim(text="The trial showed 30% reduction (p=0.04).")
    items = {1: _item(nct="NCT99999999",
                       abstract="30% reduction observed (p=0.04).")}
    traces = trace_claim(claim, items, metformin_pack,
                         registry=registry, drug_client=drug_client)
    nct_traces = [t for t in traces if t.trace_type == "nct_exists"]
    assert nct_traces and not nct_traces[0].passed


def test_trace_claim_e2e_planted_case_3(
    metformin_pack: TopicPack,
    registry: FixtureTrialRegistryClient,
    drug_client: FixtureDrugAliasClient,
) -> None:
    """E2E: planted inflated p-value shows up as failed p_value_in_text."""
    claim = _claim(text="Konopka reported VO2max attenuation (p<0.001).")
    items = {1: _item(abstract="Metformin attenuated VO2max (p=0.08).")}
    traces = trace_claim(claim, items, metformin_pack,
                         registry=registry, drug_client=drug_client)
    pv = [t for t in traces if t.trace_type == "p_value_in_text"]
    assert pv and not pv[0].passed


def test_trace_claim_e2e_planted_case_4(
    metformin_pack: TopicPack,
    registry: FixtureTrialRegistryClient,
    drug_client: FixtureDrugAliasClient,
) -> None:
    """E2E: planted alias drift shows up as failed alias_match."""
    claim = _claim(text="Glufomin reduced frailty.")
    items = {1: _item(abstract="Some study.")}
    traces = trace_claim(claim, items, metformin_pack,
                         registry=registry, drug_client=drug_client)
    drift = [t for t in traces if t.trace_type == "alias_match" and not t.passed]
    assert drift and "Glufomin" in drift[0].detail


# --- trace_claim_graph orchestrator --------------------------------------


def test_trace_claim_graph_runs_per_claim(
    metformin_pack: TopicPack,
    registry: FixtureTrialRegistryClient,
    drug_client: FixtureDrugAliasClient,
) -> None:
    c1 = _claim(cid="C01", text="(p=0.04)", refs=(1,))
    c2 = _claim(cid="C02", text="(p=0.10)", refs=(1,))
    graph = ClaimGraph(claims=(c1, c2), edges=(), thesis_claim_id="C01")
    items = {1: _item(abstract="results (p=0.04) and (p=0.10).")}
    traces = trace_claim_graph(graph, items, metformin_pack,
                                registry=registry, drug_client=drug_client)
    claim_ids = {t.claim_id for t in traces}
    assert claim_ids == {"C01", "C02"}


# --- summary helper -------------------------------------------------------


def test_summary_groups_by_type_and_outcome() -> None:
    from agent.schemas import CitationTrace
    traces = [
        CitationTrace(claim_id="C1", ref=1, trace_type="nct_exists",
                      passed=True, detail="x"),
        CitationTrace(claim_id="C1", ref=1, trace_type="nct_exists",
                      passed=False, detail="x"),
        CitationTrace(claim_id="C1", ref=1, trace_type="p_value_in_text",
                      passed=True, detail="x"),
    ]
    s = summary(traces)
    assert s == {
        "nct_exists:pass": 1, "nct_exists:fail": 1, "p_value_in_text:pass": 1,
    }


# --- regression: ClaimEdge isn't being used here, but import stays valid --


def test_imports_clean() -> None:
    """If this test runs, the module imports without circular issues."""
    # Re-import everything in one shot
    import agent.citation_trace  # noqa: F401
    assert True
