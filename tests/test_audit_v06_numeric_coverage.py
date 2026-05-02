"""P1 reviewer fix regression: numeric audit must cover percentages
+ p-values + ratios + sample sizes + doses + speeds — not just
percentages. A discriminating test per category."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import audit_v06_paper as audit  # noqa: E402


def test_p_value_untraceable_flagged() -> None:
    """A p-value that doesn't trace to corpus must lower the integrity
    score. Pre-fix this passed because only percentages were checked."""
    paper = "Treatment improved outcomes (p < 0.0007)."
    ok, msg = audit._check_numeric_integrity(paper, corpus_nums={"0.05"})
    # 0.0007 is not in corpus → should be flagged
    assert "0.0007" in msg or "p_value" in msg, msg


def test_hazard_ratio_untraceable_flagged() -> None:
    """An HR not in corpus must trip the gate."""
    paper = "Mortality reduced (HR = 0.123)."
    ok, msg = audit._check_numeric_integrity(paper, corpus_nums={"0.85"})
    assert "0.123" in msg or "ratio" in msg, msg


def test_sample_size_untraceable_flagged() -> None:
    """A sample-size n=N not in corpus must trip the gate."""
    paper = "The trial enrolled n=99999 participants."
    ok, msg = audit._check_numeric_integrity(paper, corpus_nums={"100"})
    assert "99999" in msg or "sample_size" in msg, msg


def test_dose_untraceable_flagged() -> None:
    """A dose value not in corpus must trip the gate."""
    paper = "Patients received 7777 mg of metformin daily."
    ok, msg = audit._check_numeric_integrity(paper, corpus_nums={"850"})
    assert "7777" in msg or "dose" in msg, msg


def test_all_traceable_passes() -> None:
    """When every numeric traces, gate passes regardless of category mix."""
    paper = (
        "Treatment improved outcomes 32% (p < 0.05). "
        "Hazard ratio HR=0.85 with n=120 patients on 850 mg/day."
    )
    corpus = {"32", "32.0", "0.05", "0.85", "120", "850"}
    ok, msg = audit._check_numeric_integrity(paper, corpus_nums=corpus)
    assert ok, msg


def test_percentage_still_filtered_for_trivial_values() -> None:
    """Percentages ≤1.0 (rounding artifacts) and ≥1000 (typos) are
    still skipped to keep the existing prose-noise filter."""
    paper = "Improvement was 0.5% modest with prevalence at 1500%."
    ok, msg = audit._check_numeric_integrity(paper, corpus_nums=set())
    # Both 0.5 and 1500 should be filtered; gate passes by vacuity.
    assert ok, msg
