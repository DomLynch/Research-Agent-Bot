"""Receipt filtering for BRIEFS-V1."""
from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from agent.briefs.question_parser import BriefQuery

__all__ = ["filter_receipts"]

_POP_TERMS: dict[str, tuple[str, ...]] = {
    "T2D": ("t2d", "type 2 diabetes", "diabetic"),
    "obesity": ("obesity", "obese", "overweight"),
    "older adults": ("older adults", "elderly", "geriatric", "aged"),
    "non-diabetic older adults": ("non diabetic", "non-diabetic"),
    "healthy adults": ("healthy adults", "healthy volunteers"),
}
_COMORBIDITY_TERMS: dict[str, tuple[str, ...]] = {
    "CKD": ("ckd", "chronic kidney disease"),
    "cardiovascular disease": ("cvd", "cardiovascular disease"),
    "T2D": _POP_TERMS["T2D"],
    "obesity": _POP_TERMS["obesity"],
}


def filter_receipts(
    manifest: Mapping[str, Any], query: BriefQuery,
) -> tuple[dict[str, Any], ...]:
    """Filter manifest receipts for a brief query.

    Outcome class is the hard gate when present. Population, age, and
    comorbidity are soft gates: if any outcome-matched receipts carry
    those text signals, keep the signaled subset; otherwise preserve
    the outcome-matched receipts so sparse manifests do not go empty.
    """
    receipts = [
        dict(r) for r in manifest.get("receipts", [])
        if isinstance(r, Mapping)
    ]
    if not receipts:
        return ()
    outcome_filtered = [
        r for r in receipts if _matches_outcome(r, query.outcome_classes)
    ]
    candidates = outcome_filtered or receipts
    scored = [
        (score, idx, r) for idx, r in enumerate(candidates)
        if (score := _soft_score(r, query)) >= 0
    ]
    if not scored:
        return ()
    positive = [row for row in scored if row[0] > 0]
    selected = positive if positive else scored
    return tuple(
        r for _, _, r in sorted(selected, key=lambda row: (-row[0], row[1]))
    )


def _matches_outcome(
    receipt: Mapping[str, Any], outcomes: Sequence[str],
) -> bool:
    if not outcomes:
        return True
    outcome = str(receipt.get("outcome_class") or "").strip().lower()
    if outcome in {o.lower() for o in outcomes}:
        return True
    text = _receipt_text(receipt)
    return any(o.replace("_", " ") in text for o in outcomes)


def _soft_score(receipt: Mapping[str, Any], query: BriefQuery) -> int:
    text = _receipt_text(receipt)
    score = 0
    if query.population:
        score += 2 if _has_any(text, _POP_TERMS.get(query.population, ())) else 0
    for comorbidity in query.comorbidities:
        score += 1 if _has_any(
            text, _COMORBIDITY_TERMS.get(comorbidity, ()),
        ) else 0
    if query.age_range and _has_any(
        text, ("older adults", "elderly", "geriatric", "aged", "65"),
    ):
        score += 1
    return score


def _receipt_text(receipt: Mapping[str, Any]) -> str:
    parts = [
        receipt.get("receipt_id"), receipt.get("paper_id"),
        receipt.get("citation_token"), receipt.get("source_title"),
        receipt.get("thesis_text"), receipt.get("abstract"),
    ]
    return " ".join(str(p) for p in parts if p).lower().replace("_", " ")


def _has_any(text: str, terms: Sequence[str]) -> bool:
    return any(
        re.search(rf"\b{re.escape(term.lower())}\b", text)
        for term in terms
    )
