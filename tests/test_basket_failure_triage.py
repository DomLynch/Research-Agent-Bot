from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

from basket_failure_triage import collect_triage  # noqa: E402


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def test_failure_triage_prefers_journal_surface_then_grok(tmp_path: Path) -> None:
    js_run = tmp_path / "js"
    js_run.mkdir()
    _write_json(js_run / "manifest.json", {"topic": "alpha", "n_receipts": 20})
    _write_json(js_run / "full_paper.final_verdict.json", {"js_pass": False})

    grok_run = tmp_path / "grok"
    grok_run.mkdir()
    _write_json(grok_run / "manifest.json", {"topic": "beta", "n_receipts": 20})
    _write_json(grok_run / "full_paper.review_patch_log.json", {"n_flagged": 2})

    rows = collect_triage([js_run, grok_run])

    assert rows[0]["failure_class"] == "js"
    assert rows[1]["failure_class"] == "grok"


def test_failure_triage_marks_thin_corpus(tmp_path: Path) -> None:
    run = tmp_path / "thin"
    run.mkdir()
    _write_json(run / "manifest.json", {
        "topic": "omega",
        "n_receipts": 2,
        "n_high_confidence_claims_total": 5,
    })

    assert collect_triage([run])[0]["failure_class"] == "corpus-thin"
