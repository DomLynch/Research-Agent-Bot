from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable

from agent.outcome_class_remap import outcome_key
from agent.review_type import COMPACT_REVIEW_TYPES


def _fold(text: str) -> str:
    """NFKD-fold + strip combining marks + casefold. Universal — turns
    Hernández/HERNÁNDEZ/hernandez into one comparable form. Used by the
    unreferenced-citation check so an inline cite with diacritics and a
    reference list entry without them still match (or vice versa)."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).casefold()


# Bug-fix 2026-05-14: animal/preclinical citations blended into human
# evidence prose without species framing is a journal desk-reject
# class. Universal keyword set — no per-topic table; covers organism
# names + veterinary-journal markers.
_ANIMAL_KEYWORD_RE = re.compile(
    r"\b("
    r"mice|murine|mouse|rats?|rodents?|"
    r"equids?|equine|horses?|"
    r"primates?|monkeys?|macaques?|baboons?|"
    r"dogs?|canine|cats?|feline|"
    r"swine|porcine|piglets?|pigs?|"
    r"sheep|ovine|cattle|bovine|"
    r"zebrafish|c\.\s*elegans|drosophila|yeast|nematodes?|"
    r"veterinary|preclinical|animal\s+model"
    r")\b",
    re.IGNORECASE,
)
# Phrases that, when present in the same paragraph as an animal-lane
# citation, signal the author has explicitly framed the evidence as
# non-human. The check is intentionally generous — any one of these
# qualifies the paragraph as lane-labelled. Slice 26 (2026-05-15):
# centralised on `agent.evidence_lanes.lane_qualifier_phrases_for` so
# the gate and Phase B agree on a single source of truth (was: two
# duplicate tuples that drifted).
def _animal_lane_qualifiers() -> tuple[str, ...]:
    from agent.evidence_lanes import lane_qualifier_phrases_for
    return lane_qualifier_phrases_for("animal_preclinical")


# Slice 26: word-boundary match avoids "rat" matching "iterate" / "horse"
# matching "horsepower". Compiled lazily because the tuple comes from
# `lane_qualifier_phrases_for` at first call.
_ANIMAL_LANE_RE: "re.Pattern[str] | None" = None


def _animal_lane_re() -> "re.Pattern[str]":
    global _ANIMAL_LANE_RE
    if _ANIMAL_LANE_RE is None:
        terms = sorted(_animal_lane_qualifiers(), key=len, reverse=True)
        # Slice 26: `s?` suffix handles English plurals universally
        # ("equid"→"equids", "rodent"→"rodents", "primate"→"primates")
        # without inflating the qualifier list with each plural form.
        # Safe for adjectives + multi-word terms: "in vivos" / "preclinicals"
        # are not English words so the trailing `s?` never false-matches.
        _ANIMAL_LANE_RE = re.compile(
            r"\b(?:" + "|".join(re.escape(t) for t in terms) + r")s?\b",
            re.IGNORECASE,
        )
    return _ANIMAL_LANE_RE


def is_animal_paper(text: str | None) -> bool:
    """Return True if `text` (title + abstract + journal) mentions a
    non-human organism or veterinary context. Universal — works across
    any biological / ecological / agricultural topic."""
    if not text:
        return False
    return bool(_ANIMAL_KEYWORD_RE.search(text))


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
    "<h3>", "</h3>", "### h3.", "### h3:",
    "source-context sentence cannot support", "the surviving section therefore",
    "[d1_inferential_bridge", "accepted receipt graph",
    "manifest, tension matrix, and citation registry", "evidence-context framing",
    "should be read as", "### background references", "### final interpretation",
    "decision: accept", "gate failures:", "published by researka", "living evidence brief", "not extracted",
    "accepted receipt", "receipt set", "receipt graph",
    "mechanistic receipts", "direct clinical receipts", "indirect clinical receipts",
    "accepted corpus", "with 's evidence", "with ’s evidence",
)
# Bug-fix 2026-05-14: pipeline-language → academic-language translation
# for the PUBLIC manuscript body only. Audit sidecars + supplement may
# (and should) still use the internal vocabulary. Universal — applies to
# any topic; no biomedical-specific tokens.
_PIPELINE_JARGON_PUBLIC: tuple[tuple[str, str], ...] = (
    ("source-bound observation", "extracted quantitative finding"),
    ("source-bound claim", "extracted claim"),
    ("source-bound", "extracted"),
    ("claim atom", "extracted finding"),
    ("endpoint proximity", "clinical directness"),
    ("accepted receipt graph", "included source set"), ("accepted corpus", "included studies"), ("accepted receipts", "included sources"), ("accepted receipt", "included source"),
    ("mechanistic receipts", "mechanistic sources"), ("direct clinical receipts", "direct clinical sources"), ("indirect clinical receipts", "indirect clinical sources"), ("final receipt admission", "final source admission"), ("receipt admission funnel", "source admission funnel"), ("receipt candidates", "source candidates"),
    ("receipt set", "source set"), ("receipt graph", "source set"), ("receipts", "sources"),
    # Word-count-neutral replacement: "structured corpus synthesis"
    # (3 words) → "AI-assisted evidence synthesis" (3 words) so the
    # rewrite doesn't push abstracts over the section ceiling.
    ("structured corpus synthesis", "AI-assisted evidence synthesis"),
)
_REQUIRED_SECTIONS = {"Abstract": 150, "Introduction": 400, "Background": 300, "Methods": 300, "Results": 500, "Cross-Domain Synthesis": 850, "Discussion": 800, "Limitations": 250, "Conclusion": 250}
# Slice 35 thin-corpus skeleton: only structural-evidence minimum required.
_REQUIRED_SECTIONS_THIN = {"Abstract": 100, "Methods": 200, "Results": 200, "Limitations": 80, "Conclusion": 80}
_SECTION_CEILINGS = {"Abstract": 300}
_APPENDIX_CUTOFF_RE = re.compile(r"^##\s+(?:Publication Appendix|Researka Submitter Block|Data and Code Availability|Search Provenance|AI(?:-Use)? Disclosure|Accountability|References)\b", flags=re.M)
_CITATION_ARTIFACT_RE = re.compile(r"\[(?:citation needed|source|ref|pmid|doi|TODO)[^\]]*\]|(?:^|\s)(?:PMID|DOI):?\s*$|<\s*(?:citation|ref)[^>]*>", re.IGNORECASE | re.MULTILINE)
_REFERENCE_DUMP_RE = re.compile(r"\b(?:DOI|PMID):\s*\S+", re.IGNORECASE)
_HEDGE_FRAGMENT_RE = re.compile(r"^(?:may|might|could|appears|suggests|uncertain|preliminary|context[- ]dependent|not definitive|requires confirmation)\.?$", re.IGNORECASE)
_MALFORMED_NUMERIC_RE = re.compile(r"(?<![\d,])0{2,}(?:\.\d+)?\s*(?:mg/day|mg|g|mcg|µg|μg|ng|kg|m/s|mmHg)\b", re.IGNORECASE)
_GRAMMAR_ARTIFACT_RE = re.compile(
    r"\b(?:(?:is|are|was|were)\s+\w+(?:\s+\w+){0,3}\s+to\s+(?:is|are|was|were)"
    r"|to\s+be(?:\s+\w+){0,5}\s+(?:is|are|was|were)"
    r"|does\s+not\s+automatically\s+(?:is|are|was|were))\b",
    re.IGNORECASE,
)
_CITATION_ONLY_STUB_RE = re.compile(
    r"^(?:[A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÖØ-öø-ÿ'’.\-]+|[A-Z]{2,})"
    r"(?:\s+et\s+al\.)?\s+(?:19|20)\d{2}[a-z]?\s+"
    r"(?:reported|showed|found|observed|demonstrated|concluded)\.?$"
)
_CLASSIFICATION_META_ROW_RE = re.compile(
    r"^\|\s*\*{0,2}(?:outcome class|directness|directional signal|evidence tier)\*{0,2}\b",
    re.IGNORECASE,
)
_PUBLIC_SLUG_RE = re.compile(r"\b(?:[a-z][a-z0-9]*_[a-z0-9_]*|glp1|omega3)\b")
_QEI_HEADING_RE = re.compile(r"^##\s+Quantitative\s+Evidence\s+Index\b.*$", re.M)
_TABLE_REF_RE = re.compile(r"\bTable\s+(\d+)\b", re.IGNORECASE)
_UNRESOLVED_TEMPLATE_RE = re.compile(r"(?<![a-z])(?:source|study|trial|paper)\((?:s|es)\)(?![a-z])|\bstudy/studies\b", re.IGNORECASE)
_COUNT_CLAIM_RE = re.compile(r"\b(?:spans|contains|includes|covers|across)\s+(\d+)\s+(?:curated\s+)?(?:references?|sources?|studies|papers)\b", re.IGNORECASE)
_ANALYTIC_STUB_RE = re.compile(
    r"^(?:meta-analytic evidence corroborates|mechanistically,|"
    r"mechanistic(?:al)? evidence|evidence corroborates|findings corroborate)\b",
    re.IGNORECASE,
)
_AUTHOR_YEAR_RE = re.compile(
    r"\b([A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÖØ-öø-ÿ'’.\-]+|[A-Z]{2,})"
    r"(?:\s+et\s+al\.)?\s+((?:19|20)\d{2}[a-z]?)\b"
)
_MONTH_AUTHOR_TOKENS = set("january february march april may june july august september october november december".split())


def evaluate_journal_surface(
    paper_md: str,
    *,
    animal_citations: Iterable[str] | None = None,
    citation_outcome_map: dict[str, str] | None = None,
    declared_review_type: str | None = None,
) -> SurfaceReport:
    issues: list[SurfaceIssue] = []
    body_md = _journal_body(paper_md)
    low = body_md.lower()
    qei_heads = list(_QEI_HEADING_RE.finditer(body_md))
    issues.extend(SurfaceIssue("placeholder_prose", pat) for pat in _PLACEHOLDER_PATTERNS if pat in low)
    issues.extend(SurfaceIssue("template_meta", pat) for pat in _META_PATTERNS if pat in low)
    issues.extend(SurfaceIssue("public_artifact", pat) for pat in _PUBLIC_ARTIFACT_PATTERNS if pat in low)
    issues.extend(SurfaceIssue("duplicate_paragraph", msg) for msg in _duplicate_paragraph_issue_messages(body_md))
    issues.extend(SurfaceIssue("public_artifact", msg) for msg in _public_language_issue_messages(body_md))
    issues.extend(SurfaceIssue("citation_artifact", msg) for msg in _citation_artifact_issue_messages(body_md))
    issues.extend(SurfaceIssue("citation_artifact", f"public reference dump: {m.group(0)}") for m in _REFERENCE_DUMP_RE.finditer(body_md))
    issues.extend(SurfaceIssue("hedge_fragment", msg) for msg in _hedge_fragment_issue_messages(body_md))
    issues.extend(SurfaceIssue("malformed_numeric", f"malformed numeric artifact: {m.group(0).strip()}") for m in _MALFORMED_NUMERIC_RE.finditer(body_md))
    issues.extend(SurfaceIssue("grammar_artifact", msg) for msg in _grammar_artifact_issue_messages(body_md))
    issues.extend(SurfaceIssue("public_artifact", msg) for msg in _classification_metadata_row_issue_messages(body_md))
    # Backtick-fenced spans (`like_this`) are code/file references —
    # exempt from the slug check (real-world conventional in Methods +
    # AI-disclosure sections).
    _body_for_slug_check = re.sub(r"`[^`]*`", "", body_md)
    issues.extend(SurfaceIssue("topic_slug_artifact", f"public topic-slug artifact: {m.group(0)}") for m in _PUBLIC_SLUG_RE.finditer(_body_for_slug_check))
    issues.extend(SurfaceIssue("duplicate_heading", "duplicate consecutive Quantitative Evidence Index headings") for left, right in zip(qei_heads, qei_heads[1:]) if not body_md[left.end():right.start()].strip())
    if not re.search(r"^##\s+References\b", paper_md, flags=re.M):
        issues.append(SurfaceIssue("structure_surface", "missing required section: References"))
    issues.extend(SurfaceIssue("citation_artifact", msg) for msg in _citation_reference_issue_messages(paper_md))
    issues.extend(SurfaceIssue("citation_artifact", msg) for msg in _orphan_reference_issue_messages(paper_md))
    issues.extend(SurfaceIssue("pipeline_jargon", msg) for msg in _pipeline_jargon_issue_messages(body_md))
    issues.extend(SurfaceIssue("limitations_leak", msg) for msg in _limitations_summary_leak_issue_messages(paper_md))
    issues.extend(SurfaceIssue("undeclared_thesis", msg) for msg in _undeclared_thesis_in_discussion_issue_messages(paper_md))
    issues.extend(SurfaceIssue("unsupported_novelty", msg) for msg in _unsupported_novelty_claim_issue_messages(body_md))
    if animal_citations is not None:
        issues.extend(SurfaceIssue("evidence_lane", msg) for msg in _unlabeled_animal_citation_issue_messages(paper_md, animal_citations))
    if citation_outcome_map is not None:
        issues.extend(SurfaceIssue("outcome_routing", msg) for msg in _outcome_class_mismatch_issue_messages(paper_md, citation_outcome_map))
    if declared_review_type:
        issues.extend(SurfaceIssue("review_type_overclaim", msg) for msg in _review_type_overclaim_issue_messages(paper_md, declared_review_type))
        issues.extend(SurfaceIssue("methods_pack_incomplete", msg) for msg in _methods_pack_completeness_issue_messages(paper_md, declared_review_type))
    issues.extend(SurfaceIssue("structure_surface", msg) for msg in _empty_heading_issue_messages(body_md))
    issues.extend(SurfaceIssue("structure_surface", msg) for msg in _results_outcome_section_issue_messages(body_md))
    issues.extend(SurfaceIssue("structure_surface", msg) for msg in _results_count_mismatch_issue_messages(body_md))
    issues.extend(SurfaceIssue("structure_surface", msg) for msg in _thin_analytic_paragraph_issue_messages(body_md))
    issues.extend(SurfaceIssue("structure_surface", msg) for msg in _abstract_profile_contradiction_issue_messages(body_md))
    issues.extend(SurfaceIssue("structure_surface", msg) for msg in _conclusion_scope_issue_messages(body_md))
    issues.extend(SurfaceIssue("structure_surface", msg) for msg in _orphan_table_issue_messages(body_md))
    issues.extend(SurfaceIssue("structure_surface", msg) for msg in _section_issue_messages(body_md, declared_review_type))
    issues.extend(SurfaceIssue("qei_surface", msg) for msg in _qei_shape_issue_messages(body_md))
    for row in _extract_qei_rows(body_md):
        issues.extend(SurfaceIssue("qei_surface", msg) for msg in qei_row_issue_messages(row))
    return SurfaceReport(passed=not issues, issues=tuple(issues))


def _journal_body(paper_md: str) -> str:
    m = _APPENDIX_CUTOFF_RE.search(paper_md)
    return paper_md[:m.start()] if m else paper_md


def _classification_metadata_row_issue_messages(paper_md: str) -> tuple[str, ...]:
    return tuple(
        f"classification metadata leaked as study row: {line.strip()}"
        for line in paper_md.splitlines()
        if _CLASSIFICATION_META_ROW_RE.search(line.strip())
    )


def _grammar_artifact_issue_messages(paper_md: str) -> tuple[str, ...]:
    messages: list[str] = []
    for match in _GRAMMAR_ARTIFACT_RE.finditer(paper_md):
        prefix = paper_md[:match.start()]
        stripped_prefix = prefix.rstrip()
        if match.group(0).lower().startswith("to be") and (
            not stripped_prefix or stripped_prefix[-1] in ".!?" or prefix.endswith("\n")
        ):
            continue
        messages.append(f"grammar artifact: {match.group(0).strip()}")
    return tuple(messages)


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


def _section_issue_messages(paper_md: str, declared_review_type: str | None = None) -> tuple[str, ...]:
    required = _REQUIRED_SECTIONS_THIN if declared_review_type in COMPACT_REVIEW_TYPES else _REQUIRED_SECTIONS
    issues: list[str] = []
    for heading, floor in required.items():
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
        level = len(match.group(1))
        next_match = matches[idx + 1] if idx + 1 < len(matches) else None
        if next_match is not None and len(next_match.group(1)) > level:
            continue
        end = next_match.start() if next_match else len(paper_md)
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
    h3s = [m.group(1) for m in re.finditer(r"^###\s+(.+?\bOutcomes?)\s*$", results, flags=re.M)]
    expected = {_outcome_key(outcome): outcome for outcome in outcomes}
    counts = Counter(_outcome_key(heading) for heading in h3s)
    issues: list[str] = []
    for key, outcome in expected.items():
        n = counts.get(key, 0)
        if n == 0:
            issues.append(f"missing Results outcome section: {outcome}")
        elif n > 1:
            issues.append(f"duplicate Results outcome section: {outcome}")
    issues.extend(
        f"unexpected Results outcome section: {key}"
        for key in sorted(k for k in counts if k and k not in expected)
    )
    return tuple(issues)


def _results_count_mismatch_issue_messages(paper_md: str) -> tuple[str, ...]:
    results = _section_body(paper_md, "Results")
    if not results:
        return ()
    table_counts = _outcome_counts_from_results_table(results)
    if not table_counts:
        return ()
    headings = list(re.finditer(r"^###\s+(.+?)\s*$", results, flags=re.M))
    issues: list[str] = []
    for idx, match in enumerate(headings):
        key = _outcome_key(match.group(1))
        if key not in table_counts:
            continue
        end = headings[idx + 1].start() if idx + 1 < len(headings) else len(results)
        section = results[match.end():end]
        for count_match in _COUNT_CLAIM_RE.finditer(section[:900]):
            claimed = int(count_match.group(1))
            expected = table_counts[key]
            if claimed != expected:
                issues.append(
                    f"Results count mismatch: {match.group(1)} table n={expected} body says {claimed}"
                )
    return tuple(issues)


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


def _outcome_counts_from_results_table(results: str) -> dict[str, int]:
    lines = [line.strip() for line in results.splitlines()]
    for idx, line in enumerate(lines):
        if not line.startswith("|"):
            continue
        cells = _table_cells(line)
        if not cells or _norm(cells[0]) != "outcome class":
            continue
        counts: dict[str, int] = {}
        for row in lines[idx + 2:]:
            if not row.startswith("|"):
                break
            row_cells = _table_cells(row)
            if len(row_cells) < 2:
                continue
            m = re.search(r"\bn\s*=\s*(\d+)\b", row_cells[1], flags=re.I)
            if m:
                counts[_outcome_key(row_cells[0])] = int(m.group(1))
        return counts
    return {}


def _table_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _outcome_key(text: str) -> str:
    return outcome_key(text).replace("_", " ")


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


def _public_language_issue_messages(paper_md: str) -> tuple[str, ...]:
    issues = [f"unresolved public template: {m.group(0)}" for m in _UNRESOLVED_TEMPLATE_RE.finditer(paper_md)]
    abstract = _section_body(paper_md, "Abstract") or ""
    issues.extend(_duplicate_adjacent_phrase_issue_messages(abstract))
    return tuple(issues)


def _duplicate_adjacent_phrase_issue_messages(text: str) -> tuple[str, ...]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    for size in range(2, 5):
        for idx in range(0, len(words) - (2 * size) + 1):
            phrase = words[idx:idx + size]
            if len(set(phrase)) > 1 and phrase == words[idx + size:idx + (2 * size)]:
                return (f"duplicate adjacent phrase: {' '.join(phrase)}",)
    return ()


def _thin_analytic_paragraph_issue_messages(paper_md: str) -> tuple[str, ...]:
    issues: list[str] = []
    for idx, paragraph in enumerate(re.split(r"\n\s*\n", paper_md), start=1):
        text = re.sub(r"\s+", " ", paragraph.strip())
        if not text or text.startswith(("#", "|")):
            continue
        n = len(re.findall(r"[a-z0-9]+", text.lower()))
        if 5 <= n <= 14 and _ANALYTIC_STUB_RE.search(text) and not re.search(r"\d|;|:", text):
            issues.append(f"thin analytical paragraph {idx}: {text}")
        elif _CITATION_ONLY_STUB_RE.match(text):
            issues.append(f"citation-only stub paragraph {idx}: {text}")
        elif n >= 6 and re.search(r"(?:\.\.\.|…)$|\b(?:versus|vs|and|or|but|of|to|with|for|than|between|whereas|while)$", re.sub(r"""[\s)\]"'*_`]+$""", "", text), re.I):
            issues.append(f"truncated sentence paragraph {idx}: …{text[-60:]}")
    return tuple(issues)


def _abstract_profile_contradiction_issue_messages(paper_md: str) -> tuple[str, ...]:
    abstract = _section_body(paper_md, "Abstract") or ""
    body = paper_md.replace(abstract, "", 1).lower()
    issues: list[str] = []
    for match in re.finditer(r"\b0\s+([a-z][a-z\s/-]+?)\s+source(?:\(s\)|s)?\b", abstract, flags=re.I):
        terms = [
            token for token in re.findall(r"[a-z]+", match.group(1).lower())
            if len(token) >= 6 and token not in {"source", "sources", "clinical", "direct", "adjacent"}
        ]
        if terms and any(re.search(rf"\b{re.escape(term)}\b", body) for term in terms):
            issues.append(f"abstract evidence-profile contradiction: {match.group(0)}")
    return tuple(issues)


def _conclusion_scope_issue_messages(paper_md: str) -> tuple[str, ...]:
    conclusion = _section_body(paper_md, "Conclusion") or ""
    if re.search(r"\bseparates\s+endpoint[- ]specific\s+evidence\b", conclusion, flags=re.I):
        return ("What This Synthesis Adds language appears inside Conclusion",)
    return ()


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


def _pipeline_jargon_issue_messages(paper_md: str) -> tuple[str, ...]:
    """Flag pipeline-internal vocabulary in the public manuscript body.
    Each match emits the offending token + the academic-language
    replacement so the auto-fixer or a human author can swap it in.
    Universal — no topic-specific tokens."""
    low = paper_md.lower()
    out: list[str] = []
    for jargon, replacement in _PIPELINE_JARGON_PUBLIC:
        if jargon in low:
            out.append(f"pipeline jargon in public prose: {jargon!r} → use {replacement!r}")
    return tuple(out)


def apply_pipeline_jargon_replacements(paper_md: str) -> str:
    """Deterministic post-render scrubber — replaces every pipeline-
    jargon token in the manuscript body with its academic-language
    equivalent. Universal — applies the same _PIPELINE_JARGON_PUBLIC
    table the gate uses (single source of truth). Caller (the
    pipeline) runs this AFTER the writer to make sure the body is
    journal-language-clean without depending on the LLM to comply with
    prompt rules. Longest patterns are replaced first so 'source-bound
    observation' wins over 'source-bound' alone."""
    out = paper_md
    ordered = sorted(_PIPELINE_JARGON_PUBLIC, key=lambda kv: -len(kv[0]))
    for jargon, replacement in ordered:
        out = re.sub(re.escape(jargon), replacement, out, flags=re.IGNORECASE)
    return out


# Bug-fix 2026-05-14: novelty/framework claims that don't cite any
# prior literature in the same paragraph are anti-hype gate failures —
# real frameworks "build on" or "extend" something. Universal regex,
# no per-topic table.
# 2026-05-14: "we operationalize" is intentionally NOT in this set.
# Per the journal_finalizer doctrine (Phase E.3), the safe rewrite for
# ungrounded "we propose" is "we operationalize ..." — the latter
# implies building on prior work rather than claiming first invention.
# Treating it as a novelty trigger would defeat the finalizer's
# softening pass.
_NOVELTY_CLAIM_RE = re.compile(
    r"\b(we\s+propose|novel\s+(?:framework|approach|method|model)|"
    r"we\s+introduce|"
    r"(?:our|this)\s+(?:novel|distinct)\s+contribution|"
    r"first\s+to\s+(?:propose|introduce|operationalize|formalize))\b",
    re.IGNORECASE,
)


# Bug-fix 2026-05-14: Limitations sections that contain corpus-
# summary prose ("Positive signals appear in...", "the evidence base
# for X shows...") or synthesis-contribution prose ("It separates
# endpoint-specific evidence...") fail the editorial contract.
# Limitations must name limitations, not summarise findings or assert
# contributions. Universal — patterns are topic-agnostic.
_LIMITATIONS_SUMMARY_LEAK_PATTERNS: tuple[str, ...] = (
    r"\bpositive\s+signals?\s+appear\s+in\b",
    r"\bnegative\s+signals?\s+appear\s+in\b",
    r"\bnull\s+findings?\s+dominate\b",
    r"\bthe\s+evidence\s+base\s+for\b.{0,80}\b(?:shows?|suggests?|supports?|indicates?|demonstrates?)\b",
    r"\bthe\s+strongest\s+unresolved\s+contrast\b",
    r"\bacross\s+\d+\s+curated\s+reference\s+papers?\b",
    r"\bIt\s+separates\s+endpoint[- ]specific\s+evidence\b",
)
_LIMITATIONS_LEAK_RE = re.compile(
    "|".join(f"({p})" for p in _LIMITATIONS_SUMMARY_LEAK_PATTERNS),
    re.IGNORECASE,
)


def _limitations_summary_leak_issue_messages(paper_md: str) -> tuple[str, ...]:
    """The Limitations section must name LIMITATIONS, not summarise
    findings or assert synthesis contributions. Catches summary-prose
    leakage like 'Positive signals appear in...' and synthesis-novelty
    leakage like 'It separates endpoint-specific evidence...'."""
    body = _section_body(paper_md, "Limitations") or ""
    if not body:
        return ()
    out: list[str] = []
    for match in _LIMITATIONS_LEAK_RE.finditer(body):
        snippet = match.group(0)
        out.append(
            f"summary/contribution prose in Limitations section: {snippet!r}",
        )
    return tuple(out)


_THESIS_MARKER_RE = re.compile(r"\*\*\s*thesis\s*:\s*\*\*", re.IGNORECASE)
_RESOLUTION_MARKER_RE = re.compile(
    r"\*\*\s*resolution\s+criteria\s*:\s*\*\*", re.IGNORECASE,
)


# Slice 10/11 thin wrappers — heavy lifting lives in the semantic
# home modules (`agent.review_type`, `agent.methods_pack`) per V4
# rule 49 (one module, one reason to change). This file orchestrates;
# the editorial checks live next to the data they validate.


def _review_type_overclaim_issue_messages(
    paper_md: str, declared_review_type: str | None,
) -> tuple[str, ...]:
    """Thin wrapper: extracts Abstract + Methods sections and
    delegates to `agent.review_type.review_type_overclaim_issue_messages`."""
    from agent.review_type import review_type_overclaim_issue_messages
    return review_type_overclaim_issue_messages(
        _section_body(paper_md, "Abstract") or "",
        _section_body(paper_md, "Methods") or "",
        declared_review_type,
    )


def _methods_pack_completeness_issue_messages(
    paper_md: str, declared_review_type: str | None,
) -> tuple[str, ...]:
    """Thin wrapper: extracts Methods section and delegates to
    `agent.methods_pack.methods_pack_completeness_issue_messages`."""
    from agent.methods_pack import methods_pack_completeness_issue_messages
    return methods_pack_completeness_issue_messages(
        _section_body(paper_md, "Methods") or "",
        declared_review_type,
    )


def _undeclared_thesis_in_discussion_issue_messages(
    paper_md: str,
) -> tuple[str, ...]:
    """Discussion must take a position, not hedge into 'context-
    dependent' boilerplate. Bug-fix 2026-05-14: require the writer to
    emit a literal `**Thesis:**` marker so the reader can locate the
    paper's claimed position in one scan. Universal — the marker is
    topic-agnostic; the gate just confirms presence."""
    body = _section_body(paper_md, "Discussion") or ""
    if not body:
        return ()
    issues: list[str] = []
    if not _THESIS_MARKER_RE.search(body):
        issues.append(
            "Discussion missing `**Thesis:**` marker — paragraph 1 must "
            "open with one declarative defensible thesis sentence "
            "(15-40 words). Audit will not accept hedged 'context-"
            "dependent' framing without a named position.",
        )
    if not _RESOLUTION_MARKER_RE.search(body):
        issues.append(
            "Discussion missing `**Resolution criteria:**` marker — "
            "the final paragraph must name the evidence that would "
            "settle the threats to the thesis (study designs, "
            "endpoint layers, follow-up durations).",
        )
    return tuple(issues)


def _unsupported_novelty_claim_issue_messages(paper_md: str) -> tuple[str, ...]:
    """A paragraph that asserts novelty/framework contribution must
    cite ≥1 prior Author-Year reference in the same paragraph. Catches
    the "we propose a novel framework" with zero engagement with prior
    literature failure mode (the metabolic-functional tradeoff issue).
    Universal — works for any domain."""
    issues: list[str] = []
    for para in re.split(r"\n\s*\n", paper_md):
        novelty = _NOVELTY_CLAIM_RE.search(para)
        if not novelty:
            continue
        if _AUTHOR_YEAR_RE.search(para):
            continue
        snippet = novelty.group(0)
        issues.append(
            f"novelty claim without prior-literature citation in same "
            f"paragraph: {snippet!r}",
        )
    return tuple(issues)


def unreferenced_citation_tokens(paper_md: str) -> tuple[str, ...]:
    refs = _reference_labels(paper_md)
    if not refs:
        return ()
    reference_title_tokens = _reference_nonlabel_tokens(paper_md)
    seen: set[str] = set()
    out: list[str] = []
    for match in _AUTHOR_YEAR_RE.finditer(_journal_body(paper_md)):
        author = match.group(1)
        if author.casefold().rstrip(".") in _MONTH_AUTHOR_TOKENS or author.casefold().endswith(("'s", "’s")):
            continue
        token = f"{author} {match.group(2)}"
        if _fold(token) in reference_title_tokens:
            continue
        # Compare via _fold so diacritic mismatches (Hernández inline vs
        # Hernandez in References) don't false-positive. Report the
        # original (un-folded) inline token so the issue message
        # matches what a reader sees in the manuscript.
        if _fold(token) not in refs and token not in seen:
            seen.add(token)
            out.append(token)
    return tuple(out)


def _reference_entries(paper_md: str) -> Iterable[tuple[str, str]]:
    """Yield (raw_token, folded_token) for each reference list entry.
    Only the FIRST Author-Year on a line is the canonical label; later
    matches on the same line are journal abbreviations inside the full
    citation body (e.g. 'J Am Geriatr Soc. 2006' or 'BMJ. 2010').
    Universal — works for `- **Author Year.**` and `[N] Author Year`
    reference styles alike."""
    refs = _section_body(paper_md, "References") or ""
    for line in refs.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = _AUTHOR_YEAR_RE.search(line) or _AUTHOR_YEAR_RE.search(line.title())
        if m:
            token = f"{m.group(1)} {m.group(2)}"
            yield token, _fold(token)


def _reference_labels(paper_md: str) -> set[str]:
    return {folded for _raw, folded in _reference_entries(paper_md)}


def _reference_nonlabel_tokens(paper_md: str) -> set[str]:
    refs = _section_body(paper_md, "References") or ""
    out: set[str] = set()
    for line in refs.splitlines():
        matches = list(_AUTHOR_YEAR_RE.finditer(line))
        for match in matches[1:]:
            out.add(_fold(f"{match.group(1)} {match.group(2)}"))
    return out


def orphan_reference_tokens(paper_md: str) -> tuple[str, ...]:
    """Mirror of `unreferenced_citation_tokens`: every Author-Year row
    in the References section MUST be cited at least once in the body.
    A reference with zero body cites is an orphan — usually means the
    paper was parsed into the corpus but the writer never named it,
    or a citation-token mismatch (the bug that surfaced 'renovar 2023'
    as the only place that source appeared)."""
    body = _journal_body(paper_md)
    body_folded = {_fold(f"{m.group(1)} {m.group(2)}") for m in _AUTHOR_YEAR_RE.finditer(body) if m.group(1).casefold().rstrip(".") not in _MONTH_AUTHOR_TOKENS}
    out: list[str] = []
    seen: set[str] = set()
    for raw, folded in _reference_entries(paper_md):
        if folded in seen:
            continue
        seen.add(folded)
        if folded not in body_folded:
            out.append(raw)
    return tuple(out)


def _orphan_reference_issue_messages(paper_md: str) -> tuple[str, ...]:
    return tuple(
        f"orphan reference (in bibliography, not cited inline): {token}"
        for token in orphan_reference_tokens(paper_md)
    )


_OUTCOME_HEADING_RE = re.compile(r"^###\s+(.+?)\s+Outcomes\s*$", re.M)


def _outcome_slug(label: str) -> str:
    """Universal heading → outcome-class slug. 'Muscle Function' →
    'muscle_function'; 'Cardiometabolic' → 'cardiometabolic'. No
    per-topic table; just lowercased + word-joined."""
    return outcome_key(label)


def _outcome_class_mismatch_issue_messages(
    paper_md: str, citation_outcome_map: dict[str, str],
) -> tuple[str, ...]:
    """For each `### X Outcomes` subsection in Results, every cited
    Author-Year must be from a receipt whose outcome_class normalises
    to X. Mismatches signal evidence routing errors (e.g. Beavers 2022
    with outcome_class=frailty cited inside the Cardiometabolic
    subsection). Universal — the caller passes the citation→outcome
    map derived from manifest.receipts; this gate adds no per-topic
    knowledge."""
    if not citation_outcome_map:
        return ()
    folded_map = {_fold(k): v for k, v in citation_outcome_map.items()}
    results = _section_body(paper_md, "Results") or ""
    matches = list(_OUTCOME_HEADING_RE.finditer(results))
    if not matches:
        return ()
    issues: list[str] = []
    seen: set[tuple[str, str]] = set()
    for i, m in enumerate(matches):
        section_slug = _outcome_slug(m.group(1))
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(results)
        body = results[start:end]
        for am in _AUTHOR_YEAR_RE.finditer(body):
            cite = f"{am.group(1)} {am.group(2)}"
            expected = folded_map.get(_fold(cite))
            if not expected:
                continue
            if _outcome_slug(expected) == section_slug:
                continue
            key = (_fold(cite), section_slug)
            if key in seen:
                continue
            seen.add(key)
            issues.append(
                f"outcome-class mismatch: {cite} "
                f"(receipt outcome_class={expected!r}) cited in "
                f"'### {m.group(1)} Outcomes' subsection",
            )
    return tuple(issues)


def _unlabeled_animal_citation_issue_messages(
    paper_md: str, animal_citations: Iterable[str],
) -> tuple[str, ...]:
    """For each animal-lane citation (as listed by the caller) that
    appears in a body paragraph WITHOUT any animal-lane qualifier in
    the same paragraph, emit an issue. Universal — `animal_citations`
    is a free list of author-year tokens the caller has identified as
    non-human; this gate adds no per-topic knowledge."""
    animal_set = {_fold(c.strip()) for c in animal_citations if c and c.strip()}
    if not animal_set:
        return ()
    body = _journal_body(paper_md)
    issues: list[str] = []
    seen: set[str] = set()
    qualifier_re = _animal_lane_re()
    for para in re.split(r"\n\s*\n", body):
        # Slice 26: word-boundary match against the centralised qualifier
        # set (includes everyday terms like "mice"/"rat" alongside the
        # formal "rodent"/"murine"). Avoids "rat" → "iterate" false hits.
        if qualifier_re.search(para):
            continue
        for match in _AUTHOR_YEAR_RE.finditer(para):
            token = f"{match.group(1)} {match.group(2)}"
            folded = _fold(token)
            if folded in animal_set and folded not in seen:
                seen.add(folded)
                issues.append(
                    f"animal/preclinical citation in non-lane-labelled "
                    f"paragraph: {token}",
                )
    return tuple(issues)


def _citation_reference_issue_messages(paper_md: str) -> tuple[str, ...]:
    return tuple(f"unreferenced citation: {token}" for token in unreferenced_citation_tokens(paper_md))


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
