"""Full-paper writer for trust-spine synthesis manuscripts."""
from __future__ import annotations

import os
import re
from collections.abc import Mapping, Sequence
from typing import Any

import httpx

from agent.llm_client import CallSpec, CostLedger
from agent.framework_section import (
    build_framework_engagement_section,
    build_novel_framework_section,
)
from agent.outcome_class_remap import outcome_display
from agent.paper_writer_builders import (
    build_anchored_from_parsed,
    build_results_from_parsed,
    build_scoped_from_parsed,
)
from agent.paper_writer_citations import (
    build_background_lit_block as _build_background_lit_block,
    run_citation_fix_pass as _run_citation_fix_pass,
)
from agent.paper_writer_claim_repair import repair_abstract_claim_strength
from agent.paper_writer_deterministic import (
    build_methods_section,
    build_references_full_section,
)
from agent.paper_writer_helpers import (
    build_retry_prompt as _build_retry_prompt,
    call_llm_section as _call_llm_section,
    section_word_count as _section_word_count,
    strip_rendered_citation_markers as _strip_rendered_citation_markers,
)
from agent.review_type import COMPACT_REVIEW_TYPES
from agent.synthesis_schemas import (
    ReceiptSummary,
    SectionName,
    SynthesisClaimAnchor,
    SynthesisSection,
    SynthesisThesis,
    TensionMatrix,
)
from agent.synthesis_writer import filter_accepted
from agent.topic_display import humanize_topic, intervention_label

# Day 10.16c — per-section word-count budgets enforced AT CODE LEVEL.
# Prompts ask for length; this dict defines the floors that the writer
# enforces by retrying under-budget sections up to N times. If a section
# still falls short after retries, it lands as-is and the audit picks
# up the shortfall via the WORD_COUNT_FLOOR check.
#
SECTION_WORD_FLOORS: Mapping[str, int] = {
    "abstract": 200,            # was 250
    "introduction": 800,        # was 1200
    "background": 700,          # was 1000
    "results": 1500,            # was 2000 (Tables 2 + 5 carry numerics)
    "cross_domain_synthesis": 850,   # Q12 + journal-surface margin
    "discussion": 900,          # was 1100 → 900 (matches Q11 floor)
    "limitations_full": 450,    # was 600
    "conclusion": 250,          # was 300
}

# Total full-paper floor — paper_writer's render_full_paper records
# the total word count and the auditor / script can ship-fail when
# the count is below this.
FULL_PAPER_WORD_FLOOR = 5000

# Max LLM retries per section when word count is below floor.
# Refactor 2026-05-04: bumped from 1 → 2 (3 attempts max). With
# generic-multi-topic prompts, the writer occasionally under-
# produces Discussion/Conclusion on first 2 tries; one more attempt
# turns ~50% of the misses into AAA. Worst-case wall time is +1
# section call (~30s), acceptable trade.
SECTION_RETRY_BUDGET = 2


def _revision_feedback_block() -> str:
    feedback = _revision_feedback_text()
    if not feedback:
        return ""
    # Researka joins requiredRevisions with "; ". Split only at independent
    # revision-action starts so semicolon examples stay inside the ask.
    starts = (
        "Add", "Audit", "Clarify", "Correct", "Define", "Differentiate",
        "Document", "Ensure", "Explain", "Expand", "Fix", "For each",
        "Hedge", "Include", "Operationalize", "Provide", "Re-extract",
        "Mark", "Reclassify", "Reconcile", "Regenerate", "Remove", "Repair",
        "Resolve", "Replace", "Rewrite", "Separate", "Soften", "Update", "Verify",
    )
    pattern = r";\s+(?=(?:" + "|".join(re.escape(start) for start in starts) + r")\b)"
    asks = [a.strip() for a in re.split(pattern, feedback, flags=re.IGNORECASE) if a.strip()]
    body = "\n".join(f"  {i}. {ask}" for i, ask in enumerate(asks, 1))
    return f"REVISION FEEDBACK — address EACH point below if source-supported:\n{body}\nTreat this as reviewer guidance, not evidence. Add only receipt-supported claims, citations, or numerics; do not fabricate to satisfy a point you cannot support. If an ask requests a table, render a clearly labelled markdown table; prose alone does not satisfy table-shaped feedback."


def _revision_feedback_text() -> str:
    return " ".join(os.getenv("RESEARKA_REVISION_FEEDBACK", "").split())[:4000]


# --- Tier-aware paper-tier classification (reviewer-aligned) -----------


def derive_paper_tier(summary: ReceiptSummary) -> str:
    """Split evidence tier into reader-facing paper tier."""
    tier = (summary.evidence_tier or "").upper()
    directness = (summary.directness or "").lower()
    outcome = (summary.outcome_class or "").lower()
    if tier == "A1":
        if directness == "direct" and outcome in (
            "muscle_function", "frailty", "cardiometabolic",
            "cognitive", "mortality",
        ):
            return "A1_clinical_RCT"
        return "A2_human_mechanistic"
    if tier == "A2":
        return "A2_human_mechanistic"
    if tier == "B":
        return "B1_review"
    if tier == "C":
        return "C1_preclinical"
    return tier or "unknown"


def _outcome_results_heading(outcome: str) -> str:
    return f"### {outcome_display(outcome)} Outcomes"


def _ensure_outcome_results_heading(body_md: str, outcome: str) -> str:
    body = body_md.split("\n", 1)[1].strip()
    heading = _outcome_results_heading(outcome)
    if heading in body.splitlines():
        return body
    return f"{heading}\n\n{body}".strip()


def _receipt_label(receipt: ReceiptSummary) -> str:
    title = " ".join(str(receipt.source_title or receipt.receipt_id).split())
    if len(title) > 90:
        title = title[:87].rstrip() + "..."
    return f"{title} {receipt.source_year}" if receipt.source_year else title


def _receipt_role(receipt: ReceiptSummary) -> str:
    return (
        f"{_receipt_label(receipt)} "
        f"(tier={receipt.evidence_tier}; directness={receipt.directness}; "
        f"direction={receipt.effect_direction})"
    )


def _build_thin_results_section(receipts: Sequence[ReceiptSummary], matrix: TensionMatrix) -> SynthesisSection:
    by_outcome: dict[str, list[ReceiptSummary]] = {}
    tensions: dict[str, int] = {}
    for r in receipts:
        by_outcome.setdefault(r.outcome_class, []).append(r)
    for t in matrix.non_orthogonal():
        tensions[t.outcome_class] = tensions.get(t.outcome_class, 0) + 1
    lines = ["## Results", "", f"This evidence brief includes {len(receipts)} accepted sources and {len(matrix.non_orthogonal())} same-outcome tensions. Detailed numeric claims remain in the quantitative evidence table and citation registry. Because the corpus is primary-tier limited, these counts are presented as an evidence map rather than as a full journal Results narrative or pooled treatment estimate."]
    for outcome, group in sorted(by_outcome.items()):
        tiers = ", ".join(sorted({r.evidence_tier for r in group if r.evidence_tier})) or "not classified"
        directions = ", ".join(sorted({r.effect_direction for r in group if r.effect_direction})) or "not classified"
        examples = "; ".join(_receipt_role(r) for r in group[:3])
        lines += ["", _outcome_results_heading(outcome), "", f"{len(group)} included source{'s' if len(group) != 1 else ''} were assigned to this outcome class. Evidence tiers: {tiers}. Effect directions: {directions}. Non-orthogonal same-outcome tensions: {tensions.get(outcome, 0)}. Source examples: {examples}."]
    return SynthesisSection(name="results", body_md="\n".join(lines).rstrip() + "\n", anchors=())


def _append_section_note(section: SynthesisSection, note: str) -> SynthesisSection:
    if not note or note in section.body_md:
        return section
    return SynthesisSection(
        name=section.name,
        body_md=section.body_md.rstrip() + "\n\n" + note.rstrip() + "\n",
        anchors=section.anchors,
    )


def _thin_limitations_note(receipts: Sequence[ReceiptSummary]) -> str:
    design_limited = [
        _receipt_label(r) for r in receipts
        if r.directness in {"protocol", "mechanistic"}
        or re.search(r"\b(protocol|cross-sectional|observational)\b", r.source_title or "", flags=re.I)
    ]
    if not design_limited:
        return ""
    shown = "; ".join(design_limited[:5])
    return (
        "**Design-limit note:** Protocol, mechanistic, observational, or "
        f"cross-sectional sources ({shown}) are retained for context but "
        "cannot support causal claims individually. They bound the evidence "
        "map and should not be read as direct clinical efficacy evidence."
    )


def _thin_conclusion_note(receipts: Sequence[ReceiptSummary], matrix: TensionMatrix) -> str:
    direct = [r for r in receipts if r.directness == "direct"]
    noun = "source" if len(direct) == 1 else "sources"
    direct_text = "; ".join(_receipt_role(r) for r in direct[:5]) or "none"
    extra = f"; {len(direct) - 5} additional direct sources are listed in the Findings Map" if len(direct) > 5 else ""
    remainder = max(0, len(receipts) - len(direct))
    return (
        f"**Direct-source ceiling:** The corpus contains {len(direct)} direct clinical {noun}. "
        f"Representative direct sources are {direct_text}{extra}. The remaining {remainder} sources are "
        "indirect, review, protocol, or mechanistic/contextual evidence, so "
        "they can refine scope and uncertainty but do not outweigh the direct "
        f"source role. The conclusion remains bounded by {len(matrix.non_orthogonal())} "
        "same-outcome tensions and the receipt-level evidence hierarchy."
    )


# Validation helpers + paragraph builders moved to
# agent/paper_writer_builders.py to keep this module under the 600
# per-file LOC cap.


_PAPER_TIER_HUMAN_LABEL: dict[str, str] = {
    # Internal-label forms (from derive_paper_tier when classifier fires)
    "A1_clinical_RCT":
        "RCT (clinical/functional endpoint)",
    "A2_human_mechanistic":
        "RCT (human, mechanistic/biomarker endpoint)",
    "B1_review":
        "systematic review or meta-analysis",
    "C1_preclinical":
        "preclinical (animal or in-vitro)",
    "mixed":
        "mixed cluster (multiple study types)",
    # Raw tier-code forms (when derive_paper_tier doesn't subclassify
    # — e.g. tier='C1' input, or 'B2' which has no internal-label form)
    "A1": "RCT (clinical/functional endpoint)",
    "A2": "RCT (human, mechanistic/biomarker endpoint)",
    "B1": "systematic review or meta-analysis",
    "B2": "observational cohort",
    "C1": "preclinical (animal or in-vitro)",
    "C2": "preclinical (in-vitro / cell-only)",
}


def _humanize_paper_tier(internal_label: str) -> str:
    """Map internal paper-tier labels to reader-facing phrases."""
    return _PAPER_TIER_HUMAN_LABEL.get(internal_label, internal_label)


def _build_user_prompt(
    receipts: Sequence[ReceiptSummary],
    rejected: Sequence[ReceiptSummary],
    matrix: TensionMatrix,
    thesis: SynthesisThesis,
    *,
    topic: str,
    background_lit_entries: Sequence[Any] | None = None,
) -> str:
    """Common prompt block: accepted receipts, tensions, and thesis."""
    _ = rejected  # Day 10.17 Fix A — intentionally unused, see docstring.
    lines = [f"Topic: {topic}", "", "ACCEPTED RECEIPTS:"]
    for r in receipts:
        paper_tier_raw = derive_paper_tier(r)
        # Fix #33: write a HUMAN-READABLE study-design label into the
        # prompt context instead of the internal `A1_clinical_RCT`
        # / `C1_preclinical` / `A2_human_mechanistic` / `B1_review`
        # token. MiMo was copy-pasting the internal token verbatim
        # into prose ("the C1_preclinical evidence from..."), which
        # leaks pipeline machinery into the published paper.
        paper_tier = _humanize_paper_tier(paper_tier_raw)
        # Day 10.17a: empty population_summary now means tier-gated-out
        # (mechanistic / indirect receipt) per agent/synthesis.py. Use
        # an explicit sentinel so the LLM hedges honestly instead of
        # hallucinate-filling a clinical population it doesn't have.
        pop = r.population_summary or (
            "N/A (mechanistic / indirect — no enrolled clinical population)"
        )
        lines.append(
            f"  - id: {r.receipt_id}\n"
            f"    study_design: {paper_tier}\n"
            f"    outcome_class: {r.outcome_class}\n"
            f"    directness: {r.directness}\n"
            f"    effect_direction: {r.effect_direction}\n"
            f"    canonical_trial_id: {r.canonical_trial_id or '(none)'}\n"
            f"    population: {pop}\n"
            f"    p_values: {list(r.p_values)}\n"
            f"    thesis: {r.thesis_text[:300]}"
        )
    non_orth = matrix.non_orthogonal()
    lines.extend(["", "TENSION MATRIX (non-orthogonal pairs):"])
    if non_orth:
        for t in non_orth:
            lines.append(
                f"  - {t.kind} ({t.outcome_class}, severity {t.severity}):"
                f" {t.summary}"
            )
    else:
        lines.append("  (no same-outcome non-orthogonal pairs in matrix)")
    lines.extend([
        "",
        "PICKED THESIS (the integrating sentence from the brief):",
        f"  {thesis.text}",
    ])
    bg_block = _build_background_lit_block(background_lit_entries)
    if bg_block:
        lines.append(bg_block)
    revision_block = _revision_feedback_block()
    if revision_block:
        lines.extend(["", revision_block])
    return "\n".join(lines)


# --- Section builders ----------------------------------------------------


async def _write_anchored_section(
    *,
    name: SectionName,
    heading: str,
    system_prompt: str,
    user_prompt: str,
    accepted: Sequence[ReceiptSummary],
    chain: Sequence[CallSpec],
    client: httpx.AsyncClient | None,
    ledger: CostLedger | None,
    seed: int | None,
    fallback_body: str,
    background_lit_entries: Sequence[Any] | None = None,
) -> SynthesisSection:
    """Build an anchored section with bounded retry plus citation repair."""
    floor = SECTION_WORD_FLOORS.get(str(name), 0)
    best: SynthesisSection | None = None
    best_words = 0
    current_prompt = user_prompt
    for attempt in range(SECTION_RETRY_BUDGET + 1):
        parsed = await _call_llm_section(
            system_prompt=system_prompt, user_prompt=current_prompt,
            chain=chain, client=client, ledger=ledger, seed=seed,
        )
        if not parsed:
            continue
        section = build_anchored_from_parsed(
            parsed, name=name, heading=heading, accepted=accepted,
        )
        if section is None:
            continue
        words = _section_word_count(section)
        if words > best_words:
            best, best_words = section, words
        if best_words >= floor or floor == 0:
            break
        # Below floor — prepare a retry prompt.
        current_prompt = _build_retry_prompt(
            user_prompt, section_name=str(name),
            target_floor=floor, last_word_count=words,
        )

    # Fix #20: citation fix pass (independent of word-count budget).
    def _builder(parsed_dict: dict) -> SynthesisSection | None:
        return build_anchored_from_parsed(
            parsed_dict, name=name, heading=heading, accepted=accepted,
        )
    best = await _run_citation_fix_pass(
        best, base_user_prompt=user_prompt,
        system_prompt=system_prompt, builder_fn=_builder,
        background_lit_entries=background_lit_entries,
        chain=chain, client=client, ledger=ledger, seed=seed,
        call_llm_fn=_call_llm_section,
    )
    return best or SynthesisSection(
        name=name, body_md=fallback_body, anchors=(),
    )


async def _write_scoped_section(
    *,
    name: SectionName,
    heading: str,
    system_prompt: str,
    user_prompt: str,
    topic: str,
    accepted: Sequence[ReceiptSummary],
    chain: Sequence[CallSpec],
    client: httpx.AsyncClient | None,
    ledger: CostLedger | None,
    seed: int | None,
    fallback_body: str,
    background_lit_entries: Sequence[Any] | None = None,
) -> SynthesisSection:
    """Build a scoped section with bounded retry plus citation repair."""
    floor = SECTION_WORD_FLOORS.get(str(name), 0)
    best: SynthesisSection | None = None
    best_words = 0
    current_prompt = user_prompt
    for attempt in range(SECTION_RETRY_BUDGET + 1):
        parsed = await _call_llm_section(
            system_prompt=system_prompt, user_prompt=current_prompt,
            chain=chain, client=client, ledger=ledger, seed=seed,
        )
        if not parsed:
            continue
        section = build_scoped_from_parsed(
            parsed, name=name, heading=heading,
            topic=topic, accepted=accepted,
        )
        if section is None:
            continue
        words = _section_word_count(section)
        if words > best_words:
            best, best_words = section, words
        if best_words >= floor or floor == 0:
            break
        current_prompt = _build_retry_prompt(
            user_prompt, section_name=str(name),
            target_floor=floor, last_word_count=words,
        )

    # Fix #20: citation fix pass.
    def _builder(parsed_dict: dict) -> SynthesisSection | None:
        return build_scoped_from_parsed(
            parsed_dict, name=name, heading=heading,
            topic=topic, accepted=accepted,
        )
    best = await _run_citation_fix_pass(
        best, base_user_prompt=user_prompt,
        system_prompt=system_prompt, builder_fn=_builder,
        background_lit_entries=background_lit_entries,
        chain=chain, client=client, ledger=ledger, seed=seed,
        call_llm_fn=_call_llm_section,
    )
    return best or SynthesisSection(
        name=name, body_md=fallback_body, anchors=(),
    )


async def write_results_section(
    receipts: Sequence[ReceiptSummary],
    rejected: Sequence[ReceiptSummary],
    matrix: TensionMatrix,
    thesis: SynthesisThesis,
    *,
    topic: str,
    chain: Sequence[CallSpec],
    client: httpx.AsyncClient | None = None,
    ledger: CostLedger | None = None,
    seed: int | None = None,
    background_lit_entries: Sequence[Any] | None = None,
) -> SynthesisSection:
    """Render Results by outcome-owned packet groups."""
    _ = rejected
    by_outcome: dict[str, list[ReceiptSummary]] = {}
    for receipt in receipts:
        by_outcome.setdefault(receipt.outcome_class, []).append(receipt)
    # Topic-aware Results prompt (Refactor 2026-05-04)
    from agent.paper_writer_prompts import format_prompts_for_topic
    drug_class = "drug"
    try:
        from pathlib import Path as _Path
        from agent.topic_pack import load_topic_pack
        _repo = _Path(__file__).resolve().parent.parent
        _tp = _repo / "topic_packs" / f"{topic}.toml"
        if _tp.exists():
            pack = load_topic_pack(_tp)
            drug_class = pack.drug_class or "drug"
    except (ImportError, OSError, ValueError):
        pass
    _results_prompt = format_prompts_for_topic(
        topic=intervention_label(topic, root=_repo), drug_class=drug_class,
    )["results"]
    fallback = "## Results\n\nAccepted receipts contain source-traced quantitative evidence; per-receipt details remain in the evidence brief and deterministic tables.\n"
    floor = SECTION_WORD_FLOORS.get("results", 0)
    per_outcome_floor = floor // max(1, len(by_outcome))
    per_outcome_floor = max(180, min(500, per_outcome_floor))
    result_bodies: list[str] = []
    anchors: list[SynthesisClaimAnchor] = []
    for outcome, group in sorted(by_outcome.items()):
        ids = {r.receipt_id for r in group}
        local_matrix = TensionMatrix(
            receipts=tuple(group),
            pairs=tuple(
                t for t in matrix.pairs
                if t.outcome_class == outcome
                and t.receipt_a_id in ids
                and t.receipt_b_id in ids
            ),
        )
        user = _build_user_prompt(
            group, (), local_matrix, thesis, topic=topic,
            background_lit_entries=(),
        )
        best: SynthesisSection | None = None
        best_words = 0
        current_prompt = user
        for attempt in range(SECTION_RETRY_BUDGET + 1):
            parsed = await _call_llm_section(
                system_prompt=_results_prompt, user_prompt=current_prompt,
                chain=chain, client=client, ledger=ledger, seed=seed,
            )
            if not parsed:
                continue
            section = build_results_from_parsed(parsed, accepted=group)
            if section is None:
                continue
            words = _section_word_count(section)
            if words > best_words:
                best, best_words = section, words
            if best_words >= per_outcome_floor:
                break
            current_prompt = _build_retry_prompt(
                user, section_name=f"{outcome} results",
                target_floor=per_outcome_floor, last_word_count=words,
            )

        def _builder(parsed_dict: dict) -> SynthesisSection | None:
            return build_results_from_parsed(parsed_dict, accepted=group)

        best = await _run_citation_fix_pass(
            best, base_user_prompt=user,
            system_prompt=_results_prompt, builder_fn=_builder,
            background_lit_entries=(),
            chain=chain, client=client, ledger=ledger, seed=seed,
            call_llm_fn=_call_llm_section,
        )
        if best is None:
            best = build_results_from_parsed({"subsections": []}, accepted=group)
        if best is None:
            continue
        body = _ensure_outcome_results_heading(best.body_md, outcome)
        if body:
            result_bodies.append(body)
            anchors.extend(best.anchors)
    if result_bodies and anchors:
        return SynthesisSection(
            name="results",
            body_md="## Results\n\n" + "\n\n".join(result_bodies).strip() + "\n",
            anchors=tuple(anchors),
        )
    return SynthesisSection(
        name="results", body_md=fallback, anchors=(),
    )


# --- Top-level renderer --------------------------------------------------


_FULL_PAPER_SECTION_ORDER: tuple[SectionName, ...] = (
    "abstract",
    "research_question",
    "introduction",
    "background",
    "inferential_bridge",
    "quantitative_results_table",
    "methods",
    "results",
    "cross_domain_synthesis",
    "novel_framework",
    "discussion",
    "limitations_full",
    "conclusion",
    "references_full",
)
# Slice 35: Evidence-brief skeleton — skips LLM long-form generation
# (introduction/background/cross_domain/discussion/novel_framework) when
# review_type=thin_corpus_brief. Universal — any thin corpus, any domain.
_THIN_BRIEF_SECTION_ORDER: tuple[SectionName, ...] = (
    "abstract", "research_question", "inferential_bridge",
    "quantitative_results_table", "methods", "results", "limitations_full",
    "conclusion", "references_full",
)


async def render_full_paper(
    receipts: Sequence[ReceiptSummary],
    matrix: TensionMatrix,
    thesis: SynthesisThesis,
    *,
    topic: str,
    submission_id: str,
    chain: Sequence[CallSpec],
    client: httpx.AsyncClient | None = None,
    ledger: CostLedger | None = None,
    seed: int | None = None,
    background_lit_entries: Sequence[Any] | None = None,
    qei_citation_tokens_by_paper_id: Mapping[str, str] | None = None,
    qei_quarantine_path: Any | None = None,
    review_type: str | None = None,
) -> tuple[str, tuple[SynthesisSection, ...]]:
    """Render full paper markdown plus per-section anchors. Slice 35:
    review_type=thin_corpus_brief skips long-form section generation."""
    _thin = review_type in COMPACT_REVIEW_TYPES
    _revision_feedback = re.sub(
        r"[-\u2010-\u2015]+", " ", _revision_feedback_text().lower(),
    )
    _author_feedback = " ".join(part for part in _revision_feedback.split(";") if (
        "author inference" in part or ("mechanism level" in part and "inference" in part)
    ))
    _move_to_cross_domain = bool(re.search(r"\bto (?:the )?cross domain synthesis\b", _author_feedback))
    _move_to_discussion = bool(re.search(r"\bto (?:the )?discussion\b", _author_feedback))
    _author_inference_discussion = bool(_author_feedback) and (
        _move_to_discussion or ("discussion" in _author_feedback and not _move_to_cross_domain)
    )
    _author_inference_cross_domain = bool(_author_feedback) and (
        _move_to_cross_domain
        or ("cross domain synthesis" in _author_feedback and not _move_to_discussion)
        or not any(name in _author_feedback for name in ("discussion", "cross domain synthesis"))
    )
    _bridge_requested = "inferential bridge" in _revision_feedback
    _cross_domain_requested = "cross domain synthesis" in _revision_feedback or _author_inference_cross_domain
    _discussion_requested = bool(re.search(r"\bdiscussion(?: section)?\b", _revision_feedback))
    accepted = list(filter_accepted(receipts))
    rejected = [r for r in receipts if r.spar_verdict not in (
        "accept_clean", "accept_caveated",
    )]
    # Refactor 2026-05-04: prompts are now topic-templated. Resolve
    # the topic + drug_class via the topic pack (if available) so
    # paragraph instructions read 'rapamycin (mTOR inhibitor)' not
    # 'metformin (biguanide)' for non-metformin runs.
    from agent.paper_writer_prompts import format_prompts_for_topic
    drug_class = "drug"
    pack = None
    try:
        from pathlib import Path as _Path
        from agent.topic_pack import load_topic_pack
        _repo = _Path(__file__).resolve().parent.parent
        _tp = _repo / "topic_packs" / f"{topic}.toml"
        if _tp.exists():
            pack = load_topic_pack(_tp)
            drug_class = pack.drug_class or "drug"
    except (ImportError, OSError, ValueError):
        pass
    _prompts = format_prompts_for_topic(
        topic=intervention_label(topic, root=_repo), drug_class=drug_class,
    )
    user = _build_user_prompt(
        accepted, rejected, matrix, thesis, topic=topic,
        background_lit_entries=background_lit_entries,
    )
    # Refactor 2026-05-04: removed the '**Submission:** `<run-tag>`'
    # line — that's internal pipeline metadata that belongs in the
    # manifest.json / supplement, not in the prose body. Reviewer
    # flagged this as 'too much internal pipeline language' and
    # Fix #56 was already stripping it; now we don't emit it in the
    # first place.
    topic_title = humanize_topic(topic, title_case=True, root=_repo)
    title_md = f"# Research Synthesis: {topic_title} — full paper\n\n"
    sections: dict[SectionName, SynthesisSection] = {}

    def _log_section_done(name: str, sect: SynthesisSection) -> None:
        words = _section_word_count(sect)
        print(
            f"[paper_writer] {name:25} done — {words} words",
            flush=True,
        )

    print("[paper_writer] starting full-paper render", flush=True)
    sections["abstract"] = await _write_anchored_section(
        name="abstract", heading="## Abstract",
        system_prompt=_prompts["abstract"], user_prompt=user,
        accepted=accepted, chain=chain, client=client, ledger=ledger,
        seed=seed,
        fallback_body="## Abstract\n\nThis synthesis summarizes the accepted receipt set and deterministic audit bundle for the current topic.\n",
        background_lit_entries=background_lit_entries,
    )
    abstract_md, _ = repair_abstract_claim_strength(sections["abstract"].body_md)
    if abstract_md != sections["abstract"].body_md:
        sections["abstract"] = SynthesisSection(name="abstract", body_md=abstract_md, anchors=sections["abstract"].anchors)
    _log_section_done("abstract", sections["abstract"])
    outcome_counts: dict[str, int] = {}
    population_counts: dict[str, int] = {}
    for receipt in accepted:
        outcome_counts[receipt.outcome_class] = outcome_counts.get(receipt.outcome_class, 0) + 1
        population = " ".join(receipt.population_summary.split())[:120].rstrip(" ,.;")
        if population:
            population_counts[population] = population_counts.get(population, 0) + 1
    ranked_outcomes = sorted(outcome_counts, key=lambda name: (-outcome_counts[name], name))
    outcome_scope = " and ".join(outcome_display(name).lower() for name in ranked_outcomes[:2])
    outcome_scope = outcome_scope or "the primary retained outcomes"
    populations = sorted(population_counts, key=lambda name: (-population_counts[name], name))
    population_scope = populations[0] if populations else "the populations represented by admitted sources"
    sections["research_question"] = SynthesisSection(
        name="research_question",
        body_md=(
            "## Research Question\n\n"
            f"Within the retained source corpus for {humanize_topic(topic, root=_repo)}, among {population_scope}, "
            f"do findings for {outcome_scope} support a decision-grade conclusion "
            "(clinically actionable where applicable), and which population, study-design, "
            "and directness boundaries keep extrapolation to other outcome classes "
            "hypothesis-generating?\n"
        ),
        anchors=(),
    )
    _log_section_done("research_question (deterministic)", sections["research_question"])
    if not _thin:
        sections["introduction"] = await _write_scoped_section(
            name="introduction", heading="## Introduction",
            system_prompt=_prompts["introduction"], user_prompt=user,
            topic=topic, accepted=accepted, chain=chain, client=client,
            ledger=ledger, seed=seed,
            fallback_body="## Introduction\n\nThis paper evaluates the topic through accepted receipts, source-traced quantitative claims, and explicit audit gates.\n",
            background_lit_entries=background_lit_entries,
        )
        _log_section_done("introduction", sections["introduction"])
        sections["background"] = await _write_scoped_section(
            name="background", heading="## Background",
            system_prompt=_prompts["background"], user_prompt=user,
            topic=topic, accepted=accepted, chain=chain, client=client,
            ledger=ledger, seed=seed,
            fallback_body="## Background\n\nThe background is limited to corpus-supported context and does not add load-bearing claims outside the accepted receipts.\n",
            background_lit_entries=background_lit_entries,
        )
        _log_section_done("background", sections["background"])
    if not _thin or _bridge_requested:
        from agent.inferential_bridge import build_inferential_bridge_section
        _bridge_spec = pack.inference if pack and pack.inference.allow else None
        sections["inferential_bridge"] = await build_inferential_bridge_section(
            accepted, topic=topic, chain=chain, spec=_bridge_spec, client=client, ledger=ledger, seed=seed,
            unresolved_boundary=_bridge_requested,
        )
        if sections["inferential_bridge"].body_md:
            _log_section_done("inferential_bridge", sections["inferential_bridge"])
    # Universal Q9 structural fix (2026-05-04): deterministic
    # Quantitative Evidence Index built from raw corpus
    # quant_claims.json — per-CLAIM rows, not per-receipt, so the
    # table density doesn't bottleneck on SPAR strictness. No LLM
    # cost, no fabrication risk; structurally lifts numeric density
    # without prompt fragility. See agent/results_table.py.
    #
    # Receipt-scope (2026-05-05 wave 6): map receipts → corpus
    # paper_ids via parsed/*.paper_sections.json metadata (DOI / PMID
    # match). Pass the resulting set to build_results_table so the
    # QEI only shows papers that actually became receipts in this
    # synthesis. Universal — same logic for every topic.
    from pathlib import Path as _Path
    from agent.results_table import (
        build_results_table_with_diagnostic,
        format_empty_qei_placeholder,
        resolve_accepted_paper_ids,
    )
    _repo = _Path(__file__).resolve().parent.parent
    _quant_dir = _repo / "docs" / "quality-reference" / topic / "quant_claims"
    _parsed_dir = _repo / "docs" / "quality-reference" / topic / "parsed"
    _accepted_paper_ids = resolve_accepted_paper_ids(
        receipts, _parsed_dir,
    )
    _table_md, _qei_diag = build_results_table_with_diagnostic(
        _quant_dir, topic=topic,
        accepted_paper_ids=_accepted_paper_ids,
        citation_tokens_by_paper_id=qei_citation_tokens_by_paper_id,
        quarantine_path=qei_quarantine_path,
    )
    # Slice 1 closeout (2026-05-05): empty QEI gets a *diagnostic*
    # placeholder so reviewers see whether the corpus had zero
    # claims, all dropped at confidence gate, or all dropped by
    # topic/receipt guards. The diagnostic dict is also stashed on
    # the section so manifest-builders can read it.
    if not _table_md:
        _table_md = format_empty_qei_placeholder(_qei_diag, topic=topic)
    sections["quantitative_results_table"] = SynthesisSection(
        name="quantitative_results_table",
        body_md=_table_md,
        anchors=(),
    )
    _log_section_done(
        "quantitative_results_table (deterministic)",
        sections["quantitative_results_table"],
    )
    sections["methods"] = build_methods_section(
        receipts, topic=topic, submission_id=submission_id,
    )
    _log_section_done("methods (deterministic)", sections["methods"])
    sections["results"] = _build_thin_results_section(accepted, matrix) if _thin else await write_results_section(
        accepted, rejected, matrix, thesis, topic=topic, chain=chain, client=client, ledger=ledger, seed=seed,
    )
    _log_section_done("results", sections["results"])
    if not _thin or _cross_domain_requested:
        sections["cross_domain_synthesis"] = await _write_anchored_section(
            name="cross_domain_synthesis",
            heading="## Cross-Domain Synthesis",
            system_prompt=_prompts["cross_domain_synthesis"],
            user_prompt=user,
            accepted=accepted, chain=chain, client=client, ledger=ledger,
            seed=seed,
            fallback_body="## Cross-Domain Synthesis\n\nCross-domain interpretation is bounded by the accepted receipt set, outcome coverage, and source-traced claims.\n",
            background_lit_entries=background_lit_entries,
        )
        _log_section_done("cross_domain_synthesis", sections["cross_domain_synthesis"])
    if not _thin:
        sections["novel_framework"] = build_novel_framework_section(accepted, matrix)
        _log_section_done("novel_framework (deterministic)", sections["novel_framework"])
        sections["framework_engagement"] = build_framework_engagement_section(
            accepted,
            background_refs=background_lit_entries or (),
        )
        _log_section_done(
            "framework_engagement (deterministic)",
            sections["framework_engagement"],
        )
    if not _thin or _discussion_requested:
        sections["discussion"] = await _write_scoped_section(
            name="discussion", heading="## Discussion",
            system_prompt=_prompts["discussion"], user_prompt=user,
            topic=topic, accepted=accepted, chain=chain, client=client,
            ledger=ledger, seed=seed,
            fallback_body="## Discussion\n\nThe interpretation remains cautious, limited, and context-dependent because the accepted evidence spans different populations, outcomes, and evidence tiers.\n",
            background_lit_entries=background_lit_entries,
        )
        _log_section_done("discussion", sections["discussion"])
    sections["limitations_full"] = await _write_anchored_section(
        name="limitations_full", heading="## Limitations",
        system_prompt=_prompts["limitations_full"], user_prompt=user,
        accepted=accepted, chain=chain, client=client, ledger=ledger,
        seed=seed,
        fallback_body="## Limitations\n\nInference is bounded by the accepted receipt set, outcome coverage, and source-traced numeric claims.\n",
        background_lit_entries=background_lit_entries,
    )
    if _thin:
        sections["limitations_full"] = _append_section_note(
            sections["limitations_full"], _thin_limitations_note(accepted),
        )
    _log_section_done("limitations_full", sections["limitations_full"])
    sections["conclusion"] = await _write_scoped_section(
        name="conclusion", heading="## Conclusion",
        system_prompt=_prompts["conclusion"], user_prompt=user,
        topic=topic, accepted=accepted, chain=chain, client=client,
        ledger=ledger, seed=seed,
        fallback_body="## Conclusion\n\nThe conclusion is limited to claims that survive receipt qualification, source-context checks, and final audit gates.\n",
        background_lit_entries=background_lit_entries,
    )
    if _thin:
        sections["conclusion"] = _append_section_note(
            sections["conclusion"], _thin_conclusion_note(accepted, matrix),
        )
    _log_section_done("conclusion", sections["conclusion"])
    sections["references_full"] = build_references_full_section(receipts)
    _log_section_done("references_full (deterministic)", sections["references_full"])

    # Fix #55 v2: orchestrator-side section-rerender backstop.
    # See agent/paper_writer_backstop.py for the per-section retry
    # logic. This is the FINAL retry layer (4th attempt) for any
    # audit-gated section that came in below floor. Single-shot to
    # bound wall time.
    if not _thin:
        from agent.paper_writer_backstop import apply_section_backstop
        sections = await apply_section_backstop(sections, user_prompt=user, section_prompts=_prompts, topic=topic, accepted=accepted, matrix=matrix, chain=chain, client=client, ledger=ledger, seed=seed, background_lit_entries=background_lit_entries, write_anchored_fn=_write_anchored_section, write_scoped_fn=_write_scoped_section)
    inference_note = (
        "**Author-inference boundary:** Mechanism-level explanations in this section "
        "are synthesis-author inferences unless directly attributed to an included "
        "source; they are not independently established causal findings."
    )
    for section_name, requested in (
        ("cross_domain_synthesis", _author_inference_cross_domain),
        ("discussion", _author_inference_discussion),
    ):
        if requested and section_name in sections:
            sections[section_name] = _append_section_note(sections[section_name], inference_note)
    if "discussion" in sections:
        from agent.paper_writer_backstop import repair_discussion_minimum_quality
        sections["discussion"] = repair_discussion_minimum_quality(
            sections["discussion"], thesis,
        )

    section_order = _THIN_BRIEF_SECTION_ORDER if _thin else _FULL_PAPER_SECTION_ORDER
    if _thin:
        split = section_order.index("limitations_full")
        optional = tuple(n for n in ("cross_domain_synthesis", "discussion") if n in sections)
        section_order = section_order[:split] + optional + section_order[split:]
    ordered = tuple(sections[n] for n in section_order if n in sections)
    body_md = title_md + "\n".join(s.body_md for s in ordered).rstrip() + "\n"
    body_md = _strip_rendered_citation_markers(body_md)
    return body_md, ordered


__all__ = [
    "derive_paper_tier",
    "build_methods_section",
    "build_references_full_section",
    "write_results_section",
    "render_full_paper",
]
