"""Fix #4: Evidence taxonomy — A1/A2/B1/B2/C1/C2 from structured
metadata, NOT inferred from prose.

Pre-fix: human observational mortality studies were tagged
`directness=mechanistic` because the heuristic in
`_classify_paper_tier` checked only receipt_id prefix (`PMC` →
"mechanistic"). MET-PREVENT (Witham 2025, a real human RCT) was
tagged `effect_direction=positive` even though the trial's primary
walk-speed result was null (0.001 m/s, p=0.96).

Fix: per-paper deterministic classifier from structured metadata
(study_design + species + endpoint_kind). Returns one of:

  - A1: direct human RCT with clinical/functional endpoint
  - A2: human mechanistic intervention study
  - B1: systematic / narrative review
  - B2: human observational cohort
  - C1: animal / model-organism preclinical
  - C2: molecular / mechanistic review

When metadata is insufficient, returns `tier="unknown"` and a
rationale — the audit can flag those for manual annotation.

Architecture: pure deterministic module. No LLM, no I/O. The classifier
operates on a structured dict; a separate `infer_from_paper_meta`
helper does best-effort extraction from title/abstract for legacy
runs that don't have explicit fields yet.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True, kw_only=True)
class EvidenceClassification:
    """One paper's evidence tier + directness + audit rationale.

    Cross-stage object → frozen+slots+kw_only per project rule."""
    tier: str           # A1 | A2 | B1 | B2 | C1 | C2 | unknown
    directness: str     # direct | indirect | mechanistic | review | unknown
    rationale: str      # one-sentence why-this-tier (audit trail)


# Vocabulary normalization. The classifier accepts either canonical
# values or close synonyms — calling code may produce different
# casings or phrasings depending on metadata source.
# Species marker tokens. Tight set — only species-denoting strings,
# no roles ("patients", "subjects" are roles, not species).
_SPECIES_HUMAN_TOKENS: tuple[str, ...] = (
    "human", "humans", "homo sapiens", "men", "women", "older adults",
    "adults", "elderly", "patients", "people", "participants",
    "children",
)
_SPECIES_ANIMAL_TOKENS: tuple[str, ...] = (
    "mouse", "mice", "rat", "rats", "c. elegans", "c elegans",
    "worm", "worms", "yeast", "drosophila", "fly", "flies",
    "monkey", "monkeys", "non-human primate", "marmoset", "marmosets",
    "dog", "dogs", "rabbit", "rabbits",
)

# Design markers — STRONG (high-precision) vs WEAK (broader, lower
# precision). Strong markers win order-independent; weak markers only
# fire if no strong marker matched. Substring (not exact) matching so
# real-world publication_type strings ("Randomised, double-blind,
# placebo-controlled trial", "Phase 3 randomized controlled trial")
# classify correctly.

# Strong review markers: only multi-word patterns that are specific
# to review papers (the bare word "review" is too permissive — it
# false-fires on RCT-of-reviews + methodology papers).
_DESIGN_REVIEW_STRONG: tuple[str, ...] = (
    "systematic review", "meta-analysis", "meta analysis",
    "narrative review", "scoping review", "umbrella review",
    "literature review",
)
_DESIGN_RCT_TOKENS: tuple[str, ...] = (
    "randomized controlled trial", "randomised controlled trial",
    "randomized clinical trial", "randomised clinical trial",
    "randomized trial", "randomised trial",
    "double-blind", "double blind",
    "placebo-controlled", "placebo controlled",
    "rct",
    "randomized", "randomised",
)
_DESIGN_OBSERVATIONAL_TOKENS: tuple[str, ...] = (
    "target trial emulation", "registry-based", "registry analysis",
    "prospective cohort", "retrospective cohort", "ehr cohort",
    "cohort study", "cohort", "case-control", "case control",
    "observational", "retrospective", "prospective",
)
_DESIGN_PRECLINICAL_TOKENS: tuple[str, ...] = (
    "animal study", "preclinical", "in vivo", "in vitro",
    "cell culture", "cell line", "molecular study", "biochemical",
)


def _normalize(value: str | None) -> str:
    return (value or "").strip().lower()


def _has_token(haystack: str, tokens: tuple[str, ...]) -> bool:
    return any(t in haystack for t in tokens)


def _is_human(species: str) -> bool:
    return _has_token(species, _SPECIES_HUMAN_TOKENS)


def _is_animal(species: str) -> bool:
    return _has_token(species, _SPECIES_ANIMAL_TOKENS)


def _design_class(design: str) -> str:
    """Bucket a design string into one of: rct | observational | review |
    preclinical | unknown.

    P1 reviewer fix: substring matching (not exact-string) so canonical
    publication_type values from PubMed/CrossRef classify correctly:
      - 'Randomised, double-blind, placebo-controlled trial' → rct
      - 'Phase 3 randomized controlled trial' → rct
    Order: strong review markers FIRST so 'systematic review of
    randomized controlled trials' is review, not RCT."""
    if _has_token(design, _DESIGN_REVIEW_STRONG):
        return "review"
    if _has_token(design, _DESIGN_RCT_TOKENS):
        return "rct"
    if _has_token(design, _DESIGN_OBSERVATIONAL_TOKENS):
        return "observational"
    if _has_token(design, _DESIGN_PRECLINICAL_TOKENS):
        return "preclinical"
    return "unknown"


def classify_evidence(
    *,
    study_design: str | None,
    species: str | None,
    endpoint_kind: str | None,
) -> EvidenceClassification:
    """Deterministic A1/A2/B1/B2/C1/C2 classification from metadata.

    `endpoint_kind` ∈ {clinical, functional, surrogate, mechanistic,
    mortality, longevity}; controls A1 vs A2 split for human RCTs."""
    design = _design_class(_normalize(study_design))
    sp = _normalize(species)
    ek = _normalize(endpoint_kind)

    if design == "rct" and _is_human(sp):
        # P2 reviewer fix: surrogate endpoints (HbA1c, BP, LDL) are
        # validated clinical biomarkers, not mechanism markers — they
        # belong with A1 per regulatory convention. Only true mechanism
        # endpoints (pathway, expression, biomarker) drop to A2.
        if ek in {"clinical", "functional", "mortality",
                  "longevity", "surrogate"}:
            return EvidenceClassification(
                tier="A1", directness="direct",
                rationale=(
                    f"human RCT with {ek} endpoint → A1 (direct clinical "
                    "evidence)"
                ),
            )
        if ek == "mechanistic":
            return EvidenceClassification(
                tier="A2", directness="indirect",
                rationale=(
                    "human RCT but mechanistic endpoint (pathway / "
                    "expression / biomarker) → A2"
                ),
            )
        return EvidenceClassification(
            tier="A1", directness="direct",
            rationale=(
                "human RCT, endpoint_kind unspecified → A1 by default; "
                "tag endpoint_kind for sharper classification"
            ),
        )

    if design == "review":
        return EvidenceClassification(
            tier="B1", directness="review",
            rationale="systematic / narrative review → B1",
        )

    if design == "observational" and _is_human(sp):
        # P2 reviewer fix: include endpoint_kind in rationale so the
        # downstream audit can see "B2 mortality" vs "B2 mechanistic"
        # — different evidence strength inside the same tier.
        endpoint_note = f", {ek} endpoint" if ek else ""
        return EvidenceClassification(
            tier="B2", directness="indirect",
            rationale=(
                f"human observational cohort{endpoint_note} → B2 "
                "(NOT mechanistic — confounding-prone but human-direct)"
            ),
        )

    if design == "preclinical" or _is_animal(sp):
        # P1 reviewer fix: dropped duplicate dead branch. Single C1
        # path for animal/preclinical regardless of endpoint_kind.
        return EvidenceClassification(
            tier="C1", directness="mechanistic",
            rationale=(
                f"{species or 'animal'} preclinical / model-organism "
                "study → C1"
            ),
        )

    # Contradiction guard: explicit preclinical design WITH human
    # species is a metadata error; surface it instead of silent fall-
    # through.
    if design == "preclinical" and _is_human(sp):
        return EvidenceClassification(
            tier="unknown", directness="unknown",
            rationale=(
                f"contradictory metadata: design=preclinical with "
                f"species={species!r} (human) — fix the source data"
            ),
        )

    if design == "unknown" and not sp:
        return EvidenceClassification(
            tier="unknown", directness="unknown",
            rationale=(
                "metadata insufficient: missing study_design AND species "
                "— add explicit fields to enable classification"
            ),
        )

    if design == "unknown" and not _is_human(sp) and not _is_animal(sp):
        return EvidenceClassification(
            tier="C2", directness="review",
            rationale=(
                "design unspecified, species unclear → C2 (mechanistic / "
                "molecular review by default)"
            ),
        )

    return EvidenceClassification(
        tier="unknown", directness="unknown",
        rationale=(
            f"unhandled metadata combination: "
            f"design={study_design!r} species={species!r} "
            f"endpoint_kind={endpoint_kind!r}"
        ),
    )


# Best-effort metadata extraction for legacy paper-meta dicts that
# don't yet have explicit study_design / species / endpoint_kind
# fields. Title-keyword heuristics — NOT a substitute for metadata
# annotation, but lets the deterministic classifier produce
# reasonable defaults on the existing corpus.
_TITLE_RCT_RE = re.compile(
    r"\b(randomi[sz]ed|RCT|placebo[\-\s]?controlled|double[\-\s]?blind)\b",
    re.IGNORECASE,
)
_TITLE_OBSERVATIONAL_RE = re.compile(
    r"\b(cohort|registry|observational|target trial|emulation|"
    r"retrospective|prospective|case[\-\s]?control)\b",
    re.IGNORECASE,
)
# P1 reviewer fix: drop the bare "review" keyword — it false-fires on
# "RCT methodology review", "Cohort design review", etc. Only multi-
# word strong-review patterns count.
_TITLE_REVIEW_RE = re.compile(
    r"\b(systematic review|meta[\-\s]?analysis|narrative review|"
    r"scoping review|critical review|umbrella review|"
    r"literature review)\b",
    re.IGNORECASE,
)
_TITLE_PRECLINICAL_RE = re.compile(
    r"\b(in vitro|in vivo|preclinical|cell culture|molecular|"
    r"mechanistic|biochemical)\b",
    re.IGNORECASE,
)
_TITLE_ANIMAL_RE = re.compile(
    r"\b(mouse|mice|rat|rats|c\.?\s*elegans|drosophila|yeast|"
    r"primate|marmoset)\b",
    re.IGNORECASE,
)
# P3 reviewer fix: dropped diabetic/t2d/frailty — these are conditions,
# not species markers. Mouse models of diabetes / frailty exist.
_TITLE_HUMAN_RE = re.compile(
    r"\b(human|patients|adults|older adults|men|women|elderly|"
    r"participants|subjects)\b",
    re.IGNORECASE,
)
_TITLE_MORTALITY_RE = re.compile(
    r"\b(mortality|all[\-\s]?cause death|survival|lifespan|longevity)\b",
    re.IGNORECASE,
)
_TITLE_FUNCTIONAL_RE = re.compile(
    r"\b(walk speed|grip strength|frailty|physical performance|"
    r"VO2 ?max|sarcopenia|functional)\b",
    re.IGNORECASE,
)
_TITLE_MECHANISTIC_RE = re.compile(
    r"\b(mechanism|pathway|signaling|expression|biomarker|"
    r"protein|gene)\b",
    re.IGNORECASE,
)


def infer_from_paper_meta(paper_meta: dict) -> EvidenceClassification:
    """Best-effort classification from a parsed-paper metadata dict
    (title + abstract). For corpora that haven't been annotated with
    explicit fields yet.

    Order: review FIRST (P1 reviewer fix — 'Systematic review of RCTs'
    is B1, not A1). Then RCT, observational, preclinical."""
    title = paper_meta.get("title") or ""
    abstract = paper_meta.get("abstract") or ""
    haystack = f"{title} {abstract}"

    if _TITLE_REVIEW_RE.search(haystack):
        design = "systematic review"
    elif _TITLE_RCT_RE.search(haystack):
        design = "randomized controlled trial"
    elif _TITLE_OBSERVATIONAL_RE.search(haystack):
        design = "cohort"
    elif _TITLE_PRECLINICAL_RE.search(haystack):
        design = "preclinical"
    else:
        design = ""

    if _TITLE_ANIMAL_RE.search(haystack):
        species = "mouse"
    elif _TITLE_HUMAN_RE.search(haystack):
        species = "human"
    else:
        species = ""

    if _TITLE_MORTALITY_RE.search(haystack):
        endpoint_kind = "mortality"
    elif _TITLE_FUNCTIONAL_RE.search(haystack):
        endpoint_kind = "functional"
    elif _TITLE_MECHANISTIC_RE.search(haystack):
        endpoint_kind = "mechanistic"
    else:
        endpoint_kind = ""

    return classify_evidence(
        study_design=design or None,
        species=species or None,
        endpoint_kind=endpoint_kind or None,
    )
