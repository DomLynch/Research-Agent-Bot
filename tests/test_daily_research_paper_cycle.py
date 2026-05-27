from __future__ import annotations

import datetime as dt
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


def _recent_start() -> str:
    return (dt.datetime.now(dt.UTC) - dt.timedelta(hours=1)).isoformat()


def _topic(root: Path, topic: str, *, corpus: bool = True, target_journal: bool = False) -> None:
    (root / "topic_packs").mkdir(exist_ok=True)
    text = 'name = "x"\n'
    if target_journal:
        text += 'target_journal = "GeroScience"\n'
    (root / "topic_packs" / f"{topic}.toml").write_text(text, encoding="utf-8")
    if corpus:
        qdir = root / "docs" / "quality-reference" / topic / "quant_claims"
        qdir.mkdir(parents=True)
        _write_json(qdir / "seed.quant_claims.json", {"paper_id": "seed", "claims": []})


def _prior_run(root: Path, topic: str, *, receipts: int, tensions: int, primary: int = 1, level: int = 2) -> Path:
    run = root / "runs" / f"synthesis-{topic}-v06-OLD"
    receipts_payload = [
        {"receipt_id": f"r{i}", "evidence_tier": "A1" if i < primary else "B2"}
        for i in range(receipts)
    ]
    _write_json(run / "manifest.json", {
        "topic": topic,
        "n_receipts": receipts,
        "n_non_orthogonal_tensions": tensions,
        "receipts": receipts_payload,
    })
    _write_json(run / "final_status.json", {"maturity_level": level})
    return run


def test_discover_topics_includes_pack_before_corpus_exists(tmp_path: Path) -> None:
    _topic(tmp_path, "creatine")
    _topic(tmp_path, "new_topic", corpus=False)
    (tmp_path / "topic_packs" / "_biomedical_default.toml").write_text("", encoding="utf-8")

    topics = cycle.discover_topics(tmp_path / "topic_packs", tmp_path / "docs" / "quality-reference")

    assert topics == ["creatine", "new_topic"]


def test_select_topic_skips_remote_published_titles_and_rotates_attempts(tmp_path: Path) -> None:
    ledger_dir = tmp_path / cycle.LEDGER_DIR
    _write_json(ledger_dir / "2026-05-23.json", {"topic": "creatine", "started_at": "2026-05-23T00:00:00Z"})

    selected = cycle.select_topic(
        ["aerobic_exercise", "creatine", "metformin"],
        ledger_dir,
        remote_seen={"title:researka agent-certified evidence brief: aerobic exercise and human geroscience"},
    )

    assert selected == "metformin"


def test_select_topic_prefers_publication_track_packs(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "acarbose")
    _topic(tmp_path, "caloric_restriction", target_journal=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")

    selected = cycle.select_topic(["acarbose", "caloric_restriction"], tmp_path / cycle.LEDGER_DIR)

    assert selected == "caloric_restriction"


def test_select_topic_scores_prior_l4_topic_over_plain_publication_track(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "caloric_restriction", target_journal=True)
    _topic(tmp_path, "metformin", target_journal=True)
    _prior_run(tmp_path, "metformin", receipts=40, tensions=5, level=4)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")

    selected = cycle.select_topic(
        ["caloric_restriction", "metformin"],
        tmp_path / cycle.LEDGER_DIR,
        runs_root=tmp_path / "runs",
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

    def fake_synthesis(topic: str, out_dir: Path, *, dry_run: bool, timeout: int | None = None, revision_feedback: str | None = None) -> int:
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


def test_cycle_seeds_missing_quant_claim_corpus_before_synthesis(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "new_topic", corpus=False, target_journal=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    calls: dict[str, Any] = {}

    def fake_corpus(topic: str, *, dry_run: bool, timeout: int | None = None) -> dict[str, Any]:
        calls["corpus"] = {"topic": topic, "dry_run": dry_run, "timeout": timeout}
        return {"status": "corpus_seeded", "n_quant_claims": 7}

    def fake_synthesis(topic: str, out_dir: Path, *, dry_run: bool, timeout: int | None = None, revision_feedback: str | None = None) -> int:
        calls["synthesis"] = {"topic": topic, "out_dir": out_dir.name}
        out_dir.mkdir(parents=True)
        return 0

    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-05-24",
        run_synthesis=True,
        submit=True,
        remote_loader=lambda: (set(), None),
        submit_cycle=lambda **_kwargs: {"status": "submitted_to_researka", "submitted": 1, "published": 0},
        ensure_corpus=fake_corpus,
        timeout=99,
    )

    assert ledger["status"] == "submitted_to_researka"
    assert calls["corpus"] == {"topic": "new_topic", "dry_run": False, "timeout": 99}
    assert calls["synthesis"]["topic"] == "new_topic"
    assert ledger["corpus"]["status"] == "corpus_seeded"


def test_cycle_skips_empty_seed_and_tries_next_topic(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "aaa_empty", corpus=False, target_journal=True)
    _topic(tmp_path, "zzz_seeded", corpus=False, target_journal=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    synthesis_topics: list[str] = []

    def fake_corpus(topic: str, *, dry_run: bool, timeout: int | None = None) -> dict[str, Any]:
        if topic == "aaa_empty":
            return {"status": "corpus_seed_empty", "n_quant_claims": 0}
        return {"status": "corpus_seeded", "n_quant_claims": 8}

    def fake_synthesis(topic: str, out_dir: Path, *, dry_run: bool, timeout: int | None = None, revision_feedback: str | None = None) -> int:
        synthesis_topics.append(topic)
        out_dir.mkdir(parents=True)
        return 0

    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-05-24",
        run_synthesis=True,
        submit=True,
        remote_loader=lambda: (set(), None),
        submit_cycle=lambda **_kwargs: {"status": "submitted_to_researka", "submitted": 1, "published": 0},
        ensure_corpus=fake_corpus,
        max_attempts=2,
    )

    assert ledger["status"] == "submitted_to_researka"
    assert ledger["attempts"][0]["submit_status"] == "corpus_seed_empty"
    assert ledger["attempts"][0]["failure_class"] == "B_corpus_fixable"
    assert synthesis_topics == ["zzz_seeded"]


def test_corpus_seed_failure_is_corpus_fixable(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")

    def fail_run(*_args: Any, **_kwargs: Any) -> None:
        raise OSError("offline")

    monkeypatch.setattr(cycle.subprocess, "run", fail_run)

    result = cycle._ensure_topic_corpus("new_topic", dry_run=False)

    assert result["status"] == "corpus_seed_failed"
    assert result["n_quant_claims"] == 0
    assert cycle._failure_class(result["status"]) == "B_corpus_fixable"


def test_ensure_topic_corpus_counts_seeded_quant_claims(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    seen: dict[str, Any] = {}

    def fake_run(cmd: list[str], **_kwargs: Any) -> Any:
        seen["cmd"] = cmd
        qdir = cycle.CORPORA / "new_topic" / "quant_claims"
        qdir.mkdir(parents=True)
        _write_json(qdir / "seed.quant_claims.json", {"paper_id": "seed", "claims": []})
        return cycle.subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(cycle.subprocess, "run", fake_run)

    result = cycle._ensure_topic_corpus("new_topic", dry_run=False)

    assert result["status"] == "corpus_seeded"
    assert result["n_quant_claims_before"] == 0
    assert result["n_quant_claims"] == 1
    assert seen["cmd"][2:4] == ["--topic", "new_topic"]
    assert seen["cmd"][-4:] == ["--limit", str(cycle.AUTO_SEED_LIMIT), "--max-per-source", str(cycle.AUTO_SEED_LIMIT)]
    assert "seed_topic_corpus.py" in seen["cmd"][1]
    assert result["seed_limit"] == cycle.AUTO_SEED_LIMIT


def test_cycle_separates_attempted_topic_from_submitted_bridge_candidate(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "acarbose")
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    runs: list[str] = []

    def fake_synthesis(topic: str, out_dir: Path, *, dry_run: bool, timeout: int | None = None, revision_feedback: str | None = None) -> int:
        runs.append(out_dir.name)
        out_dir.mkdir(parents=True)
        return 0

    def fake_submit(**_kwargs: Any) -> dict[str, Any]:
        return {
            "status": "submitted_to_researka",
            "submitted": 1,
            "published": 0,
            "candidate": {"topic": "rapamycin", "run": "synthesis-rapamycin-v06-DAILY-R2"},
            "considered": [
                {"run": runs[-1], "status": "audit_not_all_green"},
                {"run": "synthesis-rapamycin-v06-DAILY-R2", "status": "eligible"},
            ],
        }

    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-05-24",
        run_synthesis=True,
        submit=True,
        remote_loader=lambda: (set(), None),
        submit_cycle=fake_submit,
        max_revise_attempts=1,
    )

    attempt = ledger["attempts"][0]
    assert ledger["submitted"] == 1
    assert ledger["attempted_topic"] == "acarbose"
    assert ledger["submitted_topic"] == "rapamycin"
    assert attempt["topic"] == "acarbose"
    assert attempt["gate_status"] == "audit_not_all_green"
    assert attempt["submitted"] == 0
    assert attempt["submit_status"] == "current_run_not_submitted"
    assert attempt["bridge_status"] == "submitted_to_researka"


def test_cycle_salvages_daily_slot_with_next_topic(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "acarbose")
    _topic(tmp_path, "creatine")
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    topics: list[str] = []
    submit_calls = 0

    def fake_synthesis(topic: str, out_dir: Path, *, dry_run: bool, timeout: int | None = None, revision_feedback: str | None = None) -> int:
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
        max_revise_attempts=1,
    )

    assert ledger["status"] == "submitted_to_researka"
    assert topics == ["acarbose", "creatine"]
    assert [a["submit_status"] for a in ledger["attempts"]] == [
        "no_eligible_research_paper",
        "submitted_to_researka",
    ]


def test_cycle_retries_same_topic_before_next_topic(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "rapamycin")
    _topic(tmp_path, "creatine")
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    topics: list[str] = []
    runs: list[str] = []
    submit_calls = 0

    def fake_synthesis(topic: str, out_dir: Path, *, dry_run: bool, timeout: int | None = None, revision_feedback: str | None = None) -> int:
        topics.append(topic)
        runs.append(out_dir.name)
        out_dir.mkdir(parents=True)
        return 0

    def fake_submit(**_kwargs: Any) -> dict[str, Any]:
        nonlocal submit_calls
        submit_calls += 1
        if submit_calls < 3:
            return {
                "status": "no_eligible_research_paper",
                "submitted": 0,
                "published": 0,
                "considered": [{"run": runs[-1], "status": "journal_surface_not_passed"}],
            }
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
        max_revise_attempts=3,
    )

    assert ledger["status"] == "submitted_to_researka"
    assert topics == ["creatine", "creatine", "creatine"]
    assert [a["revise_attempt"] for a in ledger["attempts"]] == [1, 2, 3]
    assert "R2" in ledger["attempts"][1]["out_dir"]
    assert "R3" in ledger["attempts"][2]["out_dir"]


def test_cycle_regenerates_after_researka_rejection_before_rotating(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "rapamycin", target_journal=True)
    _topic(tmp_path, "creatine", target_journal=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    topics: list[str] = []
    runs: list[str] = []
    feedback_seen: list[str | None] = []
    submit_calls = 0

    def fake_synthesis(topic: str, out_dir: Path, *, dry_run: bool, timeout: int | None = None, revision_feedback: str | None = None) -> int:
        topics.append(topic)
        runs.append(out_dir.name)
        feedback_seen.append(revision_feedback)
        out_dir.mkdir(parents=True)
        return 0

    def fake_submit(**_kwargs: Any) -> dict[str, Any]:
        nonlocal submit_calls
        submit_calls += 1
        if submit_calls == 1:
            return {
                "status": "submission_rejected_by_researka",
                "submitted": 0,
                "published": 0,
                "revision_feedback": "Rejected: narrow the scope and resubmit.",
                "considered": [{"run": runs[-1], "status": "eligible"}],
            }
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
        max_revise_attempts=3,
    )

    assert ledger["status"] == "submitted_to_researka"
    assert topics == ["creatine", "creatine"]
    assert feedback_seen == [None, "Rejected: narrow the scope and resubmit."]
    assert ledger["attempts"][0]["gate_status"] == "submission_rejected_by_researka"
    assert ledger["attempts"][0]["failure_class"] == "C_writer_fixable"
    assert ledger["attempts"][1]["submitted"] == 1


def test_cycle_applies_researka_revision_feedback_on_same_topic_retry(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "rapamycin", target_journal=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    feedback_seen: list[str | None] = []
    runs: list[str] = []
    submit_calls = 0

    def fake_synthesis(
        topic: str,
        out_dir: Path,
        *,
        dry_run: bool,
        timeout: int | None = None,
        revision_feedback: str | None = None,
    ) -> int:
        feedback_seen.append(revision_feedback)
        runs.append(out_dir.name)
        out_dir.mkdir(parents=True)
        return 0

    def fake_submit(**_kwargs: Any) -> dict[str, Any]:
        nonlocal submit_calls
        submit_calls += 1
        if submit_calls == 1:
            return {
                "status": "submission_revise_requested",
                "submitted": 0,
                "published": 0,
                "revision_feedback": "Revise headline and resubmit.",
                "considered": [{"run": runs[-1], "status": "eligible"}],
            }
        return {"status": "submitted_to_researka", "submitted": 1, "published": 0}

    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-05-24",
        run_synthesis=True,
        submit=True,
        remote_loader=lambda: (set(), None),
        submit_cycle=fake_submit,
        topic="rapamycin",
        max_revise_attempts=3,
    )

    assert ledger["status"] == "submitted_to_researka"
    assert feedback_seen == [None, "Revise headline and resubmit."]
    assert ledger["attempts"][0]["failure_class"] == "C_writer_fixable"
    assert ledger["attempts"][0]["revision_feedback_received"] is True
    assert ledger["attempts"][1]["revision_feedback_applied"] is True


def test_cycle_preflights_insufficient_prior_corpus_before_synthesis(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "aaa_thin_topic", target_journal=True)
    _topic(tmp_path, "zzz_solid_topic", target_journal=True)
    _prior_run(tmp_path, "aaa_thin_topic", receipts=6, tensions=0, primary=0)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    topics: list[str] = []

    def fake_synthesis(topic: str, out_dir: Path, *, dry_run: bool, timeout: int | None = None, revision_feedback: str | None = None) -> int:
        topics.append(topic)
        out_dir.mkdir(parents=True)
        return 0

    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-05-24",
        run_synthesis=True,
        submit=True,
        remote_loader=lambda: (set(), None),
        submit_cycle=lambda **_kwargs: {"status": "submitted_to_researka", "submitted": 1, "published": 0},
        max_attempts=2,
    )

    assert topics == ["zzz_solid_topic"]
    assert ledger["attempts"][0]["submit_status"] == "preflight_insufficient_corpus"
    assert ledger["attempts"][0]["failure_class"] == "B_corpus_fixable"
    assert ledger["status"] == "submitted_to_researka"


def test_cycle_preflights_overbroad_prior_corpus_before_synthesis(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "aaa_mega_topic", target_journal=True)
    _topic(tmp_path, "zzz_solid_topic", target_journal=True)
    _prior_run(tmp_path, "aaa_mega_topic", receipts=600, tensions=60_000, primary=10)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    topics: list[str] = []

    def fake_synthesis(topic: str, out_dir: Path, *, dry_run: bool, timeout: int | None = None, revision_feedback: str | None = None) -> int:
        topics.append(topic)
        out_dir.mkdir(parents=True)
        return 0

    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-05-24",
        run_synthesis=True,
        submit=True,
        remote_loader=lambda: (set(), None),
        submit_cycle=lambda **_kwargs: {"status": "submitted_to_researka", "submitted": 1, "published": 0},
        max_attempts=2,
    )

    assert topics == ["zzz_solid_topic"]
    assert any("split topic" in r for r in ledger["attempts"][0]["preflight"]["reasons"])


def test_preflight_recent_failure_does_not_block_publication_track(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "caloric_restriction", target_journal=True)
    _prior_run(tmp_path, "caloric_restriction", receipts=40, tensions=10, primary=2)
    ledger_dir = tmp_path / "runs" / cycle.LEDGER_DIR
    _write_json(ledger_dir / "2026-05-24.json", {
        "started_at": _recent_start(),
        "attempts": [{"topic": "caloric_restriction", "submitted": 0}],
    })
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")

    preflight = cycle._preflight("caloric_restriction", tmp_path / "runs", ledger_dir)

    assert preflight["passed"] is True
    assert preflight["publication_track"] is True
    assert preflight["recent_failed_attempts"] == 1
    assert preflight["reasons"] == []


def test_preflight_recent_failure_still_blocks_exploration_track(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "acarbose")
    _prior_run(tmp_path, "acarbose", receipts=40, tensions=10, primary=2)
    ledger_dir = tmp_path / "runs" / cycle.LEDGER_DIR
    _write_json(ledger_dir / "2026-05-24.json", {
        "started_at": _recent_start(),
        "attempts": [{"topic": "acarbose", "submitted": 0}],
    })
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")

    preflight = cycle._preflight("acarbose", tmp_path / "runs", ledger_dir)

    assert preflight["passed"] is False
    assert preflight["publication_track"] is False
    assert preflight["recent_failed_attempts"] == 1
    assert "recent_failed_attempts=1" in preflight["reasons"][0]


def test_cycle_records_blocker_histogram_for_current_gate_failure(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "rapamycin", target_journal=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")

    runs: list[str] = []

    def fake_synthesis(topic: str, out_dir: Path, *, dry_run: bool, timeout: int | None = None, revision_feedback: str | None = None) -> int:
        runs.append(out_dir.name)
        out_dir.mkdir(parents=True)
        return 0

    def fake_submit(**_kwargs: Any) -> dict[str, Any]:
        return {
            "status": "no_eligible_research_paper",
            "submitted": 0,
            "published": 0,
            "considered": [{"run": runs[-1], "status": "audit_not_all_green"}],
        }

    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-05-24",
        run_synthesis=True,
        submit=True,
        remote_loader=lambda: (set(), None),
        submit_cycle=fake_submit,
        topic="rapamycin",
        max_revise_attempts=1,
    )

    histogram = json.loads((tmp_path / "runs" / cycle.LEDGER_DIR / cycle.BLOCKER_HISTOGRAM).read_text(encoding="utf-8"))
    assert ledger["attempts"][0]["gate_status"] == "audit_not_all_green"
    assert ledger["attempts"][0]["failure_class"] == "C_writer_fixable"
    assert histogram["blockers"]["audit_not_all_green"]["count"] == 1


def test_blocker_histogram_marks_repeated_compiler_failure_as_auto_fix_candidate(tmp_path: Path) -> None:
    ledger_dir = tmp_path / "runs" / cycle.LEDGER_DIR
    row = {"topic": "rapamycin", "gate_status": "journal_surface_not_passed", "out_dir": "run"}

    for i in range(cycle.HISTOGRAM_ISSUE_THRESHOLD):
        cycle._record_blockers(ledger_dir, f"2026-05-{24 + i:02d}", [row])

    histogram = json.loads((ledger_dir / cycle.BLOCKER_HISTOGRAM).read_text(encoding="utf-8"))
    blocker = histogram["blockers"]["journal_surface_not_passed"]
    assert blocker["github_issue_candidate"] is True
    assert blocker["auto_fix_candidate"] is True
    assert blocker["samples"][0]["gate_status"] == "journal_surface_not_passed"


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
