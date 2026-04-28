"""Writer — deterministic ClaimGraph renderer (NO LLM call at write time).

Hard rule: LLM PROPOSES (at fact extraction time). CODE DISPOSES.

The previous LLM-in-writer design (Day 4.3 + 4.3-fix) tried to enforce
claim integrity via per-sentence `claim_ids` binding plus citation
subset checks. The reviewer caught the residual hole (Day 4-fix P1):
the LLM could declare a valid `claim_id`, cite a valid `[N]`, and STILL
write a novel claim text that wasn't in the graph. Self-declared
binding without text-to-claim verification is insufficient — semantic
overlap checks are brittle, and full entailment is itself an LLM
problem.

The clean fix: make the writer purely deterministic. Every sentence
in the paper IS a `Claim.text` from the graph, attached to its
`supporting_refs`. No freeform LLM sentence generation, no novel
claims possible. The LLM's role ended at fact extraction; from that
point onward, code disposes.

Verdict-aware routing:
  - `accept_clean` / `accept_caveated` → render the paper
  - `reject_*` / any `gate_override` → render a structured rejection notice

`gate_override` is rendered PROMINENTLY (per the reviewer's audit-trail
requirement after Day 4.2-fix): the banner shows the panel's original
`pre_gate_verdict`, the `failed_trace_count`, and the gate's rationale,
so a reader sees both the LLM panel's call AND why the deterministic
spine overrode it.

`write_paper` is now SYNC (no LLM call). Returns `(markdown, [])` —
the rejections list is preserved for API stability but is always
empty on the deterministic path.
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from agent.schemas import (
    CitationTrace,
    Claim,
    ClaimGraph,
    SPARReview,
)
from agent.topic_pack import TopicPack
from agent.types import EvidenceItem

__all__ = [
    "RENDER_VERSION",
    "WriterError",
    "WriterRejection",
    "write_paper",
]

RENDER_VERSION = "writer/2026-04-28-deterministic"

_CITE_RE = re.compile(r"\[(\d+)\]")

# Sections — each maps to a tuple of claim_types that go in it. Order in
# the tuple is informational (smaller groups render first within a
# section). Order of the dict is the section order in the paper.
_SECTION_BUCKETS: dict[str, tuple[str, ...]] = {
    "Findings": ("efficacy", "safety"),
    "Background": ("mechanism", "indirect", "context"),
}

_DIRECTNESS_RANK: dict[str, int] = {"direct": 0, "indirect": 1, "mechanistic": 2}
_TIER_RANK: dict[str, int] = {"A1": 0, "A2": 1, "B": 2, "C": 3, "mixed": 4}
_CONFIDENCE_RANK: dict[str, int] = {"high": 0, "moderate": 1, "low": 2}


class WriterError(RuntimeError):
    """Raised when the graph is structurally inconsistent (e.g., thesis
    not in claims). Schema invariants should prevent these reaching the
    writer; this is defense-in-depth."""


@dataclass(frozen=True, slots=True)
class WriterRejection:
    """Preserved for API stability; the deterministic writer never
    populates this. Day 5+ may revive it if a non-LLM rejection path
    emerges (e.g., orphan supporting_refs)."""
    section: str
    sentence: str
    reason: str


# --- SPAR banner ---------------------------------------------------------


def _spar_banner(spar: SPARReview) -> str:
    """SPAR verdict banner. `gate_override` gets the most prominent
    treatment because that's the trust-spine override path."""
    if spar.gate_override is not None:
        g = spar.gate_override
        return (
            "## TRUST-SPINE TRACE GATE TRIGGERED\n\n"
            f"**Canonical verdict:** `{spar.verdict}` "
            f"(deterministic override of panel's `{g.pre_gate_verdict}` vote).\n\n"
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
        d_block = f"\n\n**Dissent — `{d.judge_role}`:** {d.rationale}" if d else ""
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


# --- Deterministic claim rendering ---------------------------------------


def _make_title(thesis: Claim, topic: str) -> str:
    """Title from thesis claim. Strip trailing period, capitalize first
    letter. Falls back to topic name if thesis text is empty."""
    text = thesis.text.strip().rstrip(".")
    if not text:
        return topic.title() or "Untitled draft"
    return text[0].upper() + text[1:]


def _render_claim_with_cites(claim: Claim) -> str:
    """Render a claim's text with its supporting citations appended.

    If the claim text already contains `[N]` cites, leave them alone —
    the fact_extractor pinned `Claim.text` to vetted prose, and we
    don't want to double-cite. If no cites are in the text, append the
    full supporting_refs list.
    """
    text = claim.text.strip()
    if _CITE_RE.search(text):
        return text
    if not claim.supporting_refs:
        return text
    cites = " ".join(f"[{ref}]" for ref in claim.supporting_refs)
    if text.endswith("."):
        return f"{text[:-1]} {cites}."
    return f"{text} {cites}."


def _sort_key(claim: Claim) -> tuple[int, int, int, str]:
    """Within-section ordering: directness > tier > confidence > claim_id.
    Same shape as thesis_tournament's sort but per-section, so a strong
    direct A1 claim leads the Findings section."""
    return (
        _DIRECTNESS_RANK.get(claim.directness, 9),
        _TIER_RANK.get(claim.evidence_tier, 9),
        _CONFIDENCE_RANK.get(claim.confidence, 9),
        claim.claim_id,
    )


def _claims_for_bucket(
    graph: ClaimGraph,
    bucket: tuple[str, ...],
    *,
    exclude_ids: set[str] | None = None,
) -> list[Claim]:
    """Filter claims by claim_type, excluding any IDs already rendered
    (e.g., the thesis claim has its own section)."""
    excluded = exclude_ids or set()
    return sorted(
        (c for c in graph.claims
         if c.claim_type in bucket and c.claim_id not in excluded),
        key=_sort_key,
    )


def _render_paper(
    graph: ClaimGraph,
    items: Sequence[EvidenceItem],
    spar: SPARReview,
    topic: str,
) -> str:
    thesis = next(
        (c for c in graph.claims if c.claim_id == graph.thesis_claim_id),
        None,
    )
    if thesis is None:
        # Schema invariant should prevent this, but defense-in-depth
        # keeps the bug visible if it ever slips through.
        raise WriterError(
            f"thesis_claim_id={graph.thesis_claim_id!r} not in claims — "
            f"ClaimGraph invariant violated upstream"
        )

    title = _make_title(thesis, topic)
    cited_refs: set[int] = set()
    lines: list[str] = [f"# {title}", "", _spar_banner(spar), ""]

    # Thesis section — always present, single claim
    lines.extend(["## Thesis", "", _render_claim_with_cites(thesis), ""])
    cited_refs.update(thesis.supporting_refs)

    # Bucketed sections
    for section_name, bucket in _SECTION_BUCKETS.items():
        section_claims = _claims_for_bucket(
            graph, bucket, exclude_ids={thesis.claim_id},
        )
        if not section_claims:
            continue
        lines.extend([f"## {section_name}", ""])
        for c in section_claims:
            lines.append(_render_claim_with_cites(c))
            cited_refs.update(c.supporting_refs)
        lines.append("")

    if cited_refs:
        lines.append(_render_references(items, cited_refs))
    return "\n".join(lines).rstrip() + "\n"


def _render_references(
    items: Sequence[EvidenceItem],
    cited: set[int],
) -> str:
    """Render `## References` listing only refs cited in the prose."""
    lines = ["## References", ""]
    for item in sorted(items, key=lambda it: it.source.ref):
        if item.source.ref not in cited:
            continue
        s = item.source
        year = f" ({s.year})" if s.year else ""
        url = f" {s.url}" if s.url else ""
        lines.append(f"[{s.ref}] {s.title}{year}.{url}")
    return "\n".join(lines)


# --- Rejection rendering -------------------------------------------------


def _render_rejection(
    graph: ClaimGraph,
    items: Sequence[EvidenceItem],
    spar: SPARReview,
    traces: Sequence[CitationTrace],
) -> str:
    """Structured rejection notice — banner, thesis, failed traces, panel
    reviews. No LLM call needed."""
    thesis = next(
        (c for c in graph.claims if c.claim_id == graph.thesis_claim_id),
        None,
    )
    lines: list[str] = ["# Submission rejected", "", _spar_banner(spar), ""]
    if thesis is not None:
        lines.extend(["## Proposed thesis (rejected)", "", f"> {thesis.text}", ""])

    failed = [t for t in traces if not t.passed]
    if failed:
        lines.extend(["## Failed citation traces", ""])
        for t in failed:
            lines.append(
                f"- **{t.trace_type}** on `{t.claim_id}` (ref={t.ref}): {t.detail}"
            )
        lines.append("")

    lines.extend(["## Panel reviews", ""])
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


def write_paper(
    graph: ClaimGraph,
    items: Sequence[EvidenceItem],
    traces: Sequence[CitationTrace],
    spar: SPARReview,
    *,
    pack: TopicPack,  # noqa: ARG001 — kept for API stability + future gates
    topic: str,
) -> tuple[str, list[WriterRejection]]:
    """Render a markdown paper deterministically from a SPAR-adjudicated
    ClaimGraph. NO LLM call.

    Routes by SPAR verdict:
      - `accept_clean` / `accept_caveated`: render the paper from
        Claim.text (deterministic, no novel sentences possible).
      - `reject_*` / any `gate_override`: render a structured rejection
        notice with the gate's reasoning prominently displayed.

    Returns `(markdown, rejections)`. The rejections list is always
    empty on the deterministic path (no LLM proposals to reject); the
    return shape is preserved for API stability and forward-compat.
    """
    if (
        spar.verdict in ("reject_majority", "reject_critical")
        or spar.gate_override is not None
    ):
        return _render_rejection(graph, items, spar, traces), []
    return _render_paper(graph, items, spar, topic), []
