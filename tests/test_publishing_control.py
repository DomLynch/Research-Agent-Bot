from __future__ import annotations

import datetime as dt

from agent.publishing.candidate_prepare import (
    buffer_status,
    prepared_candidate_rows,
)
from agent.publishing.event_log import conversion_funnel
from agent.publishing.policy import (
    CandidateEvidence,
    CandidateState,
    CandidateThresholds,
    PublicationSurface,
    decide_candidate,
    decision_from_status,
)


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
    assert full.ready_for_synthesis is True
    assert full.state is CandidateState.READY_FOR_SYNTHESIS
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
    report = {
        "thresholds": THRESHOLDS.as_dict(),
        "attempts": [
            {
                "topic": "ready",
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
    )

    assert set(rows) == {"ready"}
    assert buffer_status(len(rows), 3) == "candidate_buffer_partial"


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
