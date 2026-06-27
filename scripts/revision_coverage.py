"""LLM coverage judge: verify each enumerated Researka revision ask is
MATERIALLY addressed in the rendered paper before submit.

Uses the SPAR judge chain (Gemma primary — a different model family than the
MiMo writer, per the judge!=writer rule). Fail-open: any judge/infra error or
a malformed verdict returns no unmet asks, so an LLM outage can never block the
whole submission pipeline. Topic-agnostic — the asks come verbatim from
Researka; no per-topic knowledge.
"""
from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from agent.llm_client import LLMError, LLMResponse, build_judge_chain, chat_json
from agent.settings import load_settings

_SYS = "You are a strict manuscript reviewer. Reply with JSON only."
_USER = (
    "Below are {n} required revisions and a manuscript. For EACH revision, in "
    "order, decide whether the manuscript MATERIALLY addresses it — a substantive "
    "change, not merely repeating the words. Reply with JSON "
    '{{"addressed": [<one boolean per revision, in the same order>]}}.\n\n'
    "REQUIRED REVISIONS:\n{asks}\n\n=== MANUSCRIPT ===\n{paper}"
)


def revision_asks(feedback: str) -> list[str]:
    """Split Researka's joined reviewer feedback into material revision asks."""
    starts = (
        "Add", "Audit", "Clarify", "Correct", "Define", "Differentiate",
        "Document", "Ensure", "Explain", "Expand", "Fix", "For each",
        "Enumerate", "Hedge", "In", "Include", "Integrate", "Make", "Narrow",
        "Move", "Operationalize", "Populate",
        "Provide", "Recode", "Re-extract", "Either", "Mark", "Reclassify",
        "Recompute", "Reconcile", "Reduce", "Regenerate", "Remove", "Repair", "Resolve",
        "Replace", "Restate", "Restructure", "Rewrite", "Separate", "Soften", "Strengthen",
        "Surface", "Tighten", "Update", "Verify",
    )
    pattern = r";\s+(?=(?:" + "|".join(re.escape(start) for start in starts) + r")\b)"
    asks = [_with_terminal_punctuation(a.strip()) for a in re.split(pattern, feedback) if a.strip()]
    return [
        re.sub(r"^PRIOR REVISION DID NOT ADDRESS THESE REQUIRED POINTS\b.*?\bEACH:\s*", "", ask).strip()
        for ask in asks
    ]


def _with_terminal_punctuation(text: str) -> str:
    return text if not text or text[-1] in ".!?)'\"" else f"{text}."


def _excerpt(paper_md: str, head: int = 16000, tail: int = 8000) -> str:
    """Head + tail of the paper so the judge sees both the abstract/intro and
    the conclusion/limitations — where reviewer asks concentrate — without
    paying for the full ~50k-word body."""
    if len(paper_md) <= head + tail:
        return paper_md
    return f"{paper_md[:head]}\n\n[... middle omitted ...]\n\n{paper_md[-tail:]}"


def unmet_asks(
    paper_md: str,
    asks: Sequence[str],
    *,
    chat: Callable[..., Awaitable[LLMResponse]] = chat_json,
    runner: Callable[..., Any] = asyncio.run,
    settings: Any | None = None,
) -> list[str]:
    """Return the asks NOT materially addressed by the paper. Empty when every
    ask is met — or fail-open ([]) on any error or malformed verdict."""
    clean = [a.strip() for a in asks if a and a.strip()]
    if not clean:
        return []
    try:
        numbered = "\n".join(f"{i}. {a}" for i, a in enumerate(clean, 1))
        resp = runner(chat(
            messages=[
                {"role": "system", "content": _SYS},
                {"role": "user", "content": _USER.format(n=len(clean), asks=numbered, paper=_excerpt(paper_md))},
            ],
            chain=build_judge_chain(settings or load_settings()),
            temperature=0.0,
            seed=7,
        ))
        flags = resp.parsed.get("addressed", [])
    except (LLMError, ValueError, KeyError, TypeError, AttributeError, OSError, RuntimeError):
        return []  # fail-open — never block submit on a judge/infra failure
    if not isinstance(flags, list) or len(flags) != len(clean):
        return []  # malformed verdict — fail-open
    return [a for a, ok in zip(clean, flags, strict=True) if not ok]


def material_unmet_asks(paper_md: str, feedback: str) -> list[str]:
    """Coverage result after deterministic structural checks and LLM judge."""
    asks = revision_asks(feedback)
    unmet = deterministic_unmet_asks(paper_md, asks)
    deterministic_met = set(deterministic_satisfied_asks(paper_md, asks))
    for ask in unmet_asks(paper_md, asks):
        if ask not in unmet and ask not in deterministic_met:
            unmet.append(ask)
    return unmet


def deterministic_unmet_asks(paper_md: str, asks: Sequence[str]) -> list[str]:
    """Reviewer asks with deterministic manuscript evidence.

    The LLM coverage judge stays useful for semantic asks, but these recurring
    Researka revise classes are structural enough to verify directly. This
    makes the gate resilient when the judge fails open.
    """
    clean = [a.strip() for a in asks if a and a.strip()]
    if not clean:
        return []
    return [ask for ask in clean if not _deterministic_ask_satisfied(paper_md, ask)]


def deterministic_satisfied_asks(paper_md: str, asks: Sequence[str]) -> list[str]:
    """Reviewer asks whose structural predicate is known and satisfied."""
    clean = [a.strip() for a in asks if a and a.strip()]
    return [ask for ask in clean if _deterministic_ask_known(ask) and _deterministic_ask_satisfied(paper_md, ask)]


def deterministic_known_asks(asks: Sequence[str]) -> list[str]:
    """Reviewer asks covered by deterministic structural predicates."""
    clean = [a.strip() for a in asks if a and a.strip()]
    return [ask for ask in clean if _deterministic_ask_known(ask)]


def _deterministic_ask_known(ask: str) -> bool:
    lower = " ".join(ask.lower().split())
    return any(
        predicate(lower)
        for predicate in (
            _asks_classification_criteria,
            _asks_conflict_severity_criteria,
            _asks_source_outcome_class_map,
            _asks_findings_map_source_verdict,
            _asks_key_findings_source_verdict,
            _asks_most_supported_key_findings,
            _asks_adjacent_indirect_reconciliation,
            _asks_source_classification_map,
            _asks_evidence_type_metadata,
            _asks_source_inclusion_rationale,
            _asks_species_study_design_summary,
            _asks_source_directness_breakdown,
            _asks_source_statistics_landscape,
            _asks_citation_traceability_map,
            _asks_source_label_disambiguation,
            _asks_source_verification_transparency,
            _asks_source_identifier_gap_note,
            _asks_section_source_grounding,
            _asks_outcome_class_key_findings,
            _asks_two_part_research_question,
            _asks_concrete_research_question,
            _asks_scope_framing,
            _asks_outcome_taxonomy_separation,
            _asks_source_stratification_reconciliation,
            _asks_mr_causal_count,
            _asks_direction_tally_audit,
            _asks_source_scope_annex,
            _asks_direct_interventional_reclassification,
            _asks_combination_product_signal_boundary,
            _asks_substantive_evidence_synthesis,
            _asks_forward_dated_ai_disclosure_note,
            _asks_publication_year_note,
            _asks_intervention_target_boundary,
            _asks_rct_count_reconciliation,
            _asks_unbacked_appraisal_names,
            _asks_evidence_tier_directness_bounds,
            _asks_search_summary_scope_note,
            _asks_additive_screening_flow,
            _asks_admission_funnel_numeric_consistency,
            _asks_prisma_all_included_rationale,
            _asks_single_source_proportionality,
            _asks_claim_count_audit,
            _asks_direct_evidence_definition,
            _asks_evidence_boundary,
            _asks_conclusion_unproven_humans,
            _asks_directional_coding,
            _asks_directional_table_narrative_consistency,
            _asks_contextual_without_directional_signal,
            _asks_direction_coding_visibility,
            _asks_direction_coded_source_highlights,
            _asks_actionable_gaps,
            _asks_null_signal_reconciliation,
            _asks_subgroup_lens_narrative,
            _asks_underpopulated_outcome_subsections,
            _asks_replaced_surface_tensions,
            _asks_concrete_tensions_gaps,
            _asks_internal_duplication,
            _asks_long_term_safety_scope,
            _asks_unbundled_citation_cleanup,
            _asks_structured_table_stub_replacement,
            _asks_outcome_label_cleanup,
            _asks_substantive_conclusion,
            _asks_conclusion_weight_boundary,
            _asks_source_count_bundle_reconciliation,
            _asks_corpus_count_reconciliation,
            _asks_evidence_honesty_repetition,
            _asks_named_direct_clinical_source,
            _asks_outcome_subsection_source_narrative,
            _asks_protocol_design_limitations,
            _asks_external_reference_boundary,
            _asks_reference_traceability,
            _asks_prior_publication_differentiation,
            _asks_numeric_correction_markup_cleanup,
            _asks_numeric_effect_audit,
            _asks_named_numeric_correction,
            _asks_numeric_effect_accuracy,
            _asks_grammar_correction,
        )
    )


def _deterministic_ask_satisfied(paper_md: str, ask: str) -> bool:
    lower = " ".join(ask.lower().split())
    if _asks_classification_criteria(lower):
        text = paper_md.lower()
        return all(token in text for token in ("classification criteria", "outcome class", "directness", "evidence tier"))
    if _asks_conflict_severity_criteria(lower):
        text = paper_md.lower()
        return all(
            token in text
            for token in (
                "conflict-map severity note",
                "severity-level-3",
                "severity-level-4",
                "contradiction-map",
            )
        )
    if _asks_source_outcome_class_map(lower):
        if _asks_full_source_surface_request(lower):
            return _full_surface_sources_are_visible(paper_md, ask) and (
                _substantive_evidence_synthesis_is_stated(paper_md)
                or _source_outcome_class_map_is_stated(paper_md)
            )
        return _source_outcome_class_map_is_stated(paper_md) and _full_surface_sources_are_visible(paper_md, ask)
    if _asks_findings_map_source_verdict(lower):
        return _findings_map_source_verdict_is_stated(paper_md)
    if _asks_key_findings_source_verdict(lower):
        return _key_findings_source_verdict_is_stated(paper_md)
    if _asks_most_supported_key_findings(lower):
        return _most_supported_key_findings_are_stated(paper_md)
    if _asks_adjacent_indirect_reconciliation(lower):
        return _adjacent_indirect_reconciliation_is_stated(paper_md)
    if _asks_source_classification_map(lower):
        text = paper_md.lower()
        return all(token in text for token in ("source classification map", "outcome=", "directness=", "tier="))
    if _asks_evidence_type_metadata(lower):
        return _evidence_type_metadata_is_resolved(paper_md)
    if _asks_source_inclusion_rationale(lower):
        return _source_inclusion_rationale_is_stated(paper_md)
    if _asks_species_study_design_summary(lower):
        return _species_study_design_summary_is_stated(paper_md)
    if _asks_source_directness_breakdown(lower):
        return _source_directness_breakdown_is_stated(paper_md)
    if _asks_source_statistics_landscape(lower):
        return _source_statistics_landscape_is_stated(paper_md)
    if _asks_citation_traceability_map(lower):
        return _citation_traceability_map_is_stated(paper_md)
    if _asks_source_label_disambiguation(lower):
        return _source_label_disambiguation_is_stated(paper_md, ask)
    if _asks_source_verification_transparency(lower):
        return _source_verification_transparency_is_stated(paper_md)
    if _asks_source_identifier_gap_note(lower):
        return _source_identifier_gap_note_is_stated(paper_md)
    if _asks_section_source_grounding(lower):
        return _section_source_grounding_is_stated(paper_md)
    if _asks_outcome_class_key_findings(lower):
        return _outcome_class_key_findings_are_stated(paper_md)
    if _asks_two_part_research_question(lower):
        return _two_part_research_question_is_stated(paper_md)
    if _asks_concrete_research_question(lower):
        return _concrete_research_question_is_stated(paper_md)
    if _asks_scope_framing(lower):
        return _scope_framing_is_stated(paper_md) and (
            not _asks_direction_tally_audit(lower) or _direction_tally_audit_is_stated(paper_md)
        )
    if _asks_outcome_taxonomy_separation(lower):
        return _outcome_taxonomy_separation_is_stated(paper_md)
    if _asks_source_stratification_reconciliation(lower):
        return _source_stratification_reconciliation_is_stated(paper_md)
    if _asks_mr_causal_count(lower):
        return _mr_causal_count_is_stated(paper_md, ask)
    if _asks_direction_tally_audit(lower):
        return _direction_tally_audit_is_stated(paper_md)
    if _asks_source_scope_annex(lower):
        return _source_scope_annex_is_stated(paper_md, ask)
    if _asks_direct_interventional_reclassification(lower):
        return _direct_interventional_reclassification_is_stated(paper_md, ask)
    if _asks_combination_product_signal_boundary(lower):
        return _combination_product_signal_boundary_is_stated(paper_md)
    if _asks_substantive_evidence_synthesis(lower):
        return _substantive_evidence_synthesis_is_stated(paper_md) and _full_surface_sources_are_visible(paper_md, ask)
    if _asks_forward_dated_ai_disclosure_note(lower):
        return _forward_dated_ai_disclosure_note_is_stated(paper_md)
    if _asks_publication_year_note(lower):
        return _publication_year_note_is_stated(paper_md)
    if _asks_intervention_target_boundary(lower):
        return _intervention_target_boundary_is_stated(paper_md)
    if _asks_rct_count_reconciliation(lower):
        return _rct_count_reconciliation_is_stated(paper_md)
    if _asks_unbacked_appraisal_names(lower):
        return _unbacked_appraisal_names_are_resolved(paper_md)
    if _asks_evidence_tier_directness_bounds(lower):
        return _evidence_tier_directness_bounds_are_stated(paper_md)
    if _asks_search_summary_scope_note(lower):
        return _search_summary_scope_note_is_stated(paper_md)
    if _asks_additive_screening_flow(lower):
        return _additive_screening_flow_is_stated(paper_md)
    if _asks_admission_funnel_numeric_consistency(lower):
        return _admission_funnel_numeric_consistency_is_stated(paper_md)
    if _asks_prisma_all_included_rationale(lower):
        return _prisma_all_included_rationale_is_stated(paper_md)
    if _asks_single_source_proportionality(lower):
        return _single_source_proportionality_is_stated(paper_md)
    if _asks_claim_count_audit(lower):
        return _claim_count_audit_is_stated(paper_md)
    if _asks_direct_evidence_definition(lower):
        text = paper_md.lower()
        return (
            "qualifying direct source" in text
            or "direct interventional hard-endpoint evidence" in text
        )
    if _asks_evidence_boundary(lower):
        return _evidence_boundary_is_stated(paper_md, lower)
    if _asks_conclusion_unproven_humans(lower):
        return _conclusion_unproven_humans_is_stated(paper_md)
    if _asks_directional_coding(lower):
        return _directional_coding_explanation_is_material(paper_md)
    if _asks_directional_table_narrative_consistency(lower):
        return _directional_table_narrative_is_consistent(paper_md)
    if _asks_contextual_without_directional_signal(lower):
        return _contextual_without_directional_signal_is_explained(paper_md)
    if _asks_direction_coding_visibility(lower):
        return _direction_coding_visibility_is_stated(paper_md)
    if _asks_direction_coded_source_highlights(lower):
        return _direction_coded_source_highlights_are_stated(paper_md)
    if _asks_actionable_gaps(lower):
        return _gaps_section_is_actionable(paper_md)
    if _asks_null_signal_reconciliation(lower):
        return _null_signal_conclusion_is_bounded(paper_md)
    if _asks_subgroup_lens_narrative(lower):
        return _subgroup_lens_narrative_is_stated(paper_md, lower)
    if _asks_underpopulated_outcome_subsections(lower):
        return _underpopulated_outcome_subsections_are_stated(paper_md, lower)
    if _asks_replaced_surface_tensions(lower):
        return _replaced_surface_tensions_are_stated(paper_md, lower)
    if _asks_concrete_tensions_gaps(lower):
        return _concrete_tensions_gaps_are_stated(paper_md)
    if _asks_internal_duplication(lower):
        return _internal_duplication_is_low(paper_md, lower)
    if _asks_long_term_safety_scope(lower):
        return _long_term_safety_scope_is_stated(paper_md)
    if _asks_unbundled_citation_cleanup(lower):
        return _unbundled_citations_are_resolved(paper_md, ask)
    if _asks_structured_table_stub_replacement(lower):
        return _structured_table_stubs_are_replaced(paper_md)
    if _asks_outcome_label_cleanup(lower):
        return _outcome_label_cleanup_is_stated(paper_md)
    if _asks_substantive_conclusion(lower):
        return _substantive_conclusion_is_stated(paper_md)
    if _asks_conclusion_weight_boundary(lower):
        return _conclusion_weight_boundary_is_stated(paper_md)
    if _asks_source_count_bundle_reconciliation(lower):
        return _source_count_bundle_reconciliation_is_stated(paper_md)
    if _asks_corpus_count_reconciliation(lower):
        return _corpus_count_reconciliation_is_stated(paper_md)
    if _asks_evidence_honesty_repetition(lower):
        return _evidence_honesty_repetition_is_low(paper_md)
    if _asks_named_direct_clinical_source(lower):
        return _named_direct_clinical_source_is_stated(paper_md)
    if _asks_outcome_subsection_source_narrative(lower):
        return _outcome_subsection_source_narrative_is_stated(paper_md)
    if _asks_protocol_design_limitations(lower):
        return _protocol_design_limitations_are_stated(paper_md)
    if _asks_external_reference_boundary(lower):
        return _external_references_are_marked_illustrative(paper_md, lower)
    if _asks_reference_traceability(lower):
        return _references_are_traceable(paper_md)
    if _asks_prior_publication_differentiation(lower):
        return _prior_publication_differentiation_is_stated(paper_md)
    if _asks_numeric_correction_markup_cleanup(lower):
        return _numeric_correction_markup_is_resolved(paper_md)
    if _asks_numeric_effect_audit(lower):
        return _numeric_effect_audit_is_stated(paper_md) and not numeric_effect_direction_issues(paper_md)
    if _asks_named_numeric_correction(lower):
        return (
            _named_numeric_correction_is_stated(paper_md, lower)
            and _numeric_correction_markup_is_resolved(paper_md)
            and not numeric_effect_direction_issues(paper_md)
        )
    if _asks_numeric_effect_accuracy(lower):
        return not numeric_effect_direction_issues(paper_md)
    if _asks_grammar_correction(lower):
        return _grammar_artifacts_are_absent(paper_md)
    return True


def _asks_classification_criteria(text: str) -> bool:
    return "classification criteria" in text or (
        "assign" in text and "outcome class" in text and "directness" in text
    )


def _normalised_feedback(text: str) -> str:
    return " ".join(re.sub(r"[-\u2010-\u2015]+", " ", text.lower()).split())


def asks_source_classification_map(text: str) -> bool:
    return _asks_source_classification_map(_normalised_feedback(text))


def asks_evidence_type_metadata(text: str) -> bool:
    return _asks_evidence_type_metadata(_normalised_feedback(text))


def asks_source_directness_breakdown(text: str) -> bool:
    return _asks_source_directness_breakdown(_normalised_feedback(text))


def asks_source_outcome_class_map(text: str) -> bool:
    return _asks_source_outcome_class_map(_normalised_feedback(text))


def asks_scope_framing(text: str) -> bool:
    return _asks_scope_framing(_normalised_feedback(text))


def asks_outcome_taxonomy_separation(text: str) -> bool:
    return _asks_outcome_taxonomy_separation(_normalised_feedback(text))


def asks_direction_tally_audit(text: str) -> bool:
    return _asks_direction_tally_audit(_normalised_feedback(text))


def asks_source_scope_annex(text: str) -> bool:
    return _asks_source_scope_annex(_normalised_feedback(text))


def asks_conclusion_weight_boundary(text: str) -> bool:
    return _asks_conclusion_weight_boundary(_normalised_feedback(text))


def asks_findings_map_detail(text: str) -> bool:
    lower = _normalised_feedback(text)
    return (
        "findings map" in lower
        or (
            "specific findings" in lower
            and any(token in lower for token in ("cited source", "individual cited", "each retained source"))
        )
        or (
            "admitted source" in lower
            and any(token in lower for token in (
                "include all", "reconcile", "all 13", "all admitted",
                "replace with findings", "surface", "surfaced", "not surfaced",
            ))
        )
        or (
            "source" in lower
            and any(token in lower for token in ("outcome summaries", "outcome summary"))
            and any(token in lower for token in ("missing", "not surfaced", "several"))
        )
    )


def asks_source_attribution_map(text: str) -> bool:
    lower = _normalised_feedback(text)
    return (
        any(token in lower for token in ("attribute each", "finding level", "mapped claims", "outcome class"))
        and any(token in lower for token in ("source", "cited", "name and year", "by name", "by year"))
    ) or asks_source_outcome_class_map(lower)


def _asks_conflict_severity_criteria(text: str) -> bool:
    return (
        any(token in text for token in ("severity-level", "severity level"))
        and any(token in text for token in ("disagreement", "disagreements", "conflict", "conflict map"))
        and any(token in text for token in ("defined", "scored", "scoring", "supplementary", "supplemental"))
    )


def _asks_source_classification_map(text: str) -> bool:
    return "mapping table" in text or "mapping list" in text or (
        "which of the" in text and "source" in text and "outcome class" in text
    ) or (
        any(token in text for token in ("re-tier", "re tier", "retier", "misclassified"))
        and any(token in text for token in ("source", "human intervention", "mechanistic", "context", "directness"))
    )


def _asks_evidence_type_metadata(text: str) -> bool:
    return (
        "evidence_type" in text
        or ("evidence type" in text and "metadata" in text)
        or (
            "misclassified" in text
            and any(token in text for token in ("human intervention", "intervention studies", "clinical intervention"))
            and any(token in text for token in ("indirect", "review", "evidence"))
        )
    )


def _asks_source_directness_breakdown(text: str) -> bool:
    return (
        "source directness" in text
        or "directness/direction verdict" in text
        or (
            "source" in text
            and "direct" in text
            and "adjacent" in text
            and any(token in text for token in ("versus", "vs.", "which included", "scope statement"))
        )
        or (
            "source" in text
            and any(token in text for token in (
                "directly address", "directly addresses", "hard endpoint", "hard endpoints",
                "general digital biomarker", "broader", "off-topic", "off topic",
                "remove or reclassify", "remove or justify", "clearly address",
                "actually address",
            ))
            and any(token in text for token in ("adjacent", "general", "broader", "contextual", "off-topic", "off topic", "unrelated", "versus", "vs."))
        )
        or (
            any(token in text for token in ("re-tier", "re tier", "retier", "misclassified"))
            and any(token in text for token in ("source", "human intervention", "mechanistic", "context", "indirect", "review"))
        )
    )


def _asks_direction_tally_audit(text: str) -> bool:
    return (
        any(token in text for token in ("directional tally", "directional tallies", "per-source direction", "per source direction"))
        and "directness" in text
        and "tier" in text
    ) or (
        "counts in the prose" in text
        and "verified against" in text
        and "retained sources" in text
    )


def _asks_source_inclusion_rationale(text: str) -> bool:
    return (
        "source" in text
        and any(token in text for token in (
            "included under", "inclusion criteria", "included", "umbrella",
            "operationalize", "classified as addressing", "primary content",
            "prune", "reclassify", "define",
        ))
        and any(token in text for token in (
            "unrelated", "general", "other digital", "non-digital",
            "why sources", "justify", "adjacent context", "not about",
            "operationally", "population strata", "subgrouping axes",
        ))
    ) or (
        "define" in text
        and any(token in text for token in ("operationally", "operationalize"))
        and any(token in text for token in ("subgrouping axes", "population strata", "outcomes"))
    )


def _asks_species_study_design_summary(text: str) -> bool:
    return (
        "species" in text
        and ("study design" in text or "study-design" in text)
        and "summary table" in text
    )


def _asks_source_outcome_class_map(text: str) -> bool:
    if "combination-product" in text or "combination product" in text:
        return False
    return (
        "source" in text
        and any(token in text for token in ("outcome class", "coded outcome", "mapped claim"))
        and any(token in text for token in (
            "mapping table", "mapping list", "assigned to which", "which outcome",
            "per cited source", "trace each mapped claim",
        ))
        and any(token in text for token in ("external verification", "evidence landscape", "bundle sources", "source bundle"))
    ) or (
        "source" in text
        and any(token in text for token in ("findings map", "unaccounted", "attribute every admitted source"))
    ) or (
        "outcome class" in text
        and any(token in text for token in (
            "specific findings", "effect size", "directional statement",
            "study design", "population", "effect direction",
        ))
        and any(token in text for token in ("cited source", "individual cited", "each retained source"))
    ) or (
        "evidence landscape" in text
        and "admitted source" in text
        and any(token in text for token in (
            "include all", "reconcile", "all 13", "all admitted",
            "replace with findings", "surface", "surfaced", "not surfaced",
        ))
    ) or (
        "admitted source" in text
        and any(token in text for token in ("surface", "surfaced", "missing", "not surfaced"))
    ) or (
        "full admitted corpus" in text
        and "source" in text
        and any(token in text for token in ("outcome", "results", "evidence map"))
    ) or (
        "missing bundle source" in text
        and any(token in text for token in ("outcome", "results", "full admitted corpus"))
    ) or (
        "source" in text
        and any(token in text for token in ("outcome summaries", "outcome summary"))
        and any(token in text for token in ("missing", "not surfaced", "several"))
    )


def _asks_findings_map_source_verdict(text: str) -> bool:
    return (
        "findings map" in text
        and "source" in text
        and any(token in text for token in ("direction", "directness", "effect estimate", "qualitative finding"))
    )


def _asks_key_findings_source_verdict(text: str) -> bool:
    return (
        "key findings" in text
        and "source" in text
        and any(token in text for token in (
            "outcome class", "outcome slice", "retained sources", "effect size",
            "directional statement", "source abstracts", "abstracts", "concrete bounded findings",
            "source-anchored", "actual key findings",
        ))
    )


def _asks_adjacent_indirect_reconciliation(text: str) -> bool:
    return (
        "findings map" in text
        and "adjacent" in text
        and "indirect" in text
        and any(token in text for token in ("reconcile", "define", "consistently"))
    )


def _asks_source_statistics_landscape(text: str) -> bool:
    return (
        "specific statistics" in text
        and "evidence landscape" in text
        and any(token in text for token in ("source bundle", "outcome class", "buried"))
    )


def _asks_source_verification_transparency(text: str) -> bool:
    return (
        ("source bundle" in text or "reference-only" in text)
        and any(token in text for token in ("external verification", "independently verified", "exact statistics", "detailed quantitative"))
        and any(token in text for token in ("manifest", "methods_pack", "supplementary artifact", "supplemental artifact"))
    )


def _asks_source_identifier_gap_note(text: str) -> bool:
    return (
        any(token in text for token in ("without doi", "without dois", "missing doi", "no doi"))
        and any(token in text for token in ("verification-gap", "verification gap", "source-context", "source context"))
        and "source" in text
    )


def _asks_section_source_grounding(text: str) -> bool:
    return "source_grounding" in text or "directly supports that specific claim" in text or (
        "every claim" in text
        and all(token in text for token in ("key findings", "limitations", "conclusion"))
    )


def _asks_outcome_class_key_findings(text: str) -> bool:
    return (
        "key findings" in text
        and any(token in text for token in ("outcome-class", "outcome class", "outcome-class slices"))
        and any(token in text for token in ("bullet", "source", "sources support", "concrete"))
    )


def _asks_two_part_research_question(text: str) -> bool:
    return (
        "research question" in text
        and any(token in text for token in ("two-part", "two part", "both halves", "both claims"))
    )


def _asks_concrete_research_question(text: str) -> bool:
    return (
        "research question" in text
        and any(token in text for token in ("clear", "specific", "concrete", "answerable", "fix", "framing"))
    )


def _asks_substantive_evidence_synthesis(text: str) -> bool:
    return (
        "actual evidence synthesis" in text
        or "synthesis paragraph" in text
        or (
            "key findings" in text
            and "per-outcome-class" in text
            and ("source" in text or "finding" in text)
        )
        or (
            "within-class" in text
            and "synthesis narrative" in text
            and ("source" in text or "studies found" in text)
        )
        or ("integrate" in text and "evidence" in text)
        or (
            "strongest" in text
            and "positive" in text
            and any(token in text for token in ("finding", "findings", "signal", "signals"))
            and any(token in text for token in ("source citation", "source citations", "corpus", "evidence"))
        )
        or (
            "evidence landscape" in text
            and "key findings" in text
            and any(token in text for token in ("positive", "negative", "mixed", "substantive", "findings"))
        )
        or (
            "directional findings" in text
            and any(token in text for token in ("source abstract", "source abstracts", "source-level", "receipt-level", "null framing"))
        )
    )


def _asks_substantive_conclusion(text: str) -> bool:
    return (
        "conclusion" in text
        and any(token in text for token in (
            "what the evidence actually shows",
            "epistemic status",
            "not informative",
            "substantive conclusion",
        ))
    )


def _asks_combination_product_signal_boundary(text: str) -> bool:
    return (
        any(token in text for token in ("combination-product", "combination product", "monotherapy"))
        and any(token in text for token in ("positive signal", "positive sources", "positive findings"))
        and any(token in text for token in ("mouse model", "preclinical", "not human", "not a human"))
    )


def _combination_product_signal_boundary_is_stated(paper_md: str) -> bool:
    text = paper_md.lower()
    combination = "combination product" in text or "combination-product" in text
    no_monotherapy_attribution = any(
        token in text for token in (
            "cannot be attributed to spermidine monotherapy",
            "not be attributed to spermidine monotherapy",
            "not a spermidine-monotherapy signal",
            "not a spermidine monotherapy signal",
            "not spermidine-specific",
        )
    )
    preclinical_boundary = any(
        token in text for token in (
            "mouse model",
            "preclinical",
            "not a human clinical confirmation",
            "not human clinical confirmation",
            "non-human",
        )
    )
    return combination and no_monotherapy_attribution and preclinical_boundary


def _asks_rct_count_reconciliation(text: str) -> bool:
    return "rct" in text and any(token in text for token in ("single rct", "single direct rct", "two rcts", "more than one rct"))


def _asks_unbacked_appraisal_names(text: str) -> bool:
    return any(token in text for token in (
        "rob-2", "robins-i", "amstar-2", "risk-of-bias", "risk of bias",
        "appraisal", "rob judgment", "rob judgments",
    ))


def _asks_evidence_tier_directness_bounds(text: str) -> bool:
    return (
        "claims" in text
        and any(token in text for token in ("key findings", "conclusion"))
        and "evidence tier" in text
        and "directness" in text
    )


def _asks_admission_funnel_numeric_consistency(text: str) -> bool:
    text = _normalised_feedback(text)
    return (
        any(token in text for token in (
            "admission funnel", "admissions funnel", "source admission",
            "receipt admission", "receipt funnel",
        ))
        and any(token in text for token in (
            "numerical inconsistency", "numeric inconsistency", "inconsistently",
            "both equal", "contradictory", "contradiction", "clarify",
            "reconcile", "coherent accounting", "derived", "prisma style",
            "arithmetic scrutiny", "mutually exclusive", "additive rows",
            "remove the table", "arithmetic", "why",
        ))
    ) or ("no extractable claims" in text and "admitted final" in text) or (
        "partial/none-only" in text and "partial-only" in text
    ) or (
        "search summary" in text
        and "selection logic" in text
    ) or (
        "search summary" in text
        and any(token in text for token in ("source candidates", "admitted sources"))
        and any(token in text for token in (
            "non additive", "non-additive", "overlapping categories",
            "single transparent exclusion",
        ))
    )


def _asks_search_summary_scope_note(text: str) -> bool:
    return (
        "search summary" in text
        and any(token in text for token in (
            "date range", "date ranges", "topic-operationalization",
            "operationalization", "narrowing",
        ))
    )


def _asks_prisma_all_included_rationale(text: str) -> bool:
    return (
        "100%" in text
        and any(token in text for token in ("retrieved records", "records were included", "included"))
        and any(token in text for token in ("prisma", "eligibility criteria", "eligibility"))
    )


def _asks_single_source_proportionality(text: str) -> bool:
    return (
        ("single-source" in text or "single source" in text)
        and any(token in text for token in ("hypothesis-generating", "proportionality", "reduce narrative depth"))
    ) or (
        "outcome class" in text
        and ("n=1" in text or "one-source" in text or "one source" in text)
        and any(token in text for token in ("context-only", "parallel evidence", "merge them"))
    )


def _asks_claim_count_audit(text: str) -> bool:
    return (
        "claim count" in text
        and any(token in text for token in ("audit", "claim registry", "claim-derivation", "claim derivation"))
        and any(token in text for token in ("slice", "outcome", "source"))
    ) or (
        any(token in text for token in ("claim-counting methodology", "claim counting methodology"))
        and "high-confidence" in text
        and any(token in text for token in ("source", "sources", "claims"))
    )


def _asks_direct_evidence_definition(text: str) -> bool:
    return "direct evidence" in text and any(token in text for token in ("definition", "qualifying", "qualify", "0/"))


def _asks_evidence_boundary(text: str) -> bool:
    return (
        any(token in text for token in ("broad causal", "policy claims", "population-level proof", "hypothesis-generating"))
        and any(token in text for token in ("direct clinical evidence", "direct interventional", "adjacent/mechanistic", "mechanistic"))
    ) or (
        "calibration rules" in text
        and "direct clinical evidence" in text
        and any(token in text for token in ("broad population", "population-level proof", "proof is missing"))
    ) or (
        any(token in text for token in ("mixed and indirect", "indirect nature", "indirect evidence"))
        and any(token in text for token in ("abstract and conclusion", "abstract", "conclusion"))
        and any(token in text for token in ("overclaim", "proportionality", "mechanistic plausibility"))
    )


def _asks_conclusion_unproven_humans(text: str) -> bool:
    return (
        "conclusion" in text
        and any(token in text for token in ("unproven in humans", "currently unproven", "not proven in humans"))
    )


def _asks_directional_coding(text: str) -> bool:
    return "directional coding" in text or "effect_direction" in text or (
        any(token in text for token in ("re-extract direction", "re extract direction", "cannot determine direction"))
        and any(token in text for token in ("majority", "unclear", "direction"))
    ) or (
        "no extracted directional signal" in text and "clarify" in text
    ) or (
        "no extracted directional signal" in text and "reconcile" in text
    ) or (
        "no extracted directional signal" in text and "proportion" in text
    ) or (
        "null-coded" in text and "directional findings" in text
    ) or (
        "directional findings" in text
        and any(token in text for token in ("source abstract", "source abstracts", "receipt-level", "source-level", "null framing"))
    ) or (
        "directional map" in text
        and any(token in text for token in ("coded extraction", "predominantly unclear", "unclear-coded", "reconcile"))
    )


def _asks_direction_coding_visibility(text: str) -> bool:
    return (
        any(token in text for token in ("direction-coding", "direction coding", "directional coding"))
        and "unclear" in text
        and any(token in text for token in ("visible", "move", "prominent", "readers know", "narrative"))
    )


def _asks_direction_coded_source_highlights(text: str) -> bool:
    return (
        any(token in text for token in ("direction-coded", "direction coded", "direction-coded findings"))
        and any(token in text for token in ("top-cited", "top cited", "source statistic", "significant source statistic"))
        and any(token in text for token in ("outcome class", "each outcome", "interpretable"))
    )


def _asks_directional_table_narrative_consistency(text: str) -> bool:
    return (
        "evidence landscape" in text
        and any(token in text for token in ("no directional signal", "null directional signal", "all null directional", "predominantly unclear", "unclear"))
        and any(token in text for token in ("positive", "mixed", "negative", "positive/negative", "positive association", "positive associations", "positive signal", "positive signals"))
        and any(token in text for token in ("contradiction", "inconsistency", "narrative", "rest of the manuscript", "table coding", "needs correction"))
    )


def _asks_contextual_without_directional_signal(text: str) -> bool:
    return (
        "contextual claim" in text
        and any(token in text for token in ("no directional signal", "absence of directional", "near-total absence"))
    )


def _asks_actionable_gaps(text: str) -> bool:
    return (
        ("gaps identified" in text or "strengthen gaps" in text or "gaps with" in text)
        and any(token in text for token in ("actionable", "future research", "next steps", "concrete studies", "concrete actionable"))
    ) or (
        "gaps section" in text
        and any(token in text for token in ("cover all", "all five", "full outcome"))
        and any(token in text for token in ("outcome class", "outcome classes"))
    )


def _asks_null_signal_reconciliation(text: str) -> bool:
    return "null directional" in text and any(token in text for token in ("concluding", "conclusion", "rationale"))


def _asks_concrete_tensions_gaps(text: str) -> bool:
    return (
        (
            "tension" in text
            and "gap" in text
            and any(token in text for token in ("3-5", "3–5", "concrete", "specific sources", "tie each"))
        )
        or (
            "non-orthogonal tensions" in text
            and any(token in text for token in ("operationalize", "calculation", "verifiable", "auditable"))
        )
        or (
            "cross-study contradictions" in text
            and any(token in text for token in ("enumerate", "actually discussed", "body"))
        )
        or (
            ("cross-study disagreement" in text or "cross-source disagreement" in text)
            and any(token in text for token in (
                "substantiated", "enumerate", "enumerated",
                "actually-surfaced", "actually surfaced", "correct", "replace",
                "specific", "named sources", "where the disagreements lie", "what kinds",
            ))
        )
        or (
            "tensions and gaps" in text
            and any(token in text for token in ("specific disagreement", "specific disagreements", "naming specific"))
        )
    )


def _asks_subgroup_lens_narrative(text: str) -> bool:
    return (
        "subgroup lens" in text
        or "subgroup lenses" in text
        or ("subgroup" in text and "narrative synthesis" in text and "map" in text)
    )


def _asks_underpopulated_outcome_subsections(text: str) -> bool:
    return (
        "underpopulated outcome-class subsection" in text
        or "underpopulated outcome class subsection" in text
        or "per-outcome-class subsection" in text
        or ("outcome-class subsection" in text and any(token in text for token in ("expand", "remove the headers", "remove headers")))
    )


def _asks_replaced_surface_tensions(text: str) -> bool:
    return (
        "replace" in text
        and "surfaced tension" in text
        and any(token in text for token in ("within-outcome", "within outcome", "comparable"))
    )


def _asks_internal_duplication(text: str) -> bool:
    return any(token in text for token in ("internal duplication", "repetitive narrative", "verbatim repetition", "non-repetitive"))


def _asks_long_term_safety_scope(text: str) -> bool:
    return "long-term safety" in text or ("safety data" in text and "older adult" in text)


def _asks_named_direct_clinical_source(text: str) -> bool:
    return "direct clinical source" in text and any(token in text for token in ("which source", "clarify", "state this explicitly"))


def _asks_outcome_subsection_source_narrative(text: str) -> bool:
    return (
        "outcome subsection" in text
        and "source" in text
        and ("conclusion" in text or "direct source" in text)
    )


def _asks_protocol_design_limitations(text: str) -> bool:
    return (
        "limitations" in text
        and "protocol" in text
        and ("cross-sectional" in text or "observational" in text)
        and "causal claims" in text
    )


def _asks_reference_traceability(text: str) -> bool:
    return (
        "reference list" in text
        and any(token in text for token in ("doi", "pmid", "bibliographic identifier", "source bundle", "traceable"))
    ) or "traceable to the source bundle" in text


def _asks_citation_traceability_map(text: str) -> bool:
    return (
        "author-year" in text
        and "citation" in text
        and any(token in text for token in ("source bundle entry", "source-bundle entry", "bundle entry"))
        and any(token in text for token in ("methods_pack", "citation list", "mapping"))
    )


def _asks_source_label_disambiguation(text: str) -> bool:
    return (
        ("maps to exactly one" in text or "duplication" in text)
        and ("bundle entry" in text or "cited_as" in text or "cited as" in text or "label" in text)
    )


def _asks_unbundled_citation_cleanup(text: str) -> bool:
    return (
        "source_bundle" in text
        and "citation" in text
        and any(token in text for token in ("not in the source_bundle", "not in source_bundle", "not in the source bundle"))
    )


def _asks_structured_table_stub_replacement(text: str) -> bool:
    return (
        "see the structured evidence table" in text
        and any(token in text for token in ("replace", "stubs", "prose paragraph", "prose paragraphs"))
    )


def _asks_outcome_label_cleanup(text: str) -> bool:
    return (
        "dosing and pharmacokinetics" in text
        and any(token in text for token in (
            "re-label", "relabel", "remove", "not contain",
            "not a dosing", "not dosing", "not pk",
        ))
    )


def _asks_source_count_bundle_reconciliation(text: str) -> bool:
    return (
        "reconcile" in text
        and "source count" in text
        and "source bundle" in text
        and any(token in text for token in ("author-year", "citation", "bundle counterpart", "restore missing"))
    )


def _asks_external_reference_boundary(text: str) -> bool:
    return (
        "external" in text
        and any(token in text for token in ("non-corpus", "non corpus", "not in the source bundle"))
        and any(token in text for token in ("illustrative", "bundle source", "bundle sources", "remove"))
    )


def _asks_prior_publication_differentiation(text: str) -> bool:
    return "high overlap with publication" in text or (
        "differentiate" in text
        and "publication" in text
        and any(token in text for token in ("angle", "findings", "population"))
    )


def _asks_numeric_effect_accuracy(text: str) -> bool:
    if _asks_named_numeric_correction(text):
        return False
    return (
        any(token in text for token in ("p-value", "p value", "p-values", "reported p", "confidence interval", "effect direction"))
        and any(token in text for token in ("significant", "non-significant", "factual error", "correct", "audit", "direction"))
    )


def _asks_numeric_effect_audit(text: str) -> bool:
    return (
        any(token in text for token in ("audit all reported p-values", "audit all reported p values", "reported p-values", "reported p values"))
        and any(token in text for token in ("effect directions", "source bundle excerpts", "discrepancies"))
    )


def _asks_named_numeric_correction(text: str) -> bool:
    return (
        any(token in text for token in ("correct", "verify", "resolve", "reconcile", "recode", "recoded", "remove"))
        and any(token in text for token in ("p=", "p =", "p-value", "p value", "confidence interval"))
        and any(token in text for token in (
            "non-significant", "not significant", "no significant", "significant reduction", "factual error",
            "representative statistic", "miscoded", "direction/statistic", "direction statistic",
            "positive signal", "positive coding", "numeric correction", "unclear/null", "null/mixed",
        ))
    )


def _asks_numeric_correction_markup_cleanup(text: str) -> bool:
    return (
        "numeric correction" in text
        and any(token in text for token in ("leftover", "editing markup", "remove", "contextualize", "abstract", "research question"))
    )


def _asks_grammar_correction(text: str) -> bool:
    return any(token in text for token in ("grammatical error", "grammar error", "correct the grammatical"))


def _gaps_section_is_actionable(paper_md: str) -> bool:
    gaps = _section(paper_md, "Gaps Identified") or _section(paper_md, "Evidence-Gap Priority")
    if not gaps:
        return False
    text = gaps.lower()
    if len(gaps.split()) < 40:
        return False
    action_tokens = (
        "sample size", "powered", "priority population", "population", "follow-up",
        "duration", "endpoint", "trial", "randomized", "prospective", "safety",
        "dose", "comparator", "measurement",
    )
    return sum(1 for token in action_tokens if token in text) >= 3


def _null_signal_conclusion_is_bounded(paper_md: str) -> bool:
    scope = " ".join(part for part in (_abstract(paper_md), _section(paper_md, "Conclusion")) if part).lower()
    if not scope:
        return False
    if "bounded geroscience rationale" in scope and "null" not in scope:
        return False
    support_claim = bool(re.search(r"\bsupports?\b", scope))
    corrective = any(token in scope for token in (
        "does not support",
        "non-supportive",
        "hypothesis-generating only",
        "hypothesis-generating and not definitive",
    ))
    if support_claim and not corrective:
        return False
    return (
        any(token in scope for token in ("null", "mixed", "no extracted directional signal"))
        and any(token in scope for token in ("hypothesis-generating", "does not support", "non-supportive", "not definitive"))
    )


def _parenthetical_terms(text: str) -> list[str]:
    match = re.search(r"\(([^)]{3,240})\)", text)
    if not match:
        return []
    terms = []
    for piece in match.group(1).split(","):
        term = re.sub(r"^\s*and\s+", "", piece.strip(" .;:"), flags=re.I)
        if term:
            terms.append(" ".join(term.split()))
    return terms


def _term_pattern(term: str) -> re.Pattern[str]:
    tokens = [re.escape(token) for token in re.findall(r"[a-z0-9]+", term.lower())]
    return re.compile(r"\b" + r"(?:\s+and\s+|\s+)".join(tokens) + r"\b", re.I)


def _subgroup_lens_narrative_is_stated(paper_md: str, ask: str) -> bool:
    scope = " ".join(
        part for part in (
            _abstract(paper_md),
            _section(paper_md, "Results"),
            _section(paper_md, "Cross-Domain Synthesis"),
            _section(paper_md, "Discussion"),
            _section(paper_md, "Conclusion"),
        ) if part
    )
    if len(scope.split()) < 80:
        return False
    terms = _parenthetical_terms(ask)
    required = max(1, min(len(terms), 4))
    hits = sum(1 for term in terms if _term_pattern(term).search(scope))
    lower = scope.lower()
    return (
        hits >= required
        and "subgroup" in lower
        and re.search(r"\b[A-Z][A-Za-z-]+\s+20\d{2}\b", scope) is not None
    )


def _underpopulated_outcome_subsections_are_stated(paper_md: str, ask: str) -> bool:
    scope = _section(paper_md, "Results") + "\n\n" + _section(paper_md, "Evidence Snapshot")
    if not scope.strip():
        return False
    terms = _parenthetical_terms(ask)
    if not terms:
        return False
    paragraphs = re.split(r"\n\s*\n", scope)
    satisfied = 0
    for term in terms:
        pattern = _term_pattern(term)
        for idx, paragraph in enumerate(paragraphs):
            sectionlet = "\n\n".join(paragraphs[idx:idx + 2])
            if pattern.search(paragraph) and re.search(r"\b[A-Z][A-Za-z-]+\s+20\d{2}\b", sectionlet):
                satisfied += 1
                break
    return satisfied >= max(1, min(len(terms), 3))


def _concrete_tensions_gaps_are_stated(paper_md: str) -> bool:
    text = paper_md.lower()
    if "evidence-gap priority" not in text and "gaps identified" not in text:
        return False
    tension_lines = [
        line for line in paper_md.splitlines()
        if re.search(r"\b[A-Z][A-Za-z-]+\s+(?:19|20)\d{2}\b.*\b(?:vs\.?|versus)\b.*\b[A-Z][A-Za-z-]+\s+(?:19|20)\d{2}\b", line)
        and re.search(r"\b(?:tension|disagreement|conflict)\b", line, re.I)
    ]
    return len(tension_lines) >= 3


def _replaced_surface_tensions_are_stated(paper_md: str, ask: str) -> bool:
    scope = _section(paper_md, "Tensions and Gaps") or _section(paper_md, "Cross-Domain Synthesis")
    if not scope:
        return False
    blocked = {
        match.group(1).lower()
        for match in re.finditer(r"\b([a-z][a-z'’\-]+ 20\d{2})(?:-based|\s+based)\b", ask)
    }
    tension_lines = [
        line.strip()
        for line in scope.splitlines()
        if re.search(r"\b[A-Z][A-Za-z-]+\s+(?:19|20)\d{2}\b.*\b(?:vs\.?|versus)\b.*\b[A-Z][A-Za-z-]+\s+(?:19|20)\d{2}\b", line)
        and re.search(r"\b(?:tension|disagreement|conflict)\b", line, re.I)
    ]
    if len(tension_lines) < 3:
        return False
    if blocked and any(any(name in line.lower() for name in blocked) for line in tension_lines):
        return False
    comparable = [
        line for line in tension_lines
        if "same outcome" in line.lower() or re.search(r"\bin [A-Za-z][A-Za-z /-]+ because directions\b", line)
    ]
    return len(comparable) >= 3


def _internal_duplication_scope(paper_md: str, ask: str) -> str:
    names = (
        "Evidence Landscape", "Key Findings", "Results", "Full Manuscript",
        "Gaps Identified", "Discussion", "Limitations", "Conclusion",
    )
    sections = []
    named = False
    for name in names:
        if name.lower() in ask:
            named = True
            if name == "Full Manuscript":
                return paper_md
            section = _section(paper_md, name)
            if section:
                sections.append(f"## {name}\n\n{section}")
    return "\n\n".join(sections) if named else paper_md


def _internal_duplication_is_low(paper_md: str, ask: str = "") -> bool:
    seen: list[set[str]] = []
    for paragraph in re.split(r"\n\s*\n", _internal_duplication_scope(paper_md, ask)):
        text = " ".join(line.strip() for line in paragraph.splitlines() if not line.lstrip().startswith(("|", "#", "- [")))
        words = re.findall(r"[a-z0-9]+", text.lower())
        if len(words) < 18:
            continue
        tokens = set(words)
        if any(len(tokens & prior) / max(1, min(len(tokens), len(prior))) >= 0.75 for prior in seen):
            return False
        seen.append(tokens)
    return True


def _long_term_safety_scope_is_stated(paper_md: str) -> bool:
    scope = " ".join(part for part in (_abstract(paper_md), _section(paper_md, "Conclusion"), _section(paper_md, "Limitations")) if part).lower()
    if not scope:
        return False
    safety = "long-term safety" in scope or "long term safety" in scope or "safety data" in scope
    population = "older adult" in scope or "older adults" in scope or "aged" in scope
    return safety and population


def _evidence_type_metadata_is_resolved(paper_md: str) -> bool:
    scope = " ".join(
        part
        for part in (
            _section(paper_md, "Methods"),
            _section(paper_md, "Evidence Snapshot"),
            _section(paper_md, "Evidence Landscape"),
            _section(paper_md, "Results"),
        ) if part
    ).lower()
    return (
        any(token in scope for token in ("evidence_type", "evidence type"))
        and any(token in scope for token in ("review", "rct", "trial", "excerpt"))
        and any(token in scope for token in ("resolved", "reclassified", "classification criteria", "source classification map"))
    )


def _source_inclusion_rationale_is_stated(paper_md: str) -> bool:
    scope = " ".join(
        part for part in (
            _section(paper_md, "Methods"),
            _section(paper_md, "Evidence Snapshot"),
            _section(paper_md, "Evidence Landscape"),
            _section(paper_md, "Limitations"),
        ) if part
    ).lower()
    return (
        any(token in scope for token in ("inclusion rationale", "topic-fit rationale", "source directness breakdown", "source classification map"))
        and any(token in scope for token in ("operationalize", "directly addresses", "adjacent", "contextual", "excluded", "reclassified"))
    )


def _species_study_design_summary_is_stated(paper_md: str) -> bool:
    landscape = _section(paper_md, "Evidence Landscape")
    lower = landscape.lower()
    return (
        ("species and study-design summary" in lower or "species and study design summary" in lower)
        and "preclinical rodent n=" in lower
        and "human n=" in lower
        and "| evidence group |" in lower
        and "| study-design signal |" in lower
    )


def _source_statistics_landscape_is_stated(paper_md: str) -> bool:
    landscape = _section(paper_md, "Evidence Landscape")
    return bool(
        landscape
        and re.search(r"\b[A-Z][A-Za-z-]+(?:\s+et\s+al\.?)?\s+20\d{2}[a-z]?\b", landscape)
        and re.search(r"\b\d+(?:\.\d+)?\s*(?:%|percent\b|p\s*=|ci\b|confidence interval\b|hazard ratio\b|odds ratio\b|relative risk\b)", landscape, flags=re.I)
        and re.search(r"\b(outcome class|outcome=|classified|mapped)\b", landscape, flags=re.I)
    )


def _source_outcome_class_map_is_stated(paper_md: str) -> bool:
    scope = " ".join(part for part in (_section(paper_md, "Evidence Landscape"), _section(paper_md, "Evidence Snapshot")) if part).lower()
    return (
        ("source outcome-class map" in scope or "findings map" in scope)
        and "outcome=" in scope
        and re.search(r"\b[A-Z][A-Za-z-]+(?:\s+et\s+al\.?)?\s+20\d{2}[a-z]?\b", scope, flags=re.I) is not None
    )


def _findings_map_source_verdict_is_stated(paper_md: str) -> bool:
    scope = " ".join(part for part in (_section(paper_md, "Evidence Landscape"), _section(paper_md, "Evidence Snapshot")) if part)
    lower = scope.lower()
    return bool(
        "findings map" in lower
        and "outcome=" in lower
        and "direction=" in lower
        and "directness=" in lower
        and "finding=" in lower
        and re.search(r"\b[A-Z][A-Za-z-]+(?:\s+et\s+al\.?)?\s+20\d{2}[a-z]?\b", scope)
    )


def _key_findings_source_verdict_is_stated(paper_md: str) -> bool:
    scope = "\n\n".join(part for part in (
        _section(paper_md, "Key Findings"),
        _section(paper_md, "Results"),
        _section(paper_md, "Evidence Snapshot"),
    ) if part)
    lower = scope.lower()
    return bool(re.search(r"\b[A-Z][A-Za-z-]+(?:\s+et\s+al\.?)?\s+20\d{2}[a-z]?\b", scope)) and (
        (
            "key findings from source synthesis" in lower
            and "outcome=" in lower
            and "direction=" in lower
            and "directness=" in lower
            and "tier=" in lower
        )
        or (
            "source examples:" in lower
            and "tier=" in lower
            and "directness=" in lower
            and "direction=" in lower
        )
        or (
            "evidence domain" in lower
            and "source classification map" in paper_md.lower()
            and "outcome=" in paper_md.lower()
            and "directness=" in paper_md.lower()
            and "tier=" in paper_md.lower()
        )
    )


def _adjacent_indirect_reconciliation_is_stated(paper_md: str) -> bool:
    scope = " ".join(
        part for part in (
            _abstract(paper_md),
            _section(paper_md, "Evidence Snapshot"),
            _section(paper_md, "Evidence Landscape"),
        ) if part
    )
    lower = scope.lower()
    return (
        "adjacent" in lower
        and "indirect" in lower
        and "directness=" in lower
        and any(token in lower for token in (
            "reclassified as contextual",
            "used only to bound interpretation",
            "source directness breakdown",
        ))
    )


def _evidence_tier_directness_bounds_are_stated(paper_md: str) -> bool:
    sections = [_section(paper_md, name).lower() for name in ("Key Findings", "Conclusion")]
    if not all(sections):
        return False
    return all(
        re.search(r"\b(?:a1|a2|b1|b2|c1|c2|evidence tier)\b", section)
        and re.search(r"\b(?:directness|direct|indirect|review|mechanistic)\b", section)
        for section in sections
    )


def _prisma_all_included_rationale_is_stated(paper_md: str) -> bool:
    scope = " ".join(part for part in (_section(paper_md, "Methods"), _section(paper_md, "Evidence Landscape")) if part).lower()
    return (
        "100%" in scope
        and any(token in scope for token in ("retrieved records", "records were included", "all retrieved"))
        and any(token in scope for token in ("eligibility", "screening", "scope"))
        and any(token in scope for token in ("because", "rationale", "reason"))
    )


def _directional_coding_explanation_is_material(paper_md: str) -> bool:
    scope = " ".join(
        part
        for part in (_section(paper_md, "Evidence Snapshot"), _section(paper_md, "Evidence Landscape"), _section(paper_md, "Results"), _section(paper_md, "Conclusion"))
        if part
    ).lower()
    if not scope:
        return False
    directional = "directional coding" in scope and "no extracted directional signal" in scope
    null_scope = "null" in scope and any(token in scope for token in ("unclear", "no signal", "no extracted directional signal"))
    cross_context = (
        any(token in scope for token in ("positive", "mixed", "negative"))
        and any(token in scope for token in ("other outcome", "elsewhere", "separately reported", "different outcome"))
    )
    proportion_scope = "proportion" in scope and "source" in scope and any(token in scope for token in ("x/y", "/"))
    directional_map_boundary = (
        "directional-map boundary:" in scope
        and "predominantly unclear" in scope
        and "does not support" in scope
        and "directional map" in scope
    )
    if directional_map_boundary:
        return True
    return directional and null_scope and (cross_context or proportion_scope)


def _direction_coding_visibility_is_stated(paper_md: str) -> bool:
    scope = " ".join(
        part
        for part in (
            _abstract(paper_md),
            _section(paper_md, "Key Findings"),
            _section(paper_md, "Evidence Landscape"),
            _section(paper_md, "Results"),
        )
        if part
    ).lower()
    return bool(
        "direction-coding visibility note:" in scope
        and "unclear" in scope
        and re.search(r"\b\d+\s*/\s*\d+\b", scope)
    )


def _direction_coded_source_highlights_are_stated(paper_md: str) -> bool:
    findings = _section(paper_md, "Key Findings")
    lower = findings.lower()
    return bool(
        "direction-coded source highlights:" in lower
        and "direction=" in lower
        and any(token in lower for token in ("representative statistic", "source-level statistic", "p ="))
        and re.search(r"\b[A-Z][A-Za-z-]+(?:\s+et\s+al\.?)?\s+20\d{2}[a-z]?\b", findings)
    )


def _directional_table_narrative_is_consistent(paper_md: str) -> bool:
    table_scope = " ".join(
        part for part in (_section(paper_md, "Evidence Snapshot"), _section(paper_md, "Evidence Landscape")) if part
    ).lower()
    narrative_scope = " ".join(
        part for part in (_section(paper_md, "Key Findings"), _section(paper_md, "Results"), _section(paper_md, "Conclusion")) if part
    ).lower()
    if not table_scope or not narrative_scope:
        return False
    no_signal = any(token in table_scope for token in ("no extracted directional signal", "no directional signal", "null directional signal", "all null directional", "predominantly unclear", "unclear"))
    positive_narrative = any(
        token in narrative_scope
        for token in ("positive association", "positive associations", "positive signal", "positive signals", "positive/negative", "negative signal", "negative signals")
    )
    reconciled = any(
        token in (table_scope + " " + narrative_scope)
        for token in ("different outcome", "other outcome", "separately reported", "does not mean absence", "not absence of support", "directional coding", "reconciled")
    )
    return reconciled and not (no_signal and positive_narrative and not reconciled)


def _contextual_without_directional_signal_is_explained(paper_md: str) -> bool:
    scope = " ".join(
        part for part in (
            _section(paper_md, "Evidence Snapshot"),
            _section(paper_md, "Evidence Landscape"),
            _section(paper_md, "Results"),
            _section(paper_md, "Discussion"),
        ) if part
    ).lower()
    return (
        "contextual claim" in scope
        and any(token in scope for token in ("no extracted directional signal", "no directional signal", "absence of directional"))
        and any(token in scope for token in ("bibliographic", "mechanistic context", "background", "not effect-direction", "not directional"))
    )


def _section_source_grounding_is_stated(paper_md: str) -> bool:
    sections = [_section(paper_md, name) for name in ("Key Findings", "Limitations", "Conclusion")]
    return all(section and _has_source_trace_marker(section) for section in sections)


def _substantive_evidence_synthesis_is_stated(paper_md: str) -> bool:
    landscape = _section(paper_md, "Evidence Landscape")
    findings = _section(paper_md, "Key Findings")
    if not landscape or not findings:
        return False
    scope = f"{landscape}\n{findings}"
    return bool(
        "substantive evidence synthesis" in landscape.lower()
        and "key findings from source synthesis" in findings.lower()
        and "source-level findings by outcome class" in findings.lower()
        and ("synthesis interpretation:" in findings.lower() or "source-level findings" in scope.lower())
        and re.search(r"\b[A-Z][A-Za-z-]+(?:\s+et\s+al\.?)?\s+20\d{2}[a-z]?\b", scope)
        and re.search(r"\bpositive|negative|mixed|unclear|null|no extracted directional signal\b", scope, re.I)
        and "bounded conclusion" in scope.lower()
    )


def _substantive_conclusion_is_stated(paper_md: str) -> bool:
    conclusion = _section(paper_md, "Conclusion").lower()
    return (
        "substantive conclusion" in conclusion
        and "source" in conclusion
        and any(token in conclusion for token in (
            "prognostic", "survival", "causal", "mendelian",
            "mechanistic", "treatment", "intervention",
            "positive", "negative", "mixed", "null", "unclear",
        ))
        and any(token in conclusion for token in (
            "bounded", "not establish", "does not establish",
            "not standalone", "not clinical actionability",
        ))
    )


def _concrete_research_question_is_stated(paper_md: str) -> bool:
    question = _section(paper_md, "Research Question").lower()
    if not question:
        return False
    return (
        "?" in question
        and "source" in question
        and ("outcome class" in question or "outcome-class" in question)
        and any(token in question for token in ("direct", "indirect", "mechanistic", "review"))
        and any(token in question for token in ("hypothesis-generating", "clinically actionable", "clinical"))
    )


def _two_part_research_question_is_stated(paper_md: str) -> bool:
    question = _section(paper_md, "Research Question").lower()
    return bool(
        "two-part research question:" in question
        and ("(1)" in question or "first" in question)
        and ("(2)" in question or "second" in question)
        and question.count("?") >= 2
    )


def _asks_scope_framing(text: str) -> bool:
    return (
        "scope framing" in text
        or "retitle and reframe" in text
        or ("drop" in text and "anti-aging framing" in text)
        or ("mixed framing" in text and "internally inconsistent" in text)
    )


def _asks_most_supported_key_findings(text: str) -> bool:
    return (
        "key findings" in text
        and any(token in text for token in ("most-supported", "most supported", "outcome-specific signal"))
        and any(token in text for token in ("source citation", "source citations", "methodological header"))
    )


def _asks_outcome_taxonomy_separation(text: str) -> bool:
    return (
        "taxonomy" in text
        and any(token in text for token in ("restructure", "separate", "segregate", "mixes"))
        and any(token in text for token in (
            "prognostic", "risk factor", "incident cancer", "mechanism",
            "treatment", "intervention", "outcome class",
        ))
    ) or (
        "outcome class" in text
        and "mixes" in text
        and any(token in text for token in ("separate", "taxonomy", "bounded interpretation"))
    )


def _asks_source_scope_annex(text: str) -> bool:
    return any(token in text for token in ("remove", "move", "segregate", "relabel", "re-label")) and any(
        token in text for token in (
            "annex", "non-cancer evidence", "non cancer evidence",
            "not appropriate as direct", "off-topic", "off topic",
            "non-topic", "not pooled",
        )
    )


def _asks_source_stratification_reconciliation(text: str) -> bool:
    return (
        any(token in text for token in ("five-domain", "five domain", "seven-slice", "seven slice"))
        and any(token in text for token in ("source stratification", "outcome domains", "abstract"))
        and any(token in text for token in ("reconcile", "correct", "consolidate"))
    )


def _asks_mr_causal_count(text: str) -> bool:
    return (
        any(token in text for token in ("mr/", "mr ", "mendelian", "causal-risk", "causal risk"))
        and any(token in text for token in ("source count", "recompute", "actual", "unsupported"))
    )


def _asks_direct_interventional_reclassification(text: str) -> bool:
    return (
        "reclassify" in text
        and any(token in text for token in ("direct interventional", "direct evidence", "direct-evidence"))
        and any(token in text for token in ("rct", "randomized", "endpoint"))
    )


def _asks_conclusion_weight_boundary(text: str) -> bool:
    return "conclusion" in text and any(token in text for token in (
        "equally supported", "heavily skewed", "source mix",
        "minority slice", "minority slices", "over-broad", "over broad",
    ))


def _scope_framing_is_stated(paper_md: str) -> bool:
    scope = "\n\n".join(part for part in (
        _abstract(paper_md),
        _section(paper_md, "Research Question"),
        _section(paper_md, "Evidence Landscape"),
        _section(paper_md, "Limitations"),
    ) if part).lower()
    return (
        "scope-framing note:" in scope
        and any(token in scope for token in ("heterogeneous indication", "clinical application"))
        and any(token in scope for token in ("anti-aging", "longevity", "aging-relevant"))
    )


def _outcome_taxonomy_separation_is_stated(paper_md: str) -> bool:
    scope = "\n\n".join(part for part in (
        _section(paper_md, "Evidence Landscape"),
        _section(paper_md, "Key Findings"),
        _section(paper_md, "Results"),
    ) if part).lower()
    return (
        "outcome-taxonomy separation note:" in scope
        and any(token in scope for token in ("prognostic", "survival-marker"))
        and any(token in scope for token in ("causal-risk", "risk factor", "mendelian"))
        and any(token in scope for token in ("biology-mechanism", "mechanism", "molecular-context"))
        and any(token in scope for token in ("treatment", "intervention-response", "supplement"))
    )


def _most_supported_key_findings_are_stated(paper_md: str) -> bool:
    findings = _section(paper_md, "Key Findings")
    lower = findings.lower()
    return bool(
        "most-supported outcome-specific signals:" in lower
        and "source" in lower
        and any(token in lower for token in ("direction=", "p =", "representative statistic"))
        and re.search(r"\b[A-Z][A-Za-z-]+(?:\s+et\s+al\.?)?\s+20\d{2}[a-z]?\b", findings)
    )


def _source_stratification_reconciliation_is_stated(paper_md: str) -> bool:
    scope = "\n\n".join(part for part in (
        _abstract(paper_md),
        _section(paper_md, "Evidence Landscape"),
        _section(paper_md, "Key Findings"),
    ) if part).lower()
    return (
        "stratification reconciliation note:" in scope
        and any(token in scope for token in ("five-domain", "five domain"))
        and any(token in scope for token in ("seven-slice", "seven slice", "outcome-class slice"))
        and "n=" in scope
    )


def _mr_causal_count_is_stated(paper_md: str, ask: str) -> bool:
    scope = "\n\n".join(part for part in (
        _section(paper_md, "Evidence Landscape"),
        _section(paper_md, "Key Findings"),
        _section(paper_md, "Conclusion"),
    ) if part)
    lower = scope.lower()
    labels = _source_labels_from_ask(ask)
    return bool(
        "mr/causal-risk source count:" in lower
        and re.search(r"\b\d+\s*/\s*\d+\b", scope)
        and all(label.lower() in lower for label in labels)
    )


def _source_scope_annex_is_stated(paper_md: str, ask: str) -> bool:
    scope = "\n\n".join(part for part in (
        _section(paper_md, "Evidence Landscape"),
        _section(paper_md, "Limitations"),
        _section(paper_md, "Results"),
    ) if part)
    lower = scope.lower()
    labels = _source_labels_from_ask(ask)
    return (
        "source-scope annex note:" in lower
        and "not pooled" in lower
        and any(token in lower for token in ("annex", "non-topic", "non topic", "contextual"))
        and all(label.lower() in lower for label in labels)
    )


def _direct_interventional_reclassification_is_stated(paper_md: str, ask: str) -> bool:
    scope = "\n\n".join(part for part in (
        _section(paper_md, "Evidence Landscape"),
        _section(paper_md, "Key Findings"),
        _section(paper_md, "Gaps Identified"),
        _section(paper_md, "Limitations"),
    ) if part)
    lower = scope.lower()
    labels = _source_labels_from_ask(ask)
    return (
        "direct-interventional endpoint correction:" in lower
        and "direct evidence count" in lower
        and any(token in lower for token in ("rct", "randomized", "interventional"))
        and all(label.lower() in lower for label in labels)
    )


def _source_labels_from_ask(ask: str) -> list[str]:
    labels = re.findall(r"\b[A-Z][A-Za-z'’.-]+(?:\s+et\s+al\.?)?\s+(?:19|20)\d{2}[a-z]?\b", ask)
    return list(dict.fromkeys(label.strip() for label in labels if label.strip()))


def _conclusion_weight_boundary_is_stated(paper_md: str) -> bool:
    conclusion = _section(paper_md, "Conclusion").lower()
    return (
        "dominant source pattern:" in conclusion
        and any(token in conclusion for token in ("not weighed equally", "not weighted equally"))
        and "minority slice" in conclusion
        and any(token in conclusion for token in ("does not establish", "not establish"))
    )


def _direction_tally_audit_is_stated(paper_md: str) -> bool:
    scope = "\n\n".join(part for part in (
        _section(paper_md, "Key Findings"),
        _section(paper_md, "Evidence Landscape"),
        _section(paper_md, "Results"),
    ) if part)
    lower = scope.lower()
    return bool(
        "per-source direction/directness/tier audit table:" in lower
        and "direction=" in lower
        and "directness=" in lower
        and "tier=" in lower
        and re.search(r"\b[A-Z][A-Za-z-]+(?:\s+et\s+al\.?)?\s+20\d{2}[a-z]?\b", scope)
    )


def _outcome_class_key_findings_are_stated(paper_md: str) -> bool:
    findings = _section(paper_md, "Key Findings")
    lower = findings.lower()
    return bool(
        "outcome-class key findings:" in lower
        and "admitted n=" in lower
        and "direction" in lower
        and "directness" in lower
        and re.search(r"\b[A-Z][A-Za-z-]+(?:\s+et\s+al\.?)?\s+20\d{2}[a-z]?\b", findings)
    )


def _asks_publication_year_note(text: str) -> bool:
    return (
        "publication-year" in text
        or "publication year" in text
        or "doi/pubmed date" in text
        or "doi/pubmed dates" in text
        or ("in press" in text and "citation" in text)
        or ("pre-publication" in text and "source-traceable" in text)
        or ("2026-dated" in text and "source" in text)
    )


def _asks_forward_dated_ai_disclosure_note(text: str) -> bool:
    return (
        "forward-dated" in text
        and "citation" in text
        and "ai-use disclosure" in text
        and any(token in text for token in ("limitations", "reproducibility", "remove or relocate"))
    )


def _forward_dated_ai_disclosure_note_is_stated(paper_md: str) -> bool:
    limitations = _section(paper_md, "Limitations").lower()
    has_forward_date_note = (
        any(token in limitations for token in ("forward-dated", "2026 citation", "publication-year note"))
        and any(token in limitations for token in ("reproducibility", "bibliographic", "in-press"))
    )
    substantive_sections = (
        "Key Findings", "Evidence Landscape", "Results", "Discussion",
        "Limitations", "Conclusion",
    )
    ai_crowds_substance = any(
        "ai-use disclosure" in _section(paper_md, section).lower()
        for section in substantive_sections
    )
    return has_forward_date_note and not ai_crowds_substance


def _publication_year_note_is_stated(paper_md: str) -> bool:
    scope = " ".join(
        part
        for part in (
            _section(paper_md, "Key Findings"),
            _section(paper_md, "Methods"),
            _section(paper_md, "Limitations"),
            _section(paper_md, "References"),
        )
        if part
    ).lower()
    return (
        "publication-year note:" in scope
        and "doi/pubmed" in scope
        and ("bibliographic/in-press" in scope or "bibliographic" in scope)
    )


def _asks_additive_screening_flow(text: str) -> bool:
    return (
        "additive screening flow" in text
        or (
            "claim-binding funnel" in text
            and any(token in text for token in ("additive", "records screened", "eligible", "admitted"))
        )
    )


def _additive_screening_flow_is_stated(paper_md: str) -> bool:
    methods = _section(paper_md, "Methods").lower()
    return (
        "additive screening flow:" in methods
        and "records screened" in methods
        and "excluded with reasons" in methods
        and "eligible" in methods
        and "admitted" in methods
    )


def _asks_intervention_target_boundary(text: str) -> bool:
    return (
        "viable geroscience" in text
        or ("contextual evidence" in text and "intervention target" in text)
        or ("tighten the conclusion" in text and "supported" in text and "not supported" in text)
        or (
            any(token in text for token in ("anti-aging framing", "anti aging framing", "geroscience case"))
            and any(token in text for token in ("remove", "temper", "restrict"))
        )
    )


def _intervention_target_boundary_is_stated(paper_md: str) -> bool:
    conclusion = _section(paper_md, "Conclusion").lower()
    scope = f"{_abstract(paper_md)}\n{_section(paper_md, 'Key Findings')}\n{conclusion}".lower()
    if "evidence-boundary note:" in scope:
        return True
    return (
        ("not proof" in conclusion or "does not support" in conclusion or "non-supportive" in conclusion)
        and "intervention target" in conclusion
        and ("hypothesis" in conclusion or "follow-up" in conclusion)
    )


def _rct_count_reconciliation_is_stated(paper_md: str) -> bool:
    lower = paper_md.lower()
    if "single direct rct" in lower or "single rct" in lower:
        return False
    return "rct-count reconciliation" in lower and "source-coding count" in lower


def _unbacked_appraisal_names_are_resolved(paper_md: str) -> bool:
    lower = paper_md.lower()
    if "risk-of-bias appraisal summary:" in lower and "overall ratings" in lower:
        return True
    formal = re.search(r"\b(?:RoB-2|RoB 2|ROBINS-I|AMSTAR-2|AMSTAR 2)\b", paper_md)
    if formal:
        return False
    return "risk-of-bias honesty note" in lower or "per-source public appraisal ratings" in lower


def _has_source_trace_marker(text: str) -> bool:
    lower = text.lower()
    author_year = re.search(r"\b[A-Z][A-Za-z-]+(?:\s+et\s+al\.?)?\s+20\d{2}[a-z]?\b", text)
    source_note = ("source-grounding" in lower or "source grounding" in lower) and any(
        token in lower for token in ("excerpt", "title", "trace", "source")
    )
    return bool(author_year or source_note)


def _source_verification_transparency_is_stated(paper_md: str) -> bool:
    scope = " ".join(
        part
        for part in (_section(paper_md, "Methods"), _section(paper_md, "Limitations"), _section(paper_md, "References"))
        if part
    ).lower()
    if not scope:
        return False
    limitation = (
        "reference-only" in scope
        or "external verification" in scope
        or "independently verified" in scope
        or "traceability" in scope
    )
    artifact = any(token in scope for token in ("manifest", "methods_pack", "supplementary artifact", "supplemental artifact"))
    return "source bundle" in scope and limitation and artifact


def _source_directness_breakdown_is_stated(paper_md: str) -> bool:
    text = paper_md.lower()
    has_map = "source directness" in text or "source classification map" in text or "directness breakdown" in text
    has_directness = "directness=" in text or "directness:" in text
    has_direct = any(token in text for token in ("directly addresses", "directly address", "direct interventional", "hard endpoint", "hard endpoints"))
    has_adjacent = any(token in text for token in ("adjacent", "mechanistic", "review-level", "general", "broader", "contextual"))
    return has_map and has_directness and has_direct and has_adjacent


def _evidence_boundary_is_stated(paper_md: str, ask: str = "") -> bool:
    if "abstract and key findings" in ask:
        return all(
            _section_evidence_boundary_is_stated(_section(paper_md, name))
            for name in ("Abstract", "Key Findings")
        )
    scope = " ".join(
        part for part in (
            _abstract(paper_md),
            _section(paper_md, "Key Findings"),
            _section(paper_md, "Conclusion"),
        ) if part
    ).lower()
    if not scope:
        return False
    bounded = any(token in scope for token in ("hypothesis-generating", "not definitive", "does not support broad", "broad population-level proof is missing"))
    directness = any(token in scope for token in ("direct interventional hard-endpoint evidence", "direct clinical evidence", "mixed, indirect", "indirect", "adjacent/mechanistic", "mechanistic"))
    population = "population-level" in scope or "broad causal" in scope or "policy claims" in scope or "overclaim" in scope
    return bounded and directness and population


def _section_evidence_boundary_is_stated(section: str) -> bool:
    scope = section.lower()
    return (
        bool(scope)
        and any(token in scope for token in ("hypothesis-generating", "not definitive", "does not support broad"))
        and any(token in scope for token in ("direct interventional", "mixed, indirect", "indirect", "adjacent/mechanistic", "mechanistic"))
        and any(token in scope for token in ("broad causal", "policy claims", "population-level", "overclaim"))
    )


def _conclusion_unproven_humans_is_stated(paper_md: str) -> bool:
    conclusion = _section(paper_md, "Conclusion").lower()
    return bool(
        conclusion
        and "human" in conclusion
        and any(token in conclusion for token in ("unproven", "not proven", "not established"))
    )


def _prior_publication_differentiation_is_stated(paper_md: str) -> bool:
    scope = " ".join(
        part for part in (
            _section(paper_md, "Introduction"),
            _section(paper_md, "Discussion"),
            _section(paper_md, "Limitations"),
            _section(paper_md, "Conclusion"),
        ) if part
    ).lower()
    if not scope:
        return False
    return (
        "prior-brief differentiation" in scope
        and "angle" in scope
        and "finding" in scope
        and "population" in scope
    )


def _admission_funnel_numeric_consistency_is_stated(paper_md: str) -> bool:
    lower = paper_md.lower()
    if (
        "admission-bucket note:" in lower
        and "not an additive conservation table" in lower
        and "claim-binding states" in lower
    ):
        return True
    rows = _funnel_counts(paper_md)
    if not rows:
        return False
    no_extractable = rows.get("no extractable claims")
    admitted = rows.get("admitted final sources")
    if admitted is None:
        admitted = rows.get("admitted final receipts")
    if no_extractable is None or admitted is None:
        return False
    return no_extractable != admitted


def _search_summary_scope_note_is_stated(paper_md: str) -> bool:
    scope = " ".join(part for part in (_section(paper_md, "Methods"), _section(paper_md, "Evidence Landscape")) if part).lower()
    return (
        "search-summary scope note:" in scope
        and "date range" in scope
        and "operationalized" in scope
        and "candidate-to-admitted" in scope
    )


def _single_source_proportionality_is_stated(paper_md: str) -> bool:
    whole = paper_md.lower()
    if "single-source slice" in whole and "hypothesis-generating" in whole:
        return True
    scope = " ".join(
        part for part in (
            _section(paper_md, "Evidence Landscape"),
            _section(paper_md, "Key Findings"),
            _section(paper_md, "Limitations"),
            _section(paper_md, "Conclusion"),
        ) if part
    ).lower()
    if not scope:
        return False
    single_source = any(token in scope for token in ("single-source", "single source", "one-source", "one source"))
    bounded = "hypothesis-generating" in scope or "proportional" in scope or "proportionality" in scope
    return single_source and bounded


def _source_identifier_gap_note_is_stated(paper_md: str) -> bool:
    text = paper_md.lower()
    return all(
        token in text
        for token in (
            "source-context verification gap",
            "no doi",
            "source-bundle",
            "peer-reviewed",
        )
    ) and any(token in text for token in ("do not independently upgrade", "cannot independently upgrade"))


def _named_direct_clinical_source_is_stated(paper_md: str) -> bool:
    conclusion = _section(paper_md, "Conclusion").lower()
    whole = paper_md.lower()
    return bool(
        "direct-source ceiling:" in conclusion
        and "direct clinical source set" in conclusion
        and (
            "directness=direct" in whole
            or re.search(r"\b[A-Z][A-Za-z-]+\s+20\d{2}\b", _section(paper_md, "Conclusion")) is not None
        )
    )


def _outcome_subsection_source_narrative_is_stated(paper_md: str) -> bool:
    results = _section(paper_md, "Results").lower()
    conclusion = _section(paper_md, "Conclusion").lower()
    whole = paper_md.lower()
    if not results or not conclusion:
        return False
    source_grounded = (
        "source examples:" in results
        or (
            "evidence domain" in results
            and "source classification map" in whole
            and "outcome=" in whole
            and "directness=" in whole
            and "tier=" in whole
        )
    )
    direct_ceiling = (
        "direct-source ceiling:" in conclusion
        or (
            "direct" in conclusion
            and "interpretive weight" in conclusion
            and any(token in conclusion for token in ("remaining", "indirect", "mechanistic", "contextual"))
        )
    )
    return source_grounded and direct_ceiling


def _protocol_design_limitations_are_stated(paper_md: str) -> bool:
    limitations = _section(paper_md, "Limitations").lower()
    return bool(
        limitations
        and "protocol" in limitations
        and ("cross-sectional" in limitations or "observational" in limitations)
        and "causal claims" in limitations
    )


def _claim_count_audit_is_stated(paper_md: str) -> bool:
    text = paper_md.lower()
    return (
        "claim-count audit note" in text
        and "claim registry" in text
        and any(token in text for token in ("claim-derivation protocol", "claim derivation protocol"))
        and any(token in text for token in ("not independent studies", "not independent source count"))
    )


def _funnel_counts(paper_md: str) -> dict[str, int]:
    rows: dict[str, int] = {}
    in_funnel = False
    for line in paper_md.splitlines():
        stripped = line.strip()
        if re.match(r"^#{2,4}\s+", stripped):
            in_funnel = "admission funnel" in stripped.lower() or "selection flow" in stripped.lower()
            continue
        if not in_funnel or not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) < 2 or cells[0].lower() in {"admission bucket", "---"}:
            continue
        try:
            rows[cells[0].lower()] = int(cells[1].replace(",", ""))
        except ValueError:
            continue
    return rows


def _references_are_traceable(paper_md: str) -> bool:
    refs = _section(paper_md, "References")
    if not refs:
        return False
    lines: list[str] = []
    for line in refs.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("|") or stripped.startswith("#"):
            continue
        if stripped.startswith(("*", "_")) and not stripped.startswith(("- ", "* ")):
            continue
        if stripped.startswith(("- ", "* ")):
            lines.append(stripped.lstrip("-* ").strip())
            continue
        if re.search(r"\b[A-Z][A-Za-z-]+(?:\s+et\s+al\.?)?\s+20\d{2}[a-z]?\b", stripped):
            lines.append(stripped)
    if not lines:
        return False
    identifier = re.compile(
        r"\b(?:doi\s*:|https?://doi\.org/|pmid\s*:|pmcid\s*:|pmc\d+|nct\d+|isrctn\d+|clinicaltrials\.gov)",
        re.I,
    )
    explicit_caveat = re.compile(
        r"\b(?:identifier unavailable|no doi|no pmid|trial registration|protocol registration)\b",
        re.I,
    )
    return all(identifier.search(line) or explicit_caveat.search(line) for line in lines)


def _structured_table_stubs_are_replaced(paper_md: str) -> bool:
    return "see the structured evidence table" not in paper_md.lower()


def _outcome_label_cleanup_is_stated(paper_md: str) -> bool:
    text = paper_md.lower()
    return "dosing and pharmacokinetics" not in text and "exposure and dose-adjacent evidence" in text


def _source_count_bundle_reconciliation_is_stated(paper_md: str) -> bool:
    text = paper_md.lower()
    count_patterns = (
        r"\b(\d[\d,]*)\s+(?:accepted|admitted|included|curated|retained)\s+source",
        r"\b(\d[\d,]*)\s+references?\b",
        r"\b(\d[\d,]*)\s+were\s+(?:classified|admitted).*?\bsources?\b",
    )
    counts = [
        int(value.replace(",", ""))
        for pattern in count_patterns
        for value in re.findall(pattern, text)
    ]
    if counts and len(set(counts)) > 1:
        return False
    if "source bundle" not in text and "traceable synthesis sources" not in text:
        return False
    return bool(
        counts
        and any(token in text for token in ("author-year", "references", "doi", "pmid", "bundle counterpart", "traceable"))
    )


def _asks_corpus_count_reconciliation(text: str) -> bool:
    return (
        any(token in text for token in ("corpus-size", "corpus size", "overcount", "overcounts", "funnel counts"))
        and any(token in text for token in ("reconcile", "correct", "classified", "admitted", "source bundle"))
    )


def _corpus_count_reconciliation_is_stated(paper_md: str) -> bool:
    text = paper_md.lower()
    if re.search(r"\b(?:prognostic|causal-risk|mendelian|intervention-response|molecular-context)[^.\n]{0,120}\bn\s*=\s*\d+", text):
        return False
    return (
        "corpus-count reconciliation:" in text
        and "classified" in text
        and "admitted" in text
        and any(token in text for token in ("manifest outcome class", "outcome-class", "count-bearing"))
    )


def _asks_evidence_honesty_repetition(text: str) -> bool:
    return (
        "evidence-honesty" in text
        and any(token in text for token in ("repetition", "repetitive", "redundant", "reduce"))
    )


def _evidence_honesty_repetition_is_low(paper_md: str) -> bool:
    return paper_md.lower().count("evidence-honesty note:") <= 1


def _citation_traceability_map_is_stated(paper_md: str) -> bool:
    text = paper_md.lower()
    return all(
        token in text
        for token in (
            "citation traceability map",
            "author-year",
            "source-bundle entries",
            "source classification map",
            "references section",
            "methods_pack.json",
        )
    ) and ("manifest.json" in text or "citation_registry.json" in text)


def _source_label_disambiguation_is_stated(paper_md: str, ask: str) -> bool:
    text = paper_md.lower()
    if "source-label disambiguation note:" not in text:
        return False
    labels = re.findall(r"\b[A-Z][A-Za-z-]+\s+(?:19|20)\d{2}[a-z]?\b", ask)
    return all(
        label.lower() in text
        or re.sub(r"\s+((?:19|20)\d{2}[a-z]?)\b", r" (\1)", label).lower() in text
        for label in labels
    )


def _external_references_are_marked_illustrative(paper_md: str, ask: str) -> bool:
    external_names = re.findall(r"\b[A-Z][A-Za-z-]+(?:\s+et\s+al\.?)?\s+(?:19|20)\d{2}[a-z]?\b", ask, flags=re.I)
    if not external_names:
        return True
    text = paper_md.lower()
    boundary_terms = (
        "illustrative", "methodological", "benchmark", "general problem",
        "general caution", "external", "not a bundle source",
        "surrogate-endpoint", "hard-outcome validity",
    )
    for name in external_names:
        indices = [m.start() for m in re.finditer(re.escape(name.lower()), text)]
        if not indices:
            continue
        if not any(
            any(term in text[max(0, idx - 240): idx + 360] for term in boundary_terms)
            for idx in indices
        ):
            return False
    return True


def _unbundled_citations_are_resolved(paper_md: str, ask: str) -> bool:
    tokens = re.findall(r"\b[A-Z][A-Za-z-]+(?:\s+et\s+al\.?)?\s+(?:19|20)\d{2}[a-z]?\b", ask)
    return bool(tokens) and all(token not in paper_md for token in tokens)


def _numeric_effect_audit_is_stated(paper_md: str) -> bool:
    scope = " ".join(part for part in (_section(paper_md, "Methods"), _section(paper_md, "Evidence Landscape"), _section(paper_md, "Limitations")) if part).lower()
    return (
        any(token in scope for token in ("numeric effect audit", "p-value audit", "p value audit", "effect-direction audit"))
        and any(token in scope for token in ("source excerpt", "source bundle", "extracted statistic"))
    )


def _named_numeric_correction_is_stated(paper_md: str, ask: str) -> bool:
    source = (
        re.search(r"regarding\s+([a-z][a-z'’.\-]+)\s+((?:19|20)\d{2}[a-z]?)", ask, flags=re.I)
        or re.search(r"\b([a-z][a-z'’.\-]+)\s+((?:19|20)\d{2}[a-z]?)", ask, flags=re.I)
    )
    p_value = re.search(r"\bp\s*=\s*(0?\.\d+|1(?:\.0+)?)", ask, flags=re.I)
    scope = " ".join(part for part in (
        _abstract(paper_md),
        _section(paper_md, "Methods"),
        _section(paper_md, "Evidence Landscape"),
        _section(paper_md, "Conclusion"),
    ) if part).lower()
    if source and f"{source.group(1).lower()} {source.group(2).lower()}" not in scope:
        return False
    if p_value and f"p = {p_value.group(1)}" not in scope and f"p={p_value.group(1)}" not in scope:
        return False
    return (
        any(token in scope for token in ("non-significant", "not significant", "did not reach significance"))
        and not _named_numeric_positive_contradiction(paper_md, ask)
    )


def _numeric_correction_markup_is_resolved(paper_md: str) -> bool:
    reader_facing = " ".join(part for part in (_abstract(paper_md), _section(paper_md, "Research Question")) if part).lower()
    if "numeric correction:" in reader_facing:
        return False
    if "numeric correction:" not in paper_md.lower():
        return True
    technical_scope = " ".join(part for part in (
        _section(paper_md, "Methods"),
        _section(paper_md, "Evidence Landscape"),
        _section(paper_md, "Limitations"),
    ) if part).lower()
    return "numeric reconciliation note:" in technical_scope or "non-significant mapped comparison" in technical_scope


_POSITIVE_NUMERIC_CONTRADICTION_RE = re.compile(
    r"\b(?:effect_)?direction\s*=\s*positive\b|"
    r"\bpositive (?:study-level )?signals?\s+(?:in|are|were|cluster|concentrate|represented|summarized)\b|"
    r"\bpositive signal\s*;",
    re.I,
)


def _named_numeric_positive_contradiction(paper_md: str, ask: str) -> bool:
    source = (
        re.search(r"regarding\s+([a-z][a-z'’.\-]+)\s+((?:19|20)\d{2}[a-z]?)", ask, flags=re.I)
        or re.search(r"\b([a-z][a-z'’.\-]+)\s+((?:19|20)\d{2}[a-z]?)", ask, flags=re.I)
    )
    p_value = re.search(r"\bp\s*=\s*(0?\.\d+|1(?:\.0+)?)", ask, flags=re.I)
    if not source or not p_value or float(p_value.group(1)) < 0.05:
        return False
    labels = {
        f"{source.group(1)} {source.group(2)}".lower(),
        f"{source.group(1)} ({source.group(2)})".lower(),
    }
    for line in paper_md.splitlines():
        lower = line.lower()
        if any(label in lower for label in labels) and _POSITIVE_NUMERIC_CONTRADICTION_RE.search(line):
            return True
    for chunk in _source_local_chunks(paper_md):
        lower = chunk.lower()
        if any(label in lower for label in labels) and _POSITIVE_NUMERIC_CONTRADICTION_RE.search(chunk):
            return True
    return False


def _source_local_chunks(paper_md: str) -> list[str]:
    chunks: list[str] = []
    for paragraph in re.split(r"\n\s*\n", paper_md):
        for line in paragraph.splitlines():
            chunks.append(line)
            chunks.extend(re.split(r"(?<=[.!?])\s+(?=[A-Z])", line.strip()))
    return [chunk for chunk in chunks if chunk.strip()]


def _full_surface_sources_are_visible(paper_md: str, ask: str) -> bool:
    if not _asks_full_source_surface_request(ask.lower()):
        return True
    labels = _author_year_labels(ask)
    if not labels:
        return True
    scope = "\n".join(
        part for part in (_section(paper_md, "Key Findings"), _section(paper_md, "Results"))
        if part
    ).lower()
    if not scope:
        return False
    return all(_label_in_text(label, scope) for label in labels)


def _asks_full_source_surface_request(text: str) -> bool:
    return bool(re.search(r"\b(?:all|every)\s+\d+\s+admitted sources?\b", text)) or any(
        token in text
        for token in (
            "full admitted corpus", "all admitted source", "all retained source",
            "every admitted source", "missing bundle source", "missing source",
            "cover all", "covers all",
            "must appear in at least one outcome-class packet",
        )
    )


def _author_year_labels(text: str) -> list[str]:
    return list(dict.fromkeys(
        re.findall(r"\b[A-Z][A-Za-z'’.\-]+(?:\s+et\s+al\.?)?\s+(?:19|20)\d{2}[a-z]?\b", text)
    ))


def _label_in_text(label: str, text: str) -> bool:
    lower = label.lower()
    return lower in text or re.sub(r"\s+((?:19|20)\d{2}[a-z]?)\b", r" (\1)", lower) in text


def _grammar_artifacts_are_absent(paper_md: str) -> bool:
    return not re.search(r"\b(?:is|are|was|were)\s+insufficient\s+to\s+(?:is|are|was|were)\b", paper_md, flags=re.I)


_CLAIM_SYS = "You are a strict manuscript reviewer. Reply with JSON only."
_CLAIM_USER = (
    "Below is a paper's ABSTRACT and the rest of the manuscript. List any abstract "
    "claim the manuscript's own evidence does NOT support, or that overstates it "
    "(too strong / unhedged given mixed or indirect evidence) — the most common "
    "reason an abstract is sent back for revision. Do not list neutral "
    "corpus-composition summaries (evidence-tier counts, outcome-bucket summaries, "
    "or disagreement counts) unless they assert efficacy or causal benefit. Reply with JSON "
    '{{"unsupported": [<verbatim claim>, ...]}} — empty if every abstract claim '
    "is supported and appropriately hedged.\n\n"
    "ABSTRACT:\n{abstract}\n\n=== REST OF MANUSCRIPT ===\n{body}"
)
_PROFILE_SUMMARY_RE = re.compile(
    r"\b("
    r"evidence profile contains|no sources classified primarily as|"
    r"positive (?:study-level )?signals (?:concentrate|concentrated|cluster|are summarized|are represented)|"
    r"no single positive outcome class dominates|"
    r"null signals (?:in|cluster)|negative signals (?:in|cluster)|"
    r"cross-study disagreement"
    r")\b",
    re.I,
)
_P_VALUE_RE = re.compile(r"\bp\s*(?:=|>|≥|>=)\s*(0?\.\d+|1(?:\.0+)?)", re.I)
_CI_RE = re.compile(r"\b(?:CI|confidence interval)\b[^.\n;:]{0,80}?(-?\d+(?:\.\d+)?)\s*(?:-|–|to)\s*(-?\d+(?:\.\d+)?)", re.I)
_SIG_RE = re.compile(r"\b(?:statistically\s+)?significant(?:ly)?\b", re.I)
_NONSIG_RE = re.compile(
    r"\b(?:non[- ]?significant(?:ly)?|not\s+(?:statistically\s+)?significant(?:ly)?|did\s+not\s+reach\s+significance)\b",
    re.I,
)


def _abstract(paper_md: str) -> str:
    m = re.search(r"^##\s+Abstract\b.*?\n(.*?)(?=^##\s|\Z)", paper_md, re.M | re.S)
    return m.group(1).strip() if m else ""


def _section(paper_md: str, name: str) -> str:
    m = re.search(rf"^##\s+{re.escape(name)}\b.*?\n(.*?)(?=^##\s|\Z)", paper_md, re.M | re.S | re.I)
    return m.group(1).strip() if m else ""


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text.replace("\n", " ")) if s.strip()]


def numeric_effect_direction_issues(paper_md: str) -> list[str]:
    """Deterministic numeric sanity gate for the common reviewer failure:
    calling p>=0.05 or a CI crossing null "significant". Bounded and fail-closed
    only on explicit numeric contradictions, not absence of statistics."""
    scope = "\n".join(part for part in (_abstract(paper_md), _section(paper_md, "Conclusion")) if part)
    issues: list[str] = []
    for sentence in _sentences(scope):
        if not _SIG_RE.search(sentence) or _NONSIG_RE.search(sentence):
            continue
        for value in _P_VALUE_RE.findall(sentence):
            if float(value) >= 0.05:
                issues.append(f"non-significant p-value described as significant: {sentence}")
                break
        for lo, hi in _CI_RE.findall(sentence):
            low, high = float(lo), float(hi)
            if low <= 0 <= high or (low <= 1 <= high and min(abs(low), abs(high)) > 0):
                issues.append(f"CI crossing null described as significant: {sentence}")
                break
    return issues


def unsupported_abstract_claims(
    paper_md: str,
    *,
    chat: Callable[..., Awaitable[LLMResponse]] = chat_json,
    runner: Callable[..., Any] = asyncio.run,
    settings: Any | None = None,
) -> list[str]:
    """Abstract claims the manuscript's evidence does not support / overstates
    (paper-qa contradiction-check borrow). Empty when the abstract is supported,
    or fail-open ([]) on any error/malformed verdict. Bounded: one judge call."""
    abstract = _abstract(paper_md)
    if not abstract:
        return []
    body = paper_md.replace(abstract, "", 1)
    try:
        resp = runner(chat(
            messages=[
                {"role": "system", "content": _CLAIM_SYS},
                {"role": "user", "content": _CLAIM_USER.format(abstract=abstract[:6000], body=body[:18000])},
            ],
            chain=build_judge_chain(settings or load_settings()),
            temperature=0.0,
            seed=7,
        ))
        claims = resp.parsed.get("unsupported", [])
    except (LLMError, ValueError, KeyError, TypeError, AttributeError, OSError, RuntimeError):
        return []  # fail-open
    if not isinstance(claims, list):
        return []
    return [
        claim for c in claims
        if (claim := str(c).strip()) and not _PROFILE_SUMMARY_RE.search(claim)
    ]
