"""Pure reviewer-request classification used by the revision lane."""
from __future__ import annotations

import json
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


# One writer-facing instruction per revise-ask bucket. Buckets without a writer-actionable
# instruction (publication overlap) are deliberately absent. Topic-agnostic by construction.
_LESSONS = {
    "citation_bundle_mismatch": "Every Results and Conclusion claim cites its [bundle:N] source and stays within that source's own words; never cite an author-year that has no bundle entry.",
    "section_duplication": "Never repeat a paragraph, note, or boilerplate across sections; each section adds content the others do not.",
    "directness_honesty": "Call evidence direct only when the study tests the topic intervention itself on the stated outcome; label reviews, models, and co-interventions as indirect.",
    "direction_coding": "State each source's direction exactly as its own results sentence reports it (positive, negative, mixed, or null); never infer direction from a title or a count.",
    "source_relevance_classification": "Give every source the study design and outcome class its own abstract states; protocols and registrations are planned work, not results.",
    "methods_accounting": "Methods states the retrieved, assessed, and admitted counts with the admission rule, and claims no appraisal that was not performed.",
    "numeric_claim_rigor": "Report each statistic with its endpoint, comparator, and p-value exactly as the source gives it; never pool, round, or invent a number.",
    "scope_mismatch": "The title and research question describe exactly what the admitted sources test, no broader.",
    "table_without_numbers": "Every evidence-table row carries the source's numeric finding, not only a direction label.",
    "null_signal_reconciliation": "Where sources are coded null or unclear, the prose says so and draws no directional conclusion from their count.",
    "readability_redundancy": "Write complete sentences in ordinary paragraphs; no fragments, garbled headers, or repeated phrases.",
    "actionable_gaps": "Name the specific disagreements between sources and the specific study that would resolve each.",
}
REVISE_REASONS_RELPATH = "runs/_daily_research_paper_cycle_ledger/_revise_reasons.json"


def revision_lessons(root: Any, *, days: int = 30, cap: int = 8) -> str:
    """Instructions for the most frequent reviewer revision buckets of the trailing window, or ""."""
    try:
        reviews = json.loads((root / REVISE_REASONS_RELPATH).read_text()).get("reviews", [])
    except (OSError, ValueError, AttributeError):
        return ""
    cutoff = dt.datetime.now(dt.UTC) - dt.timedelta(days=days)
    counts = Counter(ask.get("bucket") for review in reviews if (seen := parse_time(str(review.get("reviewed_at") or ""))) and seen >= cutoff for ask in review.get("asks", []))
    lines = [_LESSONS[bucket] for bucket, _ in counts.most_common() if bucket in _LESSONS][:cap]
    return "Reviewer lessons (most frequent revision requests, last %d days):\n%s\n\n" % (days, "\n".join(f"- {line}" for line in lines)) if lines else ""


def revise_reason_bucket(text: str) -> str:
    lower = " ".join(str(text or "").lower().split())
    taxonomy = (
        ('publication_overlap', ('overlap with publication', 'already published', 'duplicate submission')),
        ('scope_mismatch', ('scope mismatch', 'scope/title', 'narrow the title', 'research question', 'does not match the corpus', 'match the actual corpus', 'title says', 'mismatch between the title', 'pico', 'framing that does not match', 'rename the title', 'abstract omits', 'synthesis question')),
        ('section_duplication', ('near-verbatim duplicate', 'verbatim', 'repeated', 'repeating', 'duplicated', 'duplicates content', 'redundant', 'boilerplate', 'templated', 'placeholder', 'corrupted', 'meta-commentary', 'scaffolding', 'restatement', 'collapsing redundant')),
        ('table_without_numbers', ('no actual numeric', 'aggregate counts', 'no numeric', 'without numeric', 'no effect sizes', "beyond 'positive", 'only enumerates source-level')),
        ('direction_coding', ('mis-coded', 'miscoded', 'coded as', 'coded positive', "coded 'positive'", 'labeled "null"', "labeled 'null'", 'labelled', 'labels ', 'direction profile', 'direction assignments', 'direction synthesis', 'directional coding', 'coded null', 'polarity', 'coded direct', 'directness coding', 'recode', 'coding is consistent', 'coding is internally', 'orient positive', 'outcome-class allocation', 'direction code')),
        ('methods_accounting', ('inclusion funnel', 'auditable', 'selection flow', 'retrieved records', 'search summary', 'search strategy', 'search window', 'query list', 'database coverage', 'retrieval date', 'admitted sources', 'exclusion counts', 'eligibility criterion', 'screening', 'extraction qc', 'future-dated', 'publication dates', 'dated 2025', 'risk-of-bias', 'rob ', 'rob-2', 'not visible to the reader', 'methods_pack', 'conference abstract', 'conference-abstract', 'justify its tier', 'sample-size and follow-up')),
        ('citation_bundle_mismatch', ('exact source tokens', 'exactly traceable', 'identify a bundle source', 'traceab', 'could not be verified', 'not present in the source_bundle', 'not in the source bundle', 'source-list mismatch', 'attributions are inaccurate', 'source attributions', 'attribute each', 'cited numbers', 'citations that are not', 'author-year', 'cited source', 'bundle excerpt', 'bundle entries', 'conflict between the abstract', 'enumerate and locate', 'remove the number', 'cross-study disagreements', 'tensions and gaps', 'name the specific sources', 'itemize the specific', 'without citing', 'broken author token', 'misattributed', 'misattribution', 'does not cite', 'incorrectly describes', 'incorrectly states', 'completeness claim', 'primary evidence anchor', 'invalid at indices')),
        ('directness_honesty', ('direct clinical', 'direct interventional', 'indirect', 'adjacent', 'mechanistic', 'overclaim', 'hypothesis-generating', 'broad population-level proof', 'no direct', 'single-source', 'does not directly test', 'not directly', 'stand-alone intervention', 'direct sources', 'direct-rct', 'add-on or comparator')),
        ('null_signal_reconciliation', ('null directional', 'no extracted directional signal', 'no directional signal', 'strongest signal', 'reconcile', 'supports', 'bounded rationale')),
        ('source_relevance_classification', ('source bundle', 'source directness', 'source classification', 'outcome class', 'evidence_type', 'evidence type', 'off-topic', 'operationalize', 'included under', 'misclassified', 'reclassify', 'protocol', 'belongs in the synthesis', 'clarify why it is in', 'weakly relevant', 'not a results paper', 'reframe', 'justify inclusion', "meta-analysis' label", 'source-role')),
        ('numeric_claim_rigor', ('p-value', 'p value', 'confidence interval', 'significant', 'non-significant', 'effect direction', 'factual error', 'statistic', 'numeric', 'hedged', 'hedge', 'primary endpoint', 'contradiction', 'contradicts', 'pooled', 'power rationale', 'misattribution')),
        ('readability_redundancy', ('repetitive', 'duplication', 'truncated', 'grammatical', 'readability', 'verbatim repetition', 'readable', 'formatting', 'paragraph breaks', 'paragraph structure', 'self-contained', 'garbled', 'fragment', 'capitalization', 'inline label')),
        ('actionable_gaps', ('gaps identified', 'actionable', 'future research', 'next steps', 'concise list', 'add an explicit background', 'add a single sentence', 'add one or two sentences', 'expand the discussion')),
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
