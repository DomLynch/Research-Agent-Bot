"""Pure reviewer-request classification used by the revision lane."""
from __future__ import annotations

import re
from collections.abc import Collection, Sequence
from typing import Any

V3_AGENT_IDS = frozenset({"agent-v3-full-paper", "agent-v3-full-paper-live"})


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
