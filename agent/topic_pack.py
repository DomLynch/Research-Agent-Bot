"""Topic pack loader — TOML + stdlib `tomllib`. No third-party YAML libs.

Loads a topic pack file (`topic_packs/<topic>.toml`) into a frozen TopicPack
dataclass and exposes the lookups that downstream stages need:
- alias whitelist (case-insensitive)
- canonical-trial expectations (used by qa_report surface check)
- known_role_overrides — the registry-pinned roles that evidence_cards.py
  consults BEFORE running the deterministic abstract classifier
- forbidden-verb sets for role-claim mismatch checks (consumed by validators.py)

This module owns NO classification logic — it's a pure loader + lookup layer.
Code disposes; this file is the table the code reads.
"""
from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Literal

__all__ = (
    "OverrideRecord", "CanonicalTrial", "BackgroundLiteratureEntry",
    "InferenceSpec", "TopicPack", "TopicPackError", "load_topic_pack",
)

# Type aliases match agent/types.py Role/Tier/Design literals so a hit in the
# override table is directly assignable to an EvidenceItem field.
_Role = Literal[
    "published_results",
    "published_protocol",
    "registered_pending",
    "review",
    "mechanistic",
    "off_domain",
]
_Tier = Literal["A1", "A2", "B", "C"]
_Design = Literal[
    "rct",
    "observational",
    "review",
    "meta_analysis",
    "protocol",
    "preprint",
    "registry",
    "mechanistic",
    "other",
]


class TopicPackError(ValueError):
    """Raised when a topic pack file is malformed."""


@dataclass(frozen=True, slots=True)
class OverrideRecord:
    """One row of `known_role_overrides`. Pins role/design/tier for a registry id."""

    role: _Role
    design: _Design
    tier: _Tier


@dataclass(frozen=True, slots=True)
class CanonicalTrial:
    """One canonical-trial expectation. Used by qa_report surface check."""

    id: str
    name: str
    expected_role: _Role
    design: _Design


@dataclass(frozen=True, slots=True)
class RetrievalSpec:
    """Slice 6 step 2 (Wave 7 cont., 2026-05-05): structured search
    parameters for calibrated exhaustive retrieval. Drives the per-
    source query builder so the same topic pack produces correct
    advanced queries on PubMed (MeSH+pt+dp), Europe PMC (KW+PUB_TYPE),
    OpenAlex (concepts+type), Crossref (type+from-pub-date), etc.

    All fields optional with sensible defaults so existing topic packs
    that lack a [retrieval] block fall back to their corpus_search_queries
    list unchanged.
    """
    topic_terms: tuple[str, ...] = ()       # canonical drug/concept names
    scope_terms: tuple[str, ...] = ()       # relevance context (e.g. aging)
    evidence_types: tuple[str, ...] = ()    # RCT / cohort / meta-analysis
    exclude_terms: tuple[str, ...] = ()     # known noise to drop
    date_from: int | None = None            # year, e.g. 2010
    date_to: int | None = None
    languages: tuple[str, ...] = ()         # e.g. ("English",)
    species: tuple[str, ...] = ()           # e.g. ("humans",)
    # [retrieval.background] sub-block — what counts as canonical
    # background literature (preclinical landmark, mechanism, dose
    # rationale, field history). Pulled into the background_literature
    # citation pool, NOT the core_on_thesis pool.
    background_allow: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class BackgroundLiteratureEntry:
    """One topic-specific background-numeric registry entry. Hoisted
    out of the global docs/background_literature.json so each topic
    pack owns its own canonical numerics."""

    key: str
    numeric: str
    context: str
    citation_token: str
    canonical_reference: str
    doi: str | None = None
    pmid: str | None = None


@dataclass(frozen=True, slots=True)
class InferenceSpec:
    """Optional D1 inferential-bridge config.

    This is data, not evidence. It authorizes bridge generation and
    names the canon references allowed to support conservation logic.
    """

    allow: bool = True
    accepted_mechanism_tiers: tuple[str, ...] = ()
    canon_references: tuple[str, ...] = ()
    max_inferences_per_paper: int = 5


@dataclass(frozen=True, slots=True)
class TopicPack:
    """Frozen topic pack. All collections are tuples / frozensets / mappingproxies.

    Aliases are stored lowercase for case-insensitive match. The original
    presentation casings live in `aliases_display` for prompt rendering.
    """

    topic: str
    drug_class: str
    aliases: frozenset[str]                  # lowercase, for matching
    aliases_display: tuple[str, ...]         # original case, for prompts
    expected_evidence_slots: tuple[str, ...]
    special_rules: tuple[str, ...]
    forbidden_verbs_for_protocol_role: frozenset[str]
    forbidden_verbs_for_results_role_with_protocol_keywords: frozenset[str]
    canonical_trials: tuple[CanonicalTrial, ...]
    # MappingProxyType — read-only view; mutation raises TypeError. The
    # frozen dataclass alone does NOT make the dict immutable; we need a
    # proxy wrapper so the registry-pinned roles cannot be overwritten at
    # runtime by any caller (defensive against accidental writes from
    # downstream stages — the table is sacred).
    known_role_overrides: Mapping[str, OverrideRecord]

    # --- v2 generic-multi-topic fields (Refactor 2026-05-04) ---
    # Active drug arm name synonyms (the topic compound's name as it
    # appears in trial-arm fields). Drives _claim_topic_effect()
    # generalization (was hardcoded `arm == "metformin"`).
    active_arm_synonyms: frozenset[str] = frozenset()
    placebo_arm_synonyms: frozenset[str] = frozenset(
        ("placebo", "control", "PLA", "vehicle"),
    )
    # Search queries for live corpus discovery. Drives
    # seed_topic_corpus.py --auto-corpus (was hardcoded in
    # fetch_evidence_typed_corpus.py).
    corpus_search_queries: tuple[str, ...] = ()
    # Paper IDs that should be treated as canonical RCTs by the
    # is_rct_papers logic (was hardcoded in run_v06_synthesis.py).
    canonical_rct_paper_ids: tuple[str, ...] = ()
    # Topic-specific background-literature numerics. Hoisted out
    # of docs/background_literature.json so global registry stays
    # generic.
    background_literature: tuple[BackgroundLiteratureEntry, ...] = ()
    # Endpoint polarity: which direction is "good" for the topic.
    # Was hardcoded in _claim_metformin_effect() polarity logic.
    # Map: outcome_class → "lower_is_better" | "higher_is_better"
    endpoint_polarity: Mapping[str, str] = field(
        default_factory=lambda: MappingProxyType({}),
    )
    # Slice 6 step 2: structured retrieval spec. None when the pack
    # has no [retrieval] block — caller falls back to the legacy
    # corpus_search_queries list.
    retrieval: "RetrievalSpec | None" = None
    # Slice 10 (2026-05-14): declared review type, one of the 7
    # canonical tokens in agent/review_type.REVIEW_TYPES. Drives the
    # Methods + Abstract framing + the journal_surface gate's
    # type-consistency check. Universal across any topic; default is
    # `prisma_scr_scoping_synthesis` (the most honest fit for
    # broad-corpus synthesis runs).
    review_type: str = "prisma_scr_scoping_synthesis"
    # Slice 21 (2026-05-15): declared submission target journal. Drives
    # `target_journal_pack.json` sidecar at pipeline exit so final_status
    # can resolve the target_journal dimension to pass. Universal — any
    # topic pack may declare a target. None = no target declared, the
    # pipeline writes a universal placeholder so final_status produces
    # an honest "target_journal not declared" record rather than missing.
    target_journal: str | None = None
    # Optional D1 bridge config. D1 never counts as receipt evidence.
    inference: InferenceSpec = InferenceSpec()
    osf: Mapping[str, str] | None = None

    # --- Lookups (intentionally explicit, not __contains__-style) ----------

    def has_alias(self, candidate: str) -> bool:
        """Case-insensitive alias whitelist check. Defends planted-failure case 4."""
        return candidate.strip().lower() in self.aliases

    def lookup_role_override(self, registry_id: str | None) -> OverrideRecord | None:
        """Return the pinned override for an NCT/ISRCTN, or None if not in pack.

        Case-insensitive: input is uppercased before the dict lookup, and
        the dict itself is built with uppercase keys at TOML load time
        (see _build_overrides). Both layers must agree on the canonical
        form so misformatted TOML or adapter output cannot silently miss.
        """
        if not registry_id:
            return None
        return self.known_role_overrides.get(registry_id.strip().upper())

    def is_protocol_verb_forbidden(self, verb: str) -> bool:
        return verb.strip().lower() in self.forbidden_verbs_for_protocol_role

    def is_results_protocol_keyword(self, keyword: str) -> bool:
        return (
            keyword.strip().lower()
            in self.forbidden_verbs_for_results_role_with_protocol_keywords
        )


# --- Loader -----------------------------------------------------------------

_REQUIRED_TOP_LEVEL = (
    "topic",
    "class_",
    "aliases",
    "expected_evidence_slots",
    "special_rules",
    "forbidden_verbs_for_protocol_role",
    "forbidden_verbs_for_results_role_with_protocol_keywords",
    "canonical_trials",
    "known_role_overrides",
)

_VALID_ROLES: frozenset[str] = frozenset({
    "published_results", "published_protocol", "registered_pending",
    "review", "mechanistic", "off_domain",
})
_VALID_DESIGNS: frozenset[str] = frozenset({
    "rct", "observational", "review", "meta_analysis",
    "protocol", "preprint", "registry", "mechanistic", "other",
})
_VALID_TIERS: frozenset[str] = frozenset({"A1", "A2", "B", "C"})


def _validate_top_level_keys(data: dict, path: Path) -> None:
    missing = [k for k in _REQUIRED_TOP_LEVEL if k not in data]
    if missing:
        raise TopicPackError(
            f"{path}: missing top-level keys {missing}. "
            f"TOML scoping bug suspect — top-level keys must be declared "
            f"BEFORE any [section] or [[array]] marker."
        )


def _build_canonical_trials(rows: list[dict], path: Path) -> tuple[CanonicalTrial, ...]:
    out: list[CanonicalTrial] = []
    for i, row in enumerate(rows):
        for key in ("id", "name", "expected_role", "design"):
            if key not in row:
                raise TopicPackError(
                    f"{path}: canonical_trials[{i}] missing key {key!r}"
                )
        if row["expected_role"] not in _VALID_ROLES:
            raise TopicPackError(
                f"{path}: canonical_trials[{i}] invalid role {row['expected_role']!r}"
            )
        if row["design"] not in _VALID_DESIGNS:
            raise TopicPackError(
                f"{path}: canonical_trials[{i}] invalid design {row['design']!r}"
            )
        out.append(CanonicalTrial(
            id=row["id"], name=row["name"],
            expected_role=row["expected_role"], design=row["design"],
        ))
    return tuple(out)


def _build_overrides(raw: dict, path: Path) -> Mapping[str, OverrideRecord]:
    """Build the override map with UPPERCASE keys.

    Canonicalizing the keys at load time means lookup_role_override only
    needs to upper-case its input — both layers agree on the canonical
    form. Without this, a TOML file with lowercase `nctXXX` keys would
    silently fail every lookup. Detecting duplicate keys after
    upper-casing also catches accidental case-only duplicates.
    """
    out: dict[str, OverrideRecord] = {}
    for registry_id, row in raw.items():
        canonical_id = registry_id.strip().upper()
        if canonical_id in out:
            raise TopicPackError(
                f"{path}: duplicate override id {canonical_id!r} "
                f"(after case normalization). Original keys produced this clash."
            )
        registry_id = canonical_id  # use canonical form going forward in this iter
        for key in ("role", "design", "tier"):
            if key not in row:
                raise TopicPackError(
                    f"{path}: known_role_overrides[{registry_id}] missing {key!r}"
                )
        if row["role"] not in _VALID_ROLES:
            raise TopicPackError(
                f"{path}: override {registry_id} invalid role {row['role']!r}"
            )
        if row["design"] not in _VALID_DESIGNS:
            raise TopicPackError(
                f"{path}: override {registry_id} invalid design {row['design']!r}"
            )
        if row["tier"] not in _VALID_TIERS:
            raise TopicPackError(
                f"{path}: override {registry_id} invalid tier {row['tier']!r}"
            )
        out[registry_id] = OverrideRecord(
            role=row["role"], design=row["design"], tier=row["tier"],
        )
    # Wrap in MappingProxyType so the registry-pinned roles are read-only.
    # Any attempt to mutate raises TypeError at runtime.
    return MappingProxyType(out)


def load_topic_pack(path: str | Path) -> TopicPack:
    """Load a topic pack TOML file into a frozen TopicPack.

    Raises TopicPackError on malformed input — preferable to silent
    misclassification later in the pipeline.
    """
    p = Path(path)
    if not p.exists():
        raise TopicPackError(f"topic pack not found: {p}")
    with p.open("rb") as fh:
        data = tomllib.load(fh)

    _validate_top_level_keys(data, p)

    aliases_raw = data["aliases"]
    if not aliases_raw:
        raise TopicPackError(f"{p}: aliases must be non-empty")
    aliases_lower = frozenset(a.strip().lower() for a in aliases_raw)
    aliases_display = tuple(aliases_raw)

    canonical = _build_canonical_trials(data["canonical_trials"], p)
    overrides = _build_overrides(data["known_role_overrides"], p)

    # v2 fields — all OPTIONAL with sensible defaults so existing
    # topic packs that don't set them keep working.
    active_arm_synonyms = frozenset(
        s.strip().lower()
        for s in data.get("active_arm_synonyms", [data["topic"]])
    )
    placebo_arm_synonyms = frozenset(
        s.strip().lower()
        for s in data.get(
            "placebo_arm_synonyms",
            ("placebo", "control", "PLA", "vehicle"),
        )
    )
    corpus_search_queries = tuple(
        data.get("corpus_search_queries", [])
    )
    canonical_rct_paper_ids = tuple(
        data.get("canonical_rct_paper_ids", [])
    )
    bg_lit_raw = data.get("background_literature", [])
    background_literature = tuple(
        BackgroundLiteratureEntry(
            key=row["key"],
            numeric=row["numeric"],
            context=row["context"],
            citation_token=row["citation_token"],
            canonical_reference=row["canonical_reference"],
            doi=row.get("doi"),
            pmid=row.get("pmid"),
        )
        for row in bg_lit_raw
        if all(k in row for k in (
            "key", "numeric", "context", "citation_token",
            "canonical_reference",
        ))
    )
    endpoint_polarity = MappingProxyType(
        dict(data.get("endpoint_polarity", {}))
    )

    # Slice 6 step 2: load [retrieval] / [retrieval.background] block.
    # All optional — packs without this block keep working via the
    # legacy corpus_search_queries fallback.
    retrieval = None
    raw_retrieval = data.get("retrieval")
    if isinstance(raw_retrieval, dict):
        bg_block = raw_retrieval.get("background", {}) or {}
        retrieval = RetrievalSpec(
            topic_terms=tuple(raw_retrieval.get("topic_terms", ())),
            scope_terms=tuple(raw_retrieval.get("scope_terms", ())),
            evidence_types=tuple(
                raw_retrieval.get("evidence_types", ())
            ),
            exclude_terms=tuple(
                raw_retrieval.get("exclude_terms", ())
            ),
            date_from=raw_retrieval.get("date_from"),
            date_to=raw_retrieval.get("date_to"),
            languages=tuple(raw_retrieval.get("languages", ())),
            species=tuple(raw_retrieval.get("species", ())),
            background_allow=tuple(bg_block.get("allow", ())),
        )
    raw_inference = data.get("inference")
    inference = InferenceSpec()
    if isinstance(raw_inference, dict):
        inference = InferenceSpec(
            allow=bool(raw_inference.get("allow", False)),
            accepted_mechanism_tiers=tuple(
                raw_inference.get("accepted_mechanism_tiers", ())
            ),
            canon_references=tuple(raw_inference.get("canon_references", ())),
            max_inferences_per_paper=int(
                raw_inference.get("max_inferences_per_paper", 5)
            ),
        )
    raw_osf = data.get("osf")
    osf = MappingProxyType(raw_osf) if isinstance(raw_osf, dict) else None

    return TopicPack(
        topic=data["topic"],
        drug_class=data["class_"],
        aliases=aliases_lower,
        aliases_display=aliases_display,
        expected_evidence_slots=tuple(data["expected_evidence_slots"]),
        special_rules=tuple(data["special_rules"]),
        forbidden_verbs_for_protocol_role=frozenset(
            v.strip().lower() for v in data["forbidden_verbs_for_protocol_role"]
        ),
        forbidden_verbs_for_results_role_with_protocol_keywords=frozenset(
            v.strip().lower()
            for v in data["forbidden_verbs_for_results_role_with_protocol_keywords"]
        ),
        canonical_trials=canonical,
        known_role_overrides=overrides,
        active_arm_synonyms=active_arm_synonyms,
        placebo_arm_synonyms=placebo_arm_synonyms,
        corpus_search_queries=corpus_search_queries,
        canonical_rct_paper_ids=canonical_rct_paper_ids,
        background_literature=background_literature,
        endpoint_polarity=endpoint_polarity,
        retrieval=retrieval,
        inference=inference,
        osf=osf,
        review_type=_parse_review_type_field(data.get("review_type")),
        target_journal=(
            str(data["target_journal"]).strip() or None
            if isinstance(data.get("target_journal"), str)
            else None
        ),
    )


def _parse_review_type_field(raw: object) -> str:
    """Validate the optional `review_type` field at TOML load time so a
    misspelled token in any topic pack fails fast (not later at gate
    time). Universal — delegates to `agent.review_type.parse_review_type`."""
    from agent.review_type import parse_review_type
    return parse_review_type(raw if isinstance(raw, str) else None)
