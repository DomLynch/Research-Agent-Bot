"""Atomic JSON state and timestamp helpers for publication lanes."""
from __future__ import annotations

import datetime as dt
import fcntl
import json
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Generic, TypeVar

T = TypeVar("T")


class JsonStateStatus(StrEnum):
    MISSING = "missing"
    CORRUPT = "corrupt"
    VALID = "valid"


@dataclass(frozen=True, slots=True)
class JsonStateRead(Generic[T]):
    status: JsonStateStatus
    value: T | None = None
    error: str = ""


class CorruptJsonState(RuntimeError):
    pass


class AtomicJsonState(Generic[T]):
    def __init__(self, path: Path, expected_type: type[T]) -> None:
        self.path = path
        self.expected_type = expected_type
        self.lock_path = path.with_name(f".{path.name}.lock")

    def _read_unlocked(self) -> JsonStateRead[T]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return JsonStateRead(JsonStateStatus.MISSING)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            return JsonStateRead(
                JsonStateStatus.CORRUPT,
                error=f"{type(exc).__name__}: {exc}",
            )
        if not isinstance(value, self.expected_type):
            return JsonStateRead(
                JsonStateStatus.CORRUPT,
                error=f"expected {self.expected_type.__name__} root",
            )
        return JsonStateRead(JsonStateStatus.VALID, value)

    def read(self) -> JsonStateRead[T]:
        if not self.path.parent.exists():
            return JsonStateRead(JsonStateStatus.MISSING)
        try:
            with self.lock_path.open("a+", encoding="utf-8") as lock:
                fcntl.flock(lock, fcntl.LOCK_SH)
                return self._read_unlocked()
        except FileNotFoundError:
            return JsonStateRead(JsonStateStatus.MISSING)
        except OSError as exc:
            return JsonStateRead(
                JsonStateStatus.CORRUPT,
                error=f"{type(exc).__name__}: {exc}",
            )

    def _write_unlocked(self, value: T) -> None:
        descriptor, name = tempfile.mkstemp(
            dir=self.path.parent,
            prefix=f".{self.path.name}.",
            suffix=".tmp",
        )
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(value, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            directory = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            temporary.unlink(missing_ok=True)

    def write(self, value: T) -> None:
        if not isinstance(value, self.expected_type):
            raise TypeError(f"expected {self.expected_type.__name__} state")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            current = self._read_unlocked()
            if current.status is JsonStateStatus.CORRUPT:
                raise CorruptJsonState(f"{self.path}: {current.error}")
            self._write_unlocked(value)

    def update(
        self,
        mutate: Callable[[T], None],
        *,
        missing_factory: Callable[[], T],
    ) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            current = self._read_unlocked()
            if current.status is JsonStateStatus.CORRUPT:
                raise CorruptJsonState(f"{self.path}: {current.error}")
            value = current.value if current.status is JsonStateStatus.VALID else missing_factory()
            if not isinstance(value, self.expected_type):
                raise TypeError(f"expected {self.expected_type.__name__} state")
            mutate(value)
            self._write_unlocked(value)


def read_json(path: Path) -> dict[str, Any]:
    state = AtomicJsonState[dict[str, Any]](path, dict).read()
    if state.status is JsonStateStatus.CORRUPT:
        raise CorruptJsonState(f"{path}: {state.error}")
    if state.status is JsonStateStatus.VALID:
        assert state.value is not None
        return state.value
    return {}


def write_json(path: Path, payload: Any) -> None:
    if isinstance(payload, dict) and {"target_ready", "thresholds", "ready"} <= payload.keys():
        rows = payload.get("ready")
        fields = (
            "candidate_id", "code_sha", "policy_hash", "corpus_hash",
            "receipt_set_hash", "review_type",
        )
        if not isinstance(rows, list) or any(
            not isinstance(row, dict)
            or row.get("state") != "receipt_ready"
            or not all(str(row.get(field) or "").strip() for field in fields)
            for row in rows
        ):
            raise ValueError("candidate buffer contains an unbound prepared row")
    AtomicJsonState[Any](path, object).write(payload)


def update_json_list(
    path: Path,
    update: Callable[[list[dict[str, Any]]], None],
) -> None:
    AtomicJsonState[list[dict[str, Any]]](path, list).update(
        update,
        missing_factory=list,
    )


def parse_time(value: str) -> dt.datetime | None:
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)
