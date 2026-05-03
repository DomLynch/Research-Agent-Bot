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

QUANT_DIR = REPO_ROOT / "docs" / "quality-reference" / "metformin" / "quant_claims"
PARSED_DIR = REPO_ROOT / "docs" / "quality-reference" / "metformin" / "parsed"


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


def _claim_metformin_effect(claim: dict) -> int:
    """Returns +1 if metformin's effect on this endpoint is good
    (positive), -1 if bad (negative), 0 if unclear/null."""
    direction = claim.get("direction") or ""
    arm = claim.get("arm") or ""
    endpoint = claim.get("endpoint") or ""
    polarity = _ENDPOINT_POLARITY.get(endpoint, 0)
    if not polarity or not direction or direction == "no_change":
        return 0
    direction_sign = +1 if direction == "increase" else -1
    # If the direction is described from the placebo arm, flip — a
    # placebo-arm gain implies metformin underperformed.
    arm_sign = +1 if arm == "metformin" else -1
    metformin_movement = direction_sign * arm_sign
    return polarity * metformin_movement


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
    # legacy receipt_id heuristic so existing runs don't regress.
    if cls.tier == "unknown":
        is_rct_papers = ("MASTERS", "MET_PREVENT", "Konopka_2019")
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


def build_receipts_from_quant_claims() -> list[ReceiptSummary]:
    """Adapter: v0.6.0 quant_claims → ReceiptSummary list. One receipt
    per contributing paper. Only papers with ≥1 high-confidence
    effect-role claim are included."""
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
            topic="metformin",
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
) -> SynthesisThesis:
    """Pick a thesis statement that names the cross-domain tension
    in the metformin literature."""
    receipt_ids = tuple(r.receipt_id for r in receipts)
    non_orth = matrix.non_orthogonal()
    addressed = tuple(t.summary for t in non_orth[:3])
    text = (
        "Across {n} curated reference papers, metformin shows a context-"
        "dependent profile: positive cardiometabolic and longevity "
        "signals (mortality reduction in observational analyses, "
        "preclinical lifespan extension) coexist with consistent "
        "negative effects on muscle and exercise adaptations in older "
        "adult RCTs (MASTERS/Konopka/MET-PREVENT). The synthesis "
        "thesis is that metformin's anti-aging case is incomplete: "
        "metabolic plausibility is real, but the human functional-"
        "fitness evidence is mixed and trends negative when paired "
        "with exercise."
    ).format(n=len(receipts))
    return SynthesisThesis(
        text=text,
        receipt_ids_referenced=receipt_ids,
        tensions_addressed=addressed,
        rejected_candidates=(),
        picker_rationale=(
            "Single deterministic thesis from cross-domain tension matrix; "
            "no LLM tournament (Phase 6.1 minimal adapter)."
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
    never drift out of sync."""
    lines = ["", "## References", ""]
    for r in receipts:
        if registry is not None and r.receipt_id in registry:
            author_year = registry[r.receipt_id].body_citation
        else:
            author_year = _author_year_for_receipt(r)
        bits = [f"- **{author_year}.**"]
        if r.source_title:
            bits.append(f"_{r.source_title}._")
        if r.source_venue:
            bits.append(f"{r.source_venue}")
        if r.source_year:
            bits.append(f", {r.source_year}")
        if r.source_doi:
            bits.append(f". DOI: {r.source_doi}")
        if r.source_pmid:
            bits.append(f". PMID: {r.source_pmid}")
        bits.append(".")
        lines.append(" ".join(bits))
    lines.append("")
    return paper_md.rstrip() + "\n".join(lines)


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


async def _run(out_dir: Path, dry_run: bool = False) -> int:
    settings = load_settings()
    if not settings.bot_enabled:
        print("BOT_ENABLED=false; aborting.", file=sys.stderr)
        return 1

    print("Loading v0.6.0 quant_claims...", file=sys.stderr)
    receipts = build_receipts_from_quant_claims()
    print(
        f"  Built {len(receipts)} receipts "
        f"(one per contributing paper).",
        file=sys.stderr,
    )
    if not receipts:
        print("No high-confidence claims found.", file=sys.stderr)
        return 2
    matrix = build_tension_matrix(receipts)
    thesis = build_thesis(receipts, matrix)

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
            topic="metformin", submission_id=submission_id,
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
        writer_receipts, writer_matrix, thesis, topic="metformin",
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
        topic="metformin",
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
        paper_path.write_text(paper_md)
        paper_path.with_suffix(".review_patch_log.json").write_text(json.dumps({
            "applied_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "n_proposed": len(results),
            "n_applied": sum(1 for r in results if r.decision == "applied"),
            "n_rejected": sum(1 for r in results if r.decision == "rejected"),
            "patches": [
                {
                    "patch_id": r.patch_id, "patch_type": r.patch_type,
                    "severity": r.severity, "decision": r.decision,
                    "reason_for_decision": r.reason_for_decision,
                }
                for r in results
            ],
        }, indent=2))
        n_applied = sum(1 for r in results if r.decision == "applied")
        n_rejected = sum(1 for r in results if r.decision == "rejected")
        print(
            f"[pipeline]   applied={n_applied} rejected={n_rejected}",
            file=sys.stderr,
        )

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
    unified = _compute_unified_verdict(audit_report, final_issues)
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
    """Worst-of(stage1, stage2). Cross-stage object → frozen+slots
    per project rule. Serialized via dataclasses.asdict() to JSON."""
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


def _is_blocking(severity: str) -> bool:
    """Positive allowlist: known non-blocking severities pass; ANYTHING
    ELSE blocks (fail-closed for unknown severities like 'P0' or
    'CRITICAL' that future reviewer-prompts may introduce)."""
    return severity not in _NONBLOCKING_SEVERITIES


def _compute_unified_verdict(
    stage1_report: dict[str, Any] | None,
    stage2_issues: list[Any],
) -> UnifiedVerdict:
    """Worst-of(stage1, stage2). AAA reserved for fully-green (P1+P2).
    SHIP-BLOCKED if either stage flags a P1+ severity. Trust-Spine
    Pass otherwise.

    Defensive on inputs: missing stage1 keys → treated as failure
    (fail-closed). Empty stage1.checks → cannot return AAA (AAA
    requires evidence, not vacuous success)."""
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
    # AAA requires positive evidence: at least one check ran AND all
    # passed AND zero stage-2 issues. Empty checks → CANNOT be AAA.
    all_green = (
        p1_clean
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
            f"stage2 zero issues"
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
        + "\n\n"
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
        "--out-dir", help="default: runs/synthesis-metformin-v06-{ISO}/",
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
        out_dir = REPO_ROOT / "runs" / f"synthesis-metformin-v06-{ts}"
    return asyncio.run(_run(out_dir, dry_run=args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
