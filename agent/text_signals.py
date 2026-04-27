"""Marker dictionaries and compiled regex patterns for the deterministic
classifier. Pure data, no logic.

Extracted from agent/bundle.py during the Day 2 4-file split (v4 Rule 54;
DESIGN-001 §16). The classifier in role_classifier.py and the high-level
builder in evidence_cards.py both consume these signals; centralizing them
here keeps the truth-table contract from drifting across modules.

Naming convention: all module-level constants are public (no leading
underscore). The previous private-prefix style (`_REVIEW`, `_PROTOCOL`)
was a single-file convention; once the constants are imported across
modules, the prefix is misleading.
"""
from __future__ import annotations

import re

__all__ = [
    "REVIEW_MARKERS",
    "META_ANALYSIS_MARKERS",
    "PROTOCOL_MARKERS",
    "RANDOMIZED_RE",
    "REPORTED_OUTCOME_RE",
    "MECHANISTIC_RE",
    "ANIMAL_RE",
    "CELL_RE",
    "PEDIATRIC_RE",
    "HUMAN_TRIAL_SIGNAL_RE",
    "TRIAL_DESIGN_RE",
    "QUALITATIVE_OUTCOME_RE",
    "HIGH_IMPACT_VENUES",
    "HUMAN_DOMAIN_MARKERS",
    "ADULT_DOMAIN_MARKERS",
    "AGING_DOMAIN_MARKERS",
    "AGING_RELEVANCE_RE",
    "TOPIC_STOPWORDS",
    "TOPIC_TOKEN_RE",
    "DEFAULT_WRITER_BUDGET",
    "ROLE_WRITER_PRIORITY",
    "TIER_WRITER_PRIORITY",
]

# --- Role-detection markers ------------------------------------------------

REVIEW_MARKERS = (
    "systematic review",
    "meta-analysis",
    "meta analysis",
    "umbrella review",
    "narrative review",
    "scoping review",
    "literature review",
)
META_ANALYSIS_MARKERS = ("meta-analysis", "meta analysis")
PROTOCOL_MARKERS = (
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
RANDOMIZED_RE = re.compile(
    r"\b(randomi[sz]ed|rct|double[-\s]blind|placebo[-\s]controlled)\b",
    re.IGNORECASE,
)

# Numeric outcome regex: must signal a *reported result*, not an enrollment
# count or a population descriptor. Markers retained from V1.1 day 2:
#   - p-values (p = 0.03, p<0.05)
#   - confidence intervals
#   - effect-size verbs paired with a number ("reduced by 22%", "increased 3x")
#   - hazard / odds / risk ratios
#   - explicit "mean difference" / "mean change" pairs
# Markers REMOVED in V1.1 day 2 audit:
#   - bare \d+\s*% (matched "60% female" in protocol abstracts)
#   - bare n=\d{2,} (matched "n=24 mice" in mechanistic abstracts)
# The bare patterns are now gated behind effect-verb proximity.
REPORTED_OUTCOME_RE = re.compile(
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
MECHANISTIC_RE = re.compile(
    r"\b(in[-\s]vitro|ex\s+vivo|cell\s+(line|culture)|transgenic\s+mice|"
    r"knock(out|-out)\s+mice|wild[-\s]type\s+mice|rat\s+model|mouse\s+model|"
    r"mtor\s+signaling|molecular\s+mechanism)\b",
    re.IGNORECASE,
)
ANIMAL_RE = re.compile(
    r"\b(mice|mouse|rats?|murine|canine|porcine|bovine|zebrafish|drosophila|"
    r"c\.\s*elegans|monkeys?|primates?|cynomolgus|macaque|baboon|marmoset|"
    r"non[-\s]human\s+primate)\b",
    re.IGNORECASE,
)
CELL_RE = re.compile(
    r"\b(in[-\s]vitro|cell\s+(line|culture)|primary\s+cells|ex\s+vivo)\b",
    re.IGNORECASE,
)
PEDIATRIC_RE = re.compile(
    r"\b(pediatric|paediatric|children|adolescen[ct]|infants?|neonatal)\b",
    re.IGNORECASE,
)

# High-confidence human-only signals — when present, override an
# ANIMAL_RE / CELL_RE match in the same abstract. 'we treated' /
# 'we administered' deliberately excluded because labs say those of mice
# too. Only research-jargon for human trials and explicit population
# descriptors are listed.
HUMAN_TRIAL_SIGNAL_RE = re.compile(
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
# 'open-label phase I pilot', 'we administered ... 100 mg'. Used as a fast
# path so qualitative-outcome trials don't fall through to the mechanistic
# default.
TRIAL_DESIGN_RE = re.compile(
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
# results paper even without numeric effect markers in REPORTED_OUTCOME_RE.
QUALITATIVE_OUTCOME_RE = re.compile(
    r"\b(?:improved|reduced|decreased|increased|enhanced|attenuated|"
    r"reversed|lowered|raised|cleared|eliminated|prolonged)\s+\w+",
    re.IGNORECASE,
)

# --- Tier / venue ---------------------------------------------------------

# High-impact venues for tier A1 promotion. Conservative seed list; expand
# only when a fixture proves the omission is hurting tier accuracy.
HIGH_IMPACT_VENUES = (
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

# --- Domain markers --------------------------------------------------------

HUMAN_DOMAIN_MARKERS = (
    "human",
    "longevity",
    "aging",
    "ageing",
    "older adult",
    "adult",
    "patient",
    "clinical",
)
ADULT_DOMAIN_MARKERS = ("adult", "older", "elderly", "geriatric")
AGING_DOMAIN_MARKERS = (
    "aging", "ageing", "longevity", "older", "elderly", "geriatric",
    "healthspan", "lifespan", "geroscience",
)

# Aging-relevance markers in titles/abstracts. When the domain is aging-
# focused, papers about the topic in a DIFFERENT clinical context (PCOS,
# ACS, cancer, pediatric, pure pharmacokinetics) carry the topic anchor
# but no aging signal; they're demoted to indirect so they don't dominate
# the writer's top-N slice. Non-aging domains (obesity, mental health) skip
# this gate.
AGING_RELEVANCE_RE = re.compile(
    r"\b(?:longevity|aging|ageing|older|elderly|geriatric|frailty|sarcopen[a-z]+|"
    r"healthspan|lifespan|epigenetic\s+(?:age|clock)|senescen[a-z]+|geroscience|"
    r"cognitive[-\s](?:decline|aging|impairment)|brain[-\s]aging|mortality|survival|"
    r"biological\s+age|aging[-\s]related|age[-\s]related|"
    r"geroprotective|gerotherapeutic|hallmarks?\s+of\s+aging|"
    r"physical\s+(?:function|performance)|gait\s+speed|walk\s+speed|grip\s+strength|"
    r"(?:adult|men|women|patients|participants)\s+aged|aged\s+\d{2,}|"
    r"in\s+(?:older|elderly)\s+(?:adults|men|women|patients))\b",
    re.IGNORECASE,
)

# --- Topic anchors --------------------------------------------------------

# Topic stopwords stripped before extracting topic anchors. These words appear
# in queries as filters or population descriptors but don't anchor the subject
# matter. Anchors are how we tell rapamycin papers from RTB101 papers.
TOPIC_STOPWORDS = frozenset({
    "older", "adults", "adult", "elderly", "human", "humans",
    "aging", "ageing", "longevity", "old", "young",
    "healthy", "patient", "patients", "subjects",
    "supplementation", "treatment", "therapy",
    "mortality", "loss", "weight", "and", "or", "of", "in", "the",
    "for", "with", "on", "by", "to",
})
# Allow single-character tokens (the 'd' in 'vitamin d') so the bigram
# preserves the compound entity. Single-char tokens that aren't stopwords
# survive into topic_anchors only when paired with another content token.
TOPIC_TOKEN_RE = re.compile(r"\b[a-z][a-z0-9-]*\b")

# --- Writer-budget priorities ---------------------------------------------

# Prevents the LLM from drowning in 30+ item bundles where mechanistic/old
# context dilutes the strongest evidence.
DEFAULT_WRITER_BUDGET = 16

ROLE_WRITER_PRIORITY = {
    "published_results": 0,
    "review": 1,
    "registered_pending": 2,
    "published_protocol": 3,
    "mechanistic": 4,
    "off_domain": 5,
}
TIER_WRITER_PRIORITY = {"A1": 0, "A2": 1, "B": 2, "C": 3}
