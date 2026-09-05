"""Pure ledger reconciliation helpers shared by V3 publication lanes."""
from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
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
    *, initial: bool = False, submitted_runs: set[str] | None = None,
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
            if initial and key == "attempts":
                run = str(row.get("submitted_run") or row.get("out_dir") or "")
                is_match = not run or run in matched_runs or (not matched_runs and run in (submitted_runs or set()))
            if is_match:
                for field in ("submitted", "published"):
                    if int(row.get(field) or 0) != 1:
                        row[field] = 1
                        changed = True
            elif not initial and int(row.get("published") or 0):
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


def submission_count(records: Sequence[dict[str, Any]], date: str) -> int:
    return len({value for row in records if row.get("date") == date
                if isinstance(value := row.get("run") or row.get("fingerprint"), str) and value})


def submission_day_summary(ledger: dict[str, Any], durable_submitted: int) -> dict[str, int]:
    previous = ledger.get("day_summary")
    previous = previous if isinstance(previous, dict) else {}
    return {
        "submitted": max(durable_submitted, int(ledger.get("submitted") or 0), int(previous.get("submitted") or 0)),
        "published": max(int(ledger.get("published") or 0), int(previous.get("published") or 0)),
    }


@dataclass
class PublicationState:
    """One legacy-ledger snapshot; indexes are projections, never a second store."""

    ledgers: list[dict[str, Any]]
    bridge_ledgers: list[dict[str, Any]]
    records: list[dict[str, Any]]
    paper_markers: dict[str, set[str]]
    submission_markers: Callable[[dict[str, Any]], set[str]]
    identity_keys: Sequence[str]
    bridge_markers: dict[str, set[str]] = field(init=False, default_factory=dict)
    title_counts: Counter[str] = field(init=False, default_factory=Counter)

    def __post_init__(self) -> None:
        submitted = {name for ledger in self.ledgers if int(ledger.get("submitted") or 0)
                     for name in ledger_run_names(ledger)}
        for ledger in self.bridge_ledgers:
            if isinstance(ledger.get("submissions"), list):
                entries = [(row, ledger_run_names({"candidate": row.get("candidate")}))
                           for row in _rows(ledger["submissions"])]
            else:
                entries = [(ledger, ledger_run_names(ledger))]
            for row, names in entries:
                markers = self.submission_markers(row)
                for name in names:
                    self.bridge_markers.setdefault(name, set()).update(markers)
        for row in self.records:
            raw_name = row.get("run")
            if not isinstance(raw_name, str) or not raw_name:
                continue
            submitted.add(raw_name)
            markers = self.bridge_markers.setdefault(raw_name, set())
            if isinstance(value := row.get("submission_id"), str) and value:
                markers.add(f"submission:{value.strip()}")
            markers.update(value if value.startswith("sha256:") else f"sha256:{value}"
                           for key in ("fingerprint", "paper_sha256", *self.identity_keys)
                           if isinstance(value := row.get(key), str) and value)
        self.title_counts.update(marker for name in submitted for marker in self.paper_markers.get(name, ())
                                 if marker.startswith("title:"))

    def markers_for(self, names: set[str], *, papers: bool = False) -> set[str]:
        return {marker for name in names for marker in
                (self.paper_markers if papers else self.bridge_markers).get(name, ())}

    def matched_runs(self, ledger: dict[str, Any], matched: set[str]) -> set[str]:
        names = set(ledger_run_names(ledger, submitted_only=False))
        found = {name for name in names if matched & (
            self.bridge_markers.get(name, set()) | self.paper_markers.get(name, set()))}
        for key in ("attempts", "submissions"):
            for row in _rows(ledger.get(key)):
                if row_submission_markers(row) & matched:
                    candidate = row.get("candidate")
                    name = (candidate.get("run") if isinstance(candidate, dict) else None) if key == "submissions" else row.get("submitted_run") or row.get("out_dir")
                    if isinstance(name, str) and name:
                        found.add(name)
        return found

    def reconcile(
        self, ledger: dict[str, Any], remote: set[str],
        receipts: dict[str, dict[str, Any]], *, now: str,
    ) -> bool:
        before = deepcopy(ledger)
        existing = bool(int(ledger.get("published") or 0))
        matches = reconciled_publication_markers(ledger)
        all_names = set(ledger_run_names(ledger, submitted_only=False))
        attributed = self.submission_markers(ledger) | self.markers_for(all_names) | self.markers_for(all_names, papers=True)
        if existing and matches and not matches & attributed and any(m.startswith("submission:") for m in matches):
            clear_unattributed_publication_reconciliation(ledger)
            existing = False
        submitted = set(ledger_run_names(ledger))
        matched_runs: set[str] = set()
        if not existing:
            matches = set()
            if int(ledger.get("submitted") or 0):
                exact = self.submission_markers(ledger) or self.markers_for(submitted)
                matches = exact & remote
                if exact and not matches and any(m.startswith("submission:") for m in remote):
                    return ledger != before
                if not matches:
                    for name in submitted:
                        run_matches = {marker for marker in self.paper_markers.get(name, set()) & remote
                                       if self.title_counts.get(marker, 0) <= 1}
                        if run_matches:
                            matched_runs.add(name)
                            matches.update(run_matches)
            else:
                for name in all_names:
                    if run_matches := self.bridge_markers.get(name, set()) & remote:
                        matched_runs.add(name)
                        matches.update(run_matches)
            if not matches:
                return ledger != before
            ledger["publication_reconciliation"] = {
                "source": "remote_publications", "matched": sorted(matches)[:5], "reconciled_at": now,
            }
        if matches:
            sync_reconciled_children(ledger, matched_runs or self.matched_runs(ledger, matches), matches,
                                     initial=not existing, submitted_runs=submitted)
            receipt = next((receipts[marker] for marker in sorted(matches) if marker in receipts), None)
            if receipt:
                reconciliation = ledger["publication_reconciliation"]
                ledger.update({**receipt, "reconciled": True,
                               "reconciled_at": str(reconciliation.get("reconciled_at") or now)})
                reconciliation.update(receipt)
        ledger["status"] = "published"
        ledger.pop("no_submission_reason", None)
        submitted_count, published_count = child_submission_counts(ledger)
        for key, count in (("submitted", submitted_count), ("published", published_count)):
            if not existing or count > int(ledger.get(key) or 0):
                ledger[key] = max(int(ledger.get(key) or 0), count, 0 if existing else 1)
        return ledger != before
