"""Small shared JSON and timestamp helpers for publication lanes."""
from __future__ import annotations

import datetime as dt
import fcntl
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def update_json_list(
    path: Path,
    update: Callable[[list[dict[str, Any]]], None],
) -> None:
    """Atomically update a shared JSON-list ledger under an advisory lock."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f".{path.name}.lock")
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            loaded = []
        rows = [row for row in loaded if isinstance(row, dict)] if isinstance(loaded, list) else []
        update(rows)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        temporary.write_text(json.dumps(rows, indent=2, sort_keys=True), encoding="utf-8")
        temporary.replace(path)


def parse_time(value: str) -> dt.datetime | None:
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)
