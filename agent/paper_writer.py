"""Full-paper writer (Day 10.16) — produces a 5-15k-word publishable
research synthesis from claim receipts + the Day 10 brief artifact.

Reviewer-aligned architecture (Day 10.15 external review):
  - The Day 10.x brief (`paper_synthesis.md`) stays as-is — it's the
    structured evidence layer with auditable trust-spine guarantees.
  - This module writes a NEW artifact (`full_paper.md`) alongside the
    brief, with the prose shape readers expect of a research synthesis.

Validation tiers (per section type):
  - ANCHORED      every sentence cites ≥1 receipt_id
                  (Abstract, Results, CrossDomainSynthesis,
                   LimitationsFull)
  - SCOPED        unanchored allowed; topic alias appears ≥2x per
                  paragraph; hedge phrase required; no novel numerics
                  (Introduction, Background, Discussion, Conclusion)
  - DETERMINISTIC rendered from constants/metadata, no LLM call
                  (Methods, ReferencesFull)

Trust spine preserved: ANCHORED sections still drop sentences whose
receipt_ids don't resolve, no novel numerics may enter, and SPAR-
rejected receipts remain quarantined (NOT cited in the prose; their
discussion happens explicitly in LimitationsFull).
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping, Sequence
from typing import Any

import httpx

from agent.llm_client import CallSpec, CostLedger, chat_json
from agent.paper_writer_builders import (
    build_anchored_from_parsed,
    build_results_from_parsed,
    build_scoped_from_parsed,
)
from agent.paper_writer_deterministic import (
    build_methods_section,
    build_references_full_section,
)
from agent.paper_writer_prompts import (
    ABSTRACT_SYSTEM_PROMPT,
    BACKGROUND_SYSTEM_PROMPT,
    CONCLUSION_SYSTEM_PROMPT,
    CROSS_DOMAIN_SYNTHESIS_SYSTEM_PROMPT,
    DISCUSSION_SYSTEM_PROMPT,
    INTRODUCTION_SYSTEM_PROMPT,
    LIMITATIONS_FULL_SYSTEM_PROMPT,
    RESULTS_SYSTEM_PROMPT,
)
from agent.synthesis_schemas import (
    ReceiptSummary,
    SectionName,
    SynthesisSection,
    SynthesisThesis,
    TensionMatrix,
)
from agent.synthesis_writer import filter_accepted

logger = logging.getLogger(__name__)


# Day 10.16d → 10.16h — per-LLM-call timeout. If a single section
# call (including chain fallback to Ministral) takes longer than this,
# we treat it as a hang and let the retry loop move on. Originally
# 180s, bumped to 240s in 10.16h: the inner mimo_timeout_sec is now
# 180s (was 60s — see settings.py rationale), so the outer needs to
# allow MiMo's full 180s PLUS some headroom for Ministral fallback if
# MiMo errors hard. 240s = MiMo full time + 60s for a fast Ministral
# round-trip.
PER_CALL_TIMEOUT_SEC = 240.0

PAPER_WRITER_VERSION = "paper-writer/2026-04-29-day10-16"

# Day 10.16c — per-section word-count budgets enforced AT CODE LEVEL.
# Prompts ask for length; this dict defines the floors that the writer
# enforces by retrying under-budget sections up to N times. If a section
# still falls short after retries, it lands as-is and the audit picks
# up the shortfall via the WORD_COUNT_FLOOR check.
SECTION_WORD_FLOORS: Mapping[str, int] = {
    "abstract": 250,
    "introduction": 1200,
    "background": 1000,
    "results": 2000,
    "cross_domain_synthesis": 700,
    "discussion": 1500,
    "limitations_full": 600,
    "conclusion": 300,
}

# Total full-paper floor — paper_writer's render_full_paper records
# the total word count and the auditor / script can ship-fail when
# the count is below this.
FULL_PAPER_WORD_FLOOR = 5000

# Max LLM retries per section when word count is below floor.
# Day 10.16d (reviewer-driven): cut from 2 → 1 retry. With 2 retries
# the worst-case render time was ~40min on 8 sections, exceeding
# operator patience and looking like a hang. One retry per section
# (so 2 attempts max) is the practical floor: an LLM that under-
# produces twice in a row is unlikely to magically expand on attempt 3.
SECTION_RETRY_BUDGET = 1


# --- Tier-aware paper-tier classification (reviewer-aligned) -----------


def derive_paper_tier(summary: ReceiptSummary) -> str:
    """Day 10.16 reviewer fix: split A1 by mechanistic-vs-clinical.

    A receipt's `evidence_tier` field on the summary is the original
    SPAR classification (A1 / A2 / B / C / mixed). For paper rendering,
    we add a finer paper-level tier so the writer can frame human-
    mechanistic RCTs differently from human-clinical RCTs:

      A1_clinical_RCT      direct human RCT, clinical/functional endpoint
                           (MASTERS muscle hypertrophy, MET-PREVENT
                           walk speed, TAME cardiovascular events)
      A2_human_mechanistic human RCT but mechanistic endpoint
                           (MILES muscle/adipose transcriptomics,
                           Konopka mitochondrial respiration)
      B1_review            review / meta-analysis
                           (Kulkarni 2022, Keys 2025, Mohammed 2021)
      C1_preclinical       animal / in-vitro mechanistic
      mixed                multi-source clusters

    Tier is derived from existing fields — no schema change.
    """
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


# Validation helpers + paragraph builders moved to
# agent/paper_writer_builders.py to keep this module under the 600
# per-file LOC cap.


# --- LLM section helper --------------------------------------------------


async def _call_llm_section(
    *,
    system_prompt: str,
    user_prompt: str,
    chain: Sequence[CallSpec],
    client: httpx.AsyncClient | None,
    ledger: CostLedger | None,
    seed: int | None,
) -> dict | None:
    """One LLM call returning a parsed JSON dict (or None if malformed
    or timed out). Per-call timeout enforced via asyncio.wait_for."""
    try:
        response = await asyncio.wait_for(
            chat_json(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                chain=chain,
                client=client,
                ledger=ledger,
                temperature=0.0,
                seed=seed,
            ),
            timeout=PER_CALL_TIMEOUT_SEC,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "paper_writer LLM call exceeded %.0fs timeout — moving on",
            PER_CALL_TIMEOUT_SEC,
        )
        return None
    if isinstance(response.parsed, dict):
        return response.parsed
    return None


def _build_user_prompt(
    receipts: Sequence[ReceiptSummary],
    rejected: Sequence[ReceiptSummary],
    matrix: TensionMatrix,
    thesis: SynthesisThesis,
    *,
    topic: str,
) -> str:
    """Common context block — receipt summaries + tensions + thesis +
    quarantined receipts. Each LLM section gets the same context;
    the system prompt does the section-specific work."""
    lines = [f"Topic: {topic}", "", "ACCEPTED RECEIPTS:"]
    for r in receipts:
        paper_tier = derive_paper_tier(r)
        # Day 10.17a: empty population_summary now means tier-gated-out
        # (mechanistic / indirect receipt) per agent/synthesis.py. Use
        # an explicit sentinel so the LLM hedges honestly instead of
        # hallucinate-filling a clinical population it doesn't have.
        pop = r.population_summary or (
            "N/A (mechanistic / indirect — no enrolled clinical population)"
        )
        lines.append(
            f"  - id: {r.receipt_id}\n"
            f"    paper_tier: {paper_tier}\n"
            f"    outcome_class: {r.outcome_class}\n"
            f"    directness: {r.directness}\n"
            f"    effect_direction: {r.effect_direction}\n"
            f"    canonical_trial_id: {r.canonical_trial_id or '(none)'}\n"
            f"    population: {pop}\n"
            f"    p_values: {list(r.p_values)}\n"
            f"    thesis: {r.thesis_text[:300]}"
        )
    if rejected:
        lines.extend(["", "QUARANTINED (SPAR-rejected) RECEIPTS:"])
        for r in rejected:
            lines.append(
                f"  - id: {r.receipt_id}\n"
                f"    verdict: {r.spar_verdict}\n"
                f"    outcome_class: {r.outcome_class}\n"
                f"    canonical_trial_id: {r.canonical_trial_id or '(none)'}\n"
                f"    thesis: {r.thesis_text[:200]}"
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
    return "\n".join(lines)


# --- Section builders ----------------------------------------------------


def _section_word_count(section: SynthesisSection) -> int:
    """Count words in the section body, excluding the heading line."""
    lines = section.body_md.split("\n")
    body = "\n".join(lines[1:]) if lines else ""
    return len(body.split())


def _build_retry_prompt(
    base_user_prompt: str,
    *,
    section_name: str,
    target_floor: int,
    last_word_count: int,
) -> str:
    """Append explicit retry guidance when a section under-produced.

    Empirically, LLMs default to concise output even when prompts
    request length. A retry that names the under-production and the
    floor is much more likely to hit the target than a fresh call.
    """
    return (
        base_user_prompt
        + f"\n\nRETRY GUIDANCE: the previous attempt at the "
        f"{section_name.upper()} section produced only {last_word_count} "
        f"words. The minimum word count is {target_floor}. "
        f"Re-write the section now with at least {target_floor} words "
        f"of substantive prose. Concretely: produce more paragraphs, "
        f"and make each paragraph longer (8-12 sentences each instead "
        f"of 3-5). Do NOT default to summary mode. The reader needs "
        f"the full publishable density."
    )


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
) -> SynthesisSection:
    """Build an ANCHORED section with code-level word-count retry.

    Day 10.16c: prompts ask for length but LLMs default to concise
    output. This wrapper enforces the floor at code level: if the
    rendered section is under SECTION_WORD_FLOORS[name], retry up to
    SECTION_RETRY_BUDGET times with a more aggressive expansion
    prompt. Pick the longest valid attempt across all retries."""
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
            return best
        # Below floor — prepare a retry prompt.
        current_prompt = _build_retry_prompt(
            user_prompt, section_name=str(name),
            target_floor=floor, last_word_count=words,
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
) -> SynthesisSection:
    """Build a SCOPED section with code-level word-count retry.

    See `_write_anchored_section` for the retry contract."""
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
            return best
        current_prompt = _build_retry_prompt(
            user_prompt, section_name=str(name),
            target_floor=floor, last_word_count=words,
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
) -> SynthesisSection:
    """ANCHORED multi-paragraph Results with code-level word retry.
    Each subsection has its own H3 heading. Each paragraph cites
    ≥1 accepted receipt. If overall Results word count is below
    SECTION_WORD_FLOORS['results'], retry up to N times."""
    user = _build_user_prompt(
        receipts, rejected, matrix, thesis, topic=topic,
    )
    fallback = (
        "## Results\n\n_LLM-generated results section failed validation; "
        "see Direct Evidence and Indirect / Mechanistic Evidence in the "
        "evidence brief (`paper_synthesis.md`) for the per-receipt "
        "summary._\n"
    )
    floor = SECTION_WORD_FLOORS.get("results", 0)
    best: SynthesisSection | None = None
    best_words = 0
    current_prompt = user
    for attempt in range(SECTION_RETRY_BUDGET + 1):
        parsed = await _call_llm_section(
            system_prompt=RESULTS_SYSTEM_PROMPT, user_prompt=current_prompt,
            chain=chain, client=client, ledger=ledger, seed=seed,
        )
        if not parsed:
            continue
        section = build_results_from_parsed(parsed, accepted=receipts)
        if section is None:
            continue
        words = _section_word_count(section)
        if words > best_words:
            best, best_words = section, words
        if best_words >= floor or floor == 0:
            return best
        current_prompt = _build_retry_prompt(
            user, section_name="results",
            target_floor=floor, last_word_count=words,
        )
    return best or SynthesisSection(
        name="results", body_md=fallback, anchors=(),
    )


# --- Top-level renderer --------------------------------------------------


_FULL_PAPER_SECTION_ORDER: tuple[SectionName, ...] = (
    "abstract",
    "introduction",
    "background",
    "methods",
    "results",
    "cross_domain_synthesis",
    "discussion",
    "limitations_full",
    "conclusion",
    "references_full",
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
) -> tuple[str, tuple[SynthesisSection, ...]]:
    """Render the full paper from accepted-receipt corpus + brief.

    Returns (body_md, sections_tuple) — the full markdown plus the
    per-section anchors so an audit pass can scan citation coverage.
    """
    accepted = list(filter_accepted(receipts))
    rejected = [r for r in receipts if r.spar_verdict not in (
        "accept_clean", "accept_caveated",
    )]
    user = _build_user_prompt(
        accepted, rejected, matrix, thesis, topic=topic,
    )
    title_md = (
        f"# Researka Synthesis: {topic.title()} — full paper\n\n"
        f"**Thesis:** {thesis.text}\n\n"
        f"**Submission:** `{submission_id}`\n\n"
    )
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
        system_prompt=ABSTRACT_SYSTEM_PROMPT, user_prompt=user,
        accepted=accepted, chain=chain, client=client, ledger=ledger,
        seed=seed,
        fallback_body="## Abstract\n\n_LLM-generated abstract failed validation; see Thesis above._\n",
    )
    _log_section_done("abstract", sections["abstract"])
    sections["introduction"] = await _write_scoped_section(
        name="introduction", heading="## Introduction",
        system_prompt=INTRODUCTION_SYSTEM_PROMPT, user_prompt=user,
        topic=topic, accepted=accepted, chain=chain, client=client,
        ledger=ledger, seed=seed,
        fallback_body="## Introduction\n\n_Introduction failed scoped validation._\n",
    )
    _log_section_done("introduction", sections["introduction"])
    sections["background"] = await _write_scoped_section(
        name="background", heading="## Background",
        system_prompt=BACKGROUND_SYSTEM_PROMPT, user_prompt=user,
        topic=topic, accepted=accepted, chain=chain, client=client,
        ledger=ledger, seed=seed,
        fallback_body="## Background\n\n_Background failed scoped validation._\n",
    )
    _log_section_done("background", sections["background"])
    sections["methods"] = build_methods_section(
        receipts, topic=topic, submission_id=submission_id,
    )
    _log_section_done("methods (deterministic)", sections["methods"])
    sections["results"] = await write_results_section(
        accepted, rejected, matrix, thesis,
        topic=topic, chain=chain, client=client, ledger=ledger, seed=seed,
    )
    _log_section_done("results", sections["results"])
    sections["cross_domain_synthesis"] = await _write_anchored_section(
        name="cross_domain_synthesis",
        heading="## Cross-Domain Synthesis",
        system_prompt=CROSS_DOMAIN_SYNTHESIS_SYSTEM_PROMPT,
        user_prompt=user,
        accepted=accepted, chain=chain, client=client, ledger=ledger,
        seed=seed,
        fallback_body="## Cross-Domain Synthesis\n\n_Cross-domain synthesis failed validation._\n",
    )
    _log_section_done("cross_domain_synthesis", sections["cross_domain_synthesis"])
    sections["discussion"] = await _write_scoped_section(
        name="discussion", heading="## Discussion",
        system_prompt=DISCUSSION_SYSTEM_PROMPT, user_prompt=user,
        topic=topic, accepted=accepted, chain=chain, client=client,
        ledger=ledger, seed=seed,
        fallback_body="## Discussion\n\n_Discussion failed scoped validation._\n",
    )
    _log_section_done("discussion", sections["discussion"])
    sections["limitations_full"] = await _write_anchored_section(
        name="limitations_full", heading="## Limitations",
        system_prompt=LIMITATIONS_FULL_SYSTEM_PROMPT, user_prompt=user,
        accepted=accepted, chain=chain, client=client, ledger=ledger,
        seed=seed,
        fallback_body="## Limitations\n\n_Limitations failed validation._\n",
    )
    _log_section_done("limitations_full", sections["limitations_full"])
    sections["conclusion"] = await _write_scoped_section(
        name="conclusion", heading="## Conclusion",
        system_prompt=CONCLUSION_SYSTEM_PROMPT, user_prompt=user,
        topic=topic, accepted=accepted, chain=chain, client=client,
        ledger=ledger, seed=seed,
        fallback_body="## Conclusion\n\n_Conclusion failed scoped validation._\n",
    )
    _log_section_done("conclusion", sections["conclusion"])
    sections["references_full"] = build_references_full_section(receipts)
    _log_section_done("references_full (deterministic)", sections["references_full"])
    ordered = tuple(sections[n] for n in _FULL_PAPER_SECTION_ORDER)
    body_md = title_md + "\n".join(s.body_md for s in ordered).rstrip() + "\n"
    return body_md, ordered


__all__ = [
    "PAPER_WRITER_VERSION",
    "derive_paper_tier",
    "build_methods_section",
    "build_references_full_section",
    "write_results_section",
    "render_full_paper",
]


# Suppressing unused-import warning — Mapping/Any kept for type-hint clarity.
_ = Mapping
_ = Any
