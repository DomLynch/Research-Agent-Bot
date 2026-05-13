from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True, slots=True)
class SurfaceIssue:
    code: str
    detail: str


@dataclass(frozen=True, slots=True)
class SurfaceReport:
    passed: bool
    issues: tuple[SurfaceIssue, ...]


_DASHES = {"", "-", "—", "–", "none", "n/a", "na"}
_BAD_ENDPOINTS = {"unknown", "background", "effect", "n/a", "none", "?"}
_PLACEHOLDER_PATTERNS = (
    "this paper evaluates the topic through accepted receipts", "the background is limited to corpus-supported context", "this synthesis aims to contribute to the field by", "the evidence base is limited to accepted receipts",
    "the conclusion is limited to claims that survive receipt qualification", "section generation cannot satisfy the validation contract", "generated section cannot satisfy the validation contract",
    "deterministic evidence summary", "deterministic synthesis summary", "llm proposes, code disposes", "no llm authorship", "accepted receipts contain source-traced quantitative evidence", "fallback stub used", "conservative placeholder",
    "the synthesis supports a bounded conclusion", "the topic has enough receipt-traced evidence", "enough accepted evidence to support a structured, receipt-bound synthesis", "read through its tiered profile", "### closing interpretation",
)
_META_PATTERNS = (
    "this synthesis was produced by", "submission `synthesis-", "final-layer reviewer", "patches are auto-applied", "rejected-evidence quarantine did not run",
    "full grok review", "run manifest", "bundle contains", "certification record",
    "tournament selector", "trust-spine", "grok", "a2a",
)
_PUBLIC_ARTIFACT_PATTERNS = (
    "<h3>", "</h3>", "### h3.", "### h3:", "rapamycin evidence should be interpreted",
    "source-context sentence cannot support", "the surviving section therefore",
    "risk-of-bias roll-up", "[d1_inferential_bridge", "accepted receipt graph",
    "manifest, tension matrix, and citation registry", "evidence-context framing",
    "should be read as", "### background references", "### final interpretation",
    "**thesis:**", "accepted receipt", "receipt set", "receipt graph",
    "mechanistic receipts", "direct clinical receipts", "indirect clinical receipts",
    "accepted corpus", "receipt", "with 's evidence", "with ’s evidence",
)
_REQUIRED_SECTIONS = {"Abstract": 150, "Introduction": 400, "Background": 300, "Methods": 300, "Results": 500, "Cross-Domain Synthesis": 850, "Discussion": 800, "Limitations": 250, "Conclusion": 250}
_SECTION_CEILINGS = {"Abstract": 300}
_APPENDIX_CUTOFF_RE = re.compile(r"^##\s+(?:Publication Appendix|Researka Submitter Block|Data and Code Availability|Search Provenance|AI(?:-Use)? Disclosure|Accountability|References)\b", flags=re.M)
_CITATION_ARTIFACT_RE = re.compile(r"\[(?:citation needed|source|ref|pmid|doi|TODO)[^\]]*\]|(?:^|\s)(?:PMID|DOI):?\s*$|<\s*(?:citation|ref)[^>]*>", re.IGNORECASE | re.MULTILINE)
_REFERENCE_DUMP_RE = re.compile(r"\b(?:DOI|PMID):\s*\S+", re.IGNORECASE)
_HEDGE_FRAGMENT_RE = re.compile(r"^(?:may|might|could|appears|suggests|uncertain|preliminary|context[- ]dependent|not definitive|requires confirmation)\.?$", re.IGNORECASE)
_MALFORMED_NUMERIC_RE = re.compile(r"(?<![\d,])0{2,}(?:\.\d+)?\s*(?:mg/day|mg|g|mcg|µg|μg|ng|kg|m/s|mmHg)\b", re.IGNORECASE)
_PUBLIC_SLUG_RE = re.compile(r"\b(?:[a-z][a-z0-9]*_[a-z0-9_]*|glp1|omega3)\b")
_QEI_HEADING_RE = re.compile(r"^##\s+Quantitative\s+Evidence\s+Index\b.*$", re.M)
_TABLE_REF_RE = re.compile(r"\bTable\s+(\d+)\b", re.IGNORECASE)


def evaluate_journal_surface(paper_md: str) -> SurfaceReport:
    issues: list[SurfaceIssue] = []
    body_md = _journal_body(paper_md)
    low = body_md.lower()
    qei_heads = list(_QEI_HEADING_RE.finditer(body_md))
    issues.extend(SurfaceIssue("placeholder_prose", pat) for pat in _PLACEHOLDER_PATTERNS if pat in low)
    issues.extend(SurfaceIssue("template_meta", pat) for pat in _META_PATTERNS if pat in low)
    issues.extend(SurfaceIssue("public_artifact", pat) for pat in _PUBLIC_ARTIFACT_PATTERNS if pat in low)
    issues.extend(SurfaceIssue("duplicate_paragraph", msg) for msg in _duplicate_paragraph_issue_messages(body_md))
    issues.extend(SurfaceIssue("citation_artifact", msg) for msg in _citation_artifact_issue_messages(body_md))
    issues.extend(SurfaceIssue("citation_artifact", f"public reference dump: {m.group(0)}") for m in _REFERENCE_DUMP_RE.finditer(body_md))
    issues.extend(SurfaceIssue("hedge_fragment", msg) for msg in _hedge_fragment_issue_messages(body_md))
    issues.extend(SurfaceIssue("malformed_numeric", f"malformed numeric artifact: {m.group(0).strip()}") for m in _MALFORMED_NUMERIC_RE.finditer(body_md))
    issues.extend(SurfaceIssue("topic_slug_artifact", f"public topic-slug artifact: {m.group(0)}") for m in _PUBLIC_SLUG_RE.finditer(body_md))
    issues.extend(SurfaceIssue("duplicate_heading", "duplicate consecutive Quantitative Evidence Index headings") for left, right in zip(qei_heads, qei_heads[1:]) if not body_md[left.end():right.start()].strip())
    if not re.search(r"^##\s+References\b", paper_md, flags=re.M):
        issues.append(SurfaceIssue("structure_surface", "missing required section: References"))
    issues.extend(SurfaceIssue("structure_surface", msg) for msg in _empty_heading_issue_messages(body_md))
    issues.extend(SurfaceIssue("structure_surface", msg) for msg in _results_outcome_section_issue_messages(body_md))
    issues.extend(SurfaceIssue("structure_surface", msg) for msg in _orphan_table_issue_messages(body_md))
    issues.extend(SurfaceIssue("structure_surface", msg) for msg in _section_issue_messages(body_md))
    issues.extend(SurfaceIssue("qei_surface", msg) for msg in _qei_shape_issue_messages(body_md))
    for row in _extract_qei_rows(body_md):
        issues.extend(SurfaceIssue("qei_surface", msg) for msg in qei_row_issue_messages(row))
    return SurfaceReport(passed=not issues, issues=tuple(issues))


def _journal_body(paper_md: str) -> str:
    m = _APPENDIX_CUTOFF_RE.search(paper_md)
    return paper_md[:m.start()] if m else paper_md


def is_publishable_qei_row(row: Any) -> bool:
    return not qei_row_issue_messages(_row_to_dict(row))


def qei_row_issue_messages(row: dict[str, str]) -> tuple[str, ...]:
    endpoint = _norm(row.get("endpoint", ""))
    value = _norm(row.get("value", ""))
    unit = _norm(row.get("unit_or_type", row.get("type", "")))
    stat = _norm(row.get("statistic", ""))
    study = row.get("study_label", row.get("study", "")).strip()
    issues: list[str] = []
    if endpoint in _BAD_ENDPOINTS:
        issues.append(f"unpublishable endpoint: {endpoint or 'blank'}")
    if value in _DASHES and unit in _DASHES and stat in _DASHES:
        issues.append(f"empty QEI row: {study or 'unknown study'}")
    if _malformed_study_id(study):
        issues.append(f"malformed study id: {study}")
    if _MALFORMED_NUMERIC_RE.search(f"{value} {unit} {stat}"):
        issues.append(f"malformed numeric artifact: {value} {unit}")
    unit_class = _unit_class(unit, value)
    endpoint_class = _endpoint_class(endpoint)
    if endpoint_class and unit_class:
        allowed = _ALLOWED_UNIT_CLASSES[endpoint_class]
        if unit_class not in allowed:
            issues.append(
                f"endpoint/unit mismatch: {endpoint} cannot use {unit}",
            )
    return tuple(issues)


def _extract_qei_rows(paper_md: str) -> Iterable[dict[str, str]]:
    m = re.search(r"^## Quantitative Evidence Index\b.*?\n(.*?)(?=^## |\Z)", paper_md, flags=re.M | re.S)
    if not m:
        return ()
    rows: list[dict[str, str]] = []
    for line in m.group(1).splitlines():
        if not line.startswith("|") or "---" in line:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells[:6] == ["Study", "Endpoint", "Arm", "Value", "Type", "Statistic"]:
            continue
        if len(cells) >= 6:
            rows.append({"study_label": cells[0], "endpoint": cells[1], "arm": cells[2], "value": cells[3], "unit_or_type": cells[4], "statistic": cells[5]})
    return tuple(rows)


def _qei_shape_issue_messages(paper_md: str) -> tuple[str, ...]:
    m = re.search(r"^## Quantitative Evidence Index\b.*?\n(.*?)(?=^## |\Z)", paper_md, flags=re.M | re.S)
    if not m:
        return ()
    issues: list[str] = []
    expected = 6
    for line in m.group(1).splitlines():
        if not line.startswith("|") or "---" in line:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells[:6] == ["Study", "Endpoint", "Arm", "Value", "Type", "Statistic"]:
            continue
        if len(cells) != expected:
            issues.append(f"malformed QEI row cell count: {line.strip()}")
    return tuple(issues)


def _section_issue_messages(paper_md: str) -> tuple[str, ...]:
    issues: list[str] = []
    for heading, floor in _REQUIRED_SECTIONS.items():
        body = _section_body(paper_md, heading)
        if body is None:
            issues.append(f"missing required section: {heading}")
            continue
        n = len(re.findall(r"\b\w+\b", body))
        if n < floor:
            issues.append(f"section too short: {heading} {n}/{floor} words")
        ceiling = _SECTION_CEILINGS.get(heading)
        if ceiling is not None and n > ceiling:
            issues.append(f"section too long: {heading} {n}/{ceiling} words")
    return tuple(issues)


def _empty_heading_issue_messages(paper_md: str) -> tuple[str, ...]:
    matches = list(re.finditer(r"^(#{2,6})\s+(.+?)\s*$", paper_md, flags=re.M))
    issues: list[str] = []
    for idx, match in enumerate(matches):
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(paper_md)
        if not paper_md[match.end():end].strip():
            issues.append(f"empty heading: {match.group(2).strip()}")
    return tuple(issues)


def _results_outcome_section_issue_messages(paper_md: str) -> tuple[str, ...]:
    results = _section_body(paper_md, "Results")
    if not results:
        return ()
    outcomes = _outcome_classes_from_results_table(results)
    if not outcomes:
        return ()
    h3s = [m.group(1) for m in re.finditer(r"^###\s+(.+?)\s*$", results, flags=re.M)]
    missing = [outcome for outcome in outcomes if not _has_matching_outcome_heading(outcome, h3s)]
    return tuple(f"missing Results outcome section: {outcome}" for outcome in missing)


def _outcome_classes_from_results_table(results: str) -> tuple[str, ...]:
    lines = [line.strip() for line in results.splitlines()]
    for idx, line in enumerate(lines):
        if not line.startswith("|"):
            continue
        cells = _table_cells(line)
        if not cells or _norm(cells[0]) != "outcome class":
            continue
        outcomes: list[str] = []
        for row in lines[idx + 2:]:
            if not row.startswith("|"):
                break
            row_cells = _table_cells(row)
            if row_cells:
                outcomes.append(row_cells[0])
        return tuple(outcomes)
    return ()


def _table_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _has_matching_outcome_heading(outcome: str, headings: Iterable[str]) -> bool:
    outcome_tokens = _outcome_tokens(outcome)
    return any(outcome_tokens <= _outcome_tokens(heading) for heading in headings)


def _outcome_tokens(text: str) -> set[str]:
    stop = {"and", "or", "outcome", "outcomes", "endpoint", "endpoints"}
    return {t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in stop}


def _orphan_table_issue_messages(paper_md: str) -> tuple[str, ...]:
    defined = {
        number
        for m in re.finditer(
            r"^(?:#{2,6}\s+Table\s+(\d+)\b|Table\s+(\d+)\s*[:.\-—])",
            paper_md,
            flags=re.IGNORECASE | re.MULTILINE,
        )
        for number in m.groups()
        if number
    }
    missing = sorted(
        {m.group(1) for m in _TABLE_REF_RE.finditer(paper_md) if m.group(1) not in defined},
        key=int,
    )
    return tuple(f"orphan table reference: Table {n}" for n in missing)


def _duplicate_paragraph_issue_messages(paper_md: str) -> tuple[str, ...]:
    paras: list[tuple[int, set[str]]] = []
    for para in re.split(r"\n\s*\n", paper_md):
        text = para.strip()
        if not text or text.startswith(("#", "|", "_Cited:")):
            continue
        tokens = re.findall(r"[a-z0-9]+", text.lower())
        real_tokens = {t for t in tokens if not re.fullmatch(r"word\d+", t)}
        if len(tokens) >= 30 and len(real_tokens) >= 20:
            paras.append((len(paras) + 1, set(tokens)))
    issues: list[str] = []
    for idx, left in enumerate(paras):
        for right in paras[idx + 1:]:
            overlap = len(left[1] & right[1]) / max(1, len(left[1] | right[1]))
            if overlap >= 0.9:
                issues.append(
                    f"duplicate paragraphs {left[0]},{right[0]} token_overlap={overlap:.2f}"
                )
    return tuple(issues)


def _citation_artifact_issue_messages(paper_md: str) -> tuple[str, ...]:
    return tuple(f"citation artifact: {m.group(0).strip()}" for m in _CITATION_ARTIFACT_RE.finditer(paper_md))


def _hedge_fragment_issue_messages(paper_md: str) -> tuple[str, ...]:
    issues: list[str] = []
    for idx, paragraph in enumerate(re.split(r"\n\s*\n", paper_md), start=1):
        text = re.sub(r"\s+", " ", paragraph.strip())
        if text and len(re.findall(r"[a-z0-9]+", text.lower())) <= 4 and _HEDGE_FRAGMENT_RE.match(text):
            issues.append(f"standalone hedge fragment paragraph {idx}: {text}")
    return tuple(issues)


def _section_body(paper_md: str, heading: str) -> str | None:
    m = re.search(rf"^##\s+{re.escape(heading)}\b.*?\n(.*?)(?=^##\s+|\Z)", paper_md, flags=re.M | re.S)
    return m.group(1) if m else None


def _row_to_dict(row: Any) -> dict[str, str]:
    if isinstance(row, dict):
        return {str(k): str(v) for k, v in row.items()}
    keys = ("study_label", "endpoint", "arm", "value", "unit_or_type", "statistic")
    return {key: str(getattr(row, key, "")) for key in keys}


def _malformed_study_id(study: str) -> bool:
    pattern = r"\b(?:19|20)\d{2}[a-z]{2,}$" if "_" not in study else r"(?:_\w{1,5}|_+)$"
    return bool(re.search(pattern, study))


def _endpoint_class(endpoint: str) -> str:
    checks = (
        ("event", ("mortality", "survival", "death", "incident")), ("pressure", ("blood pressure", "systolic", "diastolic")), ("bmi", ("body mass index", "bmi")),
        ("biomarker", ("glucose", "hba1c", "cholesterol", "ldl", "hdl", "triglyceride", "insulin", "crp", "biomarker", "inflammation")),
        ("renal", ("egfr", "kidney", "renal", "glomerular")), ("speed", ("walk speed", "gait speed", "walking speed")), ("mass", ("body weight", "lean mass", "fat mass", "muscle mass")),
        ("strength", ("strength", "grip", "force")), ("scale", ("frailty", "score", "index", "cognition")),
    )
    for cls, needles in checks:
        if any(n in endpoint for n in needles):
            return cls
    return ""


def _unit_class(unit: str, value: str) -> str:
    hay = f"{unit} {value}".lower()
    if unit in _DASHES:
        return ""
    if "sample size" in hay or re.search(r"\bn\s*=", hay):
        return "count"
    if "p value" in hay or re.search(r"\bp\s*[<=>]", hay):
        return "p_value"
    if "95%ci" in hay or "confidence interval" in hay:
        return "ci"
    if "hazard ratio" in hay or "odds ratio" in hay or "risk ratio" in hay:
        return "ratio"
    if "%" in hay or "percentage" in hay:
        return "percentage"
    if "kg/m2" in hay or "kg/m²" in hay:
        return "bmi_unit"
    if "mg/dl" in hay or "mmol/l" in hay or "ng/ml" in hay:
        return "concentration"
    if re.search(r"\bml\s*/\s*min\b", hay):
        return "renal_rate"
    if unit in {"ml", "l"}:
        return "volume"
    if unit in {"mg", "g", "mcg", "µg", "μg", "ng"}:
        return "dose"
    if "mmhg" in hay:
        return "pressure"
    if "m/s" in hay:
        return "speed"
    if re.search(r"\b(years?|months?|weeks?|days?|hours?)\b", hay):
        return "duration"
    if re.search(r"\b(?:cm|mm)\b", hay):
        return "length"
    if re.search(r"\bkg\b", hay):
        return "mass"
    if "mean sd" in hay:
        return "summary_stat"
    return ""


def _norm(s: str) -> str:
    return str(s or "").strip().lower().replace(" ", " ")


_COMMON = {"count", "p_value", "ci", "ratio", "percentage", "summary_stat"}
_ALLOWED_UNIT_CLASSES = {
    "event": _COMMON,
    "pressure": _COMMON | {"pressure"},
    "bmi": _COMMON | {"bmi_unit"},
    "biomarker": _COMMON | {"concentration"},
    "renal": _COMMON | {"renal_rate"},
    "speed": _COMMON | {"speed"},
    "mass": _COMMON | {"mass"},
    "strength": _COMMON | {"mass"},
    "scale": _COMMON,
}
