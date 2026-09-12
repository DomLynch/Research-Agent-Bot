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
import sys
from dataclasses import dataclass
from pathlib import Path

# Phase 7 domain-pack: load vocab from scripts/vocab/<domain>.py.
# `TOPIC_DOMAIN` env var picks the pack; default "metformin" preserves
# backward-compat with all v0.1-v0.6 callers.
# Reviewer-fix MEDIUM 1: import from domain_vocab namespace to avoid
# a top-level `vocab` package collision with any third-party install.
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
from vocab import load_domain  # noqa: E402

_DOMAIN_PACK = load_domain()
ENDPOINT_VOCAB: tuple[tuple[str, str], ...] = _DOMAIN_PACK.ENDPOINT_VOCAB
ENDPOINT_TO_OUTCOME_CLASS: dict[str, str] = (
    _DOMAIN_PACK.ENDPOINT_TO_OUTCOME_CLASS
)
ENDPOINT_POLARITY: dict[str, int] = _DOMAIN_PACK.ENDPOINT_POLARITY
# ARM_VOCAB also from the domain pack (Reviewer-fix MEDIUM 2):
# rapamycin pack overrides the "metformin" bare-keyword fallbacks
# with "rapamycin"/"sirolimus".
ARM_VOCAB: tuple[tuple[str, str], ...] = _DOMAIN_PACK.ARM_VOCAB


__all__ = [
    "EndpointBinding",
    "ENDPOINT_VOCAB",
    "ENDPOINT_TO_OUTCOME_CLASS",
    "ENDPOINT_POLARITY",
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
# Phase 7 refactor: ENDPOINT_VOCAB / ENDPOINT_TO_OUTCOME_CLASS /
# ENDPOINT_POLARITY now live in scripts/vocab/<domain>.py and are
# imported at module load via load_domain() at the top of this file.
# ARM_VOCAB and DIRECTION_VOCAB stay here (domain-agnostic).


# ARM_VOCAB now lives in scripts/vocab/<domain>.py (Phase 7 + reviewer
# fix MEDIUM 2). Loaded via `_DOMAIN_PACK.ARM_VOCAB` at module import.

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
    ("no_change", r"\bno\s+(?:significant\s+|statistically\s+significant\s+)?(?:changes?|differences?|effects?|improvements?)\b"
                  r"|did\s+not\s+(?:significantly\s+)?(?:change|differ|improve|increase|decrease|gain|reduce)"
                  r"|was\s+not\s+(?:significantly\s+)?(?:different|changed|improved|increased|decreased)"
                  r"|\bsimilar\s+(?:between|across|in\s+both)\b"
                  r"|\bnot\s+(?:significantly\s+)?different\b"
                  r"|\bunchanged\b|\bnull\s+(?:result|effect|finding)\b"
                  r"|\bnon-?significant\s+(?:effect|difference|change)\b|\b(?:were|was) not (?:statistically )?significant\b"),
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
                 r"|\bdecreas(?:e[ds]?|ing)\b|\breduc(?:e[ds]?|ing|tions?)\b|\bdiminished?\b|\bblunted?\b"
                 r"|\battenuated?\b|\bsuppressed?\b|\binhibited?\b"
                 r"|\blowered?\b|\bdeclined?\b|\bfell\b|\bdropped?\b"
                 r"|\bslowed?\b|\bworsened?\b|\bantagonized?\b|\bimpaired?\b"
                 r"|\blost?\s+(?:weight|mass|function)"
                 r"|\blower\b|\bsmaller\b"),
    ("increase", r"\bsmaller\s+(?:decrease|decline|loss|reduction)\b|\bincreas(?:e[ds]?|ing)\b|\bgain(?:ed|s)?\b|\bimprov(?:e[ds]?|ing|ements?)\b|\benhanced?\b"
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


def match_endpoint(
    sentence: str, anchor_offset: int | None = None,
) -> str:
    """Return canonical endpoint name; "" if no match.

    P1 #1 audit fix: pre-fix used vocab-order first-match-wins, so on
    Walton's dual-endpoint sentence "lean body mass (p=.003) and
    thigh muscle mass (p<.001)" both p-values bound to the same
    endpoint (whichever vocab entry matched first). Now: if
    `anchor_offset` is given, the endpoint match NEAREST to the
    anchor wins. Vocab order remains the tiebreaker only when two
    matches are equidistant (the more-specific entry wins via
    earlier vocab position — "thigh muscle mass" > "muscle mass" >
    "lean body mass" overlap rules).

    Without an anchor, falls back to first-match-wins on vocab order
    (preserves backward compatibility with callers that don't have
    a per-claim anchor — e.g., the unit tests).
    """
    if not sentence:
        return ""
    if anchor_offset is None:
        for name, pat in _ENDPOINT_COMPILED:
            if pat.search(sentence):
                return name
        return ""
    # Collect all matches with vocab priority for tiebreaking.
    candidates: list[tuple[int, int, str, int, int]] = []
    for prio, (name, pat) in enumerate(_ENDPOINT_COMPILED):
        for m in pat.finditer(sentence):
            if m.start() <= anchor_offset <= m.end():
                distance = 0
            else:
                distance = min(
                    abs(m.start() - anchor_offset),
                    abs(m.end() - anchor_offset),
                )
            candidates.append((distance, prio, name, m.start(), m.end()))
    if not candidates:
        return ""
    open_idx = sentence.rfind("(", 0, anchor_offset + 1)
    close_before = sentence.rfind(")", 0, anchor_offset + 1)
    close_after = sentence.find(")", anchor_offset)
    if open_idx > close_before and close_after != -1:
        prior_groups = list(re.finditer(r"\([^()]*(?<![A-Za-z])\d[^()]*\)", sentence[:open_idx]))
        start = prior_groups[-1].end() if prior_groups else 0
        boundary = max(sentence.rfind(",", 0, open_idx), sentence.rfind(";", 0, open_idx)) + 1
        if not re.fullmatch(r"\s*(?:although|but)\s+(?:this|it)\s+(?:did not reach (?:statistical )?significance|was (?:not )?(?:statistically )?significant)\s*", sentence[boundary:open_idx], re.I):
            start = max(start, boundary)
        candidates = [c for c in candidates if start <= c[3] and c[4] <= open_idx]
    candidates.sort(key=lambda t: (t[0], t[1]))
    return candidates[0][2] if candidates else ""


# P1 #2 audit fix: comparator grammar. Sentences like "Compared to
# placebo, metformin reduced HbA1c" have two arms; the one BEFORE
# the comma is the COMPARATOR (placebo, here), and the one AFTER
# is the SUBJECT (metformin, the arm whose effect is being claimed).
# Plain earliest-mention-wins gives the WRONG answer. We detect
# the comparator marker and exclude its referent from arm selection.
_COMPARATOR_MARKER_RE = re.compile(
    r"\b(?:compared\s+to|in\s+contrast\s+to|relative\s+to|"
    r"versus|vs\.?)\s+",
    re.IGNORECASE,
)


def match_arm(sentence: str) -> str:
    """Return canonical arm name; "" if no match.

    Two-stage rule:
      1. If the sentence contains a comparator marker ("compared to",
         "in contrast to", "vs.", "versus", "relative to"), find the
         arm immediately following the marker (the comparator) and
         EXCLUDE its byte-span from candidate selection. The remaining
         arm match — typically a different one mentioned later — is
         the subject.
      2. Otherwise, earliest-IN-SENTENCE arm wins, with vocab order
         as tiebreaker for same-position overlaps.

    P1 #2 audit fix: pre-fix used earliest-mention-wins universally.
    "Compared to placebo, metformin reduced HbA1c" wrongly bound to
    arm=placebo (the comparator). Now we detect the comparator
    marker and exclude its arm from selection.
    """
    if not sentence:
        return ""
    # Stage 1: find comparator-marker arms to exclude.
    # The arm referent must appear IMMEDIATELY after the marker — we
    # only treat the next-word slot as the comparator. Reviewer-flagged
    # MEDIUM bug fix: pre-fix accepted any arm match within 40 chars,
    # so "Compared to historical levels, metformin treatment..."
    # wrongly excluded metformin (the actual subject) because it
    # appeared past intervening "historical levels". The
    # _COMPARATOR_TIGHT_WINDOW limit confines exclusion to the
    # next-word slot only.
    _COMPARATOR_TIGHT_WINDOW = 8  # characters
    excluded_spans: list[tuple[int, int]] = []
    for marker_match in _COMPARATOR_MARKER_RE.finditer(sentence):
        scan_start = marker_match.end()
        scan_end = min(len(sentence), scan_start + 40)
        scan_text = sentence[scan_start:scan_end]
        earliest: re.Match[str] | None = None
        for _name, pat in _ARM_COMPILED:
            arm_match = pat.search(scan_text)
            if arm_match is not None and (
                earliest is None or arm_match.start() < earliest.start()
            ):
                earliest = arm_match
        # Only exclude if the earliest arm sits in the tight next-word
        # window (handles "compared to placebo," but not "compared to
        # historical levels, metformin..."). Beyond _COMPARATOR_TIGHT_WINDOW
        # the arm is just any later mention, not the comparator referent.
        if earliest is not None and earliest.start() <= _COMPARATOR_TIGHT_WINDOW:
            excluded_spans.append((
                scan_start + earliest.start(),
                scan_start + earliest.end(),
            ))
    # Stage 2: collect arm candidates excluding any in comparator spans.
    candidates: list[tuple[int, int, str]] = []  # (position, vocab_priority, name)
    for prio, (name, pat) in enumerate(_ARM_COMPILED):
        for m in pat.finditer(sentence):
            in_excluded = any(
                es <= m.start() < ee for es, ee in excluded_spans
            )
            if in_excluded:
                continue
            candidates.append((m.start(), prio, name))
    if not candidates:
        # Fallback: if every match was excluded as a comparator, the
        # sentence only names the comparator and not the subject.
        # Better to return "" than guess.
        return ""
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
    endpoint: str, arm: str, direction: str, claim_role: str = "",
) -> str:
    """Summary tag based on how many of the 3 fields were bound AND
    whether the claim is effect-shaped.

    P1 #3 audit fix: pre-fix counted 3/3 field coverage as "high"
    regardless of `claim_role`. That meant a dose like "500 mg/day"
    in a sentence mentioning an endpoint and an arm was tagged high
    confidence — even though it's a treatment dose, not an effect
    claim. Audit found 117/194 (60.3%) high-confidence claims were
    actually dose/duration/population/unknown roles. Phase 4 paper
    writer would silently use those as primary evidence.

    Fixed contract:
      "high"    — all 3 fields bound AND claim_role == "effect"
      "partial" — at least 1 field bound, OR all 3 bound but role
                  is non-effect (e.g. dose with full context)
      "none"    — 0 fields bound

    `claim_role` defaults to "" so callers that don't pass it (unit
    tests, pre-Phase-2.1 artifacts) get the strictest interpretation:
    no role → cannot be high.
    """
    bound = sum(1 for f in (endpoint, arm, direction) if f)
    if bound == 3 and claim_role == "effect":
        return "high"
    if bound >= 1:
        return "partial"
    return "none"


def bind_claim(
    sentence: str, source_offset_in_section: int,
    sentence_offset_in_section: int = 0,
    claim_role: str = "",
) -> EndpointBinding:
    """Bind one claim. `source_offset_in_section` is the claim's
    char-offset within its section (already what QuantClaim stores).
    `sentence_offset_in_section` is where the sentence STARTS within
    the section, so the per-sentence anchor is the difference.

    `claim_role` is passed through to `binding_confidence_for` so
    "high" is reserved for effect-shaped claims (P1 #3 fix).
    """
    anchor: int | None = source_offset_in_section - sentence_offset_in_section
    if anchor is not None and (anchor < 0 or anchor > len(sentence)):
        # Defensive: caller passed inconsistent offsets. Fall back to
        # vocab-order endpoint and first-match-wins direction.
        anchor = None
    endpoint = match_endpoint(sentence, anchor_offset=anchor)
    arm = match_arm(sentence)
    direction = match_direction(sentence, anchor_offset=anchor)
    return EndpointBinding(
        endpoint=endpoint,
        arm=arm,
        direction=direction,
        binding_confidence=binding_confidence_for(
            endpoint, arm, direction, claim_role=claim_role,
        ),
    )
