"""Replay historical reviewer defects against a mockable reviewer provider.

Default mode is dry-run schema validation. Live model calls require
``--provider live --allow-live`` so replay cannot accidentally spend tokens or
enable a fallback path during normal tests.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from scripts.grok_reviewer import _normalize_patch, review_with_grok  # noqa: E402

VALID_TYPES = {"formatting", "numeric", "citation", "claim", "structure"}
VALID_SEVERITIES = {"P1", "P2", "P3"}
SEVERITY_RANK = {"P1": 1, "P2": 2, "P3": 3}


def load_fixture(path: Path) -> dict[str, Any]:
    fixture = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(fixture, dict):
        raise ValueError("fixture must be a JSON object")
    if fixture.get("schema_version") != "reviewer_replay_fixture.v1":
        raise ValueError("unsupported fixture schema_version")
    cases = fixture.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("fixture requires non-empty cases list")
    for idx, case in enumerate(cases):
        _validate_case(case, idx)
    return fixture


def run_dry(fixture: dict[str, Any], *, limit: int | None = None) -> dict[str, Any]:
    cases = fixture["cases"][:limit]
    return {
        "schema_version": "reviewer_replay_result.v1",
        "provider": "dry-run",
        "total": len(cases),
        "evaluated": 0,
        "metrics": _coverage_metrics(cases),
        "cases": [
            {
                "id": case["id"],
                "topic": case["topic"],
                "defect_class": case["expected_defect_class"],
                "expected_min_severity": case["expected_min_severity"],
                "status": "schema_validated",
            }
            for case in cases
        ],
    }


def run_mock(fixture: dict[str, Any], *, limit: int | None = None) -> dict[str, Any]:
    rows = []
    for idx, case in enumerate(fixture["cases"][:limit]):
        raw = case.get("mock_response")
        if raw is None:
            rows.append(_skipped(case, "missing mock_response"))
            continue
        if not isinstance(raw, dict):
            raise ValueError(f"case {idx} mock_response must be an object")
        patches = [
            patch
            for i, p_raw in enumerate(raw.get("patches", []), start=1)
            if isinstance(p_raw, dict)
            for patch in [_normalize_patch(p_raw, i)]
            if patch is not None
        ]
        rows.append(_score_case(case, [asdict(patch) for patch in patches]))
    return _result("mock", rows)


async def run_live(
    fixture: dict[str, Any],
    *,
    model: str,
    fallback_model: str,
    limit: int | None = None,
    allow_live: bool = False,
    case_timeout_sec: float = 90.0,
) -> dict[str, Any]:
    if not allow_live:
        raise RuntimeError("live reviewer replay requires --allow-live")
    if fallback_model.startswith("x-ai/grok"):
        raise RuntimeError("Grok fallback is not allowed in reviewer replay")
    rows = []
    for case in fixture["cases"][:limit]:
        try:
            patches, _raw, model_used, cost = await asyncio.wait_for(
                review_with_grok(
                    str(case["paper_md"]),
                    case.get("manifest", {}),
                    case.get("audit", {}),
                    model=model,
                    fallback_model=fallback_model,
                    api_key=os.environ.get("OPENROUTER_API_KEY"),
                ),
                timeout=case_timeout_sec,
            )
        except TimeoutError:
            rows.append(_skipped(case, f"review timed out after {case_timeout_sec:g}s"))
            continue
        except Exception as exc:
            rows.append(_skipped(case, f"review failed: {type(exc).__name__}"))
            continue
        scored = _score_case(case, [asdict(patch) for patch in patches])
        scored["model_used"] = model_used
        scored["cost_usd"] = cost
        rows.append(scored)
    return _result("live", rows, model=model, fallback_model=fallback_model)


def _validate_case(case: Any, idx: int) -> None:
    if not isinstance(case, dict):
        raise ValueError(f"case {idx} must be an object")
    required = {
        "id",
        "topic",
        "source_run",
        "prior_patch_id",
        "expected_defect_class",
        "expected_min_severity",
        "expected_patch_types",
        "expected_recall",
        "unsafe_if_missed",
        "paper_md",
    }
    missing = sorted(required - set(case))
    if missing:
        raise ValueError(f"case {idx} missing fields: {missing}")
    if case["expected_min_severity"] not in VALID_SEVERITIES:
        raise ValueError(f"case {idx} has invalid expected_min_severity")
    patch_types = case["expected_patch_types"]
    if not isinstance(patch_types, list) or not patch_types:
        raise ValueError(f"case {idx} expected_patch_types must be a non-empty list")
    bad_types = sorted(set(patch_types) - VALID_TYPES)
    if bad_types:
        raise ValueError(f"case {idx} has invalid expected_patch_types: {bad_types}")
    if not isinstance(case["expected_recall"], bool):
        raise ValueError(f"case {idx} expected_recall must be bool")
    if not isinstance(case["unsafe_if_missed"], bool):
        raise ValueError(f"case {idx} unsafe_if_missed must be bool")
    if not str(case["paper_md"]).strip():
        raise ValueError(f"case {idx} paper_md must be non-empty")


def _score_case(case: dict[str, Any], patches: list[dict[str, Any]]) -> dict[str, Any]:
    expect_recall = bool(case["expected_recall"])
    has_patch = bool(patches)
    severity_rank = SEVERITY_RANK[str(case["expected_min_severity"])]
    severity_hit = any(
        SEVERITY_RANK.get(str(patch.get("severity")), 99) <= severity_rank
        for patch in patches
    )
    expected_types = set(case["expected_patch_types"])
    type_hit = any(str(patch.get("patch_type")) in expected_types for patch in patches)
    recall_pass = has_patch if expect_recall else not has_patch
    passed = recall_pass and (not expect_recall or (severity_hit and type_hit))
    return {
        "id": case["id"],
        "topic": case["topic"],
        "defect_class": case["expected_defect_class"],
        "expected_recall": expect_recall,
        "expected_min_severity": case["expected_min_severity"],
        "expected_patch_types": sorted(expected_types),
        "patch_count": len(patches),
        "recall_pass": recall_pass,
        "severity_hit": severity_hit,
        "type_hit": type_hit,
        "passed": passed,
        "unsafe_miss": bool(case["unsafe_if_missed"] and expect_recall and not has_patch),
        "patches": patches,
    }


def _skipped(case: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "id": case["id"],
        "topic": case["topic"],
        "defect_class": case["expected_defect_class"],
        "skipped": True,
        "skip_reason": reason,
    }


def _result(provider: str, rows: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    evaluated = [row for row in rows if not row.get("skipped")]
    total = len(evaluated)
    passed = sum(1 for row in evaluated if row.get("passed"))
    result = {
        "schema_version": "reviewer_replay_result.v1",
        "provider": provider,
        "total": len(rows),
        "evaluated": total,
        "passed": passed,
        "metrics": {
            "pass_rate": passed / total if total else 0.0,
            "recall_rate": _rate(evaluated, "recall_pass"),
            "severity_hit_rate": _rate(evaluated, "severity_hit"),
            "type_hit_rate": _rate(evaluated, "type_hit"),
            "unsafe_miss_count": sum(1 for row in evaluated if row.get("unsafe_miss")),
            "skipped_count": len(rows) - total,
        },
        "cases": rows,
    }
    result.update(extra)
    return result


def _coverage_metrics(cases: list[dict[str, Any]]) -> dict[str, Any]:
    topics = sorted({case["topic"] for case in cases})
    defect_classes = sorted({case["expected_defect_class"] for case in cases})
    return {
        "topics": topics,
        "topic_count": len(topics),
        "defect_classes": defect_classes,
        "defect_class_count": len(defect_classes),
        "unsafe_if_missed_count": sum(1 for case in cases if case["unsafe_if_missed"]),
    }


def _rate(rows: list[dict[str, Any]], field: str) -> float:
    return sum(1 for row in rows if row.get(field)) / len(rows) if rows else 0.0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("fixture", type=Path)
    parser.add_argument("--provider", choices=("dry-run", "mock", "live"), default="dry-run")
    parser.add_argument("--model", default="deepseek/deepseek-v4-pro")
    parser.add_argument("--fallback-model", default="mistralai/mistral-small-2603")
    parser.add_argument("--allow-live", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--case-timeout-sec", type=float, default=90.0)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    fixture = load_fixture(args.fixture)
    if args.provider == "dry-run":
        result = run_dry(fixture, limit=args.limit)
    elif args.provider == "mock":
        result = run_mock(fixture, limit=args.limit)
    else:
        result = asyncio.run(
            run_live(
                fixture,
                model=args.model,
                fallback_model=args.fallback_model,
                limit=args.limit,
                allow_live=args.allow_live,
                case_timeout_sec=args.case_timeout_sec,
            )
        )
    rendered = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
