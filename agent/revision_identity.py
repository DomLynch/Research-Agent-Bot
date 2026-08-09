"""Deterministic source-identity repairs for reviewer revisions."""
from __future__ import annotations

import re
from collections import Counter
from typing import Any

from agent.outcome_class_remap import outcome_display
from agent.sources.pubmed import pmid_audit_is_current, pmid_audit_passed, verify_pmid_rows


def _normalise(text: str) -> str:
    return " ".join(re.sub(r"[-\u2010-\u2015]+", " ", text.lower()).split())


_ENDPOINT_ASK_RE = re.compile(
    r"\brefers to (.+?) or (.+?)(?:,\s*and\s+(?:align|reconcile)|[.;]|$)")
_ENDPOINT_PROOF_RE = re.compile(
    r"\brefers(?: specifically)? to (.+?)(?:,\s*)?(?:not to|rather than) (.+?)(?:[.;]|$)")
_ENDPOINT_STOPWORDS = {"the", "and", "coding", "refers", "finding", "contrast"}


def _endpoint_pair(text: str, pattern: re.Pattern[str]) -> tuple[set[str], set[str]] | None:
    match = pattern.search(_normalise(text))
    return tuple(
        set(re.findall(r"\b[a-z0-9]{3,}\b", value)) - _ENDPOINT_STOPWORDS
        for value in match.groups()
    ) if match else None  # type: ignore[return-value]


def direction_attribution_requested(ask: str) -> bool:
    return _endpoint_pair(ask, _ENDPOINT_ASK_RE) is not None


def direction_attribution_note(
    label: str, direction: str, ask: str, evidence: str,
) -> str:
    """Resolve an either/or endpoint ask only when one side carries a traced statistic."""
    match = _ENDPOINT_ASK_RE.search(_normalise(ask))
    if not match:
        return ""
    alternatives = match.groups()
    evidence = _normalise(evidence)
    supported = [
        index for index, alternative in enumerate(alternatives)
        if (stats := re.findall(r"\bp\s*(?:<=|>=|<|>|=)\s*(?:0?\.\d+|1(?:\.0+)?)", alternative))
        and all(stat in evidence for stat in stats)
    ]
    if len(supported) != 1:
        return ""
    target = supported[0]
    return (
        f"{label} {direction} coding refers specifically to {alternatives[target]}, "
        f"not to {alternatives[1 - target]}."
    )


def direction_attribution_is_stated(
    scopes: list[str], label: str, direction: str, ask: str,
) -> bool:
    requested = _endpoint_pair(ask, _ENDPOINT_ASK_RE)
    if not requested or not all(len(endpoint) >= 2 for endpoint in requested):
        return False
    mappings: set[int] = set()
    for scope in scopes:
        for sentence in re.split(r"(?<=[.!?])\s+", _normalise(scope)):
            stated = _endpoint_pair(sentence, _ENDPOINT_PROOF_RE)
            if not stated or not all(token in sentence for token in (_normalise(label), direction, "coding")):
                continue
            if any(token in sentence for token in ("whether", "unresolved", "unclear", "uncertain", "may refer", "might refer", "could refer")):
                return False
            matches = lambda expected, actual: len(expected & actual) >= 2  # noqa: E731
            if all(matches(expected, actual) for expected, actual in zip(requested, stated, strict=True)):
                mappings.add(0)
            if all(matches(expected, actual) for expected, actual in zip(requested, reversed(stated), strict=True)):
                mappings.add(1)
    return len(mappings) == 1


def review_role_contradiction(sentence: str, label: str, context: str = "") -> bool:
    lower, label = _normalise(sentence), _normalise(label)
    pronoun = re.match(r"\s*(?:it|(?:this|the) (?:study|source|paper|review))\b", lower)
    if label not in lower and (label not in _normalise(context) or not pronoun):
        return False
    clauses = re.split(r"\b(?:but|while|whereas)\b|;", lower)
    identity = re.compile(
        rf"(?:{re.escape(label)}\s*:\s*|\b"
        r"(?:is|was|are|were|remains?|constitutes?|represents?|functions? as)\s+)"
        r"(?P<role>[^.]{0,80}?\b(?:rct|trial)\b)")
    containment = re.compile(
        r"\b(?:review|meta analysis|synthesis)\b[^.]{0,50}\b"
        r"(?:of|including|containing|comprising|summarizing|pooling)\b")
    active = label in lower or bool(pronoun)
    for clause in clauses:
        if label in clause:
            active = True
        elif re.search(r"\b[a-z][a-z0-9']*(?:\s+et\s+al)?\s+(?:19|20)\d{2}[a-z]?\b", clause):
            active = False
        if not active:
            continue
        match = identity.search(clause)
        if match and "not" not in match["role"].split() and not containment.search(match["role"]):
            return True
    return False


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
    counts = Counter(str(row.get("effect_direction") or "unclear").strip().lower() or "unclear" for row in rows)
    base = ("negative", "null", "positive", "unclear")
    values = "; ".join(f"{key}={counts[key]}" for key in base)
    values += "".join(f"; {key}={counts[key]}" for key in sorted(set(counts) - set(base)))
    return (
        f"Admission and direction-tally reconciliation: n={len(rows)}; {values}. "
        "These counts use the admitted manifest row set, not classified-candidate buckets."
    )


def outcome_direction_tally_note(rows: list[dict[str, Any]]) -> str:
    grouped: dict[str, Counter[str]] = {}
    for row in rows:
        outcome = outcome_display(str(row.get("outcome_class") or "unspecified"))
        direction = str(row.get("effect_direction") or "unclear").strip().lower() or "unclear"
        grouped.setdefault(outcome, Counter())[direction] += 1
    parts = []
    for outcome, counts in sorted(grouped.items()):
        total = sum(counts.values())
        direction = next(iter(counts)) if len(counts) == 1 else f"mixed ({', '.join(f'{key}={counts[key]}' for key in sorted(counts))})"
        parts.append(f"{outcome} = {direction}" + (f" in {total}/{total}" if len(counts) == 1 else ""))
    return "Outcome-class coded-direction reconciliation: " + "; ".join(parts) + "."


def outcome_class_tally_note(rows: list[dict[str, Any]]) -> str:
    outcomes = Counter(str(row.get("outcome_class") or "unspecified").strip().lower().replace("_", " ") for row in rows)
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
