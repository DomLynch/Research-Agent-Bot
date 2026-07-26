"""Daily v3 research-paper production cycle.

Builds one fresh synthesis run, then delegates acceptance submission to the
existing daily_research_paper_submit bridge. Safe by default: no synthesis or
network submission happens unless flags explicitly enable them.
"""
from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from collections.abc import Callable, Collection, Iterator, Mapping, Sequence
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from publishing import submission as submit_bridge

ROOT = Path(__file__).resolve().parents[2]
# Enable in-process `from scripts.X import Y` when systemd launches us as
# `python scripts/daily_research_paper_cycle.py` (script-style invocation
# only puts scripts/ on sys.path, not the repo root). Mirrors
# scripts/run_v06_synthesis.py:46. Without this, _repair_existing_run hits
# ModuleNotFoundError for scripts.review_noise_control and falls back to a
# full rewrite, burning the 2-hour cycle budget.
sys.path.insert(0, str(ROOT))
import revision_coverage  # noqa: E402
from source_topic_specificity import generated_pack_publishable, is_source_topic_specific, source_gate_aliases, topic_aliases  # noqa: E402
from agent.final_gate import DEFAULT_THRESHOLDS  # noqa: E402
from agent.publishing.io import (  # noqa: E402
    parse_time as _parse_time,
    read_json as _read_json,
    update_json_list as _update_json_list,
    write_json as _write_json,
)
from agent.publishing.candidate_prepare import (  # noqa: E402
    buffer_status as _candidate_buffer_status,
    prepared_candidate_rows as _validated_candidate_rows,
    recent_attempts as _recent_preparation_attempts,
)
from agent.publishing.event_log import record_daily_throughput as _record_daily_throughput  # noqa: E402
from agent.publishing.policy import (  # noqa: E402
    CandidateDecision,
    CandidateEvidence,
    CandidateThresholds,
    PublicationSurface,
    decide_candidate,
    source_fit_reasons,
)
from agent.publishing import topic_supply  # noqa: E402
from agent.publishing.revision_lane import (  # noqa: E402
    V3_AGENT_IDS,
    actionable_revisions as _actionable_revisions,
    review_agent_mismatch as _review_agent_mismatch,
    required_revision_items as _required_revision_items,
    requests_domain_scope_reset as _revision_requests_domain_scope_reset,
    revise_reason_bucket as _revise_reason_bucket,
    revision_detail_score as _revision_detail_score,
)
from agent.publishing.reconciliation import (  # noqa: E402
    child_submission_counts as _child_submission_counts,
    clear_unattributed_publication_reconciliation as _clear_unattributed_publication_reconciliation,
    ledger_run_names as _ledger_run_names,
    ledger_submission_markers as _ledger_submission_markers_impl,
    reconciled_publication_markers as _reconciled_publication_markers,
    row_submission_markers as _row_submission_markers,
    sync_reconciled_children as _sync_reconciled_children,
)
from agent.revision_contract import ask_fingerprint  # noqa: E402
from agent.revision_evidence import load_revision_evidence  # noqa: E402
from agent.review_type import (  # noqa: E402
    COMPACT_REVIEW_TYPES,
    DEFAULT_REVIEW_TYPE,
    THIN_CORPUS_MIN_PRIMARY_TIER,
    downshift_review_type_for_thin_corpus,
    parse_review_type,
)


def _positive_env_int(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default

RUNS = ROOT / "runs"
TOPIC_PACKS = ROOT / "topic_packs"
TOPIC_PACKS_DB = ROOT / "topic_packs_db"
CORPORA = ROOT / "docs" / "quality-reference"
LEDGER_DIR = "_daily_research_paper_cycle_ledger"
BLOCKER_HISTOGRAM = "_blocker_histogram.json"
HANDLED_REVISIONS = "_handled_revision_requests.json"
REVISION_COVERAGE_GATE = "revision_coverage_gate.json"
DAILY_THROUGHPUT_SUMMARY = "_daily_throughput_summary.json"
CANDIDATE_BUFFER = "_candidate_buffer.json"
DECISIONS_BY_DAY = "_decisions_by_day.json"
REVISE_REASONS = "_revise_reasons.json"
DAY_KEY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# A Researka revise may be re-processed up to this many rounds per artifact
# before it is treated as permanently handled. Single-round handling left
# papers stuck after one revise; the cap lets feedback-aware re-renders iterate
# while bounding resubmissions to the live platform.
MAX_REVISE_ROUNDS = 3
REVISION_REPAIR_EPOCH = _positive_env_int("RESEARCH_AGENT_REVISION_REPAIR_EPOCH", 11)
PREFLIGHT_MIN_RECEIPTS = DEFAULT_THRESHOLDS.min_receipts
PREFLIGHT_MIN_QUANT_CLAIMS = 10
PREFLIGHT_MIN_TENSIONS = 3
PREFLIGHT_MIN_PRIMARY_TIER = THIN_CORPUS_MIN_PRIMARY_TIER
PREFLIGHT_MIN_DIRECT_RECEIPTS = submit_bridge.PUBLIC_RESEARCH_MIN_DIRECT_RECEIPTS
_CANDIDATE_THRESHOLDS = CandidateThresholds(
    min_quant_claims=PREFLIGHT_MIN_QUANT_CLAIMS,
    min_receipts=PREFLIGHT_MIN_RECEIPTS,
    min_primary_tier=PREFLIGHT_MIN_PRIMARY_TIER,
    min_direct_receipts=PREFLIGHT_MIN_DIRECT_RECEIPTS,
)
SOURCE_PRECISION_REPAIR_PUBLISH_MIN_QUANT = max(PREFLIGHT_MIN_RECEIPTS * 2, PREFLIGHT_MIN_QUANT_CLAIMS)
PREFLIGHT_MAX_RECEIPTS = 500
PREFLIGHT_MAX_TENSIONS = 50_000
PREFLIGHT_MAX_OUTCOMES = 12
RECENT_FAILURE_COOLDOWN_HOURS = 24
CANDIDATE_BUFFER_MAX_AGE_HOURS = 24
SURFACE_REPEAT_THRESHOLD = 2
WRITER_GATE_REPEAT_THRESHOLD = 2
HISTOGRAM_ISSUE_THRESHOLD = 5
AUTO_SEED_LIMIT = 120
TOPIC_SUPPLY_REFRESH_LIMIT = 500
TOPIC_SUPPLY_REFRESH_FALLBACK_LIMIT = 1000
TOPIC_SUPPLY_REFRESH_MAX_CREATED = 20
TOPIC_SUPPLY_STRATEGIES = (
    "fact-intervention-cross",
    "fact-field-cross",
    "fact-pair-cross",
    "grouped",
)
SEED_TOPIC_TIMEOUT_SECONDS = 600
PUBLISH_SEED_TIMEOUT_SECONDS = 120
CORPUS_REPAIR_LIMIT = 1
SOURCE_PRECISION_REPAIR_SCAN_LIMIT = 3
RECEIPT_PREFLIGHT_REPAIR_ROUNDS = 2
SOURCE_TOPIC_REPAIR_FLOOR = submit_bridge.SOURCE_TOPIC_PRECISION_FLOOR
DEFAULT_CYCLE_TIMEZONE = "Asia/Dubai"
REVISION_SOURCE_BUNDLE_TOPIC_FLOOR = 0.80
DECISION_POLL_SECONDS = 900
DECISION_POLL_INTERVAL_SECONDS = 30
CYCLE_BUDGET_SECONDS = 6300
MIN_REVISE_RETRY_BUDGET_SECONDS = 1200
SYNTHESIS_TIMEOUT_RETURN_CODE = 124
NEEDS_CORPUS_RETURN_CODE = 6
PUBLISHED_TOPIC_COOLDOWN_DAYS = 21
_SPARSE_REVIEW_RE = re.compile(r"\b(mixed and sparse|evidence base\W+sparse|precludes?\W+(?:a\W+)?(?:strong\W+)?accept|no material revisions?)\b", re.I)
_TERMINAL_SPARSE_RE = re.compile(r"\b(precludes?\W+(?:a\W+)?(?:strong\W+)?accept|no material revisions?)\b", re.I)
_TERMINAL_REVISION_STATUSES = frozenset({
    "duplicate_remote_publication",
    "duplicate_submission_fingerprint",
    "researka_revision_fingerprint",
    "research_revision_fingerprint",
    "retracted_source_cited",
    "terminal_revision_source_manifest_unavailable",
    "terminal_receipt_preflight_insufficient",
    "terminal_surface_repeat",
    "terminal_source_precision_repair_incomplete",
})
_ACTIVE_REVIEW_TERMINAL_REVISION_STATUSES = frozenset({
    "terminal_domain_scope_mismatch",
    "terminal_latest_run_missing_manifest",
    "terminal_preflight_insufficient_corpus",
})
_RETRYABLE_REVISION_STATUSES = frozenset({
    "revision_coverage_unmet",
    "synthesis_timeout",
    # Back-compat for rows written before synthesis timeouts became retryable.
    "terminal_synthesis_timeout",
    # A timer window can end before another full rewrite fits. That is a
    # transient scheduling limit, not a permanent verdict on the revision.
    "terminal_revise_retry_budget_insufficient",
})
SUBMISSION_DECISION_TIMEOUT_SECONDS = int(os.environ.get("RESEARCH_AGENT_SUBMISSION_DECISION_TIMEOUT_SECONDS", "8"))

RemoteLoader = Callable[[], tuple[set[str], str | None]]
SubmitCycle = Callable[..., dict[str, Any]]
CorpusBuilder = Callable[..., dict[str, Any]]
RevisionLoader = Callable[[], tuple[list[dict[str, Any]], str | None]]
PublishedLoader = Callable[[], tuple[set[str], str | None]]
Sleeper = Callable[[float], None]

def _cycle_ledger_path(ledger_dir: Path, date: str, mode: str) -> Path:
    suffix = "" if mode == "mixed" else f"-{mode}"
    return ledger_dir / f"{date}{suffix}.json"

def _ledger_paths_for_reconciliation(ledger_dir: Path, date: str | None, mode: str | None) -> list[Path]:
    if date and mode:
        return [_cycle_ledger_path(ledger_dir, date, mode)]
    if date:
        return [_cycle_ledger_path(ledger_dir, date, lane) for lane in ("mixed", "fresh", "revise", "daily-submit")]
    return sorted(path for path in ledger_dir.glob("*.json") if not path.name.startswith("_"))


def _submit_ledger_paths_for_reconciliation(runs_root: Path, date: str | None) -> list[Path]:
    ledger_dir = runs_root / submit_bridge.LEDGER_DIR
    if date:
        return [ledger_dir / f"{date}.json"]
    return sorted(path for path in ledger_dir.glob("*.json") if not path.name.startswith("_"))


def _refresh_submit_day_summary(ledger: dict[str, Any], runs_root: Path) -> bool:
    date = str(ledger.get("date") or "")
    if not DAY_KEY_RE.fullmatch(date):
        return False
    summary = ledger.get("day_summary")
    summary = summary if isinstance(summary, dict) else {}
    before = dict(summary)
    durable_submitted = submit_bridge._submitted_count_for_date(
        runs_root / submit_bridge.LEDGER_DIR / "_submitted_fingerprints.json",
        date,
    )
    day_summary = {
        "submitted": max(
            durable_submitted,
            int(ledger.get("submitted") or 0),
            int(summary.get("submitted") or 0),
        ),
        "published": max(
            int(ledger.get("published") or 0),
            int(summary.get("published") or 0),
        ),
    }
    if day_summary["submitted"] or day_summary["published"]:
        ledger["day_summary"] = day_summary
    return ledger.get("day_summary") != before


def _publication_markers_for_run(runs_root: Path, run_name: str) -> set[str]:
    paper = runs_root / run_name / "full_paper.md"
    if not paper.exists():
        return set()
    markers = {submit_bridge._sha256(paper)}
    title = submit_bridge._paper_title(paper)
    if title:
        markers.add(submit_bridge._title_marker(title))
    return markers


def _submitted_title_marker_counts(runs_root: Path) -> Counter[str]:
    run_names: set[str] = set()
    for ledger_dir in (runs_root / LEDGER_DIR, runs_root / submit_bridge.LEDGER_DIR):
        for path in ledger_dir.glob("*.json"):
            if path.name.startswith("_"):
                continue
            ledger = _read_json(path)
            if int(ledger.get("submitted") or 0):
                run_names.update(_ledger_run_names(ledger))
    for row in submit_bridge._ledger_rows(runs_root / submit_bridge.LEDGER_DIR / "_submitted_fingerprints.json"):
        raw_run = row.get("run")
        if isinstance(raw_run, str) and raw_run:
            run_names.add(raw_run)
    counts: Counter[str] = Counter()
    for run_name in run_names:
        paper = runs_root / run_name / "full_paper.md"
        if paper.exists():
            marker = submit_bridge._title_marker(submit_bridge._paper_title(paper))
            if marker:
                counts[marker] += 1
    return counts


def _remote_has_submission_marker(remote_seen: set[str]) -> bool:
    return any(marker.startswith("submission:") for marker in remote_seen)


def _publication_matches_for_run(
    runs_root: Path,
    run_name: str,
    remote_seen: set[str],
    title_marker_counts: Counter[str],
) -> set[str]:
    matches = _publication_markers_for_run(runs_root, run_name) & remote_seen
    if not matches:
        return set()
    paper = runs_root / run_name / "full_paper.md"
    if not paper.exists():
        return matches
    title_marker = submit_bridge._title_marker(submit_bridge._paper_title(paper))
    if title_marker in matches and title_marker_counts.get(title_marker, 0) > 1:
        matches.remove(title_marker)
    return matches


def _ledger_submission_markers(ledger: dict[str, Any]) -> set[str]:
    return _ledger_submission_markers_impl(
        ledger,
        submission_ids_from_response=submit_bridge._submission_ids_from_response,
        submission_marker=submit_bridge._submission_marker,
    )


def _submit_bridge_submission_markers_by_run(runs_root: Path, run_names: set[str]) -> dict[str, set[str]]:
    if not run_names:
        return {}
    markers_by_run: dict[str, set[str]] = {}
    ledger_dir = runs_root / submit_bridge.LEDGER_DIR
    for path in ledger_dir.glob("*.json"):
        if path.name.startswith("_"):
            continue
        ledger = _read_json(path)
        submissions = ledger.get("submissions")
        if isinstance(submissions, list):
            for submission in submissions:
                if not isinstance(submission, dict):
                    continue
                candidate = submission.get("candidate")
                run_name = candidate.get("run") if isinstance(candidate, dict) else None
                if isinstance(run_name, str) and run_name in run_names:
                    markers_by_run.setdefault(run_name, set()).update(
                        _ledger_submission_markers(submission),
                    )
            continue
        matched_runs = set(_ledger_run_names(ledger)) & run_names
        if matched_runs:
            markers = _ledger_submission_markers(ledger)
            for run_name in matched_runs:
                markers_by_run.setdefault(run_name, set()).update(markers)
    for row in submit_bridge._ledger_rows(ledger_dir / "_submitted_fingerprints.json"):
        raw_run = row.get("run")
        if not isinstance(raw_run, str) or raw_run not in run_names:
            continue
        markers = markers_by_run.setdefault(raw_run, set())
        submission_id = row.get("submission_id")
        if isinstance(submission_id, str) and submission_id:
            markers.add(submit_bridge._submission_marker(submission_id))
        for key in ("fingerprint", "paper_sha256", *submit_bridge.PUBLICATION_IDENTITY_KEYS):
            value = row.get(key)
            if isinstance(value, str) and value:
                markers.add(value if value.startswith("sha256:") else f"sha256:{value}")
    return markers_by_run


def _submit_bridge_submission_markers_for_runs(runs_root: Path, run_names: set[str]) -> set[str]:
    markers: set[str] = set()
    for values in _submit_bridge_submission_markers_by_run(runs_root, run_names).values():
        markers.update(values)
    return markers


def _ledger_publication_markers_for_runs(
    ledger: dict[str, Any],
    runs_root: Path,
    run_names: set[str],
) -> set[str]:
    markers = set(_ledger_submission_markers(ledger))
    markers.update(_submit_bridge_submission_markers_for_runs(runs_root, run_names))
    for run_name in run_names:
        markers.update(_publication_markers_for_run(runs_root, run_name))
    return markers


def _reconciled_publication_matches_ledger(ledger: dict[str, Any], runs_root: Path) -> bool:
    matched = _reconciled_publication_markers(ledger)
    if not matched:
        return True
    run_names = set(_ledger_run_names(ledger, submitted_only=False))
    if matched & _ledger_publication_markers_for_runs(ledger, runs_root, run_names):
        return True
    return not any(value.startswith("submission:") for value in matched)


def _matched_ledger_runs_for_markers(
    ledger: dict[str, Any],
    runs_root: Path,
    matched: set[str],
) -> set[str]:
    run_names = set(_ledger_run_names(ledger, submitted_only=False))
    marker_map = _submit_bridge_submission_markers_by_run(runs_root, run_names)
    matched_runs = {
        run_name for run_name, markers in marker_map.items()
        if markers & matched
    }
    for run_name in run_names:
        if _publication_markers_for_run(runs_root, run_name) & matched:
            matched_runs.add(run_name)
    attempts = ledger.get("attempts")
    for attempt in attempts if isinstance(attempts, list) else []:
        if not isinstance(attempt, dict):
            continue
        attempt_run = str(attempt.get("submitted_run") or attempt.get("out_dir") or "")
        if attempt_run and _row_submission_markers(attempt) & matched:
            matched_runs.add(attempt_run)
    submissions = ledger.get("submissions")
    for submission in submissions if isinstance(submissions, list) else []:
        if not isinstance(submission, dict):
            continue
        candidate = submission.get("candidate")
        submission_run = candidate.get("run") if isinstance(candidate, dict) else None
        if isinstance(submission_run, str) and _row_submission_markers(submission) & matched:
            matched_runs.add(submission_run)
    return matched_runs


def _review_decision_summary(rows: dict[str, dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(rows.values(), key=_review_ts, reverse=True)
    counts = Counter(str(row.get("decision") or "unknown").lower() for row in ordered)
    return {
        "counts": dict(sorted(counts.items())),
        "records": [{
            "decision": row.get("decision"),
            "status": row.get("status"),
            "title": row.get("title"),
            "topic": row.get("topic"),
            "submission_id": row.get("submissionId") or row.get("submission_id"),
            "reviewed_at": (
                row.get("reviewedAt")
                or row.get("reviewed_at")
                or row.get("createdAt")
                or row.get("created_at")
                or row.get("publishedAt")
                or row.get("published_at")
            ),
        } for row in ordered[:12]],
    }


def _publication_receipts_by_marker(
    rows: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    receipts: dict[str, dict[str, Any]] = {}
    for row in rows.values():
        publication = row.get("publication")
        publication = publication if isinstance(publication, dict) else {}
        public_visible = row.get("publicVisible") is True or row.get("public_visible") is True
        publication_id = (
            publication.get("publication_id")
            or publication.get("publicationId")
            or row.get("publication_id")
            or row.get("publicationId")
            or (row.get("artifactId") if public_visible else None)
        )
        public_url = publication.get("url") or row.get("public_url") or row.get("url")
        if not public_url and public_visible and publication_id:
            papers_url = os.getenv("RESEARKA_PAPERS_URL", "https://researka.org/papers").rstrip("/")
            public_url = f"{papers_url}/{urllib.parse.quote(str(publication_id))}"
        receipt = {
            "decision": row.get("decision"),
            "public_url": public_url,
            "doi": publication.get("doi") or row.get("doi"),
            "publication_id": publication_id,
        }
        receipt = {key: value for key, value in receipt.items() if value not in (None, "")}
        for marker in _public_decision_markers({"row": row}):
            receipts[marker] = receipt
    return receipts


def _apply_publication_receipt(
    ledger: dict[str, Any],
    matched: set[str],
    receipts_by_marker: dict[str, dict[str, Any]] | None,
) -> bool:
    if not receipts_by_marker:
        return False
    receipt = next(
        (receipts_by_marker[marker] for marker in sorted(matched) if marker in receipts_by_marker),
        None,
    )
    if not receipt:
        return False
    reconciliation = ledger.get("publication_reconciliation")
    reconciliation = reconciliation if isinstance(reconciliation, dict) else {}
    reconciled_at = str(reconciliation.get("reconciled_at") or dt.datetime.now(dt.UTC).isoformat())
    changed = False
    for key, value in {**receipt, "reconciled": True, "reconciled_at": reconciled_at}.items():
        if ledger.get(key) != value:
            ledger[key] = value
            changed = True
    for key, value in receipt.items():
        if reconciliation.get(key) != value:
            reconciliation[key] = value
            changed = True
    ledger["publication_reconciliation"] = reconciliation
    return changed


def _write_reconcile_artifact(
    ledger_dir: Path,
    *,
    date: str | None,
    mode: str | None,
    result: dict[str, Any],
) -> None:
    artifact_date = date or _default_cycle_date()
    _write_json(ledger_dir / f"{artifact_date}-reconcile.json", {
        "date": artifact_date,
        "mode": mode or "all",
        "scope": date or "all_dates",
        "created_at": dt.datetime.now(dt.UTC).isoformat(),
        **result,
    })


def _reconcile_published_ledger(
    ledger: dict[str, Any],
    runs_root: Path,
    remote_seen: set[str],
    title_marker_counts: Counter[str] | None = None,
    receipts_by_marker: dict[str, dict[str, Any]] | None = None,
) -> bool:
    changed = False
    if int(ledger.get("published") or 0):
        if not _reconciled_publication_matches_ledger(ledger, runs_root):
            changed = _clear_unattributed_publication_reconciliation(ledger)
        else:
            matched = _reconciled_publication_markers(ledger)
            if matched:
                existing_matched_runs = _matched_ledger_runs_for_markers(ledger, runs_root, matched)
                changed = _sync_reconciled_children(ledger, existing_matched_runs, matched) or changed
                changed = _apply_publication_receipt(ledger, matched, receipts_by_marker) or changed
            if str(ledger.get("status") or "") != "published":
                ledger["status"] = "published"
                changed = True
            child_submitted, child_published = _child_submission_counts(ledger)
            if child_submitted and int(ledger.get("submitted") or 0) < child_submitted:
                ledger["submitted"] = child_submitted
                changed = True
            if child_published and int(ledger.get("published") or 0) < child_published:
                ledger["published"] = child_published
                changed = True
            before = len(ledger)
            ledger.pop("no_submission_reason", None)
            return changed or len(ledger) != before
    matches: set[str] = set()
    matched_runs: set[str] = set()
    submitted_runs = set(_ledger_run_names(ledger))
    title_marker_counts = title_marker_counts or _submitted_title_marker_counts(runs_root)
    if int(ledger.get("submitted") or 0):
        exact_markers = _ledger_submission_markers(ledger) or _submit_bridge_submission_markers_for_runs(runs_root, submitted_runs)
        if exact_markers:
            matches.update(exact_markers & remote_seen)
            if not matches and _remote_has_submission_marker(remote_seen):
                return changed
        if not matches:
            for run_name in submitted_runs:
                run_matches = _publication_matches_for_run(runs_root, run_name, remote_seen, title_marker_counts)
                if run_matches:
                    matched_runs.add(run_name)
                    matches.update(run_matches)
    else:
        marker_map = _submit_bridge_submission_markers_by_run(
            runs_root,
            set(_ledger_run_names(ledger, submitted_only=False)),
        )
        for run_name, markers in marker_map.items():
            run_matches = markers & remote_seen
            if run_matches:
                matched_runs.add(run_name)
                matches.update(run_matches)
        if not matches:
            return changed
    if not matches:
        return changed
    if not submitted_runs:
        submitted_runs = matched_runs
    if not matched_runs and matches:
        matched_runs = _matched_ledger_runs_for_markers(ledger, runs_root, matches)
    ledger["status"] = "published"
    ledger.pop("no_submission_reason", None)
    ledger["publication_reconciliation"] = {
        "source": "remote_publications",
        "matched": sorted(matches)[:5],
        "reconciled_at": dt.datetime.now(dt.UTC).isoformat(),
    }
    _apply_publication_receipt(ledger, matches, receipts_by_marker)
    attempts = ledger.get("attempts")
    for attempt in attempts if isinstance(attempts, list) else []:
        if not isinstance(attempt, dict):
            continue
        attempt_run = str(attempt.get("submitted_run") or attempt.get("out_dir") or "")
        if not attempt_run or attempt_run in matched_runs or (not matched_runs and attempt_run in submitted_runs):
            attempt["submitted"] = 1
            attempt["published"] = 1
    submissions = ledger.get("submissions")
    for submission in submissions if isinstance(submissions, list) else []:
        if not isinstance(submission, dict):
            continue
        values = submission.get("submission_markers")
        submission_markers = set()
        if isinstance(values, list):
            submission_markers = {
                value for value in values
                if isinstance(value, str) and value.startswith("submission:")
            }
        candidate = submission.get("candidate")
        submission_run = candidate.get("run") if isinstance(candidate, dict) else None
        if submission_markers & matches or (isinstance(submission_run, str) and submission_run in matched_runs):
            submission["submitted"] = 1
            submission["published"] = 1
    child_submitted, child_published = _child_submission_counts(ledger)
    ledger["submitted"] = max(int(ledger.get("submitted") or 0), child_submitted, 1)
    ledger["published"] = max(int(ledger.get("published") or 0), child_published, 1)
    return True


def reconcile_publication_ledgers(
    *,
    runs_root: Path = RUNS,
    date: str | None = None,
    mode: str | None = None,
    remote_loader: RemoteLoader | None = None,
) -> dict[str, Any]:
    ledger_dir = runs_root / LEDGER_DIR
    remote_seen, remote_error = (remote_loader or submit_bridge._remote_published_fingerprints)()
    if remote_error:
        result = {"status": "remote_dedupe_failed", "reason": remote_error, "checked": 0, "updated": 0}
        _write_reconcile_artifact(ledger_dir, date=date, mode=mode, result=result)
        return result
    title_marker_counts = _submitted_title_marker_counts(runs_root)
    decision_records = 0
    decision_seen: set[str] = set()
    decision_summary: dict[str, Any] = {"counts": {}, "records": []}
    receipts_by_marker: dict[str, dict[str, Any]] = {}
    if remote_loader is None:
        latest_decisions, decision_error = _latest_public_decisions_by_title()
        direct_decisions, direct_error = _submitted_submission_decisions_by_title(runs_root)
        latest_decisions = _merge_latest_by_title(
            {} if decision_error else latest_decisions,
            {} if direct_error else direct_decisions,
        )
        if latest_decisions:
            _record_review_decisions(ledger_dir, latest_decisions)
            decision_seen = _public_decision_markers(latest_decisions)
            receipts_by_marker = _publication_receipts_by_marker(latest_decisions)
            decision_records = len(latest_decisions)
            decision_summary = _review_decision_summary(latest_decisions)
    checked = 0
    updated: list[str] = []
    for ledger_path in _ledger_paths_for_reconciliation(ledger_dir, date, mode):
        ledger = _read_json(ledger_path)
        if not ledger:
            continue
        checked += 1
        changed = _reconcile_published_ledger(
            ledger, runs_root, remote_seen, title_marker_counts, receipts_by_marker,
        )
        if not changed and decision_seen:
            changed = _reconcile_published_ledger(
                ledger, runs_root, decision_seen, title_marker_counts, receipts_by_marker,
            )
        if changed:
            _write_json(ledger_path, ledger)
            _record_daily_throughput(ledger_dir, ledger)
            updated.append(ledger_path.name)
    for ledger_path in _submit_ledger_paths_for_reconciliation(runs_root, date):
        ledger = _read_json(ledger_path)
        if not ledger:
            continue
        checked += 1
        changed = _reconcile_published_ledger(
            ledger, runs_root, remote_seen, title_marker_counts, receipts_by_marker,
        )
        if not changed and decision_seen:
            changed = _reconcile_published_ledger(
                ledger, runs_root, decision_seen, title_marker_counts, receipts_by_marker,
            )
        if int(ledger.get("published") or 0):
            changed = _refresh_submit_day_summary(ledger, runs_root) or changed
        if changed:
            _write_json(ledger_path, ledger)
            updated.append(f"{submit_bridge.LEDGER_DIR}/{ledger_path.name}")
    result = {
        "status": "publication_reconciled" if updated else "no_publication_reconciliation_needed",
        "checked": checked,
        "updated": len(updated),
        "updated_ledgers": updated,
        "known_fingerprints": len(remote_seen),
        "decision_records": decision_records,
        "decision_summary": decision_summary,
    }
    _write_reconcile_artifact(ledger_dir, date=date, mode=mode, result=result)
    return result


def discover_topics(
    topic_packs: Path | None = None,
    corpora: Path | None = None,
    topic_pack_db: Path | None = None,
) -> list[str]:
    topic_packs = topic_packs or TOPIC_PACKS
    topic_pack_db = topic_pack_db or topic_packs.parent / "topic_packs_db"
    _ = corpora
    return topic_supply.discover_topics(
        topic_packs,
        topic_pack_db,
        generated_pack_publishable=generated_pack_publishable,
    )


def _topic_supply_refresh_enabled() -> bool:
    return os.getenv("RESEARCH_AGENT_TOPIC_SUPPLY_REFRESH", "1").strip().lower() not in {
        "0", "false", "no", "off",
    }


def _topic_supply_strategies() -> list[str]:
    return topic_supply.ordered_strategies(
        os.getenv("RESEARCH_AGENT_TOPIC_SUPPLY_STRATEGY", "").strip(),
        TOPIC_SUPPLY_STRATEGIES,
    )


def _refresh_topic_supply(
    topic_pack_db: Path | None = None,
    *,
    skip_slugs: set[str] | None = None,
) -> dict[str, Any]:
    """Materialize fact-backed generated packs when the fresh topic pool is empty."""
    if not _topic_supply_refresh_enabled():
        return {"status": "topic_supply_refresh_disabled", "created": []}
    try:
        import materialize_fact_topic_packs as materializer  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover - import/environment guard
        return {"status": "topic_supply_refresh_unavailable", "error": str(exc), "created": []}
    dsn = materializer.dsn_from_env()
    base_url, token = materializer.http_credentials_from_env()
    if not dsn and not (base_url and token):
        return {"status": "topic_supply_refresh_not_configured", "created": []}
    quality_mode = os.getenv("RESEARCH_AGENT_TOPIC_SUPPLY_QUALITY_MODE", "high-precision")
    limit = _positive_env_int("RESEARCH_AGENT_TOPIC_SUPPLY_LIMIT", TOPIC_SUPPLY_REFRESH_LIMIT)
    fallback_limit = _positive_env_int(
        "RESEARCH_AGENT_TOPIC_SUPPLY_FALLBACK_LIMIT", max(limit, TOPIC_SUPPLY_REFRESH_FALLBACK_LIMIT)
    )
    scan_limits = [limit, *([fallback_limit] if fallback_limit > limit else [])]
    return topic_supply.refresh_topic_supply(
        materializer=materializer,
        topic_pack_db=topic_pack_db or TOPIC_PACKS_DB,
        skip_slugs=skip_slugs,
        quality_mode=quality_mode,
        scan_limits=scan_limits,
        max_created=_positive_env_int(
            "RESEARCH_AGENT_TOPIC_SUPPLY_MAX_CREATED",
            TOPIC_SUPPLY_REFRESH_MAX_CREATED,
        ),
        strategies=_topic_supply_strategies(),
        dsn=dsn,
        base_url=base_url,
        token=token,
    )


def _created_topic_slugs(refresh: Mapping[str, Any]) -> set[str]:
    return topic_supply.created_topic_slugs(refresh)


def _generated_pack_records(topic_pack_db: Path | None = None) -> list[dict[str, Any]]:
    return topic_supply.generated_pack_records(topic_pack_db or TOPIC_PACKS_DB)


def _quant_claim_count(topic: str) -> int:
    return sum(1 for _ in (CORPORA / topic / "quant_claims").glob("*.quant_claims.json"))


def _claim_bearing_quant_count(topic: str) -> tuple[int, int]:
    """Files with explicit, usable claim payloads.

    Legacy sidecars without a ``claims`` field count as usable; explicit empty
    claim lists do not. This keeps old fixtures/data compatible while stopping
    empty extraction artifacts from looking like a publishable corpus.
    """
    total = usable = 0
    for path in (CORPORA / topic / "quant_claims").glob("*.quant_claims.json"):
        total += 1
        data = _read_json(path)
        claims = data.get("claims")
        if claims is None or isinstance(claims, list) and any(
            isinstance(claim, dict)
            and str(claim.get("binding_confidence") or "high").lower() != "none"
            for claim in claims
        ):
            usable += 1
    return usable, total


def _attempted_at(topic: str, ledger_dir: Path) -> str:
    latest = ""
    for path in ledger_dir.glob("*.json"):
        row = _read_json(path)
        if row.get("topic") == topic and str(row.get("started_at", "")) > latest:
            latest = str(row["started_at"])
        for attempt in row.get("attempts", []):
            if isinstance(attempt, dict) and attempt.get("topic") == topic and str(row.get("started_at", "")) > latest:
                latest = str(row["started_at"])
    return latest

def _parse_review_time(value: str) -> dt.datetime | None:
    value = str(value or "").strip()
    if DAY_KEY_RE.fullmatch(value):
        timezone: dt.tzinfo
        try:
            timezone = ZoneInfo(os.getenv("RESEARCH_AGENT_CYCLE_TIMEZONE", DEFAULT_CYCLE_TIMEZONE))
        except ZoneInfoNotFoundError:
            timezone = dt.UTC
        return dt.datetime.fromisoformat(value).replace(tzinfo=timezone).astimezone(dt.UTC)
    return _parse_time(value)


def _default_cycle_date(now: dt.datetime | None = None) -> str:
    timezone_name = os.getenv("RESEARCH_AGENT_CYCLE_TIMEZONE", DEFAULT_CYCLE_TIMEZONE)
    timezone: dt.tzinfo
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        timezone = dt.UTC
    current = now or dt.datetime.now(dt.UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=dt.UTC)
    return current.astimezone(timezone).date().isoformat()


def _latest_topic_run(topic: str, runs_root: Path) -> Path | None:
    runs = sorted(runs_root.glob(f"synthesis-{topic}-v*-*"), key=lambda p: p.stat().st_mtime, reverse=True)
    return next((p for p in runs if p.is_dir()), None)


def _manifest_counts(run: Path | None) -> dict[str, Any]:
    manifest = _read_json(run / "manifest.json") if run else {}
    receipts = [r for r in manifest.get("receipts", []) if isinstance(r, dict)]
    primary = sum(1 for r in receipts if str(r.get("evidence_tier") or r.get("tier") or "").upper() in {"A1", "A2", "B1"})
    direct = sum(1 for r in receipts if str(r.get("directness") or "").lower() == "direct")
    if receipts and not any("directness" in r for r in receipts):
        direct = primary
    return {
        "has_manifest": bool(manifest),
        "n_receipts": int(manifest.get("n_receipts") or len(receipts) or 0),
        "n_tensions": int(manifest.get("n_non_orthogonal_tensions") or 0),
        "n_primary_tier": primary,
        "n_direct_receipts": direct,
        "n_outcome_classes": len({str(r.get("outcome_class") or "").strip() for r in receipts if str(r.get("outcome_class") or "").strip()}),
    }


def _topic_run_stats(topic: str, runs_root: Path) -> tuple[int, int]:
    total = l4plus = 0
    for run in runs_root.glob(f"synthesis-{topic}-v*-*"):
        if not run.is_dir():
            continue
        total += 1
        status = _read_json(run / "final_status.json")
        l4plus += int(int(status.get("maturity_level") or 0) >= 4)
    return total, l4plus


def _recent_failed_attempts(topic: str, ledger_dir: Path, *, now: dt.datetime | None = None) -> int:
    now = now or dt.datetime.now(dt.UTC)
    cutoff = now - dt.timedelta(hours=RECENT_FAILURE_COOLDOWN_HOURS)
    failures = 0
    for path in ledger_dir.glob("*.json"):
        row = _read_json(path)
        started = _parse_time(str(row.get("started_at") or ""))
        if started is None or started < cutoff:
            continue
        for attempt in row.get("attempts", []):
            if (
                isinstance(attempt, dict)
                and attempt.get("topic") == topic
                and int(attempt.get("submitted") or 0) == 0
            ):
                failures += 1
    return failures


# Statuses that are transient or already routed elsewhere — they must never
# count toward a deterministic-gate "surface repeat" (universal; no topic- or
# domain-specific knowledge).
_NON_REPEAT_STATUSES = frozenset({"", "eligible", "submitted_to_researka",
                                  "cycle_budget_exhausted", "current_run_not_submitted",
                                  "synthesis_failed", "synthesis_timeout", "terminal_synthesis_timeout",
                                  "corpus_seed_failed",
                                  "terminal_surface_repeat"})
_PREFLIGHT_BLOCK_STATUSES = frozenset({"corpus_missing_dry_run", "corpus_seed_empty",
                                        "preflight_insufficient_corpus", "preflight_thin_quant_corpus",
                                        "receipt_preflight_insufficient",
                                        "source_bundle_topic_mismatch",
                                        "source_bundle_unmapped_sources"})
_SOURCE_PRECISION_STATUS = "source_topic_precision_low"
_CORPUS_REPAIR_STATUSES = _PREFLIGHT_BLOCK_STATUSES | {"retracted_source_cited", _SOURCE_PRECISION_STATUS}
_NO_AUTO_RETRY_STATUSES = frozenset({"journal_surface_failed", "journal_surface_not_passed"})


def _surface_ready_after(topic: str, runs_root: Path | None, failure_at: dt.datetime) -> bool:
    """A newer ready artifact proves a prior deterministic surface failure is stale."""
    if runs_root is None:
        return False
    runs = sorted(runs_root.glob(f"synthesis-{topic}-v*-*"), key=lambda p: p.stat().st_mtime, reverse=True)
    for run in (p for p in runs if p.is_dir()):
        updated_at = max(
            (dt.datetime.fromtimestamp(p.stat().st_mtime, dt.UTC)
             for p in (run, run / "final_status.json", run / "full_paper.journal_surface.json", run / "full_paper.md")
             if p.exists()),
            default=None,
        )
        if (
            updated_at
            and updated_at >= failure_at
            and _final_status_submission_ready(run)
            and _read_json(run / "full_paper.journal_surface.json").get("passed") is True
        ):
            return True
        if _surface_passes_current_finalizer(run):
            return True
    return False


def _declared_review_type(run: Path) -> str:
    return str(_read_json(run / "manifest.json").get("review_type") or "")


def _surface_passes_current_finalizer(run: Path) -> bool:
    """True when current finalizer code can clear a stale surface sidecar."""
    paper_path = run / "full_paper.md"
    if not paper_path.is_file():
        return False
    try:
        declared_words = _read_json(run / "manifest.json").get("total_words")
        if (
            isinstance(declared_words, int)
            and declared_words > 0
            and len(paper_path.read_text(encoding="utf-8").split()) > 2 * declared_words
        ):
            return False
        with tempfile.TemporaryDirectory(prefix="v3-surface-probe-") as tmp:
            probe = Path(tmp) / run.name
            shutil.copytree(run, probe)
            from agent.journal_finalizer import finalize_run
            from agent.journal_surface_gate import evaluate_journal_surface

            finalize_run(probe)
            paper = (probe / "full_paper.md").read_text(encoding="utf-8")
            return evaluate_journal_surface(
                paper,
                declared_review_type=_declared_review_type(probe),
            ).passed
    except (OSError, RuntimeError, ValueError, ImportError):
        return False


def _surface_repeat_topics(
    ledger_dir: Path, *, now: dt.datetime | None = None, runs_root: Path | None = None,
) -> set[str]:
    """Topics where the SAME deterministic gate failed >= SURFACE_REPEAT_THRESHOLD
    times within the failure-cooldown window. Re-rendering from scratch cannot
    change a deterministic gate's outcome, so skip the topic until the failure
    class changes (plan F: don't write R3 for a repeated surface failure).
    D_no_action gates (e.g. a cited retracted source) count too — "no action"
    means re-rendering can't fix it, which is exactly when to stop retrying.

    Reads the CUMULATIVE per-(topic, gate) timestamp log in the blocker
    histogram — the daily ledger is rewritten each run, so it cannot hold a
    cross-run count. Windowed so a topic auto-recovers once its corpus is fixed
    or a newer same-topic artifact passes the same readiness/surface checks.
    Universal — keyed on the gate code itself, not on any specific gate."""
    cutoff = (now or dt.datetime.now(dt.UTC)) - dt.timedelta(hours=RECENT_FAILURE_COOLDOWN_HOURS)
    repeats = _read_json(ledger_dir / BLOCKER_HISTOGRAM).get("repeats", {})
    out: set[str] = set()
    for key, stamps in repeats.items() if isinstance(repeats, dict) else []:
        topic, _, code = str(key).partition("\x1f")
        if (
            not topic
            or code in _NON_REPEAT_STATUSES
            or code in _PREFLIGHT_BLOCK_STATUSES
            or _failure_class(code).startswith("C_")
            or not isinstance(stamps, list)
        ):
            continue
        recent_stamps = [(t, str(s)) for s in stamps if (t := _parse_time(str(s))) and t >= cutoff]
        if recent_stamps and len(recent_stamps) >= SURFACE_REPEAT_THRESHOLD:
            latest_failure = max(t for t, _ in recent_stamps)
            if _surface_ready_after(topic, runs_root, latest_failure):
                continue
            out.add(topic)
    return out


def _recent_blocked_topics_by_status(
    ledger_dir: Path,
    statuses: Collection[str] | None = None,
    *,
    now: dt.datetime | None = None,
) -> set[str]:
    cutoff = (now or dt.datetime.now(dt.UTC)) - dt.timedelta(hours=RECENT_FAILURE_COOLDOWN_HOURS)
    repeats = _read_json(ledger_dir / BLOCKER_HISTOGRAM).get("repeats", {})
    out: set[str] = set()
    for key, stamps in repeats.items() if isinstance(repeats, dict) else []:
        topic, _, code = str(key).partition("\x1f")
        allowed = code in statuses if statuses is not None else code not in _NON_REPEAT_STATUSES
        if topic and allowed and isinstance(stamps, list) and any((t := _parse_time(str(s))) and t >= cutoff for s in stamps):
            out.add(topic)
    return out


def _recent_blocked_topics(ledger_dir: Path, *, now: dt.datetime | None = None) -> set[str]:
    return _recent_blocked_topics_by_status(ledger_dir, now=now)


def _recent_preflight_blocked_topics(ledger_dir: Path, *, now: dt.datetime | None = None) -> set[str]:
    return _recent_blocked_topics_by_status(ledger_dir, _PREFLIGHT_BLOCK_STATUSES, now=now)


def _recent_receipt_preflight_blocked_topics(ledger_dir: Path, *, now: dt.datetime | None = None) -> set[str]:
    return _recent_blocked_topics_by_status(ledger_dir, {"receipt_preflight_insufficient"}, now=now)


def _writer_gate_repeat_policy(
    ledger_dir: Path, *, now: dt.datetime | None = None,
) -> dict[str, dict[str, Any]]:
    cutoff = (now or dt.datetime.now(dt.UTC)) - dt.timedelta(hours=RECENT_FAILURE_COOLDOWN_HOURS)
    data = _read_json(ledger_dir / BLOCKER_HISTOGRAM)
    repeats = data.get("repeats", {})
    out: dict[str, dict[str, Any]] = {}
    for key, stamps in repeats.items() if isinstance(repeats, dict) else []:
        topic, _, code = str(key).partition("\x1f")
        if (
            not topic
            or not code
            or not _failure_class(code).startswith("C_")
            or not isinstance(stamps, list)
        ):
            continue
        recent = [s for s in stamps if (t := _parse_time(str(s))) and t >= cutoff]
        if len(recent) < WRITER_GATE_REPEAT_THRESHOLD:
            continue
        out[topic] = {
            "gate": code,
            "count": len(recent),
            "action": "skip_topic",
        }
    return out


def _corpus_repair_topics(ledger_dir: Path, *, now: dt.datetime | None = None) -> set[str]:
    return _recent_blocked_topics_by_status(ledger_dir, _CORPUS_REPAIR_STATUSES, now=now)


def _source_precision_repair_topics(ledger_dir: Path, *, now: dt.datetime | None = None) -> set[str]:
    return _recent_blocked_topics_by_status(ledger_dir, {_SOURCE_PRECISION_STATUS}, now=now)


def _source_precision_repair_publishable(repair: Mapping[str, Any]) -> bool:
    return (
        repair.get("status") == "source_precision_repaired"
        and int(repair.get("n_quant_claims") or 0) >= SOURCE_PRECISION_REPAIR_PUBLISH_MIN_QUANT
    )


def _source_precision_repair_checkable(repair: Mapping[str, Any]) -> bool:
    return (
        repair.get("status") == "source_precision_repaired"
        and int(repair.get("n_quant_claims") or 0) >= PREFLIGHT_MIN_QUANT_CLAIMS
    )


def _unrepairable_source_precision_topics(ledger_dir: Path, *, now: dt.datetime | None = None) -> set[str]:
    cutoff = (now or dt.datetime.now(dt.UTC)) - dt.timedelta(hours=RECENT_FAILURE_COOLDOWN_HOURS)
    out: set[str] = set()
    for path in ledger_dir.glob("*.json"):
        if path.name.startswith("_"):
            continue
        ledger = _read_json(path)
        started = _parse_time(str(ledger.get("started_at") or ""))
        if started is None or started < cutoff:
            continue
        for attempt in ledger.get("attempts", []):
            if not isinstance(attempt, dict):
                continue
            repair = attempt.get("source_precision_repair")
            if (
                isinstance(repair, dict)
                and repair.get("status") == "source_precision_repair_incomplete"
                and int(repair.get("n_quant_claims") or 0) == 0
                and attempt.get("topic")
            ):
                out.add(str(attempt["topic"]))
    return out


def _current_low_source_precision_topics(topics: list[str]) -> set[str]:
    out: set[str] = set()
    for topic in topics:
        ok, _status, _misses = _quant_claim_source_precision(topic, floor=SOURCE_TOPIC_REPAIR_FLOOR)
        if not ok:
            out.add(topic)
    return out


def _source_precision_retained_claim_count(topic: str) -> int:
    _ok, _status, misses = _quant_claim_source_precision(topic, floor=SOURCE_TOPIC_REPAIR_FLOOR)
    return max(0, _quant_claim_count(topic) - len(misses))


def _source_precision_repair_candidate(topic: str) -> bool:
    return _topic_has_quant_floor(topic)


def _revision_requests_source_precision(feedback: str) -> bool:
    text = str(feedback or "").lower()
    decision: bool | None = None
    for clause in re.split(
        r"[.;\n]+|\b(?:but|except|while|then)\b", text,
    ):
        if re.search(
            r"\b(?:keep|leave|preserve)\b.{0,60}"
            r"\b(?:source\s+bundle|bundle|corpus|all\s+(?:sources?|evidence))\b.{0,60}"
            r"\b(?:unchanged|intact|same)\b",
            clause,
        ):
            decision = False
            continue
        evidence = re.search(
            r"\b(?:sources?|evidence|stud(?:y|ies)|trials?|papers?|records?|corpus|bundle)\b",
            clause,
        )
        scope = re.search(
            r"\b(?:off[ -]?topic|unrelated|direct(?:ly)?|indirect|adjacent|"
            r"topic[ -]?specific|actually|only)\b",
            clause,
        )
        action = re.search(
            r"\b(?:clarify|exclude|fix|narrow|rebuild|reclassify|remove|replace|"
            r"reset|revise|swap|verify)\b",
            clause,
        )
        negated_action = re.search(
            r"\b(?:(?:do|does|should|must|shall|can|could|would)(?:\s+not|n['’]?t)|"
            r"don['’]?t|never|not\s+to|(?:there\s+is\s+)?no\s+need\s+to)\s+"
            r"(?:need\s+to\s+)?(?:[a-z-]+\s+){0,3}"
            r"(?:clarify|exclude|fix|narrow|rebuild|reclassify|"
            r"remove|replace|reset|revise|swap|verify)\b",
            clause,
        )
        if evidence and scope:
            if negated_action:
                decision = False
            elif action or "off-topic" in clause:
                decision = True
    return bool(decision)


def _topic_family(topic: str) -> str:
    """Grouping key for sibling topic slugs: the lead entity token (first alnum
    token >= 3 chars). A cooldown on one variant (e.g. ``nad_effects``) then also
    covers its siblings (``nad_biomarker_effects``, ``nad_metabolism_effects``)
    so the cycle stops walking every near-duplicate slug of an entity it just
    covered. Universal — derived from the slug, mirroring the entity used by
    ``_topic_retrieval_terms``; no per-topic or per-domain word lists."""
    tokens = [t for t in re.findall(r"[a-z0-9]+", topic.lower()) if len(t) >= 3]
    return tokens[0] if tokens else " ".join(str(topic).lower().split())


def _recent_submitted_topics(topics: list[str], ledger_dir: Path, *, now: dt.datetime | None = None) -> set[str]:
    """Candidate topics in cooldown: those whose *family* (lead entity) was
    submitted within PUBLISHED_TOPIC_COOLDOWN_DAYS. Family-level so distinct
    sibling slugs of a just-covered entity are held too (and re-selectable once
    the window lapses), not just the exact slug."""
    path = ledger_dir.parent / submit_bridge.LEDGER_DIR / "_submitted_fingerprints.json"
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        rows = []
    cutoff = (now or dt.datetime.now(dt.UTC)) - dt.timedelta(days=PUBLISHED_TOPIC_COOLDOWN_DAYS)
    recent_families: set[str] = set()
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        topic = str(row.get("topic") or "")
        when = _parse_time(str(row.get("date") or row.get("submitted_at") or ""))
        if topic and when and when >= cutoff:
            recent_families.add(_topic_family(topic))
    return {topic for topic in topics if _topic_family(topic) in recent_families}


def _published_topics(topics: list[str], markers: set[str], ledger_dir: Path | None = None) -> set[str]:
    """Topics the fresh cycle must skip: (1) recently-submitted families still in
    cooldown (rate-limit, expires — covers sibling slugs of the same entity), and
    (2) ALREADY-PUBLISHED ones (permanent).

    The remote-title exclusion was previously gated on `ledger_dir is None`, but
    select_topic — the only caller — always passes a ledger_dir, so that branch
    never ran: published topics were excluded only while their submission
    cooldown held, then became re-selectable, re-synthesized, and dedup'd at
    submit (a fresh non-revision re-run of a published title always returns
    duplicate_remote_publication). Remote-published topic markers also cover
    variants that differ only by generic publication-shape suffixes, without
    broad substring matching. Re-publishing an updated paper is the revise cycle's job."""
    out = _recent_submitted_topics(topics, ledger_dir) if ledger_dir else set()
    topic_markers = {m.removeprefix("topic:") for m in markers if m.startswith("topic:")}
    remote_topic_keys = {
        key for marker in topic_markers if (key := _publication_topic_key(marker))
    }
    title_markers = {m.removeprefix("title:") for m in markers if m.startswith("title:")}
    title_markers |= {
        marker.removeprefix("title:")
        for title in list(title_markers)
        for marker in submit_bridge._title_markers(title)
    }
    for topic in topics:
        normalized_topic = submit_bridge._normalized_key(topic)
        publication_key = _publication_topic_key(normalized_topic)
        if normalized_topic in topic_markers or (
            publication_key and publication_key in remote_topic_keys
        ):
            out.add(topic)
            continue
        title_keys = {
            submit_bridge._normalized_key(topic.replace("_", " ")),
            submit_bridge._normalized_key(submit_bridge._display_topic(topic)),
        }
        if title_keys & title_markers:
            out.add(topic)
    return out


def _publication_topic_key(topic: str) -> tuple[str, ...]:
    """Normalize only generic publication-shape suffixes, preserving entities."""
    tokens = re.findall(r"[a-z0-9]+", topic.lower())
    if tokens and tokens[-1] in {"effect", "effects"}:
        tokens.pop()
        if tokens and tokens[-1] in {"training", "use"}:
            tokens.pop()
    elif tokens and tokens[-1] in {"rate", "rates"}:
        tokens.pop()
    return tuple(tokens)


def _review_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        rows = payload.get("records") or payload.get("reviews") or payload.get("decisions")
        if not rows:
            rows = payload.get("props", {}).get("pageProps", {}).get("records")
        return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
    return [row for row in payload if isinstance(row, dict)] if isinstance(payload, list) else []


def _review_ts(row: dict[str, Any]) -> dt.datetime:
    """Parse a review row's decision timestamp for latest-wins comparison.
    Unparseable timestamps sort oldest so they never mask a dated decision."""
    raw = str(
        row.get("reviewedAt")
        or row.get("reviewed_at")
        or row.get("createdAt")
        or row.get("created_at")
        or row.get("publishedAt")
        or row.get("published_at")
        or ""
    )
    return _parse_review_time(raw) or dt.datetime.min.replace(tzinfo=dt.UTC)


def _submitted_record_ts(record: dict[str, Any]) -> dt.datetime | None:
    return _parse_time(str(record.get("submitted_at") or record.get("date") or ""))


def _latest_reviews_by_title(url: str | None = None) -> tuple[dict[str, dict[str, Any]], str | None]:
    """Latest research_paper review per paper title for this agent. Researka
    assigns a new artifactId per submission, so latest-wins by reviewedAt drops
    decisions a newer one supersedes. Shared by revise-routing and
    reject-tracking so both read the same authoritative current decision."""
    target = str(url or os.getenv("RESEARKA_REVIEWS_URL", "https://researka.org/reviews"))
    agent_ids = {*V3_AGENT_IDS, os.getenv("RESEARKA_AGENT_SLUG_V3", ""), os.getenv("AGENT_ID", "")}
    agent_ids.discard("")
    try:
        with urllib.request.urlopen(urllib.request.Request(target, headers={"Accept": "text/html,application/json"}), timeout=30) as response:
            text = response.read().decode("utf-8", errors="replace")
        if "<script" in text:
            match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', text, re.S)
            payload = json.loads(match.group(1)) if match else {}
        else:
            payload = json.loads(text)
    except (OSError, urllib.error.URLError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {}, f"{type(exc).__name__}: {exc}"
    rows = _review_rows(payload)
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        if str(row.get("artifactType") or row.get("artifact_type") or "") != "research_paper":
            continue
        if agent_ids and str(row.get("agentId") or row.get("agent_id") or "") not in agent_ids:
            continue
        key = submit_bridge._title_marker(str(row.get("title") or ""))
        if key and (key not in latest or _review_ts(row) > _review_ts(latest[key])):
            latest[key] = row
    if mismatch := _review_agent_mismatch(rows, agent_ids):
        return {}, mismatch
    return latest, None


def _submission_decision_url(submission_id: str) -> str:
    base = os.getenv("RESEARKA_URL", "https://api.researka.org").rstrip("/")
    return f"{base}/submissions/{urllib.parse.quote(submission_id.strip())}/decision"


def _fetch_submission_decision(submission_id: str) -> tuple[dict[str, Any] | None, str | None]:
    token, _token_env = submit_bridge._token()
    headers = {"Accept": "application/json"}
    if token:
        headers.update({"Authorization": f"Bearer {token}", "x-api-key": token})
    try:
        req = urllib.request.Request(_submission_decision_url(submission_id), headers=headers)
        with urllib.request.urlopen(req, timeout=SUBMISSION_DECISION_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None, None
        return None, f"HTTPError:{exc.code}"
    except (OSError, urllib.error.URLError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, f"{type(exc).__name__}: {exc}"
    return payload if isinstance(payload, dict) else None, None


def _submitted_submission_decisions_by_title(runs_root: Path = RUNS) -> tuple[dict[str, dict[str, Any]], str | None]:
    submitted_path = runs_root / submit_bridge.LEDGER_DIR / "_submitted_fingerprints.json"
    rows = submit_bridge._ledger_rows(submitted_path)
    latest: dict[str, dict[str, Any]] = {}
    first_error: str | None = None
    updates: dict[str, dict[str, Any]] = {}
    missing = object()
    latest_by_topic: dict[str, dict[str, Any]] = {}
    for row in reversed(rows):
        latest_by_topic.setdefault(str(row.get("topic") or row.get("submission_id") or row.get("run")), row)
    for record in latest_by_topic.values():
        submission_id = str(record.get("submission_id") or "").strip()
        run = runs_root / str(record.get("run") or "")
        paper = run / "full_paper.md"
        if not submission_id or not paper.exists():
            continue
        payload, err = _fetch_submission_decision(submission_id)
        first_error = first_error or err
        if not payload:
            continue
        decision_payload: dict[str, Any] = payload

        def present(*names: str) -> Any:
            return next(
                (
                    decision_payload[name]
                    for name in names
                    if name in decision_payload and decision_payload[name] is not None
                ),
                missing,
            )

        fields = {
            "decision_status": ("status",),
            "decision": ("decision",),
            "decision_object_id": (
                "decision_object_id", "decisionObjectId", "decision_id", "decisionId", "id",
            ),
            "review_id": ("review_id", "reviewId"),
            "reviewed_at": (
                "reviewedAt", "reviewed_at", "createdAt", "created_at", "updatedAt", "updated_at",
            ),
            "required_revisions": ("required_revisions", "requiredRevisions"),
            "review_summary": ("review_summary", "reviewSummary"),
            "failure_category": ("failure_category", "failureCategory"),
            "publication_status": ("publication_status", "publicationStatus"),
            "publication": ("publication",),
        }
        persisted = {
            key: value
            for key, names in fields.items()
            if (value := present(*names)) is not missing
        }
        if (decision_value := persisted.get("decision")) is not None:
            persisted["remote_revision_requested"] = (
                str(decision_value).strip().lower() == "revise"
            )
        current_decision = str(record.get("decision") or "").strip()
        incoming_decision = str(persisted.get("decision") or "").strip()
        if (
            current_decision
            and incoming_decision
            and _review_ts(record) > _review_ts(persisted)
        ):
            persisted = {}
            decision_payload = {}
        if persisted:
            updates[submission_id] = persisted
        effective = {**record, **persisted}
        title = submit_bridge._paper_title(paper)
        row = {
            "artifactType": "research_paper",
            "agentId": submit_bridge._agent_slug(),
            "artifactId": (
                effective.get("decision_object_id")
            ),
            "submissionId": submission_id,
            "title": title,
            "topic": effective.get("topic") or submit_bridge._run_topic(run),
            "decision": effective.get("decision"),
            "reviewedAt": (
                effective.get("reviewed_at")
                or effective.get("submitted_at")
                or effective.get("date")
            ),
            "required_revisions": effective.get("required_revisions") or [],
            "review_summary": effective.get("review_summary"),
            "publication": effective.get("publication"),
            "failure_category": effective.get("failure_category"),
            "notes": decision_payload.get("notes") or effective.get("notes"),
            "resubmission": (
                decision_payload.get("resubmission") or effective.get("resubmission")
            ),
        }
        key = submit_bridge._title_marker(title)
        if key and (key not in latest or _review_ts(row) > _review_ts(latest[key])):
            latest[key] = row
    if updates:
        def merge(current: list[dict[str, Any]]) -> None:
            for current_record in current:
                submission_id = str(current_record.get("submission_id") or "").strip()
                if submission_id in updates:
                    update = dict(updates[submission_id])
                    current_decision = str(current_record.get("decision") or "").strip()
                    incoming_decision = str(update.get("decision") or "").strip()
                    if (
                        current_decision
                        and incoming_decision
                        and _review_ts(current_record) > _review_ts(update)
                    ):
                        continue
                    if (
                        current_decision
                        and not incoming_decision
                        and update.get("decision_status") != "complete"
                    ):
                        update.pop("decision_status", None)
                    current_record.update(update)

        _update_json_list(submitted_path, merge)
    return latest, None if latest else first_error


def _review_day_key(row: dict[str, Any]) -> str:
    raw = str(
        row.get("reviewedAt")
        or row.get("reviewed_at")
        or row.get("createdAt")
        or row.get("created_at")
        or row.get("publishedAt")
        or row.get("published_at")
        or ""
    ).strip()
    if DAY_KEY_RE.fullmatch(raw):
        return raw
    ts = _review_ts(row)
    if ts == dt.datetime.min.replace(tzinfo=dt.UTC):
        return ""
    timezone: dt.tzinfo
    try:
        timezone = ZoneInfo(os.getenv("RESEARCH_AGENT_CYCLE_TIMEZONE", DEFAULT_CYCLE_TIMEZONE))
    except ZoneInfoNotFoundError:
        timezone = dt.UTC
    return ts.astimezone(timezone).date().isoformat()


def _should_replace_review_row(existing: dict[str, Any], candidate: dict[str, Any]) -> bool:
    existing_ts = _review_ts(existing)
    candidate_ts = _review_ts(candidate)
    if candidate_ts > existing_ts:
        return True
    if candidate_ts == existing_ts:
        return _revision_detail_score(candidate) > _revision_detail_score(existing)
    return (
        _review_day_key(candidate) == _review_day_key(existing)
        and str(candidate.get("decision") or "").lower() == str(existing.get("decision") or "").lower()
        and _revision_detail_score(candidate) > _revision_detail_score(existing)
    )


def _merge_latest_by_title(*sources: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for source in sources:
        for key, row in source.items():
            if key and (key not in latest or _should_replace_review_row(latest[key], row)):
                latest[key] = row
    return latest


def _latest_public_decisions_by_title() -> tuple[dict[str, dict[str, Any]], str | None]:
    reviews, review_error = _latest_reviews_by_title()
    papers, paper_error = _latest_reviews_by_title(os.getenv("RESEARKA_PAPERS_URL", "https://researka.org/papers"))
    latest = _merge_latest_by_title({} if review_error else reviews, {} if paper_error else papers)
    if latest:
        return latest, None
    return {}, review_error or paper_error


def _public_decision_markers(rows: dict[str, dict[str, Any]]) -> set[str]:
    markers: set[str] = set()
    for row in rows.values():
        decision = str(row.get("decision") or "").strip().lower()
        status = str(row.get("status") or "").strip().lower()
        if decision not in {"accept", "accepted"} and status not in {"accepted", "public", "published"}:
            continue
        title = str(row.get("title") or "")
        if title:
            markers.update(submit_bridge._title_markers(title))
        topic = row.get("topic")
        if isinstance(topic, str) and topic.strip():
            markers.add(submit_bridge._topic_marker(topic))
        submission_id = row.get("submissionId") or row.get("submission_id")
        if isinstance(submission_id, str) and submission_id.strip():
            markers.add(submit_bridge._submission_marker(submission_id))
    return markers


def _record_review_decisions(ledger_dir: Path, latest: dict[str, dict[str, Any]]) -> None:
    if not latest:
        return
    path = ledger_dir / DECISIONS_BY_DAY
    data = _read_json(path)
    days = data.get("days")
    if not isinstance(days, dict):
        days = {}
    for row in latest.values():
        ts = _review_ts(row)
        day_key = (ts if ts != dt.datetime.min.replace(tzinfo=dt.UTC) else dt.datetime.now(dt.UTC)).date().isoformat()
        day = days.setdefault(day_key, {})
        records = day.setdefault("records", [])
        if not isinstance(records, list):
            records = []
        artifact_id = str(row.get("artifactId") or row.get("artifact_id") or "")
        title = str(row.get("title") or "")
        record_id = artifact_id or submit_bridge._title_marker(title)
        entry = {
            "id": record_id,
            "title": title,
            "decision": row.get("decision"),
            "status": row.get("status"),
            "reviewed_at": (
                row.get("reviewedAt")
                or row.get("reviewed_at")
                or row.get("createdAt")
                or row.get("created_at")
                or row.get("publishedAt")
                or row.get("published_at")
            ),
        }
        records = [
            existing for existing in records
            if not (isinstance(existing, dict) and existing.get("id") == record_id)
        ] + [entry]
        counts = Counter(str(record.get("decision") or "unknown").lower() for record in records if isinstance(record, dict))
        day["records"] = records
        day["counts"] = dict(sorted(counts.items()))
    data["days"] = days
    data["updated_at"] = dt.datetime.now(dt.UTC).isoformat()
    _write_json(path, data)
    _record_revise_reasons(ledger_dir, latest)


def _record_revise_reasons(ledger_dir: Path, latest: dict[str, dict[str, Any]]) -> None:
    rows: list[dict[str, Any]] = []
    bucket_counts: Counter[str] = Counter()
    for row in sorted(latest.values(), key=_review_ts):
        if str(row.get("decision") or "").lower() != "revise":
            continue
        asks = []
        for text in _required_revision_items(row):
            bucket = _revise_reason_bucket(text)
            asks.append({"bucket": bucket, "text": text})
            bucket_counts[bucket] += 1
        if asks:
            rows.append({
                "id": str(row.get("artifactId") or row.get("artifact_id") or submit_bridge._title_marker(str(row.get("title") or ""))),
                "title": str(row.get("title") or ""),
                "reviewed_at": row.get("reviewedAt") or row.get("reviewed_at"),
                "asks": asks,
            })
    _write_json(ledger_dir / REVISE_REASONS, {
        "updated_at": dt.datetime.now(dt.UTC).isoformat(),
        "total_reviews": len(rows),
        "total_revision_asks": sum(bucket_counts.values()),
        "bucket_counts": dict(sorted(bucket_counts.items())),
        "reviews": rows,
    })


def _remote_revision_requests(url: str | None = None, *, runs_root: Path = RUNS) -> tuple[list[dict[str, Any]], str | None]:
    latest, err = _latest_reviews_by_title(url)
    if err:
        return [], err
    if url is None:
        direct, direct_err = _submitted_submission_decisions_by_title(runs_root)
        latest = _merge_latest_by_title(latest, direct)
        err = direct_err if not latest else None
    out: list[dict[str, Any]] = []
    for row in latest.values():
        required = _actionable_revisions(row)
        notes = " ".join(map(str, raw_notes)) if isinstance(raw_notes := row.get("notes"), list) else str(raw_notes or "")
        retry_unchanged = (
            not required
            and isinstance(resubmission := row.get("resubmission"), dict)
            and resubmission.get("allowed") is True
            and (
                str(row.get("failure_category") or "") == "source_authority_available"
                or all(token in notes.lower() for token in ("source", "verification", "unavailable"))
            )
        )
        if str(row.get("decision") or "").lower() != "revise" or (not required and not retry_unchanged):
            continue
        request = {
            "artifactId": row.get("artifactId") or row.get("artifact_id"),
            "submissionId": row.get("submissionId") or row.get("submission_id"),
            "title": row.get("title"),
            "topic": row.get("topic"),
            "reviewedAt": (
                row.get("reviewedAt")
                or row.get("reviewed_at")
                or row.get("createdAt")
                or row.get("created_at")
                or row.get("publishedAt")
                or row.get("published_at")
            ),
            "feedback": " ".join("; ".join(required).split())[:4000],
        }
        if required:
            request["required_revisions"] = required
        if retry_unchanged:
            request.update({"retry_unchanged": True, "failure_category": row.get("failure_category")})
        out.append(request)
    return sorted(out, key=_review_ts, reverse=True), None


def _handled_revision_ids(ledger_dir: Path, active_requests: list[dict[str, Any]] | None = None) -> set[str]:
    """Revision keys (paper-title markers) that have hit the per-paper round
    cap for the active reviewer request. A paper may be re-processed up to
    MAX_REVISE_ROUNDS times per request; older handled rows do not exhaust a
    newer reviewedAt for the same title. Counting is by title — Researka mints
    a new artifactId per submission, so artifactId counts never accumulate."""
    data = _read_json(ledger_dir / HANDLED_REVISIONS)
    rows = data.get("handled")
    if not isinstance(rows, list):
        return set()
    active_reviewed = {
        _revision_key(row): _parse_review_time(str(row.get("reviewedAt") or row.get("reviewed_at") or ""))
        for row in (active_requests or [])
    }
    active_submission_ids: dict[str, set[str]] = {}
    for row in active_requests or []:
        submission_id = str(row.get("submissionId") or row.get("submission_id") or "").strip()
        if submission_id:
            active_submission_ids.setdefault(_revision_key(row), set()).add(submission_id)

    def _row_applies_to_active_request(row: dict[str, Any]) -> bool:
        reviewed_at = active_reviewed.get(_revision_key(row))
        if reviewed_at is None:
            return True
        handled_at = _parse_time(str(row.get("handled_at") or ""))
        return bool(handled_at and handled_at >= reviewed_at)

    def _submitted_row_is_superseded_by_active_decision(row: dict[str, Any]) -> bool:
        if str(row.get("status") or "") != "submitted_to_researka":
            return False
        active_ids = active_submission_ids.get(_revision_key(row))
        if not active_ids:
            return False
        row_submission_id = str(row.get("submissionId") or row.get("submission_id") or "").strip()
        return not row_submission_id or row_submission_id in active_ids

    def _counts_toward_current_round_cap(row: dict[str, Any]) -> bool:
        status = str(row.get("status") or "")
        return (
            status not in _RETRYABLE_REVISION_STATUSES
            or str(row.get("repair_epoch") or "") == str(REVISION_REPAIR_EPOCH)
        )

    counts = Counter(
        submit_bridge._title_marker(str(row.get("title") or ""))
        for row in rows
        if (
            isinstance(row, dict)
            and row.get("title")
            and _row_applies_to_active_request(row)
            and not _submitted_row_is_superseded_by_active_decision(row)
            and _counts_toward_current_round_cap(row)
        )
    )
    terminal = {
        submit_bridge._title_marker(str(row.get("title") or ""))
        for row in rows
        if (
            isinstance(row, dict)
            and row.get("title")
            and (
                str(row.get("status") or "") in _TERMINAL_REVISION_STATUSES
                or (
                    str(row.get("status") or "") in _ACTIVE_REVIEW_TERMINAL_REVISION_STATUSES
                    and _row_applies_to_active_request(row)
                )
            )
        )
    }
    handled = terminal | {key for key, n in counts.items() if n >= MAX_REVISE_ROUNDS}
    for row in rows:
        if not isinstance(row, dict) or row.get("status") != "submitted_to_researka":
            continue
        if _submitted_row_is_superseded_by_active_decision(row):
            continue
        key = _revision_key(row)
        handled_at = _parse_time(str(row.get("handled_at") or ""))
        reviewed_at = active_reviewed.get(key)
        if reviewed_at is None or (handled_at and handled_at >= reviewed_at):
            handled.add(key)
    return handled


def _handled_revision_statuses(ledger_dir: Path, key: str, reviewed_at: str = "") -> tuple[str, ...]:
    rows = _read_json(ledger_dir / HANDLED_REVISIONS).get("handled")
    if not isinstance(rows, list):
        return ()
    reviewed = _parse_review_time(reviewed_at)
    statuses: list[str] = []
    for row in rows:
        if not isinstance(row, dict) or str(row.get("key") or _revision_key(row)) != key:
            continue
        handled_at = _parse_time(str(row.get("handled_at") or ""))
        if reviewed and handled_at and handled_at < reviewed:
            continue
        status = str(row.get("status") or "")
        if (
            status in _RETRYABLE_REVISION_STATUSES
            and str(row.get("repair_epoch") or "") != str(REVISION_REPAIR_EPOCH)
        ):
            continue
        if status:
            statuses.append(status)
    return tuple(statuses)


def _revision_key(row: dict[str, Any]) -> str:
    # Title-first so the round cap is per-paper, not per-submission: Researka
    # assigns a new artifactId per submission, which would otherwise reset the
    # count every round and let a never-converging paper loop forever.
    return submit_bridge._title_marker(str(row.get("title") or "")) or str(row.get("artifactId") or row.get("submissionId") or "")


def _compact_handled_revision_rows(rows: list[Any]) -> list[dict[str, Any]]:
    def _row_time(row: dict[str, Any]) -> dt.datetime:
        return _parse_time(str(row.get("handled_at") or "")) or dt.datetime.min.replace(tzinfo=dt.UTC)

    def _round_priority(row: dict[str, Any]) -> tuple[bool, dt.datetime]:
        status = str(row.get("status") or "")
        current = (
            status not in _RETRYABLE_REVISION_STATUSES
            or str(row.get("repair_epoch") or "") == str(REVISION_REPAIR_EPOCH)
        )
        return current, _row_time(row)

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = _revision_key(row) or str(row.get("key") or "")
        if key:
            grouped.setdefault(key, []).append({**row, "key": key})
    compacted: list[dict[str, Any]] = []
    durable_statuses = (
        _TERMINAL_REVISION_STATUSES
        | _ACTIVE_REVIEW_TERMINAL_REVISION_STATUSES
        | {"submitted_to_researka"}
    )
    for group in grouped.values():
        durable: dict[str, dict[str, Any]] = {}
        recent: list[dict[str, Any]] = []
        for row in group:
            status = str(row.get("status") or "")
            if status in durable_statuses:
                prior = durable.get(status)
                if prior is None or _row_time(row) >= _row_time(prior):
                    durable[status] = row
            else:
                recent.append(row)
        selected = [
            *sorted(recent, key=_round_priority)[-MAX_REVISE_ROUNDS:],
            *durable.values(),
        ]
        compacted.extend(selected)
    return sorted(compacted, key=_row_time)


def _mark_revision_handled(ledger_dir: Path, row: dict[str, Any], *, status: str) -> None:
    path = ledger_dir / HANDLED_REVISIONS
    data = _read_json(path)
    raw_rows = data.get("handled")
    rows: list[dict[str, Any]] = raw_rows if isinstance(raw_rows, list) else []
    rows.append({
        "key": _revision_key(row),
        "status": status,
        "title": row.get("title"),
        "artifactId": row.get("artifactId") or row.get("artifact_id"),
        "submissionId": row.get("submissionId") or row.get("submission_id"),
        "reviewedAt": row.get("reviewedAt") or row.get("reviewed_at"),
        "repair_epoch": REVISION_REPAIR_EPOCH,
        "handled_at": dt.datetime.now(dt.UTC).isoformat(),
    })
    _write_json(path, {"handled": _compact_handled_revision_rows(rows)})


def _revision_submission_row(
    row: dict[str, Any],
    submission_markers: Collection[str],
) -> dict[str, Any]:
    submission_ids = sorted(
        marker.removeprefix("submission:")
        for marker in submission_markers
        if marker.startswith("submission:")
    )
    return {**row, "submissionId": submission_ids[0]} if submission_ids else row


def _pending_remote_revision(
    runs_root: Path,
    ledger_dir: Path,
    *,
    loader: RevisionLoader | None = None,
    published_loader: PublishedLoader | None = None,
    exclude_keys: set[str] | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    rows, error = loader() if loader else _remote_revision_requests(runs_root=runs_root)
    if error:
        return None, error
    if exclude_keys:
        rows = [row for row in rows if _revision_key(row) not in exclude_keys]
    handled = _handled_revision_ids(ledger_dir, rows)
    remote_seen: set[str] = set()
    if published_loader is not None:
        remote_seen, _remote_error = published_loader()
    submitted = runs_root / submit_bridge.LEDGER_DIR / "_submitted_fingerprints.json"
    raw_records = json.loads(submitted.read_text(encoding="utf-8")) if submitted.exists() else []
    records: list[Any] = raw_records if isinstance(raw_records, list) else []
    for request in rows:
        request_key = _revision_key(request)
        title_marker = submit_bridge._title_marker(str(request.get("title") or ""))
        request_topic = submit_bridge._normalized_key(str(request.get("topic") or ""))
        matches: list[tuple[dict[str, Any], Path, str]] = []
        for record in records if isinstance(records, list) else []:
            if not isinstance(record, dict):
                continue
            run = runs_root / str(record.get("run") or "")
            paper = run / "full_paper.md"
            if not paper.exists():
                continue
            record_topic = str(record.get("topic") or submit_bridge._run_topic(run))
            markers = {
                str(record.get("fingerprint") or ""),
                submit_bridge._title_marker(submit_bridge._paper_title(paper)),
            }
            if title_marker in markers or (request_topic and request_topic == submit_bridge._normalized_key(record_topic)):
                matches.append((record, run, record_topic))
        request_submission_id = str(request.get("submissionId") or request.get("submission_id") or "").strip()
        request_reviewed = _review_ts(request)
        if any(
            str(record.get("submission_id") or "").strip() != request_submission_id
            and _submitted_record_has_pending_decision(record)
            and (
                (record_ts := _submitted_record_ts(record)) is None
                or request_reviewed == dt.datetime.min.replace(tzinfo=dt.UTC)
                or record_ts >= request_reviewed
            )
            for record, _run, _topic in matches
        ):
            continue
        if request_submission_id:
            exact_matches = [
                match for match in matches
                if str(match[0].get("submission_id") or "").strip() == request_submission_id
            ]
            if exact_matches:
                matches = exact_matches
        if any(_submitted_record_is_published(record, run / "full_paper.md", remote_seen) for record, run, _topic in matches):
            continue
        if request_key in handled:
            handled_status_rows = _handled_revision_statuses(
                ledger_dir, request_key, str(request.get("reviewedAt") or request.get("reviewed_at") or ""),
            )
            retryable_failures = sum(
                status in _RETRYABLE_REVISION_STATUSES for status in handled_status_rows
            )
            if retryable_failures >= MAX_REVISE_ROUNDS:
                continue
            handled_statuses = set(handled_status_rows)
            current_code_repairs_surface = (
                "terminal_surface_repeat" in handled_statuses
                and bool(matches)
                and _surface_passes_current_finalizer(matches[-1][1])
            )
            current_code_clears_domain_scope = (
                "terminal_domain_scope_mismatch" in handled_statuses
                and not _revision_requests_domain_scope_reset(str(request.get("feedback") or ""))
            )
            current_code_clears_source_manifest = (
                "terminal_revision_source_manifest_unavailable" in handled_statuses
                and _revision_requests_source_precision(str(request.get("feedback") or ""))
            )
            if not (
                current_code_repairs_surface
                or current_code_clears_domain_scope
                or current_code_clears_source_manifest
            ):
                continue
            reopenable = {
                "terminal_surface_repeat",
                "terminal_domain_scope_mismatch",
                "terminal_revision_source_manifest_unavailable",
            }
            hard_terminal = (
                handled_statuses
                & (_TERMINAL_REVISION_STATUSES | _ACTIVE_REVIEW_TERMINAL_REVISION_STATUSES)
                - reopenable
            )
            if hard_terminal:
                continue
        if matches:
            record, run, record_topic = max(
                matches,
                key=lambda match: _submitted_record_ts(match[0]) or dt.datetime.min.replace(tzinfo=dt.UTC),
            )
            # Retry external verifier outages across timer windows, bounded by
            # the normal revise-round cap. The count lives in the existing
            # revision sidecar, so no separate queue or state file is needed.
            if request.get("retry_unchanged"):
                raw_count = (prior := _read_json(run / "researka_revision_request.json")).get("unchanged_retry_count")
                prior_count = raw_count if type(raw_count) is int and raw_count >= 0 else int(bool(prior.get("retry_unchanged")))
                if prior_count >= MAX_REVISE_ROUNDS:
                    continue
                request["unchanged_retry_count"] = prior_count + 1
            request["topic"], request["source_run"] = record_topic, run.name
            return request, None
    return None, None


def _submitted_record_has_pending_decision(record: dict[str, Any]) -> bool:
    submission_id = str(record.get("submission_id") or "").strip()
    if not submission_id:
        return False
    payload, err = _fetch_submission_decision(submission_id)
    if err or not payload:
        return False
    if str(payload.get("decision") or "").strip():
        return False
    return str(payload.get("status") or "").strip().lower() in {
        "pending",
        "queued",
        "running",
        "processing",
        "reviewing",
        "submitted",
    }


def _pending_remote_revision_topics(
    runs_root: Path,
    ledger_dir: Path,
    *,
    loader: RevisionLoader | None = None,
    published_loader: PublishedLoader | None = None,
) -> tuple[set[str], str | None]:
    rows, error = loader() if loader else _remote_revision_requests(runs_root=runs_root)
    if error:
        return set(), error
    handled = _handled_revision_ids(ledger_dir, rows)
    remote_seen: set[str] = set()
    if published_loader is not None:
        remote_seen, _remote_error = published_loader()
    submitted = runs_root / submit_bridge.LEDGER_DIR / "_submitted_fingerprints.json"
    raw_records = json.loads(submitted.read_text(encoding="utf-8")) if submitted.exists() else []
    records: list[Any] = raw_records if isinstance(raw_records, list) else []
    out: set[str] = set()
    for request in rows:
        if _revision_key(request) in handled:
            continue
        title_marker = submit_bridge._title_marker(str(request.get("title") or ""))
        request_topic = submit_bridge._normalized_key(str(request.get("topic") or ""))
        matched_topics: set[str] = set()
        matched_published = False
        for record in records:
            if not isinstance(record, dict):
                continue
            run = runs_root / str(record.get("run") or "")
            paper = run / "full_paper.md"
            if not paper.exists():
                continue
            record_topic = str(record.get("topic") or submit_bridge._run_topic(run))
            if title_marker == submit_bridge._title_marker(submit_bridge._paper_title(paper)) or (
                request_topic and request_topic == submit_bridge._normalized_key(record_topic)
            ):
                matched_topics.add(record_topic)
                matched_published = matched_published or _submitted_record_is_published(record, paper, remote_seen)
        if not matched_published:
            out.update(matched_topics)
    return out, None


def _submitted_record_is_published(record: dict[str, Any], paper: Path, remote_seen: set[str]) -> bool:
    markers = {
        str(record.get("fingerprint") or ""),
        str(record.get("paper_sha256") or ""),
        str(record.get("content_hash") or ""),
        str(record.get("submission_payload_hash") or ""),
        str(record.get("submission_identity_key") or ""),
    }
    submission_id = record.get("submission_id")
    if isinstance(submission_id, str) and submission_id.strip():
        markers.add(submit_bridge._submission_marker(submission_id))
    if paper.exists():
        markers.add(submit_bridge._sha256(paper))
        title = submit_bridge._paper_title(paper)
        if title:
            markers.add(submit_bridge._title_marker(title))
    return bool({marker for marker in markers if marker} & remote_seen)


def _terminal_topics(
    runs_root: Path,
    *,
    loader: Callable[[], tuple[dict[str, dict[str, Any]], str | None]] | None = None,
) -> set[str]:
    """Topics whose LATEST Researka review is terminal — a reject, or a revise
    with no actionable required revisions (a publication-overlap flag or "no
    revisions required"). Excluding these from selection stops the bot from
    re-synthesising and re-submitting a paper it cannot improve by re-rendering,
    until a newer decision supersedes it. Title -> submitted-run -> topic
    matching mirrors _pending_remote_revision; universal, no per-topic knowledge."""
    latest, error = (loader or _latest_reviews_by_title)()
    if error:
        return set()
    terminal_markers = {
        submit_bridge._title_marker(str(row.get("title") or ""))
        for row in latest.values()
        if row.get("title") and (
            (decision := str(row.get("decision") or "").lower()) == "reject"
            or (decision == "revise" and not _actionable_revisions(row))
        )
    }
    if not terminal_markers:
        return set()
    submitted = runs_root / submit_bridge.LEDGER_DIR / "_submitted_fingerprints.json"
    raw_records = json.loads(submitted.read_text(encoding="utf-8")) if submitted.exists() else []
    topics: set[str] = set()
    for record in raw_records if isinstance(raw_records, list) else []:
        if not isinstance(record, dict):
            continue
        run = runs_root / str(record.get("run") or "")
        paper = run / "full_paper.md"
        if paper.exists() and submit_bridge._title_marker(submit_bridge._paper_title(paper)) in terminal_markers:
            topics.add(str(record.get("topic") or submit_bridge._run_topic(run)))
    return topics


def _poll_remote_revision(
    runs_root: Path,
    ledger_dir: Path,
    *,
    loader: RevisionLoader | None = None,
    published_loader: PublishedLoader | None = None,
    seconds: int = DECISION_POLL_SECONDS,
    interval_seconds: int = DECISION_POLL_INTERVAL_SECONDS,
    sleeper: Sleeper = time.sleep,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    meta: dict[str, Any] = {
        "checked": seconds > 0,
        "seconds": max(0, seconds),
        "interval_seconds": max(1, interval_seconds),
        "attempts": 0,
    }
    if seconds <= 0:
        return None, meta
    deadline = time.monotonic() + seconds
    last_error = None
    while True:
        meta["attempts"] = int(meta["attempts"]) + 1
        revision, error = _pending_remote_revision(
            runs_root,
            ledger_dir,
            loader=loader,
            published_loader=published_loader,
        )
        if revision:
            meta.update({"matched": True})
            return revision, meta
        last_error = error or last_error
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            meta.update({"matched": False})
            if last_error:
                meta["last_error"] = last_error
            return None, meta
        sleeper(min(float(meta["interval_seconds"]), remaining))


def _publication_track_topic(topic: str) -> bool:
    try:
        data = tomllib.loads((TOPIC_PACKS / f"{topic}.toml").read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        record = _read_json(TOPIC_PACKS_DB / topic / "latest.json")
        pack_data = record.get("pack_data")
        data = pack_data if isinstance(pack_data, dict) else {}
        if data and not generated_pack_publishable(record, peer_records=_generated_pack_records()):
            return False
    if not data:
        return False
    try:
        return parse_review_type(str(data.get("review_type") or "")) not in COMPACT_REVIEW_TYPES
    except ValueError:
        return False


def _compact_review_topic(topic: str) -> bool:
    return _topic_declared_review_type(topic) in COMPACT_REVIEW_TYPES


def _topic_declared_review_type(topic: str) -> str:
    try:
        data = tomllib.loads((TOPIC_PACKS / f"{topic}.toml").read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        record = _read_json(TOPIC_PACKS_DB / topic / "latest.json")
        pack_data = record.get("pack_data")
        data = pack_data if isinstance(pack_data, dict) else {}
    try:
        return parse_review_type(str(data.get("review_type") or ""))
    except ValueError:
        return "thin_corpus_brief"


def _publication_score(topic: str, ledger_dir: Path, runs_root: Path) -> int:
    total, l4plus = _topic_run_stats(topic, runs_root)
    pass_rate = (l4plus / total) if total else 0
    last = _parse_time(_attempted_at(topic, ledger_dir))
    freshness = 2 if last is None or dt.datetime.now(dt.UTC) - last > dt.timedelta(days=14) else 0
    return (
        round(pass_rate * 5)
        + int(_publication_track_topic(topic)) * 3
        + freshness
        - _recent_failed_attempts(topic, ledger_dir) * 2
    )


def _topic_support_score(topic: str) -> int:
    record = _read_json(TOPIC_PACKS_DB / topic / "latest.json")
    count = record.get("candidate_count")
    if isinstance(count, int) and count > 0:
        return count
    return _quant_claim_count(topic)


def _topic_has_quant_floor(topic: str) -> bool:
    return _quant_claim_count(topic) >= PREFLIGHT_MIN_QUANT_CLAIMS


def _fresh_seed_candidate(topic: str) -> bool:
    if _topic_has_quant_floor(topic):
        return True
    if (TOPIC_PACKS / f"{topic}.toml").exists():
        return True
    record = _read_json(TOPIC_PACKS_DB / topic / "latest.json")
    if not record:
        return True
    if generated_pack_publishable(record, peer_records=_generated_pack_records()):
        return True
    return _topic_support_score(topic) >= SOURCE_PRECISION_REPAIR_PUBLISH_MIN_QUANT


def _fresh_corpus_repair_candidate(topic: str) -> bool:
    record = _read_json(TOPIC_PACKS_DB / topic / "latest.json")
    count = record.get("candidate_count")
    return not isinstance(count, int) and not _fresh_seed_candidate(topic)


def _has_clean_ready_topic(
    topics: list[str],
    *,
    exclude: set[str],
    source_precision_blocked: set[str],
) -> bool:
    return any(
        candidate not in exclude
        and candidate not in source_precision_blocked
        and _publication_track_topic(candidate)
        and _topic_has_quant_floor(candidate)
        for candidate in topics
    )


def _topic_candidate_decision(topic: str, runs_root: Path) -> CandidateDecision:
    latest = _latest_topic_run(topic, runs_root)
    counts = _manifest_counts(latest)
    manifest = _read_json(latest / "manifest.json") if latest else {}
    review_type = str(manifest.get("review_type") or "").strip()
    if _compact_review_topic(topic):
        review_type = _topic_declared_review_type(topic)
    return decide_candidate(
        topic,
        review_type=review_type,
        evidence=CandidateEvidence(
            n_quant_claims=_quant_claim_count(topic),
            n_receipts=int(counts.get("n_receipts") or 0),
            n_primary_tier=int(counts.get("n_primary_tier") or 0),
            n_direct_receipts=int(counts.get("n_direct_receipts") or 0),
            has_manifest=bool(counts.get("has_manifest")),
            numeric_density_ok=not _prior_numeric_density_failed(latest),
        ),
        thresholds=_CANDIDATE_THRESHOLDS,
    )


def _receipt_source_fit_rank_from_counts(
    n_receipts: int,
    n_primary_tier: int,
    n_direct_receipts: int,
) -> tuple[int, int, int, int, int, int, int, int]:
    if n_receipts <= 0:
        return (
            3,
            PREFLIGHT_MIN_RECEIPTS,
            PREFLIGHT_MIN_RECEIPTS,
            PREFLIGHT_MIN_PRIMARY_TIER,
            PREFLIGHT_MIN_DIRECT_RECEIPTS,
            0,
            0,
            0,
        )
    receipt_gap = max(0, PREFLIGHT_MIN_RECEIPTS - n_receipts)
    primary_gap = max(0, PREFLIGHT_MIN_PRIMARY_TIER - n_primary_tier)
    direct_gap = max(0, PREFLIGHT_MIN_DIRECT_RECEIPTS - n_direct_receipts)
    source_fit_reasons = _receipt_source_fit_reasons(n_primary_tier, n_direct_receipts, n_receipts)
    status_rank = 0 if receipt_gap == 0 and not source_fit_reasons else 1 if not source_fit_reasons else 2
    source_fit_gap = primary_gap + direct_gap
    return (
        status_rank,
        receipt_gap,
        source_fit_gap,
        primary_gap,
        direct_gap,
        -n_direct_receipts,
        -n_primary_tier,
        -n_receipts,
    )


def _recent_receipt_preflight_counts(
    topic: str,
    ledger_dir: Path,
    *,
    now: dt.datetime | None = None,
) -> tuple[int, int, int] | None:
    cutoff = (now or dt.datetime.now(dt.UTC)) - dt.timedelta(hours=RECENT_FAILURE_COOLDOWN_HOURS)
    latest_at: dt.datetime | None = None
    latest_counts: tuple[int, int, int] | None = None
    for path in ledger_dir.glob("*.json"):
        row = _read_json(path)
        started = _parse_time(str(row.get("started_at") or ""))
        if started is None or started < cutoff or (latest_at is not None and started <= latest_at):
            continue
        for attempt in row.get("attempts", []):
            if not isinstance(attempt, dict) or attempt.get("topic") != topic:
                continue
            report = attempt.get("receipt_preflight")
            if not isinstance(report, dict):
                continue
            latest_at = started
            latest_counts = (
                int(report.get("n_receipts") or 0),
                int(report.get("n_primary_tier") or 0),
                int(report.get("n_direct_receipts") or 0),
            )
    return latest_counts if latest_at else None


def _receipt_source_fit_rank(topic: str, runs_root: Path, ledger_dir: Path) -> tuple[int, int, int, int, int, int, int, int]:
    recent_counts = _recent_receipt_preflight_counts(topic, ledger_dir)
    if recent_counts is not None:
        return _receipt_source_fit_rank_from_counts(*recent_counts)
    counts = _manifest_counts(_latest_topic_run(topic, runs_root))
    if not counts.get("has_manifest"):
        return _receipt_source_fit_rank_from_counts(0, 0, 0)
    return _receipt_source_fit_rank_from_counts(
        int(counts.get("n_receipts") or 0),
        int(counts.get("n_primary_tier") or 0),
        int(counts.get("n_direct_receipts") or 0),
    )


def _public_research_surface_preflight(run: Path) -> dict[str, Any]:
    counts = _manifest_counts(run)
    n_receipts = int(counts.get("n_receipts") or 0)
    n_primary = int(counts.get("n_primary_tier") or 0)
    n_direct = int(counts.get("n_direct_receipts") or 0)
    manifest = _read_json(run / "manifest.json")
    review_type = str(manifest.get("review_type") or "").strip()
    decision = decide_candidate(
        run.name,
        review_type=review_type,
        evidence=CandidateEvidence(
            n_quant_claims=PREFLIGHT_MIN_QUANT_CLAIMS,
            n_receipts=n_receipts,
            n_primary_tier=n_primary,
            n_direct_receipts=n_direct,
        ),
        thresholds=_CANDIDATE_THRESHOLDS,
    )
    source_fit_reasons = _receipt_source_fit_reasons(n_primary, n_direct, n_receipts)
    passed = decision.ready_for_synthesis
    return {
        "passed": passed,
        "status": (
            "public_research_surface_ok" if passed else
            "public_research_surface_compact_review"
            if decision.surface is PublicationSurface.INTERNAL_COMPACT else
            "public_research_surface_insufficient"
        ),
        "review_type": review_type or None,
        "n_receipts": n_receipts,
        "min_receipts": PREFLIGHT_MIN_RECEIPTS,
        "n_primary_tier": n_primary,
        "n_direct_receipts": n_direct,
        "min_direct_receipts": PREFLIGHT_MIN_DIRECT_RECEIPTS,
        "reasons": [] if passed else source_fit_reasons,
    }


def _candidate_buffer_thresholds() -> dict[str, int]:
    return _CANDIDATE_THRESHOLDS.as_dict()


def _prepared_candidate_rows(
    ledger_dir: Path, *, now: dt.datetime | None = None,
) -> dict[str, dict[str, Any]]:
    return _validated_candidate_rows(
        _read_json(ledger_dir / CANDIDATE_BUFFER),
        thresholds=_CANDIDATE_THRESHOLDS,
        now=now or dt.datetime.now(dt.UTC),
        max_age_hours=CANDIDATE_BUFFER_MAX_AGE_HOURS,
        precision_floor=SOURCE_TOPIC_REPAIR_FLOOR,
    )


def _prepared_candidate_topics(ledger_dir: Path, *, now: dt.datetime | None = None) -> set[str]:
    return set(_prepared_candidate_rows(ledger_dir, now=now))


def _recent_candidate_buffer_attempts(
    report: dict[str, Any],
    *,
    now: dt.datetime,
) -> list[dict[str, Any]]:
    return _recent_preparation_attempts(
        report,
        now=now,
        max_age_hours=CANDIDATE_BUFFER_MAX_AGE_HOURS,
    )


def _fresh_topic_pool(
    topics: list[str],
    ledger_dir: Path,
    *,
    remote_seen: set[str] | None = None,
    exclude: set[str] | None = None,
    allow_recent_blocked_fallback: bool = True,
    prefer_without_recent_failures: bool = True,
    recent_failure_exempt: set[str] | None = None,
) -> list[str]:
    blocked = _published_topics(topics, remote_seen or set(), ledger_dir)
    candidates = [topic for topic in topics if topic not in blocked and topic not in (exclude or set())]
    if not candidates:
        return []
    if prefer_without_recent_failures:
        recent_blocked = _recent_blocked_topics(ledger_dir)
        fresh_candidates = [
            topic for topic in candidates
            if topic in (recent_failure_exempt or set())
            or (topic not in recent_blocked and _recent_failed_attempts(topic, ledger_dir) == 0)
        ]
        if fresh_candidates:
            candidates = fresh_candidates
        elif not allow_recent_blocked_fallback:
            return []
    return [topic for topic in candidates if _publication_track_topic(topic) and _fresh_seed_candidate(topic)]


def select_topic(
    topics: list[str],
    ledger_dir: Path,
    *,
    runs_root: Path = RUNS,
    remote_seen: set[str] | None = None,
    exclude: set[str] | None = None,
    allow_recent_blocked_fallback: bool = True,
    prefer_without_recent_failures: bool = True,
    prefer_source_fit: bool = False,
) -> str | None:
    prepared = _prepared_candidate_topics(ledger_dir)
    pool = _fresh_topic_pool(
        topics,
        ledger_dir,
        remote_seen=remote_seen,
        exclude=exclude,
        allow_recent_blocked_fallback=allow_recent_blocked_fallback,
        prefer_without_recent_failures=prefer_without_recent_failures,
        recent_failure_exempt=prepared,
    )
    if not pool:
        return None
    synthesis_ready = {
        topic
        for topic in pool
        if _topic_candidate_decision(topic, runs_root).ready_for_synthesis
    }
    source_fit_rank = {topic: _receipt_source_fit_rank(topic, runs_root, ledger_dir) for topic in pool}
    # Prefer known synthesis-ready corpora before frontier exploration so the
    # publication lane consumes its strongest available candidate first.
    # Within each group prefer direct-source fit before raw corpus size; broad
    # indirect corpora waste fresh windows even when they have many claims.
    untried = {topic for topic in pool if _topic_run_stats(topic, runs_root)[0] == 0}
    return min(pool, key=lambda topic: (
        0 if topic in prepared else 1,
        source_fit_rank[topic] if prefer_source_fit else (),
        0 if _quant_claim_count(topic) >= PREFLIGHT_MIN_QUANT_CLAIMS else 1,
        0 if topic in synthesis_ready else 1,
        0 if topic in untried else 1,
        source_fit_rank[topic] if not prefer_source_fit else (),
        -_quant_claim_count(topic),
        -_publication_score(topic, ledger_dir, runs_root),
        -_topic_support_score(topic),
        _attempted_at(topic, ledger_dir),
        topic,
    ))


def _topic_status_map(
    topics: list[str],
    *,
    terminal: set[str],
    surface_repeat: set[str],
    preflight_blocked: set[str],
    source_precision_blocked: set[str] | None = None,
    submitted: set[str],
) -> dict[str, str]:
    """Derived, read-only queue state per topic — the 'one queue ledger' view
    (plan H). Consolidates the exclusion signals already computed this cycle so
    the state that prevents looping is visible in one place; it is NOT a second
    authoritative store (no write-path to drift out of sync)."""
    status: dict[str, str] = {}
    source_precision_blocked = source_precision_blocked or set()
    for topic in sorted(topics):
        if topic in surface_repeat:
            status[topic] = "terminal_surface_repeat"
        elif topic in source_precision_blocked:
            status[topic] = "source_precision_blocked"
        elif topic in preflight_blocked:
            status[topic] = "preflight_blocked"
        elif topic in terminal:
            status[topic] = "terminal"
        elif topic in submitted:
            status[topic] = "submitted"
        else:
            status[topic] = "ready"
    return status


def _preflight_reason_survives_corpus_refresh(reason: str) -> bool:
    if reason in {"latest_run_missing_manifest", "public_surface_not_full_research"} or reason.startswith("recent_failed_attempts="):
        return True
    return reason.startswith(("n_receipts=", "n_tensions=", "n_outcome_classes=")) and reason.endswith("(split topic)")


def _preflight(
    topic: str,
    runs_root: Path,
    ledger_dir: Path,
    *,
    current_quant_claims: int | None = None,
    ignore_recent_failures: bool = False,
    source_run: Path | None = None,
) -> dict[str, Any]:
    latest = source_run if source_run and source_run.is_dir() else _latest_topic_run(topic, runs_root)
    counts = _manifest_counts(latest)
    publication_track = _publication_track_topic(topic)
    reasons = []
    if not publication_track:
        reasons.append("public_surface_not_full_research")
    if latest and not counts["has_manifest"]:
        reasons.append("latest_run_missing_manifest")
    if counts["has_manifest"] and counts["n_receipts"] < PREFLIGHT_MIN_RECEIPTS:
        reasons.append(f"n_receipts={counts['n_receipts']} < {PREFLIGHT_MIN_RECEIPTS}")
    if counts["has_manifest"] and counts["n_tensions"] < PREFLIGHT_MIN_TENSIONS:
        reasons.append(f"n_tensions={counts['n_tensions']} < {PREFLIGHT_MIN_TENSIONS}")
    if counts["has_manifest"] and counts["n_primary_tier"] < PREFLIGHT_MIN_PRIMARY_TIER:
        reasons.append(f"n_primary_tier={counts['n_primary_tier']} < {PREFLIGHT_MIN_PRIMARY_TIER}")
    if counts["has_manifest"] and counts["n_receipts"] > PREFLIGHT_MAX_RECEIPTS:
        reasons.append(f"n_receipts={counts['n_receipts']} > {PREFLIGHT_MAX_RECEIPTS} (split topic)")
    if counts["has_manifest"] and counts["n_tensions"] > PREFLIGHT_MAX_TENSIONS:
        reasons.append(f"n_tensions={counts['n_tensions']} > {PREFLIGHT_MAX_TENSIONS} (split topic)")
    if counts["has_manifest"] and counts["n_outcome_classes"] > PREFLIGHT_MAX_OUTCOMES:
        reasons.append(f"n_outcome_classes={counts['n_outcome_classes']} > {PREFLIGHT_MAX_OUTCOMES} (split topic)")
    recent_failures = _recent_failed_attempts(topic, ledger_dir)
    if recent_failures and not publication_track and not ignore_recent_failures:
        reasons.append(f"recent_failed_attempts={recent_failures} within {RECENT_FAILURE_COOLDOWN_HOURS}h")
    if current_quant_claims is not None and current_quant_claims >= PREFLIGHT_MIN_QUANT_CLAIMS:
        # A prior failed run's manifest can be stale after corpus repair/backfill.
        # Keep true stop signs (overbroad split/recent cooldown), but don't let
        # old receipt/tension/primary counts permanently block a rebuilt topic.
        reasons = [r for r in reasons if _preflight_reason_survives_corpus_refresh(r)]
    return {
        "passed": not reasons,
        "publication_track": publication_track,
        "recent_failed_attempts": recent_failures,
        "reasons": reasons,
        "latest_run": latest.name if latest else None,
        **counts,
    }


def _quant_claim_preflight(corpus: dict[str, Any], *, topic: str | None = None) -> dict[str, Any]:
    try:
        n_quant_claims = int(corpus.get("n_quant_claims") or 0)
    except (TypeError, ValueError):
        n_quant_claims = 0
    reasons: list[str] = []
    if n_quant_claims < PREFLIGHT_MIN_QUANT_CLAIMS:
        reasons.append(f"n_quant_claims={n_quant_claims} < {PREFLIGHT_MIN_QUANT_CLAIMS}")
    claim_bearing = total_files = None
    if topic:
        claim_bearing, total_files = _claim_bearing_quant_count(topic)
        if total_files and claim_bearing < PREFLIGHT_MIN_QUANT_CLAIMS:
            reasons.append(f"n_claim_bearing_quant_files={claim_bearing} < {PREFLIGHT_MIN_QUANT_CLAIMS}")
    return {
        "passed": not reasons,
        "reasons": reasons,
        "n_quant_claims": n_quant_claims,
        **({"n_claim_bearing_quant_files": claim_bearing, "n_quant_claim_files": total_files} if topic else {}),
    }


def _receipt_source_fit_reasons(
    n_primary_tier: int,
    n_direct_receipts: int,
    n_receipts: int,
) -> list[str]:
    del n_receipts
    return source_fit_reasons(
        n_primary_tier=n_primary_tier,
        n_direct_receipts=n_direct_receipts,
        thresholds=_CANDIDATE_THRESHOLDS,
    )


def _paper_strategy(corpus: dict[str, Any], preflight: dict[str, Any], revision_feedback: str = "") -> dict[str, Any]:
    sparse = bool(_SPARSE_REVIEW_RE.search(revision_feedback))
    terminal_sparse = bool(_TERMINAL_SPARSE_RE.search(revision_feedback))
    predicted = parse_review_type(
        str(preflight.get("predicted_review_type") or DEFAULT_REVIEW_TYPE),
    )
    selected_name = (
        "skip_topic"
        if terminal_sparse
        else "needs_corpus"
        if sparse or predicted in COMPACT_REVIEW_TYPES
        else "full_paper"
    )
    score = 1.0 if selected_name == "full_paper" else 0.0
    return {
        "action": selected_name if selected_name != "full_paper" else "write",
        "review_type_override": None,
        "reason": (
            "terminal_sparse_researka_feedback"
            if selected_name == "skip_topic"
            else "full_synthesis_evidence_floor"
            if selected_name == "needs_corpus"
            else "full_synthesis_ready"
        ),
        "frames": [{"name": "full_paper", "score": score}],
        "selected": {"name": selected_name, "score": score},
    }


def _failure_class(status: str) -> str:
    code = status.split(":", 1)[0]
    if code in _TERMINAL_REVISION_STATUSES or code in _ACTIVE_REVIEW_TERMINAL_REVISION_STATUSES:
        return "D_no_action"
    return {
        "journal_surface_not_passed": "A_compiler_fixable",
        "journal_surface_failed": "A_compiler_fixable",
        "final_status_not_ready": "A_compiler_fixable",
        "final_verdict_not_aaa": "A_compiler_fixable",
        "pre_submit_not_passed": "A_compiler_fixable",
        "needs_corpus_expansion": "B_corpus_fixable",
        "audit_not_all_green": "C_writer_fixable",
        "revision_coverage_unmet": "C_writer_fixable",
        "numeric_effect_mismatch": "C_writer_fixable",
        "abstract_overclaim": "C_writer_fixable",
        "retracted_source_cited": "D_no_action",
        "synthesis_failed": "C_writer_fixable",
        "synthesis_timeout": "D_no_action",
        "submission_rejected_by_researka": "C_writer_fixable",
        "submission_revise_requested": "C_writer_fixable",
        "strategy_evidence_insufficient": "B_corpus_fixable",
        "source_topic_precision_low": "B_corpus_fixable",
        "recency_ratio_low": "B_corpus_fixable",
        "preflight_insufficient_corpus": "B_corpus_fixable",
        "preflight_thin_quant_corpus": "B_corpus_fixable",
        "corpus_missing_dry_run": "B_corpus_fixable",
        "corpus_seed_empty": "B_corpus_fixable",
        "corpus_seed_failed": "B_corpus_fixable",
        "receipt_preflight_insufficient": "B_corpus_fixable",
        "public_research_surface_compact_review": "B_corpus_fixable",
        "public_research_surface_insufficient": "B_corpus_fixable",
        # Back-compat for blocker rows written before audit failures were
        # routed through audit_not_all_green.
        "audit_p1_failed": "C_writer_fixable",
        "missing": "C_writer_fixable",
        "superseded_topic_run": "D_no_action",
        "terminal_synthesis_timeout": "D_no_action",
    }.get(code, "unknown")


def _revision_asks(feedback: str, required_revisions: Sequence[str] | None = None) -> list[str]:
    return revision_coverage.revision_asks(feedback, required_revisions)


def _unmet_revision_asks(out_dir: Path, feedback: str) -> list[str]:
    request = _read_json(out_dir / "researka_revision_request.json")
    required_revisions = _required_revision_items(request)
    asks = _revision_asks(feedback, required_revisions)
    paper = out_dir / "full_paper.md"
    if not paper.is_file():
        return asks
    try:
        text = paper.read_text(encoding="utf-8")
    except OSError:
        return asks
    supplement = out_dir / "structured_evidence_tables.md"
    if supplement.is_file():
        try:
            text += "\n\n" + supplement.read_text(encoding="utf-8")
        except OSError:
            return asks
    manifest = _read_json(out_dir / "manifest.json")
    rows_raw = manifest.get("receipts")
    rows = [row for row in rows_raw if isinstance(row, dict)] if isinstance(rows_raw, list) else []
    unmet = revision_coverage.material_unmet_asks(
        text, feedback, retained_citations=revision_coverage.retained_citation_labels(
            manifest, _read_json(out_dir / "citation_registry.json"),
        ), evidence_rows=rows,
        source_identifier_audit=_read_json(out_dir / "source_identifier_verification.json"),
        required_revisions=required_revisions,
    )
    return [ask for ask in unmet if not _payload_revision_ask_satisfied(out_dir, ask)]


def _payload_revision_ask_satisfied(out_dir: Path, ask: str) -> bool:
    ask_lower = ask.lower()
    paper_text = ""
    with suppress(OSError):
        paper_text = (out_dir / "full_paper.md").read_text(encoding="utf-8").lower()
    if revision_coverage.outcome_label_rename(ask):
        return revision_coverage.outcome_label_cleanup_is_stated(paper_text, ask)
    if "classification criteria" in ask_lower and all(
        token in paper_text
        for token in ("### classification criteria", "**outcome class**", "**directness**", "**evidence tier**")
    ):
        return True
    if (
        ("mapping table" in ask_lower or "mapping list" in ask_lower or "which of the" in ask_lower)
        and all(token in paper_text for token in ("### source classification map", "outcome=", "directness=", "tier="))
    ):
        return True
    if (
        (
            revision_coverage.asks_source_directness_breakdown(ask_lower)
            or revision_coverage.asks_evidence_type_metadata(ask_lower)
            or revision_coverage.asks_source_classification_map(ask_lower)
        )
        and all(token in paper_text for token in ("### source classification map", "outcome=", "directness=", "tier="))
        and ("low-directness" not in ask_lower or "low-directness" in paper_text)
        and ("case report" not in ask_lower or ("case report" in paper_text or "case-report" in paper_text))
        and ("patient education" not in ask_lower or "patient education" not in paper_text)
    ):
        return True
    if (
        "attribution gap" in ask_lower
        and "mortality" in ask_lower
        and "survival" in ask_lower
        and (
            "outcome=mortality and survival" in paper_text
            or "mortality and survival is unsourced" in paper_text
        )
    ):
        return True
    if (
        "outcome subsection" in ask_lower
        and "source" in ask_lower
        and "evidence domain" in paper_text
        and "source examples:" in paper_text
        and "direct-source ceiling:" in paper_text
    ):
        return True
    if (
        "direct clinical source" in ask_lower
        and (
            "direct-source ceiling:" in paper_text
            or ("### source classification map" in paper_text and "directness=direct" in paper_text)
        )
    ):
        return True
    if (
        "limitations" in ask_lower
        and "protocol" in ask_lower
        and ("cross-sectional" in ask_lower or "observational" in ask_lower)
        and "design-limit note:" in paper_text
        and "causal claims" in paper_text
    ):
        return True
    if "direct evidence" in ask_lower and any(token in ask_lower for token in ("definition", "qualifying", "qualify", "0/")):
        return "qualifying direct source" in paper_text or "direct interventional hard-endpoint evidence" in paper_text
    if revision_coverage.asks_source_attribution_map(ask_lower):
        return _paper_has_source_attribution_map(paper_text)
    if _asks_narrow_conclusion(ask_lower):
        return _paper_has_bounded_conclusion(paper_text)
    if _asks_conflict_severity_criteria(ask_lower):
        return all(
            token in paper_text
            for token in (
                "conflict-map severity note",
                "severity-level-3",
                "severity-level-4",
                "contradiction-map",
            )
        )
    if "truncated" in ask_lower and "abstract" in ask_lower and _abstract_has_complete_sentence(paper_text):
        return True
    payload_section_ask = "key findings" in ask_lower or "evidence landscape" in ask_lower
    payload_clip_ask = "truncated" in ask_lower and "abstract" in ask_lower and "research question" in ask_lower
    source_topic_ask = "source" in ask_lower and any(token in ask_lower for token in ("address", "off-topic", "off topic", "topic"))
    source_excerpt_ask = (
        ("source_bundle" in ask_lower or "source bundle" in ask_lower or "source" in ask_lower)
        and any(token in ask_lower for token in ("abstract", "excerpt", "directional coding", "claim extraction"))
    )
    evidence_type_ask = (
        "evidence_type" in ask_lower
        or ("review" in ask_lower and "primary" in ask_lower and ("source_bundle" in ask_lower or "source bundle" in ask_lower))
    )
    if not (payload_section_ask or payload_clip_ask or source_topic_ask or source_excerpt_ask or evidence_type_ask):
        return False
    try:
        payload = submit_bridge.build_payload(out_dir)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return False
    if source_topic_ask or source_excerpt_ask or evidence_type_ask:
        bundle = payload.get("source_bundle")
        if not isinstance(bundle, list) or not bundle:
            return False
        rows = [row for row in bundle if isinstance(row, dict)]
        if source_topic_ask:
            metadata = payload.get("metadata")
            topic = str(metadata.get("topic") or "") if isinstance(metadata, dict) else ""
            aliases = source_gate_aliases(
                topic, topic_aliases(topic, root=TOPIC_PACKS.parent, include_generated_terms=False),
            )
            row_texts = [
                " ".join(str(row.get(key) or "") for key in ("title", "excerpt", "doi", "id", "url", "evidence_type")).lower()
                for row in rows
            ]
            hits = sum(is_source_topic_specific(topic, text, aliases=aliases) for text in row_texts)
            if _strict_source_topic_revision_ask(ask_lower):
                allow_adjacent = "reclassify" in ask_lower or "contextual adjacent" in ask_lower
                return bool(topic) and all(
                    is_source_topic_specific(topic, text, aliases=aliases)
                    or (allow_adjacent and "contextual adjacent" in text)
                    for text in row_texts
                )
            return bool(topic) and hits / len(rows) >= REVISION_SOURCE_BUNDLE_TOPIC_FLOOR
        if evidence_type_ask and "primary" not in {str(row.get("evidence_type") or "").lower() for row in rows}:
            return False
        if source_excerpt_ask:
            top_rows = rows[:min(14, len(rows))]
            meaningful = [
                str(row.get("excerpt") or "")
                for row in top_rows
                if len(str(row.get("excerpt") or "").split()) >= 12
                and " is registered as " not in str(row.get("excerpt") or "").lower()
            ]
            return len(meaningful) == len(top_rows)
        return True
    sections = payload.get("sections", {})
    if not isinstance(sections, dict):
        return False
    if payload_clip_ask:
        abstract = str(payload.get("abstract") or "").strip()
        research_question = str(sections.get("Research Question") or "").strip()
        return bool(
            abstract
            and research_question
            and abstract.endswith((".", "!", "?"))
            and research_question.endswith((".", "!", "?"))
        )
    landscape = str(sections.get("Evidence Landscape") or "")
    findings = str(sections.get("Key Findings") or "")
    return bool(findings and landscape and findings != landscape and "|" not in findings)


def _paper_has_source_attribution_map(paper_text: str) -> bool:
    has_map = (
        "### source classification map" in paper_text
        or "### findings map" in paper_text
        or "source-level findings by outcome class" in paper_text
        or "source examples:" in paper_text
    )
    has_fields = all(token in paper_text for token in ("outcome=", "directness=", "tier="))
    has_author_year = bool(re.search(r"\b[a-z][a-z-]{2,}\s+(?:19|20)\d{2}\b", paper_text, re.I))
    return has_map and has_fields and has_author_year


def _asks_narrow_conclusion(ask_lower: str) -> bool:
    return (
        "conclusion" in ask_lower
        and any(token in ask_lower for token in ("breadth", "narrow", "bounded", "translation", "overclaim"))
    )


def _paper_has_bounded_conclusion(paper_text: str) -> bool:
    match = re.search(r"^##\s+conclusion\b(?P<body>.*?)(?=^##\s+|\Z)", paper_text, re.M | re.S)
    conclusion = match.group("body") if match else paper_text[-1200:]
    bounded = any(token in conclusion for token in (
        "bounded", "hypothesis-generating", "adjacent", "mechanistic",
        "does not support", "cannot support", "insufficient", "limited",
    ))
    overbroad = any(token in conclusion for token in (
        "establishes", "demonstrates", "proves", "supports clinical",
        "supports causal",
    ))
    return bounded and not overbroad


def _abstract_has_complete_sentence(paper_text: str) -> bool:
    match = re.search(r"^##\s+abstract\b(?P<body>.*?)(?=^##\s+|\Z)", paper_text, flags=re.M | re.S)
    body = " ".join((match.group("body") if match else "").split())
    return bool(body and re.search(r"[.!?][\"')\]]?$", body) and not body.endswith(("...", "\u2026")))


def _asks_conflict_severity_criteria(ask_lower: str) -> bool:
    return (
        any(token in ask_lower for token in ("severity-level", "severity level"))
        and any(token in ask_lower for token in ("disagreement", "disagreements", "conflict", "conflict map"))
        and any(token in ask_lower for token in ("defined", "scored", "scoring", "supplementary", "supplemental"))
    )


def _strict_source_topic_revision_ask(ask_lower: str) -> bool:
    return (
        ("all" in ask_lower and "actually address" in ask_lower)
        or "verify that all" in ask_lower
        or "directly and specifically" in ask_lower
        or "clearly off-topic" in ask_lower
        or "clearly off topic" in ask_lower
        or "unrelated topic" in ask_lower
        or "unrelated topics" in ask_lower
        or "remove or reclassify" in ask_lower
    )


def _retracted_cited_sources(out_dir: Path) -> list[str] | None:
    """Retracted DOIs, or None when the strict publication check is unavailable."""
    import retraction_check
    try:
        return retraction_check.retracted_cited_sources(out_dir, strict=True)
    except retraction_check.RetractionCheckUnavailable:
        return None


def _abstract_overclaims(out_dir: Path) -> list[str]:
    """Abstract claims the paper's evidence does not support / overstates
    (claim-support judge). Fail-open (empty on any error); monkeypatched in
    tests so they stay offline."""
    paper = out_dir / "full_paper.md"
    if not paper.is_file():
        return []
    return revision_coverage.unsupported_abstract_claims(paper.read_text(encoding="utf-8"))


def _numeric_effect_direction_issues(out_dir: Path) -> list[str]:
    paper = out_dir / "full_paper.md"
    if not paper.is_file():
        return []
    return revision_coverage.numeric_effect_direction_issues(paper.read_text(encoding="utf-8"))


def _final_status_submission_ready(out_dir: Path) -> bool:
    status = _read_json(out_dir / "final_status.json")
    if "researka_publish_ready" in status:
        return bool(status.get("researka_publish_ready"))
    return bool(status.get("submission_ready"))


def _repair_abstract_overclaim_phrasing(out_dir: Path, overclaims: list[str]) -> bool:
    """Soften only judge-flagged abstract spans, then let the same judge re-check."""
    paper = out_dir / "full_paper.md"
    if not overclaims or not paper.is_file():
        return False
    text = paper.read_text(encoding="utf-8")
    match = re.search(r"(?ms)^##\s+Abstract\b.*?(?=^##\s+|\Z)", text)
    if not match:
        return False
    abstract = match.group(0)
    repaired = abstract
    for claim in overclaims:
        needle = str(claim).strip()
        if needle and needle in repaired:
            from agent.paper_writer_claim_repair import repair_abstract_claim_strength
            safer = re.sub(r"\b[Dd]emonstrated\s+(?:in|by)\b", "suggested by", needle)
            safer = re.sub(r"\b[Pp]ositive\s+([A-Za-z][A-Za-z -]{2,80}?signals)\b", r"context-specific \1", safer)
            safer, _ = repair_abstract_claim_strength(safer)
            repaired = repaired.replace(needle, safer)
    if repaired == abstract:
        from agent.paper_writer_claim_repair import repair_abstract_claim_strength
        repaired, _ = repair_abstract_claim_strength(abstract)
    if repaired == abstract:
        return False
    paper.write_text(text[:match.start()] + repaired + text[match.end():], encoding="utf-8")
    _write_json(out_dir / "abstract_overclaim_repair.json", {"overclaims": overclaims})
    return True


def _escalate_feedback(feedback: str, unmet: list[str]) -> str:
    """Prioritize unmet asks without dropping the remaining reviewer contract."""
    required = [*unmet, *(ask for ask in _revision_asks(feedback) if ask not in unmet)]
    return (
        "PRIOR REVISION DID NOT ADDRESS THESE REQUIRED POINTS — you MUST make a "
        f"substantive change to satisfy EACH: {'; '.join(required)}"
    )


def _set_known_blocker_class(row: dict[str, Any], status: str) -> str:
    klass = _failure_class(status)
    if row.get("class") in {None, "", "unknown"} and klass != "unknown":
        row["class"] = klass
    return klass


def _record_blockers(ledger_dir: Path, date: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    path = ledger_dir / BLOCKER_HISTOGRAM
    data = _read_json(path)
    blockers = data.setdefault("blockers", {})
    if isinstance(blockers, dict):
        for code, row in blockers.items():
            if isinstance(row, dict):
                _set_known_blocker_class(row, str(code))
    # Cumulative per-(topic, gate) failure timestamps — the daily ledger is
    # rewritten each run and cannot hold a cross-run count, so the repeat-skip
    # heuristic reads this instead. Windowed to the failure cooldown.
    repeats = data.setdefault("repeats", {})
    writer_runs = data.setdefault("writer_gate_runs", {})
    now_dt = dt.datetime.now(dt.UTC)
    cutoff = now_dt - dt.timedelta(hours=RECENT_FAILURE_COOLDOWN_HOURS)
    issue_candidates: list[str] = []
    for row in rows:
        status = str(row.get("status") or row.get("gate_status") or row.get("submit_status") or "")
        if not status or status in {"eligible", "submitted_to_researka"}:
            continue
        code = status.split(":", 1)[0]
        klass = _failure_class(status)
        item = blockers.setdefault(code, {"count": 0, "class": klass, "samples": []})
        _set_known_blocker_class(item, status)
        item["count"] = int(item.get("count") or 0) + 1
        item["last_seen"] = date
        sample = {k: row.get(k) for k in ("topic", "run", "out_dir", "status", "gate_status", "submit_status") if row.get(k) is not None}
        item["samples"] = ([sample] + list(item.get("samples") or []))[:3]
        topic = str(row.get("topic") or "")
        if topic and code not in _NON_REPEAT_STATUSES:
            key = f"{topic}\x1f{code}"
            kept = [s for s in repeats.get(key, []) if (t := _parse_time(str(s))) and t >= cutoff]
            kept.append(now_dt.isoformat())
            repeats[key] = kept[-12:]
            if klass.startswith("C_"):
                prior = writer_runs.get(key, [])
                kept_rows = [
                    r for r in prior
                    if isinstance(r, dict)
                    and (t := _parse_time(str(r.get("at") or "")))
                    and t >= cutoff
                ]
                kept_rows.append({
                    "at": now_dt.isoformat(),
                    "review_type_override": row.get("review_type_override"),
                    "out_dir": row.get("out_dir") or row.get("run"),
                })
                writer_runs[key] = kept_rows[-12:]
        if int(item["count"]) >= HISTOGRAM_ISSUE_THRESHOLD and item.get("class") != "D_no_action":
            item["github_issue_candidate"] = True
            if item.get("class") == "A_compiler_fixable":
                item["auto_fix_candidate"] = True
            issue_candidates.append(code)
    data["updated_at"] = now_dt.isoformat()
    _write_json(path, data)
    return {"path": path.name, "issue_candidates": sorted(set(issue_candidates))}


def _record_attempt_blocker(
    ledger_dir: Path,
    date: str,
    ledger: dict[str, Any],
    attempt: dict[str, Any],
) -> None:
    ledger["blocker_histogram"] = _record_blockers(ledger_dir, date, [attempt])


@contextmanager
def _lock(ledger_dir: Path, name: str = ".lock", *, block: bool = False) -> Iterator[bool]:
    """Advisory file lock. Distinct `name`s are independent locks, so the fresh
    and revise lanes (`.lock.fresh` / `.lock.revise`) never block each other.
    `block=True` waits for the holder instead of returning False — used by the
    shared submit lock so submission stays single-threaded across lanes."""
    ledger_dir.mkdir(parents=True, exist_ok=True)
    with (ledger_dir / name).open("w", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX if block else fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        handle.write(str(os.getpid()))
        handle.flush()
        yield True


def _remaining_timeout(
    timeout: int | None,
    *,
    started_mono: float,
    cycle_budget_seconds: int,
    clock: Callable[[], float],
) -> int | None:
    limits: list[int] = []
    if timeout and timeout > 0:
        limits.append(timeout)
    if cycle_budget_seconds > 0:
        remaining = int(cycle_budget_seconds - (clock() - started_mono))
        limits.append(max(1, remaining))
    return min(limits) if limits else None


def _insufficient_revise_retry_budget(remaining: int | None, cycle_budget_seconds: int) -> bool:
    if remaining is None or cycle_budget_seconds <= 0:
        return False
    floor = min(MIN_REVISE_RETRY_BUDGET_SECONDS, max(1, cycle_budget_seconds // 2))
    return remaining < floor


def _run_synthesis(
    topic: str,
    out_dir: Path,
    *,
    dry_run: bool,
    timeout: int | None = None,
    revision_feedback: str | None = None,
    review_type_override: str | None = None,
    revision_source_run: Path | None = None,
) -> int:
    cmd = [sys.executable, "scripts/run_v06_synthesis.py", "--topic", topic, "--out-dir", str(out_dir)]
    if dry_run:
        cmd.append("--dry-run")
    env: dict[str, str] | None = None
    if revision_feedback or review_type_override or revision_source_run or not dry_run:
        env = os.environ.copy()
        if not dry_run:
            env["RESEARCH_AGENT_PUBLIC_FULL_ONLY"] = "1"
        if revision_feedback:
            env["RESEARKA_REVISION_FEEDBACK"] = revision_feedback[:4000]
        if review_type_override:
            env["RESEARCH_AGENT_REVIEW_TYPE_OVERRIDE"] = review_type_override
        if revision_source_run:
            env["RESEARCH_AGENT_REVISION_SOURCE_RUN"] = str(revision_source_run.resolve())
    try:
        result = subprocess.run(cmd, cwd=ROOT, check=False, timeout=timeout or None, env=env)
    except subprocess.TimeoutExpired as exc:
        out_dir.mkdir(parents=True, exist_ok=True)
        _write_json(out_dir / "synthesis_timeout.json", {
            "topic": topic,
            "timeout_seconds": timeout,
            "error": f"{type(exc).__name__}: {exc}",
        })
        return SYNTHESIS_TIMEOUT_RETURN_CODE
    return int(result.returncode)


def _receipt_preflight(
    topic: str,
    out_dir: Path,
    *,
    timeout: int | None = None,
    repair: bool = True,
    dry_run: bool = False,
) -> dict[str, Any]:
    min_receipts = DEFAULT_THRESHOLDS.min_receipts
    declared_review_type = _topic_declared_review_type(topic)
    rounds = _receipt_preflight_repair_rounds() if repair and not dry_run else 0
    probes: list[dict[str, Any]] = []
    repairs: list[dict[str, Any]] = []
    rc = 1
    n_receipts = 0
    n_primary_tier = 0
    n_direct_receipts = 0
    n_tensions = 0
    n_outcome_classes = 0
    best_receipts = 0
    best_primary_tier = 0
    best_direct_receipts = 0
    best_tensions = 0
    best_outcome_classes = 0
    predicted_review_type = declared_review_type
    surface_reasons: list[str] = []
    repair_skipped_reason: str | None = None
    for round_idx in range(rounds + 1):
        suffix = "receipt-preflight" if round_idx == 0 else f"receipt-preflight-{round_idx + 1}"
        probe_dir = out_dir.with_name(f"{out_dir.name}-{suffix}")
        try:
            rc = _run_synthesis(topic, probe_dir, dry_run=True, timeout=timeout)
            report = _read_json(probe_dir / "receipt_funnel.json")
        finally:
            shutil.rmtree(probe_dir, ignore_errors=True)
        counts = report.get("counts") if isinstance(report, dict) else {}
        n_receipts = int(counts.get("admitted_receipts") or 0) if isinstance(counts, dict) else 0
        n_primary_tier = int(counts.get("primary_tier_receipts") or 0) if isinstance(counts, dict) else 0
        direct_raw = counts.get("direct_receipts") if isinstance(counts, dict) else None
        n_direct_receipts = int(direct_raw) if direct_raw is not None else 0
        n_tensions = int(counts.get("non_orthogonal_tensions") or 0) if isinstance(counts, dict) else 0
        n_outcome_classes = int(counts.get("outcome_classes") or 0) if isinstance(counts, dict) else 0
        previous_best = (
            best_receipts,
            best_primary_tier,
            best_direct_receipts,
            best_tensions,
            best_outcome_classes,
        )
        best_receipts = max(best_receipts, n_receipts)
        best_primary_tier = max(best_primary_tier, n_primary_tier)
        best_direct_receipts = max(best_direct_receipts, n_direct_receipts)
        best_tensions = max(best_tensions, n_tensions)
        best_outcome_classes = max(best_outcome_classes, n_outcome_classes)
        source_fit_reasons = _receipt_source_fit_reasons(n_primary_tier, n_direct_receipts, n_receipts)
        predicted_review_type = downshift_review_type_for_thin_corpus(
            declared_review_type,
            n_receipts,
            n_tensions,
            n_primary_tier=n_primary_tier,
            n_outcome_classes=n_outcome_classes,
        )
        surface_reasons = (
            [f"predicted_public_surface={predicted_review_type}"]
            if not source_fit_reasons and predicted_review_type in COMPACT_REVIEW_TYPES
            else []
        )
        probes.append({
            "return_code": rc,
            "n_receipts": n_receipts,
            "min_receipts": min_receipts,
            "n_primary_tier": n_primary_tier,
            "min_primary_tier": PREFLIGHT_MIN_PRIMARY_TIER,
            "n_direct_receipts": n_direct_receipts,
            "min_direct_receipts": PREFLIGHT_MIN_DIRECT_RECEIPTS,
            "n_tensions": n_tensions,
            "n_outcome_classes": n_outcome_classes,
            "predicted_review_type": predicted_review_type,
        })
        if rc == 0 and n_receipts >= min_receipts and not source_fit_reasons and not surface_reasons:
            break
        if rc == 0 and n_receipts == 0:
            break
        if round_idx > 0 and rc == 0 and (
            best_receipts,
            best_primary_tier,
            best_direct_receipts,
            best_tensions,
            best_outcome_classes,
        ) <= previous_best:
            break
        if round_idx >= rounds:
            break
        current_quant_claims = _quant_claim_count(topic)
        if (
            current_quant_claims >= SOURCE_PRECISION_REPAIR_PUBLISH_MIN_QUANT
            and best_primary_tier == 0
            and best_direct_receipts == 0
        ):
            repair_skipped_reason = "rich_corpus_without_primary_or_direct_anchors"
            break
        if not best_receipts or (rc != 0 and not current_quant_claims):
            break
        corpus_repair = _repair_topic_corpus(
            topic,
            dry_run=False,
            timeout=timeout,
            seed_limit=_receipt_repair_seed_limit(
                max(n_receipts, best_receipts),
                min_receipts,
                round_idx,
                current_quant_claims=current_quant_claims,
                n_primary_tier=max(n_primary_tier, best_primary_tier),
                n_direct_receipts=max(n_direct_receipts, best_direct_receipts),
            ),
            force_extract=False,
        )
        repairs.append(corpus_repair)
        if corpus_repair.get("status") not in {"corpus_ready", "corpus_seeded", "corpus_repaired"}:
            break
    source_fit_reasons = _receipt_source_fit_reasons(n_primary_tier, n_direct_receipts, n_receipts)
    passed = rc == 0 and n_receipts >= min_receipts and not source_fit_reasons and not surface_reasons
    return {
        "passed": passed,
        "status": "receipt_preflight_ok" if passed else "receipt_preflight_insufficient",
        "return_code": rc,
        "n_receipts": n_receipts if passed else best_receipts,
        "min_receipts": min_receipts,
        "n_primary_tier": n_primary_tier if passed else best_primary_tier,
        "min_primary_tier": PREFLIGHT_MIN_PRIMARY_TIER,
        "n_direct_receipts": n_direct_receipts if passed else best_direct_receipts,
        "min_direct_receipts": PREFLIGHT_MIN_DIRECT_RECEIPTS,
        "n_tensions": n_tensions if passed else best_tensions,
        "n_outcome_classes": n_outcome_classes if passed else best_outcome_classes,
        "predicted_review_type": predicted_review_type,
        "reasons": [] if passed else [*source_fit_reasons, *surface_reasons],
        "probes": probes,
        **({"repairs": repairs} if repairs else {}),
        **({"repair_skipped_reason": repair_skipped_reason} if repair_skipped_reason else {}),
    }


def _existing_receipt_preflight(source_run: Path | None) -> dict[str, Any] | None:
    if source_run is None or not source_run.is_dir():
        return None
    counts = _manifest_counts(source_run)
    n_receipts = int(counts.get("n_receipts") or 0)
    n_tensions = int(counts.get("n_tensions") or 0)
    n_primary = int(counts.get("n_primary_tier") or 0)
    n_direct = int(counts.get("n_direct_receipts") or 0)
    min_receipts = DEFAULT_THRESHOLDS.min_receipts
    source_fit_reasons = _receipt_source_fit_reasons(n_primary, n_direct, n_receipts)
    manifest = _read_json(source_run / "manifest.json")
    predicted = parse_review_type(
        str(manifest.get("review_type") or DEFAULT_REVIEW_TYPE),
    )
    if predicted in COMPACT_REVIEW_TYPES:
        return {
            "passed": False,
            "status": "receipt_preflight_insufficient",
            "predicted_review_type": predicted,
            "reasons": [f"predicted_public_surface={predicted}"],
        }
    if (
        n_receipts < min_receipts
        or n_tensions < PREFLIGHT_MIN_TENSIONS
        or source_fit_reasons
    ):
        return None
    return {
        "passed": True,
        "status": "receipt_preflight_existing_ok",
        "n_receipts": n_receipts,
        "n_tensions": n_tensions,
        "n_primary_tier": n_primary,
        "n_direct_receipts": n_direct,
        "predicted_review_type": predicted,
        "min_receipts": min_receipts,
        "min_direct_receipts": PREFLIGHT_MIN_DIRECT_RECEIPTS,
    }


def _source_manifest_receipt_ids(source_run: Path | None) -> list[str]:
    manifest = _read_json(source_run / "manifest.json") if source_run else {}
    receipts = manifest.get("receipts")
    if not isinstance(receipts, list):
        return []
    return [
        str(row.get("receipt_id") or "")
        for row in receipts
        if isinstance(row, dict) and str(row.get("receipt_id") or "")
    ]


def _source_manifest_availability(topic: str, source_run: Path | None) -> dict[str, Any] | None:
    receipt_ids = _source_manifest_receipt_ids(source_run)
    if not receipt_ids:
        return None
    assert source_run is not None
    source_manifest = _read_json(source_run / "manifest.json") if source_run else {}
    snapshot_policy = source_manifest.get("revision_evidence_snapshot")
    if isinstance(snapshot_policy, dict) and snapshot_policy.get("required") is True:
        lock = load_revision_evidence(
            source_run,
            quant_dir=CORPORA / topic / "quant_claims",
            parsed_dir=CORPORA / topic / "parsed",
            expected_topic=topic,
        )
        available = lock.mode == "snapshot" and not lock.errors
        return {
            "passed": available,
            "status": "source_snapshot_available" if available else "source_snapshot_missing",
            "source_run": source_run.name if source_run else "",
            "n_source_receipts": len(receipt_ids),
            "n_available_quant_claim_files": len(receipt_ids) if available else 0,
            "n_missing_quant_claim_files": 0,
            "min_receipts": DEFAULT_THRESHOLDS.min_receipts,
            "missing_receipt_ids": [],
            "evidence_mode": "snapshot",
            "snapshot_errors": list(lock.errors),
        }
    qdir = CORPORA / topic / "quant_claims"
    available_ids = {rid for rid in receipt_ids if (qdir / f"{rid}.quant_claims.json").is_file()}
    min_receipts = DEFAULT_THRESHOLDS.min_receipts
    missing = [rid for rid in receipt_ids if rid not in available_ids]
    return {
        "passed": len(receipt_ids) >= min_receipts and not missing,
        "status": "source_manifest_available" if len(receipt_ids) >= min_receipts and not missing else "source_manifest_unavailable",
        "source_run": source_run.name if source_run else "",
        "n_source_receipts": len(receipt_ids),
        "n_available_quant_claim_files": len(available_ids),
        "n_missing_quant_claim_files": len(missing),
        "min_receipts": min_receipts,
        "missing_receipt_ids": missing[:20],
    }


def _restore_source_manifest_quant_claims(topic: str, source_run: Path | None) -> dict[str, Any]:
    receipt_ids = _source_manifest_receipt_ids(source_run)
    qdir = CORPORA / topic / "quant_claims"
    quarantine = CORPORA / topic / "quant_claims_quarantine"
    restored: list[str] = []
    missing = [rid for rid in receipt_ids if not (qdir / f"{rid}.quant_claims.json").is_file()]
    for rid in missing:
        candidates = sorted(
            quarantine.glob(f"*/{rid}.quant_claims.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not candidates:
            continue
        qdir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(candidates[0], qdir / f"{rid}.quant_claims.json")
        restored.append(rid)
    return {
        "status": "source_manifest_quant_claims_restored" if restored else "source_manifest_quant_claims_missing",
        "source_run": source_run.name if source_run else "",
        "n_missing_before": len(missing),
        "n_restored": len(restored),
        "restored_receipt_ids": restored[:20],
    }


def _terminal_revision_receipt_preflight(report: Mapping[str, Any]) -> bool:
    """A revise corpus that cannot pass receipt preflight should not monopolise
    later revise windows for the same reviewer request."""
    return not report.get("passed") and str(report.get("status") or "") == "receipt_preflight_insufficient"


def _repair_existing_run(
    source_dir: Path,
    out_dir: Path,
    *,
    revision_source: dict[str, Any] | None = None,
    revision_feedback: str | None = None,
    repair_reason: str | None = None,
) -> tuple[bool, str]:
    if not (revision_feedback or repair_reason) or not (source_dir / "full_paper.md").is_file() or out_dir.exists():
        return False, "repair_precondition_failed"
    try:
        shutil.copytree(source_dir, out_dir)
        paper_path = out_dir / "full_paper.md"
        before = paper_path.read_text(encoding="utf-8") if repair_reason else ""
        if revision_source or revision_feedback:
            payload = dict(revision_source or {})
            payload.setdefault("source_run", source_dir.name)
            payload["feedback"] = (revision_feedback or "")[:4000]
            _write_json(out_dir / "researka_revision_request.json", payload)
            if payload.get("retry_unchanged"):
                _write_json(out_dir / REVISION_COVERAGE_GATE, {"passed": True, "unmet": [], "mode": "unchanged_external_verifier_retry"})
        else:
            _write_json(out_dir / "internal_repair_request.json", {"source_run": source_dir.name, "reason": repair_reason})
        from agent.journal_finalizer import finalize_run
        finalize_run(out_dir)
        if repair_reason:
            after = paper_path.read_text(encoding="utf-8")
            if after == before and repair_reason != "submission_authority_retry":
                shutil.rmtree(out_dir, ignore_errors=True)
                return False, "repair_noop"
            if repair_reason == "journal_surface_not_passed":
                from agent.journal_surface_gate import evaluate_journal_surface
                surface = evaluate_journal_surface(after, declared_review_type=_declared_review_type(out_dir))
                if not surface.passed:
                    codes = ",".join(sorted({issue.code for issue in surface.issues}))
                    shutil.rmtree(out_dir, ignore_errors=True)
                    return False, f"surface_after_repair_failed:{codes}"
    except (OSError, RuntimeError, ValueError, ImportError) as exc:
        shutil.rmtree(out_dir, ignore_errors=True)
        return False, f"{type(exc).__name__}: {exc}"
    return True, ""


def _prior_numeric_density_failed(run: Path | None) -> bool:
    audit = _read_json(run / "full_paper.audit.json") if run else {}
    for check in audit.get("checks", []):
        if isinstance(check, dict) and check.get("name") == "Q9_numeric_density" and check.get("passed") is False:
            return True
    return False


def _current_gate_status(bridge: dict[str, Any], run_name: str) -> str:
    for row in bridge.get("considered", []):
        if isinstance(row, dict) and row.get("run") == run_name:
            return str(row.get("status") or bridge.get("status") or "")
    return str(bridge.get("status") or "")


def _submit_current_candidate(
    *,
    runs_root: Path,
    date: str,
    submit: bool,
    remote_seen: set[str],
    candidate_run: Path,
) -> dict[str, Any]:
    bridge = submit_bridge.run_cycle(
        runs_root=runs_root,
        date=date,
        submit=submit,
        remote_loader=(lambda: (remote_seen, None)) if submit else None,
        candidate_run=candidate_run,
    )
    if bridge.get("status") != "no_eligible_research_paper":
        return bridge
    candidate_path, considered = submit_bridge.select_candidate(
        runs_root,
        runs_root / submit_bridge.LEDGER_DIR / "_submitted_fingerprints.json",
        remote_seen=remote_seen,
        candidate_run=candidate_run,
    )
    if candidate_path is None:
        return bridge
    first_bridge = bridge
    bridge = submit_bridge.run_cycle(
        runs_root=runs_root,
        date=date,
        submit=submit,
        remote_loader=(lambda: (remote_seen, None)) if submit else None,
        candidate_run=candidate_run,
    )
    bridge["retry_after_no_eligible"] = {
        "first_status": first_bridge.get("status"),
        "first_considered": first_bridge.get("considered"),
        "eligibility_recheck": considered,
    }
    return bridge


def _should_retry_same_topic(attempt: dict[str, Any], *, auto_selected: bool = True) -> bool:
    if int(attempt.get("submitted") or 0):
        return False
    status = str(attempt.get("gate_status") or attempt.get("submit_status") or "").split(":", 1)[0]
    if auto_selected and status in _NO_AUTO_RETRY_STATUSES:
        return False
    return not str(attempt.get("failure_class") or "").startswith(("B_", "D_"))


def _same_gate_failure_count(attempts: list[dict[str, Any]], topic: str, status: str) -> int:
    code = status.split(":", 1)[0]
    if not code or code in {"eligible", "submitted_to_researka"}:
        return 0
    return sum(
        1 for row in attempts
        if row.get("topic") == topic
        and not int(row.get("submitted") or 0)
        and str(row.get("gate_status") or row.get("submit_status") or "").split(":", 1)[0] == code
    )


def _same_topic_retry_count(attempts: list[dict[str, Any]], topic: str) -> int:
    return sum(
        1 for row in attempts
        if row.get("topic") == topic
        and not int(row.get("submitted") or 0)
        and str(row.get("failure_class") or "").startswith(("A_", "C_"))
    )


def _repair_reason_for_retry(run: Path, attempt: dict[str, Any]) -> str:
    status = str(attempt.get("gate_status") or attempt.get("submit_status") or "")
    if str(attempt.get("failure_class") or "").startswith("A_"):
        return status
    if status == "audit_not_all_green":
        surface = _read_json(run / "full_paper.journal_surface.json")
        if surface and surface.get("passed") is not True:
            return "journal_surface_not_passed"
    return ""


def _auto_seed_limit() -> int:
    try:
        return max(1, int(os.environ.get("RESEARCH_AGENT_AUTO_SEED_LIMIT", str(AUTO_SEED_LIMIT))))
    except ValueError:
        return AUTO_SEED_LIMIT


def _seed_topic_timeout(timeout: int | None) -> int:
    try:
        cap = max(1, int(os.environ.get("RESEARCH_AGENT_SEED_TOPIC_TIMEOUT_SECONDS", str(SEED_TOPIC_TIMEOUT_SECONDS))))
    except ValueError:
        cap = SEED_TOPIC_TIMEOUT_SECONDS
    return min(timeout, cap) if timeout and timeout > 0 else cap


def _publish_seed_timeout(timeout: int | None) -> int:
    try:
        cap = max(1, int(os.environ.get(
            "RESEARCH_AGENT_PUBLISH_SEED_TIMEOUT_SECONDS",
            os.environ.get("RESEARCH_AGENT_SEED_TOPIC_TIMEOUT_SECONDS", str(PUBLISH_SEED_TIMEOUT_SECONDS)),
        )))
    except ValueError:
        cap = PUBLISH_SEED_TIMEOUT_SECONDS
    return min(timeout, cap) if timeout and timeout > 0 else cap


def _seed_discovery_timeout() -> float:
    raw = os.environ.get("RESEARCH_AGENT_DISCOVERY_TIMEOUT_SECONDS", "30")
    try:
        return min(120.0, max(1.0, float(raw)))
    except ValueError:
        return 30.0


def _seed_sources() -> list[str]:
    raw = os.environ.get("RESEARCH_AGENT_SEED_SOURCES", "").strip()
    if raw:
        return [part for part in re.split(r"[,\s]+", raw) if part]
    return []


def _corpus_repair_limit() -> int:
    try:
        return max(0, int(os.environ.get("RESEARCH_AGENT_CORPUS_REPAIR_LIMIT", str(CORPUS_REPAIR_LIMIT))))
    except ValueError:
        return CORPUS_REPAIR_LIMIT


def _receipt_preflight_repair_rounds() -> int:
    try:
        return max(0, int(os.environ.get("RESEARCH_AGENT_RECEIPT_PREFLIGHT_REPAIR_ROUNDS", str(RECEIPT_PREFLIGHT_REPAIR_ROUNDS))))
    except ValueError:
        return RECEIPT_PREFLIGHT_REPAIR_ROUNDS


def _receipt_repair_seed_limit(
    n_receipts: int,
    min_receipts: int,
    round_idx: int,
    *,
    current_quant_claims: int = 0,
    n_primary_tier: int = 0,
    n_direct_receipts: int = 0,
) -> int:
    n_receipts = max(0, n_receipts)
    n_primary_tier = max(0, n_primary_tier)
    n_direct_receipts = max(0, n_direct_receipts)
    missing_receipts = max(1, min_receipts - n_receipts)
    missing_primary = max(0, PREFLIGHT_MIN_PRIMARY_TIER - n_primary_tier)
    missing_direct = max(0, PREFLIGHT_MIN_DIRECT_RECEIPTS - n_direct_receipts)
    missing = max(missing_receipts, missing_primary, missing_direct)
    current_quant_claims = max(0, current_quant_claims)
    observed_receipts = max(1, n_receipts)
    claims_per_receipt = max(1, (max(current_quant_claims, observed_receipts) + observed_receipts - 1) // observed_receipts)
    return max(min_receipts, current_quant_claims + missing * claims_per_receipt * (round_idx + 1))


def _seed_topic(
    topic: str,
    *,
    timeout: int | None = None,
    force_extract: bool = False,
    seed_limit: int | None = None,
) -> dict[str, Any]:
    before = _quant_claim_count(topic)
    seed_limit = max(1, seed_limit or _auto_seed_limit())
    cmd = [
        sys.executable, "scripts/seed_topic_corpus.py", "--topic", topic,
        "--limit", str(seed_limit), "--max-per-source", str(seed_limit),
    ]
    sources = _seed_sources()
    if sources:
        cmd.extend(["--sources", *sources])
    if force_extract:
        cmd.append("--force-extract")
    env = os.environ.copy()
    v5_configured = (
        (env.get("RESEARKA_FULLRAW_SEARCH_URL") or env.get("V5_MEMO_FULL_RAW_CORPUS_SEARCH_URL"))
        and (env.get("RESEARKA_FULLRAW_TOKEN") or env.get("V5_MEMO_FULL_RAW_CORPUS_TOKEN"))
    )
    uses_v5 = not sources or "v5_fullraw" in sources
    if v5_configured and uses_v5:
        timeout_value = str(_seed_discovery_timeout())
        env.setdefault("RESEARKA_FULLRAW_QUERY_TIMEOUT", timeout_value)
        env.setdefault("V5_MEMO_FULL_RAW_QUERY_TIMEOUT", timeout_value)
    seed_timeout = _seed_topic_timeout(timeout)
    try:
        result = subprocess.run(cmd, cwd=ROOT, check=False, timeout=seed_timeout, capture_output=True, text=True, env=env)
    except subprocess.TimeoutExpired as exc:
        after = _quant_claim_count(topic)
        status = "corpus_seeded" if after else "corpus_seed_failed"
        stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else str(exc.stderr or "")
        return {
            "status": status,
            "return_code": SYNTHESIS_TIMEOUT_RETURN_CODE,
            "n_quant_claims_before": before,
            "n_quant_claims": after,
            "seed_limit": seed_limit,
            "seed_timeout_seconds": seed_timeout,
            "seed_timeout_expired": True,
            "error": f"{type(exc).__name__}: {exc}",
            "stderr_tail": stderr[-1200:],
        }
    except OSError as exc:
        return {
            "status": "corpus_seed_failed",
            "return_code": None,
            "n_quant_claims_before": before,
            "n_quant_claims": _quant_claim_count(topic),
            "seed_limit": seed_limit,
            "error": f"{type(exc).__name__}: {exc}",
        }
    after = _quant_claim_count(topic)
    status = "corpus_seeded" if result.returncode == 0 and after else "corpus_seed_empty" if result.returncode == 0 else "corpus_seed_failed"
    return {
        "status": status,
        "return_code": int(result.returncode),
        "n_quant_claims_before": before,
        "n_quant_claims": after,
        "seed_limit": seed_limit,
        "stderr_tail": result.stderr[-1200:],
    }


def _ensure_topic_corpus(
    topic: str,
    *,
    dry_run: bool,
    timeout: int | None = None,
    min_quant_claims: int = 1,
) -> dict[str, Any]:
    before = _quant_claim_count(topic)
    if before >= min_quant_claims:
        return {"status": "corpus_ready", "n_quant_claims": before}
    if dry_run:
        return {"status": "corpus_missing_dry_run", "n_quant_claims": before}
    return _seed_topic(topic, timeout=timeout)


def _repair_topic_corpus(
    topic: str,
    *,
    dry_run: bool,
    timeout: int | None = None,
    seed_limit: int | None = None,
    force_extract: bool = True,
) -> dict[str, Any]:
    before = _quant_claim_count(topic)
    if dry_run:
        return {"status": "corpus_repair_dry_run", "n_quant_claims": before}
    result = _seed_topic(topic, timeout=timeout, force_extract=force_extract, seed_limit=seed_limit)
    return {
        **result,
        "status": "corpus_repaired" if result.get("status") in {"corpus_ready", "corpus_seeded"} else result.get("status"),
    }


def prepare_candidate_buffer(
    *,
    runs_root: Path = RUNS,
    target_ready: int = 3,
    max_repairs: int = 3,
    max_attempts: int | None = None,
    timeout: int | None = None,
    dry_run: bool = False,
    remote_loader: Callable[[], tuple[set[str], str | None]] | None = None,
) -> dict[str, Any]:
    """Build a short-lived reserve of receipt-validated fresh topics."""
    target_ready = max(1, target_ready)
    max_repairs = max(0, max_repairs)
    max_attempts = max(target_ready, max_repairs) if max_attempts is None else max(1, max_attempts)
    ledger_dir = runs_root / LEDGER_DIR
    now = dt.datetime.now(dt.UTC)
    topics = discover_topics()
    remote_seen, remote_error = (remote_loader or submit_bridge._remote_published_fingerprints)()
    report: dict[str, Any] = {
        "generated_at": now.isoformat(), "target_ready": target_ready,
        "max_repairs": max_repairs, "max_attempts": max_attempts, "thresholds": _candidate_buffer_thresholds(),
        "ready": [], "attempts": [], "attempted_count": 0, "repair_count": 0,
    }
    if remote_error:
        report.update({"status": "remote_dedupe_failed", "error": remote_error, "ready_count": 0})
        _write_json(ledger_dir / CANDIDATE_BUFFER, report)
        return report

    terminal = _terminal_topics(runs_root)
    pool = _fresh_topic_pool(
        topics,
        ledger_dir,
        remote_seen=remote_seen,
        exclude=terminal,
        allow_recent_blocked_fallback=False,
        prefer_without_recent_failures=False,
    )
    report["candidate_pool_count"] = len(pool)
    previous = _read_json(ledger_dir / CANDIDATE_BUFFER)
    prepared_rows = _prepared_candidate_rows(ledger_dir, now=now)
    prepared = set(prepared_rows) & set(pool)
    still_prepared = {
        topic for topic in prepared if _quant_claim_source_precision(topic, floor=SOURCE_TOPIC_REPAIR_FLOOR)[0]
    }
    report["ready"] = [row for topic, row in prepared_rows.items() if topic in still_prepared]
    report["attempts"] = _recent_candidate_buffer_attempts(previous, now=now)
    recent_attempted = {str(row.get("topic") or "") for row in report["attempts"] if row.get("topic")}
    attempted = terminal | still_prepared | (recent_attempted - (prepared - still_prepared))
    while len(report["ready"]) < target_ready and report["attempted_count"] < max_attempts:
        topic = select_topic(
            topics,
            ledger_dir,
            runs_root=runs_root,
            remote_seen=remote_seen,
            exclude=attempted,
            allow_recent_blocked_fallback=False,
            prefer_without_recent_failures=False,
            prefer_source_fit=True,
        )
        if not topic:
            break
        attempted.add(topic)
        preflight = _receipt_preflight(
            topic, runs_root / "_candidate_prepare" / topic, timeout=timeout, repair=False, dry_run=dry_run,
        )
        quant_claims = _quant_claim_count(topic)
        source_precise, source_precision, _ = _quant_claim_source_precision(topic, floor=SOURCE_TOPIC_REPAIR_FLOOR)
        decision = decide_candidate(
            topic,
            review_type=None,
            evidence=CandidateEvidence(
                n_quant_claims=quant_claims,
                n_receipts=int(preflight.get("n_receipts") or 0),
                n_primary_tier=int(preflight.get("n_primary_tier") or 0),
                n_direct_receipts=int(preflight.get("n_direct_receipts") or 0),
                source_precision_ok=source_precise,
            ),
            thresholds=_CANDIDATE_THRESHOLDS,
        )
        ready = decision.ready_for_synthesis and preflight.get("passed") is True
        repair: dict[str, Any] = {"status": "not_needed"}
        if not ready and report["repair_count"] < max_repairs:
            if source_precise:
                repair = _repair_topic_corpus(topic, dry_run=dry_run, timeout=timeout, force_extract=True)
            else:
                repair = _repair_low_source_precision_corpus(topic, dry_run=dry_run, timeout=timeout)
            report["repair_count"] += 1
            preflight = _receipt_preflight(topic, runs_root / "_candidate_prepare" / topic, timeout=timeout, repair=False, dry_run=dry_run)
            quant_claims = _quant_claim_count(topic)
            source_precise, source_precision, _ = _quant_claim_source_precision(topic, floor=SOURCE_TOPIC_REPAIR_FLOOR)
            decision = decide_candidate(
                topic,
                review_type=None,
                evidence=CandidateEvidence(
                    n_quant_claims=quant_claims,
                    n_receipts=int(preflight.get("n_receipts") or 0),
                    n_primary_tier=int(preflight.get("n_primary_tier") or 0),
                    n_direct_receipts=int(preflight.get("n_direct_receipts") or 0),
                    source_precision_ok=source_precise,
                ),
                thresholds=_CANDIDATE_THRESHOLDS,
            )
            ready = decision.ready_for_synthesis and preflight.get("passed") is True
        elif not ready:
            repair = {"status": "repair_budget_exhausted"}
        row = {
            "topic": topic, "attempted_at": now.isoformat(),
            "quant_claims": quant_claims, "repair_status": repair.get("status"),
            "receipt_preflight": preflight, "source_topic_precision_after": source_precision,
        }
        report["attempts"].append(row)
        report["attempted_count"] += 1
        if ready:
            report["ready"].append({
                "topic": topic, "validated_at": now.isoformat(),
                "n_quant_claims": quant_claims, "n_receipts": int(preflight.get("n_receipts") or 0),
                "n_primary_tier": int(preflight.get("n_primary_tier") or 0),
                "n_direct_receipts": int(preflight.get("n_direct_receipts") or 0),
                "source_topic_precision": source_precision,
            })
        report.update({"status": "candidate_buffer_building", "ready_count": len(report["ready"])})
        _write_json(ledger_dir / CANDIDATE_BUFFER, report)

    ready_count = len(report["ready"])
    report["ready_count"] = ready_count
    report["status"] = _candidate_buffer_status(ready_count, target_ready)
    _write_json(ledger_dir / CANDIDATE_BUFFER, report)
    return report


def _quant_claim_identity(path: Path) -> str:
    data = _read_json(path)
    fields = [
        path.stem,
        data.get("paper_id"),
        data.get("title"),
        data.get("source_title"),
        data.get("citation"),
    ]
    meta = data.get("metadata")
    if isinstance(meta, dict):
        fields.extend([meta.get("title"), meta.get("citation")])
    return " ".join(str(field or "") for field in fields).lower()


def _entity_topic_terms(topic: str) -> tuple[str, ...]:
    """Entity/synonym retrieval terms for *topic*, minus the bare slug phrase
    and bare non-leading slug modifiers (e.g. ``lifespan`` in
    ``rapamycin_lifespan_effects``). Reads only the generated pack record so
    .toml-only field-named topics (e.g. ``metabolomic_age_clocks``) yield ()
    and keep the gate's existing behavior. The entity/modifier split is read
    from the slug itself (no per-topic word lists), universal across domains.
    """
    try:
        record = json.loads((TOPIC_PACKS_DB / topic / "latest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ()
    pack_data = record.get("pack_data") if isinstance(record.get("pack_data"), dict) else record
    retrieval = pack_data.get("retrieval") if isinstance(pack_data, dict) else {}
    raw = retrieval.get("topic_terms", ()) if isinstance(retrieval, dict) else ()
    slug_tokens = [t for t in re.findall(r"[a-z0-9]+", topic.lower()) if len(t) >= 3]
    modifiers = set(slug_tokens[1:]) if len(slug_tokens) >= 2 else set()
    entity = slug_tokens[0] if slug_tokens else ""
    slug_phrase = " ".join(topic.replace("_", " ").replace("-", " ").lower().split())
    seen: set[str] = set()
    out: list[str] = []
    for term in raw:
        norm = " ".join(str(term).replace("_", " ").replace("-", " ").lower().split())
        if not norm or norm == slug_phrase or norm in seen:
            continue
        if " " not in norm and norm != entity and norm in modifiers:
            continue
        seen.add(norm)
        out.append(norm)
    return tuple(out)


def _on_entity_quant_claims(paths: Sequence[Path], entity_terms: Sequence[str]) -> set[Path]:
    """Subset of *paths* whose identity names the topic entity or a synonym."""
    if not entity_terms:
        return set()
    on_entity: set[Path] = set()
    for path in paths:
        haystack = " ".join(_quant_claim_identity(path).replace("_", " ").replace("-", " ").lower().split())
        # Word-boundary match so a short entity token (``nad``) does not
        # substring-hit unrelated words (``gonad``, ``nadolol``); multi-word
        # synonyms ("nicotinamide riboside") still match as a phrase.
        if any(re.search(rf"\b{re.escape(term)}\b", haystack) for term in entity_terms):
            on_entity.add(path)
    return on_entity


_MODIFIER_SUFFIXES = ("ization", "isation", "ism", "ies", "ing", "es", "s")


def _modifier_stem(word: str) -> str:
    """Morphological stem of a slug modifier so the scope match catches the
    whole word family — ``metabolism`` -> ``metabol`` (prefix-matches
    metabolic/metabolite), ``regimens`` -> ``regimen`` — not just the literal
    slug token. Strips a small fixed set of common English suffixes with a
    length guard; universal, no per-topic word lists. A modifier with no
    strippable suffix (``lifespan``, ``cardiovascular``) is returned unchanged,
    so content scopes keep their exact prefix match. This unblocks genuine
    aspect topics (a fasting-metabolism corpus where studies say "metabolic
    rate", not the literal word "metabolism") WITHOUT relaxing the floor, so a
    thin variant with too few on-aspect sources still fails the gate."""
    w = word.lower()
    for suf in _MODIFIER_SUFFIXES:
        if w.endswith(suf) and len(w) - len(suf) >= 4:
            return w[: len(w) - len(suf)]
    return w


def _claim_text_has_scope(path: Path, modifiers: Sequence[str]) -> bool:
    """True if the source's full claim text evidences a non-entity topic
    modifier (e.g. ``lifespan``), not just the entity in its title. A lifespan
    study may title itself "survival", so the modifier is matched against the
    whole claim record, not the title identity. Modifiers are slug-derived (no
    per-topic word lists) and matched by morphological STEM so the whole word
    family counts (see _modifier_stem)."""
    if not modifiers:
        return True
    try:
        body = path.read_text(encoding="utf-8", errors="ignore").lower()
    except OSError:
        return False
    return any(re.search(rf"\b{re.escape(_modifier_stem(m))}", body) for m in modifiers)


def _quant_claim_source_precision(topic: str, *, floor: float | None = None) -> tuple[bool, str, list[Path]]:
    floor = submit_bridge.SOURCE_TOPIC_PRECISION_FLOOR if floor is None else floor
    tokens = submit_bridge._topic_tokens(topic)
    aliases = source_gate_aliases(
        topic, topic_aliases(topic, root=TOPIC_PACKS.parent, include_generated_terms=False),
    )
    paths = sorted((CORPORA / topic / "quant_claims").glob("*.quant_claims.json"))
    if not tokens or not paths:
        return True, "source_topic_precision_unscored", []
    misses = [
        path for path in paths
        if not is_source_topic_specific(topic, _quant_claim_identity(path), aliases=aliases)
    ]
    hits = len(paths) - len(misses)
    ratio = hits / len(paths)
    if ratio < floor:
        # Drift matcher requires the literal slug modifier (``lifespan``) so a
        # genuine entity-only paper ("Rapamycin extends survival in aged mice")
        # scores off-topic and the whole corpus is quarantined to zero. When the
        # ratio is below the floor, fall back to an entity-grounded ABSOLUTE
        # count: keep the subset whose identity names the entity/synonym and
        # pass iff that core meets the synthesis minimum. misses become the
        # off-entity remainder, so the (forced) quarantine strips only those and
        # never the on-entity core. An empty core (generic same-field bundle)
        # still fails — this is not a ratio relaxation.
        entity_terms = _entity_topic_terms(topic)
        on_entity = _on_entity_quant_claims(paths, entity_terms)
        # Codex adversarial review (2026-06-13): an entity-only core can be a
        # generic entity corpus, not the scoped compound topic — exactly the
        # dilution this gate exists to catch. Require the retained core to ALSO
        # evidence a non-entity slug modifier (``lifespan`` for
        # rapamycin_lifespan) in its claim text, so the core is genuinely
        # topic-specific and not just every paper that names the drug. Modifiers
        # are slug-derived (no per-topic word lists); single-entity topics have
        # none and keep the entity-only core.
        ent_words = {w for term in entity_terms for w in str(term).split()}
        modifiers = tuple(t for t in tokens if t not in ent_words)
        if modifiers:
            on_entity = {p for p in on_entity if _claim_text_has_scope(p, modifiers)}
        if len(on_entity) >= PREFLIGHT_MIN_QUANT_CLAIMS:
            scoped_misses = [path for path in paths if path not in on_entity]
            return (
                True,
                f"source_topic_precision_scoped_floor:{len(on_entity)}>={PREFLIGHT_MIN_QUANT_CLAIMS}"
                f"(ratio={hits}/{len(paths)}<{floor:.2f})",
                scoped_misses,
            )
        return False, f"source_topic_precision_low:{hits}/{len(paths)}<{floor:.2f}", misses
    return True, f"source_topic_precision_ok:{hits}/{len(paths)}", misses


def _repair_low_source_precision_corpus(
    topic: str, *, dry_run: bool, timeout: int | None = None, force: bool = False,
    reseed: bool = True,
) -> dict[str, Any]:
    ok, before_status, misses = _quant_claim_source_precision(topic, floor=SOURCE_TOPIC_REPAIR_FLOOR)
    if ok and not (force and misses):
        n_quant_claims = _quant_claim_count(topic)
        return {
            "status": "source_precision_ready" if n_quant_claims else "source_precision_repair_incomplete",
            "topic": topic,
            "source_topic_precision": before_status,
            "n_quant_claims": n_quant_claims,
        }
    before = _quant_claim_count(topic)
    if dry_run:
        return {
            "status": "source_precision_repair_dry_run",
            "topic": topic,
            "source_topic_precision_before": before_status,
            "off_topic_quant_claims": len(misses),
            "n_quant_claims": before,
        }
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    quarantine = CORPORA / topic / "quant_claims_quarantine" / stamp
    moved = 0
    for path in misses:
        if not path.exists():
            continue
        quarantine.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(quarantine / path.name))
        moved += 1
    seed = (
        _repair_topic_corpus(topic, dry_run=False, timeout=timeout)
        if reseed
        else {"status": "source_precision_pruned", "n_quant_claims": _quant_claim_count(topic)}
    )
    ok_after, after_status, misses_after = _quant_claim_source_precision(topic, floor=SOURCE_TOPIC_REPAIR_FLOOR)
    post_seed_moved = 0
    if not ok_after and reseed:
        post_seed_dir = quarantine / "post_seed"
        for path in misses_after:
            if not path.exists():
                continue
            post_seed_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), str(post_seed_dir / path.name))
            post_seed_moved += 1
        ok_after, after_status, _ = _quant_claim_source_precision(topic, floor=SOURCE_TOPIC_REPAIR_FLOOR)
    n_quant_claims = _quant_claim_count(topic)
    return {
        "status": "source_precision_repaired" if ok_after and n_quant_claims else "source_precision_repair_incomplete",
        "topic": topic,
        "source_topic_precision_before": before_status,
        "source_topic_precision_after": after_status,
        "off_topic_quant_claims_quarantined": moved + post_seed_moved,
        "quarantine_dir": str(quarantine) if moved else "",
        "post_seed_quarantined": post_seed_moved,
        "n_quant_claims_before": before,
        "n_quant_claims": n_quant_claims,
        "reseed": reseed,
        "seed": seed,
    }


def _source_precision_attempt(
    topic: str,
    out_dir: Path,
    gate_status: str,
    *,
    corpus: Mapping[str, Any],
    source_repair: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    attempt: dict[str, Any] = {
        "topic": topic,
        "out_dir": out_dir.name,
        "synthesis_return_code": None,
        "submit_status": gate_status,
        "gate_status": gate_status,
        "failure_class": _failure_class(gate_status),
        "submitted": 0,
        "corpus": dict(corpus),
    }
    if source_repair is not None:
        attempt["source_precision_repair"] = dict(source_repair)
    return attempt


def _gate_attempt(
    topic: str,
    out_dir: Path,
    gate_status: str,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "topic": topic,
        "out_dir": out_dir.name,
        "synthesis_return_code": None,
        "submit_status": gate_status,
        "gate_status": gate_status,
        "failure_class": _failure_class(gate_status),
        "submitted": 0,
        **extra,
    }


def _attempt_gate_counts(attempts: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for attempt in attempts:
        status = str(attempt.get("gate_status") or attempt.get("submit_status") or "").split(":", 1)[0]
        if status:
            counts[status] += 1
    return dict(sorted(counts.items()))


def run_cycle(
    *,
    runs_root: Path = RUNS,
    date: str,
    run_synthesis: bool = False,
    synthesis_dry_run: bool = False,
    submit: bool = False,
    mode: str = "mixed",
    topic: str | None = None,
    remote_loader: RemoteLoader | None = None,
    revision_loader: RevisionLoader | None = None,
    submit_cycle: SubmitCycle | None = None,
    ensure_corpus: CorpusBuilder | None = None,
    timeout: int | None = None,
    max_attempts: int = 0,
    max_revise_attempts: int = 3,
    decision_poll_seconds: int = DECISION_POLL_SECONDS,
    decision_poll_interval_seconds: int = DECISION_POLL_INTERVAL_SECONDS,
    decision_sleep: Sleeper = time.sleep,
    cycle_budget_seconds: int = CYCLE_BUDGET_SECONDS,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    started_at = dt.datetime.now(dt.UTC).isoformat()
    started_mono = clock()

    def child_timeout() -> int | None:
        return _remaining_timeout(
            timeout,
            started_mono=started_mono,
            cycle_budget_seconds=cycle_budget_seconds,
            clock=clock,
        )

    mode = mode if mode in {"fresh", "revise", "mixed"} else "mixed"
    ledger_dir = runs_root / LEDGER_DIR
    ledger_path = _cycle_ledger_path(ledger_dir, date, mode)
    ledger: dict[str, Any] = {
        "date": date,
        "started_at": started_at,
        "run_synthesis": run_synthesis,
        "synthesis_dry_run": synthesis_dry_run,
        "submit": submit,
        "mode": mode,
        "submitted": 0,
        "published": 0,
        "status": "started",
        "attempts": [],
    }
    with _lock(ledger_dir, f".lock.{mode}") as locked:
        if not locked:
            ledger["status"] = "cycle_already_running"
            _write_json(ledger_path, ledger)
            return ledger
        topics = discover_topics()
        if topic and topic not in topics:
            ledger.update({"status": "topic_not_available", "topic": topic})
            _write_json(ledger_path, ledger)
            return ledger
        if submit and submit_cycle is None and not submit_bridge._token()[0]:
            ledger.update({"status": "submit_not_configured", "reason": "missing_v3_submit_token"})
            _write_json(ledger_path, ledger)
            return ledger
        remote_seen: set[str] = set()
        if submit:
            remote_seen, remote_error = (remote_loader or submit_bridge._remote_published_fingerprints)()
            ledger["remote_dedupe"] = {"checked": True, "known_fingerprints": len(remote_seen)}
            if remote_error:
                ledger.update({"status": "remote_dedupe_failed", "reason": remote_error})
                _write_json(ledger_path, ledger)
                return ledger
            ledger["publication_reconciliation_preflight"] = reconcile_publication_ledgers(
                runs_root=runs_root,
                date=date,
                remote_loader=lambda: (remote_seen, None),
            )
        remote_revision: dict[str, Any] | None = None
        terminal_excluded: set[str] = set()
        if submit and topic is None and mode != "fresh" and (revision_loader is not None or submit_cycle is None):
            remote_revision, revision_error = _pending_remote_revision(
                runs_root,
                ledger_dir,
                loader=revision_loader,
                published_loader=lambda: (remote_seen, None),
            )
            ledger["remote_revisions"] = {"checked": True, "matched": bool(remote_revision)}
            if revision_error:
                ledger["remote_revisions"]["error"] = revision_error
        pending_revision_excluded: set[str] = set()
        if submit and topic is None and mode == "fresh" and revision_loader is None and submit_cycle is None:
            pending_revision_excluded, revision_error = _pending_remote_revision_topics(
                runs_root,
                ledger_dir,
                loader=revision_loader,
                published_loader=lambda: (remote_seen, None),
            )
            ledger["pending_revision_exclusions"] = {"checked": True, "topics": sorted(pending_revision_excluded)}
            if revision_error:
                ledger["pending_revision_exclusions"]["error"] = revision_error
        if submit and topic is None and revision_loader is None:
            # Production only (live reviews poll): drop topics whose latest review
            # is terminal (reject, or a revise with no actionable revisions such as
            # a duplicate-overlap flag) so the bot stops re-synthesising them.
            if submit_cycle is None:
                latest_reviews, review_error = _latest_reviews_by_title()
                if not review_error:
                    _record_review_decisions(ledger_dir, latest_reviews)
                terminal_excluded = _terminal_topics(
                    runs_root, loader=lambda: (latest_reviews, review_error),
                )
            else:
                terminal_excluded = _terminal_topics(runs_root)
            if terminal_excluded:
                ledger["terminal_excluded_topics"] = sorted(terminal_excluded)
        # Skip topics that keep failing the SAME deterministic gate — re-rendering
        # them only burns a slot (plan F). Excluded from fresh auto-selection
        # below, and pending revises for such topics are marked terminal in the
        # loop (a forced --topic is left untouched on purpose).
        surface_repeat = _surface_repeat_topics(ledger_dir, runs_root=runs_root)
        if surface_repeat:
            ledger["surface_repeat_excluded_topics"] = sorted(surface_repeat)
        prepared_candidates = _prepared_candidate_topics(ledger_dir)
        preflight_blocked = (
            set() if topic else _recent_preflight_blocked_topics(ledger_dir) - prepared_candidates
        )
        if preflight_blocked:
            ledger["preflight_blocked_topics"] = sorted(preflight_blocked)
        receipt_preflight_blocked = (
            set() if topic else _recent_receipt_preflight_blocked_topics(ledger_dir) - prepared_candidates
        )
        writer_gate_policy: dict[str, dict[str, Any]] = {} if topic else _writer_gate_repeat_policy(ledger_dir)
        writer_gate_skip = {
            t for t, p in writer_gate_policy.items()
            if p.get("action") == "skip_topic"
        }
        if writer_gate_skip:
            ledger["writer_gate_skip_topics"] = sorted(writer_gate_skip)
        if writer_gate_policy:
            ledger["writer_gate_repeat_policy"] = writer_gate_policy
        submitted_topics = _recent_submitted_topics(topics, ledger_dir)
        published_topics = _published_topics(topics, remote_seen, ledger_dir)
        corpus_repaired_ok: set[str] = set()
        source_precision_repaired_ok: set[str] = set()
        source_precision_repaired_checkable: set[str] = set()
        current_source_precision: set[str] = set()
        recent_source_precision_failed: set[str] = set()
        source_precision_auto_excluded: set[str] = set() if topic else _unrepairable_source_precision_topics(ledger_dir)
        if source_precision_auto_excluded:
            ledger["source_precision_unrepairable_topics"] = sorted(source_precision_auto_excluded)
        if run_synthesis and mode != "revise" and topic is None:
            repairs: list[dict[str, Any]] = []
            current_source_precision = _current_low_source_precision_topics(topics)
            recent_source_precision_failed = _source_precision_repair_topics(ledger_dir)
            if remote_revision:
                current_source_precision.discard(str(remote_revision.get("topic") or ""))
            if current_source_precision:
                ledger["source_precision_backlog_topics"] = sorted(current_source_precision)
                ledger["source_precision_backlog_count"] = len(current_source_precision)
            if recent_source_precision_failed:
                ledger["source_precision_recent_blocked_topics"] = sorted(recent_source_precision_failed)
                source_precision_auto_excluded |= recent_source_precision_failed
            repairable = (
                _corpus_repair_topics(ledger_dir) | current_source_precision
            ) - terminal_excluded - submitted_topics - published_topics - pending_revision_excluded - surface_repeat - writer_gate_skip - recent_source_precision_failed
            source_precision_repairable = _source_precision_repair_topics(ledger_dir) | current_source_precision
            selectable_before_repair = select_topic(
                topics,
                ledger_dir,
                runs_root=runs_root,
                remote_seen=remote_seen,
                exclude=(
                    terminal_excluded | submitted_topics | published_topics
                    | pending_revision_excluded | surface_repeat | preflight_blocked
                    | writer_gate_skip | source_precision_auto_excluded | current_source_precision
                ),
            )
            ready_before_repair = (
                bool(selectable_before_repair)
                and _topic_has_quant_floor(str(selectable_before_repair))
            )
            if selectable_before_repair:
                repairable = set() if ready_before_repair else repairable & current_source_precision
                if ready_before_repair:
                    source_precision_auto_excluded |= current_source_precision
            source_precision_repair_attempted: set[str] = set()
            repair_timeout = _publish_seed_timeout(timeout)
            repair_order = sorted(
                (
                    repair_topic for repair_topic in repairable
                    if (
                        repair_topic in source_precision_repairable
                        and _source_precision_repair_candidate(repair_topic)
                    )
                    or _fresh_corpus_repair_candidate(repair_topic)
                ),
                key=lambda t: (
                    0 if t in prepared_candidates else 1,
                    -_source_precision_retained_claim_count(t) if t in source_precision_repairable else -_quant_claim_count(t),
                    -_quant_claim_count(t),
                    -_topic_support_score(t),
                    _attempted_at(t, ledger_dir),
                    t,
                ),
            )
            repair_successes = 0
            repair_scan_limit = max(_corpus_repair_limit(), SOURCE_PRECISION_REPAIR_SCAN_LIMIT)
            for repair_topic in repair_order[:repair_scan_limit]:
                if repair_topic in source_precision_repairable:
                    source_precision_repair_attempted.add(repair_topic)
                    repair = _repair_low_source_precision_corpus(
                        repair_topic, dry_run=synthesis_dry_run, timeout=repair_timeout,
                    )
                else:
                    repair = _repair_topic_corpus(repair_topic, dry_run=synthesis_dry_run, timeout=repair_timeout)
                repairs.append({"topic": repair_topic, **repair})
                repair_publishable = (
                    _source_precision_repair_publishable(repair)
                    if repair_topic in source_precision_repairable
                    else int(repair.get("n_quant_claims") or 0) >= PREFLIGHT_MIN_QUANT_CLAIMS
                )
                if repair_publishable and repair_topic not in receipt_preflight_blocked:
                    preflight_blocked.discard(repair_topic)
                    surface_repeat.discard(repair_topic)
                    corpus_repaired_ok.add(repair_topic)
                if _source_precision_repair_publishable(repair):
                    source_precision_repaired_ok.add(repair_topic)
                elif _source_precision_repair_checkable(repair):
                    source_precision_repaired_checkable.add(repair_topic)
                if repair_publishable:
                    repair_successes += 1
                    prepared_unblocked = (
                        repair_topic in prepared_candidates and repair_topic in corpus_repaired_ok
                    )
                    if prepared_unblocked or repair_successes >= _corpus_repair_limit():
                        break
            source_precision_selectable = source_precision_repaired_ok or source_precision_repaired_checkable
            unrepaired_attempted = source_precision_repair_attempted - source_precision_selectable
            unattempted_source_precision = current_source_precision - source_precision_selectable - source_precision_repair_attempted
            source_precision_auto_excluded -= source_precision_selectable
            source_precision_auto_excluded |= unrepaired_attempted | unattempted_source_precision
            if source_precision_auto_excluded:
                ledger["source_precision_auto_excluded_topics"] = sorted(source_precision_auto_excluded)
            if repairs:
                ledger["corpus_repairs"] = repairs
        ledger["topic_status"] = _topic_status_map(
            topics, terminal=terminal_excluded, surface_repeat=surface_repeat, preflight_blocked=preflight_blocked,
            source_precision_blocked=source_precision_auto_excluded,
            submitted=submitted_topics,
        )
        attempted: set[str] = set()
        revise_window_excluded: set[str] = set()
        topic_supply_refreshed = False
        submitted_total = 0
        attempt_count = 0
        receipt_preflight_repairs_used = 0
        topic_supply_created: set[str] = set()
        while True:
            if topic and attempt_count:
                break
            if max_attempts > 0 and attempt_count >= max_attempts:
                break
            attempt_count += 1
            if cycle_budget_seconds > 0 and clock() - started_mono >= cycle_budget_seconds:
                ledger.update({
                    "status": "cycle_budget_exhausted",
                    "cycle_elapsed_seconds": int(clock() - started_mono),
                    "cycle_budget_seconds": cycle_budget_seconds,
                })
                break
            revision_source = remote_revision if remote_revision and not attempted else None
            if (
                mode == "revise"
                and revision_source is None
                and submit
                and topic is None
                and submitted_total == 0
                and ledger["attempts"]
                and (revision_loader is not None or submit_cycle is None)
            ):
                previous_key = _revision_key(remote_revision) if remote_revision else ""
                next_revision, revision_error = _pending_remote_revision(
                    runs_root,
                    ledger_dir,
                    loader=revision_loader,
                    published_loader=lambda: (remote_seen, None),
                    exclude_keys=revise_window_excluded,
                )
                ledger.setdefault("remote_revisions", {"checked": True})["refreshed_after_attempt"] = True
                if revision_error:
                    ledger["remote_revisions"]["refresh_error"] = revision_error
                elif next_revision and _revision_key(next_revision) != previous_key:
                    remote_revision = next_revision
                    revision_source = next_revision
                    ledger["remote_revisions"]["matched"] = True
            # Revise lane: only process pending revises — never rotate to a fresh
            # topic. If one pending revise fails terminally, try the next pending
            # revise in the same window; after the first successful submission,
            # stop so a single timer fire cannot flood Researka.
            if mode == "revise" and revision_source is None:
                if not ledger["attempts"]:
                    ledger["status"] = "no_revise_pending"
                break
            dynamic_preflight_blocked = set() if topic else _recent_preflight_blocked_topics(ledger_dir)
            dynamic_preflight_blocked -= prepared_candidates
            source_precision_selectable = source_precision_repaired_ok or source_precision_repaired_checkable
            dynamic_preflight_blocked -= corpus_repaired_ok | source_precision_selectable
            dynamic_receipt_preflight_blocked = set() if topic else _recent_receipt_preflight_blocked_topics(ledger_dir)
            dynamic_receipt_preflight_blocked -= prepared_candidates
            dynamic_receipt_preflight_blocked -= corpus_repaired_ok | source_precision_selectable
            if dynamic_preflight_blocked != preflight_blocked:
                preflight_blocked = dynamic_preflight_blocked
                ledger["preflight_blocked_topics"] = sorted(preflight_blocked)
            if dynamic_receipt_preflight_blocked != receipt_preflight_blocked:
                receipt_preflight_blocked = dynamic_receipt_preflight_blocked
            excluded = attempted | terminal_excluded | pending_revision_excluded | surface_repeat | preflight_blocked | writer_gate_skip | source_precision_auto_excluded
            selection_excluded = set(excluded)
            if topic is None and mode != "revise" and current_source_precision:
                recent_blocked = _recent_blocked_topics(ledger_dir)
                clean_ready_now = _has_clean_ready_topic(
                    topics,
                    exclude=selection_excluded | submitted_topics | published_topics | recent_blocked,
                    source_precision_blocked=current_source_precision,
                )
                if clean_ready_now:
                    selection_excluded |= current_source_precision - source_precision_repaired_ok
            source_precision_selectable = source_precision_repaired_ok or source_precision_repaired_checkable
            repaired_candidates = sorted(
                topic for topic in (corpus_repaired_ok | source_precision_selectable) - selection_excluded
                if _quant_claim_count(topic) >= PREFLIGHT_MIN_QUANT_CLAIMS
            )
            if (
                not revision_source
                and topic is None
                and mode == "fresh"
                and submit
                and not topic_supply_refreshed
                and not repaired_candidates
                and not current_source_precision
                and not any(_topic_has_quant_floor(t) for t in preflight_blocked - receipt_preflight_blocked)
                and not _has_clean_ready_topic(
                    topics,
                    exclude=selection_excluded | submitted_topics | published_topics | _recent_blocked_topics(ledger_dir),
                    source_precision_blocked=current_source_precision,
                )
            ):
                topic_supply_refreshed = True
                refresh = _refresh_topic_supply(
                    TOPIC_PACKS_DB,
                    skip_slugs=selection_excluded | submitted_topics | published_topics | set(topics),
                )
                ledger["topic_supply_refresh"] = refresh
                if refresh.get("created"):
                    topic_supply_created = _created_topic_slugs(refresh)
                    topics = discover_topics()
                    ledger["topic_supply_topic_count_after_refresh"] = len(topics)
            selected = (
                str(revision_source.get("topic") or "")
                if revision_source
                else topic or select_topic(
                    repaired_candidates or topics,
                    ledger_dir,
                    runs_root=runs_root,
                    remote_seen=remote_seen,
                    exclude=selection_excluded,
                    allow_recent_blocked_fallback=bool(repaired_candidates)
                    or not (mode == "fresh" and submit and topic is None),
                )
            )
            if not selected and not revision_source and topic is None and mode != "revise":
                retryable_preflight = {
                    t for t in preflight_blocked - receipt_preflight_blocked
                    if _topic_has_quant_floor(t)
                }
                if retryable_preflight:
                    selected = select_topic(
                        topics,
                        ledger_dir,
                        runs_root=runs_root,
                        remote_seen=remote_seen,
                        exclude=selection_excluded - retryable_preflight,
                        allow_recent_blocked_fallback=not (mode == "fresh" and submit),
                    )
                    if selected:
                        ledger["preflight_reseed_selected"] = selected
            if selected and selected in topic_supply_created:
                ledger["topic_supply_selected_after_refresh"] = selected
            if not selected:
                if (
                    ledger["attempts"]
                    and submit
                    and mode == "fresh"
                    and topic is None
                    and current_source_precision
                ):
                    fallback_order = sorted(
                        (
                            repair_topic for repair_topic in current_source_precision
                            if repair_topic not in (
                                terminal_excluded | submitted_topics | published_topics
                                | pending_revision_excluded | surface_repeat | writer_gate_skip
                                | attempted | recent_source_precision_failed
                            )
                            and _source_precision_repair_candidate(repair_topic)
                        ),
                        key=lambda t: (
                            -_source_precision_retained_claim_count(t),
                            -_quant_claim_count(t),
                            -_topic_support_score(t),
                            _attempted_at(t, ledger_dir),
                            t,
                        ),
                    )
                    fallback_repairs: list[dict[str, Any]] = []
                    for repair_topic in fallback_order[:max(_corpus_repair_limit(), SOURCE_PRECISION_REPAIR_SCAN_LIMIT)]:
                        repair = _repair_low_source_precision_corpus(
                            repair_topic, dry_run=synthesis_dry_run, timeout=_publish_seed_timeout(child_timeout()),
                        )
                        fallback_repairs.append({"topic": repair_topic, **repair})
                        if _source_precision_repair_publishable(repair):
                            source_precision_repaired_ok.add(repair_topic)
                            source_precision_auto_excluded.discard(repair_topic)
                            selected = repair_topic
                            break
                    if fallback_repairs:
                        ledger["source_precision_fallback_repairs"] = fallback_repairs
                    if selected:
                        ledger["source_precision_fallback_selected"] = selected
                if not selected and mode == "fresh" and topic is None and not topic_supply_refreshed:
                    topic_supply_refreshed = True
                    skip_slugs = selection_excluded | submitted_topics | published_topics | set(topics)
                    refresh = _refresh_topic_supply(TOPIC_PACKS_DB, skip_slugs=skip_slugs)
                    ledger["topic_supply_refresh"] = refresh
                    if refresh.get("created"):
                        topic_supply_created = _created_topic_slugs(refresh)
                        topics = discover_topics()
                        ledger["topic_supply_topic_count_after_refresh"] = len(topics)
                        selected = select_topic(
                            topics,
                            ledger_dir,
                            runs_root=runs_root,
                            remote_seen=remote_seen,
                            exclude=selection_excluded,
                            allow_recent_blocked_fallback=False,
                        )
                    if selected:
                        ledger["topic_supply_selected_after_refresh"] = selected
                if not selected and mode == "fresh" and topic is None:
                    topics = discover_topics()
                    submitted_topics = _recent_submitted_topics(topics, ledger_dir)
                    published_topics = _published_topics(topics, remote_seen, ledger_dir)
                    source_precision_selectable = source_precision_repaired_ok | source_precision_repaired_checkable
                    current_source_precision = _current_low_source_precision_topics(topics)
                    source_precision_auto_excluded = (
                        _unrepairable_source_precision_topics(ledger_dir)
                        | _source_precision_repair_topics(ledger_dir)
                        | (current_source_precision - source_precision_selectable)
                    ) - source_precision_selectable
                    selection_excluded = (
                        attempted | terminal_excluded | pending_revision_excluded
                        | _surface_repeat_topics(ledger_dir, runs_root=runs_root)
                        | _recent_preflight_blocked_topics(ledger_dir)
                        | writer_gate_skip | source_precision_auto_excluded
                    )
                    selected = select_topic(
                        topics,
                        ledger_dir,
                        runs_root=runs_root,
                        remote_seen=remote_seen,
                        exclude=selection_excluded,
                        allow_recent_blocked_fallback=False,
                    )
                    if selected:
                        ledger["fresh_last_chance_selected"] = selected
                if not selected:
                    if mode == "fresh" and topic is None and ledger.get("attempted_topic"):
                        ledger["last_attempted_topic"] = ledger["attempted_topic"]
                        ledger["topic"] = None
                    gate_counts = _attempt_gate_counts(ledger["attempts"])
                    if gate_counts:
                        ledger["fresh_terminal_gate_counts"] = gate_counts
                        ledger["no_submission_reason"] = "all_attempted_topics_gate_blocked"
                        ledger["status"] = "no_publishable_topic_available"
                    else:
                        ledger["status"] = "no_unpublished_topic_available"
                    break
            stamp = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
            out_dir = runs_root / f"synthesis-{selected}-v06-DAILY-{stamp}"
            seeded_frontier_corpus: dict[str, Any] | None = None
            if not revision_source and submit and mode == "fresh" and not _topic_has_quant_floor(selected):
                frontier_timeout = _publish_seed_timeout(child_timeout())
                seeded_frontier_corpus = (
                    ensure_corpus(selected, dry_run=synthesis_dry_run, timeout=frontier_timeout)
                    if ensure_corpus
                    else _ensure_topic_corpus(
                        selected,
                        dry_run=synthesis_dry_run,
                        timeout=frontier_timeout,
                        min_quant_claims=PREFLIGHT_MIN_QUANT_CLAIMS,
                    )
                )
                ledger["frontier_corpus_seed"] = {"topic": selected, **seeded_frontier_corpus}
            if (
                not revision_source
                and submit
                and mode == "fresh"
                and not _topic_has_quant_floor(selected)
            ):
                frontier_preflight = _quant_claim_preflight(seeded_frontier_corpus or {}, topic=selected)
                frontier_status = str((seeded_frontier_corpus or {}).get("status") or "no_ready_corpus_available")
                if not frontier_preflight["passed"] and frontier_status in {"corpus_ready", "corpus_seeded"}:
                    frontier_status = "preflight_thin_quant_corpus"
                attempt: dict[str, Any] = {
                    "topic": selected,
                    "out_dir": out_dir.name,
                    "synthesis_return_code": None,
                    "submit_status": frontier_status,
                    "failure_class": "B_corpus_fixable",
                    "submitted": 0,
                    "corpus": seeded_frontier_corpus or {},
                }
                if not frontier_preflight["passed"]:
                    attempt["preflight"] = frontier_preflight
                ledger["attempts"].append(attempt)
                _record_attempt_blocker(ledger_dir, date, ledger, attempt)
                ledger.update({
                    "status": "no_ready_corpus_available",
                    "attempted_topic": selected,
                    "attempted_run": out_dir.name,
                    "selected_without_quant_floor": selected,
                })
                attempted.add(selected)
                continue
            ledger.update({"topic": selected, "out_dir": out_dir.name, "attempted_topic": selected, "attempted_run": out_dir.name})
            if not run_synthesis:
                ledger["status"] = "dry_run_selected_topic"
                break
            revision_feedback = str(revision_source.get("feedback") or "") if revision_source else ""
            if revision_source and _revision_requests_domain_scope_reset(revision_feedback):
                gate_status = "terminal_domain_scope_mismatch"
                attempt = _gate_attempt(selected, out_dir, gate_status)
                ledger["attempts"].append(attempt)
                ledger["status"] = "revise_terminal_domain_scope_mismatch"
                _record_attempt_blocker(ledger_dir, date, ledger, attempt)
                _mark_revision_handled(ledger_dir, revision_source, status=gate_status)
                revise_window_excluded.add(_revision_key(revision_source))
                attempted.add(selected)
                remote_revision = None
                continue
            # A pending revise whose topic keeps failing the SAME deterministic gate
            # cannot be fixed by re-rendering — mark it terminal so it stops
            # monopolising revise slots instead of re-synthesising every cycle.
            if revision_source and selected in surface_repeat:
                attempt = _gate_attempt(selected, out_dir, "terminal_surface_repeat")
                ledger["attempts"].append(attempt)
                ledger["status"] = "revise_terminal_surface_repeat"
                _record_attempt_blocker(ledger_dir, date, ledger, attempt)
                _mark_revision_handled(ledger_dir, revision_source, status="terminal_surface_repeat")
                revise_window_excluded.add(_revision_key(revision_source))
                attempted.add(selected)
                remote_revision = None
                continue
            if revision_source and selected in _unrepairable_source_precision_topics(ledger_dir):
                gate_status = "terminal_source_precision_repair_incomplete"
                attempt = _gate_attempt(selected, out_dir, gate_status)
                ledger["attempts"].append(attempt)
                ledger["status"] = "revise_terminal_source_precision_repair_incomplete"
                _record_attempt_blocker(ledger_dir, date, ledger, attempt)
                _mark_revision_handled(ledger_dir, revision_source, status=gate_status)
                revise_window_excluded.add(_revision_key(revision_source))
                attempted.add(selected)
                remote_revision = None
                continue
            revision_source_run = runs_root / str(revision_source.get("source_run") or "") if revision_source else None
            existing_source_preflight = _existing_receipt_preflight(revision_source_run) if revision_source else None
            revision_source_repair = _revision_requests_source_precision(revision_feedback)
            source_manifest_availability = (
                _source_manifest_availability(selected, revision_source_run)
                if revision_source
                else None
            )
            if (
                source_manifest_availability
                and int(source_manifest_availability.get("n_missing_quant_claim_files") or 0) > 0
                and revision_source
            ):
                restore = _restore_source_manifest_quant_claims(selected, revision_source_run)
                source_manifest_availability = _source_manifest_availability(selected, revision_source_run)
                ledger["source_manifest_restore"] = {
                    **restore,
                    "availability_after": source_manifest_availability,
                }
            if (
                source_manifest_availability
                and not source_manifest_availability.get("passed")
                and not revision_source_repair
            ):
                gate_status = "terminal_revision_source_manifest_unavailable"
                attempt = _gate_attempt(
                    selected,
                    out_dir,
                    gate_status,
                    source_manifest_availability=source_manifest_availability,
                )
                ledger["attempts"].append(attempt)
                ledger["status"] = gate_status
                _record_attempt_blocker(ledger_dir, date, ledger, attempt)
                if revision_source:
                    _mark_revision_handled(ledger_dir, revision_source, status=gate_status)
                    revise_window_excluded.add(_revision_key(revision_source))
                    remote_revision = None
                attempted.add(selected)
                continue
            snapshot_evidence_locked = bool(
                source_manifest_availability
                and source_manifest_availability.get("passed")
                and source_manifest_availability.get("evidence_mode") == "snapshot"
                and not revision_source_repair
            )
            corpus_timeout = child_timeout() if revision_source else _publish_seed_timeout(child_timeout())
            corpus: dict[str, Any]
            if existing_source_preflight or snapshot_evidence_locked:
                corpus = {
                    "status": "corpus_ready",
                    "source": (
                        "existing_source_snapshot"
                        if snapshot_evidence_locked
                        else "existing_source_manifest"
                    ),
                    "source_run": revision_source_run.name if revision_source_run else "",
                    "n_quant_claims": max(
                        PREFLIGHT_MIN_QUANT_CLAIMS,
                        int(
                            (source_manifest_availability or {}).get("n_source_receipts")
                            or (existing_source_preflight or {}).get("n_receipts")
                            or 0
                        ),
                    ),
                }
            elif seeded_frontier_corpus is not None:
                corpus = seeded_frontier_corpus
            else:
                corpus = (ensure_corpus or _ensure_topic_corpus)(selected, dry_run=synthesis_dry_run, timeout=corpus_timeout)
            ledger["corpus"] = corpus
            if corpus.get("status") not in {"corpus_ready", "corpus_seeded"}:
                attempt = {
                    "topic": selected,
                    "out_dir": out_dir.name,
                    "synthesis_return_code": None,
                    "submit_status": corpus.get("status"),
                    "failure_class": "B_corpus_fixable",
                    "submitted": 0,
                    "corpus": corpus,
                }
                ledger["attempts"].append(attempt)
                ledger["status"] = "corpus_unavailable_no_submission"
                _record_attempt_blocker(ledger_dir, date, ledger, attempt)
                attempted.add(selected)
                continue
            source_precision_ok, source_precision_status, source_precision_misses = _quant_claim_source_precision(
                selected, floor=SOURCE_TOPIC_REPAIR_FLOOR,
            )
            seeded_new_corpus = (
                corpus.get("status") == "corpus_seeded"
                and int(corpus.get("n_quant_claims_before") or 0) == 0
            )
            if seeded_new_corpus and not revision_source and not source_precision_ok:
                retained = max(0, _quant_claim_count(selected) - len(source_precision_misses))
                if retained >= SOURCE_PRECISION_REPAIR_PUBLISH_MIN_QUANT:
                    source_repair = _repair_low_source_precision_corpus(
                        selected,
                        dry_run=synthesis_dry_run,
                        timeout=corpus_timeout,
                        force=True,
                        reseed=False,
                    )
                    ledger["source_precision_repair"] = {"topic": selected, **source_repair}
                    corpus = (ensure_corpus or _ensure_topic_corpus)(
                        selected,
                        dry_run=synthesis_dry_run,
                        timeout=corpus_timeout,
                    )
                    ledger["corpus"] = corpus
                    if _source_precision_repair_publishable(source_repair):
                        source_precision_ok = True
                        source_precision_misses = []
                        source_precision_repaired_ok.add(selected)
                    else:
                        attempt = _source_precision_attempt(
                            selected,
                            out_dir,
                            _SOURCE_PRECISION_STATUS,
                            corpus=corpus,
                            source_repair=source_repair,
                        )
                        ledger["attempts"].append(attempt)
                        ledger["status"] = "source_precision_repair_incomplete_no_submission"
                        _record_attempt_blocker(ledger_dir, date, ledger, attempt)
                        attempted.add(selected)
                        continue
                else:
                    attempt = _source_precision_attempt(selected, out_dir, source_precision_status, corpus=corpus)
                    ledger["attempts"].append(attempt)
                    ledger["status"] = "source_precision_repair_deferred_no_submission"
                    _record_attempt_blocker(ledger_dir, date, ledger, attempt)
                    attempted.add(selected)
                    continue
            source_precision_has_misses = (
                source_precision_ok
                and bool(source_precision_misses)
                and int(corpus.get("n_quant_claims") or 0) >= PREFLIGHT_MIN_QUANT_CLAIMS * 2
            )
            source_precision_needs_repair = (
                selected in _source_precision_repair_topics(ledger_dir)
                or revision_source_repair
                or source_precision_has_misses
                or (
                    not source_precision_ok
                    and int(corpus.get("n_quant_claims") or 0) >= PREFLIGHT_MIN_QUANT_CLAIMS
                )
            )
            if (
                revision_source
                and (existing_source_preflight or snapshot_evidence_locked)
                and not revision_source_repair
            ):
                source_precision_needs_repair = False
            source_precision_repair_cleared = False
            if selected not in source_precision_repaired_ok and source_precision_needs_repair:
                source_repair = _repair_low_source_precision_corpus(
                    selected,
                    dry_run=synthesis_dry_run,
                    timeout=corpus_timeout,
                    force=revision_source_repair or source_precision_has_misses,
                )
                ledger["source_precision_repair"] = {"topic": selected, **source_repair}
                corpus = (ensure_corpus or _ensure_topic_corpus)(
                    selected,
                    dry_run=synthesis_dry_run,
                    timeout=corpus_timeout,
                )
                ledger["corpus"] = corpus
                if source_repair.get("status") == "source_precision_repair_incomplete":
                    gate_status = (
                        "terminal_source_precision_repair_incomplete"
                        if revision_source
                        else _SOURCE_PRECISION_STATUS
                    )
                    attempt = _source_precision_attempt(
                        selected,
                        out_dir,
                        gate_status,
                        corpus=corpus,
                        source_repair=source_repair,
                    )
                    ledger["attempts"].append(attempt)
                    ledger["status"] = (
                        "revise_terminal_source_precision_repair_incomplete"
                        if revision_source
                        else "source_precision_repair_incomplete_no_submission"
                    )
                    _record_attempt_blocker(ledger_dir, date, ledger, attempt)
                    if revision_source:
                        _mark_revision_handled(ledger_dir, revision_source, status=gate_status)
                        revise_window_excluded.add(_revision_key(revision_source))
                        remote_revision = None
                    attempted.add(selected)
                    continue
                source_precision_repair_cleared = source_repair.get("status") in {
                    "source_precision_ready",
                    "source_precision_repaired",
                }
            quant_preflight = _quant_claim_preflight(
                corpus,
                topic=None if snapshot_evidence_locked else selected,
            )
            quant_corpus_repairs: list[dict[str, Any]] = []
            if not quant_preflight["passed"] and not synthesis_dry_run and not snapshot_evidence_locked:
                for round_idx in range(_receipt_preflight_repair_rounds()):
                    corpus_repair = _repair_topic_corpus(
                        selected,
                        dry_run=False,
                        timeout=corpus_timeout,
                        seed_limit=_auto_seed_limit() * (round_idx + 2),
                    )
                    quant_corpus_repairs.append(corpus_repair)
                    if corpus_repair.get("status") not in {"corpus_ready", "corpus_seeded", "corpus_repaired"}:
                        break
                    refreshed = (ensure_corpus or _ensure_topic_corpus)(
                        selected,
                        dry_run=synthesis_dry_run,
                        timeout=corpus_timeout,
                    )
                    if int(refreshed.get("n_quant_claims") or 0) >= int(corpus_repair.get("n_quant_claims") or 0):
                        corpus = refreshed
                    else:
                        corpus = corpus_repair
                    ledger["corpus"] = corpus
                    quant_preflight = _quant_claim_preflight(corpus, topic=selected)
                    if quant_preflight["passed"]:
                        break
            if not quant_preflight["passed"]:
                attempt = {
                    "topic": selected,
                    "out_dir": out_dir.name,
                    "synthesis_return_code": None,
                    "submit_status": "preflight_thin_quant_corpus",
                    "failure_class": "B_corpus_fixable",
                    "submitted": 0,
                    "preflight": quant_preflight,
                    "corpus": corpus,
                }
                if quant_corpus_repairs:
                    attempt["quant_corpus_repairs"] = quant_corpus_repairs
                ledger["attempts"].append(attempt)
                ledger["status"] = "preflight_skipped_no_submission"
                _record_attempt_blocker(ledger_dir, date, ledger, attempt)
                attempted.add(selected)
                continue
            preflight = _preflight(
                selected,
                runs_root,
                ledger_dir,
                current_quant_claims=int(corpus.get("n_quant_claims") or 0),
                ignore_recent_failures=bool(
                    revision_source
                    and (
                        existing_source_preflight
                        or snapshot_evidence_locked
                        or source_precision_repair_cleared
                    )
                ),
                source_run=(
                    revision_source_run
                    if revision_source and not revision_source_repair
                    else None
                ),
            )
            if not preflight["passed"]:
                terminal_missing_manifest = (
                    revision_source is not None
                    and "latest_run_missing_manifest" in preflight.get("reasons", [])
                )
                gate_status = (
                    "terminal_latest_run_missing_manifest"
                    if terminal_missing_manifest
                    else "terminal_preflight_insufficient_corpus"
                    if revision_source is not None
                    else "preflight_insufficient_corpus"
                )
                attempt = {
                    "topic": selected,
                    "out_dir": out_dir.name,
                    "synthesis_return_code": None,
                    "submit_status": gate_status,
                    "gate_status": gate_status,
                    "failure_class": _failure_class(gate_status),
                    "submitted": 0,
                    "preflight": preflight,
                }
                ledger["attempts"].append(attempt)
                ledger["status"] = (
                    "revise_terminal_latest_run_missing_manifest"
                    if terminal_missing_manifest
                    else "revise_terminal_preflight_insufficient_corpus"
                    if revision_source is not None
                    else "preflight_skipped_no_submission"
                )
                _record_attempt_blocker(ledger_dir, date, ledger, attempt)
                if revision_source is not None:
                    _mark_revision_handled(ledger_dir, revision_source, status=gate_status)
                    revise_window_excluded.add(_revision_key(revision_source))
                    remote_revision = None
                attempted.add(selected)
                continue
            terminal_strategy = _paper_strategy(corpus, preflight, revision_feedback)
            if terminal_strategy.get("action") == "skip_topic":
                attempt = _gate_attempt(
                    selected,
                    out_dir,
                    "strategy_evidence_insufficient",
                    paper_strategy=terminal_strategy,
                )
                ledger["attempts"].append(attempt)
                ledger["paper_strategy"] = terminal_strategy
                ledger["status"] = "strategy_skipped_no_submission"
                _record_attempt_blocker(ledger_dir, date, ledger, attempt)
                if revision_source:
                    _mark_revision_handled(
                        ledger_dir,
                        revision_source,
                        status="strategy_evidence_insufficient",
                    )
                    revise_window_excluded.add(_revision_key(revision_source))
                    remote_revision = None
                attempted.add(selected)
                continue
            if revision_source:
                ledger["revision_source"] = {
                    key: revision_source.get(key)
                    for key in ("artifactId", "submissionId", "source_run", "title")
                    if revision_source.get(key)
                }
            review_type_override: str | None = None
            last_attempt: dict[str, Any] | None = None
            revision_round_recorded = False
            for revise_attempt in range(1, max(1, max_revise_attempts) + 1):
                if cycle_budget_seconds > 0 and clock() - started_mono >= cycle_budget_seconds:
                    attempt = {
                        "topic": selected,
                        "out_dir": out_dir.name,
                        "revise_attempt": revise_attempt,
                        "synthesis_return_code": None,
                        "submit_status": "cycle_budget_exhausted",
                        "failure_class": "D_no_action",
                        "submitted": 0,
                        "cycle_elapsed_seconds": int(clock() - started_mono),
                        "cycle_budget_seconds": cycle_budget_seconds,
                    }
                    ledger["attempts"].append(attempt)
                    ledger["status"] = "cycle_budget_exhausted"
                    break
                source_base_dir = runs_root / str(revision_source.get("source_run") or "") if revision_source else None
                revision_base_dir = source_base_dir
                if revise_attempt > 1:
                    previous_out_dir = out_dir
                    if not revision_source or _existing_receipt_preflight(previous_out_dir):
                        revision_base_dir = previous_out_dir
                    stamp = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
                    out_dir = runs_root / f"synthesis-{selected}-v06-DAILY-{stamp}-R{revise_attempt}"
                    ledger.update({"out_dir": out_dir.name, "attempted_run": out_dir.name})
                # Only the explicit availability verdict can reuse a package;
                # submit selection still re-runs every normal quality gate.
                repair_reason = (
                    "submission_authority_retry"
                    if revision_source and revision_source.get("retry_unchanged")
                    else ""
                )
                if revise_attempt > 1 and last_attempt and revision_base_dir:
                    repair_reason = _repair_reason_for_retry(revision_base_dir, last_attempt)
                retry_budget = child_timeout()
                if (
                    revision_source
                    and revise_attempt > 1
                    and revision_feedback
                    and not repair_reason
                    and _insufficient_revise_retry_budget(retry_budget, cycle_budget_seconds)
                ):
                    gate_status = "terminal_revise_retry_budget_insufficient"
                    attempt = _gate_attempt(
                        selected,
                        out_dir,
                        gate_status,
                        revise_attempt=revise_attempt,
                        remaining_budget_seconds=retry_budget,
                    )
                    ledger["attempts"].append(attempt)
                    ledger["status"] = gate_status
                    _record_attempt_blocker(ledger_dir, date, ledger, attempt)
                    _mark_revision_handled(ledger_dir, revision_source, status=gate_status)
                    revision_round_recorded = True
                    revise_window_excluded.add(_revision_key(revision_source))
                    remote_revision = None
                    attempted.add(selected)
                    break
                # Researka content revises carry reviewer feedback that must reach the
                # feedback-aware writer (_run_synthesis injects RESEARKA_REVISION_FEEDBACK);
                # only mechanical internal repairs (a gate-failure repair_reason with no
                # external feedback) reuse the deterministic finalizer.
                repair_attempted = bool(revision_base_dir and repair_reason and not revision_feedback)
                existing_repair = False
                repair_error = ""
                if repair_attempted and revision_base_dir:
                    existing_repair, repair_error = _repair_existing_run(
                        revision_base_dir,
                        out_dir,
                        revision_source=revision_source,
                        repair_reason=repair_reason or None,
                    )
                synthesis_kwargs: dict[str, Any] = {
                    "dry_run": synthesis_dry_run,
                    "revision_feedback": revision_feedback or None,
                }
                if review_type_override:
                    synthesis_kwargs["review_type_override"] = review_type_override
                revision_evidence_source = (
                    revision_base_dir
                    if revision_source
                    and revision_base_dir
                    and (not revision_source_repair or revision_base_dir != source_base_dir)
                    else None
                )
                if revision_evidence_source:
                    synthesis_kwargs["revision_source_run"] = revision_evidence_source
                revision_snapshot_availability = (
                    _source_manifest_availability(selected, revision_evidence_source)
                    if revision_evidence_source
                    else None
                )
                revision_snapshot_locked = bool(
                    revision_snapshot_availability
                    and revision_snapshot_availability.get("passed")
                    and revision_snapshot_availability.get("evidence_mode") == "snapshot"
                )
                existing_receipt_preflight = (
                    _existing_receipt_preflight(revision_base_dir)
                    if revision_evidence_source
                    else None
                )
                receipt_preflight = (
                    existing_receipt_preflight
                    if existing_receipt_preflight is not None
                    and not existing_receipt_preflight.get("passed")
                    else
                    {
                        "passed": True,
                        "status": (
                            "receipt_preflight_existing_repair"
                            if existing_repair
                            else "receipt_preflight_snapshot_locked"
                        ),
                    }
                    if existing_repair or revision_snapshot_locked
                    else existing_receipt_preflight
                )
                receipt_timeout = child_timeout() if revision_source else _publish_seed_timeout(child_timeout())
                if receipt_preflight is None:
                    receipt_repair = bool(revision_source) or receipt_preflight_repairs_used < _corpus_repair_limit()
                    receipt_preflight = _receipt_preflight(
                        selected,
                        out_dir,
                        timeout=receipt_timeout,
                        repair=receipt_repair,
                        dry_run=synthesis_dry_run,
                    )
                    if not revision_source and receipt_preflight.get("repairs"):
                        receipt_preflight_repairs_used += 1
                if not receipt_preflight.get("passed"):
                    gate_status = str(receipt_preflight.get("status") or "receipt_preflight_insufficient")
                    if revision_source and _terminal_revision_receipt_preflight(receipt_preflight):
                        gate_status = "terminal_receipt_preflight_insufficient"
                    attempt = _gate_attempt(
                        selected,
                        out_dir,
                        gate_status,
                        revise_attempt=revise_attempt,
                        receipt_preflight=receipt_preflight,
                    )
                    ledger["attempts"].append(attempt)
                    ledger["status"] = (
                        "revise_terminal_receipt_preflight_insufficient"
                        if gate_status == "terminal_receipt_preflight_insufficient"
                        else
                        "revise_receipt_preflight_skipped_no_submission"
                        if revision_source
                        else "receipt_preflight_skipped_no_submission"
                    )
                    _record_attempt_blocker(ledger_dir, date, ledger, attempt)
                    if revision_source:
                        _mark_revision_handled(ledger_dir, revision_source, status=gate_status)
                        revise_window_excluded.add(_revision_key(revision_source))
                        remote_revision = None
                    last_attempt = attempt
                    attempted.add(selected)
                    break
                strategy_preflight = {
                    **preflight,
                    **{
                        key: receipt_preflight[key]
                        for key in ("n_receipts", "n_primary_tier", "n_direct_receipts")
                        if key in receipt_preflight
                    },
                }
                strategy = _paper_strategy(corpus, strategy_preflight, revision_feedback)
                ledger["paper_strategy"] = strategy
                if strategy.get("action") != "write":
                    gate_status = (
                        "needs_corpus_expansion"
                        if strategy.get("action") == "needs_corpus"
                        else "strategy_evidence_insufficient"
                    )
                    attempt = _gate_attempt(
                        selected,
                        out_dir,
                        gate_status,
                        revise_attempt=revise_attempt,
                        paper_strategy=strategy,
                        receipt_preflight=receipt_preflight,
                    )
                    ledger["attempts"].append(attempt)
                    ledger["status"] = (
                        "needs_corpus_expansion_no_submission"
                        if gate_status == "needs_corpus_expansion"
                        else "strategy_skipped_no_submission"
                    )
                    _record_attempt_blocker(ledger_dir, date, ledger, attempt)
                    if revision_source:
                        _mark_revision_handled(ledger_dir, revision_source, status=gate_status)
                        revise_window_excluded.add(_revision_key(revision_source))
                        remote_revision = None
                    last_attempt = attempt
                    attempted.add(selected)
                    break
                synthesis_kwargs["timeout"] = child_timeout()
                return_code = 0 if existing_repair else _run_synthesis(selected, out_dir, **synthesis_kwargs)
                if revision_source and out_dir.exists():
                    _write_json(out_dir / "researka_revision_request.json", revision_source)
                # Coverage gate: a content revise must materially address every
                # enumerated reviewer ask before it may be submitted.
                unmet = _unmet_revision_asks(out_dir, revision_feedback) if (return_code == 0 and revision_feedback) else []
                if return_code == 0 and revision_feedback:
                    revision_asks = _revision_asks(
                        revision_feedback, _required_revision_items(revision_source or {}),
                    )
                    _write_json(out_dir / REVISION_COVERAGE_GATE, {
                        "passed": not unmet,
                        "ask_count": len(revision_asks),
                        "ask_fingerprint": ask_fingerprint(revision_asks),
                        "unmet_asks": unmet,
                    })
                # Retraction gate: never submit a paper that cites retracted science.
                retraction_result = _retracted_cited_sources(out_dir) if return_code == 0 else []
                retraction_unverified = retraction_result is None
                retracted = retraction_result or []
                # Claim-support gate: never submit an abstract whose claims the
                # paper's own evidence does not support / overstates.
                overclaims = _abstract_overclaims(out_dir) if return_code == 0 else []
                numeric_issues = _numeric_effect_direction_issues(out_dir) if return_code == 0 else []
                public_surface = (
                    _public_research_surface_preflight(out_dir)
                    if return_code == 0 and submit and not revision_source and submit_cycle is None
                    else {"passed": True}
                )
                abstract_repaired = False
                if overclaims and _repair_abstract_overclaim_phrasing(out_dir, overclaims):
                    abstract_repaired = True
                    overclaims = _abstract_overclaims(out_dir)
                advisory_overclaims = list(overclaims)
                abstract_overclaim_advisory = bool(overclaims and _final_status_submission_ready(out_dir))
                if abstract_overclaim_advisory:
                    overclaims = []
                bridge: dict[str, Any] = {}
                if (
                    return_code == 0
                    and not unmet
                    and not retraction_unverified
                    and not retracted
                    and not numeric_issues
                    and not overclaims
                    and public_surface.get("passed")
                ):
                    # Submission stays single-threaded across lanes: the fresh and
                    # revise lanes run concurrently but share one blocking submit
                    # lock so they never race the fingerprint-dedupe / double-submit.
                    with _lock(ledger_dir, ".submit.lock", block=True):
                        if submit_cycle is None:
                            bridge = _submit_current_candidate(
                                runs_root=runs_root,
                                date=date,
                                submit=submit,
                                remote_seen=remote_seen,
                                candidate_run=out_dir,
                            )
                        else:
                            bridge = submit_cycle(
                                runs_root=runs_root,
                                date=date,
                                submit=submit,
                                remote_loader=(lambda: (remote_seen, None)) if submit else None,
                            )
                gate_status = (
                    "synthesis_timeout" if return_code == SYNTHESIS_TIMEOUT_RETURN_CODE
                    else "needs_corpus_expansion" if return_code == NEEDS_CORPUS_RETURN_CODE
                    else "synthesis_failed" if return_code != 0
                    else "retraction_check_unavailable" if retraction_unverified
                    else "retracted_source_cited" if retracted
                    else "numeric_effect_mismatch" if numeric_issues
                    else "abstract_overclaim" if overclaims
                    else str(public_surface.get("status") or "public_research_surface_insufficient")
                    if not public_surface.get("passed")
                    else "revision_coverage_unmet" if unmet
                    else _current_gate_status(bridge, out_dir.name)
                )
                bridge_status = str(bridge.get("status") or "")
                if gate_status == "eligible" and bridge_status not in {"", "submitted_to_researka"}:
                    gate_status = bridge_status
                candidate_obj = bridge.get("candidate")
                candidate: dict[str, Any] = candidate_obj if isinstance(candidate_obj, dict) else {}
                submitted_any = int(bridge.get("submitted") or 0)
                submitted_run = str(candidate.get("run") or "")
                submitted_topic = str(candidate.get("topic") or "")
                submitted_current = int(bool(submitted_any) and (not submitted_run or submitted_run == out_dir.name))
                submit_status = bridge.get("status")
                if submitted_any and not submitted_current:
                    submit_status = "current_run_not_submitted"
                attempt = {
                    "topic": selected,
                    "out_dir": out_dir.name,
                    "revise_attempt": revise_attempt,
                    "revision_feedback_applied": bool(revision_feedback),
                    "synthesis_return_code": return_code,
                    "submit_status": submit_status,
                    "bridge_status": bridge_status,
                    "gate_status": gate_status,
                    "failure_class": _failure_class(gate_status),
                    "submitted": submitted_current,
                    "existing_work_reused": existing_repair,
                    "receipt_preflight": receipt_preflight,
                }
                if quant_corpus_repairs:
                    attempt["quant_corpus_repairs"] = quant_corpus_repairs
                if unmet:
                    attempt["unmet_revision_asks"] = unmet
                    revision_feedback = _escalate_feedback(revision_feedback, unmet)
                if retracted:
                    attempt["retracted_cited_sources"] = retracted
                if retraction_unverified:
                    attempt["retraction_check_unavailable"] = True
                if numeric_issues:
                    attempt["numeric_effect_direction_issues"] = numeric_issues
                if return_code == 0 and submit and not revision_source and submit_cycle is None:
                    attempt["public_research_surface_preflight"] = public_surface
                if overclaims:
                    attempt["abstract_overclaims"] = overclaims
                if abstract_repaired:
                    attempt["abstract_overclaim_repaired"] = True
                if abstract_overclaim_advisory:
                    attempt["abstract_overclaim_advisory"] = True
                    attempt["abstract_overclaim_advisory_claims"] = advisory_overclaims
                source_precision_retry = False
                prospective_same_gate_failures = (
                    0 if (revision_source and revision_feedback)
                    else _same_gate_failure_count([*ledger["attempts"], attempt], selected, gate_status)
                )
                if gate_status.split(":", 1)[0] == _SOURCE_PRECISION_STATUS:
                    if prospective_same_gate_failures >= 2:
                        attempt["source_precision_repair_skipped"] = "repeat_gate"
                    else:
                        source_repair = _repair_low_source_precision_corpus(selected, dry_run=synthesis_dry_run, timeout=timeout)
                        attempt["source_precision_repair"] = source_repair
                        source_precision_retry = _source_precision_repair_publishable(source_repair)
                if repair_attempted:
                    attempt["repair_attempted"] = True
                if repair_error:
                    attempt["repair_error"] = repair_error
                if repair_reason:
                    attempt["repair_reason"] = repair_reason
                if review_type_override:
                    attempt["review_type_override"] = review_type_override
                if submitted_any:
                    attempt.update({"submitted_topic": submitted_topic or selected, "submitted_run": submitted_run or out_dir.name})
                    submission_markers = sorted(_ledger_submission_markers(bridge))
                    if submission_markers:
                        attempt["submission_markers"] = submission_markers
                    ledger.update({"submitted_topic": submitted_topic or selected, "submitted_run": submitted_run or out_dir.name})
                ledger["attempts"].append(attempt)
                same_gate_failures = prospective_same_gate_failures
                if same_gate_failures >= 2:
                    attempt["same_gate_repeat_count"] = same_gate_failures
                    attempt["same_gate_repeat_stop"] = True
                same_topic_retries = (
                    0 if revision_source else _same_topic_retry_count(ledger["attempts"], selected)
                )
                if same_topic_retries >= 2:
                    attempt["same_topic_retry_count"] = same_topic_retries
                    attempt["same_topic_retry_stop"] = True
                last_attempt = attempt
                ledger["synthesis_return_code"] = return_code
                ledger["submit_bridge"] = bridge
                ledger["submitted"] = submitted_any
                if revision_source and not submitted_current:
                    revise_window_excluded.add(_revision_key(revision_source))
                if isinstance(bridge.get("revision_feedback"), str):
                    revision_feedback = str(bridge["revision_feedback"])
                    attempt["revision_feedback_received"] = bool(revision_feedback)
                if gate_status and gate_status != "eligible":
                    _record_attempt_blocker(ledger_dir, date, ledger, attempt)
                if revision_source and gate_status.split(":", 1)[0] in _TERMINAL_REVISION_STATUSES:
                    _mark_revision_handled(ledger_dir, revision_source, status=gate_status)
                if return_code == SYNTHESIS_TIMEOUT_RETURN_CODE:
                    if revision_source:
                        timeout_status = "synthesis_timeout"
                        attempt["revision_timeout_status"] = timeout_status
                        _mark_revision_handled(ledger_dir, revision_source, status=timeout_status)
                    ledger["status"] = "synthesis_timeout_no_submission"
                    ledger["no_submission_reason"] = gate_status
                elif return_code == NEEDS_CORPUS_RETURN_CODE:
                    ledger["status"] = "needs_corpus_expansion_no_submission"
                    ledger["no_submission_reason"] = gate_status
                elif return_code != 0:
                    ledger["status"] = "synthesis_failed"
                elif bridge.get("status") == "submitted_to_researka":
                    ledger["status"] = "submitted_to_researka"
                    ledger.pop("no_submission_reason", None)
                    if (
                        submit
                        and mode != "fresh"  # fresh lane ships and exits; the revise lane handles decisions
                        and not revision_source
                        and bool(submitted_current)
                        and revise_attempt < max(1, max_revise_attempts)
                        and (revision_loader is not None or submit_cycle is None)
                    ):
                        followup, poll = _poll_remote_revision(
                            runs_root,
                            ledger_dir,
                            loader=revision_loader,
                            published_loader=lambda: (remote_seen, None),
                            seconds=decision_poll_seconds,
                            interval_seconds=decision_poll_interval_seconds,
                            sleeper=decision_sleep,
                        )
                        ledger["decision_poll"] = poll
                        if followup:
                            revision_source = followup
                            revision_feedback = str(followup.get("feedback") or "")
                            ledger["status"] = "submission_revise_requested"
                            attempt["remote_revision_requested"] = True
                            attempt["revision_feedback_received"] = bool(revision_feedback)
                            continue
                    break
                elif bridge.get("status") == "submission_failed":
                    ledger["status"] = "submission_failed"
                elif retraction_unverified:
                    ledger.update({"status": "retraction_check_unavailable", "no_submission_reason": gate_status})
                else:
                    ledger["status"] = "synthesis_completed_no_submission"
                    if gate_status and gate_status != "eligible":
                        ledger["no_submission_reason"] = gate_status
                if retraction_unverified:
                    break
                if source_precision_retry and revise_attempt < max(1, max_revise_attempts):
                    continue
                if (
                    same_topic_retries >= 2
                    or same_gate_failures >= 2
                    or revise_attempt >= max(1, max_revise_attempts)
                    or not _should_retry_same_topic(attempt, auto_selected=topic is None and not revision_source)
                ):
                    break
            if (
                revision_source
                and last_attempt
                and last_attempt.get("gate_status") == "revision_coverage_unmet"
                and not int(last_attempt.get("submitted") or 0)
                and not revision_round_recorded
            ):
                # Internal rewrites are one revision round. Persist one result
                # for the completed timer window, including budget-expiry exits.
                _mark_revision_handled(
                    ledger_dir, revision_source, status="revision_coverage_unmet",
                )
            if ledger["status"] in {"cycle_budget_exhausted", "retraction_check_unavailable"}:
                break
            if ledger["status"] == "submitted_to_researka":
                submitted_total += int(ledger.get("submitted") or 0)
                if revision_source:
                    # Revise shipped — record it, then keep the cycle going so it
                    # still produces a fresh paper. A backlog of revises otherwise
                    # monopolises the one-submit-per-cycle budget and starves new
                    # output (the May-30 throughput regression). Universal.
                    markers = (
                        last_attempt.get("submission_markers", [])
                        if last_attempt
                        else []
                    )
                    _mark_revision_handled(
                        ledger_dir,
                        _revision_submission_row(revision_source, markers),
                        status="submitted_to_researka",
                    )
                    remote_revision = None
                    attempted.add(selected)
                    continue
                break
            attempted.add(selected)
        if submitted_total:
            ledger["submitted"] = submitted_total
            if ledger["status"] not in {"submitted_to_researka", "submission_revise_requested"}:
                ledger["status"] = "submitted_to_researka"
        _record_daily_throughput(ledger_dir, ledger)
        _write_json(ledger_path, ledger)
        return ledger


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date")
    parser.add_argument("--runs-root", type=Path, default=RUNS)
    parser.add_argument("--topic")
    parser.add_argument("--run-synthesis", action="store_true")
    parser.add_argument("--synthesis-dry-run", action="store_true")
    parser.add_argument("--submit", action="store_true")
    parser.add_argument("--mode", choices=["fresh", "revise", "mixed"], default=None,
                        help="lane: fresh=new papers only, revise=process one pending revise only, mixed=interleave (default)")
    parser.add_argument("--timeout-sec", type=int, default=0)
    parser.add_argument("--max-attempts", type=int, default=0,
                        help="0 means keep trying topics until budget/no candidate")
    parser.add_argument("--max-revise-attempts", type=int, default=3)
    parser.add_argument("--decision-poll-sec", type=int, default=DECISION_POLL_SECONDS)
    parser.add_argument("--decision-poll-interval-sec", type=int, default=DECISION_POLL_INTERVAL_SECONDS)
    parser.add_argument("--cycle-budget-sec", type=int, default=CYCLE_BUDGET_SECONDS)
    parser.add_argument("--reconcile-publications", action="store_true",
                        help="Reconcile submitted ledgers against Researka public publications and exit")
    parser.add_argument("--prepare-only", action="store_true",
                        help="repair and receipt-validate a reserve of fresh candidates, then exit")
    parser.add_argument("--prepare-target", type=int, default=3)
    parser.add_argument("--prepare-max-repairs", type=int, default=3)
    args = parser.parse_args(argv)
    if args.reconcile_publications:
        result = reconcile_publication_ledgers(runs_root=args.runs_root, date=args.date, mode=args.mode)
        print(
            f"[daily-v3-cycle] status={result['status']} checked={result['checked']} "
            f"updated={result['updated']} ledgers={','.join(result.get('updated_ledgers', [])) or '-'}"
        )
        return 0 if result["status"] != "remote_dedupe_failed" else 2
    if args.prepare_only:
        result = prepare_candidate_buffer(
            runs_root=args.runs_root,
            target_ready=args.prepare_target,
            max_repairs=args.prepare_max_repairs,
            max_attempts=args.max_attempts or None,
            timeout=args.timeout_sec or None,
            dry_run=args.synthesis_dry_run,
        )
        print(
            f"[daily-v3-prepare] status={result['status']} ready={result['ready_count']}/"
            f"{result['target_ready']} attempted={result['attempted_count']}"
        )
        attempted_count = int(result.get("attempted_count") or 0)
        ready_topics = {str(row.get("topic") or "") for row in result.get("ready", [])}
        attempts = result.get("attempts")
        for attempt in (attempts[-attempted_count:] if isinstance(attempts, list) and attempted_count else []):
            topic = str(attempt.get("topic") or "unknown")
            if topic in ready_topics:
                continue
            preflight = attempt.get("receipt_preflight")
            reasons = preflight.get("reasons") if isinstance(preflight, dict) else None
            reason = " | ".join(str(item) for item in reasons) if isinstance(reasons, list) else ""
            print(f"[daily-v3-prepare] rejected_topic={topic} reason={reason or 'readiness_checks_failed'}")
        if result["status"] == "remote_dedupe_failed":
            return 2
        return 0 if result["ready_count"] >= result["target_ready"] else 3
    ledger = run_cycle(
        runs_root=args.runs_root,
        date=args.date or _default_cycle_date(),
        run_synthesis=args.run_synthesis,
        synthesis_dry_run=args.synthesis_dry_run,
        submit=args.submit,
        mode=args.mode or "mixed",
        topic=args.topic,
        timeout=args.timeout_sec or None,
        max_attempts=args.max_attempts,
        max_revise_attempts=args.max_revise_attempts,
        decision_poll_seconds=args.decision_poll_sec,
        decision_poll_interval_seconds=args.decision_poll_interval_sec,
        cycle_budget_seconds=args.cycle_budget_sec,
    )
    print(
        f"[daily-v3-cycle] status={ledger['status']} attempted_topic={ledger.get('attempted_topic', ledger.get('topic', '-'))} "
        f"submitted_topic={ledger.get('submitted_topic', '-')} "
        f"submitted={ledger['submitted']} published={ledger['published']}"
    )
    failures = {"submission_failed", "synthesis_failed", "remote_dedupe_failed", "submit_not_configured", "topic_not_available"}
    if ledger["status"] in failures:
        return 2
    no_output = args.submit and not int(ledger.get("submitted") or 0)
    if no_output and not (args.mode == "revise" and ledger["status"] == "no_revise_pending"):
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
