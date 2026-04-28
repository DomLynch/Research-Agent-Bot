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

from agent.registry_overrides import _ISRCTN_RE, _NCT_RE
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
    "registry_ids_for",
    "trace_nct_exists",
    "trace_role_match",
    "trace_p_value_in_text",
    "trace_percentage_in_text",
    "trace_numeric_in_text",
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

# --- Numeric effect-size trace --------------------------------------------
#
# Day 9.1 (AAA push): the auditor judge was rejecting rapamycin / everolimus
# runs at ~75% of attempts because PEARL ηp² and PROTECTOR HR / OR effect
# sizes weren't traced — only p-values + percentages were. The auditor
# correctly read "untraced numeric in claim" as a verification gap.
#
# This trace covers the common effect-size statistics that appear in
# clinical trial claim text: hazard ratios, odds ratios, relative risks,
# absolute risk reductions, NNT, partial eta squared, beta coefficients,
# and confidence-interval ranges. Each detected numeric in the claim is
# verified against the source abstract (Unicode-normalized — abstracts
# from Lancet/BMJ-style journals use middle-dot 0·02 instead of 0.02).
#
# Match shape: NAME OPTIONAL_PUNCT VALUE — e.g. "HR 0.79", "HR=0.79",
# "HR, 0.79", "OR 0.601", "ηp² = 0.202", "95% CI 0.66-0.95",
# "(aHR 0.85)". Captures (name, value) tuples. Order-of-pattern matters:
# the longer / more-specific names (95% CI, partial η²) come first so a
# bare HR pattern doesn't swallow the numeric out of a longer expression.
#
# Names supported (alternation, case-insensitive):
#   - 95% CI / 90% CI / 99% CI                  (confidence intervals)
#   - HR / aHR (adjusted HR)                    (hazard ratio)
#   - OR / aOR                                  (odds ratio)
#   - RR / aRR                                  (relative risk)
#   - ARR                                       (absolute risk reduction)
#   - NNT                                       (number needed to treat)
#   - β / beta                                  (regression coefficient)
#   - ηp² / partial η² / partial eta squared    (effect size, ANOVA)
#   - SMD                                       (standardized mean difference)
#
# Value capture:
#   - Single point estimate: "HR 0.79"
#   - Range: "95% CI 0.66-0.95" / "95% CI 0.66 to 0.95"
#
# Trace logic mirrors trace_p_value_in_text: one CitationTrace per
# detected numeric, passed=True iff the (normalized) value appears in
# the (normalized) abstract.

# Effect-size names — case-insensitive alternation. Order matters: longer
# patterns first so "95% CI" doesn't get partially matched as a bare CI.
_EFFECT_NAME_PATTERN = (
    r"95\s*%\s*CI|90\s*%\s*CI|99\s*%\s*CI"
    r"|partial\s+η[2²]|partial\s+eta\s+squared|η[p]?[2²]|eta\s+squared"
    r"|aHR|aOR|aRR|HR|OR|RR|ARR|NNT|SMD"
    r"|β|beta"
)
# Value: a number (possibly negative) optionally followed by a range
# separator (-, –, 'to') and a second number. Captures the full string
# including range so we can look it up verbatim in the source.
_NUMERIC_VALUE_PATTERN = (
    r"-?\d+(?:[.·]\d+)?"
    r"(?:\s*(?:[-–]|to)\s*-?\d+(?:[.·]\d+)?)?"
)
# Glue: optional punctuation between name and value (= , : - or just space)
_NUMERIC_RE = re.compile(
    rf"\b({_EFFECT_NAME_PATTERN})\s*[=:,\-]?\s*({_NUMERIC_VALUE_PATTERN})",
    re.IGNORECASE,
)


def _normalize_numeric_text(text: str) -> str:
    """Lowercase + collapse whitespace + Unicode middle-dot/en-dash → ASCII.

    Mirrors fact_extractor._normalize_unicode but keeps the trace layer
    self-contained (no cross-module import for one helper). Applied to
    both claim and abstract before substring comparison.
    """
    return " ".join(
        text.replace("·", ".").replace("–", "-").replace("—", "-").split()
    ).lower()

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
    # Common transition / connecting words capitalized at sentence start.
    # Day 6.1 added the second batch after a live metformin run flagged
    # "After" + "Similarly" as drug-aliases, false-positive-rejecting two
    # legitimate result claims. These are PROSE CONNECTIVES, never drug
    # names — adding them is safe for any topic pack.
    "this", "these", "those", "their", "there", "when", "where", "what",
    "which", "while", "with", "from", "the", "and", "but",
    "after", "before", "during", "however", "moreover", "furthermore",
    "similarly", "likewise", "additionally", "consequently", "therefore",
    "although", "despite", "whereas", "while", "since", "because",
    "indeed", "notably", "specifically", "importantly", "interestingly",
    "overall", "finally", "first", "second", "third", "fourth", "next",
    "subsequently", "previously", "recently", "currently", "initially",
    # Body-composition / outcome terms commonly capitalized at sentence
    # start in clinical abstracts (Day 8.1 from rapamycin run regression)
    "lean", "visceral", "fat", "self", "muscle", "body", "weight",
    "mean", "median", "average", "total", "primary", "secondary",
    "compared", "using", "both", "either", "neither", "such",
    "treatment", "patients", "subjects", "control", "placebo",
})

# Trial-status set indicating "results are publicly accessible". A claim
# citing a trial as published_results requires has_results=True OR a
# completed status (some registries have results not yet posted). For
# citation_trace, we treat has_results as the load-bearing field.
_RESULTS_AVAILABLE_STATUSES: frozenset[TrialStatus] = frozenset({
    "completed", "active_not_recruiting",
})


# --- Per-check trace functions --------------------------------------------


def registry_ids_for(item: EvidenceItem) -> list[str]:
    """Collect all registry IDs (NCT/ISRCTN) from an EvidenceItem's surfaces.

    Mirrors the lookup-precedence in registry_overrides.lookup_override:
    source.nct first, then ISRCTN-in-source.url, then NCT/ISRCTN scanned
    from the abstract text. Deduplicates while preserving first-seen
    order so the trace records list reads predictably.

    Day 3.0 added the abstract scan to lookup_override; Day 3.1 P1.2
    follow-up makes citation_trace consult the same surfaces. Without
    this, a live MASTERS-style record (NCT only in abstract, source.nct=None)
    would have its role pinned by the override but receive NO external
    citation trace — silently inconsistent.

    Day 5.3-fix-2 promoted this from private — `scripts/e2e_metformin_proof_001.py`
    uses it for canonical-trial detection in `--max-items` capping. Keeping
    the surface-scan logic in one place avoids drift between the script
    and trace_nct_exists.
    """
    ids: list[str] = []
    seen: set[str] = set()

    def _add(candidate: str | None) -> None:
        if not candidate:
            return
        canonical = candidate.strip().upper()
        if canonical in seen:
            return
        seen.add(canonical)
        ids.append(canonical)

    if item.source.nct:
        _add(item.source.nct)
    if item.source.url:
        for digits in _ISRCTN_RE.findall(item.source.url):
            _add(f"ISRCTN{digits}")
    if item.abstract:
        for nct in _NCT_RE.findall(item.abstract):
            _add(nct)
        for digits in _ISRCTN_RE.findall(item.abstract):
            _add(f"ISRCTN{digits}")
    return ids


def trace_nct_exists(
    claim: Claim,
    item: EvidenceItem,
    registry: TrialRegistryClient,
) -> Iterator[CitationTrace]:
    """Yield one CitationTrace per registry id found across the item's
    source.nct + source.url + abstract surfaces.

    Three outcomes per id:
      1. registry has no record       → passed=False (case 2 fab NCT)
      2. registry has record, but
         item.role='published_results'
         AND record.has_results=False → passed=False (P1.1: case 1
         protocol-as-results — the registry says no results but the
         pipeline classified the cite as a published-results citation;
         contradiction caught at trace layer)
      3. registry has record, and
         (role != 'published_results'
          OR record.has_results)      → passed=True

    Yields nothing when no registry IDs exist on any surface — there's
    nothing to trace, which is not a failure.
    """
    for nct in registry_ids_for(item):
        record = registry.get_trial(nct)
        if record is None:
            yield CitationTrace(
                claim_id=claim.claim_id, ref=item.source.ref,
                trace_type="nct_exists", passed=False,
                detail=f"NCT {nct!r} not found in registry (fabricated or stale)",
            )
            continue
        if item.role == "published_results" and not record.has_results:
            yield CitationTrace(
                claim_id=claim.claim_id, ref=item.source.ref,
                trace_type="nct_exists", passed=False,
                detail=(
                    f"{nct} role='published_results' but registry says "
                    f"has_results=False (status={record.status}). "
                    f"Protocol-as-results contradiction at trace layer."
                ),
            )
            continue
        yield CitationTrace(
            claim_id=claim.claim_id, ref=item.source.ref,
            trace_type="nct_exists", passed=True,
            detail=(
                f"{nct} found: status={record.status}, "
                f"has_results={record.has_results}"
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


def trace_numeric_in_text(
    claim: Claim,
    item: EvidenceItem,
) -> Iterator[CitationTrace]:
    """One CitationTrace per effect-size numeric (HR / OR / RR / ηp² / β /
    CI / etc.) cited in the claim text. Each verifies the (name, value)
    pair appears in the source abstract — Unicode-normalized so a claim
    rendered with ASCII `0.79` traces against an abstract that writes
    `0·79` (Lancet / BMJ middle-dot convention).

    Yields nothing when the claim has no detected numeric tokens — that's
    not a failure. Day 9.1 added this trace to close the auditor's
    main rejection reason: "untraced numeric in claim" was firing on
    every PEARL run (rapamycin) and every PROTECTOR run (everolimus)
    because their primary outcomes are reported as ηp² / HR / OR pairs
    rather than p-values + percentages.
    """
    matches = list(_NUMERIC_RE.findall(claim.text))
    if not matches:
        return
    abstract_norm = _normalize_numeric_text(item.abstract or "")
    for name_raw, value_raw in matches:
        # Look for the value (or the (name, value) pair) in normalized abstract.
        # Day 9.1: pass if EITHER the bare value substring appears (most
        # journals format effect sizes as "(HR 0.79; ...)" so the value
        # alone is reliable proof) OR the name+value pair appears verbatim.
        value_norm = _normalize_numeric_text(value_raw)
        name_norm = _normalize_numeric_text(name_raw)
        # Strip whitespace inside the value (e.g. "0.66 - 0.95" → "0.66-0.95")
        # so range separators normalize too.
        value_compact = value_norm.replace(" ", "")
        passed = (
            value_compact in abstract_norm.replace(" ", "")
            or f"{name_norm} {value_norm}" in abstract_norm
        )
        canonical = f"{name_raw} {value_raw}".strip()
        excerpt = (item.abstract or "")[:200] if not passed else None
        yield CitationTrace(
            claim_id=claim.claim_id, ref=item.source.ref,
            trace_type="numeric_in_text", passed=passed,
            detail=(
                f"{canonical} {'found in' if passed else 'NOT found in'} "
                f"source abstract"
            ),
            source_excerpt=excerpt,
        )


def _trial_name_tokens(pack: TopicPack) -> frozenset[str]:
    """Build the set of capitalized tokens appearing in canonical_trial
    names. Used by trace_alias_match to avoid false-flagging trial
    acronyms (MASTERS, TAME, MILES, etc.) as drug-alias drift.

    For multi-word names like 'MET-PREVENT', extracts each capitalized
    fragment (≥3 chars) so 'PREVENT' alone in prose also passes.
    Includes the full name uppercased so the regex's stricter ≥4-char
    rule still skips short fragments embedded in matches.
    """
    out: set[str] = set()
    for ct in pack.canonical_trials:
        out.add(ct.name.upper())
        # Extract capitalized fragments (allow 3+ chars to cover TAME, MET)
        for fragment in re.findall(r"[A-Za-z]{3,}", ct.name):
            out.add(fragment.upper())
    return frozenset(out)


def trace_alias_match(
    claim: Claim,
    pack: TopicPack,
    drug_client: DrugAliasClient,
) -> Iterator[CitationTrace]:
    """For each drug-name-like capitalized token in the claim text, look
    up the alias in DrugAliasClient. None response = case 4 (alias drift)
    caught at the external layer.

    Skips:
      - tokens already in the pack alias whitelist (valid by definition)
      - common false-positive stopwords (Trial, Study, etc.)
      - canonical trial-name tokens (P1.3 fix: prose like 'MASTERS
        demonstrated...' was false-flagging MASTERS as a drug drift
        because trial acronyms look like drug names to the regex)
      - all-caps acronyms ≤6 chars (Day 6.3): VSMCs, SASP, AMPK, mTOR-
        style biological abbreviations are never drug names. Real drugs
        are mixed-case (Glucophage, Rapamycin) or trade-name proper
        nouns. The all-caps short-token shape is reserved for acronyms
        in scientific prose, never for drug aliases.
    """
    seen: set[str] = set()
    trial_tokens = _trial_name_tokens(pack)
    for raw_token in _DRUG_CANDIDATE_RE.findall(claim.text):
        token = raw_token
        if token.lower() in _DRUG_CANDIDATE_STOPWORDS:
            continue
        if pack.has_alias(token):
            continue  # known topic alias — already validated
        if token.upper() in trial_tokens:
            continue  # canonical trial acronym — not a drug-alias claim
        # All-caps acronym OR all-caps-with-trailing-lowercase-plural
        # ('RTIs', 'VSMCs') — biological acronyms, not drugs.
        core = token.rstrip("s") if token.endswith("s") else token
        if core.isupper() and len(token) <= 7:
            continue
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
         d. numeric_in_text (per HR/OR/RR/ηp²/β/CI/etc — Day 9.1)
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
        traces.extend(trace_nct_exists(claim, item, registry))
        traces.extend(trace_p_value_in_text(claim, item))
        traces.extend(trace_percentage_in_text(claim, item))
        traces.extend(trace_numeric_in_text(claim, item))

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
