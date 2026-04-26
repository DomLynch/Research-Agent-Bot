"""Deterministic role / tier / design / directness classifier.

Pure functions. No LLM. Same input -> same output. The classifier is the
single typed contract that prevents the LLM from contradicting metadata
in compose.py and beyond.

CLASSIFICATION TRUTH TABLE
==========================

Step 1 - role  (the most load-bearing decision)
| Signal                                                 | role                  |
|--------------------------------------------------------|-----------------------|
| source=clinicaltrials AND has_results=True             | published_results     |
| source=clinicaltrials AND has_results=False            | registered_pending    |
| title or abstract has REVIEW marker                    | review                |
| abstract has PROTOCOL marker but no REPORTED_OUTCOME   | published_protocol    |
| abstract has REPORTED_OUTCOME (effect, p, CI, %, ...)  | published_results     |
| abstract has only MECHANISTIC markers                  | mechanistic           |
| anything else                                          | mechanistic (default) |

Step 2 - design  (derived from role + abstract markers)
| role + signal                            | design          |
|------------------------------------------|-----------------|
| published_results + RANDOMIZED marker    | rct             |
| published_results without randomized     | observational   |
| review + META_ANALYSIS marker            | meta_analysis   |
| review (other)                           | review          |
| published_protocol                       | protocol        |
| registered_pending                       | registry        |
| mechanistic                              | mechanistic     |

Step 3 - tier   (evidence quality, A1 best)
| condition                                                | tier |
|----------------------------------------------------------|------|
| design in {rct, meta_analysis} AND venue is high-impact  | A1   |
| design in {rct, meta_analysis}                           | A2   |
| role=published_results, design=observational             | A2   |
| role=review                                              | A2   |
| role in {published_protocol, registered_pending}         | B    |
| role=mechanistic                                         | C    |

Step 4 - direct (binary, defaults True; degraded by mismatch with domain or topic)
| condition                                                       | direct |
|-----------------------------------------------------------------|--------|
| ANIMAL or CELL marker AND domain looks human-focused            | False  |
| PEDIATRIC marker AND domain mentions adult/older                | False  |
| topic provided AND no topic anchor appears in title+abstract    | False  |
| otherwise                                                       | True   |

The topic-anchor gate prevents off-topic candidates (RTB101 in a rapamycin
query, young-plasma trials in a senolytics query) from being marked as
direct evidence just because they're human studies.

Step 5 - strict (whether the item meets criteria's strict-eligibility bar)
| condition                                                       | strict |
|-----------------------------------------------------------------|--------|
| direct=False                                                    | False  |
| year present AND year >= criteria_min_year (if specified)       | True   |
| no year filter or no year info                                  | True   |

If the truth table changes, update this docstring AND the per-rule constant
below in lockstep. Tests in test_bundle.py drive every row.
"""
from __future__ import annotations

import re
from collections.abc import Mapping

from agent.types import Design, EvidenceItem, Role, Source, Tier

# --- Marker dictionaries (lowercase substring matches against abstract+title) ---

_REVIEW = (
    "systematic review",
    "meta-analysis",
    "meta analysis",
    "umbrella review",
    "narrative review",
    "scoping review",
    "literature review",
)
_META_ANALYSIS = ("meta-analysis", "meta analysis")
_PROTOCOL = (
    "study protocol",
    "trial protocol",
    "is a protocol",
    "rationale and design",
    "study design and rationale",
    "design of a randomized",
    "design of a randomised",
    "design of an open-label",
    # Real-world protocol-paper phrasings caught during day 2 audit
    # (PMID 39354527 RAPA-EX-01 protocol paper missed by the original list).
    "study to evaluate",
    "study evaluates the safety and efficacy",
    "evaluates the safety and efficacy",
    "trial investigating",
    "trial designed to",
    "this study examines whether",
    "we will assess",
    "we will evaluate",
    "we will examine",
    "study will assess",
    "study will evaluate",
    "study will examine",
    "study will test",
    "this study aims to",
    "study is to assess",
    "study is to evaluate",
    "study is to determine",
)
# Patterns use word boundaries (\b) so "Mice were treated" matches as well
# as "transgenic mice." String containment (" mice ") was too brittle —
# missed sentence-initial and post-punctuation cases.
_RANDOMIZED_RE = re.compile(
    r"\b(randomi[sz]ed|rct|double[-\s]blind|placebo[-\s]controlled)\b",
    re.IGNORECASE,
)
# Numeric outcome regex: must signal a *reported result*, not an enrollment
# count or a population descriptor. Markers retained from day 2:
#   - p-values (p = 0.03, p<0.05)
#   - confidence intervals
#   - effect-size verbs paired with a number ("reduced by 22%", "increased 3x")
#   - hazard / odds / risk ratios
#   - explicit "mean difference" / "mean change" pairs
# Markers removed in audit:
#   - bare \d+\s*% (matched "60% female" in protocol abstracts)
#   - bare n=\d{2,} (matched "n=24 mice" in mechanistic abstracts)
# The bare patterns are now gated behind effect-verb proximity.
_REPORTED_OUTCOME_RE = re.compile(
    r"(\bp\s*[=<>]\s*0?\.\d+"
    r"|95\s*%\s*ci"
    r"|\bhazard\s+ratio|\bodds\s+ratio|\brisk\s+ratio"
    r"|\bhr\s*=?\s*\d|\bor\s*=?\s*\d|\brr\s*=?\s*\d"
    r"|(?:reduced|increased|improved|decreased|lowered|raised|"
    r"declined|reversed|attenuated)\s+(?:by\s+)?\d+(?:\.\d+)?\s*%"
    r"|\bmean\s+(?:difference|change|reduction|increase)"
    r"|\b(?:participants|patients|subjects|adults)\s+\(\s*n\s*=\s*\d{2,}\s*\))",
    re.IGNORECASE,
)
_MECHANISTIC_RE = re.compile(
    r"\b(in[-\s]vitro|ex\s+vivo|cell\s+(line|culture)|transgenic\s+mice|"
    r"knock(out|-out)\s+mice|wild[-\s]type\s+mice|rat\s+model|mouse\s+model|"
    r"mtor\s+signaling|molecular\s+mechanism)\b",
    re.IGNORECASE,
)
_ANIMAL_RE = re.compile(
    r"\b(mice|mouse|rats?|murine|canine|porcine|bovine|zebrafish|drosophila|"
    r"c\.\s*elegans)\b",
    re.IGNORECASE,
)
_CELL_RE = re.compile(
    r"\b(in[-\s]vitro|cell\s+(line|culture)|primary\s+cells|ex\s+vivo)\b",
    re.IGNORECASE,
)
_PEDIATRIC_RE = re.compile(
    r"\b(pediatric|paediatric|children|adolescen[ct]|infants?|neonatal)\b",
    re.IGNORECASE,
)

# High-confidence human-only signals — when present, override an
# _ANIMAL_RE / _CELL_RE match in the same abstract. 'we treated' /
# 'we administered' deliberately excluded because labs say those of mice
# too. Only research-jargon for human trials and explicit population
# descriptors are listed.
_HUMAN_TRIAL_SIGNAL_RE = re.compile(
    r"\b(?:"
    r"we\s+(?:randomi[sz]ed|enrolled|recruited|randomly\s+assigned)"
    r"|(?:older|elderly|adult|aged)\s+(?:adults|men|women|patients|participants|subjects)"
    r"|patients\s+(?:were\s+)?(?:randomi[sz]ed|enrolled|recruited)"
    r"|participants\s*\(\s*n\s*=\s*\d{2,}"
    r"|men\s+and\s+women|male\s+and\s+female\s+(?:patients|participants)"
    r"|n\s*=\s*\d{2,}\s+(?:patients|participants|subjects|adults|older)"
    r"|in\s+(?:patients|participants|subjects|adults|older\s+adults)\s+with"
    r"|in\s+a\s+(?:randomi[sz]ed|placebo[-\s]controlled|double[-\s]blind)\s+trial\s+(?:of|in)\s+(?:patients|adults|participants)"
    r")\b",
    re.IGNORECASE,
)

# Trial-design markers — even without a numeric outcome, these phrases plus
# any qualitative effect verb (improved/reduced/decreased/increased) flag a
# real human trial paper. Examples this catches: 'first clinical trial of',
# 'open-label phase I pilot', 'we administered ... 100 mg'. Used in
# _classify_role as a fast path so qualitative-outcome trials don't fall
# through to the mechanistic default.
_TRIAL_DESIGN_RE = re.compile(
    r"(?:first|pivotal|seminal)\s+clinical\s+trial"
    r"|phase\s+(?:i{1,3}|1|2|3|iv|4)\b"
    r"|open[-\s]label\s+(?:trial|study|phase|pilot)"
    r"|(?:double|single)[-\s]blind\s+(?:randomi[sz]ed|trial|placebo)"
    r"|placebo[-\s]controlled\s+(?:trial|study|pilot|phase)"
    r"|we\s+(?:randomi[sz]ed|administered|treated|assigned)\s+\w+"
    r"|in\s+this\s+(?:open[-\s]label|double[-\s]blind|randomi[sz]ed|placebo[-\s]controlled|pilot)\s+",
    re.IGNORECASE,
)

# Qualitative outcome verbs — paired with trial-design markers, signal a
# results paper even without numeric effect markers in _REPORTED_OUTCOME_RE.
_QUALITATIVE_OUTCOME_RE = re.compile(
    r"\b(?:improved|reduced|decreased|increased|enhanced|attenuated|"
    r"reversed|lowered|raised|cleared|eliminated|prolonged)\s+\w+",
    re.IGNORECASE,
)
# High-impact venues for tier A1 promotion. Conservative seed list; expand
# only when a fixture proves the omission is hurting tier accuracy.
_HIGH_IMPACT_VENUES = (
    "new england journal of medicine",
    "lancet",
    "jama",
    "bmj",
    "nature medicine",
    "cell",
    "nature",
    "science",
    "annals of internal medicine",
)

_HUMAN_DOMAIN_MARKERS = (
    "human",
    "longevity",
    "aging",
    "ageing",
    "older adult",
    "adult",
    "patient",
    "clinical",
)
_ADULT_DOMAIN_MARKERS = ("adult", "older", "elderly", "geriatric")

# Topic stopwords stripped before extracting topic anchors. These words appear
# in queries as filters or population descriptors but don't anchor the subject
# matter. Anchors are how we tell rapamycin papers from RTB101 papers.
_TOPIC_STOPWORDS = frozenset({
    "older", "adults", "adult", "elderly", "human", "humans",
    "aging", "ageing", "longevity", "old", "young",
    "healthy", "patient", "patients", "subjects",
    "supplementation", "treatment", "therapy",
    "mortality", "loss", "weight", "and", "or", "of", "in", "the",
    "for", "with", "on", "by", "to",
})
# Allow single-character tokens (the 'd' in 'vitamin d') so the bigram
# preserves the compound entity. Single-char tokens that aren't stopwords
# survive into _topic_anchors only when paired with another content token.
_TOPIC_TOKEN_RE = re.compile(r"\b[a-z][a-z0-9-]*\b")

# Writer-budget defaults — prevents the LLM from drowning in 30+ item
# bundles where mechanistic/old context dilutes the strongest evidence.
DEFAULT_WRITER_BUDGET = 16

_ROLE_WRITER_PRIORITY = {
    "published_results": 0,
    "review": 1,
    "registered_pending": 2,
    "published_protocol": 3,
    "mechanistic": 4,
    "off_domain": 5,
}
_TIER_WRITER_PRIORITY = {"A1": 0, "A2": 1, "B": 2, "C": 3}


# --- Public entry point ----------------------------------------------------


def bundle(
    sources: list[Source],
    abstracts: Mapping[int, str],
    *,
    topic: str = "",
    domain: str = "",
    criteria_min_year: int | None = None,
    raw_signals: Mapping[int, Mapping[str, object]] | None = None,
) -> list[EvidenceItem]:
    """Map (Source, abstract) -> EvidenceItem with role/tier/design/direct/strict.

    `topic`   anchors topic-relevance — items whose title+abstract contains no
              topic anchor are marked direct=False (and therefore strict=False).
              Empty topic disables the gate.
    `domain`  anchors population/setting fit (human, adult, etc.).
    `raw_signals` is the per-ref `RawHit.raw` dict from the adapter (e.g.
              clinicaltrials passes `has_results`).

    Pure function; deterministic.
    """
    items: list[EvidenceItem] = []
    domain_lower = (domain or "").lower()
    topic_anchors = _topic_anchors(topic)
    signals = raw_signals or {}
    for src in sources:
        abstract = abstracts.get(src.ref, "")
        sig = signals.get(src.ref, {}) or {}
        role = _classify_role(src, abstract, sig)
        design = _classify_design(role, abstract)
        tier = _classify_tier(role, design, src.venue)
        direct = _is_direct(src.title, abstract, domain_lower, topic_anchors)
        strict = _is_strict(direct, src.year, criteria_min_year)
        items.append(
            EvidenceItem(
                source=src,
                abstract=abstract,
                design=design,
                role=role,
                tier=tier,
                direct=direct,
                strict=strict,
            )
        )
    return items


def rank_for_writer(
    items: list[EvidenceItem], n: int = DEFAULT_WRITER_BUDGET
) -> list[EvidenceItem]:
    """Sort items by writer priority and return the top N.

    Priority key (smaller = higher rank):
      direct=True before direct=False
      tier   A1 < A2 < B < C
      role   published_results < review < registered_pending < protocol < mechanistic
      year   newer first
      ref    ascending (stable tie-break)

    The LLM sees only this top-N slice; the full bundle still flows to render
    so the evidence table and bibliography stay complete.
    """

    def key(it: EvidenceItem) -> tuple:
        return (
            not it.direct,
            _TIER_WRITER_PRIORITY.get(it.tier, 9),
            _ROLE_WRITER_PRIORITY.get(it.role, 9),
            -(it.source.year or 0),
            it.source.ref,
        )

    return sorted(items, key=key)[:n]


def _topic_anchors(topic: str) -> tuple[str, ...]:
    """Extract content-bearing topic phrases for the relevance gate.

    Rules:
      0 content tokens   -> () (gate disabled)
      1 content token    -> single unigram   ("rapamycin",)
      2 content tokens   -> single BIGRAM    ("vitamin d",) — keeps the
                            compound entity intact so "Vitamin K" doesn't
                            falsely match a Vitamin D topic.
      3+ content tokens  -> individual unigrams (>=3 chars)
                            ("senolytics", "dasatinib", "quercetin"). The
                            user is naming alternatives, not a single
                            multi-word entity.

    All matches against title+abstract use \\b word boundaries (in
    _is_direct) so "vitamin" in "multivitamin" does not match.
    """
    if not topic:
        return ()
    tokens = _TOPIC_TOKEN_RE.findall(topic.lower())
    content = [t for t in tokens if t not in _TOPIC_STOPWORDS]
    if not content:
        return ()
    if len(content) == 2:
        return (f"{content[0]} {content[1]}",)
    return tuple(t for t in content[:3] if len(t) >= 3)


# --- Step 1: role ----------------------------------------------------------


def _classify_role(src: Source, abstract: str, sig: Mapping[str, object]) -> Role:
    haystack = f"{src.title} {abstract}".lower()
    if src.source == "clinicaltrials":
        return "published_results" if sig.get("has_results") else "registered_pending"
    if any(token in haystack for token in _REVIEW):
        return "review"
    has_protocol = any(token in haystack for token in _PROTOCOL)
    has_outcome = bool(_REPORTED_OUTCOME_RE.search(abstract))
    # Protocol markers DOMINATE — a paper saying 'this study evaluates' or
    # 'we will assess' is a protocol regardless of trial-design phrasing
    # (protocols always describe their planned design). Only a hard numeric
    # outcome marker overrides this. Without that, protocol -> protocol.
    if has_protocol and not has_outcome:
        return "published_protocol"
    if has_outcome:
        return "published_results"
    # Trial-design fast path: a paper with explicit trial-design markers
    # (Phase I/II/III, open-label, randomized double-blind, placebo-controlled,
    # 'we randomized/administered') plus a qualitative outcome verb is a
    # results paper even when the abstract uses only qualitative effect
    # language. Catches the Hickson IPF senolytics pilot and similar real
    # RCTs whose abstracts don't carry p-values. Runs ONLY when no protocol
    # markers are present (otherwise the protocol branch above already won).
    if _TRIAL_DESIGN_RE.search(abstract) and _QUALITATIVE_OUTCOME_RE.search(abstract):
        return "published_results"
    if _MECHANISTIC_RE.search(haystack):
        return "mechanistic"
    return "mechanistic"


# --- Step 2: design --------------------------------------------------------


def _classify_design(role: Role, abstract: str) -> Design:
    haystack = abstract.lower()
    if role == "published_results":
        return "rct" if _RANDOMIZED_RE.search(haystack) else "observational"
    if role == "review":
        return "meta_analysis" if any(t in haystack for t in _META_ANALYSIS) else "review"
    if role == "published_protocol":
        return "protocol"
    if role == "registered_pending":
        return "registry"
    if role == "mechanistic":
        return "mechanistic"
    return "other"


# --- Step 3: tier ----------------------------------------------------------


def _classify_tier(role: Role, design: Design, venue: str | None) -> Tier:
    is_high_impact = bool(venue) and any(
        marker in venue.lower() for marker in _HIGH_IMPACT_VENUES
    )
    if design in {"rct", "meta_analysis"}:
        return "A1" if is_high_impact else "A2"
    if role == "published_results":
        return "A2"
    if role == "review":
        return "A2"
    if role in {"published_protocol", "registered_pending"}:
        return "B"
    return "C"


# --- Step 4: direct --------------------------------------------------------


def _is_direct(
    title: str,
    abstract: str,
    domain: str,
    topic_anchors: tuple[str, ...],
) -> bool:
    """Direct = on-topic AND on-population. Off either axis -> indirect.

    Topic anchors are matched with word boundaries so 'vitamin' as an anchor
    does not match 'multivitamin', and a 'vitamin d' bigram anchor does not
    match 'Vitamin K' (the K isn't part of the bigram).

    Animal/cell match is OVERRIDDEN when the abstract carries an explicit
    human-trial signal ('we randomized N patients', 'older adults',
    'placebo-controlled', etc.). Real human RCTs routinely cite preclinical
    mouse work in their introduction; the override prevents a real human
    trial from being marked indirect just because its background mentions
    'mice'.
    """
    domain_human = any(marker in domain for marker in _HUMAN_DOMAIN_MARKERS)
    domain_adult = any(marker in domain for marker in _ADULT_DOMAIN_MARKERS)
    has_human_signal = bool(_HUMAN_TRIAL_SIGNAL_RE.search(abstract))
    if domain_human and not has_human_signal and (
        _ANIMAL_RE.search(abstract) or _CELL_RE.search(abstract)
    ):
        return False
    if domain_adult and _PEDIATRIC_RE.search(abstract):
        return False
    if topic_anchors:
        haystack = f"{title} {abstract}".lower()
        anchor_re = re.compile(
            r"\b(?:" + "|".join(re.escape(a) for a in topic_anchors) + r")\b"
        )
        if not anchor_re.search(haystack):
            return False
    return True


# --- Step 5: strict --------------------------------------------------------


def _is_strict(direct: bool, year: int | None, min_year: int | None) -> bool:
    if not direct:
        return False
    if min_year is not None and year is not None and year < min_year:
        return False
    return True
