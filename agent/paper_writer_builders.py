"""Pure-function builders for paper_writer sections."""
from __future__ import annotations

import difflib
import re
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path

from agent.evidence_lanes import is_animal_context
from agent.outcome_class_remap import outcome_display, outcome_key
from agent.synthesis_schemas import ReceiptSummary, SectionName, SynthesisClaimAnchor, SynthesisSection

__all__ = [
    "build_anchored_from_parsed",
    "build_scoped_from_parsed",
    "build_results_from_parsed",
    "citation_only_repair",
    "citation_only_repair_eligible",
    "repair_receipt_ids",
]


# Matches one-character receipt-id drift without snapping unrelated IDs.
_RECEIPT_ID_REPAIR_CUTOFF = 0.85
_CONTINUING_ABBREVIATION_RE = re.compile(r"\b(?:et al\.(?=[ \t]+(?-i:[a-z0-9(]))|vs\.(?=\s+[-+]?\s*\d)|p\s*[<=>≤≥]+\s*0?\.(?=[ \t]+\d))", re.I)
_AMBIGUOUS_ABBREVIATION_RE = re.compile(
    r"\b(?:(?-i:[A-Z])\.|(?:[A-Za-z]\.){2,}|(?:dr|mr|mrs|ms|prof|sr|jr|st|figs?|eqs?|refs?|"
    r"secs?|dept|nos?|vol|inc|ltd|co|etc|approx|vs|cf|et al)\.)[,;:]?\s+",
    re.I,
)
_SENTENCE_BREAK_RE = re.compile(r"[.!?][^\w\s]*\s+")
_INLINE_RECEIPT_RE = re.compile(r"\[([^\[\]\n]+)\]")
def _has_internal_sentence_boundary(text: str) -> bool:
    protected = _CONTINUING_ABBREVIATION_RE.sub(lambda match: match.group().replace(".", "<DOT>"), text)
    return len(_SENTENCE_BREAK_RE.split(protected)) > 1


def _repair_rows(payload: Mapping[str, object]) -> list[object]:
    return value if isinstance(value := payload.get("paragraphs"), list) else [payload]


def _receipt_outcome(receipt: ReceiptSummary) -> str:
    return "animal_preclinical_context" if is_animal_context(receipt) else outcome_key(receipt.outcome_class)


def citation_only_repair_eligible(payload: Mapping[str, object]) -> bool:
    rows = _repair_rows(payload)
    return bool(rows) and all(
        isinstance(row, dict)
        and isinstance(row.get("receipt_ids"), list) and bool(row.get("receipt_ids"))
        and isinstance(row.get("text") or row.get("sentence"), str)
        and (not _has_internal_sentence_boundary(str(row.get("text") or row.get("sentence")))
             or (len(set(map(str, row["receipt_ids"]))) == 1
                 and not _AMBIGUOUS_ABBREVIATION_RE.search(str(row.get("text") or row.get("sentence")))))
        for row in rows
    )


def citation_only_repair(
    before: Mapping[str, object], after: Mapping[str, object], accepted_ids: set[str],
) -> bool:
    def prose(text: str, ids: list[object]) -> str:
        text = _INLINE_RECEIPT_RE.sub(
            lambda match: "" if match.group(1) in ids else match.group(), text,
        )
        text = " ".join(text.split())
        return re.sub(r"\s+([.!?,;:])", r"\1", text)

    original, repaired = _repair_rows(before), _repair_rows(after)
    if not citation_only_repair_eligible(before) or len(original) != len(repaired):
        return False
    for old, new in zip(original, repaired, strict=True):
        if not isinstance(old, dict) or not isinstance(new, dict):
            return False
        ids, new_ids = old.get("receipt_ids"), new.get("receipt_ids")
        old_text = old.get("text") or old.get("sentence")
        new_text = new.get("text") or new.get("sentence")
        if (
            not isinstance(ids, list) or new_ids != ids
            or not set(map(str, ids)) <= accepted_ids
            or not isinstance(old_text, str) or not isinstance(new_text, str)
            or prose(old_text, ids) != prose(new_text, ids)
        ):
            return False
        old_tokens = _INLINE_RECEIPT_RE.findall(old_text)
        new_tokens = _INLINE_RECEIPT_RE.findall(new_text)
        new_known = [token for token in new_tokens if token in ids]
        if (
            [token for token in old_tokens if token not in ids]
            != [token for token in new_tokens if token not in ids]
            or not new_known
        ):
            return False
        expected = list(map(str, ids))
        protected = _CONTINUING_ABBREVIATION_RE.sub(
            lambda match: match.group().replace(".", "<DOT>"), new_text)
        sentence_ids = [
            {token for token in _INLINE_RECEIPT_RE.findall(sentence) if token in ids}
            for sentence in _SENTENCE_BREAK_RE.split(protected)
        ]
        if (
            set(new_known) != set(expected)
            or (len(sentence_ids) > 1
                and any(sentence != set(expected) for sentence in sentence_ids))
        ):
            return False
    return True


def repair_receipt_ids(
    rids: Sequence[str], accepted_ids: set[str],
) -> tuple[list[str], list[tuple[str, str]]]:
    """Repair near-miss receipt IDs; return repaired IDs and a change log."""
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
    # Allow sentence-final punctuation without matching partial numbers.
    r")(?!\w)",
    re.IGNORECASE,
)

def _normalize(text: str) -> str:
    return " ".join(text.replace("·", ".").split()).lower()


def _topic_aliases(topic: str) -> tuple[str, ...]:
    """Return full topic variants plus its lead entity."""
    raw = topic.strip()
    variants = {raw, raw.replace("_", " "), raw.replace("-", " ")}
    lead = re.split(r"[_\s-]+", raw.strip())
    if lead and lead[0]:
        variants.add(lead[0])
    return tuple(_normalize(v) for v in variants if _normalize(v))


# Four-digit years are bibliographic only when their prose context says so.
_CALENDAR_YEAR_RE = re.compile(r"(?:19|20)\d{2}")
_YEAR_PREFIX_RE = re.compile(r"\b(?:in|from|since|during|by)\s*$", re.IGNORECASE)
_YEAR_CITATION_RE = re.compile(r"\b[A-Z][A-Za-z'’-]+(?:\s+et\s+al\.)?\s*\(?\s*$")
_YEAR_STUDY_RE = re.compile(
    r"\s*(?:(?:randomi[sz]ed|prospective|retrospective|observational|clinical)\s+)*"
    r"(?:trial|study|cohort|report|analysis|publication|paper|review|registry)\b",
    re.IGNORECASE,
)
_YEAR_COUNT_RE = re.compile(
    r"\s*(?:participants|patients|subjects|cases|records|people|individuals|"
    r"adults|children|samples|observations)\b",
    re.IGNORECASE,
)


def _numeric_token(text: str) -> str:
    return re.sub(r"\s+", "", _normalize(text))


def _is_bibliographic_year(text: str, match: re.Match[str]) -> bool:
    """Distinguish study dates from four-digit sample sizes."""
    if not _CALENDAR_YEAR_RE.fullmatch(_numeric_token(match.group(0))):
        return False
    before = text[max(0, match.start() - 16):match.start()]
    after = text[match.end():match.end() + 40]
    if _YEAR_COUNT_RE.match(after):
        return False
    return bool(_YEAR_PREFIX_RE.search(before) or _YEAR_STUDY_RE.match(after) or _YEAR_CITATION_RE.search(before))


def receipt_evidence_text(receipt: ReceiptSummary, limit: int | None = None) -> str:
    """Budget complete result sentences before the historical receipt excerpt."""
    if not receipt.source_result_excerpts:
        return receipt.thesis_text if limit is None else receipt.thesis_text[:limit]
    title, _, historical = receipt.thesis_text.partition("source excerpts:")
    prefix = title + "source excerpts: "
    selected: list[str] = []
    for excerpt in dict.fromkeys((*receipt.source_result_excerpts, *historical.split(" | "))):
        excerpt = excerpt.strip()
        if excerpt and (limit is None or len(prefix + " | ".join((*selected, excerpt))) <= limit):
            selected.append(excerpt)
    return prefix + " | ".join(selected)


def _accepted_numeric_tokens(receipts: Sequence[ReceiptSummary]) -> set[str]:
    # population_summary is source-derived text (e.g. "older adults, age 65+")
    # and carries the enrolment numerics a paragraph legitimately cites. Omitting
    # it made the guard reject sample sizes that DO trace to a receipt -- observed
    # live as novel_numeric:n=125 while 125 was present in the corpus. Still
    # source-bounded: nothing outside the receipts is admitted.
    corpus = " ".join(value for receipt in receipts for value in (*receipt.p_values, receipt_evidence_text(receipt), receipt.population_summary))
    return {_numeric_token(match.group(0)) for match in _NUMERIC_RE.finditer(corpus)}


def _source_grounding_reason(text: str, receipt_ids: Sequence[str], receipts_by_id: Mapping[str, ReceiptSummary]) -> str | None:
    if (scripts := str(Path(__file__).resolve().parents[1] / "scripts")) not in sys.path:
        sys.path.insert(0, scripts)
    from publishing.submission import _evidence_aligns, _source_language_clauses
    source_by_id: dict[str, dict] = {}
    for receipt in (receipts_by_id[rid] for rid in receipt_ids if rid in receipts_by_id):
        parts = re.split(r"\bsource excerpts:\s*", receipt_evidence_text(receipt), maxsplit=1, flags=re.I)
        excerpt = " | ".join(filter(None, (parts[1] if len(parts) == 2 else "", *receipt.p_values,
                                                  receipt.population_summary)))
        source_by_id[receipt.receipt_id] = {"cited_as": "", "title": receipt.source_title or parts[0].rstrip(" -\u2014"), "population": receipt.population_summary, "quote": excerpt, "evidence_span": excerpt, "excerpt": excerpt, "outcome_class": receipt.outcome_class, "effect_direction": receipt.effect_direction, "directness": receipt.directness, "evidence_tier": receipt.evidence_tier}
    protected = _CONTINUING_ABBREVIATION_RE.sub(lambda match: match.group().replace(".", "<DOT>"), text)
    cited_ids = set(_INLINE_RECEIPT_RE.findall(text)) & source_by_id.keys() or set(receipt_ids)
    quoted = _normalize(_INLINE_RECEIPT_RE.sub(lambda match: "" if match[1] in source_by_id else match[0], text)).strip(' ."“”')
    if len(cited_ids) == 1 and any(quoted == _normalize(span).strip(' ."“”') for rid in cited_ids & source_by_id.keys()
           for parts in [re.split(r"\bsource excerpts:\s*", receipt_evidence_text(receipts_by_id[rid]), maxsplit=1, flags=re.I)]
           if len(parts) == 2 for span in parts[1].split(" | ") if len(span.strip()) >= 20):
        return None
    for sentence in _SENTENCE_BREAK_RE.split(protected):
        clean, sentence_ids = sentence.replace("<DOT>", ".").strip(), set(_INLINE_RECEIPT_RE.findall(sentence)) or set(receipt_ids)
        for clause in _source_language_clauses(clean):
            atom_ids = set(_INLINE_RECEIPT_RE.findall(clause)) or sentence_ids
            atom = _INLINE_RECEIPT_RE.sub("[bundle:1]", clause)
            if not any(_evidence_aligns(atom, source_by_id[rid], source_language=True) for rid in atom_ids if rid in source_by_id):
                return "source_grounding:" + ",".join(sorted(atom_ids))
    return None


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
    """Return paragraph entries, tolerating a bare single paragraph."""
    paragraphs = parsed.get("paragraphs")
    if isinstance(paragraphs, list):
        return paragraphs
    if parsed.get("text") or parsed.get("sentence"):
        return [dict(parsed)]
    return []


def _materialize_inline_receipts(text: str, receipt_ids: Sequence[str]) -> str:
    """Render missing canonical metadata inline without changing the claim."""
    if not text.strip() or not receipt_ids:
        return text
    inline_ids = _INLINE_RECEIPT_RE.findall(text)
    if any(receipt_id not in receipt_ids for receipt_id in inline_ids):
        return text

    if _has_internal_sentence_boundary(text):
        if len(set(receipt_ids)) != 1 or _AMBIGUOUS_ABBREVIATION_RE.search(text):
            return text
        protected = _CONTINUING_ABBREVIATION_RE.sub(
            lambda match: match.group().replace(".", "<DOT>"), text,
        )
        parts = re.split(f"({_SENTENCE_BREAK_RE.pattern})", protected)
        for index in range(0, len(parts), 2):
            parts[index] = _materialize_inline_receipts(parts[index], receipt_ids)
        return "".join(parts).replace("<DOT>", ".")
    missing = [rid for rid in receipt_ids if rid not in inline_ids]
    if not missing:
        return text
    text = text.rstrip()
    citations = " ".join(f"[{rid}]" for rid in missing)
    ending = re.search(r"([.!?][^\w\s]*)$", text)
    if not ending:
        return f"{text} {citations}"
    return f"{text[:ending.start()].rstrip()} {citations}{ending.group(1)}"


def _check_anchored_paragraph(
    text: str,
    receipt_ids: Sequence[str],
    accepted_ids: set[str],
    accepted_numerics: set[str],
    *,
    allow_numerics: bool = True,
    allow_uncited: bool = False,
) -> tuple[bool, str]:
    if not text.strip():
        return False, "empty_paragraph"
    cited = [r for r in receipt_ids if r in accepted_ids]
    if not cited and (not allow_uncited or _INLINE_RECEIPT_RE.search(text)):
        return False, f"no_accepted_anchor:{list(receipt_ids)}"
    inline = re.compile(r"(?<![A-Za-z0-9_-])(?:" + "|".join(map(re.escape, cited)) + r")(?![A-Za-z0-9_-])") if cited else re.compile(r"(?!)")
    protected = _CONTINUING_ABBREVIATION_RE.sub(
        lambda match: match.group().replace(".", "<DOT>"), text,
    )
    if cited and any(not inline.search(sentence) for sentence in _SENTENCE_BREAK_RE.split(protected)):
        return False, "missing_inline_anchor"
    for m in _NUMERIC_RE.finditer(inline.sub("", text)):
        tok = _numeric_token(m.group(0))
        if _is_bibliographic_year(text, m):
            continue
        if not allow_numerics:
            return False, f"novel_numeric:{tok!r}"
        if tok in accepted_numerics:
            continue
        return False, f"novel_numeric:{tok!r}"
    return True, "ok"


def _balanced_cross_domain_groups(
    records: Sequence[tuple[str, list[str], SynthesisClaimAnchor]],
    accepted_outcomes: Mapping[str, str],
) -> tuple[dict[str, tuple[list[str], list[str]]], list[SynthesisClaimAnchor]] | None:
    records = records[:54]
    if len(records) < 24:
        return None
    for group_count in range(4, 7):
        if not 5 * group_count <= len(records) <= 9 * group_count:
            continue
        base, extra = divmod(len(records), group_count)
        groups: dict[str, tuple[list[str], list[str]]] = {}
        kept: list[SynthesisClaimAnchor] = []
        offset = 0
        for index in range(1, group_count + 1):
            chunk = records[offset:offset + base + (index <= extra)]
            offset += len(chunk)
            ids = list(dict.fromkeys(rid for _, rids, _ in chunk for rid in rids))
            if len(ids) < 2 or len({accepted_outcomes[rid] for rid in ids}) < 2:
                break
            groups[str(index)] = ([text for text, _, _ in chunk], ids)
            kept.extend(anchor for _, _, anchor in chunk)
        else:
            return groups, kept
    return None


def _check_scoped_paragraph(
    text: str,
    receipt_ids: Sequence[str],
    accepted_ids: set[str],
    accepted_numerics: set[str],
) -> tuple[bool, str]:
    if not text.strip():
        return False, "empty_paragraph"
    cited = [receipt_id for receipt_id in receipt_ids if receipt_id in accepted_ids]
    if not cited:
        return False, f"no_accepted_anchor:{list(receipt_ids)}"
    for m in _NUMERIC_RE.finditer(text):
        tok = _numeric_token(m.group(0))
        if tok in accepted_numerics:
            continue
        if _is_bibliographic_year(text, m):
            continue
        return False, f"novel_numeric:{tok!r}"
    return True, "ok"


def build_anchored_from_parsed(
    parsed: dict,
    *,
    name: SectionName,
    heading: str,
    accepted: Sequence[ReceiptSummary],
    rejection_reasons: list[str] | None = None,
    reviewed: frozenset[tuple[str, tuple[str, ...]]] = frozenset(),
    author_numerics: frozenset[str] = frozenset(),
) -> SynthesisSection | None:
    accepted_ids = {r.receipt_id for r in accepted}
    accepted_by_id = {r.receipt_id: r for r in accepted}
    accepted_outcomes = {r.receipt_id: r.outcome_class for r in accepted}
    numeric_sources = {token: {r.receipt_id for r in accepted if token in _accepted_numeric_tokens([r])} for token in _accepted_numeric_tokens(accepted)}
    paragraphs = _paragraph_list(parsed)
    body_lines: list[str] = [heading, ""]
    anchors: list[SynthesisClaimAnchor] = []
    rejections: list[str] = []
    grouped: dict[str, tuple[list[str], list[str]]] = {}
    cross_domain_records: list[tuple[int | None, str, list[str], SynthesisClaimAnchor]] = []
    for entry in paragraphs:
        if not isinstance(entry, dict):
            continue
        text = entry.get("text") or entry.get("sentence") or ""
        rids = entry.get("receipt_ids") or []
        if not isinstance(text, str) or not isinstance(rids, list):
            continue
        # Repair one-character receipt-id drift before validation.
        original_rids = [str(r) for r in rids]
        repaired_rids, _repair_log = repair_receipt_ids(original_rids, accepted_ids)
        mapped_numerics = _accepted_numeric_tokens([accepted_by_id[rid] for rid in repaired_rids])
        for match in _NUMERIC_RE.finditer(text) if repaired_rids else ():
            token = _numeric_token(match.group(0))
            quantity = bool(re.search(r"[.%<=>A-Za-zµβ]", match.group(0)) or re.match(r"\s*(?:of\b|participants?|patients?|subjects?|people|adults?|children)\b", text[match.end():], re.I))
            candidate_ids = sorted(numeric_sources.get(token, set()) - set(repaired_rids))
            if (quantity and token not in mapped_numerics and not _is_bibliographic_year(text, match)
                    and not re.search(r"\b(?:fig(?:ure)?|table|equation|section|appendix)\s*$", text[:match.start()], re.I)
                    and len(candidate_ids) == 1 and not _source_grounding_reason(
                        _INLINE_RECEIPT_RE.sub("", text), candidate_ids, accepted_by_id)):
                old_markers = r"\[(?:" + "|".join(map(re.escape, original_rids)) + r")\]"
                text, repaired_rids = re.sub(old_markers, "", re.sub(old_markers, f"[{candidate_ids[0]}]", text, count=1)), candidate_ids
                break
        text = _materialize_inline_receipts(text, repaired_rids)
        mapped_receipts = [accepted_by_id[rid] for rid in repaired_rids if rid in accepted_by_id]
        source_reviewed = name == "abstract" and (text.strip(), tuple(sorted(repaired_rids))) in reviewed
        ok, reason = _check_anchored_paragraph(
            text, repaired_rids, accepted_ids, _accepted_numeric_tokens(mapped_receipts) | (set(author_numerics) if source_reviewed and not repaired_rids else set()),
            allow_numerics=name not in {"cross_domain_synthesis", "limitations_full"},
            allow_uncited=source_reviewed and not repaired_rids,
        )
        if not ok:
            rejections.append(reason)
            continue
        if not source_reviewed and name in {"abstract", "results"} and (
            grounding_reason := _source_grounding_reason(text, repaired_rids, accepted_by_id)
        ):
            rejections.append(grounding_reason)
            continue
        anchor = SynthesisClaimAnchor(
            sentence=text.strip(),
            receipt_ids=tuple(repaired_rids),
            numerics=tuple(
                _numeric_token(m.group(0))
                for m in _NUMERIC_RE.finditer(text)
            ),
        )
        paragraph_index = entry.get("paragraph_index")
        if name in {"cross_domain_synthesis", "limitations_full"}:
            if (
                Counter(_INLINE_RECEIPT_RE.findall(text)) != Counter(repaired_rids)
                or _has_internal_sentence_boundary(text)
            ):
                rejections.append("invalid_sentence_record_contract")
                continue
            max_index = 6 if name == "cross_domain_synthesis" else 4
            if (
                isinstance(paragraph_index, bool)
                or not isinstance(paragraph_index, int)
                or not 1 <= paragraph_index <= max_index
            ):
                rejections.append("invalid_sentence_record_contract")
                if name == "limitations_full":
                    continue
                paragraph_index = None
            if name == "cross_domain_synthesis":
                cross_domain_records.append((paragraph_index, text.strip(), repaired_rids, anchor))
        if paragraph_index is None:
            if name != "cross_domain_synthesis":
                body_lines.extend((text.strip(), "", f"  _Cited: {', '.join(f'`{i}`' for i in repaired_rids)}_", ""))
        else:
            group_text, group_ids = grouped.setdefault(str(paragraph_index), ([], []))
            group_text.append(text.strip())
            group_ids.extend(rid for rid in repaired_rids if rid not in group_ids)
        anchors.append(anchor)
    if name == "cross_domain_synthesis":
        index_counts = Counter(index for index, *_ in cross_domain_records if index is not None)
        valid_indices = {
            index for index, count in index_counts.items()
            if 5 <= count <= 9
            and len(grouped[str(index)][1]) >= 2
            and len({accepted_outcomes[rid] for rid in grouped[str(index)][1]}) >= 2
        }
        declared_layout_ok = (
            4 <= len(valid_indices) <= 6
            and sum(index_counts[index] for index in valid_indices) >= 24
        )
        if declared_layout_ok:
            anchors = [
                anchor for index, _, _, anchor in cross_domain_records
                if index in valid_indices
            ]
            grouped = {
                key: value for key, value in grouped.items()
                if int(key) in valid_indices
            }
        else:
            if "invalid_sentence_record_contract" not in rejections:
                rejections.append("invalid_sentence_record_contract")
            recovered = _balanced_cross_domain_groups(
                [(text, ids, anchor) for _, text, ids, anchor in cross_domain_records],
                accepted_outcomes,
            )
            grouped, anchors = recovered or ({}, [])
    for group_text, group_ids in grouped.values():
        body_lines.extend((
            " ".join(group_text), "",
            f"  _Cited: {', '.join(f'`{rid}`' for rid in group_ids)}_", "",
        ))
    if rejection_reasons is not None:
        rejection_reasons.extend(rejections)
    if not anchors:
        # Report the upstream cause before the caller emits its short fallback.
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


def _scoped_contract_failures(text: str, topic: str) -> list[str]:
    # Source/numeric checks validate each claim; final review judges calibration.
    # Repeated names and a hedge keyword establish neither relevance nor caution.
    aliases = _topic_aliases(topic)
    return [f"missing_topic_alias:{aliases[0]}"] if aliases and not any(
        re.search(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", text) for alias in aliases
    ) else []


def build_scoped_from_parsed(
    parsed: dict,
    *,
    name: SectionName,
    heading: str,
    topic: str,
    accepted: Sequence[ReceiptSummary],
    rejection_reasons: list[str] | None = None,
    allow_partial: bool = False,
    reviewed: frozenset[tuple[str, tuple[str, ...]]] = frozenset(),
) -> SynthesisSection | None:
    accepted_ids = {r.receipt_id for r in accepted}
    accepted_by_id = {r.receipt_id: r for r in accepted}
    paragraphs = _paragraph_list(parsed)
    body_lines: list[str] = [heading, ""]
    anchors: list[SynthesisClaimAnchor] = []
    rejections: list[str] = []
    for entry in paragraphs:
        if not isinstance(entry, dict):
            continue
        text = entry.get("text") or ""
        rids = entry.get("receipt_ids") or []
        if not isinstance(text, str) or not isinstance(rids, list):
            continue
        if any(_normalize(a.sentence) == _normalize(text) for a in anchors):
            continue
        # Day 10.17 Fix C.3: same fuzzy-id repair as anchored builder.
        repaired_rids, _repair_log = repair_receipt_ids(
            [str(r) for r in rids], accepted_ids,
        )
        mapped_receipts = [accepted_by_id[rid] for rid in repaired_rids if rid in accepted_by_id]
        text = _materialize_inline_receipts(text, repaired_rids)
        ok, reason = _check_scoped_paragraph(
            text, repaired_rids, accepted_ids, _accepted_numeric_tokens(mapped_receipts),
        )
        if not ok:
            rejections.append(reason)
            continue
        if name == "conclusion" and (text.strip(), tuple(sorted(repaired_rids))) not in reviewed and (
            grounding_reason := _source_grounding_reason(text, repaired_rids, accepted_by_id)
        ):
            rejections.append(grounding_reason)
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
    if rejection_reasons is not None:
        rejection_reasons.extend(rejections)
    if not anchors:
        if rejection_reasons is not None and not rejections:
            rejection_reasons.append("empty_or_invalid_paragraphs")
        return None
    section_text = _normalize(" ".join(anchor.sentence for anchor in anchors))
    contract_failures = _scoped_contract_failures(section_text, topic)
    if rejection_reasons is not None:
        rejection_reasons.extend(contract_failures)
    if contract_failures and not allow_partial:
        return None
    return SynthesisSection(
        name=name, body_md="\n".join(body_lines).rstrip() + "\n",
        anchors=tuple(anchors),
    )


def build_results_from_parsed(
    parsed: dict,
    *,
    accepted: Sequence[ReceiptSummary],
    rejection_reasons: list[str] | None = None,
) -> SynthesisSection | None:
    accepted_ids = {r.receipt_id for r in accepted}
    accepted_by_id = {r.receipt_id: r for r in accepted}
    # Group/resolve on the CANONICAL outcome key (outcome_key) so near-duplicate
    # classes (e.g. "immune" vs "immune_inflammation") collapse to one section,
    # matching the finalizer's _outcome_key routing. Idempotent for classes that
    # are already canonical.
    receipt_outcomes = {r.receipt_id: _receipt_outcome(r) for r in accepted}
    by_outcome: dict[str, list[ReceiptSummary]] = {}
    for receipt in accepted:
        by_outcome.setdefault(_receipt_outcome(receipt), []).append(receipt)
    body_lines: list[str] = ["## Results", ""]
    outcome_bodies: dict[str, list[str]] = {}
    anchors: list[SynthesisClaimAnchor] = []
    rendered_outcomes: set[str] = set()
    rejections: list[str] = []
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
            if (not isinstance(text, str) or not isinstance(rids, list)
                    or any(_normalize(a.sentence) == _normalize(text) for a in sub_anchors)):
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
            mapped_receipts = [accepted_by_id[rid] for rid in repaired_rids if rid in accepted_by_id]
            ids = "|".join(map(re.escape, repaired_rids))
            text = re.sub(rf'([.!?])(["”])(\s+\[(?:{ids})\])[.!?]?$', r'\2\3\1', text)
            ok, reason = _check_anchored_paragraph(
                text, repaired_rids, accepted_ids, _accepted_numeric_tokens(mapped_receipts),
            )
            if not ok:
                rejections.append(reason)
                continue
            if grounding_reason := _source_grounding_reason(text, repaired_rids, accepted_by_id):
                rejections.append(grounding_reason)
                continue
            if not sub_body:
                sub_body = [
                    f"### {_label_for_outcome(subsection_outcome)} Outcomes", "",
                ]
            cite_str = ", ".join(f"`{i}`" for i in repaired_rids)
            sub_body.extend((text.strip(), "", f"  _Cited: {cite_str}_", ""))
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
    if rejection_reasons is not None:
        rejection_reasons.extend(rejections)
    if rejections and not anchors:
        return None
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
