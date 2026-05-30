"""Golden paper-quality eval (HeurekaBench-style, recreated — not vendored).

A curated set of canonical topics, each with a quality floor the bot's latest
run must clear (maturity level + required trust-spine dimensions). Turns paper
quality into a regression check: a change that degrades a paper (a gate stops
passing, maturity drops) is caught locally / in CI instead of at Researka.

`evaluate_run` is a pure scorer over a run's `final_status.json` sidecar;
topic-agnostic logic. The curated set lives in EVALS/golden_paper_eval.jsonl
(data, not code) and is extended as new canonical topics certify.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "EVALS" / "golden_paper_eval.jsonl"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def load_golden(path: Path = GOLDEN) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def evaluate_run(run_dir: Path, expectation: dict[str, Any]) -> list[str]:
    """Quality-floor failures for one run dir; empty list means it clears the
    golden bar. A missing/unreadable final_status sidecar fails every floor."""
    status = _read_json(run_dir / "final_status.json")
    failures: list[str] = []
    level = int(status.get("maturity_level") or 0)
    floor = int(expectation.get("min_maturity_level") or 0)
    if level < floor:
        failures.append(f"maturity_level {level} < {floor}")
    dims_raw = status.get("dimensions")
    dims = dims_raw if isinstance(dims_raw, dict) else {}
    for dim in expectation.get("require_dimensions") or []:
        if not dims.get(dim):
            failures.append(f"dimension {dim} not passing")
    return failures


def _latest_run(runs_root: Path, topic: str) -> Path | None:
    runs = sorted(runs_root.glob(f"synthesis-{topic}-v*-*"), key=lambda p: p.stat().st_mtime, reverse=True)
    return runs[0] if runs else None


def evaluate_all(runs_root: Path, golden: list[dict[str, Any]] | None = None) -> dict[str, list[str] | None]:
    """topic -> failures (empty = pass) or None when no run exists yet (skip)."""
    out: dict[str, list[str] | None] = {}
    for entry in (golden if golden is not None else load_golden()):
        topic = str(entry.get("topic") or "")
        run = _latest_run(runs_root, topic)
        out[topic] = None if run is None else evaluate_run(run, entry)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="golden_paper_eval")
    parser.add_argument("--runs-root", type=Path, default=ROOT / "runs")
    results = evaluate_all(parser.parse_args(argv).runs_root)
    failed = 0
    for topic, fails in results.items():
        tag = "SKIP" if fails is None else ("PASS" if not fails else "FAIL")
        print(f"{tag} {topic}: {'; '.join(fails) if fails else ('no run yet' if fails is None else 'clears golden bar')}")
        failed += int(bool(fails))
    scored = sum(1 for f in results.values() if f is not None)
    print(f"\n{scored - failed}/{scored} scored topics clear the golden bar ({len(results) - scored} skipped)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
