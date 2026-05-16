"""Slice 18 regression tests — three reviewer-named polish fixes plus
the accountability-aware readiness contract.

Stdlib-only, no LLM. Covers:
  1. `_lowercase_first_letter` — joins Phase B prepended lane qualifier
     into a natural sentence ("In animal/preclinical evidence, the ..."
     not "...The...") and PRESERVES acronyms (RCT, ATP).
  2. Phase E.3 `_soften` — "We propose" → "We operationalize" preserves
     uppercase; "we propose" → "we operationalize" preserves lowercase.
  3. `_accountability_text` — researka-native vs legacy-journal-submission
     emit different prose; default is researka-native.
  4. Phase G `_phase_g_refresh_sidecars` — refreshes stale verdict
     surface state + rebuilds readiness contract item 13 from manifest
     accountability_model.

Universal — no topic-specific fixtures; uses synthetic minimal sidecars.
"""
from __future__ import annotations

import json
from pathlib import Path

from agent.journal_finalizer import (  # type: ignore[import-not-found]
    _lowercase_first_letter,
    _phase_g_refresh_sidecars,
)
from agent.methods_pack import (  # type: ignore[import-not-found]
    REQUIRED_METHODS_H3_MARKERS,
    _accountability_text,
    build_methods_pack,
    render_methods_md,
)


# ---- Fix 1: _lowercase_first_letter ---------------------------------------


def test_lowercase_first_letter_lowercases_normal_word() -> None:
    assert _lowercase_first_letter("The corpus shows ...") == "the corpus shows ..."


def test_lowercase_first_letter_preserves_acronyms() -> None:
    # RCT, ATP, MTOR — all-caps multi-char words stay capitalized.
    assert _lowercase_first_letter("RCT data suggests ...") == "RCT data suggests ..."
    assert _lowercase_first_letter("ATP levels rose.") == "ATP levels rose."


def test_lowercase_first_letter_keeps_leading_whitespace() -> None:
    assert _lowercase_first_letter("  The mice ...") == "  the mice ..."


def test_lowercase_first_letter_handles_non_alpha_start() -> None:
    assert _lowercase_first_letter("42% of ...") == "42% of ..."
    assert _lowercase_first_letter("") == ""


# ---- Fix 3: accountability-aware Methods prose ----------------------------


def test_accountability_text_default_is_researka_native() -> None:
    text = _accountability_text("")
    assert "researka_agent_certified" in text
    assert "machine-verifiable" in text
    assert "human_signoff.json" not in text


def test_accountability_text_legacy_cites_human_signoff() -> None:
    text = _accountability_text("legacy_journal_submission")
    assert "human_signoff.json" in text
    assert "AI assistance does not transfer authorship" in text


def test_accountability_text_unknown_token_falls_back_to_researka() -> None:
    text = _accountability_text("nonsense_value")
    assert "researka_agent_certified" in text


def test_methods_pack_h3_markers_no_longer_say_human_accountability() -> None:
    # Slice 18: heading was renamed; constant must match the renderer.
    assert "### Accountability" in REQUIRED_METHODS_H3_MARKERS
    assert "### Human accountability" not in REQUIRED_METHODS_H3_MARKERS


def test_methods_pack_render_matches_required_markers() -> None:
    pack = build_methods_pack(
        review_type="prisma_scr_scoping_synthesis",
        topic="example_topic",
        corpus_search_queries=("example query",),
        n_retrieved=10, n_screened=10, n_included=8, n_rejected=2,
        outcome_classes=("primary_outcome",),
        accountability_model="researka_agent_certified",
    )
    md = render_methods_md(pack, submission_id="run-0000")
    for marker in REQUIRED_METHODS_H3_MARKERS:
        assert marker in md, f"renderer missing required H3: {marker!r}"


def test_methods_pack_legacy_model_swaps_accountability_prose() -> None:
    pack_researka = build_methods_pack(
        review_type="prisma_scr_scoping_synthesis", topic="example",
        corpus_search_queries=(), n_retrieved=1, n_screened=1,
        n_included=1, n_rejected=0, outcome_classes=("x",),
        accountability_model="researka_agent_certified",
    )
    pack_legacy = build_methods_pack(
        review_type="prisma_scr_scoping_synthesis", topic="example",
        corpus_search_queries=(), n_retrieved=1, n_screened=1,
        n_included=1, n_rejected=0, outcome_classes=("x",),
        accountability_model="legacy_journal_submission",
    )
    assert "human_signoff.json" not in pack_researka.human_accountability
    assert "human_signoff.json" in pack_legacy.human_accountability


# ---- Phase G: sidecar refresh ---------------------------------------------


def _make_run(tmp_path: Path, *, surface_passed: bool,
              accountability_model: str,
              old_contract_name: str) -> Path:
    """Set up a minimal stale-sidecar run dir for Phase G tests."""
    run = tmp_path / "run"
    run.mkdir()
    (run / "full_paper.md").write_text("# Stub\n")
    (run / "manifest.json").write_text(json.dumps({
        "accountability_model": accountability_model,
    }))
    # Authoritative surface report (post-finalizer)
    (run / "full_paper.journal_surface.json").write_text(json.dumps({
        "passed": surface_passed,
        "issues": [] if surface_passed else [
            {"code": "STALE", "detail": "kept here for old verdict"},
        ],
    }))
    # Stale verdict — claims the OPPOSITE of the surface report
    (run / "full_paper.final_verdict.json").write_text(json.dumps({
        "verdict": "L4",
        "journal_surface_pass": not surface_passed,
        "journal_surface_issues": [
            "OLD_ISSUE: stale issue from earlier point in run",
        ],
    }))
    # Stale readiness contract — item 13 has the OLD shape
    (run / "pre_submit_gate.json").write_text(json.dumps({
        "result": {"passed": surface_passed, "failures": []},
        "journal_readiness_contract": [
            {"id": 1, "name": "product_tiers", "status": "pass",
             "audit": "ok", "next_action": ""},
            {"id": 13, "name": old_contract_name, "status": "not_ready",
             "audit": "old hardcoded text",
             "next_action": "old next action"},
        ],
    }))
    # Spine artifacts so researka_check passes when needed
    (run / "citation_registry.json").write_text("[]")
    (run / "artifact_consistency.json").write_text(json.dumps({
        "passed": True,
    }))
    return run


def test_phase_g_refreshes_stale_verdict_surface_state(tmp_path: Path) -> None:
    """Slice 19 update: Phase G now re-evaluates the surface gate against
    the on-disk paper FIRST, then reconciles verdict to match. The stub
    paper `# Stub\n` triggers real surface issues; verdict reconciles to
    the freshly-evaluated state, not the pre-seeded `passed=True`."""
    run = _make_run(
        tmp_path, surface_passed=True,
        accountability_model="researka_agent_certified",
        old_contract_name="accountability",
    )
    log = _phase_g_refresh_sidecars(run)
    surface = json.loads((run / "full_paper.journal_surface.json").read_text())
    verdict = json.loads((run / "full_paper.final_verdict.json").read_text())
    # After re-eval, verdict must mirror the freshly-evaluated surface.
    assert verdict["journal_surface_pass"] is bool(surface["passed"])
    assert len(verdict["journal_surface_issues"]) == len(surface["issues"])
    rules = [e.rule for e in log]
    assert "reevaluate_journal_surface_post_finalizer" in rules
    assert "reconcile_final_verdict_surface_state" in rules


def test_phase_g_rebuilds_readiness_contract_for_researka(
    tmp_path: Path,
) -> None:
    run = _make_run(
        tmp_path, surface_passed=True,
        accountability_model="researka_agent_certified",
        old_contract_name="human_signoff",  # stale legacy shape
    )
    log = _phase_g_refresh_sidecars(run)
    gate = json.loads((run / "pre_submit_gate.json").read_text())
    contract = gate["journal_readiness_contract"]
    item_13 = next(i for i in contract if i["id"] == 13)
    assert item_13["name"] == "accountability"
    assert item_13["status"] == "pass"  # spine artifacts present
    rules = [e.rule for e in log]
    # Slice 29 broadened the rule from item-13-only to a full multi-item
    # refresh (items 1/7/9/12/13). The single rule name now covers the
    # whole reconciliation pass.
    assert "reconcile_readiness_contract_items" in rules


def test_phase_g_rebuilds_readiness_contract_for_legacy(
    tmp_path: Path,
) -> None:
    run = _make_run(
        tmp_path, surface_passed=True,
        accountability_model="legacy_journal_submission",
        old_contract_name="accountability",  # stale researka shape
    )
    # legacy needs human_signoff.json ready
    (run / "human_signoff.json").write_text(json.dumps({
        "ready_to_submit": True,
    }))
    _phase_g_refresh_sidecars(run)
    gate = json.loads((run / "pre_submit_gate.json").read_text())
    item_13 = next(
        i for i in gate["journal_readiness_contract"] if i["id"] == 13
    )
    assert item_13["name"] == "human_signoff"
    assert item_13["status"] == "pass"


def test_phase_g_noop_when_already_consistent(tmp_path: Path) -> None:
    """Slice 19 update: Phase G's no-op property is now defined as
    'second call after stabilisation produces no log entries' — the
    first call re-evaluates the surface gate and reconciles verdict,
    leaving the run dir in a fixed-point state. A second invocation
    against that fixed-point state must add no log entries."""
    run = _make_run(
        tmp_path, surface_passed=True,
        accountability_model="researka_agent_certified",
        old_contract_name="accountability",
    )
    _phase_g_refresh_sidecars(run)  # first call: stabilise
    log = _phase_g_refresh_sidecars(run)  # second call: must be quiet
    assert log == []


def test_phase_g_reevaluates_surface_gate_on_post_finalizer_paper(
    tmp_path: Path,
) -> None:
    """Slice 19: pipeline writes journal_surface.json against pre-finalizer
    paper; Phase A then swaps in PRISMA-ScR Methods. Phase G must re-run
    the surface gate against the on-disk paper so the sidecar reflects
    the actual final paper state.

    Concrete scenario: pre-seed the surface sidecar as a stale `passed=True
    with 0 issues` from a hypothetical pre-finalizer evaluation. The on-
    disk paper is a stub that the gate WILL find issues with. Phase G's
    re-eval must rewrite the sidecar with the real, non-zero issue count,
    and emit a `reevaluate_journal_surface_post_finalizer` log entry."""
    run = _make_run(
        tmp_path, surface_passed=True,
        accountability_model="researka_agent_certified",
        old_contract_name="accountability",
    )
    pre_eval = json.loads((run / "full_paper.journal_surface.json").read_text())
    assert pre_eval["passed"] is True and pre_eval["issues"] == []
    log = _phase_g_refresh_sidecars(run)
    post_eval = json.loads((run / "full_paper.journal_surface.json").read_text())
    # Re-eval against `# Stub\n` produces real issues — sidecar updated.
    assert len(post_eval["issues"]) > 0
    rules = [e.rule for e in log]
    assert "reevaluate_journal_surface_post_finalizer" in rules


def test_phase_g_reeval_handles_missing_inputs_gracefully(
    tmp_path: Path,
) -> None:
    """Re-eval must fail-soft when its inputs (evidence_lanes.json,
    citation_registry.json) are missing — the gate should still run with
    empty animal_citations/citation_outcome_map fallbacks."""
    run = tmp_path / "minimal"
    run.mkdir()
    (run / "full_paper.md").write_text("# Minimal\n## Methods\nstub\n")
    (run / "manifest.json").write_text(json.dumps({
        "review_type": "prisma_scr_scoping_synthesis",
        "accountability_model": "researka_agent_certified",
    }))
    log = _phase_g_refresh_sidecars(run)
    # Surface sidecar must now exist (re-eval wrote it).
    assert (run / "full_paper.journal_surface.json").is_file()
    surface = json.loads((run / "full_paper.journal_surface.json").read_text())
    assert "issues" in surface
    # First-call delta is `new_issues - 0` so a log entry is expected.
    rules = [e.rule for e in log]
    assert "reevaluate_journal_surface_post_finalizer" in rules


def test_phase_g_refreshes_pre_submit_gate_when_surface_flips(
    tmp_path: Path,
) -> None:
    """Slice 20: when Phase G's surface re-eval flips journal_surface_pass,
    the cached pre_submit_gate.result must be recomputed so the L3/L4
    ladder responds. Universal — operates on the gate inputs dict + the
    freshly-rewritten surface sidecar.

    Direction tested: pre_submit was passing with stale `surface_passed=
    True`; the re-eval against a thin stub paper produces real surface
    issues, which must propagate to flip pre_submit's result to fail."""
    run = tmp_path / "run"
    run.mkdir()
    (run / "full_paper.md").write_text("# Stub\n## Methods\nminimal\n")
    (run / "manifest.json").write_text(json.dumps({
        "review_type": "prisma_scr_scoping_synthesis",
        "accountability_model": "researka_agent_certified",
    }))
    # Pre-seed pre_submit_gate as PASSING with stale `surface_passed=True`.
    (run / "pre_submit_gate.json").write_text(json.dumps({
        "inputs": {
            "numeric_coverage": 1.0,
            "audit_gates_passed": True,
            "journal_surface_passed": True,  # stale — re-eval will flip to False
            "citation_registry_complete": True,
            "rob_coverage": 1.0, "grade_coverage": 1.0,
            "n_tensions": 10, "n_receipts": 30,
            "unresolved_reviewer_p1_count": 0,
            "template_language_blocking": False,
        },
        "result": {"passed": True, "failures": [],
                   "warnings": [], "summary": "PASS — stale"},
    }))
    log = _phase_g_refresh_sidecars(run)
    rules = [e.rule for e in log]
    assert "refresh_pre_submit_gate_with_fresh_surface" in rules
    gate = json.loads((run / "pre_submit_gate.json").read_text())
    # Re-eval against stub paper produces surface failures → input flips
    # → pre_submit result must reflect the flip.
    assert gate["inputs"]["journal_surface_passed"] is False
    assert gate["result"]["passed"] is False
    assert "journal_surface_failed" in gate["result"]["failures"]


def test_slice26_gate_qualifier_accepts_everyday_animal_terms() -> None:
    """Slice 26: the journal-surface gate's animal-lane qualifier check
    must accept everyday prose terms ("aged mice", "in cultured cells",
    "senior dogs") — not just the formal taxonomy ("rodent / murine /
    in vivo / canine"). Senolytics audit surfaced ≥5 false-positive
    `evidence_lane` flags because the writer routinely uses "mice" and
    "dogs"; before Slice 26 those silenced no flag."""
    from agent.journal_surface_gate import _unlabeled_animal_citation_issue_messages
    paper = (
        "# Body\n\n"
        "Murray 2025 studied frailty markers. Similarly, Novais 2021 found "
        "that D+Q treatment improved physical performance in aged mice.\n"
    )
    # Without Slice 26 ("mice" missing from qualifier list), this would
    # flag Novais 2021. With Slice 26 it correctly stays silent.
    msgs = _unlabeled_animal_citation_issue_messages(paper, ["Novais 2021"])
    assert msgs == ()


def test_slice26_gate_qualifier_handles_plurals_via_word_boundary() -> None:
    """Slice 26: the regex's `s?` suffix must accept English plurals
    ("equids" → matches "equid"; "rodents" → matches "rodent"). CR
    audit caught the regression case where "obese equids" failed to
    silence the flag after switching from substring to word-boundary."""
    from agent.journal_surface_gate import _unlabeled_animal_citation_issue_messages
    paper = (
        "# Body\n\n"
        "Bamford 2019, in a model of obese equids, reported "
        "cardiometabolic improvements.\n"
    )
    msgs = _unlabeled_animal_citation_issue_messages(paper, ["Bamford 2019"])
    assert msgs == ()


def test_slice26_word_boundary_avoids_false_positive_substring_matches() -> None:
    """Slice 26: switching to word-boundary regex must NOT silence the
    gate on prose that incidentally contains short substrings like
    'rate' (was previously matching the absent 'rat' qualifier via
    pure substring search — actually a non-issue pre-Slice-26 since
    'rat' wasn't in the list, but `cat`/`dog` ARE now and could
    accidentally match 'category'/'doggedly' without the boundary)."""
    from agent.journal_surface_gate import _unlabeled_animal_citation_issue_messages
    paper = (
        "# Body\n\n"
        "Jones 2024 examined the rate of categorical adverse events in "
        "the dogmatic literature; doggedly tracking outcomes proved "
        "challenging.\n"
    )
    # Even though "rate"/"categorical"/"dogmatic"/"doggedly" each contain
    # an animal qualifier as substring, none should match at word
    # boundary. Jones 2024 must still be flagged when treated as animal.
    msgs = _unlabeled_animal_citation_issue_messages(paper, ["Jones 2024"])
    assert len(msgs) == 1
    assert "Jones 2024" in msgs[0]


def test_phase_b_patches_mixed_lane_paragraphs_post_slice27(
    tmp_path: Path,
) -> None:
    """Slice 27 (reverses Slice 23): Phase B now patches mixed-lane
    paragraphs too. The qualifier "In animal/preclinical evidence,"
    is a partial-truth statement about the citation set — it correctly
    flags the animal portion without claiming the non-animal cites are
    also animal. Leaving mixed-lane paragraphs un-qualified produces
    a worse outcome (the gate flags every unlabelled animal cite as a
    surface failure). Universal."""
    from agent.journal_finalizer import _phase_b_lane_qualifier
    run = tmp_path / "run"
    run.mkdir()
    (run / "evidence_lanes.json").write_text(json.dumps({
        "animal_citations": [
            {"citation": "Smith 2022", "paper_id": "p1"},
        ],
        "lanes": {
            "Smith 2022": "animal_preclinical",
            "Wilson 2023": "human_observational",
        },
    }))
    # Mixed-lane paragraph: cites the animal source AND a human source.
    # Slice 23 made Phase B skip this; Slice 27 makes Phase B patch it.
    paper = (
        "# Paper\n\n"
        "Some context. Smith 2022 reported a finding; Wilson 2023 confirmed it.\n"
    )
    new_text, log = _phase_b_lane_qualifier(paper, run)
    assert new_text != paper
    assert "In animal/preclinical evidence," in new_text
    assert len(log) == 1
    assert log[0].rule == "animal_preclinical_lead_in"


def test_phase_b_still_skips_paragraphs_with_existing_qualifier(
    tmp_path: Path,
) -> None:
    """Slice 27 boundary: even with the aggressive-patch reversion of
    Slice 23, Phase B must still respect an existing qualifier (avoids
    double-prepending). Universal."""
    from agent.journal_finalizer import _phase_b_lane_qualifier
    run = tmp_path / "run"
    run.mkdir()
    (run / "evidence_lanes.json").write_text(json.dumps({
        "animal_citations": [
            {"citation": "Smith 2022", "paper_id": "p1"},
        ],
        "lanes": {"Smith 2022": "animal_preclinical"},
    }))
    paper = (
        "# Paper\n\n"
        "In animal/preclinical evidence, Smith 2022 reported a finding.\n"
    )
    new_text, log = _phase_b_lane_qualifier(paper, run)
    assert new_text == paper  # already qualified — no change
    assert log == []


def test_phase_b_fires_on_exclusively_animal_lane_paragraph(
    tmp_path: Path,
) -> None:
    """Slice 23: Phase B SHOULD fire when every cited token in the
    paragraph is animal-lane. Confirms precision tightening did not
    regress the positive-trigger case. Slice 26 update: synthetic
    citation tokens MUST NOT contain animal qualifier words (the
    centralised qualifier set now includes "mouse"/"rat" — using
    those as author surnames would make the citation itself match
    the gate's qualifier regex)."""
    from agent.journal_finalizer import _phase_b_lane_qualifier
    run = tmp_path / "run"
    run.mkdir()
    (run / "evidence_lanes.json").write_text(json.dumps({
        "animal_citations": [
            {"citation": "Smith 2022", "paper_id": "p1"},
            {"citation": "Jones 2023", "paper_id": "p2"},
        ],
        "lanes": {
            "Smith 2022": "animal_preclinical",
            "Jones 2023": "animal_preclinical",
            "Wilson 2023": "human_observational",
        },
    }))
    paper = (
        "# Paper\n\n"
        "Smith 2022 showed an effect that Jones 2023 replicated.\n"
    )
    new_text, log = _phase_b_lane_qualifier(paper, run)
    assert new_text != paper
    assert "In animal/preclinical evidence," in new_text
    assert len(log) == 1
    assert log[0].rule == "animal_preclinical_lead_in"


def test_slice31_downshift_to_thin_corpus_brief_on_few_receipts() -> None:
    """Slice 31: when n_receipts < THIN_CORPUS_MIN_RECEIPTS the
    declared review_type is downshifted to `thin_corpus_brief`,
    regardless of what the topic pack declared. Universal."""
    from agent.review_type import downshift_review_type_for_thin_corpus
    assert downshift_review_type_for_thin_corpus(
        "systematic_review", n_receipts=2, n_tensions=5,
    ) == "thin_corpus_brief"


def test_slice31_downshift_on_zero_tensions() -> None:
    """Slice 31: n_tensions==0 triggers downshift even when receipt
    count is large (a paper with many receipts but no cross-claim
    tensions is still a thin-evidence artifact)."""
    from agent.review_type import downshift_review_type_for_thin_corpus
    assert downshift_review_type_for_thin_corpus(
        "prisma_scr_scoping_synthesis", n_receipts=40, n_tensions=0,
    ) == "thin_corpus_brief"


def test_slice31_no_downshift_when_corpus_is_dense() -> None:
    """Slice 31 boundary: when both receipts and tensions clear the
    thresholds the declared review_type is preserved as-is."""
    from agent.review_type import downshift_review_type_for_thin_corpus
    assert downshift_review_type_for_thin_corpus(
        "systematic_review", n_receipts=30, n_tensions=5,
    ) == "systematic_review"
    # None / empty falls back to default, not thin-corpus
    assert downshift_review_type_for_thin_corpus(
        None, n_receipts=30, n_tensions=5,
    ) == "prisma_scr_scoping_synthesis"


def test_slice31_thin_corpus_brief_has_display_label() -> None:
    """Slice 31: the new review_type token must render with a journal-
    conventional display label, like the other 7 types."""
    from agent.review_type import display_label, REVIEW_TYPES
    assert "thin_corpus_brief" in REVIEW_TYPES
    assert display_label("thin_corpus_brief") == "Thin-corpus evidence brief"


def test_phase_i_splits_concatenated_h3_h2_heading_line() -> None:
    """Slice 30: Phase I splits a line like `### Sub Title## Next H2`
    into two heading lines separated by a blank. Universal Markdown
    structural fix — surfaced by the GLP-1 run where the writer/render
    glued `### Longevity Outcomes## Cross-Domain Synthesis` on one line."""
    from agent.journal_finalizer import _phase_i_split_concatenated_headings
    text = (
        "# Paper\n\n"
        "Some body.\n"
        "### Longevity Outcomes## Cross-Domain Synthesis\n\n"
        "Next paragraph.\n"
    )
    new_text, log = _phase_i_split_concatenated_headings(text)
    assert "### Longevity Outcomes\n\n## Cross-Domain Synthesis" in new_text
    assert log and log[0].n_changes == 1
    assert log[0].rule == "insert_blank_line_between_headings"


def test_phase_i_noop_when_headings_already_separated() -> None:
    """Slice 30: clean Markdown with blank-line separators must pass
    through untouched (Phase I is a structural repair, not a reformat)."""
    from agent.journal_finalizer import _phase_i_split_concatenated_headings
    text = (
        "# Paper\n\n"
        "### Sub A\n\n"
        "Body.\n\n"
        "## Next Section\n\n"
    )
    new_text, log = _phase_i_split_concatenated_headings(text)
    assert new_text == text
    assert log == []


def test_phase_h_substitutes_snake_case_slug_with_display_form(
    tmp_path: Path,
) -> None:
    """Slice 28: Phase H substitutes snake_case slug with display form."""
    from agent.journal_finalizer import _phase_h_topic_slug_normalise
    run = tmp_path / "r"
    run.mkdir()
    (run / "manifest.json").write_text(json.dumps({"topic": "vitamin_d"}))
    paper = "# Body\n\nvitamin_d trials report mixed outcomes. The vitamin_d field is dense.\n"
    new_text, log = _phase_h_topic_slug_normalise(paper, run)
    assert "vitamin_d" not in new_text
    assert "vitamin D" in new_text
    assert len(log) == 1 and log[0].n_changes == 2


def test_phase_h_preserves_backtick_spans(tmp_path: Path) -> None:
    """Slice 28 boundary: file refs inside `` survive."""
    from agent.journal_finalizer import _phase_h_topic_slug_normalise
    run = tmp_path / "r"
    run.mkdir()
    (run / "manifest.json").write_text(json.dumps({"topic": "glp1"}))
    paper = "# Body\n\nThe glp1 corpus loaded from `topic_packs/glp1.toml`.\n"
    new_text, log = _phase_h_topic_slug_normalise(paper, run)
    assert "GLP-1 corpus" in new_text
    assert "`topic_packs/glp1.toml`" in new_text


def test_phase_h_skips_plain_english_slugs(tmp_path: Path) -> None:
    """Slice 28 precision: senolytics/rapamycin slugs skip — substituting
    would damage valid English prose. Gated by _PUBLIC_SLUG_RE.fullmatch."""
    from agent.journal_finalizer import _phase_h_topic_slug_normalise
    run = tmp_path / "r"
    run.mkdir()
    (run / "manifest.json").write_text(json.dumps({"topic": "senolytics"}))
    paper = "# Body\n\nTwo senolytics trials reported. The senolytics field remains preclinical-heavy.\n"
    new_text, log = _phase_h_topic_slug_normalise(paper, run)
    assert new_text == paper
    assert log == []


def test_phase_g_missing_sidecars_is_safe(tmp_path: Path) -> None:
    run = tmp_path / "empty_run"
    run.mkdir()
    # No sidecars exist — must not raise.
    log = _phase_g_refresh_sidecars(run)
    assert log == []


def test_slice35_render_full_paper_thin_brief_skips_long_form_sections() -> None:
    """Slice 35 supersedes Phase J: writer skips generating Introduction,
    Background, Cross-Domain, Discussion, novel_framework when called with
    review_type='thin_corpus_brief'. Verified by checking the section-order
    constant — no LLM call needed. Universal — any thin-corpus run."""
    from agent.paper_writer import _THIN_BRIEF_SECTION_ORDER, _FULL_PAPER_SECTION_ORDER
    skipped = set(_FULL_PAPER_SECTION_ORDER) - set(_THIN_BRIEF_SECTION_ORDER)
    assert skipped == {"introduction", "background", "inferential_bridge", "cross_domain_synthesis", "novel_framework", "discussion"}
    assert set(_THIN_BRIEF_SECTION_ORDER) == {"abstract", "quantitative_results_table", "methods", "results", "limitations_full", "conclusion", "references_full"}


def test_phase_k_routes_immune_paragraph_to_immune_outcomes(tmp_path: Path) -> None:
    """Slice 33: paragraph cite-majority is immune → moves from ###
    Cardiometabolic Outcomes to ### Immune Outcomes. Universal — uses
    receipt outcome_class + citation registry. Surfaced in glp1 run."""
    from agent.journal_finalizer import _phase_k_route_outcome_paragraphs
    run = tmp_path / "r"
    run.mkdir()
    (run / "manifest.json").write_text(json.dumps({"receipts": [
        {"receipt_id": "p1", "outcome_class": "cardiometabolic"},
        {"receipt_id": "p2", "outcome_class": "immune"},
        {"receipt_id": "p3", "outcome_class": "immune"},
    ]}))
    (run / "citation_registry.json").write_text(json.dumps({
        "p1": {"body_citation": "Smith 2022"},
        "p2": {"body_citation": "Jones 2023"},
        "p3": {"body_citation": "Lee 2024"},
    }))
    text = (
        "## Results\n\n"
        "### Cardiometabolic Outcomes\n\n"
        "Smith 2022 reports weight loss and glycemic improvement.\n\n"
        "Jones 2023 and Lee 2024 found null immune-system effects across the corpus.\n\n"
        "### Immune Outcomes\n\n"
        "Placeholder.\n\n"
        "## Discussion\n"
    )
    new_text, log = _phase_k_route_outcome_paragraphs(text, run)
    # The immune paragraph (Jones 2023, Lee 2024) should now live under Immune Outcomes
    immune_idx = new_text.index("### Immune Outcomes")
    cardio_idx = new_text.index("### Cardiometabolic Outcomes")
    assert new_text.index("Jones 2023 and Lee 2024") > immune_idx
    assert new_text.index("Smith 2022 reports") > cardio_idx
    assert new_text.index("Smith 2022 reports") < immune_idx
    assert log and log[0].n_changes == 1
    assert log[0].rule == "route_paragraph_by_citation_class"


def test_phase_k_noop_when_no_misclassified_paragraphs(tmp_path: Path) -> None:
    """Slice 33: paragraphs already in correct sections pass through untouched."""
    from agent.journal_finalizer import _phase_k_route_outcome_paragraphs
    run = tmp_path / "r"
    run.mkdir()
    (run / "manifest.json").write_text(json.dumps({"receipts": [
        {"receipt_id": "p1", "outcome_class": "cardiometabolic"},
        {"receipt_id": "p2", "outcome_class": "immune"},
    ]}))
    (run / "citation_registry.json").write_text(json.dumps({
        "p1": {"body_citation": "Smith 2022"},
        "p2": {"body_citation": "Jones 2023"},
    }))
    text = (
        "## Results\n\n"
        "### Cardiometabolic Outcomes\n\n"
        "Smith 2022 reports weight loss.\n\n"
        "### Immune Outcomes\n\n"
        "Jones 2023 found null effects.\n\n"
        "## Discussion\n"
    )
    new_text, log = _phase_k_route_outcome_paragraphs(text, run)
    assert log == []


def test_phase_k_noop_when_no_results_section(tmp_path: Path) -> None:
    """Slice 33: safe when Results section absent (e.g. Evidence Brief)."""
    from agent.journal_finalizer import _phase_k_route_outcome_paragraphs
    run = tmp_path / "r"
    run.mkdir()
    (run / "manifest.json").write_text(json.dumps({"receipts": []}))
    (run / "citation_registry.json").write_text(json.dumps({}))
    text = "## Abstract\nA.\n\n## Methods\nM.\n"
    new_text, log = _phase_k_route_outcome_paragraphs(text, run)
    assert new_text == text
    assert log == []
