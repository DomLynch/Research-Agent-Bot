"""Pure-function helpers for paper_writer.

Each `_build_*_from_parsed` turns a parsed LLM JSON envelope into
a `SynthesisSection` (or None if no valid paragraphs survived).
Extracted from paper_writer.py to keep both modules under the
600-cloc per-file cap.

Validation rules per builder:
  - _build_anchored_from_parsed: every paragraph cites ≥1 accepted
    receipt; novel-numeric check; uncited paragraphs dropped.
  - _build_scoped_from_parsed: paragraphs need topic alias ≥2x +
    hedge phrase + no novel numerics; receipt citation OPTIONAL.
  - _build_results_from_parsed: anchored, multi-paragraph by outcome
    class; one H3 subsection per OutcomeClass.

The paragraph-validity helpers (_check_anchored_paragraph,
_check_scoped_paragraph, _accepted_corpus_norm, _NUMERIC_RE,
_normalize) live in paper_writer.py and are re-exported here as
needed by the builders.
"""
from __future__ import annotations

import re
from collections.abc import Sequence

from agent.synthesis_schemas import (
    ReceiptSummary,
    SectionName,
    SynthesisClaimAnchor,
    SynthesisSection,
)

__all__ = [
    "build_anchored_from_parsed",
    "build_scoped_from_parsed",
    "build_results_from_parsed",
]


_NUMERIC_RE = re.compile(
    r"\b(?:p\s*[<=>]\s*0?\.\d+|"
    r"\d+(?:\.\d+)?\s*%|"
    r"(?:hr|or|rr|ahr|aor|arr|ηp[2²]|β)\s*[=:,\-]?\s*\d+(?:\.\d+)?"
    r")\b",
    re.IGNORECASE,
)


def _normalize(text: str) -> str:
    return " ".join(text.replace("·", ".").split()).lower()


def _accepted_corpus_norm(receipts: Sequence[ReceiptSummary]) -> str:
    parts: list[str] = []
    for r in receipts:
        parts.extend(r.p_values)
        parts.append(r.thesis_text)
    return _normalize(" ".join(parts))


def _check_anchored_paragraph(
    text: str,
    receipt_ids: Sequence[str],
    accepted_ids: set[str],
    accepted_corpus_norm: str,
) -> tuple[bool, str]:
    if not text.strip():
        return False, "empty_paragraph"
    cited = [r for r in receipt_ids if r in accepted_ids]
    if not cited:
        return False, f"no_accepted_anchor:{list(receipt_ids)}"
    for m in _NUMERIC_RE.finditer(text):
        tok = _normalize(m.group(0))
        if tok not in accepted_corpus_norm:
            return False, f"novel_numeric:{tok!r}"
    return True, "ok"


_HEDGE_PHRASES = (
    "may ", "appears to", "evidence suggests", "remains uncertain",
    "has been proposed", "the question of whether", "we interpret",
    "this suggests", "one reading is", "the evidence supports",
    "in our view", "remains to be confirmed", "is not yet established",
    "is unresolved", "is unclear", "could ", "might ",
    "proposed as", "hypothesized", "tentative",
)


def _check_scoped_paragraph(
    text: str,
    topic: str,
    receipt_ids: Sequence[str],
    accepted_corpus_norm: str,
) -> tuple[bool, str]:
    if not text.strip():
        return False, "empty_paragraph"
    norm = _normalize(text)
    topic_norm = _normalize(topic)
    if topic_norm and norm.count(topic_norm) < 2:
        return False, f"topic_alias_under_count:<2:{topic_norm!r}"
    if not any(h in norm for h in _HEDGE_PHRASES):
        return False, "missing_hedge_phrase"
    for m in _NUMERIC_RE.finditer(text):
        tok = _normalize(m.group(0))
        if tok not in accepted_corpus_norm:
            return False, f"novel_numeric:{tok!r}"
    return True, "ok"


def build_anchored_from_parsed(
    parsed: dict,
    *,
    name: SectionName,
    heading: str,
    accepted: Sequence[ReceiptSummary],
) -> SynthesisSection | None:
    accepted_ids = {r.receipt_id for r in accepted}
    corpus_norm = _accepted_corpus_norm(accepted)
    paragraphs = parsed.get("paragraphs") or []
    body_lines: list[str] = [heading, ""]
    anchors: list[SynthesisClaimAnchor] = []
    for entry in paragraphs:
        if not isinstance(entry, dict):
            continue
        text = entry.get("text") or entry.get("sentence") or ""
        rids = entry.get("receipt_ids") or []
        if not isinstance(text, str) or not isinstance(rids, list):
            continue
        ok, _reason = _check_anchored_paragraph(
            text, [str(r) for r in rids], accepted_ids, corpus_norm,
        )
        if not ok:
            continue
        body_lines.append(text.strip())
        body_lines.append("")
        cite_str = ", ".join(f"`{i}`" for i in rids)
        body_lines.append(f"  _Cited: {cite_str}_")
        body_lines.append("")
        anchors.append(SynthesisClaimAnchor(
            sentence=text.strip(),
            receipt_ids=tuple(str(r) for r in rids),
            numerics=tuple(
                _normalize(m.group(0))
                for m in _NUMERIC_RE.finditer(text)
            ),
        ))
    if not anchors:
        return None
    return SynthesisSection(
        name=name, body_md="\n".join(body_lines).rstrip() + "\n",
        anchors=tuple(anchors),
    )


def build_scoped_from_parsed(
    parsed: dict,
    *,
    name: SectionName,
    heading: str,
    topic: str,
    accepted: Sequence[ReceiptSummary],
) -> SynthesisSection | None:
    corpus_norm = _accepted_corpus_norm(accepted)
    paragraphs = parsed.get("paragraphs") or []
    body_lines: list[str] = [heading, ""]
    anchors: list[SynthesisClaimAnchor] = []
    for entry in paragraphs:
        if not isinstance(entry, dict):
            continue
        text = entry.get("text") or ""
        rids = entry.get("receipt_ids") or []
        if not isinstance(text, str) or not isinstance(rids, list):
            continue
        ok, _reason = _check_scoped_paragraph(
            text, topic, [str(r) for r in rids], corpus_norm,
        )
        if not ok:
            continue
        body_lines.append(text.strip())
        body_lines.append("")
        if rids:
            cite_str = ", ".join(f"`{i}`" for i in rids)
            body_lines.append(f"  _Cited: {cite_str}_")
            body_lines.append("")
        anchors.append(SynthesisClaimAnchor(
            sentence=text.strip(),
            receipt_ids=tuple(str(r) for r in rids),
            numerics=(),
        ))
    if not anchors:
        return None
    return SynthesisSection(
        name=name, body_md="\n".join(body_lines).rstrip() + "\n",
        anchors=tuple(anchors),
    )


def build_results_from_parsed(
    parsed: dict,
    *,
    accepted: Sequence[ReceiptSummary],
) -> SynthesisSection | None:
    accepted_ids = {r.receipt_id for r in accepted}
    corpus_norm = _accepted_corpus_norm(accepted)
    body_lines: list[str] = ["## Results", ""]
    anchors: list[SynthesisClaimAnchor] = []
    for sub in parsed.get("subsections") or []:
        if not isinstance(sub, dict):
            continue
        h3 = sub.get("heading") or sub.get("outcome_class") or ""
        sub_paragraphs = sub.get("paragraphs") or []
        sub_body: list[str] = [f"### {h3}", ""]
        sub_anchors: list[SynthesisClaimAnchor] = []
        for entry in sub_paragraphs:
            if not isinstance(entry, dict):
                continue
            text = entry.get("text") or ""
            rids = entry.get("receipt_ids") or []
            if not isinstance(text, str) or not isinstance(rids, list):
                continue
            ok, _reason = _check_anchored_paragraph(
                text, [str(r) for r in rids], accepted_ids, corpus_norm,
            )
            if not ok:
                continue
            sub_body.append(text.strip())
            sub_body.append("")
            cite_str = ", ".join(f"`{i}`" for i in rids)
            sub_body.append(f"  _Cited: {cite_str}_")
            sub_body.append("")
            sub_anchors.append(SynthesisClaimAnchor(
                sentence=text.strip(),
                receipt_ids=tuple(str(r) for r in rids),
                numerics=tuple(
                    _normalize(m.group(0))
                    for m in _NUMERIC_RE.finditer(text)
                ),
            ))
        if sub_anchors:
            body_lines.extend(sub_body)
            anchors.extend(sub_anchors)
    if not anchors:
        return None
    return SynthesisSection(
        name="results",
        body_md="\n".join(body_lines).rstrip() + "\n",
        anchors=tuple(anchors),
    )
