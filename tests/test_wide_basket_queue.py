from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

from wide_basket_queue import build_report, main, rows_to_json, rows_to_markdown  # noqa: E402


def _pack(root: Path, topic: str, *, queries: int = 5, trials: int = 0) -> None:
    lines = [
        f'topic = "{topic}"',
        'expected_evidence_slots = ["human_rcts", "human_observational", "human_mechanism", "safety", "mortality", "frailty", "function", "biomarkers"]',
        "corpus_search_queries = [" + ", ".join(f'"q{i}"' for i in range(queries)) + "]",
        "canonical_trials = [" + ", ".join("{}" for _ in range(trials)) + "]",
    ]
    (root / f"{topic}.toml").write_text("\n".join(lines), encoding="utf-8")


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
    }), encoding="utf-8")
    (run / "full_paper.final_verdict.json").write_text(json.dumps({
        "verdict": "AAA" if maturity >= 5 else "SHIP-BLOCKED",
        "maturity_level": maturity,
        "journal_surface_pass": js,
        "grok_unresolved_p1": grok,
        "auto_stripped_count": strips,
    }), encoding="utf-8")
    return run


def test_build_report_queues_topics_without_rich_runs(tmp_path: Path) -> None:
    packs = tmp_path / "topic_packs"
    runs = tmp_path / "runs"
    packs.mkdir()
    runs.mkdir()
    _pack(packs, "alpha", queries=7, trials=3)
    _pack(packs, "beta", queries=5)
    _run(runs, "synthesis-alpha-v06-PATH2RICH-2026-01-01Z", topic="alpha")

    data = build_report(packs, runs)

    assert data["inventory"]["topic_packs"] == 2
    assert data["inventory"]["rich_topics"] == ["alpha"]
    assert [row["topic"] for row in data["queue"]] == ["beta"]
    assert data["queue"][0]["status"] == "ready"


def test_build_report_detects_regressions_and_journal_surface(tmp_path: Path) -> None:
    packs = tmp_path / "topic_packs"
    runs = tmp_path / "runs"
    packs.mkdir()
    runs.mkdir()
    _pack(packs, "alpha", queries=7, trials=3)
    _run(runs, "synthesis-alpha-v06-BASE-2026-01-01Z", topic="alpha", receipts=30, maturity=5)
    _run(
        runs,
        "synthesis-alpha-v06-PATH2RICH-2026-01-02Z",
        topic="alpha",
        receipts=24,
        maturity=4,
        js=False,
    )

    data = build_report(packs, runs)
    row = data["rich_baseline_comparison"][0]

    assert row["maturity_delta"] == -1
    assert row["receipt_delta"] == -6
    assert data["cert_regressions"][0]["topic"] == "alpha"
    assert data["corpus_regressions"][0]["topic"] == "alpha"
    assert data["journal_surface_blocks"][0]["topic"] == "alpha"
    assert data["watchlist"][0]["reasons"] == [
        "journal-surface", "cert-regression", "corpus-regression",
    ]


def test_build_report_marks_needs_corpus_tuning(tmp_path: Path) -> None:
    packs = tmp_path / "topic_packs"
    runs = tmp_path / "runs"
    packs.mkdir()
    runs.mkdir()
    _pack(packs, "alpha", queries=4)
    _run(runs, "synthesis-alpha-v06-PATH1-2026-01-01Z", topic="alpha", receipts=3)

    data = build_report(packs, runs)

    assert data["queue"][0]["status"] == "needs corpus tuning"
    assert data["queue"][0]["latest_failure"] == "corpus-thin"


def test_cli_writes_json_and_markdown(tmp_path: Path, capsys) -> None:
    packs = tmp_path / "topic_packs"
    runs = tmp_path / "runs"
    packs.mkdir()
    runs.mkdir()
    _pack(packs, "alpha")
    json_out = tmp_path / "queue.json"
    md_out = tmp_path / "queue.md"

    rc = main([
        "--topic-pack-dir", str(packs),
        "--runs-dir", str(runs),
        "--format", "json",
        "--json-out", str(json_out),
        "--markdown-out", str(md_out),
    ])
    captured = capsys.readouterr()
    data = json.loads(json_out.read_text(encoding="utf-8"))

    assert rc == 0
    assert captured.out.startswith("{\n")
    assert rows_to_json(data).startswith("{\n")
    assert rows_to_markdown(data).startswith("# Wide Basket Queue")
    assert md_out.read_text(encoding="utf-8").startswith("# Wide Basket Queue")
