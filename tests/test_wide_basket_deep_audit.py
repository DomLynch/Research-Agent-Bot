from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

from wide_basket_deep_audit import build_report, main, rows_to_json, rows_to_markdown  # noqa: E402


def _pack(root: Path, topic: str, *, queries: int = 5, trials: int = 0) -> None:
    (root / f"{topic}.toml").write_text(
        "\n".join([
            f'topic = "{topic}"',
            'class_ = "test"',
            'aliases = ["a", "b"]',
            'expected_evidence_slots = ["a", "b", "c", "d", "e", "f", "g", "h"]',
            "corpus_search_queries = [" + ", ".join(f'"q{i}"' for i in range(queries)) + "]",
            "canonical_trials = [" + ", ".join("{}" for _ in range(trials)) + "]",
            "[retrieval]",
            'scope_terms = ["older adults", "aging", "trial"]',
            'exclude_terms = ["animal"]',
        ]),
        encoding="utf-8",
    )


def _run(
    root: Path,
    name: str,
    *,
    topic: str,
    receipts: int = 20,
    maturity: int = 5,
    js: bool = True,
    grok: int = 0,
    strips: int = 0,
) -> Path:
    run = root / name
    run.mkdir()
    (run / "manifest.json").write_text(json.dumps({
        "topic": topic,
        "n_receipts": receipts,
        "n_high_confidence_claims_total": 25,
        "n_non_orthogonal_tensions": 4,
    }), encoding="utf-8")
    (run / "full_paper.final_verdict.json").write_text(json.dumps({
        "verdict": "AAA" if maturity >= 5 else "SHIP-BLOCKED",
        "maturity_level": maturity,
        "journal_surface_pass": js,
        "grok_unresolved_p1": grok,
        "auto_stripped_count": strips,
    }), encoding="utf-8")
    return run


def test_deep_audit_marks_ready_and_no_run_topics(tmp_path: Path) -> None:
    packs = tmp_path / "packs"
    runs = tmp_path / "runs"
    packs.mkdir()
    runs.mkdir()
    _pack(packs, "ready")
    _pack(packs, "new")
    _run(runs, "synthesis-ready-v06-PATH1-2026-01-01Z", topic="ready")

    data = build_report(packs, runs)
    buckets = {row["topic"]: row["bucket"] for row in data["topics"]}

    assert buckets["ready"] == "run_now"
    assert buckets["new"] == "run_now"
    assert data["run_now"][0]["next_command"].endswith("--dry-run")


def test_deep_audit_marks_thin_and_grok_for_corpus_tuning(tmp_path: Path) -> None:
    packs = tmp_path / "packs"
    runs = tmp_path / "runs"
    packs.mkdir()
    runs.mkdir()
    _pack(packs, "thin")
    _pack(packs, "grok")
    _run(runs, "synthesis-thin-v06-PATH1-2026-01-01Z", topic="thin", receipts=3)
    _run(runs, "synthesis-grok-v06-PATH1-2026-01-01Z", topic="grok", grok=1)

    data = build_report(packs, runs)

    assert {row["topic"] for row in data["corpus_tune_first"]} == {"thin", "grok"}
    assert all("--max-per-source 35" in row["tune_command"] for row in data["corpus_tune_first"])


def test_deep_audit_marks_l6_rerun_and_rich_monitor(tmp_path: Path) -> None:
    packs = tmp_path / "packs"
    runs = tmp_path / "runs"
    packs.mkdir()
    runs.mkdir()
    _pack(packs, "single")
    _pack(packs, "stable")
    _run(runs, "synthesis-single-v06-PATH2RICH-2026-01-01Z", topic="single")
    _run(runs, "synthesis-stable-v06-PATH2RICH-2026-01-01Z", topic="stable")
    _run(runs, "synthesis-stable-v06-PATH2RICHFIX-2026-01-02Z", topic="stable")

    data = build_report(packs, runs)
    buckets = {row["topic"]: row["bucket"] for row in data["topics"]}

    assert buckets["single"] == "l6_rerun"
    assert buckets["stable"] == "rich_monitor"


def test_deep_audit_blocks_rich_topic_with_grok_failure(tmp_path: Path) -> None:
    packs = tmp_path / "packs"
    runs = tmp_path / "runs"
    packs.mkdir()
    runs.mkdir()
    _pack(packs, "alpha")
    _run(runs, "synthesis-alpha-v06-PATH2RICH-2026-01-01Z", topic="alpha", grok=2)

    data = build_report(packs, runs)

    assert data["topics"][0]["bucket"] == "corpus_tune_first"
    assert data["topics"][0]["latest_rich_failure"] == "grok"


def test_deep_audit_reports_rich_baseline_regression(tmp_path: Path) -> None:
    packs = tmp_path / "packs"
    runs = tmp_path / "runs"
    packs.mkdir()
    runs.mkdir()
    _pack(packs, "alpha")
    _run(runs, "synthesis-alpha-v06-BASE-2026-01-01Z", topic="alpha", receipts=30, maturity=5)
    _run(
        runs,
        "synthesis-alpha-v06-PATH2RICH-2026-01-02Z",
        topic="alpha",
        receipts=20,
        maturity=4,
    )

    row = build_report(packs, runs)["topics"][0]

    assert row["maturity_delta"] == -1
    assert row["receipt_delta"] == -10


def test_deep_audit_cli_writes_json_and_markdown(tmp_path: Path, capsys) -> None:
    packs = tmp_path / "packs"
    runs = tmp_path / "runs"
    packs.mkdir()
    runs.mkdir()
    _pack(packs, "alpha")
    json_out = tmp_path / "report.json"
    md_out = tmp_path / "report.md"

    rc = main([
        "--topic-pack-dir", str(packs),
        "--runs-dir", str(runs),
        "--format", "json",
        "--json-out", str(json_out),
        "--markdown-out", str(md_out),
    ])
    data = json.loads(json_out.read_text(encoding="utf-8"))

    assert rc == 0
    assert capsys.readouterr().out.startswith("{\n")
    assert rows_to_json(data).startswith("{\n")
    assert rows_to_markdown(data).startswith("# Wide Basket Deep Execution Plan")
    assert md_out.read_text(encoding="utf-8").startswith("# Wide Basket Deep Execution Plan")
