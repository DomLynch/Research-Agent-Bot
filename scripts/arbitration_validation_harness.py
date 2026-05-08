"""Offline arbitration validation harness.

Compares fixture model responses against expected labels. No live model calls.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from scripts.granite_arbitrator import parse_model_content  # noqa: E402

VALID_VERDICTS = {"APPLY", "REJECT", "ESCALATE"}


def _expected_verdict(case: dict[str, Any], idx: int) -> str:
    raw = (
        case.get("human_consensus_verdict")
        or case.get("consensus_verdict")
        or case.get("expected_verdict")
    )
    verdict = str(raw or "").strip().upper()
    if verdict not in VALID_VERDICTS:
        raise ValueError(f"case {idx} has invalid expected verdict")
    return verdict


def _metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    passed = sum(1 for row in rows if row["passed"])
    confusion = {
        expected: {actual: 0 for actual in sorted(VALID_VERDICTS)}
        for expected in sorted(VALID_VERDICTS)
    }
    by_expected: dict[str, dict[str, int | float]] = {}
    for row in rows:
        confusion[row["expected"]][row["actual"]] += 1
    for expected, actuals in confusion.items():
        n = sum(actuals.values())
        agreed = actuals[expected]
        by_expected[expected] = {
            "total": n,
            "agreed": agreed,
            "agreement_rate": agreed / n if n else 0.0,
        }
    return {
        "agreement_rate": passed / total if total else 0.0,
        "fail_closed_count": sum(1 for row in rows if row["fail_closed"]),
        "escalate_count": sum(1 for row in rows if row["actual"] == "ESCALATE"),
        "by_expected": by_expected,
        "confusion_matrix": confusion,
    }


def run_fixture(path: Path) -> dict[str, Any]:
    cases = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(cases, list):
        raise ValueError("fixture must be a JSON list")
    rows = []
    for idx, case in enumerate(cases):
        if not isinstance(case, dict):
            raise ValueError(f"case {idx} must be an object")
        expected = _expected_verdict(case, idx)
        decision = parse_model_content(str(case["model_response"]))
        rows.append(
            {
                "id": case.get("id", str(idx)),
                "expected": expected,
                "actual": decision.verdict,
                "passed": decision.verdict == expected,
                "fail_closed": decision.fail_closed,
                "confidence": decision.confidence,
            }
        )
    return {
        "total": len(rows),
        "passed": sum(1 for row in rows if row["passed"]),
        "metrics": _metrics(rows),
        "cases": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("fixture", type=Path)
    parser.add_argument("--min-agreement", type=float, default=1.0)
    args = parser.parse_args(argv)
    result = run_fixture(args.fixture)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["metrics"]["agreement_rate"] >= args.min_agreement else 1


if __name__ == "__main__":
    raise SystemExit(main())
