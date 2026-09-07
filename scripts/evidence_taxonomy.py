"""Deterministic evidence taxonomy from study_design, species and endpoint_kind.
The legacy inference path uses the paper's title/abstract, not its identifier prefix.
  - A1: direct human RCT with clinical/functional endpoint
  - A2: human mechanistic intervention study
  - B1: systematic / narrative review
  - B2: human observational cohort
  - C1: animal / model-organism preclinical
  - C2: molecular / mechanistic review
  - D1: protocol without reported results

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
from typing import Iterable


@dataclass(frozen=True, slots=True, kw_only=True)
class EvidenceClassification:
    """One paper's evidence tier + directness + audit rationale.

    Cross-stage object → frozen+slots+kw_only per project rule."""
    tier: str           # A1 | A2 | B1 | B2 | C1 | C2 | unknown
    directness: str     # direct | indirect | mechanistic | review | unknown
    rationale: str      # one-sentence why-this-tier (audit trail)


def public_directness_phrase(tiers: Iterable[str], directnesses: Iterable[str]) -> str:
    """Reader-facing directness phrase from existing tier/directness labels."""
    tier_set = {str(t or "").upper() for t in tiers}
    direct_set = {str(d or "").lower() for d in directnesses}
    if "A1" in tier_set or "direct" in direct_set:
        return "direct interventional evidence is present"
    if "A2" in tier_set:
        return "human interventional surrogate-endpoint evidence is present"
    if "B2" in tier_set or "indirect" in direct_set:
        return "human observational/prognostic evidence is present"
    if "B1" in tier_set or "review" in direct_set:
        return "review-level evidence is present"
    if {"C1", "C2"} & tier_set or "mechanistic" in direct_set:
        return "preclinical/mechanistic evidence is present"
    if "protocol" in direct_set or "D1" in tier_set:
        return "only registered study protocols (no results reported yet) are present"
    return "directness is not yet classifiable from the structured metadata"


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
    "mouse", "mice", "murine", "rat", "rats", "rodent", "rodents",
    "c. elegans", "c elegans", "nematode", "nematodes",
    "worm", "worms", "yeast", "drosophila", "fly", "flies", "zebrafish",
    "monkey", "monkeys", "macaque", "macaques", "baboon", "baboons",
    "non-human primate", "nonhuman primate", "marmoset", "marmosets",
    "dog", "dogs", "rabbit", "rabbits", "hamster", "hamsters",
    "guinea pig", "fox", "foxes", "vulpes",
    "broiler", "broilers", "chicken", "chickens", "poultry", "fowl",
    "avian", "cow", "cows", "cattle", "bovine",
    "pig", "pigs", "piglet", "piglets", "porcine", "swine",
    "sheep", "ovine", "goat", "goats", "caprine",
    "horse", "horses", "equine",
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
    "case report", "case series", "case-by-case",
)
_DESIGN_PRECLINICAL_TOKENS: tuple[str, ...] = (
    "animal study", "preclinical", "in vivo", "in vitro",
    "cell culture", "cell line", "molecular study", "biochemical",
)
# Registered study protocols / design papers announce a trial but carry
# NO results yet. Their strings match the RCT tokens above
# ("randomized, double-blind, placebo-controlled") so they MUST be
# detected first — otherwise a protocol is misgraded as A1 direct
# efficacy evidence. Topic-agnostic markers: design/plan papers across
# any domain phrase themselves this way.
_DESIGN_PROTOCOL_TOKENS: tuple[str, ...] = (
    "study protocol", "trial protocol", "research protocol",
    "protocol for a", "protocol for the", "rationale and design",
    "design and rationale", "rationale and study design", "statistical analysis plan",
)


def _normalize(value: str | None) -> str:
    return (value or "").strip().lower()


def _has_token(haystack: str, tokens: tuple[str, ...]) -> bool:
    return any(t in haystack for t in tokens)


def _is_human(species: str) -> bool:
    return _has_token(species, _SPECIES_HUMAN_TOKENS)


def _is_animal(species: str) -> bool:
    return _has_token(species, _SPECIES_ANIMAL_TOKENS)


# Free-text population classifier. `_is_human`/`_is_animal` substring-
# match the *controlled* `species` metadata field; `population_of` scans
# *free text* (title + abstract + claim sentences) so it must be word-
# boundary-anchored — bare "rat" must not fire inside "literature",
# "cow" inside "coworker", "fox" inside "foxglove". Lookarounds (not
# \b) so multi-word / punctuated tokens ("guinea pig", "c. elegans")
# anchor correctly.
def _word_boundary_re(tokens: tuple[str, ...]) -> "re.Pattern[str]":
    parts = sorted((re.escape(t) for t in tokens), key=len, reverse=True)
    return re.compile(r"(?<![a-z])(?:" + "|".join(parts) + r")(?![a-z])", re.I)


_HUMAN_TEXT_RE = _word_boundary_re(_SPECIES_HUMAN_TOKENS)
_ANIMAL_TEXT_RE = _word_boundary_re(_SPECIES_ANIMAL_TOKENS)


def population_of(text: str) -> str:
    """Classify a source's study population from free text as
    'human' | 'animal' | 'unknown'.

    Human markers win ties: a translational "mouse model of human
    disease" source stays 'human' and is therefore never pruned on
    population grounds — only an unambiguously non-human source (an
    animal marker present, no human marker) is classifiable 'animal'.
    Universal species vocabulary — no per-topic tokens. Consumed by the
    relative corpus population-coherence gate in run_v06_synthesis."""
    blob = _normalize(text)
    if _HUMAN_TEXT_RE.search(blob):
        return "human"
    if _ANIMAL_TEXT_RE.search(blob):
        return "animal"
    return "unknown"


def _design_class(design: str) -> str:
    """Bucket a design string into one of: protocol | rct | observational |
    review | preclinical | unknown.

    P1 reviewer fix: substring matching (not exact-string) so canonical
    publication_type values from PubMed/CrossRef classify correctly:
      - 'Randomised, double-blind, placebo-controlled trial' → rct
      - 'Phase 3 randomized controlled trial' → rct
    Order: protocol markers FIRST (a protocol string also contains the
    RCT tokens), then strong review markers (so 'systematic review of
    randomized controlled trials' is review, not RCT)."""
    if _has_token(design, _DESIGN_PROTOCOL_TOKENS):
        return "protocol"
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

    if design == "protocol":
        # Registered protocol / design paper: the trial is announced but
        # NO outcomes are reported yet. It is neither primary nor direct
        # evidence — grade it lowest-weight (D1) with a dedicated
        # directness so downstream excludes it from direct-efficacy
        # comparisons instead of crediting it as an A1 result.
        return EvidenceClassification(
            tier="D1", directness="protocol",
            rationale=(
                "registered study protocol / design paper — trial "
                "announced but NO results reported yet → D1, excluded "
                "from direct-efficacy evidence"
            ),
        )

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
# Registered-protocol markers. Matched against the TITLE ONLY (see
# infer_from_paper_meta): a protocol paper announces itself in its
# title, whereas a results paper that merely mentions "the study
# protocol" in its abstract must NOT be downgraded.
_TITLE_PROTOCOL_RE = re.compile(
    r"\b(study protocol|trial protocol|research protocol|"
    r"protocol (?:for|of)(?: (?:a|an|the))?|rationale and design|"
    r"design and rationale|rationale and study design|statistical analysis plan)\b",
    re.IGNORECASE,
)
_TITLE_RCT_RE = re.compile(
    r"\b(randomi[sz]ed|randomly assigned|RCT|placebo[\-\s]?controlled|double[\-\s]?blind)\b",
    re.IGNORECASE,
)
_TITLE_OBSERVATIONAL_RE = re.compile(
    r"\b(cohort|registry|observational|target trial|emulation|"
    r"retrospective|prospective|case[\-\s]?control|case reports?|case series|case-by-case|single[\-\s]?(?:arm|group)|non[\-\s]?randomi[sz]ed)\b",
    re.IGNORECASE,
)
_NONRANDOMIZED_DESIGN_RE = re.compile(
    r"\b(?:single[\-\s]?(?:arm|group)|non[\-\s]?randomi[sz]ed|observational|retrospective|case reports?|case series|case-by-case)\b", re.I,
)
_FUTURE_TRIAL_RE = re.compile(
    r"\b(?:trials?\s+(?:are|is)\s+(?:needed|required|warranted)|"
    r"(?:need(?:ed)?|requires?|warrants?|future)\b[^.!?]*\btrials?|"
    r"trials?\s+to\s+(?:confirm|test))\b", re.I,
)
# P1 reviewer fix: drop the bare "review" keyword — it false-fires on
# "RCT methodology review", "Cohort design review", etc. Only multi-
# word strong-review patterns count.
_TITLE_REVIEW_RE = re.compile(
    r"\b(systematic review|meta[\-\s]?analys(?:is|es)|narrative review|"
    r"scoping review|critical review|umbrella review|"
    r"literature review|pooled analysis|review of)\b",
    re.IGNORECASE,
)
_TITLE_PRECLINICAL_RE = re.compile(
    r"\b(in vitro|in vivo|preclinical|cell culture|molecular|"
    r"mechanistic|mechanism|biochemical)\b",
    re.IGNORECASE,
)
_TITLE_ANIMAL_RE = re.compile(
    r"\b(mouse|mice|rat|rats|c\.?\s*elegans|drosophila|yeast|"
    r"primate|marmoset|zebrafish|fish|bass|nematode|worm)\b",
    re.IGNORECASE,
)
# P3 reviewer fix: dropped diabetic/t2d/frailty — these are conditions,
# not species markers. Mouse models of diabetes / frailty exist.
_TITLE_HUMAN_RE = re.compile(
    r"\b(human|patients|adults|older adults|men|women|elderly|"
    r"males|females|participants|subjects)\b",
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
_UNICODE_DASH_RE = re.compile(r"[\u00ad\u2010-\u2015\u2212]")


def _normalize_study_text(value: object) -> str:
    return _UNICODE_DASH_RE.sub("-", str(value or ""))


def _is_protocol_paper(title: str, abstract: str) -> bool:
    return bool(_TITLE_PROTOCOL_RE.search(title) or (
        re.search(r"\bstudy design\s*$", title, re.I)
        and re.search(r"\b(?:trial|study) is designed to\b", abstract, re.I)
    ))


def is_primary_randomized_study(title: str, abstract: str = "", *, study_design: str = "") -> bool:
    title, abstract, study_design = map(_normalize_study_text, (title, abstract, study_design))
    identity_text = f"{title} {study_design}"
    # Structured abstracts often cite earlier trials in Background, not Methods.
    methods = re.search(r"\bmethods?\s*:\s*(.*?)(?=\b(?:results?|conclusions?|discussion)\s*:|$)", abstract, re.I | re.S)
    design_text = methods.group(1) if methods else abstract
    # Calls for future trials describe missing evidence, not this study's design.
    trial_evidence = " ".join(sentence for sentence in re.split(r"[.!?]\s+", design_text)
                              if not _FUTURE_TRIAL_RE.search(sentence)
                              and not _NONRANDOMIZED_DESIGN_RE.search(sentence))
    return bool(
        not _is_protocol_paper(title, abstract)
        and not _TITLE_PROTOCOL_RE.search(study_design)
        and not _TITLE_REVIEW_RE.search(identity_text)
        and not _NONRANDOMIZED_DESIGN_RE.search(identity_text)
        and (
            _TITLE_RCT_RE.search(identity_text)
            or (_TITLE_RCT_RE.search(trial_evidence) and not _TITLE_REVIEW_RE.search(abstract))
        )
    )


def infer_from_paper_meta(paper_meta: dict) -> EvidenceClassification:
    """Best-effort classification from a parsed-paper metadata dict
    (title + abstract). For corpora that haven't been annotated with
    explicit fields yet.

    Order: protocol FIRST (a registered protocol has no results — never
    A1), then review ('Systematic review of RCTs' is B1, not A1), then
    RCT, observational, preclinical."""
    title = _normalize_study_text(paper_meta.get("title"))
    abstract = _normalize_study_text(paper_meta.get("abstract"))
    haystack = f"{title} {abstract}"

    # Require title evidence; design-only titles also need an explicit
    # planned-trial statement, not merely a mention of a study protocol.
    if _is_protocol_paper(title, abstract):
        design = "study protocol"
    elif _TITLE_REVIEW_RE.search(haystack):
        design = "systematic review"
    elif is_primary_randomized_study(title, abstract):
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
