"""Deterministic template-language detector for paper-render audit.

Phase 6 of the WORLDCLASS rapamycin sprint. Stdlib-only, no LLM.

Scans markdown paper text for AI-template phrases that draw senior-reviewer comments without changing claims.
The detector is regex-driven; the rewriter is the only LLM-touching surface.

Categories:
  - generic_research_cliche: "further research is needed"-class phrases
  - ai_summary_tell:         "this synthesis suggests"-class openers
  - vague_limitation:        "evidence base is limited" without specifics
  - unsupported_authority:   "it is clear that", "undeniably", "proves that"

Skipped: code fences, tables, references, and audit metadata sections.

Severity:
  - P1: unsupported_authority (overclaiming; gates pass/fail)
  - P2: cliches, AI tells, vague limitations (gates pass/fail)
  - P3: reserved for advisory categories (none currently)
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Iterable, Literal

__all__ = [
    "Severity",
    "Category",
    "Hit",
    "detect_template_language",
    "mask_fenced_markdown",
    "hit_to_dict",
    "has_blocking_severity",
    "DENYLIST_ALWAYS",
    "DENYLIST_CONDITIONAL",
    "SKIP_SECTION_HEADINGS",
]

Severity = Literal["P1", "P2", "P3"]
Category = Literal[
    "generic_research_cliche",
    "ai_summary_tell",
    "vague_limitation",
    "unsupported_authority",
]


@dataclass(frozen=True, slots=True)
class Hit:
    """One template-language match. line_number is 1-based, refers to the
    line where the matched phrase appears. sentence is the trimmed
    sentence context."""

    phrase: str
    category: Category
    severity: Severity
    line_number: int
    sentence: str
    reason: str


def hit_to_dict(hit: Hit) -> dict[str, object]:
    """JSON-serializable dict view of a Hit."""
    return asdict(hit)


# Headings whose section bodies are skipped entirely. Substring match,
# case-insensitive, against heading text after the leading ## marker.
SKIP_SECTION_HEADINGS: tuple[str, ...] = (
    "references",
    "background references",
    "ai-use disclosure",
    "researka submitter block",
    "data and code availability",
    "search provenance and selection",
    "structured evidence tables",
)


# (regex, category, severity, reason). Compact 2-lines-per-entry format
# stays within the per-file LOC budget.
DENYLIST_ALWAYS: tuple[tuple[re.Pattern[str], Category, Severity, str], ...] = (
    (re.compile(r"\bfurther research is needed\b", re.I), "generic_research_cliche", "P2",
     "Generic call for more research; replace with specific design recommendation."),
    (re.compile(r"\bmore studies are needed\b", re.I), "generic_research_cliche", "P2",
     "Generic call for more studies; replace with specific design recommendation."),
    (re.compile(r"\bmore research is needed\b", re.I), "generic_research_cliche", "P2",
     "Generic call for more research; replace with specific design recommendation."),
    (re.compile(r"\badditional research is warranted\b", re.I), "generic_research_cliche", "P2",
     "Generic warrant; replace with concrete trial-design parameters."),
    (re.compile(r"\bfurther studies are warranted\b", re.I), "generic_research_cliche", "P2",
     "Generic warrant; replace with concrete trial-design parameters."),
    (re.compile(r"\bthis synthesis suggests\b", re.I), "ai_summary_tell", "P2",
     "AI-summary opener; lead with the specific finding instead."),
    (re.compile(r"\bin conclusion\s*,", re.I), "ai_summary_tell", "P2",
     "AI-summary section opener; lead with the actual conclusion statement."),
    (re.compile(r"\btaken together\s*,", re.I), "ai_summary_tell", "P2",
     "AI-summary connector; replace with specific aggregation statement."),
    (re.compile(r"\bin summary\s*,", re.I), "ai_summary_tell", "P2",
     "AI-summary opener; lead with the actual summary content."),
    (re.compile(r"\bthis review suggests\b", re.I), "ai_summary_tell", "P2",
     "AI-summary opener; lead with the specific finding instead."),
    (re.compile(r"\bit is clear that\b", re.I), "unsupported_authority", "P1",
     "Authority claim without anchor; cite or remove."),
    (re.compile(r"\bundeniably\b", re.I), "unsupported_authority", "P1",
     "Absolute language; replace with hedged claim or remove."),
    (re.compile(r"\bundoubtedly\b", re.I), "unsupported_authority", "P1",
     "Absolute language; replace with hedged claim or remove."),
    (re.compile(r"\bproves that\b", re.I), "unsupported_authority", "P1",
     '"Proves" requires definitive evidence; use "indicates" or "suggests".'),
    (re.compile(r"\bclearly demonstrates\b", re.I), "unsupported_authority", "P1",
     '"Clearly" intensifier without anchor; use "demonstrates" + cite.'),
    (re.compile(r"\bdefinitively shows\b", re.I), "unsupported_authority", "P1",
     '"Definitively" requires definitive evidence; use "shows" + cite.'),
)

# Conditional: flagged only if the containing sentence lacks specifics.
DENYLIST_CONDITIONAL: tuple[tuple[re.Pattern[str], Category, Severity, str], ...] = (
    (re.compile(r"\bevidence base is limited\b", re.I), "vague_limitation", "P2",
     "Vague limitation; specify what is limited (n, duration, endpoint, population)."),
    (re.compile(r"\bthe literature is limited\b", re.I), "vague_limitation", "P2",
     "Vague limitation; specify what is limited."),
    (re.compile(r"\blimited evidence base\b", re.I), "vague_limitation", "P2",
     "Vague limitation; specify what is limited."),
)


# Specifics indicators
_DIGIT = re.compile(r"\d")
_CITATION = re.compile(r"\b[A-Z][A-Za-z]+\s+\d{4}[a-z]?\b")  # e.g. "Smith 2023"
_MEASUREMENT_WORD = re.compile(
    r"\b(?:n\s*=|p\s*[<>=]|years?|months?|weeks?|days?|hours?|mg|ng|kg|ml|"
    r"percent|%|hba1c|bmi|patients?|participants?|subjects?|trials?|"
    r"studies|cohorts?|samples?|arms?|gait|grip|mortality|incidence|"
    r"reduction|increase|rcts?|cis?)\b",
    re.I,
)


def _has_specifics(sentence: str) -> bool:
    """A sentence is "specific" if it contains a citation token, or both
    a digit and a measurement/unit word. Cheap proxy used to distinguish
    "evidence base is limited" (vague) from "evidence base is limited to
    3 RCTs with n<100" (specific)."""
    if _CITATION.search(sentence):
        return True
    if _DIGIT.search(sentence) and _MEASUREMENT_WORD.search(sentence):
        return True
    return False


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'(])")


def _split_sentences(line: str) -> list[str]:
    """Naive sentence splitter scoped to prose lines. Over-splits on
    abbreviations; harmless because each fragment is searched independently."""
    return [p for p in _SENTENCE_SPLIT.split(line) if p.strip()]


def _heading_level_and_text(stripped: str) -> tuple[int, str] | None:
    """Return (level, text-lowercased) for a markdown heading line, else None."""
    m = re.match(r"^(#{1,6})\s+(.+?)\s*$", stripped)
    if not m:
        return None
    return len(m.group(1)), m.group(2).strip().lower()


def mask_fenced_markdown(markdown: str) -> str:
    out, fence = [], ""
    for line in markdown.splitlines(keepends=True):
        marker = match.group(1) if (match := re.match(r"^[ \t]{0,3}(`{3,}|~{3,})", line)) else ""
        if marker and (not fence or marker[0] == fence[0] and len(marker) >= len(fence) and not line[len(line) - len(line.lstrip()) + len(marker):].strip()):
            fence = "" if fence else marker
        out.append(re.sub(r"[^\n]", " ", line) if fence or marker else line)
    return "".join(out)


def detect_template_language(text: str) -> list[Hit]:
    """Scan markdown text for template-language hits.

    Skips code fences, markdown table rows, and the bodies of headings
    whose names match SKIP_SECTION_HEADINGS (until the next heading at
    the same or higher level)."""
    hits: list[Hit] = []
    skip_until_level: int | None = None

    for i, line in enumerate(mask_fenced_markdown(text).splitlines(), start=1):
        stripped = line.strip()

        heading = _heading_level_and_text(stripped)
        if heading is not None:
            level, text_lower = heading
            if skip_until_level is not None and level <= skip_until_level:
                skip_until_level = None
            if any(name in text_lower for name in SKIP_SECTION_HEADINGS):
                skip_until_level = level
            continue

        if skip_until_level is not None:
            continue
        if stripped.startswith("|"):
            continue
        if not stripped:
            continue

        for sentence in _split_sentences(line):
            _scan_sentence(sentence, line_number=i, hits=hits)

    return hits


def _scan_sentence(sentence: str, *, line_number: int, hits: list[Hit]) -> None:
    """Run sentence through always-flag and conditional denylists."""
    trimmed = sentence.strip()
    for pattern, category, severity, reason in DENYLIST_ALWAYS:
        m = pattern.search(sentence)
        if m:
            hits.append(Hit(
                phrase=m.group(0), category=category, severity=severity,
                line_number=line_number, sentence=trimmed, reason=reason,
            ))
    if not _has_specifics(sentence):
        for pattern, category, severity, reason in DENYLIST_CONDITIONAL:
            m = pattern.search(sentence)
            if m:
                hits.append(Hit(
                    phrase=m.group(0), category=category, severity=severity,
                    line_number=line_number, sentence=trimmed, reason=reason,
                ))


def has_blocking_severity(hits: Iterable[Hit]) -> bool:
    """True if any hit has severity P1 or P2 (the gate-blocking levels)."""
    return any(h.severity in ("P1", "P2") for h in hits)
