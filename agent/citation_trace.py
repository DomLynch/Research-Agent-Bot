"""Citation trace — the moat orchestrator.

Connects validators.py (claim-vs-source local checks) with trace_clients.py
(external registry/alias/literature lookups), producing a stream of
CitationTrace records per claim. Each record names a single check on a
single (claim_id, ref) pair: passed/failed + human-readable detail +
optional source-text excerpt.

DESIGN-001 §6.1 names citation-trace as **the moat**. It is what
distinguishes Researka-style adjudication from arXiv: every cited NCT,
every cited p-value, every cited percentage, every drug-alias claim is
verified against an authoritative source AND against the source's own
abstract. The 5 TraceType values (frozen at Day 1 in agent/schemas.py)
correspond to 5 checks here:

| TraceType            | Check                                              |
|----------------------|----------------------------------------------------|
| nct_exists           | TrialRegistryClient.get_trial(source.nct) != None |
| p_value_in_text      | every p-value in claim.text appears in abstract   |
| percentage_in_text   | every percentage in claim.text appears in abstract |
| alias_match          | DrugAliasClient.lookup() resolves names in claim   |
| role_match           | claim.directness aligns with cited evidence roles  |

Hard rule (DESIGN-001 §1, posted at top of compiler.py):
  LLM PROPOSES. CODE DISPOSES.
  - Claim membership in paper.md: gated by claim_graph.json. LLM cannot add claims.

Citation trace is the audit-trail half of "code disposes". The LLM may
propose claims, but each claim ships a per-check trace receipt; failed
traces become rejection rationale at the SPAR layer (Day 4).

Day 3.1 ships:
- 5 trace functions (one per TraceType)
- 1 orchestrator: trace_claim
- 1 graph orchestrator: trace_claim_graph
- 26 tests covering each trace + orchestrator + planted-failure cases 2/3/4

Day 3.3 will swap the fixture trace_clients backends for httpx + MCP
without changing this module — citation_trace.py only knows the
Protocol contract.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Iterator, Mapping

from agent.schemas import CitationTrace, Claim, ClaimGraph, TraceType
from agent.topic_pack import TopicPack
from agent.trace_clients import (
    DrugAliasClient,
    LiteratureClient,
    TrialRegistryClient,
    TrialStatus,
)
from agent.types import EvidenceItem
from agent.validators import PVALUE_RE, check_role_claim_match

__all__ = [
    "trace_nct_exists",
    "trace_role_match",
    "trace_p_value_in_text",
    "trace_percentage_in_text",
    "trace_alias_match",
    "trace_claim",
    "trace_claim_graph",
]

# Match bare percentages: "20%", "1.5%", "12 %". Captured as numeric string
# (no operator). Used by trace_percentage_in_text. Discriminating from
# REPORTED_OUTCOME_RE in text_signals: that regex requires effect-verb
# proximity to avoid matching "60% female" in protocol abstracts. Here
# we want EVERY percentage cited in a claim, on the assumption that
# claims don't cite irrelevant population descriptors.
_PERCENTAGE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")

# Drug-name-like tokens in claim prose: capitalized words ≥4 chars. The
# alias_match trace looks each candidate up in the DrugAliasClient. Common
# false positives (Trial, Study, Older, etc.) are filtered. This is
# deliberately coarse — the topic_pack alias whitelist + validators
# .check_alias_drift catch known-misuse patterns; alias_match is the
# external second layer for arbitrary drug names.
_DRUG_CANDIDATE_RE = re.compile(r"\b[A-Z][a-zA-Z]{3,}\b")
_DRUG_CANDIDATE_STOPWORDS = frozenset({
    # Trial/study language
    "trial", "trials", "study", "studies", "phase", "results", "evidence",
    "meta", "systematic", "review", "cohort", "observational", "registered",
    "registration", "clinical",
    # Population descriptors
    "older", "elderly", "adults", "adult", "patients", "subjects",
    "participants", "human", "humans", "men", "women",
    # Trial-design adjectives
    "double", "single", "blind", "placebo", "controlled", "randomized",
    "randomised", "open", "label", "pilot",
    # Effect verbs (past tense, past participle, gerund forms)
    "showed", "found", "reported", "demonstrated", "established", "proved",
    "associated", "compared", "investigated", "evaluated", "assessed",
    "reduced", "increased", "decreased", "improved", "lowered", "raised",
    "attenuated", "inhibited", "blunted", "enhanced", "elevated",
    "prolonged", "shortened", "abrogated", "reversed", "diminished",
    # Modifiers
    "effective", "ineffective", "significant", "significantly", "modest",
    "substantial", "primary", "secondary",
    # Aging-domain words
    "aging", "ageing", "longevity", "geroscience", "geroprotective",
    "cardiovascular", "mortality", "morbidity", "hazard", "risk",
    "frailty", "sarcopenia", "healthspan", "lifespan",
    # Common transition / connecting words capitalized at sentence start
    "this", "these", "those", "their", "there", "when", "where", "what",
    "which", "while", "with", "from", "the", "and", "but",
})

# Trial-status set indicating "results are publicly accessible". A claim
# citing a trial as published_results requires has_results=True OR a
# completed status (some registries have results not yet posted). For
# citation_trace, we treat has_results as the load-bearing field.
_RESULTS_AVAILABLE_STATUSES: frozenset[TrialStatus] = frozenset({
    "completed", "active_not_recruiting",
})


# --- Per-check trace functions --------------------------------------------


def trace_nct_exists(
    claim: Claim,
    item: EvidenceItem,
    registry: TrialRegistryClient,
) -> CitationTrace | None:
    """Verify that an NCT cited via source.nct resolves in the trial registry.

    Returns None when there's nothing to trace (source has no NCT). When
    the registry returns None for a populated NCT, that's planted-failure
    case 2 — fabricated NCT — caught at the external layer.
    """
    nct = item.source.nct
    if not nct:
        return None  # nothing to trace; not a failure
    record = registry.get_trial(nct)
    if record is None:
        return CitationTrace(
            claim_id=claim.claim_id, ref=item.source.ref,
            trace_type="nct_exists", passed=False,
            detail=f"NCT {nct!r} not found in registry (fabricated or stale)",
        )
    return CitationTrace(
        claim_id=claim.claim_id, ref=item.source.ref,
        trace_type="nct_exists", passed=True,
        detail=(
            f"{nct} found: status={record.status}, has_results={record.has_results}"
        ),
    )


def trace_role_match(
    claim: Claim,
    items_by_ref: Mapping[int, EvidenceItem],
) -> CitationTrace:
    """Wrap validators.check_role_claim_match into the trace shape.

    One CitationTrace per claim (not per ref) because the role-match check
    operates on the claim's full ref set, not individual refs.
    """
    failure = check_role_claim_match(claim, items_by_ref)
    if failure is None:
        return CitationTrace(
            claim_id=claim.claim_id, ref=0,  # 0 = claim-level (no specific ref)
            trace_type="role_match", passed=True,
            detail=(
                f"directness={claim.directness!r}, supporting_refs="
                f"{list(claim.supporting_refs)} consistent"
            ),
        )
    return CitationTrace(
        claim_id=claim.claim_id, ref=0,
        trace_type="role_match", passed=False,
        detail=f"{failure.code}: {failure.message}",
    )


def trace_p_value_in_text(
    claim: Claim,
    item: EvidenceItem,
) -> Iterator[CitationTrace]:
    """One CitationTrace per p-value cited in the claim. Each verifies the
    (op, digits) tuple appears in the source abstract.

    Yields nothing if the claim has no p-values — there's nothing to
    trace, which is not a failure.
    """
    claim_pvs = list(PVALUE_RE.findall(claim.text))
    if not claim_pvs:
        return
    source_pvs = set(PVALUE_RE.findall(item.abstract or ""))
    for op, digits in claim_pvs:
        canonical = f"p{op}0.{digits}"
        passed = (op, digits) in source_pvs
        excerpt = (item.abstract or "")[:200] if not passed else None
        yield CitationTrace(
            claim_id=claim.claim_id, ref=item.source.ref,
            trace_type="p_value_in_text", passed=passed,
            detail=(
                f"{canonical} {'found in' if passed else 'NOT found in'} "
                f"source abstract"
            ),
            source_excerpt=excerpt,
        )


def trace_percentage_in_text(
    claim: Claim,
    item: EvidenceItem,
) -> Iterator[CitationTrace]:
    """One CitationTrace per percentage cited in the claim. Each verifies
    the numeric value (e.g., "30") appears in the source abstract as a
    percentage."""
    claim_pcts = list(_PERCENTAGE_RE.findall(claim.text))
    if not claim_pcts:
        return
    source_pcts = set(_PERCENTAGE_RE.findall(item.abstract or ""))
    for pct in claim_pcts:
        passed = pct in source_pcts
        excerpt = (item.abstract or "")[:200] if not passed else None
        yield CitationTrace(
            claim_id=claim.claim_id, ref=item.source.ref,
            trace_type="percentage_in_text", passed=passed,
            detail=(
                f"{pct}% {'found in' if passed else 'NOT found in'} "
                f"source abstract"
            ),
            source_excerpt=excerpt,
        )


def trace_alias_match(
    claim: Claim,
    pack: TopicPack,
    drug_client: DrugAliasClient,
) -> Iterator[CitationTrace]:
    """For each drug-name-like capitalized token in the claim text, look
    up the alias in DrugAliasClient. None response = case 4 (alias drift)
    caught at the external layer.

    Skips tokens already in the pack alias whitelist (those are valid by
    definition) and common false-positive stopwords (Trial, Study, etc.).
    """
    seen: set[str] = set()
    for raw_token in _DRUG_CANDIDATE_RE.findall(claim.text):
        token = raw_token
        if token.lower() in _DRUG_CANDIDATE_STOPWORDS:
            continue
        if pack.has_alias(token):
            continue  # known topic alias — already validated
        if token.lower() in seen:
            continue
        seen.add(token.lower())
        record = drug_client.lookup(token)
        passed = record is not None
        yield CitationTrace(
            claim_id=claim.claim_id, ref=0,
            trace_type="alias_match", passed=passed,
            detail=(
                f"alias {token!r} {'resolved to' if passed else 'NOT resolved (drift)'}"
                + (f" {record.canonical_name!r}" if record else "")
            ),
        )


# --- Orchestrators --------------------------------------------------------


def trace_claim(
    claim: Claim,
    items_by_ref: Mapping[int, EvidenceItem],
    pack: TopicPack,
    *,
    registry: TrialRegistryClient,
    drug_client: DrugAliasClient,
    literature: LiteratureClient | None = None,  # reserved for Day 3.2+
) -> list[CitationTrace]:
    """Run every trace check for one claim. Returns the full record list.

    Order:
      1. role_match (claim-level)
      2. for each supporting_ref:
         a. nct_exists (if source.nct populated)
         b. p_value_in_text (per p-value)
         c. percentage_in_text (per percentage)
      3. alias_match (claim-level, per drug-name candidate)

    `literature` is wired for Day 3.2+ (fact-extraction will fetch
    abstracts when the local copy is missing). Unused in Day 3.1 traces.
    """
    traces: list[CitationTrace] = [trace_role_match(claim, items_by_ref)]

    for ref in claim.supporting_refs:
        item = items_by_ref.get(ref)
        if item is None:
            traces.append(CitationTrace(
                claim_id=claim.claim_id, ref=ref,
                trace_type="role_match", passed=False,
                detail=f"ref={ref} not present in evidence_items_by_ref",
            ))
            continue
        nct_trace = trace_nct_exists(claim, item, registry)
        if nct_trace is not None:
            traces.append(nct_trace)
        traces.extend(trace_p_value_in_text(claim, item))
        traces.extend(trace_percentage_in_text(claim, item))

    traces.extend(trace_alias_match(claim, pack, drug_client))
    return traces


def trace_claim_graph(
    graph: ClaimGraph,
    items_by_ref: Mapping[int, EvidenceItem],
    pack: TopicPack,
    *,
    registry: TrialRegistryClient,
    drug_client: DrugAliasClient,
    literature: LiteratureClient | None = None,
) -> list[CitationTrace]:
    """Run trace_claim on every claim in the graph. Returns the flat list
    suitable for serialization to citation_trace.json."""
    out: list[CitationTrace] = []
    for claim in graph.claims:
        out.extend(trace_claim(
            claim, items_by_ref, pack,
            registry=registry, drug_client=drug_client,
            literature=literature,
        ))
    return out


def summary(traces: Iterable[CitationTrace]) -> dict[str, int]:
    """Per-TraceType pass/fail counts. Useful for logs and the
    citation-trace failure dashboard (DESIGN-001 §6.1)."""
    counts: dict[str, int] = {}
    for t in traces:
        key = f"{t.trace_type}:{'pass' if t.passed else 'fail'}"
        counts[key] = counts.get(key, 0) + 1
    return counts


# Keep `summary` discoverable in __all__ for spar.py / compiler.py reuse.
__all__.append("summary")

# Re-export TraceType for consumers that don't want to depend on schemas
# directly when they're only working with citation_trace records.
__all__.append("TraceType")
_re_export_TraceType: TraceType = "nct_exists"  # noqa: F841 — type-anchor only
