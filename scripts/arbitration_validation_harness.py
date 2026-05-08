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


def run_fixture(path: Path) -> dict[str, Any]:
    cases = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(cases, list):
        raise ValueError("fixture must be a JSON list")
    rows = []
    for idx, case in enumerate(cases):
        if not isinstance(case, dict):
            raise ValueError(f"case {idx} must be an object")
        expected = str(case["expected_verdict"]).upper()
        decision = parse_model_content(str(case["model_response"]))
        rows.append(
            {
                "id": case.get("id", str(idx)),
                "expected": expected,
                "actual": decision.verdict,
                "passed": decision.verdict == expected,
            }
        )
    return {
        "total": len(rows),
        "passed": sum(1 for row in rows if row["passed"]),
        "cases": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("fixture", type=Path)
    args = parser.parse_args(argv)
    result = run_fixture(args.fixture)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] == result["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
