"""Pure ledger reconciliation helpers shared by V3 publication lanes."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any


def _rows(value: object) -> list[dict[str, Any]]:
    return (
        [row for row in value if isinstance(row, dict)]
        if isinstance(value, list)
        else []
    )


def ledger_run_names(
    ledger: dict[str, Any],
    *,
    submitted_only: bool = True,
) -> list[str]:
    names = [
        value
        for key in ("submitted_run", "attempted_run", "out_dir")
        if isinstance(value := ledger.get(key), str) and value
    ]
    candidate = ledger.get("candidate")
    if isinstance(candidate, dict) and isinstance(candidate.get("run"), str):
        names.append(candidate["run"])
    for attempt in _rows(ledger.get("attempts")):
        if submitted_only and not int(attempt.get("submitted") or 0):
            continue
        names.extend(
            value
            for key in ("submitted_run", "out_dir")
            if isinstance(value := attempt.get(key), str) and value
        )
    for submission in _rows(ledger.get("submissions")):
        if submitted_only and not int(submission.get("submitted") or 0):
            continue
        candidate = submission.get("candidate")
        if isinstance(candidate, dict) and isinstance(candidate.get("run"), str):
            names.append(candidate["run"])
    return list(dict.fromkeys(names))


def ledger_submission_markers(
    ledger: dict[str, Any],
    *,
    submission_ids_from_response: Callable[[object], list[str]],
    submission_marker: Callable[[str], str],
) -> set[str]:
    markers: set[str] = set()
    response = ledger.get("submission")
    response = response.get("response") if isinstance(response, dict) else {}
    if isinstance(response, dict):
        markers.update(
            submission_marker(value)
            for value in submission_ids_from_response(response)
        )
    for key in ("attempts", "submissions"):
        for row in _rows(ledger.get(key)):
            values = row.get("submission_markers")
            if isinstance(values, list):
                markers.update(
                    value
                    for value in values
                    if isinstance(value, str) and value.startswith("submission:")
                )
    return markers


def reconciled_publication_markers(ledger: dict[str, Any]) -> set[str]:
    reconciliation = ledger.get("publication_reconciliation")
    values = (
        reconciliation.get("matched")
        if isinstance(reconciliation, dict)
        else None
    )
    return (
        {value for value in values if isinstance(value, str) and value}
        if isinstance(values, list)
        else set()
    )


def row_submission_markers(row: dict[str, Any]) -> set[str]:
    values = row.get("submission_markers")
    return (
        {
            value
            for value in values
            if isinstance(value, str) and value.startswith("submission:")
        }
        if isinstance(values, list)
        else set()
    )


def sync_reconciled_children(
    ledger: dict[str, Any],
    matched_runs: set[str],
    matched: set[str],
) -> bool:
    changed = False
    for key in ("attempts", "submissions"):
        for row in _rows(ledger.get(key)):
            candidate = row.get("candidate")
            run = (
                candidate.get("run")
                if isinstance(candidate, dict)
                else row.get("submitted_run") or row.get("out_dir")
            )
            is_match = bool(
                isinstance(run, str) and run in matched_runs
                or row_submission_markers(row) & matched
            )
            if is_match:
                for field in ("submitted", "published"):
                    if int(row.get(field) or 0) != 1:
                        row[field] = 1
                        changed = True
            elif int(row.get("published") or 0):
                row["published"] = 0
                changed = True
    return changed


def clear_unattributed_publication_reconciliation(
    ledger: dict[str, Any],
) -> bool:
    changed = False
    if int(ledger.get("published") or 0):
        ledger["published"] = 0
        changed = True
    if (
        int(ledger.get("submitted") or 0)
        and str(ledger.get("status") or "") == "published"
    ):
        ledger["status"] = "submitted_to_researka"
        changed = True
    if ledger.pop("publication_reconciliation", None) is not None:
        changed = True
    for key in ("attempts", "submissions"):
        for row in _rows(ledger.get(key)):
            if int(row.get("published") or 0):
                row["published"] = 0
                changed = True
    return changed


def child_submission_counts(ledger: dict[str, Any]) -> tuple[int, int]:
    rows = _rows(ledger.get("submissions"))
    return (
        sum(bool(int(row.get("submitted") or 0)) for row in rows),
        sum(bool(int(row.get("published") or 0)) for row in rows),
    )
