"""Synthesis layer — Day 10 paper engine.

Aggregates N claim receipts (Day 1-9 output) into a synthesis paper
artifact (`paper_synthesis.md`) audited against the 7-paper Quality
Reference Corpus rubric.

Day 10.2 (this slice): the deterministic foundation. Two public
functions:

  build_receipt_summary(...)   — convert one saved receipt directory
                                 into a structured ReceiptSummary
  build_tension_matrix(...)    — pairwise tension classification
                                 across N summaries

Subsequent slices add:
  Day 10.3: synthesize_thesis (LLM proposes K, code disposes)
  Day 10.4: render_synthesis_paper (sectioned writer)
  Day 10.5: orchestration glue + --synthesize flag
  Day 10.6: empirical metformin run + audit ≥8.5/10

Design decisions for the tension matrix:

  1. NO LLM in tension detection — branches considered:
     (A) deterministic keyword/sign classifier (chosen)
     (B) LLM-aided pairing — rejected, defeats CODE DISPOSES
     (C) ClaimEdge-based — rejected, Day 1-9 left edges empty

  2. outcome_class derivation: case-insensitive substring match against
     curated keyword sets per class. First-seen-wins ordering covers
     the metformin reference corpus cleanly (muscle_function before
     mechanism, etc.) without per-pack tuning.

  3. effect_direction derivation: heuristic combining
     - "blunted/attenuated/reduced/decreased" verbs → negative
     - "improved/increased/enhanced" verbs → positive
     - "no significant difference/comparable/null" verbs → null
     - p-value ≥ 0.05 with no signed effect verb → null
     - HR/OR/RR with explicit numeric → sign from value
     - mechanism-only (no human outcome) → unclear

  4. Pair classification produces ONE Tension per (a, b) with
     a.receipt_id < b.receipt_id (canonical ordering, no double-count).

  5. severity is 0 (orthogonal) → 5 (direct disagreement on same
     outcome). The synthesis writer uses severity to prioritize which
     tensions get prose treatment in the Tensions section.
"""
from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path

from agent.synthesis_schemas import (
    EffectDirection,
    OutcomeClass,
    ReceiptSummary,
    Tension,
    TensionKind,
    TensionMatrix,
)

__all__ = [
    "build_receipt_summary",
    "build_tension_matrix",
    "detect_outcome_class",
    "detect_effect_direction",
]


# --- Outcome-class keyword maps ------------------------------------------
#
# Order matters: more-specific outcomes come first so a paper that
# mentions "muscle" inside a "mechanism" abstract doesn't get tagged
# as muscle_function when the load-bearing claim is mechanistic. Each
# match is case-insensitive substring; ties go to first-listed.

_OUTCOME_KEYWORDS: Mapping[OutcomeClass, frozenset[str]] = {
    "muscle_function": frozenset({
        "hypertrophy", "lean body mass", "lean tissue", "muscle mass",
        "thigh muscle", "resistance training", "fiber type",
        "sarcopenia",
    }),
    "frailty": frozenset({
        "frailty", "walk speed", "gait speed", "grip strength",
        "physical function", "sppb", "tug", "4-m walk",
    }),
    "cardiometabolic": frozenset({
        "hba1c", "glycemic", "insulin sensitivity", "vo2max",
        "vo2 max", "aerobic capacity", "blood pressure", "lipid",
        "cholesterol", "myocardial", "cardiovascular event",
    }),
    "cognitive": frozenset({
        "cognition", "cognitive decline", "dementia", "alzheimer",
        "mmse", "moca", "memory", "executive function",
    }),
    "longevity": frozenset({
        "all-cause mortality", "exceptional longevity", "lifespan",
        "death before age", "survival", "longevity",
    }),
    "immune": frozenset({
        "respiratory tract infection", "rti", "vaccination",
        "vaccine response", "antibody response", "immune function",
        "t cell", "covid",
    }),
    "ophthalmologic": frozenset({
        "amd", "macular degeneration", "diabetic retinopathy",
        "retinal", "geographic atrophy", "neovascular",
    }),
    "oncology": frozenset({
        "renal cell carcinoma", "rcc", "metastatic",
        "tumor", "neoplasm", "tnbc", "carcinoma",
        "cancer incidence",
    }),
    "safety": frozenset({
        "adverse event", "tolerability", "side effect",
        "discontinuation", "withdrawal", "gi distress",
        "diarrhea", "poorly tolerated",
    }),
    "mechanism": frozenset({
        "ampk", "mtor", "mtorc1", "autophagy", "senescence",
        "vsmc", "fibroblast", "in vitro", "transcriptom",
        "gene expression", "pathway", "knockout",
    }),
}


# Effect-direction signal patterns. Order matters within each list:
# stronger signals first. Phrase matching is case-insensitive; we
# search for whole-word boundaries where ambiguity exists.
_NEGATIVE_VERBS = (
    "blunted", "attenuated", "blunts", "attenuates",
    "negatively impacts", "interferes with", "decreased",
    "reduced [^.]{0,40}adaptation",  # reduced muscle adaptation, etc.
    "did not enhance", "did not improve", "worse", "worsens",
    "harmed", "impaired",
)
_POSITIVE_VERBS = (
    "improved", "increased", "enhanced", "augmented",
    "extended", "preserved", "protected", "lower [^.]{0,40}risk",
    "lower [^.]{0,40}mortality",
)
_NULL_VERBS = (
    "did not improve", "did not reduce", "did not change",
    "no significant difference", "comparable risk",
    "comparable [^.]{0,40}outcome", "similar [^.]{0,40}risk",
    "did not meet statistical significance",
    "no significant", "null result",
)

# Sign-from-numeric for ratios. HR/OR/RR < 1 with mortality/disease
# outcome → positive (treatment reduces bad outcome). The caller has
# already derived outcome_class so we know the direction polarity.
_RATIO_RE = re.compile(
    r"\b(?:hr|or|rr|ahr|aor|arr)\s*[=:,\-]?\s*"
    r"(\d+(?:[.·]\d+)?)",
    re.IGNORECASE,
)
# p-value capture (mirrors validators.PVALUE_RE shape).
_PVALUE_RE = re.compile(r"\bp\s*([=<>])\s*0?\.(\d+)", re.IGNORECASE)


def detect_outcome_class(
    text: str,
    *,
    fallback: OutcomeClass = "other",
) -> OutcomeClass:
    """Pure deterministic classification: substring match against the
    curated keyword sets per outcome class.

    Order is preserved from `_OUTCOME_KEYWORDS` insertion (specific
    outcomes first), so when "muscle hypertrophy" and "AMPK signaling"
    both appear in the same text, muscle_function wins (the load-bearing
    clinical outcome). Returns `fallback` when no keyword matches.
    """
    lowered = text.lower()
    for klass, kws in _OUTCOME_KEYWORDS.items():
        for kw in kws:
            if kw in lowered:
                return klass
    return fallback


def _normalize_for_match(text: str) -> str:
    """Lowercase + collapse whitespace + Unicode middle-dot → period.
    Same shape as agent/citation_trace._normalize_numeric_text but
    kept local so synthesis doesn't import from the trace layer."""
    return " ".join(
        text.replace("·", ".").replace("–", "-").replace("—", "-").split()
    ).lower()


def detect_effect_direction(
    thesis_text: str,
    *,
    outcome_class: OutcomeClass | None = None,
    p_values: Sequence[str] = (),
) -> EffectDirection:
    """Heuristic effect-direction inference from claim text + p-values.

    Rules in priority order (first match wins):
      1. Mechanism-only outcome → unclear (no clinical direction).
      2. Null-language phrase present → null.
      3. Negative-effect verb present → negative.
      4. Positive-effect verb present → positive.
      5. Explicit p-value ≥ 0.05 with no other signal → null.
      6. Otherwise → unclear.

    Day 10.2 NOTE: this is a heuristic, not a perfect classifier. The
    tension matrix is robust to "unclear" — pairs with unclear
    direction default to orthogonal (severity 0), so misclassification
    here loses tension signal but doesn't generate false agreement.
    """
    if outcome_class == "mechanism":
        return "unclear"

    norm = _normalize_for_match(thesis_text)

    # Rule 2: null first (some null phrases contain "did not improve"
    # which would also match a negative regex below if we reversed order).
    for phrase in _NULL_VERBS:
        if re.search(phrase, norm, re.IGNORECASE):
            return "null"

    # Rule 3: negative verbs
    for phrase in _NEGATIVE_VERBS:
        if re.search(phrase, norm, re.IGNORECASE):
            return "negative"

    # Rule 4: positive verbs
    for phrase in _POSITIVE_VERBS:
        if re.search(phrase, norm, re.IGNORECASE):
            return "positive"

    # Rule 5: p-value-based fallback
    for pv in p_values:
        m = _PVALUE_RE.search(pv)
        if m is None:
            continue
        op, digits = m.group(1), m.group(2)
        # Treat "p=0.NNN" / "p<0.NNN" — assume the prose authors mean
        # "the value at this op". For "p>0.05" or "p=0.NN" with NN
        # describing a fraction ≥0.05 → null.
        try:
            value = float(f"0.{digits}")
        except ValueError:
            continue
        if op in {"=", ">"} and value >= 0.05:
            return "null"
        if op == "<" and value <= 0.05:
            # Significant but no signed verb — ambiguous, leave unclear.
            return "unclear"

    return "unclear"


# --- Helpers for build_receipt_summary -----------------------------------


_NCT_RE = re.compile(r"NCT\d{8}", re.IGNORECASE)
_ISRCTN_RE = re.compile(r"ISRCTN\d+", re.IGNORECASE)


def _detect_canonical_trial_id(
    thesis_text: str,
    items_by_ref: Mapping[int, dict],
    supporting_refs: Sequence[int],
) -> str | None:
    """Find the canonical NCT or ISRCTN id this receipt anchors on.

    Looks at: (1) thesis_text, (2) supporting_refs' source.nct,
    (3) supporting_refs' abstracts. Returns first found, uppercased.
    """
    for m in _NCT_RE.findall(thesis_text):
        return m.upper()
    for m in _ISRCTN_RE.findall(thesis_text):
        return m.upper()
    for ref in supporting_refs:
        item = items_by_ref.get(ref)
        if not item:
            continue
        src = item.get("source", {}) if isinstance(item, dict) else {}
        nct = src.get("nct") if isinstance(src, dict) else None
        if nct:
            return nct.upper()
        abstract = item.get("abstract", "") if isinstance(item, dict) else ""
        for m in _NCT_RE.findall(abstract or ""):
            return m.upper()
        for m in _ISRCTN_RE.findall(abstract or ""):
            return m.upper()
    return None


_POPULATION_PATTERNS = (
    re.compile(r"(?:older|elderly)\s+adults?", re.IGNORECASE),
    re.compile(r"adults?\s+(?:aged|≥|>=)\s*\d+", re.IGNORECASE),
    re.compile(r"aged\s+\d+\s*[-–to]\s*\d+", re.IGNORECASE),
    re.compile(r"postmenopausal", re.IGNORECASE),
    re.compile(r"(?:type 2|t2d|t2dm)", re.IGNORECASE),
)


def _detect_population_summary(thesis_text: str, items_by_ref: Mapping[int, dict]) -> str:
    """Extract a one-line population descriptor from the thesis text or
    the first supporting item's abstract. Best-effort — empty string
    when no canonical pattern matches."""
    candidates: list[str] = [thesis_text]
    for item in items_by_ref.values():
        if isinstance(item, dict):
            abstract = item.get("abstract", "")
            if abstract:
                candidates.append(abstract[:300])  # first 300 chars only
    for text in candidates:
        for pat in _POPULATION_PATTERNS:
            m = pat.search(text)
            if m:
                return m.group(0)
    return ""


def _extract_p_values(thesis_text: str) -> tuple[str, ...]:
    """Pull canonical-form p-value strings from thesis text.
    Returns empty tuple when none found."""
    out: list[str] = []
    for m in _PVALUE_RE.finditer(thesis_text):
        out.append(f"p{m.group(1)}0.{m.group(2)}")
    return tuple(out)


# --- build_receipt_summary -----------------------------------------------


def build_receipt_summary(
    *,
    receipt_id: str,
    receipt_path: Path | str,
    topic: str,
    claim_graph: dict,
    items_by_ref: Mapping[int, dict],
    spar_review: dict,
) -> ReceiptSummary:
    """Convert one saved claim receipt into a structured ReceiptSummary.

    `claim_graph` is the parsed claim_graph.json (a dict with
    `claims`, `edges`, `thesis_claim_id`). `items_by_ref` maps each
    EvidenceItem ref → its dict form (parsed evidence_cards.json
    entries, but keyed by source.ref for direct lookup). `spar_review`
    is the parsed spar_review.json.

    Returns a ReceiptSummary with derived outcome_class +
    effect_direction. These are heuristic; the tension matrix is
    robust to "other"/"unclear" defaults.
    """
    claims = claim_graph.get("claims", [])
    thesis_id = claim_graph.get("thesis_claim_id")
    thesis = next(
        (c for c in claims if c.get("claim_id") == thesis_id), None,
    )
    thesis_text = thesis.get("text", "") if thesis else ""
    supporting_refs = thesis.get("supporting_refs", []) if thesis else []

    # Roll up across all claims for outcome detection so a thesis that
    # tersely says "metformin blunted X" still classifies via the
    # supporting claims' fuller text.
    rolled_text = " ".join(
        c.get("text", "") for c in claims
    )

    outcome_class = detect_outcome_class(rolled_text, fallback="other")
    if outcome_class == "other":
        # Fallback: peek at the first supporting item's abstract.
        for ref in supporting_refs:
            item = items_by_ref.get(ref)
            if isinstance(item, dict):
                abstract = item.get("abstract", "") or ""
                outcome_class = detect_outcome_class(abstract, fallback="other")
                if outcome_class != "other":
                    break

    p_values = _extract_p_values(thesis_text)
    effect_direction = detect_effect_direction(
        thesis_text, outcome_class=outcome_class, p_values=p_values,
    )

    # Pick the strongest evidence_tier and directness across the
    # claims supporting the thesis.
    if thesis:
        evidence_tier = thesis.get("evidence_tier", "C")
        directness = thesis.get("directness", "indirect")
    else:
        evidence_tier = "C"
        directness = "indirect"

    n_failed_traces = sum(
        1 for t in claim_graph.get("citation_traces", [])
        if not t.get("passed", False)
    )

    return ReceiptSummary(
        receipt_id=receipt_id,
        receipt_path=str(receipt_path),
        topic=topic,
        thesis_text=thesis_text,
        spar_verdict=spar_review.get("verdict", ""),
        n_claims=len(claims),
        n_failed_traces=n_failed_traces,
        canonical_trial_id=_detect_canonical_trial_id(
            thesis_text, items_by_ref, supporting_refs,
        ),
        evidence_tier=evidence_tier,
        directness=directness,
        outcome_class=outcome_class,
        effect_direction=effect_direction,
        p_values=p_values,
        population_summary=_detect_population_summary(
            thesis_text, items_by_ref,
        ),
    )


def load_receipt_summary(receipt_dir: Path | str) -> ReceiptSummary:
    """Convenience: load all the JSON receipts from a directory and
    build a ReceiptSummary in one call."""
    path = Path(receipt_dir)
    md = json.loads((path / "run_metadata.json").read_text(encoding="utf-8"))
    cg = json.loads((path / "claim_graph.json").read_text(encoding="utf-8"))
    sr = json.loads((path / "spar_review.json").read_text(encoding="utf-8"))
    cards = json.loads((path / "evidence_cards.json").read_text(encoding="utf-8"))
    items_by_ref = {
        item.get("source", {}).get("ref"): item
        for item in cards
        if isinstance(item, dict) and isinstance(item.get("source"), dict)
    }
    return build_receipt_summary(
        receipt_id=md.get("submission_id", path.name),
        receipt_path=path,
        topic=md.get("topic", ""),
        claim_graph=cg,
        items_by_ref=items_by_ref,
        spar_review=sr,
    )


# --- Tension matrix ------------------------------------------------------


# Severity table: matches the (kind, indirectness_gap?) cell. 0 is
# weakest (orthogonal); 5 is strongest (direct disagreement on the
# same outcome class). The synthesis writer prioritizes higher-severity
# tensions for prose treatment.
_SEVERITY: Mapping[TensionKind, int] = {
    "orthogonal": 0,
    "agreement": 2,
    "indirectness_gap": 3,
    "null_vs_positive": 4,
    "disagreement": 5,
}


def _tension_summary(kind: TensionKind, a: ReceiptSummary, b: ReceiptSummary) -> str:
    """One-line deterministic description of the tension. The synthesis
    writer can cite this verbatim in the Tensions section."""
    if kind == "orthogonal":
        return (
            f"{a.receipt_id} ({a.outcome_class}) and {b.receipt_id} "
            f"({b.outcome_class}) cover different outcome classes — no logical conflict"
        )
    if kind == "agreement":
        return (
            f"{a.receipt_id} and {b.receipt_id} both report "
            f"{a.effect_direction} effect on {a.outcome_class}"
        )
    if kind == "disagreement":
        return (
            f"{a.receipt_id} reports {a.effect_direction} effect on "
            f"{a.outcome_class}; {b.receipt_id} reports {b.effect_direction} "
            f"on the same outcome — direct conflict"
        )
    if kind == "null_vs_positive":
        signed = a if a.effect_direction != "null" else b
        nullish = b if a.effect_direction != "null" else a
        return (
            f"{signed.receipt_id} ({signed.effect_direction} on "
            f"{a.outcome_class}) vs {nullish.receipt_id} (null on "
            f"{a.outcome_class}) — partial conflict"
        )
    if kind == "indirectness_gap":
        direct_one = a if a.directness == "direct" else b
        other = b if a.directness == "direct" else a
        return (
            f"{direct_one.receipt_id} (direct, {direct_one.evidence_tier}) "
            f"vs {other.receipt_id} ({other.directness}) on "
            f"{a.outcome_class} — direct vs indirect must be kept separate"
        )
    return f"{a.receipt_id} vs {b.receipt_id}"


def _classify_pair(a: ReceiptSummary, b: ReceiptSummary) -> Tension:
    """Pure deterministic classification of one pair (a, b).

    Rules (first match wins):
      1. outcome_class differs → orthogonal
      2. one is direct, the other is mechanistic, same outcome class
         → indirectness_gap
      3. one effect is null, other is positive/negative → null_vs_positive
      4. effect_directions are opposite (positive vs negative) → disagreement
      5. effect_directions same and signed → agreement
      6. otherwise → orthogonal (both unclear / both null)

    Severity is read from `_SEVERITY` table, applied uniformly per
    kind so ranking is deterministic.
    """
    same_outcome = a.outcome_class == b.outcome_class

    if not same_outcome:
        kind: TensionKind = "orthogonal"
    else:
        # Same outcome class — now decide by directness + direction.
        a_direct = a.directness == "direct"
        b_direct = b.directness == "direct"
        a_mech = a.directness == "mechanistic"
        b_mech = b.directness == "mechanistic"

        if (a_direct and b_mech) or (b_direct and a_mech):
            kind = "indirectness_gap"
        elif a.effect_direction == "null" and b.effect_direction in {"positive", "negative"}:
            kind = "null_vs_positive"
        elif b.effect_direction == "null" and a.effect_direction in {"positive", "negative"}:
            kind = "null_vs_positive"
        elif {a.effect_direction, b.effect_direction} == {"positive", "negative"}:
            kind = "disagreement"
        elif (
            a.effect_direction == b.effect_direction
            and a.effect_direction in {"positive", "negative"}
        ):
            kind = "agreement"
        else:
            # Both unclear / both null / mixed unclear+something → orthogonal.
            kind = "orthogonal"

    return Tension(
        receipt_a_id=a.receipt_id,
        receipt_b_id=b.receipt_id,
        kind=kind,
        outcome_class=a.outcome_class if same_outcome else a.outcome_class,
        summary=_tension_summary(kind, a, b),
        severity=_SEVERITY[kind],
    )


def build_tension_matrix(
    summaries: Sequence[ReceiptSummary],
) -> TensionMatrix:
    """Pairwise tension classification across N receipt summaries.

    Returns a TensionMatrix with all C(N, 2) pairs in canonical
    ordering (a.receipt_id < b.receipt_id lexically). No LLM —
    deterministic per-pair classification.

    For N ≤ 1, returns an empty `pairs` tuple — there are no pairs
    to compare, but the matrix shell still carries the receipts so
    downstream code has something to render.
    """
    sorted_summaries = sorted(summaries, key=lambda s: s.receipt_id)
    pairs: list[Tension] = []
    for i, a in enumerate(sorted_summaries):
        for b in sorted_summaries[i + 1:]:
            pairs.append(_classify_pair(a, b))
    return TensionMatrix(
        receipts=tuple(sorted_summaries),
        pairs=tuple(pairs),
    )
