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
import subprocess
import sys
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

RemoteLoader = Callable[[], tuple[set[str], str | None]]
SubmitCycle = Callable[..., dict[str, Any]]


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def discover_topics(topic_packs: Path = TOPIC_PACKS, corpora: Path = CORPORA) -> list[str]:
    topics = []
    for path in sorted(topic_packs.glob("*.toml")):
        topic = path.stem
        if not topic.startswith("_") and (corpora / topic).is_dir():
            topics.append(topic)
    return topics


def _attempted_at(topic: str, ledger_dir: Path) -> str:
    latest = ""
    for path in ledger_dir.glob("*.json"):
        row = _read_json(path)
        if row.get("topic") == topic and str(row.get("started_at", "")) > latest:
            latest = str(row["started_at"])
    return latest


def _published_topics(topics: list[str], markers: set[str]) -> set[str]:
    title_markers = [m.removeprefix("title:") for m in markers if m.startswith("title:")]
    out = set()
    for topic in topics:
        display = submit_bridge._normalized_key(submit_bridge._display_topic(topic))
        if display and any(display in marker for marker in title_markers):
            out.add(topic)
    return out


def select_topic(topics: list[str], ledger_dir: Path, *, remote_seen: set[str] | None = None) -> str | None:
    blocked = _published_topics(topics, remote_seen or set())
    candidates = [topic for topic in topics if topic not in blocked]
    if not candidates:
        return None
    return min(candidates, key=lambda topic: (_attempted_at(topic, ledger_dir), topic))


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


def _run_synthesis(topic: str, out_dir: Path, *, dry_run: bool, timeout: int | None = None) -> int:
    cmd = [sys.executable, "scripts/run_v06_synthesis.py", "--topic", topic, "--out-dir", str(out_dir)]
    if dry_run:
        cmd.append("--dry-run")
    result = subprocess.run(cmd, cwd=ROOT, check=False, timeout=timeout or None)
    return int(result.returncode)


def run_cycle(
    *,
    runs_root: Path = RUNS,
    date: str,
    run_synthesis: bool = False,
    synthesis_dry_run: bool = False,
    submit: bool = False,
    topic: str | None = None,
    remote_loader: RemoteLoader | None = None,
    submit_cycle: SubmitCycle | None = None,
    timeout: int | None = None,
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
        remote_seen: set[str] = set()
        if submit:
            remote_seen, remote_error = (remote_loader or submit_bridge._remote_published_fingerprints)()
            ledger["remote_dedupe"] = {"checked": True, "known_fingerprints": len(remote_seen)}
            if remote_error:
                ledger.update({"status": "remote_dedupe_failed", "reason": remote_error})
                _write_json(ledger_path, ledger)
                return ledger
        selected = topic or select_topic(topics, ledger_dir, remote_seen=remote_seen)
        if not selected:
            ledger["status"] = "no_unpublished_topic_with_corpus"
            _write_json(ledger_path, ledger)
            return ledger
        stamp = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
        out_dir = runs_root / f"synthesis-{selected}-v06-DAILY-{stamp}"
        ledger.update({"topic": selected, "out_dir": out_dir.name})
        if not run_synthesis:
            ledger["status"] = "dry_run_selected_topic"
            _write_json(ledger_path, ledger)
            return ledger
        return_code = _run_synthesis(selected, out_dir, dry_run=synthesis_dry_run, timeout=timeout)
        ledger["synthesis_return_code"] = return_code
        if return_code != 0:
            ledger["status"] = "synthesis_failed"
            _write_json(ledger_path, ledger)
            return ledger
        bridge = (submit_cycle or submit_bridge.run_cycle)(
            runs_root=runs_root,
            date=date,
            submit=submit,
            remote_loader=(lambda: (remote_seen, None)) if submit else None,
        )
        ledger["submit_bridge"] = bridge
        ledger["submitted"] = int(bridge.get("submitted") or 0)
        if bridge.get("status") == "submitted_to_researka":
            ledger["status"] = "submitted_to_researka"
        else:
            ledger["status"] = "synthesis_completed_no_submission"
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
    args = parser.parse_args(argv)
    ledger = run_cycle(
        runs_root=args.runs_root,
        date=args.date,
        run_synthesis=args.run_synthesis,
        synthesis_dry_run=args.synthesis_dry_run,
        submit=args.submit,
        topic=args.topic,
        timeout=args.timeout_sec or None,
    )
    print(
        f"[daily-v3-cycle] status={ledger['status']} topic={ledger.get('topic', '-')} "
        f"submitted={ledger['submitted']} published={ledger['published']}"
    )
    return 0 if ledger["status"] not in {"synthesis_failed", "remote_dedupe_failed"} else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
