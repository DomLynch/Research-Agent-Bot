"""Fix #23: no-regression gate.

Discriminating tests for the six-dimension comparison + the report
shape + the auto-fail-on-any-regression contract."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import no_regression_gate as nrg  # noqa: E402


def _write_run(
    parent: Path, name: str,
    *,
    p1_failed: int = 0,
    n_traced: int = 21, n_total: int = 21,
    consistency_issues: int = 0,
    leakage_issues: int = 0,
    word_count: int = 11000,
    paper_extra: str = "",
) -> Path:
    """Build a synthetic run dir with the four artifacts the gate
    reads, populated to produce the requested dimension values."""
    rdir = parent / name
    rdir.mkdir(parents=True, exist_ok=True)
    audit = {
        "checks": [
            {"name": "Q2_numeric_integrity", "p1": True, "passed": True,
             "detail": f"{n_traced}/{n_total} numerics trace to corpus"},
        ] + [
            {"name": f"Q{i}_other", "p1": True, "passed": False,
             "detail": "x"}
            for i in range(p1_failed)
        ],
    }
    (rdir / "full_paper.audit.json").write_text(
        json.dumps(audit),
    )
    consistency = []
    for i in range(consistency_issues):
        consistency.append({
            "id": f"C99-test-{i}",
            "issue_type": "test_issue",
            "severity": "P2",
            "auto_fixable": False,
            "evidence": "x", "suggested_fix": "x",
        })
    for i in range(leakage_issues):
        consistency.append({
            "id": f"C04-broken_paper_id-{i}",
            "issue_type": "broken_paper_id_citation",
            "severity": "P1",
            "auto_fixable": False,
            "evidence": "x", "suggested_fix": "x",
        })
    (rdir / "full_paper.consistency.json").write_text(
        json.dumps(consistency),
    )
    (rdir / "manifest.json").write_text(
        json.dumps({"total_words": word_count, "receipts": []}),
    )
    paper = "## Abstract\n\n" + ("Real sentence. " * (word_count // 2))
    paper += paper_extra
    (rdir / "full_paper.md").write_text(paper)
    return rdir


def test_compare_runs_passes_when_dimensions_unchanged() -> None:
    """Baseline = new on every dimension → no regressions → passes."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        baseline = _write_run(tmp_path, "baseline")
        new = _write_run(tmp_path, "new")
        report = nrg.compare_runs(baseline, new)
        assert report.passes
        assert report.n_regressions == 0


def test_p1_increase_flags_regression() -> None:
    """New run has more P1 failures → fails."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        baseline = _write_run(tmp_path, "baseline", p1_failed=0)
        new = _write_run(tmp_path, "new", p1_failed=2)
        report = nrg.compare_runs(baseline, new)
        assert not report.passes
        p1_dim = next(d for d in report.dimensions
                       if d.name == "p1_count")
        assert p1_dim.is_regression
        assert p1_dim.baseline_value == 0
        assert p1_dim.new_value == 2


def test_numeric_traceability_drop_flags_regression() -> None:
    """New % below baseline → fails."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        baseline = _write_run(tmp_path, "baseline",
                               n_traced=21, n_total=21)
        new = _write_run(tmp_path, "new", n_traced=18, n_total=21)
        report = nrg.compare_runs(baseline, new)
        assert not report.passes
        trace_dim = next(d for d in report.dimensions
                          if d.name == "numeric_trace_pct")
        assert trace_dim.is_regression


def test_consistency_increase_flags_regression() -> None:
    """New consistency P1+P2 count higher → fails."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        baseline = _write_run(tmp_path, "baseline", consistency_issues=0)
        new = _write_run(tmp_path, "new", consistency_issues=3)
        report = nrg.compare_runs(baseline, new)
        cons_dim = next(d for d in report.dimensions
                         if d.name == "consistency_count")
        assert cons_dim.is_regression


def test_leakage_increase_flags_regression() -> None:
    """New leakage count higher → fails."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        baseline = _write_run(tmp_path, "baseline", leakage_issues=0)
        new = _write_run(tmp_path, "new", leakage_issues=5)
        report = nrg.compare_runs(baseline, new)
        leak_dim = next(d for d in report.dimensions
                         if d.name == "leakage_count")
        assert leak_dim.is_regression


def test_word_count_above_floor_passes_even_after_compression() -> None:
    """Fix #28: floor-pass semantics — a 30% intentional compression
    is FINE as long as the new word count stays above the
    WORD_COUNT_FLOOR (5000). Prose compression (Fix #27) was the
    explicit reviewer-driven path forward; the gate must not
    false-flag intentional leaner prose."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        baseline = _write_run(tmp_path, "baseline", word_count=13500)
        # 30% drop, but still well above the 5000 floor
        new = _write_run(tmp_path, "new", word_count=9500)
        report = nrg.compare_runs(baseline, new)
        wc_dim = next(d for d in report.dimensions
                       if d.name == "word_count")
        assert not wc_dim.is_regression


def test_word_count_below_floor_flags_regression() -> None:
    """Fix #28: sub-floor (under 5000 words) IS a regression.
    Q1 audit threshold matches WORD_COUNT_FLOOR so a sub-floor run
    already trips P1 — making the gate consistent."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        baseline = _write_run(tmp_path, "baseline", word_count=10000)
        new = _write_run(tmp_path, "new", word_count=4500)  # below floor
        report = nrg.compare_runs(baseline, new)
        wc_dim = next(d for d in report.dimensions
                       if d.name == "word_count")
        assert wc_dim.is_regression
        assert wc_dim.direction == "floor_pass"


def test_orphan_increase_flags_regression() -> None:
    """New orphan citation count higher → fails."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        baseline = _write_run(tmp_path, "baseline", paper_extra="")
        # New run has an orphan _Cited block
        orphan = "\n\n  _Cited: `X 2020`_\n"
        new = _write_run(tmp_path, "new", paper_extra=orphan)
        report = nrg.compare_runs(baseline, new)
        orphan_dim = next(d for d in report.dimensions
                           if d.name == "orphan_count")
        assert orphan_dim.is_regression


def test_improvement_does_not_flag_regression() -> None:
    """New run is BETTER on every dimension → passes (clearly)."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        baseline = _write_run(tmp_path, "baseline",
                               p1_failed=2, consistency_issues=5,
                               leakage_issues=3, n_traced=18, n_total=21)
        new = _write_run(tmp_path, "new",
                          p1_failed=0, consistency_issues=0,
                          leakage_issues=0, n_traced=21, n_total=21)
        report = nrg.compare_runs(baseline, new)
        assert report.passes


def test_report_serializes_to_json() -> None:
    """Report.to_dict produces a JSON-serialisable dict for archival."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        baseline = _write_run(tmp_path, "baseline")
        new = _write_run(tmp_path, "new")
        report = nrg.compare_runs(baseline, new)
        d = report.to_dict()
        # Round-trip JSON
        s = json.dumps(d)
        d2 = json.loads(s)
        assert d2["passes"] == report.passes
        assert len(d2["dimensions"]) == 6


def test_report_md_has_per_dimension_row() -> None:
    """Markdown rendering includes one row per dimension + a verdict."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        baseline = _write_run(tmp_path, "baseline")
        new = _write_run(tmp_path, "new")
        report = nrg.compare_runs(baseline, new)
        md = nrg.render_report_md(report)
        assert "PASS" in md or "REGRESSION" in md
        for dim_name in (
            "p1_count", "numeric_trace_pct", "consistency_count",
            "leakage_count", "word_count", "orphan_count",
        ):
            assert dim_name in md


def test_main_returns_zero_when_passes(tmp_path: Path) -> None:
    """CLI exit-code: 0 on pass."""
    baseline = _write_run(tmp_path, "baseline")
    new = _write_run(tmp_path, "new")
    rc = nrg.main([str(baseline), str(new)])
    assert rc == 0


def test_main_returns_nonzero_when_regression(tmp_path: Path) -> None:
    """CLI exit-code: 1 on any regression."""
    baseline = _write_run(tmp_path, "baseline")
    new = _write_run(tmp_path, "new", p1_failed=3)
    rc = nrg.main([str(baseline), str(new)])
    assert rc == 1
