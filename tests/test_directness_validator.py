"""Directness validator: a primary randomized trial can never be coded
directness='review'.

Reviewer feedback (Fasting Regimens paper): Monda 2026 — titled "… A 12-Month
Randomized Trial in Adults with Obesity", the corpus's only human RCT — was
coded directness=review/tier=B2. That mis-code zeroed the paper's
'direct interventional' count (false "0 direct sources" headline) and
manufactured eight spurious Monda-vs-X 'tensions'. The fix reads RCT signals
from the title/study_design and exempts primary RCTs from the partial-only
downgrade. Meta-analyses *of* RCTs stay reviews. Universal — no topic terms.
"""
from __future__ import annotations

import json
import sys
import pytest
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import run_v06_synthesis as v06  # type: ignore[import-not-found]  # noqa: E402


@pytest.mark.parametrize("target", ["resistance_training", "aerobic_exercise", "metformin"])
def test_shared_target_is_not_the_randomized_contrast(monkeypatch, target):
    monkeypatch.setattr(v06, "_ACTIVE_TOPIC", target)
    monkeypatch.setattr(v06, "_TOPIC_PACK", None)
    label = target.replace("_", " ")
    meta = {"title": "Adjunct supplementation: a randomized controlled trial", "abstract": (
        f"Both groups received the same {label} intervention. "
        "Participants were randomized to supplement or placebo."
    )}
    assert v06._classify_paper_tier("anonymous", 5, meta) == ("A1", "indirect")
    meta["abstract"] = f"Participants were randomized to {label} or placebo. Both groups received the same dietary advice."
    assert v06._classify_paper_tier("anonymous", 5, meta) == ("A1", "direct")
    meta["abstract"] = f"Both groups received dietary advice. One group received {label}."
    assert v06._classify_paper_tier("anonymous", 5, meta) == ("A1", "direct")


def test_explicit_combination_comparison_does_not_isolate_single_ingredient(monkeypatch) -> None:
    monkeypatch.setattr(v06, "_ACTIVE_TOPIC", "resveratrol")
    title = "Combined supplementation with Curcumin and Resveratrol: a randomized trial in patients"
    abstract = "Patients were randomly assigned to two groups. The control group treated with placebo (Group B)."
    meta = {"title": title, "abstract": abstract}
    assert v06._classify_paper_tier("example", 4, meta) == ("A1", "indirect")
    for adjusted in (
        abstract.replace("placebo (Group B)", "placebo plus curcumin"),
        abstract + " Both groups received curcumin.",
        abstract.replace("two groups", "a factorial design"),
    ):
        assert not v06.unisolated_combination(title, adjusted, "resveratrol")
    assert not v06.unisolated_combination(title, abstract, "curcumin_and_resveratrol")
    assert not v06.unisolated_combination("A randomized resveratrol trial", abstract, "resveratrol")


def test_multi_ingredient_juice_placebo_does_not_establish_ingredient_effect() -> None:
    title = "A multi-ingredient nutrition supplement intervention: a randomised trial"
    abstract = "A between-subjects factor of group (placebo, intervention) was used. The placebo contained juice only."
    assert v06.unisolated_combination(title, abstract, "resveratrol")


def test_is_randomized_trial_detects_primary_rct_from_title() -> None:
    monda = {"title": "Metabolic and Orexin-A Responses to Ketogenic Diet and "
                      "Intermittent Fasting: A 12-Month Randomized Trial in "
                      "Adults with Obesity"}
    assert v06._is_randomized_trial(monda) is True
    # study_design field alone is enough
    assert v06._is_randomized_trial({"title": "Effect of TRE", "study_design": "RCT"}) is True
    assert v06._is_randomized_trial({"title": "A randomised controlled trial of ADF"}) is True


def test_is_randomized_trial_excludes_meta_analyses_and_non_trials() -> None:
    # a review/meta-analysis *of* randomized trials is NOT a primary trial
    assert v06._is_randomized_trial(
        {"title": "Intermittent fasting: a systematic review and meta-analysis "
                  "of randomized controlled trials"}
    ) is False
    assert v06._is_randomized_trial(
        {"title": "A meta‐analysis of randomized controlled trials"}
    ) is False
    assert v06._is_randomized_trial(
        {"title": "A randomized controlled trial: study protocol"}
    ) is False
    assert v06._is_randomized_trial({"title": "A prospective cohort study of fasting"}) is False
    assert v06._is_randomized_trial({"title": "Mechanisms of ketone bodies in mice"}) is False


def test_classify_paper_tier_codes_title_only_rct_as_direct() -> None:
    """A title-only RCT (blank study_design) must classify A1/direct, not fall
    through to review — the path that mislabelled Monda."""
    tier, directness = v06._classify_paper_tier(
        "DOI_10_3390_nu18020238_monda_2026",
        n_claims=8,
        paper_meta={"title": "… A 12-Month Randomized Trial in Adults with Obesity"},
    )
    assert (tier, directness) == ("A1", "direct")


def test_classify_paper_tier_keeps_meta_analysis_out_of_direct() -> None:
    tier, directness = v06._classify_paper_tier(
        "PMC_meta",
        n_claims=5,
        paper_meta={"title": "Fasting and longevity: a systematic review and "
                            "meta-analysis of randomized controlled trials"},
    )
    assert directness != "direct"


def test_canonical_rct_hint_does_not_override_source_protocol(monkeypatch) -> None:
    monkeypatch.setattr(v06, "_TOPIC_PACK", SimpleNamespace(canonical_rct_paper_ids=("design",)))
    meta = {
        "title": "Clinical Evaluation of Effects of Chronic Resveratrol Supplementation on "
                 "Cerebrovascular Function, Cognition, Mood, Physical Function and General "
                 "Well-Being in Postmenopausal Women--Rationale and Study Design",
        "sections": {"abstract": "This methodological paper presents both a scientific "
                     "rationale and a methodological approach. A clinical trial was designed "
                     "to test this hypothesis."},
    }
    assert v06._classify_paper_tier("design", 1, meta) == ("D1", "protocol")
    assert v06._classify_paper_tier("design", 1, {}) == ("A1", "direct")


def test_off_topic_rct_is_not_admitted_as_direct_receipt(tmp_path: Path, monkeypatch) -> None:
    topic = "therapeutic_plasma_exchange"
    root = tmp_path / topic
    parsed, claims = root / "parsed", root / "quant_claims"
    parsed.mkdir(parents=True)
    claims.mkdir()
    records = {
        "PMC1_tpe": "Therapeutic plasma exchange randomized controlled trial",
        "PMC2_web": "Cost-utility analysis of a web-based interactive patient education platform",
    }
    (root / "_extract_report.json").write_text(json.dumps({"active_paper_ids": list(records)}))
    for paper_id, title in records.items():
        (parsed / f"{paper_id}.paper_sections.json").write_text(json.dumps({
            "paper_id": paper_id, "title": title, "abstract": title,
        }))
        (claims / f"{paper_id}.quant_claims.json").write_text(json.dumps({
            "paper_id": paper_id,
            "claims": [{
                "binding_confidence": "high", "claim_type": "effect_size",
                "arm": "therapeutic plasma exchange" if paper_id == "PMC1_tpe" else "web platform",
                "endpoint": "clinical response", "direction": "increase",
            }],
        }))
    v06._set_topic("therapeutic_plasma_exchange")
    monkeypatch.setattr(v06, "QUANT_DIR", claims)
    monkeypatch.setattr(v06, "PARSED_DIR", parsed)
    monkeypatch.setattr(v06, "_TOPIC_PACK", SimpleNamespace(
        active_arm_synonyms=frozenset({"therapeutic plasma exchange"}),
        placebo_arm_synonyms=frozenset({"control"}),
        canonical_rct_paper_ids=frozenset(),
        endpoint_polarity={},
    ))

    receipts = v06.build_receipts_from_quant_claims(topic)
    titles = {r.source_title or "": (r.evidence_tier, r.directness) for r in receipts}

    assert "Cost-utility analysis of a web-based interactive patient education platform" not in " ".join(titles)
    assert any("therapeutic plasma exchange" in title.lower() for title in titles)
