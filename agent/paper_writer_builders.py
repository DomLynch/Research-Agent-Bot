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
    r"(?<![\w.])(?:"
    r"p\s*[<=>]\s*0?\.\d+|"
    r"(?:\d+(?:\.\d+)?\s*%\s*)?ci\s*[=:]?\s*"
    r"-?\d+(?:\.\d+)?\s*(?:-|to|–)\s*-?\d+(?:\.\d+)?|"
    r"(?:n|mean|median|sd|se|age(?:d)?)\s*[=:]?\s*-?\d+(?:\.\d+)?|"
    r"-?\d+(?:\.\d+)?\s*(?:%|mmol/l|mg/dl|mcg|µg|mg|kg|ml|g|l|"
    r"hours?|days?|weeks?|months?|years?)\b|"
    r"(?:hr|or|rr|ahr|aor|arr|ηp[2²]|β)\s*[=:,\-]?\s*-?\d+(?:\.\d+)?|"
    r"-?\d+(?:\.\d+)?"
    r")(?![\w.])",
    re.IGNORECASE,
)


def _normalize(text: str) -> str:
    return " ".join(text.replace("·", ".").split()).lower()


def _topic_aliases(topic: str) -> tuple[str, ...]:
    """Accept file-safe and prose topic labels, plus the lead entity.

    The scoped validator requires an alias to appear at least twice in a
    paragraph to prove it is on-topic. Matching only the whole slug demanded
    prose repeat "liraglutide adverse effects" verbatim twice, which no real
    writing does -- it says "liraglutide". Every scoped paragraph was therefore
    rejected and the section fell back to a ~15-word placeholder.

    The lead entity is the subject of the topic, so counting it preserves the
    on-topic guarantee: a paragraph naming a different drug still fails.
    """
    raw = topic.strip()
    variants = {raw, raw.replace("_", " "), raw.replace("-", " ")}
    lead = re.split(r"[_\s-]+", raw.strip())
    if lead and lead[0]:
        variants.add(lead[0])
    return tuple(_normalize(v) for v in variants if _normalize(v))


# Bare four-digit calendar years are bibliographic, not quantitative.
_CALENDAR_YEAR_RE = re.compile(r"(?:19|20)\d{2}")


def _numeric_token(text: str) -> str:
    return re.sub(r"\s+", "", _normalize(text))


def _accepted_numeric_tokens(receipts: Sequence[ReceiptSummary]) -> set[str]:
    # population_summary is source-derived text (e.g. "older adults, age 65+")
    # and carries the enrolment numerics a paragraph legitimately cites. Omitting
    # it made the guard reject sample sizes that DO trace to a receipt -- observed
    # live as novel_numeric:n=125 while 125 was present in the corpus. Still
    # source-bounded: nothing outside the receipts is admitted.
    corpus = " ".join(
        value
        for receipt in receipts
        for value in (*receipt.p_values, receipt.thesis_text, receipt.population_summary)
    )
    return {_numeric_token(match.group(0)) for match in _NUMERIC_RE.finditer(corpus)}


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


def _paragraph_list(parsed: Mapping[str, object]) -> list[object]:
    """Return the paragraph entries, tolerating a bare single paragraph.

    The writer asks for {"paragraphs": [...]}, but the model sometimes returns
    ONE paragraph unwrapped, e.g. keys=["receipt_ids", "tension_kind", "text"].
    Reading only "paragraphs" then yielded zero entries, the builder returned
    None, and the section fell back to a ~15-word placeholder that cannot meet
    any word floor -- observed live on cross_domain_synthesis. Which section it
    hits varies per run, which made it look like several unrelated defects.
    """
    paragraphs = parsed.get("paragraphs")
    if isinstance(paragraphs, list):
        return paragraphs
    if parsed.get("text") or parsed.get("sentence"):
        return [dict(parsed)]
    return []


def _check_anchored_paragraph(
    text: str,
    receipt_ids: Sequence[str],
    accepted_ids: set[str],
    accepted_numerics: set[str],
) -> tuple[bool, str]:
    if not text.strip():
        return False, "empty_paragraph"
    cited = [r for r in receipt_ids if r in accepted_ids]
    if not cited:
        return False, f"no_accepted_anchor:{list(receipt_ids)}"
    for m in _NUMERIC_RE.finditer(text):
        tok = _numeric_token(m.group(0))
        if tok in accepted_numerics:
            continue
        # A bare four-digit calendar year is bibliographic context ("a 2025
        # trial", "the 2015 cohort"), not a quantitative claim, so it can never
        # appear in a receipt's numeric set. Rejecting on it discarded EVERY
        # paragraph that dated a study — measured on a live run, all 5
        # cross-domain paragraphs failed on '2025'/'2015' — which made the
        # writer emit a ~15-word placeholder for every LLM section and hung the
        # finalizer on a section it could not repair. The fabrication guard
        # still applies to percentages, p-values, CIs and effect sizes.
        if _CALENDAR_YEAR_RE.fullmatch(tok):
            continue
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
    accepted_ids: set[str],
    accepted_numerics: set[str],
) -> tuple[bool, str]:
    if not text.strip():
        return False, "empty_paragraph"
    cited = [receipt_id for receipt_id in receipt_ids if receipt_id in accepted_ids]
    if not cited:
        return False, f"no_accepted_anchor:{list(receipt_ids)}"
    norm = _normalize(text)
    aliases = _topic_aliases(topic)
    if aliases and max(norm.count(a) for a in aliases) < 2:
        return False, f"topic_alias_under_count:<2:{aliases[0]!r}"
    if not any(h in norm for h in _HEDGE_PHRASES):
        return False, "missing_hedge_phrase"
    for m in _NUMERIC_RE.finditer(text):
        tok = _numeric_token(m.group(0))
        if tok in accepted_numerics:
            continue
        # A bare four-digit calendar year is bibliographic context ("a 2025
        # trial", "the 2015 cohort"), not a quantitative claim, so it can never
        # appear in a receipt's numeric set. Rejecting on it discarded EVERY
        # paragraph that dated a study — measured on a live run, all 5
        # cross-domain paragraphs failed on '2025'/'2015' — which made the
        # writer emit a ~15-word placeholder for every LLM section and hung the
        # finalizer on a section it could not repair. The fabrication guard
        # still applies to percentages, p-values, CIs and effect sizes.
        if _CALENDAR_YEAR_RE.fullmatch(tok):
            continue
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
    accepted_numerics = _accepted_numeric_tokens(accepted)
    paragraphs = _paragraph_list(parsed)
    body_lines: list[str] = [heading, ""]
    anchors: list[SynthesisClaimAnchor] = []
    rejections: list[str] = []
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
        ok, reason = _check_anchored_paragraph(
            text, repaired_rids, accepted_ids, accepted_numerics,
        )
        if not ok:
            rejections.append(reason)
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
                _numeric_token(m.group(0))
                for m in _NUMERIC_RE.finditer(text)
            ),
        ))
    if not anchors:
        # Every paragraph failed anchor validation, so the caller falls back to
        # a ~15-word placeholder that cannot meet any section floor. The reason
        # used to be discarded, which made a total writer failure look like a
        # downstream gate error. Report why the first few were rejected.
        counts = Counter(rejections)
        detail = "; ".join(f"{r} x{n}" for r, n in counts.most_common(3))
        print(
            f"[paper_writer] {name}: all {len(paragraphs)} paragraph(s) failed "
            f"anchor validation — {detail or 'no paragraphs returned'}",
            flush=True,
        )
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
    accepted_numerics = _accepted_numeric_tokens(accepted)
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
            text, topic, repaired_rids, accepted_ids, accepted_numerics,
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
    # Group/resolve on the CANONICAL outcome key (outcome_key) so near-duplicate
    # classes (e.g. "immune" vs "immune_inflammation") collapse to one section,
    # matching the finalizer's _outcome_key routing. Idempotent for classes that
    # are already canonical.
    receipt_outcomes = {r.receipt_id: outcome_key(r.outcome_class) for r in accepted}
    by_outcome: dict[str, list[ReceiptSummary]] = {}
    for receipt in accepted:
        by_outcome.setdefault(outcome_key(receipt.outcome_class), []).append(receipt)
    accepted_numerics = _accepted_numeric_tokens(accepted)
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
                text, repaired_rids, accepted_ids, accepted_numerics,
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
                    _numeric_token(m.group(0))
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
