from __future__ import annotations

import datetime as dt
import json
import sys
import urllib.request

import pytest
from pathlib import Path
from types import SimpleNamespace
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import daily_research_paper_cycle as cycle  # type: ignore[import-not-found]  # noqa: E402

_REAL_UNMET_REVISION_ASKS = cycle._unmet_revision_asks


def test_researka_revision_fingerprint_status_is_terminal_contract() -> None:
    assert "researka_revision_fingerprint" in cycle._TERMINAL_REVISION_STATUSES
    assert "research_revision_fingerprint" in cycle._TERMINAL_REVISION_STATUSES
    assert cycle._failure_class("researka_revision_fingerprint") == "D_no_action"
    assert cycle._failure_class("research_revision_fingerprint") == "D_no_action"


def test_terminal_statuses_and_retryable_timeouts_do_not_drift() -> None:
    terminal = cycle._TERMINAL_REVISION_STATUSES | cycle._ACTIVE_REVIEW_TERMINAL_REVISION_STATUSES
    assert all(cycle._failure_class(status) == "D_no_action" for status in terminal)

    retryable_timeouts = {
        status for status in cycle._RETRYABLE_REVISION_STATUSES
        if "timeout" in status
    }
    assert retryable_timeouts <= cycle._NON_REPEAT_STATUSES
    assert "corpus_seed_failed" in cycle._NON_REPEAT_STATUSES


def test_daily_paper_policy_uses_12_receipts_and_shared_source_precision() -> None:
    assert cycle.PREFLIGHT_MIN_RECEIPTS == 12
    assert cycle.SOURCE_TOPIC_REPAIR_FLOOR == cycle.submit_bridge.SOURCE_TOPIC_PRECISION_FLOOR


def test_default_cycle_date_uses_production_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RESEARCH_AGENT_CYCLE_TIMEZONE", "Asia/Dubai")

    assert cycle._default_cycle_date(dt.datetime(2026, 6, 25, 23, 30, tzinfo=dt.UTC)) == "2026-06-26"


def test_preflight_thin_quant_blocker_is_classified_and_backfills_unknown(tmp_path: Path) -> None:
    assert cycle._failure_class("preflight_thin_quant_corpus") == "B_corpus_fixable"
    assert cycle._failure_class("audit_p1_failed") == "C_writer_fixable"

    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    cycle._write_json(ledger_dir / cycle.BLOCKER_HISTOGRAM, {
        "blockers": {
            "preflight_thin_quant_corpus": {"count": 1, "class": "unknown", "samples": []},
            "audit_p1_failed": {"count": 1, "class": "unknown", "samples": []},
        },
    })

    cycle._record_blockers(ledger_dir, "2026-06-25", [{
        "topic": "thin_topic",
        "submit_status": "receipt_preflight_insufficient",
        "submitted": 0,
    }])

    blockers = cycle._read_json(ledger_dir / cycle.BLOCKER_HISTOGRAM)["blockers"]
    assert blockers["preflight_thin_quant_corpus"]["class"] == "B_corpus_fixable"
    assert blockers["audit_p1_failed"]["class"] == "C_writer_fixable"


def test_fresh_lane_keeps_8h_cadence_with_larger_search_budget() -> None:
    service = (REPO / "deploy" / "research-agent-paper-fresh.service").read_text(encoding="utf-8")
    timer = (REPO / "deploy" / "research-agent-paper-fresh.timer").read_text(encoding="utf-8")

    assert "OnCalendar=*-*-* 00/8:00:00" in timer
    assert "--max-attempts 0" in service
    assert "--cycle-budget-sec 10800" in service
    assert "RESEARKA_DOI_PREFLIGHT_ENABLED=1" in service
    assert "RESEARCH_AGENT_SEED_TOPIC_TIMEOUT_SECONDS=300" in service
    assert "Restart=on-failure" in service
    assert "RestartSec=60" in service
    assert "TimeoutStartSec=14400" in service


def test_long_running_paper_units_restart_after_signal_failures() -> None:
    for name in ("research-agent-paper-fresh.service", "research-agent-paper-revise.service"):
        service = (REPO / "deploy" / name).read_text(encoding="utf-8")
        assert "Type=oneshot" in service
        assert "Restart=on-failure" in service
        assert "RestartSec=60" in service


def test_submit_units_enable_doi_preflight() -> None:
    for name in (
        "research-agent-paper-daily-submit.service",
        "research-agent-paper-fresh.service",
        "research-agent-paper-revise.service",
    ):
        service = (REPO / "deploy" / name).read_text(encoding="utf-8")
        assert "RESEARKA_DOI_PREFLIGHT_ENABLED=1" in service


@pytest.mark.parametrize(
    ("publish_timeout", "seed_timeout", "expected_timeout"),
    [("17", None, 17), (None, "300", 300)],
)
def test_fresh_publish_seeds_empty_frontier_with_bounded_timeout(
    tmp_path: Path, monkeypatch, publish_timeout: str | None, seed_timeout: str | None, expected_timeout: int,
) -> None:
    _topic(tmp_path, "empty_frontier", corpus=False, target_journal=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.delenv("RESEARCH_AGENT_PUBLISH_SEED_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("RESEARCH_AGENT_SEED_TOPIC_TIMEOUT_SECONDS", raising=False)
    if publish_timeout is not None:
        monkeypatch.setenv("RESEARCH_AGENT_PUBLISH_SEED_TIMEOUT_SECONDS", publish_timeout)
    if seed_timeout is not None:
        monkeypatch.setenv("RESEARCH_AGENT_SEED_TOPIC_TIMEOUT_SECONDS", seed_timeout)
    monkeypatch.setattr(cycle, "_quant_claim_source_precision", lambda *_a, **_k: (
        True, "source_topic_precision_ok:10/10", [],
    ))
    monkeypatch.setattr(cycle, "_receipt_preflight", lambda topic, out_dir, **_k: {"passed": True})
    seen: list[int | None] = []

    def fake_corpus(topic: str, *, dry_run: bool, timeout: int | None = None) -> dict[str, Any]:
        seen.append(timeout)
        qdir = cycle.CORPORA / topic / "quant_claims"
        qdir.mkdir(parents=True)
        for i in range(cycle.PREFLIGHT_MIN_QUANT_CLAIMS):
            _write_json(qdir / f"seed-{i}.quant_claims.json", {"paper_id": f"seed {i}", "claims": []})
        return {"status": "corpus_seeded", "n_quant_claims": cycle.PREFLIGHT_MIN_QUANT_CLAIMS}

    def fake_synthesis(topic: str, out_dir: Path, **_kwargs: Any) -> int:
        out_dir.mkdir(parents=True)
        return 0

    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-06-25",
        run_synthesis=True,
        submit=True,
        mode="fresh",
        remote_loader=lambda: (set(), None),
        submit_cycle=lambda **_kwargs: {"status": "submitted_to_researka", "submitted": 1, "published": 0},
        ensure_corpus=fake_corpus,
        cycle_budget_seconds=1000,
        max_attempts=1,
    )

    assert seen == [expected_timeout]
    assert ledger["status"] == "submitted_to_researka"
    assert ledger["frontier_corpus_seed"]["topic"] == "empty_frontier"


def test_fresh_publish_continues_after_frontier_seed_stays_thin(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "aaa_empty_frontier", corpus=False, target_journal=True)
    _topic(tmp_path, "bbb_ready", corpus=True, target_journal=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_current_low_source_precision_topics", lambda _topics: set())
    monkeypatch.setattr(cycle, "_quant_claim_source_precision", lambda *_a, **_k: (
        True, "source_topic_precision_ok:12/12", [],
    ))
    monkeypatch.setattr(cycle, "_preflight", lambda *_a, **_k: {"passed": True})
    monkeypatch.setattr(cycle, "_receipt_preflight", lambda *_a, **_k: {"passed": True})

    def fake_select(topics, _ledger_dir, **kwargs):
        excluded = kwargs.get("exclude", set())
        for candidate in ("aaa_empty_frontier", "bbb_ready"):
            if candidate in topics and candidate not in excluded:
                return candidate
        return None

    def fake_corpus(topic: str, *, dry_run: bool, timeout: int | None = None) -> dict[str, Any]:
        if topic == "aaa_empty_frontier":
            return {"status": "corpus_seed_failed", "n_quant_claims": 0}
        return {"status": "corpus_ready", "n_quant_claims": cycle.PREFLIGHT_MIN_QUANT_CLAIMS}

    def fake_synthesis(topic: str, out_dir: Path, **_kwargs: Any) -> int:
        out_dir.mkdir(parents=True)
        return 0

    monkeypatch.setattr(cycle, "select_topic", fake_select)
    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-06-25",
        run_synthesis=True,
        submit=True,
        mode="fresh",
        remote_loader=lambda: (set(), None),
        submit_cycle=lambda **_kwargs: {"status": "submitted_to_researka", "submitted": 1, "published": 0},
        ensure_corpus=fake_corpus,
        cycle_budget_seconds=1000,
        max_attempts=2,
    )

    assert ledger["status"] == "submitted_to_researka"
    assert [attempt["topic"] for attempt in ledger["attempts"]] == ["aaa_empty_frontier", "bbb_ready"]
    assert ledger["attempts"][0]["submit_status"] == "corpus_seed_failed"
    assert ledger["submitted_topic"] == "bbb_ready"


def test_fresh_receipt_preflight_uses_publish_seed_timeout(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "ready_topic", corpus=True, target_journal=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setenv("RESEARCH_AGENT_PUBLISH_SEED_TIMEOUT_SECONDS", "17")
    monkeypatch.setattr(cycle, "_current_low_source_precision_topics", lambda _topics: set())
    monkeypatch.setattr(cycle, "_quant_claim_source_precision", lambda *_a, **_k: (
        True, "source_topic_precision_ok:12/12", [],
    ))
    monkeypatch.setattr(cycle, "_preflight", lambda *_a, **_k: {"passed": True})
    seen: list[int | None] = []

    def fake_receipt_preflight(topic: str, out_dir: Path, *, timeout: int | None = None, **_kwargs: Any) -> dict[str, Any]:
        seen.append(timeout)
        return {"passed": True}

    def fake_synthesis(topic: str, out_dir: Path, **_kwargs: Any) -> int:
        out_dir.mkdir(parents=True)
        return 0

    monkeypatch.setattr(cycle, "_receipt_preflight", fake_receipt_preflight)
    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-06-25",
        run_synthesis=True,
        submit=True,
        mode="fresh",
        remote_loader=lambda: (set(), None),
        submit_cycle=lambda **_kwargs: {"status": "submitted_to_researka", "submitted": 1, "published": 0},
        cycle_budget_seconds=1000,
        max_attempts=1,
    )

    assert ledger["status"] == "submitted_to_researka"
    assert seen == [17]


def test_fresh_publish_repairs_best_unpublished_source_precision_topic(tmp_path: Path, monkeypatch) -> None:
    for name in ("aaa_low_support", "published_high_support", "zzz_high_support"):
        _topic(tmp_path, name, target_journal=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_current_low_source_precision_topics", lambda _topics: {
        "aaa_low_support", "published_high_support", "zzz_high_support",
    })
    monkeypatch.setattr(cycle, "_published_topics", lambda *_a, **_k: {"published_high_support"})
    monkeypatch.setattr(cycle, "_topic_support_score", lambda topic: 100 if topic.endswith("high_support") else 1)
    monkeypatch.setattr(cycle, "_quant_claim_count", lambda _topic: cycle.SOURCE_PRECISION_REPAIR_PUBLISH_MIN_QUANT)
    monkeypatch.setattr(cycle, "_quant_claim_source_precision", lambda *_a, **_k: (
        False, "source_topic_precision_low:24/48<0.80", [],
    ))
    monkeypatch.setenv("RESEARCH_AGENT_PUBLISH_SEED_TIMEOUT_SECONDS", "17")
    repairs: list[tuple[str, int | None]] = []

    def fake_repair(topic: str, *, timeout: int | None = None, **_kwargs: Any) -> dict[str, Any]:
        repairs.append((topic, timeout))
        return {"status": "source_precision_repair_incomplete", "n_quant_claims": 0}

    monkeypatch.setattr(cycle, "_repair_low_source_precision_corpus", fake_repair)

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-06-25",
        run_synthesis=True,
        submit=True,
        mode="fresh",
        remote_loader=lambda: (set(), None),
        submit_cycle=lambda **_kwargs: {"status": "submitted_to_researka", "submitted": 1, "published": 0},
        max_attempts=1,
        cycle_budget_seconds=1000,
    )

    assert repairs[0] == ("zzz_high_support", 17)
    assert ledger["status"] == "no_unpublished_topic_available"


@pytest.fixture(autouse=True)
def _offline_coverage_judge(monkeypatch):
    """The revision coverage judge calls a live model; default every test to
    "all asks met" so revise tests stay deterministic and offline. The four
    coverage-gate tests override this with their own monkeypatch."""
    monkeypatch.setattr(cycle, "_unmet_revision_asks", lambda out_dir, fb: [])
    monkeypatch.setattr(cycle, "_retracted_cited_sources", lambda out_dir: [])
    monkeypatch.setattr(cycle, "_abstract_overclaims", lambda out_dir: [])
    monkeypatch.setattr(cycle, "_numeric_effect_direction_issues", lambda out_dir: [])


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
            _write_json(qdir / f"seed-{i}.quant_claims.json", {"paper_id": f"{topic} seed {i}", "claims": []})


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
    qdir = root / "docs" / "quality-reference" / topic / "quant_claims"
    qdir.mkdir(parents=True, exist_ok=True)
    for row in receipts_payload:
        rid = str(row["receipt_id"])
        _write_json(qdir / f"{rid}.quant_claims.json", {"paper_id": rid, "claims": [{"binding_confidence": "high"}]})
    return run


def test_discover_topics_includes_pack_before_corpus_exists(tmp_path: Path) -> None:
    _topic(tmp_path, "creatine")
    _topic(tmp_path, "new_topic", corpus=False)
    (tmp_path / "topic_packs" / "_biomedical_default.toml").write_text("", encoding="utf-8")

    topics = cycle.discover_topics(tmp_path / "topic_packs", tmp_path / "docs" / "quality-reference")

    assert topics == ["creatine", "new_topic"]


def test_discover_topics_includes_generated_pack_records(tmp_path: Path) -> None:
    _topic(tmp_path, "creatine")
    _write_json(tmp_path / "topic_packs_db" / "senescence_biomarker_effects" / "latest.json", {
        "candidate_count": 12,
        "pack_data": {"topic": "senescence_biomarker_effects", "aliases": ["senescence biomarker effects", "senescence"], "target_journal": "GeroScience"},
    })

    topics = cycle.discover_topics(
        tmp_path / "topic_packs",
        tmp_path / "docs" / "quality-reference",
        tmp_path / "topic_packs_db",
    )

    assert topics == ["creatine", "senescence_biomarker_effects"]


def test_discover_topics_excludes_low_information_generated_pack_records(tmp_path: Path) -> None:
    _write_json(tmp_path / "topic_packs_db" / "biomarker_effects" / "latest.json", {
        "candidate_count": 12,
        "pack_data": {"topic": "biomarker_effects", "aliases": ["biomarker effects", "biomarker"], "target_journal": "GeroScience"},
    })
    _write_json(tmp_path / "topic_packs_db" / "telomere_biomarker_effects" / "latest.json", {
        "candidate_count": 12,
        "pack_data": {"topic": "telomere_biomarker_effects", "aliases": ["telomere biomarker effects", "telomere"], "target_journal": "GeroScience"},
    })

    topics = cycle.discover_topics(
        tmp_path / "topic_packs",
        tmp_path / "docs" / "quality-reference",
        tmp_path / "topic_packs_db",
    )

    assert topics == ["telomere_biomarker_effects"]


def test_generated_pack_record_counts_as_publication_track(tmp_path: Path, monkeypatch) -> None:
    _write_json(tmp_path / "topic_packs_db" / "senescence_biomarker_effects" / "latest.json", {
        "candidate_count": 12,
        "pack_data": {"topic": "senescence_biomarker_effects", "aliases": ["senescence biomarker effects", "senescence"], "target_journal": "GeroScience"},
    })
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")

    assert cycle._publication_track_topic("senescence_biomarker_effects") is True


def test_low_information_generated_pack_is_not_publication_track(tmp_path: Path, monkeypatch) -> None:
    _write_json(tmp_path / "topic_packs_db" / "biomarker_effects" / "latest.json", {
        "candidate_count": 12,
        "pack_data": {"topic": "biomarker_effects", "aliases": ["biomarker effects", "biomarker"], "target_journal": "GeroScience"},
    })
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")

    assert cycle._publication_track_topic("biomarker_effects") is False



def test_select_topic_skips_remote_published_titles_and_rotates_attempts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _topic(tmp_path, "aerobic_exercise", corpus=True, target_journal=True)
    _topic(tmp_path, "creatine", corpus=False, target_journal=True)
    _topic(tmp_path, "metformin", corpus=True, target_journal=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
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


def test_select_topic_skips_remote_published_topic_marker_when_title_changed(tmp_path: Path) -> None:
    ledger_dir = tmp_path / cycle.LEDGER_DIR

    selected = cycle.select_topic(
        ["ergothioneine", "metformin"],
        ledger_dir,
        remote_seen={cycle.submit_bridge._topic_marker("ergothioneine")},
    )

    assert selected == "metformin"


def test_reconcile_publication_ledgers_updates_submitted_public_ledger(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    run = runs_root / "synthesis-mitochondrial_health-v06-TEST"
    paper = run / "full_paper.md"
    paper.parent.mkdir(parents=True)
    paper.write_text("# Research Synthesis: Mitochondrial Health Effects\n\nBody.\n", encoding="utf-8")
    ledger_dir = runs_root / cycle.LEDGER_DIR
    started_at = "2026-06-05T08:00:00+00:00"
    _write_json(ledger_dir / "2026-06-05-fresh.json", {
        "date": "2026-06-05",
        "mode": "fresh",
        "started_at": started_at,
        "status": "submitted_to_researka",
        "submitted": 1,
        "published": 0,
        "no_submission_reason": "journal_surface_not_passed",
        "submitted_topic": "mitochondrial_health",
        "submitted_run": run.name,
        "attempts": [{"out_dir": run.name, "submitted": 1}],
    })
    cycle._record_daily_throughput(ledger_dir, {
        "date": "2026-06-05",
        "mode": "fresh",
        "started_at": started_at,
        "status": "submitted_to_researka",
        "submitted": 1,
        "published": 0,
        "submitted_topic": "mitochondrial_health",
    })

    result = cycle.reconcile_publication_ledgers(
        runs_root=runs_root,
        date="2026-06-05",
        mode="fresh",
        remote_loader=lambda: ({cycle.submit_bridge._title_marker("Research Synthesis: Mitochondrial Health Effects")}, None),
    )

    ledger = json.loads((ledger_dir / "2026-06-05-fresh.json").read_text(encoding="utf-8"))
    throughput = json.loads((ledger_dir / cycle.DAILY_THROUGHPUT_SUMMARY).read_text(encoding="utf-8"))
    assert result["status"] == "publication_reconciled"
    assert result["updated_ledgers"] == ["2026-06-05-fresh.json"]
    assert ledger["status"] == "published"
    assert ledger["published"] == 1
    assert "no_submission_reason" not in ledger
    assert ledger["attempts"][0]["published"] == 1
    assert ledger["publication_reconciliation"]["source"] == "remote_publications"
    assert throughput["days"]["2026-06-05"]["published"] == 1
    assert throughput["days"]["2026-06-05"]["runs"][0]["published"] == 1


def test_reconcile_publication_ledgers_updates_submit_bridge_ledger(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    run = runs_root / "synthesis-longevity_lifespan_effects-v06-TEST"
    paper = run / "full_paper.md"
    paper.parent.mkdir(parents=True)
    title = "Research Synthesis: Longevity Lifespan Effects — full paper"
    paper.write_text(f"# {title}\n\nBody.\n", encoding="utf-8")
    submit_ledger_dir = runs_root / cycle.submit_bridge.LEDGER_DIR
    _write_json(submit_ledger_dir / "2026-06-05.json", {
        "date": "2026-06-05",
        "status": "submitted_to_researka",
        "submitted": 1,
        "published": 0,
        "day_summary": {"submitted": 3, "published": 0},
        "no_submission_reason": "journal_surface_not_passed",
        "candidate": {"run": run.name, "topic": "longevity_lifespan_effects"},
    })

    result = cycle.reconcile_publication_ledgers(
        runs_root=runs_root,
        date="2026-06-05",
        mode="fresh",
        remote_loader=lambda: ({cycle.submit_bridge._title_marker(title)}, None),
    )

    ledger = json.loads((submit_ledger_dir / "2026-06-05.json").read_text(encoding="utf-8"))
    assert result["status"] == "publication_reconciled"
    assert result["updated_ledgers"] == ["_daily_research_paper_ledger/2026-06-05.json"]
    assert ledger["status"] == "published"
    assert ledger["published"] == 1
    assert ledger["day_summary"] == {"submitted": 3, "published": 1}
    assert "no_submission_reason" not in ledger
    assert ledger["publication_reconciliation"]["source"] == "remote_publications"


def test_reconcile_publication_ledgers_refreshes_published_submit_day_summary(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    submit_ledger_dir = runs_root / cycle.submit_bridge.LEDGER_DIR
    _write_json(submit_ledger_dir / "2026-06-05.json", {
        "date": "2026-06-05",
        "status": "published",
        "submitted": 1,
        "published": 1,
        "day_summary": {"submitted": 3, "published": 0},
    })

    result = cycle.reconcile_publication_ledgers(
        runs_root=runs_root,
        date="2026-06-05",
        remote_loader=lambda: (set(), None),
    )

    ledger = json.loads((submit_ledger_dir / "2026-06-05.json").read_text(encoding="utf-8"))
    assert result["status"] == "publication_reconciled"
    assert result["updated_ledgers"] == ["_daily_research_paper_ledger/2026-06-05.json"]
    assert ledger["day_summary"] == {"submitted": 3, "published": 1}


def test_reconcile_publication_ledgers_prefers_submission_id_over_same_title(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    title = "Adjacent Evidence Brief: Alpha-klotho — full paper"
    old_run = runs_root / "synthesis-klotho-v06-R1"
    new_run = runs_root / "synthesis-klotho-v06-R2"
    for run in (old_run, new_run):
        run.mkdir(parents=True)
        (run / "full_paper.md").write_text(f"# {title}\n\nBody.\n", encoding="utf-8")
    submit_ledger_dir = runs_root / cycle.submit_bridge.LEDGER_DIR
    base = {
        "status": "submitted_to_researka",
        "submitted": 1,
        "published": 0,
    }
    _write_json(submit_ledger_dir / "2026-06-05-old.json", {
        **base,
        "candidate": {"run": old_run.name, "topic": "klotho"},
        "submission": {"response": {"submission": {"id": "old-submission"}}},
    })
    _write_json(submit_ledger_dir / "2026-06-05-new.json", {
        **base,
        "candidate": {"run": new_run.name, "topic": "klotho"},
        "submission": {"response": {"submission": {"id": "new-submission"}}},
    })

    result = cycle.reconcile_publication_ledgers(
        runs_root=runs_root,
        remote_loader=lambda: ({
            cycle.submit_bridge._title_marker(title),
            cycle.submit_bridge._submission_marker("new-submission"),
        }, None),
    )

    old_ledger = json.loads((submit_ledger_dir / "2026-06-05-old.json").read_text(encoding="utf-8"))
    new_ledger = json.loads((submit_ledger_dir / "2026-06-05-new.json").read_text(encoding="utf-8"))
    assert result["updated_ledgers"] == ["_daily_research_paper_ledger/2026-06-05-new.json"]
    assert old_ledger["status"] == "submitted_to_researka"
    assert old_ledger["published"] == 0
    assert new_ledger["status"] == "published"
    assert new_ledger["published"] == 1
    assert new_ledger["publication_reconciliation"]["matched"] == ["submission:new-submission"]


def test_reconcile_publication_ledgers_uses_cycle_attempt_submission_markers(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    title = "Adjacent Evidence Brief: Alpha-klotho — full paper"
    old_run = runs_root / "synthesis-klotho-v06-R1"
    new_run = runs_root / "synthesis-klotho-v06-R2"
    for run in (old_run, new_run):
        run.mkdir(parents=True)
        (run / "full_paper.md").write_text(f"# {title}\n\nBody.\n", encoding="utf-8")
    ledger_dir = runs_root / cycle.LEDGER_DIR
    _write_json(ledger_dir / "2026-06-05-fresh.json", {
        "status": "submitted_to_researka",
        "submitted": 1,
        "published": 0,
        "attempts": [
            {"out_dir": old_run.name, "submitted": 1, "submission_markers": ["submission:old-submission"]},
        ],
    })

    result = cycle.reconcile_publication_ledgers(
        runs_root=runs_root,
        date="2026-06-05",
        mode="fresh",
        remote_loader=lambda: ({
            cycle.submit_bridge._title_marker(title),
            cycle.submit_bridge._submission_marker("new-submission"),
        }, None),
    )

    ledger = json.loads((ledger_dir / "2026-06-05-fresh.json").read_text(encoding="utf-8"))
    assert "2026-06-05-fresh.json" not in result["updated_ledgers"]
    assert ledger["status"] == "submitted_to_researka"
    assert ledger["published"] == 0


def test_reconcile_publication_ledgers_uses_submit_bridge_ids_for_legacy_cycle_ledgers(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    title = "Adjacent Evidence Brief: Alpha-klotho — full paper"
    old_run = runs_root / "synthesis-klotho-v06-R1"
    old_run.mkdir(parents=True)
    (old_run / "full_paper.md").write_text(f"# {title}\n\nBody.\n", encoding="utf-8")
    cycle_ledger_dir = runs_root / cycle.LEDGER_DIR
    submit_ledger_dir = runs_root / cycle.submit_bridge.LEDGER_DIR
    _write_json(cycle_ledger_dir / "2026-06-05-fresh.json", {
        "status": "submitted_to_researka",
        "submitted": 1,
        "published": 0,
        "submitted_run": old_run.name,
    })
    _write_json(submit_ledger_dir / "2026-06-05.json", {
        "status": "submitted_to_researka",
        "submitted": 1,
        "published": 0,
        "candidate": {"run": old_run.name, "topic": "klotho"},
        "submission": {"response": {"submission": {"id": "old-submission"}}},
    })

    result = cycle.reconcile_publication_ledgers(
        runs_root=runs_root,
        date="2026-06-05",
        mode="fresh",
        remote_loader=lambda: ({
            cycle.submit_bridge._title_marker(title),
            cycle.submit_bridge._submission_marker("new-submission"),
        }, None),
    )

    ledger = json.loads((cycle_ledger_dir / "2026-06-05-fresh.json").read_text(encoding="utf-8"))
    assert "2026-06-05-fresh.json" not in result["updated_ledgers"]
    assert ledger["status"] == "submitted_to_researka"
    assert ledger["published"] == 0


def test_reconcile_publication_ledgers_maps_aggregate_submit_markers_by_run(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    old_title = "Adjacent Evidence Brief: Alpha-klotho — full paper"
    new_title = "Adjacent Evidence Brief: Beta-klotho — full paper"
    old_run = runs_root / "synthesis-klotho-v06-R1"
    new_run = runs_root / "synthesis-klotho-v06-R2"
    for run, title in ((old_run, old_title), (new_run, new_title)):
        run.mkdir(parents=True)
        (run / "full_paper.md").write_text(f"# {title}\n\nBody.\n", encoding="utf-8")
    cycle_ledger_dir = runs_root / cycle.LEDGER_DIR
    submit_ledger_dir = runs_root / cycle.submit_bridge.LEDGER_DIR
    _write_json(cycle_ledger_dir / "2026-06-05-fresh.json", {
        "status": "submitted_to_researka",
        "submitted": 1,
        "published": 0,
        "submitted_run": old_run.name,
    })
    _write_json(submit_ledger_dir / "2026-06-05.json", {
        "status": "submitted_to_researka",
        "submitted": 2,
        "published": 0,
        "candidate": {"run": old_run.name, "topic": "klotho"},
        "submission": {"response": {"submission": {"id": "new-submission"}}},
        "submissions": [
            {
                "candidate": {"run": old_run.name, "topic": "klotho"},
                "submitted": 1,
                "submission_markers": ["submission:old-submission"],
            },
            {
                "candidate": {"run": new_run.name, "topic": "klotho"},
                "submitted": 1,
                "submission_markers": ["submission:new-submission"],
            },
        ],
    })

    result = cycle.reconcile_publication_ledgers(
        runs_root=runs_root,
        date="2026-06-05",
        mode="fresh",
        remote_loader=lambda: ({cycle.submit_bridge._submission_marker("new-submission")}, None),
    )

    ledger = json.loads((cycle_ledger_dir / "2026-06-05-fresh.json").read_text(encoding="utf-8"))
    assert "2026-06-05-fresh.json" not in result["updated_ledgers"]
    assert ledger["status"] == "submitted_to_researka"
    assert ledger["published"] == 0


def test_reconcile_publication_ledgers_updates_cycle_after_later_submit_bridge_publish(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    title = "Hypothesis-Generating Brief: Berberine hydrochloride"
    run = runs_root / "synthesis-berberine-v06-DAILY-2026-06-24T12-58-39Z-R2"
    run.mkdir(parents=True)
    (run / "full_paper.md").write_text(f"# {title}\n\nBody.\n", encoding="utf-8")
    cycle_ledger_dir = runs_root / cycle.LEDGER_DIR
    submit_ledger_dir = runs_root / cycle.submit_bridge.LEDGER_DIR
    _write_json(cycle_ledger_dir / "2026-06-24-fresh.json", {
        "date": "2026-06-24",
        "mode": "fresh",
        "started_at": "2026-06-24T08:00:00+00:00",
        "status": "no_ready_corpus_available",
        "submitted": 0,
        "published": 0,
        "attempts": [{"topic": "berberine", "out_dir": run.name, "submitted": 0}],
    })
    _write_json(submit_ledger_dir / "2026-06-24.json", {
        "date": "2026-06-24",
        "status": "no_eligible_research_paper",
        "submitted": 0,
        "published": 0,
        "considered": [{"run": run.name, "status": "duplicate_submission_run"}],
    })
    _write_json(submit_ledger_dir / "_submitted_fingerprints.json", [{
        "run": run.name,
        "topic": "berberine",
        "submission_id": "berberine-submission",
        "content_hash": "sha256:berberine-content",
    }])

    result = cycle.reconcile_publication_ledgers(
        runs_root=runs_root,
        date="2026-06-24",
        mode="fresh",
        remote_loader=lambda: ({cycle.submit_bridge._submission_marker("berberine-submission")}, None),
    )

    cycle_ledger = json.loads((cycle_ledger_dir / "2026-06-24-fresh.json").read_text(encoding="utf-8"))
    submit_ledger = json.loads((submit_ledger_dir / "2026-06-24.json").read_text(encoding="utf-8"))
    throughput = json.loads((cycle_ledger_dir / cycle.DAILY_THROUGHPUT_SUMMARY).read_text(encoding="utf-8"))
    assert result["status"] == "publication_reconciled"
    assert result["updated_ledgers"] == ["2026-06-24-fresh.json"]
    assert cycle_ledger["status"] == "published"
    assert cycle_ledger["submitted"] == 1
    assert cycle_ledger["published"] == 1
    assert cycle_ledger["attempts"][0]["submitted"] == 1
    assert cycle_ledger["attempts"][0]["published"] == 1
    assert cycle_ledger["publication_reconciliation"]["matched"] == ["submission:berberine-submission"]
    assert submit_ledger["status"] == "no_eligible_research_paper"
    assert submit_ledger["published"] == 0
    assert throughput["days"]["2026-06-24"]["published"] == 1


def test_reconcile_publication_ledgers_uses_unique_title_when_public_api_omits_submission_id(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    title = "Hypothesis-Generating Brief: Sulforaphane Nrf2"
    run = runs_root / "synthesis-sulforaphane_nrf2-v06-DAILY-2026-06-27T12-00-00Z"
    run.mkdir(parents=True)
    (run / "full_paper.md").write_text(f"# {title}\n\nBody.\n", encoding="utf-8")
    cycle_ledger_dir = runs_root / cycle.LEDGER_DIR
    submit_ledger_dir = runs_root / cycle.submit_bridge.LEDGER_DIR
    _write_json(cycle_ledger_dir / "2026-06-27-fresh.json", {
        "date": "2026-06-27",
        "mode": "fresh",
        "status": "submitted_to_researka",
        "submitted": 1,
        "published": 0,
        "submitted_topic": "sulforaphane_nrf2",
        "submitted_run": run.name,
    })
    _write_json(submit_ledger_dir / "_submitted_fingerprints.json", [{
        "date": "2026-06-27",
        "run": run.name,
        "topic": "sulforaphane_nrf2",
        "submission_id": "submission-not-exposed-on-public-page",
    }])

    result = cycle.reconcile_publication_ledgers(
        runs_root=runs_root,
        date="2026-06-27",
        mode="fresh",
        remote_loader=lambda: ({cycle.submit_bridge._title_marker(title)}, None),
    )

    ledger = json.loads((cycle_ledger_dir / "2026-06-27-fresh.json").read_text(encoding="utf-8"))
    assert result["status"] == "publication_reconciled"
    assert result["updated_ledgers"] == ["2026-06-27-fresh.json"]
    assert ledger["status"] == "published"
    assert ledger["submitted"] == 1
    assert ledger["published"] == 1
    assert ledger["publication_reconciliation"]["matched"] == [cycle.submit_bridge._title_marker(title)]


def test_reconcile_publication_ledgers_does_not_title_match_unsubmitted_cycle(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    title = "Hypothesis-Generating Brief: Berberine hydrochloride"
    run = runs_root / "synthesis-berberine-v06-DAILY-2026-06-24T12-58-39Z-R2"
    run.mkdir(parents=True)
    (run / "full_paper.md").write_text(f"# {title}\n\nBody.\n", encoding="utf-8")
    cycle_ledger_dir = runs_root / cycle.LEDGER_DIR
    _write_json(cycle_ledger_dir / "2026-06-24-fresh.json", {
        "status": "synthesis_completed_no_submission",
        "submitted": 0,
        "published": 0,
        "attempts": [{"topic": "berberine", "out_dir": run.name, "submitted": 0}],
    })

    result = cycle.reconcile_publication_ledgers(
        runs_root=runs_root,
        date="2026-06-24",
        mode="fresh",
        remote_loader=lambda: ({cycle.submit_bridge._title_marker(title)}, None),
    )

    ledger = json.loads((cycle_ledger_dir / "2026-06-24-fresh.json").read_text(encoding="utf-8"))
    assert result["updated_ledgers"] == []
    assert ledger["status"] == "synthesis_completed_no_submission"
    assert ledger["published"] == 0


def test_reconcile_publication_ledgers_cleans_stale_published_reason(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    ledger_dir = runs_root / cycle.LEDGER_DIR
    _write_json(ledger_dir / "2026-06-05-fresh.json", {
        "date": "2026-06-05",
        "mode": "fresh",
        "started_at": "2026-06-05T08:00:00+00:00",
        "status": "no_ready_corpus_available",
        "submitted": 1,
        "published": 1,
        "no_submission_reason": "journal_surface_not_passed",
        "submitted_topic": "mitochondrial_health",
    })

    result = cycle.reconcile_publication_ledgers(
        runs_root=runs_root,
        date="2026-06-05",
        mode="fresh",
        remote_loader=lambda: (set(), None),
    )

    ledger = json.loads((ledger_dir / "2026-06-05-fresh.json").read_text(encoding="utf-8"))
    assert result["status"] == "publication_reconciled"
    assert ledger["status"] == "published"
    assert ledger["published"] == 1
    assert "no_submission_reason" not in ledger


def test_reconcile_publication_ledgers_records_public_accept_decisions(tmp_path: Path, monkeypatch) -> None:
    runs_root = tmp_path / "runs"
    title = "Hypothesis-Generating Brief: Taurine supplementation — full paper"
    run = runs_root / "synthesis-taurine-v06-DAILY-2026-06-24T08-00-00Z"
    run.mkdir(parents=True)
    (run / "full_paper.md").write_text(f"# {title}\n\nBody.\n", encoding="utf-8")
    ledger_dir = runs_root / cycle.LEDGER_DIR
    _write_json(ledger_dir / "2026-06-24-fresh.json", {
        "date": "2026-06-24",
        "mode": "fresh",
        "status": "submitted_to_researka",
        "submitted": 1,
        "published": 0,
        "submitted_run": run.name,
    })
    monkeypatch.setattr(cycle.submit_bridge, "_remote_published_fingerprints", lambda: (set(), None))
    monkeypatch.setattr(cycle, "_latest_public_decisions_by_title", lambda: ({
        cycle.submit_bridge._title_marker(title): {
            "artifactId": "paper-1",
            "title": title,
            "decision": "accept",
            "status": "published",
            "submissionId": "public-decision-submission-id",
            "createdAt": "2026-06-24T12:22:51+04:00",
        },
    }, None))

    result = cycle.reconcile_publication_ledgers(runs_root=runs_root, date="2026-06-24")

    decisions = json.loads((ledger_dir / cycle.DECISIONS_BY_DAY).read_text(encoding="utf-8"))
    ledger = json.loads((ledger_dir / "2026-06-24-fresh.json").read_text(encoding="utf-8"))
    assert result["status"] == "publication_reconciled"
    assert result["updated_ledgers"] == ["2026-06-24-fresh.json"]
    assert result["decision_records"] == 1
    assert ledger["status"] == "published"
    assert ledger["published"] == 1
    assert decisions["days"]["2026-06-24"]["counts"] == {"accept": 1}
    assert decisions["days"]["2026-06-24"]["records"][0]["reviewed_at"] == "2026-06-24T12:22:51+04:00"


def test_reconcile_cli_without_mode_checks_all_lanes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen: dict[str, Any] = {}

    def fake_reconcile(**kwargs: Any) -> dict[str, Any]:
        seen.update(kwargs)
        return {
            "status": "no_publication_reconciliation_needed",
            "checked": 0,
            "updated": 0,
            "updated_ledgers": [],
        }

    monkeypatch.setattr(cycle, "reconcile_publication_ledgers", fake_reconcile)

    assert cycle.main(["--runs-root", str(tmp_path / "runs"), "--date", "2026-06-05", "--reconcile-publications"]) == 0
    assert seen["mode"] is None


def test_reconcile_cli_without_date_checks_all_dates(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen: dict[str, Any] = {}

    def fake_reconcile(**kwargs: Any) -> dict[str, Any]:
        seen.update(kwargs)
        return {
            "status": "no_publication_reconciliation_needed",
            "checked": 0,
            "updated": 0,
            "updated_ledgers": [],
        }

    monkeypatch.setattr(cycle, "reconcile_publication_ledgers", fake_reconcile)

    assert cycle.main(["--runs-root", str(tmp_path / "runs"), "--reconcile-publications"]) == 0
    assert seen["date"] is None


def test_select_topic_prefers_no_recent_failure_when_available(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "aaa_recent_failure", target_journal=True)
    _topic(tmp_path, "zzz_clean", target_journal=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    ledger_dir = tmp_path / cycle.LEDGER_DIR
    cycle._record_blockers(
        ledger_dir,
        "2026-06-02",
        [{"topic": "aaa_recent_failure", "gate_status": "receipt_preflight_insufficient", "submitted": 0}],
    )

    selected = cycle.select_topic(["aaa_recent_failure", "zzz_clean"], ledger_dir)

    assert selected == "zzz_clean"


def test_select_topic_allows_submitted_topic_after_cooldown(tmp_path: Path, monkeypatch) -> None:
    """The 21-day cooldown rate-limits re-submission of a topic that was
    submitted but is NOT published (pending/rejected): after the window it is
    selectable again. remote_seen is empty here — the topic is not published."""
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
        remote_seen=set(),  # not published → only the submission cooldown applies
    )

    assert selected == "aerobic_exercise"


def test_select_topic_skips_published_topic_marker_even_after_cooldown(tmp_path: Path, monkeypatch) -> None:
    """A topic whose paper is ALREADY PUBLISHED (its title is in the remote
    published set) must NOT be re-selected by the fresh cycle even once the
    submission cooldown lapses: a fresh non-revision re-run of a published title
    always dedups at submit (duplicate_remote_publication), wasting the
    synthesis. Updating a published paper is the revise cycle's job. Regression
    for the 2026-06 stall where telomere_effects (published) was re-selected
    every cycle and dedup'd, yielding published=0 for days."""
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
        remote_seen={cycle.submit_bridge._topic_marker("aerobic_exercise")},
    )

    assert selected is None  # published → permanently excluded from the fresh cycle


def test_select_topic_does_not_substring_block_sibling_published_title(
    tmp_path: Path, monkeypatch,
) -> None:
    _topic(tmp_path, "sglt2_inhibitors", target_journal=True)
    runs_root = tmp_path / "runs"
    ledger_dir = runs_root / cycle.LEDGER_DIR
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")

    selected = cycle.select_topic(
        ["sglt2_inhibitors"],
        ledger_dir,
        runs_root=runs_root,
        remote_seen={cycle.submit_bridge._title_marker("Research Synthesis: SGLT2 inhibitors effects")},
    )

    assert selected == "sglt2_inhibitors"


def test_select_topic_skips_published_title_when_topic_key_is_plural(
    tmp_path: Path, monkeypatch,
) -> None:
    _topic(tmp_path, "epigenetic_clocks", target_journal=True)
    runs_root = tmp_path / "runs"
    ledger_dir = runs_root / cycle.LEDGER_DIR
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")

    selected = cycle.select_topic(
        ["epigenetic_clocks"],
        ledger_dir,
        runs_root=runs_root,
        remote_seen={cycle.submit_bridge._title_marker("Research Synthesis: Epigenetic Clocks")},
    )

    assert selected is None


def test_topic_family_groups_sibling_slugs_by_lead_entity() -> None:
    fam = cycle._topic_family
    # sibling slugs of the same entity collapse to one family key…
    assert fam("nad_effects") == fam("nad_biomarker_effects") == fam("nad_metabolism_effects") == "nad"
    # …while distinct entities stay distinct (no over-broad collapse).
    assert fam("rapamycin_longevity") != fam("nad_effects")
    assert fam("aerobic_exercise") == "aerobic"


def test_select_topic_freezes_sibling_topic_within_family_cooldown(tmp_path: Path, monkeypatch) -> None:
    """A sibling slug of a recently-submitted topic (same lead entity) is held
    by the family cooldown. Regression for the 2026-06 NAD walk: nad_effects
    (submitted) left nad_metabolism_effects selectable, producing a near-dup
    researka held as a duplicate (published=0)."""
    _topic(tmp_path, "nad_metabolism_effects", target_journal=True)
    runs_root = tmp_path / "runs"
    ledger_dir = runs_root / cycle.LEDGER_DIR
    recent = dt.datetime.now(dt.UTC) - dt.timedelta(days=1)
    _write_json(runs_root / cycle.submit_bridge.LEDGER_DIR / "_submitted_fingerprints.json", [{
        "date": recent.isoformat(),
        "topic": "nad_effects",
        "fingerprint": "sha256:abc",
    }])
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")

    selected = cycle.select_topic(
        ["nad_metabolism_effects"],
        ledger_dir,
        runs_root=runs_root,
        remote_seen=set(),  # not published → only the family cooldown applies
    )

    assert selected is None  # sibling of nad_effects frozen (was selectable before the family fix)


def test_select_topic_allows_sibling_after_family_cooldown(tmp_path: Path, monkeypatch) -> None:
    """The family cooldown is a rate-limit, not a ban: once the window lapses a
    sibling slug becomes selectable again."""
    _topic(tmp_path, "nad_metabolism_effects", target_journal=True)
    runs_root = tmp_path / "runs"
    ledger_dir = runs_root / cycle.LEDGER_DIR
    old = dt.datetime.now(dt.UTC) - dt.timedelta(days=cycle.PUBLISHED_TOPIC_COOLDOWN_DAYS + 1)
    _write_json(runs_root / cycle.submit_bridge.LEDGER_DIR / "_submitted_fingerprints.json", [{
        "date": old.isoformat(),
        "topic": "nad_effects",
        "fingerprint": "sha256:abc",
    }])
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")

    selected = cycle.select_topic(
        ["nad_metabolism_effects"],
        ledger_dir,
        runs_root=runs_root,
        remote_seen=set(),
    )

    assert selected == "nad_metabolism_effects"  # cooldown lapsed → family freeze lifts


def test_modifier_stem_matches_word_family_universally() -> None:
    # stem catches the whole word family (no per-topic word lists)…
    assert cycle._modifier_stem("metabolism") == "metabol"
    assert cycle._modifier_stem("regimens") == "regimen"
    # …while content scopes with no strippable suffix stay exact.
    assert cycle._modifier_stem("lifespan") == "lifespan"
    assert cycle._modifier_stem("cardiovascular") == "cardiovascular"


def test_claim_scope_matches_modifier_word_family(tmp_path: Path) -> None:
    """A fasting-metabolism study that says 'metabolic rate' (not the literal
    'metabolism') now counts on-scope via the stem; an off-aspect claim does
    not — so genuine aspect corpora pass while the anti-dilution floor holds."""
    on = tmp_path / "on.quant_claims.json"
    on.write_text('{"claims":[{"text":"resting metabolic rate fell 12%"}]}', encoding="utf-8")
    off = tmp_path / "off.quant_claims.json"
    off.write_text('{"claims":[{"text":"mood scores improved"}]}', encoding="utf-8")
    assert cycle._claim_text_has_scope(on, ["metabolism"]) is True
    assert cycle._claim_text_has_scope(off, ["metabolism"]) is False


def test_select_topic_prefers_publication_track_packs(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "acarbose")
    _topic(tmp_path, "caloric_restriction", target_journal=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")

    selected = cycle.select_topic(["acarbose", "caloric_restriction"], tmp_path / cycle.LEDGER_DIR)

    assert selected == "caloric_restriction"


def test_select_topic_returns_none_when_no_publication_track_topics(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "acarbose")
    _topic(tmp_path, "berberine")
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")

    selected = cycle.select_topic(["acarbose", "berberine"], tmp_path / cycle.LEDGER_DIR)

    assert selected is None


def test_preflight_requires_declared_target_journal(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "berberine")
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")

    status = cycle._preflight("berberine", tmp_path / "runs", tmp_path / cycle.LEDGER_DIR)

    assert status["passed"] is False
    assert "target_journal_not_declared" in status["reasons"]


def test_select_topic_prefers_untried_over_prior_l4_to_advance_frontier(tmp_path: Path, monkeypatch) -> None:
    """Frontier-advance: a never-attempted publish-ready topic outranks a
    re-run of an already-worked one, so the cycle works through the untried
    backlog instead of orbiting a handful of proven topics. (Was: prior-L4
    preferred — that preference is what stalled the new-topic frontier.)"""
    _topic(tmp_path, "caloric_restriction", target_journal=True)
    _topic(tmp_path, "metformin", target_journal=True)
    _prior_run(tmp_path, "metformin", receipts=40, tensions=5, level=4)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")

    selected = cycle.select_topic(
        ["caloric_restriction", "metformin"],
        tmp_path / cycle.LEDGER_DIR,
        runs_root=tmp_path / "runs",
    )

    assert selected == "caloric_restriction"  # untried beats the re-run


def test_select_topic_prefers_local_corpus_over_empty_frontier_topic(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "empty_frontier", corpus=False, target_journal=True)
    _topic(tmp_path, "solid_ready", target_journal=True)
    _prior_run(tmp_path, "solid_ready", receipts=40, tensions=5, level=4)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")

    selected = cycle.select_topic(
        ["empty_frontier", "solid_ready"],
        tmp_path / cycle.LEDGER_DIR,
        runs_root=tmp_path / "runs",
    )

    assert selected == "solid_ready"


def test_select_topic_skips_weak_generated_frontier_topic(tmp_path: Path, monkeypatch) -> None:
    _write_json(tmp_path / "topic_packs_db" / "weak_generated_marker" / "latest.json", {
        "candidate_count": cycle.SOURCE_PRECISION_REPAIR_PUBLISH_MIN_QUANT - 1,
        "pack_data": {
            "topic": "weak_generated_marker",
            "aliases": ["weak generated marker", "marker-17"],
            "target_journal": "GeroScience",
        },
    })
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")

    selected = cycle.select_topic(["weak_generated_marker"], tmp_path / cycle.LEDGER_DIR)

    assert selected is None


def test_select_topic_allows_supported_generated_frontier_topic(tmp_path: Path, monkeypatch) -> None:
    for topic, count in {
        "weak_generated_marker": cycle.SOURCE_PRECISION_REPAIR_PUBLISH_MIN_QUANT - 1,
        "supported_generated_marker": cycle.SOURCE_PRECISION_REPAIR_PUBLISH_MIN_QUANT,
    }.items():
        _write_json(tmp_path / "topic_packs_db" / topic / "latest.json", {
            "candidate_count": count,
            "pack_data": {
                "topic": topic,
                "aliases": [topic.replace("_", " "), "marker-17"],
                "target_journal": "GeroScience",
            },
        })
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")

    selected = cycle.select_topic(
        ["weak_generated_marker", "supported_generated_marker"],
        tmp_path / cycle.LEDGER_DIR,
    )

    assert selected == "supported_generated_marker"


def test_select_topic_keeps_static_frontier_seedable(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "static_frontier", corpus=False, target_journal=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")

    selected = cycle.select_topic(["static_frontier"], tmp_path / cycle.LEDGER_DIR)

    assert selected == "static_frontier"


def test_cycle_skips_weak_generated_corpus_repair_topic(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "ready_cached", target_journal=True)
    _write_json(tmp_path / "topic_packs_db" / "weak_generated_marker" / "latest.json", {
        "candidate_count": cycle.SOURCE_PRECISION_REPAIR_PUBLISH_MIN_QUANT - 1,
        "pack_data": {
            "topic": "weak_generated_marker",
            "aliases": ["weak generated marker", "marker-17"],
            "target_journal": "GeroScience",
        },
    })
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_corpus_repair_topics", lambda *_a, **_k: {"weak_generated_marker"})
    monkeypatch.setattr(cycle, "_current_low_source_precision_topics", lambda _topics: set())
    monkeypatch.setattr(cycle, "_repair_topic_corpus", lambda topic, **_k: pytest.fail(f"unexpected repair: {topic}"))
    monkeypatch.setattr(cycle, "_quant_claim_source_precision", lambda *_a, **_k: (
        True, "source_topic_precision_ok:10/10", [],
    ))
    monkeypatch.setattr(cycle, "_receipt_preflight", lambda *_a, **_k: {"passed": True})
    synthesized: list[str] = []

    def fake_synthesis(topic: str, out_dir: Path, **_kwargs: Any) -> int:
        synthesized.append(topic)
        out_dir.mkdir(parents=True)
        return 0

    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-06-25",
        run_synthesis=True,
        submit=True,
        mode="fresh",
        remote_loader=lambda: (set(), None),
        submit_cycle=lambda **_kwargs: {"status": "submitted_to_researka", "submitted": 1, "published": 0},
    )

    assert synthesized == ["ready_cached"]
    assert ledger["status"] == "submitted_to_researka"
    assert "corpus_repairs" not in ledger


def test_cycle_reseeds_seedable_backlog_after_selection(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "ready_cached", target_journal=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_corpus_repair_topics", lambda *_a, **_k: {"ready_cached"})
    monkeypatch.setattr(cycle, "_current_low_source_precision_topics", lambda _topics: set())
    monkeypatch.setattr(cycle, "_repair_topic_corpus", lambda topic, **_k: pytest.fail(f"unexpected repair: {topic}"))
    monkeypatch.setattr(cycle, "_quant_claim_source_precision", lambda *_a, **_k: (
        True, "source_topic_precision_ok:10/10", [],
    ))
    monkeypatch.setattr(cycle, "_receipt_preflight", lambda *_a, **_k: {"passed": True})
    ensured: list[str] = []
    synthesized: list[str] = []

    def fake_corpus(topic: str, **_kwargs: Any) -> dict[str, Any]:
        ensured.append(topic)
        return {"status": "corpus_ready", "n_quant_claims": cycle.PREFLIGHT_MIN_QUANT_CLAIMS}

    def fake_synthesis(topic: str, out_dir: Path, **_kwargs: Any) -> int:
        synthesized.append(topic)
        out_dir.mkdir(parents=True)
        return 0

    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-06-25",
        run_synthesis=True,
        submit=True,
        mode="fresh",
        remote_loader=lambda: (set(), None),
        ensure_corpus=fake_corpus,
        submit_cycle=lambda **_kwargs: {"status": "submitted_to_researka", "submitted": 1, "published": 0},
    )

    assert ensured == ["ready_cached"]
    assert synthesized == ["ready_cached"]
    assert ledger["status"] == "submitted_to_researka"
    assert "corpus_repairs" not in ledger


def test_select_topic_falls_back_to_score_when_all_attempted(tmp_path: Path, monkeypatch) -> None:
    """Steady state (NOT the orbit bug): once every publish-ready candidate has
    been attempted, the untried-first flag is uniform, so selection falls back
    to the existing order — the higher-pass-rate topic wins. The bug was never
    reaching fresh topics; preferring a proven topic among already-tried ones is
    correct."""
    _topic(tmp_path, "caloric_restriction", target_journal=True)
    _topic(tmp_path, "metformin", target_journal=True)
    _prior_run(tmp_path, "caloric_restriction", receipts=8, tensions=1, level=1)
    _prior_run(tmp_path, "metformin", receipts=40, tensions=5, level=4)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")

    selected = cycle.select_topic(
        ["caloric_restriction", "metformin"],
        tmp_path / cycle.LEDGER_DIR,
        runs_root=tmp_path / "runs",
    )

    assert selected == "metformin"  # all tried → higher-pass-rate wins


def test_select_topic_prefers_more_fact_supported_publication_track_topic(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "low_fact_topic", target_journal=True)
    _topic(tmp_path, "high_fact_topic", target_journal=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    for i in range(20):
        _write_json(
            cycle.CORPORA / "high_fact_topic" / "quant_claims" / f"extra-{i}.quant_claims.json",
            {"paper_id": f"extra-{i}"},
        )

    selected = cycle.select_topic(["low_fact_topic", "high_fact_topic"], tmp_path / cycle.LEDGER_DIR)

    assert selected == "high_fact_topic"


def test_cycle_dry_run_selects_topic_without_synthesis(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "creatine", target_journal=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")

    ledger = cycle.run_cycle(runs_root=tmp_path / "runs", date="2026-05-24")

    assert ledger["status"] == "dry_run_selected_topic"
    assert ledger["topic"] == "creatine"
    assert ledger["submitted"] == 0
    assert ledger["published"] == 0


def test_cycle_writes_mode_specific_ledgers(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "creatine", target_journal=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")

    fresh = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-06-01",
        mode="fresh",
    )
    revise = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-06-01",
        mode="revise",
        submit=True,
        remote_loader=lambda: (set(), None),
        revision_loader=lambda: ([], None),
        submit_cycle=lambda **_kwargs: {"status": "no_eligible_research_paper", "submitted": 0, "published": 0},
    )

    ledger_dir = tmp_path / "runs" / cycle.LEDGER_DIR
    assert fresh["status"] == "dry_run_selected_topic"
    assert revise["status"] == "no_revise_pending"
    assert (ledger_dir / "2026-06-01-fresh.json").exists()
    assert (ledger_dir / "2026-06-01-revise.json").exists()


def test_daily_throughput_summary_survives_later_zero_submit_cycle(tmp_path: Path) -> None:
    ledger_dir = tmp_path / cycle.LEDGER_DIR
    first = {
        "date": "2026-06-01",
        "started_at": "2026-06-01T10:00:00+00:00",
        "mode": "fresh",
        "status": "submitted_to_researka",
        "submitted": 1,
        "published": 0,
        "topic": "grip_strength_longevity",
    }
    second = {
        "date": "2026-06-01",
        "started_at": "2026-06-01T10:15:00+00:00",
        "mode": "revise",
        "status": "no_revise_pending",
        "submitted": 0,
        "published": 0,
    }

    cycle._record_daily_throughput(ledger_dir, first)
    cycle._record_daily_throughput(ledger_dir, second)
    cycle._record_daily_throughput(ledger_dir, first)

    summary = json.loads((ledger_dir / cycle.DAILY_THROUGHPUT_SUMMARY).read_text(encoding="utf-8"))
    day = summary["days"]["2026-06-01"]
    assert day["submitted"] == 1
    assert day["published"] == 0
    assert day["cycles"] == 2
    assert day["latest_status"] == "no_revise_pending"


def test_daily_throughput_summary_skips_probe_date_keys(tmp_path: Path) -> None:
    ledger_dir = tmp_path / cycle.LEDGER_DIR

    cycle._record_daily_throughput(ledger_dir, {
        "date": "2026-06-01-revise-probe",
        "started_at": "2026-06-01T10:00:00+00:00",
        "mode": "revise",
        "status": "dry_run_selected_topic",
        "submitted": 0,
        "published": 0,
    })

    assert not (ledger_dir / cycle.DAILY_THROUGHPUT_SUMMARY).exists()


def test_review_decisions_by_day_preserves_null_status(tmp_path: Path) -> None:
    ledger_dir = tmp_path / cycle.LEDGER_DIR
    latest: dict[str, dict[str, Any]] = {
        "hrv": {
            "artifactId": "art-1",
            "title": "Research Synthesis: HRV",
            "decision": "revise",
            "status": None,
            "reviewedAt": "2026-06-01T08:35:00+00:00",
            "requiredRevisions": [
                "Clarify direct clinical evidence boundaries and avoid overclaiming.",
                "Correct the truncated sentence in the abstract.",
            ],
        },
        "glynac": {
            "artifactId": "art-2",
            "title": "Research Synthesis: GlyNAC",
            "decision": "accept",
            "status": "published",
            "reviewedAt": "2026-06-01T05:42:00+00:00",
        },
    }

    cycle._record_review_decisions(ledger_dir, latest)

    data = json.loads((ledger_dir / cycle.DECISIONS_BY_DAY).read_text(encoding="utf-8"))
    day = data["days"]["2026-06-01"]
    assert day["counts"] == {"accept": 1, "revise": 1}
    assert any(record["decision"] == "revise" and record["status"] is None for record in day["records"])
    reasons = json.loads((ledger_dir / cycle.REVISE_REASONS).read_text(encoding="utf-8"))
    assert reasons["total_reviews"] == 1
    assert reasons["total_revision_asks"] == 2
    assert reasons["bucket_counts"] == {"directness_honesty": 1, "readability_redundancy": 1}


def test_revision_asks_keep_semicolon_examples_inside_one_ask() -> None:
    feedback = (
        "Re-extract and re-code directional signals per source (e.g., Katsube 2024 positive; "
        "Meng 2025 inverse association; Cheah 2026 lower serum ET). The uniform-null coding "
        "is a pipeline artifact.; Add an explicit Tensions and Gaps section that names the real "
        "disagreements: animal positive signals vs. absence of direct human RCTs; observational "
        "dose-response vs. lack of replication; off-topic sources vs. clinical relevance.; "
        "Clarify the admission funnel arithmetic."
    )

    asks = cycle._revision_asks(feedback)

    assert len(asks) == 3
    assert "Meng 2025 inverse association" in asks[0]
    assert "observational dose-response vs. lack of replication" in asks[1]
    assert asks[2] == "Clarify the admission funnel arithmetic."


def test_revision_asks_split_independent_review_actions_not_examples() -> None:
    feedback = (
        "Repair the Limitations sentence fragment ('a different outcome (e.'); "
        "Replace the 'Contextual Adjacent Evidence' outcome class with informative "
        "sub-classes (e.g., methodological/algorithmic, AD/dementia, sleep); "
        "For each non-null or mixed signal, name the specific cited source(s) "
        "(e.g., Selitser 2025; Wang 2025 and Kou 2024); "
        "Operationalize and enumerate the '56 cross-study disagreements'; "
        "Expand Tensions and Gaps into a substantive section; "
        "Verify the '894 high-confidence extracted claims' figure."
    )

    asks = cycle._revision_asks(feedback)

    assert len(asks) == 6
    assert "Selitser 2025; Wang 2025" in asks[2]
    assert asks[3].startswith("Operationalize")
    assert asks[4].startswith("Expand")
    assert asks[5].startswith("Verify")


def test_revision_asks_strip_retry_escalation_prefix() -> None:
    feedback = (
        "PRIOR REVISION DID NOT ADDRESS THESE REQUIRED POINTS — you MUST make a "
        "substantive change to satisfy EACH: Repair the sentence fragment.; "
        "Verify the source counts."
    )

    asks = cycle._revision_asks(feedback)

    assert asks == ["Repair the sentence fragment.", "Verify the source counts."]


def test_escalated_revision_feedback_does_not_duplicate_original_feedback() -> None:
    feedback = "Repair the sentence fragment.; Verify the source counts."
    escalated = cycle._escalate_feedback(feedback, cycle._revision_asks(feedback))

    asks = cycle._revision_asks(escalated)

    assert asks == ["Repair the sentence fragment.", "Verify the source counts."]


def test_cycle_runs_synthesis_then_delegates_to_submit_bridge(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "creatine", target_journal=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_quant_claim_source_precision", lambda *_a, **_k: (
        True, "source_topic_precision_ok:10/10", [],
    ))
    monkeypatch.setattr(cycle, "_receipt_preflight", lambda topic, out_dir, **_k: {"passed": True})
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


def test_fresh_lane_refreshes_topic_supply_when_no_candidate_remains(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_quant_claim_source_precision", lambda *_a, **_k: (
        True, "source_topic_precision_ok:10/10", [],
    ))
    monkeypatch.setattr(cycle, "_receipt_preflight", lambda topic, out_dir, **_k: {"passed": True})
    calls: dict[str, Any] = {}

    def fake_refresh(db_dir: Path, *, skip_slugs: set[str] | None = None) -> dict[str, Any]:
        calls["skip_slugs"] = skip_slugs
        latest = db_dir / "sglt2_inhibitors_effects" / "latest.json"
        _write_json(latest, {
            "candidate_count": cycle.SOURCE_PRECISION_REPAIR_PUBLISH_MIN_QUANT,
            "pack_data": {
                "topic": "sglt2_inhibitors_effects",
                "aliases": ["SGLT2 inhibitors effects", "SGLT2 inhibitors"],
                "target_journal": "GeroScience",
                "retrieval": {
                    "topic_terms": ["SGLT2 inhibitors effects", "SGLT2 inhibitors"],
                    "scope_terms": [],
                },
            },
        })
        return {"status": "topic_supply_refreshed", "created": [{"slug": "sglt2_inhibitors_effects"}]}

    def fake_corpus(topic: str, *, dry_run: bool, timeout: int | None = None) -> dict[str, Any]:
        qdir = cycle.CORPORA / topic / "quant_claims"
        qdir.mkdir(parents=True)
        for i in range(cycle.PREFLIGHT_MIN_QUANT_CLAIMS):
            _write_json(qdir / f"seed-{i}.quant_claims.json", {"paper_id": f"{topic}-{i}"})
        return {"status": "corpus_seeded", "n_quant_claims": cycle.PREFLIGHT_MIN_QUANT_CLAIMS}

    def fake_synthesis(topic: str, out_dir: Path, **_kwargs: Any) -> int:
        calls["topic"] = topic
        out_dir.mkdir(parents=True)
        return 0

    monkeypatch.setattr(cycle, "_refresh_topic_supply", fake_refresh)
    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-06-25",
        run_synthesis=True,
        submit=True,
        mode="fresh",
        remote_loader=lambda: (set(), None),
        ensure_corpus=fake_corpus,
        submit_cycle=lambda **_kwargs: {"status": "submitted_to_researka", "submitted": 1, "published": 0},
    )

    assert ledger["topic_supply_refresh"]["status"] == "topic_supply_refreshed"
    assert ledger["topic_supply_selected_after_refresh"] == "sglt2_inhibitors_effects"
    assert calls["topic"] == "sglt2_inhibitors_effects"
    assert isinstance(calls["skip_slugs"], set)
    assert ledger["status"] == "submitted_to_researka"


def test_fresh_lane_refreshes_topic_supply_before_thin_frontier_candidate(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "thin_frontier", corpus=False, target_journal=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_quant_claim_source_precision", lambda *_a, **_k: (
        True, "source_topic_precision_ok:10/10", [],
    ))
    calls: dict[str, Any] = {"preflights": []}

    def fake_refresh(db_dir: Path, *, skip_slugs: set[str] | None = None) -> dict[str, Any]:
        calls["skip_slugs"] = skip_slugs
        latest = db_dir / "refreshed_candidate" / "latest.json"
        _write_json(latest, {
            "candidate_count": cycle.SOURCE_PRECISION_REPAIR_PUBLISH_MIN_QUANT,
            "pack_data": {
                "topic": "refreshed_candidate",
                "aliases": ["refreshed candidate"],
                "target_journal": "GeroScience",
                "retrieval": {"topic_terms": ["refreshed candidate"], "scope_terms": []},
            },
        })
        return {"status": "topic_supply_refreshed", "created": [{"slug": "refreshed_candidate"}]}

    def fake_corpus(topic: str, *, dry_run: bool, timeout: int | None = None) -> dict[str, Any]:
        qdir = cycle.CORPORA / topic / "quant_claims"
        qdir.mkdir(parents=True)
        for i in range(cycle.PREFLIGHT_MIN_QUANT_CLAIMS):
            _write_json(qdir / f"seed-{i}.quant_claims.json", {"paper_id": f"{topic}-{i}"})
        return {"status": "corpus_seeded", "n_quant_claims": cycle.PREFLIGHT_MIN_QUANT_CLAIMS}

    def fake_receipt_preflight(topic: str, out_dir: Path, **_kwargs: Any) -> dict[str, Any]:
        calls["preflights"].append(topic)
        return {"passed": True, "status": "receipt_preflight_ok", "n_receipts": 12, "min_receipts": 12}

    def fake_synthesis(topic: str, out_dir: Path, **_kwargs: Any) -> int:
        calls["topic"] = topic
        out_dir.mkdir(parents=True)
        return 0

    monkeypatch.setattr(cycle, "_refresh_topic_supply", fake_refresh)
    monkeypatch.setattr(cycle, "_receipt_preflight", fake_receipt_preflight)
    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-06-25",
        run_synthesis=True,
        submit=True,
        mode="fresh",
        remote_loader=lambda: (set(), None),
        ensure_corpus=fake_corpus,
        submit_cycle=lambda **_kwargs: {"status": "submitted_to_researka", "submitted": 1, "published": 0},
    )

    assert ledger["topic_supply_refresh"]["status"] == "topic_supply_refreshed"
    assert ledger["topic_supply_selected_after_refresh"] == "refreshed_candidate"
    assert calls["topic"] == "refreshed_candidate"
    assert calls["preflights"] == ["refreshed_candidate"]
    assert "thin_frontier" in (calls["skip_slugs"] or set())
    assert ledger["status"] == "submitted_to_researka"


def test_topic_supply_refresh_uses_deeper_default_window(tmp_path: Path, monkeypatch) -> None:
    calls: list[dict[str, Any]] = []

    class FakeMaterializer:
        @staticmethod
        def dsn_from_env() -> str:
            return "postgresql://example"

        @staticmethod
        def http_credentials_from_env() -> tuple[str, str]:
            return "", ""

        @staticmethod
        def fetch_rows(**kwargs: Any) -> list[dict[str, Any]]:
            calls.append({"limit": kwargs["limit"], "strategy": kwargs["strategy"]})
            return []

        @staticmethod
        def materialize_rows(rows: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
            calls[-1].update({
                "quality_mode": kwargs["quality_mode"],
                "max_created": kwargs["max_created"],
                "skip_slugs": kwargs["skip_slugs"],
            })
            return {"created": [], "skipped": []}

    monkeypatch.setitem(sys.modules, "materialize_fact_topic_packs", FakeMaterializer)
    monkeypatch.delenv("RESEARCH_AGENT_TOPIC_SUPPLY_LIMIT", raising=False)
    monkeypatch.delenv("RESEARCH_AGENT_TOPIC_SUPPLY_QUALITY_MODE", raising=False)

    result = cycle._refresh_topic_supply(tmp_path / "topic_packs_db")

    assert calls[0] == {
        "limit": 500,
        "strategy": "fact-intervention-cross",
        "quality_mode": "high-precision",
        "max_created": cycle.TOPIC_SUPPLY_REFRESH_MAX_CREATED,
        "skip_slugs": None,
    }
    assert [call["strategy"] for call in calls] == list(cycle.TOPIC_SUPPLY_STRATEGIES)
    assert result["status"] == "topic_supply_no_new_packs"
    assert result["strategies_attempted"] == [
        {"strategy": strategy, "rows": 0, "created": 0, "skipped": 0}
        for strategy in cycle.TOPIC_SUPPLY_STRATEGIES
    ]


def test_topic_supply_refresh_falls_back_to_next_strategy(tmp_path: Path, monkeypatch) -> None:
    calls: list[dict[str, Any]] = []

    class FakeMaterializer:
        @staticmethod
        def dsn_from_env() -> str:
            return "postgresql://example"

        @staticmethod
        def http_credentials_from_env() -> tuple[str, str]:
            return "", ""

        @staticmethod
        def fetch_rows(**kwargs: Any) -> list[dict[str, Any]]:
            calls.append({"strategy": kwargs["strategy"]})
            return [{"topic": "metformin", "sub_topic": kwargs["strategy"], "claim_type": "effect_size"}]

        @staticmethod
        def materialize_rows(rows: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
            strategy = calls[-1]["strategy"]
            calls[-1].update({
                "quality_mode": kwargs["quality_mode"],
                "skip_slugs": kwargs["skip_slugs"],
            })
            if strategy == "fact-field-cross":
                return {"created": [{"slug": "metformin_field_effects"}], "skipped": []}
            return {"created": [], "skipped": [{"slug": f"skip-{strategy}", "reason": "quality_filter_failed"}]}

    monkeypatch.setitem(sys.modules, "materialize_fact_topic_packs", FakeMaterializer)
    monkeypatch.delenv("RESEARCH_AGENT_TOPIC_SUPPLY_STRATEGY", raising=False)

    result = cycle._refresh_topic_supply(tmp_path / "topic_packs_db", skip_slugs={"old_topic"})

    assert [call["strategy"] for call in calls] == ["fact-intervention-cross", "fact-field-cross"]
    assert all(call["quality_mode"] == "high-precision" for call in calls)
    assert all(call["skip_slugs"] == {"old_topic"} for call in calls)
    assert result["status"] == "topic_supply_refreshed"
    assert result["strategy"] == "fact-field-cross"
    assert result["created"] == [{"slug": "metformin_field_effects"}]
    assert result["skipped"] == [{"slug": "skip-fact-intervention-cross", "reason": "quality_filter_failed"}]


def test_fresh_lane_refreshes_before_retrying_recent_blocked_topics(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "old_blocked", target_journal=True)
    ledger_dir = tmp_path / "runs" / cycle.LEDGER_DIR
    _write_json(ledger_dir / cycle.BLOCKER_HISTOGRAM, {
        "repeats": {
            "old_blocked\x1fsource_topic_precision_low": [dt.datetime.now(dt.UTC).isoformat()],
        },
    })
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_quant_claim_source_precision", lambda *_a, **_k: (
        True, "source_topic_precision_ok:10/10", [],
    ))
    monkeypatch.setattr(cycle, "_receipt_preflight", lambda topic, out_dir, **_k: {"passed": True})
    calls: dict[str, Any] = {}

    def fake_refresh(db_dir: Path, *, skip_slugs: set[str] | None = None) -> dict[str, Any]:
        calls["skip_slugs"] = skip_slugs
        latest = db_dir / "nr_precursor_effects" / "latest.json"
        _write_json(latest, {
            "candidate_count": 24,
            "pack_data": {
                "topic": "nr_precursor_effects",
                "aliases": ["NR precursor effects", "nicotinamide riboside"],
                "target_journal": "GeroScience",
                "retrieval": {
                    "topic_terms": ["NR precursor effects", "nicotinamide riboside"],
                    "scope_terms": [],
                },
            },
        })
        return {"status": "topic_supply_refreshed", "created": [{"slug": "nr_precursor_effects"}]}

    def fake_corpus(topic: str, *, dry_run: bool, timeout: int | None = None) -> dict[str, Any]:
        qdir = cycle.CORPORA / topic / "quant_claims"
        qdir.mkdir(parents=True)
        for i in range(cycle.PREFLIGHT_MIN_QUANT_CLAIMS):
            _write_json(qdir / f"seed-{i}.quant_claims.json", {"paper_id": f"{topic}-{i}"})
        return {"status": "corpus_seeded", "n_quant_claims": cycle.PREFLIGHT_MIN_QUANT_CLAIMS}

    def fake_synthesis(topic: str, out_dir: Path, **_kwargs: Any) -> int:
        calls["topic"] = topic
        out_dir.mkdir(parents=True)
        return 0

    monkeypatch.setattr(cycle, "_refresh_topic_supply", fake_refresh)
    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-06-25",
        run_synthesis=True,
        submit=True,
        mode="fresh",
        remote_loader=lambda: (set(), None),
        ensure_corpus=fake_corpus,
        submit_cycle=lambda **_kwargs: {"status": "submitted_to_researka", "submitted": 1, "published": 0},
    )

    assert ledger["topic_supply_selected_after_refresh"] == "nr_precursor_effects"
    assert calls["topic"] == "nr_precursor_effects"
    assert "old_blocked" in (calls["skip_slugs"] or set())
    assert ledger["status"] == "submitted_to_researka"


def test_fresh_lane_prefers_ready_cached_topic_over_repaired_cold_topic(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "ready_cached", target_journal=True)
    _topic(tmp_path, "cold_repaired", corpus=False, target_journal=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_corpus_repair_topics", lambda *_a, **_k: {"cold_repaired"})
    monkeypatch.setattr(cycle, "_repair_topic_corpus", lambda *_a, **_k: {
        "status": "corpus_seeded",
        "n_quant_claims": cycle.PREFLIGHT_MIN_QUANT_CLAIMS,
    })
    monkeypatch.setattr(cycle, "_quant_claim_source_precision", lambda *_a, **_k: (
        True, "source_topic_precision_ok:10/10", [],
    ))
    monkeypatch.setattr(cycle, "_receipt_preflight", lambda topic, out_dir, **_k: {"passed": True})
    calls: dict[str, Any] = {}

    def fake_synthesis(topic: str, out_dir: Path, **_kwargs: Any) -> int:
        calls["topic"] = topic
        out_dir.mkdir(parents=True)
        return 0

    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-06-23",
        run_synthesis=True,
        submit=True,
        remote_loader=lambda: (set(), None),
        submit_cycle=lambda **_kwargs: {"status": "submitted_to_researka", "submitted": 1, "published": 0},
    )

    assert ledger["status"] == "submitted_to_researka"
    assert calls["topic"] == "ready_cached"


def test_fresh_lane_excludes_unrepaired_source_precision_backlog(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "aaa_failed_repair", corpus=False, target_journal=True)
    _topic(tmp_path, "clean_published", target_journal=True)
    _topic(tmp_path, "ready_cached", target_journal=True)
    _topic(tmp_path, "zzz_seed_candidate", corpus=False, target_journal=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_current_low_source_precision_topics", lambda topics: {
        "aaa_failed_repair",
        "ready_cached",
    })
    monkeypatch.setattr(cycle, "_published_topics", lambda *_a, **_k: {"clean_published"})
    monkeypatch.setattr(cycle, "_corpus_repair_limit", lambda: 1)
    monkeypatch.setattr(cycle, "_quant_claim_count", lambda topic: (
        10 if topic == "aaa_failed_repair" else cycle.SOURCE_PRECISION_REPAIR_PUBLISH_MIN_QUANT
    ))
    monkeypatch.setattr(cycle, "_quant_claim_source_precision", lambda topic, **_k: (
        (False, "source_topic_precision_low:0/10<0.80", [Path(f"miss-{i}.json") for i in range(10)])
        if topic == "aaa_failed_repair"
        else (False, "source_topic_precision_low:24/48<0.80", [])
    ))
    monkeypatch.setattr(cycle, "_receipt_preflight", lambda topic, out_dir, **_k: {"passed": True})
    calls: dict[str, Any] = {}

    def fake_source_repair(topic: str, **_kwargs: Any) -> dict[str, Any]:
        if topic == "aaa_failed_repair":
            return {"status": "source_precision_repair_incomplete", "n_quant_claims": 0}
        return {"status": "source_precision_repaired", "n_quant_claims": cycle.SOURCE_PRECISION_REPAIR_PUBLISH_MIN_QUANT}

    def fake_corpus(topic: str, **_kwargs: Any) -> dict[str, Any]:
        return {"status": "corpus_ready", "n_quant_claims": cycle.PREFLIGHT_MIN_QUANT_CLAIMS}

    def fake_synthesis(topic: str, out_dir: Path, **_kwargs: Any) -> int:
        calls["topic"] = topic
        out_dir.mkdir(parents=True)
        return 0

    monkeypatch.setattr(cycle, "_repair_low_source_precision_corpus", fake_source_repair)
    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-06-23",
        run_synthesis=True,
        submit=True,
        remote_loader=lambda: (set(), None),
        ensure_corpus=fake_corpus,
        submit_cycle=lambda **_kwargs: {"status": "submitted_to_researka", "submitted": 1, "published": 0},
    )

    assert ledger["status"] == "submitted_to_researka"
    assert "aaa_failed_repair" in ledger["source_precision_auto_excluded_topics"]
    assert calls["topic"] == "zzz_seed_candidate"


def test_fresh_lane_rechecks_preflight_cooldown_before_source_low_selection(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "aaa_low_source", target_journal=True)
    _topic(tmp_path, "zzz_clean_ready", target_journal=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_corpus_repair_limit", lambda: 0)
    monkeypatch.setattr(cycle, "_current_low_source_precision_topics", lambda _topics: {"aaa_low_source"})
    blocked_snapshots = iter([{"zzz_clean_ready"}, set()])
    monkeypatch.setattr(cycle, "_recent_preflight_blocked_topics", lambda *_a, **_k: next(blocked_snapshots, set()))
    monkeypatch.setattr(cycle, "_recent_blocked_topics", lambda *_a, **_k: set())

    def fake_precision(topic: str, **_kwargs: Any) -> tuple[bool, str, list[Path]]:
        if topic == "aaa_low_source":
            return False, "source_topic_precision_low:1/10<0.80", [Path("bad.json")]
        return True, "source_topic_precision_ok:10/10", []

    synthesized: list[str] = []
    monkeypatch.setattr(cycle, "_quant_claim_source_precision", fake_precision)
    monkeypatch.setattr(cycle, "_receipt_preflight", lambda topic, out_dir, **_k: {"passed": True})

    def fake_synthesis(topic: str, out_dir: Path, **_kwargs: Any) -> int:
        synthesized.append(topic)
        out_dir.mkdir(parents=True)
        return 0

    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-06-23",
        run_synthesis=True,
        submit=True,
        remote_loader=lambda: (set(), None),
        submit_cycle=lambda **_kwargs: {"status": "submitted_to_researka", "submitted": 1, "published": 0},
        max_attempts=1,
    )

    assert ledger["status"] == "submitted_to_researka"
    assert synthesized == ["zzz_clean_ready"]


def test_zero_claim_candidate_does_not_skip_source_precision_repair(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "aaa_source_low", target_journal=True)
    _topic(tmp_path, "zzz_zero_claim", corpus=False, target_journal=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_current_low_source_precision_topics", lambda _topics: {"aaa_source_low"})
    monkeypatch.setattr(cycle, "_corpus_repair_limit", lambda: 1)
    monkeypatch.setattr(cycle, "_receipt_preflight", lambda *_a, **_k: {"passed": True})
    repaired: set[str] = set()
    synthesized: list[str] = []

    def fake_precision(topic: str, **_kwargs: Any) -> tuple[bool, str, list[Path]]:
        if topic == "aaa_source_low" and topic not in repaired:
            return False, "source_topic_precision_low:24/25<0.50", [Path("off-topic.json")]
        return True, "source_topic_precision_ok:10/10", []

    def fake_repair(topic: str, **_kwargs: Any) -> dict[str, Any]:
        repaired.add(topic)
        return {"status": "source_precision_repaired", "n_quant_claims": cycle.SOURCE_PRECISION_REPAIR_PUBLISH_MIN_QUANT}

    def fake_corpus(topic: str, **_kwargs: Any) -> dict[str, Any]:
        if topic == "zzz_zero_claim":
            raise AssertionError("zero-claim fallback must not skip repairable source-low corpus")
        return {"status": "corpus_ready", "n_quant_claims": cycle.PREFLIGHT_MIN_QUANT_CLAIMS}

    def fake_synthesis(topic: str, out_dir: Path, **_kwargs: Any) -> int:
        synthesized.append(topic)
        out_dir.mkdir(parents=True)
        return 0

    monkeypatch.setattr(cycle, "_quant_claim_source_precision", fake_precision)
    monkeypatch.setattr(cycle, "_quant_claim_count", lambda topic: (
        cycle.SOURCE_PRECISION_REPAIR_PUBLISH_MIN_QUANT + 1 if topic == "aaa_source_low" else 0
    ))
    monkeypatch.setattr(cycle, "_repair_low_source_precision_corpus", fake_repair)
    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-06-24",
        run_synthesis=True,
        submit=True,
        remote_loader=lambda: (set(), None),
        ensure_corpus=fake_corpus,
        submit_cycle=lambda **_kwargs: {"status": "submitted_to_researka", "submitted": 1, "published": 0},
    )

    assert repaired == {"aaa_source_low"}
    assert synthesized == ["aaa_source_low"]
    assert ledger["status"] == "submitted_to_researka"


def test_clean_ready_helper_excludes_published_and_source_low(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "published_clean", target_journal=True)
    _topic(tmp_path, "source_low", target_journal=True)
    _topic(tmp_path, "clean_ready", target_journal=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")

    assert not cycle._topic_has_quant_floor("missing_topic")
    assert cycle._topic_has_quant_floor("clean_ready")
    assert cycle._has_clean_ready_topic(
        ["published_clean", "source_low", "clean_ready"],
        exclude={"published_clean"},
        source_precision_blocked={"source_low"},
    )
    assert not cycle._has_clean_ready_topic(
        ["published_clean", "source_low"],
        exclude={"published_clean"},
        source_precision_blocked={"source_low"},
    )


def test_cycle_restricts_real_submit_bridge_to_current_run(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "creatine")
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_quant_claim_source_precision", lambda *_a, **_k: (
        True, "source_topic_precision_ok:10/10", [],
    ))
    monkeypatch.setattr(cycle, "_receipt_preflight", lambda topic, out_dir, **_k: {"passed": True})
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


def test_cycle_retries_real_submit_bridge_when_current_run_rechecks_eligible(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "curcumin_inflammaging")
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_quant_claim_source_precision", lambda *_a, **_k: (
        True, "source_topic_precision_ok:10/10", [],
    ))
    monkeypatch.setattr(cycle, "_receipt_preflight", lambda topic, out_dir, **_k: {"passed": True})
    monkeypatch.setattr(cycle.submit_bridge, "_token", lambda: ("token", "TOKEN_ENV"))
    calls: list[Path] = []

    def fake_synthesis(
        topic: str,
        out_dir: Path,
        *,
        dry_run: bool,
        timeout: int | None = None,
        revision_feedback: str | None = None,
        review_type_override: str | None = None,
    ) -> int:
        out_dir.mkdir(parents=True)
        return 0

    def fake_submit_bridge(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs["candidate_run"])
        if len(calls) == 1:
            return {"status": "no_eligible_research_paper", "submitted": 0, "published": 0}
        return {"status": "submitted_to_researka", "submitted": 1, "published": 0}

    def fake_select_candidate(*_args: Any, candidate_run: Path | None = None, **_kwargs: Any) -> tuple[Path | None, list[dict[str, str]]]:
        assert candidate_run is not None
        return candidate_run, [{"run": candidate_run.name, "status": "eligible"}]

    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)
    monkeypatch.setattr(cycle.submit_bridge, "run_cycle", fake_submit_bridge)
    monkeypatch.setattr(cycle.submit_bridge, "select_candidate", fake_select_candidate)

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-05-31",
        run_synthesis=True,
        submit=True,
        topic="curcumin_inflammaging",
        remote_loader=lambda: (set(), None),
        decision_poll_seconds=0,
    )

    assert ledger["status"] == "submitted_to_researka"
    assert len(calls) == 2
    assert ledger["submit_bridge"]["retry_after_no_eligible"]["eligibility_recheck"][0]["status"] == "eligible"


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


def test_run_synthesis_timeout_returns_status_code_and_sidecar(tmp_path: Path, monkeypatch) -> None:
    def fake_run(*args: Any, **kwargs: Any) -> object:
        raise cycle.subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    monkeypatch.setattr(cycle.subprocess, "run", fake_run)
    out_dir = tmp_path / "timeout-run"

    rc = cycle._run_synthesis("rapamycin_cancer_effects", out_dir, dry_run=False, timeout=7)

    assert rc == cycle.SYNTHESIS_TIMEOUT_RETURN_CODE
    timeout = json.loads((out_dir / "synthesis_timeout.json").read_text(encoding="utf-8"))
    assert timeout["topic"] == "rapamycin_cancer_effects"
    assert timeout["timeout_seconds"] == 7
    assert "TimeoutExpired" in timeout["error"]


def test_cycle_records_synthesis_timeout_without_service_failure_status(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "rapamycin_cancer_effects", target_journal=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_current_low_source_precision_topics", lambda _topics: set())
    monkeypatch.setattr(cycle, "_quant_claim_source_precision", lambda _topic, **_k: (True, "source_topic_precision_ok:12/12", []))
    monkeypatch.setattr(cycle, "_receipt_preflight", lambda *_args, **_kwargs: {"passed": True})
    monkeypatch.setattr(cycle, "_run_synthesis", lambda *_args, **_kwargs: cycle.SYNTHESIS_TIMEOUT_RETURN_CODE)

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-06-22",
        run_synthesis=True,
        submit=True,
        mode="fresh",
        topic="rapamycin_cancer_effects",
        remote_loader=lambda: (set(), None),
        submit_cycle=lambda **_kwargs: (_ for _ in ()).throw(AssertionError("timeout must not submit")),
        max_attempts=0,
    )

    assert ledger["status"] == "synthesis_timeout_no_submission"
    assert ledger["no_submission_reason"] == "synthesis_timeout"
    assert ledger["attempts"][0]["gate_status"] == "synthesis_timeout"
    assert ledger["attempts"][0]["failure_class"] == "D_no_action"


def test_revise_timeout_remains_retryable_until_round_cap(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "taurine", target_journal=True)
    source = _prior_run(tmp_path, "taurine", receipts=67, tensions=727, primary=1, level=5)
    title = "Research Synthesis: Taurine — full paper"
    paper = source / "full_paper.md"
    paper.write_text(f"# {title}\n", encoding="utf-8")
    _write_json(tmp_path / "runs" / cycle.submit_bridge.LEDGER_DIR / "_submitted_fingerprints.json", [{
        "run": source.name,
        "topic": "taurine",
        "fingerprint": cycle.submit_bridge._sha256(paper),
    }])
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_quant_claim_source_precision", lambda *_a, **_k: (True, "source_topic_precision_ok:67/67", []))
    monkeypatch.setattr(cycle, "_receipt_preflight", lambda *_a, **_k: {"passed": True})
    monkeypatch.setattr(cycle, "_preflight", lambda *_a, **_k: {
        "passed": True,
        "has_manifest": True,
        "n_receipts": 67,
        "n_tensions": 727,
        "n_primary_tier": 1,
    })
    monkeypatch.setattr(cycle, "_run_synthesis", lambda *_a, **_k: cycle.SYNTHESIS_TIMEOUT_RETURN_CODE)

    reviewed_at = (dt.datetime.now(dt.UTC) - dt.timedelta(hours=1)).isoformat()
    request = {
        "artifactId": "taurine-review",
        "title": title,
        "feedback": "Revise the dense evidence-map language and resubmit.",
        "reviewedAt": reviewed_at,
    }

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-06-24",
        run_synthesis=True,
        submit=True,
        mode="revise",
        remote_loader=lambda: (set(), None),
        revision_loader=lambda: ([dict(request)], None),
        submit_cycle=lambda **_kwargs: (_ for _ in ()).throw(AssertionError("timeout must not submit")),
        ensure_corpus=lambda *_a, **_k: {"status": "corpus_ready", "n_quant_claims": cycle.PREFLIGHT_MIN_QUANT_CLAIMS},
        max_revise_attempts=1,
    )

    assert ledger["status"] == "synthesis_timeout_no_submission"
    assert ledger["attempts"][0]["revision_timeout_status"] == "synthesis_timeout"
    handled_path = tmp_path / "runs" / cycle.LEDGER_DIR / cycle.HANDLED_REVISIONS
    handled = json.loads(handled_path.read_text(encoding="utf-8"))
    assert handled["handled"][0]["status"] == "synthesis_timeout"
    pending, error = cycle._pending_remote_revision(
        tmp_path / "runs",
        tmp_path / "runs" / cycle.LEDGER_DIR,
        loader=lambda: ([dict(request)], None),
    )
    assert error is None
    assert pending is not None

    after_review = (dt.datetime.fromisoformat(reviewed_at) + dt.timedelta(minutes=1)).isoformat()
    handled["handled"].extend(
        {**handled["handled"][0], "handled_at": after_review}
        for i in range(1, cycle.MAX_REVISE_ROUNDS)
    )
    _write_json(handled_path, handled)
    pending, error = cycle._pending_remote_revision(
        tmp_path / "runs",
        tmp_path / "runs" / cycle.LEDGER_DIR,
        loader=lambda: ([dict(request)], None),
    )
    assert error is None
    assert pending is None

    newer = {**request, "artifactId": "taurine-review-2", "reviewedAt": (dt.datetime.now(dt.UTC) + dt.timedelta(hours=1)).isoformat()}
    pending, error = cycle._pending_remote_revision(
        tmp_path / "runs",
        tmp_path / "runs" / cycle.LEDGER_DIR,
        loader=lambda: ([newer], None),
    )
    assert error is None
    assert pending and pending["artifactId"] == "taurine-review-2"


def test_retryable_revision_statuses_expire_before_round_cap(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    ledger_dir = runs / cycle.LEDGER_DIR
    ledger_dir.mkdir(parents=True)
    title = "Hypothesis-Generating Brief: Taurine supplementation — full paper"
    _seed_submitted_run(runs, "taurine", f"# {title}")
    statuses = tuple(sorted(cycle._RETRYABLE_REVISION_STATUSES))
    assert statuses == ("revision_coverage_unmet", "synthesis_timeout", "terminal_synthesis_timeout")
    handled_at = dt.datetime.now(dt.UTC) - dt.timedelta(
        seconds=cycle.RETRYABLE_REVISION_STATUS_COOLDOWN_SECONDS + 60,
    )
    reviewed_at = handled_at - dt.timedelta(minutes=1)
    _write_json(ledger_dir / cycle.HANDLED_REVISIONS, {"handled": [
        {
            "key": cycle.submit_bridge._title_marker(title),
            "title": title,
            "status": status,
            "handled_at": handled_at.isoformat(),
        }
        for status in statuses
    ]})
    request = {
        "artifactId": "taurine-review",
        "title": title,
        "topic": "taurine",
        "feedback": "Revise the manuscript.",
        "reviewedAt": reviewed_at.isoformat(),
    }

    pending, error = cycle._pending_remote_revision(
        runs,
        ledger_dir,
        loader=lambda: ([request], None),
    )

    assert error is None
    assert pending is not None
    assert pending["topic"] == "taurine"


def test_revise_lane_does_not_start_full_retry_without_budget(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "taurine", target_journal=True)
    source = _prior_run(tmp_path, "taurine", receipts=67, tensions=727, primary=1, level=5)
    title = "Hypothesis-Generating Brief: Taurine supplementation — full paper"
    paper = source / "full_paper.md"
    paper.write_text(f"# {title}\n", encoding="utf-8")
    _write_json(tmp_path / "runs" / cycle.submit_bridge.LEDGER_DIR / "_submitted_fingerprints.json", [{
        "run": source.name,
        "topic": "taurine",
        "fingerprint": cycle.submit_bridge._sha256(paper),
    }])
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_quant_claim_source_precision", lambda *_a, **_k: (True, "source_topic_precision_ok:67/67", []))
    monkeypatch.setattr(cycle, "_receipt_preflight", lambda *_a, **_k: {"passed": True})
    monkeypatch.setattr(cycle, "_preflight", lambda *_a, **_k: {
        "passed": True,
        "has_manifest": True,
        "n_receipts": 67,
        "n_tensions": 727,
        "n_primary_tier": 1,
    })
    monkeypatch.setattr(cycle, "_unmet_revision_asks", lambda *_a, **_k: ["define the non-orthogonal tension count"])
    now = [0.0]
    calls = 0

    def fake_synthesis(_topic_name: str, out_dir: Path, **_kwargs: Any) -> int:
        nonlocal calls
        calls += 1
        assert calls == 1, "second full rerender should be skipped when budget is too low"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "full_paper.md").write_text("# revised\n", encoding="utf-8")
        now[0] = 1301.0
        return 0

    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)
    request = {
        "artifactId": "taurine-review",
        "title": title,
        "feedback": "Define and operationalize the dense evidence-map tension figure.",
        "reviewedAt": (dt.datetime.now(dt.UTC) - dt.timedelta(hours=1)).isoformat(),
    }

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-06-24",
        run_synthesis=True,
        submit=True,
        mode="revise",
        remote_loader=lambda: (set(), None),
        revision_loader=lambda: ([dict(request)], None),
        submit_cycle=lambda **_kwargs: (_ for _ in ()).throw(AssertionError("unmet revise must not submit")),
        ensure_corpus=lambda *_a, **_k: {"status": "corpus_ready", "n_quant_claims": cycle.PREFLIGHT_MIN_QUANT_CLAIMS},
        max_revise_attempts=2,
        cycle_budget_seconds=2400,
        clock=lambda: now[0],
    )

    assert calls == 1
    assert ledger["status"] == "terminal_revise_retry_budget_insufficient"
    assert ledger["attempts"][0]["gate_status"] == "revision_coverage_unmet"
    assert ledger["attempts"][1]["gate_status"] == "terminal_revise_retry_budget_insufficient"
    assert ledger["attempts"][1]["remaining_budget_seconds"] == 1099
    handled = json.loads((tmp_path / "runs" / cycle.LEDGER_DIR / cycle.HANDLED_REVISIONS).read_text(encoding="utf-8"))
    assert handled["handled"][-1]["status"] == "terminal_revise_retry_budget_insufficient"


def test_cycle_seeds_missing_quant_claim_corpus_before_synthesis(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "new_topic", corpus=False, target_journal=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_receipt_preflight", lambda topic, out_dir, **_k: {"passed": True})
    monkeypatch.setattr(cycle, "_current_low_source_precision_topics", lambda topics: set())
    monkeypatch.setattr(cycle, "_quant_claim_source_precision", lambda topic, **_k: (True, "source_topic_precision_ok:57/57", []))
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


def test_fresh_publish_tops_up_partial_quant_corpus_before_synthesis(tmp_path: Path, monkeypatch) -> None:
    topic = "partial_frontier"
    _topic(tmp_path, topic, corpus=False, target_journal=True)
    qdir = tmp_path / "docs" / "quality-reference" / topic / "quant_claims"
    qdir.mkdir(parents=True)
    for i in range(4):
        _write_json(qdir / f"partial-{i}.quant_claims.json", {"paper_id": f"partial {i}"})
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_current_low_source_precision_topics", lambda _topics: set())
    monkeypatch.setattr(cycle, "_quant_claim_source_precision", lambda *_a, **_k: (
        True, "source_topic_precision_ok:10/10", [],
    ))
    monkeypatch.setattr(cycle, "_receipt_preflight", lambda *_a, **_k: {"passed": True})
    seeded: list[str] = []
    synthesized: list[str] = []

    def fake_seed(selected: str, **_kwargs: Any) -> dict[str, Any]:
        seeded.append(selected)
        before = cycle._quant_claim_count(selected)
        for i in range(before, cycle.PREFLIGHT_MIN_QUANT_CLAIMS):
            _write_json(qdir / f"seed-{i}.quant_claims.json", {"paper_id": f"seed {i}"})
        return {
            "status": "corpus_seeded",
            "n_quant_claims_before": before,
            "n_quant_claims": cycle.PREFLIGHT_MIN_QUANT_CLAIMS,
        }

    def fake_synthesis(selected: str, out_dir: Path, **_kwargs: Any) -> int:
        synthesized.append(selected)
        out_dir.mkdir(parents=True)
        return 0

    monkeypatch.setattr(cycle, "_seed_topic", fake_seed)
    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-06-25",
        run_synthesis=True,
        submit=True,
        mode="fresh",
        remote_loader=lambda: (set(), None),
        submit_cycle=lambda **_kwargs: {"status": "submitted_to_researka", "submitted": 1, "published": 0},
        max_attempts=1,
    )

    assert seeded == [topic]
    assert synthesized == [topic]
    assert ledger["status"] == "submitted_to_researka"
    assert ledger["frontier_corpus_seed"]["n_quant_claims_before"] == 4


def test_cycle_passes_remaining_budget_to_child_work(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "budget_topic", target_journal=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_quant_claim_source_precision", lambda *_a, **_k: (
        True, "source_topic_precision_ok:10/10", [],
    ))
    calls: dict[str, int | None] = {}
    now = 995.0

    def fake_clock() -> float:
        nonlocal now
        now += 5.0
        return now

    def fake_corpus(topic: str, *, dry_run: bool, timeout: int | None = None) -> dict[str, Any]:
        calls["corpus_timeout"] = timeout
        return {"status": "corpus_ready", "n_quant_claims": cycle.PREFLIGHT_MIN_QUANT_CLAIMS}

    def fake_receipt(topic: str, out_dir: Path, *, timeout: int | None = None, **_kwargs: Any) -> dict[str, Any]:
        calls["receipt_timeout"] = timeout
        return {"passed": True}

    def fake_synthesis(topic: str, out_dir: Path, *, dry_run: bool, timeout: int | None = None, **_kwargs: Any) -> int:
        calls["synthesis_timeout"] = timeout
        out_dir.mkdir(parents=True)
        return 0

    monkeypatch.setattr(cycle, "_receipt_preflight", fake_receipt)
    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-06-21",
        run_synthesis=True,
        submit=True,
        topic="budget_topic",
        remote_loader=lambda: (set(), None),
        submit_cycle=lambda **_kwargs: {"status": "submitted_to_researka", "submitted": 1, "published": 0},
        ensure_corpus=fake_corpus,
        cycle_budget_seconds=40,
        clock=fake_clock,
    )

    assert ledger["status"] == "submitted_to_researka"
    assert calls["corpus_timeout"] is not None
    assert calls["receipt_timeout"] is not None
    assert calls["synthesis_timeout"] is not None
    assert calls["corpus_timeout"] <= 40
    assert calls["receipt_timeout"] < calls["corpus_timeout"]
    assert calls["synthesis_timeout"] < calls["receipt_timeout"]


def test_cycle_skips_empty_seed_and_tries_next_topic(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "aaa_empty", corpus=False, target_journal=True)
    _topic(tmp_path, "zzz_seeded", corpus=False, target_journal=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_receipt_preflight", lambda topic, out_dir, **_k: {"passed": True})
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


def test_cycle_repairs_thin_quant_corpus_before_skip(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "thin_topic", corpus=False, target_journal=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    repairs: list[dict[str, Any]] = []

    def no_synthesis(*_args: Any, **_kwargs: Any) -> int:
        raise AssertionError("thin corpus should not reach synthesis")

    def fake_repair(
        topic: str,
        *,
        dry_run: bool,
        timeout: int | None = None,
        seed_limit: int | None = None,
    ) -> dict[str, Any]:
        repair = {
            "status": "corpus_repaired",
            "n_quant_claims": 3,
            "topic": topic,
            "dry_run": dry_run,
            "timeout": timeout,
            "seed_limit": seed_limit,
        }
        repairs.append(repair)
        return repair

    monkeypatch.setattr(cycle, "_run_synthesis", no_synthesis)
    monkeypatch.setattr(cycle, "_repair_topic_corpus", fake_repair)
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
    assert [row["seed_limit"] for row in ledger["attempts"][0]["quant_corpus_repairs"]] == [
        cycle.AUTO_SEED_LIMIT * 2,
        cycle.AUTO_SEED_LIMIT * 3,
    ]
    assert ledger["attempts"][0]["quant_corpus_repairs"] == repairs


def test_cycle_repairs_thin_quant_corpus_then_submits(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "thin_topic", corpus=False, target_journal=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_receipt_preflight", lambda topic, out_dir, **_k: {"passed": True})
    n_claims = {"value": 4}
    repairs: list[dict[str, Any]] = []
    synthesized: list[str] = []

    def fake_corpus(topic: str, *, dry_run: bool, timeout: int | None = None) -> dict[str, Any]:
        return {"status": "corpus_ready", "n_quant_claims": n_claims["value"]}

    def fake_repair(
        topic: str,
        *,
        dry_run: bool,
        timeout: int | None = None,
        seed_limit: int | None = None,
    ) -> dict[str, Any]:
        n_claims["value"] = cycle.PREFLIGHT_MIN_QUANT_CLAIMS
        repair = {
            "status": "corpus_repaired",
            "n_quant_claims": n_claims["value"],
            "seed_limit": seed_limit,
        }
        repairs.append(repair)
        return repair

    def fake_synthesis(topic: str, out_dir: Path, **_kwargs: Any) -> int:
        synthesized.append(topic)
        out_dir.mkdir(parents=True)
        return 0

    monkeypatch.setattr(cycle, "_repair_topic_corpus", fake_repair)
    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-06-05",
        run_synthesis=True,
        submit=True,
        remote_loader=lambda: (set(), None),
        submit_cycle=lambda **_kwargs: {"status": "submitted_to_researka", "submitted": 1, "published": 0},
        ensure_corpus=fake_corpus,
        max_attempts=1,
    )

    assert ledger["status"] == "submitted_to_researka"
    assert synthesized == ["thin_topic"]
    assert ledger["attempts"][0]["quant_corpus_repairs"] == repairs
    assert repairs[0]["seed_limit"] == cycle.AUTO_SEED_LIMIT * 2


def test_fresh_cycle_keeps_searching_after_failed_quant_repair_by_default(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "aaa_thin_topic", corpus=False, target_journal=True)
    _topic(tmp_path, "zzz_solid_topic", corpus=False, target_journal=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_topic_support_score", lambda topic: 100 if topic == "aaa_thin_topic" else 10)
    monkeypatch.setattr(cycle, "_receipt_preflight", lambda topic, out_dir, **_k: {"passed": True})
    synthesized: list[str] = []

    def fake_corpus(topic: str, *, dry_run: bool, timeout: int | None = None) -> dict[str, Any]:
        if topic == "aaa_thin_topic":
            return {"status": "corpus_ready", "n_quant_claims": 4}
        return {"status": "corpus_ready", "n_quant_claims": cycle.PREFLIGHT_MIN_QUANT_CLAIMS}

    def fake_repair(
        topic: str,
        *,
        dry_run: bool,
        timeout: int | None = None,
        seed_limit: int | None = None,
    ) -> dict[str, Any]:
        return {"status": "corpus_repaired", "n_quant_claims": 4, "seed_limit": seed_limit}

    def fake_synthesis(topic: str, out_dir: Path, **_kwargs: Any) -> int:
        synthesized.append(topic)
        out_dir.mkdir(parents=True)
        return 0

    monkeypatch.setattr(cycle, "_repair_topic_corpus", fake_repair)
    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-06-05",
        run_synthesis=True,
        submit=True,
        remote_loader=lambda: (set(), None),
        submit_cycle=lambda **_kwargs: {"status": "submitted_to_researka", "submitted": 1, "published": 0},
        ensure_corpus=fake_corpus,
    )

    assert ledger["status"] == "submitted_to_researka"
    assert [attempt["topic"] for attempt in ledger["attempts"]] == ["aaa_thin_topic", "zzz_solid_topic"]
    assert ledger["attempts"][0]["submit_status"] == "preflight_thin_quant_corpus"
    assert synthesized == ["zzz_solid_topic"]


def test_receipt_preflight_stops_when_repair_does_not_improve_receipts(tmp_path: Path, monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setenv("RESEARCH_AGENT_RECEIPT_PREFLIGHT_REPAIR_ROUNDS", "3")
    monkeypatch.setattr(cycle, "_quant_claim_count", lambda _topic: 13)

    def fake_synthesis(_topic: str, out_dir: Path, **_kwargs: Any) -> int:
        calls.append(out_dir.name)
        out_dir.mkdir(parents=True)
        _write_json(out_dir / "receipt_funnel.json", {"counts": {"admitted_receipts": 1}})
        return 0

    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)
    monkeypatch.setattr(cycle, "_repair_topic_corpus", lambda *_args, **_kwargs: {
        "status": "corpus_repaired",
        "n_quant_claims": 13,
    })

    result = cycle._receipt_preflight("thin_topic", tmp_path / "runs" / "synthesis-thin_topic-v06-test")

    assert result["passed"] is False
    assert result["n_receipts"] == 1
    assert len(result["probes"]) == 2
    assert len(calls) == 2


def test_receipt_preflight_does_not_repair_zero_receipt_probe(tmp_path: Path, monkeypatch) -> None:
    repairs: list[str] = []
    monkeypatch.setenv("RESEARCH_AGENT_RECEIPT_PREFLIGHT_REPAIR_ROUNDS", "3")

    def fake_synthesis(_topic: str, out_dir: Path, **_kwargs: Any) -> int:
        out_dir.mkdir(parents=True)
        _write_json(out_dir / "receipt_funnel.json", {"counts": {"admitted_receipts": 0}})
        return 0

    def fake_repair(topic: str, **_kwargs: Any) -> dict[str, Any]:
        repairs.append(topic)
        return {"status": "corpus_repaired"}

    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)
    monkeypatch.setattr(cycle, "_repair_topic_corpus", fake_repair)

    result = cycle._receipt_preflight("zero_topic", tmp_path / "runs" / "synthesis-zero_topic-v06-test")

    assert result["passed"] is False
    assert result["n_receipts"] == 0
    assert len(result["probes"]) == 1
    assert repairs == []


def test_receipt_preflight_does_not_repair_zero_receipt_failed_probe(tmp_path: Path, monkeypatch) -> None:
    repairs: list[str] = []
    monkeypatch.setenv("RESEARCH_AGENT_RECEIPT_PREFLIGHT_REPAIR_ROUNDS", "3")
    monkeypatch.setattr(cycle, "_quant_claim_count", lambda _topic: 120)

    def fake_synthesis(_topic: str, out_dir: Path, **_kwargs: Any) -> int:
        out_dir.mkdir(parents=True)
        _write_json(out_dir / "receipt_funnel.json", {"counts": {"admitted_receipts": 0}})
        return 4

    def fake_repair(topic: str, **_kwargs: Any) -> dict[str, Any]:
        repairs.append(topic)
        return {"status": "corpus_repaired"}

    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)
    monkeypatch.setattr(cycle, "_repair_topic_corpus", fake_repair)

    result = cycle._receipt_preflight("zero_topic", tmp_path / "runs" / "synthesis-zero_topic-v06-test")

    assert result["passed"] is False
    assert result["n_receipts"] == 0
    assert len(result["probes"]) == 1
    assert repairs == []


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
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_ensure_topic_corpus", lambda topic, **_k: {
        "status": "corpus_ready", "n_quant_claims": cycle.PREFLIGHT_MIN_QUANT_CLAIMS,
    })
    monkeypatch.setattr(cycle, "_quant_claim_source_precision", lambda *_a, **_k: (
        True, "source_topic_precision_ok:10/10", [],
    ))
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


def test_revision_domain_scope_reset_matches_imported_longevity_frame() -> None:
    feedback = (
        "Align the scope and abstract with the actual research question and "
        "remove the imported geroscience / anti-aging / longevity framing "
        "that does not match the cited corpus."
    )

    assert cycle._revision_requests_domain_scope_reset(feedback)
    assert not cycle._revision_requests_domain_scope_reset(
        "Tighten the limitations and cite the relevant subgroup evidence.",
    )
    assert not cycle._revision_requests_domain_scope_reset(
        "Reconcile the abstract's '2 direct / 12 adjacent / 1 mechanistic' "
        "framing with the Findings Map's 'direct / indirect / mechanistic' "
        "framing, or define 'adjacent' and 'indirect' consistently across all "
        "sections.; Expand the Tensions and Gaps section to enumerate the "
        "specific 26 cross-study disagreements by pairing Kemna 2025 positive "
        "AD-biomarker signal vs. the null longevity class.; Either remove "
        "sources whose design is review/perspective/bioinformatics from the "
        "admitted direct-evidence counting, or relabel them."
    )
    assert not cycle._revision_requests_domain_scope_reset(
        "Reframe the conclusion away from anti-aging endorsement; add the "
        "missing bundle sources to the Results outcome slices; recode direction "
        "values and report excluded-with-reasons in the screening flow."
    )
    assert not cycle._revision_requests_domain_scope_reset(
        "Reframe research question and conclusion so the retained set is not "
        "direct interventional/clinical efficacy.; Reconcile each cited source's "
        "effect_direction with the actual reported finding in excerpt.; Add explicit "
        "statement no direct interventional hard-endpoint sources admitted; remove "
        "clinical actionability/anti-aging framing.; Verify 2026-dated sources for "
        "actual publication status and preprint distinction."
    )


def test_revise_lane_marks_domain_scope_mismatch_terminal(tmp_path: Path, monkeypatch) -> None:
    topic = "influenza_vaccination_rates"
    _topic(tmp_path, topic, target_journal=True)
    source = _prior_run(tmp_path, topic, receipts=26, tensions=153, primary=9, level=5)
    title = "Research Synthesis: Influenza Vaccination Rates — full paper"
    paper = source / "full_paper.md"
    paper.write_text(f"# {title}\n", encoding="utf-8")
    _write_json(tmp_path / "runs" / cycle.submit_bridge.LEDGER_DIR / "_submitted_fingerprints.json", [{
        "run": source.name,
        "topic": topic,
        "fingerprint": cycle.submit_bridge._sha256(paper),
    }])
    request = {
        "artifactId": "flu-review",
        "title": title,
        "topic": topic,
        "feedback": (
            "Remove the geroscience / anti-aging / longevity framing throughout, "
            "as the source bundle does not support this thematic overlay."
        ),
        "reviewedAt": (dt.datetime.now(dt.UTC) - dt.timedelta(minutes=5)).isoformat(),
    }
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_run_synthesis", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("scope-mismatch revise must not synthesize")))

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-06-24",
        run_synthesis=True,
        submit=True,
        mode="revise",
        remote_loader=lambda: (set(), None),
        revision_loader=lambda: ([dict(request)], None),
        submit_cycle=lambda **_kwargs: (_ for _ in ()).throw(AssertionError("scope-mismatch revise must not submit")),
    )

    assert ledger["status"] == "revise_terminal_domain_scope_mismatch"
    assert ledger["attempts"][0]["gate_status"] == "terminal_domain_scope_mismatch"
    assert ledger["attempts"][0]["failure_class"] == "D_no_action"
    handled = json.loads((tmp_path / "runs" / cycle.LEDGER_DIR / cycle.HANDLED_REVISIONS).read_text(encoding="utf-8"))
    assert handled["handled"][0]["status"] == "terminal_domain_scope_mismatch"


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
    monkeypatch.delenv("RESEARCH_AGENT_SEED_SOURCES", raising=False)
    monkeypatch.delenv("V5_MEMO_FULL_RAW_CORPUS_SEARCH_URL", raising=False)
    monkeypatch.delenv("V5_MEMO_FULL_RAW_CORPUS_TOKEN", raising=False)
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


def test_seed_topic_bounds_v5_timeout_without_forcing_v5_only(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.delenv("RESEARCH_AGENT_SEED_SOURCES", raising=False)
    monkeypatch.setenv("V5_MEMO_FULL_RAW_CORPUS_SEARCH_URL", "http://127.0.0.1:9903/search")
    monkeypatch.setenv("V5_MEMO_FULL_RAW_CORPUS_TOKEN", "token")
    monkeypatch.setenv("RESEARCH_AGENT_DISCOVERY_TIMEOUT_SECONDS", "17")
    monkeypatch.setenv("RESEARCH_AGENT_SEED_TOPIC_TIMEOUT_SECONDS", "91")
    seen: dict[str, Any] = {}

    def fake_run(cmd: list[str], **_kwargs: Any) -> Any:
        seen["cmd"] = cmd
        seen["env"] = _kwargs["env"]
        seen["timeout"] = _kwargs["timeout"]
        return cycle.subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(cycle.subprocess, "run", fake_run)

    result = cycle._seed_topic("new_topic", seed_limit=7)

    assert result["status"] == "corpus_seed_empty"
    assert "--sources" not in seen["cmd"]
    assert seen["env"]["V5_MEMO_FULL_RAW_QUERY_TIMEOUT"] == "17.0"
    assert seen["timeout"] == 91


def test_seed_topic_source_env_override_wins(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setenv("RESEARCH_AGENT_SEED_SOURCES", "pubmed,europepmc openalex")
    monkeypatch.setenv("RESEARCH_AGENT_DISCOVERY_TIMEOUT_SECONDS", "17")
    monkeypatch.setenv("V5_MEMO_FULL_RAW_CORPUS_SEARCH_URL", "http://127.0.0.1:9903/search")
    monkeypatch.setenv("V5_MEMO_FULL_RAW_CORPUS_TOKEN", "token")
    seen: dict[str, Any] = {}

    def fake_run(cmd: list[str], **_kwargs: Any) -> Any:
        seen["cmd"] = cmd
        seen["env"] = _kwargs["env"]
        return cycle.subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(cycle.subprocess, "run", fake_run)

    result = cycle._seed_topic("new_topic", seed_limit=7)

    assert result["status"] == "corpus_seed_empty"
    assert seen["cmd"][-4:] == ["--sources", "pubmed", "europepmc", "openalex"]
    assert "V5_MEMO_FULL_RAW_QUERY_TIMEOUT" not in seen["env"]


def test_seed_topic_timeout_with_claims_stays_gate_checkable(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setenv("RESEARCH_AGENT_SEED_TOPIC_TIMEOUT_SECONDS", "17")
    seen: dict[str, Any] = {}

    def slow_run(cmd: list[str], **kwargs: Any) -> Any:
        seen["timeout"] = kwargs["timeout"]
        qdir = cycle.CORPORA / "new_topic" / "quant_claims"
        qdir.mkdir(parents=True)
        _write_json(qdir / "seed.quant_claims.json", {"paper_id": "seed", "claims": []})
        raise cycle.subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs["timeout"], stderr="report written")

    monkeypatch.setattr(cycle.subprocess, "run", slow_run)

    result = cycle._ensure_topic_corpus("new_topic", dry_run=False, timeout=999)

    assert result["status"] == "corpus_seeded"
    assert result["return_code"] == cycle.SYNTHESIS_TIMEOUT_RETURN_CODE
    assert result["seed_timeout_expired"] is True
    assert result["n_quant_claims"] == 1
    assert result["stderr_tail"] == "report written"
    assert seen["timeout"] == 17


def test_cycle_separates_attempted_topic_from_submitted_bridge_candidate(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "acarbose", target_journal=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_quant_claim_source_precision", lambda *_a, **_k: (
        True, "source_topic_precision_ok:10/10", [],
    ))
    monkeypatch.setattr(cycle, "_receipt_preflight", lambda topic, out_dir, **_k: {"passed": True})
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


def test_cycle_records_no_submission_reason_from_submit_bridge(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "epigenome_editing_longevity", target_journal=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_quant_claim_source_precision", lambda *_a, **_k: (
        True, "source_topic_precision_ok:10/10", [],
    ))
    monkeypatch.setattr(cycle, "_receipt_preflight", lambda topic, out_dir, **_k: {"passed": True})
    runs: list[str] = []
    monkeypatch.setattr(cycle, "_repair_low_source_precision_corpus", lambda topic, **_k: {
        "status": "source_precision_repair_incomplete",
        "source_topic_precision_after": "source_topic_precision_low:1/4<0.50",
    })

    def fake_synthesis(
        topic: str,
        out_dir: Path,
        *,
        dry_run: bool,
        timeout: int | None = None,
        revision_feedback: str | None = None,
        review_type_override: str | None = None,
    ) -> int:
        runs.append(out_dir.name)
        out_dir.mkdir(parents=True)
        return 0

    def fake_submit(**_kwargs: Any) -> dict[str, Any]:
        return {
            "status": "no_eligible_research_paper",
            "submitted": 0,
            "published": 0,
            "considered": [{"run": runs[-1], "status": "source_topic_precision_low:1/4<0.50"}],
        }

    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-06-01",
        run_synthesis=True,
        submit=True,
        remote_loader=lambda: (set(), None),
        submit_cycle=fake_submit,
        max_attempts=1,
    )

    assert ledger["status"] == "synthesis_completed_no_submission"
    assert ledger["no_submission_reason"] == "source_topic_precision_low:1/4<0.50"
    assert ledger["attempts"][0]["gate_status"] == "source_topic_precision_low:1/4<0.50"


def test_cycle_salvages_daily_slot_with_next_topic(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "acarbose", target_journal=True)
    _topic(tmp_path, "creatine", target_journal=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_quant_claim_source_precision", lambda *_a, **_k: (
        True, "source_topic_precision_ok:10/10", [],
    ))
    monkeypatch.setattr(cycle, "_receipt_preflight", lambda topic, out_dir, **_k: {"passed": True})
    topics: list[str] = []
    submit_calls = 0

    def fake_synthesis(
        topic: str,
        out_dir: Path,
        *,
        dry_run: bool,
        timeout: int | None = None,
        revision_feedback: str | None = None,
        review_type_override: str | None = None,
    ) -> int:
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


def test_cycle_rotates_after_same_gate_fails_twice(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "rapamycin", target_journal=True)
    _topic(tmp_path, "creatine", target_journal=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_quant_claim_source_precision", lambda *_a, **_k: (
        True, "source_topic_precision_ok:10/10", [],
    ))
    monkeypatch.setattr(cycle, "_receipt_preflight", lambda topic, out_dir, **_k: {"passed": True})
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
                "revision_feedback": "Internal gate feedback should not disable duplicate-gate rotation.",
                "considered": [{"run": runs[-1], "status": "audit_not_all_green"}],
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
    assert topics == ["creatine", "creatine", "rapamycin"]
    assert [a["revise_attempt"] for a in ledger["attempts"]] == [1, 2, 1]
    assert "R2" in ledger["attempts"][1]["out_dir"]
    assert ledger["attempts"][1]["same_gate_repeat_stop"] is True
    assert "R3" not in ledger["attempts"][2]["out_dir"]


def test_cycle_regenerates_after_researka_rejection_before_rotating(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "rapamycin", target_journal=True)
    _topic(tmp_path, "creatine", target_journal=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_receipt_preflight", lambda topic, out_dir, **_k: {"passed": True})
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
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_receipt_preflight", lambda topic, out_dir, **_k: {"passed": True})
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
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_receipt_preflight", lambda topic, out_dir, **_k: {"passed": True})
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
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_receipt_preflight", lambda topic, out_dir, **_k: {"passed": True})
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
        decision_poll_seconds=0,
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


# --- Coverage gate: every reviewer ask must be addressed before submit -------

def _seed_delayed_revise(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "aspirin_geroprotection", target_journal=True)
    source_run = _prior_run(tmp_path, "aspirin_geroprotection", receipts=57, tensions=274, level=5)
    paper = source_run / "full_paper.md"
    paper.write_text("# Research Synthesis: Aspirin Geroprotection — full paper\n\n## Abstract\n\nA.", encoding="utf-8")
    _write_json(tmp_path / "runs" / cycle.submit_bridge.LEDGER_DIR / "_submitted_fingerprints.json", [{
        "date": "2026-05-27", "run": source_run.name, "topic": "aspirin_geroprotection",
        "fingerprint": cycle.submit_bridge._sha256(paper)}])
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_receipt_preflight", lambda topic, out_dir, **_k: {"passed": True})


def _aspirin_revise_loader() -> tuple[list[dict[str, Any]], None]:
    return ([{"artifactId": "rev-1", "submissionId": "sub-1",
              "title": "Research Synthesis: Aspirin Geroprotection — full paper",
              "feedback": "Hedge the cognitive claims"}], None)


def _coverage_fake_synthesis(feedback_seen: list[str | None], paper_md: str | None = None):
    def fake(topic: str, out_dir: Path, *, dry_run: bool, timeout: int | None = None,
             revision_feedback: str | None = None, review_type_override: str | None = None) -> int:
        feedback_seen.append(revision_feedback)
        out_dir.mkdir(parents=True)
        (out_dir / "full_paper.md").write_text(
            paper_md or "# Research Synthesis: Aspirin Geroprotection — full paper\n\n## Abstract\n\nA.", encoding="utf-8")
        return 0
    return fake


def _run_coverage_cycle(
    tmp_path: Path,
    monkeypatch,
    *,
    unmet,
    submit_cycle,
    max_revise_attempts=3,
    paper_md: str | None = None,
    mode: str = "mixed",
):
    feedback_seen: list[str | None] = []
    monkeypatch.setattr(cycle, "_run_synthesis", _coverage_fake_synthesis(feedback_seen, paper_md))
    monkeypatch.setattr(cycle, "_unmet_revision_asks", lambda out_dir, fb: list(unmet))
    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs", date="2026-05-28", run_synthesis=True, submit=True,
        remote_loader=lambda: (set(), None), revision_loader=_aspirin_revise_loader,
        submit_cycle=submit_cycle, max_revise_attempts=max_revise_attempts, mode=mode)
    return ledger, feedback_seen


def test_coverage_all_asks_met_allows_submit(tmp_path: Path, monkeypatch) -> None:
    _seed_delayed_revise(tmp_path, monkeypatch)
    ledger, _ = _run_coverage_cycle(
        tmp_path, monkeypatch, unmet=[],
        submit_cycle=lambda **_k: {"status": "submitted_to_researka", "submitted": 1, "published": 0},
        mode="revise",
    )
    assert ledger["attempts"][0]["submitted"] == 1                    # all asks met -> submitted
    assert "unmet_revision_asks" not in ledger["attempts"][0]
    gate = json.loads((tmp_path / "runs" / ledger["attempts"][0]["out_dir"] / cycle.REVISION_COVERAGE_GATE).read_text())
    assert gate["passed"] is True


def test_revise_reuses_existing_source_receipt_floor(tmp_path: Path, monkeypatch) -> None:
    _seed_delayed_revise(tmp_path, monkeypatch)
    monkeypatch.setattr(
        cycle,
        "_ensure_topic_corpus",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("revise source manifest should skip corpus seeding")),
    )
    monkeypatch.setattr(
        cycle,
        "_receipt_preflight",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("revise source already passed receipt floor")),
    )

    ledger, _ = _run_coverage_cycle(
        tmp_path, monkeypatch, unmet=[],
        submit_cycle=lambda **_k: {"status": "submitted_to_researka", "submitted": 1, "published": 0},
        mode="revise",
    )

    assert ledger["attempts"][0]["receipt_preflight"]["status"] == "receipt_preflight_existing_ok"
    assert ledger["corpus"]["source"] == "existing_source_manifest"
    assert ledger["attempts"][0]["submitted"] == 1


def test_revise_with_existing_source_manifest_ignores_stale_topic_cooldown(tmp_path: Path, monkeypatch) -> None:
    topic = "cardiovascular_subgroups"
    _topic(tmp_path, topic)
    source = _prior_run(tmp_path, topic, receipts=63, tensions=367, primary=21, level=5)
    paper = source / "full_paper.md"
    title = "Research Synthesis: Cardiovascular Subgroups — full paper"
    paper.write_text(f"# {title}\n\n## Abstract\n\nA.", encoding="utf-8")
    _write_json(tmp_path / "runs" / cycle.submit_bridge.LEDGER_DIR / "_submitted_fingerprints.json", [{
        "date": "2026-06-25",
        "run": source.name,
        "topic": topic,
        "fingerprint": cycle.submit_bridge._sha256(paper),
    }])
    ledger_dir = tmp_path / "runs" / cycle.LEDGER_DIR
    _write_json(ledger_dir / "2026-06-25-old.json", {
        "started_at": _recent_start(),
        "attempts": [
            {"topic": topic, "submitted": 0},
            {"topic": topic, "submitted": 0},
        ],
    })
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_unmet_revision_asks", lambda *_a, **_k: [])
    feedback_seen: list[str | None] = []
    monkeypatch.setattr(cycle, "_run_synthesis", _coverage_fake_synthesis(feedback_seen))
    preflights: list[dict[str, Any]] = []
    original_preflight = cycle._preflight

    def spy_preflight(*args: Any, **kwargs: Any) -> dict[str, Any]:
        result = original_preflight(*args, **kwargs)
        preflights.append(result)
        return result

    monkeypatch.setattr(cycle, "_preflight", spy_preflight)

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-06-25",
        run_synthesis=True,
        submit=True,
        mode="revise",
        remote_loader=lambda: (set(), None),
        revision_loader=lambda: ([{
            "artifactId": "cardio-review",
            "submissionId": "sub-cardio",
            "title": title,
            "feedback": "Revise with a clearer Findings Map.",
        }], None),
        submit_cycle=lambda **_kwargs: {"status": "submitted_to_researka", "submitted": 1, "published": 0},
    )

    attempt = ledger["attempts"][0]
    assert ledger["status"] == "submitted_to_researka"
    assert preflights[-1]["recent_failed_attempts"] == 2
    assert not any("recent_failed_attempts=" in reason for reason in preflights[-1]["reasons"])
    assert attempt["receipt_preflight"]["status"] == "receipt_preflight_existing_ok"
    assert attempt["submitted"] == 1
    assert feedback_seen == ["Revise with a clearer Findings Map."]


def test_revise_source_manifest_drift_fails_fast_before_synthesis(tmp_path: Path, monkeypatch) -> None:
    _seed_delayed_revise(tmp_path, monkeypatch)
    qdir = tmp_path / "docs" / "quality-reference" / "aspirin_geroprotection" / "quant_claims"
    for idx in range(cycle.PREFLIGHT_MIN_RECEIPTS - 1, 57):
        (qdir / f"r{idx}.quant_claims.json").unlink()
    monkeypatch.setattr(
        cycle,
        "_run_synthesis",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("unavailable source manifest must not synthesize")),
    )

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-05-28",
        run_synthesis=True,
        submit=True,
        mode="revise",
        remote_loader=lambda: (set(), None),
        revision_loader=_aspirin_revise_loader,
        submit_cycle=lambda **_k: {"status": "submitted_to_researka", "submitted": 1, "published": 0},
    )

    attempt = ledger["attempts"][0]
    assert ledger["status"] == "terminal_revision_source_manifest_unavailable"
    assert attempt["gate_status"] == "terminal_revision_source_manifest_unavailable"
    assert attempt["source_manifest_availability"]["n_source_receipts"] == 57
    assert attempt["source_manifest_availability"]["n_available_quant_claim_files"] == cycle.PREFLIGHT_MIN_RECEIPTS - 1
    handled = json.loads((tmp_path / "runs" / cycle.LEDGER_DIR / cycle.HANDLED_REVISIONS).read_text(encoding="utf-8"))
    assert handled["handled"][0]["status"] == "terminal_revision_source_manifest_unavailable"


def test_revise_restores_source_manifest_files_from_quarantine(tmp_path: Path, monkeypatch) -> None:
    _seed_delayed_revise(tmp_path, monkeypatch)
    qdir = tmp_path / "docs" / "quality-reference" / "aspirin_geroprotection" / "quant_claims"
    quarantine = tmp_path / "docs" / "quality-reference" / "aspirin_geroprotection" / "quant_claims_quarantine" / "old"
    quarantine.mkdir(parents=True)
    for idx in range(cycle.PREFLIGHT_MIN_RECEIPTS - 1, 57):
        (qdir / f"r{idx}.quant_claims.json").rename(quarantine / f"r{idx}.quant_claims.json")
    calls: list[str] = []

    def fake_synthesis(
        topic: str,
        out_dir: Path,
        *,
        dry_run: bool,
        timeout: int | None = None,
        revision_feedback: str | None = None,
        review_type_override: str | None = None,
    ) -> int:
        calls.append(topic)
        out_dir.mkdir(parents=True)
        (out_dir / "full_paper.md").write_text("# Research Synthesis: Aspirin Geroprotection\n", encoding="utf-8")
        return 0

    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)
    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-05-28",
        run_synthesis=True,
        submit=True,
        mode="revise",
        remote_loader=lambda: (set(), None),
        revision_loader=_aspirin_revise_loader,
        submit_cycle=lambda **_k: {"status": "submitted_to_researka", "submitted": 1, "published": 0},
    )

    assert calls == ["aspirin_geroprotection"]
    assert ledger["source_manifest_restore"]["n_restored"] == 57 - (cycle.PREFLIGHT_MIN_RECEIPTS - 1)
    assert ledger["source_manifest_restore"]["availability_after"]["passed"] is True
    assert ledger["attempts"][0]["submitted"] == 1


def test_revise_restores_source_manifest_when_feedback_mentions_source_bundle(tmp_path: Path, monkeypatch) -> None:
    _seed_delayed_revise(tmp_path, monkeypatch)
    qdir = tmp_path / "docs" / "quality-reference" / "aspirin_geroprotection" / "quant_claims"
    quarantine = tmp_path / "docs" / "quality-reference" / "aspirin_geroprotection" / "quant_claims_quarantine" / "old"
    quarantine.mkdir(parents=True)
    for idx in range(cycle.PREFLIGHT_MIN_RECEIPTS - 1, 57):
        (qdir / f"r{idx}.quant_claims.json").rename(quarantine / f"r{idx}.quant_claims.json")
    monkeypatch.setattr(cycle, "_repair_low_source_precision_corpus", lambda *_a, **_k: (
        (_ for _ in ()).throw(AssertionError("source-bundle explanation must not prune corpus"))
    ))
    feedback_seen: list[str | None] = []
    monkeypatch.setattr(cycle, "_run_synthesis", _coverage_fake_synthesis(feedback_seen))

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-05-28",
        run_synthesis=True,
        submit=True,
        mode="revise",
        remote_loader=lambda: (set(), None),
        revision_loader=lambda: ([{
            "artifactId": "rev-1",
            "submissionId": "sub-1",
            "title": "Research Synthesis: Aspirin Geroprotection — full paper",
            "feedback": "Reconcile the outcome-class coding with the actual source bundle.",
        }], None),
        submit_cycle=lambda **_k: {"status": "submitted_to_researka", "submitted": 1, "published": 0},
    )

    assert cycle._revision_requests_source_precision("actual source bundle") is False
    assert cycle._revision_requests_source_precision("remove off-topic sources") is True
    assert ledger["source_manifest_restore"]["n_restored"] == 57 - (cycle.PREFLIGHT_MIN_RECEIPTS - 1)
    assert ledger["source_manifest_restore"]["availability_after"]["passed"] is True
    assert feedback_seen == ["Reconcile the outcome-class coding with the actual source bundle."]
    assert ledger["attempts"][0]["submitted"] == 1


def test_revise_retry_after_synthesis_failure_keeps_source_manifest(tmp_path: Path, monkeypatch) -> None:
    _seed_delayed_revise(tmp_path, monkeypatch)
    calls = 0

    def fake_synthesis(
        topic: str,
        out_dir: Path,
        *,
        dry_run: bool,
        timeout: int | None = None,
        revision_feedback: str | None = None,
        review_type_override: str | None = None,
    ) -> int:
        nonlocal calls
        calls += 1
        if calls == 1:
            return 1
        out_dir.mkdir(parents=True)
        (out_dir / "full_paper.md").write_text(
            "# Research Synthesis: Aspirin Geroprotection — full paper\n\n## Abstract\n\nA.",
            encoding="utf-8",
        )
        return 0

    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)
    monkeypatch.setattr(cycle, "_unmet_revision_asks", lambda out_dir, fb: [])
    monkeypatch.setattr(
        cycle,
        "_receipt_preflight",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("retry must keep source manifest")),
    )

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-05-28",
        run_synthesis=True,
        submit=True,
        mode="revise",
        remote_loader=lambda: (set(), None),
        revision_loader=_aspirin_revise_loader,
        submit_cycle=lambda **_k: {"status": "submitted_to_researka", "submitted": 1, "published": 0},
        max_revise_attempts=2,
    )

    assert calls == 2
    assert ledger["attempts"][0]["gate_status"] == "synthesis_failed"
    assert ledger["attempts"][1]["receipt_preflight"]["status"] == "receipt_preflight_existing_ok"
    assert ledger["attempts"][1]["submitted"] == 1


def test_coverage_unmet_ask_blocks_submit(tmp_path: Path, monkeypatch) -> None:
    _seed_delayed_revise(tmp_path, monkeypatch)
    submitted: list[int] = []

    def fake_submit(**_k: Any) -> dict[str, Any]:
        submitted.append(1)
        return {"status": "submitted_to_researka", "submitted": 1, "published": 0}

    ledger, _ = _run_coverage_cycle(
        tmp_path, monkeypatch, unmet=["Hedge the cognitive claims"], submit_cycle=fake_submit)
    assert submitted == []                                            # one ask unmet -> never submitted
    assert ledger["attempts"][0]["gate_status"] == "revision_coverage_unmet"
    assert ledger["attempts"][0]["unmet_revision_asks"] == ["Hedge the cognitive claims"]
    gate = json.loads((tmp_path / "runs" / ledger["attempts"][0]["out_dir"] / cycle.REVISION_COVERAGE_GATE).read_text())
    assert gate["passed"] is False
    assert gate["unmet_asks"] == ["Hedge the cognitive claims"]
    assert int(ledger.get("submitted") or 0) == 0
    handled = json.loads((tmp_path / "runs" / cycle.LEDGER_DIR / cycle.HANDLED_REVISIONS).read_text())
    assert handled["handled"][0]["status"] == "revision_coverage_unmet"


def test_payload_section_revision_ask_can_be_satisfied_by_payload(tmp_path: Path, monkeypatch) -> None:
    out_dir = tmp_path / "run"
    out_dir.mkdir()
    (out_dir / "full_paper.md").write_text(
        "# Research Synthesis: Topic\n\n"
        "## Abstract\n\nAbstract overview.\n\n"
        "## Results\n\n| Outcome | Signal |\n|---|---|\n| immune | mixed |\n\n"
        "## Conclusion\n\nThe key finding is bounded human application with few direct clinical trials.\n",
        encoding="utf-8",
    )
    _write_json(out_dir / "manifest.json", {"topic": "topic", "receipts": []})
    _write_json(out_dir / "citation_registry.json", {})

    assert cycle._payload_revision_ask_satisfied(
        out_dir,
        "Remove duplication between Evidence Landscape and Key Findings",
    )
    assert not cycle._payload_revision_ask_satisfied(out_dir, "tighten the abstract")


def test_classification_revision_asks_can_be_satisfied_by_public_sections(tmp_path: Path) -> None:
    out_dir = tmp_path / "run"
    out_dir.mkdir()
    (out_dir / "full_paper.md").write_text(
        "# Research Synthesis: Topic\n\n"
        "## Abstract\n\n"
        "No source is classified as direct interventional hard-endpoint evidence.\n\n"
        "## Evidence Snapshot\n\n"
        "### Classification Criteria\n\n"
        "- **Outcome class** is assigned from endpoint and claim text.\n"
        "- **Directness** is coded as direct only when a source tests the topic; "
        "a qualifying direct source would be a human interventional study.\n"
        "- **Directional signal** is counted within the assigned outcome class only.\n"
        "- **Evidence tier** follows the deterministic taxonomy.\n\n"
        "### Source Classification Map\n\n"
        "- Hayashi 2025: outcome=contextual adjacent evidence; directness=mechanistic; "
        "tier=C1; direction=positive; claims=12.\n",
        encoding="utf-8",
    )

    assert cycle._payload_revision_ask_satisfied(
        out_dir,
        "Define the classification criteria used to assign studies to outcome classes and to code directness.",
    )
    assert cycle._payload_revision_ask_satisfied(
        out_dir,
        "Provide a mapping table or list showing which of the 28 bundle sources were assigned to which outcome class.",
    )
    assert cycle._payload_revision_ask_satisfied(
        out_dir,
        "Clarify the definition of 'direct evidence' and provide a qualifying direct source example.",
    )
    assert not cycle._payload_revision_ask_satisfied(
        out_dir,
        "Clarify whether 'no extracted directional signal' means no signal for this specific outcome class.",
    )


def test_conflict_severity_revision_ask_can_be_satisfied_by_public_note(tmp_path: Path) -> None:
    out_dir = tmp_path / "run"
    out_dir.mkdir()
    (out_dir / "full_paper.md").write_text(
        "# Research Synthesis: Topic\n\n"
        "## Methods\n\n"
        "Conflict-map severity note: severity-level-3 disagreements are defined and scored "
        "as material null-versus-positive conflicts. severity-level-4 disagreements are "
        "defined and scored as higher-weight conflicts. The scoring inputs are recorded "
        "in the supplementary contradiction-map and source-audit sidecars.\n",
        encoding="utf-8",
    )

    assert cycle._payload_revision_ask_satisfied(
        out_dir,
        "Add a brief explanation in the main text of how 'severity-level-3' and "
        "'severity-level-4' disagreements are defined and scored, or provide a clear "
        "pointer to the exact supplementary file where this is defined.",
    )
    assert not cycle._payload_revision_ask_satisfied(
        out_dir,
        "Rewrite the Gaps Identified section with actionable future research steps.",
    )


def test_unmet_revision_asks_uses_deterministic_gate_when_judge_fails_open(tmp_path: Path, monkeypatch) -> None:
    import revision_coverage  # type: ignore[import-not-found]

    out_dir = tmp_path / "run"
    out_dir.mkdir()
    (out_dir / "full_paper.md").write_text(
        "# Research Synthesis: Topic\n\n"
        "## Methods\n\nMethods.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(revision_coverage, "unmet_asks", lambda *_args, **_kwargs: [])

    ask = "Define the classification criteria used to assign studies to outcome classes and to code directness."

    assert _REAL_UNMET_REVISION_ASKS(out_dir, ask) == [ask]


def test_unmet_revision_asks_accepts_material_directional_explanation(tmp_path: Path, monkeypatch) -> None:
    import revision_coverage  # type: ignore[import-not-found]

    out_dir = tmp_path / "run"
    out_dir.mkdir()
    (out_dir / "full_paper.md").write_text(
        "# Research Synthesis: Topic\n\n"
        "## Evidence Snapshot\n\n"
        "Directional coding is counted within each assigned outcome class only. A no extracted directional "
        "signal cell means null or unclear coding for that outcome slice; positive and mixed signals in "
        "other outcome classes remain separately reported and do not change that row.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(revision_coverage, "unmet_asks", lambda *_args, **_kwargs: [])

    ask = (
        "Clarify whether 'no extracted directional signal' means no signal for this specific outcome class, "
        "given that some sources report positive or mixed associations elsewhere."
    )

    assert _REAL_UNMET_REVISION_ASKS(out_dir, ask) == []


def test_deterministic_revision_satisfaction_overrides_stale_judge_block(tmp_path: Path, monkeypatch) -> None:
    import revision_coverage  # type: ignore[import-not-found]

    out_dir = tmp_path / "run"
    out_dir.mkdir()
    (out_dir / "full_paper.md").write_text(
        "# Research Synthesis: Brain age MRI\n\n"
        "## Evidence Landscape\n\n"
        "RCT-count reconciliation: this manuscript treats any prior single-RCT wording as a "
        "source-coding count, not as a claim that the underlying trial evidence contains only one RCT. "
        "Substantive evidence synthesis: Huang 2025 showed an immune-dementia null signal, "
        "Kou 2024 reported mixed proteomic brain-age associations, and Jawinski 2025 reported "
        "positive MR signals; these source-level findings inform the bounded conclusion.\n\n"
        "## Key Findings\n\n"
        "Key findings from source synthesis: positive, mixed, and null findings are separated by "
        "source type and directness. Huang 2025 and Kou 2024 do not prove a broad intervention "
        "effect, but they bound the conclusion.\n\n"
        "Source-level findings by outcome class:\n\n"
        "- Cognitive Aging: Huang 2025 reported a null immune-dementia signal, "
        "direction=null, directness=indirect, tier=B2.\n"
        "- Brain Imaging: Kou 2024 reported mixed proteomic brain-age associations, "
        "direction=mixed, directness=indirect, tier=B2.\n"
        "- Genetics: Jawinski 2025 reported positive MR signals, "
        "direction=positive, directness=mechanistic, tier=B2.\n\n"
        "## Methods\n\n"
        "Risk-of-bias appraisal summary: The public appraisal artifact reports 65 source-level "
        "rating rows using RoB-2, ROBINS-I, and SYRCLE; overall ratings are some_concerns=65.\n",
        encoding="utf-8",
    )
    asks = [
        "Provide an actual evidence synthesis in the Evidence Landscape and Key Findings sections. "
        "At minimum, surface the key positive, negative, and mixed findings from the bundle and explain "
        "how they inform the bounded conclusion.",
        "Differentiate Key Findings from Conclusion — the two sections currently contain nearly identical "
        "text and Key Findings should present the substantive evidence-based observations, not a restatement "
        "of the conclusion's caveats.; Report actual RoB-2/ROBINS-I/AMSTAR-2 results for included sources, "
        "or remove the framework name if no appraisal was performed.",
    ]
    monkeypatch.setattr(revision_coverage, "unmet_asks", lambda _paper, _asks: list(asks))

    assert _REAL_UNMET_REVISION_ASKS(out_dir, "; ".join(asks)) == []


def test_payload_truncation_revision_ask_can_be_satisfied_by_payload(tmp_path: Path) -> None:
    out_dir = tmp_path / "run"
    out_dir.mkdir()
    long_abstract = (
        "This synthesis keeps the public abstract sentence safe and bounded. "
        "It repeats enough context to exceed the remote payload limit while still "
        "ending at a complete sentence. "
    ) * 40
    (out_dir / "full_paper.md").write_text(
        "# Research Synthesis: Topic\n\n"
        "## Abstract\n\n"
        f"{long_abstract}\n\n"
        "## Results\n\nEvidence remains mixed.\n\n"
        "## Conclusion\n\nThe conclusion is bounded and complete.\n",
        encoding="utf-8",
    )
    _write_json(out_dir / "manifest.json", {"topic": "topic", "receipts": []})
    _write_json(out_dir / "citation_registry.json", {})

    assert cycle._payload_revision_ask_satisfied(
        out_dir,
        "Fix the truncated text at the end of the Abstract and Research Question sections.",
    )


def test_abstract_only_truncation_revision_ask_accepts_complete_abstract(tmp_path: Path) -> None:
    out_dir = tmp_path / "run"
    out_dir.mkdir()
    (out_dir / "full_paper.md").write_text(
        "# Research Synthesis: Topic\n\n"
        "## Abstract\n\n"
        "This abstract is complete and ends with a normal sentence.\n\n"
        "## Results\n\nEvidence remains mixed.\n",
        encoding="utf-8",
    )

    assert cycle._payload_revision_ask_satisfied(out_dir, "Fix the truncated sentence in the abstract.")


def test_payload_source_bundle_revision_ask_can_be_satisfied_by_payload(tmp_path: Path, monkeypatch) -> None:
    out_dir = tmp_path / "run"
    out_dir.mkdir()
    bundle = [
        {"evidence_type": "primary", "excerpt": "This source reports GDF11 dosing, measured outcomes, and directional effects in a bounded experiment."}
        for _ in range(14)
    ]
    bundle.append({"evidence_type": "review", "excerpt": "This review summarizes context without being counted as primary evidence."})
    monkeypatch.setattr(cycle.submit_bridge, "build_payload", lambda _out_dir: {"source_bundle": bundle})

    assert cycle._payload_revision_ask_satisfied(
        out_dir,
        "Provide abstracts or meaningful source excerpts in source_bundle so directional coding and claim extraction can be verified.",
    )
    assert cycle._payload_revision_ask_satisfied(
        out_dir,
        "Clarify why all source_bundle entries have evidence_type review when the manuscript claims primary and review evidence.",
    )


def test_payload_source_bundle_revision_ask_rejects_generic_registry_summaries(tmp_path: Path, monkeypatch) -> None:
    out_dir = tmp_path / "run"
    out_dir.mkdir()
    monkeypatch.setattr(cycle.submit_bridge, "build_payload", lambda _out_dir: {
        "source_bundle": [{"evidence_type": "review", "excerpt": "NCT123 is registered as a clinical trial."}]
    })

    assert not cycle._payload_revision_ask_satisfied(
        out_dir,
        "Provide abstracts or meaningful source excerpts in source_bundle.",
    )
    assert not cycle._payload_revision_ask_satisfied(
        out_dir,
        "Clarify why all source_bundle entries have evidence_type review when the manuscript claims primary evidence.",
    )


def test_payload_source_bundle_topicality_revision_ask_requires_all_rows_for_all_sources_ask(
    tmp_path: Path, monkeypatch,
) -> None:
    out_dir = tmp_path / "run"
    out_dir.mkdir()
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle.submit_bridge, "build_payload", lambda _out_dir: {
        "metadata": {"topic": "melatonin_aging"},
        "source_bundle": [
            {"title": "Trial A", "excerpt": "Melatonin changed a measured endpoint in randomized adults."},
            {"title": "Trial B", "excerpt": "Melatonin was tested in patients with inflammatory biomarkers."},
            {"title": "Trial C", "excerpt": "A clinical trial measured melatonin effects on sleep and biomarkers."},
            {"title": "Review D", "excerpt": "Melatonin review evidence summarized human trial outcomes."},
            {"title": "Context E", "excerpt": "A broad clinical cohort measured unrelated cardiovascular endpoints."},
        ],
    })

    assert not cycle._payload_revision_ask_satisfied(
        out_dir,
        "Verify that all 50 bundle sources actually address melatonin and aging.",
    )


def test_payload_source_bundle_topicality_revision_ask_accepts_all_specific_rows(tmp_path: Path, monkeypatch) -> None:
    out_dir = tmp_path / "run"
    out_dir.mkdir()
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle.submit_bridge, "build_payload", lambda _out_dir: {
        "metadata": {"topic": "melatonin_aging"},
        "source_bundle": [
            {"title": "Trial A", "excerpt": "Melatonin changed an aging-related endpoint in randomized adults."},
            {"title": "Trial B", "excerpt": "Melatonin was tested in aging patients with inflammatory biomarkers."},
            {"title": "Trial C", "excerpt": "A clinical trial measured melatonin effects on aging biomarkers."},
            {"title": "Review D", "excerpt": "Melatonin review evidence summarized human aging-trial outcomes."},
            {"title": "Mechanistic E", "excerpt": "Melatonin signaling was evaluated in aging-relevant inflammatory pathways."},
        ],
    })

    assert cycle._payload_revision_ask_satisfied(
        out_dir,
        "Verify that all 50 bundle sources actually address melatonin and aging.",
    )


def test_payload_source_bundle_topicality_revision_ask_accepts_labeled_adjacent_context(
    tmp_path: Path, monkeypatch,
) -> None:
    out_dir = tmp_path / "run"
    out_dir.mkdir()
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle.submit_bridge, "build_payload", lambda _out_dir: {
        "metadata": {"topic": "melatonin_aging"},
        "source_bundle": [
            {"title": "Trial A", "excerpt": "Melatonin changed an aging-related endpoint in randomized adults."},
            {"title": "Trial B", "excerpt": "Melatonin was tested in aging patients with inflammatory biomarkers."},
            {"title": "Trial C", "excerpt": "A clinical trial measured melatonin effects on aging biomarkers."},
            {"title": "Review D", "excerpt": "Melatonin review evidence summarized human aging-trial outcomes."},
            {"title": "Context E", "excerpt": "Contextual adjacent evidence: a broader aging cohort measured cardiovascular endpoints."},
        ],
    })

    assert cycle._payload_revision_ask_satisfied(
        out_dir,
        "Remove or reclassify sources whose excerpts clearly address unrelated topics; if contextual adjacent, label explicitly in bundle.",
    )


def test_source_reclassification_ask_accepts_public_classification_map(tmp_path: Path) -> None:
    out_dir = tmp_path / "run"
    out_dir.mkdir()
    (out_dir / "full_paper.md").write_text(
        "\n".join([
            "# Paper",
            "### Source Classification Map",
            "- Trial A: outcome=Immune and Inflammation; direction=null; directness=direct; tier=A1.",
            "- Case B: outcome=Contextual Adjacent Evidence; direction=null; directness=indirect; tier=B2.",
            "Case-report and small-series evidence is coded as low-directness rather than clinical-grade evidence.",
        ]),
        encoding="utf-8",
    )

    assert cycle._payload_revision_ask_satisfied(
        out_dir,
        "Reconcile and correct the source bundle: remove off-topic patient education sources; reclassify case reports to a clearly labeled low-directness / case-report tier rather than pooling them with clinical evidence.",
    )


def test_outcome_attribution_gap_ask_accepts_mapped_outcome_row(tmp_path: Path) -> None:
    out_dir = tmp_path / "run"
    out_dir.mkdir()
    (out_dir / "full_paper.md").write_text(
        "\n".join([
            "# Paper",
            "### Source Classification Map",
            "- Study A: outcome=Mortality and Survival; direction=null; directness=indirect; tier=B2.",
        ]),
        encoding="utf-8",
    )

    assert cycle._payload_revision_ask_satisfied(
        out_dir,
        "Resolve the Mortality and Survival attribution gap: either re-attribute the orphaned narrative rows to their correct outcome class or state explicitly that Mortality and Survival is unsourced in the retained corpus.",
    )


def test_thin_brief_revision_asks_accept_deterministic_source_surfaces(tmp_path: Path) -> None:
    out_dir = tmp_path / "run"
    out_dir.mkdir()
    (out_dir / "full_paper.md").write_text(
        "\n".join([
            "# Paper",
            "## Results",
            "| Evidence domain | Corpus slice | Strongest signal | Directness | Main limitation |",
            "|---|---|---|---|---|",
            "| Vascular age / Cardiometabolic | n=1 | null | 1 direct | thin |",
            "Source examples: Direct vascular-age cohort 2025 (tier=A1; directness=direct; direction=null).",
            "## Limitations",
            "**Design-limit note:** Protocol, mechanistic, observational, or cross-sectional sources are retained for context but cannot support causal claims individually.",
            "## Conclusion",
            "**Direct-source ceiling:** The direct clinical source set is Direct vascular-age cohort 2025 (tier=A1; directness=direct; direction=null).",
            "### Source Classification Map",
            "- Direct vascular-age cohort 2025: outcome=Cardiometabolic; direction=null; directness=direct; tier=A1.",
        ]),
        encoding="utf-8",
    )

    assert cycle._payload_revision_ask_satisfied(
        out_dir,
        "Add substantive narrative under each outcome subsection that links at least one specific quantitative or qualitative finding to its source; In the Conclusion, tie the tiered interpretation to the specific bundle.",
    )
    assert cycle._payload_revision_ask_satisfied(
        out_dir,
        "Clarify which source is the '1 direct clinical source' and state this explicitly so readers can audit the evidence hierarchy.",
    )
    assert cycle._payload_revision_ask_satisfied(
        out_dir,
        "Expand the Limitations to specifically note that several admitted sources are protocols or cross-sectional observational designs that cannot support causal claims even individually.",
    )


def test_payload_source_bundle_topicality_revision_ask_rejects_polluted_bundle(tmp_path: Path, monkeypatch) -> None:
    out_dir = tmp_path / "run"
    out_dir.mkdir()
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle.submit_bridge, "build_payload", lambda _out_dir: {
        "metadata": {"topic": "melatonin_aging"},
        "source_bundle": [
            {"title": "Trial A", "excerpt": "Melatonin changed a measured endpoint in randomized adults."},
            {"title": "Trial B", "excerpt": "Melatonin was tested in patients with inflammatory biomarkers."},
            {"title": "Context C", "excerpt": "A broad clinical cohort measured unrelated cardiovascular endpoints."},
            {"title": "Context D", "excerpt": "A generic review covered unrelated surgery outcomes."},
            {"title": "Context E", "excerpt": "A broad clinical cohort measured unrelated metabolic endpoints."},
        ],
    })

    assert not cycle._payload_revision_ask_satisfied(
        out_dir,
        "Verify that all 50 bundle sources actually address melatonin and aging.",
    )


def test_revision_ask_requires_outcome_findings_mapped_to_source_names(tmp_path: Path) -> None:
    out_dir = tmp_path / "run"
    out_dir.mkdir()
    (out_dir / "full_paper.md").write_text(
        "\n".join([
            "# Paper",
            "## Results",
            "Source-level findings by outcome class:",
            "- Smith 2026: outcome=Immune and Inflammation; direction=null; directness=adjacent; tier=B2.",
            "- Jones 2025: outcome=Mechanistic Signaling; direction=mixed; directness=mechanistic; tier=C1.",
        ]),
        encoding="utf-8",
    )

    assert cycle._payload_revision_ask_satisfied(
        out_dir,
        "Attribute each outcome-class finding to specific cited sources by name and year at the finding level.",
    )


def test_revision_ask_accepts_surface_every_admitted_source_map(tmp_path: Path) -> None:
    out_dir = tmp_path / "run"
    out_dir.mkdir()
    (out_dir / "full_paper.md").write_text(
        "\n".join([
            "# Paper",
            "## Evidence Landscape",
            "### Findings Map",
            "- Smith 2026: outcome=Immune and Inflammation; direction=null; directness=adjacent; tier=B2.",
            "- Jones 2025: outcome=Mechanistic Signaling; direction=mixed; directness=mechanistic; tier=C1.",
        ]),
        encoding="utf-8",
    )

    assert cycle._payload_revision_ask_satisfied(
        out_dir,
        "Surface every admitted source; redesign outcome taxonomy; recode direction values.",
    )


def test_revision_ask_accepts_source_reclassification_map(tmp_path: Path) -> None:
    out_dir = tmp_path / "run"
    out_dir.mkdir()
    (out_dir / "full_paper.md").write_text(
        "\n".join([
            "# Paper",
            "## Evidence Landscape",
            "### Source Classification Map",
            "- Trialists 2026: outcome=Clinical Intervention; direction=mixed; directness=direct; tier=A1.",
            "- Reviewers 2025: outcome=Contextual Adjacent Evidence; direction=unclear; directness=review; tier=B2.",
        ]),
        encoding="utf-8",
    )

    assert cycle._payload_revision_ask_satisfied(
        out_dir,
        "Human intervention studies were misclassified as indirect/review evidence.",
    )
    assert cycle._payload_revision_ask_satisfied(
        out_dir,
        "Re-tier mechanistic/context sources and reconcile bundle vs manuscript citations.",
    )


def test_revision_ask_rejects_unmapped_outcome_findings(tmp_path: Path) -> None:
    out_dir = tmp_path / "run"
    out_dir.mkdir()
    (out_dir / "full_paper.md").write_text(
        "# Paper\n\n## Results\n\nThe immune outcome was mixed, with no source-level map.\n",
        encoding="utf-8",
    )

    assert not cycle._payload_revision_ask_satisfied(
        out_dir,
        "Attribute each outcome-class finding to specific cited sources by name and year at the finding level.",
    )


def test_revision_ask_requires_bounded_conclusion_for_breadth_feedback(tmp_path: Path) -> None:
    out_dir = tmp_path / "run"
    out_dir.mkdir()
    (out_dir / "full_paper.md").write_text(
        "# Paper\n\n## Conclusion\n\nThe conclusion is bounded and hypothesis-generating; it does not support clinical efficacy.\n",
        encoding="utf-8",
    )

    assert cycle._payload_revision_ask_satisfied(
        out_dir,
        "Reconcile the conclusion's breadth with the actual evidence slice; narrow the conclusion.",
    )


def test_revision_ask_rejects_overbroad_conclusion(tmp_path: Path) -> None:
    out_dir = tmp_path / "run"
    out_dir.mkdir()
    (out_dir / "full_paper.md").write_text(
        "# Paper\n\n## Conclusion\n\nThis demonstrates clinical efficacy across the retained evidence.\n",
        encoding="utf-8",
    )

    assert not cycle._payload_revision_ask_satisfied(
        out_dir,
        "Reconcile the conclusion's breadth with the actual evidence slice; narrow the conclusion.",
    )


def test_coverage_repeated_ask_escalates_writer_directive(tmp_path: Path, monkeypatch) -> None:
    _seed_delayed_revise(tmp_path, monkeypatch)
    _, feedback_seen = _run_coverage_cycle(
        tmp_path, monkeypatch, unmet=["Hedge the cognitive claims"],
        submit_cycle=lambda **_k: {"status": "submitted_to_researka", "submitted": 1, "published": 0})
    assert feedback_seen[0] == "Hedge the cognitive claims"           # first render: verbatim ask
    assert any("PRIOR REVISION DID NOT ADDRESS" in (f or "") for f in feedback_seen[1:])  # repeat -> escalated


def test_coverage_unmet_stops_after_max_rounds(tmp_path: Path, monkeypatch) -> None:
    _seed_delayed_revise(tmp_path, monkeypatch)
    _, feedback_seen = _run_coverage_cycle(
        tmp_path, monkeypatch, unmet=["Hedge the cognitive claims"], max_revise_attempts=3,
        submit_cycle=lambda **_k: {"status": "submitted_to_researka", "submitted": 1, "published": 0})
    assert len(feedback_seen) == 3                                    # bounded: stops after max_revise_attempts


def test_retracted_source_blocks_submit(tmp_path: Path, monkeypatch) -> None:
    # A paper citing a retracted source must never reach Researka.
    _seed_delayed_revise(tmp_path, monkeypatch)
    monkeypatch.setattr(cycle, "_retracted_cited_sources", lambda out_dir: ["10.2/retracted"])
    submitted: list[int] = []

    def fake_submit(**_k: Any) -> dict[str, Any]:
        submitted.append(1)
        return {"status": "submitted_to_researka", "submitted": 1, "published": 0}

    ledger, _ = _run_coverage_cycle(tmp_path, monkeypatch, unmet=[], submit_cycle=fake_submit)
    assert submitted == []                                            # retraction gate blocked submit
    assert ledger["attempts"][0]["gate_status"] == "retracted_source_cited"
    assert ledger["attempts"][0]["retracted_cited_sources"] == ["10.2/retracted"]
    handled = json.loads((tmp_path / "runs" / cycle.LEDGER_DIR / cycle.HANDLED_REVISIONS).read_text())
    assert handled["handled"][0]["status"] == "retracted_source_cited"  # terminal revise: don't rerender next slot


def test_numeric_effect_mismatch_blocks_submit(tmp_path: Path, monkeypatch) -> None:
    _seed_delayed_revise(tmp_path, monkeypatch)
    monkeypatch.setattr(cycle, "_numeric_effect_direction_issues", lambda out_dir: [
        "non-significant p-value described as significant: LF HRV decreased significantly (p = 0.08)."
    ])
    submitted: list[int] = []

    def fake_submit(**_k: Any) -> dict[str, Any]:
        submitted.append(1)
        return {"status": "submitted_to_researka", "submitted": 1, "published": 0}

    ledger, _ = _run_coverage_cycle(tmp_path, monkeypatch, unmet=[], submit_cycle=fake_submit)
    assert submitted == []
    assert ledger["attempts"][0]["gate_status"] == "numeric_effect_mismatch"
    assert ledger["attempts"][0]["numeric_effect_direction_issues"] == [
        "non-significant p-value described as significant: LF HRV decreased significantly (p = 0.08)."
    ]


def test_abstract_overclaim_blocks_submit(tmp_path: Path, monkeypatch) -> None:
    # An abstract whose claims the evidence does not support must not be submitted.
    _seed_delayed_revise(tmp_path, monkeypatch)
    monkeypatch.setattr(cycle, "_abstract_overclaims", lambda out_dir: ["EGCG reverses aging"])
    submitted: list[int] = []

    def fake_submit(**_k: Any) -> dict[str, Any]:
        submitted.append(1)
        return {"status": "submitted_to_researka", "submitted": 1, "published": 0}

    ledger, _ = _run_coverage_cycle(tmp_path, monkeypatch, unmet=[], submit_cycle=fake_submit)
    assert submitted == []                                            # claim-support gate blocked submit
    assert ledger["attempts"][0]["gate_status"] == "abstract_overclaim"
    assert ledger["attempts"][0]["abstract_overclaims"] == ["EGCG reverses aging"]


def test_submission_ready_final_status_makes_duplicate_overclaim_advisory(tmp_path: Path, monkeypatch) -> None:
    _seed_delayed_revise(tmp_path, monkeypatch)
    monkeypatch.setattr(cycle, "_abstract_overclaims", lambda out_dir: ["profile summary overclaim"])
    monkeypatch.setattr(cycle, "_unmet_revision_asks", lambda out_dir, fb: [])

    def fake_synthesis(
        topic: str,
        out_dir: Path,
        *,
        dry_run: bool,
        timeout: int | None = None,
        revision_feedback: str | None = None,
        review_type_override: str | None = None,
    ) -> int:
        out_dir.mkdir(parents=True)
        (out_dir / "full_paper.md").write_text(
            "# Research Synthesis: Aspirin Geroprotection — full paper\n\n## Abstract\n\nA.",
            encoding="utf-8",
        )
        _write_json(out_dir / "final_status.json", {"submission_ready": True, "maturity_level": 5})
        return 0

    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)
    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-05-28",
        run_synthesis=True,
        submit=True,
        remote_loader=lambda: (set(), None),
        revision_loader=_aspirin_revise_loader,
        submit_cycle=lambda **_k: {"status": "submitted_to_researka", "submitted": 1, "published": 0},
    )

    assert ledger["attempts"][0]["gate_status"] == "submitted_to_researka"
    assert ledger["attempts"][0]["abstract_overclaim_advisory"] is True
    assert ledger["attempts"][0]["abstract_overclaim_advisory_claims"] == ["profile summary overclaim"]


def test_abstract_overclaim_repair_handles_paraphrased_judge_claim(tmp_path: Path) -> None:
    out_dir = tmp_path / "run"
    out_dir.mkdir()
    paper = (
        "# Research Synthesis: Aspirin Geroprotection — full paper\n\n"
        "## Abstract\n\n"
        "Positive signals demonstrated in preclinical models justify further targeted testing.\n\n"
        "## Methods\n\nBody."
    )
    (out_dir / "full_paper.md").write_text(paper, encoding="utf-8")

    assert cycle._repair_abstract_overclaim_phrasing(out_dir, ["judge paraphrased this overclaim"])
    body = (out_dir / "full_paper.md").read_text(encoding="utf-8")
    assert "context-specific signals suggested by preclinical models can motivate further targeted testing" in body


def test_abstract_overclaim_repair_rechecks_before_submit(tmp_path: Path, monkeypatch) -> None:
    _seed_delayed_revise(tmp_path, monkeypatch)
    calls = iter([[
        "mechanistic plausibility—demonstrated in preclinical frailty attenuation",
        "positive cardioprotection signals",
    ], []])
    monkeypatch.setattr(cycle, "_abstract_overclaims", lambda out_dir: next(calls))
    submitted: list[int] = []
    paper = (
        "# Research Synthesis: Aspirin Geroprotection — full paper\n\n"
        "## Abstract\n\n"
        "The synthesis finds mechanistic plausibility—demonstrated in preclinical frailty attenuation.\n\n"
        "It also reports positive cardioprotection signals alongside null functional endpoints.\n\n"
        "## Methods\n\nBody."
    )

    def fake_submit(**_k: Any) -> dict[str, Any]:
        submitted.append(1)
        return {"status": "submitted_to_researka", "submitted": 1, "published": 0}

    ledger, _ = _run_coverage_cycle(tmp_path, monkeypatch, unmet=[], submit_cycle=fake_submit, paper_md=paper)
    out_dir = tmp_path / "runs" / ledger["attempts"][0]["out_dir"]
    assert submitted == [1]
    assert ledger["attempts"][0]["abstract_overclaim_repaired"] is True
    body = (out_dir / "full_paper.md").read_text(encoding="utf-8")
    assert "suggested by preclinical frailty attenuation" in body
    assert "context-specific cardioprotection signals" in body


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
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_receipt_preflight", lambda topic, out_dir, **_k: {"passed": True})

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
    _write_json(tmp_path / "runs" / cycle.submit_bridge.LEDGER_DIR / "_submitted_fingerprints.json", [{
        "run": source_run.name,
        "topic": "aspirin_geroprotection",
        "fingerprint": cycle.submit_bridge._sha256(paper),
    }])
    _write_json(ledger_dir / cycle.HANDLED_REVISIONS, {"handled": [
        {"key": f"review-art-{i}", "title": "Research Synthesis: Aspirin Geroprotection — full paper"}
        for i in range(cycle.MAX_REVISE_ROUNDS)
    ]})

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


def test_handled_revision_ids_round_cap_resets_for_newer_review(tmp_path: Path) -> None:
    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    title = "Research Synthesis: Brain Age MRI — full paper"
    marker = cycle.submit_bridge._title_marker(title)
    old_rows = [
        {
            "key": marker,
            "title": title,
            "status": "revision_coverage_unmet",
            "handled_at": f"2026-06-01T0{i}:00:00+00:00",
        }
        for i in range(cycle.MAX_REVISE_ROUNDS)
    ]
    _write_json(ledger_dir / cycle.HANDLED_REVISIONS, {"handled": old_rows})

    active = [{"title": title, "reviewedAt": "2026-06-01T10:00:00+00:00"}]

    assert marker not in cycle._handled_revision_ids(ledger_dir, active)


def test_handled_revision_ids_round_cap_still_applies_within_active_review(tmp_path: Path) -> None:
    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    title = "Research Synthesis: Brain Age MRI — full paper"
    marker = cycle.submit_bridge._title_marker(title)
    reviewed_at = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=15)
    handled_at = reviewed_at + dt.timedelta(minutes=5)
    current_rows = [
        {
            "key": marker,
            "title": title,
            "status": "revision_coverage_unmet",
            "handled_at": handled_at.isoformat(),
        }
        for i in range(cycle.MAX_REVISE_ROUNDS)
    ]
    _write_json(ledger_dir / cycle.HANDLED_REVISIONS, {"handled": current_rows})

    active = [{"title": title, "reviewedAt": reviewed_at.isoformat()}]

    assert marker in cycle._handled_revision_ids(ledger_dir, active)


def test_terminal_revision_row_before_newer_review_still_blocks(tmp_path: Path) -> None:
    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    title = "Research Synthesis: Brain Age MRI — full paper"
    marker = cycle.submit_bridge._title_marker(title)
    _write_json(ledger_dir / cycle.HANDLED_REVISIONS, {"handled": [{
        "key": marker,
        "title": title,
        "status": "terminal_source_precision_repair_incomplete",
        "handled_at": "2026-06-01T09:00:00+00:00",
    }]})

    active = [{"title": title, "reviewedAt": "2026-06-01T10:00:00+00:00"}]

    assert marker in cycle._handled_revision_ids(ledger_dir, active)


def test_terminal_revision_row_after_active_review_still_blocks(tmp_path: Path) -> None:
    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    title = "Research Synthesis: Brain Age MRI — full paper"
    marker = cycle.submit_bridge._title_marker(title)
    _write_json(ledger_dir / cycle.HANDLED_REVISIONS, {"handled": [{
        "key": marker,
        "title": title,
        "status": "terminal_source_precision_repair_incomplete",
        "handled_at": "2026-06-01T11:00:00+00:00",
    }]})

    active = [{"title": title, "reviewedAt": "2026-06-01T10:00:00+00:00"}]

    assert marker in cycle._handled_revision_ids(ledger_dir, active)


def test_terminal_source_precision_handled_row_bypasses_round_cap(tmp_path: Path) -> None:
    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    marker = cycle.submit_bridge._title_marker("Research Synthesis: Digital Frailty Index — full paper")
    _write_json(ledger_dir / cycle.HANDLED_REVISIONS, {"handled": [{
        "key": marker,
        "title": "Research Synthesis: Digital Frailty Index — full paper",
        "status": "terminal_source_precision_repair_incomplete",
    }]})

    assert marker in cycle._handled_revision_ids(ledger_dir)


def test_receipt_preflight_handled_rows_obey_round_cap(tmp_path: Path) -> None:
    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    marker = cycle.submit_bridge._title_marker("Research Synthesis: HRV Autonomic Aging — full paper")
    row = {
        "key": marker,
        "title": "Research Synthesis: HRV Autonomic Aging — full paper",
        "status": "receipt_preflight_insufficient",
    }

    _write_json(ledger_dir / cycle.HANDLED_REVISIONS, {"handled": [row] * (cycle.MAX_REVISE_ROUNDS - 1)})
    assert marker not in cycle._handled_revision_ids(ledger_dir)
    _write_json(ledger_dir / cycle.HANDLED_REVISIONS, {"handled": [row] * cycle.MAX_REVISE_ROUNDS})
    assert marker in cycle._handled_revision_ids(ledger_dir)


def test_date_only_reviewed_at_counts_same_cycle_day_revise_attempts(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RESEARCH_AGENT_CYCLE_TIMEZONE", "Asia/Dubai")
    runs = tmp_path / "runs"
    ledger_dir = runs / cycle.LEDGER_DIR
    ledger_dir.mkdir(parents=True)
    sasp_title = "Adjacent Evidence Brief: SASP secretome — full paper"
    telomere_title = "Research Synthesis: Telomere Cancer Effects — full paper"
    sasp_run = _prior_run(tmp_path, "sasp_secretome", receipts=9, tensions=0, primary=0, level=5)
    telomere_run = _prior_run(tmp_path, "telomere_cancer_effects", receipts=20, tensions=5, primary=1, level=5)
    (sasp_run / "full_paper.md").write_text(f"# {sasp_title}\n", encoding="utf-8")
    (telomere_run / "full_paper.md").write_text(f"# {telomere_title}\n", encoding="utf-8")
    _write_json(runs / cycle.submit_bridge.LEDGER_DIR / "_submitted_fingerprints.json", [
        {
            "run": sasp_run.name,
            "topic": "sasp_secretome",
            "fingerprint": cycle.submit_bridge._sha256(sasp_run / "full_paper.md"),
        },
        {
            "run": telomere_run.name,
            "topic": "telomere_cancer_effects",
            "fingerprint": cycle.submit_bridge._sha256(telomere_run / "full_paper.md"),
        },
    ])
    sasp_marker = cycle.submit_bridge._title_marker(sasp_title)
    _write_json(ledger_dir / cycle.HANDLED_REVISIONS, {"handled": [
        {
            "key": sasp_marker,
            "title": sasp_title,
            "status": "receipt_preflight_insufficient",
            "handled_at": "2026-06-26T20:19:51+00:00",
        },
        {
            "key": sasp_marker,
            "title": sasp_title,
            "status": "receipt_preflight_insufficient",
            "handled_at": "2026-06-27T00:19:51+00:00",
        },
        {
            "key": sasp_marker,
            "title": sasp_title,
            "status": "receipt_preflight_insufficient",
            "handled_at": "2026-06-27T04:19:51+00:00",
        },
    ]})
    requests = [
        {
            "artifactId": "sasp-review",
            "title": sasp_title,
            "topic": "sasp_secretome",
            "feedback": "Revise the source bundle and directness wording.",
            "reviewedAt": "2026-06-27",
        },
        {
            "artifactId": "telomere-review",
            "title": telomere_title,
            "topic": "telomere_cancer_effects",
            "feedback": "Revise the mortality and survival attribution.",
            "reviewedAt": "2026-06-26",
        },
    ]

    assert sasp_marker in cycle._handled_revision_ids(ledger_dir, requests)
    pending, error = cycle._pending_remote_revision(
        runs,
        ledger_dir,
        loader=lambda: (requests, None),
    )

    assert error is None
    assert pending is not None
    assert pending["topic"] == "telomere_cancer_effects"


def test_submitted_revision_waits_for_newer_review_before_reprocessing(tmp_path: Path) -> None:
    source_run = _prior_run(tmp_path, "aspirin_geroprotection", receipts=57, tensions=274, level=5)
    paper = source_run / "full_paper.md"
    title = "Research Synthesis: Aspirin Geroprotection — full paper"
    paper.write_text(f"# {title}\n", encoding="utf-8")
    ledger_dir = tmp_path / "runs" / cycle.LEDGER_DIR
    _write_json(tmp_path / "runs" / cycle.submit_bridge.LEDGER_DIR / "_submitted_fingerprints.json", [{
        "run": source_run.name,
        "topic": "aspirin_geroprotection",
        "fingerprint": cycle.submit_bridge._sha256(paper),
    }])
    _write_json(ledger_dir / cycle.HANDLED_REVISIONS, {"handled": [{
        "key": cycle.submit_bridge._title_marker(title),
        "title": title,
        "status": "submitted_to_researka",
        "handled_at": "2026-05-29T13:00:00+00:00",
    }]})

    old_review = {"artifactId": "r1", "title": title, "feedback": "Revise.", "reviewedAt": "2026-05-29T12:00:00+00:00"}
    pending, error = cycle._pending_remote_revision(tmp_path / "runs", ledger_dir, loader=lambda: ([old_review], None))
    assert error is None
    assert pending is None

    newer_review = {**old_review, "artifactId": "r2", "reviewedAt": "2026-05-29T14:00:00+00:00"}
    pending, error = cycle._pending_remote_revision(tmp_path / "runs", ledger_dir, loader=lambda: ([newer_review], None))
    assert error is None
    assert pending and pending["artifactId"] == "r2"


def test_submitted_revision_direct_decision_reopens_same_submission(tmp_path: Path) -> None:
    source_run = _prior_run(tmp_path, "vascular_age", receipts=57, tensions=274, level=5)
    paper = source_run / "full_paper.md"
    title = "Hypothesis-Generating Brief: Vascular age — full paper"
    paper.write_text(f"# {title}\n", encoding="utf-8")
    ledger_dir = tmp_path / "runs" / cycle.LEDGER_DIR
    submission_id = "sub-vascular-2"
    _write_json(tmp_path / "runs" / cycle.submit_bridge.LEDGER_DIR / "_submitted_fingerprints.json", [{
        "run": source_run.name,
        "topic": "vascular_age",
        "fingerprint": cycle.submit_bridge._sha256(paper),
        "submission_id": submission_id,
    }])
    _write_json(ledger_dir / cycle.HANDLED_REVISIONS, {"handled": [{
        "key": cycle.submit_bridge._title_marker(title),
        "title": title,
        "status": "submitted_to_researka",
        "handled_at": "2026-06-26T18:10:42+00:00",
    }]})
    request = {
        "artifactId": "decision-2",
        "submissionId": submission_id,
        "title": title,
        "topic": "vascular_age",
        "feedback": "Populate Key Findings with source-level results.",
        "reviewedAt": "2026-06-26T18:09:45+00:00",
    }

    assert cycle.submit_bridge._title_marker(title) not in cycle._handled_revision_ids(ledger_dir, [request])
    pending, error = cycle._pending_remote_revision(
        tmp_path / "runs",
        ledger_dir,
        loader=lambda: ([request], None),
    )

    assert error is None
    assert pending is not None
    assert pending["submissionId"] == submission_id
    assert pending["topic"] == "vascular_age"
    assert pending["source_run"] == source_run.name


def test_pending_remote_revision_matches_topic_when_paper_title_is_malformed(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    source_run = runs / "synthesis-sirtuin_intervention_aging_effects-v06-DAILY-2026-06-21T20-04-33Z"
    source_run.mkdir(parents=True)
    paper = source_run / "full_paper.md"
    paper.write_text(
        "Additional corpus sources included animal/preclinical evidence.\n\n## Abstract\n",
        encoding="utf-8",
    )
    _write_json(runs / cycle.submit_bridge.LEDGER_DIR / "_submitted_fingerprints.json", [{
        "run": source_run.name,
        "topic": "sirtuin_intervention_aging_effects",
        "fingerprint": cycle.submit_bridge._sha256(paper),
    }])

    pending, error = cycle._pending_remote_revision(
        runs,
        runs / cycle.LEDGER_DIR,
        loader=lambda: ([{
            "artifactId": "sirtuin-review",
            "title": "Research Synthesis: Sirtuin Intervention Aging Effects",
            "topic": "sirtuin_intervention_aging_effects",
            "feedback": "Revise directional coding.",
            "reviewedAt": "2026-06-22T00:11:11+04:00",
        }], None),
    )

    assert error is None
    assert pending and pending["artifactId"] == "sirtuin-review"
    assert pending["source_run"] == source_run.name


def test_pending_remote_revision_reopens_repairable_terminal_surface_repeat(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runs = tmp_path / "runs"
    ledger_dir = runs / cycle.LEDGER_DIR
    ledger_dir.mkdir(parents=True)
    title = "Hypothesis-Generating Brief: ABT-263 — full paper"
    source_run = _seed_submitted_run(runs, "senolytics", f"# {title}")
    marker = cycle.submit_bridge._title_marker(title)
    _write_json(ledger_dir / cycle.HANDLED_REVISIONS, {"handled": [{
        "key": marker,
        "title": title,
        "status": "terminal_surface_repeat",
        "handled_at": "2026-06-25T00:05:28+00:00",
    }]})
    monkeypatch.setattr(cycle, "_surface_passes_current_finalizer", lambda run: run == source_run)
    request = {
        "artifactId": "abt263-review",
        "title": title,
        "topic": "senolytics",
        "feedback": "Clarify direct ABT-263 studies versus adjacent senolytics.",
        "reviewedAt": "2026-06-24T23:00:00+00:00",
    }

    pending, error = cycle._pending_remote_revision(
        runs,
        ledger_dir,
        loader=lambda: ([request], None),
    )

    assert error is None
    assert pending is not None
    assert pending["artifactId"] == "abt263-review"
    assert pending["source_run"] == source_run.name


def test_pending_remote_revision_reopens_false_domain_scope_terminal(
    tmp_path: Path,
) -> None:
    runs = tmp_path / "runs"
    ledger_dir = runs / cycle.LEDGER_DIR
    ledger_dir.mkdir(parents=True)
    title = "Research Synthesis: Metabolism Biomarker Effects"
    source_run = _seed_submitted_run(runs, "metabolism_biomarker_effects", f"# {title}")
    marker = cycle.submit_bridge._title_marker(title)
    _write_json(ledger_dir / cycle.HANDLED_REVISIONS, {"handled": [{
        "key": marker,
        "title": title,
        "status": "terminal_domain_scope_mismatch",
        "handled_at": "2026-06-25T00:38:21+00:00",
    }]})
    request = {
        "artifactId": "metabolism-review",
        "title": title,
        "topic": "metabolism_biomarker_effects",
        "feedback": (
            "Reconcile the abstract's direct / adjacent framing with the Findings Map. "
            "Expand the 26 cross-study disagreements including the null longevity class. "
            "Either remove review sources from direct-evidence counting, or relabel them."
        ),
        "reviewedAt": "2026-06-25T00:37:00+00:00",
    }

    pending, error = cycle._pending_remote_revision(
        runs,
        ledger_dir,
        loader=lambda: ([request], None),
    )

    assert error is None
    assert pending is not None
    assert pending["artifactId"] == "metabolism-review"
    assert pending["source_run"] == source_run.name


def test_pending_remote_revision_reopens_stale_revision_coverage_unmet(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runs = tmp_path / "runs"
    ledger_dir = runs / cycle.LEDGER_DIR
    ledger_dir.mkdir(parents=True)
    title = "Hypothesis-Generating Brief: Metabolism Biomarker Effects — full paper"
    source_run = _seed_submitted_run(runs, "metabolism_biomarker_effects", f"# {title}")
    marker = cycle.submit_bridge._title_marker(title)
    _write_json(ledger_dir / cycle.HANDLED_REVISIONS, {"handled": [
        {
            "key": marker,
            "title": title,
            "status": "revision_coverage_unmet",
            "handled_at": "2026-06-25T00:50:36+00:00",
        },
        {
            "key": marker,
            "title": title,
            "status": "revision_coverage_unmet",
            "handled_at": "2026-06-25T00:52:47+00:00",
        },
        {
            "key": marker,
            "title": title,
            "status": "revision_coverage_unmet",
            "handled_at": "2026-06-25T00:54:47+00:00",
        },
    ]})
    monkeypatch.setattr(
        cycle,
        "_revision_coverage_passes_current_finalizer",
        lambda run, feedback: run == source_run and "Findings Map" in feedback,
    )
    request = {
        "artifactId": "metabolism-review",
        "title": title,
        "topic": "metabolism_biomarker_effects",
        "feedback": "Reconstruct the Findings Map.",
        "reviewedAt": "2026-06-25T00:49:00+00:00",
    }

    pending, error = cycle._pending_remote_revision(
        runs,
        ledger_dir,
        loader=lambda: ([request], None),
    )

    assert error is None
    assert pending is not None
    assert pending["artifactId"] == "metabolism-review"
    assert pending["source_run"] == source_run.name


def test_pending_remote_revision_reopens_retry_budget_terminal_when_current_code_covers_asks(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runs = tmp_path / "runs"
    ledger_dir = runs / cycle.LEDGER_DIR
    ledger_dir.mkdir(parents=True)
    title = "Hypothesis-Generating Brief: Cardiovascular Subgroups — full paper"
    source_run = _seed_submitted_run(runs, "cardiovascular_subgroups", f"# {title}")
    marker = cycle.submit_bridge._title_marker(title)
    _write_json(ledger_dir / cycle.HANDLED_REVISIONS, {"handled": [{
        "key": marker,
        "title": title,
        "status": "terminal_revise_retry_budget_insufficient",
        "handled_at": "2026-06-26T01:36:54+00:00",
    }, {
        "key": marker,
        "title": title,
        "status": "synthesis_timeout",
        "handled_at": "2026-06-26T03:41:46+00:00",
    }]})
    monkeypatch.setattr(
        cycle,
        "_revision_coverage_passes_current_finalizer",
        lambda run, feedback: run == source_run and "source attribution" in feedback,
    )
    request = {
        "artifactId": "cardio-review",
        "title": title,
        "topic": "cardiovascular_subgroups",
        "feedback": "Tighten source attribution.",
        "reviewedAt": "2026-06-26T00:49:00+00:00",
    }

    pending, error = cycle._pending_remote_revision(
        runs,
        ledger_dir,
        loader=lambda: ([request], None),
    )

    assert error is None
    assert pending is not None
    assert pending["artifactId"] == "cardio-review"
    assert pending["source_run"] == source_run.name


def test_fresh_lane_excludes_topic_with_pending_revise(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "hydrogen_water", target_journal=True)
    _topic(tmp_path, "telomere_biomarker_effects", target_journal=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    title = "Research Synthesis: Hydrogen Water — full paper"
    _seed_submitted_run(tmp_path / "runs", "hydrogen_water", f"# {title}")
    revision = {
        "artifactId": "rev-1",
        "title": title,
        "feedback": "Revise source specificity.",
        "reviewedAt": "2026-06-01T10:00:00+00:00",
    }
    monkeypatch.setattr(cycle, "_remote_revision_requests", lambda: ([revision], None))
    monkeypatch.setattr(cycle.submit_bridge, "_token", lambda: ("token", "TEST_TOKEN"))

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-06-01",
        mode="fresh",
        submit=True,
        remote_loader=lambda: (set(), None),
    )

    assert ledger["pending_revision_exclusions"] == {"checked": True, "topics": ["hydrogen_water"]}
    assert ledger["topic"] == "telomere_biomarker_effects"


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


def test_remote_revision_requests_are_newest_first(monkeypatch) -> None:
    old_title = "Adjacent Evidence Brief: Alpha-klotho — full paper"
    new_title = "Research Synthesis: Sirtuin Intervention Aging Effects"
    base = {"artifactType": "research_paper", "agentId": "agent-v3-full-paper", "decision": "revise"}
    _patch_reviews(monkeypatch, [
        {**base, "artifactId": "old", "title": old_title, "reviewedAt": "2026-06-21T22:19:58+04:00", "requiredRevisions": ["older"]},
        {**base, "artifactId": "new", "title": new_title, "reviewedAt": "2026-06-22T00:11:11+04:00", "requiredRevisions": ["newer"]},
    ])

    out, err = cycle._remote_revision_requests("http://reviews.test")

    assert err is None
    assert [row["artifactId"] for row in out] == ["new", "old"]


def test_pending_revision_skips_request_when_matching_run_is_published(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    ledger_dir = runs / cycle.LEDGER_DIR
    _seed_submitted_run(runs, "sirtuin_intervention_aging_effects", "# Hypothesis-Generating Brief: Sirtuin Intervention Aging Effects")
    request = {
        "artifactId": "revise-1",
        "title": "Research Synthesis: Sirtuin Intervention Aging Effects",
        "topic": "sirtuin_intervention_aging_effects",
        "feedback": "Add evidence examples.",
    }

    pending, err = cycle._pending_remote_revision(
        runs,
        ledger_dir,
        loader=lambda: ([request], None),
        published_loader=lambda: ({"sha256:x"}, None),
    )
    topics, topic_err = cycle._pending_remote_revision_topics(
        runs,
        ledger_dir,
        loader=lambda: ([request], None),
        published_loader=lambda: ({"sha256:x"}, None),
    )

    assert err is None
    assert pending is None
    assert topic_err is None
    assert topics == set()


def test_pending_revision_keeps_unpublished_matching_request(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    ledger_dir = runs / cycle.LEDGER_DIR
    _seed_submitted_run(runs, "sirtuin_intervention_aging_effects", "# Hypothesis-Generating Brief: Sirtuin Intervention Aging Effects")
    request = {
        "artifactId": "revise-1",
        "title": "Research Synthesis: Sirtuin Intervention Aging Effects",
        "topic": "sirtuin_intervention_aging_effects",
        "feedback": "Add evidence examples.",
    }

    pending, err = cycle._pending_remote_revision(
        runs,
        ledger_dir,
        loader=lambda: ([request], None),
        published_loader=lambda: (set(), None),
    )

    assert err is None
    assert pending is not None
    assert pending["source_run"] == "synthesis-sirtuin_intervention_aging_effects-v06-DAILY-2026-05-29T00-00-00Z"


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


def test_remote_revision_skips_revise_with_no_required_revisions(monkeypatch) -> None:
    # Researka can return decision=revise with zero requiredRevisions ("No
    # revisions are required"); routing it burns a ~15-min re-render for nothing.
    title = "Research Synthesis: Colchicine Inflammaging — full paper"
    base = {"artifactType": "research_paper", "agentId": "agent-v3-full-paper", "title": title}
    _patch_reviews(monkeypatch, [
        {**base, "decision": "revise", "reviewedAt": "2026-05-29T17:31:01+04:00",
         "requiredRevisions": [], "reviewSummary": "No revisions are required."},
    ])
    out, err = cycle._remote_revision_requests("http://reviews.test")
    assert err is None
    assert out == []  # no concrete required revisions -> no-op revise skipped


def _seed_submitted_run(runs: Path, topic: str, title_line: str) -> Path:
    run = runs / f"synthesis-{topic}-v06-DAILY-2026-05-29T00-00-00Z"
    run.mkdir(parents=True)
    (run / "full_paper.md").write_text(f"{title_line}\n\nbody\n", encoding="utf-8")
    _write_json(runs / cycle.submit_bridge.LEDGER_DIR / "_submitted_fingerprints.json",
                [{"run": run.name, "topic": topic, "fingerprint": "sha256:x"}])
    return run


def test_pending_revision_uses_submission_decision_when_reviews_feed_empty(tmp_path: Path, monkeypatch) -> None:
    runs = tmp_path / "runs"
    ledger_dir = runs / cycle.LEDGER_DIR
    run = _seed_submitted_run(runs, "senolytics", "# Hypothesis-Generating Brief: ABT-263 — full paper")
    _write_json(runs / cycle.submit_bridge.LEDGER_DIR / "_submitted_fingerprints.json", [{
        "run": run.name,
        "topic": "senolytics",
        "fingerprint": "sha256:x",
        "submission_id": "submission-1",
        "date": "2026-06-25",
    }])
    monkeypatch.setattr(cycle, "_latest_reviews_by_title", lambda _url=None: ({}, None))
    monkeypatch.setattr(cycle, "_fetch_submission_decision", lambda _submission_id: ({
        "decision": "revise",
        "decision_object_id": "decision-1",
        "required_revisions": ["Clarify direct ABT-263 evidence."],
        "review_summary": "Clarify direct ABT-263 evidence.",
        "publication": None,
    }, None))

    pending, err = cycle._pending_remote_revision(
        runs,
        ledger_dir,
        published_loader=lambda: (set(), None),
    )

    assert err is None
    assert pending is not None
    assert pending["submissionId"] == "submission-1"
    assert pending["topic"] == "senolytics"
    assert pending["source_run"] == run.name
    assert pending["feedback"] == "Clarify direct ABT-263 evidence."


def test_pending_revision_retries_source_manifest_terminal_after_source_repair_request(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runs = tmp_path / "runs"
    ledger_dir = runs / cycle.LEDGER_DIR
    title = "# Adjacent Evidence Brief: Cardiovascular Subgroups — full paper"
    run = _seed_submitted_run(runs, "cardiovascular_subgroups", title)
    _write_json(runs / cycle.submit_bridge.LEDGER_DIR / "_submitted_fingerprints.json", [{
        "run": run.name,
        "topic": "cardiovascular_subgroups",
        "fingerprint": "sha256:x",
        "submission_id": "submission-1",
        "date": "2026-06-25",
    }])
    _write_json(ledger_dir / cycle.HANDLED_REVISIONS, {"handled": [{
        "title": title.removeprefix("# "),
        "status": "terminal_revision_source_manifest_unavailable",
        "handled_at": "2026-06-25T17:55:00+00:00",
    }]})
    monkeypatch.setattr(cycle, "_latest_reviews_by_title", lambda _url=None: ({}, None))
    monkeypatch.setattr(cycle, "_fetch_submission_decision", lambda _submission_id: ({
        "decision": "revise",
        "decision_object_id": "decision-1",
        "required_revisions": ["Reset the source bundle to directly address cardiovascular subgroups."],
        "publication": None,
    }, None))

    pending, err = cycle._pending_remote_revision(
        runs,
        ledger_dir,
        published_loader=lambda: (set(), None),
    )

    assert err is None
    assert pending is not None
    assert pending["topic"] == "cardiovascular_subgroups"
    assert pending["source_run"] == run.name


def test_submission_decision_fallback_does_not_route_accepted_publication(tmp_path: Path, monkeypatch) -> None:
    runs = tmp_path / "runs"
    run = _seed_submitted_run(runs, "senolytics", "# Hypothesis-Generating Brief: ABT-263 — full paper")
    _write_json(runs / cycle.submit_bridge.LEDGER_DIR / "_submitted_fingerprints.json", [{
        "run": run.name,
        "topic": "senolytics",
        "fingerprint": "sha256:x",
        "submission_id": "submission-1",
        "date": "2026-06-25",
    }])
    monkeypatch.setattr(cycle, "_latest_reviews_by_title", lambda _url=None: ({}, None))
    monkeypatch.setattr(cycle, "_fetch_submission_decision", lambda _submission_id: ({
        "decision": "accept",
        "decision_object_id": "decision-1",
        "required_revisions": [],
        "publication": {"url": "https://researka.org/papers/accepted"},
    }, None))

    rows, err = cycle._remote_revision_requests(runs_root=runs)

    assert err is None
    assert rows == []


def test_terminal_topics_excludes_topic_with_latest_reject(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    _seed_submitted_run(runs, "foo_topic", "# Research Synthesis: Foo Topic")
    latest = {"k": {"decision": "reject", "title": "Research Synthesis: Foo Topic"}}
    out = cycle._terminal_topics(runs, loader=lambda: (latest, None))
    assert out == {"foo_topic"}  # reject is terminal-for-topic


def test_terminal_topics_ignores_topic_with_actionable_revise(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    _seed_submitted_run(runs, "foo_topic", "# Research Synthesis: Foo Topic")
    latest = {"k": {"decision": "revise", "title": "Research Synthesis: Foo Topic",
                    "requiredRevisions": ["Add a clinical-use caveat."]}}
    out = cycle._terminal_topics(runs, loader=lambda: (latest, None))
    assert out == set()  # actionable revise -> re-processed, not terminal


def test_terminal_topics_excludes_revise_with_no_actionable_revisions(tmp_path: Path) -> None:
    # Real EGCG production failure: Researka returns decision=revise with empty
    # requiredRevisions and "High overlap with publication ... differentiate to
    # resubmit". The writer cannot act on it, so re-synthesising just bounces —
    # the topic must be terminal-for-selection.
    runs = tmp_path / "runs"
    _seed_submitted_run(runs, "foo_topic", "# Research Synthesis: Foo Topic")
    latest = {"k": {"decision": "revise", "title": "Research Synthesis: Foo Topic",
                    "requiredRevisions": [],
                    "reviewSummary": "High overlap with publication 873ff54a. Differentiate to resubmit."}}
    out = cycle._terminal_topics(runs, loader=lambda: (latest, None))
    assert out == {"foo_topic"}  # no actionable revisions -> terminal-for-topic


def test_terminal_topics_excludes_calibration_only_direct_evidence_revise(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    _seed_submitted_run(runs, "foo_topic", "# Research Synthesis: Foo Topic")
    latest = {"k": {
        "decision": "revise",
        "title": "Research Synthesis: Foo Topic",
        "requiredRevisions": [
            "Per calibration rules, the explicit absence of direct clinical evidence requires a revise status because broad population-level proof is missing.",
        ],
    }}
    out = cycle._terminal_topics(runs, loader=lambda: (latest, None))
    assert out == {"foo_topic"}


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


def test_cycle_does_not_let_stale_thin_manifest_block_healthy_corpus(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "aaa_thin_topic", target_journal=True)
    _topic(tmp_path, "zzz_solid_topic", target_journal=True)
    _prior_run(tmp_path, "aaa_thin_topic", receipts=6, tensions=0, primary=0)
    # Both topics already attempted, so the new untried-first selection rule is
    # uniform and the existing alphabetical tiebreak (aaa < zzz) still picks the
    # thin-manifest topic — this test asserts that topic is NOT blocked.
    _prior_run(tmp_path, "zzz_solid_topic", receipts=40, tensions=5, primary=3)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_receipt_preflight", lambda topic, out_dir, **_k: {"passed": True})
    topics: list[str] = []

    def fake_synthesis(
        topic: str,
        out_dir: Path,
        *,
        dry_run: bool,
        timeout: int | None = None,
        revision_feedback: str | None = None,
        review_type_override: str | None = None,
    ) -> int:
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

    assert topics == ["aaa_thin_topic"]
    assert ledger["status"] == "submitted_to_researka"


def test_cycle_preflights_overbroad_prior_corpus_before_synthesis(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "aaa_mega_topic", target_journal=True)
    _topic(tmp_path, "zzz_solid_topic", target_journal=True)
    _prior_run(tmp_path, "aaa_mega_topic", receipts=600, tensions=60_000, primary=10)
    # Both topics already attempted, so untried-first is uniform and the
    # alphabetical tiebreak selects the overbroad aaa_mega_topic first — it gets
    # preflight-rejected ("split topic"), and the cycle falls back to the
    # healthy (non-overbroad) zzz_solid_topic.
    _prior_run(tmp_path, "zzz_solid_topic", receipts=40, tensions=5, primary=3)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_current_low_source_precision_topics", lambda topics: set())
    monkeypatch.setattr(cycle, "_quant_claim_source_precision", lambda topic, **_k: (True, "source_topic_precision_ok:40/40", []))
    topics: list[str] = []

    def fake_synthesis(
        topic: str,
        out_dir: Path,
        *,
        dry_run: bool,
        timeout: int | None = None,
        revision_feedback: str | None = None,
        review_type_override: str | None = None,
    ) -> int:
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
    assert "target_journal_not_declared" in preflight["reasons"]
    assert any("recent_failed_attempts=1" in reason for reason in preflight["reasons"])


def test_preflight_blocks_latest_run_without_manifest(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "cancer_biomarker_subgroups", target_journal=True)
    run = tmp_path / "runs" / "synthesis-cancer_biomarker_subgroups-v06-DAILY-2026-06-01T16-04-43Z"
    run.mkdir(parents=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")

    preflight = cycle._preflight(
        "cancer_biomarker_subgroups",
        tmp_path / "runs",
        tmp_path / "runs" / cycle.LEDGER_DIR,
        current_quant_claims=39,
    )

    assert preflight["passed"] is False
    assert preflight["latest_run"] == run.name
    assert preflight["reasons"] == ["latest_run_missing_manifest"]


def test_preflight_uses_revise_source_run_over_newer_manifestless_run(tmp_path: Path, monkeypatch) -> None:
    topic = "cardiovascular_subgroups"
    _topic(tmp_path, topic, target_journal=True)
    source = _prior_run(tmp_path, topic, receipts=37, tensions=113, primary=1, level=5)
    (tmp_path / "runs" / f"synthesis-{topic}-v06-DAILY-2026-06-26T03-32-00Z-R2").mkdir(parents=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")

    preflight = cycle._preflight(
        topic,
        tmp_path / "runs",
        tmp_path / "runs" / cycle.LEDGER_DIR,
        current_quant_claims=39,
        source_run=source,
    )

    assert preflight["passed"] is True
    assert preflight["latest_run"] == source.name
    assert "latest_run_missing_manifest" not in preflight["reasons"]


def test_preflight_blocks_revise_source_run_without_manifest(tmp_path: Path, monkeypatch) -> None:
    topic = "therapeutic_plasma_exchange"
    _topic(tmp_path, topic, target_journal=True)
    source = _prior_run(tmp_path, topic, receipts=37, tensions=113, primary=1, level=5)
    (source / "manifest.json").unlink()
    (tmp_path / "runs" / f"synthesis-{topic}-v06-DAILY-2026-06-24T16-15-05Z").mkdir(parents=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")

    preflight = cycle._preflight(
        topic,
        tmp_path / "runs",
        tmp_path / "runs" / cycle.LEDGER_DIR,
        current_quant_claims=39,
        source_run=source,
    )

    assert preflight["passed"] is False
    assert preflight["latest_run"] == source.name
    assert preflight["reasons"] == ["latest_run_missing_manifest"]


def test_preflight_allows_latest_run_with_manifest(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "metformin_biomarker_subgroups", target_journal=True)
    run = _prior_run(tmp_path, "metformin_biomarker_subgroups", receipts=40, tensions=10, primary=2)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")

    preflight = cycle._preflight(
        "metformin_biomarker_subgroups",
        tmp_path / "runs",
        tmp_path / "runs" / cycle.LEDGER_DIR,
        current_quant_claims=40,
    )

    assert preflight["passed"] is True
    assert preflight["latest_run"] == run.name
    assert preflight["has_manifest"] is True
    assert preflight["reasons"] == []


def test_cycle_records_blocker_histogram_for_current_gate_failure(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "rapamycin", target_journal=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_receipt_preflight", lambda topic, out_dir, **_k: {"passed": True})

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
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_receipt_preflight", lambda topic, out_dir, **_k: {"passed": True})
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
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_receipt_preflight", lambda topic, out_dir, **_k: {"passed": True})
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


def test_internal_surface_repair_uses_declared_review_type(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import agent.journal_finalizer as finalizer
    import agent.journal_surface_gate as surface_gate

    source = tmp_path / "source"
    out = tmp_path / "out"
    source.mkdir()
    _write_json(source / "manifest.json", {"review_type": "thin_corpus_brief"})
    (source / "full_paper.md").write_text("bad public artifact\n", encoding="utf-8")

    def fake_finalize(out_dir: Path) -> None:
        (out_dir / "full_paper.md").write_text("fixed public prose\n", encoding="utf-8")

    seen_review_types: list[str | None] = []

    def fake_surface(_paper: str, **kwargs: Any) -> Any:
        seen_review_types.append(kwargs.get("declared_review_type"))
        return SimpleNamespace(passed=True, issues=())

    monkeypatch.setattr(finalizer, "finalize_run", fake_finalize)
    monkeypatch.setattr(surface_gate, "evaluate_journal_surface", fake_surface)

    ok, error = cycle._repair_existing_run(source, out, repair_reason="journal_surface_not_passed")

    assert ok is True
    assert error == ""
    assert seen_review_types == ["thin_corpus_brief"]


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
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_receipt_preflight", lambda topic, out_dir, **_k: {"passed": True})
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
    monkeypatch.setattr(cycle, "_current_low_source_precision_topics", lambda topics: set())
    monkeypatch.setattr(cycle, "_quant_claim_source_precision", lambda topic, **_k: (
        True, "source_topic_precision_ok:40/40", [],
    ))
    monkeypatch.setattr(cycle, "_receipt_preflight", lambda *_args, **_kwargs: {"passed": True})
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


# --- A-Z throughput lanes: --mode fresh|revise|mixed -------------------------


def test_fresh_mode_ignores_revise_backlog(tmp_path: Path, monkeypatch) -> None:
    """Fresh lane never polls the revise backlog — it always attempts new output,
    so a revision backlog can no longer starve fresh papers (the May-30 regression)."""
    _topic(tmp_path, "creatine", target_journal=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_receipt_preflight", lambda *_args, **_kwargs: {"passed": True})
    runs: list[str] = []

    def fake_synthesis(topic: str, out_dir: Path, *, dry_run: bool, timeout: int | None = None, revision_feedback: str | None = None) -> int:
        runs.append(topic)
        out_dir.mkdir(parents=True)
        return 0

    def boom_revision() -> Any:
        raise AssertionError("fresh lane must not poll the revise backlog")

    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-05-24",
        run_synthesis=True,
        submit=True,
        mode="fresh",
        remote_loader=lambda: (set(), None),
        revision_loader=boom_revision,
        submit_cycle=lambda **_kwargs: {"status": "submitted_to_researka", "submitted": 1, "published": 0},
    )

    assert ledger["mode"] == "fresh"
    assert "remote_revisions" not in ledger  # revise backlog never polled
    assert runs == ["creatine"]
    assert ledger["status"] == "submitted_to_researka"


def test_fresh_mode_excludes_terminal_review_topics(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "aaa_terminal", target_journal=True)
    _topic(tmp_path, "zzz_fresh", target_journal=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_terminal_topics", lambda _runs_root: {"aaa_terminal"})
    runs: list[str] = []

    def fake_synthesis(topic: str, out_dir: Path, *, dry_run: bool, timeout: int | None = None, revision_feedback: str | None = None) -> int:
        runs.append(topic)
        out_dir.mkdir(parents=True)
        return 0

    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)
    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-05-24",
        run_synthesis=True,
        submit=True,
        mode="fresh",
        remote_loader=lambda: (set(), None),
        submit_cycle=lambda **_kwargs: {"status": "submitted_to_researka", "submitted": 1, "published": 0},
    )

    assert ledger["terminal_excluded_topics"] == ["aaa_terminal"]
    assert runs == ["zzz_fresh"]


def test_revise_mode_with_no_pending_revise_does_nothing(tmp_path: Path, monkeypatch) -> None:
    """Revise lane with an empty backlog exits cleanly without writing a fresh paper."""
    _topic(tmp_path, "creatine")
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_run_synthesis", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("revise lane must not synthesise a fresh paper")))

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-05-24",
        run_synthesis=True,
        submit=True,
        mode="revise",
        remote_loader=lambda: (set(), None),
        revision_loader=lambda: ([], None),
        submit_cycle=lambda **_kwargs: {"status": "submitted_to_researka", "submitted": 1, "published": 0},
    )

    assert ledger["mode"] == "revise"
    assert ledger["status"] == "no_revise_pending"
    assert ledger["attempts"] == []


def test_revise_mode_never_rotates_to_fresh_topic(tmp_path: Path, monkeypatch) -> None:
    """Revise lane processes only the pending revise — it must not fall through to a
    fresh topic even when one is available (lane isolation)."""
    _topic(tmp_path, "colchicine_inflammaging", target_journal=True)
    _topic(tmp_path, "creatine")  # a fresh topic is available to rotate to
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
    monkeypatch.setattr(cycle, "_run_synthesis", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("terminal sparse revise should not synthesise")))
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
        mode="revise",
        remote_loader=lambda: (set(), None),
        revision_loader=lambda: ([request], None),
        submit_cycle=lambda **_kwargs: {"status": "submitted_to_researka", "submitted": 1, "published": 0},
    )

    assert ledger["mode"] == "revise"
    # only the revise topic is ever touched — never the available fresh topic
    assert [a["topic"] for a in ledger["attempts"]] == ["colchicine_inflammaging"]
    assert "creatine" not in {a["topic"] for a in ledger["attempts"]}


def test_lock_distinct_lane_names_are_independent(tmp_path: Path) -> None:
    """Fresh and revise lanes use distinct lock files, so they never block each
    other — a revise run no longer waits on an in-flight fresh synthesis."""
    d = tmp_path / "ledger"
    with cycle._lock(d, ".lock.fresh") as fresh, cycle._lock(d, ".lock.revise") as revise:
        assert fresh is True
        assert revise is True
    # same lane held twice is still exclusive (no concurrent duplicate run)
    with cycle._lock(d, ".lock.fresh") as first:
        assert first is True
        with cycle._lock(d, ".lock.fresh") as second:
            assert second is False


def test_submit_lock_blocks_until_free(tmp_path: Path) -> None:
    """The shared submit lock is blocking: a second holder is refused while the
    first holds it, keeping submission single-threaded across lanes."""
    d = tmp_path / "ledger"
    with cycle._lock(d, ".submit.lock", block=True) as held:
        assert held is True
        with cycle._lock(d, ".submit.lock") as contended:  # non-blocking probe
            assert contended is False
    with cycle._lock(d, ".submit.lock", block=True) as reacquired:
        assert reacquired is True


def test_surface_repeat_topics_skips_same_deterministic_gate_twice(tmp_path: Path) -> None:
    """A topic that fails the SAME deterministic gate twice in-window is skipped;
    different gates, single failures, transient statuses, and stale windows are not.
    Source is the CUMULATIVE histogram (the daily ledger is rewritten each run)."""
    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    now = dt.datetime.now(dt.UTC)
    recent, older = now.isoformat(), (now - dt.timedelta(minutes=5)).isoformat()
    stale = (now - dt.timedelta(hours=cycle.RECENT_FAILURE_COOLDOWN_HOURS + 1)).isoformat()
    s = "\x1f"
    cycle._write_json(ledger_dir / cycle.BLOCKER_HISTOGRAM, {"repeats": {
        f"epigenetic_clocks{s}journal_surface_not_passed": [older, recent],     # 2 in-window -> skip
        f"coenzyme_q10_ubiquinol{s}retracted_source_cited": [older, recent],    # D_no_action counts -> skip
        f"gdf11{s}abstract_overclaim": [older, recent],                         # writer-fixable -> no
        f"young_plasma{s}receipt_preflight_insufficient": [older, recent],       # preflight -> no
        f"ergothioneine{s}journal_surface_not_passed": [recent],                # single -> no
        f"creatine{s}cycle_budget_exhausted": [older, recent],                  # transient code -> no
        f"glynac{s}final_status_not_ready": [older, recent],                    # repeated artifact not-ready -> skip
        f"rapamycin{s}journal_surface_not_passed": [stale, stale],              # out of window -> no
    }})

    assert cycle._surface_repeat_topics(ledger_dir, now=now) == {"epigenetic_clocks", "coenzyme_q10_ubiquinol", "glynac"}


def test_surface_repeat_topics_ignores_repaired_ready_topic(tmp_path: Path) -> None:
    ledger_dir = tmp_path / "runs" / cycle.LEDGER_DIR
    ledger_dir.mkdir(parents=True)
    topic = "colchicine_inflammaging"
    now = dt.datetime.now(dt.UTC)
    _write_json(ledger_dir / cycle.BLOCKER_HISTOGRAM, {"repeats": {
        f"{topic}\x1fjournal_surface_not_passed": [
            (now - dt.timedelta(minutes=10)).isoformat(),
            (now - dt.timedelta(minutes=5)).isoformat(),
        ],
    }})
    run = tmp_path / "runs" / f"synthesis-{topic}-v06-DAILY-2026-06-22T12-00-00Z"
    _write_json(run / "final_status.json", {"submission_ready": True})
    _write_json(run / "full_paper.journal_surface.json", {"passed": True, "issues": []})
    (run / "full_paper.md").write_text("# Research Synthesis: Colchicine Inflammaging\n", encoding="utf-8")
    # Later dry-run/probe folders are incomplete; they must not hide the latest
    # real ready artifact.
    (tmp_path / "runs" / f"synthesis-{topic}-v06-DAILY-2026-06-22T13-00-00Z").mkdir()

    assert cycle._surface_repeat_topics(ledger_dir, now=now, runs_root=tmp_path / "runs") == set()


def test_surface_repeat_topics_ignores_current_finalizer_repairable_topic(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import agent.journal_finalizer as finalizer
    import agent.journal_surface_gate as surface_gate

    ledger_dir = tmp_path / "runs" / cycle.LEDGER_DIR
    ledger_dir.mkdir(parents=True)
    topic = "senolytics"
    now = dt.datetime.now(dt.UTC)
    _write_json(ledger_dir / cycle.BLOCKER_HISTOGRAM, {"repeats": {
        f"{topic}\x1fjournal_surface_not_passed": [
            (now - dt.timedelta(minutes=10)).isoformat(),
            (now - dt.timedelta(minutes=5)).isoformat(),
        ],
    }})
    run = tmp_path / "runs" / f"synthesis-{topic}-v06-DAILY-2026-06-22T12-00-00Z-R2"
    _write_json(run / "final_status.json", {"submission_ready": False})
    _write_json(run / "full_paper.journal_surface.json", {
        "passed": False,
        "issues": [{"code": "topic_slug_artifact", "detail": "public topic-slug artifact: evidence_type"}],
    })
    _write_json(run / "manifest.json", {"review_type": "thin_corpus_brief"})
    (run / "full_paper.md").write_text("Evidence_type metadata note: evidence_type labels.\n", encoding="utf-8")

    def fake_finalize(out_dir: Path) -> None:
        (out_dir / "full_paper.md").write_text("Evidence type metadata note: evidence-type labels.\n", encoding="utf-8")

    seen_review_types: list[str | None] = []

    def fake_surface(paper: str, **kwargs: Any) -> Any:
        seen_review_types.append(kwargs.get("declared_review_type"))
        return SimpleNamespace(passed="evidence_type" not in paper, issues=())

    monkeypatch.setattr(finalizer, "finalize_run", fake_finalize)
    monkeypatch.setattr(surface_gate, "evaluate_journal_surface", fake_surface)

    assert cycle._surface_repeat_topics(ledger_dir, now=now, runs_root=tmp_path / "runs") == set()
    assert seen_review_types == ["thin_corpus_brief"]


def test_writer_gate_repeat_policy_downshifts_then_skips_after_brief_failure(tmp_path: Path) -> None:
    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    row = {"topic": "gdf11", "gate_status": "abstract_overclaim", "submitted": 0}
    cycle._record_blockers(ledger_dir, "2026-05-31", [row])
    cycle._record_blockers(ledger_dir, "2026-05-31", [row])

    policy = cycle._writer_gate_repeat_policy(ledger_dir)

    assert policy["gdf11"]["action"] == "thin_corpus_brief"
    assert policy["gdf11"]["gate"] == "abstract_overclaim"

    cycle._record_blockers(ledger_dir, "2026-05-31", [{
        **row,
        "review_type_override": "thin_corpus_brief",
    }])

    assert cycle._writer_gate_repeat_policy(ledger_dir)["gdf11"]["action"] == "skip_topic"


def test_record_blockers_accumulates_repeat_log_across_runs(tmp_path: Path) -> None:
    """_record_blockers builds the cumulative per-(topic, gate) log that survives
    the daily-ledger rewrite, so two separate runs trip the repeat skip."""
    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    attempt = {"topic": "coenzyme_q10_ubiquinol", "gate_status": "retracted_source_cited", "submitted": 0}
    cycle._record_blockers(ledger_dir, "2026-05-31", [attempt])
    assert cycle._surface_repeat_topics(ledger_dir) == set()  # one failure so far
    cycle._record_blockers(ledger_dir, "2026-05-31", [attempt])  # a later run
    assert cycle._surface_repeat_topics(ledger_dir) == {"coenzyme_q10_ubiquinol"}


def test_recent_preflight_blocked_topics_skip_after_one_recent_failure(tmp_path: Path) -> None:
    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    cycle._record_blockers(
        ledger_dir,
        "2026-05-31",
        [{"topic": "epigenetic_clocks", "submit_status": "preflight_insufficient_corpus", "submitted": 0}],
    )

    assert cycle._recent_preflight_blocked_topics(ledger_dir) == {"epigenetic_clocks"}


def test_recent_preflight_blocked_topics_include_receipt_preflight(tmp_path: Path) -> None:
    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    cycle._record_blockers(
        ledger_dir,
        "2026-06-02",
        [{"topic": "hrv_autonomic_aging", "gate_status": "receipt_preflight_insufficient", "submitted": 0}],
    )

    assert cycle._recent_preflight_blocked_topics(ledger_dir) == {"hrv_autonomic_aging"}


def test_cycle_downshifts_topic_after_same_writer_gate_twice(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "gdf11", target_journal=True)
    _prior_run(tmp_path, "gdf11", receipts=40, tensions=8, primary=3)
    ledger_dir = tmp_path / "runs" / cycle.LEDGER_DIR
    row = {"topic": "gdf11", "gate_status": "abstract_overclaim", "submitted": 0}
    cycle._record_blockers(ledger_dir, "2026-05-31", [row])
    cycle._record_blockers(ledger_dir, "2026-05-31", [row])
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_current_low_source_precision_topics", lambda topics: set())
    monkeypatch.setattr(cycle, "_quant_claim_source_precision", lambda topic, **_k: (
        True, "source_topic_precision_ok:40/40", [],
    ))
    monkeypatch.setattr(cycle, "_receipt_preflight", lambda *_args, **_kwargs: {"passed": True})
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
        date="2026-05-31",
        run_synthesis=True,
        submit=True,
        remote_loader=lambda: (set(), None),
        submit_cycle=lambda **_kwargs: {"status": "submitted_to_researka", "submitted": 1, "published": 0},
        max_attempts=1,
    )

    assert overrides == ["thin_corpus_brief"]
    assert ledger["review_type_override"]["reason"] == "writer_gate_repeat:abstract_overclaim"
    assert ledger["attempts"][0]["review_type_override"] == "thin_corpus_brief"


def test_cycle_skips_topic_after_brief_fails_same_writer_gate(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "aaa_gdf11", target_journal=True)
    _topic(tmp_path, "zzz_creatine", target_journal=True)
    _prior_run(tmp_path, "aaa_gdf11", receipts=40, tensions=8, primary=3)
    _prior_run(tmp_path, "zzz_creatine", receipts=40, tensions=8, primary=3)
    ledger_dir = tmp_path / "runs" / cycle.LEDGER_DIR
    row = {"topic": "aaa_gdf11", "gate_status": "abstract_overclaim", "submitted": 0}
    cycle._record_blockers(ledger_dir, "2026-05-31", [row])
    cycle._record_blockers(ledger_dir, "2026-05-31", [row])
    cycle._record_blockers(ledger_dir, "2026-05-31", [{
        **row,
        "review_type_override": "thin_corpus_brief",
    }])
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_current_low_source_precision_topics", lambda topics: set())
    monkeypatch.setattr(cycle, "_quant_claim_source_precision", lambda topic, **_k: (True, "source_topic_precision_ok:40/40", []))
    topics: list[str] = []

    def fake_synthesis(
        topic: str,
        out_dir: Path,
        *,
        dry_run: bool,
        timeout: int | None = None,
        revision_feedback: str | None = None,
        review_type_override: str | None = None,
    ) -> int:
        topics.append(topic)
        out_dir.mkdir(parents=True)
        return 0

    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-05-31",
        run_synthesis=True,
        submit=True,
        remote_loader=lambda: (set(), None),
        submit_cycle=lambda **_kwargs: {"status": "submitted_to_researka", "submitted": 1, "published": 0},
        max_attempts=1,
    )

    assert ledger["writer_gate_skip_topics"] == ["aaa_gdf11"]
    assert topics == ["zzz_creatine"]


def test_corpus_repair_topics_include_preflight_and_retracted_only(tmp_path: Path) -> None:
    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    for topic, status in [
        ("epigenetic_clocks", "preflight_insufficient_corpus"),
        ("coenzyme_q10_ubiquinol", "retracted_source_cited"),
        ("epigenome_editing_longevity", "source_topic_precision_low:1/4<0.50"),
        ("gdf11", "abstract_overclaim"),
    ]:
        cycle._record_blockers(ledger_dir, "2026-05-31", [{"topic": topic, "gate_status": status, "submitted": 0}])

    assert cycle._corpus_repair_topics(ledger_dir) == {
        "epigenetic_clocks",
        "coenzyme_q10_ubiquinol",
        "epigenome_editing_longevity",
    }
    assert cycle._source_precision_repair_topics(ledger_dir) == {"epigenome_editing_longevity"}


def test_corpus_repair_topic_helpers_use_exact_recent_histogram_statuses(tmp_path: Path) -> None:
    ledger_dir = tmp_path / "ledger"
    now = dt.datetime(2026, 6, 25, tzinfo=dt.UTC)
    stale = now - dt.timedelta(hours=cycle.RECENT_FAILURE_COOLDOWN_HOURS + 1)
    _write_json(ledger_dir / cycle.BLOCKER_HISTOGRAM, {
        "repeats": {
            "fresh_enough\x1fpreflight_insufficient_corpus": [now.isoformat()],
            "stale_enough\x1fpreflight_insufficient_corpus": [stale.isoformat()],
            f"source_low\x1f{cycle._SOURCE_PRECISION_STATUS}": [now.isoformat()],
            "surface_fail\x1fjournal_surface_failed": [now.isoformat()],
        },
    })

    assert cycle._corpus_repair_topics(ledger_dir, now=now) == {"fresh_enough", "source_low"}
    assert cycle._source_precision_repair_topics(ledger_dir, now=now) == {"source_low"}


def test_recent_blocked_topics_ignore_transient_seed_failures(tmp_path: Path) -> None:
    ledger_dir = tmp_path / "ledger"
    now = dt.datetime(2026, 6, 25, tzinfo=dt.UTC)
    _write_json(ledger_dir / cycle.BLOCKER_HISTOGRAM, {
        "repeats": {
            "repaired_later\x1fcorpus_seed_failed": [now.isoformat()],
            "surface_fail\x1fjournal_surface_failed": [now.isoformat()],
        },
    })

    assert cycle._recent_blocked_topics(ledger_dir, now=now) == {"surface_fail"}


def test_low_source_precision_repair_quarantines_and_reseeds(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "epigenome_editing_longevity", corpus=False)
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    qdir = cycle.CORPORA / "epigenome_editing_longevity" / "quant_claims"
    qdir.mkdir(parents=True)
    _write_json(qdir / "epigenome_editing_locus_specific.quant_claims.json", {"paper_id": "epigenome_editing_locus_specific"})
    _write_json(qdir / "supercapacitor_material.quant_claims.json", {"paper_id": "supercapacitor_material"})
    _write_json(qdir / "plant_flowering.quant_claims.json", {"paper_id": "plant_flowering"})
    _write_json(qdir / "glucose_transport.quant_claims.json", {"paper_id": "glucose_transport"})

    def fake_seed(topic: str, **_kwargs: Any) -> dict[str, Any]:
        _write_json(qdir / "epigenome_editing_database_fact.quant_claims.json", {"paper_id": "epigenome_editing_database_fact"})
        for i in range(3):
            _write_json(qdir / f"new_supercapacitor_noise_{i}.quant_claims.json", {"paper_id": f"new_supercapacitor_noise_{i}"})
        return {"status": "corpus_seeded", "n_quant_claims": 5}

    monkeypatch.setattr(cycle, "_repair_topic_corpus", fake_seed)

    repaired = cycle._repair_low_source_precision_corpus("epigenome_editing_longevity", dry_run=False)

    assert repaired["status"] == "source_precision_repaired"
    assert repaired["source_topic_precision_before"] == "source_topic_precision_low:1/4<0.50"
    assert repaired["source_topic_precision_after"] == "source_topic_precision_ok:2/2"
    assert repaired["off_topic_quant_claims_quarantined"] == 6
    assert repaired["post_seed_quarantined"] == 3
    assert sorted(path.name for path in qdir.glob("*.quant_claims.json")) == [
        "epigenome_editing_database_fact.quant_claims.json",
        "epigenome_editing_locus_specific.quant_claims.json",
    ]


def test_source_precision_repair_does_not_treat_empty_corpus_as_repaired(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "digital_frailty_index", corpus=False)
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")

    repaired = cycle._repair_low_source_precision_corpus("digital_frailty_index", dry_run=False)

    assert repaired["status"] == "source_precision_repair_incomplete"
    assert repaired["source_topic_precision"] == "source_topic_precision_unscored"
    assert repaired["n_quant_claims"] == 0


def test_source_precision_repair_fails_closed_when_all_claims_quarantined(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "digital_frailty_index", corpus=False)
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    qdir = cycle.CORPORA / "digital_frailty_index" / "quant_claims"
    qdir.mkdir(parents=True)
    _write_json(qdir / "generic_sensor.quant_claims.json", {"paper_id": "generic sensor biomarker"})
    _write_json(qdir / "voice_cough.quant_claims.json", {"paper_id": "voice cough digital biomarker"})
    monkeypatch.setattr(cycle, "_repair_topic_corpus", lambda topic, **_kwargs: {"status": "corpus_repaired", "n_quant_claims": 0})

    repaired = cycle._repair_low_source_precision_corpus("digital_frailty_index", dry_run=False)

    assert repaired["status"] == "source_precision_repair_incomplete"
    assert repaired["source_topic_precision_before"] == "source_topic_precision_low:0/2<0.50"
    assert repaired["source_topic_precision_after"] == "source_topic_precision_unscored"
    assert repaired["off_topic_quant_claims_quarantined"] == 2
    assert repaired["n_quant_claims"] == 0


def test_source_precision_repair_force_quarantines_misses_above_floor(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "hydrogen_water", corpus=False)
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    qdir = cycle.CORPORA / "hydrogen_water" / "quant_claims"
    qdir.mkdir(parents=True)
    _write_json(qdir / "hydrogen_water_trial.quant_claims.json", {"paper_id": "hydrogen_water_trial"})
    _write_json(qdir / "hydrogen_water_human_review.quant_claims.json", {"paper_id": "hydrogen_water_human_review"})
    _write_json(qdir / "cheminform_hydrogen_catalyst.quant_claims.json", {"paper_id": "cheminform_hydrogen_catalyst"})
    monkeypatch.setattr(cycle, "_repair_topic_corpus", lambda topic, **_kwargs: {"status": "corpus_ready", "n_quant_claims": 2})

    repaired = cycle._repair_low_source_precision_corpus("hydrogen_water", dry_run=False, force=True)

    assert repaired["status"] == "source_precision_repaired"
    assert repaired["source_topic_precision_before"] == "source_topic_precision_ok:2/3"
    assert repaired["off_topic_quant_claims_quarantined"] == 1
    assert sorted(path.name for path in qdir.glob("*.quant_claims.json")) == [
        "hydrogen_water_human_review.quant_claims.json",
        "hydrogen_water_trial.quant_claims.json",
    ]


def test_source_precision_uses_topic_aliases_without_keeping_plant_drift(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "hydrogen_water", corpus=False)
    (tmp_path / "topic_packs" / "hydrogen_water.toml").write_text(
        'aliases = ["molecular hydrogen", "hydrogen-rich water"]\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    qdir = cycle.CORPORA / "hydrogen_water" / "quant_claims"
    qdir.mkdir(parents=True)
    _write_json(qdir / "randomized_molecular_hydrogen_trial.quant_claims.json", {"paper_id": "randomized_molecular_hydrogen_trial"})
    _write_json(qdir / "molecular_hydrogen_improves_blueberry_plant_traits.quant_claims.json", {"paper_id": "molecular_hydrogen_improves_blueberry_plant_traits"})

    ok, status, misses = cycle._quant_claim_source_precision("hydrogen_water", floor=0.75)

    assert not ok
    assert status == "source_topic_precision_low:1/2<0.75"
    assert [path.name for path in misses] == ["molecular_hydrogen_improves_blueberry_plant_traits.quant_claims.json"]


def test_source_precision_repair_uses_submit_gate_aliases(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "low_dose_naltrexone_inflammation", corpus=False)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    (tmp_path / "topic_packs_db" / "low_dose_naltrexone_inflammation").mkdir(parents=True)
    _write_json(
        tmp_path / "topic_packs_db" / "low_dose_naltrexone_inflammation" / "latest.json",
        {
            "pack_data": {
                "aliases": ["inflammation"],
                "retrieval": {"topic_terms": ["inflammation", "naltrexone"]},
            },
        },
    )
    qdir = cycle.CORPORA / "low_dose_naltrexone_inflammation" / "quant_claims"
    qdir.mkdir(parents=True)
    _write_json(qdir / "named.quant_claims.json", {"paper_id": "low dose naltrexone trial"})
    _write_json(qdir / "broad.quant_claims.json", {"paper_id": "inflammation biomarker cohort"})

    ok, status, misses = cycle._quant_claim_source_precision(
        "low_dose_naltrexone_inflammation", floor=0.75,
    )

    assert not ok
    assert status == "source_topic_precision_low:1/2<0.75"
    assert [path.name for path in misses] == ["broad.quant_claims.json"]


def test_source_precision_drops_generic_static_alias_for_composite_topic(tmp_path: Path, monkeypatch) -> None:
    topic = "low_dose_naltrexone_inflammation"
    _topic(tmp_path, topic, corpus=False)
    (tmp_path / "topic_packs" / f"{topic}.toml").write_text(
        'aliases = ["low dose naltrexone", "LDN", "inflammation", "immune modulation"]\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    qdir = cycle.CORPORA / topic / "quant_claims"
    qdir.mkdir(parents=True)
    _write_json(qdir / "ldn_trial.quant_claims.json", {"paper_id": "low dose naltrexone trial"})
    _write_json(qdir / "inflammation_only.quant_claims.json", {"paper_id": "exercise inflammation cohort"})

    ok, status, misses = cycle._quant_claim_source_precision(topic, floor=0.75)

    assert not ok
    assert status == "source_topic_precision_low:1/2<0.75"
    assert [path.name for path in misses] == ["inflammation_only.quant_claims.json"]


def test_cycle_repairs_low_source_precision_then_retries_same_topic(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "epigenome_editing_longevity", target_journal=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_current_low_source_precision_topics", lambda topics: set())
    monkeypatch.setattr(cycle, "_receipt_preflight", lambda topic, out_dir, **_k: {"passed": True})
    runs: list[str] = []
    submit_calls = 0

    def fake_synthesis(
        topic: str,
        out_dir: Path,
        *,
        dry_run: bool,
        timeout: int | None = None,
        revision_feedback: str | None = None,
        review_type_override: str | None = None,
    ) -> int:
        runs.append(out_dir.name)
        out_dir.mkdir(parents=True)
        return 0

    def fake_submit(**_kwargs: Any) -> dict[str, Any]:
        nonlocal submit_calls
        submit_calls += 1
        if submit_calls == 1:
            return {
                "status": "no_eligible_research_paper",
                "submitted": 0,
                "published": 0,
                "considered": [{"run": runs[-1], "status": "source_topic_precision_low:1/4<0.50"}],
            }
        return {"status": "submitted_to_researka", "submitted": 1, "published": 0}

    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)
    monkeypatch.setattr(cycle, "_repair_low_source_precision_corpus", lambda topic, **_k: {
        "status": "source_precision_repaired",
        "source_topic_precision_after": "source_topic_precision_ok:12/12",
        "n_quant_claims": cycle.SOURCE_PRECISION_REPAIR_PUBLISH_MIN_QUANT,
    })

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-06-01",
        run_synthesis=True,
        submit=True,
        remote_loader=lambda: (set(), None),
        submit_cycle=fake_submit,
        max_attempts=1,
        max_revise_attempts=2,
    )

    assert ledger["status"] == "submitted_to_researka"
    assert len(runs) == 2
    assert ledger["attempts"][0]["source_precision_repair"]["status"] == "source_precision_repaired"


def test_cycle_stops_repeated_source_precision_retry_and_advances(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "aaa_hrv", target_journal=True)
    _topic(tmp_path, "zzz_ready", target_journal=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_current_low_source_precision_topics", lambda topics: set())
    monkeypatch.setattr(cycle, "_receipt_preflight", lambda topic, out_dir, **_k: {"passed": True})
    synthesized: list[str] = []
    runs: list[str] = []
    repair_calls = 0

    def fake_synthesis(topic: str, out_dir: Path, **_kwargs: Any) -> int:
        synthesized.append(topic)
        runs.append(out_dir.name)
        out_dir.mkdir(parents=True)
        _write_json(out_dir / "final_status.json", {"submission_ready": True})
        (out_dir / "full_paper.md").write_text(_surface_passing_paper(), encoding="utf-8")
        return 0

    def fake_submit(**_kwargs: Any) -> dict[str, Any]:
        if len(synthesized) < 3:
            return {
                "status": "no_eligible_research_paper",
                "submitted": 0,
                "published": 0,
                "considered": [{"run": runs[-1], "status": "source_topic_precision_low:1/16<0.50"}],
            }
        return {"status": "submitted_to_researka", "submitted": 1, "published": 0}

    def fake_repair(topic: str, **_kwargs: Any) -> dict[str, Any]:
        nonlocal repair_calls
        repair_calls += 1
        return {
            "status": "source_precision_repaired",
            "source_topic_precision_after": "source_topic_precision_ok:16/16",
            "n_quant_claims": cycle.SOURCE_PRECISION_REPAIR_PUBLISH_MIN_QUANT,
        }

    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)
    monkeypatch.setattr(cycle, "_repair_low_source_precision_corpus", fake_repair)

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-06-22",
        run_synthesis=True,
        submit=True,
        mode="fresh",
        remote_loader=lambda: (set(), None),
        submit_cycle=fake_submit,
        max_attempts=2,
        max_revise_attempts=3,
    )

    assert ledger["status"] == "submitted_to_researka"
    assert synthesized == ["aaa_hrv", "aaa_hrv", "zzz_ready"]
    assert repair_calls == 1
    assert ledger["attempts"][1]["same_gate_repeat_stop"] is True
    assert ledger["attempts"][1]["source_precision_repair_skipped"] == "repeat_gate"
    assert ledger["attempts"][2]["submit_status"] == "submitted_to_researka"


def test_cycle_repairs_low_precision_corpus_at_publish_floor_before_synthesis(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "epigenome_editing_longevity", corpus=False, target_journal=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_receipt_preflight", lambda topic, out_dir, **_k: {"passed": True})
    qdir = cycle.CORPORA / "epigenome_editing_longevity" / "quant_claims"
    qdir.mkdir(parents=True)
    for i in range(cycle.SOURCE_PRECISION_REPAIR_PUBLISH_MIN_QUANT):
        _write_json(qdir / f"epigenome_editing_{i}.quant_claims.json", {"paper_id": f"epigenome_editing_{i}"})
    for i in range(cycle.SOURCE_PRECISION_REPAIR_PUBLISH_MIN_QUANT):
        _write_json(qdir / f"supercapacitor_{i}.quant_claims.json", {"paper_id": f"supercapacitor_{i}"})
    synthesized: list[str] = []

    monkeypatch.setattr(cycle, "_repair_low_source_precision_corpus", lambda topic, **_k: {
        "status": "source_precision_repaired",
        "source_topic_precision_before": "source_topic_precision_low:24/48<0.50",
        "source_topic_precision_after": "source_topic_precision_ok:24/24",
        "n_quant_claims": cycle.SOURCE_PRECISION_REPAIR_PUBLISH_MIN_QUANT,
    })

    def fake_synthesis(
        topic: str,
        out_dir: Path,
        *,
        dry_run: bool,
        timeout: int | None = None,
        revision_feedback: str | None = None,
        review_type_override: str | None = None,
    ) -> int:
        synthesized.append(topic)
        out_dir.mkdir(parents=True)
        return 0

    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)
    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-06-01",
        run_synthesis=True,
        submit=True,
        remote_loader=lambda: (set(), None),
        submit_cycle=lambda **_kwargs: {"status": "submitted_to_researka", "submitted": 1, "published": 0},
        max_attempts=1,
    )

    assert synthesized == ["epigenome_editing_longevity"]
    assert ledger["corpus_repairs"][0]["source_topic_precision_before"] == "source_topic_precision_low:24/48<0.50"
    assert ledger["status"] == "submitted_to_researka"


def test_source_precision_repair_publishable_requires_receipt_buffer() -> None:
    assert not cycle._source_precision_repair_publishable({
        "status": "source_precision_repaired",
        "n_quant_claims": cycle.PREFLIGHT_MIN_RECEIPTS + 1,
    })
    assert cycle._source_precision_repair_publishable({
        "status": "source_precision_repaired",
        "n_quant_claims": cycle.SOURCE_PRECISION_REPAIR_PUBLISH_MIN_QUANT,
    })


def test_cycle_skips_sparse_receipt_topic_before_synthesis(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "oral_microbiome_periodontal_aging", target_journal=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_current_low_source_precision_topics", lambda topics: set())
    monkeypatch.setattr(cycle, "_quant_claim_source_precision", lambda topic, **_k: (True, "source_topic_precision_ok:10/10", []))
    monkeypatch.setattr(cycle, "_receipt_preflight", lambda topic, out_dir, **_k: {
        "passed": False,
        "status": "receipt_preflight_insufficient",
        "n_receipts": 5,
        "min_receipts": 12,
    })
    synthesized: list[str] = []

    def fake_synthesis(topic: str, out_dir: Path, **_kwargs: Any) -> int:
        synthesized.append(topic)
        return 0

    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-06-01",
        run_synthesis=True,
        submit=True,
        remote_loader=lambda: (set(), None),
        submit_cycle=lambda **_kwargs: {"status": "submitted_to_researka", "submitted": 1, "published": 0},
        max_attempts=1,
    )

    assert synthesized == []
    assert ledger["status"] == "receipt_preflight_skipped_no_submission"
    assert ledger["attempts"][0]["receipt_preflight"]["n_receipts"] == 5


def test_receipt_preflight_repairs_and_reprobes_until_floor(tmp_path: Path, monkeypatch) -> None:
    counts = [7, 9, cycle.DEFAULT_THRESHOLDS.min_receipts]
    repairs: list[dict[str, Any]] = []
    monkeypatch.setattr(cycle, "_quant_claim_count", lambda topic: 0)

    def fake_synthesis(topic: str, out_dir: Path, *, dry_run: bool, timeout: int | None = None, **_kwargs: Any) -> int:
        assert topic == "urolithin_a"
        assert dry_run is True
        assert timeout == 99
        n_receipts = counts.pop(0)
        out_dir.mkdir(parents=True)
        _write_json(out_dir / "receipt_funnel.json", {"counts": {"admitted_receipts": n_receipts}})
        return 0

    def fake_repair(
        topic: str,
        *,
        dry_run: bool,
        timeout: int | None = None,
        seed_limit: int | None = None,
        force_extract: bool = True,
    ) -> dict[str, Any]:
        repair = {
            "topic": topic,
            "dry_run": dry_run,
            "timeout": timeout,
            "seed_limit": seed_limit,
            "force_extract": force_extract,
            "status": "corpus_repaired",
        }
        repairs.append(repair)
        return repair

    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)
    monkeypatch.setattr(cycle, "_repair_topic_corpus", fake_repair)

    result = cycle._receipt_preflight("urolithin_a", tmp_path / "run", timeout=99)

    assert result["passed"] is True
    assert result["n_receipts"] == cycle.DEFAULT_THRESHOLDS.min_receipts
    assert [probe["n_receipts"] for probe in result["probes"]] == [7, 9, cycle.DEFAULT_THRESHOLDS.min_receipts]
    assert repairs == [
        {"topic": "urolithin_a", "dry_run": False, "timeout": 99, "seed_limit": cycle.DEFAULT_THRESHOLDS.min_receipts, "force_extract": False, "status": "corpus_repaired"},
        {"topic": "urolithin_a", "dry_run": False, "timeout": 99, "seed_limit": cycle.DEFAULT_THRESHOLDS.min_receipts, "force_extract": False, "status": "corpus_repaired"},
    ]
    assert result["repairs"] == repairs


def test_receipt_preflight_repair_keeps_best_probe_after_regression(tmp_path: Path, monkeypatch) -> None:
    probes = [(0, 7), (2, 0), (0, cycle.DEFAULT_THRESHOLDS.min_receipts)]
    repairs: list[dict[str, Any]] = []
    monkeypatch.setattr(cycle, "_quant_claim_count", lambda topic: 34)

    def fake_synthesis(topic: str, out_dir: Path, *, dry_run: bool, **_kwargs: Any) -> int:
        rc, n_receipts = probes.pop(0)
        out_dir.mkdir(parents=True)
        _write_json(out_dir / "receipt_funnel.json", {"counts": {"admitted_receipts": n_receipts}})
        return rc

    def fake_repair(topic: str, **kwargs: Any) -> dict[str, Any]:
        repair = {"topic": topic, "status": "corpus_repaired", **kwargs}
        repairs.append(repair)
        return repair

    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)
    monkeypatch.setattr(cycle, "_repair_topic_corpus", fake_repair)

    result = cycle._receipt_preflight("partial_epigenetic_reprogramming", tmp_path / "run")

    assert result["passed"] is True
    assert [probe["n_receipts"] for probe in result["probes"]] == [7, 0, cycle.DEFAULT_THRESHOLDS.min_receipts]
    assert [repair["seed_limit"] for repair in repairs] == [59, 84]
    assert all(repair["force_extract"] is False for repair in repairs)


def test_receipt_preflight_dry_run_does_not_repair(tmp_path: Path, monkeypatch) -> None:
    repairs: list[str] = []

    def fake_synthesis(topic: str, out_dir: Path, *, dry_run: bool, **_kwargs: Any) -> int:
        out_dir.mkdir(parents=True)
        _write_json(out_dir / "receipt_funnel.json", {"counts": {"admitted_receipts": 7}})
        return 0

    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)
    monkeypatch.setattr(cycle, "_repair_topic_corpus", lambda topic, **_k: repairs.append(topic))

    result = cycle._receipt_preflight("urolithin_a", tmp_path / "run", dry_run=True)

    assert result["passed"] is False
    assert [probe["n_receipts"] for probe in result["probes"]] == [7]
    assert repairs == []


def test_fresh_cycle_repairs_sparse_receipt_preflight_before_submit(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "urolithin_a", target_journal=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_current_low_source_precision_topics", lambda topics: set())
    monkeypatch.setattr(cycle, "_quant_claim_source_precision", lambda topic, **_k: (True, "source_topic_precision_ok:10/10", []))
    monkeypatch.setattr(cycle, "_repair_topic_corpus", lambda topic, **_k: {"status": "corpus_repaired", "n_quant_claims": 18})
    receipt_counts = [7, cycle.DEFAULT_THRESHOLDS.min_receipts]
    synthesized: list[str] = []

    def fake_synthesis(topic: str, out_dir: Path, *, dry_run: bool, **_kwargs: Any) -> int:
        out_dir.mkdir(parents=True)
        if dry_run:
            _write_json(out_dir / "receipt_funnel.json", {"counts": {"admitted_receipts": receipt_counts.pop(0)}})
        else:
            synthesized.append(topic)
            _write_json(out_dir / "final_status.json", {"submission_ready": True})
            (out_dir / "full_paper.md").write_text(_surface_passing_paper(), encoding="utf-8")
        return 0

    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-06-04",
        run_synthesis=True,
        submit=True,
        mode="fresh",
        remote_loader=lambda: (set(), None),
        submit_cycle=lambda **_kwargs: {"status": "submitted_to_researka", "submitted": 1, "published": 0},
        max_attempts=1,
    )

    assert ledger["status"] == "submitted_to_researka"
    assert synthesized == ["urolithin_a"]
    assert [probe["n_receipts"] for probe in ledger["attempts"][0]["receipt_preflight"]["probes"]] == [
        7,
        cycle.DEFAULT_THRESHOLDS.min_receipts,
    ]
    assert ledger["attempts"][0]["receipt_preflight"]["repairs"][0]["status"] == "corpus_repaired"


def test_revise_lane_sparse_receipt_preflight_is_terminal(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "hrv_autonomic_aging", target_journal=True)
    source = _prior_run(tmp_path, "hrv_autonomic_aging", receipts=12, tensions=2, primary=1, level=5)
    paper = source / "full_paper.md"
    paper.write_text("# Research Synthesis: HRV Autonomic Aging\n", encoding="utf-8")
    _write_json(tmp_path / "runs" / cycle.submit_bridge.LEDGER_DIR / "_submitted_fingerprints.json", [{
        "run": source.name,
        "topic": "hrv_autonomic_aging",
        "fingerprint": cycle.submit_bridge._sha256(paper),
    }])
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_current_low_source_precision_topics", lambda topics: set())
    monkeypatch.setattr(cycle, "_quant_claim_source_precision", lambda topic, **_k: (True, "source_topic_precision_ok:10/10", []))
    receipt_kwargs = []

    def fake_receipt_preflight(topic: str, out_dir: Path, **kwargs: Any) -> dict[str, Any]:
        receipt_kwargs.append(kwargs)
        return {
        "passed": False,
        "status": "receipt_preflight_insufficient",
        "n_receipts": 2,
        "min_receipts": 12,
        }

    monkeypatch.setattr(cycle, "_receipt_preflight", fake_receipt_preflight)
    monkeypatch.setattr(cycle, "_run_synthesis", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("sparse receipt revise must not synthesize")))
    request = {
        "artifactId": "hrv-review",
        "title": "Research Synthesis: HRV Autonomic Aging",
        "feedback": "Revise with better support.",
    }

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-06-02",
        run_synthesis=True,
        submit=True,
        mode="revise",
        remote_loader=lambda: (set(), None),
        revision_loader=lambda: ([request], None),
        submit_cycle=lambda **_kwargs: {"status": "submitted_to_researka", "submitted": 1, "published": 0},
    )

    assert ledger["status"] == "revise_terminal_receipt_preflight_insufficient"
    assert ledger["attempts"][0]["gate_status"] == "terminal_receipt_preflight_insufficient"
    assert receipt_kwargs[0]["repair"] is True
    handled = json.loads((tmp_path / "runs" / cycle.LEDGER_DIR / cycle.HANDLED_REVISIONS).read_text(encoding="utf-8"))
    assert handled["handled"][0]["status"] == "terminal_receipt_preflight_insufficient"
    assert cycle.submit_bridge._title_marker(request["title"]) in cycle._handled_revision_ids(tmp_path / "runs" / cycle.LEDGER_DIR)
    pending, error = cycle._pending_remote_revision(
        tmp_path / "runs",
        tmp_path / "runs" / cycle.LEDGER_DIR,
        loader=lambda: ([request], None),
    )
    assert error is None
    assert pending is None


def test_revise_lane_marks_repaired_severely_sparse_receipt_preflight_terminal(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "plasma_proteomic_age_clocks", target_journal=True)
    source = _prior_run(tmp_path, "plasma_proteomic_age_clocks", receipts=3, tensions=0, primary=0, level=5)
    paper = source / "full_paper.md"
    title = "Hypothesis-Generating Brief: Plasma proteomic age clocks — full paper"
    paper.write_text(f"# {title}\n", encoding="utf-8")
    _write_json(tmp_path / "runs" / cycle.submit_bridge.LEDGER_DIR / "_submitted_fingerprints.json", [{
        "run": source.name,
        "topic": "plasma_proteomic_age_clocks",
        "fingerprint": cycle.submit_bridge._sha256(paper),
    }])
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_current_low_source_precision_topics", lambda topics: set())
    monkeypatch.setattr(cycle, "_quant_claim_source_precision", lambda topic, **_k: (True, "source_topic_precision_ok:10/10", []))

    def fake_receipt_preflight(topic: str, out_dir: Path, **_kwargs: Any) -> dict[str, Any]:
        return {
            "passed": False,
            "status": "receipt_preflight_insufficient",
            "n_receipts": 3,
            "min_receipts": 12,
            "probes": [
                {"return_code": 0, "n_receipts": 3, "min_receipts": 12},
                {"return_code": 0, "n_receipts": 3, "min_receipts": 12},
            ],
            "repairs": [{"status": "corpus_repaired", "n_quant_claims": 15}],
        }

    monkeypatch.setattr(cycle, "_receipt_preflight", fake_receipt_preflight)
    monkeypatch.setattr(cycle, "_run_synthesis", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("terminal sparse revise must not synthesize")))
    request = {
        "artifactId": "plasma-review",
        "title": title,
        "feedback": "Reset the source bundle to include only studies that actually develop, validate, or apply a plasma proteomic age clock.",
    }

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-06-24",
        run_synthesis=True,
        submit=True,
        mode="revise",
        remote_loader=lambda: (set(), None),
        revision_loader=lambda: ([request], None),
        submit_cycle=lambda **_kwargs: {"status": "submitted_to_researka", "submitted": 1, "published": 0},
    )

    assert ledger["status"] == "revise_terminal_receipt_preflight_insufficient"
    assert ledger["attempts"][0]["gate_status"] == "terminal_receipt_preflight_insufficient"
    handled = json.loads((tmp_path / "runs" / cycle.LEDGER_DIR / cycle.HANDLED_REVISIONS).read_text(encoding="utf-8"))
    assert handled["handled"][0]["status"] == "terminal_receipt_preflight_insufficient"
    pending, error = cycle._pending_remote_revision(
        tmp_path / "runs",
        tmp_path / "runs" / cycle.LEDGER_DIR,
        loader=lambda: ([request], None),
    )
    assert error is None
    assert pending is None


def test_fresh_lane_tries_next_after_sparse_receipt_preflight(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "aaa_sparse_receipts", target_journal=True)
    _topic(tmp_path, "zzz_ready", target_journal=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_current_low_source_precision_topics", lambda topics: set())
    monkeypatch.setattr(cycle, "_quant_claim_source_precision", lambda topic, **_k: (True, "source_topic_precision_ok:10/10", []))

    def fake_receipt_preflight(topic: str, out_dir: Path, **_k: Any) -> dict[str, Any]:
        if topic == "aaa_sparse_receipts":
            return {
                "passed": False,
                "status": "receipt_preflight_insufficient",
                "n_receipts": 3,
                "min_receipts": 12,
            }
        return {"passed": True, "status": "receipt_preflight_ok", "n_receipts": 18, "min_receipts": 12}

    synthesized: list[str] = []

    def fake_synthesis(topic: str, out_dir: Path, **_kwargs: Any) -> int:
        synthesized.append(topic)
        out_dir.mkdir(parents=True)
        _write_json(out_dir / "final_status.json", {"submission_ready": True})
        (out_dir / "full_paper.md").write_text(_surface_passing_paper(), encoding="utf-8")
        return 0

    monkeypatch.setattr(cycle, "_receipt_preflight", fake_receipt_preflight)
    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-06-02",
        run_synthesis=True,
        submit=True,
        mode="fresh",
        remote_loader=lambda: (set(), None),
        submit_cycle=lambda **_kwargs: {"status": "submitted_to_researka", "submitted": 1, "published": 0},
        max_attempts=2,
    )

    assert synthesized == ["zzz_ready"]
    assert ledger["status"] == "submitted_to_researka"
    assert [a["topic"] for a in ledger["attempts"]] == ["aaa_sparse_receipts", "zzz_ready"]
    assert ledger["attempts"][0]["gate_status"] == "receipt_preflight_insufficient"
    assert ledger["attempts"][1]["submit_status"] == "submitted_to_researka"


def test_fresh_lane_unbounded_attempts_reach_ready_after_sparse_receipts(
    tmp_path: Path, monkeypatch,
) -> None:
    for topic in ("aaa_sparse_receipts", "bbb_sparse_receipts", "zzz_ready"):
        _topic(tmp_path, topic, target_journal=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_current_low_source_precision_topics", lambda topics: set())
    monkeypatch.setattr(cycle, "_quant_claim_source_precision", lambda topic, **_k: (True, "source_topic_precision_ok:10/10", []))

    def fake_receipt_preflight(topic: str, out_dir: Path, **_k: Any) -> dict[str, Any]:
        if topic.startswith(("aaa_", "bbb_")):
            return {
                "passed": False,
                "status": "receipt_preflight_insufficient",
                "n_receipts": 9,
                "min_receipts": 12,
            }
        return {"passed": True, "status": "receipt_preflight_ok", "n_receipts": 18, "min_receipts": 12}

    synthesized: list[str] = []

    def fake_synthesis(topic: str, out_dir: Path, **_kwargs: Any) -> int:
        synthesized.append(topic)
        out_dir.mkdir(parents=True)
        _write_json(out_dir / "final_status.json", {"submission_ready": True})
        (out_dir / "full_paper.md").write_text(_surface_passing_paper(), encoding="utf-8")
        return 0

    monkeypatch.setattr(cycle, "_receipt_preflight", fake_receipt_preflight)
    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-06-02",
        run_synthesis=True,
        submit=True,
        mode="fresh",
        remote_loader=lambda: (set(), None),
        submit_cycle=lambda **_kwargs: {"status": "submitted_to_researka", "submitted": 1, "published": 0},
        max_attempts=0,
    )

    assert synthesized == ["zzz_ready"]
    assert ledger["status"] == "submitted_to_researka"
    assert [a["topic"] for a in ledger["attempts"]] == [
        "aaa_sparse_receipts",
        "bbb_sparse_receipts",
        "zzz_ready",
    ]
    assert [a["gate_status"] for a in ledger["attempts"][:2]] == [
        "receipt_preflight_insufficient",
        "receipt_preflight_insufficient",
    ]


@pytest.mark.parametrize(
    ("repair_limit", "expected_preflights"),
    [
        (
            0,
            [
                ("aaa_sparse_receipts", False),
                ("bbb_sparse_receipts", False),
                ("zzz_ready", False),
            ],
        ),
        (
            1,
            [
                ("aaa_sparse_receipts", True),
                ("bbb_sparse_receipts", False),
                ("zzz_ready", False),
            ],
        ),
        (
            2,
            [
                ("aaa_sparse_receipts", True),
                ("bbb_sparse_receipts", True),
                ("zzz_ready", False),
            ],
        ),
    ],
)
def test_fresh_lane_receipt_preflight_repair_respects_corpus_repair_limit(
    tmp_path: Path, monkeypatch, repair_limit: int, expected_preflights: list[tuple[str, bool]],
) -> None:
    for topic in ("aaa_sparse_receipts", "bbb_sparse_receipts", "zzz_ready"):
        _topic(tmp_path, topic, target_journal=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_corpus_repair_limit", lambda: repair_limit)
    monkeypatch.setattr(cycle, "_current_low_source_precision_topics", lambda topics: set())
    monkeypatch.setattr(cycle, "_quant_claim_source_precision", lambda topic, **_k: (True, "source_topic_precision_ok:10/10", []))
    preflights: list[tuple[str, bool]] = []

    def fake_receipt_preflight(topic: str, out_dir: Path, **kwargs: Any) -> dict[str, Any]:
        repair = bool(kwargs.get("repair"))
        preflights.append((topic, repair))
        if topic.startswith(("aaa_", "bbb_")):
            result: dict[str, Any] = {
                "passed": False,
                "status": "receipt_preflight_insufficient",
                "n_receipts": 9,
                "min_receipts": 12,
            }
            if repair:
                result["repairs"] = [{"status": "corpus_repaired", "n_quant_claims": 18}]
            return result
        return {"passed": True, "status": "receipt_preflight_ok", "n_receipts": 18, "min_receipts": 12}

    synthesized: list[str] = []

    def fake_synthesis(topic: str, out_dir: Path, **_kwargs: Any) -> int:
        synthesized.append(topic)
        out_dir.mkdir(parents=True)
        _write_json(out_dir / "final_status.json", {"submission_ready": True})
        (out_dir / "full_paper.md").write_text(_surface_passing_paper(), encoding="utf-8")
        return 0

    monkeypatch.setattr(cycle, "_receipt_preflight", fake_receipt_preflight)
    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-06-02",
        run_synthesis=True,
        submit=True,
        mode="fresh",
        remote_loader=lambda: (set(), None),
        submit_cycle=lambda **_kwargs: {"status": "submitted_to_researka", "submitted": 1, "published": 0},
        max_attempts=0,
    )

    assert preflights == expected_preflights
    assert synthesized == ["zzz_ready"]
    assert ledger["status"] == "submitted_to_researka"


@pytest.mark.parametrize(
    ("first_gate", "second_gate"),
    [
        ("abstract_overclaim", "audit_not_all_green"),
        ("pre_submit_not_passed", "audit_not_all_green"),
    ],
)
def test_fresh_lane_moves_on_after_same_topic_gate_retry_exhausted(
    tmp_path: Path, monkeypatch, first_gate: str, second_gate: str,
) -> None:
    _topic(tmp_path, "aaa_bad_surface", target_journal=True)
    _topic(tmp_path, "zzz_ready", target_journal=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_current_low_source_precision_topics", lambda topics: set())
    monkeypatch.setattr(cycle, "_quant_claim_source_precision", lambda topic, **_k: (True, "source_topic_precision_ok:10/10", []))
    monkeypatch.setattr(cycle, "_receipt_preflight", lambda topic, out_dir, **_k: {"passed": True})
    monkeypatch.setattr(cycle, "_repair_existing_run", lambda *_a, **_k: (False, "repair_noop"))
    synthesized: list[str] = []
    synthesized_runs: list[str] = []

    def fake_synthesis(topic: str, out_dir: Path, **_kwargs: Any) -> int:
        synthesized.append(topic)
        synthesized_runs.append(out_dir.name)
        out_dir.mkdir(parents=True)
        _write_json(out_dir / "final_status.json", {"submission_ready": True})
        (out_dir / "full_paper.md").write_text(_surface_passing_paper(), encoding="utf-8")
        return 0

    gate_statuses = iter([first_gate, second_gate, "submitted_to_researka"])

    def fake_submit(**_kwargs: Any) -> dict[str, Any]:
        status = next(gate_statuses)
        if status == "submitted_to_researka":
            return {"status": status, "submitted": 1, "published": 0}
        return {
            "status": "no_eligible_research_paper",
            "submitted": 0,
            "published": 0,
            "considered": [{"run": synthesized_runs[-1], "status": status}],
        }

    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-06-10",
        run_synthesis=True,
        submit=True,
        mode="fresh",
        remote_loader=lambda: (set(), None),
        submit_cycle=fake_submit,
        max_attempts=2,
    )

    assert ledger["status"] == "submitted_to_researka"
    assert synthesized == ["aaa_bad_surface", "aaa_bad_surface", "zzz_ready"]
    assert [a["topic"] for a in ledger["attempts"]] == ["aaa_bad_surface", "aaa_bad_surface", "zzz_ready"]
    assert ledger["attempts"][1]["same_topic_retry_stop"] is True
    assert ledger["attempts"][2]["submit_status"] == "submitted_to_researka"
    assert "no_submission_reason" not in ledger


def test_fresh_lane_rotates_after_one_surface_failure(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "aaa_bad_surface", target_journal=True)
    _topic(tmp_path, "zzz_ready", target_journal=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_current_low_source_precision_topics", lambda topics: set())
    monkeypatch.setattr(cycle, "_quant_claim_source_precision", lambda topic, **_k: (True, "source_topic_precision_ok:10/10", []))
    monkeypatch.setattr(cycle, "_receipt_preflight", lambda topic, out_dir, **_k: {"passed": True})
    synthesized: list[str] = []
    synthesized_runs: list[str] = []

    def fake_synthesis(topic: str, out_dir: Path, **_kwargs: Any) -> int:
        synthesized.append(topic)
        synthesized_runs.append(out_dir.name)
        out_dir.mkdir(parents=True)
        _write_json(out_dir / "final_status.json", {"submission_ready": True})
        (out_dir / "full_paper.md").write_text(_surface_passing_paper(), encoding="utf-8")
        return 0

    statuses = iter(["journal_surface_failed", "submitted_to_researka"])

    def fake_submit(**_kwargs: Any) -> dict[str, Any]:
        status = next(statuses)
        if status == "submitted_to_researka":
            return {"status": status, "submitted": 1, "published": 0}
        return {
            "status": "no_eligible_research_paper",
            "submitted": 0,
            "published": 0,
            "considered": [{"run": synthesized_runs[-1], "status": status}],
        }

    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-06-24",
        run_synthesis=True,
        submit=True,
        mode="fresh",
        remote_loader=lambda: (set(), None),
        submit_cycle=fake_submit,
        max_attempts=2,
    )

    assert ledger["status"] == "submitted_to_researka"
    assert synthesized == ["aaa_bad_surface", "zzz_ready"]
    assert [a["topic"] for a in ledger["attempts"]] == ["aaa_bad_surface", "zzz_ready"]
    assert ledger["attempts"][0]["gate_status"] == "journal_surface_failed"


def test_fresh_lane_retries_once_after_transient_synthesis_failure(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "aaa_transient", target_journal=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_current_low_source_precision_topics", lambda topics: set())
    monkeypatch.setattr(cycle, "_quant_claim_source_precision", lambda topic, **_k: (True, "source_topic_precision_ok:10/10", []))
    monkeypatch.setattr(cycle, "_receipt_preflight", lambda topic, out_dir, **_k: {"passed": True})
    synthesized: list[str] = []

    def fake_synthesis(topic: str, out_dir: Path, **_kwargs: Any) -> int:
        synthesized.append(topic)
        if len(synthesized) == 1:
            return 1
        out_dir.mkdir(parents=True)
        _write_json(out_dir / "final_status.json", {"submission_ready": True})
        (out_dir / "full_paper.md").write_text(_surface_passing_paper(), encoding="utf-8")
        return 0

    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-06-10",
        run_synthesis=True,
        submit=True,
        mode="fresh",
        remote_loader=lambda: (set(), None),
        submit_cycle=lambda **_kwargs: {"status": "submitted_to_researka", "submitted": 1, "published": 0},
        max_attempts=1,
    )

    assert ledger["status"] == "submitted_to_researka"
    assert synthesized == ["aaa_transient", "aaa_transient"]
    assert ledger["attempts"][0]["gate_status"] == "synthesis_failed"
    assert "same_topic_retry_stop" not in ledger["attempts"][0]
    assert ledger["attempts"][1]["submit_status"] == "submitted_to_researka"


def test_cycle_quarantines_source_precision_misses_before_synthesis(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "hydrogen_water", corpus=False, target_journal=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_receipt_preflight", lambda topic, out_dir, **_k: {"passed": True})
    qdir = cycle.CORPORA / "hydrogen_water" / "quant_claims"
    qdir.mkdir(parents=True)
    for i in range(24):
        _write_json(qdir / f"hydrogen_water_{i}.quant_claims.json", {"paper_id": f"hydrogen_water_{i}"})
    _write_json(qdir / "blueberry_plant.quant_claims.json", {"paper_id": "blueberry plant traits"})
    repaired: list[dict[str, Any]] = []
    synthesized: list[str] = []

    def fake_repair(topic: str, **kwargs: Any) -> dict[str, Any]:
        repaired.append({"topic": topic, **kwargs})
        return {
            "status": "source_precision_repaired",
            "source_topic_precision_before": "source_topic_precision_ok:24/25",
            "source_topic_precision_after": "source_topic_precision_ok:24/24",
            "n_quant_claims": 24,
        }

    def fake_synthesis(topic: str, out_dir: Path, **_kwargs: Any) -> int:
        synthesized.append(topic)
        out_dir.mkdir(parents=True)
        return 0

    monkeypatch.setattr(cycle, "_repair_low_source_precision_corpus", fake_repair)
    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)
    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-06-01",
        run_synthesis=True,
        submit=True,
        remote_loader=lambda: (set(), None),
        submit_cycle=lambda **_kwargs: {"status": "submitted_to_researka", "submitted": 1, "published": 0},
        max_attempts=1,
    )

    assert len(repaired) == 1
    assert repaired[0]["timeout"] is not None
    assert {k: v for k, v in repaired[0].items() if k != "timeout"} == {
        "topic": "hydrogen_water",
        "dry_run": False,
        "force": True,
    }
    assert synthesized == ["hydrogen_water"]
    assert ledger["source_precision_repair"]["source_topic_precision_after"] == "source_topic_precision_ok:24/24"
    assert ledger["status"] == "submitted_to_researka"


def test_cycle_skips_preflight_repair_when_clean_topic_ready(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "aaa_thin_topic", target_journal=True)
    _topic(tmp_path, "zzz_solid_topic", target_journal=True)
    _prior_run(tmp_path, "aaa_thin_topic", receipts=6, tensions=0, primary=0)
    ledger_dir = tmp_path / "runs" / cycle.LEDGER_DIR
    cycle._record_blockers(
        ledger_dir,
        "2026-05-31",
        [{"topic": "aaa_thin_topic", "submit_status": "preflight_insufficient_corpus", "submitted": 0}],
    )
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_corpus_repair_limit", lambda: 1)
    monkeypatch.setattr(cycle, "_receipt_preflight", lambda topic, out_dir, **_k: {"passed": True})
    monkeypatch.setattr(cycle, "_quant_claim_source_precision", lambda topic, **_k: (True, "source_topic_precision_ok:10/10", []))
    monkeypatch.setattr(cycle, "_repair_topic_corpus", lambda topic, **_k: {
        "status": "corpus_repaired", "n_quant_claims": cycle.PREFLIGHT_MIN_QUANT_CLAIMS,
    })
    topics: list[str] = []

    def fake_synthesis(
        topic: str,
        out_dir: Path,
        *,
        dry_run: bool,
        timeout: int | None = None,
        revision_feedback: str | None = None,
        review_type_override: str | None = None,
    ) -> int:
        topics.append(topic)
        out_dir.mkdir(parents=True)
        return 0

    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-05-31",
        run_synthesis=True,
        submit=True,
        remote_loader=lambda: (set(), None),
        submit_cycle=lambda **_kwargs: {"status": "submitted_to_researka", "submitted": 1, "published": 0},
        max_attempts=1,
    )

    assert "corpus_repairs" not in ledger
    assert ledger["topic_status"]["aaa_thin_topic"] == "preflight_blocked"
    assert topics == ["zzz_solid_topic"]
    assert ledger["status"] == "submitted_to_researka"


def test_cycle_reseeds_preflight_blocked_topic_when_no_clean_topic_ready(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "aaa_thin_topic", target_journal=True)
    _prior_run(tmp_path, "aaa_thin_topic", receipts=6, tensions=0, primary=0)
    ledger_dir = tmp_path / "runs" / cycle.LEDGER_DIR
    cycle._record_blockers(
        ledger_dir,
        "2026-05-31",
        [{"topic": "aaa_thin_topic", "submit_status": "preflight_insufficient_corpus", "submitted": 0}],
    )
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_corpus_repair_limit", lambda: 1)
    monkeypatch.setattr(cycle, "_receipt_preflight", lambda topic, out_dir, **_k: {"passed": True})
    monkeypatch.setattr(cycle, "_quant_claim_source_precision", lambda topic, **_k: (True, "source_topic_precision_ok:10/10", []))
    monkeypatch.setattr(cycle, "_repair_topic_corpus", lambda topic, **_k: pytest.fail(f"unexpected repair: {topic}"))
    topics: list[str] = []

    def fake_synthesis(topic: str, out_dir: Path, **_kwargs: Any) -> int:
        topics.append(topic)
        out_dir.mkdir(parents=True)
        return 0

    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-05-31",
        run_synthesis=True,
        submit=True,
        remote_loader=lambda: (set(), None),
        submit_cycle=lambda **_kwargs: {"status": "submitted_to_researka", "submitted": 1, "published": 0},
        max_attempts=1,
    )

    assert "corpus_repairs" not in ledger
    assert ledger["topic_status"]["aaa_thin_topic"] == "preflight_blocked"
    assert ledger["preflight_reseed_selected"] == "aaa_thin_topic"
    assert topics == ["aaa_thin_topic"]
    assert ledger["status"] == "submitted_to_researka"


def test_cycle_does_not_reseed_recent_receipt_preflight_blocked_topic(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "aaa_sparse_receipts", target_journal=True)
    _prior_run(tmp_path, "aaa_sparse_receipts", receipts=4, tensions=0, primary=0)
    ledger_dir = tmp_path / "runs" / cycle.LEDGER_DIR
    cycle._record_blockers(
        ledger_dir,
        "2026-06-25",
        [{"topic": "aaa_sparse_receipts", "gate_status": "receipt_preflight_insufficient", "submitted": 0}],
    )
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_corpus_repair_limit", lambda: 1)
    monkeypatch.setattr(cycle, "_refresh_topic_supply", lambda *_a, **_k: {"created": 0})
    monkeypatch.setattr(cycle, "_receipt_preflight", lambda *_a, **_k: pytest.fail("unexpected receipt preflight"))
    monkeypatch.setattr(cycle, "_repair_topic_corpus", lambda *_a, **_k: pytest.fail("unexpected repair"))
    monkeypatch.setattr(cycle, "_run_synthesis", lambda *_a, **_k: pytest.fail("unexpected synthesis"))

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-06-25",
        run_synthesis=True,
        submit=True,
        remote_loader=lambda: (set(), None),
        submit_cycle=lambda **_kwargs: {"status": "submitted_to_researka", "submitted": 1, "published": 0},
        max_attempts=1,
    )

    assert ledger["topic_status"]["aaa_sparse_receipts"] == "preflight_blocked"
    assert "preflight_reseed_selected" not in ledger
    assert ledger["status"] == "no_unpublished_topic_available"


def test_fresh_lane_skips_recent_receipt_block_and_submits_ready_topic(
    tmp_path: Path, monkeypatch,
) -> None:
    _topic(tmp_path, "aaa_sparse_receipts", target_journal=True)
    _topic(tmp_path, "zzz_ready", target_journal=True)
    ledger_dir = tmp_path / "runs" / cycle.LEDGER_DIR
    cycle._record_blockers(
        ledger_dir,
        "2026-06-25",
        [{"topic": "aaa_sparse_receipts", "gate_status": "receipt_preflight_insufficient", "submitted": 0}],
    )
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_current_low_source_precision_topics", lambda topics: set())
    monkeypatch.setattr(cycle, "_quant_claim_source_precision", lambda topic, **_k: (True, "source_topic_precision_ok:10/10", []))
    monkeypatch.setattr(cycle, "_receipt_preflight", lambda topic, out_dir, **_k: {"passed": True})
    synthesized: list[str] = []

    def fake_synthesis(topic: str, out_dir: Path, **_kwargs: Any) -> int:
        synthesized.append(topic)
        out_dir.mkdir(parents=True)
        _write_json(out_dir / "final_status.json", {"submission_ready": True})
        (out_dir / "full_paper.md").write_text(_surface_passing_paper(), encoding="utf-8")
        return 0

    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-06-25",
        run_synthesis=True,
        submit=True,
        mode="fresh",
        remote_loader=lambda: (set(), None),
        submit_cycle=lambda **_kwargs: {"status": "submitted_to_researka", "submitted": 1, "published": 0},
        max_attempts=0,
    )

    assert synthesized == ["zzz_ready"]
    assert ledger["topic_status"]["aaa_sparse_receipts"] == "preflight_blocked"
    assert ledger["status"] == "submitted_to_researka"


def test_cycle_skips_backlog_repair_when_new_candidate_selectable(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "aaa_thin_topic", target_journal=True)
    _topic(tmp_path, "mmm_new_topic", corpus=False, target_journal=True)
    _prior_run(tmp_path, "aaa_thin_topic", receipts=6, tensions=0, primary=0)
    ledger_dir = tmp_path / "runs" / cycle.LEDGER_DIR
    cycle._record_blockers(
        ledger_dir,
        "2026-05-31",
        [{"topic": "aaa_thin_topic", "submit_status": "preflight_insufficient_corpus", "submitted": 0}],
    )
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_corpus_repair_limit", lambda: 1)
    monkeypatch.setattr(cycle, "_repair_topic_corpus", lambda topic, **_k: pytest.fail(f"unexpected repair: {topic}"))
    monkeypatch.setattr(cycle, "_quant_claim_source_precision", lambda topic, **_k: (True, "source_topic_precision_ok:10/10", []))
    monkeypatch.setattr(cycle, "_receipt_preflight", lambda topic, out_dir, **_k: {"passed": True})
    synthesized: list[str] = []

    def fake_synthesis(topic: str, out_dir: Path, **_kwargs: Any) -> int:
        synthesized.append(topic)
        out_dir.mkdir(parents=True)
        return 0

    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-05-31",
        run_synthesis=True,
        submit=True,
        remote_loader=lambda: (set(), None),
        ensure_corpus=lambda topic, **_k: {"status": "corpus_seeded", "n_quant_claims": cycle.PREFLIGHT_MIN_QUANT_CLAIMS},
        submit_cycle=lambda **_kwargs: {"status": "submitted_to_researka", "submitted": 1, "published": 0},
        max_attempts=1,
    )

    assert "corpus_repairs" not in ledger
    assert ledger["topic_status"]["aaa_thin_topic"] == "preflight_blocked"
    assert synthesized == ["mmm_new_topic"]
    assert ledger["status"] == "submitted_to_researka"


def test_cycle_defers_source_repair_for_new_frontier_topic(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "aaa_frontier_bad", corpus=False, target_journal=True)
    _topic(tmp_path, "zzz_frontier_good", corpus=False, target_journal=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_current_low_source_precision_topics", lambda _topics: set())
    monkeypatch.setattr(cycle, "_repair_low_source_precision_corpus", lambda topic, **_k: pytest.fail(f"unexpected repair: {topic}"))
    monkeypatch.setattr(cycle, "_receipt_preflight", lambda topic, out_dir, **_k: {"passed": True})

    def fake_precision(topic: str, **_kwargs: Any) -> tuple[bool, str, list[Path]]:
        if topic == "aaa_frontier_bad":
            return False, "source_topic_precision_low:0/12<0.50", [Path("bad.json")]
        return True, "source_topic_precision_ok:12/12", []

    synthesized: list[str] = []
    monkeypatch.setattr(cycle, "_quant_claim_source_precision", fake_precision)
    selections = iter([None, "aaa_frontier_bad", "zzz_frontier_good"])
    monkeypatch.setattr(cycle, "select_topic", lambda *_a, **_k: next(selections, None))

    def fake_synthesis(topic: str, out_dir: Path, **_kwargs: Any) -> int:
        synthesized.append(topic)
        out_dir.mkdir(parents=True)
        return 0

    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-05-31",
        run_synthesis=True,
        submit=True,
        remote_loader=lambda: (set(), None),
        ensure_corpus=lambda topic, **_k: {
            "status": "corpus_seeded",
            "n_quant_claims_before": 0,
            "n_quant_claims": cycle.SOURCE_PRECISION_REPAIR_PUBLISH_MIN_QUANT,
        },
        submit_cycle=lambda **_kwargs: {"status": "submitted_to_researka", "submitted": 1, "published": 0},
        max_attempts=2,
    )

    assert ledger["attempts"][0]["topic"] == "aaa_frontier_bad"
    assert ledger["attempts"][0]["gate_status"] == "source_topic_precision_low:0/12<0.50"
    assert synthesized == ["zzz_frontier_good"]
    assert ledger["status"] == "submitted_to_researka"


def test_cycle_prunes_seeded_frontier_overflow_before_synthesis(tmp_path: Path, monkeypatch) -> None:
    topic = "frontier_overflow"
    _topic(tmp_path, topic, corpus=False, target_journal=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_current_low_source_precision_topics", lambda _topics: set())
    monkeypatch.setattr(cycle, "_receipt_preflight", lambda _topic, _out_dir, **_k: {"passed": True})
    qdir = cycle.CORPORA / topic / "quant_claims"
    qdir.mkdir(parents=True)
    for i in range(cycle.SOURCE_PRECISION_REPAIR_PUBLISH_MIN_QUANT * 2):
        _write_json(qdir / f"claim_{i}.quant_claims.json", {"paper_id": f"claim_{i}"})

    misses = [
        qdir / f"claim_{i}.quant_claims.json"
        for i in range(cycle.SOURCE_PRECISION_REPAIR_PUBLISH_MIN_QUANT)
    ]
    monkeypatch.setattr(
        cycle,
        "_quant_claim_source_precision",
        lambda *_a, **_k: (
            False,
            (
                "source_topic_precision_low:"
                f"{cycle.SOURCE_PRECISION_REPAIR_PUBLISH_MIN_QUANT}/"
                f"{cycle.SOURCE_PRECISION_REPAIR_PUBLISH_MIN_QUANT * 2}<0.50"
            ),
            misses,
        ),
    )
    repaired: list[dict[str, Any]] = []

    def fake_repair(selected: str, **kwargs: Any) -> dict[str, Any]:
        repaired.append({"topic": selected, **kwargs})
        return {
            "status": "source_precision_repaired",
            "source_topic_precision_before": (
                "source_topic_precision_low:"
                f"{cycle.SOURCE_PRECISION_REPAIR_PUBLISH_MIN_QUANT}/"
                f"{cycle.SOURCE_PRECISION_REPAIR_PUBLISH_MIN_QUANT * 2}<0.50"
            ),
            "source_topic_precision_after": (
                "source_topic_precision_ok:"
                f"{cycle.SOURCE_PRECISION_REPAIR_PUBLISH_MIN_QUANT}/"
                f"{cycle.SOURCE_PRECISION_REPAIR_PUBLISH_MIN_QUANT}"
            ),
            "n_quant_claims": cycle.SOURCE_PRECISION_REPAIR_PUBLISH_MIN_QUANT,
            "reseed": kwargs.get("reseed"),
        }

    synthesized: list[str] = []

    def fake_synthesis(selected: str, out_dir: Path, **_kwargs: Any) -> int:
        synthesized.append(selected)
        out_dir.mkdir(parents=True)
        return 0

    monkeypatch.setattr(cycle, "_repair_low_source_precision_corpus", fake_repair)
    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-05-31",
        run_synthesis=True,
        submit=True,
        remote_loader=lambda: (set(), None),
        ensure_corpus=lambda _topic, **_k: {
            "status": "corpus_seeded",
            "n_quant_claims_before": 0,
            "n_quant_claims": 24,
        },
        submit_cycle=lambda **_kwargs: {"status": "submitted_to_researka", "submitted": 1, "published": 0},
        max_attempts=1,
    )

    assert repaired and repaired[0]["reseed"] is False
    assert synthesized == [topic]
    assert ledger["source_precision_repair"]["source_topic_precision_after"] == (
        "source_topic_precision_ok:"
        f"{cycle.SOURCE_PRECISION_REPAIR_PUBLISH_MIN_QUANT}/"
        f"{cycle.SOURCE_PRECISION_REPAIR_PUBLISH_MIN_QUANT}"
    )
    assert ledger["status"] == "submitted_to_researka"


def test_cycle_skips_receipt_preflight_repair_when_clean_topic_ready(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "aaa_sparse_receipts", target_journal=True)
    _topic(tmp_path, "zzz_solid_topic", target_journal=True)
    _prior_run(tmp_path, "aaa_sparse_receipts", receipts=5, tensions=2, primary=1)
    _prior_run(tmp_path, "zzz_solid_topic", receipts=18, tensions=2, primary=5)
    ledger_dir = tmp_path / "runs" / cycle.LEDGER_DIR
    cycle._record_blockers(
        ledger_dir,
        "2026-06-04",
        [{"topic": "aaa_sparse_receipts", "gate_status": "receipt_preflight_insufficient", "submitted": 0}],
    )
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_corpus_repair_limit", lambda: 1)
    monkeypatch.setattr(cycle, "_receipt_preflight", lambda topic, out_dir, **_k: {"passed": True, "n_receipts": 18, "min_receipts": 12})
    monkeypatch.setattr(cycle, "_quant_claim_source_precision", lambda topic, **_k: (True, "source_topic_precision_ok:10/10", []))
    monkeypatch.setattr(cycle, "_repair_topic_corpus", lambda topic, **_k: {
        "status": "corpus_repaired", "n_quant_claims": cycle.PREFLIGHT_MIN_QUANT_CLAIMS,
    })
    synthesized: list[str] = []

    def fake_synthesis(
        topic: str,
        out_dir: Path,
        *,
        dry_run: bool,
        timeout: int | None = None,
        revision_feedback: str | None = None,
        review_type_override: str | None = None,
    ) -> int:
        synthesized.append(topic)
        out_dir.mkdir(parents=True)
        return 0

    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-06-04",
        run_synthesis=True,
        submit=True,
        remote_loader=lambda: (set(), None),
        submit_cycle=lambda **_kwargs: {"status": "submitted_to_researka", "submitted": 1, "published": 0},
        max_attempts=1,
    )

    assert "corpus_repairs" not in ledger
    assert ledger["topic_status"]["aaa_sparse_receipts"] == "preflight_blocked"
    assert synthesized == ["zzz_solid_topic"]
    assert ledger["status"] == "submitted_to_researka"


def test_cycle_skips_source_precision_repair_when_clean_topic_ready(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "aaa_low_source", target_journal=True)
    _topic(tmp_path, "bbb_low_source", target_journal=True)
    _topic(tmp_path, "zzz_clean_topic", target_journal=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_corpus_repair_limit", lambda: 1)
    monkeypatch.setattr(cycle, "_unrepairable_source_precision_topics", lambda *_a, **_k: {
        "aaa_low_source",
        "bbb_low_source",
    })

    def fake_precision(topic: str, *, floor: float | None = None) -> tuple[bool, str, list[Path]]:
        if topic in {"aaa_low_source", "bbb_low_source"}:
            return False, "source_topic_precision_low:24/25<0.50", [Path(f"{topic}.json")]
        return True, "source_topic_precision_ok:4/4", []

    repairs: list[str] = []
    synthesized: list[str] = []
    monkeypatch.setattr(cycle, "_quant_claim_source_precision", fake_precision)
    monkeypatch.setattr(cycle, "_quant_claim_count", lambda _topic: cycle.SOURCE_PRECISION_REPAIR_PUBLISH_MIN_QUANT + 1)
    monkeypatch.setattr(cycle, "_quant_claim_count", lambda _topic: cycle.SOURCE_PRECISION_REPAIR_PUBLISH_MIN_QUANT + 1)

    def fake_repair(topic: str, **_kwargs: Any) -> dict[str, Any]:
        repairs.append(topic)
        return {
            "status": "source_precision_repaired",
            "source_topic_precision_after": "source_topic_precision_ok:24/24",
            "n_quant_claims": cycle.SOURCE_PRECISION_REPAIR_PUBLISH_MIN_QUANT,
        }

    def fake_synthesis(topic: str, out_dir: Path, **_kwargs: Any) -> int:
        synthesized.append(topic)
        out_dir.mkdir(parents=True)
        return 0

    monkeypatch.setattr(cycle, "_repair_low_source_precision_corpus", fake_repair)
    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)
    monkeypatch.setattr(cycle, "_receipt_preflight", lambda topic, out_dir, **_k: {"passed": True})

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-06-01",
        run_synthesis=True,
        submit=True,
        remote_loader=lambda: (set(), None),
        submit_cycle=lambda **_kwargs: {"status": "submitted_to_researka", "submitted": 1, "published": 0},
        max_attempts=1,
    )

    assert ledger["source_precision_backlog_topics"] == ["aaa_low_source", "bbb_low_source"]
    assert ledger["source_precision_backlog_count"] == 2
    assert repairs == []
    assert synthesized == ["zzz_clean_topic"]
    assert "corpus_repairs" not in ledger
    assert ledger["source_precision_auto_excluded_topics"] == ["aaa_low_source", "bbb_low_source"]
    assert ledger["status"] == "submitted_to_researka"


def test_cycle_repairs_source_precision_when_no_clean_topic_ready(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "aaa_low_source", target_journal=True)
    _topic(tmp_path, "bbb_low_source", target_journal=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_corpus_repair_limit", lambda: 1)

    def fake_precision(topic: str, *, floor: float | None = None) -> tuple[bool, str, list[Path]]:
        if topic in {"aaa_low_source", "bbb_low_source"}:
            return False, "source_topic_precision_low:1/4<0.50", [Path(f"{topic}.json")]
        return True, "source_topic_precision_ok:4/4", []

    repairs: list[str] = []
    synthesized: list[str] = []
    monkeypatch.setattr(cycle, "_quant_claim_source_precision", fake_precision)

    def fake_repair(topic: str, **_kwargs: Any) -> dict[str, Any]:
        repairs.append(topic)
        return {
            "status": "source_precision_repaired",
            "source_topic_precision_after": "source_topic_precision_ok:4/4",
            "n_quant_claims": cycle.SOURCE_PRECISION_REPAIR_PUBLISH_MIN_QUANT,
        }

    monkeypatch.setattr(cycle, "_repair_low_source_precision_corpus", fake_repair)

    def fake_synthesis(topic: str, out_dir: Path, **_kwargs: Any) -> int:
        synthesized.append(topic)
        out_dir.mkdir(parents=True)
        return 0

    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)
    monkeypatch.setattr(cycle, "_receipt_preflight", lambda topic, out_dir, **_k: {"passed": True})

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-06-01",
        run_synthesis=True,
        submit=True,
        remote_loader=lambda: (set(), None),
        submit_cycle=lambda **_kwargs: {"status": "submitted_to_researka", "submitted": 1, "published": 0},
        max_attempts=1,
    )

    assert repairs == ["aaa_low_source"]
    assert synthesized == ["aaa_low_source"]
    assert ledger["corpus_repairs"][0]["topic"] == "aaa_low_source"
    assert ledger["source_precision_auto_excluded_topics"] == ["bbb_low_source"]
    assert ledger["status"] == "submitted_to_researka"


def test_source_precision_repair_prefers_retained_claims_over_raw_file_count(
    tmp_path: Path, monkeypatch,
) -> None:
    _topic(tmp_path, "aaa_noisy_low_source", target_journal=True)
    _topic(tmp_path, "bbb_retained_low_source", target_journal=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_corpus_repair_limit", lambda: 1)
    monkeypatch.setattr(cycle, "_quant_claim_count", lambda topic: {
        "aaa_noisy_low_source": 120,
        "bbb_retained_low_source": 50,
    }[topic])

    def fake_precision(topic: str, *, floor: float | None = None) -> tuple[bool, str, list[Path]]:
        if topic == "aaa_noisy_low_source":
            return False, "source_topic_precision_low:0/120<0.50", [Path(f"noisy-{i}.json") for i in range(120)]
        return False, "source_topic_precision_low:30/50<0.75", [Path(f"miss-{i}.json") for i in range(20)]

    repairs: list[str] = []

    def fake_repair(topic: str, **_kwargs: Any) -> dict[str, Any]:
        repairs.append(topic)
        return {
            "status": "source_precision_repaired",
            "source_topic_precision_after": "source_topic_precision_ok:30/30",
            "n_quant_claims": cycle.SOURCE_PRECISION_REPAIR_PUBLISH_MIN_QUANT,
        }

    monkeypatch.setattr(cycle, "_quant_claim_source_precision", fake_precision)
    monkeypatch.setattr(cycle, "_repair_low_source_precision_corpus", fake_repair)
    monkeypatch.setattr(cycle, "_receipt_preflight", lambda topic, out_dir, **_k: {"passed": True})
    monkeypatch.setattr(cycle, "_run_synthesis", lambda topic, out_dir, **_k: out_dir.mkdir(parents=True) or 0)

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-06-26",
        run_synthesis=True,
        submit=True,
        mode="fresh",
        remote_loader=lambda: (set(), None),
        submit_cycle=lambda **_kwargs: {"status": "submitted_to_researka", "submitted": 1, "published": 0},
        max_attempts=1,
    )

    assert repairs == ["bbb_retained_low_source"]
    assert ledger["corpus_repairs"][0]["topic"] == "bbb_retained_low_source"
    assert ledger["status"] == "submitted_to_researka"


def test_source_precision_repair_scans_until_publishable(
    tmp_path: Path, monkeypatch,
) -> None:
    _topic(tmp_path, "aaa_underfloor_repair", target_journal=True)
    _topic(tmp_path, "bbb_publishable_repair", target_journal=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_corpus_repair_limit", lambda: 1)
    monkeypatch.setattr(cycle, "_quant_claim_count", lambda topic: {
        "aaa_underfloor_repair": 40,
        "bbb_publishable_repair": 38,
    }[topic])

    def fake_precision(topic: str, *, floor: float | None = None) -> tuple[bool, str, list[Path]]:
        if topic == "aaa_underfloor_repair":
            return False, "source_topic_precision_low:23/40<0.75", [Path(f"miss-{i}.json") for i in range(17)]
        return False, "source_topic_precision_low:22/38<0.75", [Path(f"miss-{i}.json") for i in range(16)]

    repairs: list[str] = []

    def fake_repair(topic: str, **_kwargs: Any) -> dict[str, Any]:
        repairs.append(topic)
        if topic == "aaa_underfloor_repair":
            return {
                "status": "source_precision_repaired",
                "source_topic_precision_after": "source_topic_precision_ok:22/22",
                "n_quant_claims": cycle.SOURCE_PRECISION_REPAIR_PUBLISH_MIN_QUANT - 2,
            }
        return {
            "status": "source_precision_repaired",
            "source_topic_precision_after": "source_topic_precision_ok:24/24",
            "n_quant_claims": cycle.SOURCE_PRECISION_REPAIR_PUBLISH_MIN_QUANT,
        }

    synthesized: list[str] = []
    monkeypatch.setattr(cycle, "_quant_claim_source_precision", fake_precision)
    monkeypatch.setattr(cycle, "_repair_low_source_precision_corpus", fake_repair)
    monkeypatch.setattr(cycle, "_receipt_preflight", lambda topic, out_dir, **_k: {"passed": True})
    def fake_synthesis(topic: str, out_dir: Path, **_kwargs: Any) -> int:
        synthesized.append(topic)
        out_dir.mkdir(parents=True)
        return 0

    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-06-26",
        run_synthesis=True,
        submit=True,
        mode="fresh",
        remote_loader=lambda: (set(), None),
        submit_cycle=lambda **_kwargs: {"status": "submitted_to_researka", "submitted": 1, "published": 0},
        max_attempts=1,
    )

    assert repairs == ["aaa_underfloor_repair", "bbb_publishable_repair"]
    assert synthesized == ["bbb_publishable_repair"]
    assert ledger["corpus_repairs"][0]["topic"] == "aaa_underfloor_repair"
    assert ledger["corpus_repairs"][1]["topic"] == "bbb_publishable_repair"
    assert ledger["status"] == "submitted_to_researka"


def test_cycle_skips_recent_source_precision_failure_before_repairing_next_topic(
    tmp_path: Path, monkeypatch,
) -> None:
    _topic(tmp_path, "aaa_recent_low_source", target_journal=True)
    _topic(tmp_path, "bbb_low_source", target_journal=True)
    ledger_dir = tmp_path / "runs" / cycle.LEDGER_DIR
    cycle._record_blockers(
        ledger_dir,
        "2026-06-01",
        [{"topic": "aaa_recent_low_source", "gate_status": "source_topic_precision_low:1/4<0.50", "submitted": 0}],
    )
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_corpus_repair_limit", lambda: 1)
    monkeypatch.setattr(cycle, "_quant_claim_source_precision", lambda topic, **_k: (
        False, "source_topic_precision_low:24/25<0.50", [Path(f"{topic}.json")],
    ))
    monkeypatch.setattr(cycle, "_quant_claim_count", lambda _topic: cycle.SOURCE_PRECISION_REPAIR_PUBLISH_MIN_QUANT + 1)
    repairs: list[str] = []

    def fake_repair(topic: str, **_kwargs: Any) -> dict[str, Any]:
        repairs.append(topic)
        return {
            "status": "source_precision_repaired",
            "source_topic_precision_after": "source_topic_precision_ok:24/24",
            "n_quant_claims": cycle.SOURCE_PRECISION_REPAIR_PUBLISH_MIN_QUANT,
        }

    monkeypatch.setattr(cycle, "_repair_low_source_precision_corpus", fake_repair)
    monkeypatch.setattr(cycle, "_run_synthesis", lambda topic, out_dir, **_k: out_dir.mkdir(parents=True) or 0)
    monkeypatch.setattr(cycle, "_receipt_preflight", lambda topic, out_dir, **_k: {"passed": True})

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-06-01",
        run_synthesis=True,
        submit=True,
        remote_loader=lambda: (set(), None),
        submit_cycle=lambda **_kwargs: {"status": "submitted_to_researka", "submitted": 1, "published": 0},
        max_attempts=1,
    )

    assert repairs == ["bbb_low_source"]
    assert ledger["source_precision_recent_blocked_topics"] == ["aaa_recent_low_source"]
    assert ledger["source_precision_auto_excluded_topics"] == ["aaa_recent_low_source"]
    assert ledger["status"] == "submitted_to_researka"


def test_fresh_cycle_selects_currently_repaired_topic_despite_recent_preflight_block(
    tmp_path: Path, monkeypatch,
) -> None:
    assert cycle.PREFLIGHT_MIN_QUANT_CLAIMS < cycle.SOURCE_PRECISION_REPAIR_PUBLISH_MIN_QUANT
    _topic(tmp_path, "aaa_repaired_source", target_journal=True)
    ledger_dir = tmp_path / "runs" / cycle.LEDGER_DIR
    _write_json(ledger_dir / "2026-06-27-fresh.json", {
        "started_at": dt.datetime.now(dt.UTC).isoformat(),
        "attempts": [{
            "topic": "aaa_repaired_source",
            "gate_status": "preflight_thin_quant_corpus",
            "submitted": 0,
        }],
    })
    cycle._record_blockers(ledger_dir, "2026-06-27", [{
        "topic": "aaa_repaired_source",
        "gate_status": "preflight_thin_quant_corpus",
        "submitted": 0,
    }])
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_current_low_source_precision_topics", lambda _topics: {"aaa_repaired_source"})
    monkeypatch.setattr(cycle, "_corpus_repair_limit", lambda: 1)
    monkeypatch.setattr(cycle, "_quant_claim_count", lambda _topic: cycle.PREFLIGHT_MIN_QUANT_CLAIMS)
    monkeypatch.setattr(cycle, "_quant_claim_source_precision", lambda *_a, **_k: (
        True, "source_topic_precision_ok:24/24", [],
    ))
    monkeypatch.setattr(cycle, "_repair_low_source_precision_corpus", lambda topic, **_k: {
        "status": "source_precision_repaired",
        "source_topic_precision_after": "source_topic_precision_ok:24/24",
        "n_quant_claims": cycle.PREFLIGHT_MIN_QUANT_CLAIMS,
    })
    monkeypatch.setattr(cycle, "_receipt_preflight", lambda topic, out_dir, **_k: {"passed": True})
    monkeypatch.setattr(cycle, "_refresh_topic_supply", lambda *_a, **_k: pytest.fail("unexpected refresh"))
    synthesized: list[str] = []

    def fake_synthesis(topic: str, out_dir: Path, **_kwargs: Any) -> int:
        synthesized.append(topic)
        out_dir.mkdir(parents=True)
        return 0

    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-06-28",
        run_synthesis=True,
        submit=True,
        mode="fresh",
        remote_loader=lambda: (set(), None),
        ensure_corpus=lambda topic, **_k: {
            "status": "corpus_ready",
            "n_quant_claims": cycle.PREFLIGHT_MIN_QUANT_CLAIMS,
        },
        submit_cycle=lambda **_kwargs: {"status": "submitted_to_researka", "submitted": 1, "published": 0},
        max_attempts=1,
    )

    assert synthesized == ["aaa_repaired_source"]
    assert ledger["corpus_repairs"][0]["topic"] == "aaa_repaired_source"
    assert ledger["status"] == "submitted_to_researka"


def test_cycle_auto_excludes_unrepaired_low_source_precision_topics(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "aaa_low_source", target_journal=True)
    _topic(tmp_path, "bbb_low_source", target_journal=True)
    _topic(tmp_path, "zzz_clean_topic", target_journal=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_corpus_repair_limit", lambda: 1)

    def fake_precision(topic: str, *, floor: float | None = None) -> tuple[bool, str, list[Path]]:
        if topic in {"aaa_low_source", "bbb_low_source"}:
            return False, "source_topic_precision_low:0/4<0.50", [Path(f"{topic}.json")]
        return True, "source_topic_precision_ok:4/4", []

    synthesized: list[str] = []
    monkeypatch.setattr(cycle, "_quant_claim_source_precision", fake_precision)
    monkeypatch.setattr(cycle, "_repair_low_source_precision_corpus", lambda topic, **_k: {
        "status": "source_precision_repair_incomplete",
        "source_topic_precision_after": "source_topic_precision_low:0/4<0.50",
        "n_quant_claims": cycle.PREFLIGHT_MIN_QUANT_CLAIMS,
    })

    def fake_synthesis(topic: str, out_dir: Path, **_kwargs: Any) -> int:
        synthesized.append(topic)
        out_dir.mkdir(parents=True)
        return 0

    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)
    monkeypatch.setattr(cycle, "_receipt_preflight", lambda topic, out_dir, **_k: {"passed": True})

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-06-01",
        run_synthesis=True,
        submit=True,
        remote_loader=lambda: (set(), None),
        submit_cycle=lambda **_kwargs: {"status": "submitted_to_researka", "submitted": 1, "published": 0},
        max_attempts=1,
    )

    assert ledger["source_precision_auto_excluded_topics"] == ["aaa_low_source", "bbb_low_source"]
    assert ledger["topic_status"]["aaa_low_source"] == "source_precision_blocked"
    assert synthesized == ["zzz_clean_topic"]
    assert ledger["status"] == "submitted_to_researka"


def test_fresh_cycle_repairs_source_precision_fallback_after_clean_topic_receipt_failure(
    tmp_path: Path, monkeypatch,
) -> None:
    _topic(tmp_path, "aaa_clean_sparse", target_journal=True)
    _topic(tmp_path, "bbb_low_source", target_journal=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_corpus_repair_limit", lambda: 1)
    monkeypatch.setattr(cycle, "_current_low_source_precision_topics", lambda _topics: {"bbb_low_source"})
    monkeypatch.setattr(cycle, "_quant_claim_count", lambda _topic: cycle.SOURCE_PRECISION_REPAIR_PUBLISH_MIN_QUANT)
    monkeypatch.setattr(cycle, "_quant_claim_source_precision", lambda *_a, **_k: (
        True, "source_topic_precision_ok:24/24", [],
    ))
    repairs: list[str] = []

    def fake_repair(topic: str, **_kwargs: Any) -> dict[str, Any]:
        repairs.append(topic)
        return {
            "status": "source_precision_repaired",
            "source_topic_precision_after": "source_topic_precision_ok:24/24",
            "n_quant_claims": cycle.SOURCE_PRECISION_REPAIR_PUBLISH_MIN_QUANT,
        }

    def fake_receipt_preflight(topic: str, out_dir: Path, **_k: Any) -> dict[str, Any]:
        if topic == "aaa_clean_sparse":
            return {
                "passed": False,
                "status": "receipt_preflight_insufficient",
                "n_receipts": 1,
                "min_receipts": cycle.PREFLIGHT_MIN_RECEIPTS,
            }
        return {
            "passed": True,
            "status": "receipt_preflight_ok",
            "n_receipts": cycle.PREFLIGHT_MIN_RECEIPTS,
            "min_receipts": cycle.PREFLIGHT_MIN_RECEIPTS,
        }

    synthesized: list[str] = []

    def fake_synthesis(topic: str, out_dir: Path, **_kwargs: Any) -> int:
        synthesized.append(topic)
        out_dir.mkdir(parents=True)
        return 0

    monkeypatch.setattr(cycle, "_repair_low_source_precision_corpus", fake_repair)
    monkeypatch.setattr(cycle, "_receipt_preflight", fake_receipt_preflight)
    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)
    monkeypatch.setattr(cycle, "_refresh_topic_supply", lambda *_a, **_k: pytest.fail("unexpected refresh"))

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-06-26",
        run_synthesis=True,
        submit=True,
        mode="fresh",
        remote_loader=lambda: (set(), None),
        submit_cycle=lambda **_kwargs: {"status": "submitted_to_researka", "submitted": 1, "published": 0},
        max_attempts=0,
    )

    assert repairs == ["bbb_low_source"]
    assert synthesized == ["bbb_low_source"]
    assert ledger["source_precision_fallback_selected"] == "bbb_low_source"
    assert "topic_supply_selected_after_refresh" not in ledger
    assert [attempt["topic"] for attempt in ledger["attempts"]] == ["aaa_clean_sparse", "bbb_low_source"]
    assert ledger["attempts"][0]["gate_status"] == "receipt_preflight_insufficient"
    assert ledger["status"] == "submitted_to_researka"


def test_cycle_auto_excludes_recent_unrepairable_zero_source_precision_topic(
    tmp_path: Path, monkeypatch,
) -> None:
    _topic(tmp_path, "aaa_bad_source", target_journal=True)
    _topic(tmp_path, "zzz_ready_topic", target_journal=True)
    ledger_dir = tmp_path / "runs" / cycle.LEDGER_DIR
    _write_json(ledger_dir / "2026-06-01-fresh.json", {
        "started_at": dt.datetime.now(dt.UTC).isoformat(),
        "attempts": [{
            "topic": "aaa_bad_source",
            "source_precision_repair": {
                "status": "source_precision_repair_incomplete",
                "n_quant_claims": 0,
            },
        }],
    })
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_quant_claim_source_precision", lambda *_a, **_k: (
        True, "source_topic_precision_unscored", [],
    ))
    monkeypatch.setattr(cycle, "_receipt_preflight", lambda topic, out_dir, **_k: {"passed": True})
    synthesized: list[str] = []

    def fake_synthesis(topic: str, out_dir: Path, **_kwargs: Any) -> int:
        synthesized.append(topic)
        out_dir.mkdir(parents=True)
        return 0

    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-06-02",
        run_synthesis=True,
        submit=True,
        mode="fresh",
        remote_loader=lambda: (set(), None),
        submit_cycle=lambda **_kwargs: {"status": "submitted_to_researka", "submitted": 1, "published": 0},
        max_attempts=1,
    )

    assert ledger["source_precision_unrepairable_topics"] == ["aaa_bad_source"]
    assert ledger["source_precision_auto_excluded_topics"] == ["aaa_bad_source"]
    assert ledger["topic_status"]["aaa_bad_source"] == "source_precision_blocked"
    assert synthesized == ["zzz_ready_topic"]
    assert ledger["status"] == "submitted_to_researka"


def test_revise_lane_marks_repeat_failing_revise_terminal(tmp_path: Path, monkeypatch) -> None:
    """A pending revise whose topic keeps failing the same deterministic gate is
    marked terminal (handled) instead of being re-synthesised every cycle."""
    _topic(tmp_path, "colchicine_inflammaging", target_journal=True)
    source = _prior_run(tmp_path, "colchicine_inflammaging", receipts=37, tensions=113, primary=1, level=5)
    (source / "full_paper.md").write_text("# Research Synthesis: Colchicine Inflammaging\n", encoding="utf-8")
    _write_json(tmp_path / "runs" / cycle.submit_bridge.LEDGER_DIR / "_submitted_fingerprints.json", [{
        "run": source.name, "topic": "colchicine_inflammaging",
        "fingerprint": cycle.submit_bridge._sha256(source / "full_paper.md"),
    }])
    # prime two prior deterministic-gate failures in the cumulative histogram
    ledger_dir = tmp_path / "runs" / cycle.LEDGER_DIR
    ledger_dir.mkdir(parents=True, exist_ok=True)
    now = dt.datetime.now(dt.UTC)
    _write_json(ledger_dir / cycle.BLOCKER_HISTOGRAM, {"repeats": {
        "colchicine_inflammaging\x1fretracted_source_cited":
            [(now - dt.timedelta(minutes=10)).isoformat(), now.isoformat()],
    }})
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_run_synthesis", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("repeat-failing revise must not re-synthesise")))
    request = {"artifactId": "colchicine-review", "title": "Research Synthesis: Colchicine Inflammaging",
               "feedback": "Please add a subgroup analysis for the 65+ cohort and report absolute risk reduction."}

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs", date="2026-05-29", run_synthesis=True, submit=True, mode="revise",
        remote_loader=lambda: (set(), None), revision_loader=lambda: ([request], None),
        submit_cycle=lambda **_kwargs: {"status": "submitted_to_researka", "submitted": 1, "published": 0},
    )

    assert ledger["status"] == "revise_terminal_surface_repeat"
    assert ledger["attempts"][0]["gate_status"] == "terminal_surface_repeat"
    assert (ledger_dir / cycle.HANDLED_REVISIONS).exists()


def test_revise_lane_allows_surface_repeat_after_new_ready_run(tmp_path: Path, monkeypatch) -> None:
    """A repaired same-topic run supersedes stale surface-repeat history."""
    topic = "colchicine_inflammaging"
    _topic(tmp_path, topic, target_journal=True)
    source = _prior_run(tmp_path, topic, receipts=37, tensions=113, primary=1, level=5)
    (source / "full_paper.md").write_text("# Research Synthesis: Colchicine Inflammaging\n", encoding="utf-8")
    _write_json(tmp_path / "runs" / cycle.submit_bridge.LEDGER_DIR / "_submitted_fingerprints.json", [{
        "run": source.name,
        "topic": topic,
        "fingerprint": cycle.submit_bridge._sha256(source / "full_paper.md"),
    }])
    ledger_dir = tmp_path / "runs" / cycle.LEDGER_DIR
    ledger_dir.mkdir(parents=True, exist_ok=True)
    now = dt.datetime.now(dt.UTC)
    _write_json(ledger_dir / cycle.BLOCKER_HISTOGRAM, {"repeats": {
        f"{topic}\x1fjournal_surface_not_passed": [
            (now - dt.timedelta(minutes=10)).isoformat(),
            (now - dt.timedelta(minutes=5)).isoformat(),
        ],
    }})
    ready = tmp_path / "runs" / f"synthesis-{topic}-v06-DAILY-2026-06-22T12-00-00Z"
    _write_json(ready / "final_status.json", {"submission_ready": True})
    _write_json(ready / "full_paper.journal_surface.json", {"passed": True, "issues": []})
    (ready / "full_paper.md").write_text("# Research Synthesis: Colchicine Inflammaging\n", encoding="utf-8")
    (tmp_path / "runs" / f"synthesis-{topic}-v06-DAILY-2026-06-22T13-00-00Z").mkdir()
    synthesized: list[str] = []

    def fake_synthesis(selected: str, out_dir: Path, **_kwargs: Any) -> int:
        synthesized.append(selected)
        out_dir.mkdir(parents=True, exist_ok=True)
        _write_json(out_dir / "final_status.json", {"submission_ready": True})
        _write_json(out_dir / "full_paper.journal_surface.json", {"passed": True, "issues": []})
        (out_dir / "full_paper.md").write_text(_surface_passing_paper(), encoding="utf-8")
        return 0

    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_ensure_topic_corpus", lambda *_a, **_k: {
        "status": "corpus_ready", "n_quant_claims": cycle.PREFLIGHT_MIN_QUANT_CLAIMS,
    })
    monkeypatch.setattr(cycle, "_preflight", lambda *_a, **_k: {
        "passed": True, "has_manifest": True, "n_receipts": 37, "n_tensions": 113, "n_primary_tier": 1,
    })
    monkeypatch.setattr(cycle, "_receipt_preflight", lambda *_a, **_k: {"passed": True})
    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)
    request = {
        "artifactId": "colchicine-review",
        "title": "Research Synthesis: Colchicine Inflammaging",
        "feedback": "Please add a subgroup analysis for the 65+ cohort and report absolute risk reduction.",
    }

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-05-29",
        run_synthesis=True,
        submit=True,
        mode="revise",
        remote_loader=lambda: (set(), None),
        revision_loader=lambda: ([request], None),
        submit_cycle=lambda **_kwargs: {"status": "submitted_to_researka", "submitted": 1, "published": 0},
    )

    assert synthesized == [topic]
    assert ledger["status"] == "submitted_to_researka"
    assert ledger["attempts"][0]["gate_status"] == "submitted_to_researka"


def test_revise_source_precision_repair_clears_recent_failure_cooldown(tmp_path: Path, monkeypatch) -> None:
    topic = "cardiovascular_subgroups"
    _topic(tmp_path, topic, target_journal=False)
    source = _prior_run(tmp_path, topic, receipts=12, tensions=5, primary=2, level=5)
    paper = source / "full_paper.md"
    paper.write_text("# Research Synthesis: Cardiovascular Subgroups\n", encoding="utf-8")
    qdir = tmp_path / "docs" / "quality-reference" / topic / "quant_claims"
    for idx in range(5):
        (qdir / f"r{idx}.quant_claims.json").unlink()
    _write_json(tmp_path / "runs" / cycle.submit_bridge.LEDGER_DIR / "_submitted_fingerprints.json", [{
        "run": source.name,
        "topic": topic,
        "fingerprint": cycle.submit_bridge._sha256(paper),
    }])
    ledger_dir = tmp_path / "runs" / cycle.LEDGER_DIR
    cycle._record_blockers(
        ledger_dir,
        "2026-06-25",
        [{"topic": topic, "submit_status": "preflight_insufficient_corpus", "submitted": 0}],
    )
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_current_low_source_precision_topics", lambda _topics: set())
    monkeypatch.setattr(cycle, "_quant_claim_source_precision", lambda *_a, **_k: (
        False, "source_topic_precision_low:0/12<0.50", [Path("bad.json")]
    ))
    monkeypatch.setattr(cycle, "_repair_low_source_precision_corpus", lambda *_a, **_k: {
        "status": "source_precision_repaired",
        "source_topic_precision_after": "source_topic_precision_scoped_floor:60>=10",
        "n_quant_claims": 139,
    })
    monkeypatch.setattr(cycle, "_ensure_topic_corpus", lambda *_a, **_k: {
        "status": "corpus_ready",
        "n_quant_claims": 139,
    })
    monkeypatch.setattr(cycle, "_receipt_preflight", lambda *_a, **_k: {"passed": True})
    synthesized: list[str] = []

    def fake_synthesis(selected: str, out_dir: Path, **_kwargs: Any) -> int:
        synthesized.append(selected)
        out_dir.mkdir(parents=True)
        _write_json(out_dir / "final_status.json", {"submission_ready": True})
        _write_json(out_dir / "full_paper.journal_surface.json", {"passed": True, "issues": []})
        (out_dir / "full_paper.md").write_text(_surface_passing_paper(), encoding="utf-8")
        return 0

    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)
    request = {
        "artifactId": "cardio-review",
        "title": "Research Synthesis: Cardiovascular Subgroups",
        "feedback": "Revise the source bundle and remove off-topic subgroup records.",
    }

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs",
        date="2026-06-25",
        run_synthesis=True,
        submit=True,
        mode="revise",
        remote_loader=lambda: (set(), None),
        revision_loader=lambda: ([request], None),
        submit_cycle=lambda **_kwargs: {"status": "submitted_to_researka", "submitted": 1, "published": 0},
    )

    assert synthesized == [topic]
    assert ledger["status"] == "submitted_to_researka"
    assert ledger["attempts"][0]["gate_status"] == "submitted_to_researka"


def test_revise_lane_marks_unrepairable_source_precision_terminal(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "digital_frailty_index", target_journal=True)
    source = _prior_run(tmp_path, "digital_frailty_index", receipts=37, tensions=113, primary=1, level=5)
    (source / "full_paper.md").write_text("# Research Synthesis: Digital Frailty Index\n", encoding="utf-8")
    _write_json(tmp_path / "runs" / cycle.submit_bridge.LEDGER_DIR / "_submitted_fingerprints.json", [{
        "run": source.name, "topic": "digital_frailty_index",
        "fingerprint": cycle.submit_bridge._sha256(source / "full_paper.md"),
    }])
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_terminal_topics", lambda *_a, **_k: set())
    monkeypatch.setattr(cycle, "_quant_claim_source_precision", lambda *_a, **_k: (False, "source_topic_precision_low:0/107<0.50", [Path("bad.json")]))
    monkeypatch.setattr(cycle, "_repair_low_source_precision_corpus", lambda *_a, **_k: {
        "status": "source_precision_repair_incomplete",
        "source_topic_precision_before": "source_topic_precision_low:0/107<0.50",
        "source_topic_precision_after": "source_topic_precision_unscored",
        "n_quant_claims": 0,
    })
    monkeypatch.setattr(cycle, "_run_synthesis", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("unrepairable source revise must not re-synthesise")))
    request = {"artifactId": "digital-frailty-review", "title": "Research Synthesis: Digital Frailty Index",
               "feedback": "The source bundle includes off-topic records; revise with topic-specific sources."}

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs", date="2026-06-02", run_synthesis=True, submit=True, mode="revise",
        remote_loader=lambda: (set(), None), revision_loader=lambda: ([request], None),
        submit_cycle=lambda **_kwargs: {"status": "submitted_to_researka", "submitted": 1, "published": 0},
    )

    assert ledger["status"] == "revise_terminal_source_precision_repair_incomplete"
    assert ledger["attempts"][0]["gate_status"] == "terminal_source_precision_repair_incomplete"
    handled = json.loads((tmp_path / "runs" / cycle.LEDGER_DIR / cycle.HANDLED_REVISIONS).read_text(encoding="utf-8"))
    assert handled["handled"][0]["status"] == "terminal_source_precision_repair_incomplete"


def test_revision_source_precision_request_matches_direct_source_wording() -> None:
    feedback = (
        "Clarify which of the 52 sources directly address a composite digital "
        "frailty index versus general digital biomarker research, and bound the "
        "synthesis claims accordingly."
    )

    assert cycle._revision_requests_source_precision(feedback)


def test_revision_source_precision_request_matches_remove_or_reclassify_wording() -> None:
    feedback = (
        "Verify that all 50 bundle sources actually address melatonin and aging; "
        "remove or reclassify sources whose excerpts clearly address unrelated topics."
    )

    assert cycle._revision_requests_source_precision(feedback)


def test_revise_lane_does_not_reseed_recent_unrepairable_source_precision(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "digital_frailty_index", target_journal=True)
    source = _prior_run(tmp_path, "digital_frailty_index", receipts=37, tensions=113, primary=1, level=5)
    (source / "full_paper.md").write_text("# Research Synthesis: Digital Frailty Index\n", encoding="utf-8")
    _write_json(tmp_path / "runs" / cycle.submit_bridge.LEDGER_DIR / "_submitted_fingerprints.json", [{
        "run": source.name, "topic": "digital_frailty_index",
        "fingerprint": cycle.submit_bridge._sha256(source / "full_paper.md"),
    }])
    ledger_dir = tmp_path / "runs" / cycle.LEDGER_DIR
    _write_json(ledger_dir / "2026-06-01-revise.json", {
        "started_at": _recent_start(),
        "attempts": [{
            "topic": "digital_frailty_index",
            "source_precision_repair": {
                "status": "source_precision_repair_incomplete",
                "n_quant_claims": 0,
            },
        }],
    })
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "_terminal_topics", lambda *_a, **_k: set())
    request = {"artifactId": "digital-frailty-review", "title": "Research Synthesis: Digital Frailty Index",
               "feedback": "The source bundle includes off-topic records; revise with topic-specific sources."}

    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs", date="2026-06-02", run_synthesis=True, submit=True, mode="revise",
        remote_loader=lambda: (set(), None), revision_loader=lambda: ([request], None),
        submit_cycle=lambda **_kwargs: {"status": "submitted_to_researka", "submitted": 1, "published": 0},
        ensure_corpus=lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("known-unrepairable revise must not reseed")),
    )

    assert ledger["status"] == "revise_terminal_source_precision_repair_incomplete"
    assert ledger["attempts"][0]["gate_status"] == "terminal_source_precision_repair_incomplete"


def test_topic_status_map_consolidates_queue_state(tmp_path: Path) -> None:
    """The derived queue view classifies every topic by its strongest signal:
    surface-repeat > preflight-blocked > terminal > submitted > ready."""
    status = cycle._topic_status_map(
        ["epigenetic_clocks", "egcg", "colchicine", "rapamycin", "egcg_dup", "thin_topic"],
        terminal={"egcg", "egcg_dup"},
        surface_repeat={"epigenetic_clocks", "egcg_dup"},  # surface-repeat wins over terminal
        preflight_blocked={"thin_topic"},
        submitted={"colchicine"},
    )
    assert status == {
        "colchicine": "submitted",
        "egcg": "terminal",
        "egcg_dup": "terminal_surface_repeat",
        "epigenetic_clocks": "terminal_surface_repeat",
        "rapamycin": "ready",
        "thin_topic": "preflight_blocked",
    }


# --- Entity-floor fallback for compound topics (corpus dilution fix) -------

def _entity_floor_corpus(tmp_path, monkeypatch, *, n_on_entity, n_off_entity,
                         entity_terms=("zzdrug",), scope_in_core=True):
    topic = "zzdrug_zzmodifier_effects"  # tokens -> entity zzdrug + modifier zzmodifier
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    qdir = cycle.CORPORA / topic / "quant_claims"
    qdir.mkdir(parents=True)
    # On-entity files name the entity in the title; scope_in_core controls
    # whether their claim text also evidences the modifier (zzmodifier).
    sentence = "zzdrug improved zzmodifier outcome" if scope_in_core else "zzdrug improved an outcome"
    for i in range(n_on_entity):
        _write_json(qdir / f"zzdrug_study_{i}.quant_claims.json",
                    {"paper_id": f"zzdrug pivotal study {i}", "claims": [{"sentence": f"{sentence} {i}"}]})
    for i in range(n_off_entity):
        _write_json(qdir / f"offtopic_{i}.quant_claims.json",
                    {"paper_id": f"unrelated topic review {i}"})
    monkeypatch.setattr(cycle, "_entity_topic_terms", lambda _t: entity_terms)
    return topic


def test_entity_floor_passes_when_drift_zero_but_enough_scoped_entity(tmp_path, monkeypatch) -> None:
    # Drift matcher scores 0/17 (no source title has the literal modifier), but
    # >=10 name the entity AND evidence the modifier in claim text -> scoped
    # floor passes and quarantines only the off-entity remainder.
    topic = _entity_floor_corpus(tmp_path, monkeypatch, n_on_entity=12, n_off_entity=5)
    ok, status, misses = cycle._quant_claim_source_precision(topic)
    assert ok is True
    assert status.startswith("source_topic_precision_scoped_floor:12>=")
    assert len(misses) == 5 and all("offtopic" in m.name for m in misses)


def test_scoped_floor_rejects_generic_entity_without_topic_scope(tmp_path, monkeypatch) -> None:
    # Codex adversarial review (2026-06-13): >=10 papers naming the entity but
    # with NO topic-scope modifier in their claim text is a generic entity
    # corpus, not the compound topic -> must stay blocked.
    topic = _entity_floor_corpus(tmp_path, monkeypatch, n_on_entity=12, n_off_entity=5,
                                 scope_in_core=False)
    ok, status, _m = cycle._quant_claim_source_precision(topic)
    assert ok is False and status.startswith("source_topic_precision_low:")


def test_entity_floor_rejects_below_minimum(tmp_path, monkeypatch) -> None:
    topic = _entity_floor_corpus(tmp_path, monkeypatch, n_on_entity=9, n_off_entity=5)
    ok, status, _m = cycle._quant_claim_source_precision(topic)
    assert ok is False and status.startswith("source_topic_precision_low:")


def test_entity_floor_rejects_empty_core(tmp_path, monkeypatch) -> None:
    # Entity terms exist but no source names the entity -> empty core -> fail
    # (a generic same-field bundle cannot pass; not a ratio relaxation).
    topic = _entity_floor_corpus(tmp_path, monkeypatch, n_on_entity=0, n_off_entity=14)
    ok, status, _m = cycle._quant_claim_source_precision(topic)
    assert ok is False and status.startswith("source_topic_precision_low:")


def test_entity_floor_does_not_fire_without_pack_entity(tmp_path, monkeypatch) -> None:
    # Field-named / no-db-pack topic -> entity_terms=() -> branch never fires,
    # broad-field rejection preserved (defends the metabolomic_age_clocks class).
    topic = _entity_floor_corpus(tmp_path, monkeypatch, n_on_entity=12, n_off_entity=5,
                                 entity_terms=())
    ok, status, _m = cycle._quant_claim_source_precision(topic)
    assert ok is False and status.startswith("source_topic_precision_low:")


def test_entity_topic_terms_drops_bare_modifier_keeps_synonyms(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    d = cycle.TOPIC_PACKS_DB / "zzdrug_zzfield_effects"
    d.mkdir(parents=True)
    _write_json(d / "latest.json", {"pack_data": {"retrieval": {"topic_terms": [
        "zzdrug zzfield effects", "zzdrug", "zzfield", "zzdrug analogue",
    ]}}})
    out = cycle._entity_topic_terms("zzdrug_zzfield_effects")
    assert "zzdrug" in out                       # entity kept
    assert "zzdrug analogue" in out              # multi-word synonym kept
    assert "zzfield" not in out                  # bare slug modifier dropped
    assert "zzdrug zzfield effects" not in out   # bare slug phrase dropped
