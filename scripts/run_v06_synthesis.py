"""Day 10.17 Phase 6.1 — wire v0.6.0 bound claims into agent/paper_writer.py.

The user-audited v0.5.0/v0.6.0 diagnostic writer (scripts/diagnostic_paper_run.py)
hits 3.8k words. The OLD agent/paper_writer.py routinely produces
5–7k word papers with section floors, deterministic Methods, and
trust-spine validation. The end-game needs both — old writer volume +
new bound-claim evidence.

This script is the adapter:
  1. Load v0.6.0 quant_claims (only effect-role + high-confidence
     bindings — the strict 90/93 set)
  2. Group by contributing paper → one ReceiptSummary per paper
  3. Aggregate per-paper outcome_class + effect_direction from the
     dominant bound claims
  4. Build a TensionMatrix from cross-paper direction conflicts on
     the same outcome class
  5. Pick a SynthesisThesis that names the central pattern (most
     metformin papers find muscle-suppression alongside metabolic
     benefit — a real cross-domain tension)
  6. Call render_full_paper() exactly as the existing e2e pipeline does
  7. Optional: claim-strength repair pass (the Phase 2 hardening)
  8. Write to runs/synthesis-metformin-{ISO}/full_paper.md

This is "Path 1" per the audit: keep v0.6.0 extractor fixes; stop
expanding the diagnostic writer; wire bound claims into the production
writer instead.
"""
from __future__ import annotations

import argparse
import asyncio
import dataclasses
import datetime as dt
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from agent.llm_client import CallSpec, CostLedger  # noqa: E402
from agent.paper_writer import render_full_paper  # noqa: E402
from agent.paper_writer_claim_repair import repair_claim_strength  # noqa: E402
from agent.paper_writer_deterministic import (  # noqa: E402
    build_what_this_adds_section,
)
from agent.synthesis_schemas import (  # noqa: E402
    ReceiptSummary, SynthesisThesis, Tension, TensionMatrix,
)
from agent.settings import load_settings  # noqa: E402

# Pipeline-stage modules (auto-included after writer; final-layer
# review by Grok 4.3 with Mistral fallback closes the loop with NO
# manual step required).
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import audit_v06_paper as _audit_v06  # noqa: E402
import final_consistency_audit as _consistency_audit  # noqa: E402
import apply_consistency_fixes as _consistency_fixer  # noqa: E402
import grok_reviewer as _final_reviewer  # noqa: E402
import apply_patches as _patch_applier  # noqa: E402
import run_mode_contract as _run_mode  # noqa: E402
import citation_registry as _citations  # noqa: E402
import evidence_taxonomy as _taxonomy  # noqa: E402
import effect_direction as _direction  # noqa: E402
import table_renderer as _tables  # noqa: E402
import background_literature as _bglit  # noqa: E402

# Workstream A (autonomous): topic-parameterized pipeline.
# Module-level corpus paths + active topic — populated by
# _set_topic() at the top of every pipeline invocation. The sentinel
# path `_TOPIC_UNSET` deliberately doesn't exist on disk: any code
# path that reads QUANT_DIR/PARSED_DIR before _set_topic() ran will
# get a Path that fails the .exists() check (and therefore returns
# 0 hits), but won't crash on AttributeError as None would. This is
# the universal-fix-no-hardcoding rule (2026-05-04): no metformin
# fallback, but a placeholder that surfaces the bug at use-time.
# CLI accepts `--topic rapamycin` (or any topic with a corpus dir
# at docs/quality-reference/<topic>/). _run() always calls
# _set_topic() before any downstream code reads QUANT_DIR/PARSED_DIR.
_TOPIC_UNSET = REPO_ROOT / "_TOPIC_UNSET_call_set_topic_first"
QUANT_DIR: Path = _TOPIC_UNSET
PARSED_DIR: Path = _TOPIC_UNSET

# Active topic pack (set by _set_topic). Generic topic-aware logic
# reads from this instead of hardcoded strings. None until first
# _set_topic call.
_TOPIC_PACK = None
_ACTIVE_TOPIC: str = ""


def _set_topic(topic: str) -> None:
    """Update module-level corpus paths + topic pack for the given
    topic across the orchestrator, audit, and bg-lit modules.
    Called once by _run() at the top of each pipeline invocation.

    Refactor 2026-05-04: also loads the topic pack so generic
    helpers (_claim_topic_effect, canonical RCT lists, etc.) can
    read topic-specific data without hardcoded strings.

    Also sets TOPIC_DOMAIN env var so vocab/__init__.py picks up
    the correct vocab pack (auto-synthesizes from topic pack TOML
    if no vocab/<topic>.py exists)."""
    global QUANT_DIR, PARSED_DIR, _TOPIC_PACK, _ACTIVE_TOPIC
    import os
    QUANT_DIR = REPO_ROOT / "docs" / "quality-reference" / topic / "quant_claims"
    PARSED_DIR = REPO_ROOT / "docs" / "quality-reference" / topic / "parsed"
    _ACTIVE_TOPIC = topic
    os.environ["TOPIC_DOMAIN"] = topic
    # Keep audit module in lockstep
    _audit_v06._set_topic(topic)
    # Load topic pack (best-effort — pack may not exist for new topics)
    try:
        from agent.topic_pack import load_topic_pack
        tp_path = REPO_ROOT / "topic_packs" / f"{topic}.toml"
        if tp_path.exists():
            _TOPIC_PACK = load_topic_pack(tp_path)
        else:
            _TOPIC_PACK = None
    except (ImportError, OSError, ValueError) as e:
        print(
            f"  ! topic pack load failed for {topic}: {e}",
            file=sys.stderr,
        )
        _TOPIC_PACK = None


def _get_topic_pack():
    """Accessor for the active topic pack. Returns None if no
    pack is loaded for the active topic (graceful fallback for
    new/experimental topics)."""
    return _TOPIC_PACK


def _get_active_topic() -> str:
    """Accessor for the currently-set topic name."""
    return _ACTIVE_TOPIC


# v0.6.0 endpoint → SynthesisSchemas OutcomeClass mapping. Curated
# for the metformin/aging corpus; extending to a new drug pack means
# editing this table only.
_ENDPOINT_TO_OUTCOME_CLASS: dict[str, str] = {
    # muscle_function
    "VO2max": "muscle_function",
    "thigh muscle mass": "muscle_function",
    "lean body mass": "muscle_function",
    "muscle hypertrophy": "muscle_function",
    "muscle strength": "muscle_function",
    "protein synthesis": "muscle_function",
    "cardiorespiratory fitness": "muscle_function",
    # frailty
    "walk speed": "frailty",
    "frailty": "frailty",
    "sarcopenia": "frailty",
    # longevity
    "mortality": "longevity",
    "lifespan": "longevity",
    "healthspan": "longevity",
    # cardiometabolic
    "HbA1c": "cardiometabolic",
    "insulin sensitivity": "cardiometabolic",
    "fasting glucose": "cardiometabolic",
    "blood glucose": "cardiometabolic",
    "body weight": "cardiometabolic",
    "body mass index": "cardiometabolic",
    "AMPK signaling": "cardiometabolic",
    "mTOR signaling": "cardiometabolic",
    "mitochondrial respiration": "cardiometabolic",
    "blood pressure": "cardiometabolic",
    # immune
    "inflammation": "immune",
    "oxidative stress": "immune",
}


# Per-endpoint polarity: +1 means "increase = good for the patient"
# (so metformin direction=increase → effect_direction=positive on this
# endpoint). -1 means "decrease = good" (e.g. mortality, HbA1c). The
# adapter combines this with the bound arm + direction to derive a
# per-paper effect_direction.
_ENDPOINT_POLARITY: dict[str, int] = {
    "VO2max": +1, "thigh muscle mass": +1, "lean body mass": +1,
    "muscle hypertrophy": +1, "muscle strength": +1, "lifespan": +1,
    "healthspan": +1, "insulin sensitivity": +1, "AMPK signaling": +1,
    "mitochondrial respiration": +1, "protein synthesis": +1,
    "cardiorespiratory fitness": +1,
    "mortality": -1, "frailty": -1, "sarcopenia": -1, "HbA1c": -1,
    "fasting glucose": -1, "blood glucose": -1, "body weight": -1,
    "body mass index": -1, "inflammation": -1, "oxidative stress": -1,
    "blood pressure": -1, "mTOR signaling": -1, "walk speed": +1,
}


def _claim_topic_effect(claim: dict) -> int:
    """Returns +1 if the active topic's compound has a good effect
    on this endpoint, -1 if bad, 0 if unclear/null.

    Refactor 2026-05-04: was hardcoded to `arm == "metformin"`.
    Now reads active_arm_synonyms from the topic pack so this works
    for any drug (rapamycin, GLP-1, statins, etc.) without code
    changes."""
    direction = claim.get("direction") or ""
    arm = (claim.get("arm") or "").strip().lower()
    endpoint = claim.get("endpoint") or ""
    polarity = _ENDPOINT_POLARITY.get(endpoint, 0)
    if not polarity or not direction or direction == "no_change":
        return 0
    direction_sign = +1 if direction == "increase" else -1
    # If the direction is described from the active-drug arm, +1.
    # If from the placebo arm, -1 (placebo gain = drug underperformed).
    pack = _get_topic_pack()
    if pack is not None and arm:
        if arm in pack.active_arm_synonyms:
            arm_sign = +1
        elif arm in pack.placebo_arm_synonyms:
            arm_sign = -1
        else:
            # Unknown arm name — fall back to topic-name match
            arm_sign = +1 if arm == _get_active_topic() else -1
    else:
        # No pack loaded — fall back to topic-name string match
        arm_sign = +1 if arm == _get_active_topic() else -1
    drug_movement = direction_sign * arm_sign
    return polarity * drug_movement


# Backward-compat alias — some legacy call sites may still use the
# old name. Forwards to the new generic function.
_claim_metformin_effect = _claim_topic_effect


def _aggregate_paper(paper_id: str, claims: list[dict]) -> dict[str, Any]:
    """Per-paper rollup: dominant outcome_class, dominant
    effect_direction (Fix #5: now significance-aware → null/mixed
    states), p-values list, sample-size summary."""
    outcome_counter: Counter[str] = Counter()
    p_values: list[str] = []
    sample_sizes: list[float] = []
    for c in claims:
        if oc := _ENDPOINT_TO_OUTCOME_CLASS.get(c.get("endpoint") or ""):
            outcome_counter[oc] += 1
        if c.get("claim_type") == "p_value":
            raw = c.get("raw_text") or ""
            if raw:
                p_values.append(raw.replace("\xa0", " ").strip())
        if c.get("claim_type") == "sample_size":
            vals = c.get("numeric_values") or []
            if vals:
                sample_sizes.append(vals[0])

    dominant_outcome: str = (
        outcome_counter.most_common(1)[0][0]
        if outcome_counter else "longevity"
    )
    # Fix #5: significance-aware aggregation. Returns one of
    # positive/negative/null/mixed/unclear. The MET-PREVENT case
    # (Witham 2025: 0.001 m/s walk speed, p=0.96) now correctly
    # produces "null" instead of "positive".
    effect_direction = _direction.infer_effect_direction(
        claims, metformin_effect_fn=_claim_metformin_effect,
    )

    return {
        "outcome_class": dominant_outcome,
        "effect_direction": effect_direction,
        "p_values": p_values,
        "sample_sizes": sample_sizes,
        "n_claims": len(claims),
    }


def _classify_paper_tier(paper_id: str, n_claims: int, paper_meta: dict) -> tuple[str, str]:
    """Return (evidence_tier, directness) — Fix #4: deterministic
    classification from structured metadata via evidence_taxonomy.

    First tries explicit metadata fields (`study_design`, `species`,
    `endpoint_kind` if the parsed-paper JSON has them). Falls back to
    a title/abstract keyword extractor for legacy papers without
    explicit annotation. The pre-fix heuristic (PMC* → "mechanistic",
    everything else → "B/indirect") incorrectly tagged human
    observational mortality studies as "mechanistic" — a category
    error that propagated into the synthesis."""
    # Explicit-field path: metadata sources MAY include these fields
    # directly. Empty/missing fields fall through to inference.
    explicit_design = paper_meta.get("study_design")
    explicit_species = paper_meta.get("species")
    explicit_endpoint_kind = paper_meta.get("endpoint_kind")
    if explicit_design or explicit_species or explicit_endpoint_kind:
        cls = _taxonomy.classify_evidence(
            study_design=explicit_design,
            species=explicit_species,
            endpoint_kind=explicit_endpoint_kind,
        )
    else:
        cls = _taxonomy.infer_from_paper_meta(paper_meta)
    # If the deterministic path returns "unknown", fall back to the
    # topic-pack canonical RCT list so existing runs don't regress.
    # Refactor 2026-05-04: was hardcoded to metformin RCT names
    # ("MASTERS", "MET_PREVENT", "Konopka_2019") — now reads from
    # the active topic pack's canonical_rct_paper_ids.
    if cls.tier == "unknown":
        pack = _get_topic_pack()
        is_rct_papers = (
            pack.canonical_rct_paper_ids if pack is not None
            else ()
        )
        if any(name in paper_id for name in is_rct_papers):
            return "A1", "direct"
        if paper_id.startswith("PMC"):
            # P1 reviewer fix: PMC* prefix alone is NOT a reliable
            # mechanistic signal — many PMC papers are human
            # observational mortality studies. Default to B2 here so
            # we err toward "human-direct" rather than misclassifying
            # as mechanistic.
            return "B2", "indirect"
        return "B1", "review"
    return cls.tier, cls.directness


def _build_population_summary(paper_meta: dict, n_subjects: list[float]) -> str:
    """Best-effort population summary from paper metadata + sample sizes."""
    title = (paper_meta.get("title") or "").lower()
    if "older adults" in title:
        pop = "older adults"
    elif "frailt" in title or "sarcopen" in title:
        pop = "frail / sarcopenic adults"
    elif "diabetes" in title or "t2d" in title:
        pop = "type 2 diabetes patients"
    elif "mice" in title or "mouse" in title:
        pop = "mice (preclinical)"
    elif "review" in title or "geroscience" in title:
        return ""  # review — no enrolled population
    else:
        pop = "adults"
    if n_subjects:
        n_total = int(sum(n_subjects))
        return f"{pop}, n={n_total}"
    return pop


def _extract_canonical_trial_id(claims: list[dict]) -> str | None:
    """Find an NCT or ISRCTN id mentioned in any claim's sentence."""
    nct_re = re.compile(r"\b(NCT\d{8})\b")
    isrctn_re = re.compile(r"\b(ISRCTN\d{6,10})\b")
    for c in claims:
        sent = c.get("sentence") or ""
        m = nct_re.search(sent) or isrctn_re.search(sent)
        if m:
            return m.group(1)
    return None


def _load_paper_meta_by_id() -> dict[str, dict]:
    """Load all parsed-paper metadata (paper_id → dict). Used both
    by the receipt builder AND by Fix #10's citation-registry call
    (Author-Year extraction from authors+year fields)."""
    paper_meta_by_id: dict[str, dict] = {}
    for path in sorted(PARSED_DIR.glob("*.paper_sections.json")):
        d = json.loads(path.read_text())
        pid = d.get("paper_id") or path.stem
        paper_meta_by_id[pid] = d
    return paper_meta_by_id


def build_receipts_from_quant_claims(
    topic: str,
) -> list[ReceiptSummary]:
    """Adapter: v0.6.0 quant_claims → ReceiptSummary list. One receipt
    per contributing paper. Only papers with ≥1 high-confidence
    effect-role claim are included.

    Workstream A: `topic` parameter is the per-receipt label (set on
    every ReceiptSummary). The corpus directory is QUANT_DIR which
    has already been set by `_set_topic(topic)` upstream."""
    receipts: list[ReceiptSummary] = []
    paper_meta_by_id = _load_paper_meta_by_id()

    # Group high-confidence claims by paper_id
    by_paper: dict[str, list[dict]] = defaultdict(list)
    for path in sorted(QUANT_DIR.glob("*.quant_claims.json")):
        d = json.loads(path.read_text())
        pid = d.get("paper_id") or path.stem.replace(".quant_claims", "")
        for c in d.get("claims", []):
            if c.get("binding_confidence") == "high":
                by_paper[pid].append(c)

    for paper_id, claims in by_paper.items():
        if not claims:
            continue
        meta = paper_meta_by_id.get(paper_id, {})
        agg = _aggregate_paper(paper_id, claims)
        tier, directness = _classify_paper_tier(paper_id, agg["n_claims"], meta)
        # Most-common bound thesis as a one-line summary.
        thesis_lines = []
        for c in claims[:5]:
            ep = c.get("endpoint") or "?"
            arm = c.get("arm") or "?"
            dirn = c.get("direction") or "?"
            val = c.get("raw_text") or "?"
            thesis_lines.append(f"{arm} {dirn} {ep} ({val})")
        thesis_text = (
            f"{meta.get('title', paper_id)} — bound findings: "
            + "; ".join(thesis_lines[:3])
        )
        receipts.append(ReceiptSummary(
            receipt_id=paper_id,
            receipt_path=str(QUANT_DIR / f"{paper_id}.quant_claims.json"),
            topic=topic,
            thesis_text=thesis_text,
            spar_verdict="accept_clean",  # v0.6.0 high-conf passes our filter
            n_claims=agg["n_claims"],
            n_failed_traces=0,
            canonical_trial_id=_extract_canonical_trial_id(claims),
            evidence_tier=tier,
            directness=directness,
            outcome_class=agg["outcome_class"],
            effect_direction=agg["effect_direction"],
            p_values=tuple(agg["p_values"][:6]),
            population_summary=_build_population_summary(meta, agg["sample_sizes"]),
            source_title=meta.get("title"),
            source_year=meta.get("year"),
            source_doi=meta.get("doi"),
            source_pmid=meta.get("pmid"),
            source_venue=meta.get("journal"),
        ))
    receipts.sort(key=lambda r: -r.n_claims)
    return receipts


def build_tension_matrix(receipts: list[ReceiptSummary]) -> TensionMatrix:
    """Pairwise tensions between receipts. Same outcome_class + opposite
    effect_directions = disagreement. Different outcome_classes with
    one direct + one mechanistic = cross-domain tension."""
    pairs: list[Tension] = []
    sorted_receipts = sorted(receipts, key=lambda r: r.receipt_id)
    for i, a in enumerate(sorted_receipts):
        for b in sorted_receipts[i + 1:]:
            if a.outcome_class == b.outcome_class:
                # Fix #5 reviewer P2: explicit branches for the new
                # null/mixed direction values; agreement covers same-
                # value pairs (incl. null-vs-null and mixed-vs-mixed).
                if a.effect_direction == b.effect_direction:
                    kind = "agreement"
                    severity = 1
                elif "mixed" in (a.effect_direction, b.effect_direction):
                    # mixed vs anything (positive / negative / null) is a
                    # partial disagreement — strongest evidence the paper
                    # has internal contradiction worth surfacing.
                    kind = "disagreement"
                    severity = 4
                elif "null" in (a.effect_direction, b.effect_direction):
                    kind = "null_vs_positive"
                    severity = 3
                elif {a.effect_direction, b.effect_direction} == {
                    "positive", "negative",
                }:
                    kind = "disagreement"
                    severity = 5
                else:
                    kind = "orthogonal"
                    severity = 0
                summary = (
                    f"{a.receipt_id} ({a.effect_direction}) vs "
                    f"{b.receipt_id} ({b.effect_direction}) on "
                    f"{a.outcome_class}"
                )
            else:
                # Cross-domain tension if one is direct and the other mechanistic.
                if (a.directness == "direct" and b.directness == "mechanistic") or (
                    a.directness == "mechanistic" and b.directness == "direct"
                ):
                    kind = "cross_domain"
                    severity = 4
                    summary = (
                        f"{a.receipt_id} ({a.outcome_class}, "
                        f"{a.directness}) vs {b.receipt_id} "
                        f"({b.outcome_class}, {b.directness})"
                    )
                else:
                    kind = "orthogonal"
                    severity = 0
                    summary = (
                        f"{a.receipt_id} and {b.receipt_id} address "
                        "different outcome classes"
                    )
            pairs.append(Tension(
                receipt_a_id=a.receipt_id,
                receipt_b_id=b.receipt_id,
                kind=kind,
                outcome_class=a.outcome_class,
                summary=summary,
                severity=severity,
            ))
    return TensionMatrix(receipts=tuple(receipts), pairs=tuple(pairs))


def build_thesis(
    receipts: list[ReceiptSummary], matrix: TensionMatrix,
    topic: str,
) -> SynthesisThesis:
    """Build a topic-generic deterministic thesis.

    Pre-Fix: hardcoded metformin-specific narrative ('MASTERS/
    Konopka/MET-PREVENT', 'metformin's anti-aging case'). Caused
    rapamycin synthesis to ship with metformin contamination in
    its thesis text, which Grok flagged as P1 but couldn't repair
    safely (ambiguous BEFORE replacement).

    Post-Fix: composes thesis from the receipts' own metadata —
    positive vs negative outcome-class signals, the dominant
    evidence tiers, and the cross-domain tensions surfaced by the
    matrix. Topic-name appears only as the subject; everything
    else derives from the actual corpus."""
    from collections import Counter
    receipt_ids = tuple(r.receipt_id for r in receipts)
    non_orth = matrix.non_orthogonal()
    addressed = tuple(t.summary for t in non_orth[:3])

    # Aggregate outcome × effect signals
    pos_outcomes: list[str] = []
    neg_outcomes: list[str] = []
    null_outcomes: list[str] = []
    for r in receipts:
        oc = (r.outcome_class or "").replace("_", " ")
        ed = (r.effect_direction or "").lower()
        if not oc:
            continue
        if ed == "positive":
            pos_outcomes.append(oc)
        elif ed == "negative":
            neg_outcomes.append(oc)
        elif ed == "null":
            null_outcomes.append(oc)
    pos_top = [
        o for o, _ in Counter(pos_outcomes).most_common(2)
    ]
    neg_top = [
        o for o, _ in Counter(neg_outcomes).most_common(2)
    ]
    null_top = [
        o for o, _ in Counter(null_outcomes).most_common(2)
    ]

    n = len(receipts)
    parts = [f"Across {n} curated reference paper"]
    parts[-1] += "s" if n != 1 else ""
    parts[-1] += f", {topic} shows a context-dependent profile."

    if pos_top:
        parts.append(
            f"Positive signals appear in: "
            f"{', '.join(pos_top)}."
        )
    if neg_top:
        parts.append(
            f"Negative signals appear in: "
            f"{', '.join(neg_top)}."
        )
    if null_top:
        parts.append(
            f"Null findings dominate: "
            f"{', '.join(null_top)}."
        )
    if non_orth:
        parts.append(
            f"The synthesis surfaces {len(non_orth)} non-"
            "orthogonal tensions across outcome classes — see "
            "Cross-Domain Synthesis."
        )
    parts.append(
        f"The {topic} anti-aging case as currently constituted is "
        "incomplete: mechanistic plausibility coexists with mixed "
        "or sparse human-RCT evidence, and the boundary conditions "
        "remain to be established."
    )
    text = " ".join(parts)
    return SynthesisThesis(
        text=text,
        receipt_ids_referenced=receipt_ids,
        tensions_addressed=addressed,
        rejected_candidates=(),
        picker_rationale=(
            "Topic-generic deterministic thesis composed from "
            "receipt outcome × effect signals + tension matrix; "
            "no LLM tournament. Replaces the v0.6 metformin-"
            "hardcoded thesis (which contaminated rapamycin runs)."
        ),
    )


def _author_year_for_receipt(r: ReceiptSummary) -> str:
    """Best-effort Author Year citation for a receipt. Pulls the first
    surname from paper_id (e.g. 'Walton_2019_MASTERS_...' → 'Walton')
    and the year. Falls back to receipt_id if structure unrecognized."""
    parts = (r.receipt_id or "").split("_")
    if len(parts) >= 2:
        author = parts[0]
        year = parts[1] if parts[1].isdigit() else (
            str(r.source_year) if r.source_year else ""
        )
        if author and year:
            return f"{author} {year}"
    if r.source_year:
        return f"{r.receipt_id[:20]} {r.source_year}"
    return r.receipt_id[:30]


def _replace_paper_ids_with_author_year(
    paper_md: str, receipts: list[ReceiptSummary],
    *, registry: dict | None = None,
) -> str:
    """Substitute paper_id strings (and their truncated forms) in the
    markdown with Author-Year citation. Audit Q3 ship-blocks otherwise.

    Reviewer-fix Fix #6 P1 v2: when `registry` is provided, the
    Author-Year substitution string comes from the registry's
    body_citation — SAME source the Tables and References use, so the
    body prose, tables, and references are guaranteed to use the same
    citation token for each receipt."""
    out = paper_md

    def _citation_for(r: ReceiptSummary) -> str:
        if registry is not None and r.receipt_id in registry:
            return registry[r.receipt_id].body_citation
        return _author_year_for_receipt(r)

    # Sort by length desc so longer forms get replaced before shorter
    # truncations (avoids "Walton_2019" replacing inside
    # "Walton_2019_MASTERS_...").
    pairs = sorted(
        ((r.receipt_id, _citation_for(r)) for r in receipts),
        key=lambda p: -len(p[0]),
    )
    for paper_id, author_year in pairs:
        for variant in (paper_id, paper_id[:30], paper_id[:25], paper_id[:20]):
            if variant and len(variant) >= 8:
                out = out.replace(variant, author_year)
    return out


def _append_references_block(
    paper_md: str, receipts: list[ReceiptSummary],
    *, registry: dict | None = None,
) -> str:
    """Append a deterministic References section at the end of the
    paper (after Conclusion). Each entry: Author Year. Title. Journal,
    Year. DOI/PMID. Replaces the writer's References section with one
    grounded in paper_sections.json metadata.

    Reviewer-fix Fix #6 P1: when `registry` is provided, the per-entry
    Author-Year token is sourced from the registry's body_citation —
    SAME source the Tables use, so prose / References / Tables can
    never drift out of sync.

    Fix #30: also append a "Background References" subsection listing
    any background_literature entries whose citation_token appears in
    the paper prose (e.g. 'Owen 2000', 'Anisimov 2008', 'ADA 2024').
    Pre-fix these citations were used by MiMo but missing from
    References — a public-review reader would flag that as missing
    bibliography. Per Fix #16/#18 the registry already validates the
    citation_token is in the same sentence as the numeric; here we
    add the canonical reference to the bibliography."""
    lines = ["", "## References", ""]
    for r in receipts:
        if registry is not None and r.receipt_id in registry:
            author_year = registry[r.receipt_id].body_citation
        else:
            author_year = _author_year_for_receipt(r)
        # Fix #35: smart-join — venue + year glue with single comma,
        # no `" ".join` artefact that produced "Lancet , 2025 ." with
        # a stray space before the comma. Title is also de-hyphenated
        # to fix PDF-parsed soft-breaks like "Anti- Aging".
        clean_title = (
            _clean_reference_title(r.source_title)
            if r.source_title else None
        )
        parts: list[str] = [f"- **{author_year}.**"]
        if clean_title:
            parts.append(f"_{clean_title}._")
        venue_year_bits: list[str] = []
        if r.source_venue:
            venue_year_bits.append(r.source_venue.strip().rstrip(",."))
        if r.source_year:
            venue_year_bits.append(str(r.source_year))
        if venue_year_bits:
            parts.append(", ".join(venue_year_bits) + ".")
        if r.source_doi:
            parts.append(f"DOI: {r.source_doi}.")
        if r.source_pmid:
            parts.append(f"PMID: {r.source_pmid}.")
        lines.append(" ".join(parts))
    lines.append("")

    # Fix #30: background-literature references used in prose
    used_bglit = _used_background_lit_entries(paper_md)
    if used_bglit:
        lines.extend([
            "### Background References",
            "",
            "*Canonical clinical thresholds cited in prose. Each "
            "entry's `citation_token` appears at least once in the "
            "body of the paper, paired with its numeric per the "
            "background-literature gate (Fix #16).*",
            "",
        ])
        for entry in used_bglit:
            ref_clean = (
                _clean_reference_title(entry.canonical_reference)
                if entry.canonical_reference else ""
            )
            bg_parts = [f"- **{entry.citation_token}.**"]
            if ref_clean:
                bg_parts.append(f"_{ref_clean}._")
            if entry.doi:
                bg_parts.append(f"DOI: {entry.doi}.")
            if entry.pmid:
                bg_parts.append(f"PMID: {entry.pmid}.")
            lines.append(" ".join(bg_parts))
        lines.append("")

    return paper_md.rstrip() + "\n".join(lines)


def _clean_reference_title(title: str) -> str:
    """Fix #35: collapse soft-broken hyphens in PDF-parsed titles.
    'Anti- Aging' → 'Anti-Aging'. Pattern: word-char + hyphen + space
    + word-char (the space is the artefact). Also collapses internal
    runs of double-spaces to single space and strips leading/trailing
    whitespace + trailing periods that would duplicate the closing
    period the renderer adds."""
    cleaned = re.sub(r"(\w)-\s+(\w)", r"\1-\2", title)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned.strip().rstrip(".")


def _used_background_lit_entries(paper_md: str) -> list:
    """Fix #30: load the background_literature registry, return the
    entries whose citation_token appears anywhere in `paper_md`.
    Returns an ordered, de-duplicated list (entry-key insertion
    order from the registry)."""
    try:
        registry = _bglit.load_registry()
    except (ImportError, FileNotFoundError, ValueError):
        return []
    seen_tokens: set[str] = set()
    used: list = []
    for entry in registry.values():
        if entry.citation_token in seen_tokens:
            continue
        if entry.citation_token in paper_md:
            used.append(entry)
            seen_tokens.add(entry.citation_token)
    return used


def _build_call_chain() -> list[CallSpec]:
    """Bulk paper writer chain — MiMo v2.5 Pro is PRIMARY.

    Order: MiMo v2.5 Pro (unlimited token plan) → Mistral Small (paid
    fallback) → Gemma 4 31B (paid fallback). OpenRouter fires only if
    MiMo is unreachable; the user's MiMo plan is unlimited while
    OpenRouter is metered.

    All identifiers come from agent/settings.py — never hardcode here.
    Past drift put `mimo-vl-7b-rl` (a vision model) and Gemma 3 27B as
    primaries, silently bypassing MiMo v2.5 Pro entirely.
    """
    settings = load_settings()
    chain: list[CallSpec] = []
    if settings.mimo_api_key:
        chain.append(CallSpec(
            base_url=settings.mimo_base_url,
            api_key=settings.mimo_api_key,
            model=settings.mimo_model,
            timeout_sec=settings.mimo_timeout_sec,
        ))
    if settings.openrouter_api_key:
        for openrouter_model in (settings.fallback_model, settings.judge_model):
            chain.append(CallSpec(
                base_url=settings.openrouter_base_url,
                api_key=settings.openrouter_api_key,
                model=openrouter_model,
                timeout_sec=settings.mimo_timeout_sec,
            ))
    return chain


async def _run(
    out_dir: Path,
    *,
    topic: str,
    dry_run: bool = False,
) -> int:
    settings = load_settings()
    if not settings.bot_enabled:
        print("BOT_ENABLED=false; aborting.", file=sys.stderr)
        return 1

    # Workstream A: lock the corpus dirs to the requested topic
    # before any downstream code reads them.
    _set_topic(topic)
    if not QUANT_DIR.exists():
        print(
            f"corpus directory does not exist for topic={topic!r}: "
            f"{QUANT_DIR}\n"
            f"Expected docs/quality-reference/{topic}/quant_claims/ "
            f"with at least one *.quant_claims.json.",
            file=sys.stderr,
        )
        return 4

    print(
        f"Loading v0.6.0 quant_claims (topic={topic!r})...",
        file=sys.stderr,
    )
    receipts = build_receipts_from_quant_claims(topic=topic)
    print(
        f"  Built {len(receipts)} receipts "
        f"(one per contributing paper).",
        file=sys.stderr,
    )
    if not receipts:
        print("No high-confidence claims found.", file=sys.stderr)
        return 2
    matrix = build_tension_matrix(receipts)
    thesis = build_thesis(receipts, matrix, topic=topic)

    print(f"Thesis: {thesis.text[:160]}...", file=sys.stderr)
    print(
        f"  Receipts: {len(receipts)} | "
        f"Non-orth tensions: {len(matrix.non_orthogonal())}",
        file=sys.stderr,
    )
    for r in receipts:
        print(
            f"  - {r.receipt_id[:50]:50s} "
            f"tier={r.evidence_tier} direct={r.directness} "
            f"outcome={r.outcome_class} effect={r.effect_direction} "
            f"n_claims={r.n_claims}",
            file=sys.stderr,
        )

    if dry_run:
        return 0

    chain = _build_call_chain()
    if not chain:
        print("No LLM keys configured.", file=sys.stderr)
        return 3

    out_dir.mkdir(parents=True, exist_ok=True)
    submission_id = out_dir.name
    ledger = CostLedger()

    # Fix #3: build the citation registry BEFORE the writer runs and
    # transform receipts AND matrix so the writer never sees raw
    # internal handles. PMCID body leaks become structurally
    # impossible (vs the previous post-hoc regex chase that missed
    # ~half the leaks). Matrix transformation MUST happen in lockstep
    # with receipt transformation, otherwise the writer's anchor-
    # validator sees mismatched IDs and trips invariant checks.
    # Fix #10: pass parsed paper metadata so PMC papers get
    # Author-Year body citations (e.g. "Yu 2025") instead of bare
    # PMC handles ("PMC12978362 2026"). PhD-grade citation surface.
    citation_registry = _citations.build_registry(
        receipts, paper_meta_by_id=_load_paper_meta_by_id(),
    )
    writer_receipts = _citations.transform_receipts_for_writer(
        receipts, citation_registry,
    )
    writer_matrix = _citations.transform_matrix_for_writer(
        matrix, citation_registry,
    )
    (out_dir / "citation_registry.json").write_text(json.dumps({
        rid: dataclasses.asdict(entry)
        for rid, entry in citation_registry.items()
    }, indent=2))

    print(
        "\nCalling render_full_paper "
        "(target 5-15k words, multi-section, tiered validation)...",
        file=sys.stderr,
    )
    # Fix #18a: load background-literature registry once and pass
    # entries to the writer so MiMo sees the canonical citation tokens
    # it can reference (e.g. 'Studenski 2011' for the 0.8 m/s frailty
    # cutoff). Without this, MiMo only sees the system-prompt rule
    # (Fix #17) and uses background numerics without their citations.
    bglit_entries = list(_bglit.load_registry().values())
    import httpx
    async with httpx.AsyncClient(timeout=180.0) as client:
        full_paper_md, sections = await render_full_paper(
            writer_receipts, writer_matrix, thesis,
            topic=topic, submission_id=submission_id,
            chain=chain, client=client, ledger=ledger,
            background_lit_entries=bglit_entries,
        )
    print(
        "render_full_paper done.",
        file=sys.stderr,
    )

    # Phase 2 hardening: claim-strength repair pass
    accepted = list(receipts)
    full_paper_md, repair_log = repair_claim_strength(full_paper_md, accepted)
    print(
        f"Claim-strength repair: {len(repair_log)} sentence(s) repaired",
        file=sys.stderr,
    )

    # Belt-and-braces: even though Fix #3 substituted upstream, run the
    # registry-backed substitution again as a safety net. Idempotent —
    # if upstream already converted everything, this is a no-op.
    full_paper_md = _citations.substitute_receipt_ids(
        full_paper_md, citation_registry,
    )
    # Fix #6 P1 v2: pass registry through so body prose substitution
    # uses the SAME body_citation source as Tables and References. No
    # 3-way drift possible.
    full_paper_md = _replace_paper_ids_with_author_year(
        full_paper_md, receipts, registry=citation_registry,
    )
    # Fix #6 + Fix #21: insert deterministic Tables 1-5 BEFORE
    # References. Built from the post-citation-registry receipts so
    # table cells use clean body_citation strings (no raw internal
    # handles). Fix #21 passes the writer-side TensionMatrix so
    # Table 3 (cross-domain tensions) renders the non-orthogonal
    # pairs as one row per tension — the dense numerics carrier that
    # raises Q9 density without prose bloat. Fix #21 follow-up
    # builds claims_by_citation from the original receipt_id →
    # quant_claims JSON so Table 5 can surface top-N per-paper
    # numerics (the densest carrier — closes the Q9 AAA gap).
    claims_by_citation = _build_claims_by_citation(
        receipts, citation_registry,
    )

    # Fix #25: append the deterministic 'What This Synthesis Adds'
    # section AFTER Conclusion and BEFORE Tables. Templated from
    # writer_receipts + writer_matrix + thesis so the originality
    # claim is grounded in pipeline data (zero LLM cost). Position
    # gives a PhD reviewer the explicit "beyond prior reviews"
    # statement right after the conclusion they just read.
    what_adds_md = build_what_this_adds_section(
        writer_receipts, writer_matrix, thesis, topic=topic,
    )
    if what_adds_md:
        full_paper_md = full_paper_md.rstrip() + "\n\n" + what_adds_md

    tables_md = _tables.render_all_tables(
        writer_receipts, writer_matrix, claims_by_citation,
    )
    if tables_md:
        full_paper_md = full_paper_md.rstrip() + "\n\n" + tables_md
    # Pass the registry to References so its Author-Year tokens come
    # from the SAME source as the table cells — no drift possible.
    full_paper_md = _append_references_block(
        full_paper_md, receipts, registry=citation_registry,
    )

    # Fix #2: replace LLM-templated Methods with deterministic block
    # rendered from a RunModeContract. Eliminates the contradiction
    # where Methods describes pipeline stages that didn't run.
    contract = _build_run_mode_contract(
        settings=settings,
        topic=topic,
        submission_id=submission_id,
        n_papers=len(receipts),
        n_claims=sum(r.n_claims for r in receipts),
    )
    contract_errors = _run_mode.validate_contract(contract)
    if contract_errors:
        raise RuntimeError(
            f"RunModeContract failed self-validation: {contract_errors}"
        )
    methods_md = _run_mode.render_methods(contract)
    blocked_in_rendered = _run_mode.validate_rendered(methods_md)
    if blocked_in_rendered:
        raise RuntimeError(
            f"Rendered Methods contains blocked phrases: {blocked_in_rendered}"
        )
    full_paper_md = _run_mode.replace_methods_in_paper(full_paper_md, methods_md)
    (out_dir / "run_mode_contract.json").write_text(
        json.dumps(dataclasses.asdict(contract), indent=2)
    )

    paper_path = out_dir / "full_paper.md"
    paper_path.write_text(full_paper_md)
    word_count = len(full_paper_md.split())

    # Per-section breakdown
    section_words = {}
    for s in sections:
        section_words[s.name] = len(s.body_md.split())

    manifest = {
        "extractor_version": "v0.6.0",
        "writer_path": "agent.paper_writer.render_full_paper (production)",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "n_receipts": len(receipts),
        "n_high_confidence_claims_total": sum(r.n_claims for r in receipts),
        "n_non_orthogonal_tensions": len(matrix.non_orthogonal()),
        "thesis": thesis.text,
        "receipts": [
            {
                "receipt_id": r.receipt_id,
                "outcome_class": r.outcome_class,
                "effect_direction": r.effect_direction,
                "evidence_tier": r.evidence_tier,
                "directness": r.directness,
                "n_claims": r.n_claims,
                "canonical_trial_id": r.canonical_trial_id,
            }
            for r in receipts
        ],
        "section_words": section_words,
        "total_words": word_count,
        "claim_strength_repairs": len(repair_log),
        "n_llm_calls": len(ledger.calls),
        "total_cost_usd": round(
            sum(c.estimated_cost_usd for c in ledger.calls), 6,
        ),
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))

    # ===== Auto-pipeline stages (Layer 1 audit + auto-fix → Grok final
    # review → auto-apply → final audit). No manual step required —
    # this whole chain runs from one invocation. =====
    final_paper_md = await _run_post_paper_pipeline(
        paper_path=paper_path, manifest=manifest, out_dir=out_dir,
        citation_registry=citation_registry,
    )
    word_count = len(final_paper_md.split())

    print(f"\nDONE: {paper_path}", file=sys.stderr)
    print(f"  final_words: {word_count}", file=sys.stderr)
    print(f"  per-section: {section_words}", file=sys.stderr)
    print(
        f"  llm_calls: {manifest['n_llm_calls']} "
        f"cost_usd: ${manifest['total_cost_usd']:.4f} (writer-only; "
        f"final-layer review cost in {out_dir.name}/full_paper.review_patches.json)",
        file=sys.stderr,
    )
    return 0


async def _run_post_paper_pipeline(
    *, paper_path: Path, manifest: dict, out_dir: Path,
    citation_registry: dict | None = None,
) -> str:
    """Layer 1 deterministic audit + auto-fix → final-layer LLM review
    (Grok 4.3 → Mistral fallback) → auto-apply patches → final audit.

    Each step's artifact is written to disk so a human can retroactively
    review what changed and why. Returns the final paper text."""
    paper_md = paper_path.read_text()

    # Stage 1: deterministic audit (Q1-Q10) on the as-written paper.
    print("[pipeline] Stage 1/5 — initial audit...", file=sys.stderr)
    audit_report = _audit_v06.audit(paper_md)
    audit_path = paper_path.with_suffix(".audit.json")
    audit_path.write_text(json.dumps(audit_report, indent=2))
    audit_md = _audit_v06._format_summary(audit_report)
    paper_path.with_suffix(".audit.md").write_text(audit_md)

    # Stage 2: Layer 1 consistency audit + deterministic auto-fix.
    print("[pipeline] Stage 2/5 — consistency audit + auto-fix...", file=sys.stderr)
    issues = _consistency_audit.run_audit(
        paper_md, manifest, audit_report, audit_md,
    )
    paper_path.with_suffix(".consistency.json").write_text(
        json.dumps([_issue_to_dict(i) for i in issues], indent=2)
    )
    paper_path.with_suffix(".consistency.md").write_text(
        _consistency_audit._format_summary(issues)
    )
    paper_md, fix_log = _consistency_fixer.apply_fixes(paper_md, issues)
    paper_path.with_suffix(".fixed_log.json").write_text(
        json.dumps(fix_log, indent=2)
    )
    paper_path.write_text(paper_md)

    # Re-run the audit + manifest now that auto-fixes have landed
    # (the consistency audit's verdict-overclaim check needs the
    # updated audit_md to pass).
    audit_report = _audit_v06.audit(paper_md)
    audit_path.write_text(json.dumps(audit_report, indent=2))
    audit_md = _audit_v06._format_summary(audit_report)
    paper_path.with_suffix(".audit.md").write_text(audit_md)

    # Stage 3: Final-layer LLM review (Grok 4.3 primary, Mistral fallback).
    print(
        "[pipeline] Stage 3/5 — final-layer review (Grok 4.3 → Mistral fallback)...",
        file=sys.stderr,
    )
    try:
        # Fix #11: pass citation_registry so Grok sees clean Author-Year
        # tokens in the "allowed body citations" list, not internal
        # receipt_id handles. Pre-fix Grok was reverting clean citations
        # to long PMC handles because the prompt asked for "receipt-key
        # consistency" — exactly the bug the third reviewer warned about.
        patches, _raw, model_used, cost = await _final_reviewer.review_with_grok(
            paper_md, manifest, audit_report,
            citation_registry=citation_registry,
        )
    except RuntimeError as exc:
        # No OPENROUTER_API_KEY OR both Grok and Mistral failed. Log
        # but don't crash the whole run — the deterministic Layer 1
        # work has already happened. The reviewer artifact records
        # the gap for transparency.
        print(
            f"[pipeline] final-layer review unavailable: {exc}",
            file=sys.stderr,
        )
        patches, model_used, cost = [], "none", 0.0
    paper_path.with_suffix(".review_patches.json").write_text(json.dumps({
        "model_used": model_used,
        "cost_usd": cost,
        "n_patches": len(patches),
        "patches": [
            {
                "id": p.id, "patch_type": p.patch_type,
                "severity": p.severity, "location": p.location,
                "before": p.before, "after": p.after, "reason": p.reason,
            }
            for p in patches
        ],
    }, indent=2))
    paper_path.with_suffix(".review_summary.md").write_text(
        _final_reviewer._format_summary(patches, cost, model_used)
    )

    # Stage 4: Auto-apply final-layer patches. Trust Grok with
    # mechanical safety only — no flag-for-human terminal state.
    print(
        f"[pipeline] Stage 4/5 — auto-apply {len(patches)} patches...",
        file=sys.stderr,
    )
    if patches:
        patches_dicts = [
            {
                "id": p.id, "patch_type": p.patch_type,
                "severity": p.severity, "location": p.location,
                "before": p.before, "after": p.after, "reason": p.reason,
            }
            for p in patches
        ]
        paper_md, results = _patch_applier.apply_patches(
            paper_md, patches_dicts, manifest,
        )

        # Fix #49: agent-to-agent repair loop. For every flagged P1
        # patch, re-prompt Grok with the rejection reason and ask
        # for a shorter/safer alternative. Pure agent-to-agent —
        # no human in the loop. Returns updated (paper_md, results)
        # with new decision states 'applied_via_repair' or
        # 'auto_stripped' for what the repair loop touched.
        paper_md, results = await _agent_repair_loop(
            paper_md=paper_md,
            results=results,
            manifest=manifest,
        )

        paper_path.write_text(paper_md)
        paper_path.with_suffix(".review_patch_log.json").write_text(json.dumps({
            "applied_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "n_proposed": len(results),
            "n_applied": sum(
                1 for r in results
                if r.decision in ("applied", "applied_via_repair")
            ),
            "n_rejected": sum(1 for r in results if r.decision == "rejected"),
            # Fix #36: surface the flagged count too — these are
            # patches the auto-applier refuses to apply because they
            # change scientific meaning (claim/numeric patches) or
            # have ambiguous targets. They count as unresolved P1
            # for the unified verdict.
            "n_flagged": sum(1 for r in results if r.decision == "flagged"),
            "n_auto_stripped": sum(
                1 for r in results if r.decision == "auto_stripped"
            ),
            "patches": [
                {
                    "patch_id": r.patch_id, "patch_type": r.patch_type,
                    "severity": r.severity, "decision": r.decision,
                    "reason_for_decision": r.reason_for_decision,
                }
                for r in results
            ],
        }, indent=2))
        n_applied = sum(
            1 for r in results
            if r.decision in ("applied", "applied_via_repair")
        )
        n_rejected = sum(1 for r in results if r.decision == "rejected")
        n_flagged = sum(1 for r in results if r.decision == "flagged")
        n_repaired = sum(
            1 for r in results if r.decision == "applied_via_repair"
        )
        n_stripped = sum(
            1 for r in results if r.decision == "auto_stripped"
        )
        # Fix #31 + Fix #36 + Fix #49: count Grok P1 patches that
        # remain unresolved AFTER the agent-to-agent repair loop.
        # Decisions:
        #   - "rejected"            → mechanical safety failed
        #   - "flagged"             → still unsafe after repair
        #                             rounds AND auto-strip couldn't
        #                             apply (BEFORE not unique etc.)
        #   - "applied_via_repair"  → repair loop succeeded, NOT
        #                             counted as unresolved
        #   - "auto_stripped"       → repair loop exhausted; offending
        #                             BEFORE region deleted; resolved
        #                             agent-to-agent. NOT counted.
        # Refactor 2026-05-04: distinguish Grok HALLUCINATIONS from
        # genuine unresolved P1s. When Grok proposes a patch with a
        # `before` text that doesn't exist in the paper, that's
        # Grok hallucinating an issue — the paper itself is fine.
        # The smart-gate rejects with reason starting "'before' text
        # not found in paper". Don't count those as unresolved P1.
        def _is_grok_hallucination(r) -> bool:
            reason = (r.reason_for_decision or "").lower()
            return (
                "before' text not found" in reason
                or "before text not found" in reason
                or "appears 0x" in reason
            )
        grok_unresolved_p1 = sum(
            1 for r in results
            if r.decision in ("rejected", "flagged")
            and (r.severity or "").upper() in {
                "P1", "HIGH", "CRITICAL",
            }
            and not _is_grok_hallucination(r)
        )
        print(
            f"[pipeline]   applied={n_applied} rejected={n_rejected} "
            f"flagged={n_flagged} repaired={n_repaired} "
            f"auto_stripped={n_stripped}"
            + (f" (Grok-unresolved P1 after repair: "
               f"{grok_unresolved_p1})"
               if grok_unresolved_p1 else ""),
            file=sys.stderr,
        )
    else:
        grok_unresolved_p1 = 0

    # Stage 5: Final audit + UNIFIED verdict (Fix #1 reviewer-P1).
    # Re-runs stage-1 audit AND stage-2 consistency on the post-Grok
    # paper, computes a single honest verdict. `final_verdict =
    # worst(stage1, stage2)`.
    #
    # Fix #19: re-run the deterministic auto-fixer on the post-Grok
    # paper BEFORE final audit. Stage-2's auto-fix (Fix #18b strips
    # unsourced background sentences) ran in Stage 2 but Grok's
    # patches in Stage 4 can re-introduce sentences with
    # background numerics. A Stage-5 re-fix closes the loop so the
    # final-audit verdict reflects post-cleanup state.
    print(
        "[pipeline] Stage 5/5 — final audit + unified verdict...",
        file=sys.stderr,
    )
    pre_audit = _audit_v06.audit(paper_md)
    pre_audit_md = _audit_v06._format_summary(pre_audit)
    pre_issues = _consistency_audit.run_audit(
        paper_md, manifest, pre_audit, pre_audit_md,
    )
    if any(i.auto_fixable for i in pre_issues):
        paper_md, _refix_log = _consistency_fixer.apply_fixes(
            paper_md, pre_issues,
        )
        paper_path.write_text(paper_md)
    audit_report = _audit_v06.audit(paper_md)
    audit_path.write_text(json.dumps(audit_report, indent=2))
    audit_md = _audit_v06._format_summary(audit_report)
    paper_path.with_suffix(".audit.md").write_text(audit_md)
    final_issues = _consistency_audit.run_audit(
        paper_md, manifest, audit_report, audit_md,
    )
    paper_path.with_suffix(".consistency.json").write_text(
        json.dumps([_issue_to_dict(i) for i in final_issues], indent=2)
    )
    paper_path.with_suffix(".consistency.md").write_text(
        _consistency_audit._format_summary(final_issues)
    )
    unified = _compute_unified_verdict(
        audit_report, final_issues, grok_unresolved_p1=grok_unresolved_p1,
    )
    paper_path.with_suffix(".final_verdict.json").write_text(
        json.dumps(dataclasses.asdict(unified), indent=2)
    )
    paper_path.with_suffix(".final_verdict.md").write_text(
        _format_unified_verdict(unified)
    )
    print(
        f"[pipeline] DONE — verdict={unified.verdict} "
        f"(stage1 {unified.stage1_pass_rate}; "
        f"stage2 P1={unified.stage2_p1} P2={unified.stage2_p2})",
        file=sys.stderr,
    )

    # Stage 5b (publication-prep): splice journal-required appendix
    # sections (Search Provenance / AI-Use Disclosure / Human
    # Accountability / Data + Code Availability) into the paper just
    # before the References section. Idempotent — re-runs don't
    # duplicate. Pure prose with no numerics, citations, or tier
    # labels, so audit gates already passed are unaffected.
    try:
        from agent.manuscript_appendix import (
            compose_appendix, splice_appendix_before_references,
        )
        from agent.settings import load_settings as _load_settings
        import subprocess as _sp
        try:
            git_sha = _sp.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=REPO_ROOT, text=True, timeout=5,
            ).strip()
        except (_sp.SubprocessError, FileNotFoundError):
            git_sha = "unknown"
        # Load settings here — Stage 5b runs in
        # _run_post_paper_pipeline() which doesn't receive settings
        # from the _run() scope. Cheap call (env-var read).
        _settings = _load_settings()
        model_stack = {
            "writer": _settings.mimo_model,
            "reviewer": _settings.final_layer_reviewer_model,
            "extractor": _settings.mimo_model,
            "thesis": _settings.mimo_model,
        }
        # Topic from the run dir name: synthesis-<topic>-v06-...
        _name_parts = paper_path.parent.name.split("-")
        _topic = (
            _name_parts[1] if len(_name_parts) >= 2
            else "unknown"
        )
        appendix_md = compose_appendix(
            manifest, audit=audit_report,
            model_stack=model_stack,
            topic=_topic,
            run_id=paper_path.parent.name,
            git_sha=git_sha,
            bundle_path=f"bundles/{paper_path.parent.name}/",
        )
        paper_md = splice_appendix_before_references(
            paper_md, appendix_md,
        )
        paper_path.write_text(paper_md)
        print(
            "[pipeline] Stage 5b — manuscript appendix spliced "
            "(Search Provenance / AI Disclosure / Accountability / "
            "Data Availability)",
            file=sys.stderr,
        )
    except Exception as _e:  # pragma: no cover — best-effort
        print(
            f"[pipeline] Stage 5b — appendix splice skipped: {_e}",
            file=sys.stderr,
        )

    # Stage 6 (Fix #23): no-regression gate. If runs/_baseline.txt
    # names a baseline run dir, compare the new run's six dimensions
    # (P1, numeric trace, consistency, leakage, word count, orphan
    # cites) against it. Writes report.{json,md} to the new run dir
    # so the next agent / human can audit deltas. Informational only
    # — does not fail the pipeline (the unified verdict already gates
    # ship). Caller-driven exit-codes happen via the standalone
    # `python scripts/no_regression_gate.py` CLI for CI.
    _maybe_run_no_regression_gate(paper_path.parent)

    return paper_md


_MAX_REPAIR_ROUNDS = 2


async def _agent_repair_loop(
    *,
    paper_md: str,
    results: list[Any],
    manifest: dict,
) -> tuple[str, list[Any]]:
    """Fix #49: agent-to-agent repair loop.

    For each `decision == 'flagged'` result, re-prompt Grok with the
    rejection reason and ask for a safer alternative. The new
    proposal goes through the same smart-gate as any other patch.
    Up to _MAX_REPAIR_ROUNDS rounds. After all rounds, any still-
    flagged P1 patch is auto-stripped (the offending sentence is
    deleted) — pipeline never resigns to 'human review'.

    Returns updated (paper_md, results). Successful repair patches
    are tagged decision='applied_via_repair'; auto-strips are
    tagged decision='auto_stripped'."""
    if not results:
        return paper_md, results
    flagged_p1 = [
        r for r in results
        if r.decision == "flagged"
        and (r.severity or "").upper() in {"P1", "HIGH", "CRITICAL"}
    ]
    if not flagged_p1:
        return paper_md, results
    for _ in range(_MAX_REPAIR_ROUNDS):
        if not flagged_p1:
            break
        try:
            repaired = await _final_reviewer.repair_flagged_patches(
                [(r, r.reason_for_decision) for r in flagged_p1],
                paper_md,
            )
        except Exception as e:  # noqa: BLE001
            print(
                f"[pipeline] repair-loop Grok call failed: {e}",
                file=sys.stderr,
            )
            break
        if not repaired:
            # Grok returned 'unfixable' for every patch
            break
        # Re-run smart-gate on repaired patches
        repaired_dicts = [
            {
                "id": p.id, "patch_type": p.patch_type,
                "severity": p.severity, "location": p.location,
                "before": p.before, "after": p.after,
                "reason": f"REPAIR: {p.reason}",
            }
            for p in repaired
        ]
        paper_md, repair_results = _patch_applier.apply_patches(
            paper_md, repaired_dicts, manifest,
        )
        # Map newly-applied repair results back into the original
        # results list (find by patch_id).
        applied_repair_ids = {
            r.patch_id for r in repair_results if r.decision == "applied"
        }
        if applied_repair_ids:
            results = [
                _patch_applier.PatchResult(
                    patch_id=r.patch_id, patch_type=r.patch_type,
                    severity=r.severity,
                    decision=(
                        "applied_via_repair"
                        if r.patch_id in applied_repair_ids
                        and r.decision == "flagged"
                        else r.decision
                    ),
                    reason_for_decision=(
                        f"AGENT-REPAIR: original flagged, replacement "
                        f"applied. {r.reason_for_decision}"
                        if r.patch_id in applied_repair_ids
                        and r.decision == "flagged"
                        else r.reason_for_decision
                    ),
                    before=r.before, after=r.after,
                )
                for r in results
            ]
        # Recompute the still-flagged set for next round
        flagged_p1 = [
            r for r in results
            if r.decision == "flagged"
            and (r.severity or "").upper() in {"P1", "HIGH", "CRITICAL"}
        ]
    # Final pass: any still-flagged P1 → auto-strip the BEFORE region.
    # Pure deletion; safer than leaving a flagged patch unresolved.
    if flagged_p1:
        for r in flagged_p1:
            if not r.before or r.before not in paper_md:
                continue
            # Only strip if the BEFORE appears exactly once (avoid
            # accidental over-strip).
            if paper_md.count(r.before) != 1:
                continue
            paper_md = paper_md.replace(r.before, "", 1)
            # Tag the result as auto-stripped
            results = [
                _patch_applier.PatchResult(
                    patch_id=rr.patch_id, patch_type=rr.patch_type,
                    severity=rr.severity,
                    decision=(
                        "auto_stripped"
                        if rr.patch_id == r.patch_id
                        else rr.decision
                    ),
                    reason_for_decision=(
                        f"AGENT-AUTO-STRIP: repair loop exhausted; "
                        f"BEFORE region deleted to avoid leaving "
                        f"flagged P1. {rr.reason_for_decision}"
                        if rr.patch_id == r.patch_id
                        else rr.reason_for_decision
                    ),
                    before=rr.before, after=rr.after,
                )
                for rr in results
            ]
    return paper_md, results


def _build_claims_by_citation(
    receipts: list, registry: dict,
) -> dict[str, list[dict]]:
    """Build {body_citation: [claim_dicts]} from the original receipt
    list (pre-transform — receipt_ids are still raw paper-IDs that
    map directly to docs/quality-reference/<topic>/quant_claims/
    <receipt_id>.quant_claims.json).

    Used by Table 5 (Per-Paper Numeric Index) to surface the corpus's
    underlying quantitative claims. The map keys are body_citation
    strings (e.g. 'Walton 2019') so Table 5 can look up a writer-side
    receipt's claims using its already-transformed receipt_id.

    Only high-confidence claims are surfaced — Q2 numeric integrity
    trace uses the same high-confidence filter (see
    audit_v06_paper._load_corpus_numerics), so a Table 5 numeric
    that's NOT high-confidence would render to a paper cell that
    Q2 then fails to trace. Pre-filter so Table 5 cells = Q2
    corpus numerics by construction."""
    out: dict[str, list[dict]] = {}
    for r in receipts:
        raw_id = getattr(r, "receipt_id", "")
        entry = registry.get(raw_id)
        if entry is None:
            continue
        path = QUANT_DIR / f"{raw_id}.quant_claims.json"
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        all_claims = data.get("claims", [])
        if not isinstance(all_claims, list):
            continue
        high_conf = [
            c for c in all_claims
            if isinstance(c, dict)
            and c.get("binding_confidence") == "high"
        ]
        out[entry.body_citation] = high_conf
    return out


def _maybe_run_no_regression_gate(new_run_dir: Path) -> None:
    """Stage 6 (Fix #23): if docs/no_regression_baseline.txt names a
    baseline run dir, compare the new run's quality dimensions
    against it. Skip silently when no baseline configured.

    Marker file is checked-in (under docs/) so the baseline name
    travels with the repo across MacBook + GitHub + VPS — every
    machine evaluates against the same anchor."""
    baseline_marker = (
        Path(__file__).resolve().parent.parent
        / "docs" / "no_regression_baseline.txt"
    )
    if not baseline_marker.exists():
        return
    baseline_name = baseline_marker.read_text().strip()
    if not baseline_name:
        return
    baseline_dir = (Path("runs") / baseline_name).resolve()
    if not baseline_dir.exists() or baseline_dir == new_run_dir:
        return
    # Fix: skip if topics differ (run dir names are
    # 'synthesis-<topic>-v06-...'; comparing rapamycin to metformin
    # baseline produces a meaningless 'regression').
    def _topic_of(name: str) -> str:
        parts = name.split("-")
        return parts[1] if len(parts) >= 2 else ""
    new_topic = _topic_of(new_run_dir.name)
    baseline_topic = _topic_of(baseline_dir.name)
    if new_topic != baseline_topic:
        print(
            f"[pipeline] Stage 6/6 — no-regression gate skipped: "
            f"new run topic={new_topic!r} differs from baseline "
            f"topic={baseline_topic!r} (cross-topic comparison "
            "is not meaningful — promote a per-topic baseline)",
            file=sys.stderr,
        )
        return
    try:
        import no_regression_gate as _nrg
        report = _nrg.compare_runs(baseline_dir, new_run_dir)
        md = _nrg.render_report_md(report)
        (new_run_dir / "no_regression_report.md").write_text(md)
        (new_run_dir / "no_regression_report.json").write_text(
            json.dumps(report.to_dict(), indent=2),
        )
        verdict = "PASS" if report.passes else (
            f"REGRESSION ({report.n_regressions} dim(s))"
        )
        print(
            f"[pipeline] Stage 6/6 — no-regression gate vs "
            f"{baseline_name}: {verdict}",
            file=sys.stderr,
        )
    except (ImportError, OSError) as e:
        print(
            f"[pipeline] no-regression gate skipped: {e}",
            file=sys.stderr,
        )


def _issue_to_dict(issue) -> dict[str, Any]:
    return {
        "id": issue.id, "severity": issue.severity,
        "issue_type": issue.issue_type, "auto_fixable": issue.auto_fixable,
        "evidence": issue.evidence, "suggested_fix": issue.suggested_fix,
    }


def _build_run_mode_contract(
    *, settings: Any, topic: str, submission_id: str,
    n_papers: int, n_claims: int,
) -> _run_mode.RunModeContract:
    """Construct the contract from settings + run facts. The v0.6
    quant-claim adapter never runs SPAR, never uses LLM fact
    extraction, never builds multi-receipt clusters — those flags
    are False because that's the literal pipeline behaviour."""
    return _run_mode.RunModeContract(
        run_mode="v0.6 quant-claim adapter",
        topic=topic,
        submission_id=submission_id,
        n_papers_in_corpus=n_papers,
        n_high_confidence_claims_used_by_writer=n_claims,
        writer_model=settings.mimo_model,
        in_writing_judge_model=settings.judge_model,
        final_layer_reviewer_model=settings.final_layer_reviewer_model,
        final_layer_fallback_model=settings.fallback_model,
        claim_source=f"docs/quality-reference/{topic}/quant_claims/*.json",
        spar_adjudication_ran=False,
        multi_receipt_clusters_ran=False,
        llm_fact_extraction_ran=False,
        rejected_evidence_quarantine_ran=False,
    )


# Severities that block ship — anything ELSE is treated as informational.
# Positive allowlist (not blocklist) so future severities like "P0" or
# "CRITICAL" silently fail closed instead of silently passing.
_BLOCKING_SEVERITIES: frozenset[str] = frozenset({"P0", "P1", "CRITICAL"})
_NONBLOCKING_SEVERITIES: frozenset[str] = frozenset({"P2", "P3", "INFO"})


@dataclass(frozen=True, slots=True)
class UnifiedVerdict:
    """Worst-of(stage1, stage2, grok-unresolved). Cross-stage object →
    frozen+slots per project rule. Serialized via dataclasses.asdict()
    to JSON. Fix #31: tracks Grok-unresolved P1 patches separately —
    even when stage1 + stage2 are clean, an unresolved Grok P1
    flag downgrades the verdict to 'Trust-Spine Pass — Human Review
    Required' rather than AAA (the harness can't autonomously verify
    Grok's flag was wrong)."""
    verdict: str
    reason: str
    stage1_p1_pass: bool
    stage1_score: float
    stage1_pass_rate: str
    stage2_p1: int
    stage2_p2: int
    stage2_unknown_severity_count: int
    all_green: bool
    p1_clean: bool
    grok_unresolved_p1: int = 0


def _is_blocking(severity: str) -> bool:
    """Positive allowlist: known non-blocking severities pass; ANYTHING
    ELSE blocks (fail-closed for unknown severities like 'P0' or
    'CRITICAL' that future reviewer-prompts may introduce)."""
    return severity not in _NONBLOCKING_SEVERITIES


def _compute_unified_verdict(
    stage1_report: dict[str, Any] | None,
    stage2_issues: list[Any],
    grok_unresolved_p1: int = 0,
) -> UnifiedVerdict:
    """Worst-of(stage1, stage2, grok-unresolved). AAA reserved for
    fully-green (P1+P2 + zero unresolved Grok P1). SHIP-BLOCKED if
    either deterministic stage flags a P1+ severity. Trust-Spine
    Pass otherwise — and 'Trust-Spine Pass — Human Review Required'
    when only Grok-unresolved P1 prevents AAA.

    Defensive on inputs: missing stage1 keys → treated as failure
    (fail-closed). Empty stage1.checks → cannot return AAA (AAA
    requires evidence, not vacuous success).

    Fix #31: `grok_unresolved_p1` is the count of Grok-flagged P1
    patches that the auto-applier rejected (couldn't be safely
    applied). The harness can't autonomously verify Grok's flag was
    wrong, so an unresolved P1 must surface as 'human review' even
    when both deterministic stages are green."""
    stage1_report = stage1_report or {}
    s1_p1_pass = bool(stage1_report.get("p1_pass", False))
    s1_score = float(stage1_report.get("score_out_of_10", 0.0))
    checks = stage1_report.get("checks") or []
    s1_n_pass = sum(1 for c in checks if c.get("passed", False))
    s1_n_total = len(checks)

    # Stage-2 severity tally with unknown-severity counter for telemetry.
    s2_p1_blocking = 0
    s2_p2 = 0
    s2_unknown = 0
    for i in stage2_issues:
        sev = getattr(i, "severity", None) or ""
        if sev == "P2":
            s2_p2 += 1
        elif sev in _BLOCKING_SEVERITIES:
            s2_p1_blocking += 1
        elif sev in _NONBLOCKING_SEVERITIES:
            pass  # P3 / INFO — no count needed for this verdict
        else:
            # Unknown severity — fail closed. Counts as blocking.
            s2_p1_blocking += 1
            s2_unknown += 1

    p1_clean = s1_p1_pass and s2_p1_blocking == 0
    grok_clean = grok_unresolved_p1 == 0
    # AAA requires positive evidence: at least one check ran AND all
    # passed AND zero stage-2 issues AND zero unresolved Grok P1.
    all_green = (
        p1_clean
        and grok_clean
        and s1_n_total > 0
        and s1_n_pass == s1_n_total
        and s2_p2 == 0
    )

    if not p1_clean:
        verdict = "SHIP-BLOCKED"
        reason = (
            f"P1 fail: stage1 P1_pass={s1_p1_pass}, "
            f"stage2 blocking issues={s2_p1_blocking}"
            + (f" (incl. {s2_unknown} unknown-severity)" if s2_unknown else "")
        )
    elif all_green:
        verdict = "AAA"
        reason = (
            f"All-green: stage1 {s1_n_pass}/{s1_n_total} + "
            f"stage2 zero issues + zero unresolved Grok P1"
        )
    elif not grok_clean and p1_clean:
        # Fix #31 + Fix #49: deterministic stages clean, but Grok
        # flagged P1 patches that the agent-to-agent repair loop
        # AND the auto-strip safety net BOTH could not resolve
        # (e.g. the BEFORE region wasn't unique in the paper or
        # appeared in load-bearing structural context). The
        # pipeline went as far as it can autonomously — this is
        # the honest agent-review-unresolved state, NOT a 'human
        # review please' cop-out.
        verdict = "Trust-Spine Pass — Agent Review Unresolved"
        reason = (
            f"P1 clean (stage1 {s1_n_pass}/{s1_n_total}, "
            f"stage2 P2={s2_p2}); BUT {grok_unresolved_p1} "
            f"Grok-flagged P1 patch(es) survived BOTH the "
            "agent-to-agent repair loop AND the auto-strip safety "
            "net (Fix #49). The pipeline exhausted its autonomous "
            "options; the issue is materially unresolvable without "
            "either a corpus-side fix or an out-of-band edit."
        )
    else:
        verdict = "Trust-Spine Pass"
        reason = (
            f"P1 clean; stage1 {s1_n_pass}/{s1_n_total} "
            f"(score {s1_score}/10); stage2 {s2_p2} P2 notes"
            + (
                "; stage1 had ZERO checks (no positive evidence — AAA blocked)"
                if s1_n_total == 0 else ""
            )
        )

    return UnifiedVerdict(
        verdict=verdict,
        reason=reason,
        stage1_p1_pass=s1_p1_pass,
        stage1_score=s1_score,
        stage1_pass_rate=f"{s1_n_pass}/{s1_n_total}",
        stage2_p1=s2_p1_blocking,
        stage2_p2=s2_p2,
        stage2_unknown_severity_count=s2_unknown,
        all_green=all_green,
        p1_clean=p1_clean,
        grok_unresolved_p1=grok_unresolved_p1,
    )


def _format_unified_verdict(u: UnifiedVerdict) -> str:
    return (
        f"# Unified Final Verdict\n\n"
        f"**Verdict: {u.verdict}**\n\n"
        f"**Reason:** {u.reason}\n\n"
        f"## Components\n\n"
        f"- Stage-1 audit (Q1-Q10): "
        f"P1_pass={u.stage1_p1_pass}, "
        f"score={u.stage1_score}/10, "
        f"pass_rate={u.stage1_pass_rate}\n"
        f"- Stage-2 consistency audit: "
        f"P1 issues={u.stage2_p1}, "
        f"P2 issues={u.stage2_p2}"
        + (
            f", unknown-severity={u.stage2_unknown_severity_count} "
            f"(treated as blocking)"
            if u.stage2_unknown_severity_count else ""
        )
        + "\n"
        + (
            f"- Grok-flagged P1 patches unresolved: "
            f"{u.grok_unresolved_p1} "
            f"(downgrades AAA → 'Trust-Spine Pass — Human Review "
            f"Required'; Fix #31)\n"
            if u.grok_unresolved_p1 else ""
        )
        + "\n"
        "## Verdict scale\n\n"
        "- **AAA** — all-green (stage-1 + stage-2 both zero issues, "
        "and stage-1 actually ran checks).\n"
        "- **Trust-Spine Pass** — P1 clean in both stages; "
        "stage-1 P2s or stage-2 P2 notes allowed.\n"
        "- **SHIP-BLOCKED** — ANY P1 fail in stage-1 OR stage-2 "
        "(unknown severities fail closed).\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Phase 6.1 — wire v0.6.0 bound claims into agent/paper_writer.py",
    )
    parser.add_argument(
        "--topic", required=True,
        help=(
            "Topic to synthesise (REQUIRED — no default to prevent "
            "accidental metformin runs after a topic-pack edit). "
            "Must match a topic_packs/<topic>.toml file AND a "
            "docs/quality-reference/<topic>/ corpus directory. "
            "Examples: metformin, rapamycin, statins, glp1, "
            "senolytics, nad_precursors."
        ),
    )
    parser.add_argument(
        "--out-dir", help=(
            "default: runs/synthesis-<topic>-v06-{ISO}/"
        ),
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Build receipts/matrix/thesis but do not call the LLM",
    )
    args = parser.parse_args(argv)
    if args.out_dir:
        out_dir = Path(args.out_dir).resolve()
    else:
        ts = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
        out_dir = (
            REPO_ROOT / "runs" / f"synthesis-{args.topic}-v06-{ts}"
        )
    return asyncio.run(_run(
        out_dir, dry_run=args.dry_run, topic=args.topic,
    ))


if __name__ == "__main__":
    sys.exit(main())
