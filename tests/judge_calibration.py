"""Judge calibration test — VPS ONLY. Requires live MiMo API.

Run manually on the VPS:
    cd /opt/research-agent-bot && .venv/bin/python -m pytest tests/judge_calibration.py -v

Compares MiMo judge ratings against human expert ratings on calibrated drafts.
Pass condition: weighted Cohen's kappa >= 0.60 on each axis.
Skips when MIMO_API_KEY is unset.
"""
from __future__ import annotations

import os
import pytest

from tests.golden.harness import judge_draft, weighted_kappa, _JUDGE_AXES

# ---------------------------------------------------------------------------
# Calibrated sample drafts with human expert ratings
# ---------------------------------------------------------------------------

_SAMPLES: list[dict] = [
    {
        "id": "good_draft",
        # Should score: coherence=5, accuracy=5, readability=5, source_quality=5
        "human": dict(zip(_JUDGE_AXES, (5, 5, 5, 5))),
        "draft": """# Rapamycin and Aging: A Comprehensive Review

## Introduction
Rapamycin (sirolimus) is an mTOR inhibitor originally developed as an immunosuppressant.
Emerging evidence from multiple preclinical and clinical studies suggests it may have
significant geroprotective properties. This review summarizes the current state of
evidence from animal models and human trials.

## Key Findings
- Rapamycin extends lifespan in mice by 9-14% across multiple independent studies
  (Harrison et al., 2009; Miller et al., 2014).
- The PEARL trial (NCT04488601) demonstrated improved healthspan biomarkers in 200+
  older adults over 12 months of intermittent dosing.
- mTOR inhibition activates autophagy, reduces cellular senescence, and improves
  mitochondrial function in preclinical models (Lamming et al., 2013).
- A meta-analysis of 14 murine studies found a median lifespan extension of 12%
  (p < 0.001).

## Safety Profile
Long-term use carries risks of immunosuppression and metabolic changes. Intermittent
dosing protocols are being explored to minimize side effects while preserving benefits.
The PEARL trial reported no serious adverse events with 5mg weekly dosing.

## Conclusion
Rapamycin represents the most promising pharmacological intervention for aging currently
under investigation, with multiple Phase II trials ongoing. The consistency of preclinical
findings across species warrants continued investment in human longevity trials.
""",
    },
    {
        "id": "mediocre_draft",
        # Should score: coherence=3, accuracy=3, readability=3, source_quality=1
        "human": dict(zip(_JUDGE_AXES, (3, 3, 3, 1))),
        "draft": """# Metformin and Aging

Metformin is a diabetes drug. Some studies suggest it might help with aging. There are
clinical trials looking at this. The TAME trial is the most well-known one. Metformin
works by activating AMPK and inhibiting mTOR. It may reduce inflammation too.

More research is needed to understand the full effects. Some people think it could be
helpful but there are also concerns about side effects in non-diabetic populations.
The drug is cheap and widely available which makes it attractive for longevity research.

Overall, metformin is interesting but we need more data before we can say anything
definitive about its role in aging.
""",
    },
    {
        "id": "poor_draft",
        # Should score: coherence=1, accuracy=1, readability=1, source_quality=1
        "human": dict(zip(_JUDGE_AXES, (1, 1, 1, 1))),
        "draft": """aging is bad drugs might help rapamycin and metformin are drugs that might help with aging
the body gets old when you age and drugs can fix that maybe some researchers looked into
this but not sure what they found there might be clinical trials somewhere and also
nad stuff works too senolytics kill old cells or something and fasting helps everyone
do it nmn is the best supplement ever made proven science trust me on this one guys
""",
    },
    {
        "id": "high_structure_low_sources",
        # Should score: coherence=5, accuracy=3, readability=4, source_quality=1
        "human": dict(zip(_JUDGE_AXES, (5, 3, 4, 1))),
        "draft": """# The Promise of Senolytic Therapies

## Background
Cellular senescence is a hallmark of aging. Senescent cells accumulate in tissues and
secrete pro-inflammatory factors that drive age-related dysfunction.

## Potential Approaches
Researchers have identified several drug candidates that selectively eliminate senescent
cells. Dasatinib combined with quercetin is the most studied combination. Fisetin, a
natural flavonoid, also shows senolytic activity in preclinical models. Navitoclax
targets BCL-2 family proteins in senescent cells.

## Challenges
Selectivity remains a concern. Off-target effects could damage healthy cells. The
optimal dosing schedule is unknown. Long-term safety data in humans is minimal.
Biomarkers for senescent cell burden are still being validated.

## Conclusion
Senolytic therapy could transform geriatric medicine, but significant research gaps
remain before clinical translation becomes viable.
""",
    },
]


@pytest.mark.skipif(
    not os.getenv("MIMO_API_KEY", "").strip(),
    reason="MIMO_API_KEY not set — calibration requires live MiMo",
)
@pytest.mark.parametrize("sample", _SAMPLES, ids=[s["id"] for s in _SAMPLES])
def test_judge_rates_sample(sample: dict):
    """Verify MiMo judge returns valid scores for each sample draft."""
    scores = judge_draft(sample["draft"])
    for axis in _JUDGE_AXES:
        assert axis in scores, f"Missing axis: {axis}"
        assert 1 <= scores[axis] <= 5, f"Score out of range on {axis}: {scores[axis]}"


@pytest.mark.skipif(
    not os.getenv("MIMO_API_KEY", "").strip(),
    reason="MIMO_API_KEY not set — calibration requires live MiMo",
)
def test_judge_calibration_kappa():
    """Weighted Cohen's kappa >= 0.60 on each axis between human and MiMo judge."""
    human_scores: dict[str, list[int]] = {ax: [] for ax in _JUDGE_AXES}
    judge_scores: dict[str, list[int]] = {ax: [] for ax in _JUDGE_AXES}

    for sample in _SAMPLES:
        scores = judge_draft(sample["draft"])
        for ax in _JUDGE_AXES:
            human_scores[ax].append(sample["human"][ax])
            judge_scores[ax].append(scores[ax])

    failing_axes: list[str] = []
    kappa_results: dict[str, float] = {}
    for ax in _JUDGE_AXES:
        k = weighted_kappa(human_scores[ax], judge_scores[ax])
        kappa_results[ax] = round(k, 3)
        if k < 0.60:
            failing_axes.append(ax)

    print(f"\nCalibration results: {kappa_results}")
    if failing_axes:
        pytest.fail(
            f"Kappa below 0.60 on axes: {failing_axes}. "
            f"Results: {kappa_results}. Consider re-calibrating the judge rubric."
        )
