from __future__ import annotations

import datetime as dt
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import daily_research_paper_cycle as cycle  # type: ignore[import-not-found]  # noqa: E402


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _words(n: int, prefix: str) -> str:
    return " ".join(f"{prefix}{i}" for i in range(n))


def _surface_passing_paper(*, discussion_extra: str = "") -> str:
    return (
        f"## Abstract\n\n{_words(160, 'abstract')}\n\n"
        f"## Introduction\n\nSmith 2024 provides prior context. {_words(410, 'intro')}\n\n"
        f"## Background\n\n{_words(310, 'background')}\n\n"
        "## Quantitative Evidence Index — topic\n\n"
        "| Study | Endpoint | Arm | Value | Type | Statistic |\n"
        "|---|---|---|---|---|---|\n"
        "| Smith 2024 | fasting glucose | treatment | 89 mg/dL | mg/dL | mean |\n\n"
        f"## Methods\n\n{_words(310, 'methods')}\n\n"
        f"## Results\n\n{_words(510, 'results')}\n\n"
        f"## Cross-Domain Synthesis\n\n{_words(860, 'cross')}\n\n"
        "## Discussion\n\n"
        "**Thesis:** This synthesis takes a defensible bounded position. "
        f"{discussion_extra} {_words(820, 'discussion')}\n\n"
        f"**Resolution criteria:** Future trials would settle the claim. {_words(40, 'resolution')}\n\n"
        f"## Limitations\n\n{_words(260, 'limits')}\n\n"
        f"## Conclusion\n\n{_words(260, 'conclusion')}\n\n"
        "## References\n\n- Smith 2024.\n"
    )


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
        for i in range(cycle.PREFLIGHT_MIN_QUANT_CLAIMS):
            _write_json(qdir / f"seed-{i}.quant_claims.json", {"paper_id": f"seed-{i}", "claims": []})


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
    _write_json(tmp_path / cycle.submit_bridge.LEDGER_DIR / "_submitted_fingerprints.json", [{
        "date": dt.datetime.now(dt.UTC).isoformat(),
        "topic": "aerobic_exercise",
        "fingerprint": "sha256:abc",
    }])

    selected = cycle.select_topic(
        ["aerobic_exercise", "creatine", "metformin"],
        ledger_dir,
        remote_seen={"title:researka agent-certified evidence brief: aerobic exercise and human geroscience"},
    )

    assert selected == "metformin"


def test_select_topic_allows_submitted_topic_after_cooldown(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "aerobic_exercise", target_journal=True)
    runs_root = tmp_path / "runs"
    ledger_dir = runs_root / cycle.LEDGER_DIR
    old = dt.datetime.now(dt.UTC) - dt.timedelta(days=cycle.PUBLISHED_TOPIC_COOLDOWN_DAYS + 1)
    _write_json(runs_root / cycle.submit_bridge.LEDGER_DIR / "_submitted_fingerprints.json", [{
        "date": old.isoformat(),
        "topic": "aerobic_exercise",
        "fingerprint": "sha256:abc",
    }])
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")

    selected = cycle.select_topic(
        ["aerobic_exercise"],
        ledger_dir,
        runs_root=runs_root,
        remote_seen={"title:researka agent-certified evidence brief: aerobic exercise and human geroscience"},
    )

    assert selected == "aerobic_exercise"


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


def test_cycle_restricts_real_submit_bridge_to_current_run(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "creatine")
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle.submit_bridge, "_token", lambda: ("token", "TOKEN_ENV"))
    calls: dict[str, Any] = {}

    def fake_synthesis(topic: str, out_dir: Path, *, dry_run: bool, timeout: int | None = None, revision_feedback: str | None = None) -> int:
        out_dir.mkdir(parents=True)
        (out_dir / "full_paper.md").write_text("# Research Synthesis: Creatine — full paper\n", encoding="utf-8")
        return 0

    def fake_submit_bridge(**kwargs: Any) -> dict[str, Any]:
        calls.update(kwargs)
        return {"status": "no_eligible_research_paper", "submitted": 0, "published": 0}

    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)
    monkeypatch.setattr(cycle.submit_bridge, "run_cycle", fake_submit_bridge)

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-05-29",
        run_synthesis=True,
        submit=True,
        topic="creatine",
        remote_loader=lambda: (set(), None),
    )

    assert ledger["status"] == "synthesis_completed_no_submission"
    assert calls["candidate_run"] == tmp_path / "runs" / ledger["attempts"][-1]["out_dir"]


def test_run_synthesis_passes_revision_feedback_into_full_pipeline(tmp_path: Path, monkeypatch) -> None:
    seen: dict[str, Any] = {}

    class Result:
        returncode = 0

    def fake_run(*args: Any, **kwargs: Any) -> Result:
        seen["args"] = args
        seen["kwargs"] = kwargs
        return Result()

    monkeypatch.setattr(cycle.subprocess, "run", fake_run)

    rc = cycle._run_synthesis(
        "aspirin_geroprotection",
        tmp_path / "revised-run",
        dry_run=False,
        timeout=123,
        revision_feedback="Add clinical-use caveat.",
        review_type_override="thin_corpus_brief",
    )

    cmd = seen["args"][0]
    assert rc == 0
    assert cmd[:4] == [sys.executable, "scripts/run_v06_synthesis.py", "--topic", "aspirin_geroprotection"]
    assert seen["kwargs"]["cwd"] == cycle.ROOT
    assert seen["kwargs"]["timeout"] == 123
    assert seen["kwargs"]["env"]["RESEARKA_REVISION_FEEDBACK"] == "Add clinical-use caveat."
    assert seen["kwargs"]["env"]["RESEARCH_AGENT_REVIEW_TYPE_OVERRIDE"] == "thin_corpus_brief"


def test_cycle_seeds_missing_quant_claim_corpus_before_synthesis(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "new_topic", corpus=False, target_journal=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    calls: dict[str, Any] = {}

    def fake_corpus(topic: str, *, dry_run: bool, timeout: int | None = None) -> dict[str, Any]:
        calls["corpus"] = {"topic": topic, "dry_run": dry_run, "timeout": timeout}
        return {"status": "corpus_seeded", "n_quant_claims": cycle.PREFLIGHT_MIN_QUANT_CLAIMS}

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
        return {"status": "corpus_seeded", "n_quant_claims": cycle.PREFLIGHT_MIN_QUANT_CLAIMS}

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


def test_cycle_skips_thin_quant_corpus_before_synthesis(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "thin_topic", corpus=False, target_journal=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")

    def no_synthesis(*_args: Any, **_kwargs: Any) -> int:
        raise AssertionError("thin corpus should not reach synthesis")

    monkeypatch.setattr(cycle, "_run_synthesis", no_synthesis)
    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-05-24",
        run_synthesis=True,
        submit=True,
        remote_loader=lambda: (set(), None),
        submit_cycle=lambda **_kwargs: {"status": "submitted_to_researka", "submitted": 1, "published": 0},
        ensure_corpus=lambda *_args, **_kwargs: {"status": "corpus_seeded", "n_quant_claims": 3},
        max_attempts=1,
    )

    assert ledger["status"] == "preflight_skipped_no_submission"
    assert ledger["attempts"][0]["submit_status"] == "preflight_thin_quant_corpus"
    assert ledger["attempts"][0]["failure_class"] == "B_corpus_fixable"
    assert ledger["attempts"][0]["preflight"]["reasons"] == [f"n_quant_claims=3 < {cycle.PREFLIGHT_MIN_QUANT_CLAIMS}"]


def test_paper_strategy_skips_terminal_sparse_researka_feedback() -> None:
    strategy = cycle._paper_strategy(
        {"status": "corpus_ready", "n_quant_claims": 37},
        {"has_manifest": True, "n_receipts": 37, "n_tensions": 113, "n_primary_tier": 1},
        "The evidence base is mixed and sparse, which precludes a strong accept verdict. No material revisions.",
    )

    assert strategy["action"] == "skip_topic"
    assert strategy["selected"]["name"] == "skip_topic"
    assert strategy["reason"] == "terminal_sparse_researka_feedback"


def test_cycle_skips_terminal_sparse_revision_before_resynthesis(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "colchicine_inflammaging", target_journal=True)
    source = _prior_run(tmp_path, "colchicine_inflammaging", receipts=37, tensions=113, primary=1, level=5)
    paper = source / "full_paper.md"
    paper.write_text("# Research Synthesis: Colchicine Inflammaging\n", encoding="utf-8")
    _write_json(tmp_path / "runs" / cycle.submit_bridge.LEDGER_DIR / "_submitted_fingerprints.json", [{
        "run": source.name,
        "topic": "colchicine_inflammaging",
        "fingerprint": cycle.submit_bridge._sha256(paper),
    }])
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_run_synthesis", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should not rerender terminal sparse revise")))
    request = {
        "artifactId": "colchicine-review",
        "title": "Research Synthesis: Colchicine Inflammaging",
        "feedback": "The evidence base is mixed and sparse, which precludes a strong accept verdict. No material revisions.",
    }

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-05-29",
        run_synthesis=True,
        submit=True,
        remote_loader=lambda: (set(), None),
        revision_loader=lambda: ([request], None),
        submit_cycle=lambda **_kwargs: {"status": "submitted_to_researka", "submitted": 1, "published": 0},
        max_attempts=1,
    )

    assert ledger["status"] == "strategy_skipped_no_submission"
    assert ledger["attempts"][0]["submit_status"] == "strategy_evidence_insufficient"
    assert ledger["attempts"][0]["paper_strategy"]["selected"]["name"] == "skip_topic"
    assert (tmp_path / "runs" / cycle.LEDGER_DIR / cycle.HANDLED_REVISIONS).exists()


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


def test_cycle_polls_revision_after_submit_and_resubmits(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "ace_inhibitors_aging", target_journal=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    feedback_seen: list[str | None] = []
    run_names: list[str] = []
    loader_calls = 0
    submit_calls = 0

    title = "Research Synthesis: ACE Inhibitors Aging — full paper"

    def fake_synthesis(
        topic: str,
        out_dir: Path,
        *,
        dry_run: bool,
        timeout: int | None = None,
        revision_feedback: str | None = None,
    ) -> int:
        assert topic == "ace_inhibitors_aging"
        feedback_seen.append(revision_feedback)
        run_names.append(out_dir.name)
        out_dir.mkdir(parents=True)
        (out_dir / "full_paper.md").write_text(f"# {title}\n\n## Abstract\n\nA.", encoding="utf-8")
        return 0

    def fake_submit(**kwargs: Any) -> dict[str, Any]:
        nonlocal submit_calls
        submit_calls += 1
        runs_root = kwargs["runs_root"]
        paper = runs_root / run_names[-1] / "full_paper.md"
        _write_json(runs_root / cycle.submit_bridge.LEDGER_DIR / "_submitted_fingerprints.json", [{
            "run": run_names[-1],
            "topic": "ace_inhibitors_aging",
            "fingerprint": cycle.submit_bridge._sha256(paper),
        }])
        return {"status": "submitted_to_researka", "submitted": 1, "published": 0}

    def fake_revision_loader() -> tuple[list[dict[str, Any]], str | None]:
        nonlocal loader_calls
        loader_calls += 1
        if loader_calls == 1:
            return [], None
        return ([{
            "artifactId": "ace-review-1",
            "title": title,
            "feedback": "Define Contextual Other, dedupe repeated blocks, and trim minor rows.",
        }], None)

    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-05-28",
        run_synthesis=True,
        submit=True,
        remote_loader=lambda: (set(), None),
        revision_loader=fake_revision_loader,
        submit_cycle=fake_submit,
        max_revise_attempts=3,
        decision_poll_seconds=1,
        decision_poll_interval_seconds=1,
        decision_sleep=lambda _seconds: None,
    )

    assert ledger["status"] == "submitted_to_researka"
    assert submit_calls == 2
    assert feedback_seen == [None, "Define Contextual Other, dedupe repeated blocks, and trim minor rows."]
    assert ledger["attempts"][0]["remote_revision_requested"] is True
    assert ledger["attempts"][1]["revision_feedback_applied"] is True
    assert ledger["attempts"][1]["existing_work_reused"] is False
    sidecar = json.loads((tmp_path / "runs" / ledger["attempts"][1]["out_dir"] / "researka_revision_request.json").read_text(encoding="utf-8"))
    assert sidecar["source_run"] == run_names[0]
    handled = json.loads((tmp_path / "runs" / cycle.LEDGER_DIR / cycle.HANDLED_REVISIONS).read_text(encoding="utf-8"))
    assert handled["handled"][0]["key"] == cycle.submit_bridge._title_marker(title)  # per-paper key


def test_cycle_prioritizes_delayed_researka_revision_request(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "aspirin_geroprotection", target_journal=True)
    _topic(tmp_path, "rapamycin", target_journal=True)
    source_run = _prior_run(tmp_path, "aspirin_geroprotection", receipts=57, tensions=274, level=5)
    paper = source_run / "full_paper.md"
    paper.write_text(
        "# Research Synthesis: Aspirin Geroprotection — full paper\n\n## Abstract\n\nA.",
        encoding="utf-8",
    )
    fingerprint = cycle.submit_bridge._sha256(paper)
    _write_json(tmp_path / "runs" / cycle.submit_bridge.LEDGER_DIR / "_submitted_fingerprints.json", [{
        "date": "2026-05-27",
        "run": source_run.name,
        "topic": "aspirin_geroprotection",
        "fingerprint": fingerprint,
    }])
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    synthesis_calls: list[str] = []
    feedback_seen: list[str | None] = []

    def fake_synthesis(
        topic: str,
        out_dir: Path,
        *,
        dry_run: bool,
        timeout: int | None = None,
        revision_feedback: str | None = None,
    ) -> int:
        synthesis_calls.append(topic)
        feedback_seen.append(revision_feedback)
        out_dir.mkdir(parents=True)
        (out_dir / "full_paper.md").write_text(
            "# Research Synthesis: Aspirin Geroprotection — full paper\n\n## Abstract\n\nA.",
            encoding="utf-8",
        )
        return 0

    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-05-28",
        run_synthesis=True,
        submit=True,
        remote_loader=lambda: (set(), None),
        revision_loader=lambda: ([{
            "artifactId": "review-art-1",
            "submissionId": "review-sub-1",
            "title": "Research Synthesis: Aspirin Geroprotection — full paper",
            "feedback": "Add clinical-use caveat and resubmit.",
        }], None),
        submit_cycle=lambda **_kwargs: {"status": "submitted_to_researka", "submitted": 1, "published": 0},
    )

    assert ledger["status"] == "submitted_to_researka"
    # Interleave: the delayed revise is handled first, then the cycle still ships a
    # fresh paper so a revise backlog cannot starve new-topic output.
    assert synthesis_calls[0] == "aspirin_geroprotection"
    assert feedback_seen[0] == "Add clinical-use caveat and resubmit."
    assert "rapamycin" in synthesis_calls
    assert ledger["submitted"] == 2
    assert ledger["revision_source"]["artifactId"] == "review-art-1"
    assert ledger["attempts"][0]["revision_feedback_applied"] is True
    assert ledger["attempts"][0]["existing_work_reused"] is False
    sidecar = json.loads((tmp_path / "runs" / ledger["attempts"][0]["out_dir"] / "researka_revision_request.json").read_text(encoding="utf-8"))
    assert sidecar["source_run"] == source_run.name
    handled = json.loads((tmp_path / "runs" / cycle.LEDGER_DIR / cycle.HANDLED_REVISIONS).read_text(encoding="utf-8"))
    assert handled["handled"][0]["key"] == cycle.submit_bridge._title_marker(
        "Research Synthesis: Aspirin Geroprotection — full paper")  # per-paper key


def test_failed_delayed_revision_remains_pending_for_next_cycle(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "aspirin_geroprotection", target_journal=True)
    source_run = _prior_run(tmp_path, "aspirin_geroprotection", receipts=57, tensions=274, level=5)
    paper = source_run / "full_paper.md"
    paper.write_text("# Research Synthesis: Aspirin Geroprotection — full paper\n", encoding="utf-8")
    _write_json(tmp_path / "runs" / cycle.submit_bridge.LEDGER_DIR / "_submitted_fingerprints.json", [{
        "run": source_run.name,
        "topic": "aspirin_geroprotection",
        "fingerprint": cycle.submit_bridge._sha256(paper),
    }])
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")

    monkeypatch.setattr(cycle, "_run_synthesis", lambda *_args, **_kwargs: 4)
    request = {
        "artifactId": "review-art-1",
        "title": "Research Synthesis: Aspirin Geroprotection — full paper",
        "feedback": "Add caveat.",
    }

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-05-28",
        run_synthesis=True,
        submit=True,
        remote_loader=lambda: (set(), None),
        revision_loader=lambda: ([request], None),
        submit_cycle=lambda **_kwargs: {"status": "no_eligible_research_paper", "submitted": 0, "published": 0},
        max_revise_attempts=1,
    )

    assert ledger["attempts"][0]["topic"] == "aspirin_geroprotection"
    assert ledger["attempts"][0]["existing_work_reused"] is False
    assert ledger["attempts"][0]["synthesis_return_code"] == 4
    assert not (tmp_path / "runs" / cycle.LEDGER_DIR / cycle.HANDLED_REVISIONS).exists()
    pending, error = cycle._pending_remote_revision(
        tmp_path / "runs",
        tmp_path / "runs" / cycle.LEDGER_DIR,
        loader=lambda: ([request], None),
    )
    assert error is None
    assert pending and pending["artifactId"] == "review-art-1"


def test_handled_delayed_revision_is_not_reprocessed(tmp_path: Path) -> None:
    source_run = _prior_run(tmp_path, "aspirin_geroprotection", receipts=57, tensions=274, level=5)
    paper = source_run / "full_paper.md"
    paper.write_text("# Research Synthesis: Aspirin Geroprotection — full paper\n", encoding="utf-8")
    ledger_dir = tmp_path / "runs" / cycle.LEDGER_DIR
    _write_json(ledger_dir / "_submitted_fingerprints.json", [{
        "run": source_run.name,
        "topic": "aspirin_geroprotection",
        "fingerprint": cycle.submit_bridge._sha256(paper),
    }])
    _write_json(ledger_dir / cycle.HANDLED_REVISIONS, {"handled": [{"key": "review-art-1"}]})

    pending, error = cycle._pending_remote_revision(
        tmp_path / "runs",
        ledger_dir,
        loader=lambda: ([{
            "artifactId": "review-art-1",
            "title": "Research Synthesis: Aspirin Geroprotection — full paper",
            "feedback": "Add caveat.",
        }], None),
    )

    assert pending is None
    assert error is None


def test_handled_revision_ids_caps_after_max_rounds(tmp_path: Path) -> None:
    # A Researka revise is re-routable until the same PAPER (by title, since
    # Researka mints a new artifactId per submission) has been handled
    # MAX_REVISE_ROUNDS times; only then is it permanently handled so it stops
    # monopolising the cycle. Rounds across distinct artifactIds still count.
    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    marker = cycle.submit_bridge._title_marker("Research Synthesis: Foo — full paper")

    def _write_rounds(occurrences: int) -> None:
        # distinct artifactId each round, same title -> must still accumulate
        _write_json(ledger_dir / cycle.HANDLED_REVISIONS, {"handled": [
            {"key": f"art-{i}", "title": "Research Synthesis: Foo — full paper"}
            for i in range(occurrences)
        ]})

    _write_rounds(cycle.MAX_REVISE_ROUNDS - 1)
    assert marker not in cycle._handled_revision_ids(ledger_dir)  # below cap -> re-routable
    _write_rounds(cycle.MAX_REVISE_ROUNDS)
    assert marker in cycle._handled_revision_ids(ledger_dir)  # at cap -> permanently handled


def _patch_reviews(monkeypatch, rows: list[dict[str, Any]]) -> None:
    class _Resp:
        def __enter__(self) -> "_Resp":
            return self

        def __exit__(self, *_a: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps({"reviews": rows}).encode("utf-8")

    monkeypatch.setattr(urllib.request, "urlopen", lambda *_a, **_k: _Resp())


def test_remote_revision_keeps_only_latest_review_per_title(monkeypatch) -> None:
    # Researka issues a new artifactId per submission; a stale revise must not
    # be re-routed when a fresher review exists for the same paper title.
    title = "Research Synthesis: Brain Age MRI — full paper"
    base = {"artifactType": "research_paper", "agentId": "agent-v3-full-paper", "title": title}
    _patch_reviews(monkeypatch, [
        {**base, "decision": "revise", "reviewedAt": "2026-05-29T13:51:08+04:00", "requiredRevisions": ["stale"]},
        {**base, "decision": "reject", "reviewedAt": "2026-05-29T15:33:15+04:00", "requiredRevisions": ["rejected"]},
        {**base, "decision": "revise", "reviewedAt": "2026-05-29T17:31:01+04:00", "requiredRevisions": ["fresh"]},
    ])
    out, err = cycle._remote_revision_requests("http://reviews.test")
    assert err is None
    assert [r["feedback"] for r in out] == ["fresh"]  # only the latest revise, not the stale one


def test_remote_revision_suppressed_when_latest_decision_is_reject(monkeypatch) -> None:
    title = "Research Synthesis: Brain Age MRI — full paper"
    base = {"artifactType": "research_paper", "agentId": "agent-v3-full-paper", "title": title}
    _patch_reviews(monkeypatch, [
        {**base, "decision": "revise", "reviewedAt": "2026-05-29T13:51:08+04:00", "requiredRevisions": ["stale"]},
        {**base, "decision": "reject", "reviewedAt": "2026-05-29T17:31:01+04:00", "requiredRevisions": ["rejected"]},
    ])
    out, err = cycle._remote_revision_requests("http://reviews.test")
    assert err is None
    assert out == []  # latest decision is reject -> no revise routed


def _seed_submitted_run(runs: Path, topic: str, title_line: str) -> Path:
    run = runs / f"synthesis-{topic}-v06-DAILY-2026-05-29T00-00-00Z"
    run.mkdir(parents=True)
    (run / "full_paper.md").write_text(f"{title_line}\n\nbody\n", encoding="utf-8")
    _write_json(runs / cycle.submit_bridge.LEDGER_DIR / "_submitted_fingerprints.json",
                [{"run": run.name, "topic": topic, "fingerprint": "sha256:x"}])
    return run


def test_rejected_topics_excludes_topic_with_latest_reject(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    _seed_submitted_run(runs, "foo_topic", "# Research Synthesis: Foo Topic")
    latest = {"k": {"decision": "reject", "title": "Research Synthesis: Foo Topic"}}
    out = cycle._rejected_topics(runs, loader=lambda: (latest, None))
    assert out == {"foo_topic"}  # reject is terminal-for-topic


def test_rejected_topics_ignores_topic_whose_latest_is_revise(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    _seed_submitted_run(runs, "foo_topic", "# Research Synthesis: Foo Topic")
    latest = {"k": {"decision": "revise", "title": "Research Synthesis: Foo Topic"}}
    out = cycle._rejected_topics(runs, loader=lambda: (latest, None))
    assert out == set()  # latest is revise, not reject -> still allowed


def test_cycle_ignores_unmatched_delayed_revision_request(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "aspirin_geroprotection", target_journal=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")

    pending, error = cycle._pending_remote_revision(
        tmp_path / "runs",
        tmp_path / "runs" / cycle.LEDGER_DIR,
        loader=lambda: ([{
            "artifactId": "alpha-1",
            "title": "Acarbose alpha memo",
            "feedback": "revise",
        }], None),
    )

    assert pending is None
    assert error is None


def test_remote_revision_requests_keeps_only_v3_research_paper_revisions(monkeypatch) -> None:
    payload = {
        "records": [
            {
                "artifactId": "v3-1",
                "artifactType": "research_paper",
                "agentId": "agent-v3-full-paper",
                "decision": "revise",
                "title": "Research Synthesis: Aspirin",
                "requiredRevisions": ["Add caveat.", "Reduce repetition."],
            },
            {"artifactId": "alpha-1", "artifactType": "alpha_memo", "agentId": "agent-v4-alpha-memo", "decision": "revise"},
            {"artifactId": "reject-1", "artifactType": "research_paper", "agentId": "agent-v3-full-paper", "decision": "reject"},
        ]
    }

    class Response:
        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(payload).encode()

    monkeypatch.setattr(cycle.urllib.request, "urlopen", lambda *_args, **_kwargs: Response())

    rows, error = cycle._remote_revision_requests("https://example.test/reviews")

    assert error is None
    assert [row["artifactId"] for row in rows] == ["v3-1"]
    assert rows[0]["feedback"] == "Add caveat.; Reduce repetition."


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


def test_cycle_reuses_existing_work_for_compiler_fixable_retry(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "allostatic_load", target_journal=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    synthesis_runs: list[str] = []
    submit_calls = 0

    def fake_synthesis(topic: str, out_dir: Path, *, dry_run: bool, timeout: int | None = None, revision_feedback: str | None = None) -> int:
        synthesis_runs.append(out_dir.name)
        out_dir.mkdir(parents=True)
        (out_dir / "full_paper.md").write_text(
            _surface_passing_paper(
                discussion_extra="This novel approach organizes the evidence without claiming treatment guidance.",
            ),
            encoding="utf-8",
        )
        return 0

    def fake_submit(**_kwargs: Any) -> dict[str, Any]:
        nonlocal submit_calls
        submit_calls += 1
        if submit_calls == 1:
            return {
                "status": "no_eligible_research_paper",
                "submitted": 0,
                "published": 0,
                "considered": [{"run": synthesis_runs[-1], "status": "journal_surface_not_passed"}],
            }
        return {"status": "submitted_to_researka", "submitted": 1, "published": 0}

    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-05-28",
        run_synthesis=True,
        submit=True,
        remote_loader=lambda: (set(), None),
        submit_cycle=fake_submit,
        topic="allostatic_load",
        max_revise_attempts=2,
    )

    assert ledger["status"] == "submitted_to_researka"
    assert synthesis_runs == [ledger["attempts"][0]["out_dir"]]
    assert ledger["attempts"][1]["existing_work_reused"] is True
    assert ledger["attempts"][1]["repair_reason"] == "journal_surface_not_passed"
    sidecar = json.loads((tmp_path / "runs" / ledger["attempts"][1]["out_dir"] / "internal_repair_request.json").read_text(encoding="utf-8"))
    assert sidecar["source_run"] == ledger["attempts"][0]["out_dir"]


def test_cycle_repairs_audit_failure_when_surface_also_failed(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "cgm_glucose_variability", target_journal=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    synthesis_runs: list[str] = []
    repair_reasons: list[str | None] = []
    submit_calls = 0

    def fake_synthesis(topic: str, out_dir: Path, *, dry_run: bool, timeout: int | None = None, revision_feedback: str | None = None) -> int:
        synthesis_runs.append(out_dir.name)
        out_dir.mkdir(parents=True)
        (out_dir / "full_paper.md").write_text("# Paper\n", encoding="utf-8")
        _write_json(out_dir / "full_paper.journal_surface.json", {"passed": False, "issues": [{"code": "duplicate_blocks"}]})
        return 0

    def fake_repair(source_dir: Path, out_dir: Path, **kwargs: Any) -> tuple[bool, str]:
        repair_reasons.append(kwargs.get("repair_reason"))
        out_dir.mkdir(parents=True)
        (out_dir / "full_paper.md").write_text((source_dir / "full_paper.md").read_text(encoding="utf-8"), encoding="utf-8")
        return True, ""

    def fake_submit(**_kwargs: Any) -> dict[str, Any]:
        nonlocal submit_calls
        submit_calls += 1
        if submit_calls == 1:
            return {
                "status": "no_eligible_research_paper",
                "submitted": 0,
                "published": 0,
                "considered": [{"run": synthesis_runs[-1], "status": "audit_not_all_green"}],
            }
        return {"status": "submitted_to_researka", "submitted": 1, "published": 0}

    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)
    monkeypatch.setattr(cycle, "_repair_existing_run", fake_repair)

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-05-28",
        run_synthesis=True,
        submit=True,
        remote_loader=lambda: (set(), None),
        submit_cycle=fake_submit,
        topic="cgm_glucose_variability",
        max_revise_attempts=2,
    )

    assert ledger["status"] == "submitted_to_researka"
    assert synthesis_runs == [ledger["attempts"][0]["out_dir"]]
    assert repair_reasons == ["journal_surface_not_passed"]
    assert ledger["attempts"][1]["existing_work_reused"] is True


def test_internal_repair_clears_surface_novelty_without_resynthesis(tmp_path: Path) -> None:
    source = tmp_path / "source"
    out = tmp_path / "out"
    source.mkdir()
    (source / "full_paper.md").write_text(
        _surface_passing_paper(
            discussion_extra="This novel approach organizes the evidence without claiming treatment guidance.",
        ),
        encoding="utf-8",
    )

    ok, error = cycle._repair_existing_run(source, out, repair_reason="journal_surface_not_passed")

    assert ok is True
    assert error == ""
    text = (out / "full_paper.md").read_text(encoding="utf-8")
    assert "novel approach" not in text.lower()
    assert "structured approach" in text.lower()
    sidecar = json.loads((out / "internal_repair_request.json").read_text(encoding="utf-8"))
    assert sidecar == {"source_run": "source", "reason": "journal_surface_not_passed"}


def test_internal_repair_noop_cleans_output_for_synthesis_fallback(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import agent.journal_finalizer as finalizer

    source = tmp_path / "source"
    out = tmp_path / "out"
    source.mkdir()
    (source / "full_paper.md").write_text(
        _surface_passing_paper(
            discussion_extra="This novel approach organizes the evidence without claiming treatment guidance.",
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(finalizer, "finalize_run", lambda _out_dir: None)

    ok, error = cycle._repair_existing_run(source, out, repair_reason="journal_surface_not_passed")

    assert ok is False
    assert error == "repair_noop"
    assert not out.exists()


def test_cycle_rewrites_for_writer_fixable_retry(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "rapamycin", target_journal=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    synthesis_runs: list[str] = []
    submit_calls = 0

    def fake_synthesis(topic: str, out_dir: Path, *, dry_run: bool, timeout: int | None = None, revision_feedback: str | None = None) -> int:
        synthesis_runs.append(out_dir.name)
        out_dir.mkdir(parents=True)
        (out_dir / "full_paper.md").write_text("# Paper\n\n## Abstract\n\nA.", encoding="utf-8")
        return 0

    def fake_submit(**_kwargs: Any) -> dict[str, Any]:
        nonlocal submit_calls
        submit_calls += 1
        if submit_calls == 1:
            return {
                "status": "no_eligible_research_paper",
                "submitted": 0,
                "published": 0,
                "considered": [{"run": synthesis_runs[-1], "status": "audit_not_all_green"}],
            }
        return {"status": "submitted_to_researka", "submitted": 1, "published": 0}

    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-05-28",
        run_synthesis=True,
        submit=True,
        remote_loader=lambda: (set(), None),
        submit_cycle=fake_submit,
        topic="rapamycin",
        max_revise_attempts=2,
    )

    assert ledger["status"] == "submitted_to_researka"
    assert len(synthesis_runs) == 2
    assert ledger["attempts"][1]["existing_work_reused"] is False


def test_cycle_downshifts_after_recent_numeric_density_failure(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "akkermansia_muciniphila", target_journal=True)
    prior = _prior_run(tmp_path, "akkermansia_muciniphila", receipts=40, tensions=8, primary=4)
    _write_json(prior / "full_paper.audit.json", {"checks": [{"name": "Q9_numeric_density", "passed": False}]})
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    overrides: list[str | None] = []

    def fake_synthesis(
        topic: str,
        out_dir: Path,
        *,
        dry_run: bool,
        timeout: int | None = None,
        revision_feedback: str | None = None,
        review_type_override: str | None = None,
    ) -> int:
        overrides.append(review_type_override)
        out_dir.mkdir(parents=True)
        return 0

    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-05-28",
        run_synthesis=True,
        submit=True,
        remote_loader=lambda: (set(), None),
        submit_cycle=lambda **_kwargs: {"status": "submitted_to_researka", "submitted": 1, "published": 0},
        topic="akkermansia_muciniphila",
    )

    assert overrides == ["thin_corpus_brief"]
    assert ledger["attempts"][0]["review_type_override"] == "thin_corpus_brief"


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
