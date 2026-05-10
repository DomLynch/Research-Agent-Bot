"""Deterministic template-language detector for paper-render audit.

Phase 6 of the WORLDCLASS rapamycin sprint. Stdlib-only, no LLM.

Scans markdown paper text for AI-template phrases that draw senior-reviewer
comments without changing the paper's claims. The detector is regex-driven;
the rewriter (a separate concern) is the only LLM-touching surface.

Categories:
  - generic_research_cliche: "further research is needed"-class phrases
  - ai_summary_tell:         "this synthesis suggests"-class openers
  - vague_limitation:        "evidence base is limited" without specifics
  - unsupported_authority:   "it is clear that", "undeniably", "proves that"

Use-vs-mention discipline (Fix #58):
  Good academic writing sometimes refers to forbidden phrases instead of
  USING them — quoting, negating, or critiquing the cliché. E.g.,
  "Rather than concluding that 'further research is needed,' …" is the
  desired pattern, not a violation. The gate distinguishes:
    - USE   : the writer is asserting the phrase as their own claim → flag.
    - MENTION: the writer is referring to the phrase itself          → skip.
  Mentions are detected by either (a) the phrase being inside a balanced
  quote pair, or (b) a configured negation/meta-discourse pivot earlier
  in the sentence. Pivots are data-driven (MENTION_NEGATION_PIVOTS,
  MENTION_META_MARKERS) — extend without code changes.

Skipped: code fences (```), markdown table rows (|), references and
audit-metadata sections (until next heading of equal/higher level).

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
    "hit_to_dict",
    "has_blocking_severity",
    "DENYLIST_ALWAYS",
    "DENYLIST_CONDITIONAL",
    "MENTION_NEGATION_PIVOTS",
    "MENTION_META_MARKERS",
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


# --- Use vs Mention discipline (Fix #58) ----------------------------------
# A MENTION is when the writer refers to a forbidden phrase (quoting,
# negating, critiquing) rather than asserting it as their own claim.
# Mentions are good academic writing — the writer is pushing back against
# the cliché — and must NOT be flagged.
#
# Detection signals (any one suffices):
#   1. The phrase falls inside a balanced quote pair (straight or curly).
#   2. A negation pivot appears within MENTION_PIVOT_LOOKBACK_CHARS before.
#   3. A meta-discourse marker appears within the same window.
#
# Lists are data-driven so future patterns can be added without code edits.

MENTION_NEGATION_PIVOTS: tuple[str, ...] = (
    "rather than",
    "instead of",
    "in place of",
    "as opposed to",
    "not merely",
    "not just",
    "not the standard",
    "not the boilerplate",
    "more than just",
    "beyond the standard",
    "beyond merely",
    "moves past",
    "moving past",
    "avoids the cliché",
    "avoids the cliche",
    "rejects the standard",
    "no longer say",
    "we do not conclude",
    "we will not say",
    "this paper does not",
    "this synthesis does not",
)

MENTION_META_MARKERS: tuple[str, ...] = (
    "the cliché",
    "the cliche",
    "the phrase",
    "the boilerplate",
    "the standard ending",
    "the standard close",
    "the usual ending",
    "the formulaic",
)

# Curly + straight quote pairs. Curly are unambiguous; straight pairs
# are noisy but useful as a fallback when curly aren't used.
_QUOTE_PAIRS: tuple[tuple[str, str], ...] = (
    ("‘", "’"),  # left/right single (curly)
    ("“", "”"),  # left/right double (curly)
    ("‹", "›"),  # single guillemets
    ("«", "»"),  # double guillemets
    ("'", "'"),            # straight single
    ('"', '"'),            # straight double
)

MENTION_PIVOT_LOOKBACK_CHARS: int = 80


def _quote_regions(sentence: str) -> list[tuple[int, int]]:
    """Return (start, end) char-offset spans of every balanced quote pair.

    Curly quotes are matched left→right so they're unambiguous. Straight
    quotes are matched as adjacent pairs (greedy nearest-pair) — imperfect
    but better than ignoring them entirely. A phrase whose match falls
    inside any returned span is treated as quoted."""
    regions: list[tuple[int, int]] = []
    for opener, closer in _QUOTE_PAIRS:
        i = 0
        while i < len(sentence):
            start = sentence.find(opener, i)
            if start < 0:
                break
            search_from = start + len(opener)
            if opener == closer:
                # Straight quotes: nearest match wins; advance past it.
                end = sentence.find(closer, search_from)
            else:
                end = sentence.find(closer, search_from)
            if end < 0:
                break
            regions.append((start, end + len(closer)))
            i = end + len(closer)
    return regions


def _is_mention(sentence: str, match_start: int, match_end: int) -> bool:
    """Return True if the matched span is a MENTION (writer is referring
    to the phrase) rather than a USE (writer is asserting it). Match
    spans falling inside any quote region, or preceded by a negation
    pivot / meta-discourse marker, are mentions."""
    # Rule 1 — quoted: match falls inside a balanced quote pair.
    for q_start, q_end in _quote_regions(sentence):
        if q_start <= match_start and match_end <= q_end:
            return True
    # Rule 2 — negation/meta pivot earlier in the sentence.
    lookback_start = max(0, match_start - MENTION_PIVOT_LOOKBACK_CHARS)
    lookback = sentence[lookback_start:match_start].lower()
    for pivot in MENTION_NEGATION_PIVOTS:
        if pivot in lookback:
            return True
    for marker in MENTION_META_MARKERS:
        if marker in lookback:
            return True
    return False


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


def detect_template_language(text: str) -> list[Hit]:
    """Scan markdown text for template-language hits.

    Skips code fences, markdown table rows, and the bodies of headings
    whose names match SKIP_SECTION_HEADINGS (until the next heading at
    the same or higher level)."""
    hits: list[Hit] = []
    in_code_fence = False
    skip_until_level: int | None = None

    for i, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()

        if stripped.startswith("```"):
            in_code_fence = not in_code_fence
            continue
        if in_code_fence:
            continue

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
