from __future__ import annotations

import json
from pathlib import Path

from scripts.arbitration_validation_harness import main, run_fixture


def test_validation_harness_compares_fixture_labels(tmp_path: Path) -> None:
    fixture = tmp_path / "cases.json"
    fixture.write_text(
        json.dumps(
            [
                {
                    "id": "a",
                    "expected_verdict": "APPLY",
                    "model_response": (
                        '{"verdict":"APPLY","rationale":"ok","confidence":0.9}'
                    ),
                },
                {
                    "id": "b",
                    "expected_verdict": "ESCALATE",
                    "model_response": '{"verdict":"APPLY"',
                },
            ]
        ),
        encoding="utf-8",
    )
    result = run_fixture(fixture)
    assert result["total"] == 2
    assert result["passed"] == 2


def test_validation_harness_cli_returns_nonzero_on_mismatch(tmp_path: Path) -> None:
    fixture = tmp_path / "cases.json"
    fixture.write_text(
        json.dumps(
            [
                {
                    "expected_verdict": "REJECT",
                    "model_response": (
                        '{"verdict":"APPLY","rationale":"ok","confidence":0.9}'
                    ),
                }
            ]
        ),
        encoding="utf-8",
    )
    assert main([str(fixture)]) == 1
