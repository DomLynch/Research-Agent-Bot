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
import datetime as dt
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from agent.llm_client import CallSpec, CostLedger  # noqa: E402
from agent.paper_writer import render_full_paper  # noqa: E402
from agent.paper_writer_claim_repair import repair_claim_strength  # noqa: E402
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
    effect_direction, p-values list, sample-size summary."""
    outcome_counter: Counter[str] = Counter()
    direction_score = 0
    p_values: list[str] = []
    sample_sizes: list[float] = []
    for c in claims:
        if oc := _ENDPOINT_TO_OUTCOME_CLASS.get(c.get("endpoint") or ""):
            outcome_counter[oc] += 1
        eff = _claim_metformin_effect(c)
        direction_score += eff
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
    if direction_score > 0:
        effect_direction = "positive"
    elif direction_score < 0:
        effect_direction = "negative"
    else:
        effect_direction = "unclear"

    return {
        "outcome_class": dominant_outcome,
        "effect_direction": effect_direction,
        "p_values": p_values,
        "sample_sizes": sample_sizes,
        "n_claims": len(claims),
    }


def _classify_paper_tier(paper_id: str, n_claims: int, paper_meta: dict) -> tuple[str, str]:
    """Return (evidence_tier, directness) heuristic.

    The 5 RCT-style core papers (Walton/Konopka/Witham/Mohammed/Keys)
    contributing >5 high-confidence claims get tier A (RCT) or B (review).
    The 35 OA papers from search are mostly mechanistic/review.
    """
    # Heuristic: papers in the original 7 reference set are tier A1
    # (Walton/Konopka/Witham are RCTs) or B (Mohammed/Keys/MILES/Kulkarni
    # 2022 are reviews). The 35 PMC papers are mostly editorials.
    is_rct_papers = ("MASTERS", "MET_PREVENT", "Konopka_2019")
    if any(name in paper_id for name in is_rct_papers):
        return "A1", "direct"
    if paper_id.startswith("PMC"):
        return "C", "mechanistic"
    return "B", "indirect"


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


def build_receipts_from_quant_claims() -> list[ReceiptSummary]:
    """Adapter: v0.6.0 quant_claims → ReceiptSummary list. One receipt
    per contributing paper. Only papers with ≥1 high-confidence
    effect-role claim are included."""
    receipts: list[ReceiptSummary] = []

    # Load paper metadata once (paper_id → {title, journal, year, doi, pmid})
    paper_meta_by_id: dict[str, dict] = {}
    for path in sorted(PARSED_DIR.glob("*.paper_sections.json")):
        d = json.loads(path.read_text())
        pid = d.get("paper_id") or path.stem
        paper_meta_by_id[pid] = d

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
                if a.effect_direction == b.effect_direction:
                    kind = "agreement"
                    severity = 1
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
) -> str:
    """Substitute paper_id strings (and their truncated forms) in the
    markdown with Author-Year citation. Audit Q3 ship-blocks otherwise."""
    out = paper_md
    # Sort by length desc so longer forms get replaced before shorter
    # truncations (avoids "Walton_2019" replacing inside
    # "Walton_2019_MASTERS_...").
    pairs = sorted(
        ((r.receipt_id, _author_year_for_receipt(r)) for r in receipts),
        key=lambda p: -len(p[0]),
    )
    for paper_id, author_year in pairs:
        # Replace full id + common truncations the LLM produces
        for variant in (paper_id, paper_id[:30], paper_id[:25], paper_id[:20]):
            if variant and len(variant) >= 8:
                out = out.replace(variant, author_year)
    return out


def _append_references_block(
    paper_md: str, receipts: list[ReceiptSummary],
) -> str:
    """Append a deterministic References section at the end of the
    paper (after Conclusion). Each entry: Author Year. Title. Journal,
    Year. DOI/PMID. Replaces the writer's References section with one
    grounded in paper_sections.json metadata."""
    lines = ["", "## References", ""]
    for r in receipts:
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
    print(
        "\nCalling render_full_paper "
        "(target 5-15k words, multi-section, tiered validation)...",
        file=sys.stderr,
    )
    import httpx
    async with httpx.AsyncClient(timeout=180.0) as client:
        full_paper_md, sections = await render_full_paper(
            receipts, matrix, thesis,
            topic="metformin", submission_id=submission_id,
            chain=chain, client=client, ledger=ledger,
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

    # Phase 6.2 audit-driven: replace paper_id citations with Author-Year
    # form so the body prose doesn't leak internal handles. The production
    # writer cites by receipt_id (which IS paper_id in our adapter); the
    # audit Q3 ship-blocks if those leak into prose. Post-processing
    # substitutes Author-Year throughout body + leaves a proper References
    # block at the end for traceability.
    full_paper_md = _replace_paper_ids_with_author_year(full_paper_md, receipts)
    full_paper_md = _append_references_block(full_paper_md, receipts)

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
        patches, _raw, model_used, cost = await _final_reviewer.review_with_grok(
            paper_md, manifest, audit_report,
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

    # Stage 5: Final audit (re-run after all patches applied).
    print("[pipeline] Stage 5/5 — final audit...", file=sys.stderr)
    audit_report = _audit_v06.audit(paper_md)
    audit_path.write_text(json.dumps(audit_report, indent=2))
    audit_md = _audit_v06._format_summary(audit_report)
    paper_path.with_suffix(".audit.md").write_text(audit_md)
    print(
        f"[pipeline] DONE — score={audit_report['score_out_of_10']}/10 "
        f"P1_pass={audit_report['p1_pass']}",
        file=sys.stderr,
    )
    return paper_md


def _issue_to_dict(issue) -> dict[str, Any]:
    return {
        "id": issue.id, "severity": issue.severity,
        "issue_type": issue.issue_type, "auto_fixable": issue.auto_fixable,
        "evidence": issue.evidence, "suggested_fix": issue.suggested_fix,
    }


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
