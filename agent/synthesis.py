"""Deterministic evidence synthesis and source-level deduplication."""
from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path

from agent.endpoint_evidence import directional_kind, endpoint_direction_map, endpoint_key
from agent.sources._base import normalize_doi
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
    "load_receipt_summary",
    "unique_evidence_key",
    "same_bibliographic_source",
    "bibliographic_sources_unique",
    "dedupe_receipts",
    "count_unique_trials",
    "InsufficientUniqueEvidenceError",
    "MIN_UNIQUE_TRIALS_FOR_SYNTHESIS",
]


# Day 10.7 (reviewer P1): synthesis must operate on UNIQUE evidence
# units, not duplicate receipts. The first ship of Day 10 fed 12
# metformin receipts (all anchored on MASTERS NCT02308228) into the
# tension matrix — that's repeated-receipt aggregation, not
# cross-source synthesis. Reviewer's load-bearing finding.
#
# unique_evidence_key returns a tuple identifying a receipt's evidence
# content. Two receipts with the same key are duplicates regardless of
# their submission_id or run timestamp. Dedup uses this to collapse
# duplicates BEFORE the tension matrix is built.
#
# MIN_UNIQUE_TRIALS_FOR_SYNTHESIS is the floor below which synthesis
# isn't meaningful. Single-trial "synthesis" is a duplicate stack;
# two-trial synthesis is borderline. Three unique trials is the
# minimum bar for the Day 10 audit to be honest about coverage.
MIN_UNIQUE_TRIALS_FOR_SYNTHESIS = 3


class InsufficientUniqueEvidenceError(ValueError):
    """Raised by `_run_synthesize` when fewer than the minimum number
    of unique evidence units are available after dedup. Carries the
    unique_keys list so the caller can render a precise diagnostic.
    """


def unique_evidence_key(r: ReceiptSummary) -> tuple[str, str]:
    """Identify evidence by canonical trial and normalized thesis; unanchored receipts deduplicate by thesis alone."""
    trial = (r.canonical_trial_id or "").upper()
    thesis_sig = " ".join(r.thesis_text.lower().split())[:200]
    return (trial, thesis_sig)


def same_bibliographic_source(left: object, right: object) -> bool:
    """Match source rows by non-conflicting registered identity or exact title."""
    def value(row: object, *names: str) -> str:
        values = (row.get(name) for name in names) if isinstance(row, Mapping) else (
            getattr(row, name, None) for name in names
        )
        return next((str(item).strip() for item in values if item not in (None, "")), "")

    pairs = (
        (normalize_doi(value(left, "source_doi", "doi")) or "",
         normalize_doi(value(right, "source_doi", "doi")) or ""),
        (value(left, "source_pmid", "pmid").lstrip("0"),
         value(right, "source_pmid", "pmid").lstrip("0")),
        (value(left, "source_pmcid", "pmcid").upper(),
         value(right, "source_pmcid", "pmcid").upper()),
    )
    if any(a and b and a != b for a, b in pairs):
        return False
    if any(a and a == b for a, b in pairs):
        return True
    years = value(left, "source_year", "year"), value(right, "source_year", "year")
    if all(years) and years[0] != years[1]:
        return False
    titles = tuple(
        re.sub(r"[^a-z0-9]+", "", value(row, "source_title", "title").lower())
        for row in (left, right)
    )
    return bool(titles[0] and titles[0] == titles[1])


def bibliographic_sources_unique(rows: Sequence[object]) -> bool:
    return bool(rows) and not any(
        same_bibliographic_source(row, other)
        for index, row in enumerate(rows) for other in rows[index + 1:]
    )


def dedupe_receipts(
    summaries: Sequence[ReceiptSummary],
) -> tuple[ReceiptSummary, ...]:
    """Keep one receipt per evidence unit or bibliographic source.

    Exact-title matches collapse only when registered identifiers do not
    conflict. The strongest identified, highest-claim receipt wins.
    """
    ranked = sorted(enumerate(summaries), key=lambda item: (
        -(bool(item[1].source_doi) + bool(item[1].source_pmid)), -item[1].n_claims, item[0],
    ))
    kept: list[tuple[int, ReceiptSummary]] = []
    for item in ranked:
        if not any(
            unique_evidence_key(item[1]) == unique_evidence_key(other)
            or same_bibliographic_source(item[1], other)
            for _, other in kept
        ):
            kept.append(item)
    return tuple(row for _, row in sorted(kept))


def count_unique_trials(summaries: Sequence[ReceiptSummary]) -> int:
    """Count canonical trials, with thesis signatures for unanchored receipts. Multiple endpoints from one trial count once."""
    trial_set: set[str] = set()
    for r in summaries:
        if r.canonical_trial_id:
            trial_set.add(r.canonical_trial_id.upper())
        else:
            # Untrialed: thesis signature serves as the source-identity
            # proxy. Truncated so minor wording variations don't inflate.
            sig = " ".join(r.thesis_text.lower().split())[:120]
            trial_set.add(f"untrialed:{sig}")
    return len(trial_set)


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
    # 2026-05-09 peer-review fix: patient-reported QoL endpoints (SF-36,
    # emotional well-being, general health perception, pain, vitality)
    # are NOT cognitive outcomes. Place BEFORE "cognitive" so a paper
    # whose abstract mentions "emotional well-being" doesn't fall through
    # to the cognitive class on a partial keyword scan.
    "healthspan_qol": frozenset({
        "emotional well-being", "psychological well-being",
        "general health perception", "self-reported health",
        "self-reported pain", "pain score", "quality of life",
        "qol", "sf-36", "sf36", "vitality scale", "well-being",
        "patient-reported outcome", "pro measure",
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
    """Match curated outcome keywords in insertion order, returning fallback if none match."""
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
    """Infer direction heuristically from outcome, language and p-values. Unclear directions remain orthogonal in the tension matrix."""
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


def _detect_population_summary(
    thesis_text: str,
    items_by_ref: Mapping[int, dict],
    *,
    directness: str = "indirect",
) -> str:
    """Extract a matching population for direct RCT receipts; return empty for indirect or unmatched evidence."""
    if directness != "direct":
        return ""
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


def _claim_endpoint_evidence(
    claims: Sequence[dict],
) -> tuple[tuple[str, ...], tuple[tuple[str, EffectDirection], ...]]:
    """Derive endpoint directions only from claims explicitly bound to that endpoint."""
    grouped: dict[str, list[str]] = {}
    labels: dict[str, str] = {}
    for claim in claims:
        endpoint = " ".join(str(claim.get("endpoint") or claim.get("outcome") or "").split())
        key = endpoint_key(endpoint)
        if not key:
            continue
        labels.setdefault(key, endpoint)
        grouped.setdefault(key, []).append(str(claim.get("text") or ""))
    directions = tuple(
        (
            labels[key],
            detect_effect_direction(
                text := " ".join(parts),
                outcome_class=detect_outcome_class(f"{labels[key]} {text}"),
                p_values=_extract_p_values(text),
            ),
        )
        for key, parts in grouped.items()
    )
    return tuple(labels.values()), directions


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
    """Derive a ReceiptSummary from claim_graph, ref-keyed evidence items and SPAR review; outcome and direction remain heuristic."""
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
    endpoints, endpoint_directions = _claim_endpoint_evidence(claims)

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

    # Day 10.17 Phase 3: surface bibliographic fields from the
    # thesis-supporting evidence cards so References can render real
    # citations. Pick the first supporting ref's source as the canonical
    # bibliographic anchor (matches how the thesis was built); fall
    # back to ref=1 if supporting_refs is empty.
    bib_source: dict | None = None
    for ref_id in supporting_refs or [1]:
        item = items_by_ref.get(ref_id)
        if isinstance(item, dict):
            src = item.get("source")
            if isinstance(src, dict):
                bib_source = src
                break

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
        endpoints=endpoints,
        endpoint_directions=endpoint_directions,
        population_summary=_detect_population_summary(
            thesis_text, items_by_ref, directness=directness,
        ),
        source_title=bib_source.get("title") if bib_source else None,
        source_year=bib_source.get("year") if bib_source else None,
        source_doi=bib_source.get("doi") if bib_source else None,
        source_pmid=bib_source.get("pmid") if bib_source else None,
        source_venue=bib_source.get("venue") if bib_source else None,
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
    # Day 10.17 Phase 2 — mechanism_vs_clinical is severity 3 (same as
    # indirectness_gap): both are "direct evidence vs mechanistic
    # evidence — synthesis must keep them separate." The cross-class
    # variant is the cross-domain version of the same trust hazard.
    "mechanism_vs_clinical": 3,
    "null_vs_positive": 4,
    "null_vs_negative": 4,
    "disagreement": 5,
}


def _tension_summary(
    kind: TensionKind,
    a: ReceiptSummary,
    b: ReceiptSummary,
    *,
    endpoint: str | None = None,
    direction_a: EffectDirection | None = None,
    direction_b: EffectDirection | None = None,
) -> str:
    """One-line deterministic description of the tension. The synthesis
    writer can cite this verbatim in the Tensions section."""
    if kind == "orthogonal":
        if a.outcome_class == b.outcome_class:
            return (
                f"{a.receipt_id} and {b.receipt_id} share the broad "
                f"{a.outcome_class} class but no comparable endpoint-level "
                "direction — no logical conflict"
            )
        return (
            f"{a.receipt_id} ({a.outcome_class}) and {b.receipt_id} "
            f"({b.outcome_class}) cover different outcome classes — no logical conflict"
        )
    if kind == "agreement":
        return (
            f"{a.receipt_id} and {b.receipt_id} both report "
            f"{direction_a} effect on {endpoint}"
        )
    if kind == "disagreement":
        return (
            f"{a.receipt_id} reports {direction_a} effect on {endpoint}; "
            f"{b.receipt_id} reports {direction_b} on the same endpoint "
            "— opposite reported directions; intervention and comparator alignment must be checked"
        )
    if kind in ("null_vs_positive", "null_vs_negative"):
        signed = a if direction_a != "null" else b
        nullish = b if direction_a != "null" else a
        signed_direction = direction_a if direction_a != "null" else direction_b
        return (
            f"{signed.receipt_id} ({signed_direction} on {endpoint}) vs "
            f"{nullish.receipt_id} (null on {endpoint}) — different reported directions; intervention and comparator alignment must be checked"
        )
    if kind == "indirectness_gap":
        direct_one = a if a.directness == "direct" else b
        other = b if a.directness == "direct" else a
        return (
            f"{direct_one.receipt_id} (direct, {direct_one.evidence_tier}) "
            f"vs {other.receipt_id} ({other.directness}) on "
            f"{a.outcome_class} — direct vs indirect must be kept separate"
        )
    if kind == "mechanism_vs_clinical":
        direct_one = a if a.directness == "direct" else b
        other = b if a.directness == "direct" else a
        return (
            f"{direct_one.receipt_id} (direct, {direct_one.outcome_class}) "
            f"vs {other.receipt_id} ({other.directness}, "
            f"{other.outcome_class}) — cross-domain: clinical evidence "
            f"on one outcome must not be fused with mechanistic / "
            f"preclinical evidence on a different outcome"
        )
    return f"{a.receipt_id} vs {b.receipt_id}"


def _classify_pair(a: ReceiptSummary, b: ReceiptSummary) -> Tension:
    """Classify domain and directness gaps before shared-endpoint direction comparisons; use the fixed severity table."""
    same_outcome = a.outcome_class == b.outcome_class
    endpoint: str | None = None
    direction_a: EffectDirection | None = None
    direction_b: EffectDirection | None = None

    a_direct = a.directness == "direct"
    b_direct = b.directness == "direct"
    # Day 10.17 Phase 2 review: use `not direct` rather than an
    # explicit list of non-direct values. This fail-closed predicate
    # captures "mechanistic", "indirect", AND any malformed empty/
    # unknown directness so a future receipt with `directness=""`
    # can't silently re-bury the cross-domain trust hazard.
    a_non_direct = not a_direct
    b_non_direct = not b_direct

    if not same_outcome:
        if (a_direct and b_non_direct) or (b_direct and a_non_direct):
            kind: TensionKind = "mechanism_vs_clinical"
        else:
            kind = "orthogonal"
    else:
        # Same outcome class — now decide by directness + direction.
        # Day 10.17 Phase 2 review: same-outcome indirectness_gap now
        # uses the same `not direct` predicate as the cross-outcome
        # mechanism_vs_clinical rule above. Resolves an asymmetry the
        # reviewer flagged (cross-outcome direct+indirect was severity
        # 3 but same-outcome direct+indirect was severity 0).
        # Indirect comparisons do not establish agreement or conflict on the
        # target intervention merely because endpoint names and signs match.
        # Direct-versus-indirect evidence remains a separate role contrast.
        comparable = a_direct and b_direct
        if (a_direct and b_non_direct) or (b_direct and a_non_direct):
            kind = "indirectness_gap"
        else:
            map_a = endpoint_direction_map(
                a.endpoint_directions, a.endpoints, a.effect_direction,
            )
            map_b = endpoint_direction_map(
                b.endpoint_directions, b.endpoints, b.effect_direction,
            )
            candidates: list[
                tuple[int, str, TensionKind, EffectDirection, EffectDirection]
            ] = []
            for shared_endpoint in sorted(map_a.keys() & map_b.keys()):
                candidate_a = map_a[shared_endpoint]
                candidate_b = map_b[shared_endpoint]
                candidate_kind = directional_kind(candidate_a, candidate_b)
                if (
                    candidate_kind in {"null_vs_positive", "null_vs_negative", "disagreement", "agreement"}
                    and not comparable
                ):
                    continue
                if candidate_kind != "orthogonal":
                    candidates.append((
                        -_SEVERITY[candidate_kind], shared_endpoint,
                        candidate_kind, candidate_a, candidate_b,
                    ))
            if candidates:
                _, endpoint, kind, direction_a, direction_b = min(candidates)
            else:
                kind = "orthogonal"

    return Tension(
        receipt_a_id=a.receipt_id,
        receipt_b_id=b.receipt_id,
        kind=kind,
        outcome_class=a.outcome_class if same_outcome else a.outcome_class,
        summary=_tension_summary(
            kind, a, b, endpoint=endpoint,
            direction_a=direction_a, direction_b=direction_b,
        ),
        severity=_SEVERITY[kind],
        endpoint=endpoint,
    )


def build_tension_matrix(
    summaries: Sequence[ReceiptSummary],
) -> TensionMatrix:
    """Classify all canonical receipt pairs deterministically; zero or one receipt yields an empty matrix."""
    sorted_summaries = sorted(summaries, key=lambda s: s.receipt_id)
    pairs: list[Tension] = []
    for i, a in enumerate(sorted_summaries):
        for b in sorted_summaries[i + 1:]:
            pairs.append(_classify_pair(a, b))
    return TensionMatrix(
        receipts=tuple(sorted_summaries),
        pairs=tuple(pairs),
    )
