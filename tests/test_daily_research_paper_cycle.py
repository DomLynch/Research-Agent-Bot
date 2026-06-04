from __future__ import annotations

import datetime as dt
import json
import sys
import urllib.request

import pytest
from pathlib import Path
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


def test_select_topic_prefers_no_recent_failure_when_available(tmp_path: Path) -> None:
    ledger_dir = tmp_path / cycle.LEDGER_DIR
    cycle._record_blockers(
        ledger_dir,
        "2026-06-02",
        [{"topic": "aaa_recent_failure", "gate_status": "receipt_preflight_insufficient", "submitted": 0}],
    )

    selected = cycle.select_topic(["aaa_recent_failure", "zzz_clean"], ledger_dir)

    assert selected == "zzz_clean"


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
    _topic(tmp_path, "creatine")
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


def test_cycle_runs_synthesis_then_delegates_to_submit_bridge(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "creatine")
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


def test_cycle_seeds_missing_quant_claim_corpus_before_synthesis(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "new_topic", corpus=False, target_journal=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_receipt_preflight", lambda topic, out_dir, **_k: {"passed": True})
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
            "considered": [{"run": runs[-1], "status": "source_topic_precision_low:1/4<0.35"}],
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
    assert ledger["no_submission_reason"] == "source_topic_precision_low:1/4<0.35"
    assert ledger["attempts"][0]["gate_status"] == "source_topic_precision_low:1/4<0.35"


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


def _run_coverage_cycle(tmp_path: Path, monkeypatch, *, unmet, submit_cycle, max_revise_attempts=3, paper_md: str | None = None):
    feedback_seen: list[str | None] = []
    monkeypatch.setattr(cycle, "_run_synthesis", _coverage_fake_synthesis(feedback_seen, paper_md))
    monkeypatch.setattr(cycle, "_unmet_revision_asks", lambda out_dir, fb: list(unmet))
    ledger = cycle.run_cycle(
        runs_root=tmp_path / "runs", date="2026-05-28", run_synthesis=True, submit=True,
        remote_loader=lambda: (set(), None), revision_loader=_aspirin_revise_loader,
        submit_cycle=submit_cycle, max_revise_attempts=max_revise_attempts)
    return ledger, feedback_seen


def test_coverage_all_asks_met_allows_submit(tmp_path: Path, monkeypatch) -> None:
    _seed_delayed_revise(tmp_path, monkeypatch)
    ledger, _ = _run_coverage_cycle(
        tmp_path, monkeypatch, unmet=[],
        submit_cycle=lambda **_k: {"status": "submitted_to_researka", "submitted": 1, "published": 0})
    assert ledger["attempts"][0]["submitted"] == 1                    # all asks met -> submitted
    assert "unmet_revision_asks" not in ledger["attempts"][0]


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
    assert int(ledger.get("submitted") or 0) == 0


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
            {"title": "Trial A", "excerpt": "Melatonin changed a measured endpoint in randomized adults."},
            {"title": "Trial B", "excerpt": "Melatonin was tested in patients with inflammatory biomarkers."},
            {"title": "Trial C", "excerpt": "A clinical trial measured melatonin effects on sleep and biomarkers."},
            {"title": "Review D", "excerpt": "Melatonin review evidence summarized human trial outcomes."},
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
            {"title": "Trial A", "excerpt": "Melatonin changed a measured endpoint in randomized adults."},
            {"title": "Trial B", "excerpt": "Melatonin was tested in patients with inflammatory biomarkers."},
            {"title": "Trial C", "excerpt": "A clinical trial measured melatonin effects on sleep and biomarkers."},
            {"title": "Review D", "excerpt": "Melatonin review evidence summarized human trial outcomes."},
            {"title": "Context E", "excerpt": "Contextual adjacent evidence: a broader clinical cohort measured cardiovascular endpoints."},
        ],
    })

    assert cycle._payload_revision_ask_satisfied(
        out_dir,
        "Remove or reclassify sources whose excerpts clearly address unrelated topics; if contextual adjacent, label explicitly in bundle.",
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


def test_terminal_receipt_preflight_handled_row_bypasses_round_cap(tmp_path: Path) -> None:
    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    marker = cycle.submit_bridge._title_marker("Research Synthesis: HRV Autonomic Aging — full paper")
    _write_json(ledger_dir / cycle.HANDLED_REVISIONS, {"handled": [{
        "key": marker,
        "title": "Research Synthesis: HRV Autonomic Aging — full paper",
        "status": "terminal_receipt_preflight_insufficient",
    }]})

    assert marker in cycle._handled_revision_ids(ledger_dir)


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
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
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
    assert "recent_failed_attempts=1" in preflight["reasons"][0]


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
    _topic(tmp_path, "creatine")
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
    _topic(tmp_path, "aaa_terminal")
    _topic(tmp_path, "zzz_fresh")
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
        f"ergothioneine{s}journal_surface_not_passed": [recent],                # single -> no
        f"creatine{s}cycle_budget_exhausted": [older, recent],                  # transient code -> no
        f"glynac{s}final_status_not_ready": [older, recent],                    # readiness refreshable -> no
        f"rapamycin{s}journal_surface_not_passed": [stale, stale],              # out of window -> no
    }})

    assert cycle._surface_repeat_topics(ledger_dir, now=now) == {"epigenetic_clocks", "coenzyme_q10_ubiquinol"}


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
        ("epigenome_editing_longevity", "source_topic_precision_low:1/4<0.35"),
        ("gdf11", "abstract_overclaim"),
    ]:
        cycle._record_blockers(ledger_dir, "2026-05-31", [{"topic": topic, "gate_status": status, "submitted": 0}])

    assert cycle._corpus_repair_topics(ledger_dir) == {
        "epigenetic_clocks",
        "coenzyme_q10_ubiquinol",
        "epigenome_editing_longevity",
    }
    assert cycle._source_precision_repair_topics(ledger_dir) == {"epigenome_editing_longevity"}


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
                "considered": [{"run": runs[-1], "status": "source_topic_precision_low:1/4<0.35"}],
            }
        return {"status": "submitted_to_researka", "submitted": 1, "published": 0}

    monkeypatch.setattr(cycle, "_run_synthesis", fake_synthesis)
    monkeypatch.setattr(cycle, "_repair_low_source_precision_corpus", lambda topic, **_k: {
        "status": "source_precision_repaired",
        "source_topic_precision_after": "source_topic_precision_ok:12/12",
        "n_quant_claims": cycle.PREFLIGHT_MIN_QUANT_CLAIMS,
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


def test_cycle_repairs_low_precision_corpus_at_publish_floor_before_synthesis(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "epigenome_editing_longevity", corpus=False, target_journal=True)
    monkeypatch.setattr(cycle, "TOPIC_PACKS", tmp_path / "topic_packs")
    monkeypatch.setattr(cycle, "TOPIC_PACKS_DB", tmp_path / "topic_packs_db")
    monkeypatch.setattr(cycle, "CORPORA", tmp_path / "docs" / "quality-reference")
    monkeypatch.setattr(cycle, "_receipt_preflight", lambda topic, out_dir, **_k: {"passed": True})
    qdir = cycle.CORPORA / "epigenome_editing_longevity" / "quant_claims"
    qdir.mkdir(parents=True)
    for i in range(4):
        _write_json(qdir / f"epigenome_editing_{i}.quant_claims.json", {"paper_id": f"epigenome_editing_{i}"})
    for i in range(15):
        _write_json(qdir / f"supercapacitor_{i}.quant_claims.json", {"paper_id": f"supercapacitor_{i}"})
    synthesized: list[str] = []

    monkeypatch.setattr(cycle, "_repair_low_source_precision_corpus", lambda topic, **_k: {
        "status": "source_precision_repaired",
        "source_topic_precision_before": "source_topic_precision_low:4/19<0.50",
        "source_topic_precision_after": "source_topic_precision_ok:19/19",
        "n_quant_claims": 19,
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
    assert ledger["corpus_repairs"][0]["source_topic_precision_before"] == "source_topic_precision_low:4/19<0.50"
    assert ledger["status"] == "submitted_to_researka"


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
    ) -> dict[str, Any]:
        repair = {
            "topic": topic,
            "dry_run": dry_run,
            "timeout": timeout,
            "seed_limit": seed_limit,
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
        {"topic": "urolithin_a", "dry_run": False, "timeout": 99, "seed_limit": cycle.AUTO_SEED_LIMIT * 2, "status": "corpus_repaired"},
        {"topic": "urolithin_a", "dry_run": False, "timeout": 99, "seed_limit": cycle.AUTO_SEED_LIMIT * 3, "status": "corpus_repaired"},
    ]
    assert result["repairs"] == repairs


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


def test_revise_lane_terminalizes_sparse_receipt_preflight(tmp_path: Path, monkeypatch) -> None:
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
    monkeypatch.setattr(cycle, "_receipt_preflight", lambda topic, out_dir, **_k: {
        "passed": False,
        "status": "receipt_preflight_insufficient",
        "n_receipts": 2,
        "min_receipts": 12,
    })
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
    handled = json.loads((tmp_path / "runs" / cycle.LEDGER_DIR / cycle.HANDLED_REVISIONS).read_text(encoding="utf-8"))
    assert handled["handled"][0]["status"] == "terminal_receipt_preflight_insufficient"


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

    assert repaired == [{"topic": "hydrogen_water", "dry_run": False, "timeout": None, "force": True}]
    assert synthesized == ["hydrogen_water"]
    assert ledger["source_precision_repair"]["source_topic_precision_after"] == "source_topic_precision_ok:24/24"
    assert ledger["status"] == "submitted_to_researka"


def test_cycle_repairs_preflight_blocked_topic_then_retries_once(tmp_path: Path, monkeypatch) -> None:
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

    assert ledger["corpus_repairs"][0]["topic"] == "aaa_thin_topic"
    assert ledger["topic_status"]["aaa_thin_topic"] == "ready"
    assert topics == ["aaa_thin_topic"]
    assert ledger["status"] == "submitted_to_researka"


def test_cycle_does_not_retry_receipt_preflight_topic_after_quant_repair(tmp_path: Path, monkeypatch) -> None:
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

    assert ledger["corpus_repairs"][0]["topic"] == "aaa_sparse_receipts"
    assert ledger["topic_status"]["aaa_sparse_receipts"] == "preflight_blocked"
    assert synthesized == ["zzz_solid_topic"]
    assert ledger["status"] == "submitted_to_researka"


def test_cycle_records_backlog_and_repairs_selected_low_source_precision(tmp_path: Path, monkeypatch) -> None:
    _topic(tmp_path, "aaa_low_source", target_journal=True)
    _topic(tmp_path, "bbb_low_source", target_journal=True)
    _topic(tmp_path, "zzz_clean_topic", target_journal=True)
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
            "n_quant_claims": cycle.PREFLIGHT_MIN_QUANT_CLAIMS,
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
    assert repairs == ["aaa_low_source"]
    assert synthesized == ["aaa_low_source"]
    assert ledger["corpus_repairs"][0]["topic"] == "aaa_low_source"
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
