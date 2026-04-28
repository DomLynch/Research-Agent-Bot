"""Writer — claim-graph-gated prose drafter.

Hard rule: LLM PROPOSES. CODE DISPOSES. The LLM proposes prose for
accepted ClaimGraphs; code gates which sentences survive based on:
  1. Claim-graph membership: every `[N]` citation must reference a
     supporting_ref of a real claim in the graph (LLM cannot invent
     citations or refer to refs the spine didn't approve).
  2. Per-cited-ref verb-ban + p-value source-trace via `validators.*`.
  3. Topic-pack alias-drift on the whole sentence.
  4. SPAR verdict routing: `reject_*` and `gate_override` paths skip
     the LLM entirely and render a structured rejection notice.

The output is a markdown string suitable for `runs/<topic>/paper.md`.
Rejected sentences are surfaced as `WriterRejection` records for the
run log — the run accepts a partial draft (drop-and-record) rather
than re-prompting; orchestrators can decide whether to retry.

`gate_override` is rendered PROMINENTLY in any output where it appears
(per the reviewer's audit-trail requirement after Day 4.2-fix): the
banner shows the panel's original `pre_gate_verdict`, the
`failed_trace_count`, and the gate's rationale, so a reader can see
both the LLM panel's call AND why the deterministic spine overrode it.
"""
from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import httpx

from agent.llm_client import CallSpec, CostLedger, chat_json
from agent.schemas import (
    CitationTrace,
    ClaimGraph,
    SPARReview,
)
from agent.topic_pack import TopicPack
from agent.types import EvidenceItem
from agent.validators import (
    check_alias_drift,
    check_p_value_in_source,
    check_verb_ban,
)

__all__ = [
    "PROMPT_VERSION",
    "WriterError",
    "WriterRejection",
    "write_paper",
]

PROMPT_VERSION = "writer/2026-04-28"

_CITE_RE = re.compile(r"\[(\d+)\]")


class WriterError(RuntimeError):
    """Raised when the LLM response can't be parsed into the writer's
    expected JSON shape. Caller decides retry vs surface."""


@dataclass(frozen=True, slots=True)
class WriterRejection:
    """One sentence that didn't survive code-disposes. Captured for the
    run log so the orchestrator can see why prose was dropped."""
    section: str
    sentence: str
    reason: str


# --- Prompt --------------------------------------------------------------

_SYSTEM_PROMPT = """You draft a research paper from a vetted CLAIM GRAPH.

HARD RULES (any violation drops the offending sentence):
1. Cite ONLY refs in the bundle below. `[N]` citations referencing
   refs not in the bundle are dropped.
2. Cite ONLY claims listed in the CLAIM GRAPH. Don't invent facts
   beyond what's there.
3. Verb-ban discipline:
   - For role=registered_pending or role=published_protocol refs,
     do NOT use "showed", "demonstrated", "reduced", "improved",
     "lowered", "raised". Those imply outcomes the paper hasn't
     reported. Use "is studying", "plans to assess", "in progress".
   - For role=published_results refs, do NOT describe as "planned",
     "pending", "will assess".
4. Numeric values must be VERBATIM from the abstracts. Don't paraphrase
   p-values, effect sizes, or CIs.
5. Don't introduce drug names that aren't in the topic pack's alias
   whitelist; if you need to mention a comparator drug, use a generic
   description.

Output exactly ONE JSON object, no prose outside it, no markdown fences:
{
  "title": "concise paper title",
  "abstract": ["sentence with [N] cites", ...],
  "sections": {
    "introduction": ["sentence with [N] cites", ...],
    "findings": ["sentence with [N] cites", ...],
    "limitations": ["sentence with [N] cites", ...],
    "conclusion": ["sentence with [N] cites", ...]
  }
}"""


def _build_user_prompt(
    graph: ClaimGraph,
    items: Sequence[EvidenceItem],
    topic: str,
) -> str:
    valid_refs = _valid_refs(graph)
    relevant_items = [it for it in items if it.source.ref in valid_refs]
    bundle_block = "\n".join(
        f"[{it.source.ref}] role={it.role} design={it.design} tier={it.tier} "
        f"direct={it.direct} year={it.source.year}\n"
        f"    title: {it.source.title}\n"
        f"    abstract: {(it.abstract or '')[:1200]}"
        for it in relevant_items
    )
    thesis = next(
        (c for c in graph.claims if c.claim_id == graph.thesis_claim_id),
        None,
    )
    thesis_line = (
        f"THESIS [{thesis.claim_id}]: {thesis.text}" if thesis
        else f"THESIS [{graph.thesis_claim_id}]: <not found in claims>"
    )
    claims_block = "\n".join(
        f"  [{c.claim_id} | {c.directness} | {c.evidence_tier} | "
        f"{c.confidence}] supporting_refs={list(c.supporting_refs)}: "
        f"{c.text}"
        for c in graph.claims
    )
    return (
        f"Topic: {topic}\n\n"
        f"{thesis_line}\n\n"
        f"CLAIM GRAPH ({len(graph.claims)} claims):\n{claims_block}\n\n"
        f"BUNDLE (cite from these only):\n{bundle_block}"
    )


def _valid_refs(graph: ClaimGraph) -> set[int]:
    """Refs the writer is allowed to cite — union of all claims'
    supporting_refs. A ref the spine didn't approve as supporting some
    claim cannot be cited even if it's in the items list."""
    out: set[int] = set()
    for c in graph.claims:
        out.update(c.supporting_refs)
    return out


# --- Sentence gating ------------------------------------------------------


def _validate_sentence(
    sentence: str,
    *,
    valid_refs: set[int],
    items_by_ref: Mapping[int, EvidenceItem],
    pack: TopicPack,
) -> str | None:
    """Return None if the sentence passes all gates, else a reason code.

    Each gate runs in priority order; the first failure short-circuits
    so the rejection reason is the most informative one (membership
    bugs surface as cite_not_in_bundle rather than as a downstream
    verb-ban or p-value miss).
    """
    cited_refs = [int(m.group(1)) for m in _CITE_RE.finditer(sentence)]
    bad_cites = [c for c in cited_refs if c not in valid_refs]
    if bad_cites:
        return f"cite_not_in_bundle:{bad_cites}"

    for ref in cited_refs:
        item = items_by_ref.get(ref)
        if item is None:
            continue  # validator-side guard: shouldn't happen post-membership
        verb_fail = check_verb_ban(sentence, item, pack)
        if verb_fail is not None:
            return f"verb_ban:{verb_fail.code}:ref={ref}"
        pval_fail = check_p_value_in_source(sentence, item.abstract)
        if pval_fail is not None:
            return f"p_value_not_in_source:{pval_fail.code}:ref={ref}"

    alias_fail = check_alias_drift(sentence, pack)
    if alias_fail is not None:
        return f"alias_drift:{alias_fail.code}"

    return None


def _filter_sentences(
    parsed: Mapping[str, Any],
    *,
    valid_refs: set[int],
    items_by_ref: Mapping[int, EvidenceItem],
    pack: TopicPack,
) -> tuple[dict[str, Any], list[WriterRejection]]:
    """Walk the LLM's structured output; drop sentences that fail gates.

    Sentences that aren't strings are silently skipped (the LLM
    occasionally emits null / nested objects in arrays); strings are
    validated and either kept or recorded as a WriterRejection.
    """
    rejections: list[WriterRejection] = []

    def _filter(section: str, items: list) -> list[str]:
        kept: list[str] = []
        for sent in items:
            if not isinstance(sent, str):
                continue
            reason = _validate_sentence(
                sent, valid_refs=valid_refs,
                items_by_ref=items_by_ref, pack=pack,
            )
            if reason is None:
                kept.append(sent)
            else:
                rejections.append(WriterRejection(
                    section=section, sentence=sent, reason=reason,
                ))
        return kept

    title_raw = parsed.get("title", "")
    title = title_raw.strip() if isinstance(title_raw, str) else ""
    abstract_in = parsed.get("abstract") or []
    sections_in = parsed.get("sections") or {}

    out: dict[str, Any] = {
        "title": title,
        "abstract": _filter("abstract", abstract_in if isinstance(abstract_in, list) else []),
        "sections": {
            name: _filter(name, sentences if isinstance(sentences, list) else [])
            for name, sentences in (
                sections_in.items() if isinstance(sections_in, Mapping) else []
            )
        },
    }
    return out, rejections


# --- Markdown rendering ---------------------------------------------------


def _spar_banner(spar: SPARReview) -> str:
    """SPAR verdict banner — gate_override gets the most prominent
    treatment because that's the trust-spine override path."""
    if spar.gate_override is not None:
        g = spar.gate_override
        return (
            "## TRUST-SPINE TRACE GATE TRIGGERED\n\n"
            f"**Canonical verdict:** `{spar.verdict}` "
            f"(deterministic override of panel's "
            f"`{g.pre_gate_verdict}` vote).\n\n"
            f"**Failed citation traces:** {g.failed_trace_count}\n\n"
            f"**Gate rationale:** {g.rationale}\n\n"
            "Panel votes preserved verbatim in `spar_review.json` for "
            "audit. The deterministic trace gate fired because the "
            "Auditor prompt instructs reject on failed traces — code "
            "disposes when LLM compliance fails."
        )
    if spar.verdict == "accept_clean":
        return f"**SPAR verdict:** `{spar.verdict}` (3-0 unanimous accept)."
    if spar.verdict == "accept_caveated":
        d = spar.dissent
        d_block = (
            f"\n\n**Dissent — `{d.judge_role}`:** {d.rationale}"
            if d else ""
        )
        return f"**SPAR verdict:** `{spar.verdict}` (2-1 accept).{d_block}"
    if spar.verdict == "reject_majority":
        d = spar.dissent
        d_block = (
            f"\n\n**Minority accept — `{d.judge_role}`:** {d.rationale}"
            if d else ""
        )
        return (
            f"## DRAFT REJECTED\n\n"
            f"**SPAR verdict:** `{spar.verdict}` (2-1 reject).{d_block}"
        )
    return (
        f"## DRAFT REJECTED\n\n"
        f"**SPAR verdict:** `{spar.verdict}` (3-0 unanimous reject)."
    )


def _render_references(items: Sequence[EvidenceItem], cited: set[int]) -> str:
    """Render a `## References` section listing only the refs that
    actually appear in the cited set (sorted ascending). Items with
    refs not cited are omitted to keep the bibliography clean."""
    lines = ["## References", ""]
    for item in sorted(items, key=lambda it: it.source.ref):
        if item.source.ref not in cited:
            continue
        s = item.source
        year = f" ({s.year})" if s.year else ""
        url = f" {s.url}" if s.url else ""
        lines.append(f"[{s.ref}] {s.title}{year}.{url}")
    return "\n".join(lines)


def _gather_cited(filtered: Mapping[str, Any]) -> set[int]:
    cited: set[int] = set()

    def _walk(items: list[str]) -> None:
        for sent in items:
            for m in _CITE_RE.finditer(sent):
                cited.add(int(m.group(1)))

    _walk(filtered.get("abstract") or [])
    for sentences in (filtered.get("sections") or {}).values():
        _walk(sentences)
    return cited


def _render_paper(
    filtered: Mapping[str, Any],
    items: Sequence[EvidenceItem],
    spar: SPARReview,
) -> str:
    title = filtered.get("title") or "Untitled draft"
    abstract = filtered.get("abstract") or []
    sections = filtered.get("sections") or {}

    lines: list[str] = [f"# {title}", "", _spar_banner(spar), ""]
    if abstract:
        lines.extend(["## Abstract", "", " ".join(abstract), ""])
    for name in ("introduction", "findings", "limitations", "conclusion"):
        sentences = sections.get(name) or []
        if not sentences:
            continue
        lines.extend([f"## {name.title()}", "", " ".join(sentences), ""])

    cited = _gather_cited(filtered)
    if cited:
        lines.append(_render_references(items, cited))
    return "\n".join(lines).rstrip() + "\n"


def _render_rejection(
    graph: ClaimGraph,
    items: Sequence[EvidenceItem],
    spar: SPARReview,
    traces: Sequence[CitationTrace],
) -> str:
    """Structured rejection notice for reject_* / gate_override paths.
    No LLM call — just the panel's own rationale + failed traces."""
    thesis = next(
        (c for c in graph.claims if c.claim_id == graph.thesis_claim_id),
        None,
    )
    lines: list[str] = ["# Submission rejected", "", _spar_banner(spar), ""]
    if thesis is not None:
        lines.extend(["## Proposed thesis (rejected)", "", f"> {thesis.text}", ""])

    failed = [t for t in traces if not t.passed]
    if failed:
        lines.append("## Failed citation traces")
        lines.append("")
        for t in failed:
            lines.append(
                f"- **{t.trace_type}** on `{t.claim_id}` (ref={t.ref}): {t.detail}"
            )
        lines.append("")

    lines.append("## Panel reviews")
    lines.append("")
    for r in spar.reviews:
        lines.append(f"### `{r.judge_role}` — `{r.verdict}` (score {r.score})")
        lines.append("")
        lines.append(r.rationale)
        if r.flagged_claims:
            lines.append("")
            lines.append(f"**Flagged claims:** {', '.join(r.flagged_claims)}")
        lines.append("")

    cited_via_traces = {t.ref for t in traces if t.ref}
    if cited_via_traces:
        lines.append(_render_references(items, cited_via_traces))
    return "\n".join(lines).rstrip() + "\n"


# --- Top-level entry ------------------------------------------------------


async def write_paper(
    graph: ClaimGraph,
    items: Sequence[EvidenceItem],
    traces: Sequence[CitationTrace],
    spar: SPARReview,
    *,
    pack: TopicPack,
    topic: str,
    chain: Sequence[CallSpec],
    client: httpx.AsyncClient | None = None,
    ledger: CostLedger | None = None,
    temperature: float = 0.2,
) -> tuple[str, list[WriterRejection]]:
    """Produce a markdown paper from a SPAR-adjudicated ClaimGraph.

    Routes by SPAR verdict:
      - `accept_clean` / `accept_caveated`: invoke the LLM, gate each
        sentence against the claim graph + validators, render prose
        with the verdict banner.
      - `reject_majority` / `reject_critical` / any `gate_override`:
        skip the LLM, render a structured rejection notice with the
        gate's reasoning prominently displayed.

    Returns `(markdown, rejections)`. The rejections list is empty on
    the rejection path; on the accept path it contains every sentence
    the LLM proposed that didn't survive code-disposes.
    """
    if (
        spar.verdict in ("reject_majority", "reject_critical")
        or spar.gate_override is not None
    ):
        return _render_rejection(graph, items, spar, traces), []

    response = await chat_json(
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_prompt(graph, items, topic)},
        ],
        chain=chain,
        client=client,
        ledger=ledger,
        temperature=temperature,
    )
    parsed = response.parsed
    if not isinstance(parsed, Mapping):
        raise WriterError(
            f"writer LLM returned non-object root: {type(parsed).__name__}"
        )

    items_by_ref = {it.source.ref: it for it in items}
    valid_refs = _valid_refs(graph)
    filtered, rejections = _filter_sentences(
        parsed, valid_refs=valid_refs,
        items_by_ref=items_by_ref, pack=pack,
    )
    return _render_paper(filtered, items, spar), rejections
