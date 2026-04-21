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
_AGING_RE = re.compile(
    r"(?:aging|ageing|healthspan|longevity|older\s+adults?|frailty|"
    r"biological\s+age|geroscience|multimorbidity|cognitive\s+decline|"
    r"mild\s+cognitive\s+impairment|mci|sarcopenia)",
    re.IGNORECASE,
)
_ONCOLOGY_RE = re.compile(
    r"(?:cancer|oncology|tumou?r|carcinoma|neoplasm|metastatic|leukemia|"
    r"lymphoma|melanoma|renal\s+cell)",
    re.IGNORECASE,
)
_TRANSPLANT_RE = re.compile(
    r"(?:transplant|allograft|graft|immunosuppression)",
    re.IGNORECASE,
)
_DEVICE_RE = re.compile(
    r"(?:stent|angioplasty|catheter|implant|device)",
    re.IGNORECASE,
)
_PEDIATRIC_RE = re.compile(
    r"(?:children|child|pediatric|paediatric|adolescent|infant|neonate|fetal|foetal|pregnan)",
    re.IGNORECASE,
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


def _context_label(entry: dict[str, Any]) -> str:
    text = f"{entry.get('title', '')} {entry.get('excerpt', '')}"
    if _AGING_RE.search(text):
        return "aging"
    if _ONCOLOGY_RE.search(text):
        return "oncology"
    if _TRANSPLANT_RE.search(text):
        return "transplant"
    if _DEVICE_RE.search(text):
        return "device"
    if _PEDIATRIC_RE.search(text):
        return "pediatric"
    return "general"


def _grade_lite(entry: dict[str, Any]) -> str:
    quality = _infer_quality_signal(entry)
    study_type = _infer_study_type(entry)
    year = int(entry.get("year") or 0)
    score = 1
    if quality in {"meta-analysis", "systematic-review", "review"}:
        score = 3
    elif study_type in {"rct", "clinical-trial"} or entry.get("evidence_type") == "interventional":
        score = 3
    elif study_type in {"cohort", "observational", "case-control", "cross-sectional"} or entry.get("evidence_type") == "observational":
        score = 2
    if quality == "preprint":
        score -= 1
    if entry.get("evidence_type") == "mechanism" or entry.get("source_type") == "chembl":
        score = 1
    if year and year < 2020:
        score -= 1
    score = max(1, min(3, score))
    return {3: "H", 2: "M", 1: "L"}[score]


def build_card(entry: dict[str, Any]) -> dict[str, Any]:
    """Build an evidence card from a source entry."""
    text = " ".join(
        str(entry.get(key, "") or "")
        for key in ("title", "excerpt", "full_text")
    )
    return {
        "citation": _format_citation(entry),
        "journal": entry.get("journal") or "",
        "quality_signal": _infer_quality_signal(entry),
        "evidence_grade": _grade_lite(entry),
        "study_type": _infer_study_type(entry),
        "context": _context_label(entry),
        "population": _extract_regex(text, _POP_RE, max_matches=2),
        "intervention": _extract_regex(text, _INTERVENTION_RE, max_matches=2),
        "outcomes": _extract_regex(text, _OUTCOMES_RE, max_matches=2),
        "full_text_source": entry.get("full_text_source") or "",
        "full_text_found": bool(entry.get("full_text")),
    }
