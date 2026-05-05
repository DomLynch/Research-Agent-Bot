"""5-class corpus classifier — Wave 7 Evidence Factory slice 2 full
(2026-05-05).

Replaces the binary off-topic-vs-keep filter with a 5-class scheme so
the synthesis engine knows WHY each paper is in the corpus and which
citation pool it belongs to:

  core_on_thesis        — primary clinical evidence on the topic
                          (RCT / cohort / meta-analysis directly
                          testing the active intervention)
  background_mechanism  — mechanism / preclinical citation; kept for
                          background, not as primary evidence
  adjacent_clinical     — clinical but adjacent (e.g. ezetimibe in a
                          statin synthesis); cited cautiously
  off_thesis            — clinically relevant but wrong topic; kept
                          only if explicitly listed as a comparator
  reject                — preclinical noise / off-domain / spam

Universal across topics — pure heuristic on title + abstract +
topic-pack metadata, no LLM, no per-topic regex bloat. The
classifier emits a *score* (0-100) and a one-line *reason* per
paper so the synthesis engine + dashboard can show operators why
a paper was excluded or downweighted.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Class-specific score floors (also act as upper bounds when classifier
# downgrades on weak signals).
_CLASS_BASE_SCORE: dict[str, int] = {
    "core_on_thesis": 100,
    "background_mechanism": 60,
    "adjacent_clinical": 40,
    "off_thesis": 20,
    "reject": 0,
}

_TIER_BONUS: dict[str, int] = {
    "A1": 30, "A2": 25, "B1": 15, "B2": 10,
    "C1": 5, "C2": 3, "C": 5, "": 0,
}

_DIRECTNESS_BONUS: dict[str, int] = {
    "direct": 20, "indirect": 10, "review": 15,
    "mechanistic": 5, "": 0,
}

# Strong "this is core clinical evidence" signals — RCT, cohort,
# meta-analysis, regulatory mortality endpoints.
_CORE_CLINICAL_SIGNALS: tuple[str, ...] = (
    "randomized controlled trial", "randomised controlled trial",
    " rct ", "(rct)", "cohort study", "case-control study",
    "meta-analysis", "systematic review",
    "all-cause mortality", "primary prevention",
    "secondary prevention", "incident cancer",
    "incidence of", "real-world evidence", "trial emulation",
    "biobank", "registry-based",
)

# "This is a mechanism paper" signals — kept for background only.
_MECHANISM_SIGNALS: tuple[str, ...] = (
    "in vitro", "cell culture", "molecular mechanism",
    "signaling pathway", "kinase activity", "expression of",
    "transcriptional", "protein interaction", "receptor binding",
    "knockout mouse", "transgenic mouse", "pharmacokinetics",
    "pharmacodynamics", "wistar rat", "wistar rats",
    "drosophila", "c. elegans", "yeast",
)

# Hard-reject signals — irrelevant species or topics.
_REJECT_SIGNALS: tuple[str, ...] = (
    "traumatic brain injury", " tbi ", "tbi-",
    "burn wound", "cerebral cavernous malformation",
    "atrial fibrillation", "cardioversion", "stroke patients",
    "neurovascular unit", "blood-brain barrier",
)


@dataclass(frozen=True, slots=True)
class CorpusClassification:
    """One row of the classifier's decision per paper."""
    paper_id: str
    classification: str  # one of the 5 classes
    score: int           # 0-100
    reason: str
    signals: tuple[str, ...]


def _gather_text(paper: dict[str, Any]) -> str:
    title = paper.get("title") or ""
    abstract = (paper.get("sections") or {}).get("abstract") or ""
    return f" {title} {abstract} ".lower()


def _aliases_match(text: str, aliases: tuple[str, ...]) -> bool:
    """True if any topic alias appears in the title/abstract text."""
    return any(a in text for a in aliases)


def _signal_hits(text: str, signals: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(s for s in signals if s in text)


def classify_paper(
    paper: dict[str, Any], *, topic_aliases: tuple[str, ...],
    expected_slots: tuple[str, ...] = (),
    evidence_tier: str = "", directness: str = "",
) -> CorpusClassification:
    """Return a 5-class classification + score + reason. Inputs are
    the parsed paper_sections dict + topic-pack metadata. Pure
    function; no LLM, no IO."""
    text = _gather_text(paper)
    paper_id = paper.get("paper_id") or paper.get("doi") or "_"

    reject_hits = _signal_hits(text, _REJECT_SIGNALS)
    on_topic = _aliases_match(text, topic_aliases)
    core_hits = _signal_hits(text, _CORE_CLINICAL_SIGNALS)
    mech_hits = _signal_hits(text, _MECHANISM_SIGNALS)

    # Hard reject: irrelevant species/topic AND no topic alias hit
    if reject_hits and not on_topic:
        return CorpusClassification(
            paper_id=paper_id, classification="reject",
            score=_CLASS_BASE_SCORE["reject"],
            reason=(
                f"Hard-reject signal(s): {', '.join(reject_hits[:3])}; "
                f"no topic alias hit."
            ),
            signals=reject_hits,
        )

    # Off-thesis: not on topic AND not a generic mechanism paper
    if not on_topic and not mech_hits:
        return CorpusClassification(
            paper_id=paper_id, classification="off_thesis",
            score=_CLASS_BASE_SCORE["off_thesis"],
            reason="No topic alias hit and no mechanism signals.",
            signals=(),
        )

    # Core clinical evidence: on topic + core clinical signal
    if on_topic and core_hits:
        score = _CLASS_BASE_SCORE["core_on_thesis"]
        score = min(100, score)
        return CorpusClassification(
            paper_id=paper_id, classification="core_on_thesis",
            score=score,
            reason=(
                f"On-topic clinical evidence: "
                f"{', '.join(core_hits[:3])}"
            ),
            signals=core_hits,
        )

    # Background mechanism: on topic OR off-topic mechanism markers
    if mech_hits:
        return CorpusClassification(
            paper_id=paper_id, classification="background_mechanism",
            score=_CLASS_BASE_SCORE["background_mechanism"],
            reason=(
                f"Mechanism / preclinical: "
                f"{', '.join(mech_hits[:3])}"
            ),
            signals=mech_hits,
        )

    # On topic but no clinical signal → adjacent clinical (or weak topic match)
    if on_topic:
        return CorpusClassification(
            paper_id=paper_id, classification="adjacent_clinical",
            score=_CLASS_BASE_SCORE["adjacent_clinical"],
            reason=(
                "On-topic but no clear clinical-evidence signal; "
                "treated as adjacent."
            ),
            signals=(),
        )

    # Fallback: off-thesis (caught earlier, defensive)
    return CorpusClassification(
        paper_id=paper_id, classification="off_thesis",
        score=_CLASS_BASE_SCORE["off_thesis"],
        reason="Unclassified — falls through to off-thesis.",
        signals=(),
    )


def score_paper(
    classification: CorpusClassification, *,
    evidence_tier: str = "", directness: str = "",
    publication_year: int | None = None, current_year: int = 2026,
) -> int:
    """Bump a classification's base score by tier / directness /
    recency. Returns 0-100. Universal across topics — input fields
    come from the synthesis manifest, not topic-pack."""
    score = classification.score
    score += _TIER_BONUS.get(evidence_tier, 0)
    score += _DIRECTNESS_BONUS.get(directness, 0)
    if publication_year:
        age = current_year - publication_year
        if age <= 5:
            score += 10
        elif age <= 10:
            score += 5
    return max(0, min(100, score))


def classify_corpus(
    papers: list[dict[str, Any]], *, topic_aliases: tuple[str, ...],
    expected_slots: tuple[str, ...] = (),
) -> list[CorpusClassification]:
    """Classify every paper, return a list of CorpusClassifications.
    Caller decides what to do with each class (synthesis pipeline
    drops 'reject' and 'off_thesis', keeps the rest as appropriate
    citation pools)."""
    return [
        classify_paper(
            p, topic_aliases=topic_aliases,
            expected_slots=expected_slots,
        )
        for p in papers
    ]


__all__ = [
    "CorpusClassification",
    "classify_paper",
    "classify_corpus",
    "score_paper",
]
