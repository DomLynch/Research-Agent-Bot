"""Writer — claim-graph-gated prose drafter.

Hard rule: LLM PROPOSES. CODE DISPOSES. The LLM proposes prose for
accepted ClaimGraphs; the writer FORCES every sentence to be bound
to one or more claims from `claim_graph.json`, then gates the prose
through five layers:

  1. **Claim binding** (Day 4.3-fix P1): each sentence is an object
     `{"claim_ids": [...], "text": "..."}`. The LLM must declare
     which claim(s) the sentence is asserting; the writer rejects
     sentences with no claim_ids, unknown claim_ids, or missing
     `text`. This closes the V1.1 hole where the LLM could cite a
     valid `[N]` while making a novel claim that wasn't in the graph.
  2. **Citation-to-claim subset**: every `[N]` in `text` must be in
     the union of the declared claims' `supporting_refs`. The LLM
     can't repurpose a paper's citation to support an unrelated
     claim from the same paper; the spine pinned each fact-to-ref
     mapping at compile time.
  3. **Verb-ban** per-cited-ref via `validators.check_verb_ban`.
  4. **P-value source trace** per-cited-ref via
     `validators.check_p_value_in_source`.
  5. **Alias drift** on the whole sentence via
     `validators.check_alias_drift`.

SPAR verdict routing: `reject_*` and any `gate_override` skip the LLM
entirely and render a structured rejection notice; `accept_clean` /
`accept_caveated` invoke the LLM and gate every sentence.

`gate_override` is rendered PROMINENTLY (per the reviewer's audit-trail
requirement after Day 4.2-fix): the banner shows the panel's original
`pre_gate_verdict`, the `failed_trace_count`, and the gate's rationale.

Failed sentences become `WriterRejection` records (drop-and-record,
no re-prompt); orchestrators decide whether to retry on heavy rates.
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

1. **Every sentence must be CLAIM-BOUND.** Each entry in `abstract` and
   in any `sections.*` array is an OBJECT with two fields:
       {"claim_ids": ["C001", ...], "text": "the sentence with [N] cites."}
   - `claim_ids` lists ≥1 claim_id from the CLAIM GRAPH. It declares
     which claim(s) this sentence is asserting. Empty / missing /
     unknown claim_ids drop the sentence.
   - `text` must contain ≥1 `[N]` citation. Sentences with no `[N]`
     are dropped (you cannot make a claim-of-fact without sourcing).
2. **Citations must match the declared claim's evidence.** Every `[N]`
   in `text` must be in the union of `supporting_refs` across the
   declared `claim_ids`. You cannot repurpose a paper's `[N]` to
   support a claim it wasn't pinned to in the graph.
3. **Don't invent facts beyond the graph.** If the graph doesn't
   contain a claim for what you want to say, omit that sentence. Do
   not extrapolate, generalize, or extend.
4. Verb-ban discipline:
   - role=registered_pending / published_protocol refs: NEVER use
     "showed" / "demonstrated" / "reduced" / "improved" / "lowered" /
     "raised". Use "is studying", "plans to assess", "in progress".
   - role=published_results refs: NEVER use "planned" / "pending" /
     "will assess".
5. Numeric values are VERBATIM from the cited abstract — no paraphrasing
   of p-values, effect sizes, or CIs.
6. Don't introduce drug names outside the topic pack alias whitelist.

Output exactly ONE JSON object, no prose outside it, no markdown fences:
{
  "title": "concise paper title",
  "abstract": [
    {"claim_ids": ["C001"], "text": "metformin reduced X (p=0.003) [1]."},
    ...
  ],
  "sections": {
    "introduction": [{"claim_ids": [...], "text": "..."}, ...],
    "findings":     [{"claim_ids": [...], "text": "..."}, ...],
    "limitations":  [{"claim_ids": [...], "text": "..."}, ...],
    "conclusion":   [{"claim_ids": [...], "text": "..."}, ...]
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
    sentence: Mapping[str, Any],
    *,
    graph: ClaimGraph,
    items_by_ref: Mapping[int, EvidenceItem],
    pack: TopicPack,
) -> tuple[str | None, str | None]:
    """Return `(text, None)` on accept, `(None, reason)` on reject.

    The strict claim-binding contract (Day 4.3-fix P1):
      1. `text` must be a non-empty string.
      2. `claim_ids` must be a non-empty list of strings, all in the
         graph (LLM cannot invent claim_ids or skip the binding).
      3. `text` must contain ≥1 `[N]` citation (no uncited claims).
      4. Every `[N]` in `text` must be in the union of the declared
         claims' `supporting_refs` (cite-to-claim subset rule).
      5. (existing) per-cited-ref `check_verb_ban`.
      6. (existing) per-cited-ref `check_p_value_in_source`.
      7. (existing) `check_alias_drift` on the whole sentence.

    Gates run in this order; the first failure short-circuits so the
    rejection reason is the most informative.
    """
    raw_text = sentence.get("text", "")
    if not isinstance(raw_text, str) or not raw_text.strip():
        return None, "empty_or_non_string_text"
    text = raw_text.strip()

    raw_claim_ids = sentence.get("claim_ids")
    if not isinstance(raw_claim_ids, list) or not raw_claim_ids:
        return None, "missing_claim_ids"
    claims_by_id = {c.claim_id: c for c in graph.claims}
    declared_claims = []
    for cid in raw_claim_ids:
        if not isinstance(cid, str):
            return None, f"non_string_claim_id:{cid!r}"
        claim = claims_by_id.get(cid)
        if claim is None:
            return None, f"unknown_claim_id:{cid}"
        declared_claims.append(claim)

    cite_nums = [int(m.group(1)) for m in _CITE_RE.finditer(text)]
    if not cite_nums:
        return None, "missing_citation"

    allowed_refs: set[int] = set()
    for claim in declared_claims:
        allowed_refs.update(claim.supporting_refs)
    bad_cites = [n for n in cite_nums if n not in allowed_refs]
    if bad_cites:
        return None, (
            f"cite_not_supported_by_claim:{bad_cites}:declared="
            f"{[c.claim_id for c in declared_claims]}"
        )

    for ref in cite_nums:
        item = items_by_ref.get(ref)
        if item is None:
            continue
        verb_fail = check_verb_ban(text, item, pack)
        if verb_fail is not None:
            return None, f"verb_ban:{verb_fail.code}:ref={ref}"
        pval_fail = check_p_value_in_source(text, item.abstract)
        if pval_fail is not None:
            return None, f"p_value_not_in_source:{pval_fail.code}:ref={ref}"

    alias_fail = check_alias_drift(text, pack)
    if alias_fail is not None:
        return None, f"alias_drift:{alias_fail.code}"

    return text, None


def _filter_sentences(
    parsed: Mapping[str, Any],
    *,
    graph: ClaimGraph,
    items_by_ref: Mapping[int, EvidenceItem],
    pack: TopicPack,
) -> tuple[dict[str, Any], list[WriterRejection]]:
    """Walk the LLM's structured output; drop sentences that fail gates.

    Each entry in `abstract` / `sections.*` must be an object with
    `claim_ids` and `text`. Bare strings (legacy format) and other
    non-Mapping entries are recorded as `non_object_sentence`
    rejections — the LLM is on a strict contract, not a permissive one.
    """
    rejections: list[WriterRejection] = []

    def _filter(section: str, items: list) -> list[str]:
        kept: list[str] = []
        for sent in items:
            if not isinstance(sent, Mapping):
                rejections.append(WriterRejection(
                    section=section,
                    sentence=str(sent)[:200],
                    reason="non_object_sentence",
                ))
                continue
            text, reason = _validate_sentence(
                sent, graph=graph,
                items_by_ref=items_by_ref, pack=pack,
            )
            if text is not None:
                kept.append(text)
            else:
                snippet = sent.get("text") if isinstance(sent.get("text"), str) else str(sent)
                rejections.append(WriterRejection(
                    section=section,
                    sentence=str(snippet)[:200],
                    reason=reason or "unknown",
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
    filtered, rejections = _filter_sentences(
        parsed, graph=graph,
        items_by_ref=items_by_ref, pack=pack,
    )
    return _render_paper(filtered, items, spar), rejections
