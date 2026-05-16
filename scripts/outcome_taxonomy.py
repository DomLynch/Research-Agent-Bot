"""Outcome-class refiner — split 'other' into specific OutcomeClass via keyword scan.

Slice 39 (2026-05-16): role-aware admission (Slice 37) admitted 65
vitamin_d receipts but 46 landed in `other` because the endpoint→class
vocab covers a thin subset. This refiner is a deterministic post-pass
that promotes `other` to a meaningful OutcomeClass when the receipt's
text contains characteristic vocabulary. Maps to the EXISTING enum so
no schema migration. Universal — same rules apply to any topic.

Lives in scripts/ rather than agent/ because it is runner-side glue
called from `build_receipts_from_quant_claims`. If the rules grow into
a domain library, promote to `agent/outcome_taxonomy.py` then.
"""
from __future__ import annotations
from typing import Any

# (target_class, keyword_tuple). Order = priority (first match wins).
# All targets map to the EXISTING OutcomeClass Literal in synthesis_schemas
# so no enum migration is needed. Keywords are biomedical-leaning today but
# the structure is universal — swap the table per domain later.
_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("longevity", ("mortality", "survival", "death", "all-cause", "lifespan")),
    ("immune", ("immune", "inflammation", "sepsis", "infection", "cytokine", "crp", "il-6", "tnf")),
    ("frailty", ("bone", "fracture", "osteoporosis", "calcium", "skeletal", "fall", "hip")),
    ("cardiometabolic", ("diabetes", "glycem", "insulin", "lipid", "ldl", "hdl", "blood pressure", "hypertension", "kidney", "renal", "ckd")),
    ("muscle_function", ("muscle", "strength", "grip", "sarcopenia", "lean mass")),
    ("safety", ("safety", "adverse", "toxic", "tolerability")),
    ("mechanism", ("pharmacokinetic", "pharmacology", "cholecalciferol", "calcifediol", "calcitriol", "metabolism")),
    ("cognitive", ("cognitive", "dementia", "alzheimer", "mmse")),
)


def refine_outcome_class(receipt: Any) -> str:
    """Promote `other` to a specific OutcomeClass via keyword scan over
    receipt text fields. Pass-through unchanged for already-classified
    receipts. Universal — no per-topic tokens."""
    current = (getattr(receipt, "outcome_class", "") or "").lower()
    if current and current != "other":
        return current
    text = " ".join(str(getattr(receipt, f, "") or "").lower()
                    for f in ("receipt_id", "thesis_text", "source_title", "population_summary"))
    return next((cls for cls, keys in _RULES if any(k in text for k in keys)), "other")
