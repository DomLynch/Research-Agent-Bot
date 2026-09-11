"""#4 — Relative corpus population-coherence gate.

Reviewer feedback (resveratrol_metabolism_effects): retrieval pulled
arctic-fox testosterone (Limin 2026, the SOLE source for the entire
"Dosing and Pharmacokinetics" class), broiler chickens (Fu 2026),
bovine cow follicles (Chen 2026), and mouse skin into ONE human-aging
synthesis. No stage compared a source's study population against the
corpus's dominant population.

Fix: `evidence_taxonomy.population_of` classifies a source's population
from free text (human/animal/unknown), and a RELATIVE, self-calibrating
gate in run_v06 drops off-population animal background receipts only when
the high-confidence core is clearly human-dominant. Universal — no topic
words, no per-domain rule; an animal-dominant corpus keeps its sources.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import evidence_taxonomy as tax  # type: ignore[import-not-found]  # noqa: E402
import run_v06_synthesis as v06  # type: ignore[import-not-found]  # noqa: E402
from agent.synthesis_schemas import ReceiptSummary  # noqa: E402


# --------------------------- population_of --------------------------------


def test_population_of_flags_the_real_offenders_as_animal() -> None:
    for text in (
        "testicular steroidogenesis in male arctic foxes (Vulpes lagopus)",
        "AA Broiler chickens fed resveratrol over 42 days",
        "resveratrol on bovine cumulus-oocyte complexes (cow follicles)",
        "topical resveratrol on mouse skin photoaging",
        "C. elegans lifespan extension assay",
    ):
        assert tax.population_of(text) == "animal", text


def test_population_of_recognises_human_studies() -> None:
    for text in (
        "resveratrol supplementation in older adults: a randomized trial",
        "effect on HbA1c in patients with type 2 diabetes",
        "pharmacokinetics in healthy men and women",
        "a cohort of community-dwelling participants",
    ):
        assert tax.population_of(text) == "human", text


def test_population_of_word_boundary_avoids_false_animal_hits() -> None:
    # bare animal substrings inside ordinary words must NOT fire.
    for text in (
        "a comprehensive literature review of the pathway",  # "rat" in literature
        "mechanistic study of SIRT1 activation",
        "co-workers in an occupational setting",  # "cow" in co-workers
    ):
        assert tax.population_of(text) != "animal", text


def test_population_of_human_wins_translational_ties() -> None:
    # A "mouse model of human disease" paper stays human → never pruned.
    text = "a mouse model of human metabolic disease validated in patients"
    assert tax.population_of(text) == "human"


def test_population_of_unknown_when_no_population_marker() -> None:
    assert tax.population_of("") == "unknown"
    assert tax.population_of("an in-silico docking analysis") == "unknown"


# --------------------- _enforce_population_coherence ----------------------


def _r(rid: str, *, tier: str, directness: str, n: int = 5) -> ReceiptSummary:
    return ReceiptSummary(
        receipt_id=rid, receipt_path=f"/tmp/{rid}", topic="t",
        thesis_text="", spar_verdict="accept_clean", n_claims=n,
        n_failed_traces=0, canonical_trial_id=None, evidence_tier=tier,
        directness=directness, outcome_class="metabolic_health",
        effect_direction="positive", p_values=(), population_summary="",
    )


def _human_core(k: int) -> list[tuple[ReceiptSummary, str]]:
    return [(_r(f"H{i}", tier="A1", directness="direct"), "human") for i in range(k)]


def test_human_dominant_corpus_prunes_animal_background() -> None:
    typed = _human_core(12)
    typed += [(_r("A1x", tier="C1", directness="mechanistic"), "animal"),
              (_r("A2x", tier="B2", directness="review"), "animal")]
    typed += [(_r("U1", tier="B2", directness="review"), "unknown")]  # NOT pruned
    high = {f"H{i}" for i in range(12)}
    kept = {r.receipt_id for r in v06._enforce_population_coherence(typed, high)}
    assert "A1x" not in kept and "A2x" not in kept  # animal background dropped
    assert "U1" in kept  # only positively-animal is pruned, never "unknown"
    assert len([k for k in kept if k.startswith("H")]) == 12


def test_interventional_grade_animal_is_never_pruned() -> None:
    typed = _human_core(12)
    # An animal source that is somehow interventional-grade (A1/direct) is
    # exempt — the gate only drops off-population *background*.
    typed += [(_r("AINT", tier="A1", directness="direct"), "animal"),
              (_r("ABG", tier="C1", directness="mechanistic"), "animal")]
    high = {f"H{i}" for i in range(12)}
    kept = {r.receipt_id for r in v06._enforce_population_coherence(typed, high)}
    assert "AINT" in kept and "ABG" not in kept


def test_animal_dominant_corpus_is_left_intact() -> None:
    # A veterinary / model-organism topic: core is animal, so the gate
    # never activates (self-calibrating, no denylist).
    typed = [(_r(f"M{i}", tier="C1", directness="mechanistic"), "animal")
             for i in range(14)]
    typed += [(_r("H0", tier="A1", directness="direct"), "human")]
    high = {f"M{i}" for i in range(14)}
    kept = {r.receipt_id for r in v06._enforce_population_coherence(typed, high)}
    assert len(kept) == len(typed)  # nothing pruned


def test_tie_core_does_not_activate() -> None:
    typed = _human_core(3)
    typed += [(_r(f"M{i}", tier="C1", directness="mechanistic"), "animal")
              for i in range(3)]  # core animal == core human → tie
    typed += [(_r(f"P{i}", tier="B2", directness="review"), "unknown")
              for i in range(7)]
    high = {f"H{i}" for i in range(3)} | {f"M{i}" for i in range(3)}
    kept = {r.receipt_id for r in v06._enforce_population_coherence(typed, high)}
    assert len(kept) == len(typed)  # tie → fail-open


def test_small_corpus_below_floor_is_untouched() -> None:
    typed = _human_core(5)
    typed += [(_r("A0", tier="C1", directness="mechanistic"), "animal")]
    high = {f"H{i}" for i in range(5)}
    kept = {r.receipt_id for r in v06._enforce_population_coherence(typed, high)}
    assert "A0" in kept  # below floor → never prune


def test_floor_guard_blocks_a_starving_prune() -> None:
    # Human core activates the gate, but pruning the 10 animal background
    # would drop the corpus below the floor → keep everything.
    typed = _human_core(3)
    typed += [(_r(f"A{i}", tier="C1", directness="mechanistic"), "animal")
              for i in range(10)]
    high = {f"H{i}" for i in range(3)}
    kept = {r.receipt_id for r in v06._enforce_population_coherence(typed, high)}
    assert len(kept) == len(typed)  # would starve → fail-open


# ------------------------- end-to-end wiring ------------------------------


def _seed(root: Path, pid: str, *, title: str, species: str,
          design: str | None, endpoint: str | None) -> None:
    (root / "parsed").mkdir(parents=True, exist_ok=True)
    (root / "quant_claims").mkdir(parents=True, exist_ok=True)
    meta = {"paper_id": pid, "title": title, "abstract": title,
            "species": species}
    if design:
        meta["study_design"] = design
    if endpoint:
        meta["endpoint_kind"] = endpoint
    (root / "parsed" / f"{pid}.paper_sections.json").write_text(json.dumps(meta))
    (root / "quant_claims" / f"{pid}.quant_claims.json").write_text(json.dumps({
        "paper_id": pid,
        "claims": [{"binding_confidence": "high", "claim_type": "effect_size",
                    "endpoint": "grip strength", "raw_text": "creatine improved by 10%",
                    "sentence": title}],
    }))


def test_build_receipts_prunes_offpopulation_animal_end_to_end(tmp_path: Path) -> None:
    root = tmp_path / "creatine"
    pids: list[str] = []
    for i in range(12):
        pid = f"PMC{1000 + i}_human_rct"
        _seed(root, pid, title=f"Creatine improves grip strength in older adults (study {i})",
              species="older adults", design="randomized controlled trial",
              endpoint="clinical")
        pids.append(pid)
    animal_pid = "PMC2000_broiler"
    _seed(root, animal_pid, title="Creatine supplementation in broiler chickens",
          species="broiler chickens", design=None, endpoint=None)
    pids.append(animal_pid)
    (root / "_extract_report.json").write_text(json.dumps({"active_paper_ids": pids}))

    import importlib
    mod = importlib.import_module("scripts.run_v06_synthesis")
    mod._set_topic("creatine")
    setattr(mod, "QUANT_DIR", root / "quant_claims")
    setattr(mod, "PARSED_DIR", root / "parsed")
    setattr(mod, "_TOPIC_PACK", None)

    ids = {r.receipt_id for r in mod.build_receipts_from_quant_claims(topic="creatine")}
    assert animal_pid not in ids, "broiler-chicken receipt must be pruned"
    assert len([i for i in ids if i.endswith("_human_rct")]) == 12
