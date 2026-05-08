from __future__ import annotations

import json
from pathlib import Path

from scripts.arbitration_validation_harness import main, run_fixture


def test_arbitration_benchmark_fixture_schema_and_coverage() -> None:
    fixture = Path("tests/fixtures/arbitration_benchmark.jsonl")
    rows = [
        json.loads(line)
        for line in fixture.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    required = {
        "id",
        "patch_id",
        "patch_type",
        "severity",
        "before",
        "after",
        "expected_verdict",
        "grok_rationale",
        "smart_gate_reason",
        "manual_judgment_reason",
        "model_response",
        "source_run",
    }
    assert len(rows) == 10
    assert {row["expected_verdict"] for row in rows} == {
        "APPLY",
        "REJECT",
        "ESCALATE",
    }
    assert sum(row["expected_verdict"] == "APPLY" for row in rows) == 2
    assert sum(row["expected_verdict"] == "REJECT" for row in rows) == 2
    assert sum(row["expected_verdict"] == "ESCALATE" for row in rows) == 6
    for row in rows:
        assert required <= row.keys()
        assert Path(row["source_run"]).exists()


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
    assert result["metrics"]["agreement_rate"] == 1.0
    assert result["metrics"]["fail_closed_count"] == 1
    assert result["metrics"]["confusion_matrix"]["APPLY"]["APPLY"] == 1
    assert result["metrics"]["confusion_matrix"]["ESCALATE"]["ESCALATE"] == 1


def test_validation_harness_accepts_human_consensus_labels(tmp_path: Path) -> None:
    fixture = tmp_path / "cases.json"
    fixture.write_text(
        json.dumps(
            [
                {
                    "human_consensus_verdict": "REJECT",
                    "model_response": (
                        '{"verdict":"REJECT","rationale":"judge-only rejection",'
                        '"confidence":0.8}'
                    ),
                }
            ]
        ),
        encoding="utf-8",
    )
    result = run_fixture(fixture)
    assert result["metrics"]["by_expected"]["REJECT"] == {
        "total": 1,
        "agreed": 1,
        "agreement_rate": 1.0,
    }


def test_validation_harness_reports_all_three_verdict_classes(tmp_path: Path) -> None:
    fixture = tmp_path / "cases.json"
    fixture.write_text(
        json.dumps(
            [
                {
                    "human_consensus_verdict": "APPLY",
                    "model_response": (
                        '{"verdict":"APPLY","rationale":"safe deterministic patch",'
                        '"confidence":0.9}'
                    ),
                },
                {
                    "human_consensus_verdict": "REJECT",
                    "model_response": (
                        '{"verdict":"REJECT","rationale":"would alter science",'
                        '"confidence":0.8}'
                    ),
                },
                {
                    "human_consensus_verdict": "ESCALATE",
                    "model_response": (
                        '{"verdict":"APPLY","rationale":"attempted rewrite",'
                        '"confidence":0.5,"replacement_text":"new content"}'
                    ),
                },
            ]
        ),
        encoding="utf-8",
    )
    metrics = run_fixture(fixture)["metrics"]
    assert metrics["agreement_rate"] == 1.0
    assert metrics["fail_closed_count"] == 1
    assert metrics["confusion_matrix"]["APPLY"]["APPLY"] == 1
    assert metrics["confusion_matrix"]["REJECT"]["REJECT"] == 1
    assert metrics["confusion_matrix"]["ESCALATE"]["ESCALATE"] == 1


def test_validation_harness_rejects_invalid_consensus_label(tmp_path: Path) -> None:
    fixture = tmp_path / "cases.json"
    fixture.write_text(
        json.dumps([{"human_consensus_verdict": "MAYBE", "model_response": "{}"}]),
        encoding="utf-8",
    )
    try:
        run_fixture(fixture)
    except ValueError as exc:
        assert "invalid expected verdict" in str(exc)
    else:
        raise AssertionError("invalid consensus label accepted")


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


def test_validation_harness_cli_allows_lower_agreement_threshold(tmp_path: Path) -> None:
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
    assert main([str(fixture), "--min-agreement", "0"]) == 0


def test_model_stack_benchmark_fixture_schema_and_coverage() -> None:
    fixture = Path("tests/fixtures/model_stack_arbitration_benchmark_2026-05-08.json")
    rows = json.loads(fixture.read_text(encoding="utf-8"))
    required = {
        "id",
        "topic",
        "patch_id",
        "patch_type",
        "severity",
        "before",
        "after",
        "expected_verdict",
        "grok_rationale",
        "smart_gate_reason",
        "manual_judgment_reason",
        "model_response",
        "source_run",
    }
    topics = {row["topic"] for row in rows}
    assert len(rows) == 20
    assert {
        "urolithin_a",
        "metformin",
        "glp1",
        "statins",
        "rapamycin",
        "omega3",
        "senolytics",
    } <= topics
    assert {row["expected_verdict"] for row in rows} == {
        "APPLY",
        "REJECT",
        "ESCALATE",
    }
    for row in rows:
        assert required <= row.keys()
        assert Path(row["source_run"]).exists()


def test_model_stack_benchmark_runs_and_persists_log_shape() -> None:
    fixture = Path("tests/fixtures/model_stack_arbitration_benchmark_2026-05-08.json")
    result = run_fixture(fixture)
    assert result["total"] == 20
    assert result["passed"] == 20
    assert result["metrics"]["agreement_rate"] == 1.0
    assert result["metrics"]["expected_distribution"] == {
        "APPLY": 14,
        "ESCALATE": 4,
        "REJECT": 2,
    }
    first = result["cases"][0]["arbitration_log_entry"]
    assert first["schema_version"] == "arbitration_log.v1"
    assert first["decision"] in {"APPLY", "REJECT", "ESCALATE"}
    assert first["model"] == "offline-fixture"
    assert first["input_hash"]


def test_model_stack_fail_closed_fixture() -> None:
    fixture = Path("tests/fixtures/model_stack_fail_closed_cases_2026-05-08.json")
    result = run_fixture(fixture)
    assert result["total"] == 5
    assert result["passed"] == 5
    assert result["metrics"]["agreement_rate"] == 1.0
    assert result["metrics"]["fail_closed_count"] == 4
    assert result["metrics"]["actual_distribution"] == {
        "APPLY": 0,
        "ESCALATE": 5,
        "REJECT": 0,
    }
