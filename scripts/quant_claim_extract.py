"""Day 10.17 Path B-prime Phase 2 — quantitative claim extraction.

Reads `paper_sections.json` artifacts produced by Phase 1/1.5
`pdf_ingest.py` and emits structured `QuantClaim` records as
gold-benchmark data for Phase 4+ (gold-vs-bot comparison).

Lives under `scripts/` (not `agent/`) to preserve AGENTS.md
"Runtime dep: httpx only" — this module uses only stdlib `re` +
`json` + the local `pdf_ingest` schema for type compatibility.

Hard rule (from AGENTS.md): LLM proposes, code disposes. Phase 2
is the gold-benchmark side of the system, so it MUST be
deterministic regex + heuristics — no LLM. The runtime
`agent/fact_extractor.py` is a different beast (LLM extracts
candidates from retrieved evidence, validators dispose). Don't
confuse the two.

Patterns extracted (claim_type values, v0.3 set):
  - p_value           : "p = 0.08" / "p < .001" / "P=0.04"
  - confidence_interval: "95% CI -0.06 to 0.06"
  - sample_size       : "n = 27"
  - mean_sd           : "9.7 ± 8.5"
  - percentage        : "58%" with surrounding context
  - unit_value        : "0.57 m/s" / "12.3 kg" / "5 kg/day"
  - hazard_ratio      : "HR: 1.25" / "hazard ratio 1.25" (Phase 2.1)
  - odds_ratio        : "OR: 0.75" / "odds ratio 0.75" (Phase 2.1)
  - risk_ratio        : "RR: 1.10" / "relative risk 1.10" (Phase 2.1)
  - correlation       : "Pearson r = 0.45" / "(r = 0.32)" (Phase 2.1)

Each claim also carries a `claim_role` (effect | dose | duration |
population | background | unknown) tagged from sentence keywords +
section context (Phase 2.1).

Sections are processed in isolation; references is skipped (citation
years and page numbers false-fire on percentage/sample_size patterns).

Output shape (one file per paper):
{
  "paper_id": "Walton_2019_MASTERS_...",
  "doi": "10.1111/acel.13039",
  "extracted_at": "2026-05-02T...",
  "extractor_version": "0.1.0",
  "claims_count_by_type": {"p_value": 70, "percentage": 64, ...},
  "claims": [QuantClaim, ...]
}
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from dataclasses import asdict, dataclass, replace
from pathlib import Path

# Phase 2.2 binding: vocab matchers live in a sibling module so the
# vocab can be swapped per corpus (rapamycin will use a different
# endpoint set). Import from the same scripts/ directory.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import quant_endpoints  # noqa: E402

__all__ = [
    "QuantClaim",
    "EXTRACTOR_VERSION",
    "extract_from_text",
    "extract_from_paper_sections",
    "make_artifact",
    "main",
]


EXTRACTOR_VERSION = "0.5.0"
# Day 10.17 Phase 2.2 schema versioning (see Phase 2.1 history below):
#   0.4.0 — endpoint/arm/direction binding via scripts/quant_endpoints.py
#           vocab matchers. Each claim now carries:
#             * endpoint:    canonical name from ENDPOINT_VOCAB
#                            (e.g. "VO2max", "lean body mass")
#             * arm:         "metformin" / "placebo" / "control" / etc.
#             * direction:   increase | decrease | no_change | mixed
#             * binding_confidence: high (3/3) | partial (1-2) | none
#           Span-containment filter handles "attenuated the increase"
#           and "did not improve" subsuming bare "increase"/"improve".
#           Defaults are "" / "none" so v0.3 artifacts upgrade cleanly.
#   0.5.0 — Phase 2.2-fix audit response. Three P1 semantic bugs
#           caught and locked-in via regression tests:
#             * P1 #1: endpoint matcher uses CLAIM-ANCHORED PROXIMITY.
#               Pre-fix Walton dual-endpoint sentence
#               "lean body mass (p=.003) and thigh muscle mass (p<.001)"
#               bound BOTH p-values to the same endpoint by vocab order.
#               Now the nearest endpoint to each claim wins.
#             * P1 #2: arm matcher honors COMPARATOR GRAMMAR.
#               "Compared to placebo, metformin reduced HbA1c" pre-fix
#               bound to arm=placebo (the comparator). Now the marker
#               "compared to|vs.|versus|in contrast to" excludes its
#               referent so the subject (metformin) wins.
#             * P1 #3: binding_confidence requires claim_role=="effect"
#               for "high". Pre-fix audit found 117/194 (60.3%)
#               high-confidence claims were dose/duration/population/
#               unknown roles. Now: 0/92 (0%) non-effect leakage.
#               Locked in by an artifact-level invariant test.
#   0.1.0 — initial extractor (p_value, CI, sample_size, mean_sd,
#           percentage, unit_value)
#   0.2.0 — claim_role field added; HR/OR/RR/correlation patterns
#           introduced; dose units extended (kg/day, mg/kg/day, mg/d).
#           Initial cut had 4 HIGH false-positive bugs.
#   0.3.0 — reviewer-driven hotfix:
#           * OR/HR/RR abbreviations require CAPS + mandatory [:=]
#             (English "or"/"hr" no longer false-positive)
#           * sanity bounds on effect sizes (HR/OR/RR < 100; |r| <= 1)
#           * correlation requires Pearson/Spearman or paren anchor
#           * BACKGROUND wins over EFFECT in claim_role when prevalence/
#             incidence keywords co-occur
#           * results/discussion/conclusion section fallback now
#             "unknown" instead of "effect" when no keywords matched
#             (audit pin: section-only effect tagging was overlabeling
#             interpretive numbers)
#           * sample_size with trailing duration token (n=12 weeks)
#             gets claim_role="duration" so Phase 4 can post-filter
#             without losing the candidate.

# Sections that downstream Phase 4 actually wants quant claims from.
# References is excluded because citation years and page numbers
# false-fire on percentage and sample_size regexes (e.g. "p. 245"
# or "Smith 2019, p. 12").
_INCLUDED_SECTIONS = frozenset(
    {
        "abstract", "introduction", "methods",
        "results", "discussion", "limitations", "conclusion",
    },
)


@dataclass(frozen=True, slots=True)
class QuantClaim:
    """One extracted quantitative claim.

    `numeric_values` is a tuple so a single record can cover scalar
    facts (p=0.08 → (0.08,)), pair facts (95% CI -0.06 to 0.06 →
    (-0.06, 0.06)), and triple+ if needed later. `units` is "" for
    dimensionless values; "%" for percentages; SI symbols otherwise.

    `source_offset` is the CHAR offset within the SECTION body
    (NOT byte offset; NOT within the full paper). Python `str.find`
    and `re.Match.start()` are char-indexed, so Unicode normalization
    that swaps a multi-byte char for a single-byte one (e.g. U+22C5
    `⋅` → `.`) is safe — both the pre- and post-norm strings index
    by char. Phase 4 cross-checks against paper_sections.json with
    the same char-offset coordinate system.

    `sentence` is the full sentence containing the value — Phase 4
    uses it for context-aware comparison ("did the bot say the same
    thing about insulin sensitivity?"). `context_window` is a
    smaller ±60-char view for fast scan.
    """
    claim_id: str
    claim_type: str
    raw_text: str
    numeric_values: tuple[float, ...]
    units: str
    source_section: str
    source_offset: int
    sentence: str
    context_window: str
    # Day 10.17 Phase 2.1 — semantic role of the value within the
    # paper. `claim_type` says WHAT shape the number has (p_value,
    # percentage, etc.). `claim_role` says WHAT IT MEANS in the
    # study's argument: an outcome effect, a treatment dose, a
    # study duration, a population descriptor (e.g. age range), or
    # background context (epidemiology / disease prevalence).
    # Heuristic from sentence keywords + section context — best-effort,
    # not authoritative. Default "" preserves backward compatibility
    # with v0.1 artifacts.
    claim_role: str = ""
    # Day 10.17 Phase 2.2 — endpoint/arm/direction binding from
    # quant_endpoints.py vocab matchers. Each is "" when no vocab
    # match was found in the claim's sentence. binding_confidence
    # rolls up the 3-field coverage:
    #   "high"    — all 3 fields bound
    #   "partial" — 1 or 2 bound
    #   "none"    — 0 bound (sentence had no clinical vocab match)
    # Phase 4 paper writer uses "high"-confidence claims for primary
    # evidence; "partial" go to a secondary pool; "none" are typically
    # background / methodology numbers without endpoint context.
    endpoint: str = ""
    arm: str = ""
    direction: str = ""
    binding_confidence: str = "none"


# --- Text normalization --------------------------------------------------


# PyMuPDF leaks several Unicode whitespace variants inside numeric
# tokens — most painfully U+00A0 (non-breaking space) inside
# "p = 0.05" which makes naive `\s` regexes silently miss matches
# in some Python configurations. We normalize once up front so the
# regexes are simple and the tests are predictable.
_WHITESPACE_NORMALIZATION = {
    " ": " ",  # non-breaking space (Walton MASTERS)
    " ": " ",  # thin space
    " ": " ",  # narrow no-break space
    " ": " ",  # figure space
}
# Minus-sign variants that can show up in CI ranges from typeset PDFs.
# Normalize all to ASCII '-' before running the CI regex.
_MINUS_NORMALIZATION = {
    "−": "-",  # MINUS SIGN
    "–": "-",  # EN DASH
    "—": "-",  # EM DASH (rare in CI but present in some Lancet typesets)
}
# Decimal-point variants. Lancet (Witham MET-PREVENT) typesets
# decimals with U+22C5 DOT OPERATOR ("0⋅96" instead of "0.96"); pre-fix,
# the number regex `\d+\.?\d*` silently missed every Witham p-value,
# CI bound, and m/s unit value because none of them used ASCII period.
# Normalize before regex so the patterns stay simple ASCII.
_DECIMAL_NORMALIZATION = {
    "⋅": ".",   # U+22C5 DOT OPERATOR (Lancet typesetting)
    "·": ".",   # U+00B7 MIDDLE DOT (occasionally used the same way)
    "・": ".",  # U+30FB KATAKANA MIDDLE DOT (rare cross-typeset)
    "‧": ".",   # U+2027 HYPHENATION POINT (some publisher templates)
    "․": ".",   # U+2024 ONE DOT LEADER (some PDF leader-row artifacts)
}


def _normalize(text: str) -> str:
    """Canonicalize whitespace + minus + decimal variants. Preserves
    char count 1-for-1 so source_offset stays meaningful against the
    original section body."""
    out = text
    for src, dst in _WHITESPACE_NORMALIZATION.items():
        out = out.replace(src, dst)
    for src, dst in _MINUS_NORMALIZATION.items():
        out = out.replace(src, dst)
    for src, dst in _DECIMAL_NORMALIZATION.items():
        out = out.replace(src, dst)
    return out


# --- Pattern compilers ---------------------------------------------------


# p-value: "p = 0.08", "P < .001", "p=.04" — comparator + decimal
# (with or without leading zero). `\b[Pp]` anchors on the literal
# 'p' so we don't match middle-of-word 'p's. `[<>=≤≥]` covers the
# four standard comparators (we keep the Unicode ≤≥ even though
# normalization keeps them — they're rare but valid).
_P_VALUE_RE = re.compile(
    r"\b([Pp])\s*([<>=≤≥])\s*(0?\.\d+)\b",
)


# Confidence interval: "95% CI -0.06 to 0.06" / "99% CI [0.05, 0.10]".
# We require an explicit `<level>% CI` anchor; bare two-number ranges
# are too noisy to claim are CIs. Per reviewer fix the level is
# captured (2-3 digits — covers 90/95/99 and rare 99.9); silent drop
# of non-95% CIs would have hurt the gold benchmark on meta-analysis
# papers. Bound minus signs already normalized to ASCII '-' upstream.
_CI_RE = re.compile(
    r"(\d{2,3}(?:\.\d)?)\s*%\s*CI[\s:\[]*"
    r"(-?\d+\.?\d*)"
    r"\s*(?:to|,|-)\s*"
    r"(-?\d+\.?\d*)",
)


# Sample size: "n = 27" / "N=14" / "n=27". Bounded to integer (no
# decimal). The downstream filter (test_sample_size_does_not_match_dose)
# tolerates both "n = 12 weeks" and "n = 12 patients" — Phase 4 can
# filter by trailing token if needed.
_SAMPLE_SIZE_RE = re.compile(r"\b[nN]\s*=\s*(\d+)\b")


# Mean ± SD: "9.7 ± 8.5". The ± character is U+00B1; we don't
# normalize it (it's the canonical typeset symbol). Captures both
# the mean and the SD as numeric_values.
_MEAN_SD_RE = re.compile(r"(\d+\.?\d*)\s*±\s*(\d+\.?\d*)")


# Percentage: "58%" / "12.4 %". The percent SIGN is unambiguous; we
# don't try to parse "twelve percent" written out. Decimal allowed
# but not required.
_PERCENT_RE = re.compile(r"(\d+\.?\d*)\s*%")


# Unit value: numeric immediately followed by a recognized SI/clinical
# unit. The unit list is curated — extensions are easy to add, but we
# DON'T over-include (no general "any unit" match) because that turns
# into noise on author-name superscripts like "Walton1" or "Smith2019".
# Reviewer-fix v0.2: added g/dL, IU/L, μg/L, ng/mL, bpm, mmHg — common
# clinical units that were silently dropped in v0.1. Order matters:
# longer multi-character units FIRST so "kg/m2" wins over "kg".
_UNIT_VALUE_RE = re.compile(
    r"(\d+\.?\d*)\s*"
    # Phase 2.1 reviewer fix: dose units added BEFORE the bare
    # "kg" / "mg" so "5 kg/day" wins over "5 kg" (Mohammed false
    # positive). Order is load-bearing — first match wins.
    r"(mg/kg/day|mg/kg/d|kg/day|mg/day|μg/day|ug/day|μg/d|"
    r"mL/min|kg/m2|mg/dL|mg/d|ng/mL|μg/L|ug/L|IU/L|mmHg|bpm|"
    r"m/s|kg|mg|mmol|μmol|µmol|umol|"
    r"mL|months?|weeks?|days?|years?|cm|mm)"
    r"\b",
)


# Day 10.17 Phase 2.1 — effect-size patterns. These are the shapes
# the v0.1 extractor missed. Each pattern captures the effect
# estimate; CIs that follow are caught by the existing CI regex
# (downstream pairing is Phase 4 territory).
#
# Reviewer-flagged HIGH bugs in v0.2:
#   - "OR" matches the English conjunction "metformin or placebo"
#   - "HR" collides with "heart rate" (clinical papers report HR=72)
#   - bare "r=" matches "for r = 4 patients"
# Fixes applied in v0.3 (Phase 2.1 hotfix):
#   - Drop re.IGNORECASE on the abbreviation forms (OR/HR/RR must
#     be CAPS — English "or"/"hr"/"rr" are lowercase)
#   - Require explicit [:=] (no bare "HR 1.25" — must be "HR: 1.25"
#     or "HR = 1.25" or the spelled-out long form "hazard ratio 1.25")
#   - Sanity bounds enforced in extractor (HR/OR/RR < 100 — clinical
#     ratios are 0.01-50 range; 72 = heart rate, drop)
#   - Long forms (e.g. "hazard ratio") keep IGNORECASE since they're
#     unambiguous English.
_HAZARD_RATIO_LONG_RE = re.compile(
    r"\b(?:hazard\s+ratio|adjusted\s+hazard\s+ratio)\s*"
    r"[:=]?\s*(\d+\.?\d*)",
    re.IGNORECASE,
)
_HAZARD_RATIO_ABBR_RE = re.compile(
    r"\b(?:HR|aHR)\s*[:=]\s*(\d+\.?\d*)",  # CAPS only, [:=] mandatory
)
_ODDS_RATIO_LONG_RE = re.compile(
    r"\b(?:odds\s+ratio|adjusted\s+odds\s+ratio)\s*"
    r"[:=]?\s*(\d+\.?\d*)",
    re.IGNORECASE,
)
_ODDS_RATIO_ABBR_RE = re.compile(
    r"\b(?:OR|aOR)\s*[:=]\s*(\d+\.?\d*)",
)
_RISK_RATIO_LONG_RE = re.compile(
    r"\b(?:risk\s+ratio|relative\s+risk|adjusted\s+relative\s+risk)\s*"
    r"[:=]?\s*(\d+\.?\d*)",
    re.IGNORECASE,
)
_RISK_RATIO_ABBR_RE = re.compile(
    r"\b(?:RR|aRR)\s*[:=]\s*(\d+\.?\d*)",
)
# Correlation: "r = 0.45", "R² = 0.23", "Pearson r = -0.32".
# Reviewer-fix: bare "r=" was matching "for r = 4 patients". The
# fix requires either (a) an explicit Pearson/Spearman keyword
# preceding, OR (b) the value to be in correlation range (-1 to 1).
# Sanity bound enforced in extractor; pattern just captures candidates.
_CORRELATION_RE = re.compile(
    r"\b(?:Pearson|Spearman)\s+[Rr]\s*=\s*(-?\d+\.?\d*)"
    r"|\b(?:R²|r2|R2)\s*=\s*(-?\d+\.?\d*)"
    r"|\(\s*[Rr]\s*=\s*(-?\d+\.?\d*)\s*\)",
)


# Day 10.17 Phase 2.1 — claim_role tagger keywords. Each role's
# keyword set is checked against the sentence (lowercased). First
# match wins; order matters — more-specific roles before less-specific.
_ROLE_KEYWORD_DOSE = (
    "dose", "dosing", "dosage", "administered", "received",
    "treatment with", "treated with", "/day", "per day",
    "/d ", "twice daily", "tablets",
)
_ROLE_KEYWORD_DURATION = (
    "follow-up", "follow up", "duration of", "for a period of",
    "during the", "weeks of", "months of", "years of",
    "treatment period", "trial duration",
)
_ROLE_KEYWORD_POPULATION = (
    "age range", "aged", "older adults", "participants were",
    "subjects were", "median age", "mean age", "enrolled",
    "recruited", "inclusion criteria",
)
_ROLE_KEYWORD_BACKGROUND = (
    "prevalence", "incidence", "worldwide", "globally",
    "general population", "epidemiology", "background",
    "literature reports", "previous studies",
    "estimated to affect", "is associated with the",
)
_ROLE_KEYWORD_EFFECT = (
    # Direction verbs
    "increased", "decreased", "improved", "reduced", "blunted",
    "attenuated", "enhanced", "elevated", "lowered", "diminished",
    "suppressed", "inhibited", "declined", "rose", "rose by",
    # Phase 2.2-fix: P1 #3 / Walton-class regressions. The pre-fix
    # keyword set missed common effect verbs ("gained", "lost") used
    # in body-composition trials, so a sentence like "Placebo gained
    # more lean body mass than metformin (p = .003)" landed as role=
    # unknown (no keyword match) → binding_confidence=partial. Now
    # tagged as effect.
    # Reviewer-fix v0.5.0: bare "more than" / "less than" REMOVED.
    # They false-fire on background prose like "More than 27 trials
    # have been conducted" or "Less than half of subjects met
    # criteria." Kept the arm-anchored variants ("than placebo",
    # "than metformin", "gained more", "lost less") which require
    # a clinical context word.
    "gained", "lost more", "lost less", "gained more", "gained less",
    "than placebo", "than metformin",
    "than control", "than the placebo", "than the metformin",
    # Trial-design markers
    "treatment effect", "primary endpoint", "secondary endpoint",
    "between groups", "between arms", "between the groups",
    "compared to placebo", "vs. placebo", "vs placebo",
    "treatment arm", "metformin group", "placebo group",
    "did not improve", "did not change", "did not differ",
    "did not reach", "did not reach significance",
)


def _assign_claim_role(sentence: str, section: str) -> str:
    """Heuristic role tagging from sentence keywords + section.
    Returns 'effect' | 'dose' | 'duration' | 'population' |
    'background' | 'unknown'.

    Phase 2.1 v0.3 reviewer fix: pre-fix prioritized 'effect' first,
    so a sentence like "Global incidence of T2DM has increased over
    the past decade" tagged as effect (because of "increased") even
    though "incidence" / "globally" are clear background signals.
    Fix: BACKGROUND wins when its keywords co-occur with effect
    keywords. Effect keywords alone still tag as effect.

    Order: BACKGROUND-strong-signals > EFFECT > DURATION > DOSE >
    POPULATION > section fallback.
    """
    s = sentence.lower()
    has_effect = any(k in s for k in _ROLE_KEYWORD_EFFECT)
    has_background = any(k in s for k in _ROLE_KEYWORD_BACKGROUND)
    # Strong-background signals override effect keywords. Otherwise
    # effect wins (since most quantitative claims in results sections
    # use one of the effect keywords).
    if has_background:
        return "background"
    if has_effect:
        return "effect"
    if any(k in s for k in _ROLE_KEYWORD_DURATION):
        return "duration"
    if any(k in s for k in _ROLE_KEYWORD_DOSE):
        return "dose"
    if any(k in s for k in _ROLE_KEYWORD_POPULATION):
        return "population"
    # Phase 2.1 v0.3 audit fix: section-based fallback is honest only
    # when there's a clear introduction-vs-results polarity. Pre-fix,
    # results/discussion/conclusion defaulted to "effect" for ANY
    # claim with no keyword match — that overlabeled interpretive
    # numbers, table-residue percentages, and citation-context numbers
    # as findings. Now: only "introduction" carries a directional
    # default (background); everything else stays "unknown" so
    # downstream Phase 4 can apply its own logic without assuming
    # the extractor "knew."
    if section == "introduction":
        return "background"
    return "unknown"


# Phase 2.1 v0.3 audit fix: word-boundary anchored duration tokens
# for the sample_size override. Substring matching false-fired on
# "min" inside "metformin"; \b ensures whole-word match. Plurals
# allowed via optional 's'.
_DURATION_TOKEN_RE = re.compile(
    r"\b(?:weeks?|months?|days?|years?|hours?|minutes?)\b",
    re.IGNORECASE,
)


# Sentence segmenter — split on sentence-final punctuation followed
# by whitespace + a sentence-start (capital letter OR digit). Reviewer-
# flagged HIGH bug fix: pre-fix `(?=[A-Z])` failed to split "...
# significant. 58% of subjects responded." because '5' is not [A-Z],
# producing a multi-sentence blob in the `sentence` field. Now splits
# on `[A-Z0-9]` so number-starting clauses also count as sentence
# boundaries (e.g. "the effect was significant. 58% of participants...").
# Decimals like "0.05" don't false-split because the preceding char
# is a digit, not [.!?].
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")


def _split_sentences(text: str) -> list[tuple[int, str]]:
    """Returns (start_offset_in_text, sentence_text) tuples. Used to
    map a numeric match back to its containing sentence."""
    out: list[tuple[int, str]] = []
    cursor = 0
    for chunk in _SENTENCE_SPLIT_RE.split(text):
        chunk_clean = chunk.strip()
        if not chunk_clean:
            cursor += len(chunk) + 1  # +1 for the consumed delimiter
            continue
        idx = text.find(chunk_clean, cursor)
        if idx < 0:
            idx = cursor
        out.append((idx, chunk_clean))
        cursor = idx + len(chunk_clean)
    return out


def _sentence_for_offset(
    offset: int, sentences: list[tuple[int, str]],
) -> str:
    """Find the sentence containing `offset`; "" if not found."""
    best = ""
    for start, text in sentences:
        if start <= offset < start + len(text):
            best = text
        elif start > offset:
            break
    return best


def _context_window(text: str, start: int, end: int, radius: int = 60) -> str:
    """Return ±radius chars around [start, end), with newlines flattened."""
    a = max(0, start - radius)
    b = min(len(text), end + radius)
    return " ".join(text[a:b].split())


# --- Per-pattern extractors ----------------------------------------------


def _extract_p_values(
    text: str, section: str, paper_id: str, sentences: list[tuple[int, str]],
) -> list[QuantClaim]:
    # group(2) is the comparator (<, >, =) — preserved verbatim in
    # raw_text (e.g. "p < .001"); Phase 4 parses it from raw_text.
    out: list[QuantClaim] = []
    for m in _P_VALUE_RE.finditer(text):
        try:
            value = float(m.group(3))
        except ValueError:
            continue
        out.append(QuantClaim(
            claim_id=f"{paper_id}-p-{m.start()}",
            claim_type="p_value",
            raw_text=m.group(0),
            numeric_values=(value,),
            units="",
            source_section=section,
            source_offset=m.start(),
            sentence=_sentence_for_offset(m.start(), sentences),
            context_window=_context_window(text, m.start(), m.end()),
        ))
    return out


def _extract_confidence_intervals(
    text: str, section: str, paper_id: str, sentences: list[tuple[int, str]],
) -> list[QuantClaim]:
    out: list[QuantClaim] = []
    for m in _CI_RE.finditer(text):
        # Reviewer-fix v0.2: CI level (95/99/...) captured as group(1)
        # so non-95% intervals don't silently drop. Lo/hi shift to
        # group(2)/group(3); the level itself goes into `units` so
        # downstream Phase 4 can disambiguate `95% CI` vs `99% CI`.
        try:
            level_pct = m.group(1)
            lo = float(m.group(2))
            hi = float(m.group(3))
        except (ValueError, IndexError):
            continue
        out.append(QuantClaim(
            claim_id=f"{paper_id}-ci-{m.start()}",
            claim_type="confidence_interval",
            raw_text=m.group(0),
            numeric_values=(lo, hi),
            units=f"{level_pct}%CI",
            source_section=section,
            source_offset=m.start(),
            sentence=_sentence_for_offset(m.start(), sentences),
            context_window=_context_window(text, m.start(), m.end()),
        ))
    return out


def _extract_sample_sizes(
    text: str, section: str, paper_id: str, sentences: list[tuple[int, str]],
) -> list[QuantClaim]:
    out: list[QuantClaim] = []
    for m in _SAMPLE_SIZE_RE.finditer(text):
        try:
            value = int(m.group(1))
        except ValueError:
            continue
        out.append(QuantClaim(
            claim_id=f"{paper_id}-n-{m.start()}",
            claim_type="sample_size",
            raw_text=m.group(0),
            numeric_values=(float(value),),
            units="",
            source_section=section,
            source_offset=m.start(),
            sentence=_sentence_for_offset(m.start(), sentences),
            context_window=_context_window(text, m.start(), m.end()),
        ))
    return out


def _extract_mean_sd(
    text: str, section: str, paper_id: str, sentences: list[tuple[int, str]],
) -> list[QuantClaim]:
    out: list[QuantClaim] = []
    for m in _MEAN_SD_RE.finditer(text):
        try:
            mean = float(m.group(1))
            sd = float(m.group(2))
        except ValueError:
            continue
        out.append(QuantClaim(
            claim_id=f"{paper_id}-msd-{m.start()}",
            claim_type="mean_sd",
            raw_text=m.group(0),
            numeric_values=(mean, sd),
            units="",
            source_section=section,
            source_offset=m.start(),
            sentence=_sentence_for_offset(m.start(), sentences),
            context_window=_context_window(text, m.start(), m.end()),
        ))
    return out


def _is_inside_occupied_span(
    start: int, end: int, occupied: list[tuple[int, int]],
) -> bool:
    """Reviewer-flagged HIGH bug fix: pre-fix the `occupied` membership
    check used `(start, end) in set` which only matched EXACT tuple
    equality. A percentage at offset (25, 28) inside a CI at offset
    (25, 62) had different tuples and was NOT suppressed — the CI's
    own '95%' anchor leaked back as a standalone percentage claim
    (and the same for digits inside CI bounds and unit values). Fix:
    proper interval-containment check."""
    for s, e in occupied:
        if s <= start and end <= e:
            return True
    return False


def _extract_percentages(
    text: str, section: str, paper_id: str, sentences: list[tuple[int, str]],
    occupied: list[tuple[int, int]],
) -> list[QuantClaim]:
    out: list[QuantClaim] = []
    for m in _PERCENT_RE.finditer(text):
        # Skip if this percent's span sits INSIDE an already-claimed
        # higher-priority span (CI literal includes "95%" anchor and
        # numeric bounds; we don't double-count).
        if _is_inside_occupied_span(m.start(), m.end(), occupied):
            continue
        try:
            value = float(m.group(1))
        except ValueError:
            continue
        out.append(QuantClaim(
            claim_id=f"{paper_id}-pct-{m.start()}",
            claim_type="percentage",
            raw_text=m.group(0),
            numeric_values=(value,),
            units="%",
            source_section=section,
            source_offset=m.start(),
            sentence=_sentence_for_offset(m.start(), sentences),
            context_window=_context_window(text, m.start(), m.end()),
        ))
    return out


# Per-pattern dispatch with sanity bounds. Reviewer-flagged HIGH bug
# fix: HR/OR/RR clinical ratios live in 0.01-50 range; values outside
# that are typically heart rate (72), age (65), or body weight (80) —
# false positives from pattern collisions. Drop them post-match.
_EFFECT_SIZE_PATTERNS = (
    # (claim_type, id_prefix, pattern, max_plausible_value)
    ("hazard_ratio", "hr-l", _HAZARD_RATIO_LONG_RE, 100.0),
    ("hazard_ratio", "hr-a", _HAZARD_RATIO_ABBR_RE, 100.0),
    ("odds_ratio", "or-l", _ODDS_RATIO_LONG_RE, 100.0),
    ("odds_ratio", "or-a", _ODDS_RATIO_ABBR_RE, 100.0),
    ("risk_ratio", "rr-l", _RISK_RATIO_LONG_RE, 100.0),
    ("risk_ratio", "rr-a", _RISK_RATIO_ABBR_RE, 100.0),
    # Correlation r values must be in [-1, 1] by definition.
    ("correlation", "corr", _CORRELATION_RE, 1.0),
)


def _extract_effect_sizes(
    text: str, section: str, paper_id: str, sentences: list[tuple[int, str]],
    occupied: list[tuple[int, int]],
) -> list[QuantClaim]:
    """Phase 2.1: extract HR / OR / RR / correlation. Each matches a
    keyword anchor + numeric. Skipped if span is inside an already-
    claimed CI literal. Sanity bound applied per claim_type so bare
    "HR: 72" (a heart rate, not a hazard ratio) doesn't leak.

    Phase 2.1 v0.3 reviewer fix: separate long-form (case-insensitive,
    "hazard ratio") from short-form (CAPS only + mandatory [:=])
    patterns, with per-type sanity ceilings.
    """
    out: list[QuantClaim] = []
    for claim_type, prefix, pattern, max_value in _EFFECT_SIZE_PATTERNS:
        for m in pattern.finditer(text):
            if _is_inside_occupied_span(m.start(), m.end(), occupied):
                continue
            # Correlation pattern has multiple alternation groups —
            # find the first non-None capture.
            value_str = next(
                (g for g in m.groups() if g is not None), None,
            )
            if value_str is None:
                continue
            try:
                value = float(value_str)
            except ValueError:
                continue
            # Sanity bound — reject implausible values that almost
            # certainly come from pattern-natural-language collision.
            # For correlations, also enforce the lower bound (-1).
            if abs(value) > max_value:
                continue
            if claim_type == "correlation" and value < -1.0:
                continue
            out.append(QuantClaim(
                claim_id=f"{paper_id}-{prefix}-{m.start()}",
                claim_type=claim_type,
                raw_text=m.group(0),
                numeric_values=(value,),
                units="",
                source_section=section,
                source_offset=m.start(),
                sentence=_sentence_for_offset(m.start(), sentences),
                context_window=_context_window(text, m.start(), m.end()),
            ))
    return out


def _extract_unit_values(
    text: str, section: str, paper_id: str, sentences: list[tuple[int, str]],
    occupied: list[tuple[int, int]],
) -> list[QuantClaim]:
    out: list[QuantClaim] = []
    for m in _UNIT_VALUE_RE.finditer(text):
        # Same interval-containment fix as percentages — see
        # `_is_inside_occupied_span` docstring for the bug history.
        if _is_inside_occupied_span(m.start(), m.end(), occupied):
            continue
        try:
            value = float(m.group(1))
        except ValueError:
            continue
        unit = m.group(2)
        out.append(QuantClaim(
            claim_id=f"{paper_id}-u-{m.start()}",
            claim_type="unit_value",
            raw_text=m.group(0),
            numeric_values=(value,),
            units=unit,
            source_section=section,
            source_offset=m.start(),
            sentence=_sentence_for_offset(m.start(), sentences),
            context_window=_context_window(text, m.start(), m.end()),
        ))
    return out


# --- Public API -----------------------------------------------------------


def extract_from_text(
    text: str, section: str, paper_id: str = "anon",
) -> tuple[QuantClaim, ...]:
    """Extract quantitative claims from one section body.

    Returns an empty tuple if `section` is "references" — citation
    years and page numbers in references false-fire on percentage
    and sample_size patterns. Phase 4 doesn't want references claims
    anyway.
    """
    if section == "references":
        return ()
    if section not in _INCLUDED_SECTIONS:
        return ()
    if not text:
        return ()
    norm = _normalize(text)
    sentences = _split_sentences(norm)

    # Char-spans already claimed by higher-priority patterns. Stored as
    # a LIST (not a set) so `_is_inside_occupied_span` can do interval
    # containment — the previous tuple-equality set silently allowed
    # CI bounds and "95%" anchors to leak as standalone percentage
    # claims (reviewer-flagged HIGH bug; tested in
    # test_percentage_inside_ci_not_double_counted).
    occupied: list[tuple[int, int]] = []
    p_claims = _extract_p_values(norm, section, paper_id, sentences)
    for c in p_claims:
        occupied.append((c.source_offset, c.source_offset + len(c.raw_text)))
    ci_claims = _extract_confidence_intervals(norm, section, paper_id, sentences)
    for c in ci_claims:
        # Mark the entire CI raw_text span occupied so percentages
        # inside it (the bounds + the "95%" anchor) aren't re-claimed.
        occupied.append((c.source_offset, c.source_offset + len(c.raw_text)))
    sample_claims = _extract_sample_sizes(norm, section, paper_id, sentences)
    for c in sample_claims:
        occupied.append((c.source_offset, c.source_offset + len(c.raw_text)))
    mean_sd_claims = _extract_mean_sd(norm, section, paper_id, sentences)
    for c in mean_sd_claims:
        occupied.append((c.source_offset, c.source_offset + len(c.raw_text)))
    pct_claims = _extract_percentages(
        norm, section, paper_id, sentences, occupied,
    )
    for c in pct_claims:
        occupied.append((c.source_offset, c.source_offset + len(c.raw_text)))
    # Phase 2.1: effect-size patterns (HR / OR / RR / correlation)
    # before unit_value so a "HR: 1.25" doesn't get misread; effect-
    # size raw_text spans marked occupied to prevent unit_value
    # double-claim.
    effect_claims = _extract_effect_sizes(
        norm, section, paper_id, sentences, occupied,
    )
    for c in effect_claims:
        occupied.append((c.source_offset, c.source_offset + len(c.raw_text)))
    unit_claims = _extract_unit_values(
        norm, section, paper_id, sentences, occupied,
    )

    all_claims = (
        p_claims + ci_claims + sample_claims
        + mean_sd_claims + pct_claims + effect_claims + unit_claims
    )
    # Phase 2.1: post-process — assign claim_role from sentence
    # keywords + section context. Frozen dataclass rebuild via
    # dataclasses.replace.
    # Phase 2.2: also bind endpoint/arm/direction from sentence vocab.
    # The sentence-relative anchor (claim's source_offset minus the
    # sentence's start in the section) lets the proximity tiebreaker
    # in match_direction pick the closest direction word.
    # Reviewer-flagged MEDIUM fix: pre-fix used a dict keyed by
    # sentence text, which collapsed identical-text sentences (e.g.
    # boilerplate "Results are shown in Figure X.") and made the
    # proximity anchor stale for the first occurrence. Now we look
    # up sentence start by SCANNING sentences in order and taking the
    # one whose [start, start+len] window contains the claim offset.
    def _sentence_start_for_claim(claim_offset: int) -> int:
        for s_start, s_text in sentences:
            if s_start <= claim_offset < s_start + len(s_text):
                return s_start
        return 0
    enriched = []
    for c in all_claims:
        role = _assign_claim_role(c.sentence, section)
        # Phase 2.1 v0.3 audit fix: sample_size with trailing duration
        # token (n=12 weeks/months/days/years/hours/min) is a study
        # duration, not an enrollment count. Override role so Phase 4
        # can post-filter cleanly without dropping the candidate.
        # Word-boundary regex prevents "min" inside "metformin" from
        # false-firing on real sample sizes like "(n = 26) or metformin".
        if c.claim_type == "sample_size":
            # Reviewer-flagged LOW guard: context_window.find can return
            # -1 if the raw_text was fragmented during whitespace
            # canonicalization. In practice raw_text is single-space-
            # canonical from _normalize, but cheap defensive: skip the
            # tail check if the substring isn't found verbatim.
            idx = c.context_window.find(c.raw_text)
            if idx >= 0:
                tail = c.context_window[idx + len(c.raw_text):][:30]
                if _DURATION_TOKEN_RE.search(tail):
                    role = "duration"
        # Phase 2.2 binding: pass the claim's sentence + the sentence's
        # start-offset within the section so direction proximity is
        # computed in sentence-local coordinates.
        # Phase 2.2-fix (P1 #3): pass `role` so binding_confidence_for
        # gates "high" on effect-shaped roles. Dose/duration/population
        # claims with full endpoint+arm+direction context now correctly
        # land as "partial" rather than masquerading as primary evidence.
        sent_start = _sentence_start_for_claim(c.source_offset)
        binding = quant_endpoints.bind_claim(
            sentence=c.sentence,
            source_offset_in_section=c.source_offset,
            sentence_offset_in_section=sent_start,
            claim_role=role,
        )
        enriched.append(replace(
            c,
            claim_role=role,
            endpoint=binding.endpoint,
            arm=binding.arm,
            direction=binding.direction,
            binding_confidence=binding.binding_confidence,
        ))
    enriched.sort(key=lambda c: (c.source_offset, c.claim_type))
    return tuple(enriched)


def extract_from_paper_sections(
    parsed_path: Path | str,
) -> tuple[QuantClaim, ...]:
    """Read a `paper_sections.json` and run extraction on every
    non-references section. Returns the union of all per-section
    claims. Each claim's `source_section` says which section it came
    from; offsets are within that section.
    """
    p = Path(parsed_path)
    data = json.loads(p.read_text())
    paper_id = data.get("paper_id", p.stem)
    sections: dict[str, str] = data.get("sections", {})
    out: list[QuantClaim] = []
    for section_name, body in sections.items():
        if section_name == "references":
            continue
        if not body:
            continue
        out.extend(extract_from_text(body, section_name, paper_id))
    return tuple(out)


def make_artifact(
    paper_id: str, doi: str, claims: tuple[QuantClaim, ...] | list[QuantClaim],
    *, now: dt.datetime | None = None,
) -> dict:
    """Wrap a list of claims into the JSON output shape (with metadata
    + per-type counts). Counts are useful for at-a-glance quality
    scoring without parsing the full claims array.

    `now` is injectable for deterministic CI snapshots — pass a fixed
    datetime to get a byte-identical artifact across runs. Default is
    real wall-clock UTC, which is fine for the human-read artifact but
    breaks naive snapshot tests.
    """
    counts: dict[str, int] = {}
    for c in claims:
        counts[c.claim_type] = counts.get(c.claim_type, 0) + 1
    when = now if now is not None else dt.datetime.now(dt.timezone.utc)
    return {
        "paper_id": paper_id,
        "doi": doi,
        "extracted_at": when.isoformat(timespec="seconds"),
        "extractor_version": EXTRACTOR_VERSION,
        "claims_count_by_type": counts,
        "claims": [asdict(c) for c in claims],
    }


def main(argv: list[str] | None = None) -> int:
    """CLI: extract claims from one paper_sections.json and write the
    quant_claims artifact to --out (default: sibling `.quant_claims.json`)."""
    parser = argparse.ArgumentParser(
        description="Extract quantitative claims from a paper_sections.json",
    )
    parser.add_argument(
        "input", help="Path to paper_sections.json from pdf_ingest.py",
    )
    parser.add_argument(
        "--out",
        help="Output path (default: <input>.quant_claims.json next to input)",
    )
    args = parser.parse_args(argv)
    in_path = Path(args.input).resolve()
    if not in_path.exists():
        print(f"input not found: {in_path}", file=sys.stderr)
        return 2
    data = json.loads(in_path.read_text())
    claims = extract_from_paper_sections(in_path)
    artifact = make_artifact(
        paper_id=data.get("paper_id", in_path.stem),
        doi=data.get("doi", ""),
        claims=claims,
    )
    out_path = (
        Path(args.out).resolve() if args.out
        else in_path.with_suffix(".quant_claims.json")
    )
    out_path.write_text(json.dumps(artifact, indent=2))
    counts = artifact["claims_count_by_type"]
    summary = (
        f"{artifact['paper_id']}: total={len(claims)} "
        + " ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    )
    print(summary, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
