from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from agent.outcome_class_remap import outcome_display


@dataclass(frozen=True, slots=True)
class OutcomeDirection:
    outcome_key: str
    outcome_label: str
    direction: str
    n_sources: int


_ABSTRACT_RE = re.compile(r"^##\s+Abstract\b(.*?)(?=^##\s+|\Z)", re.MULTILINE | re.DOTALL)
_DIRECTION_SUMMARY_RE = re.compile(
    r"Positive\s+(?:study-level\s+)?signals[^.]*?"
    r"(?:null|no extracted directional)\s+signals[^.]*?"
    r"(?:negative|adverse)[^.]*?\.",
    re.IGNORECASE | re.DOTALL,
)
_POSITIVE_RE = re.compile(r"\b(positive|benefit|beneficial|improv(?:e|ed|es|ing)|favorable)\b", re.IGNORECASE)
_NULL_RE = re.compile(r"\b(null|no effect|no additional|no significant|non-supportive|unchanged)\b", re.IGNORECASE)
_NEGATIVE_RE = re.compile(r"\b(negative|adverse|worse|harm|detrimental|decrease|reduced)\b", re.IGNORECASE)


def normalize_direction(value: object) -> str:
    raw = str(value or "").strip().lower().replace("_", " ")
    if raw in {"positive", "benefit", "beneficial", "supportive", "increase"}:
        return "positive"
    if raw in {"negative", "adverse", "harm", "decrease"}:
        return "negative"
    if raw in {"null", "none", "no effect", "no change", "no extracted directional signal"}:
        return "null"
    return "mixed"


def outcome_direction_profile(manifest: Mapping[str, Any]) -> tuple[OutcomeDirection, ...]:
    by_outcome: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for receipt in manifest.get("receipts", ()):
        if not isinstance(receipt, dict):
            continue
        outcome = str(receipt.get("outcome_class") or "").strip()
        if outcome:
            by_outcome[outcome].append(receipt)

    rows: list[OutcomeDirection] = []
    for outcome, receipts in by_outcome.items():
        counts = Counter(normalize_direction(r.get("effect_direction")) for r in receipts)
        if not counts:
            direction = "mixed"
        else:
            top = counts.most_common()
            direction = top[0][0]
            if len(top) > 1 and top[0][1] == top[1][1]:
                direction = "mixed"
        rows.append(OutcomeDirection(
            outcome_key=outcome,
            outcome_label=outcome_display(outcome).lower(),
            direction=direction,
            n_sources=len(receipts),
        ))
    return tuple(sorted(rows, key=lambda r: (-r.n_sources, r.outcome_label)))


def abstract_direction_sentence(manifest: Mapping[str, Any]) -> str:
    groups: dict[str, list[str]] = {"positive": [], "null": [], "negative": [], "mixed": []}
    for row in outcome_direction_profile(manifest):
        groups[row.direction].append(row.outcome_label)

    def phrase(direction: str, noun: str) -> str:
        labels = groups[direction]
        if not labels:
            return f"{noun} are not the dominant direction in any outcome class"
        if len(labels) == 1:
            target = f"the {labels[0]} outcome class"
        elif len(labels) == 2:
            target = f"the {labels[0]} and {labels[1]} outcome classes"
        else:
            target = f"the {', '.join(labels[:-1])}, and {labels[-1]} outcome classes"
        return f"{noun} are summarized in {target}"

    clauses = [
        phrase("positive", "Positive study-level signals"),
        phrase("null", "null signals"),
        phrase("negative", "negative signals"),
    ]
    if groups["mixed"]:
        clauses.append(phrase("mixed", "mixed or heterogeneous signals"))
    return "; ".join(clauses) + "."


def repair_abstract_direction_summary(paper_md: str, manifest: Mapping[str, Any]) -> tuple[str, int]:
    abstract_match = _ABSTRACT_RE.search(paper_md)
    if not abstract_match:
        return paper_md, 0
    abstract = abstract_match.group(1)
    if not _DIRECTION_SUMMARY_RE.search(abstract):
        return paper_md, 0
    replacement = abstract_direction_sentence(manifest)
    repaired, n = _DIRECTION_SUMMARY_RE.subn(replacement, abstract, count=1)
    if not n:
        return paper_md, 0
    return paper_md[:abstract_match.start(1)] + repaired + paper_md[abstract_match.end(1):], n


def abstract_direction_mismatches(paper_md: str, manifest: Mapping[str, Any]) -> tuple[dict[str, str], ...]:
    abstract_match = _ABSTRACT_RE.search(paper_md)
    if not abstract_match:
        return ()
    abstract = abstract_match.group(1)
    issues: list[dict[str, str]] = []
    for row in outcome_direction_profile(manifest):
        label = re.escape(row.outcome_label)
        if row.direction != "positive" and re.search(rf"\bpositive\b[^.]*\b{label}\b", abstract, re.IGNORECASE):
            issues.append({"outcome": row.outcome_label, "abstract": "positive", "results": row.direction})
        if row.direction != "null" and re.search(rf"\bnull\b[^.]*\b{label}\b", abstract, re.IGNORECASE):
            issues.append({"outcome": row.outcome_label, "abstract": "null", "results": row.direction})
        if row.direction != "negative" and re.search(rf"\bnegative\b[^.]*\b{label}\b", abstract, re.IGNORECASE):
            issues.append({"outcome": row.outcome_label, "abstract": "negative", "results": row.direction})
    return tuple(issues)


def metadata_prose_direction_mismatches(paper_md: str, manifest: Mapping[str, Any]) -> tuple[dict[str, str], ...]:
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z])|\n\n+", paper_md)
    issues: list[dict[str, str]] = []
    for receipt in manifest.get("receipts", ()):
        if not isinstance(receipt, dict):
            continue
        expected = normalize_direction(receipt.get("effect_direction"))
        labels = [
            str(receipt.get(key) or "").strip()
            for key in ("citation_token", "body_citation", "paper_id", "receipt_id")
        ]
        labels = [label for label in labels if label and len(label) >= 4]
        if not labels:
            continue
        for sentence in sentences:
            if not any(re.search(rf"\b{re.escape(label)}\b", sentence) for label in labels[:3]):
                continue
            observed = ""
            if _POSITIVE_RE.search(sentence):
                observed = "positive"
            elif _NEGATIVE_RE.search(sentence):
                observed = "negative"
            elif _NULL_RE.search(sentence):
                observed = "null"
            if observed and observed != expected:
                issues.append({
                    "source": labels[0],
                    "metadata": expected,
                    "prose": observed,
                    "evidence": sentence.strip()[:180],
                })
                break
    return tuple(issues)
