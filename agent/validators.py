"""Pure-function validation gates — the prose-claim defense layer.

Hard rule (also posted at top of compiler.py and every relevant prompt):
  LLM PROPOSES. CODE DISPOSES.
  - Role assignment: registry override > deterministic abstract classifier. Never LLM.
  - Fact identity: extracted by LLM, schema-validated, source-text-traced.
  - Claim membership in claim_receipt.md: gated by claim_graph.json. LLM cannot add claims.

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
    "check_objective_as_claim",
    "OBJECTIVE_PATTERN_RE",
    "PVALUE_RE",  # public so citation_trace.py can reuse the canonical regex
]

# --- Regex helpers ---------------------------------------------------------

# Match `p <op> <digits>` with optional whitespace and an optional leading
# zero. Captures (op, digits) — e.g., 'p<0.001' → ('<', '001'). Used by
# both check_p_value_in_source and (later) citation_trace.py.
PVALUE_RE = re.compile(r"\bp\s*([=<>])\s*0?\.(\d+)", re.IGNORECASE)


# Day 10.11 — objective/protocol sentence patterns.
# A claim quoted by the fact extractor that matches one of these patterns
# is describing what a study SET OUT TO DO ("To determine whether...",
# "We aimed to...", "Trial registration:") rather than what it FOUND.
# Reviewer P1 / SPAR: this was the dominant rejection mode on the Day
# 10.10 metformin run — fact_extractor pulled abstract objective spans
# as if they were findings, and SPAR correctly rejected.
#
# Patterns are anchored to sentence/clause beginnings (after lowercasing
# and whitespace normalization). Matches catch:
#   "To determine whether metformin can improve immune response..."
#   "The objective of this research is to assess the efficacy..."
#   "This study aims to evaluate..."
#   "This research is being done to determine if..."
#   "We aim/aimed/sought to..."
#   "The aim/purpose of this study is/was to..."
#   "Trial registration: ..."
OBJECTIVE_PATTERN_RE = re.compile(
    r"(?:^|\.\s+|;\s+)\s*"
    r"(?:"
    r"to\s+(?:determine|assess|evaluate|investigate|examine|explore|"
    r"identify|test|study|compare|measure|characterize)"
    r"\s+(?:whether|if|the|how)\b"
    r"|the\s+(?:primary\s+)?(?:objective|aim|purpose|goal)\s+"
    r"of\s+this\s+(?:study|research|trial|investigation)"
    r"\s+(?:is|was|are|were)\s+to\b"
    r"|this\s+(?:study|research|trial|investigation)\s+"
    r"(?:aims?|aimed|seeks?|sought|is\s+(?:being\s+)?(?:done|conducted)|"
    r"will|intends?|plans?)\s+to\b"
    r"|we\s+(?:aim|aimed|sought|seek|hypothesi[sz]ed?|investigate[d]?|"
    r"will|plan|propose)\s+to\b"
    r"|trial\s+registration:"
    r")",
    re.IGNORECASE,
)


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


# --- check_objective_as_claim — Day 10.11 -------------------------------


def check_objective_as_claim(
    claim_text: str,
    evidence_item: EvidenceItem,
) -> GateFailure | None:
    """Reject quotes that describe a study's OBJECTIVE / DESIGN / REGISTRATION
    rather than its findings, when the cited item is `published_results`.

    Day 10.11 reviewer P1 fix: the dominant SPAR rejection mode on the
    Day 10.10 metformin corpus was protocol-as-claim — the fact extractor
    pulled abstract spans like "To determine whether metformin can improve
    the immune response..." or "Trial registration: NCT..." and emitted
    them as Facts with kind='result'. SPAR judges correctly rejected these
    as 'not actually claims, but study purposes'.

    Approach: a deterministic regex (`OBJECTIVE_PATTERN_RE`) matches the
    most common objective/protocol sentence forms ("To determine whether",
    "We aimed to", "The objective of this study is to", "This study aims
    to", "Trial registration:", etc.). When a results-role item's quote
    matches one of those patterns, the validator returns
    OBJECTIVE_AS_CLAIM_RESULTS so the fact extractor can drop the
    proposal upstream of SPAR.

    Why not also gate review/mechanistic? Reviews and mechanistic
    abstracts often legitimately START with "We investigated..." or
    "This study aimed to..." in the framing sentence, even though their
    findings appear later. The trust-spine cost of false-positives there
    is high (legitimate review-of-evidence facts get dropped) while the
    benefit is low (review-role items already filter to review-style
    facts elsewhere). Reserve this gate for the published_results role
    where the failure mode is empirically dominant.
    """
    if evidence_item.role != "published_results":
        return None
    norm = " ".join(claim_text.split())
    if OBJECTIVE_PATTERN_RE.search(norm):
        ref = evidence_item.source.ref
        snippet = norm[:80]
        return GateFailure(
            code="OBJECTIVE_AS_CLAIM_RESULTS",
            message=(
                f"quote (ref={ref}) describes the study's OBJECTIVE / "
                f"DESIGN / REGISTRATION rather than a finding "
                f"(matched objective-pattern). Quote: {snippet!r}. "
                f"For published_results items, extract spans that report "
                f"WHAT WAS FOUND, not WHAT WAS PLANNED."
            ),
            severity="block",
        )
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
