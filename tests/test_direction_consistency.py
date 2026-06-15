"""Tests for the prose-vs-receipt direction overclaim detector
(scripts/direction_consistency.py). Universal: patterns are generic English,
directions read from receipt metadata only — no topic/domain tokens."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import direction_consistency as dc  # type: ignore[import-not-found]  # noqa: E402


_MANIFEST = {
    "receipts": [
        {"receipt_id": "A 2022", "outcome_class": "cardiometabolic", "effect_direction": "positive"},
        {"receipt_id": "B 2015", "outcome_class": "cardiometabolic", "effect_direction": "null"},
    ],
}


def _paper(results_body: str) -> str:
    return (
        "## Results\n\n"
        f"### Cardiometabolic Outcomes\n\n{results_body}\n\n"
        "### Other Outcomes\n\nUnrelated.\n"
    )


def test_all_positive_overclaim_flagged_when_class_has_null() -> None:
    """'positive ... for both' while the class carries a null receipt."""
    paper = _paper("The source-traced numerics support a positive direction of effect for both pieces of evidence.")
    out = dc.outcome_prose_direction_mismatches(paper, _MANIFEST)
    assert any(m["claim"] == "all_positive" and m["outcome"] == "cardiometabolic" for m in out), out


def test_no_null_or_negative_overclaim_flagged() -> None:
    """'No source ... reported a null or negative effect' is false here."""
    paper = _paper("No source in this outcome class reported a null or negative effect.")
    out = dc.outcome_prose_direction_mismatches(paper, _MANIFEST)
    assert any(m["claim"] == "no_null_or_negative" for m in out), out


def test_honest_mixed_prose_not_flagged() -> None:
    """Prose that acknowledges the null source must not be flagged."""
    paper = _paper("One source reported a positive effect and one reported a null effect.")
    assert dc.outcome_prose_direction_mismatches(paper, _MANIFEST) == ()


def test_uniform_positive_class_not_flagged() -> None:
    """A class whose receipts are all positive can say 'positive for both'."""
    manifest = {"receipts": [
        {"receipt_id": "A 2022", "outcome_class": "cardiometabolic", "effect_direction": "positive"},
        {"receipt_id": "C 2020", "outcome_class": "cardiometabolic", "effect_direction": "positive"},
    ]}
    paper = _paper("A positive direction of effect holds for both sources.")
    assert dc.outcome_prose_direction_mismatches(paper, manifest) == ()


def test_metadata_prose_excludes_references_block() -> None:
    """A source's title verb in the References list ('... improves ...') must
    not be read as a directional claim about its result (splitter guard)."""
    manifest = {"receipts": [{
        "receipt_id": "B 2015", "body_citation": "B 2015", "citation_token": "B 2015",
        "outcome_class": "cardiometabolic", "effect_direction": "null",
    }]}
    paper = (
        "## Results\n\nThe cardiometabolic class is mixed.\n\n"
        "## References\n\n- **B 2015.** A trial that improves a benefit and favorable outcome.\n"
    )
    assert dc.metadata_prose_direction_mismatches(paper, manifest) == ()
