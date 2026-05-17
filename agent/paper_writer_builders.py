"""Pure-function builders for paper_writer sections."""
from __future__ import annotations

import difflib
import re
from collections import Counter
from collections.abc import Mapping, Sequence

from agent.synthesis_schemas import (
    ReceiptSummary,
    SectionName,
    SynthesisClaimAnchor,
    SynthesisSection,
)
from agent.outcome_class_remap import outcome_display, outcome_key

__all__ = [
    "build_anchored_from_parsed",
    "build_scoped_from_parsed",
    "build_results_from_parsed",
    "repair_receipt_ids",
]


# Day 10.17 Fix C.3 — fuzzy-match cutoff for receipt-id repair.
# 0.85 ratio matches "cfab-01" against "cfab-c01" (ratio 0.86) but
# rejects "cfab-99" against "cfab-c01" (ratio 0.71). Tight enough
# to avoid snapping fabricated ids to real ones, loose enough to
# repair the empirical 1-char typo class.
_RECEIPT_ID_REPAIR_CUTOFF = 0.85


def repair_receipt_ids(
    rids: Sequence[str], accepted_ids: set[str],
) -> tuple[list[str], list[tuple[str, str]]]:
    """Snap each id in `rids` to its closest match in `accepted_ids`
    via stdlib difflib. Exact matches pass through. Near-misses
    (SequenceMatcher ratio ≥ 0.85) are repaired. Fabricated ids
    (no close match) are dropped.

    Returns (repaired_list, log_of_changes). Log entries are
    (original, repaired_or_dropped_to). The caller can write the
    log to artifact for audit trail.

    Day 10.17 Fix C.3 prescription from external review: prevent
    Q9 receipt-id-format failures at the builder layer rather than
    catching them after rendering. The empirical typo class is
    1-char insertions/deletions in the cluster suffix (LLM dropped
    the 'c' prefix in "cfab-c01" → "cfab-01"); difflib catches that
    cleanly without snapping fabricated ids.
    """
    repaired: list[str] = []
    log: list[tuple[str, str]] = []
    valid_list = list(accepted_ids)
    for rid in rids:
        if rid in accepted_ids:
            repaired.append(rid)
            continue
        match = difflib.get_close_matches(
            rid, valid_list, n=1, cutoff=_RECEIPT_ID_REPAIR_CUTOFF,
        )
        if match:
            repaired.append(match[0])
            log.append((rid, match[0]))
        else:
            log.append((rid, "<dropped>"))
    return repaired, log


_NUMERIC_RE = re.compile(
    r"\b(?:p\s*[<=>]\s*0?\.\d+|"
    r"\d+(?:\.\d+)?\s*%|"
    r"(?:hr|or|rr|ahr|aor|arr|ηp[2²]|β)\s*[=:,\-]?\s*\d+(?:\.\d+)?"
    r")\b",
    re.IGNORECASE,
)


def _normalize(text: str) -> str:
    return " ".join(text.replace("·", ".").split()).lower()


def _topic_aliases(topic: str) -> tuple[str, ...]:
    """Accept file-safe and prose topic labels."""
    raw = topic.strip()
    variants = {raw, raw.replace("_", " "), raw.replace("-", " ")}
    return tuple(_normalize(v) for v in variants if _normalize(v))


def _accepted_corpus_norm(receipts: Sequence[ReceiptSummary]) -> str:
    parts: list[str] = []
    for r in receipts:
        parts.extend(r.p_values)
        parts.append(r.thesis_text)
    return _normalize(" ".join(parts))


def _label_for_outcome(outcome: str) -> str:
    return outcome_display(outcome)


def _norm_label(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", outcome_key(text))


def _resolve_results_outcome(
    sub: dict,
    receipt_ids: Sequence[str],
    receipt_outcomes: Mapping[str, str],
) -> str | None:
    """Resolve Results subsection ownership from corpus facets."""
    label = _norm_label(
        " ".join(str(sub.get(k) or "") for k in ("outcome_class", "heading"))
    )
    outcomes = set(receipt_outcomes.values())
    for outcome in outcomes:
        aliases = (_norm_label(outcome), _norm_label(_label_for_outcome(outcome)))
        if any(alias and alias in label for alias in aliases):
            return outcome
    cited = {receipt_outcomes[rid] for rid in receipt_ids if rid in receipt_outcomes}
    return next(iter(cited)) if len(cited) == 1 else None


def _same_outcome_receipt_ids(
    receipt_ids: Sequence[str],
    outcome: str,
    receipt_outcomes: Mapping[str, str],
) -> list[str]:
    return [rid for rid in receipt_ids if receipt_outcomes.get(rid) == outcome]


def _backfill_results_subsection(
    outcome: str,
    receipts: Sequence[ReceiptSummary],
) -> tuple[list[str], list[SynthesisClaimAnchor]]:
    directions = Counter(r.effect_direction for r in receipts)
    directness = Counter(r.directness for r in receipts)
    dominant = directions.most_common(1)[0][0] if directions else "mixed"
    direct = ", ".join(f"{n} {k}" for k, n in sorted(directness.items()) if k)
    ids = tuple(r.receipt_id for r in receipts)
    label = _label_for_outcome(outcome)
    text = (
        f"The {label.lower()} evidence base comprised {len(receipts)} "
        f"source{'s' if len(receipts) != 1 else ''}; the directness profile "
        f"was {direct or 'unclassified'}, and the dominant direction was "
        f"{dominant}. These sources define the outcome-specific signal for "
        f"this domain before cross-domain interpretation."
    )
    lines = [
        f"### {label} Outcomes", "", text, "",
        "  _Cited: " + ", ".join(f"`{rid}`" for rid in ids) + "_", "",
    ]
    return lines, [SynthesisClaimAnchor(sentence=text, receipt_ids=ids, numerics=())]


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
    aliases = _topic_aliases(topic)
    if aliases and max(norm.count(a) for a in aliases) < 2:
        return False, f"topic_alias_under_count:<2:{aliases[0]!r}"
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
        # Day 10.17 Fix C.3: repair LLM-emitted receipt-id typos
        # before validation. The empirical pattern is 1-char drops
        # (e.g. "cfab-c01" → "cfab-01"); difflib snaps them back.
        repaired_rids, _repair_log = repair_receipt_ids(
            [str(r) for r in rids], accepted_ids,
        )
        ok, _reason = _check_anchored_paragraph(
            text, repaired_rids, accepted_ids, corpus_norm,
        )
        if not ok:
            continue
        body_lines.append(text.strip())
        body_lines.append("")
        cite_str = ", ".join(f"`{i}`" for i in repaired_rids)
        body_lines.append(f"  _Cited: {cite_str}_")
        body_lines.append("")
        anchors.append(SynthesisClaimAnchor(
            sentence=text.strip(),
            receipt_ids=tuple(repaired_rids),
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
    accepted_ids = {r.receipt_id for r in accepted}
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
        # Day 10.17 Fix C.3: same fuzzy-id repair as anchored builder.
        repaired_rids, _repair_log = repair_receipt_ids(
            [str(r) for r in rids], accepted_ids,
        )
        ok, _reason = _check_scoped_paragraph(
            text, topic, repaired_rids, corpus_norm,
        )
        if not ok:
            continue
        body_lines.append(text.strip())
        body_lines.append("")
        if repaired_rids:
            cite_str = ", ".join(f"`{i}`" for i in repaired_rids)
            body_lines.append(f"  _Cited: {cite_str}_")
            body_lines.append("")
        anchors.append(SynthesisClaimAnchor(
            sentence=text.strip(),
            receipt_ids=tuple(repaired_rids),
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
    receipt_outcomes = {r.receipt_id: r.outcome_class for r in accepted}
    by_outcome: dict[str, list[ReceiptSummary]] = {}
    for receipt in accepted:
        by_outcome.setdefault(receipt.outcome_class, []).append(receipt)
    corpus_norm = _accepted_corpus_norm(accepted)
    body_lines: list[str] = ["## Results", ""]
    outcome_bodies: dict[str, list[str]] = {}
    anchors: list[SynthesisClaimAnchor] = []
    rendered_outcomes: set[str] = set()
    for sub in parsed.get("subsections") or []:
        if not isinstance(sub, dict):
            continue
        sub_paragraphs = sub.get("paragraphs") or []
        subsection_outcome: str | None = None
        sub_body: list[str] = []
        sub_anchors: list[SynthesisClaimAnchor] = []
        for entry in sub_paragraphs:
            if not isinstance(entry, dict):
                continue
            text = entry.get("text") or ""
            rids = entry.get("receipt_ids") or []
            if not isinstance(text, str) or not isinstance(rids, list):
                continue
            # Day 10.17 Fix C.3: receipt-id typo repair (same as
            # anchored / scoped builders).
            repaired_rids, _repair_log = repair_receipt_ids(
                [str(r) for r in rids], accepted_ids,
            )
            if subsection_outcome is None:
                subsection_outcome = _resolve_results_outcome(
                    sub, repaired_rids, receipt_outcomes,
                )
            if subsection_outcome is None:
                continue
            repaired_rids = _same_outcome_receipt_ids(
                repaired_rids, subsection_outcome, receipt_outcomes,
            )
            ok, _reason = _check_anchored_paragraph(
                text, repaired_rids, accepted_ids, corpus_norm,
            )
            if not ok:
                continue
            if not sub_body:
                sub_body = [
                    f"### {_label_for_outcome(subsection_outcome)} Outcomes", "",
                ]
            sub_body.append(text.strip())
            sub_body.append("")
            cite_str = ", ".join(f"`{i}`" for i in repaired_rids)
            sub_body.append(f"  _Cited: {cite_str}_")
            sub_body.append("")
            sub_anchors.append(SynthesisClaimAnchor(
                sentence=text.strip(),
                receipt_ids=tuple(repaired_rids),
                numerics=tuple(
                    _normalize(m.group(0))
                    for m in _NUMERIC_RE.finditer(text)
                ),
            ))
        if sub_anchors and subsection_outcome is not None:
            if subsection_outcome in outcome_bodies:
                outcome_bodies[subsection_outcome].extend(sub_body[2:])
            else:
                outcome_bodies[subsection_outcome] = sub_body
            anchors.extend(sub_anchors)
            rendered_outcomes.add(subsection_outcome)
    for outcome in sorted(outcome_bodies):
        body_lines.extend(outcome_bodies[outcome])
    for outcome in sorted(by_outcome):
        if outcome in rendered_outcomes:
            continue
        sub_body, sub_anchors = _backfill_results_subsection(
            outcome, by_outcome[outcome],
        )
        body_lines.extend(sub_body)
        anchors.extend(sub_anchors)
    if not anchors:
        return None
    return SynthesisSection(
        name="results",
        body_md="\n".join(body_lines).rstrip() + "\n",
        anchors=tuple(anchors),
    )
