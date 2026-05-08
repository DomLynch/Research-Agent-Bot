"""Offline arbitration validation harness.

Compares fixture model responses against expected labels. No live model calls.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from agent.settings import load_settings  # noqa: E402
from scripts.granite_arbitrator import (  # noqa: E402
    ArbitrationInput,
    GraniteArbitratorConfig,
    parse_model_content,
    request_granite_arbitration,
)

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
    cases = _load_cases(path)
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


async def run_live_fixture(path: Path, *, limit: int | None = None) -> dict[str, Any]:
    cases = _load_cases(path)
    settings = load_settings()
    api_key = os.environ.get(
        "ARBITRATOR_API_KEY",
        os.environ.get("GRANITE_API_KEY", settings.openrouter_api_key),
    ).strip()
    if not api_key:
        raise RuntimeError("missing ARBITRATOR_API_KEY/OPENROUTER_API_KEY")
    config = GraniteArbitratorConfig(
        base_url=os.environ.get(
            "ARBITRATOR_BASE_URL",
            os.environ.get("GRANITE_ARBITRATOR_BASE_URL", settings.openrouter_base_url),
        ),
        api_key=api_key,
        model=os.environ.get(
            "ARBITRATOR_MODEL",
            os.environ.get(
                "GRANITE_ARBITRATOR_MODEL",
                "mistralai/mistral-small-2603",
            ),
        ),
        enabled=True,
        timeout_sec=float(os.environ.get(
            "ARBITRATOR_TIMEOUT_SEC",
            os.environ.get("GRANITE_ARBITRATOR_TIMEOUT_SEC", "60"),
        )),
    )
    rows = []
    for idx, case in enumerate(cases[:limit]):
        expected = _expected_verdict(case, idx)
        decision = await request_granite_arbitration(
            _input_from_case(case), config,
        )
        rows.append({
            "id": case.get("id", str(idx)),
            "expected": expected,
            "actual": decision.verdict,
            "passed": decision.verdict == expected,
            "fail_closed": decision.fail_closed,
            "confidence": decision.confidence,
            "rationale": decision.rationale,
        })
    return {
        "total": len(rows),
        "passed": sum(1 for row in rows if row["passed"]),
        "metrics": _metrics(rows),
        "cases": rows,
        "model": config.model,
    }


def _load_cases(path: Path) -> list[Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    return json.loads(text)


def _input_from_case(case: dict[str, Any]) -> ArbitrationInput:
    context = str(case.get("paper_context") or _context_from_source(case))
    payload = "|".join([
        str(case.get("id", "")),
        str(case.get("before", "")),
        str(case.get("after", "")),
        context,
    ])
    return ArbitrationInput(
        patch_id=str(case.get("patch_id") or case.get("id") or "case"),
        before=str(case.get("before", "")),
        after=str(case.get("after", "")),
        refusal=str(case.get("smart_gate_reason", "")),
        rationale=str(case.get("grok_rationale", "")),
        context_hash="sha256:" + hashlib.sha256(payload.encode()).hexdigest(),
        paper_context=context,
    )


def _context_from_source(case: dict[str, Any], radius: int = 2500) -> str:
    source = case.get("source_run")
    before = str(case.get("before", ""))
    paper = Path(str(source or "")) / "full_paper.md"
    if not source or not paper.exists():
        return ""
    text = paper.read_text(encoding="utf-8", errors="ignore")
    pos = text.find(before) if before else -1
    if pos < 0:
        return text[: radius * 2]
    return text[max(0, pos - radius): min(len(text), pos + len(before) + radius)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("fixture", type=Path)
    parser.add_argument("--min-agreement", type=float, default=1.0)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)
    result = (
        asyncio.run(run_live_fixture(args.fixture, limit=args.limit))
        if args.live
        else run_fixture(args.fixture)
    )
    rendered = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(rendered + "\n")
    print(rendered)
    return 0 if result["metrics"]["agreement_rate"] >= args.min_agreement else 1


if __name__ == "__main__":
    raise SystemExit(main())
