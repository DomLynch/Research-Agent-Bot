"""Trace claim citations against source text and authoritative registries."""
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
    """Normalize claim and source numerics for trace comparison."""
    return " ".join(
        text.replace("·", ".").replace("–", "-").replace("—", "-").split()
    ).lower()


# Day 9.4 (reviewer P1 trust-spine fix): the previous numeric trace
# accepted ANY value substring in the abstract — `HR 0.79` falsely
# passed against an abstract that mentioned `0.79 kg` of weight loss
# with no HR context. Real label-value pairs in clinical abstracts
# co-occur within tight proximity (parentheses, brackets, "of"), so
# we require the label OR a known synonym to appear within ±60 chars
# of the value. The window is generous enough to cross "(HR, 0.79)"
# and "hazard ratio of 0.79" but tight enough to reject "HR" appearing
# elsewhere in the abstract while "0.79" is in an unrelated context.
_LABEL_PROXIMITY_WINDOW = 60

# Compact-form synonyms (lowercased, whitespace stripped). When the
# claim says "HR" the abstract may say "hazard ratio"; both must trace.
_LABEL_SYNONYMS: Mapping[str, tuple[str, ...]] = {
    "hr": ("hazardratio",),
    "ahr": ("adjustedhr", "adjustedhazardratio", "hazardratio", "hr"),
    "or": ("oddsratio",),
    "aor": ("adjustedor", "adjustedoddsratio", "oddsratio", "or"),
    "rr": ("relativerisk",),
    "arr": ("absoluteriskreduction",),
    "nnt": ("numberneededtotreat",),
    "smd": ("standardizedmeandifference",),
    "ηp2": ("ηp²", "partialη²", "partialη2", "partialetasquared"),
    "ηp²": ("ηp2", "partialη²", "partialη2", "partialetasquared"),
    "η2": ("η²", "etasquared"),
    "η²": ("η2", "etasquared"),
    "β": ("beta",),
    "beta": ("β",),
    "95%ci": ("95%confidenceinterval", "95ci"),
    "90%ci": ("90%confidenceinterval", "90ci"),
    "99%ci": ("99%confidenceinterval", "99ci"),
}


def _label_value_co_occurs(
    label_raw: str,
    value_raw: str,
    abstract: str,
) -> bool:
    """Require a value and label synonym to co-occur in source text."""
    abstract_compact = _normalize_numeric_text(abstract).replace(" ", "")
    label_compact = _normalize_numeric_text(label_raw).replace(" ", "")
    value_compact = _normalize_numeric_text(value_raw).replace(" ", "")
    if not value_compact or not abstract_compact:
        return False
    variants = (label_compact, *_LABEL_SYNONYMS.get(label_compact, ()))
    for m in re.finditer(re.escape(value_compact), abstract_compact):
        v_start, v_end = m.start(), m.end()
        window = abstract_compact[
            max(0, v_start - _LABEL_PROXIMITY_WINDOW):
            min(len(abstract_compact), v_end + _LABEL_PROXIMITY_WINDOW)
        ]
        if any(variant and variant in window for variant in variants):
            return True
    return False

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
    "although", "despite", "whereas", "since", "because",
    "indeed", "notably", "specifically", "importantly", "interestingly",
    "overall", "finally", "first", "second", "third", "fourth", "next",
    "subsequently", "previously", "recently", "currently", "initially",
    # Body-composition / outcome terms commonly capitalized at sentence
    # start in clinical abstracts (Day 8.1 from rapamycin run regression)
    "lean", "visceral", "fat", "self", "muscle", "body", "weight",
    "mean", "median", "average", "total",
    "using", "both", "either", "neither", "such",
    "treatment", "control",
    # Day 10.14 — generic biology/anatomy/physiology terms. Without
    # these, the alias-match trace queries ChEMBL for words like
    # "Mitochondrial" and ChEMBL returns the first molecule whose
    # description contains the term ("Mitoquinone Mesylate"). The
    # claim is talking about mitochondrial physiology, not a drug —
    # so the resolution is a false-positive. Empirical: caused
    # cluster_05 (Konopka 2019) to spuriously fail SPAR in the
    # Day 10.13 canonical-corpus benchmark. These are NOUNS THAT
    # MODIFY processes/structures, not drug names. Reserved for
    # generic biology vocabulary; specific drug names (Glucophage,
    # Rapamycin) still pass through.
    #
    # Day 10.14 reviewer note (deliberately NOT in the stoplist):
    # "Insulin", "Glucose" — these ARE legitimate drug-class names
    # (insulin glargine/lispro/detemir; glucose tablets). A future
    # diabetes-comparator topic_pack might cite them as comparator
    # therapies. Letting alias_match query them against ChEMBL keeps
    # that path open. The 7-paper metformin canonical corpus uses
    # "insulin" as a physiology term, but it's never capitalized at
    # sentence start except as a sentence-leading word — which the
    # capital-first regex catches. The risk-reward is letting them
    # through.
    "mitochondrial", "mitochondria", "metabolic", "metabolism",
    "respiratory", "respiration", "oxidative", "oxidation",
    "cellular", "molecular", "biological", "physiological",
    "skeletal", "vascular", "cardiac", "hepatic", "renal", "neural",
    "tissue", "tissues", "organ", "pathway", "pathways", "signaling",
    "receptor", "receptors", "enzyme", "enzymes", "protein", "proteins",
    "lipid", "lipids", "cholesterol", "triglyceride",
    "inflammation", "inflammatory", "immune", "immunity",
    "nuclear", "cytoplasmic", "membrane", "membranes",
    "endocrine", "neurological", "musculoskeletal",
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
    """Collect first-seen NCT/ISRCTN IDs from all evidence-item surfaces."""
    candidates = [
        item.source.nct,
        *(f"ISRCTN{digits}" for digits in _ISRCTN_RE.findall(item.source.url or "")),
        *_NCT_RE.findall(item.abstract or ""),
        *(f"ISRCTN{digits}" for digits in _ISRCTN_RE.findall(item.abstract or "")),
    ]
    return list(dict.fromkeys(value.strip().upper() for value in candidates if value))


def trace_nct_exists(
    claim: Claim,
    item: EvidenceItem,
    registry: TrialRegistryClient,
) -> Iterator[CitationTrace]:
    """Trace each registry ID; bind lagging results to PMID plus the same abstract ID."""
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
            abstract_ids = {
                *(value.upper() for value in _NCT_RE.findall(item.abstract or "")),
                *(f"ISRCTN{digits}" for digits in _ISRCTN_RE.findall(item.abstract or "")),
            }
            if item.source.pmid and nct in abstract_ids:
                yield CitationTrace(
                    claim_id=claim.claim_id, ref=item.source.ref,
                    trace_type="nct_exists", passed=True,
                    detail=(
                        f"{nct} found: status={record.status}, "
                        f"registry has_results=False but item has "
                        f"PMID {item.source.pmid} whose abstract names {nct} — "
                        f"peer-reviewed paper is bound to the lagging registry."
                    ),
                )
                continue
            yield CitationTrace(
                claim_id=claim.claim_id, ref=item.source.ref,
                trace_type="nct_exists", passed=False,
                detail=(
                    f"{nct} role='published_results' but registry says "
                    f"has_results=False (status={record.status}) AND "
                    f"item has no PMID-to-{nct} abstract binding — no verified "
                    f"peer-reviewed publication backing the registry record. "
                    f"Protocol-as-results contradiction."
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
    """Trace claim-level role compatibility across all supporting refs."""
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
    """Trace each claim p-value to the source abstract."""
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
    """Trace each claim percentage to the source abstract."""
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
    """Trace each normalized effect-size label/value pair to source text."""
    matches = list(_NUMERIC_RE.findall(claim.text))
    if not matches:
        return
    for name_raw, value_raw in matches:
        passed = _label_value_co_occurs(name_raw, value_raw, item.abstract or "")
        canonical = f"{name_raw} {value_raw}".strip()
        excerpt = (item.abstract or "")[:200] if not passed else None
        yield CitationTrace(
            claim_id=claim.claim_id, ref=item.source.ref,
            trace_type="numeric_in_text", passed=passed,
            detail=(
                f"{canonical} {'found in' if passed else 'NOT found in'} "
                f"source abstract (label+value co-occurrence within "
                f"{_LABEL_PROXIMITY_WINDOW} chars)"
            ),
            source_excerpt=excerpt,
        )


def _trial_name_tokens(pack: TopicPack) -> frozenset[str]:
    """Return canonical trial-name tokens exempt from drug-alias lookup."""
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
    item: EvidenceItem | None = None,
) -> Iterator[CitationTrace]:
    """Trace source-bound pack aliases and drug-like claim tokens."""
    seen: set[str] = set()
    trial_tokens = _trial_name_tokens(pack)
    # When an EvidenceItem is supplied, bind each alias to THAT source: the
    # trace is keyed to its ref and the alias must appear in its abstract
    # (claim-AND-source specific, one trace per token×ref). Without one
    # (token-level callers), fall back to the global name-validity check at
    # ref=0. This replaces a single claim-level trace that validated names
    # globally but never tied them to the sources backing the claim.
    abstract = (getattr(item, "abstract", "") or "").lower() if item is not None else None
    ref = item.source.ref if item is not None else 0
    claim_low = claim.text.lower()
    for alias in sorted(pack.aliases):
        pattern = rf"(?<!\w){re.escape(alias)}(?!\w)"
        if not re.search(pattern, claim_low):
            continue
        seen.update(re.findall(r"[a-z0-9]+", alias))
        in_source = abstract is None or re.search(pattern, abstract) is not None
        yield CitationTrace(
            claim_id=claim.claim_id, ref=ref,
            trace_type="alias_match", passed=in_source,
            detail=(
                f"known topic alias {alias!r}"
                + ("" if abstract is None else (
                    "; present in source" if in_source else "; ABSENT from source"
                ))
            ),
        )
    for raw_token in _DRUG_CANDIDATE_RE.findall(claim.text):
        token = raw_token
        if token.lower() in _DRUG_CANDIDATE_STOPWORDS:
            continue
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
        in_source = abstract is None or token.lower() in abstract
        passed = record is not None and in_source
        resolved = f"resolved to {record.canonical_name!r}" if record else "NOT resolved (drift)"
        presence = "" if abstract is None else (
            "; present in source" if token.lower() in abstract else "; ABSENT from source"
        )
        yield CitationTrace(
            claim_id=claim.claim_id, ref=ref,
            trace_type="alias_match", passed=passed,
            detail=f"alias {token!r} {resolved}{presence}",
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
    """Run all claim-level and source-level citation traces in stable order."""
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
        # Per-ref: bind each drug alias in the claim to THIS source (was a
        # single claim-level global validity check at ref=0).
        traces.extend(trace_alias_match(claim, pack, drug_client, item))
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
    """Return flattened citation traces for every claim in the graph."""
    out: list[CitationTrace] = []
    for claim in graph.claims:
        out.extend(trace_claim(
            claim, items_by_ref, pack,
            registry=registry, drug_client=drug_client,
            literature=literature,
        ))
    return out


def summary(traces: Iterable[CitationTrace]) -> dict[str, int]:
    """Count pass/fail traces by trace type."""
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
