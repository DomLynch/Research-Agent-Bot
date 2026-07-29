"""Deterministic source binding for reviewer-requested major-claim traces."""
from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from agent.endpoint_evidence import endpoint_key
from agent.outcome_class_remap import BIOMEDICAL_OTHER_OUTCOME_RULES, outcome_key
from agent.publication_evidence import attach_bundle_references, ordered_source_rows

_TRACE_LINE_RE = re.compile(r"^- \*\*Manuscript claim (?P<number>\d+)\.\*\* (?P<claim>.*?) \*\*Supporting source:\*\* (?P<support>.*?\[bundle:(?P<bundle>\d+)\].*?) \*\*Evidence span:\*\* (?P<span>.+)$", re.I | re.M)
_ABBREVIATION_RE = re.compile(r"\b(?:vs|e\.g|i\.e|et al)\.", re.I)
_RESULT_SIGNAL_RE = re.compile(r"\b(?:lower(?:s|ed|ing)?|decreas(?:e[sd]?|ing)|improv(?:e[sd]?|ing|ement|ements)|increas(?:e[sd]?|ing)|reduc(?:e[sd]?|ing|tion|tions)|unchanged|differ(?:ed|ence|ences)|associated|association)\b|\b(?:no|not|statistically)\s+significant\b|\bdid not (?:change|decrease|improve|increase|reduce)\b|\b(?:better|worse)\b.{0,80}\b(?:than|compared (?:with|to))\b", re.I)
_STATISTIC_RE = re.compile(r"(?i:\bp\s*[<=>]\s*\.?\d|\b(?:confidence interval|ci|md|smd|wmd|rr|hr)\s*(?::|=)?\s*-?\.?\d|\d+(?:\.\d+)?\s*%)|\b(?:OR|(?i:odds ratio))\s*(?::|=)?\s*-?\.?\d")
_EFFECT_ESTIMATE_RE = re.compile(r"\b(?:beta|β)\s*[:=]?\s*-?\d+(?:\.\d+)?|(?<!\w)-?\d+(?:\.\d+)?\s*(?:kg(?:\s*/\s*m\s*2)?|mm\s*hg|mg\s*/\s*dL|mmol\s*/\s*L|mol\s*%)\b|\bfrom\s+-?\d+(?:\.\d+)?\s+to\s+-?\d+(?:\.\d+)?\b", re.I)
_QUALITATIVE_RESULT_RE = re.compile(r"\b(?:achiev(?:e[ds]?|ing)\s+(?:a\s+)?better|associated with|significant(?:ly)?\s+(?:decreas|improv|increas|reduc)|show(?:s|ed)?\s+(?:a\s+)?(?:significant(?:ly)?\s+)?(?:benefit|decreas(?:e|es)|improvement|increase|reduction)|(?:no|not)\s+significant|did not (?:change|decrease|improve|increase|reduce))\b", re.I)
_PROCEDURAL_RE = re.compile(r"\b(?:allocat(?:e[sd]?|ing|ions?)|assign(?:s|ed|ing|ments?)?|at baseline|baseline\b.{0,80}\b(?:is|are|was|were|differ(?:ed|ent)?|increas(?:e[sd]?|ing)|decreas(?:e[sd]?|ing))|calibrat(?:e[ds]?|ing|ion)|candidate (?:coverage|pool)|dos(?:e|es|ing)|dosages?|enrollment|index selection|literature search|primary outcomes? (?:chosen|selected)|recommend(?:ation|ations|ed)?|records? (?:identified|screened)|regimens?|search (?:increased|strategy)|secondary outcomes? (?:chosen|selected)|sample size|titrat(?:e|ed|ing|ions?)|(?:measurement|visit) frequency|aim(?:s|ed)? to|(?:aim|objective|purpose|sought)\b.{0,80}\b(?:whether|determine|examine|evaluate|assess|investigate|test)|(?:to|designed to)\s+(?:determine|examine|evaluate|assess|investigate|test)\s+whether|(?:hypothesis|hypothesi[sz]ed)\b.{0,50}\b(?:that|whether)|(?:examined|evaluated|assessed|investigated|tested) whether|evaluate whether|(?:assay|instrument|model)\b.{0,80}\b(?:sensitivity|specificity|performance|validat)|during validation|quantitative analysis was performed|standardized mean differences?\b.{0,120}\bcompare outcomes)\b", re.I)
_AMBIGUOUS_TRACE_TERMS = frozenset({"chronic", "dose", "dosing", "prevalence", "safety", "serum", "status"})
_TRACE_ENDPOINT_ALIASES = {"blood glucose": ("glucose", "glycemic", "glycaemic"), "blood pressure": ("bp", "sbp", "dbp", "systolic blood pressure", "diastolic blood pressure"), "body mass index": ("bmi",), "body weight": ("weight",), "inflammation": ("inflammatory", "c reactive protein", "crp"), "insulin sensitivity": ("homa ir",), "lean body mass": ("lean mass", "fat free mass", "ffm")}
_TRACE_OUTCOME_ALIASES = {"cardiometabolic": ("bmi", "cholesterol", "glucose", "glycemic", "hba1c", "hepatic", "insulin", "lipid", "liver stiffness", "steatosis", "triglyceride", "waist", "weight"), "immune_inflammation": ("c-reactive protein", "crp", "interleukin", "tnf", "malondialdehyde", "mda", "glutathione peroxidase")}
_PROTECTED_PERIOD = "\ue000"
_NON_CLAIM_PREFIXES = ("Evidence-type reconciliation:", "Source-direction reconciliation (", "Source-statistic reconciliation (", "Source-scope boundary (")


def asks_major_claim_trace(text: str) -> bool:
    tokens = ("exact source token", "doi/pmid", "doi or pmid", "evidence span", "exactly traceable")
    return "major claim" in text and any(token in text for token in tokens)


def major_claim_trace_is_stated(paper_md: str, ask: str, rows: Sequence[dict[str, Any]]) -> bool:
    rows = _ordered_rows(rows)
    if "exactly traceable" in ask.casefold():
        valid = {key for key, _number, statement in _source_owned_results(rows) if _source_owned_result_is_stated(statement, paper_md)}
        return len(valid) >= _requested_count(ask, len(valid))
    source_claims = _source_bound_claims(_without_trace(paper_md), rows)
    return len({claim for claim, _number, _row in source_claims if _claim_is_fully_traced(claim, rows)}) >= _requested_count(ask, len(source_claims))


def major_claim_trace_capacity(ask: str, rows: Sequence[dict[str, Any]]) -> tuple[int, int] | None:
    if "exactly traceable" not in ask.casefold():
        return None
    available = {key for key, _number, _statement in _source_owned_results(_ordered_rows(rows))}
    return len(available), _requested_count(ask, len(available))


def strip_validated_trace_support(paper_md: str, rows: Sequence[dict[str, Any]]) -> str:
    rows = _ordered_rows(rows)
    statements = {statement for _key, _number, statement in _source_owned_results(rows)}
    parts = re.split(r"(\n\s*\n)", paper_md)
    for index in range(0, len(parts), 2):
        if " ".join(parts[index].split()) in statements:
            parts[index] = "Validated source-owned result trace."
    paper_md = "".join(parts)
    source_bound_claims = {(claim, number) for claim, number, _row in _source_bound_claims(paper_md, rows)}
    def replace(match: re.Match[str]) -> str:
        claim, number = match.group("claim").strip(), int(match.group("bundle"))
        if not 1 <= number <= len(rows):
            return match.group(0)
        row = rows[number - 1]
        support = f"{_label(row)} [bundle:{number}]" + (f" {_stable_locator(row)}" if _stable_locator(row) else "")
        valid = _evidence_span(row) and (claim, number) in source_bound_claims and f"[bundle:{number}]" in claim and match.group("support").strip() == support and match.group("span").strip() == _evidence_span(row)
        return f"- **Manuscript claim {match.group('number')}.** {claim} **Supporting source:** validated manifest source." if valid else match.group(0)
    return _TRACE_LINE_RE.sub(replace, paper_md)


def repair_major_claim_trace(paper_md: str, ask: str, rows: Sequence[dict[str, Any]]) -> tuple[str, int]:
    rows = _ordered_rows(rows)
    patched = attach_bundle_references(re.sub(r"\s*\(evidence anchor:\s*.*?\s+\[bundle:\d+\]\)(?:\s*\[exact source:\s*https?://[^\]]+\])?", "", re.sub(r"(?ms)^### Source-Traced Findings\b.*?(?=^## |\Z)", "", _without_trace(paper_md)), flags=re.I), rows)
    claims = _source_bound_claims(patched, rows)
    for claim, _bundle_number, _row in claims:
        traced = claim
        for number in _bundle_numbers(claim, len(rows)):
            locator = _stable_locator(rows[number - 1])
            if locator and not _locator_is_stated(traced, locator):
                traced = _append_inline_locator(traced, locator)
        if traced != claim:
            patched = patched.replace(claim, traced, 1)
    patched = _add_source_trace_findings(patched, rows, ask)
    return patched, int(patched != paper_md)


def _add_source_trace_findings(paper_md: str, rows: Sequence[dict[str, Any]], ask: str) -> str:
    if "exactly traceable" in ask.casefold():
        valid = [(key, number) for key, number, statement in _source_owned_results(rows) if _source_owned_result_is_stated(statement, paper_md)]
        findings = {key: "" for key, _number in valid}
    else:
        valid = [(claim, number) for claim, number, _row in _source_bound_claims(paper_md, rows) if _claim_is_fully_traced(claim, rows)]
        findings = {_claim_key(claim, rows): "" for claim, _number in valid}
    missing = _requested_count(ask, len(rows)) - len(findings)
    if missing <= 0:
        return paper_md
    used = {number for _claim, number in valid}
    candidates: list[tuple[bool, bool, bool, int, int, str, str, str]] = []
    for number, row in enumerate(rows, 1):
        label, locator = _label(row), _stable_locator(row)
        if label and locator and row.get("thesis_text"):
            candidates.extend((number in used, str(row.get("directness") or "").lower() != "direct", not str(row.get("evidence_tier") or "").upper().startswith("A"), depth, number, label, locator, span) for depth, span in enumerate(_result_spans(row)))
    added = 0
    for _used, _indirect, _lower_tier, _depth, number, label, locator, span in sorted(candidates):
        if (key := _claim_key(span, rows)) in findings:
            continue
        findings[key] = f"{label} [bundle:{number}] reports: {span} [exact source: {locator}]."
        added += 1
        if added >= missing:
            break
    block = "### Source-Traced Findings\n\n" + "\n\n".join(value for value in findings.values() if value)
    return re.sub(r"(?ms)(^## Results\b.*?)(?=^## |\Z)", lambda match: match.group(1).rstrip() + "\n\n" + block + "\n\n", paper_md, count=1) if any(findings.values()) else paper_md


def _append_inline_locator(claim: str, locator: str) -> str:
    return f"{claim} [exact source: {locator}]" if not (terminal := re.search(r"""[.!?](?:["')\]]|\*{1,2}|_{1,2})*$""", claim)) else f"{claim[:terminal.start()]} [exact source: {locator}]{claim[terminal.start():]}"


def _requested_count(ask: str, available: int) -> int:
    return max(1, int(match.group(1)) if (match := re.search(r"\brequired\s+(\d+)\b", ask, re.I)) else min(16, available))


def _claim_key(claim: str, rows: Sequence[dict[str, Any]] = ()) -> str:
    claim = re.sub(labels, "", claim, flags=re.I) if (labels := "|".join(sorted((re.escape(_label(row)) for row in rows if _label(row)), key=len, reverse=True))) else claim
    text = re.sub(r"^.*?\[bundle:\d+\]\s+reports:\s*|\[exact source:\s*https?://[^\]]+\]|\[bundle:\d+\]", "", claim, flags=re.I)
    text = re.sub(r"^\s*(?:(?:the )?(?:study|authors?|investigators?|results?)\s+)?(?:reports?|reported|found|showed|observed|revealed)(?:\s+that|:)?\s+", "", text, flags=re.I)
    return " ".join(re.sub(r"\W+", " ", text.casefold()).split())


def _result_spans(row: dict[str, Any]) -> list[str]:
    if str(row.get("directness") or "").lower() == "protocol" or str(row.get("evidence_tier") or "").upper().startswith("D"):
        return []
    endpoints = {key for value in row.get("endpoints") or () if (key := endpoint_key(value))}
    endpoint_terms = endpoints | {endpoint_key(alias) for endpoint in endpoints for alias in _TRACE_ENDPOINT_ALIASES.get(endpoint, ())}
    endpoint_acronyms = {"".join(word[0] for word in value.split()).upper() for value in endpoints}
    outcome = outcome_key(str(row.get("outcome_class") or ""))
    outcome_terms = next((tuple(term for term in terms if endpoint_key(term) not in _AMBIGUOUS_TRACE_TERMS) for label, terms in BIOMEDICAL_OTHER_OUTCOME_RULES if label == outcome), ()) + _TRACE_OUTCOME_ALIASES.get(outcome, ())
    groups: tuple[list[str], list[str]] = ([], [])
    seen: set[str] = set()
    for part in re.split(r"source excerpts:\s*", str(row.get("thesis_text") or ""), maxsplit=1, flags=re.I)[-1].split("|"):
        for sentence in _sentences(part.strip()):
            for clause in re.split(r";\s*|,\s*(?=(?:while|whereas|but)\b)", sentence, flags=re.I):
                normalized = endpoint_key(clause)
                if not (_RESULT_SIGNAL_RE.search(clause) and not _PROCEDURAL_RE.search(clause) and (_STATISTIC_RE.search(clause) or _EFFECT_ESTIMATE_RE.search(clause) or _QUALITATIVE_RESULT_RE.search(clause))):
                    continue
                span = _evidence_span({"thesis_text": clause}).strip().rstrip(" .!?")
                if len(span) < 20 or re.search(r"\b(?:compared (?:to|with)|versus|vs)\.?\s*$", span, re.I) or (key := _claim_key(span, [row])) in seen:
                    continue
                matched = any(re.search(rf"\b{re.escape(value)}\b", normalized) for value in endpoint_terms) or any(len(initials) >= 2 and re.search(rf"\b(?:[SD])?{'[^A-Za-z0-9]*'.join(initials)}\b", clause) for initials in endpoint_acronyms)
                if not matched and (not any(re.search(rf"\b{re.escape(endpoint_key(term))}\b", normalized) for term in outcome_terms) or str(row.get("directness") or "").lower() != "direct" or not str(row.get("evidence_tier") or "").upper().startswith("A") or not (_STATISTIC_RE.search(clause) or _EFFECT_ESTIMATE_RE.search(clause))):
                    continue
                seen.add(key)
                groups[int(not matched)].append(span)
    return groups[0] + groups[1]


def _without_trace(paper_md: str) -> str:
    return re.sub(r"^## Major Claim Trace\b.*?(?=^## |\Z)", "", paper_md, count=1, flags=re.M | re.S | re.I)


def _sentences(text: str) -> list[str]:
    protected = _ABBREVIATION_RE.sub(lambda match: match.group(0)[:-1] + _PROTECTED_PERIOD, text)
    return [claim.replace(_PROTECTED_PERIOD, ".") for claim in re.split(r"(?:(?<=[.!?])|(?<=[.!?][\"')\]]))\s+(?=(?:[\"'(\[]|\*{1,2}|_{1,2})?[A-Z0-9])", protected)]


def _bundle_numbers(claim: str, row_count: int) -> list[int]:
    values = (int(value) for value in re.findall(r"\[bundle:(\d+)\]", claim, re.I))
    return list(dict.fromkeys(value for value in values if 1 <= value <= row_count))


def _claim_is_fully_traced(claim: str, rows: Sequence[dict[str, Any]]) -> bool:
    return bool((numbers := _bundle_numbers(claim, len(rows))) and all((locator := _stable_locator(rows[number - 1])) and _locator_is_stated(claim, locator) for number in numbers))


def _source_owned_results(rows: Sequence[dict[str, Any]]) -> list[tuple[str, int, str]]:
    results: list[tuple[str, int, str]] = []
    for number, row in enumerate(rows, 1):
        label, locator = _label(row), _stable_locator(row)
        if label and locator:
            results.extend(
                (key, number, f"{label} [bundle:{number}] reports: {span} [exact source: {locator}].")
                for span in _result_spans(row) if (key := _claim_key(span, [row]))
            )
    return results


def _source_owned_result_is_stated(statement: str, paper_md: str) -> bool:
    return any(" ".join(paragraph.split()) == statement for paragraph in re.split(r"\n\s*\n", paper_md))


def _locator_is_stated(claim: str, locator: str) -> bool:
    return f"[exact source: {locator}]" in claim or f"]({locator})" in claim or bool(
        re.search(rf"(?<!\S){re.escape(locator)}(?=\s|$)", claim)
    )


def _source_bound_claims(paper_md: str, rows: Sequence[dict[str, Any]]) -> list[tuple[str, int, dict[str, Any]]]:
    claims: list[tuple[int, int, str, int, dict[str, Any]]] = []
    section = ""
    seen: set[str] = set()
    for order, line in enumerate(_without_trace(paper_md).splitlines()):
        if heading := re.match(r"^##+\s+(.+?)\s*$", line):
            section = heading.group(1).strip().lower()
            continue
        stripped = " ".join(line.split())
        if (
            section == "references"
            or len(stripped) < 40
            or stripped.startswith(("#", "|", "```", "- "))
            or stripped.startswith(_NON_CLAIM_PREFIXES)
        ):
            continue
        for claim in _sentences(stripped):
            claim = _drop_unmatched_parentheses(claim)
            candidates = _bundle_numbers(claim, len(rows))
            if not candidates:
                continue
            bundle_number = min(candidates, key=lambda number: (
                str(rows[number - 1].get("directness") or "").lower() != "direct",
                not str(rows[number - 1].get("evidence_tier") or "").upper().startswith("A"),
                number,
            ))
            key = _claim_key(claim, [rows[number - 1] for number in candidates])
            if key in seen:
                continue
            seen.add(key)
            priority = 0 if any(token in section for token in (
                "result", "outcome", "synthesis", "conclusion", "what this synthesis adds",
            )) else 1
            claims.append((priority, order, claim, bundle_number, rows[bundle_number - 1]))
    ordered = [(claim, number, row) for _, _, claim, number, row in sorted(claims)]
    first: dict[int, tuple[str, int, dict[str, Any]]] = {}
    for item in ordered:
        first.setdefault(item[1], item)
    return list(first.values()) + [item for item in ordered if item is not first[item[1]]]


def _ordered_rows(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    return ordered_source_rows(list(rows), {str(row.get("receipt_id") or ""): row for row in rows})


def _label(row: dict[str, Any]) -> str:
    return str(row.get("citation_token") or row.get("cited_as") or row.get("body_citation") or row.get("receipt_id") or "").strip()


def _evidence_span(row: dict[str, Any]) -> str:
    text = " ".join(str(row.get("thesis_text") or row.get("source_title") or "").split())
    if "source excerpts:" in text.lower():
        text = re.split(r"source excerpts:\s*", text, maxsplit=1, flags=re.I)[1]
    text = text.split(" | ", 1)[0].replace("|", " ").strip()
    upstream_truncated = text.endswith(("...", "\u2026"))
    if upstream_truncated:
        text = text.removesuffix("\u2026").removesuffix("...").rstrip()
    if upstream_truncated or len(text) > 320:
        suffix = " [excerpt truncated]."
        limit = 320 - len(suffix)
        prefix = text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0]
        text = (prefix or text[:limit]).rstrip(" ,;:") + suffix
    return _drop_unmatched_parentheses(text)


def _drop_unmatched_parentheses(text: str) -> str:
    open_positions: list[int] = []
    remove: set[int] = set()
    for index, character in enumerate(text):
        if character == "(":
            open_positions.append(index)
        elif character == ")" and open_positions:
            open_positions.pop()
        elif character == ")":
            remove.add(index)
    remove.update(open_positions)
    return "".join(character for index, character in enumerate(text) if index not in remove)


def _stable_locator(row: dict[str, Any]) -> str:
    doi = str(row.get("source_doi") or row.get("doi") or "").strip()
    return "https://doi.org/" + re.sub(r"^(?:doi:\s*|https?://(?:dx\.)?doi\.org/)", "", doi, flags=re.I) if doi else f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if (pmid := str(row.get("source_pmid") or row.get("pmid") or "").strip()) else ""
