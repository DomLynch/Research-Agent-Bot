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

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import run_v06_synthesis as v06  # type: ignore[import-not-found]  # noqa: E402


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
