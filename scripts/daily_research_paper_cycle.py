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
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from collections.abc import Callable, Collection, Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import daily_research_paper_submit as submit_bridge

ROOT = Path(__file__).resolve().parent.parent
# Enable in-process `from scripts.X import Y` when systemd launches us as
# `python scripts/daily_research_paper_cycle.py` (script-style invocation
# only puts scripts/ on sys.path, not the repo root). Mirrors
# scripts/run_v06_synthesis.py:46. Without this, _repair_existing_run hits
# ModuleNotFoundError for scripts.review_noise_control and falls back to a
# full rewrite, burning the 2-hour cycle budget.
sys.path.insert(0, str(ROOT))
from source_topic_specificity import generated_pack_publishable, is_source_topic_specific, source_gate_aliases, topic_aliases  # noqa: E402
from agent.final_gate import DEFAULT_THRESHOLDS  # noqa: E402

RUNS = ROOT / "runs"
TOPIC_PACKS = ROOT / "topic_packs"
TOPIC_PACKS_DB = ROOT / "topic_packs_db"
CORPORA = ROOT / "docs" / "quality-reference"
LEDGER_DIR = "_daily_research_paper_cycle_ledger"
BLOCKER_HISTOGRAM = "_blocker_histogram.json"
HANDLED_REVISIONS = "_handled_revision_requests.json"
REVISION_COVERAGE_GATE = "revision_coverage_gate.json"
DAILY_THROUGHPUT_SUMMARY = "_daily_throughput_summary.json"
DECISIONS_BY_DAY = "_decisions_by_day.json"
REVISE_REASONS = "_revise_reasons.json"
DAY_KEY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# A Researka revise may be re-processed up to this many rounds per artifact
# before it is treated as permanently handled. Single-round handling left
# papers stuck after one revise; the cap lets feedback-aware re-renders iterate
# while bounding resubmissions to the live platform.
MAX_REVISE_ROUNDS = 3
PREFLIGHT_MIN_RECEIPTS = DEFAULT_THRESHOLDS.min_receipts
PREFLIGHT_MIN_QUANT_CLAIMS = 10
PREFLIGHT_MIN_TENSIONS = 3
PREFLIGHT_MIN_PRIMARY_TIER = 1
PREFLIGHT_MAX_RECEIPTS = 500
PREFLIGHT_MAX_TENSIONS = 50_000
PREFLIGHT_MAX_OUTCOMES = 12
RECENT_FAILURE_COOLDOWN_HOURS = 24
SURFACE_REPEAT_THRESHOLD = 2
WRITER_GATE_REPEAT_THRESHOLD = 2
HISTOGRAM_ISSUE_THRESHOLD = 5
AUTO_SEED_LIMIT = 120
SEED_TOPIC_TIMEOUT_SECONDS = 600
PUBLISH_SEED_TIMEOUT_SECONDS = 120
CORPUS_REPAIR_LIMIT = 1
RECEIPT_PREFLIGHT_REPAIR_ROUNDS = 2
SOURCE_TOPIC_REPAIR_FLOOR = submit_bridge.SOURCE_TOPIC_PRECISION_FLOOR
REVISION_SOURCE_BUNDLE_TOPIC_FLOOR = 0.80
DECISION_POLL_SECONDS = 900
DECISION_POLL_INTERVAL_SECONDS = 30
CYCLE_BUDGET_SECONDS = 6300
MIN_REVISE_RETRY_BUDGET_SECONDS = 1200
SYNTHESIS_TIMEOUT_RETURN_CODE = 124
PUBLISHED_TOPIC_COOLDOWN_DAYS = 21
FRAME_MIN_FULL_SCORE = 0.65
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
    "terminal_revise_retry_budget_insufficient",
})
_RETRYABLE_REVISION_STATUSES = frozenset({
    "revision_coverage_unmet",
    "synthesis_timeout",
    # Back-compat for rows written before synthesis timeouts became retryable.
    "terminal_synthesis_timeout",
})
DEFAULT_RETRYABLE_REVISION_STATUS_COOLDOWN_SECONDS = 3600
RETRYABLE_REVISION_STATUS_COOLDOWN_SECONDS = int(os.environ.get(
    "RESEARCH_AGENT_RETRYABLE_REVISION_STATUS_COOLDOWN_SECONDS",
    str(DEFAULT_RETRYABLE_REVISION_STATUS_COOLDOWN_SECONDS),
))
SUBMISSION_DECISION_LOOKBACK = int(os.environ.get("RESEARCH_AGENT_SUBMISSION_DECISION_LOOKBACK", "20"))
SUBMISSION_DECISION_TIMEOUT_SECONDS = int(os.environ.get("RESEARCH_AGENT_SUBMISSION_DECISION_TIMEOUT_SECONDS", "8"))

RemoteLoader = Callable[[], tuple[set[str], str | None]]
SubmitCycle = Callable[..., dict[str, Any]]
CorpusBuilder = Callable[..., dict[str, Any]]
RevisionLoader = Callable[[], tuple[list[dict[str, Any]], str | None]]
PublishedLoader = Callable[[], tuple[set[str], str | None]]
Sleeper = Callable[[float], None]


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _cycle_ledger_path(ledger_dir: Path, date: str, mode: str) -> Path:
    suffix = "" if mode == "mixed" else f"-{mode}"
    return ledger_dir / f"{date}{suffix}.json"


def _record_daily_throughput(ledger_dir: Path, ledger: dict[str, Any]) -> None:
    date = str(ledger.get("date") or "")
    started_at = str(ledger.get("started_at") or "")
    if not DAY_KEY_RE.fullmatch(date) or not started_at:
        return
    path = ledger_dir / DAILY_THROUGHPUT_SUMMARY
    data = _read_json(path)
    days = data.get("days")
    if not isinstance(days, dict):
        days = {}
    day = days.setdefault(date, {})
    runs = day.setdefault("runs", [])
    if not isinstance(runs, list):
        runs = []
    run_id = f"{ledger.get('mode') or 'mixed'}:{started_at}"
    run_row = {
        "run_id": run_id,
        "mode": ledger.get("mode") or "mixed",
        "status": ledger.get("status") or "unknown",
        "submitted": int(ledger.get("submitted") or 0),
        "published": int(ledger.get("published") or 0),
        "topic": ledger.get("submitted_topic") or ledger.get("topic") or ledger.get("attempted_topic"),
        "started_at": started_at,
    }
    existing = next((run for run in runs if isinstance(run, dict) and run.get("run_id") == run_id), None)
    if existing is not None:
        existing.update(run_row)
    else:
        runs.append(run_row)
    day["runs"] = runs
    day["submitted"] = sum(int(run.get("submitted") or 0) for run in runs if isinstance(run, dict))
    day["published"] = sum(int(run.get("published") or 0) for run in runs if isinstance(run, dict))
    day["cycles"] = len([run for run in runs if isinstance(run, dict)])
    latest = max((run for run in runs if isinstance(run, dict)), key=lambda run: str(run.get("started_at") or ""), default={})
    day["latest_status"] = latest.get("status") or "unknown"
    day["updated_at"] = dt.datetime.now(dt.UTC).isoformat()
    data["days"] = days
    _write_json(path, data)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _ledger_paths_for_reconciliation(ledger_dir: Path, date: str | None, mode: str | None) -> list[Path]:
    if date and mode:
        return [_cycle_ledger_path(ledger_dir, date, mode)]
    if date:
        return [_cycle_ledger_path(ledger_dir, date, lane) for lane in ("mixed", "fresh", "revise")]
    return sorted(path for path in ledger_dir.glob("*.json") if not path.name.startswith("_"))


def _submit_ledger_paths_for_reconciliation(runs_root: Path, date: str | None) -> list[Path]:
    ledger_dir = runs_root / submit_bridge.LEDGER_DIR
    if date:
        return [ledger_dir / f"{date}.json"]
    return sorted(path for path in ledger_dir.glob("*.json") if not path.name.startswith("_"))


def _ledger_run_names(ledger: dict[str, Any], *, submitted_only: bool = True) -> list[str]:
    names: list[str] = []
    for key in ("submitted_run", "attempted_run", "out_dir"):
        value = ledger.get(key)
        if isinstance(value, str) and value:
            names.append(value)
    candidate = ledger.get("candidate")
    if isinstance(candidate, dict):
        value = candidate.get("run")
        if isinstance(value, str) and value:
            names.append(value)
    attempts = ledger.get("attempts")
    for attempt in attempts if isinstance(attempts, list) else []:
        if not isinstance(attempt, dict):
            continue
        if submitted_only and not int(attempt.get("submitted") or 0):
            continue
        for key in ("submitted_run", "out_dir"):
            value = attempt.get(key)
            if isinstance(value, str) and value:
                names.append(value)
    return list(dict.fromkeys(names))


def _publication_markers_for_run(runs_root: Path, run_name: str) -> set[str]:
    paper = runs_root / run_name / "full_paper.md"
    if not paper.exists():
        return set()
    markers = {submit_bridge._sha256(paper)}
    title = submit_bridge._paper_title(paper)
    if title:
        markers.add(submit_bridge._title_marker(title))
    return markers


def _ledger_submission_markers(ledger: dict[str, Any]) -> set[str]:
    markers: set[str] = set()
    response = ledger.get("submission")
    response = response.get("response") if isinstance(response, dict) else {}
    if isinstance(response, dict):
        markers.update(
            submit_bridge._submission_marker(value)
            for value in submit_bridge._submission_ids_from_response(response)
        )
    attempts = ledger.get("attempts")
    for attempt in attempts if isinstance(attempts, list) else []:
        if not isinstance(attempt, dict):
            continue
        values = attempt.get("submission_markers")
        if isinstance(values, list):
            markers.update(
                value for value in values
                if isinstance(value, str) and value.startswith("submission:")
            )
    return markers


def _submit_bridge_submission_markers_by_run(runs_root: Path, run_names: set[str]) -> dict[str, set[str]]:
    if not run_names:
        return {}
    markers_by_run: dict[str, set[str]] = {}
    ledger_dir = runs_root / submit_bridge.LEDGER_DIR
    for path in ledger_dir.glob("*.json"):
        if path.name.startswith("_"):
            continue
        ledger = _read_json(path)
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


def _reconcile_published_ledger(ledger: dict[str, Any], runs_root: Path, remote_seen: set[str]) -> bool:
    if int(ledger.get("published") or 0):
        changed = False
        if str(ledger.get("status") or "") != "published":
            ledger["status"] = "published"
            changed = True
        before = len(ledger)
        ledger.pop("no_submission_reason", None)
        return changed or len(ledger) != before
    matches: set[str] = set()
    matched_runs: set[str] = set()
    submitted_runs = set(_ledger_run_names(ledger))
    if int(ledger.get("submitted") or 0):
        exact_markers = _ledger_submission_markers(ledger) or _submit_bridge_submission_markers_for_runs(runs_root, submitted_runs)
        if exact_markers:
            matches.update(exact_markers & remote_seen)
            if not matches:
                return False
        if not matches:
            for run_name in submitted_runs:
                run_matches = _publication_markers_for_run(runs_root, run_name) & remote_seen
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
            return False
    if not matches:
        return False
    if not submitted_runs:
        submitted_runs = matched_runs
    ledger["submitted"] = 1
    ledger["published"] = 1
    ledger["status"] = "published"
    ledger.pop("no_submission_reason", None)
    ledger["publication_reconciliation"] = {
        "source": "remote_publications",
        "matched": sorted(matches)[:5],
        "reconciled_at": dt.datetime.now(dt.UTC).isoformat(),
    }
    attempts = ledger.get("attempts")
    for attempt in attempts if isinstance(attempts, list) else []:
        if not isinstance(attempt, dict):
            continue
        attempt_run = str(attempt.get("submitted_run") or attempt.get("out_dir") or "")
        if not attempt_run or attempt_run in submitted_runs:
            attempt["submitted"] = 1
            attempt["published"] = 1
    return True


def reconcile_publication_ledgers(
    *,
    runs_root: Path = RUNS,
    date: str | None = None,
    mode: str | None = None,
    remote_loader: RemoteLoader | None = None,
) -> dict[str, Any]:
    remote_seen, remote_error = (remote_loader or submit_bridge._remote_published_fingerprints)()
    if remote_error:
        return {"status": "remote_dedupe_failed", "reason": remote_error, "checked": 0, "updated": 0}
    ledger_dir = runs_root / LEDGER_DIR
    decision_records = 0
    if remote_loader is None:
        latest_decisions, decision_error = _latest_public_decisions_by_title()
        if not decision_error:
            _record_review_decisions(ledger_dir, latest_decisions)
            decision_records = len(latest_decisions)
    checked = 0
    updated: list[str] = []
    for ledger_path in _ledger_paths_for_reconciliation(ledger_dir, date, mode):
        ledger = _read_json(ledger_path)
        if not ledger:
            continue
        checked += 1
        if _reconcile_published_ledger(ledger, runs_root, remote_seen):
            _write_json(ledger_path, ledger)
            _record_daily_throughput(ledger_dir, ledger)
            updated.append(ledger_path.name)
    for ledger_path in _submit_ledger_paths_for_reconciliation(runs_root, date):
        ledger = _read_json(ledger_path)
        if not ledger:
            continue
        checked += 1
        if _reconcile_published_ledger(ledger, runs_root, remote_seen):
            _write_json(ledger_path, ledger)
            updated.append(f"{submit_bridge.LEDGER_DIR}/{ledger_path.name}")
    return {
        "status": "publication_reconciled" if updated else "no_publication_reconciliation_needed",
        "checked": checked,
        "updated": len(updated),
        "updated_ledgers": updated,
        "known_fingerprints": len(remote_seen),
        "decision_records": decision_records,
    }


def discover_topics(
    topic_packs: Path | None = None,
    corpora: Path | None = None,
    topic_pack_db: Path | None = None,
) -> list[str]:
    topic_packs = topic_packs or TOPIC_PACKS
    topic_pack_db = topic_pack_db or topic_packs.parent / "topic_packs_db"
    _ = corpora
    topics: set[str] = set()
    for path in sorted(topic_packs.glob("*.toml")):
        topic = path.stem
        if not topic.startswith("_"):
            topics.add(topic)
    generated_records = _generated_pack_records(topic_pack_db)
    for path in sorted(topic_pack_db.glob("*/latest.json")):
        topic = path.parent.name
        record = _read_json(path)
        pack_data = record.get("pack_data")
        if (
            not topic.startswith("_")
            and isinstance(pack_data, dict)
            and generated_pack_publishable(record, peer_records=generated_records)
        ):
            topics.add(topic)
    return sorted(topics)


def _generated_pack_records(topic_pack_db: Path | None = None) -> list[dict[str, Any]]:
    db = topic_pack_db or TOPIC_PACKS_DB
    return [
        record for path in sorted(db.glob("*/latest.json"))
        if (record := _read_json(path))
    ]


def _quant_claim_count(topic: str) -> int:
    return sum(1 for _ in (CORPORA / topic / "quant_claims").glob("*.quant_claims.json"))


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


def _parse_time(value: str) -> dt.datetime | None:
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)


def _latest_topic_run(topic: str, runs_root: Path) -> Path | None:
    runs = sorted(runs_root.glob(f"synthesis-{topic}-v*-*"), key=lambda p: p.stat().st_mtime, reverse=True)
    return next((p for p in runs if p.is_dir()), None)


def _manifest_counts(run: Path | None) -> dict[str, Any]:
    manifest = _read_json(run / "manifest.json") if run else {}
    receipts = [r for r in manifest.get("receipts", []) if isinstance(r, dict)]
    primary = sum(1 for r in receipts if str(r.get("evidence_tier") or r.get("tier") or "").upper() in {"A1", "B1"})
    return {
        "has_manifest": bool(manifest),
        "n_receipts": int(manifest.get("n_receipts") or len(receipts) or 0),
        "n_tensions": int(manifest.get("n_non_orthogonal_tensions") or 0),
        "n_primary_tier": primary,
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
                                  "terminal_surface_repeat"})
_PREFLIGHT_BLOCK_STATUSES = frozenset({"corpus_missing_dry_run", "corpus_seed_empty",
                                        "preflight_insufficient_corpus", "preflight_thin_quant_corpus",
                                        "receipt_preflight_insufficient"})
_SOURCE_PRECISION_STATUS = "source_topic_precision_low"
_CORPUS_REPAIR_STATUSES = _PREFLIGHT_BLOCK_STATUSES | {"retracted_source_cited", _SOURCE_PRECISION_STATUS}
_NO_AUTO_RETRY_STATUSES = frozenset({"journal_surface_failed", "journal_surface_not_passed"})


def _surface_ready_after(topic: str, runs_root: Path | None, failure_at: dt.datetime) -> bool:
    """A newer ready artifact proves a prior deterministic surface failure is stale."""
    if runs_root is None:
        return False
    runs = sorted(runs_root.glob(f"synthesis-{topic}-v*-*"), key=lambda p: p.stat().st_mtime, reverse=True)
    for run in (p for p in runs if p.is_dir()):
        if not _final_status_submission_ready(run):
            continue
        surface = _read_json(run / "full_paper.journal_surface.json")
        if surface.get("passed") is not True:
            continue
        updated_at = max(
            (dt.datetime.fromtimestamp(p.stat().st_mtime, dt.UTC)
             for p in (run, run / "final_status.json", run / "full_paper.journal_surface.json", run / "full_paper.md")
             if p.exists()),
            default=None,
        )
        if updated_at and updated_at >= failure_at:
            return True
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
        if topic and allowed and isinstance(stamps, list):
            if any((t := _parse_time(str(s))) and t >= cutoff for s in stamps):
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
    writer_runs = data.get("writer_gate_runs", {})
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
        runs = writer_runs.get(key, []) if isinstance(writer_runs, dict) else []
        brief_failed = any(
            isinstance(row, dict)
            and row.get("review_type_override") == "thin_corpus_brief"
            and (t := _parse_time(str(row.get("at") or "")))
            and t >= cutoff
            for row in runs if isinstance(runs, list)
        )
        out[topic] = {
            "gate": code,
            "count": len(recent),
            "action": "skip_topic" if brief_failed else "thin_corpus_brief",
        }
    return out


def _corpus_repair_topics(ledger_dir: Path, *, now: dt.datetime | None = None) -> set[str]:
    cutoff = (now or dt.datetime.now(dt.UTC)) - dt.timedelta(hours=RECENT_FAILURE_COOLDOWN_HOURS)
    repeats = _read_json(ledger_dir / BLOCKER_HISTOGRAM).get("repeats", {})
    out: set[str] = set()
    for key, stamps in repeats.items() if isinstance(repeats, dict) else []:
        topic, _, code = str(key).partition("\x1f")
        if topic and code in _CORPUS_REPAIR_STATUSES and isinstance(stamps, list):
            if any((t := _parse_time(str(s))) and t >= cutoff for s in stamps):
                out.add(topic)
    return out


def _source_precision_repair_topics(ledger_dir: Path, *, now: dt.datetime | None = None) -> set[str]:
    cutoff = (now or dt.datetime.now(dt.UTC)) - dt.timedelta(hours=RECENT_FAILURE_COOLDOWN_HOURS)
    repeats = _read_json(ledger_dir / BLOCKER_HISTOGRAM).get("repeats", {})
    out: set[str] = set()
    for key, stamps in repeats.items() if isinstance(repeats, dict) else []:
        topic, _, code = str(key).partition("\x1f")
        if topic and code == _SOURCE_PRECISION_STATUS and isinstance(stamps, list):
            if any((t := _parse_time(str(s))) and t >= cutoff for s in stamps):
                out.add(topic)
    return out


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


def _revision_requests_source_precision(feedback: str) -> bool:
    text = str(feedback or "").lower()
    return "source" in text and any(token in text for token in (
        "off-topic", "off topic", "source bundle", "directly address",
        "directly addresses", "narrow the source", "remove or reclassify",
        "unrelated topic", "unrelated topics", "operationalize",
    ))


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
    duplicate_remote_publication). Applying the remote-published exclusion
    unconditionally stops the cycle burning synthesis on already-published
    topics. Universal — keys on the run's own deterministic topic->title, no
    topic terms. Re-publishing an updated paper is the revise cycle's job."""
    out = _recent_submitted_topics(topics, ledger_dir) if ledger_dir else set()
    topic_markers = {m.removeprefix("topic:") for m in markers if m.startswith("topic:")}
    title_markers = [m.removeprefix("title:") for m in markers if m.startswith("title:")]
    for topic in topics:
        if submit_bridge._normalized_key(topic) in topic_markers:
            out.add(topic)
            continue
        display = submit_bridge._normalized_key(submit_bridge._display_topic(topic))
        if display and any(display in marker for marker in title_markers):
            out.add(topic)
    return out


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
    try:
        parsed = dt.datetime.fromisoformat(raw)
    except ValueError:
        return dt.datetime.min.replace(tzinfo=dt.UTC)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)


def _latest_reviews_by_title(url: str | None = None) -> tuple[dict[str, dict[str, Any]], str | None]:
    """Latest research_paper review per paper title for this agent. Researka
    assigns a new artifactId per submission, so latest-wins by reviewedAt drops
    decisions a newer one supersedes. Shared by revise-routing and
    reject-tracking so both read the same authoritative current decision."""
    target = str(url or os.getenv("RESEARKA_REVIEWS_URL", "https://researka.org/reviews"))
    agent_ids = {
        "agent-v3-full-paper",
        os.getenv("RESEARKA_AGENT_SLUG_V3", ""),
        os.getenv("AGENT_ID", ""),
    }
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
    latest: dict[str, dict[str, Any]] = {}
    for row in _review_rows(payload):
        if str(row.get("artifactType") or row.get("artifact_type") or "") != "research_paper":
            continue
        if agent_ids and str(row.get("agentId") or row.get("agent_id") or "") not in agent_ids:
            continue
        key = submit_bridge._title_marker(str(row.get("title") or ""))
        if key and (key not in latest or _review_ts(row) > _review_ts(latest[key])):
            latest[key] = row
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
    rows = submit_bridge._ledger_rows(runs_root / submit_bridge.LEDGER_DIR / "_submitted_fingerprints.json")
    latest: dict[str, dict[str, Any]] = {}
    first_error: str | None = None
    for record in reversed(rows[-SUBMISSION_DECISION_LOOKBACK:]):
        submission_id = str(record.get("submission_id") or "").strip()
        run = runs_root / str(record.get("run") or "")
        paper = run / "full_paper.md"
        if not submission_id or not paper.exists():
            continue
        payload, err = _fetch_submission_decision(submission_id)
        first_error = first_error or err
        if not payload:
            continue
        title = submit_bridge._paper_title(paper)
        row = {
            "artifactType": "research_paper",
            "agentId": submit_bridge._agent_slug(),
            "artifactId": payload.get("decision_object_id") or payload.get("decision_id"),
            "submissionId": submission_id,
            "title": title,
            "topic": record.get("topic") or submit_bridge._run_topic(run),
            "decision": payload.get("decision"),
            "reviewedAt": record.get("submitted_at") or record.get("date"),
            "required_revisions": payload.get("required_revisions") or [],
            "review_summary": payload.get("review_summary"),
            "publication": payload.get("publication"),
        }
        key = submit_bridge._title_marker(title)
        if key and (key not in latest or _review_ts(row) > _review_ts(latest[key])):
            latest[key] = row
    return latest, None if latest else first_error


def _merge_latest_by_title(*sources: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for source in sources:
        for key, row in source.items():
            if key and (key not in latest or _review_ts(row) > _review_ts(latest[key])):
                latest[key] = row
    return latest


def _latest_public_decisions_by_title() -> tuple[dict[str, dict[str, Any]], str | None]:
    reviews, review_error = _latest_reviews_by_title()
    papers, paper_error = _latest_reviews_by_title(os.getenv("RESEARKA_PAPERS_URL", "https://researka.org/papers"))
    latest = _merge_latest_by_title({} if review_error else reviews, {} if paper_error else papers)
    if latest:
        return latest, None
    return {}, review_error or paper_error


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


def _revise_reason_bucket(text: str) -> str:
    lower = " ".join(str(text or "").lower().split())
    taxonomy = (
        ("directness_honesty", ("direct clinical", "direct interventional", "indirect", "adjacent", "mechanistic", "overclaim", "hypothesis-generating", "broad population-level proof", "no direct")),
        ("null_signal_reconciliation", ("null directional", "no extracted directional signal", "no directional signal", "strongest signal", "reconcile", "supports", "bounded rationale")),
        ("source_relevance_classification", ("source bundle", "source directness", "source classification", "outcome class", "evidence_type", "evidence type", "off-topic", "operationalize", "included under")),
        ("numeric_claim_rigor", ("p-value", "p value", "confidence interval", "significant", "non-significant", "effect direction", "factual error", "statistic")),
        ("readability_redundancy", ("repetitive", "duplication", "truncated", "grammatical", "readability", "verbatim repetition")),
        ("actionable_gaps", ("gaps identified", "actionable", "future research", "next steps")),
    )
    for bucket, tokens in taxonomy:
        if any(token in lower for token in tokens):
            return bucket
    return "unknown"


def _required_revision_items(row: dict[str, Any]) -> list[str]:
    raw = row.get("requiredRevisions") or row.get("required_revisions")
    return [str(item).strip() for item in raw if str(item).strip()] if isinstance(raw, list) else []


def _actionable_revisions(row: dict[str, Any]) -> list[str]:
    """Concrete required revisions on a review row. A revise with none (a
    publication-overlap flag, or "no revisions required") has nothing the
    writer can act on — re-rendering it just bounces at the same verdict."""
    return [item for item in _required_revision_items(row) if not _calibration_only_revision(item)]


def _calibration_only_revision(text: str) -> bool:
    lower = " ".join(str(text or "").lower().split())
    return (
        "calibration rules" in lower
        and "revise" in lower
        and (
            "direct clinical evidence" in lower
            or "broad population-level proof is missing" in lower
            or "underlying evidence base" in lower
        )
    )


def _revision_requests_domain_scope_reset(feedback: str) -> bool:
    lower = " ".join(str(feedback or "").lower().split())
    has_domain_frame = any(
        term in lower
        for term in ("geroscience", "anti-aging", "anti aging", "longevity", "healthspan")
    )
    if not has_domain_frame:
        return False
    return (
        ("does not support" in lower and ("framing" in lower or "overlay" in lower))
        or ("does not match" in lower and ("actual question" in lower or "actual research question" in lower))
        or ("remove" in lower and ("framing" in lower or "overlay" in lower))
    )


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
        if str(row.get("decision") or "").lower() != "revise" or not required:
            continue  # only route revises that carry concrete, actionable required revisions
        out.append({
            "artifactId": row.get("artifactId") or row.get("artifact_id"),
            "submissionId": row.get("submissionId") or row.get("submission_id"),
            "title": row.get("title"),
            "topic": row.get("topic"),
            "reviewedAt": row.get("reviewedAt") or row.get("reviewed_at"),
            "feedback": " ".join("; ".join(required).split())[:4000],
        })
    return sorted(out, key=_review_ts, reverse=True), None


def _load_remote_revision_requests(runs_root: Path) -> tuple[list[dict[str, Any]], str | None]:
    try:
        return _remote_revision_requests(runs_root=runs_root)
    except TypeError as exc:
        if "unexpected keyword argument 'runs_root'" not in str(exc):
            raise
        return _remote_revision_requests()


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
        _revision_key(row): _parse_time(str(row.get("reviewedAt") or row.get("reviewed_at") or ""))
        for row in (active_requests or [])
    }

    def _row_applies_to_active_request(row: dict[str, Any]) -> bool:
        reviewed_at = active_reviewed.get(_revision_key(row))
        if reviewed_at is None:
            return True
        handled_at = _parse_time(str(row.get("handled_at") or ""))
        return bool(handled_at and handled_at >= reviewed_at)

    def _retryable_status_in_cooldown(row: dict[str, Any]) -> bool:
        if str(row.get("status") or "") not in _RETRYABLE_REVISION_STATUSES:
            return False
        handled_at = _parse_time(str(row.get("handled_at") or ""))
        if handled_at is None:
            return True
        return dt.datetime.now(dt.UTC) - handled_at < dt.timedelta(
            seconds=RETRYABLE_REVISION_STATUS_COOLDOWN_SECONDS,
        )

    counts = Counter(
        submit_bridge._title_marker(str(row.get("title") or ""))
        for row in rows
        if (
            isinstance(row, dict)
            and row.get("title")
            and _row_applies_to_active_request(row)
            and (str(row.get("status") or "") not in _RETRYABLE_REVISION_STATUSES or _retryable_status_in_cooldown(row))
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
        key = _revision_key(row)
        handled_at = _parse_time(str(row.get("handled_at") or ""))
        reviewed_at = active_reviewed.get(key)
        if reviewed_at is None or (handled_at and (reviewed_at is None or handled_at >= reviewed_at)):
            handled.add(key)
    return handled


def _revision_key(row: dict[str, Any]) -> str:
    # Title-first so the round cap is per-paper, not per-submission: Researka
    # assigns a new artifactId per submission, which would otherwise reset the
    # count every round and let a never-converging paper loop forever.
    return submit_bridge._title_marker(str(row.get("title") or "")) or str(row.get("artifactId") or row.get("submissionId") or "")


def _mark_revision_handled(ledger_dir: Path, row: dict[str, Any], *, status: str) -> None:
    path = ledger_dir / HANDLED_REVISIONS
    data = _read_json(path)
    raw_rows = data.get("handled")
    rows: list[dict[str, Any]] = raw_rows if isinstance(raw_rows, list) else []
    rows.append({
        "key": _revision_key(row),
        "status": status,
        "title": row.get("title"),
        "handled_at": dt.datetime.now(dt.UTC).isoformat(),
    })
    _write_json(path, {"handled": rows[-100:]})


def _pending_remote_revision(
    runs_root: Path,
    ledger_dir: Path,
    *,
    loader: RevisionLoader | None = None,
    published_loader: PublishedLoader | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    rows, error = loader() if loader else _load_remote_revision_requests(runs_root)
    if error:
        return None, error
    handled = _handled_revision_ids(ledger_dir, rows)
    remote_seen: set[str] = set()
    if published_loader is not None:
        remote_seen, _remote_error = published_loader()
    submitted = runs_root / submit_bridge.LEDGER_DIR / "_submitted_fingerprints.json"
    raw_records = json.loads(submitted.read_text(encoding="utf-8")) if submitted.exists() else []
    records: list[Any] = raw_records if isinstance(raw_records, list) else []
    for request in rows:
        if _revision_key(request) in handled:
            continue
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
        if any(_submitted_record_is_published(record, run / "full_paper.md", remote_seen) for record, run, _topic in matches):
            continue
        if matches:
            record, run, record_topic = matches[-1]
            request["topic"] = record_topic
            request["source_run"] = run.name
            return request, None
    return None, None


def _pending_remote_revision_topics(
    runs_root: Path,
    ledger_dir: Path,
    *,
    loader: RevisionLoader | None = None,
    published_loader: PublishedLoader | None = None,
) -> tuple[set[str], str | None]:
    rows, error = loader() if loader else _load_remote_revision_requests(runs_root)
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
    return bool(str(data.get("target_journal", "")).strip())


def _publication_score(topic: str, ledger_dir: Path, runs_root: Path) -> int:
    total, l4plus = _topic_run_stats(topic, runs_root)
    pass_rate = (l4plus / total) if total else 0
    last = _parse_time(_attempted_at(topic, ledger_dir))
    freshness = 2 if last is None or dt.datetime.now(dt.UTC) - last > dt.timedelta(days=14) else 0
    return round(pass_rate * 5) + int(_publication_track_topic(topic)) * 3 + freshness - _recent_failed_attempts(topic, ledger_dir) * 2


def _topic_support_score(topic: str) -> int:
    record = _read_json(TOPIC_PACKS_DB / topic / "latest.json")
    count = record.get("candidate_count")
    if isinstance(count, int) and count > 0:
        return count
    return _quant_claim_count(topic)


def _topic_has_quant_floor(topic: str) -> bool:
    return _quant_claim_count(topic) >= PREFLIGHT_MIN_QUANT_CLAIMS


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


def select_topic(
    topics: list[str],
    ledger_dir: Path,
    *,
    runs_root: Path = RUNS,
    remote_seen: set[str] | None = None,
    exclude: set[str] | None = None,
) -> str | None:
    blocked = _published_topics(topics, remote_seen or set(), ledger_dir)
    candidates = [topic for topic in topics if topic not in blocked and topic not in (exclude or set())]
    if not candidates:
        return None
    recent_blocked = _recent_blocked_topics(ledger_dir)
    fresh_candidates = [topic for topic in candidates if topic not in recent_blocked and _recent_failed_attempts(topic, ledger_dir) == 0]
    candidates = fresh_candidates or candidates
    pool = [topic for topic in candidates if _publication_track_topic(topic)]
    if not pool:
        return None
    # Prefer topics with a local corpus first; empty generated frontier topics
    # belong behind publishable corpora so the publish lane does not spend the
    # whole window seeding. Within that ready pool, frontier-advance still holds:
    # a never-attempted topic outranks any already-attempted one.
    # Within each group the existing order still applies — publication score,
    # then fact support, then least-recently attempted. Revisiting proven
    # topics is the revise cycle's job, not the fresh cycle's.
    untried = {topic for topic in pool if _topic_run_stats(topic, runs_root)[0] == 0}
    return min(pool, key=lambda topic: (
        0 if _quant_claim_count(topic) >= PREFLIGHT_MIN_QUANT_CLAIMS else 1,
        0 if topic in untried else 1,
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
    if reason == "latest_run_missing_manifest" or reason.startswith("recent_failed_attempts="):
        return True
    return reason.startswith(("n_receipts=", "n_tensions=", "n_outcome_classes=")) and reason.endswith("(split topic)")


def _preflight(topic: str, runs_root: Path, ledger_dir: Path, *, current_quant_claims: int | None = None) -> dict[str, Any]:
    latest = _latest_topic_run(topic, runs_root)
    counts = _manifest_counts(latest)
    publication_track = _publication_track_topic(topic)
    reasons = []
    if not publication_track:
        reasons.append("target_journal_not_declared")
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
    if recent_failures and not publication_track:
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


def _quant_claim_preflight(corpus: dict[str, Any]) -> dict[str, Any]:
    try:
        n_quant_claims = int(corpus.get("n_quant_claims") or 0)
    except (TypeError, ValueError):
        n_quant_claims = 0
    reasons = [] if n_quant_claims >= PREFLIGHT_MIN_QUANT_CLAIMS else [f"n_quant_claims={n_quant_claims} < {PREFLIGHT_MIN_QUANT_CLAIMS}"]
    return {"passed": not reasons, "reasons": reasons, "n_quant_claims": n_quant_claims}


def _paper_strategy(corpus: dict[str, Any], preflight: dict[str, Any], revision_feedback: str = "") -> dict[str, Any]:
    q = int(corpus.get("n_quant_claims") or 0)
    receipts = int(preflight.get("n_receipts") or q)
    tensions = int(preflight.get("n_tensions") or 0)
    primary = int(preflight.get("n_primary_tier") or 0)
    sparse = bool(_SPARSE_REVIEW_RE.search(revision_feedback))
    terminal_sparse = bool(_TERMINAL_SPARSE_RE.search(revision_feedback))
    if not preflight.get("has_manifest") and not sparse:
        return {
            "action": "write",
            "review_type_override": None,
            "reason": "no_prior_manifest",
            "frames": [{"name": "full_paper", "score": 1.0}],
            "selected": {"name": "full_paper", "score": 1.0},
        }
    full = min(1.0, q / 50) * 0.15 + min(1.0, receipts / 30) * 0.40 + min(1.0, tensions / 10) * 0.30 + min(1.0, primary / 3) * 0.15 - (0.45 if sparse else 0)
    brief = min(1.0, q / 10) * 0.35 + min(1.0, receipts / 10) * 0.25 + min(1.0, primary) * 0.10 + (0.20 if sparse else 0)
    skip = 1.1 if terminal_sparse and full < FRAME_MIN_FULL_SCORE else 0.05
    scores = [
        ("full_paper", round(max(0.0, full), 3)),
        ("thin_corpus_brief", round(min(1.0, brief), 3)),
        ("skip_topic", round(skip, 3)),
    ]
    selected_name, selected_score = max(scores, key=lambda row: (row[1], row[0] == "full_paper"))
    frames = [{"name": name, "score": score} for name, score in scores]
    return {
        "action": "skip_topic" if selected_name == "skip_topic" else "write",
        "review_type_override": "thin_corpus_brief" if selected_name == "thin_corpus_brief" else None,
        "reason": "terminal_sparse_researka_feedback" if terminal_sparse else "sparse_researka_feedback" if sparse else "highest_frame_score",
        "frames": frames,
        "selected": {"name": selected_name, "score": selected_score},
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
        "corpus_missing_dry_run": "B_corpus_fixable",
        "corpus_seed_empty": "B_corpus_fixable",
        "corpus_seed_failed": "B_corpus_fixable",
        "receipt_preflight_insufficient": "B_corpus_fixable",
        "missing": "C_writer_fixable",
        "superseded_topic_run": "D_no_action",
        "terminal_synthesis_timeout": "D_no_action",
    }.get(code, "unknown")


def _revision_asks(feedback: str) -> list[str]:
    """The enumerated reviewer asks recovered from the '; '-joined feedback."""
    import revision_coverage
    return revision_coverage.revision_asks(feedback)


def _unmet_revision_asks(out_dir: Path, feedback: str) -> list[str]:
    """Reviewer asks the rendered paper does NOT materially address, per the
    coverage judge. Fail-open (empty on any error). Monkeypatched in tests."""
    paper = out_dir / "full_paper.md"
    if not paper.is_file():
        return []
    import revision_coverage
    text = paper.read_text(encoding="utf-8")
    unmet = revision_coverage.material_unmet_asks(text, feedback)
    return [ask for ask in unmet if not _payload_revision_ask_satisfied(out_dir, ask)]


def _payload_revision_ask_satisfied(out_dir: Path, ask: str) -> bool:
    ask_lower = ask.lower()
    paper_text = ""
    try:
        paper_text = (out_dir / "full_paper.md").read_text(encoding="utf-8").lower()
    except OSError:
        paper_text = ""
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
    if "direct evidence" in ask_lower and any(token in ask_lower for token in ("definition", "qualifying", "qualify", "0/")):
        return "qualifying direct source" in paper_text or "direct interventional hard-endpoint evidence" in paper_text
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


def _retracted_cited_sources(out_dir: Path) -> list[str]:
    """Retracted DOIs the paper cites (OpenAlex check). Fail-open (empty on any
    error); monkeypatched in tests so they stay offline."""
    import retraction_check
    return retraction_check.retracted_cited_sources(out_dir)


def _abstract_overclaims(out_dir: Path) -> list[str]:
    """Abstract claims the paper's evidence does not support / overstates
    (claim-support judge). Fail-open (empty on any error); monkeypatched in
    tests so they stay offline."""
    paper = out_dir / "full_paper.md"
    if not paper.is_file():
        return []
    import revision_coverage
    return revision_coverage.unsupported_abstract_claims(paper.read_text(encoding="utf-8"))


def _numeric_effect_direction_issues(out_dir: Path) -> list[str]:
    paper = out_dir / "full_paper.md"
    if not paper.is_file():
        return []
    import revision_coverage
    return revision_coverage.numeric_effect_direction_issues(paper.read_text(encoding="utf-8"))


def _final_status_submission_ready(out_dir: Path) -> bool:
    return bool(_read_json(out_dir / "final_status.json").get("submission_ready"))


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
    """Prepend an explicit escalation so an unmet ask is materially fixed on the
    bounded re-render, not skimmed again."""
    return (
        "PRIOR REVISION DID NOT ADDRESS THESE REQUIRED POINTS — you MUST make a "
        f"substantive change to satisfy EACH: {'; '.join(unmet)}"
    )


def _record_blockers(ledger_dir: Path, date: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    path = ledger_dir / BLOCKER_HISTOGRAM
    data = _read_json(path)
    blockers = data.setdefault("blockers", {})
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
        item = blockers.setdefault(code, {"count": 0, "class": _failure_class(status), "samples": []})
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
            if _failure_class(code).startswith("C_"):
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
) -> int:
    cmd = [sys.executable, "scripts/run_v06_synthesis.py", "--topic", topic, "--out-dir", str(out_dir)]
    if dry_run:
        cmd.append("--dry-run")
    env: dict[str, str] | None = None
    if revision_feedback or review_type_override:
        env = os.environ.copy()
        if revision_feedback:
            env["RESEARKA_REVISION_FEEDBACK"] = revision_feedback[:4000]
        if review_type_override:
            env["RESEARCH_AGENT_REVIEW_TYPE_OVERRIDE"] = review_type_override
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
    rounds = _receipt_preflight_repair_rounds() if repair and not dry_run else 0
    probes: list[dict[str, Any]] = []
    repairs: list[dict[str, Any]] = []
    rc = 1
    n_receipts = 0
    best_receipts = 0
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
        previous_best = best_receipts
        best_receipts = max(best_receipts, n_receipts)
        probes.append({"return_code": rc, "n_receipts": n_receipts, "min_receipts": min_receipts})
        if rc == 0 and n_receipts >= min_receipts:
            break
        if rc == 0 and n_receipts == 0:
            break
        if round_idx > 0 and rc == 0 and best_receipts <= previous_best:
            break
        if round_idx >= rounds:
            break
        current_quant_claims = _quant_claim_count(topic)
        if not best_receipts or (rc != 0 and not current_quant_claims):
            break
        corpus_repair = _repair_topic_corpus(
            topic,
            dry_run=False,
            timeout=timeout,
            seed_limit=_receipt_repair_seed_limit(
                max(n_receipts, best_receipts), min_receipts, round_idx, current_quant_claims=current_quant_claims,
            ),
            force_extract=False,
        )
        repairs.append(corpus_repair)
        if corpus_repair.get("status") not in {"corpus_ready", "corpus_seeded", "corpus_repaired"}:
            break
    passed = rc == 0 and n_receipts >= min_receipts
    return {
        "passed": passed,
        "status": "receipt_preflight_ok" if passed else "receipt_preflight_insufficient",
        "return_code": rc,
        "n_receipts": n_receipts if passed else best_receipts,
        "min_receipts": min_receipts,
        "probes": probes,
        **({"repairs": repairs} if repairs else {}),
    }


def _existing_receipt_preflight(source_run: Path | None) -> dict[str, Any] | None:
    if source_run is None or not source_run.is_dir():
        return None
    counts = _manifest_counts(source_run)
    n_receipts = int(counts.get("n_receipts") or 0)
    n_tensions = int(counts.get("n_tensions") or 0)
    n_primary = int(counts.get("n_primary_tier") or 0)
    min_receipts = DEFAULT_THRESHOLDS.min_receipts
    if (
        n_receipts < min_receipts
        or n_tensions < PREFLIGHT_MIN_TENSIONS
        or n_primary < PREFLIGHT_MIN_PRIMARY_TIER
    ):
        return None
    return {
        "passed": True,
        "status": "receipt_preflight_existing_ok",
        "n_receipts": n_receipts,
        "n_tensions": n_tensions,
        "n_primary_tier": n_primary,
        "min_receipts": min_receipts,
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
    qdir = CORPORA / topic / "quant_claims"
    available_ids = {rid for rid in receipt_ids if (qdir / f"{rid}.quant_claims.json").is_file()}
    min_receipts = DEFAULT_THRESHOLDS.min_receipts
    missing = [rid for rid in receipt_ids if rid not in available_ids]
    return {
        "passed": len(available_ids) >= min_receipts,
        "status": "source_manifest_available" if len(available_ids) >= min_receipts else "source_manifest_unavailable",
        "source_run": source_run.name if source_run else "",
        "n_source_receipts": len(receipt_ids),
        "n_available_quant_claim_files": len(available_ids),
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
    """A repaired revise corpus that stays severely sparse should not monopolise
    later revise windows for the same reviewer request."""
    if report.get("passed") or str(report.get("status") or "") != "receipt_preflight_insufficient":
        return False
    repairs = report.get("repairs")
    probes = report.get("probes")
    if not isinstance(repairs, list) or not repairs or not isinstance(probes, list) or not probes:
        return False
    try:
        n_receipts = int(report.get("n_receipts") or 0)
        min_receipts = int(report.get("min_receipts") or 0)
        first_probe = int(probes[0].get("n_receipts") or 0) if isinstance(probes[0], dict) else 0
    except (TypeError, ValueError):
        return False
    return min_receipts > 0 and n_receipts < max(1, min_receipts // 2) and n_receipts <= first_probe


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
        else:
            _write_json(out_dir / "internal_repair_request.json", {"source_run": source_dir.name, "reason": repair_reason})
        from agent.journal_finalizer import finalize_run
        finalize_run(out_dir)
        if repair_reason:
            after = paper_path.read_text(encoding="utf-8")
            if after == before:
                shutil.rmtree(out_dir, ignore_errors=True)
                return False, "repair_noop"
            if repair_reason == "journal_surface_not_passed":
                from agent.journal_surface_gate import evaluate_journal_surface
                surface = evaluate_journal_surface(after)
                if not surface.passed:
                    codes = ",".join(sorted({issue.code for issue in surface.issues}))
                    shutil.rmtree(out_dir, ignore_errors=True)
                    return False, f"surface_after_repair_failed:{codes}"
    except (OSError, RuntimeError, ValueError, ImportError) as exc:
        shutil.rmtree(out_dir, ignore_errors=True)
        return False, f"{type(exc).__name__}: {exc}"
    return True, ""


def _numeric_density_downshift(run: Path | None) -> str | None:
    audit = _read_json(run / "full_paper.audit.json") if run else {}
    for check in audit.get("checks", []):
        if isinstance(check, dict) and check.get("name") == "Q9_numeric_density" and check.get("passed") is False:
            return "thin_corpus_brief"
    return None


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
    if str(attempt.get("failure_class") or "").startswith(("B_", "D_")):
        return False
    return True


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
        cap = max(1, int(os.environ.get("RESEARCH_AGENT_PUBLISH_SEED_TIMEOUT_SECONDS", str(PUBLISH_SEED_TIMEOUT_SECONDS))))
    except ValueError:
        cap = PUBLISH_SEED_TIMEOUT_SECONDS
    return min(timeout, cap) if timeout and timeout > 0 else cap


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
    n_receipts: int, min_receipts: int, round_idx: int, *, current_quant_claims: int = 0,
) -> int:
    missing = max(1, min_receipts - max(0, n_receipts))
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
    if force_extract:
        cmd.append("--force-extract")
    seed_timeout = _seed_topic_timeout(timeout)
    try:
        result = subprocess.run(cmd, cwd=ROOT, check=False, timeout=seed_timeout, capture_output=True, text=True)
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


def _ensure_topic_corpus(topic: str, *, dry_run: bool, timeout: int | None = None) -> dict[str, Any]:
    before = _quant_claim_count(topic)
    if before:
        return {"status": "corpus_ready", "n_quant_claims": before}
    if dry_run:
        return {"status": "corpus_missing_dry_run", "n_quant_claims": 0}
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
        preflight_blocked = set() if topic else _recent_preflight_blocked_topics(ledger_dir)
        if preflight_blocked:
            ledger["preflight_blocked_topics"] = sorted(preflight_blocked)
        receipt_preflight_blocked = set() if topic else _recent_receipt_preflight_blocked_topics(ledger_dir)
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
        current_source_precision: set[str] = set()
        source_precision_auto_excluded: set[str] = set() if topic else _unrepairable_source_precision_topics(ledger_dir)
        if source_precision_auto_excluded:
            ledger["source_precision_unrepairable_topics"] = sorted(source_precision_auto_excluded)
        if run_synthesis and mode != "revise" and topic is None:
            repairs: list[dict[str, Any]] = []
            current_source_precision = _current_low_source_precision_topics(topics)
            if remote_revision:
                current_source_precision.discard(str(remote_revision.get("topic") or ""))
            if current_source_precision:
                ledger["source_precision_backlog_topics"] = sorted(current_source_precision)
                ledger["source_precision_backlog_count"] = len(current_source_precision)
            repairable = (
                _corpus_repair_topics(ledger_dir) | current_source_precision
            ) - terminal_excluded - submitted_topics - published_topics - pending_revision_excluded - surface_repeat - writer_gate_skip
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
                repairable,
                key=lambda t: (-_quant_claim_count(t), -_topic_support_score(t), _attempted_at(t, ledger_dir), t),
            )
            for repair_topic in repair_order[:_corpus_repair_limit()]:
                if repair_topic in source_precision_repairable:
                    source_precision_repair_attempted.add(repair_topic)
                    repair = _repair_low_source_precision_corpus(
                        repair_topic, dry_run=synthesis_dry_run, timeout=repair_timeout,
                    )
                else:
                    repair = _repair_topic_corpus(repair_topic, dry_run=synthesis_dry_run, timeout=repair_timeout)
                repairs.append({"topic": repair_topic, **repair})
                if int(repair.get("n_quant_claims") or 0) >= PREFLIGHT_MIN_QUANT_CLAIMS:
                    if repair_topic not in receipt_preflight_blocked:
                        preflight_blocked.discard(repair_topic)
                        surface_repeat.discard(repair_topic)
                        corpus_repaired_ok.add(repair_topic)
                if repair.get("status") == "source_precision_repaired":
                    source_precision_repaired_ok.add(repair_topic)
            unrepaired_attempted = source_precision_repair_attempted - source_precision_repaired_ok
            unattempted_source_precision = current_source_precision - source_precision_repaired_ok - source_precision_repair_attempted
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
        submitted_total = 0
        attempt_count = 0
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
            # Revise lane: only process pending revises — never rotate to a fresh
            # topic. Once the one revise is handled (revision_source drops to None
            # on the next pass), stop. No pending revise at all -> nothing to do.
            if mode == "revise" and revision_source is None:
                if not ledger["attempts"]:
                    ledger["status"] = "no_revise_pending"
                break
            dynamic_preflight_blocked = set() if topic else _recent_preflight_blocked_topics(ledger_dir)
            dynamic_preflight_blocked -= corpus_repaired_ok | source_precision_repaired_ok
            if dynamic_preflight_blocked != preflight_blocked:
                preflight_blocked = dynamic_preflight_blocked
                ledger["preflight_blocked_topics"] = sorted(preflight_blocked)
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
            repaired_candidates = sorted(
                topic for topic in (corpus_repaired_ok | source_precision_repaired_ok) - selection_excluded
                if _quant_claim_count(topic) >= PREFLIGHT_MIN_QUANT_CLAIMS
            )
            selected = (
                str(revision_source.get("topic") or "")
                if revision_source
                else topic or select_topic(repaired_candidates or topics, ledger_dir, runs_root=runs_root, remote_seen=remote_seen, exclude=selection_excluded)
            )
            if not selected:
                ledger["status"] = "no_unpublished_topic_available"
                break
            seeded_frontier_corpus: dict[str, Any] | None = None
            if not revision_source and submit and mode == "fresh" and not _topic_has_quant_floor(selected):
                seeded_frontier_corpus = (ensure_corpus or _ensure_topic_corpus)(
                    selected, dry_run=synthesis_dry_run, timeout=_publish_seed_timeout(child_timeout()),
                )
                ledger["frontier_corpus_seed"] = {"topic": selected, **seeded_frontier_corpus}
            if (
                not revision_source
                and submit
                and mode == "fresh"
                and not _topic_has_quant_floor(selected)
            ):
                ledger.update({
                    "status": "no_ready_corpus_available",
                    "attempted_topic": selected,
                    "selected_without_quant_floor": selected,
                })
                break
            numeric_review_type = _numeric_density_downshift(_latest_topic_run(selected, runs_root))
            stamp = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
            out_dir = runs_root / f"synthesis-{selected}-v06-DAILY-{stamp}"
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
                ledger["blocker_histogram"] = _record_blockers(ledger_dir, date, [attempt])
                _mark_revision_handled(ledger_dir, revision_source, status=gate_status)
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
                ledger["blocker_histogram"] = _record_blockers(ledger_dir, date, [attempt])
                _mark_revision_handled(ledger_dir, revision_source, status="terminal_surface_repeat")
                attempted.add(selected)
                remote_revision = None
                continue
            if revision_source and selected in _unrepairable_source_precision_topics(ledger_dir):
                gate_status = "terminal_source_precision_repair_incomplete"
                attempt = _gate_attempt(selected, out_dir, gate_status)
                ledger["attempts"].append(attempt)
                ledger["status"] = "revise_terminal_source_precision_repair_incomplete"
                ledger["blocker_histogram"] = _record_blockers(ledger_dir, date, [attempt])
                _mark_revision_handled(ledger_dir, revision_source, status=gate_status)
                attempted.add(selected)
                remote_revision = None
                continue
            revision_source_run = runs_root / str(revision_source.get("source_run") or "") if revision_source else None
            existing_source_preflight = _existing_receipt_preflight(revision_source_run) if revision_source else None
            corpus_timeout = child_timeout() if revision_source else _publish_seed_timeout(child_timeout())
            corpus: dict[str, Any]
            if existing_source_preflight:
                corpus = {
                    "status": "corpus_ready",
                    "source": "existing_source_manifest",
                    "source_run": revision_source_run.name if revision_source_run else "",
                    "n_quant_claims": max(
                        PREFLIGHT_MIN_QUANT_CLAIMS,
                        int(existing_source_preflight.get("n_receipts") or 0),
                    ),
                }
            elif seeded_frontier_corpus is not None:
                corpus = seeded_frontier_corpus
            else:
                corpus = (ensure_corpus or _ensure_topic_corpus)(selected, dry_run=synthesis_dry_run, timeout=corpus_timeout)
            ledger["corpus"] = corpus
            revision_source_repair = _revision_requests_source_precision(revision_feedback)
            source_manifest_availability = (
                _source_manifest_availability(selected, revision_source_run)
                if existing_source_preflight
                else None
            )
            if (
                source_manifest_availability
                and not source_manifest_availability.get("passed")
                and revision_source
                and not revision_source_repair
            ):
                restore = _restore_source_manifest_quant_claims(selected, revision_source_run)
                source_manifest_availability = _source_manifest_availability(selected, revision_source_run)
                ledger["source_manifest_restore"] = {
                    **restore,
                    "availability_after": source_manifest_availability,
                }
            if source_manifest_availability and not source_manifest_availability.get("passed"):
                gate_status = "terminal_revision_source_manifest_unavailable"
                attempt = _gate_attempt(
                    selected,
                    out_dir,
                    gate_status,
                    source_manifest_availability=source_manifest_availability,
                )
                ledger["attempts"].append(attempt)
                ledger["status"] = gate_status
                ledger["blocker_histogram"] = _record_blockers(ledger_dir, date, [attempt])
                if revision_source:
                    _mark_revision_handled(ledger_dir, revision_source, status=gate_status)
                    remote_revision = None
                attempted.add(selected)
                continue
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
                ledger["blocker_histogram"] = _record_blockers(ledger_dir, date, [attempt])
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
                if retained >= PREFLIGHT_MIN_QUANT_CLAIMS:
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
                    if source_repair.get("status") == "source_precision_repaired":
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
                        ledger["blocker_histogram"] = _record_blockers(ledger_dir, date, [attempt])
                        attempted.add(selected)
                        continue
                else:
                    attempt = _source_precision_attempt(selected, out_dir, source_precision_status, corpus=corpus)
                    ledger["attempts"].append(attempt)
                    ledger["status"] = "source_precision_repair_deferred_no_submission"
                    ledger["blocker_histogram"] = _record_blockers(ledger_dir, date, [attempt])
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
            if revision_source and existing_source_preflight and not revision_source_repair:
                source_precision_needs_repair = False
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
                    ledger["blocker_histogram"] = _record_blockers(ledger_dir, date, [attempt])
                    if revision_source:
                        _mark_revision_handled(ledger_dir, revision_source, status=gate_status)
                        remote_revision = None
                    attempted.add(selected)
                    continue
            quant_preflight = _quant_claim_preflight(corpus)
            quant_corpus_repairs: list[dict[str, Any]] = []
            if not quant_preflight["passed"] and not synthesis_dry_run:
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
                    quant_preflight = _quant_claim_preflight(corpus)
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
                ledger["blocker_histogram"] = _record_blockers(ledger_dir, date, [attempt])
                attempted.add(selected)
                continue
            preflight = _preflight(
                selected,
                runs_root,
                ledger_dir,
                current_quant_claims=int(corpus.get("n_quant_claims") or 0),
            )
            if not preflight["passed"]:
                terminal_missing_manifest = (
                    revision_source is not None
                    and "latest_run_missing_manifest" in preflight.get("reasons", [])
                )
                gate_status = (
                    "terminal_latest_run_missing_manifest"
                    if terminal_missing_manifest
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
                    else "preflight_skipped_no_submission"
                )
                ledger["blocker_histogram"] = _record_blockers(ledger_dir, date, [attempt])
                if terminal_missing_manifest and revision_source is not None:
                    _mark_revision_handled(ledger_dir, revision_source, status=gate_status)
                    remote_revision = None
                attempted.add(selected)
                continue
            strategy = _paper_strategy(corpus, preflight, revision_feedback)
            ledger["paper_strategy"] = strategy
            if strategy.get("action") == "skip_topic":
                attempt = {
                    "topic": selected,
                    "out_dir": out_dir.name,
                    "synthesis_return_code": None,
                    "submit_status": "strategy_evidence_insufficient",
                    "failure_class": _failure_class("strategy_evidence_insufficient"),
                    "submitted": 0,
                    "paper_strategy": strategy,
                }
                ledger["attempts"].append(attempt)
                ledger["status"] = "strategy_skipped_no_submission"
                ledger["blocker_histogram"] = _record_blockers(ledger_dir, date, [attempt])
                if revision_source:
                    _mark_revision_handled(ledger_dir, revision_source, status="strategy_evidence_insufficient")
                attempted.add(selected)
                continue
            if revision_source:
                ledger["revision_source"] = {
                    key: revision_source.get(key)
                    for key in ("artifactId", "submissionId", "source_run", "title")
                    if revision_source.get(key)
                }
            strategy_review_type = str(strategy.get("review_type_override") or "") or None
            repeat_policy = writer_gate_policy.get(selected, {})
            repeat_review_type = "thin_corpus_brief" if repeat_policy.get("action") == "thin_corpus_brief" else None
            review_type_override = numeric_review_type or strategy_review_type or repeat_review_type
            if review_type_override:
                reason = "Q9_numeric_density" if numeric_review_type else (
                    str(strategy.get("reason") or "paper_strategy")
                    if strategy_review_type
                    else f"writer_gate_repeat:{repeat_policy.get('gate')}"
                )
                ledger["review_type_override"] = {"topic": selected, "value": review_type_override, "reason": reason}
            last_attempt: dict[str, Any] | None = None
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
                repair_reason = ""
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
                    ledger["blocker_histogram"] = _record_blockers(ledger_dir, date, [attempt])
                    _mark_revision_handled(ledger_dir, revision_source, status=gate_status)
                    remote_revision = None
                    attempted.add(selected)
                    break
                feedback_applied = bool(revision_feedback)
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
                receipt_preflight = (
                    {"passed": True}
                    if existing_repair
                    else _existing_receipt_preflight(revision_base_dir)
                    if revision_source
                    else None
                )
                if receipt_preflight is None:
                    receipt_preflight = _receipt_preflight(
                        selected,
                        out_dir,
                        timeout=child_timeout(),
                        repair=True,
                        dry_run=synthesis_dry_run,
                    )
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
                    ledger["blocker_histogram"] = _record_blockers(ledger_dir, date, [attempt])
                    if revision_source:
                        _mark_revision_handled(ledger_dir, revision_source, status=gate_status)
                        remote_revision = None
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
                    _write_json(out_dir / REVISION_COVERAGE_GATE, {
                        "passed": not unmet,
                        "ask_count": len(_revision_asks(revision_feedback)),
                        "unmet_asks": unmet,
                    })
                # Retraction gate: never submit a paper that cites retracted science.
                retracted = _retracted_cited_sources(out_dir) if return_code == 0 else []
                # Claim-support gate: never submit an abstract whose claims the
                # paper's own evidence does not support / overstates.
                overclaims = _abstract_overclaims(out_dir) if return_code == 0 else []
                numeric_issues = _numeric_effect_direction_issues(out_dir) if return_code == 0 else []
                abstract_repaired = False
                if overclaims and _repair_abstract_overclaim_phrasing(out_dir, overclaims):
                    abstract_repaired = True
                    overclaims = _abstract_overclaims(out_dir)
                advisory_overclaims = list(overclaims)
                abstract_overclaim_advisory = bool(overclaims and _final_status_submission_ready(out_dir))
                if abstract_overclaim_advisory:
                    overclaims = []
                bridge: dict[str, Any] = {}
                if return_code == 0 and not unmet and not retracted and not numeric_issues and not overclaims:
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
                    else "synthesis_failed" if return_code != 0
                    else "retracted_source_cited" if retracted
                    else "numeric_effect_mismatch" if numeric_issues
                    else "abstract_overclaim" if overclaims
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
                    "revision_feedback_applied": feedback_applied,
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
                if numeric_issues:
                    attempt["numeric_effect_direction_issues"] = numeric_issues
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
                        source_precision_retry = source_repair.get("status") == "source_precision_repaired"
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
                if isinstance(bridge.get("revision_feedback"), str):
                    revision_feedback = str(bridge["revision_feedback"])
                    attempt["revision_feedback_received"] = bool(revision_feedback)
                if gate_status and gate_status != "eligible":
                    ledger["blocker_histogram"] = _record_blockers(ledger_dir, date, [attempt])
                if revision_source and gate_status.split(":", 1)[0] in _TERMINAL_REVISION_STATUSES:
                    _mark_revision_handled(ledger_dir, revision_source, status=gate_status)
                elif revision_source and gate_status == "revision_coverage_unmet":
                    _mark_revision_handled(ledger_dir, revision_source, status=gate_status)
                if return_code == SYNTHESIS_TIMEOUT_RETURN_CODE:
                    if revision_source:
                        timeout_status = "synthesis_timeout"
                        attempt["revision_timeout_status"] = timeout_status
                        _mark_revision_handled(ledger_dir, revision_source, status=timeout_status)
                    ledger["status"] = "synthesis_timeout_no_submission"
                    ledger["no_submission_reason"] = gate_status
                elif return_code != 0:
                    ledger["status"] = "synthesis_failed"
                elif bridge.get("status") == "submitted_to_researka":
                    ledger["status"] = "submitted_to_researka"
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
                else:
                    ledger["status"] = "synthesis_completed_no_submission"
                    if gate_status and gate_status != "eligible":
                        ledger["no_submission_reason"] = gate_status
                if source_precision_retry and revise_attempt < max(1, max_revise_attempts):
                    continue
                if (
                    same_topic_retries >= 2
                    or same_gate_failures >= 2
                    or revise_attempt >= max(1, max_revise_attempts)
                    or not _should_retry_same_topic(attempt, auto_selected=topic is None and not revision_source)
                ):
                    break
            if ledger["status"] == "cycle_budget_exhausted":
                break
            if ledger["status"] == "submitted_to_researka":
                submitted_total += int(ledger.get("submitted") or 0)
                if revision_source:
                    # Revise shipped — record it, then keep the cycle going so it
                    # still produces a fresh paper. A backlog of revises otherwise
                    # monopolises the one-submit-per-cycle budget and starves new
                    # output (the May-30 throughput regression). Universal.
                    _mark_revision_handled(ledger_dir, revision_source, status="submitted_to_researka")
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
    args = parser.parse_args(argv)
    if args.reconcile_publications:
        result = reconcile_publication_ledgers(runs_root=args.runs_root, date=args.date, mode=args.mode)
        print(
            f"[daily-v3-cycle] status={result['status']} checked={result['checked']} "
            f"updated={result['updated']} ledgers={','.join(result.get('updated_ledgers', [])) or '-'}"
        )
        return 0 if result["status"] != "remote_dedupe_failed" else 2
    ledger = run_cycle(
        runs_root=args.runs_root,
        date=args.date or dt.datetime.now(dt.UTC).date().isoformat(),
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
    failures = {"synthesis_failed", "remote_dedupe_failed", "submit_not_configured", "topic_not_available"}
    return 0 if ledger["status"] not in failures else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
