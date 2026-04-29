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

import re
from collections.abc import Mapping, Sequence
from typing import Any

import httpx

from agent.llm_client import CallSpec, CostLedger, chat_json
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
from agent.paper_writer_deterministic import (
    build_methods_section,
    build_references_full_section,
)
from agent.synthesis_schemas import (
    ReceiptSummary,
    SectionName,
    SynthesisClaimAnchor,
    SynthesisSection,
    SynthesisThesis,
    TensionMatrix,
)
from agent.synthesis_writer import filter_accepted

PAPER_WRITER_VERSION = "paper-writer/2026-04-29-day10-16"

# Numeric token regex (mirrors synthesis_writer / synthesis_thesis).
_NUMERIC_RE = re.compile(
    r"\b(?:p\s*[<=>]\s*0?\.\d+|"
    r"\d+(?:\.\d+)?\s*%|"
    r"(?:hr|or|rr|ahr|aor|arr|ηp[2²]|β)\s*[=:,\-]?\s*\d+(?:\.\d+)?"
    r")\b",
    re.IGNORECASE,
)

_HEDGE_PHRASES = (
    "may ", "appears to", "evidence suggests", "remains uncertain",
    "has been proposed", "the question of whether", "we interpret",
    "this suggests", "one reading is", "the evidence supports",
    "in our view", "remains to be confirmed", "is not yet established",
    "is unresolved", "is unclear", "could ", "might ",
    "proposed as", "hypothesized", "tentative",
)


def _normalize(text: str) -> str:
    return " ".join(text.replace("·", ".").split()).lower()


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


# --- Validation helpers --------------------------------------------------


def _check_anchored_paragraph(
    text: str,
    receipt_ids: Sequence[str],
    accepted_ids: set[str],
    accepted_corpus_norm: str,
) -> tuple[bool, str]:
    """Validate an ANCHORED paragraph: must cite ≥1 accepted receipt,
    no novel numerics."""
    if not text.strip():
        return False, "empty_paragraph"
    cited = [r for r in receipt_ids if r in accepted_ids]
    if not cited:
        return False, f"no_accepted_anchor:{list(receipt_ids)}"
    for m in _NUMERIC_RE.finditer(text):
        tok = _normalize(m.group(0))
        if tok not in accepted_corpus_norm:
            return False, f"novel_numeric:{tok!r}"
    return True, "ok"


def _check_scoped_paragraph(
    text: str,
    topic: str,
    receipt_ids: Sequence[str],
    accepted_corpus_norm: str,
) -> tuple[bool, str]:
    """Validate a SCOPED paragraph: topic mentioned ≥2x, contains a
    hedge phrase, no novel numerics. Receipt anchoring is OPTIONAL
    here (this is framing prose, not evidence reporting)."""
    if not text.strip():
        return False, "empty_paragraph"
    norm = _normalize(text)
    topic_norm = _normalize(topic)
    if topic_norm and norm.count(topic_norm) < 2:
        return False, f"topic_alias_under_count:<2:{topic_norm!r}"
    if not any(h in norm for h in _HEDGE_PHRASES):
        return False, "missing_hedge_phrase"
    for m in _NUMERIC_RE.finditer(text):
        tok = _normalize(m.group(0))
        if tok not in accepted_corpus_norm:
            return False, f"novel_numeric:{tok!r}"
    return True, "ok"


def _accepted_corpus_norm(receipts: Sequence[ReceiptSummary]) -> str:
    """Concatenated normalized text of all receipts' p_values + thesis.
    Used for novel-numeric checks."""
    parts: list[str] = []
    for r in receipts:
        parts.extend(r.p_values)
        parts.append(r.thesis_text)
    return _normalize(" ".join(parts))


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
    response = await chat_json(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        chain=chain,
        client=client,
        ledger=ledger,
        temperature=0.0,
        seed=seed,
    )
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
        lines.append(
            f"  - id: {r.receipt_id}\n"
            f"    paper_tier: {paper_tier}\n"
            f"    outcome_class: {r.outcome_class}\n"
            f"    directness: {r.directness}\n"
            f"    effect_direction: {r.effect_direction}\n"
            f"    canonical_trial_id: {r.canonical_trial_id or '(none)'}\n"
            f"    population: {r.population_summary}\n"
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
    """Build a section that requires every paragraph to cite ≥1
    accepted receipt. Drops invalid paragraphs; falls back to a
    deterministic stub when nothing survives."""
    parsed = await _call_llm_section(
        system_prompt=system_prompt, user_prompt=user_prompt,
        chain=chain, client=client, ledger=ledger, seed=seed,
    )
    if not parsed:
        return SynthesisSection(name=name, body_md=fallback_body, anchors=())
    accepted_ids = {r.receipt_id for r in accepted}
    corpus_norm = _accepted_corpus_norm(accepted)
    paragraphs = parsed.get("paragraphs") or parsed.get("subsections") or []
    body_lines: list[str] = [heading, ""]
    anchors: list[SynthesisClaimAnchor] = []
    for entry in paragraphs:
        if not isinstance(entry, dict):
            continue
        # Results section uses {subsections: [{outcome_class, heading, paragraphs}]}
        if "subsections" in (parsed or {}):
            pass  # handled by the dedicated results path
        text = entry.get("text") or entry.get("sentence") or ""
        rids = entry.get("receipt_ids") or []
        if not isinstance(text, str) or not isinstance(rids, list):
            continue
        ok, _reason = _check_anchored_paragraph(
            text, [str(r) for r in rids], accepted_ids, corpus_norm,
        )
        if not ok:
            continue
        body_lines.append(text.strip())
        body_lines.append("")
        cite_str = ", ".join(f"`{i}`" for i in rids)
        body_lines.append(f"  _Cited: {cite_str}_")
        body_lines.append("")
        anchors.append(SynthesisClaimAnchor(
            sentence=text.strip(),
            receipt_ids=tuple(str(r) for r in rids),
            numerics=tuple(
                _normalize(m.group(0))
                for m in _NUMERIC_RE.finditer(text)
            ),
        ))
    if not anchors:
        return SynthesisSection(name=name, body_md=fallback_body, anchors=())
    return SynthesisSection(
        name=name, body_md="\n".join(body_lines).rstrip() + "\n",
        anchors=tuple(anchors),
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
    """Build a SCOPED section (Introduction, Background, Discussion,
    Conclusion). Topic alias and hedge phrase required per paragraph;
    receipt citation is OPTIONAL but preferred."""
    parsed = await _call_llm_section(
        system_prompt=system_prompt, user_prompt=user_prompt,
        chain=chain, client=client, ledger=ledger, seed=seed,
    )
    if not parsed:
        return SynthesisSection(name=name, body_md=fallback_body, anchors=())
    corpus_norm = _accepted_corpus_norm(accepted)
    paragraphs = parsed.get("paragraphs") or []
    body_lines: list[str] = [heading, ""]
    anchors: list[SynthesisClaimAnchor] = []
    for entry in paragraphs:
        if not isinstance(entry, dict):
            continue
        text = entry.get("text") or ""
        rids = entry.get("receipt_ids") or []
        if not isinstance(text, str) or not isinstance(rids, list):
            continue
        ok, _reason = _check_scoped_paragraph(
            text, topic, [str(r) for r in rids], corpus_norm,
        )
        if not ok:
            continue
        body_lines.append(text.strip())
        body_lines.append("")
        if rids:
            cite_str = ", ".join(f"`{i}`" for i in rids)
            body_lines.append(f"  _Cited: {cite_str}_")
            body_lines.append("")
        anchors.append(SynthesisClaimAnchor(
            sentence=text.strip(),
            receipt_ids=tuple(str(r) for r in rids),
            numerics=(),
        ))
    if not anchors:
        return SynthesisSection(name=name, body_md=fallback_body, anchors=())
    return SynthesisSection(
        name=name, body_md="\n".join(body_lines).rstrip() + "\n",
        anchors=tuple(anchors),
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
    """ANCHORED multi-paragraph Results, organized by outcome class.
    Each subsection has its own H3 heading. Each paragraph cites
    ≥1 accepted receipt."""
    user = _build_user_prompt(
        receipts, rejected, matrix, thesis, topic=topic,
    )
    parsed = await _call_llm_section(
        system_prompt=RESULTS_SYSTEM_PROMPT, user_prompt=user,
        chain=chain, client=client, ledger=ledger, seed=seed,
    )
    fallback = (
        "## Results\n\n_LLM-generated results section failed validation; "
        "see Direct Evidence and Indirect / Mechanistic Evidence in the "
        "evidence brief (`paper_synthesis.md`) for the per-receipt "
        "summary._\n"
    )
    if not parsed:
        return SynthesisSection(
            name="results", body_md=fallback, anchors=(),
        )
    accepted_ids = {r.receipt_id for r in receipts}
    corpus_norm = _accepted_corpus_norm(receipts)
    body_lines: list[str] = ["## Results", ""]
    anchors: list[SynthesisClaimAnchor] = []
    for sub in parsed.get("subsections") or []:
        if not isinstance(sub, dict):
            continue
        h3 = sub.get("heading") or sub.get("outcome_class") or ""
        sub_paragraphs = sub.get("paragraphs") or []
        sub_body: list[str] = [f"### {h3}", ""]
        sub_anchors: list[SynthesisClaimAnchor] = []
        for entry in sub_paragraphs:
            if not isinstance(entry, dict):
                continue
            text = entry.get("text") or ""
            rids = entry.get("receipt_ids") or []
            if not isinstance(text, str) or not isinstance(rids, list):
                continue
            ok, _reason = _check_anchored_paragraph(
                text, [str(r) for r in rids], accepted_ids, corpus_norm,
            )
            if not ok:
                continue
            sub_body.append(text.strip())
            sub_body.append("")
            cite_str = ", ".join(f"`{i}`" for i in rids)
            sub_body.append(f"  _Cited: {cite_str}_")
            sub_body.append("")
            sub_anchors.append(SynthesisClaimAnchor(
                sentence=text.strip(),
                receipt_ids=tuple(str(r) for r in rids),
                numerics=tuple(
                    _normalize(m.group(0))
                    for m in _NUMERIC_RE.finditer(text)
                ),
            ))
        if sub_anchors:
            body_lines.extend(sub_body)
            anchors.extend(sub_anchors)
    if not anchors:
        return SynthesisSection(
            name="results", body_md=fallback, anchors=(),
        )
    return SynthesisSection(
        name="results", body_md="\n".join(body_lines).rstrip() + "\n",
        anchors=tuple(anchors),
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
    sections["abstract"] = await _write_anchored_section(
        name="abstract", heading="## Abstract",
        system_prompt=ABSTRACT_SYSTEM_PROMPT, user_prompt=user,
        accepted=accepted, chain=chain, client=client, ledger=ledger,
        seed=seed,
        fallback_body="## Abstract\n\n_LLM-generated abstract failed validation; see Thesis above._\n",
    )
    sections["introduction"] = await _write_scoped_section(
        name="introduction", heading="## Introduction",
        system_prompt=INTRODUCTION_SYSTEM_PROMPT, user_prompt=user,
        topic=topic, accepted=accepted, chain=chain, client=client,
        ledger=ledger, seed=seed,
        fallback_body="## Introduction\n\n_Introduction failed scoped validation._\n",
    )
    sections["background"] = await _write_scoped_section(
        name="background", heading="## Background",
        system_prompt=BACKGROUND_SYSTEM_PROMPT, user_prompt=user,
        topic=topic, accepted=accepted, chain=chain, client=client,
        ledger=ledger, seed=seed,
        fallback_body="## Background\n\n_Background failed scoped validation._\n",
    )
    sections["methods"] = build_methods_section(
        receipts, topic=topic, submission_id=submission_id,
    )
    sections["results"] = await write_results_section(
        accepted, rejected, matrix, thesis,
        topic=topic, chain=chain, client=client, ledger=ledger, seed=seed,
    )
    sections["cross_domain_synthesis"] = await _write_anchored_section(
        name="cross_domain_synthesis",
        heading="## Cross-Domain Synthesis",
        system_prompt=CROSS_DOMAIN_SYNTHESIS_SYSTEM_PROMPT,
        user_prompt=user,
        accepted=accepted, chain=chain, client=client, ledger=ledger,
        seed=seed,
        fallback_body="## Cross-Domain Synthesis\n\n_Cross-domain synthesis failed validation._\n",
    )
    sections["discussion"] = await _write_scoped_section(
        name="discussion", heading="## Discussion",
        system_prompt=DISCUSSION_SYSTEM_PROMPT, user_prompt=user,
        topic=topic, accepted=accepted, chain=chain, client=client,
        ledger=ledger, seed=seed,
        fallback_body="## Discussion\n\n_Discussion failed scoped validation._\n",
    )
    sections["limitations_full"] = await _write_anchored_section(
        name="limitations_full", heading="## Limitations",
        system_prompt=LIMITATIONS_FULL_SYSTEM_PROMPT, user_prompt=user,
        accepted=accepted, chain=chain, client=client, ledger=ledger,
        seed=seed,
        fallback_body="## Limitations\n\n_Limitations failed validation._\n",
    )
    sections["conclusion"] = await _write_scoped_section(
        name="conclusion", heading="## Conclusion",
        system_prompt=CONCLUSION_SYSTEM_PROMPT, user_prompt=user,
        topic=topic, accepted=accepted, chain=chain, client=client,
        ledger=ledger, seed=seed,
        fallback_body="## Conclusion\n\n_Conclusion failed scoped validation._\n",
    )
    sections["references_full"] = build_references_full_section(receipts)
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
