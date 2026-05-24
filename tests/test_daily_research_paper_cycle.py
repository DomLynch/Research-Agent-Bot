from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import daily_research_paper_cycle as cycle  # type: ignore[import-not-found]  # noqa: E402


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _topic(root: Path, topic: str, *, corpus: bool = True) -> None:
    (root / "topic_packs").mkdir(exist_ok=True)
    (root / "topic_packs" / f"{topic}.toml").write_text("name = \"x\"\n", encoding="utf-8")
    if corpus:
        (root / "docs" / "quality-reference" / topic).mkdir(parents=True)


def test_discover_topics_requires_pack_and_corpus(tmp_path: Path) -> None:
    _topic(tmp_path, "creatine")
    _topic(tmp_path, "missing_corpus", corpus=False)
    (tmp_path / "topic_packs" / "_biomedical_default.toml").write_text("", encoding="utf-8")

    topics = cycle.discover_topics(tmp_path / "topic_packs", tmp_path / "docs" / "quality-reference")

    assert topics == ["creatine"]


def test_select_topic_skips_remote_published_titles_and_rotates_attempts(tmp_path: Path) -> None:
    ledger_dir = tmp_path / cycle.LEDGER_DIR
    _write_json(ledger_dir / "2026-05-23.json", {"topic": "creatine", "started_at": "2026-05-23T00:00:00Z"})

    selected = cycle.select_topic(
        ["aerobic_exercise", "creatine", "metformin"],
        ledger_dir,
        remote_seen={"title:researka agent-certified evidence brief: aerobic exercise and human geroscience"},
    )

    assert selected == "metformin"


def test_cycle_dry_run_selects_topic_without_synthesis(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "creatine")
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")

    ledger = cycle.run_cycle(runs_root=tmp_path / "runs", date="2026-05-24")

    assert ledger["status"] == "dry_run_selected_topic"
    assert ledger["topic"] == "creatine"
    assert ledger["submitted"] == 0
    assert ledger["published"] == 0


def test_cycle_runs_synthesis_then_delegates_to_submit_bridge(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "creatine")
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    calls: dict[str, Any] = {}

    def fake_synthesis(topic: str, out_dir: Path, *, dry_run: bool, timeout: int | None = None) -> int:
        calls["synthesis"] = {"topic": topic, "out_dir": out_dir.name, "dry_run": dry_run, "timeout": timeout}
        out_dir.mkdir(parents=True)
        return 0

    def fake_submit(**kwargs: Any) -> dict[str, Any]:
        calls["submit"] = kwargs
        return {"status": "submitted_to_researka", "submitted": 1, "published": 0}

    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-05-24",
        run_synthesis=True,
        submit=True,
        remote_loader=lambda: (set(), None),
        submit_cycle=fake_submit,
    )

    assert ledger["status"] == "submitted_to_researka"
    assert calls["synthesis"]["topic"] == "creatine"
    assert calls["submit"]["submit"] is True
    assert ledger["published"] == 0


def test_cycle_salvages_daily_slot_with_next_topic(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "acarbose")
    _topic(tmp_path, "creatine")
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    topics: list[str] = []
    submit_calls = 0

    def fake_synthesis(topic: str, out_dir: Path, *, dry_run: bool, timeout: int | None = None) -> int:
        topics.append(topic)
        out_dir.mkdir(parents=True)
        return 0

    def fake_submit(**_kwargs: Any) -> dict[str, Any]:
        nonlocal submit_calls
        submit_calls += 1
        if submit_calls == 1:
            return {"status": "no_eligible_research_paper", "submitted": 0, "published": 0}
        return {"status": "submitted_to_researka", "submitted": 1, "published": 0}

    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-05-24",
        run_synthesis=True,
        submit=True,
        remote_loader=lambda: (set(), None),
        submit_cycle=fake_submit,
        max_attempts=2,
    )

    assert ledger["status"] == "submitted_to_researka"
    assert topics == ["acarbose", "creatine"]
    assert [a["submit_status"] for a in ledger["attempts"]] == [
        "no_eligible_research_paper",
        "submitted_to_researka",
    ]


def test_cycle_fails_closed_when_remote_dedupe_fails(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "creatine")
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setenv("RESEARKA_API_KEY_V3", "test-token")

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-05-24",
        submit=True,
        remote_loader=lambda: (set(), "timeout"),
    )

    assert ledger["status"] == "remote_dedupe_failed"
    assert ledger["submitted"] == 0


def test_cycle_holds_before_synthesis_when_submit_token_missing(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "creatine")
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    for name in cycle.submit_bridge.TOKEN_ENVS:
        monkeypatch.delenv(name, raising=False)

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-05-24",
        run_synthesis=True,
        submit=True,
    )

    assert ledger["status"] == "submit_not_configured"
    assert "topic" not in ledger
