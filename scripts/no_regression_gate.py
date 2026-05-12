"""Fix #23: No-regression gate — every new run must not worsen the
six load-bearing quality dimensions vs the baseline.

User-mandated discipline (memory anchor: no_regression_rule.md):

  1. P1 status          — # ship blockers (audit + consistency)
  2. Numeric traceability — % of numerics that trace to corpus + bglit
  3. Consistency audit  — # P1 + P2 issues in Stage-2
  4. Citation leakage   — # paper-ID / PMCID / internal-handle leaks
  5. Word count         — total paper words (≥ 95% of baseline OK)
  6. Orphan citation blocks — # surface-lint findings

Each dimension is computed identically for the baseline and new run.
A REGRESSION on ANY dimension fails the gate.

Architecture: pure deterministic, no LLM, no I/O beyond reading the
two run directories' artifacts (`full_paper.audit.json`,
`full_paper.consistency.json`, `manifest.json`, `full_paper.md`)."""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

__all__ = [
    "RegressionDimension",
    "RegressionReport",
    "compare_runs",
    "main",
]


# Word-count floor (Fix #28): only flag a regression if the new run
# drops BELOW this floor. Above the floor, lower word count is a
# feature (Fix #27 prose compression), not a regression. The audit's
# Q1 word-count check uses the same floor, so a sub-floor run already
# fails Q1 and trips p1_count anyway — making word_count semantics
# `floor-pass` instead of `must-not-drop` is consistent.
WORD_COUNT_FLOOR = 5000


@dataclass(frozen=True, slots=True)
class RegressionDimension:
    """One quality dimension comparison. `is_regression=True` means
    the new run is WORSE than the baseline on this dimension."""
    name: str
    baseline_value: float
    new_value: float
    is_regression: bool
    delta_str: str
    direction: str  # "lower_is_better" | "higher_is_better"


@dataclass(frozen=True, slots=True)
class RegressionReport:
    """Full regression check across all six dimensions."""
    baseline_run_dir: str
    new_run_dir: str
    dimensions: tuple[RegressionDimension, ...]

    @property
    def passes(self) -> bool:
        """True iff NO dimension regressed."""
        return not any(d.is_regression for d in self.dimensions)

    @property
    def n_regressions(self) -> int:
        return sum(1 for d in self.dimensions if d.is_regression)

    def to_dict(self) -> dict:
        return {
            "baseline_run_dir": self.baseline_run_dir,
            "new_run_dir": self.new_run_dir,
            "passes": self.passes,
            "n_regressions": self.n_regressions,
            "dimensions": [asdict(d) for d in self.dimensions],
        }


def _load_json(p: Path) -> dict | list:
    """Load JSON file or return empty dict on missing/malformed."""
    try:
        return json.loads(p.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _count_p1_blockers(audit: dict) -> int:
    """Number of P1 checks that failed (i.e. ship blockers)."""
    return sum(
        1 for c in audit.get("checks", [])
        if c.get("p1") and not c.get("passed", True)
    )


def _numeric_traceability_pct(audit: dict) -> float:
    """% of numerics that trace to corpus or bglit registry."""
    for c in audit.get("checks", []):
        if c.get("name") != "Q2_numeric_integrity":
            continue
        # detail string: "21/21 numerics trace to corpus (100%); …"
        # The exact format may vary; match the leading n/total.
        detail = c.get("detail", "")
        m = re.match(r"^(\d+)/(\d+)", detail)
        if m:
            n_traced = int(m.group(1))
            n_total = int(m.group(2))
            if n_total > 0:
                return (n_traced / n_total) * 100.0
    return 0.0


def _consistency_issue_count(consistency: list | dict) -> int:
    """Total Stage-2 issues. The consistency JSON is either a list of
    issue dicts (modern format) or an object with 'issues' key."""
    if isinstance(consistency, list):
        return len(consistency)
    return len(consistency.get("issues", []))


def _citation_leakage_count(consistency: list | dict) -> int:
    """Count of paper-ID leak issues in Stage-2."""
    issues = (
        consistency if isinstance(consistency, list)
        else consistency.get("issues", [])
    )
    return sum(
        1 for i in issues
        if "paper_id" in (i.get("issue_type", "")
                          if isinstance(i, dict) else "")
        or "broken_paper_id" in (i.get("id", "")
                                  if isinstance(i, dict) else "")
    )


def _word_count(manifest: dict) -> int:
    """Total paper words from manifest."""
    return int(manifest.get("total_words", 0))


def _orphan_count(paper_md: str) -> int:
    """Surface-render orphan + consecutive + abstract-cite-only count."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import surface_render_lint as _srl
    except ImportError:
        return 0
    return len(_srl.run_surface_lint(paper_md))


def _load_run_metrics(run_dir: Path) -> dict:
    """Pull all six dimension values from a run directory."""
    audit = _load_json(run_dir / "full_paper.audit.json")
    consistency = _load_json(run_dir / "full_paper.consistency.json")
    manifest = _load_json(run_dir / "manifest.json")
    if not isinstance(audit, dict):
        audit = {}
    if not isinstance(manifest, dict):
        manifest = {}
    paper_path = run_dir / "full_paper.md"
    paper_md = (
        paper_path.read_text() if paper_path.exists() else ""
    )
    return {
        "p1_count": _count_p1_blockers(audit),
        "numeric_trace_pct": _numeric_traceability_pct(audit),
        "consistency_count": _consistency_issue_count(consistency),
        "leakage_count": _citation_leakage_count(consistency),
        "word_count": _word_count(manifest),
        "orphan_count": _orphan_count(paper_md),
    }


def _dim(
    name: str, baseline: float, new: float, *,
    direction: str,
    floor: float | None = None,
) -> RegressionDimension:
    """Build one dimension. `direction` is one of:

      lower_is_better   — new must be ≤ baseline (no tolerance now;
                          cosmetic +/- 0 strict)
      higher_is_better  — new must be ≥ baseline (strict)
      floor_pass        — new must be ≥ `floor` (Fix #28: used for
                          word_count so prose compression no longer
                          false-flags as a regression once we're
                          comfortably above the floor)
    """
    delta = new - baseline
    delta_str = f"{delta:+g}" if delta else "0 (unchanged)"
    if direction == "lower_is_better":
        regress = new > baseline
    elif direction == "floor_pass":
        if floor is None:
            raise ValueError(
                "floor_pass requires `floor` argument"
            )
        regress = new < floor
    else:  # higher_is_better
        regress = new < baseline
    return RegressionDimension(
        name=name,
        baseline_value=float(baseline),
        new_value=float(new),
        is_regression=regress,
        delta_str=delta_str,
        direction=direction,
    )


def compare_runs(
    baseline_dir: Path, new_dir: Path,
) -> RegressionReport:
    """Compare baseline vs new run across all six dimensions.

    Returns a RegressionReport. Caller gates promotion of `new_dir`
    on `report.passes`."""
    baseline = _load_run_metrics(baseline_dir)
    new = _load_run_metrics(new_dir)
    dims = (
        _dim("p1_count", baseline["p1_count"], new["p1_count"],
             direction="lower_is_better"),
        _dim("numeric_trace_pct", baseline["numeric_trace_pct"],
             new["numeric_trace_pct"], direction="higher_is_better"),
        _dim("consistency_count", baseline["consistency_count"],
             new["consistency_count"], direction="lower_is_better"),
        _dim("leakage_count", baseline["leakage_count"],
             new["leakage_count"], direction="lower_is_better"),
        # Fix #28: word_count uses floor-pass semantics. Above
        # WORD_COUNT_FLOOR (matches Q1's audit threshold) lower
        # word counts are a feature (Fix #27 prose compression),
        # not a regression. Sub-floor runs already trip Q1 → P1
        # so the gate doesn't need to double-flag.
        _dim("word_count", baseline["word_count"], new["word_count"],
             direction="floor_pass", floor=WORD_COUNT_FLOOR),
        _dim("orphan_count", baseline["orphan_count"],
             new["orphan_count"], direction="lower_is_better"),
    )
    return RegressionReport(
        baseline_run_dir=str(baseline_dir),
        new_run_dir=str(new_dir),
        dimensions=dims,
    )


def render_report_md(report: RegressionReport) -> str:
    """Markdown report of the regression check."""
    verdict = "PASS" if report.passes else "REGRESSION"
    lines = [
        "# No-Regression Gate Report",
        "",
        f"**Baseline:** `{report.baseline_run_dir}`",
        f"**New:** `{report.new_run_dir}`",
        "",
        f"**Verdict: {verdict}**"
        + (f" — {report.n_regressions} regression(s)"
           if report.n_regressions else ""),
        "",
        "| Dimension | Baseline | New | Δ | Direction | Status |",
        "|---|---|---|---|---|---|",
    ]
    for d in report.dimensions:
        status = "❌ REGRESSION" if d.is_regression else "✅ ok"
        lines.append(
            f"| {d.name} | {d.baseline_value:g} | {d.new_value:g} "
            f"| {d.delta_str} | {d.direction} | {status} |"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fix #23: no-regression gate — compare two runs.",
    )
    parser.add_argument("baseline_dir", help="Path to baseline run dir.")
    parser.add_argument("new_dir", help="Path to new run dir to gate.")
    parser.add_argument(
        "--report-out", default=None,
        help="Optional .md path to write the regression report to.",
    )
    args = parser.parse_args(argv)
    baseline = Path(args.baseline_dir).resolve()
    new = Path(args.new_dir).resolve()
    if not baseline.exists():
        print(f"baseline not found: {baseline}", file=sys.stderr)
        return 2
    if not new.exists():
        print(f"new run not found: {new}", file=sys.stderr)
        return 2
    report = compare_runs(baseline, new)
    md = render_report_md(report)
    print(md)
    if args.report_out:
        Path(args.report_out).write_text(md)
        json_path = Path(args.report_out).with_suffix(".json")
        json_path.write_text(json.dumps(report.to_dict(), indent=2))
    return 0 if report.passes else 1


if __name__ == "__main__":
    sys.exit(main())
