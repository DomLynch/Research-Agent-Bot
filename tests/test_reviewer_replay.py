from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import reviewer_replay


FIXTURE = Path("tests/fixtures/reviewer_replay_2026-05-09.json")


def test_committed_reviewer_replay_fixture_schema_and_coverage() -> None:
    fixture = reviewer_replay.load_fixture(FIXTURE)
    result = reviewer_replay.run_dry(fixture)

    assert result["total"] == 18
    assert result["metrics"]["topic_count"] >= 8
    assert result["metrics"]["defect_class_count"] >= 10
    assert result["metrics"]["unsafe_if_missed_count"] >= 10


def test_mock_provider_scores_recall_type_and_severity(tmp_path: Path) -> None:
    fixture_path = tmp_path / "fixture.json"
    fixture_path.write_text(
        json.dumps(
            {
                "schema_version": "reviewer_replay_fixture.v1",
                "cases": [
                    {
                        "id": "caught",
                        "topic": "metformin",
                        "source_run": "runs/example",
                        "prior_patch_id": "P01",
                        "expected_defect_class": "broken_public_citation",
                        "expected_min_severity": "P1",
                        "expected_patch_types": ["citation"],
                        "expected_recall": True,
                        "unsafe_if_missed": True,
                        "paper_md": "Bad citation (Metformin 2019b 2019).",
                        "mock_response": {
                            "patches": [
                                {
                                    "id": "P01",
                                    "patch_type": "citation",
                                    "severity": "P1",
                                    "location": "Abstract",
                                    "before": "(Metformin 2019b 2019)",
                                    "after": "(Konopka 2019)",
                                    "reason": "Malformed public citation token.",
                                    "auto_applicable": False,
                                    "requires_trace": True,
                                }
                            ]
                        },
                    },
                    {
                        "id": "missed",
                        "topic": "glp1",
                        "source_run": "runs/example",
                        "prior_patch_id": "P02",
                        "expected_defect_class": "unsupported_numeric_claim",
                        "expected_min_severity": "P1",
                        "expected_patch_types": ["numeric"],
                        "expected_recall": True,
                        "unsafe_if_missed": True,
                        "paper_md": "Unsupported 71.0% effect estimate.",
                        "mock_response": {"patches": []},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    fixture = reviewer_replay.load_fixture(fixture_path)
    result = reviewer_replay.run_mock(fixture)

    assert result["evaluated"] == 2
    assert result["passed"] == 1
    assert result["metrics"]["unsafe_miss_count"] == 1
    assert result["cases"][0]["type_hit"] is True
    assert result["cases"][0]["severity_hit"] is True


def test_live_provider_requires_explicit_allow_live() -> None:
    fixture = reviewer_replay.load_fixture(FIXTURE)

    with pytest.raises(RuntimeError, match="requires --allow-live"):
        reviewer_replay.asyncio.run(
            reviewer_replay.run_live(
                fixture,
                model="google/gemini-3.1-flash-lite:exacto",
                fallback_model="mistralai/mistral-small-2603",
                limit=1,
                allow_live=False,
            )
        )


def test_live_provider_rejects_escalation_fallback() -> None:
    fixture = reviewer_replay.load_fixture(FIXTURE)

    with pytest.raises(RuntimeError, match="final-layer reviewer fallback"):
        reviewer_replay.asyncio.run(
            reviewer_replay.run_live(
                fixture,
                model="google/gemini-3.1-flash-lite:exacto",
                fallback_model="x-ai/grok-4.3",
                limit=1,
                allow_live=True,
            )
        )


def test_live_provider_skips_timeout(monkeypatch) -> None:
    async def slow_review(*args, **kwargs):
        await reviewer_replay.asyncio.sleep(0.05)
        return [], {}, "google/gemini-3.1-flash-lite:exacto", 0.0

    monkeypatch.setattr(reviewer_replay, "review_paper", slow_review)
    fixture = reviewer_replay.load_fixture(FIXTURE)

    result = reviewer_replay.asyncio.run(
        reviewer_replay.run_live(
            fixture,
            model="google/gemini-3.1-flash-lite:exacto",
            fallback_model="mistralai/mistral-small-2603",
            limit=1,
            allow_live=True,
            case_timeout_sec=0.001,
        )
    )

    assert result["evaluated"] == 0
    assert result["metrics"]["skipped_count"] == 1
    assert "timed out" in result["cases"][0]["skip_reason"]
