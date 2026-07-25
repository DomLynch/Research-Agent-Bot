"""Deterministic repair for reviewer source-role and disclosure asks."""
from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any, Callable

from agent.evidence_lanes import derive_receipt_lane
from agent.revision_identity import review_role_contradiction

_PROPOSED_TRIAL_NOTE = (
    "Design-gap boundary: The proposed long-duration randomized trial is not represented in the retained "
    "corpus; it is a future-study requirement, not evidence claimed to exist."
)
_CODED_POLARITY_NOTE = (
    "Direction-coding boundary: Receipt-level direction is a conservative coded polarity for synthesis "
    "accounting and may differ from claim-level direction reported within a source."
)


def _normalise(text: str) -> str:
    return " ".join(re.sub(r"[-\u2010-\u2015]+", " ", text.lower()).split())


def _asks_role_reconciliation(text: str) -> bool:
    return (
        any(token in text for token in ("evidence_type", "evidence type"))
        and "directness" in text
        and any(token in text for token in ("clinical rct", "randomized", "randomised"))
    ) or (
        any(token in text for token in ("animal", "veterinary", "preclinical"))
        and any(token in text for token in ("direct human", "human clinical", "directness"))
        and any(token in text for token in ("downgrade", "reclass", "move out", "not list"))
    ) or (
        "review grade" in text and "comparison" in text
        and any(token in text for token in ("consistent", "framing", "role"))
    )


def _asks_source_indexing(text: str) -> bool:
    return any(token in text for token in ("non pubmed", "source_type=corpus", "source type corpus")) and any(
        token in text for token in ("methods", "disclose", "publisher venue", "venue")
    )


def _asks_unrepresented_trial(text: str) -> bool:
    return any(token in text for token in ("trial", "rct")) and any(
        token in text for token in ("propos", "future study")
    ) and any(token in text for token in ("does not exist", "does not currently exist", "not represented"))


def _asks_coded_polarity(text: str) -> bool:
    return (
        "abstract" in text
        and any(token in text for token in ("receipt level", "source level"))
        and "claim level" in text
        and any(token in text for token in ("coded polarity", "direction"))
    )


def ask_known(ask: str, _rows: Sequence[dict[str, Any]] | None = None) -> bool:
    text = _normalise(ask)
    return any(check(text) for check in (
        _asks_role_reconciliation, _asks_source_indexing,
        _asks_unrepresented_trial, _asks_coded_polarity,
    ))


def _label(row: dict[str, Any]) -> str:
    return str(
        row.get("citation_token") or row.get("body_citation")
        or row.get("source_title") or row.get("receipt_id") or "source"
    ).strip()


def _mention_key(text: str) -> str:
    return _normalise(re.sub(r"\bet\s+al\.?", "", text, flags=re.I))


def _named_rows(ask: str, rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    lower = _mention_key(ask)
    return [row for row in rows if any(
        value and re.search(rf"(?<!\w){re.escape(_mention_key(value))}(?!\w)", lower)
        for value in (_label(row), str(row.get("source_title") or "").strip())
    )]


def _section_span(paper_md: str, heading: str) -> tuple[int, int] | None:
    match = re.search(rf"^(?P<marks>#{{2,3}})\s+{re.escape(heading)}[ \t]*$", paper_md, re.M | re.I)
    if not match:
        return None
    tail = paper_md[match.end():]
    next_heading = re.search(rf"^#{{1,{len(match.group('marks'))}}}\s+", tail, re.M)
    return match.end(), match.end() + (next_heading.start() if next_heading else len(tail))


def _upsert_note(paper_md: str, heading: str, marker: str, note: str) -> tuple[str, int]:
    span = _section_span(paper_md, heading)
    if not span:
        return paper_md, 0
    start, end = span
    existing = re.search(rf"^{re.escape(marker)}.*$", paper_md[start:end], re.M)
    if existing and existing.group(0) == note:
        return paper_md, 0
    if existing:
        left, right = start + existing.start(), start + existing.end()
        return paper_md[:left] + note + paper_md[right:], 1
    return paper_md[:start] + "\n\n" + note + paper_md[start:], 1


def _has_note(paper_md: str, heading: str, note: str) -> bool:
    span = _section_span(paper_md, heading)
    return bool(span and note in paper_md[span[0]:span[1]])


def _review_level(row: dict[str, Any]) -> bool:
    return any(str(row.get(key) or "").strip().lower() == "review" for key in ("evidence_type", "directness"))


def _role_note(row: dict[str, Any], ask: str) -> str:
    label = _label(row)
    if derive_receipt_lane(row) == "animal_preclinical":
        return (
            f"{label} is retained as animal/preclinical contextual evidence "
            "(directness=indirect) and is not counted as direct human clinical evidence."
        )
    if "review grade" in _normalise(ask) and "comparison" in _normalise(ask):
        return (
            f"{label} is reported as a randomized trial by study design but functions here "
            "as a review-grade comparison because it does not isolate the target intervention; "
            "it is not double-counted as independent direct clinical support."
        )
    if _review_level(row):
        return (
            f"{label} is retained as review-level evidence (directness=review) "
            "and is not counted as a direct clinical RCT."
        )
    return ""


def _role_rows(ask: str, rows: Sequence[dict[str, Any]]) -> list[tuple[dict[str, Any], str]]:
    return [(row, note) for row in _named_rows(ask, rows) if (note := _role_note(row, ask))]


def _paragraphs(paper_md: str) -> list[tuple[str, str]]:
    heading, out = "", []
    for part in re.split(r"\n\s*\n", paper_md):
        if match := re.match(r"^#{2,3}\s+(.+?)\s*$", part.strip()):
            heading = match.group(1)
        elif part.strip() and not part.lstrip().startswith(("#", "|", "```")):
            out.append((heading, part))
    return out


def _reconcile_roles(paper_md: str, ask: str, rows: Sequence[dict[str, Any]]) -> tuple[str, int]:
    role_rows = _role_rows(ask, rows)
    if not role_rows:
        return paper_md, 0
    review_rows = [] if "review grade" in _normalise(ask) else [
        row for row, _note in role_rows if _review_level(row)
    ]
    changed, parts, heading = 0, re.split(r"(\n\s*\n)", paper_md), ""
    for index in range(0, len(parts), 2):
        if match := re.match(r"^#{2,3}\s+(.+?)\s*$", parts[index].strip()):
            heading = match.group(1)
            continue
        if heading.lower().startswith(("references", "bibliography")):
            continue
        sentences = re.split(r"(?<=[.!?])\s+", parts[index])
        kept = [sentence for pos, sentence in enumerate(sentences) if not any(
            review_role_contradiction(sentence, _label(row), sentences[pos - 1] if pos else "")
            for row in review_rows
        )]
        if len(kept) != len(sentences):
            parts[index], changed = " ".join(kept), changed + 1
    patched = "".join(parts)
    note = "Evidence-type reconciliation: " + " ".join(note for _row, note in role_rows)
    heading = (
        "Tensions and Gaps" if _section_span(patched, "Tensions and Gaps") else "Cross-Domain Synthesis"
    ) if "tension" in _normalise(ask) else "Results"
    patched, n = _upsert_note(patched, heading, "Evidence-type reconciliation:", note)
    return patched, changed + n


def _roles_reconciled(paper_md: str, ask: str, rows: Sequence[dict[str, Any]]) -> bool:
    role_rows, scope = _role_rows(ask, rows), paper_md.lower()
    review_grade = "review grade" in _normalise(ask)
    return bool(role_rows) and all(
        (note.lower() in scope or _review_level(row) and not review_grade
         and _label(row).lower() in scope and "directness=review" in scope)
        and "evidence-type reconciliation:" in scope
        and (not _review_level(row) or review_grade or not any(
            review_role_contradiction(sentence, _label(row), sentences[pos - 1] if pos else "")
            for heading, paragraph in _paragraphs(paper_md)
            if not heading.lower().startswith(("references", "bibliography"))
            for sentences in (re.split(r"(?<=[.!?])\s+", paragraph),)
            for pos, sentence in enumerate(sentences)
        ))
        for row, note in role_rows
    )


def _source_indexing_note(rows: Sequence[dict[str, Any]]) -> str:
    corpus_rows = [row for row in rows if not str(row.get("source_pmid") or "").strip()]
    if not corpus_rows:
        return ""
    entries = "; ".join(
        f"{_label(row)} (venue={str(row.get('source_venue') or '').strip() or 'unavailable in retained metadata'})"
        for row in corpus_rows
    )
    return (
        "Source-indexing disclosure: Non-PubMed corpus sources are identified separately "
        f"and are not treated as PubMed-indexed based on corpus inclusion alone: {entries}."
    )


def proof_is_stated(paper_md: str, ask: str, rows: Sequence[dict[str, Any]]) -> bool:
    text = _normalise(ask)
    source_note = _source_indexing_note(rows)
    checks: tuple[tuple[Callable[[str], bool], bool], ...] = (
        (_asks_role_reconciliation, _roles_reconciled(paper_md, ask, rows)),
        (_asks_source_indexing, bool(source_note) and _has_note(paper_md, "Methods", source_note)),
        (_asks_unrepresented_trial, _has_note(paper_md, "Cross-Domain Synthesis", _PROPOSED_TRIAL_NOTE)),
        (_asks_coded_polarity, _has_note(paper_md, "Abstract", _CODED_POLARITY_NOTE)),
    )
    return all(not matches(text) or passed for matches, passed in checks)


def _feedback_parts(feedback: str) -> list[str]:
    return [part.strip() for part in re.split(r";\s+(?=[A-Z])", feedback) if part.strip()]


def repair(
    paper_md: str, rows: Sequence[dict[str, Any]], feedback: str,
) -> tuple[str, list[str]]:
    text, patched, details = _normalise(feedback), paper_md, []
    role_ask = " ".join(
        part for part in _feedback_parts(feedback) if _asks_role_reconciliation(_normalise(part))
    )
    if role_ask:
        patched, changed = _reconcile_roles(patched, role_ask, rows)
        if changed:
            details.append("evidence_role_reconciliation")
    for predicate, heading, marker, note, detail in (
        (_asks_source_indexing, "Methods", "Source-indexing disclosure:",
         _source_indexing_note(rows), "source_indexing_disclosure"),
        (_asks_unrepresented_trial, "Cross-Domain Synthesis", "Design-gap boundary:",
         _PROPOSED_TRIAL_NOTE, "unrepresented_trial_boundary"),
        (_asks_coded_polarity, "Abstract", "Direction-coding boundary:",
         _CODED_POLARITY_NOTE, "abstract_coded_polarity"),
    ):
        if predicate(text) and note:
            patched, changed = _upsert_note(patched, heading, marker, note)
            if changed:
                details.append(detail)
    return patched, details
