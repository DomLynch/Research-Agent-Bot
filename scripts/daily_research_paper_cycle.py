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
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import daily_research_paper_submit as submit_bridge

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "runs"
TOPIC_PACKS = ROOT / "topic_packs"
CORPORA = ROOT / "docs" / "quality-reference"
LEDGER_DIR = "_daily_research_paper_cycle_ledger"
BLOCKER_HISTOGRAM = "_blocker_histogram.json"
HANDLED_REVISIONS = "_handled_revision_requests.json"
PREFLIGHT_MIN_RECEIPTS = 15
PREFLIGHT_MIN_TENSIONS = 3
PREFLIGHT_MIN_PRIMARY_TIER = 1
PREFLIGHT_MAX_RECEIPTS = 500
PREFLIGHT_MAX_TENSIONS = 50_000
PREFLIGHT_MAX_OUTCOMES = 12
RECENT_FAILURE_COOLDOWN_HOURS = 24
HISTOGRAM_ISSUE_THRESHOLD = 5
AUTO_SEED_LIMIT = 120
DECISION_POLL_SECONDS = 900
DECISION_POLL_INTERVAL_SECONDS = 30
PUBLISHED_TOPIC_COOLDOWN_DAYS = 30

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


def _remote_revision_requests(url: str | None = None) -> tuple[list[dict[str, Any]], str | None]:
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
        return [], f"{type(exc).__name__}: {exc}"
    out: list[dict[str, Any]] = []
    for row in _review_rows(payload):
        if str(row.get("decision") or "").lower() != "revise":
            continue
        if str(row.get("artifactType") or row.get("artifact_type") or "") != "research_paper":
            continue
        if agent_ids and str(row.get("agentId") or row.get("agent_id") or "") not in agent_ids:
            continue
        raw_required = row.get("requiredRevisions")
        required: list[Any] = raw_required if isinstance(raw_required, list) else []
        feedback = "; ".join(str(item) for item in required if str(item).strip()) or str(row.get("reviewSummary") or "")
        out.append({
            "artifactId": row.get("artifactId"),
            "submissionId": row.get("submissionId"),
            "title": row.get("title"),
            "feedback": " ".join(feedback.split())[:4000],
        })
    return out, None


def _handled_revision_ids(ledger_dir: Path) -> set[str]:
    data = _read_json(ledger_dir / HANDLED_REVISIONS)
    rows = data.get("handled")
    return {str(row.get("key")) for row in rows if isinstance(row, dict) and row.get("key")} if isinstance(rows, list) else set()


def _revision_key(row: dict[str, Any]) -> str:
    return str(row.get("artifactId") or row.get("submissionId") or submit_bridge._title_marker(str(row.get("title") or "")))


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


def _preflight(topic: str, runs_root: Path, ledger_dir: Path) -> dict[str, Any]:
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
    return {
        "passed": not reasons,
        "publication_track": publication_track,
        "recent_failed_attempts": recent_failures,
        "reasons": reasons,
        "latest_run": latest.name if latest else None,
        **counts,
    }


def _failure_class(status: str) -> str:
    code = status.split(":", 1)[0]
    return {
        "journal_surface_not_passed": "A_compiler_fixable",
        "final_verdict_not_aaa": "A_compiler_fixable",
        "pre_submit_not_passed": "A_compiler_fixable",
        "audit_not_all_green": "C_writer_fixable",
        "synthesis_failed": "C_writer_fixable",
        "submission_rejected_by_researka": "C_writer_fixable",
        "submission_revise_requested": "C_writer_fixable",
        "preflight_insufficient_corpus": "B_corpus_fixable",
        "corpus_missing_dry_run": "B_corpus_fixable",
        "corpus_seed_empty": "B_corpus_fixable",
        "corpus_seed_failed": "B_corpus_fixable",
        "missing": "C_writer_fixable",
        "duplicate_submission_fingerprint": "D_no_action",
        "duplicate_remote_publication": "D_no_action",
        "researka_revision_fingerprint": "D_no_action",
        "superseded_topic_run": "D_no_action",
    }.get(code, "unknown")


def _record_blockers(ledger_dir: Path, date: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    path = ledger_dir / BLOCKER_HISTOGRAM
    data = _read_json(path)
    blockers = data.setdefault("blockers", {})
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
        if int(item["count"]) >= HISTOGRAM_ISSUE_THRESHOLD and item.get("class") != "D_no_action":
            item["github_issue_candidate"] = True
            if item.get("class") == "A_compiler_fixable":
                item["auto_fix_candidate"] = True
            issue_candidates.append(code)
    data["updated_at"] = dt.datetime.now(dt.UTC).isoformat()
    _write_json(path, data)
    return {"path": path.name, "issue_candidates": sorted(set(issue_candidates))}


@contextmanager
def _lock(ledger_dir: Path) -> Iterator[bool]:
    ledger_dir.mkdir(parents=True, exist_ok=True)
    with (ledger_dir / ".lock").open("w", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
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
        if revision_source or revision_feedback:
            payload = dict(revision_source or {})
            payload.setdefault("source_run", source_dir.name)
            payload["feedback"] = (revision_feedback or "")[:4000]
            _write_json(out_dir / "researka_revision_request.json", payload)
        else:
            _write_json(out_dir / "internal_repair_request.json", {"source_run": source_dir.name, "reason": repair_reason})
        from agent.journal_finalizer import finalize_run
        finalize_run(out_dir)
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


def _auto_seed_limit() -> int:
    try:
        return max(1, int(os.environ.get("RESEARCH_AGENT_AUTO_SEED_LIMIT", str(AUTO_SEED_LIMIT))))
    except ValueError:
        return AUTO_SEED_LIMIT


def _ensure_topic_corpus(topic: str, *, dry_run: bool, timeout: int | None = None) -> dict[str, Any]:
    before = _quant_claim_count(topic)
    if before:
        return {"status": "corpus_ready", "n_quant_claims": before}
    if dry_run:
        return {"status": "corpus_missing_dry_run", "n_quant_claims": 0}
    seed_limit = _auto_seed_limit()
    cmd = [
        sys.executable, "scripts/seed_topic_corpus.py", "--topic", topic,
        "--limit", str(seed_limit), "--max-per-source", str(seed_limit),
    ]
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


def run_cycle(
    *,
    runs_root: Path = RUNS,
    date: str,
    run_synthesis: bool = False,
    synthesis_dry_run: bool = False,
    submit: bool = False,
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
) -> dict[str, Any]:
    started_at = dt.datetime.now(dt.UTC).isoformat()
    ledger_dir = runs_root / LEDGER_DIR
    ledger_path = ledger_dir / f"{date}.json"
    ledger: dict[str, Any] = {
        "date": date,
        "started_at": started_at,
        "run_synthesis": run_synthesis,
        "synthesis_dry_run": synthesis_dry_run,
        "submit": submit,
        "submitted": 0,
        "published": 0,
        "status": "started",
        "attempts": [],
    }
    with _lock(ledger_dir) as locked:
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
        if submit and topic is None and (revision_loader is not None or submit_cycle is None):
            remote_revision, revision_error = _pending_remote_revision(runs_root, ledger_dir, loader=revision_loader)
            ledger["remote_revisions"] = {"checked": True, "matched": bool(remote_revision)}
            if revision_error:
                ledger["remote_revisions"]["error"] = revision_error
        attempted: set[str] = set()
        for _ in range(max(1, max_attempts if not topic else 1)):
            revision_source = remote_revision if remote_revision and not attempted else None
            selected = (
                str(revision_source.get("topic") or "")
                if revision_source
                else topic or select_topic(topics, ledger_dir, runs_root=runs_root, remote_seen=remote_seen, exclude=attempted)
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
            preflight = _preflight(selected, runs_root, ledger_dir)
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
            if revision_source:
                ledger["revision_source"] = {
                    key: revision_source.get(key)
                    for key in ("artifactId", "submissionId", "source_run", "title")
                    if revision_source.get(key)
                }
            review_type_override = _numeric_density_downshift(_latest_topic_run(selected, runs_root))
            if review_type_override:
                ledger["review_type_override"] = {"topic": selected, "value": review_type_override, "reason": "Q9_numeric_density"}
            last_attempt: dict[str, Any] | None = None
            for revise_attempt in range(1, max(1, max_revise_attempts) + 1):
                revision_base_dir = runs_root / str(revision_source.get("source_run") or "") if revision_source else None
                if revise_attempt > 1:
                    revision_base_dir = out_dir
                    stamp = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
                    out_dir = runs_root / f"synthesis-{selected}-v06-DAILY-{stamp}-R{revise_attempt}"
                    ledger.update({"out_dir": out_dir.name, "attempted_run": out_dir.name})
                repair_reason = ""
                if revise_attempt > 1 and last_attempt and str(last_attempt.get("failure_class") or "").startswith("A_"):
                    repair_reason = str(last_attempt.get("gate_status") or last_attempt.get("submit_status") or "")
                feedback_applied = bool(revision_feedback)
                repair_attempted = bool(revision_base_dir and (revision_feedback or repair_reason))
                existing_repair = False
                repair_error = ""
                if revision_base_dir:
                    existing_repair, repair_error = _repair_existing_run(
                        revision_base_dir,
                        out_dir,
                        revision_source=revision_source,
                        revision_feedback=revision_feedback or None,
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
                bridge: dict[str, Any] = {}
                if return_code == 0:
                    bridge = (submit_cycle or submit_bridge.run_cycle)(
                        runs_root=runs_root,
                        date=date,
                        submit=submit,
                        remote_loader=(lambda: (remote_seen, None)) if submit else None,
                    )
                gate_status = "synthesis_failed" if return_code != 0 else _current_gate_status(bridge, out_dir.name)
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
                if return_code != 0:
                    ledger["status"] = "synthesis_failed"
                elif bridge.get("status") == "submitted_to_researka":
                    ledger["status"] = "submitted_to_researka"
                    if (
                        submit
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
            if ledger["status"] == "submitted_to_researka":
                if revision_source:
                    _mark_revision_handled(ledger_dir, revision_source, status="submitted_to_researka")
                break
            attempted.add(selected)
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
    parser.add_argument("--timeout-sec", type=int, default=0)
    parser.add_argument("--max-attempts", type=int, default=5)
    parser.add_argument("--max-revise-attempts", type=int, default=3)
    parser.add_argument("--decision-poll-sec", type=int, default=DECISION_POLL_SECONDS)
    parser.add_argument("--decision-poll-interval-sec", type=int, default=DECISION_POLL_INTERVAL_SECONDS)
    args = parser.parse_args(argv)
    ledger = run_cycle(
        runs_root=args.runs_root,
        date=args.date,
        run_synthesis=args.run_synthesis,
        synthesis_dry_run=args.synthesis_dry_run,
        submit=args.submit,
        topic=args.topic,
        timeout=args.timeout_sec or None,
        max_attempts=args.max_attempts,
        max_revise_attempts=args.max_revise_attempts,
        decision_poll_seconds=args.decision_poll_sec,
        decision_poll_interval_seconds=args.decision_poll_interval_sec,
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
