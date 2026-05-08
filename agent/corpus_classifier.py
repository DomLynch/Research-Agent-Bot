"""5-class corpus classifier — Wave 7 Evidence Factory slice 2 full
(2026-05-05).

Replaces the binary off-topic-vs-keep filter with a 5-class scheme so
the synthesis engine knows WHY each paper is in the corpus and which
citation pool it belongs to:

  core_on_thesis        — primary clinical evidence on the topic
                          (RCT / cohort / meta-analysis directly
                          testing the active intervention)
  background_mechanism  — on-topic mechanism / preclinical citation; kept for
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

import re
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
    "meta-analysis", "systematic review", "clinical trial",
    " randomized ", " randomised ", "double-blind",
    "placebo-controlled",
    "all-cause mortality", "primary prevention",
    "secondary prevention", "incident cancer",
    "incidence of", "real-world evidence", "trial emulation",
    "biobank", "registry-based",
)

_INTERVENTION_CONTEXT_SIGNALS: tuple[str, ...] = (
    "assigned to", "randomized to", "randomised to", "received",
    "receiving", "administered", "supplementation with",
    "treatment with", "therapy with", "use of", "effect of",
    "effects of", "trial of", "evaluated", "compared",
    "versus", " vs ",
)

# "This is a mechanism paper" signals — kept for background only.
_MECHANISM_SIGNALS: tuple[str, ...] = (
    "in vitro", "cell culture", "molecular mechanism",
    "signaling pathway", "kinase activity", "expression of",
    "transcriptional", "protein interaction", "receptor binding",
    "knockout mouse", "transgenic mouse", "pharmacokinetics",
    "pharmacodynamics", "wistar rat", "wistar rats",
    " mouse ", " mice ", " rat ", " rats ", "animal model",
    "animal models", "preclinical", "drosophila", "c. elegans",
    "yeast",
)

# Hard-reject signals — irrelevant species or topics.
_REJECT_SIGNALS: tuple[str, ...] = (
    "traumatic brain injury", " tbi ", "tbi-",
    "burn wound", "cerebral cavernous malformation",
    "atrial fibrillation", "cardioversion", "stroke patients",
    "neurovascular unit", "blood-brain barrier",
)

_DEVICE_ONLY_CONTEXT: tuple[str, ...] = (
    "eluting stent", "drug-eluting stent", "coated stent", "-eluting",
    "eluting stents", "bioresorbable polymer", "coronary stent",
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


def _gather_title(paper: dict[str, Any]) -> str:
    return f" {paper.get('title') or ''} ".lower()


def _aliases_match(text: str, aliases: tuple[str, ...]) -> bool:
    """True if any topic alias appears in the title/abstract text."""
    for alias in aliases:
        a = alias.strip().lower()
        if not a:
            continue
        variants = [a]
        if len(a) >= 4 and a[-1].isalnum() and not a.endswith("s"):
            variants.append(f"{a}s")
        if a.endswith(" inhibitor"):
            variants.append(a.removesuffix(" inhibitor") + " inhibition")
        for variant in variants:
            pattern = rf"(?<![a-z0-9]){re.escape(variant)}(?![a-z0-9])"
            for match in re.finditer(pattern, text):
                lo = max(0, match.start() - 40)
                hi = min(len(text), match.end() + 60)
                context = text[lo:hi]
                if any(signal in context for signal in _DEVICE_ONLY_CONTEXT):
                    continue
                if f"target of {variant}" in context:
                    continue
                return True
    return False


def _alias_device_delivery(text: str, variant: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(variant)}[-\s]*eluting", text) is not None


def _intervention_alias_hits(text: str, aliases: tuple[str, ...]) -> tuple[str, ...]:
    hits: list[str] = []
    for alias in aliases:
        a = alias.strip().lower()
        if not a:
            continue
        variants = [a]
        if len(a) >= 4 and a[-1].isalnum() and not a.endswith("s"):
            variants.append(f"{a}s")
        if a.endswith(" inhibitor"):
            variants.append(a.removesuffix(" inhibitor") + " inhibition")
        for variant in variants:
            if _alias_device_delivery(text, variant):
                continue
            for match in re.finditer(
                rf"(?<![a-z0-9]){re.escape(variant)}(?![a-z0-9])", text,
            ):
                lo = max(0, match.start() - 80)
                hi = min(len(text), match.end() + 80)
                context = text[lo:hi]
                if any(signal in context for signal in _DEVICE_ONLY_CONTEXT):
                    continue
                if any(signal in context for signal in _INTERVENTION_CONTEXT_SIGNALS):
                    hits.append(a)
                    break
            if a in hits:
                break
    return tuple(dict.fromkeys(hits))


def _signal_hits(text: str, signals: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(s for s in signals if s in text)


def _exclude_hits(text: str, exclude_terms: tuple[str, ...]) -> tuple[str, ...]:
    hits: list[str] = []
    for term in exclude_terms:
        t = term.strip().lower()
        if not t:
            continue
        variants = {t, t.replace(" only", "")}
        for variant in variants:
            if variant and variant in text:
                hits.append(t)
                break
    return tuple(hits)


def classify_paper(
    paper: dict[str, Any], *, topic_aliases: tuple[str, ...],
    expected_slots: tuple[str, ...] = (),
    evidence_tier: str = "", directness: str = "",
    exclude_terms: tuple[str, ...] = (),
) -> CorpusClassification:
    """Return a 5-class classification + score + reason. Inputs are
    the parsed paper_sections dict + topic-pack metadata. Pure
    function; no LLM, no IO."""
    text = _gather_text(paper)
    title_text = _gather_title(paper)
    paper_id = paper.get("paper_id") or paper.get("doi") or "_"

    reject_hits = _signal_hits(text, _REJECT_SIGNALS)
    on_topic = _aliases_match(text, topic_aliases)
    title_on_topic = _aliases_match(title_text, topic_aliases)
    core_hits = _signal_hits(text, _CORE_CLINICAL_SIGNALS)
    mech_hits = _signal_hits(text, _MECHANISM_SIGNALS)
    exclusion_hits = _exclude_hits(text, exclude_terms)
    intervention_hits = _intervention_alias_hits(text, topic_aliases)

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

    # Off-thesis: no topic fit. Mechanism markers alone are not
    # enough; otherwise unrelated mechanistic papers pollute every
    # topic's background pool.
    if not on_topic:
        return CorpusClassification(
            paper_id=paper_id, classification="off_thesis",
            score=_CLASS_BASE_SCORE["off_thesis"],
            reason="No topic alias hit; excluded from extraction.",
            signals=mech_hits,
        )

    if not title_on_topic and intervention_hits and core_hits:
        return CorpusClassification(
            paper_id=paper_id, classification="adjacent_clinical",
            score=_CLASS_BASE_SCORE["adjacent_clinical"],
            reason=(
                "Topic alias appears in intervention context outside "
                "title; kept adjacent."
            ),
            signals=tuple(dict.fromkeys((*intervention_hits, *core_hits))),
        )

    if not title_on_topic:
        return CorpusClassification(
            paper_id=paper_id, classification="off_thesis",
            score=_CLASS_BASE_SCORE["off_thesis"],
            reason=(
                "Topic alias appears outside title; excluded from "
                "extraction."
            ),
            signals=core_hits or mech_hits,
        )

    # Core clinical evidence: on topic + core clinical signal
    if on_topic and core_hits:
        if exclusion_hits:
            return CorpusClassification(
                paper_id=paper_id, classification="adjacent_clinical",
                score=_CLASS_BASE_SCORE["adjacent_clinical"],
                reason=(
                    "Topic hit has exclusion context; kept adjacent, "
                    "not core."
                ),
                signals=exclusion_hits,
            )
        if mech_hits:
            return CorpusClassification(
                paper_id=paper_id, classification="background_mechanism",
                score=_CLASS_BASE_SCORE["background_mechanism"],
                reason=(
                    f"On-topic mechanism / preclinical: "
                    f"{', '.join(mech_hits[:3])}"
                ),
                signals=mech_hits,
            )
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

    # Background mechanism: on topic + mechanism markers
    if on_topic and mech_hits:
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
