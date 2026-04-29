"""Synthesis writer — Day 10.4 sectioned paper renderer.

Given N claim receipts + a TensionMatrix + a SynthesisThesis (from
Day 10.2 + 10.3), produce a `SynthesisPaper` whose `body_md` is the
full markdown for `paper_synthesis.md`.

Section split (matches `agent/synthesis_schemas.SectionName`):

  Section              Source            Trust contract
  -------              ------            --------------
  title                LLM (thesis)      from SynthesisThesis (already validated)
  thesis               deterministic     wraps SynthesisThesis.text + receipt list
  evidence_summary     deterministic     table rendered from receipts
  direct_evidence      deterministic     bullet list from direct receipts
  indirect_evidence    deterministic     bullet list from mechanistic / review
  tensions             LLM-anchored      one paragraph per non-orthogonal tension
  synthesis            LLM-anchored      2-4 paragraphs cross-receipt synthesis
  limitations          LLM-anchored      bulleted list with receipt anchors
  spar_adjudication    deterministic     receipt-level SPAR votes table
  references           deterministic     all source papers cited

LLM-anchored sections share one validator: `validate_anchored_sentence`
checks (a) `receipt_ids` is a subset of input ids; (b) all numerics
appear in at least one receipt's p_values + thesis_text. Sentences
that fail are dropped from the section; if the section ends up empty
the writer falls back to a deterministic stub paragraph so the paper
still ships.

Same temperature-0 + seed determinism contract as Day 9.4 / 10.3.
"""
from __future__ import annotations

import re
from collections.abc import Sequence

import httpx

from agent.llm_client import CallSpec, CostLedger, chat_json
from agent.synthesis_schemas import (
    ReceiptSummary,
    SectionName,
    SynthesisClaimAnchor,
    SynthesisPaper,
    SynthesisSection,
    SynthesisThesis,
    TensionMatrix,
)
from agent.synthesis_writer_prompts import (
    LIMITATIONS_SYSTEM_PROMPT as _LIMITATIONS_SYSTEM_PROMPT,
    SYNTHESIS_SYSTEM_PROMPT as _SYNTHESIS_SYSTEM_PROMPT,
    TENSIONS_SYSTEM_PROMPT as _TENSIONS_SYSTEM_PROMPT,
)

__all__ = [
    "WRITER_VERSION",
    "ACCEPTED_VERDICTS",
    "is_accepted_for_synthesis",
    "filter_accepted",
    "render_synthesis_paper",
    "build_evidence_summary_section",
    "build_direct_evidence_section",
    "build_indirect_evidence_section",
    "build_rejected_evidence_section",
    "build_references_section",
    "build_spar_adjudication_section",
    "build_thesis_section",
    "build_title_section",
    "write_tensions_section",
    "write_synthesis_section",
    "write_limitations_section",
    "validate_anchored_sentence",
]

WRITER_VERSION = "synthesis-writer/2026-04-29-day10-10"

# Day 10.10 reviewer P1: trust-spine ordering. SPAR is the gate; only
# receipts that survive SPAR adjudication may be cited as evidence in
# synthesis. Rejected receipts are quarantined in their own section
# for transparency but do NOT contribute to direct/indirect/synthesis
# bullets, the thesis tournament, or the cross-source gate.
ACCEPTED_VERDICTS: frozenset[str] = frozenset({
    "accept_clean", "accept_caveated",
})


def is_accepted_for_synthesis(receipt: ReceiptSummary) -> bool:
    """Trust-spine gate: a receipt is eligible to be cited as evidence
    in the synthesis layer iff SPAR accepted it."""
    return receipt.spar_verdict in ACCEPTED_VERDICTS


def filter_accepted(
    receipts: Sequence[ReceiptSummary],
) -> tuple[ReceiptSummary, ...]:
    """Subset to the SPAR-accepted slice. Order-preserving."""
    return tuple(r for r in receipts if is_accepted_for_synthesis(r))

# Numeric pattern (mirrors synthesis_thesis._NUMERIC_TOKEN_RE).
_NUMERIC_RE = re.compile(
    r"\b(?:p\s*[<=>]\s*0?\.\d+|"
    r"\d+(?:\.\d+)?\s*%|"
    r"(?:hr|or|rr|ahr|aor|arr|ηp[2²]|β)\s*[=:,\-]?\s*\d+(?:\.\d+)?"
    r")\b",
    re.IGNORECASE,
)


def _normalize(text: str) -> str:
    return " ".join(text.replace("·", ".").split()).lower()


# --- Validators -----------------------------------------------------------


def validate_anchored_sentence(
    sentence: str,
    referenced_ids: Sequence[str],
    *,
    receipts: Sequence[ReceiptSummary],
) -> tuple[bool, str]:
    """Return (passed, reason). Used by every LLM-driven section to
    drop sentences that violate the trust contract."""
    if not sentence.strip():
        return False, "empty_sentence"
    receipt_ids = {r.receipt_id for r in receipts}
    unknown = set(referenced_ids) - receipt_ids
    if unknown:
        return False, f"unknown_receipt_ids:{sorted(unknown)}"
    if not referenced_ids:
        return False, "no_receipt_anchor"
    # Numeric check
    receipt_numeric_corpus = _normalize(" ".join(
        " ".join(r.p_values) + " " + r.thesis_text
        for r in receipts
    ))
    for m in _NUMERIC_RE.finditer(sentence):
        tok = _normalize(m.group(0))
        if tok not in receipt_numeric_corpus:
            return False, f"novel_numeric:{tok!r}"
    return True, "ok"


# --- Deterministic sections ----------------------------------------------


def build_title_section(thesis: SynthesisThesis, *, topic: str) -> SynthesisSection:
    """The title is the thesis text used as a one-line H1. Anchors map
    to the thesis's referenced receipts."""
    body = f"# {thesis.text}\n"
    anchors = (
        SynthesisClaimAnchor(
            sentence=thesis.text,
            receipt_ids=thesis.receipt_ids_referenced,
            numerics=tuple(_normalize(m.group(0)) for m in _NUMERIC_RE.finditer(thesis.text)),
        ),
    )
    return SynthesisSection(name="title", body_md=body, anchors=anchors)


def build_thesis_section(thesis: SynthesisThesis) -> SynthesisSection:
    """Render the thesis section: thesis sentence + which receipts it
    references + which tensions it addresses."""
    refs_str = ", ".join(thesis.receipt_ids_referenced) or "(none)"
    tensions_lines = "\n".join(
        f"  - {t}" for t in thesis.tensions_addressed
    ) or "  (no tensions in matrix)"
    body = (
        f"## Thesis\n\n"
        f"{thesis.text}\n\n"
        f"**Receipts integrated:** {refs_str}\n\n"
        f"**Tensions addressed:**\n{tensions_lines}\n\n"
        f"**Picker rationale:** {thesis.picker_rationale}\n"
    )
    anchors = (
        SynthesisClaimAnchor(
            sentence=thesis.text,
            receipt_ids=thesis.receipt_ids_referenced,
            numerics=(),
        ),
    )
    return SynthesisSection(name="thesis", body_md=body, anchors=anchors)


def build_evidence_summary_section(receipts: Sequence[ReceiptSummary]) -> SynthesisSection:
    """Render a markdown table summarizing all receipts. Deterministic."""
    rows = ["| Receipt | Trial | Outcome | Tier | Directness | Effect | SPAR |",
            "|---|---|---|---|---|---|---|"]
    for r in sorted(receipts, key=lambda x: x.receipt_id):
        trial = r.canonical_trial_id or "—"
        rows.append(
            f"| `{r.receipt_id}` | {trial} | {r.outcome_class} | "
            f"{r.evidence_tier} | {r.directness} | {r.effect_direction} | "
            f"{r.spar_verdict} |"
        )
    body = "## Evidence Summary\n\n" + "\n".join(rows) + "\n"
    return SynthesisSection(name="evidence_summary", body_md=body, anchors=())


def build_direct_evidence_section(receipts: Sequence[ReceiptSummary]) -> SynthesisSection:
    """Bullet list of SPAR-ACCEPTED direct receipts. Day 10.10: receipts
    that SPAR rejected are not evidence — they appear in the Rejected /
    Contested Evidence quarantine section, not here."""
    accepted = filter_accepted(receipts)
    direct = [r for r in accepted if r.directness == "direct"]
    if not direct:
        body = (
            "## Direct Evidence\n\n"
            "_No SPAR-accepted direct (RCT-tier) receipts in this corpus._\n"
        )
        return SynthesisSection(name="direct_evidence", body_md=body, anchors=())
    lines = ["## Direct Evidence\n"]
    for r in sorted(direct, key=lambda x: (x.outcome_class, x.receipt_id)):
        pv_str = (
            f" ({', '.join(r.p_values)})" if r.p_values else ""
        )
        lines.append(
            f"- **{r.receipt_id}** ({r.outcome_class}, {r.evidence_tier}, "
            f"{r.spar_verdict}): {r.thesis_text}{pv_str}"
        )
    body = "\n".join(lines) + "\n"
    return SynthesisSection(name="direct_evidence", body_md=body, anchors=())


def build_indirect_evidence_section(receipts: Sequence[ReceiptSummary]) -> SynthesisSection:
    """Bullet list of SPAR-ACCEPTED mechanistic + indirect receipts.
    Day 10.10 trust-spine ordering — see `build_direct_evidence_section`."""
    accepted = filter_accepted(receipts)
    indirect = [
        r for r in accepted
        if r.directness in ("mechanistic", "indirect")
    ]
    if not indirect:
        body = (
            "## Indirect / Mechanistic Evidence\n\n"
            "_No SPAR-accepted mechanistic or indirect receipts in this corpus._\n"
        )
        return SynthesisSection(name="indirect_evidence", body_md=body, anchors=())
    lines = ["## Indirect / Mechanistic Evidence\n"]
    for r in sorted(indirect, key=lambda x: (x.directness, x.receipt_id)):
        lines.append(
            f"- **{r.receipt_id}** ({r.outcome_class}, {r.directness}, "
            f"{r.spar_verdict}): {r.thesis_text}"
        )
    body = "\n".join(lines) + "\n"
    return SynthesisSection(name="indirect_evidence", body_md=body, anchors=())


def build_rejected_evidence_section(
    receipts: Sequence[ReceiptSummary],
) -> SynthesisSection:
    """Day 10.10 — quarantine zone for SPAR-rejected receipts.

    Trust-spine ordering: SPAR is the gate. Rejected receipts are NOT
    cited as evidence in the synthesis (no thesis tournament input,
    no direct/indirect bullets, no synthesis paragraph anchors). They
    are listed here for transparency — a reviewer can see WHAT was in
    the corpus and WHY each rejected one was excluded — without those
    receipts being granted evidentiary weight.
    """
    rejected = [r for r in receipts if not is_accepted_for_synthesis(r)]
    if not rejected:
        body = (
            "## Rejected / Contested Evidence\n\n"
            "_All receipts in this corpus passed SPAR adjudication; "
            "nothing to quarantine._\n"
        )
        return SynthesisSection(name="rejected_evidence", body_md=body, anchors=())
    lines = [
        "## Rejected / Contested Evidence\n",
        "_The receipts below were retrieved and clustered but rejected "
        "by SPAR. Per Day 10.10 trust-spine ordering, they are listed "
        "here for transparency but NOT cited as evidence in the thesis, "
        "synthesis, tensions, or limitations sections._\n",
    ]
    for r in sorted(rejected, key=lambda x: (x.spar_verdict, x.receipt_id)):
        trial = r.canonical_trial_id or "—"
        lines.append(
            f"- **{r.receipt_id}** "
            f"(verdict: `{r.spar_verdict}`, trial: {trial}, "
            f"outcome: {r.outcome_class}, directness: {r.directness}, "
            f"failed traces: {r.n_failed_traces}/{r.n_claims}): "
            f"{r.thesis_text}"
        )
    body = "\n".join(lines) + "\n"
    return SynthesisSection(name="rejected_evidence", body_md=body, anchors=())


def build_spar_adjudication_section(
    receipts: Sequence[ReceiptSummary],
) -> SynthesisSection:
    """Receipt-level SPAR verdicts in a table. Deterministic."""
    rows = ["| Receipt | SPAR verdict | Failed traces | n_claims |",
            "|---|---|---|---|"]
    for r in sorted(receipts, key=lambda x: x.receipt_id):
        rows.append(
            f"| `{r.receipt_id}` | {r.spar_verdict} | "
            f"{r.n_failed_traces} | {r.n_claims} |"
        )
    body = "## SPAR Adjudication\n\n" + "\n".join(rows) + "\n"
    return SynthesisSection(name="spar_adjudication", body_md=body, anchors=())


def build_references_section(receipts: Sequence[ReceiptSummary]) -> SynthesisSection:
    """Deterministic reference list. Each receipt contributes one line:
    its receipt_id + canonical_trial_id + thesis_text excerpt. Real
    DOI / PMID lookups would require reading evidence_cards.json; for
    now this is the receipt-level shape — sufficient for the audit."""
    lines = ["## References\n"]
    for i, r in enumerate(sorted(receipts, key=lambda x: x.receipt_id), 1):
        trial = f" (Trial: {r.canonical_trial_id})" if r.canonical_trial_id else ""
        excerpt = r.thesis_text[:140].rstrip()
        lines.append(f"[{i}] `{r.receipt_id}`{trial}: {excerpt}")
    body = "\n".join(lines) + "\n"
    return SynthesisSection(name="references", body_md=body, anchors=())


# --- LLM-anchored sections ------------------------------------------------
# System prompts (TENSIONS / SYNTHESIS / LIMITATIONS) live in
# `agent/synthesis_writer_prompts.py` to keep this module under the
# per-file LOC cap. They are imported as module-level aliases above.


def _parse_paragraphs(parsed: dict) -> list[dict]:
    """Extract the 'paragraphs' list from an LLM response. Defensive —
    returns [] when malformed."""
    raw = parsed.get("paragraphs") if isinstance(parsed, dict) else None
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for p in raw:
        if not isinstance(p, dict):
            continue
        sentence = p.get("sentence")
        ids = p.get("receipt_ids", [])
        if isinstance(sentence, str) and isinstance(ids, list):
            out.append({
                "sentence": sentence.strip(),
                "receipt_ids": tuple(
                    str(i) for i in ids if isinstance(i, str)
                ),
            })
    return out


def _build_anchored_section(
    name: SectionName,
    heading: str,
    paragraphs: Sequence[dict],
    receipts: Sequence[ReceiptSummary],
    *,
    fallback_body: str,
) -> SynthesisSection:
    """Validate each paragraph's anchor, drop failures, render
    surviving sentences as bullets. If nothing survives, render the
    fallback body deterministically.

    Day 10.10: REVERTED Day 10.9's auto-prefix transition logic. The
    reviewer correctly observed that prepending "Mechanistically, " /
    "By contrast, " is cosmetic — it games the Q3 audit without
    addressing the underlying synthesis quality. If the LLM doesn't
    produce real transitions, the audit should fail Q3 and the
    operator should fix the prompt or the corpus, not the markdown.
    """
    valid_anchors: list[SynthesisClaimAnchor] = []
    body_lines: list[str] = []
    for p in paragraphs:
        sentence = p["sentence"]
        ok, _reason = validate_anchored_sentence(
            sentence, p["receipt_ids"], receipts=receipts,
        )
        if not ok:
            continue
        numerics = tuple(
            _normalize(m.group(0))
            for m in _NUMERIC_RE.finditer(sentence)
        )
        valid_anchors.append(SynthesisClaimAnchor(
            sentence=sentence,
            receipt_ids=p["receipt_ids"],
            numerics=numerics,
        ))
        cite_str = ", ".join(f"`{i}`" for i in p["receipt_ids"])
        body_lines.append(f"- {sentence} ({cite_str})")
    if not valid_anchors:
        return SynthesisSection(name=name, body_md=fallback_body, anchors=())
    body = f"{heading}\n\n" + "\n".join(body_lines) + "\n"
    return SynthesisSection(
        name=name, body_md=body, anchors=tuple(valid_anchors),
    )


async def _llm_section(
    *,
    system_prompt: str,
    user_prompt: str,
    chain: Sequence[CallSpec],
    client: httpx.AsyncClient | None,
    ledger: CostLedger | None,
    seed: int | None,
) -> list[dict]:
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
    return _parse_paragraphs(
        response.parsed if isinstance(response.parsed, dict) else {},
    )


def _build_user_prompt(
    receipts: Sequence[ReceiptSummary],
    matrix: TensionMatrix,
    thesis: SynthesisThesis,
    *,
    topic: str,
) -> str:
    """Common user prompt — receipts + tensions + thesis. Each LLM
    call gets the same context block, only system prompt differs."""
    lines = [f"Topic: {topic}", "", "RECEIPTS:"]
    for r in receipts:
        lines.append(
            f"  - id: {r.receipt_id}; outcome: {r.outcome_class}; "
            f"directness: {r.directness}; tier: {r.evidence_tier}; "
            f"effect: {r.effect_direction}; "
            f"p_values: {list(r.p_values)}; "
            f"thesis: {r.thesis_text[:200]}"
        )
    lines.extend(["", "TENSIONS (non-orthogonal):"])
    non_orth = matrix.non_orthogonal()
    if not non_orth:
        lines.append("  (none — receipts cover distinct outcomes)")
    else:
        for t in non_orth:
            lines.append(
                f"  - {t.kind} ({t.outcome_class}, severity {t.severity}): "
                f"{t.summary}"
            )
    lines.extend([
        "",
        "THESIS:",
        f"  {thesis.text}",
        f"  (references: {list(thesis.receipt_ids_referenced)})",
    ])
    return "\n".join(lines)


async def write_tensions_section(
    receipts: Sequence[ReceiptSummary],
    matrix: TensionMatrix,
    thesis: SynthesisThesis,
    *,
    topic: str,
    chain: Sequence[CallSpec],
    client: httpx.AsyncClient | None = None,
    ledger: CostLedger | None = None,
    seed: int | None = None,
) -> SynthesisSection:
    non_orth = matrix.non_orthogonal()
    if not non_orth:
        body = (
            "## Tensions\n\n"
            "_No non-orthogonal tensions detected — the receipts in this "
            "corpus cover distinct outcome classes._\n"
        )
        return SynthesisSection(name="tensions", body_md=body, anchors=())
    user = _build_user_prompt(receipts, matrix, thesis, topic=topic)
    paragraphs = await _llm_section(
        system_prompt=_TENSIONS_SYSTEM_PROMPT, user_prompt=user,
        chain=chain, client=client, ledger=ledger, seed=seed,
    )
    fallback = (
        "## Tensions\n\n"
        "_LLM-generated tensions failed validation; matrix surfaces "
        f"{len(non_orth)} non-orthogonal pair(s) — see Evidence Summary._\n"
    )
    return _build_anchored_section(
        "tensions", "## Tensions", paragraphs, receipts,
        fallback_body=fallback,
    )


async def write_synthesis_section(
    receipts: Sequence[ReceiptSummary],
    matrix: TensionMatrix,
    thesis: SynthesisThesis,
    *,
    topic: str,
    chain: Sequence[CallSpec],
    client: httpx.AsyncClient | None = None,
    ledger: CostLedger | None = None,
    seed: int | None = None,
) -> SynthesisSection:
    user = _build_user_prompt(receipts, matrix, thesis, topic=topic)
    paragraphs = await _llm_section(
        system_prompt=_SYNTHESIS_SYSTEM_PROMPT, user_prompt=user,
        chain=chain, client=client, ledger=ledger, seed=seed,
    )
    fallback = (
        "## Synthesis\n\n"
        "_LLM-generated synthesis failed validation. The thesis above "
        "names the integrating finding; receipt-level claims are in "
        "Direct Evidence and Indirect / Mechanistic Evidence sections._\n"
    )
    return _build_anchored_section(
        "synthesis", "## Synthesis", paragraphs, receipts,
        fallback_body=fallback,
    )


async def write_limitations_section(
    receipts: Sequence[ReceiptSummary],
    matrix: TensionMatrix,
    thesis: SynthesisThesis,
    *,
    topic: str,
    chain: Sequence[CallSpec],
    client: httpx.AsyncClient | None = None,
    ledger: CostLedger | None = None,
    seed: int | None = None,
) -> SynthesisSection:
    user = _build_user_prompt(receipts, matrix, thesis, topic=topic)
    paragraphs = await _llm_section(
        system_prompt=_LIMITATIONS_SYSTEM_PROMPT, user_prompt=user,
        chain=chain, client=client, ledger=ledger, seed=seed,
    )
    fallback = (
        "## Limitations\n\n"
        "- Single-trial theses risk generalization beyond the studied "
        "population.\n"
        "- Mechanistic / indirect evidence does not directly demonstrate "
        "human clinical benefit.\n"
        "- The LLM-generated limitations failed validation; this stub "
        "is a conservative placeholder.\n"
    )
    return _build_anchored_section(
        "limitations", "## Limitations", paragraphs, receipts,
        fallback_body=fallback,
    )


# --- Top-level renderer ---------------------------------------------------


_SECTION_ORDER: tuple[SectionName, ...] = (
    "title",
    "thesis",
    "evidence_summary",
    "direct_evidence",
    "indirect_evidence",
    "rejected_evidence",   # Day 10.10 quarantine — listed but not cited
    "tensions",
    "synthesis",
    "limitations",
    "spar_adjudication",
    "references",
)


async def render_synthesis_paper(
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
) -> SynthesisPaper:
    """Render the full synthesis paper.

    Deterministic sections render first (no LLM cost). LLM sections
    run sequentially (could parallelize in a follow-on; keeping
    sequential for now so cost ledger entries are deterministic in
    order — useful for the audit step).

    Returns a SynthesisPaper. body_md is the full markdown for
    `paper_synthesis.md`. The 8-receipt invariants
    (`assert_synthesis_invariants`) are not enforced HERE — that's
    Day 10.5's orchestrator responsibility before the file is written.
    """
    # Day 10.10 reviewer P1: trust-spine ordering. The evidence_summary
    # table and SPAR adjudication / references / quarantine sections
    # cover the FULL corpus (audit transparency requires the reader to
    # see what was rejected); but the LLM-driven thesis-aligned
    # sections (tensions, synthesis, limitations) and the deterministic
    # direct/indirect evidence bullets only see the SPAR-ACCEPTED slice.
    accepted_receipts = filter_accepted(receipts)

    sections_by_name: dict[SectionName, SynthesisSection] = {
        "title": build_title_section(thesis, topic=topic),
        "thesis": build_thesis_section(thesis),
        "evidence_summary": build_evidence_summary_section(receipts),
        "direct_evidence": build_direct_evidence_section(receipts),
        "indirect_evidence": build_indirect_evidence_section(receipts),
        "rejected_evidence": build_rejected_evidence_section(receipts),
        "spar_adjudication": build_spar_adjudication_section(receipts),
        "references": build_references_section(receipts),
    }

    sections_by_name["tensions"] = await write_tensions_section(
        accepted_receipts, matrix, thesis, topic=topic,
        chain=chain, client=client, ledger=ledger, seed=seed,
    )
    sections_by_name["synthesis"] = await write_synthesis_section(
        accepted_receipts, matrix, thesis, topic=topic,
        chain=chain, client=client, ledger=ledger, seed=seed,
    )
    sections_by_name["limitations"] = await write_limitations_section(
        accepted_receipts, matrix, thesis, topic=topic,
        chain=chain, client=client, ledger=ledger, seed=seed,
    )

    sections = tuple(sections_by_name[n] for n in _SECTION_ORDER)
    body_md = "\n".join(s.body_md for s in sections).rstrip() + "\n"

    return SynthesisPaper(
        submission_id=submission_id,
        topic=topic,
        thesis=thesis,
        matrix=matrix,
        sections=sections,
        body_md=body_md,
        render_version=WRITER_VERSION,
    )
