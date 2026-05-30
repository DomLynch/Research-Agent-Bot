from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import golden_paper_eval as gpe  # type: ignore[import-not-found]  # noqa: E402

_GOOD = {"maturity_level": 5, "dimensions": {"journal_surface_pass": True, "audit_pass": True}}
_EXPECT = {"min_maturity_level": 4, "require_dimensions": ["journal_surface_pass", "audit_pass"]}


def _run(tmp_path: Path, status: dict[str, Any] | None) -> Path:
    run = tmp_path / "synthesis-foo-v06-DAILY-2026-05-30T00-00-00Z"
    run.mkdir(parents=True)
    if status is not None:
        (run / "final_status.json").write_text(json.dumps(status), encoding="utf-8")
    return run


def test_run_clearing_the_bar_has_no_failures(tmp_path: Path) -> None:
    assert gpe.evaluate_run(_run(tmp_path, _GOOD), _EXPECT) == []


def test_low_maturity_is_flagged(tmp_path: Path) -> None:
    bad = {"maturity_level": 3, "dimensions": {"journal_surface_pass": True, "audit_pass": True}}
    assert gpe.evaluate_run(_run(tmp_path, bad), _EXPECT) == ["maturity_level 3 < 4"]


def test_failed_required_dimension_is_flagged(tmp_path: Path) -> None:
    bad = {"maturity_level": 5, "dimensions": {"journal_surface_pass": False, "audit_pass": True}}
    assert gpe.evaluate_run(_run(tmp_path, bad), _EXPECT) == ["dimension journal_surface_pass not passing"]


def test_missing_sidecar_fails_every_floor(tmp_path: Path) -> None:
    fails = gpe.evaluate_run(_run(tmp_path, None), _EXPECT)
    assert "maturity_level 0 < 4" in fails


def test_evaluate_all_skips_topics_without_a_run(tmp_path: Path) -> None:
    golden = [{"topic": "foo", **_EXPECT}, {"topic": "bar", **_EXPECT}]
    _run(tmp_path, _GOOD)  # only "foo" has a run
    result = gpe.evaluate_all(tmp_path, golden)
    assert result == {"foo": [], "bar": None}  # bar skipped (no run), foo passes


def test_curated_golden_set_loads_and_is_well_formed() -> None:
    golden = gpe.load_golden()
    assert len(golden) >= 10
    for entry in golden:
        assert entry["topic"] and int(entry["min_maturity_level"]) >= 1
        assert isinstance(entry["require_dimensions"], list)
