from __future__ import annotations

import datetime as dt
from dataclasses import replace
from pathlib import Path

import pytest

from agent.publishing.candidate_prepare import (
    candidate_binding,
    buffer_status,
    prepared_candidate_rows,
)
from agent.publishing.event_log import conversion_funnel, record_daily_throughput
from agent.publishing.io import (
    AtomicJsonState,
    CorruptJsonState,
    JsonStateStatus,
    update_json_list,
    write_json,
)
from agent.publishing.policy import (
    CandidateEvidence,
    CandidateState,
    CandidateThresholds,
    PublicationSurface,
    decide_candidate,
    decision_from_status,
)
from agent.publishing.topic_supply import generated_pack_records


THRESHOLDS = CandidateThresholds(
    min_quant_claims=10,
    min_receipts=12,
    min_primary_tier=3,
    min_direct_receipts=4,
)


def test_candidate_policy_is_full_only_and_typed() -> None:
    evidence = CandidateEvidence(
        n_quant_claims=20,
        n_receipts=30,
        n_primary_tier=8,
        n_direct_receipts=6,
    )

    full = decide_candidate(
        "full",
        review_type="systematic_review",
        evidence=evidence,
        thresholds=THRESHOLDS,
    )
    compact = decide_candidate(
        "compact",
        review_type="evidence_brief",
        evidence=evidence,
        thresholds=THRESHOLDS,
    )
    invalid = decide_candidate(
        "invalid",
        review_type="research_synthesis",
        evidence=evidence,
        thresholds=THRESHOLDS,
    )

    assert full.publishable is False
    assert full.receipt_ready is True
    assert full.ready_for_synthesis is True
    assert full.state is CandidateState.RECEIPT_READY
    assert full.state.value == "receipt_ready"
    assert full.surface is PublicationSurface.RESEARCH_SYNTHESIS
    assert full.next_action == "synthesize"
    assert compact.publishable is False
    assert compact.state is CandidateState.INTERNAL_ALPHA
    assert compact.blocker_code == "public_research_surface_compact_review"
    assert invalid.state is CandidateState.INTERNAL_ALPHA


def test_candidate_policy_reports_one_stable_corpus_blocker() -> None:
    decision = decide_candidate(
        "thin",
        review_type=None,
        evidence=CandidateEvidence(
            n_quant_claims=10,
            n_receipts=12,
            n_primary_tier=3,
            n_direct_receipts=2,
        ),
        thresholds=THRESHOLDS,
    )

    assert decision.state is CandidateState.NEEDS_CORPUS
    assert decision.blocker_code == "direct_receipts_below_floor"
    assert decision.retryable is True
    assert decision.next_action == "repair_corpus"


def test_status_policy_distinguishes_pending_revision_and_terminal() -> None:
    pending = decision_from_status(
        "submitted",
        review_type="systematic_review",
        status="submitted_to_researka",
    )
    revision = decision_from_status(
        "revise",
        review_type="systematic_review",
        status="revision_coverage_unmet",
    )
    terminal = decision_from_status(
        "duplicate",
        review_type="systematic_review",
        status="duplicate_remote_publication",
    )
    published = decision_from_status(
        "published",
        review_type="systematic_review",
        status="published",
    )

    assert pending.state is CandidateState.SUBMITTED_PENDING
    assert revision.state is CandidateState.NEEDS_REVISION
    assert terminal.state is CandidateState.TERMINAL
    assert terminal.retryable is False
    assert published.state is CandidateState.TERMINAL
    assert published.next_action == "none"


def test_compact_published_status_remains_terminal() -> None:
    decision = decision_from_status(
        "published-brief",
        review_type="evidence_brief",
        status="published",
    )

    assert decision.state is CandidateState.TERMINAL
    assert decision.retryable is False
    assert decision.next_action == "none"


def test_status_policy_separates_operational_failure_from_revision() -> None:
    decision = decision_from_status(
        "network",
        review_type="systematic_review",
        status="submission_failed",
    )

    assert decision.state is CandidateState.OPERATIONAL_ERROR
    assert decision.retryable is True
    assert decision.next_action == "retry_operation"


def test_prepared_rows_use_the_same_candidate_policy() -> None:
    now = dt.datetime(2026, 7, 24, tzinfo=dt.UTC)
    precision = "source_topic_precision_ok:10/10"
    bindings = {
        topic: candidate_binding(
            topic,
            code_sha="a" * 40,
            corpus_hash="b" * 64,
            receipt_set_hash="c" * 64,
            review_type="systematic_review",
            thresholds=THRESHOLDS,
        )
        for topic in ("ready", "thin")
    }
    report = {
        "thresholds": THRESHOLDS.as_dict(),
        "attempts": [
            {
                "topic": "ready",
                "state": "receipt_ready",
                **bindings["ready"].as_dict(),
                "attempted_at": now.isoformat(),
                "quant_claims": 10,
                "source_topic_precision_after": precision,
                "receipt_preflight": {
                    "passed": True,
                    "n_receipts": 12,
                    "n_primary_tier": 3,
                    "n_direct_receipts": 4,
                },
            },
            {
                "topic": "thin",
                "state": "receipt_ready",
                **bindings["thin"].as_dict(),
                "attempted_at": now.isoformat(),
                "quant_claims": 10,
                "source_topic_precision_after": precision,
                "receipt_preflight": {
                    "passed": True,
                    "n_receipts": 12,
                    "n_primary_tier": 3,
                    "n_direct_receipts": 2,
                },
            },
        ],
    }

    rows = prepared_candidate_rows(
        report,
        thresholds=THRESHOLDS,
        now=now,
        max_age_hours=24,
        precision_floor=0.5,
        current_bindings={
            **bindings,
            "ready": replace(bindings["ready"], code_sha="d" * 40),
        },
    )

    assert set(rows) == {"ready"}
    assert rows["ready"]["state"] == "receipt_ready"
    assert rows["ready"]["candidate_id"] == bindings["ready"].candidate_id
    assert buffer_status(len(rows), 3) == "candidate_buffer_partial"
    assert buffer_status(3, 3) == "candidate_buffer_receipt_ready"


@pytest.mark.parametrize(
    "field,value",
    [
        ("candidate_id", "different-candidate"),
        ("policy_hash", "different-policy"),
        ("corpus_hash", "d" * 64),
        ("receipt_set_hash", "e" * 64),
        ("review_type", "meta_analysis"),
    ],
)
def test_prepared_rows_invalidate_binding_mismatches(field: str, value: str) -> None:
    now = dt.datetime(2026, 8, 1, tzinfo=dt.UTC)
    binding = candidate_binding(
        "metformin",
        code_sha="a" * 40,
        corpus_hash="b" * 64,
        receipt_set_hash="c" * 64,
        review_type="systematic_review",
        thresholds=THRESHOLDS,
    )
    row = {
        "topic": "metformin",
        "state": "receipt_ready",
        "validated_at": now.isoformat(),
        **binding.as_dict(),
    }
    rows = prepared_candidate_rows(
        {"thresholds": THRESHOLDS.as_dict(), "ready": [row]},
        thresholds=THRESHOLDS,
        now=now,
        max_age_hours=24,
        precision_floor=0.5,
        current_bindings={"metformin": replace(binding, **{field: value})},
    )

    assert rows == {}


def test_prepared_rows_reject_unbound_and_non_receipt_ready_rows() -> None:
    now = dt.datetime(2026, 8, 1, tzinfo=dt.UTC)
    binding = candidate_binding(
        "metformin",
        code_sha="a" * 40,
        corpus_hash="b" * 64,
        receipt_set_hash="c" * 64,
        review_type="systematic_review",
        thresholds=THRESHOLDS,
    )
    unbound = {"topic": "metformin", "validated_at": now.isoformat()}
    wrong_state = {**unbound, **binding.as_dict(), "state": "publishable"}
    missing_sha = {**unbound, **binding.as_dict(), "state": "receipt_ready", "code_sha": ""}

    for row in (unbound, wrong_state, missing_sha):
        assert prepared_candidate_rows(
            {"thresholds": THRESHOLDS.as_dict(), "ready": [row]},
            thresholds=THRESHOLDS,
            now=now,
            max_age_hours=24,
            precision_floor=0.5,
            current_bindings={"metformin": binding},
        ) == {}


def test_atomic_json_state_distinguishes_missing_corrupt_and_valid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "state.json"
    store = AtomicJsonState[dict[str, object]](path, dict)
    assert store.read().status is JsonStateStatus.MISSING

    path.write_text("{broken", encoding="utf-8")
    assert store.read().status is JsonStateStatus.CORRUPT
    with pytest.raises(CorruptJsonState):
        store.write({"fabricated": True})
    assert path.read_text(encoding="utf-8") == "{broken"

    path.unlink()
    fsync_calls: list[int] = []
    monkeypatch.setattr("agent.publishing.io.os.fsync", fsync_calls.append)
    store.write({"state": "receipt_ready"})
    result = store.read()
    assert result.status is JsonStateStatus.VALID
    assert result.value == {"state": "receipt_ready"}
    assert len(fsync_calls) == 2
    assert not list(tmp_path.glob("*.tmp"))


def test_atomic_updates_do_not_replace_corrupt_state(tmp_path: Path) -> None:
    path = tmp_path / "rows.json"
    path.write_text("not-json", encoding="utf-8")

    with pytest.raises(CorruptJsonState):
        update_json_list(path, lambda rows: rows.append({"id": "new"}))
    with pytest.raises(CorruptJsonState):
        write_json(path, [])
    assert path.read_text(encoding="utf-8") == "not-json"


def test_candidate_buffer_writer_rejects_unbound_ready_rows(tmp_path: Path) -> None:
    path = tmp_path / "candidate-buffer.json"
    payload = {
        "target_ready": 1,
        "thresholds": THRESHOLDS.as_dict(),
        "ready": [{"topic": "metformin", "state": "receipt_ready"}],
    }

    with pytest.raises(ValueError, match="unbound prepared row"):
        write_json(path, payload)
    assert not path.exists()


@pytest.mark.parametrize("contents", ["{broken", '{"days": []}'])
def test_daily_throughput_refuses_corrupt_existing_state(
    tmp_path: Path,
    contents: str,
) -> None:
    path = tmp_path / "_daily_throughput_summary.json"
    path.write_text(contents, encoding="utf-8")
    ledger = {
        "date": "2026-08-01",
        "started_at": "2026-08-01T00:00:00+00:00",
        "status": "submitted_to_researka",
    }

    with pytest.raises(CorruptJsonState):
        record_daily_throughput(tmp_path, ledger)
    assert path.read_text(encoding="utf-8") == contents


def test_generated_pack_reader_surfaces_corrupt_state(tmp_path: Path) -> None:
    path = tmp_path / "metformin" / "latest.json"
    path.parent.mkdir()
    path.write_text("{broken", encoding="utf-8")

    with pytest.raises(CorruptJsonState):
        generated_pack_records(tmp_path)


def test_conversion_funnel_counts_unique_candidates_not_retries() -> None:
    repeated = {
        "attempts": [
            {
                "out_dir": "run-metformin-R1",
                "receipt_preflight": {"passed": True},
                "synthesis_return_code": 0,
                "gate_status": "journal_surface_not_passed",
                "submitted": 0,
            },
            {
                "out_dir": "run-metformin-R2",
                "receipt_preflight": {"passed": True},
                "synthesis_return_code": 0,
                "gate_status": "journal_surface_not_passed",
                "submitted": 0,
            },
            {
                "topic": "statins",
                "out_dir": "run-statins",
                "receipt_preflight": {"passed": True},
                "synthesis_return_code": 0,
                "gate_status": "eligible",
                "submitted": 1,
                "published": 1,
            },
        ],
    }

    funnel = conversion_funnel([repeated])

    assert funnel == {
        "discovered": 2,
        "prepared": 2,
        "synthesized": 2,
        "local_gate_pass": 1,
        "submitted": 1,
        "revise": 0,
        "accepted": 1,
        "top_unique_blockers": {"journal_surface_not_passed": 1},
    }


def test_conversion_funnel_reads_ledger_level_submission_without_nested_candidate() -> None:
    funnel = conversion_funnel([{
        "submitted_run": "run-statins",
        "submitted": 1,
        "published": 0,
    }])

    assert funnel["local_gate_pass"] == 1
    assert funnel["submitted"] == 1


def test_conversion_funnel_reads_capped_daily_submit_rows() -> None:
    funnel = conversion_funnel([{
        "status": "submitted_to_researka",
        "submitted": 2,
        "published": 0,
        "submissions": [
            {
                "status": "submitted_to_researka",
                "submitted": 1,
                "candidate": {"run": "run-a-R1", "topic": "a"},
            },
            {
                "status": "submitted_to_researka",
                "submitted": 1,
                "candidate": {"run": "run-b", "topic": "b"},
            },
        ],
    }])

    assert funnel["discovered"] == 2
    assert funnel["local_gate_pass"] == 2
    assert funnel["submitted"] == 2


def test_conversion_funnel_unifies_buffer_topic_with_run_attempt() -> None:
    funnel = conversion_funnel([
        {"ready": [{"topic": "metformin"}]},
        {
            "attempts": [{
                "topic": "metformin",
                "out_dir": "synthesis-metformin-R1",
                "gate_status": "eligible",
                "submitted": 1,
            }],
        },
    ])

    assert funnel["discovered"] == 1
    assert funnel["prepared"] == 1
    assert funnel["submitted"] == 1


def test_conversion_funnel_does_not_repeat_published_child_as_aggregate() -> None:
    funnel = conversion_funnel([{
        "candidate": {"run": "run-b", "topic": "b"},
        "submitted": 1,
        "published": 1,
        "submissions": [{
            "candidate": {"run": "run-a", "topic": "a"},
            "status": "published",
            "submitted": 1,
            "published": 1,
        }],
    }])

    assert funnel["accepted"] == 1


def test_conversion_funnel_unifies_uncapped_considered_run_with_aggregate_topic() -> None:
    funnel = conversion_funnel([{
        "candidate": {"run": "run-statins", "topic": "statins"},
        "status": "submitted_to_researka",
        "submitted": 1,
        "considered": [{"run": "run-statins", "status": "eligible"}],
    }])

    assert funnel["discovered"] == 1
    assert funnel["local_gate_pass"] == 1
    assert funnel["submitted"] == 1


def test_conversion_funnel_maps_capped_considered_run_to_each_child_topic() -> None:
    funnel = conversion_funnel([{
        "candidate": {"run": "run-a", "topic": "a"},
        "submitted": 2,
        "considered": [{"run": "run-b", "status": "eligible"}],
        "submissions": [
            {
                "candidate": {"run": "run-a", "topic": "a"},
                "status": "submitted_to_researka",
                "submitted": 1,
            },
            {
                "candidate": {"run": "run-b", "topic": "b"},
                "status": "submitted_to_researka",
                "submitted": 1,
            },
        ],
    }])

    assert funnel["discovered"] == 2
    assert funnel["local_gate_pass"] == 2
    assert funnel["submitted"] == 2


def test_conversion_funnel_recovers_topic_from_legacy_considered_runs() -> None:
    funnel = conversion_funnel([{
        "considered": [
            {
                "run": "synthesis-metformin_effects-v06-2026-07-24T01-00-00Z",
                "status": "journal_surface_failed",
            },
            {
                "run": "synthesis-metformin_effects-v06-2026-07-24T02-00-00Z",
                "status": "journal_surface_failed",
            },
        ],
    }])

    assert funnel["discovered"] == 1
    assert funnel["top_unique_blockers"] == {"journal_surface_failed": 1}
