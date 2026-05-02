"""Day 10.17 Path B-prime Phase 2.2 — endpoint + arm + direction binding.

Each QuantClaim carries a numeric value; Phase 2.2 enriches it with the
SEMANTIC context the paper writer needs:
  - endpoint: WHAT was measured (lean body mass, VO2max, walk speed, ...)
  - arm:      WHICH group (metformin, placebo, control, ...)
  - direction: increase | decrease | no_change | mixed

Vocab is curated for the metformin/aging corpus — extending to a new
domain (e.g., rapamycin) means swapping `_ENDPOINT_VOCAB` only. Matchers
are deterministic regex (per AGENTS.md "code disposes" — no LLM).

Binding heuristic per claim:
  1. Scan the claim's `sentence` for endpoint vocab; first match wins.
  2. Scan for arm vocab; first match wins.
  3. For direction, find the keyword CLOSEST to the claim's
     source_offset (NOT first-match-wins). Metformin papers commonly
     write "X increased but Y decreased" — proximity disambiguates.
  4. binding_confidence: high (3/3 fields bound) | partial (1-2/3) |
     none (0/3).

Lives in scripts/ (offline benchmark tool). Pure stdlib + re. No httpx
dependency added; no agent/ runtime touched.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = [
    "EndpointBinding",
    "ENDPOINT_VOCAB",
    "ARM_VOCAB",
    "DIRECTION_VOCAB",
    "match_endpoint",
    "match_arm",
    "match_direction",
    "bind_claim",
    "binding_confidence_for",
]


@dataclass(frozen=True, slots=True)
class EndpointBinding:
    """Result of binding one claim to its semantic context.

    Empty strings mean "unbound" — Phase 4 can choose to drop or
    surface as candidates. binding_confidence summarizes the 3-field
    coverage so downstream filters don't have to recompute.
    """
    endpoint: str
    arm: str
    direction: str
    binding_confidence: str  # "high" | "partial" | "none"


# --- Vocab tables ---------------------------------------------------------


# Endpoint vocabulary — curated for the metformin/aging benchmark
# corpus. Each entry: (canonical_display_name, regex_pattern). Pattern
# matches common spelling variants + acronyms case-insensitively.
# Order matters — more-specific patterns FIRST so "thigh muscle mass"
# wins over the broader "muscle mass". Verified against the 7 reference
# papers' results sections; gaps tracked as Phase 2.3 work.
ENDPOINT_VOCAB: tuple[tuple[str, str], ...] = (
    # Cardio / aerobic
    ("VO2max", r"\bVO\s*2\s*max\b|\bVO₂\s*max\b|peak\s+oxygen\s+(?:consumption|uptake)|aerobic\s+capacity"),
    ("walk speed", r"\b(?:4-?\s*m|six-?minute)\s+walk(?:\s+(?:speed|distance|test))?\b|gait\s+speed\b"),
    # Body composition
    ("thigh muscle mass", r"\bthigh\s+muscle\s+(?:mass|size|area|volume|cross-?sectional\s+area)|thigh\s+CSA"),
    ("lean body mass", r"\blean\s+(?:body\s+)?mass\b|fat-?free\s+mass\b|\bFFM\b"),
    ("muscle hypertrophy", r"\bhypertroph(?:y|ic\s+response)|muscle\s+gain"),
    ("muscle strength", r"\b(?:muscle\s+|grip\s+|leg\s+|knee\s+|handgrip\s+)?strength\b|\b1\s*RM\b|one[\s-]?rep\s*max"),
    ("body weight", r"\bbody\s+weight\b|\bweight\s+(?:loss|gain|change)\b"),
    ("body mass index", r"\bbody\s+mass\s+index\b|\bBMI\b"),
    # Glucose / insulin
    ("HbA1c", r"\bHbA1c\b|glycated\s+h(?:a|ae)moglobin|hemoglobin\s+A1c|\bA1c\b"),
    ("insulin sensitivity", r"\binsulin\s+sensitivit(?:y|ies)\b|\bHOMA-?IR\b|insulin\s+action|insulin\s+resistance"),
    ("fasting glucose", r"\bfasting\s+(?:plasma\s+)?glucose\b|FPG\b"),
    ("blood glucose", r"\bblood\s+glucose\b|plasma\s+glucose\b|24-?h(?:r|our)?\s+glucose"),
    # Mitochondrial / cellular
    ("mitochondrial respiration", r"mitochondrial\s+respiration|mitochondrial\s+function|oxygen\s+consumption\s+rate|\bOCR\b"),
    ("AMPK signaling", r"\bAMPK\b|AMP-?activated\s+protein\s+kinase"),
    ("mTOR signaling", r"\bmTORC?[12]?\b|mammalian\s+target\s+of\s+rapamycin|S6K1\b|p70S6K"),
    ("protein synthesis", r"\bprotein\s+synthesis\b|fractional\s+synthesis\s+rate"),
    # Aging-specific
    ("frailty", r"\bfrailt(?:y|ies)\b|frail\s+(?:index|status)|frailty\s+phenotype"),
    ("sarcopenia", r"\bsarcopeni(?:a|c)\b|muscle\s+wasting"),
    ("lifespan", r"\blifespan\b|life\s+span|all-?cause\s+mortality"),
    ("healthspan", r"\bhealthspan\b|health\s+span|disease-?free\s+years"),
    # Inflammation / biomarkers
    ("inflammation", r"\binflammat(?:ion|ory)\b|\bIL-?6\b|\bTNF-?[αα]?\b|\bCRP\b|\bhsCRP\b"),
    ("oxidative stress", r"\boxidative\s+stress\b|reactive\s+oxygen\s+species|\bROS\b"),
    # Common clinical
    ("blood pressure", r"\bblood\s+pressure\b|systolic\s+BP|diastolic\s+BP|\bSBP\b|\bDBP\b"),
    ("cardiorespiratory fitness", r"cardiorespiratory\s+fitness|\bCRF\b"),
)

# Arm vocabulary — which group is the value attributed to.
# "metformin" and "treatment" treated as synonyms for the active arm
# in metformin-vs-placebo trials. Order: most-specific first.
ARM_VOCAB: tuple[tuple[str, str], ...] = (
    ("metformin", r"\bmetformin\s+(?:group|arm|treatment|cohort)|\bmetformin-?treated"),
    ("placebo", r"\bplacebo\s+(?:group|arm|cohort|control)|\bplacebo-?treated"),
    ("control", r"\bcontrol\s+(?:group|arm|cohort|subjects?)\b"),
    ("treatment", r"\btreatment\s+(?:group|arm|cohort)\b|\bactive\s+treatment\b"),
    ("pooled", r"\bpooled\b|combined\s+groups?|both\s+(?:groups|arms)|across\s+groups"),
    # Bare keyword fallbacks (looser, lower confidence) - kept LAST
    # so the modified-noun forms above win when both present.
    ("metformin", r"\bmetformin\b"),
    ("placebo", r"\bplacebo\b"),
)

# Direction vocabulary — which way the value moved. Each entry is a
# regex; first whole-token match in proximity wins (proximity check
# happens in match_direction). Kept tight to verb forms + comparative
# adjectives that unambiguously signal direction in clinical prose.
DIRECTION_VOCAB: tuple[tuple[str, str], ...] = (
    # NO-CHANGE compounds — explicit negations of any direction. The
    # span-containment filter in match_direction lets these subsume
    # bare "improve" / "increase" / "decrease" matches inside them
    # (Witham "did not improve walk speed" pre-fix bound to increase
    # because of bare "improve").
    ("no_change", r"\bno\s+(?:significant\s+|statistically\s+significant\s+)?(?:change|difference|effect|improvement)\b"
                  r"|did\s+not\s+(?:significantly\s+)?(?:change|differ|improve|increase|decrease|gain|reduce)"
                  r"|was\s+not\s+(?:significantly\s+)?(?:different|changed|improved)"
                  r"|\bsimilar\s+(?:between|across|in\s+both)\b"
                  r"|\bnot\s+(?:significantly\s+)?different\b"
                  r"|\bunchanged\b|\bnull\s+(?:result|effect|finding)\b"
                  r"|\bnon-?significant\s+(?:effect|difference|change)\b"),
    ("mixed", r"\bmixed\s+(?:response|result|finding|effect)\b"
              r"|\bvariable\s+(?:response|effect)\b"
              r"|\bdichotomous\b"
              r"|\b(?:positive\s+and\s+negative|opposite|divergent)\s+respon"),
    # DECREASE compounds first — phrases like "attenuated the increase"
    # are decrease semantics that contain a bare "increase" word.
    # Pre-fix Konopka "attenuated the increase in VO2max" wrongly
    # bound to increase by proximity. Span-containment now drops
    # the inner "increase" when these compound forms match.
    ("decrease", r"\battenuated?\s+the\s+(?:increase|gain|improvement|rise|growth|response)"
                 r"|\bblunted?\s+the\s+(?:increase|gain|improvement|rise|growth|response)"
                 r"|\bsuppressed?\s+the\s+(?:increase|gain|improvement|rise|growth|response)"
                 r"|\binhibited?\s+the\s+(?:increase|gain|improvement|rise|growth|response)"
                 r"|\bantagonized?\s+the\s+(?:increase|gain|improvement|rise|growth|response)"
                 r"|\bsmaller\s+(?:gain|increase|improvement|response)"
                 # Bare decrease verbs/adjectives.
                 r"|\bdecreased?\b|\breduced?\b|\bdiminished?\b|\bblunted?\b"
                 r"|\battenuated?\b|\bsuppressed?\b|\binhibited?\b"
                 r"|\blowered?\b|\bdeclined?\b|\bfell\b|\bdropped?\b"
                 r"|\bslowed?\b|\bworsened?\b|\bantagonized?\b|\bimpaired?\b"
                 r"|\blost?\s+(?:weight|mass|function)"
                 r"|\blower\b|\bsmaller\b"),
    ("increase", r"\bincreased?\b|\bgained?\b|\bimproved?\b|\benhanced?\b"
                 r"|\brose\b|\brisen\b|\bgrew\b|\bgrowth\s+of\b|\belevated?\b"
                 r"|\bgreater\b|\bhigher\b|\blarger\b|\bmore\b|\bgained?\s+more\b"
                 r"|\bextended?\b|\bprolonged?\b"),
)


# --- Matchers -------------------------------------------------------------


def _compile_vocab(
    vocab: tuple[tuple[str, str], ...],
) -> tuple[tuple[str, re.Pattern[str]], ...]:
    """Pre-compile vocab regexes once at import. Pattern flags:
    IGNORECASE for case-insensitivity, MULTILINE not needed (we
    work on single-sentence inputs)."""
    return tuple(
        (name, re.compile(pat, re.IGNORECASE)) for name, pat in vocab
    )


_ENDPOINT_COMPILED = _compile_vocab(ENDPOINT_VOCAB)
_ARM_COMPILED = _compile_vocab(ARM_VOCAB)
_DIRECTION_COMPILED = _compile_vocab(DIRECTION_VOCAB)


def match_endpoint(sentence: str) -> str:
    """Return canonical endpoint name; "" if no match. First-match-wins
    on the vocab order (ENDPOINT_VOCAB is curated longest/most-specific
    first — "thigh muscle mass" before "muscle mass")."""
    if not sentence:
        return ""
    for name, pat in _ENDPOINT_COMPILED:
        if pat.search(sentence):
            return name
    return ""


def match_arm(sentence: str) -> str:
    """Return canonical arm name; "" if no match.

    Reviewer-flagged HIGH bug fix: pre-fix iterated ARM_VOCAB in vocab
    order and returned the first matching entry. For sentences with
    BOTH bare "metformin" and "placebo" (e.g. "Placebo gained more
    mass than metformin"), this systematically returned arm=metformin
    because the bare-metformin entry preceded bare-placebo in the
    vocab — independent of which word actually appeared first in
    the sentence. The corpus 509:51 metformin:placebo skew was
    consistent with this bias.

    Fix: collect ALL matches across ALL vocab entries, then pick the
    one whose match position is EARLIEST in the sentence. Vocab
    order remains the tiebreaker (modified-noun forms still win
    when they overlap a bare match at the same position). This
    aligns with clinical prose convention: the FIRST-MENTIONED arm
    is typically the subject of the comparison statement.
    """
    if not sentence:
        return ""
    candidates: list[tuple[int, int, str]] = []  # (position, vocab_priority, name)
    for prio, (name, pat) in enumerate(_ARM_COMPILED):
        for m in pat.finditer(sentence):
            candidates.append((m.start(), prio, name))
    if not candidates:
        return ""
    # Earliest sentence position wins; vocab priority tiebreaks ties
    # (which only happen when two vocab entries match at the same
    # offset — e.g., "metformin group" matches both modified-noun
    # form AND bare "metformin"; we want the modified-noun, which
    # comes first in vocab).
    candidates.sort(key=lambda t: (t[0], t[1]))
    return candidates[0][2]


def match_direction(
    sentence: str, anchor_offset: int | None = None,
) -> str:
    """Return one of: increase | decrease | no_change | mixed | "".

    `anchor_offset` is the position of the numeric token within the
    sentence. Disambiguation rules (in order):

      1. Span-containment filter: if a "compound" direction phrase
         like "did not improve" or "attenuated the increase" matches,
         drop any single-word match (improve / increase) that sits
         INSIDE its span. The outer phrase is more specific and would
         be lost to the proximity tiebreaker otherwise. This is the
         load-bearing fix — Konopka's "attenuated the increase in
         VO2max" pre-fix bound to increase (the closer word) instead
         of decrease (the semantically correct phrase).

      2. Proximity to anchor: among the surviving candidates, the
         closest match to `anchor_offset` wins (handles "metformin
         increased X but decreased Y" — the closer word to the
         numeric anchor wins).

      3. Vocab-order tiebreaker: when matches are equidistant, the
         entry listed earlier in DIRECTION_VOCAB wins (no_change >
         mixed > decrease > increase) — biases toward the more-
         conservative reading.
    """
    if not sentence:
        return ""
    direction_priority = {
        n: i for i, (n, _) in enumerate(DIRECTION_VOCAB)
    }
    # Collect all matches: (start, end, name, vocab_priority)
    all_matches: list[tuple[int, int, str, int]] = []
    for name, pat in _DIRECTION_COMPILED:
        for m in pat.finditer(sentence):
            all_matches.append(
                (m.start(), m.end(), name, direction_priority[name]),
            )
    if not all_matches:
        return ""

    # Filter 1: drop any match strictly contained within another,
    # longer match (compound phrase wins over its inner words).
    def _is_strictly_inside(
        candidate: tuple[int, int, str, int],
        others: list[tuple[int, int, str, int]],
    ) -> bool:
        cs, ce, _, _ = candidate
        c_len = ce - cs
        for other in others:
            os_, oe, _, _ = other
            if (os_, oe) == (cs, ce):
                continue
            if os_ <= cs and ce <= oe and (oe - os_) > c_len:
                return True
        return False

    filtered = [
        m for m in all_matches if not _is_strictly_inside(m, all_matches)
    ]

    # Filter 2 + 3: pick by anchor proximity, then vocab priority.
    if anchor_offset is None:
        filtered.sort(key=lambda m: (m[0], m[3]))
        return filtered[0][2]

    def _distance(m: tuple[int, int, str, int]) -> int:
        start, end, _, _ = m
        if start <= anchor_offset <= end:
            return 0
        return min(abs(start - anchor_offset), abs(end - anchor_offset))

    filtered.sort(key=lambda m: (_distance(m), m[3]))
    return filtered[0][2]


def binding_confidence_for(
    endpoint: str, arm: str, direction: str,
) -> str:
    """Summary tag based on how many of the 3 fields were bound.
    Phase 4 uses this as a quick filter ("show only high-confidence
    claims for the abstract") without re-checking each field."""
    bound = sum(1 for f in (endpoint, arm, direction) if f)
    if bound == 3:
        return "high"
    if bound >= 1:
        return "partial"
    return "none"


def bind_claim(
    sentence: str, source_offset_in_section: int,
    sentence_offset_in_section: int = 0,
) -> EndpointBinding:
    """Bind one claim. `source_offset_in_section` is the claim's
    char-offset within its section (already what QuantClaim stores).
    `sentence_offset_in_section` is where the sentence STARTS within
    the section, so the per-sentence anchor is the difference.
    """
    anchor = source_offset_in_section - sentence_offset_in_section
    if anchor < 0 or anchor > len(sentence):
        # Defensive: caller passed inconsistent offsets. Fall back to
        # first-match-wins direction.
        anchor = None
    endpoint = match_endpoint(sentence)
    arm = match_arm(sentence)
    direction = match_direction(sentence, anchor_offset=anchor)
    return EndpointBinding(
        endpoint=endpoint,
        arm=arm,
        direction=direction,
        binding_confidence=binding_confidence_for(endpoint, arm, direction),
    )
