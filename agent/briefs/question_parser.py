"""Question parser for BRIEFS-V1.

Phase 1 is deterministic: it turns a user question into a small query
object for topic matching and receipt filtering. Later phases may add
LLM-assisted parsing, but this layer stays schema-first and testable.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_MAX_AGE = 120

_INTERVENTION_PATTERNS = (
    re.compile(
        r"\b(?:about|evidence\s+(?:for|on)|effects?\s+of|impact\s+of|"
        r"role\s+of)\s+(?P<span>.+)$",
        re.IGNORECASE,
    ),
    re.compile(r"^(?P<span>.+?)\s+(?:for|on)\b", re.IGNORECASE),
)
_TRAILING_CONTEXT_RE = re.compile(
    r"\s+(?:for|on|in|among|with|patients?|adults?|people)\b.*$",
    re.IGNORECASE,
)
_SPLIT_RE = re.compile(
    r"\s+(?:vs\.?|versus|compared\s+with|and|or)\s+", re.IGNORECASE,
)
_LEADING_NOISE_RE = re.compile(
    r"^(?:what\s+does\s+(?:the\s+)?evidence\s+say\s+|"
    r"what\s+is\s+(?:the\s+)?evidence\s+|does\s+|do\s+|can\s+)",
    re.IGNORECASE,
)

_OUTCOME_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("muscle_function", (r"\bsarcopenia\b", r"\bmuscle\b",
                         r"\blean mass\b", r"\bstrength\b")),
    ("frailty", (r"\bfrailty\b", r"\bgait speed\b",
                 r"\bgrip strength\b", r"\bphysical function\b")),
    ("cardiometabolic", (r"\bcardiovascular\b", r"\bcardiometabolic\b",
                         r"\bglucose\b", r"\bhba1c\b", r"\blipid\b",
                         r"\bweight\b", r"\bbmi\b")),
    ("cognitive", (r"\bcognition\b", r"\bcognitive\b",
                   r"\bdementia\b", r"\balzheimer", r"\bmemory\b")),
    ("longevity", (r"\blongevity\b", r"\bhealthspan\b",
                   r"\blifespan\b", r"\bmortality\b", r"\bsurvival\b")),
    ("immune", (r"\binflammation\b", r"\bimmune\b", r"\bvaccine\b")),
    ("safety", (r"\bsafety\b", r"\badverse\b", r"\btolerability\b")),
    ("oncology", (r"\bcancer\b", r"\boncology\b", r"\btumou?r\b")),
    ("mechanism", (r"\bmechanism\b", r"\bmtor\b", r"\bampk\b",
                   r"\bautophagy\b", r"\bsenescence\b")),
)

_POPULATION_PATTERNS: tuple[tuple[str, str], ...] = (
    ("non-diabetic older adults", r"\bnon[- ]diabetic older adults\b"),
    ("T2D", r"\b(?:t2d|type\s*2 diabetes|diabetic patients?)\b"),
    ("obesity", r"\b(?:obesity|obese)\b"),
    ("older adults", r"\b(?:older adults|elderly|geriatric)\b"),
    ("healthy adults", r"\bhealthy adults?\b"),
)
_COMORBIDITY_PATTERNS: tuple[tuple[str, str], ...] = (
    ("T2D", r"\b(?:t2d|type\s*2 diabetes)\b"),
    ("obesity", r"\b(?:obesity|obese)\b"),
    ("CKD", r"\b(?:ckd|chronic kidney disease)\b"),
    ("cardiovascular disease", r"\b(?:cvd|cardiovascular disease)\b"),
)


@dataclass(frozen=True, slots=True)
class BriefQuery:
    """Structured query used by BRIEFS-V1 downstream filters."""

    question: str
    interventions: tuple[str, ...] = ()
    outcome_classes: tuple[str, ...] = ()
    population: str | None = None
    age_range: tuple[int, int] | None = None
    comorbidities: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "interventions": list(self.interventions),
            "outcome_classes": list(self.outcome_classes),
            "population": self.population,
            "age_range": list(self.age_range) if self.age_range else None,
            "comorbidities": list(self.comorbidities),
        }


def parse_question(question: str) -> BriefQuery:
    """Parse a focused evidence question into the BRIEFS query schema."""
    q = " ".join(question.strip().split())
    if not q:
        raise ValueError("question must be non-empty")
    low = q.lower()
    population = _first_match(low, _POPULATION_PATTERNS)
    comorbidities = tuple(
        label for label, pat in _COMORBIDITY_PATTERNS
        if re.search(pat, low, re.IGNORECASE) and label != population
    )
    return BriefQuery(
        question=q,
        interventions=_extract_interventions(q),
        outcome_classes=_extract_outcomes(low),
        population=population,
        age_range=_extract_age_range(low),
        comorbidities=comorbidities,
    )


def _extract_interventions(question: str) -> tuple[str, ...]:
    span = ""
    for pat in _INTERVENTION_PATTERNS:
        if match := pat.search(question):
            span = match.group("span")
            break
    if not span:
        return ()
    span = _TRAILING_CONTEXT_RE.sub("", _LEADING_NOISE_RE.sub("", span))
    out: list[str] = []
    for piece in _SPLIT_RE.split(span):
        cleaned = piece.strip(" ,.;:?").lower()
        if cleaned and cleaned not in {"the", "evidence"}:
            out.append(cleaned)
    return tuple(dict.fromkeys(out))


def _extract_outcomes(question_lower: str) -> tuple[str, ...]:
    hits: list[tuple[int, str]] = []
    for label, patterns in _OUTCOME_PATTERNS:
        positions = [
            m.start() for pat in patterns
            if (m := re.search(pat, question_lower, re.IGNORECASE))
        ]
        if positions:
            hits.append((min(positions), label))
    return tuple(label for _, label in sorted(hits))


def _first_match(
    question_lower: str, patterns: tuple[tuple[str, str], ...],
) -> str | None:
    for label, pat in patterns:
        if re.search(pat, question_lower, re.IGNORECASE):
            return label
    return None


def _extract_age_range(question_lower: str) -> tuple[int, int] | None:
    if match := re.search(r"\b(\d{2,3})\s*\+", question_lower):
        return (int(match.group(1)), _MAX_AGE)
    if match := re.search(
        r"\b(?:aged?|ages?)\s*(\d{2,3})\s*(?:-|to)\s*(\d{2,3})\b",
        question_lower,
    ):
        low, high = sorted((int(match.group(1)), int(match.group(2))))
        return (low, high)
    if match := re.search(
        r"\b(?:over|older than|at least|>=)\s*(\d{2,3})\b",
        question_lower,
    ):
        return (int(match.group(1)), _MAX_AGE)
    if match := re.search(
        r"\b(?:under|younger than|<)\s*(\d{2,3})\b",
        question_lower,
    ):
        return (0, int(match.group(1)))
    return None
