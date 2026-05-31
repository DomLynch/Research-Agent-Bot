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
import urllib.request
from collections import Counter
from collections.abc import Callable, Iterator
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
RUNS = ROOT / "runs"
TOPIC_PACKS = ROOT / "topic_packs"
CORPORA = ROOT / "docs" / "quality-reference"
LEDGER_DIR = "_daily_research_paper_cycle_ledger"
BLOCKER_HISTOGRAM = "_blocker_histogram.json"
HANDLED_REVISIONS = "_handled_revision_requests.json"
# A Researka revise may be re-processed up to this many rounds per artifact
# before it is treated as permanently handled. Single-round handling left
# papers stuck after one revise; the cap lets feedback-aware re-renders iterate
# while bounding resubmissions to the live platform.
MAX_REVISE_ROUNDS = 3
PREFLIGHT_MIN_RECEIPTS = 15
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
CORPUS_REPAIR_LIMIT = 1
DECISION_POLL_SECONDS = 900
DECISION_POLL_INTERVAL_SECONDS = 30
CYCLE_BUDGET_SECONDS = 6300
PUBLISHED_TOPIC_COOLDOWN_DAYS = 30
FRAME_MIN_FULL_SCORE = 0.65
_SPARSE_REVIEW_RE = re.compile(r"\b(mixed and sparse|evidence base\W+sparse|precludes?\W+(?:a\W+)?(?:strong\W+)?accept|no material revisions?)\b", re.I)
_TERMINAL_SPARSE_RE = re.compile(r"\b(precludes?\W+(?:a\W+)?(?:strong\W+)?accept|no material revisions?)\b", re.I)
_TERMINAL_REVISION_STATUSES = frozenset({
    "duplicate_remote_publication",
    "duplicate_submission_fingerprint",
    "researka_revision_fingerprint",
    "research_revision_fingerprint",
    "retracted_source_cited",
    "terminal_surface_repeat",
})

RemoteLoader = Callable[[], tuple[set[str], str | None]]
SubmitCycle = Callable[..., dict[str, Any]]
CorpusBuilder = Callable[..., dict[str, Any]]
RevisionLoader = Callable[[], tuple[list[dict[str, Any]], str | None]]
Sleeper = Callable[[float], None]


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def discover_topics(topic_packs: Path | None = None, corpora: Path | None = None) -> list[str]:
    topic_packs = topic_packs or TOPIC_PACKS
    _ = corpora
    topics = []
    for path in sorted(topic_packs.glob("*.toml")):
        topic = path.stem
        if not topic.startswith("_"):
            topics.append(topic)
    return topics


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
                                  "synthesis_failed", "terminal_surface_repeat"})
_PREFLIGHT_BLOCK_STATUSES = frozenset({"corpus_missing_dry_run", "corpus_seed_empty",
                                        "preflight_insufficient_corpus", "preflight_thin_quant_corpus"})
_CORPUS_REPAIR_STATUSES = _PREFLIGHT_BLOCK_STATUSES | {"retracted_source_cited"}


def _surface_repeat_topics(ledger_dir: Path, *, now: dt.datetime | None = None) -> set[str]:
    """Topics where the SAME deterministic gate failed >= SURFACE_REPEAT_THRESHOLD
    times within the failure-cooldown window. Re-rendering from scratch cannot
    change a deterministic gate's outcome, so skip the topic until the failure
    class changes (plan F: don't write R3 for a repeated surface failure).
    D_no_action gates (e.g. a cited retracted source) count too — "no action"
    means re-rendering can't fix it, which is exactly when to stop retrying.

    Reads the CUMULATIVE per-(topic, gate) timestamp log in the blocker
    histogram — the daily ledger is rewritten each run, so it cannot hold a
    cross-run count. Windowed so a topic auto-recovers once its corpus is fixed.
    Universal — keyed on the gate code itself, not on any specific gate."""
    cutoff = (now or dt.datetime.now(dt.UTC)) - dt.timedelta(hours=RECENT_FAILURE_COOLDOWN_HOURS)
    repeats = _read_json(ledger_dir / BLOCKER_HISTOGRAM).get("repeats", {})
    out: set[str] = set()
    for key, stamps in repeats.items() if isinstance(repeats, dict) else []:
        topic, _, code = str(key).partition("\x1f")
        if (
            not topic
            or code in _NON_REPEAT_STATUSES
            or _failure_class(code).startswith("C_")
            or not isinstance(stamps, list)
        ):
            continue
        recent = sum(1 for s in stamps if (t := _parse_time(str(s))) and t >= cutoff)
        if recent >= SURFACE_REPEAT_THRESHOLD:
            out.add(topic)
    return out


def _recent_preflight_blocked_topics(ledger_dir: Path, *, now: dt.datetime | None = None) -> set[str]:
    cutoff = (now or dt.datetime.now(dt.UTC)) - dt.timedelta(hours=RECENT_FAILURE_COOLDOWN_HOURS)
    repeats = _read_json(ledger_dir / BLOCKER_HISTOGRAM).get("repeats", {})
    out: set[str] = set()
    for key, stamps in repeats.items() if isinstance(repeats, dict) else []:
        topic, _, code = str(key).partition("\x1f")
        if topic and code in _PREFLIGHT_BLOCK_STATUSES and isinstance(stamps, list):
            if any((t := _parse_time(str(s))) and t >= cutoff for s in stamps):
                out.add(topic)
    return out


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


def _recent_submitted_topics(topics: list[str], ledger_dir: Path, *, now: dt.datetime | None = None) -> set[str]:
    path = ledger_dir.parent / submit_bridge.LEDGER_DIR / "_submitted_fingerprints.json"
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        rows = []
    cutoff = (now or dt.datetime.now(dt.UTC)) - dt.timedelta(days=PUBLISHED_TOPIC_COOLDOWN_DAYS)
    topic_set = set(topics)
    out: set[str] = set()
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or str(row.get("topic") or "") not in topic_set:
            continue
        when = _parse_time(str(row.get("date") or row.get("submitted_at") or ""))
        if when and when >= cutoff:
            out.add(str(row["topic"]))
    return out


def _published_topics(topics: list[str], markers: set[str], ledger_dir: Path | None = None) -> set[str]:
    out = _recent_submitted_topics(topics, ledger_dir) if ledger_dir else set()
    title_markers = [m.removeprefix("title:") for m in markers if m.startswith("title:")]
    for topic in topics:
        display = submit_bridge._normalized_key(submit_bridge._display_topic(topic))
        if ledger_dir is None and display and any(display in marker for marker in title_markers):
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
    raw = str(row.get("reviewedAt") or row.get("reviewed_at") or "")
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


def _actionable_revisions(row: dict[str, Any]) -> list[str]:
    """Concrete required revisions on a review row. A revise with none (a
    publication-overlap flag, or "no revisions required") has nothing the
    writer can act on — re-rendering it just bounces at the same verdict."""
    raw = row.get("requiredRevisions")
    return [str(item).strip() for item in raw if str(item).strip()] if isinstance(raw, list) else []


def _remote_revision_requests(url: str | None = None) -> tuple[list[dict[str, Any]], str | None]:
    latest, err = _latest_reviews_by_title(url)
    if err:
        return [], err
    out: list[dict[str, Any]] = []
    for row in latest.values():
        required = _actionable_revisions(row)
        if str(row.get("decision") or "").lower() != "revise" or not required:
            continue  # only route revises that carry concrete, actionable required revisions
        out.append({
            "artifactId": row.get("artifactId"),
            "submissionId": row.get("submissionId"),
            "title": row.get("title"),
            "feedback": " ".join("; ".join(required).split())[:4000],
        })
    return out, None


def _handled_revision_ids(ledger_dir: Path) -> set[str]:
    """Revision keys (paper-title markers) that have hit the per-paper round
    cap. A paper may be re-processed up to MAX_REVISE_ROUNDS times across cycles
    (one row appended per round); once the count reaches the cap the paper is
    treated as permanently handled so it stops monopolising the cycle and the
    bot rotates to fresh topics. Counting is by title — Researka mints a new
    artifactId per submission, so artifactId counts never accumulate."""
    data = _read_json(ledger_dir / HANDLED_REVISIONS)
    rows = data.get("handled")
    if not isinstance(rows, list):
        return set()
    counts = Counter(
        submit_bridge._title_marker(str(row.get("title") or ""))
        for row in rows if isinstance(row, dict) and row.get("title")
    )
    return {key for key, n in counts.items() if n >= MAX_REVISE_ROUNDS}


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
) -> tuple[dict[str, Any] | None, str | None]:
    rows, error = (loader or _remote_revision_requests)()
    if error:
        return None, error
    handled = _handled_revision_ids(ledger_dir)
    submitted = runs_root / submit_bridge.LEDGER_DIR / "_submitted_fingerprints.json"
    raw_records = json.loads(submitted.read_text(encoding="utf-8")) if submitted.exists() else []
    records: list[Any] = raw_records if isinstance(raw_records, list) else []
    for request in rows:
        if _revision_key(request) in handled:
            continue
        title_marker = submit_bridge._title_marker(str(request.get("title") or ""))
        for record in records if isinstance(records, list) else []:
            if not isinstance(record, dict):
                continue
            run = runs_root / str(record.get("run") or "")
            paper = run / "full_paper.md"
            if not paper.exists():
                continue
            markers = {
                str(record.get("fingerprint") or ""),
                submit_bridge._title_marker(submit_bridge._paper_title(paper)),
            }
            if title_marker in markers:
                request["topic"] = record.get("topic") or submit_bridge._run_topic(run)
                request["source_run"] = run.name
                return request, None
    return None, None


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
        revision, error = _pending_remote_revision(runs_root, ledger_dir, loader=loader)
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
        return False
    return bool(str(data.get("target_journal", "")).strip())


def _publication_score(topic: str, ledger_dir: Path, runs_root: Path) -> int:
    total, l4plus = _topic_run_stats(topic, runs_root)
    pass_rate = (l4plus / total) if total else 0
    last = _parse_time(_attempted_at(topic, ledger_dir))
    freshness = 2 if last is None or dt.datetime.now(dt.UTC) - last > dt.timedelta(days=14) else 0
    return round(pass_rate * 5) + int(_publication_track_topic(topic)) * 3 + freshness - _recent_failed_attempts(topic, ledger_dir) * 2


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
    pool = [topic for topic in candidates if _publication_track_topic(topic)] or candidates
    return min(pool, key=lambda topic: (-_publication_score(topic, ledger_dir, runs_root), _attempted_at(topic, ledger_dir), topic))


def _topic_status_map(
    topics: list[str],
    *,
    terminal: set[str],
    surface_repeat: set[str],
    preflight_blocked: set[str],
    submitted: set[str],
) -> dict[str, str]:
    """Derived, read-only queue state per topic — the 'one queue ledger' view
    (plan H). Consolidates the exclusion signals already computed this cycle so
    the state that prevents looping is visible in one place; it is NOT a second
    authoritative store (no write-path to drift out of sync)."""
    status: dict[str, str] = {}
    for topic in sorted(topics):
        if topic in surface_repeat:
            status[topic] = "terminal_surface_repeat"
        elif topic in preflight_blocked:
            status[topic] = "preflight_blocked"
        elif topic in terminal:
            status[topic] = "terminal"
        elif topic in submitted:
            status[topic] = "submitted"
        else:
            status[topic] = "ready"
    return status


def _preflight(topic: str, runs_root: Path, ledger_dir: Path, *, current_quant_claims: int | None = None) -> dict[str, Any]:
    latest = _latest_topic_run(topic, runs_root)
    counts = _manifest_counts(latest)
    publication_track = _publication_track_topic(topic)
    reasons = []
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
        reasons = [r for r in reasons if ">" in r or r.startswith("recent_failed_attempts=")]
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
    return {
        "journal_surface_not_passed": "A_compiler_fixable",
        "final_verdict_not_aaa": "A_compiler_fixable",
        "pre_submit_not_passed": "A_compiler_fixable",
        "audit_not_all_green": "C_writer_fixable",
        "revision_coverage_unmet": "C_writer_fixable",
        "abstract_overclaim": "C_writer_fixable",
        "retracted_source_cited": "D_no_action",
        "synthesis_failed": "C_writer_fixable",
        "submission_rejected_by_researka": "C_writer_fixable",
        "submission_revise_requested": "C_writer_fixable",
        "strategy_evidence_insufficient": "B_corpus_fixable",
        "preflight_insufficient_corpus": "B_corpus_fixable",
        "corpus_missing_dry_run": "B_corpus_fixable",
        "corpus_seed_empty": "B_corpus_fixable",
        "corpus_seed_failed": "B_corpus_fixable",
        "missing": "C_writer_fixable",
        "duplicate_submission_fingerprint": "D_no_action",
        "duplicate_remote_publication": "D_no_action",
        "researka_revision_fingerprint": "D_no_action",
        "research_revision_fingerprint": "D_no_action",
        "superseded_topic_run": "D_no_action",
        "terminal_surface_repeat": "D_no_action",
    }.get(code, "unknown")


def _revision_asks(feedback: str) -> list[str]:
    """The enumerated reviewer asks recovered from the '; '-joined feedback."""
    return [a.strip() for a in feedback.split(";") if a.strip()]


def _unmet_revision_asks(out_dir: Path, feedback: str) -> list[str]:
    """Reviewer asks the rendered paper does NOT materially address, per the
    coverage judge. Fail-open (empty on any error). Monkeypatched in tests."""
    paper = out_dir / "full_paper.md"
    if not paper.is_file():
        return []
    import revision_coverage
    unmet = revision_coverage.unmet_asks(paper.read_text(encoding="utf-8"), _revision_asks(feedback))
    return [ask for ask in unmet if not _payload_revision_ask_satisfied(out_dir, ask)]


def _payload_revision_ask_satisfied(out_dir: Path, ask: str) -> bool:
    ask_lower = ask.lower()
    payload_section_ask = "key findings" in ask_lower or "evidence landscape" in ask_lower
    payload_clip_ask = "truncated" in ask_lower and "abstract" in ask_lower and "research question" in ask_lower
    if not (payload_section_ask or payload_clip_ask):
        return False
    try:
        payload = submit_bridge.build_payload(out_dir)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return False
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
        f"substantive change to satisfy EACH: {'; '.join(unmet)}. {feedback}"
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
    result = subprocess.run(cmd, cwd=ROOT, check=False, timeout=timeout or None, env=env)
    return int(result.returncode)


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


def _should_retry_same_topic(attempt: dict[str, Any]) -> bool:
    if int(attempt.get("submitted") or 0):
        return False
    if str(attempt.get("failure_class") or "").startswith(("B_", "D_")):
        return False
    return True


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


def _corpus_repair_limit() -> int:
    try:
        return max(0, int(os.environ.get("RESEARCH_AGENT_CORPUS_REPAIR_LIMIT", str(CORPUS_REPAIR_LIMIT))))
    except ValueError:
        return CORPUS_REPAIR_LIMIT


def _seed_topic(topic: str, *, timeout: int | None = None, force_extract: bool = False) -> dict[str, Any]:
    before = _quant_claim_count(topic)
    seed_limit = _auto_seed_limit()
    cmd = [
        sys.executable, "scripts/seed_topic_corpus.py", "--topic", topic,
        "--limit", str(seed_limit), "--max-per-source", str(seed_limit),
    ]
    if force_extract:
        cmd.append("--force-extract")
    try:
        result = subprocess.run(cmd, cwd=ROOT, check=False, timeout=timeout or None, capture_output=True, text=True)
    except (OSError, subprocess.TimeoutExpired) as exc:
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


def _repair_topic_corpus(topic: str, *, dry_run: bool, timeout: int | None = None) -> dict[str, Any]:
    before = _quant_claim_count(topic)
    if dry_run:
        return {"status": "corpus_repair_dry_run", "n_quant_claims": before}
    result = _seed_topic(topic, timeout=timeout, force_extract=True)
    return {
        **result,
        "status": "corpus_repaired" if result.get("status") in {"corpus_ready", "corpus_seeded"} else result.get("status"),
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
    max_attempts: int = 5,
    max_revise_attempts: int = 3,
    decision_poll_seconds: int = DECISION_POLL_SECONDS,
    decision_poll_interval_seconds: int = DECISION_POLL_INTERVAL_SECONDS,
    decision_sleep: Sleeper = time.sleep,
    cycle_budget_seconds: int = CYCLE_BUDGET_SECONDS,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    started_at = dt.datetime.now(dt.UTC).isoformat()
    started_mono = clock()
    mode = mode if mode in {"fresh", "revise", "mixed"} else "mixed"
    ledger_dir = runs_root / LEDGER_DIR
    ledger_path = ledger_dir / f"{date}.json"
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
        remote_revision: dict[str, Any] | None = None
        terminal_excluded: set[str] = set()
        if submit and topic is None and mode != "fresh" and (revision_loader is not None or submit_cycle is None):
            remote_revision, revision_error = _pending_remote_revision(runs_root, ledger_dir, loader=revision_loader)
            ledger["remote_revisions"] = {"checked": True, "matched": bool(remote_revision)}
            if revision_error:
                ledger["remote_revisions"]["error"] = revision_error
        if submit and topic is None and revision_loader is None:
            # Production only (live reviews poll): drop topics whose latest review
            # is terminal (reject, or a revise with no actionable revisions such as
            # a duplicate-overlap flag) so the bot stops re-synthesising them.
            terminal_excluded = _terminal_topics(runs_root)
            if terminal_excluded:
                ledger["terminal_excluded_topics"] = sorted(terminal_excluded)
        # Skip topics that keep failing the SAME deterministic gate — re-rendering
        # them only burns a slot (plan F). Excluded from fresh auto-selection
        # below, and pending revises for such topics are marked terminal in the
        # loop (a forced --topic is left untouched on purpose).
        surface_repeat = _surface_repeat_topics(ledger_dir)
        if surface_repeat:
            ledger["surface_repeat_excluded_topics"] = sorted(surface_repeat)
        preflight_blocked = set() if topic else _recent_preflight_blocked_topics(ledger_dir)
        if preflight_blocked:
            ledger["preflight_blocked_topics"] = sorted(preflight_blocked)
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
        if run_synthesis and mode != "revise" and topic is None:
            repairs: list[dict[str, Any]] = []
            repairable = _corpus_repair_topics(ledger_dir) - terminal_excluded - submitted_topics
            for repair_topic in sorted(repairable)[:_corpus_repair_limit()]:
                repair = _repair_topic_corpus(repair_topic, dry_run=synthesis_dry_run, timeout=timeout)
                repairs.append({"topic": repair_topic, **repair})
                if int(repair.get("n_quant_claims") or 0) >= PREFLIGHT_MIN_QUANT_CLAIMS:
                    preflight_blocked.discard(repair_topic)
                    surface_repeat.discard(repair_topic)
            if repairs:
                ledger["corpus_repairs"] = repairs
        ledger["topic_status"] = _topic_status_map(
            topics, terminal=terminal_excluded, surface_repeat=surface_repeat, preflight_blocked=preflight_blocked,
            submitted=submitted_topics,
        )
        attempted: set[str] = set()
        submitted_total = 0
        for _ in range(max(1, max_attempts if not topic else 1)):
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
            selected = (
                str(revision_source.get("topic") or "")
                if revision_source
                else topic or select_topic(topics, ledger_dir, runs_root=runs_root, remote_seen=remote_seen, exclude=attempted | terminal_excluded | surface_repeat | preflight_blocked | writer_gate_skip)
            )
            if not selected:
                ledger["status"] = "no_unpublished_topic_available"
                break
            stamp = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
            out_dir = runs_root / f"synthesis-{selected}-v06-DAILY-{stamp}"
            ledger.update({"topic": selected, "out_dir": out_dir.name, "attempted_topic": selected, "attempted_run": out_dir.name})
            if not run_synthesis:
                ledger["status"] = "dry_run_selected_topic"
                break
            # A pending revise whose topic keeps failing the SAME deterministic gate
            # cannot be fixed by re-rendering — mark it terminal so it stops
            # monopolising revise slots instead of re-synthesising every cycle.
            if revision_source and selected in surface_repeat:
                attempt: dict[str, Any] = {
                    "topic": selected,
                    "out_dir": out_dir.name,
                    "synthesis_return_code": None,
                    "submit_status": "terminal_surface_repeat",
                    "gate_status": "terminal_surface_repeat",
                    "failure_class": _failure_class("terminal_surface_repeat"),
                    "submitted": 0,
                }
                ledger["attempts"].append(attempt)
                ledger["status"] = "revise_terminal_surface_repeat"
                ledger["blocker_histogram"] = _record_blockers(ledger_dir, date, [attempt])
                _mark_revision_handled(ledger_dir, revision_source, status="terminal_surface_repeat")
                attempted.add(selected)
                remote_revision = None
                continue
            corpus = (ensure_corpus or _ensure_topic_corpus)(selected, dry_run=synthesis_dry_run, timeout=timeout)
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
                ledger["blocker_histogram"] = _record_blockers(ledger_dir, date, [attempt])
                attempted.add(selected)
                continue
            quant_preflight = _quant_claim_preflight(corpus)
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
                attempt = {
                    "topic": selected,
                    "out_dir": out_dir.name,
                    "synthesis_return_code": None,
                    "submit_status": "preflight_insufficient_corpus",
                    "failure_class": "B_corpus_fixable",
                    "submitted": 0,
                    "preflight": preflight,
                }
                ledger["attempts"].append(attempt)
                ledger["status"] = "preflight_skipped_no_submission"
                ledger["blocker_histogram"] = _record_blockers(ledger_dir, date, [attempt])
                attempted.add(selected)
                continue
            revision_feedback = str(revision_source.get("feedback") or "") if revision_source else ""
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
            numeric_review_type = _numeric_density_downshift(_latest_topic_run(selected, runs_root))
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
                revision_base_dir = runs_root / str(revision_source.get("source_run") or "") if revision_source else None
                if revise_attempt > 1:
                    revision_base_dir = out_dir
                    stamp = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
                    out_dir = runs_root / f"synthesis-{selected}-v06-DAILY-{stamp}-R{revise_attempt}"
                    ledger.update({"out_dir": out_dir.name, "attempted_run": out_dir.name})
                repair_reason = ""
                if revise_attempt > 1 and last_attempt and revision_base_dir:
                    repair_reason = _repair_reason_for_retry(revision_base_dir, last_attempt)
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
                    "timeout": timeout,
                    "revision_feedback": revision_feedback or None,
                }
                if review_type_override:
                    synthesis_kwargs["review_type_override"] = review_type_override
                return_code = 0 if existing_repair else _run_synthesis(selected, out_dir, **synthesis_kwargs)
                if revision_source and out_dir.exists():
                    _write_json(out_dir / "researka_revision_request.json", revision_source)
                # Coverage gate: a content revise must materially address every
                # enumerated reviewer ask before it may be submitted.
                unmet = _unmet_revision_asks(out_dir, revision_feedback) if (return_code == 0 and revision_feedback) else []
                # Retraction gate: never submit a paper that cites retracted science.
                retracted = _retracted_cited_sources(out_dir) if return_code == 0 else []
                # Claim-support gate: never submit an abstract whose claims the
                # paper's own evidence does not support / overstates.
                overclaims = _abstract_overclaims(out_dir) if return_code == 0 else []
                abstract_repaired = False
                if overclaims and _repair_abstract_overclaim_phrasing(out_dir, overclaims):
                    abstract_repaired = True
                    overclaims = _abstract_overclaims(out_dir)
                advisory_overclaims = list(overclaims)
                abstract_overclaim_advisory = bool(overclaims and _final_status_submission_ready(out_dir))
                if abstract_overclaim_advisory:
                    overclaims = []
                bridge: dict[str, Any] = {}
                if return_code == 0 and not unmet and not retracted and not overclaims:
                    # Submission stays single-threaded across lanes: the fresh and
                    # revise lanes run concurrently but share one blocking submit
                    # lock so they never race the fingerprint-dedupe / double-submit.
                    with _lock(ledger_dir, ".submit.lock", block=True):
                        if submit_cycle is None:
                            bridge = submit_bridge.run_cycle(
                                runs_root=runs_root,
                                date=date,
                                submit=submit,
                                remote_loader=(lambda: (remote_seen, None)) if submit else None,
                                candidate_run=out_dir,
                            )
                            if bridge.get("status") == "no_eligible_research_paper":
                                candidate_path, considered = submit_bridge.select_candidate(
                                    runs_root,
                                    runs_root / submit_bridge.LEDGER_DIR / "_submitted_fingerprints.json",
                                    remote_seen=remote_seen,
                                    candidate_run=out_dir,
                                )
                                if candidate_path is not None:
                                    first_bridge = bridge
                                    bridge = submit_bridge.run_cycle(
                                        runs_root=runs_root,
                                        date=date,
                                        submit=submit,
                                        remote_loader=(lambda: (remote_seen, None)) if submit else None,
                                        candidate_run=out_dir,
                                    )
                                    bridge["retry_after_no_eligible"] = {
                                        "first_status": first_bridge.get("status"),
                                        "first_considered": first_bridge.get("considered"),
                                        "eligibility_recheck": considered,
                                    }
                        else:
                            bridge = submit_cycle(
                                runs_root=runs_root,
                                date=date,
                                submit=submit,
                                remote_loader=(lambda: (remote_seen, None)) if submit else None,
                            )
                gate_status = (
                    "synthesis_failed" if return_code != 0
                    else "retracted_source_cited" if retracted
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
                }
                if unmet:
                    attempt["unmet_revision_asks"] = unmet
                    revision_feedback = _escalate_feedback(revision_feedback, unmet)
                if retracted:
                    attempt["retracted_cited_sources"] = retracted
                if overclaims:
                    attempt["abstract_overclaims"] = overclaims
                if abstract_repaired:
                    attempt["abstract_overclaim_repaired"] = True
                if abstract_overclaim_advisory:
                    attempt["abstract_overclaim_advisory"] = True
                    attempt["abstract_overclaim_advisory_claims"] = advisory_overclaims
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
                    ledger.update({"submitted_topic": submitted_topic or selected, "submitted_run": submitted_run or out_dir.name})
                ledger["attempts"].append(attempt)
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
                if return_code != 0:
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
                if revise_attempt >= max(1, max_revise_attempts) or not _should_retry_same_topic(attempt):
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
        _write_json(ledger_path, ledger)
        return ledger


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=dt.datetime.now(dt.UTC).date().isoformat())
    parser.add_argument("--runs-root", type=Path, default=RUNS)
    parser.add_argument("--topic")
    parser.add_argument("--run-synthesis", action="store_true")
    parser.add_argument("--synthesis-dry-run", action="store_true")
    parser.add_argument("--submit", action="store_true")
    parser.add_argument("--mode", choices=["fresh", "revise", "mixed"], default="mixed",
                        help="lane: fresh=new papers only, revise=process one pending revise only, mixed=interleave (default)")
    parser.add_argument("--timeout-sec", type=int, default=0)
    parser.add_argument("--max-attempts", type=int, default=5)
    parser.add_argument("--max-revise-attempts", type=int, default=3)
    parser.add_argument("--decision-poll-sec", type=int, default=DECISION_POLL_SECONDS)
    parser.add_argument("--decision-poll-interval-sec", type=int, default=DECISION_POLL_INTERVAL_SECONDS)
    parser.add_argument("--cycle-budget-sec", type=int, default=CYCLE_BUDGET_SECONDS)
    args = parser.parse_args(argv)
    ledger = run_cycle(
        runs_root=args.runs_root,
        date=args.date,
        run_synthesis=args.run_synthesis,
        synthesis_dry_run=args.synthesis_dry_run,
        submit=args.submit,
        mode=args.mode,
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
