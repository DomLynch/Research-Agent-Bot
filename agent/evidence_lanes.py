"""Shared source-identity lanes separate model-system evidence from human evidence."""
from __future__ import annotations

import re
from typing import Any, Final

from agent.journal_surface_gate import is_animal_paper
from agent.text_signals import HUMAN_TRIAL_SIGNAL_RE

# Six canonical lanes, ordered by clinical / evidentiary strength.
# Lower index = stronger direct-clinical claim weight.
LANE_TOKENS: Final[tuple[str, ...]] = (
    "human_rct",
    "human_observational",
    "human_mechanistic",
    "review_meta_analysis",
    "animal_preclinical",
    "background_only",
)

LANE_DISPLAY: Final[dict[str, str]] = {
    "human_rct": "Human randomised controlled trial",
    "human_observational": "Human observational study",
    "human_mechanistic": "Human mechanistic / biomarker study",
    "review_meta_analysis": "Review or meta-analysis",
    "animal_preclinical": "Animal / preclinical evidence",
    "background_only": "Background / methodological reference",
}

_HUMAN_POPULATION_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:humans?|people|adults|men|women|human\s+(?:patients?|participants?|subjects?))\b",
    re.IGNORECASE,
)
_CLINICAL_TRIAL_IDENTITY_RE: Final[re.Pattern[str]] = re.compile(
    r"\brandomi[sz]ed(?:\s+controlled)?\s+clinical\s+trial\b",
    re.IGNORECASE,
)


def derive_lane(
    *,
    evidence_tier: str | None,
    directness: str | None,
    title: str | None = None,
    venue: str | None = None,
    population: str | None = None,
    source_excerpt: str | None = None,
) -> str:
    """Classify source identity; human trials outrank incidental animal mentions."""
    # source_excerpt (the receipt's claim-sentence excerpts) is included so
    # species named only in the body text — "in male arctic foxes", "broiler
    # chickens" — flip the lane even when the title is generic.
    tier = (evidence_tier or "").upper()
    direct = (directness or "").lower()
    identity = " ".join(s for s in (title, venue, population) if s)
    animal_identity = is_animal_paper(identity)
    animal_excerpt = is_animal_paper(source_excerpt)
    human_population = bool(_HUMAN_POPULATION_RE.search(identity))
    human_signal = human_population and bool(
        HUMAN_TRIAL_SIGNAL_RE.search(identity)
        or _CLINICAL_TRIAL_IDENTITY_RE.search(identity)
        or re.search(r"\bin (?:healthy |older |younger )?humans?\b", title or "", re.I)
    )
    if direct == "review" or tier == "B1":
        return "review_meta_analysis"
    # Human trial papers routinely mention mouse work in their background.
    # Strong human-study metadata wins unless the source identity itself is
    # explicitly non-human; incidental excerpt text must not relabel the paper.
    if tier == "A1" and not animal_identity and (not animal_excerpt or human_signal):
        return "human_rct"
    if animal_identity or (animal_excerpt and not human_signal):
        return "animal_preclinical"
    if direct == "mechanistic":
        return "human_mechanistic"
    if tier in ("A2", "B2"):
        return "human_observational"
    if tier == "C":
        return "animal_preclinical"
    return "background_only"


def lane_qualifier_phrases_for(lane: str) -> tuple[str, ...]:
    """Academic qualifiers for each source lane; callers require word boundaries."""
    if lane == "animal_preclinical":
        # Slice 26 (2026-05-15): added the everyday-prose terms researchers
        # actually use in body text ("mice", "mouse", "rat", "rats", "in
        # vitro", "cell line"). Senolytics audit surfaced that the writer
        # routinely writes "aged mice" or "in cultured cells" rather than
        # the formal "rodent / murine / in vivo" — so the qualifier check
        # missed legitimate lane-labelled prose. Caller must use word-
        # boundary matching to avoid e.g. "rat" matching "iterate".
        return (
            "animal", "preclinical", "rodent", "murine", "in vivo",
            "model organism", "veterinary", "non-human",
            "equine", "equid", "primate", "macaque", "horse",
            "swine", "porcine", "canine", "ovine",
            # Everyday-prose terms (Slice 26 additions):
            "mouse", "mice", "rat", "rats",
            "dog", "cat", "pig",  # everyday counterparts to canine/feline/porcine
            "in vitro", "cell line",
            "transgenic", "knockout", "knock-out", "wild-type",
        )
    if lane == "human_rct":
        return ("randomised", "randomized", "rct", "clinical trial")
    if lane == "human_observational":
        return ("observational", "cohort", "cross-sectional", "registry")
    if lane == "human_mechanistic":
        return ("mechanistic", "biomarker", "in vitro", "ex vivo")
    if lane == "review_meta_analysis":
        return ("review", "meta-analysis", "systematic", "umbrella")
    return ()


def build_lane_map(receipts: Any) -> dict[str, str]:
    """Map author-year citations to source lanes, accepting typed receipts or dicts."""
    return {str(cite): derive_receipt_lane(receipt) for receipt in receipts
            if (cite := _get(receipt, "citation_token") or _get(receipt, "body_citation"))}



def derive_receipt_lane(receipt: Any) -> str:
    return derive_lane(
        evidence_tier=_get(receipt, "evidence_tier"),
        directness=_get(receipt, "directness"),
        title=_get(receipt, "source_title"),
        venue=_get(receipt, "source_venue"),
        population=_get(receipt, "population_summary"),
        source_excerpt=_get(receipt, "thesis_text"),
    )


def is_animal_context(receipt: Any) -> bool:
    return derive_receipt_lane(receipt) == "animal_preclinical"


def effective_directness(receipt: Any) -> str:
    """Prevent model-system evidence from counting as direct human evidence."""
    directness = str(_get(receipt, "directness") or "indirect").lower()
    return "indirect" if directness == "direct" and derive_receipt_lane(receipt) == "animal_preclinical" else directness


def unisolated_combination(title: str, abstract: str, target: str, aliases: tuple[str, ...] = ()) -> bool:
    """Detect comparisons that do not isolate the target intervention."""
    from agent.results_table import _owned_result_sentence
    record = {"sections": {"abstract": abstract}}
    abstract = " ".join(sentence for sentence in re.split(r"(?<=[.!?])\s+", abstract)
                        if _owned_result_sentence(sentence, record))
    title, abstract, target = (re.sub(r"[_\-\u2010-\u2015]+", " ", value.casefold()) for value in (title, abstract, target))
    terms = {target, *(re.sub(r"[_\-\u2010-\u2015]+", " ", value.casefold()) for value in aliases)} - {""}
    for term in tuple(terms):
        terms.update(re.findall(rf"\b{re.escape(term)}\s*\(([a-z]{{2,5}})\)", abstract))
    patterns = [re.escape(term) for term in sorted(terms, key=len, reverse=True)]
    patterns += [re.escape(short) + r"(?=\s+(?:group|arm)s?\b)" for term in terms if (short := re.sub(r"\s+(?:training|exercise|supplementation|treatment|therapy)$", "", term)) != term]
    target_re = re.compile(r"\b(?:" + "|".join(patterns) + r")\b") if patterns else None
    if target and re.search(
        rf"\b(?:both|all)(?:\s+the)?\s+(?:groups|arms|participants|subjects)\s+"
        rf"(?:received|underwent|performed|completed|participated in)\s+"
        rf"(?:(?:the\s+)?(?:same|identical)\s+)?{re.escape(target)}\b", abstract,
    ):
        return True
    if target_re and target_re.search(abstract):
        shared = re.search(r"\bwhile also (?:participating in|undergoing|completing|receiving)\s+([^.;]+)", abstract)
        if shared and target_re.search(shared[1]) and re.search(r"\b(?:randomi[sz]ed|randomly assigned)\b", abstract):
            return True
        # An explicit randomized contrast defines what the trial isolates;
        # mentioning the topic elsewhere does not make it the treatment contrast.
        contrast_text = re.sub(r"\bdivided into(?=[^.;\n]{0,160}\bplacebo\b)", "randomized into", abstract)
        for match in re.finditer(r"\b(?:randomi[sz]ed|randomly assigned|randomi[sz]ation)(?:\s+\w+){0,4}\s+(?:to|into)\s+(.+?)(?=(?<!\d)\.(?!\d)|[\n]|$)|\btrials comparing\s+([^.;\n]+)|\beffects? of ([^.;]+? compared (?:to|with) [^.;]+?)(?= on | during | for |[.;]|$)", contrast_text):
            comparison = re.split(r"\b(?:for|during|following|after|effects on)\b", match[1] or match[2] or match[3], maxsplit=1)[0]
            comparison = re.sub(r"^.*?groups?:\s*", "", comparison)
            arms = re.split(r";\s*(?:and\s+)?|\s+(?:or|versus|vs\.?|and|compared to|compared with)\s+|,\s*", comparison)
            if len(arms) >= 2 and all(arm.strip() for arm in arms):
                present = [bool(target_re.search(arm)) for arm in arms]
                # Dose/regimen/group labels alone do not identify another intervention.
                anonymous = all(re.fullmatch(r"(?:\d+(?:\.\d+)?\s*(?:mg|mcg|[µu]?g)(?:/\w+)?|(?:low|high|moderate) (?:dose|intensity|volume|frequency)|(?:group|arm) [a-z\d]+|placebo|control|intervention|treatment)", arm.strip()) for arm in arms)
                if not any(present) and not anonymous or all(present) and all(re.search(r"\bplus\b|\+", arm) for arm in arms):
                    return True
    combination = r"\b(?:multi ingredient|combined supplementation|combination|combined [^.!?:]{0,100}\band\b)"
    if re.search(combination, target) or re.search(r"\band\b|\+", target) or not re.search(combination, title):
        return False
    binary = re.search(r"\btwo (?:groups|arms)\b|\b(?:intervention|treatment) or control\b|\bgroup\s*\(\s*placebo,\s*intervention\s*\)", abstract)
    placebo = re.search(r"\bcontrols? (?:group )?maintained usual (?:lifestyle|care)\b|\bcontrol group (?:was )?treated with placebo\s*(?:[.!?]|\(group)|\bplacebo contained[^.!?]+\bonly\b", abstract)
    shared = re.search(r"\b(?:both|all) groups (?:received|took|were given|were treated)\b|\bfactorial\b", abstract)
    return bool(binary and placebo and not shared)


def _get(receipt: Any, field: str) -> str | None:
    """Read a field from either a manifest row or a typed receipt."""
    return receipt.get(field) if isinstance(receipt, dict) and not hasattr(receipt, field) else getattr(receipt, field, None)
