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


# Ratio + CI patterns. Order matters: HR/AHR most specific first, then
# OR/aOR, then RR/RR (relative risk).
_Z95 = NormalDist().inv_cdf(0.975)  # ≈ 1.95996

_RATIO_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("log_HR", re.compile(
        r"\b(?:adjusted\s+)?(?:hazard\s+ratio|aHR|HR)\s*"
        r"(?:was|of|=|:)?\s*"
        r"(?P<eff>\d+\.\d+|\d+)"
        r"[\s,;]*\(?[\s,:]*"
        r"(?:95\s*%\s*CI[\s,:]*|95\s*%\s*confidence\s+interval[\s,:]*)?"
        r"(?P<lo>\d+\.\d+|\d+)"
        r"\s*(?:[-–—]|to|,)\s*"
        r"(?P<hi>\d+\.\d+|\d+)\s*\)?",
        re.IGNORECASE,
    )),
    ("log_OR", re.compile(
        r"\b(?:adjusted\s+)?(?:odds\s+ratio|aOR|OR)\s*"
        r"(?:was|of|=|:)?\s*"
        r"(?P<eff>\d+\.\d+|\d+)"
        r"[\s,;]*\(?[\s,:]*"
        r"(?:95\s*%\s*CI[\s,:]*|95\s*%\s*confidence\s+interval[\s,:]*)?"
        r"(?P<lo>\d+\.\d+|\d+)"
        r"\s*(?:[-–—]|to|,)\s*"
        r"(?P<hi>\d+\.\d+|\d+)\s*\)?",
        re.IGNORECASE,
    )),
    ("log_RR", re.compile(
        r"\b(?:relative\s+risk|risk\s+ratio|RR)\s*"
        r"(?:was|of|=|:)?\s*"
        r"(?P<eff>\d+\.\d+|\d+)"
        r"[\s,;]*\(?[\s,:]*"
        r"(?:95\s*%\s*CI[\s,:]*|95\s*%\s*confidence\s+interval[\s,:]*)?"
        r"(?P<lo>\d+\.\d+|\d+)"
        r"\s*(?:[-–—]|to|,)\s*"
        r"(?P<hi>\d+\.\d+|\d+)\s*\)?",
        re.IGNORECASE,
    )),
)


def _row_from_match(
    *,
    study_id: str,
    paper_id: str,
    outcome_class: str,
    measure: str,
    eff_s: str,
    lo_s: str,
    hi_s: str,
    sentence: str,
) -> ExtractedRow | None:
    """Build an ExtractedRow from regex groups. Returns None when the
    bracketed CI is degenerate (lo>=hi) or any value isn't strictly
    positive (a ratio of 0 is mathematically undefined for log)."""
    try:
        eff = float(eff_s)
        lo = float(lo_s)
        hi = float(hi_s)
    except ValueError:
        return None
    if not (lo > 0.0 and hi > 0.0 and eff > 0.0):
        return None
    if lo >= hi:
        return None
    # Sanity: the point estimate should fall within or very close to the CI.
    # Off by >5% on either side suggests the regex grabbed two unrelated
    # numbers; reject silently.
    margin = 1.05
    if eff < lo / margin or eff > hi * margin:
        return None
    log_eff = math.log(eff)
    se = (math.log(hi) - math.log(lo)) / (2.0 * _Z95)
    if se <= 0.0 or not math.isfinite(se):
        return None
    return ExtractedRow(
        study_id=study_id,
        paper_id=paper_id,
        outcome_class=outcome_class,
        effect_measure=measure,
        effect=log_eff,
        se=se,
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
        for measure, pattern in _RATIO_PATTERNS:
            m = pattern.search(sentence)
            if not m:
                continue
            row = _row_from_match(
                study_id=study_id,
                paper_id=paper_id,
                outcome_class=outcome_class,
                measure=measure,
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
