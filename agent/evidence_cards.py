from __future__ import annotations

import re
from typing import Any


_STUDY_TYPES = (
    ("meta-analysis", "meta-analysis"),
    ("systematic review", "systematic-review"),
    ("randomized controlled trial", "rct"),
    ("randomised controlled trial", "rct"),
    ("randomized trial", "rct"),
    ("randomised trial", "rct"),
    ("rct", "rct"),
    ("cohort study", "cohort"),
    ("prospective cohort", "cohort"),
    ("retrospective cohort", "cohort"),
    ("case-control", "case-control"),
    ("cross-sectional", "cross-sectional"),
    ("observational", "observational"),
    ("clinical trial", "clinical-trial"),
    ("double-blind", "rct"),
    ("placebo-controlled", "rct"),
)
_POP_RE = re.compile(
    r"(?:adults?|patients?|elderly|older\s+adults?|children|pediatric|"
    r"populations?|participants?|men|women|individuals?|subjects?|cohort"
    r")",
    re.IGNORECASE,
)
_INTERVENTION_RE = re.compile(
    r"(?:rapamycin|metformin|exercise|caloric\s+restriction|fasting|"
    r"senolytic|dasatinib|quercetin|resveratrol|acarbose|spermidine|"
    r"intervention|treatment|therapy|drug|compound|supplement|dosage|dose)",
    re.IGNORECASE,
)
_OUTCOMES_RE = re.compile(
    r"(?:lifespan|longevity|mortality|healthspan|aging|ageing|"
    r"biomarker|telomere|inflammation|cognitive|frailty|sarcopenia|"
    r"survival|outcome|endpoint|efficacy|safety|adverse\s+event|toxicity)",
    re.IGNORECASE,
)


def _infer_quality_signal(entry: dict[str, Any]) -> str:
    """Return a quality signal label for the entry."""
    etype = str(entry.get("evidence_type") or "").lower()
    if etype == "review":
        title = str(entry.get("title") or "").lower()
        if "meta-analysis" in title:
            return "meta-analysis"
        if "systematic review" in title:
            return "systematic-review"
        return "review"
    title_lower = str(entry.get("title") or "").lower()
    abstract = str(entry.get("excerpt") or "").lower()
    if "randomized" in title_lower or "randomised" in title_lower or "rct" in abstract:
        return "rct"
    if "cohort" in title_lower or "prospective" in title_lower:
        return "cohort"
    if "preprint" in title_lower or "preprint" in abstract:
        return "preprint"
    return etype or "primary"


def _infer_study_type(entry: dict[str, Any]) -> str:
    """Infer study type from title/excerpt."""
    text = f"{entry.get('title', '')} {entry.get('excerpt', '')}".lower()
    for keyword, label in _STUDY_TYPES:
        if keyword in text:
            return label
    return entry.get("evidence_type", "primary")


def _extract_regex(text: str, pattern: re.Pattern, max_matches: int = 2) -> str:
    """Extract first N regex matches from text, lowercase."""
    matches = pattern.findall(text)
    if not matches:
        return ""
    return ", ".join(str(m).lower() for m in matches[:max_matches])


def _format_citation(entry: dict[str, Any]) -> str:
    """Build a citation string: Last-Author et al., YEAR."""
    authors = entry.get("authors") or []
    year = entry.get("year") or "n.d."
    if isinstance(authors, list) and authors:
        first = str(authors[0]).split(",")[0].split()[-1].strip()
        suffix = " et al." if len(authors) > 1 else ""
        return f"{first}{suffix}, {year}"
    title = str(entry.get("title") or "Untitled")
    short = title.split(":")[0][:40].strip()
    return f"{short}, {year}"


def build_card(entry: dict[str, Any]) -> dict[str, Any]:
    """Build an evidence card from a source entry."""
    text = f"{entry.get('title', '')} {entry.get('excerpt', '')}"
    return {
        "citation": _format_citation(entry),
        "journal": entry.get("journal") or "",
        "quality_signal": _infer_quality_signal(entry),
        "study_type": _infer_study_type(entry),
        "population": _extract_regex(text, _POP_RE, max_matches=2),
        "intervention": _extract_regex(text, _INTERVENTION_RE, max_matches=2),
        "outcomes": _extract_regex(text, _OUTCOMES_RE, max_matches=2),
    }
