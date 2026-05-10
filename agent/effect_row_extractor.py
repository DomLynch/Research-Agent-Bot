"""Bridge from per-paper quant_claims.json to meta-analysis EffectRow.

Phase 5 (Fix #59): the meta-analysis pooler in `scripts.meta_analysis`
expects rows shaped (study_id, effect_measure, effect, se). The synthesis
manifest only carries slim receipt summaries (no effect / SE), so the
adapter previously had no input and fail-closed every outcome group with
"insufficient_compatible_effect_sizes".

This module pattern-matches sentences inside per-paper quant_claims for
the canonical HR/OR/RR + 95% CI report shape:

    "HR 0.85 (95% CI 0.72–1.01)"
    "Hazard ratio 1.27, 95% CI: 1.05 to 1.54"
    "OR = 0.43 (95% CI, 0.21-0.85)"

When matched, it computes log_HR/log_OR/log_RR + SE under the log-normal
CI assumption (the standard back-calculation every survival paper uses)
and returns the row in the {effect, se, effect_measure, outcome,
study_id} shape the pooler consumes.

Stdlib only. No LLM. Fail-closed: a paper with no parseable ratio is
simply absent from the output (no spurious zero rows).
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from statistics import NormalDist
from typing import Any, Iterable, Sequence

__all__ = [
    "ExtractedRow",
    "extract_rows_from_paper",
    "extract_rows_from_corpus",
    "to_pooler_input",
]


@dataclass(frozen=True, slots=True)
class ExtractedRow:
    """One ratio claim normalized for the meta-analysis pooler."""

    study_id: str
    paper_id: str
    outcome_class: str
    effect_measure: str   # "log_HR" | "log_OR" | "log_RR"
    effect: float          # log of the point estimate
    se: float              # SE of the log effect
    point_estimate: float  # original ratio (HR/OR/RR)
    ci_lower: float
    ci_upper: float
    sentence: str


# Effect + 95% CI patterns. Each entry: (measure, scale, regex).
#   - "log" scale: ratio measures (HR/OR/RR). effect = ln(eff),
#     SE = (ln(hi) - ln(lo)) / (2 * z_95). Sign-preserving point check.
#   - "linear" scale: absolute differences (MD/SMD/beta). effect = eff,
#     SE = (hi - lo) / (2 * z_95). Allows negative effects/CIs.
# Order matters: more specific patterns first so generic "OR" doesn't
# eat "aOR" etc. Within scale, ratio patterns precede linear patterns
# so a sentence with both reports flags the ratio (the canonical
# meta-analysable shape).
_Z95 = NormalDist().inv_cdf(0.975)  # ≈ 1.95996

# Reusable shared tail: optional opener + space + lo, sep, hi, optional closer.
_CI_TAIL_LOG = (
    r"[\s,;]*\(?[\s,:]*"
    r"(?:95\s*%\s*CI[\s,:]*|95\s*%\s*confidence\s+interval[\s,:]*)?"
    r"(?P<lo>\d+\.\d+|\d+)"
    r"\s*(?:[-–—]|to|,)\s*"
    r"(?P<hi>\d+\.\d+|\d+)\s*\)?"
)

# Linear patterns must accept negative numbers in eff, lo, hi. The
# em-dash separator collides with a leading minus sign, so for linear
# CIs we accept "to" / "," / explicit dashes flanked by whitespace.
_LIN_NUM = r"-?\d+\.\d+|-?\d+"
_CI_TAIL_LINEAR = (
    r"[\s,;]*\(?[\s,:]*"
    r"(?:95\s*%\s*CI[\s,:]*|95\s*%\s*confidence\s+interval[\s,:]*)?"
    r"(?P<lo>" + _LIN_NUM + r")"
    r"\s*(?:to|,|–|—|\s-\s)\s*"
    r"(?P<hi>" + _LIN_NUM + r")\s*\)?"
)

_RATIO_PATTERNS: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    ("log_HR", "log", re.compile(
        r"\b(?:adjusted\s+)?(?:hazard\s+ratio|aHR|HR)\s*"
        r"(?:was|of|=|:)?\s*"
        r"(?P<eff>\d+\.\d+|\d+)" + _CI_TAIL_LOG,
        re.IGNORECASE,
    )),
    ("log_OR", "log", re.compile(
        r"\b(?:adjusted\s+)?(?:odds\s+ratio|aOR|OR)\s*"
        r"(?:was|of|=|:)?\s*"
        r"(?P<eff>\d+\.\d+|\d+)" + _CI_TAIL_LOG,
        re.IGNORECASE,
    )),
    ("log_RR", "log", re.compile(
        r"\b(?:relative\s+risk|risk\s+ratio|RR)\s*"
        r"(?:was|of|=|:)?\s*"
        r"(?P<eff>\d+\.\d+|\d+)" + _CI_TAIL_LOG,
        re.IGNORECASE,
    )),
    # Wave 16+: absolute-difference measures. SE = (hi - lo) / (2*z_95)
    # — no log transform. Effects can be negative.
    ("MD", "linear", re.compile(
        r"\b(?:mean\s+difference|MD)\s*"
        r"(?:was|of|=|:)?\s*"
        r"(?P<eff>" + _LIN_NUM + r")" + _CI_TAIL_LINEAR,
        re.IGNORECASE,
    )),
    ("SMD", "linear", re.compile(
        r"\b(?:standardi[sz]ed\s+mean\s+difference|SMD|Cohen'?s\s+d)\s*"
        r"(?:was|of|=|:)?\s*"
        r"(?P<eff>" + _LIN_NUM + r")" + _CI_TAIL_LINEAR,
        re.IGNORECASE,
    )),
    ("beta", "linear", re.compile(
        r"\b(?:beta|β|regression\s+coefficient)\s*"
        r"(?:coefficient\s*)?"
        r"(?:was|of|=|:)?\s*"
        r"(?P<eff>" + _LIN_NUM + r")" + _CI_TAIL_LINEAR,
        re.IGNORECASE,
    )),
)


def _row_from_match(
    *,
    study_id: str,
    paper_id: str,
    outcome_class: str,
    measure: str,
    scale: str,
    eff_s: str,
    lo_s: str,
    hi_s: str,
    sentence: str,
) -> ExtractedRow | None:
    """Build an ExtractedRow from regex groups. Returns None when the
    bracketed CI is degenerate or the scale-specific math is undefined
    (e.g. a ratio of 0 for which log is undefined).

    `scale` selects the math:
      - "log"    : ratio measures (HR/OR/RR). Effect = ln(eff),
                   SE = (ln(hi)-ln(lo))/(2*z_95). Requires all values > 0.
      - "linear" : absolute differences (MD/SMD/beta). Effect = eff,
                   SE = (hi-lo)/(2*z_95). Negative values are allowed.
    """
    try:
        eff = float(eff_s)
        lo = float(lo_s)
        hi = float(hi_s)
    except ValueError:
        return None
    if lo >= hi:
        return None
    # Sanity: the point estimate should fall within or very close to the CI.
    # Off by >5% on either side suggests the regex grabbed two unrelated
    # numbers; reject silently. For linear scale the margin is additive
    # (5% of the CI width) since multiplicative margins break around zero.
    if scale == "log":
        if not (lo > 0.0 and hi > 0.0 and eff > 0.0):
            return None
        margin = 1.05
        if eff < lo / margin or eff > hi * margin:
            return None
        out_effect = math.log(eff)
        out_se = (math.log(hi) - math.log(lo)) / (2.0 * _Z95)
    else:
        # linear
        margin_abs = 0.05 * (hi - lo)
        if eff < lo - margin_abs or eff > hi + margin_abs:
            return None
        out_effect = eff
        out_se = (hi - lo) / (2.0 * _Z95)
    if out_se <= 0.0 or not math.isfinite(out_se):
        return None
    return ExtractedRow(
        study_id=study_id,
        paper_id=paper_id,
        outcome_class=outcome_class,
        effect_measure=measure,
        effect=out_effect,
        se=out_se,
        point_estimate=eff,
        ci_lower=lo,
        ci_upper=hi,
        sentence=sentence,
    )


def extract_rows_from_paper(
    quant_claims_path: Path | str,
    *,
    study_id: str,
    paper_id: str,
    outcome_class: str,
) -> list[ExtractedRow]:
    """Scan one paper's quant_claims.json for ratio + CI report shapes.

    Each matched (HR|OR|RR + 95% CI lo–hi) sentence becomes one row.
    A paper can produce multiple rows (different endpoints / arms);
    callers downstream filter by outcome_class match. The first
    well-formed match per claim wins (higher-precedence pattern first)."""
    p = Path(quant_claims_path)
    if not p.is_file():
        return []
    try:
        data = json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    claims = data.get("claims") or []
    if not isinstance(claims, list):
        return []
    rows: list[ExtractedRow] = []
    seen_sentences: set[str] = set()
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        sentence = str(claim.get("sentence") or claim.get("raw_text") or "").strip()
        if not sentence or sentence in seen_sentences:
            continue
        for measure, scale, pattern in _RATIO_PATTERNS:
            m = pattern.search(sentence)
            if not m:
                continue
            row = _row_from_match(
                study_id=study_id,
                paper_id=paper_id,
                outcome_class=outcome_class,
                measure=measure,
                scale=scale,
                eff_s=m.group("eff"),
                lo_s=m.group("lo"),
                hi_s=m.group("hi"),
                sentence=sentence,
            )
            if row is not None:
                rows.append(row)
                seen_sentences.add(sentence)
                break
    return rows


def extract_rows_from_corpus(
    receipts: Sequence[dict[str, Any]],
    *,
    quant_claims_dir: Path | str,
) -> list[ExtractedRow]:
    """Scan every receipt's per-paper quant_claims for ratio rows.

    Resolves the quant_claims file by `<quant_claims_dir>/<paper_id>.quant_claims.json`.
    Receipts without a parseable ratio contribute zero rows. Order is
    receipt-list order so callers can map back deterministically."""
    base = Path(quant_claims_dir)
    out: list[ExtractedRow] = []
    for r in receipts:
        if not isinstance(r, dict):
            continue
        paper_id = str(r.get("paper_id") or r.get("receipt_id") or "")
        if not paper_id:
            continue
        study_id = str(r.get("citation_token") or paper_id)
        outcome_class = str(r.get("outcome_class") or "unknown")
        path = base / f"{paper_id}.quant_claims.json"
        out.extend(extract_rows_from_paper(
            path, study_id=study_id, paper_id=paper_id,
            outcome_class=outcome_class,
        ))
    return out


def to_pooler_input(rows: Iterable[ExtractedRow]) -> list[dict[str, Any]]:
    """Convert ExtractedRow objects into the dict shape that
    `scripts.meta_analysis.pool_fixed_effect` consumes (it indexes via
    .get(...) calls on a Mapping). One dict per row; outcomes mixed in
    one list — caller groups by outcome_class before pooling."""
    return [
        {
            "receipt_id": r.study_id,
            "outcome": r.outcome_class,
            "effect_measure": r.effect_measure,
            "effect": r.effect,
            "standard_error": r.se,
        }
        for r in rows
    ]
