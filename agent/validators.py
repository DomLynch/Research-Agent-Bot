"""Pure-function validation gates — the prose-claim defense layer.

Hard rule (also posted at top of compiler.py and every relevant prompt):
  LLM PROPOSES. CODE DISPOSES.
  - Role assignment: registry override > deterministic abstract classifier. Never LLM.
  - Fact identity: extracted by LLM, schema-validated, source-text-traced.
  - Claim membership in paper.md: gated by claim_graph.json. LLM cannot add claims.

This module's validators run AFTER the claim graph is compiled but BEFORE
prose is rendered. Each function takes a (claim_text, evidence_item, pack)
or (claim, evidence_items_by_ref) tuple and returns either:
  - None  — the check passed
  - GateFailure  — the check failed; severity='block' kills the draft

Validators consume `topic_pack.TopicPack` outputs (alias whitelist + verb-ban
sets); they NEVER call an LLM. Pure deterministic functions of their inputs.

The four checks for v0 close the local-data layer for three planted-failure
cases. External-lookup checks (NCT existence via TrialRegistryClient,
ChEMBL alias via DrugAliasClient) live in citation_trace.py — those are
Day 3.

| Planted case | Local layer (this module)             | External layer (Day 3)      |
|--------------|---------------------------------------|------------------------------|
| 1 (protocol-as-results) | `check_verb_ban`            | —                            |
| 3 (inflated p-value)    | `check_p_value_in_source`   | `citation_trace.trace_pvalue`|
| 4 (alias drift)         | `check_alias_drift`         | `DrugAliasClient.lookup`     |

`check_role_claim_match` enforces the directness contract within the claim
graph; it has no external counterpart.
"""
from __future__ import annotations

import re
from collections.abc import Mapping

from agent.schemas import Claim
from agent.topic_pack import TopicPack
from agent.types import EvidenceItem, GateFailure

__all__ = [
    "check_verb_ban",
    "check_role_claim_match",
    "check_alias_drift",
    "check_p_value_in_source",
    "PVALUE_RE",  # public so citation_trace.py can reuse the canonical regex
]

# --- Regex helpers ---------------------------------------------------------

# Match `p <op> <digits>` with optional whitespace and an optional leading
# zero. Captures (op, digits) — e.g., 'p<0.001' → ('<', '001'). Used by
# both check_p_value_in_source and (later) citation_trace.py.
PVALUE_RE = re.compile(r"\bp\s*([=<>])\s*0?\.(\d+)", re.IGNORECASE)


# --- check_verb_ban — planted case 1's third layer ------------------------


def check_verb_ban(
    claim_text: str,
    evidence_item: EvidenceItem,
    pack: TopicPack,
) -> GateFailure | None:
    """Reject prose claims whose verbs contradict the cited evidence's role.

    Two halves to the contract (both come from `pack`):

    1. If `evidence_item.role` is in {`registered_pending`, `published_protocol`},
       no verb in `pack.forbidden_verbs_for_protocol_role` may appear in
       `claim_text`. This catches planted case 1: 'TAME demonstrated CV
       benefit' citing TAME (registered_pending). The registry-override
       layer pinned the role correctly; this layer ensures the prose
       respects the role.

    2. If `evidence_item.role` is `published_results`, no protocol-keyword
       from `pack.forbidden_verbs_for_results_role_with_protocol_keywords`
       may appear. This catches the inverse: a published trial described
       as 'planned' or 'pending'.

    Both checks use word boundaries so 'demonstrated' matches but
    'demonstrative' does not.
    """
    text = claim_text.lower()
    ref = evidence_item.source.ref

    if evidence_item.role in {"registered_pending", "published_protocol"}:
        for verb in pack.forbidden_verbs_for_protocol_role:
            if re.search(rf"\b{re.escape(verb)}\b", text):
                return GateFailure(
                    code="VERB_BAN_PROTOCOL",
                    message=(
                        f"claim uses verb {verb!r} but cited evidence "
                        f"(ref={ref}) has role={evidence_item.role!r} "
                        f"(no published results yet)."
                    ),
                    severity="block",
                )
        return None

    if evidence_item.role == "published_results":
        for keyword in pack.forbidden_verbs_for_results_role_with_protocol_keywords:
            if re.search(rf"\b{re.escape(keyword)}\b", text):
                return GateFailure(
                    code="VERB_BAN_RESULTS_PROTOCOL_KEYWORD",
                    message=(
                        f"claim uses protocol-keyword {keyword!r} but cited "
                        f"evidence (ref={ref}) has role='published_results'. "
                        f"Don't describe a published trial as planned/pending."
                    ),
                    severity="block",
                )
        return None

    # review/mechanistic/off_domain — verb-ban not applicable
    return None


# --- check_role_claim_match — directness contract ------------------------


def check_role_claim_match(
    claim: Claim,
    evidence_items_by_ref: Mapping[int, EvidenceItem],
) -> GateFailure | None:
    """Verify a `direct` claim has at least one direct evidence item.

    A claim labelled `directness='direct'` must be supported by evidence
    that the deterministic classifier marked `direct=True`. If every
    supporting ref is `direct=False`, the claim is structurally
    contradicting its own evidence.

    Indirect / mechanistic claims have no analogous constraint here — they
    can cite mechanistic or indirect evidence by design.
    """
    if claim.directness != "direct":
        return None

    if not claim.supporting_refs:
        return GateFailure(
            code="CLAIM_NO_SUPPORT",
            message=f"claim {claim.claim_id!r} has no supporting refs",
            severity="block",
        )

    items = [evidence_items_by_ref.get(r) for r in claim.supporting_refs]
    valid = [it for it in items if it is not None]

    if not valid:
        return GateFailure(
            code="CLAIM_REFS_NOT_FOUND",
            message=(
                f"claim {claim.claim_id!r} references {list(claim.supporting_refs)} "
                f"but none resolve to evidence items"
            ),
            severity="block",
        )

    if not any(it.direct for it in valid):
        return GateFailure(
            code="CLAIM_DIRECTNESS_MISMATCH",
            message=(
                f"claim {claim.claim_id!r} marked directness='direct' but "
                f"none of supporting refs {list(claim.supporting_refs)} "
                f"are direct evidence (off-topic or off-population)."
            ),
            severity="block",
        )
    return None


# --- check_alias_drift — planted case 4's local layer --------------------


# Matches "Word, a/an <topic> <equivalent|analog|...>" — the canonical
# apposition pattern for alias claims. We don't try to flag every
# capitalized token (too many false positives); we only flag tokens
# explicitly presented as a topic-alias.
_ALIAS_PRESENTATION_PATTERNS = (
    r"equivalent",
    r"analog(?:ue)?",
    r"derivative",
    r"alias",
    r"version",
    r"formulation",
    r"alternative",
    r"variant",
    r"substitute",
    r"isomer",
)


def check_alias_drift(claim_text: str, pack: TopicPack) -> GateFailure | None:
    """Catch claims that present a non-whitelisted token as a topic-alias.

    Pattern caught:
      "Glufomin, a metformin equivalent, ..."  → flag if 'Glufomin' not in pack
      "Glucophagex (a metformin alternative)"  → same
      "Acme-X, an analog of metformin, ..."    → same

    Targeted by design — only fires when the claim explicitly presents the
    candidate as a topic-alias. False positives on common drug names are
    Day 3's `DrugAliasClient` problem (full ChEMBL lookup).
    """
    presentation = "|".join(_ALIAS_PRESENTATION_PATTERNS)
    pattern = re.compile(
        rf"\b([A-Z][a-zA-Z][a-zA-Z0-9-]{{2,}})\b"  # Capitalized token (≥4 chars)
        rf"\s*[,()]?\s*"
        rf"(?:a|an|the)?\s*"
        rf"(?:{re.escape(pack.topic)}\s+(?:{presentation})"
        rf"|(?:{presentation})\s+of\s+{re.escape(pack.topic)})",
        re.IGNORECASE,
    )
    match = pattern.search(claim_text)
    if not match:
        return None

    candidate = match.group(1)
    if pack.has_alias(candidate):
        return None  # the topic itself or a recognized alias

    return GateFailure(
        code="ALIAS_DRIFT",
        message=(
            f"claim presents {candidate!r} as a {pack.topic} alias/equivalent, "
            f"but {candidate!r} is not in the topic_pack alias whitelist. "
            f"Day 3 DrugAliasClient will provide authoritative ChEMBL verification."
        ),
        severity="block",
    )


# --- check_p_value_in_source — planted case 3's local layer --------------


def check_p_value_in_source(
    claim_text: str,
    source_abstract: str,
) -> GateFailure | None:
    """Verify every p-value cited in the claim appears verbatim in the source.

    Catches planted case 3: claim cites 'p<0.001' but source actually says
    'p=0.08'. Match is on the (operator, digits) tuple — exact, not fuzzy
    — so 'p<0.001' and 'p=0.08' do NOT match. The `PVALUE_RE` normalizes
    whitespace and an optional leading zero before the decimal.

    Day 8.0: Unicode middle-dot (U+00B7) normalized to ASCII period before
    matching, so a claim with `p=0.02` traces against an abstract that
    writes `p=0·02` (British medical journal style — Lancet, BMJ, etc.).

    Returns None when no p-values are cited (nothing to verify).
    """
    claim_pvs = set(PVALUE_RE.findall(claim_text.replace("·", ".")))
    if not claim_pvs:
        return None

    source_pvs = set(PVALUE_RE.findall(source_abstract.replace("·", ".")))
    missing = claim_pvs - source_pvs
    if not missing:
        return None

    # Render missing tuples back to readable form for the error message.
    rendered = ", ".join(f"p{op}0.{digits}" for op, digits in sorted(missing))
    source_rendered = (
        ", ".join(f"p{op}0.{digits}" for op, digits in sorted(source_pvs))
        if source_pvs else "(none)"
    )
    return GateFailure(
        code="P_VALUE_NOT_IN_SOURCE",
        message=(
            f"claim cites p-value(s) {rendered} not present in source abstract. "
            f"Source p-values: {source_rendered}"
        ),
        severity="block",
    )
