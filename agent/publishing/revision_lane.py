"""Pure reviewer-request classification used by the revision lane."""
from __future__ import annotations

import re
import datetime as dt
from collections import Counter
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from typing import Any

from agent.publishing.io import parse_time
from agent.revision_contract import ask_fingerprint

V3_AGENT_IDS = frozenset({"agent-v3-full-paper", "agent-v3-full-paper-live"})


def revision_identity(row: dict[str, Any]) -> tuple[str, str]:
    return (str(row.get("submissionId") or row.get("submission_id") or "").strip(),
            str(row.get("artifactId") or row.get("artifact_id") or "").strip())


def revision_identity_applies(row: dict[str, Any], submission_id: str, artifact_id: str) -> bool:
    if not (submission_id or artifact_id):
        return True
    row_submission, row_artifact = revision_identity(row)
    comparable = [(left, right) for left, right in zip((row_submission, row_artifact), (submission_id, artifact_id)) if left and right]
    return all(left == right for left, right in comparable) if comparable else not submission_id and not (row_submission or row_artifact)


def revision_request_fingerprint(row: dict[str, Any]) -> str:
    return ask_fingerprint([*revision_identity(row), str(row.get("reviewedAt") or row.get("reviewed_at") or ""),
                            str(row.get("failure_category") or row.get("failureCategory") or ""), *sorted(required_revision_items(row))])


@dataclass(frozen=True)
class HandledReview:
    row: dict[str, Any]
    key: str
    status: str
    time: dt.datetime | None
    fingerprint: str
    current_epoch: bool


class RevisionHistory:
    """Normalize handled rows once, with separate cap, reopen and retention queries."""

    def __init__(
        self, rows: object, *, key: Callable[[dict[str, Any]], str],
        title_markers: Callable[[str], set[str]], title_marker: Callable[[str], str],
        parse_review_time: Callable[[str], dt.datetime | None],
        terminal: Collection[str], retryable: Collection[str], epoch: str, max_rounds: int,
    ) -> None:
        self.key, self.title_markers, self.title_marker = key, title_markers, title_marker
        self.parse_review_time, self.terminal, self.max_rounds = parse_review_time, set(terminal), max_rounds
        self.rows = [HandledReview(row, key(row), str(row.get("status") or ""),
                                  parse_time(str(row.get("handled_at") or "")), str(row.get("request_fingerprint") or ""),
                                  str(row.get("status") or "") not in retryable or str(row.get("repair_epoch") or "") == epoch)
                     for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []

    def _applies(self, row: HandledReview, request: dict[str, Any], *, cap: bool) -> bool:
        fingerprint = str(request.get("request_fingerprint") or "")
        if fingerprint and row.fingerprint:
            if row.fingerprint != fingerprint:
                return False
            if cap:
                return True
        if not (fingerprint and row.fingerprint) and (cap or fingerprint and row.status not in self.terminal) and not revision_identity_applies(row.row, *revision_identity(request)):
            return False
        reviewed = self.parse_review_time(str(request.get("reviewedAt") or request.get("reviewed_at") or ""))
        return not reviewed or (bool(row.time and row.time >= reviewed) if cap else not row.time or row.time >= reviewed)

    def handled(self, active: Sequence[dict[str, Any]] = ()) -> set[str]:
        requests = {self.key(row): {**row, "request_fingerprint": revision_request_fingerprint(row)} for row in active}
        counts: Counter[str] = Counter()
        titles: dict[str, str] = {}
        handled: set[str] = set()
        for row in self.rows:
            request = requests.get(row.key)
            active_submission = revision_identity(request or {})[0]
            superseded = row.status == "submitted_to_researka" and active_submission and revision_identity(row.row)[0] in {"", active_submission}
            if title := str(row.row.get("title") or ""):
                markers = self.title_markers(title)
                titles[title] = min(markers, key=lambda marker: (len(marker), marker)) if markers else ""
                if request is None or self._applies(row, request, cap=True):
                    if not superseded and row.current_epoch:
                        counts[titles[title]] += 1
                    if row.status in self.terminal:
                        handled.add(self.title_marker(title))
            if row.status == "submitted_to_researka" and not superseded:
                reviewed = self.parse_review_time(str((request or {}).get("reviewedAt") or (request or {}).get("reviewed_at") or ""))
                if reviewed is None or row.time and row.time >= reviewed:
                    handled.add(row.key)
        return handled | {self.title_marker(title) for title, cap in titles.items() if counts[cap] >= self.max_rounds}

    def statuses(self, key: str, request: dict[str, Any]) -> tuple[str, ...]:
        return tuple(row.status for row in self.rows
                     if str(row.row.get("key") or row.key) == key and row.status and row.current_epoch
                     and self._applies(row, request, cap=False))

    def compact(self) -> list[dict[str, Any]]:
        grouped: dict[str, list[HandledReview]] = {}
        oldest = dt.datetime.min.replace(tzinfo=dt.UTC)
        for row in self.rows:
            if key := row.key or str(row.row.get("key") or ""):
                grouped.setdefault(key, []).append(row)
        selected: list[tuple[dt.datetime, dict[str, Any]]] = []
        for key, group in grouped.items():
            durable: dict[str, HandledReview] = {}
            recent = []
            for row in group:
                if row.status in self.terminal | {"submitted_to_researka"}:
                    prior = durable.get(row.status)
                    if prior is None or (row.time or oldest) >= (prior.time or oldest):
                        durable[row.status] = row
                else:
                    recent.append(row)
            keep = sorted(recent, key=lambda row: (row.current_epoch, row.time or oldest))[-self.max_rounds:] + list(durable.values())
            selected.extend((row.time or oldest, {**row.row, "key": key}) for row in keep)
        return [row for _time, row in sorted(selected, key=lambda item: item[0])]


def review_agent_mismatch(rows: Sequence[dict[str, Any]], allowed: Collection[str]) -> str | None:
    unknown = sorted({
        str(row.get("agentId") or row.get("agent_id") or "")
        for row in rows
        if str(row.get("artifactType") or row.get("artifact_type") or "") == "research_paper"
        and str(row.get("agentId") or row.get("agent_id") or "").startswith("agent-v3-")
    } - set(allowed))
    return f"review_agent_id_mismatch:{','.join(unknown)}" if unknown else None


def _revision_item_text(item: Any) -> str:
    if isinstance(item, dict):
        item = next((item.get(key) for key in ("message", "description", "name", "check", "issue", "reason") if item.get(key)), "")
    return str(item).strip()


def required_revision_items(row: dict[str, Any]) -> list[str]:
    items: list[str] = []
    for snake, camel in (("required_revisions", "requiredRevisions"), ("failed_checks", "failedChecks"), ("major_issues", "majorIssues")):
        raw = row.get(snake) or row.get(camel)
        values = raw if isinstance(raw, list) else [raw] if isinstance(raw, str) else []
        items.extend(text for item in values if (text := _revision_item_text(item)))
    return list(dict.fromkeys(items))


def calibration_only_revision(text: str) -> bool:
    lower = " ".join(str(text or "").lower().split())
    tokens = ("direct clinical evidence", "broad population-level proof is missing", "underlying evidence base")
    return "calibration rules" in lower and "revise" in lower and any(token in lower for token in tokens)


def actionable_revisions(row: dict[str, Any]) -> list[str]:
    items = [item for item in required_revision_items(row) if not calibration_only_revision(item)]
    fallback = [str(row.get("reviewSummary") or row.get("review_summary") or "").strip(), *(map(str, notes) if isinstance(notes := row.get("notes"), list) else [str(notes or "")])]
    verbs = r"(?:add|address|clarify|correct|reconcile|remove|replace|rewrite|update|verify)"
    clauses = [clause.strip() for text in fallback for clause in re.split(r"[.!?;]+|,\s*(?:and|but|however|whereas)\s+", text, flags=re.I) if clause.strip()]
    return items or [clause for clause in clauses if re.search(rf"(?:^(?:please\s+)?{verbs}\b|\b(?:must|should|needs? to|required to)\s+(?:please\s+)?{verbs}\b)", clause, re.I) and not re.search(rf"\b(?:no(?:\s+\w+){{0,2}}\s+need to|(?:do|does) not need to|don['’]?t need to|need not|not required to|should not|must not)\s+{verbs}\b", clause, re.I) and not calibration_only_revision(clause)]


def terminal_revision(row: dict[str, Any]) -> bool:
    if str(row.get("decision") or "").strip().lower() != "revise":
        return False
    if actionable_revisions(row):
        return False
    category = str(row.get("failureCategory") or row.get("failure_category") or "").strip().lower()
    summary = row.get("reviewSummary") or row.get("review_summary") or ""
    text = " ".join((*required_revision_items(row), str(summary), str(row.get("notes") or "")))
    terminal_text = re.search(r"\bhigh overlap with publication\b|\bno revisions? (?:are )?required\b", text, re.I)
    return category in {"integrity_duplicate", "duplicate_remote_publication", "publication_overlap"} or calibration_only_revision(text) or bool(terminal_text)


def revise_reason_bucket(text: str) -> str:
    lower = " ".join(str(text or "").lower().split())
    taxonomy = (
        ("directness_honesty", ("direct clinical", "direct interventional", "indirect", "adjacent", "mechanistic", "overclaim", "hypothesis-generating", "broad population-level proof", "no direct")),
        ("null_signal_reconciliation", ("null directional", "no extracted directional signal", "no directional signal", "strongest signal", "reconcile", "supports", "bounded rationale")),
        ("source_relevance_classification", ("source bundle", "source directness", "source classification", "outcome class", "evidence_type", "evidence type", "off-topic", "operationalize", "included under")),
        ("numeric_claim_rigor", ("p-value", "p value", "confidence interval", "significant", "non-significant", "effect direction", "factual error", "statistic")),
        ("readability_redundancy", ("repetitive", "duplication", "truncated", "grammatical", "readability", "verbatim repetition")),
        ("actionable_gaps", ("gaps identified", "actionable", "future research", "next steps")),
    )
    return next(
        (
            bucket
            for bucket, tokens in taxonomy
            if any(token in lower for token in tokens)
        ),
        "unknown",
    )


def requests_domain_scope_reset(feedback: str) -> bool:
    lower = " ".join(str(feedback or "").lower().split())
    frame = r"(?:framing|overlay)"
    patterns = (
        rf"does not support\b.{{0,120}}\b{frame}\b",
        rf"\b{frame}\b.{{0,120}}\bdoes not support\b",
        r"does not match\b.{0,120}\bactual (?:research )?question\b",
        r"actual (?:research )?question\b.{0,120}\bdoes not match\b",
        rf"\bremove\b.{{0,120}}\b{frame}\b",
        rf"\b{frame}\b.{{0,120}}\bremove\b",
    )
    segments = [segment for segment in re.split(r"(?:;|\.)\s+", lower) if segment]
    return bool(segments) and all(
        any(
            term in segment
            for term in (
                "geroscience",
                "anti-aging",
                "anti aging",
                "longevity",
                "healthspan",
            )
        )
        and any(re.search(pattern, segment) for pattern in patterns)
        for segment in segments
    )
