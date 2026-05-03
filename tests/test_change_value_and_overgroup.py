"""Fix #37 + Fix #38 — content audit gates that catch the two
reviewer-flagged P1s on the metformin public-repro paper:

  C13 (Fix #37) — change-value misread: a numeric the corpus
                  describes as a change/improvement/difference is
                  rendered in prose as an absolute value below a
                  threshold.

  C14 (Fix #38) — abstract over-grouping: an abstract sentence
                  cites ≥2 receipts under a numeric range, but at
                  least one cited receipt has zero high-confidence
                  percentage claims in its corpus quant_claims.

Both detections are P1, NOT auto-fixable — they require Grok or
human rewrite. Combined with Fix #36 (flagged-decision counting)
they downgrade the unified verdict to 'Trust-Spine Pass — Human
Review Required' until corrected."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import final_consistency_audit as fca  # noqa: E402


def _empty_audit() -> dict:
    return {"score_out_of_10": 10.0, "p1_pass": True}


def _empty_manifest() -> dict:
    return {"receipts": []}


# ============ Fix #37 — change-value misread ===========================


def test_change_value_misread_smoke_on_actual_paper(monkeypatch) -> None:
    """End-to-end on the actual public-repro paper: the 0.13 m/s
    Witham/MET-PREVENT misread surfaces as P1 C13."""
    paper_path = (
        Path(__file__).resolve().parent.parent
        / "runs/synthesis-metformin-v06-public-repro-"
          "2026-05-03T17-54-36Z/full_paper.md"
    )
    if not paper_path.exists():
        return  # archived runs may be cleaned up; skip silently
    paper = paper_path.read_text()
    manifest_path = paper_path.parent / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    issues = fca.run_audit(paper, manifest, _empty_audit())
    c13 = [i for i in issues if i.id.startswith("C13-")]
    assert len(c13) >= 1, (
        "Fix #37 must catch the 0.13 m/s change-value misread on "
        "the public-repro paper"
    )
    assert c13[0].severity == "P1"
    assert c13[0].auto_fixable is False
    assert "0.13 m/s" in c13[0].suggested_fix


def test_change_value_misread_silent_when_no_misread() -> None:
    """A clean paper that uses 0.13 m/s WITH the change-word
    surfaces no C13 finding."""
    paper = (
        "## Discussion\n\n"
        "MET-PREVENT reported an improvement in walk speed of "
        "0.13 m/s with metformin. This change estimate is below "
        "the 0.8 m/s threshold for typical clinically meaningful "
        "differences in research practice.\n"
    )
    issues = fca.run_audit(paper, _empty_manifest(), _empty_audit())
    c13 = [i for i in issues if i.id.startswith("C13-")]
    assert c13 == []


def test_change_value_misread_handles_missing_quant_dir(
    monkeypatch, tmp_path: Path,
) -> None:
    """Defensive: if QUANT_DIR doesn't exist, the check is a
    no-op (returns []), never crashes."""
    sys.path.insert(0, str(
        Path(__file__).resolve().parent.parent / "scripts"
    ))
    import run_v06_synthesis as orch
    monkeypatch.setattr(orch, "QUANT_DIR", tmp_path / "nope")
    paper = "Random text with 0.13 m/s below 0.8 m/s threshold."
    issues = fca._check_change_value_misread(paper, _empty_manifest())
    assert issues == []


# ============ Fix #38 — abstract over-grouping =========================


def test_abstract_over_grouping_smoke_on_actual_paper() -> None:
    """End-to-end: the Henney over-grouping (Keys+Patel+Henney
    'each reporting 16-42%') surfaces as P1 C14."""
    paper_path = (
        Path(__file__).resolve().parent.parent
        / "runs/synthesis-metformin-v06-public-repro-"
          "2026-05-03T17-54-36Z/full_paper.md"
    )
    if not paper_path.exists():
        return
    paper = paper_path.read_text()
    manifest_path = paper_path.parent / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    issues = fca.run_audit(paper, manifest, _empty_audit())
    c14 = [i for i in issues if i.id.startswith("C14-")]
    assert len(c14) >= 1, (
        "Fix #38 must catch the Henney over-grouping on the "
        "public-repro paper"
    )
    assert c14[0].severity == "P1"
    assert c14[0].auto_fixable is False
    assert "Henney" in c14[0].suggested_fix


def test_abstract_over_grouping_silent_when_no_abstract() -> None:
    """A paper without an Abstract section → no C14 findings."""
    paper = "## Methods\n\nNo abstract here.\n"
    issues = fca._check_abstract_over_grouping(paper, _empty_manifest())
    assert issues == []


def test_abstract_over_grouping_silent_when_single_citation() -> None:
    """C14 requires ≥2 citations + a percent range. A single-citation
    sentence is fine — over-grouping is by definition ≥2."""
    paper = (
        "## Abstract\n\n"
        "Keys 2025 reported mortality reductions of 16-42%.\n"
    )
    issues = fca._check_abstract_over_grouping(paper, _empty_manifest())
    assert issues == []


def test_abstract_over_grouping_silent_when_no_range() -> None:
    """No percent range in the sentence → no C14 finding (the check
    is about over-attributing a numeric)."""
    paper = (
        "## Abstract\n\n"
        "Keys 2025 and Patel 2026 both contribute mortality "
        "evidence to this synthesis.\n"
    )
    issues = fca._check_abstract_over_grouping(paper, _empty_manifest())
    assert issues == []
