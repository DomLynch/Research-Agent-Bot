"""Deterministic source-identity repairs for reviewer revisions."""
from __future__ import annotations

import re
from typing import Any

from agent.sources.pubmed import pmid_audit_is_current, pmid_audit_passed, verify_pmid_rows


def _normalise(text: str) -> str:
    return " ".join(re.sub(r"[-\u2010-\u2015]+", " ", text.lower()).split())


def asks_pmid_accuracy(text: str) -> bool:
    lower = _normalise(text)
    return "pmid" in lower and any(token in lower for token in ("accuracy", "accurate", "cannot be verified"))


def asks_direction_tally(text: str) -> bool:
    lower = _normalise(text)
    return (
        any(token in lower for token in ("admission count", "admission counts", "admitted count", "admitted sources"))
        and any(token in lower for token in ("receipt level direction", "direction tally", "direction tallies"))
        and any(token in lower for token in ("reconcile", "verify", "against", "actual"))
    )


def asks_outcome_class_tally(text: str) -> bool:
    lower = _normalise(text)
    return (
        "internal count discrepancies" in lower
        and "outcome class tally" in lower
        and any(token in lower for token in ("reconcile", "authoritative"))
    )


def asks_authoritative_tally(text: str) -> bool:
    return asks_outcome_class_tally(text) or asks_direction_tally(text)


def _section(text: str, heading: str) -> str:
    match = re.search(rf"^## {re.escape(heading)}\b(.*?)(?=^## (?!#)|\Z)", text, flags=re.M | re.S)
    return match.group(1) if match else ""


def _prepend(text: str, heading: str, paragraph: str) -> tuple[str, bool]:
    match = re.search(rf"^## {re.escape(heading)}\b", text, flags=re.M)
    if not match or paragraph.lower() in text.lower():
        return text, False
    return text[:match.end()] + "\n\n" + paragraph + text[match.end():], True


def pmid_verification_is_stated(paper_md: str) -> bool:
    scope = "\n\n".join((_section(paper_md, "Methods"), _section(paper_md, "Evidence Landscape")))
    matches = re.findall(r"declared PMIDs=(\d+); verified=(\d+)/(\d+); unverifiable=0", scope)
    match = matches[0] if len(matches) == 1 else None
    return bool(len(re.findall(r"PMID verification audit:", scope, flags=re.I)) == 1
                and match and int(match[0]) > 0
                and match[0] == match[1] == match[2])


def pmid_verification_note(audit: dict[str, Any]) -> str:
    return (f"PMID verification audit: retained bundle entries={audit['entries']}; declared PMIDs="
            f"{audit['declared']}; verified={audit['verified']}/{audit['declared']}; unverifiable=0; "
            f"entries without PMID={audit['without_pmid']}. Each declared PMID was matched to its "
            "NCBI PubMed title and every supplied DOI or PMCID.")


def tally_note_is_stated(paper_md: str, *, require_outcomes: bool) -> bool:
    scope = _section(paper_md, "Conclusion") if require_outcomes else "\n\n".join(
        _section(paper_md, name) for name in ("Evidence Landscape", "Key Findings", "Results", "Conclusion")
    )

    def valid(marker: str) -> int | None:
        matches = list(re.finditer(
            rf"{marker}\s*n\s*=\s*(\d+)\s*;\s*([^.]+)\.", scope, flags=re.I,
        ))
        if len(matches) != 1:
            return None
        match = matches[0]
        n = int(match[1])
        counts = [int(value) for value in re.findall(r"(?:^|;)\s*[^;=]+=(\d+)", match[2])]
        return n if n > 0 and counts and sum(counts) == n else None

    if require_outcomes:
        return bool(
            valid("Authoritative outcome-class tally:") is not None
            and "numerator for each category in this tally" in scope.lower()
        )
    return valid("Admission and direction-tally reconciliation:") is not None


def revision_identity_proof_is_stated(
    paper_md: str,
    ask: str,
    rows: list[dict[str, Any]] | None,
    audit: dict[str, Any] | None,
) -> bool:
    if asks_authoritative_tally(ask):
        needs_outcome = asks_outcome_class_tally(ask)
        needs_direction = asks_direction_tally(ask)
        expected = ([outcome_class_tally_note(rows or [])] if needs_outcome else []) + (
            [direction_tally_note(rows or [])] if needs_direction else []
        )
        conclusion = _section(paper_md, "Conclusion")
        return bool(
            rows
            and all(note in conclusion for note in expected)
            and (not needs_outcome or tally_note_is_stated(paper_md, require_outcomes=True))
            and (not needs_direction or tally_note_is_stated(paper_md, require_outcomes=False))
        )
    if asks_pmid_accuracy(ask):
        return bool(rows and audit and pmid_audit_passed(audit, rows)
                    and pmid_verification_note(audit) in _section(paper_md, "Methods"))
    return True


def direction_tally_note(rows: list[dict[str, Any]]) -> str:
    counts: dict[str, int] = {"negative": 0, "null": 0, "positive": 0, "unclear": 0}
    for row in rows:
        direction = str(row.get("effect_direction") or "unclear").strip().lower() or "unclear"
        counts[direction] = counts.get(direction, 0) + 1
    base = ("negative", "null", "positive", "unclear")
    values = "; ".join(f"{key}={counts[key]}" for key in base)
    values += "".join(f"; {key}={counts[key]}" for key in sorted(set(counts) - set(base)))
    return (
        f"Admission and direction-tally reconciliation: n={len(rows)}; {values}. "
        "These counts use the admitted manifest row set, not classified-candidate buckets."
    )


def outcome_class_tally_note(rows: list[dict[str, Any]]) -> str:
    outcomes: dict[str, int] = {}
    for row in rows:
        outcome = str(row.get("outcome_class") or "unspecified").strip().lower().replace("_", " ")
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
    outcome_values = "; ".join(f"{key}={outcomes[key]}" for key in sorted(outcomes))
    return (
        f"Authoritative outcome-class tally: n={len(rows)}; {outcome_values}. "
        "The numerator for each category in this tally is the number "
        "of retained evidence rows with that classification; n is all retained evidence rows. "
        "These counts use the admitted manifest row set, not classified-candidate buckets."
    )


def repair_revision_identity(
    text: str, rows: list[dict[str, Any]], feedback: str, *, audit: dict[str, Any] | None = None,
) -> tuple[str, list[str], dict[str, Any] | None]:
    details: list[str] = []
    if asks_authoritative_tally(feedback):
        text = re.sub(
            r"\n*(?:Admission and direction-tally reconciliation|Authoritative outcome-class tally):"
            r".*?(?=\n\n|\Z)", "", text, flags=re.I | re.S,
        )
        needs_outcome = asks_outcome_class_tally(feedback)
        needs_direction = asks_direction_tally(feedback)
        notes = ([outcome_class_tally_note(rows)] if needs_outcome else []) + (
            [direction_tally_note(rows)] if needs_direction else []
        )
        text, changed = _prepend(text, "Conclusion", "\n\n".join(notes))
        if changed:
            if needs_outcome:
                details.append("authoritative_outcome_tally")
            if needs_direction:
                details.append("authoritative_direction_tally")
    if asks_pmid_accuracy(feedback):
        if not pmid_audit_is_current(audit, rows):
            audit = verify_pmid_rows(rows)
        text = re.sub(r"(?im)^PMID verification audit:.*(?:\n|$)", "", text)
        if audit and audit.get("passed"):
            text, changed = _prepend(text, "Methods", pmid_verification_note(audit))
            if changed:
                details.append("pmid_identity_verification")
    return text, details, audit
