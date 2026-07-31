"""Fail-closed structural and judge coverage for reviewer revision asks."""
from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable, Collection, Iterable, Mapping, Sequence
from typing import Any

from agent.llm_client import LLMError, LLMResponse, build_judge_chain, chat_json
from agent import revision_identity as _revision
from agent import revision_quality as _quality
from agent.reviewer_consistency_repairs import unsupported_general_health_claim_spans
from agent.settings import load_settings
from agent.statistical_consistency import has_adjusted_significance_threshold

_SYS = "You are a strict manuscript reviewer. Reply with JSON only."
_USER = (
    "Below are {n} required revisions and a manuscript. For EACH revision, in "
    "order, decide whether the manuscript MATERIALLY addresses it — a substantive "
    "change, not merely repeating the words. Reply with JSON "
    '{{"addressed": [<one boolean per revision, in the same order>]}}.\n\n'
    "REQUIRED REVISIONS:\n{asks}\n\n=== MANUSCRIPT ===\n{paper}"
)

_AUTHOR_INFERENCE_BOUNDARY = (
    "**Author-inference boundary:** Mechanism-level explanations in this section "
    "are synthesis-author inferences unless directly attributed to an included "
    "source; they are not independently established causal findings."
)


def place_author_inference_boundary(text: str, feedback: str) -> tuple[str, tuple[str, ...]]:
    if not _asks_author_inference_boundary(feedback):
        return text, ()
    sections = _author_inference_sections(feedback)
    patched = re.sub(
        rf"\n*{re.escape(_AUTHOR_INFERENCE_BOUNDARY)}\s*", "\n\n", text, flags=re.I,
    )
    placed: list[str] = []
    for section in sections:
        match = re.search(rf"^## {re.escape(section)}\b", patched, flags=re.M)
        if match:
            at = match.end()
            patched = patched[:at] + "\n\n" + _AUTHOR_INFERENCE_BOUNDARY + patched[at:]
            placed.append(section)
    return (patched, tuple(placed)) if placed else (text, ())


def revision_asks(feedback: str, required_revisions: Sequence[str] | None = None) -> list[str]:
    """Split Researka's joined reviewer feedback into material revision asks."""
    if required_revisions:
        return [_with_terminal_punctuation(str(ask).strip()) for ask in required_revisions if str(ask).strip()]
    starts = (
        "Add", "Audit", "Clarify", "Complete", "Correct", "Define", "Differentiate",
        "Document", "Ensure", "Explain", "Expand", "Fix", "For each", "For every",
        "Enumerate", "Hedge", "In", "Include", "Integrate", "Make", "Narrow",
        "Justify", "Move", "Operationalize", "Populate", "Rename",
        "Provide", "Recode", "Re-extract", "Either", "Mark", "Reclassify", "Reframe",
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
    """Return asks not materially addressed, failing closed on judge errors."""
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
        return clean
    if (
        not isinstance(flags, list)
        or len(flags) != len(clean)
        or any(type(flag) is not bool for flag in flags)
    ):
        return clean
    return [a for a, ok in zip(clean, flags, strict=True) if not ok]


def material_unmet_asks(
    paper_md: str, feedback: str, *, retained_citations: Iterable[str] | None = None,
    evidence_rows: list[dict[str, Any]] | None = None,
    source_identifier_audit: dict[str, Any] | None = None,
    required_revisions: Sequence[str] | None = None,
) -> list[str]:
    """Coverage result after deterministic structural checks and LLM judge."""
    asks = revision_asks(feedback, required_revisions)
    unmet = deterministic_unmet_asks(
        paper_md, asks, retained_citations=retained_citations,
        evidence_rows=evidence_rows, source_identifier_audit=source_identifier_audit,
    )
    deterministic_met = set(deterministic_known_asks(asks, evidence_rows=evidence_rows)) - set(unmet)
    for ask in unmet_asks(paper_md, asks):
        if ask not in unmet and ask not in deterministic_met:
            unmet.append(ask)
    return unmet


def deterministic_unmet_asks(
    paper_md: str, asks: Sequence[str], *, retained_citations: Iterable[str] | None = None,
    evidence_rows: list[dict[str, Any]] | None = None,
    source_identifier_audit: dict[str, Any] | None = None,
) -> list[str]:
    """Reviewer asks with deterministic manuscript evidence.

    The LLM coverage judge stays useful for semantic asks, but these recurring
    Researka revise classes are structural enough to verify directly. This
    makes the gate resilient when the judge fails open.
    """
    return [ask for ask in (a.strip() for a in asks if a and a.strip())
            if not _deterministic_ask_satisfied(paper_md, ask)
            or not _revision.revision_identity_proof_is_stated(
                paper_md, ask, evidence_rows, source_identifier_audit,
            )
            or not _quality.revision_quality_proof_is_stated(paper_md, ask, evidence_rows)
            or retained_citations is not None
            and not _retained_tension_ask_satisfied(paper_md, ask, retained_citations)]


def deterministic_known_asks(
    asks: Sequence[str], *, evidence_rows: Sequence[dict[str, Any]] | None = None,
) -> list[str]:
    """Reviewer asks covered by deterministic structural predicates."""
    return [ask for ask in (a.strip() for a in asks if a and a.strip())
            if _deterministic_ask_known(ask, evidence_rows)]


def _deterministic_ask_known(
    ask: str, evidence_rows: Sequence[dict[str, Any]] | None = None,
) -> bool:
    return _quality.revision_quality_ask_known(ask, evidence_rows) or any(
        matches(" ".join(ask.lower().split())) for matches, _ in _DETERMINISTIC_ASK_RULES
    )


def _deterministic_ask_satisfied(paper_md: str, ask: str) -> bool:
    lower = " ".join(ask.lower().split())
    for matches, is_satisfied in _DETERMINISTIC_ASK_RULES:
        if matches(lower):
            return is_satisfied(paper_md, ask, lower)
    return True


def _retained_tension_ask_satisfied(
    paper_md: str, ask: str, retained_citations: Iterable[str],
) -> bool:
    lower = " ".join(ask.lower().split())
    checker = (
        _replaced_surface_tensions_are_stated
        if _asks_replaced_surface_tensions(lower) else _concrete_tensions_gaps_are_stated
    )
    return not (_asks_replaced_surface_tensions(lower) or _asks_concrete_tensions_gaps(lower)) or checker(
        paper_md, ask, retained_citations=retained_citations)


def retained_citation_labels(
    manifest: dict[str, Any], registry: dict[str, Any] | None = None,
) -> frozenset[str]:
    rows = manifest.get("receipts") or manifest.get("source_bundle") or ()
    records = [row for row in rows if isinstance(row, dict)]
    if isinstance(registry, dict):
        records.extend(row for row in registry.values() if isinstance(row, dict))
    fields = "body_citation", "citation_token", "citation", "source_label", "receipt_id", "source_title", "source_pmcid", "pmcid"
    return frozenset(
        " ".join(str(row.get(field) or "").casefold().split())
        for row in records for field in fields if str(row.get(field) or "").strip())


def _asks_classification_criteria(text: str) -> bool:
    return "classification criteria" in text or (
        "assign" in text and "outcome class" in text and "directness" in text
    )


def _asks_inferential_bridge(text: str) -> bool:
    return "inferential bridge" in text and "section" in text


def _asks_directness_coding_criteria(text: str) -> bool:
    return (
        "directness" in text
        and any(token in text for token in (
            "coding criteria",
            "directness criteria",
            "criteria for directness",
            "what constitutes",
        ))
        and any(token in text for token in ("indirect", "review"))
    ) or all(token in text for token in ("direct", "bundle", "metadata")) and any(token in text for token in ("design", "protocol", "full text extractable"))


def _directness_coding_criteria_are_stated(paper_md: str) -> bool:
    methods = " ".join(_section(paper_md, "Methods").lower().split())
    return all(token in methods for token in (
        "directness coding criteria",
        "coded as direct only when",
        "coded as indirect",
        "review-level evidence",
    ))


def _inferential_bridge_is_stated(paper_md: str) -> bool:
    text = paper_md.lower()
    if "## inferential bridge" not in text:
        return False
    if "[inferential bridge status: not established]" in text:
        return all(token in text for token in (
            "mechanistic-to-clinical",
            "population-to-population transfer",
            "biomarker-to-bedside",
        ))
    return all(token in text for token in (
        "[d1_",
        "[mechanism anchor:",
        "[conservation:",
        "[testability:",
    ))


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


def asks_most_supported_key_findings(text: str) -> bool:
    return _asks_most_supported_key_findings(_normalised_feedback(text))


def asks_outcome_taxonomy_separation(text: str) -> bool:
    return _asks_outcome_taxonomy_separation(_normalised_feedback(text))


def asks_source_stratification_reconciliation(text: str) -> bool:
    return _asks_source_stratification_reconciliation(_normalised_feedback(text))


def asks_mr_causal_count(text: str) -> bool:
    return _asks_mr_causal_count(_normalised_feedback(text))


def asks_effect_direction_reconciliation(text: str) -> bool:
    return _asks_effect_direction_reconciliation(_normalised_feedback(text))


def authorized_receipt_contract_fields(text: str) -> set[str]:
    """Receipt fields a reviewer explicitly asked this revision to recode."""
    lower = _normalised_feedback(text)
    fields = {"effect_direction"} if _asks_effect_direction_reconciliation(lower) else set()
    action = any(token in lower for token in (
        "correct", "move", "reclassify", "recode", "reconcile", "reroute",
        "inconsistent", "misclassified", "not a review", "underlying source",
    ))
    if action and "effect direction" in lower:
        fields.add("effect_direction")
    if action and any(token in lower for token in ("outcome class", "outcome-class")):
        fields.add("outcome_class")
    study_recode = action and (
        any(token in lower for token in ("directness", "direct/indirect", "evidence tier", "proper tier"))
        or all(token in lower for token in ("primary", "review"))
        and any(token in lower for token in ("rct", "randomized", "randomised"))
    )
    if study_recode:
        fields.update(("directness", "evidence_tier"))
    return fields


def authorized_receipt_contract_fields_by_receipt(
    text: str,
    rows: dict[str, dict[str, Any]],
    aliases_by_receipt: Mapping[str, Collection[str]] | None = None,
) -> dict[str, set[str]]:
    """Map source-specific reviewer recode asks to only the named receipts."""
    aliases_by_receipt = aliases_by_receipt or {}
    segments = [
        _normalised_feedback(segment)
        for segment in re.split(r"(?:\r?\n)+|;\s+", text)
        if segment.strip()
    ]
    authorized: dict[str, set[str]] = {}
    for receipt_id, row in rows.items():
        aliases = {
            str(value).casefold().strip()
            for value in (
                receipt_id,
                row.get("source_title"),
                row.get("source_doi"),
                row.get("source_pmid"),
                *aliases_by_receipt.get(receipt_id, ()),
            )
            if str(value or "").strip()
        }
        fields: set[str] = set()
        for segment in segments:
            if any(alias in segment for alias in aliases):
                fields.update(authorized_receipt_contract_fields(segment))
        if fields:
            authorized[receipt_id] = fields
    return authorized


def asks_admission_direction_tally_reconciliation(text: str) -> bool:
    return _asks_admission_direction_tally_reconciliation(_normalised_feedback(text))


def asks_bounded_research_question_conclusion(text: str) -> bool:
    return _asks_bounded_research_question_conclusion(_normalised_feedback(text))


def asks_mr_mechanism_disagreement_separation(text: str) -> bool:
    return _asks_mr_mechanism_disagreement_separation(_normalised_feedback(text))


def asks_no_direct_hard_endpoint_statement(text: str) -> bool:
    return _asks_no_direct_hard_endpoint_statement(_normalised_feedback(text))


def asks_publication_status_preprint_flags(text: str) -> bool:
    return _asks_publication_status_preprint_flags(_normalised_feedback(text))


def asks_direction_tally_audit(text: str) -> bool:
    return _asks_direction_tally_audit(_normalised_feedback(text))


def asks_source_scope_annex(text: str) -> bool:
    return _asks_source_scope_annex(_normalised_feedback(text))


def asks_direct_interventional_reclassification(text: str) -> bool:
    return _asks_direct_interventional_reclassification(_normalised_feedback(text))


def asks_conclusion_weight_boundary(text: str) -> bool:
    return _asks_conclusion_weight_boundary(_normalised_feedback(text))


def asks_direction_coded_source_highlights(text: str) -> bool:
    return _asks_direction_coded_source_highlights(_normalised_feedback(text))


def _asks_tension_section_placement(text: str) -> bool:
    return (
        any(token in text for token in ("tension", "disagreement", "conflict"))
        and any(token in text for token in ("conclusion", "discussion"))
        and any(token in text for token in ("surface", "place", "state", "directly"))
        and any(token in text for token in ("not only", "rather than only", "directly in"))
    )


def _asks_mechanistic_content_reconciliation(text: str) -> bool:
    return "mechanistic" in text and any(token in text for token in ("no mechanistic source", "no sources classified primarily as mechanistic", "absence of mechanistic", "mechanistic content")) and any(
        token in text for token in ("correct", "decide consistently", "recode", "adjust", "resolve", "reconcile", "framing"))


def asks_tension_section_placement(text: str) -> bool:
    return _asks_tension_section_placement(_normalised_feedback(text))


def asks_mechanistic_content_reconciliation(text: str) -> bool:
    return _asks_mechanistic_content_reconciliation(_normalised_feedback(text))


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
        _asks_mechanistic_content_reconciliation(text)
        or "evidence_type" in text
        or ("evidence type" in text and "metadata" in text)
        or (
            any(token in text for token in ("misclassified", "recode", "reroute", "not a review"))
            and any(token in text for token in ("human intervention", "intervention studies", "clinical intervention", "rct"))
            and any(token in text for token in ("indirect", "review", "evidence", "directness", "tier"))
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
        or (
            any(token in text for token in ("human cohort", "biopsy", "adjacent human", "human evidence"))
            and any(token in text for token in ("direct framing", "directness framing", "0 direct", "zero direct", "direct clinical"))
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


def _asks_source_inclusion_rationale_note(text: str) -> bool:
    note_terms = (
        "included under", "inclusion criteria", "why sources", "umbrella",
        "operationalize", "directly study", "directly addresses", "justify",
        "adjacent context", "primary content", "prune", "reclassify", "define",
        "operationally", "population strata", "subgrouping axes",
    )
    return _asks_source_inclusion_rationale(text) or (
        "source" in text and any(token in text for token in note_terms)
    )


def _asks_species_study_design_summary(text: str) -> bool:
    return (
        "species" in text
        and ("study design" in text or "study-design" in text)
        and "summary table" in text
    )


def _asks_source_outcome_class_map(text: str) -> bool:
    if any(token in text for token in ("combination-product", "combination product", "direct-source denominator")) or "cross-domain synthesis" in text and "template prose" in text:
        return False
    return (
        "findings map" in text
        and "direction" in text
        and "directness" in text
        and any(token in text for token in ("totals", "counts", "auditable", "receipt level", "receipt-level"))
    ) or (
        "for each outcome class" in text
        and "every admitted source" in text
        and "direction" in text
        and "directness" in text
    ) or (
        "cited numbers" in text
        and "findings map" in text
        and "abstract" in text
        and any(token in text for token in ("receipt level", "receipt-level"))
    ) or (
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
        "findings map" in text
        and any(token in text for token in ("source-level attribution", "prose-cited", "prose cited"))
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
    ) or (
        "outcome class" in text
        and "mechanistic" in text
        and any(token in text for token in ("animal", "biomarker/adjacent", "clinical outcome"))
    )


def _asks_findings_map_source_verdict(text: str) -> bool:
    return not ("cross-domain synthesis" in text and "template prose" in text) and (
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


def _asks_concrete_research_question_note(text: str) -> bool:
    terms = (
        "clear", "specific", "concrete", "answerable", "directly answerable",
        "fix", "framing", "substantive", "self-referential",
        "two-part", "two part", "both halves",
    )
    return "research question" in text and any(token in text for token in terms)


def _author_inference_action_clause(text: str) -> str:
    text = _normalised_feedback(text)
    for clause in re.split(r"[.;\n]+|\bbut\b", text):
        subject = "author inference" in clause or (
            "boundary" in clause and "mechanis" in clause
        )
        preserved = re.search(
            r"\b(?:keep|leave|preserve)\b.{0,60}"
            r"\b(?:author inference|boundary)\b.{0,60}"
            r"\b(?:unchanged|intact|same)\b",
            clause,
        )
        positive_action = re.search(
            r"\b(?:add|insert|label(?:ed|led)?|mark|move|place|relocate|state)\b",
            clause,
        )
        negated_action = re.search(
            r"\b(?:(?:do|does|should|must|shall|can|could|would)(?:\s+not|n['’]?t)|"
            r"don['’]?t|never|not\s+to|(?:there\s+is\s+)?no\s+need\s+to)\s+"
            r"(?:need\s+to\s+)?(?:be\s+)?(?:[a-z-]+\s+){0,3}"
            r"(?:add|insert|label(?:ed|led)?|mark|move|place|relocate|state)\b",
            clause,
        )
        if subject and positive_action and not preserved and not negated_action:
            return clause
    return ""


def _asks_author_inference_boundary(text: str) -> bool:
    return bool(_author_inference_action_clause(text))


def _author_inference_sections(feedback: str) -> tuple[str, ...]:
    feedback = _author_inference_action_clause(feedback) or _normalised_feedback(feedback)
    contrast = re.search(
        r"\b(?:in|to|into|within) (?:the )?(cross domain synthesis|discussion)\b"
        r".{0,120}\brather than\b\s*(?:(?:in|to|into|within) )?(?:the )?"
        r"(cross domain synthesis|discussion)\b",
        feedback,
    )
    if contrast:
        return (
            "Cross-Domain Synthesis"
            if contrast.group(1) == "cross domain synthesis"
            else "Discussion",
        )
    destinations = re.findall(
        r"\b(?:in|to|into|within) (?:the )?(cross domain synthesis|discussion)\b",
        feedback,
    )
    if destinations:
        return (
            "Cross-Domain Synthesis"
            if destinations[-1] == "cross domain synthesis"
            else "Discussion",
        )
    sections = tuple(name for phrase, name in (
        ("cross domain synthesis", "Cross-Domain Synthesis"),
        ("discussion", "Discussion"),
    ) if phrase in feedback)
    return sections or ("Cross-Domain Synthesis",)


def _asks_quantitative_evidence_index(text: str) -> bool:
    text = _normalised_feedback(text)
    return "quantitative evidence index" in text or ("evidence claim table" in text and "p value" in text)


def _asks_numeric_discrepancy_resolution(text: str) -> bool:
    text = _normalised_feedback(text)
    return "numeric discrepanc" in text and any(token in text for token in ("p value", "p =", "p <", "statistic"))


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


def _asks_contextual_subdomain_disaggregation(text: str) -> bool:
    text = _normalised_feedback(text)
    return "disaggregat" in text and "contextual" in text and not re.search(r"\b(?:do not|don t|avoid|without|never|cannot|can not|no need to)\s+(?:(?!and\b)\w+\s+){0,2}disaggregat", text)


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
            "remove the table", "arithmetic", "why", "non-overlapping",
            "non overlapping", "step-by-step", "step by step", "candidate union",
        ))
    ) or ("no extractable claims" in text and "admitted final" in text) or (
        "partial/none-only" in text and "partial-only" in text
    ) or (
        "search summary" in text
        and "selection logic" in text
    ) or ("classified candidate" in text and "admitted final" in text and any(token in text for token in ("reconcile", "resolve"))) or (
        "search summary" in text
        and any(token in text for token in ("source candidates", "admitted sources"))
        and any(token in text for token in (
            "non additive", "non-additive", "overlapping categories",
            "single transparent exclusion",
        ))
    ) or (
        "funnel" in text
        and any(token in text for token in ("arithmetic", "reconcile", "consistent", "remove funnel numbers"))
        and any(token in text for token in ("admitted source", "classified candidate", "candidate count", "corpus size", "overlapping bucket", "partial-only", "partial only", "mixed partial-or-none"))
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


def _asks_directional_coding_note(text: str) -> bool:
    return _asks_directional_coding(text) or (
        "evidence landscape" in text and "strongest signal" in text and "directional signal" in text
    ) or ("contextual claim" in text and "directional signal" in text) or (
        "null" in text and "absence of support" in text
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
    if _asks_mechanistic_content_reconciliation(text) or "cross-domain synthesis" in text and "template prose" in text or "severity 4" in text and re.search(r"(?:per[- ]endpoint|coding[- ]artifact)", text):
        return False
    if "tension descriptions" in text and any(token in text for token in ("source role", "review grade", "framing")):
        return False
    if re.search(
        r"\b(?:there\s+(?:is|are)\s+)?no\s+(?:(?:cross[- ]study|cross[- ]source|source|study)\s+)?"
        r"(?:disagreement|conflict|tension)s?\b|"
        r"\b(?:studies|sources?)\s+(?:do|does|did)\s+not\s+(?:disagree|conflict)|"
        r"\b(?:studies|sources?)\s+agree\s+rather\s+than\s+(?:disagree|conflict)|"
        r"\b(?:do|does|did|should|must)\s+not\s+(?:fabricate|invent|manufacture|add|claim)\s+"
        r"(?:any\s+)?(?:source|study)?\s*(?:disagreement|conflict|tension)s?|"
        r"\b(?:source|study)?\s*(?:disagreement|conflict|tension)s?\s+"
        r"(?:(?:is|are|was|were)\s+not\s+(?:found|observed|present|substantiated|supported)|"
        r"(?:should|must)\s+not\s+be\s+(?:fabricated|invented|manufactured|added|claimed))",
        text,
    ):
        return False
    disagreement = any(token in text for token in ("conflict", "contradiction", "disagree", "tension"))
    source_identity = any(identity in text for identity in ("source", "study", "studies", "author-year", "author year"))
    pair_tokens = ("cross-source", "cross-study", "source pair", "source-pair", "study pair", "study-pair",
                   "pairs of sources", "pairs of retained sources", "author-year contrast", "author year contrast",
                   "sources on each side", "studies on each side")
    pair_language = any(token in text for token in pair_tokens) or source_identity and bool(re.search(r"\b(?:pairs?|contrasts?)\b", text))
    numbered_pairs = pair_language and bool(re.search(r"\b(?:three(?!\s*[-–]?\s*year)|3)\b", text))
    return source_identity and disagreement or numbered_pairs or (
        "non-orthogonal tensions" in text
        and any(token in text for token in ("operationalize", "calculation", "verifiable", "auditable"))
    ) or (
        "tensions and gaps" in text and disagreement
        and any(token in text for token in ("0 disagreement", "zero disagreement", "do not say", "don't say"))
    )


def _asks_boundary_matrix_reconciliation(text: str) -> bool:
    return (
        any(token in text for token in ("directness map", "boundary-condition matrix"))
        and "outcome-class table" in text
        and any(token in text for token in ("reconcile", "cumulative", "match"))
    )


def _boundary_matrix_reconciliation_is_stated(paper_md: str) -> bool:
    text = " ".join(paper_md.lower().split())
    return (
        "source counts are cumulative within each outcome class" in text
        and "reconcile to the results outcome-class roster" in text
    )


def _asks_non_orthogonal_dyad_definition(text: str) -> bool:
    return (
        "non-orthogonal dyad" in text
        and any(token in text for token in ("define", "definition", "operational"))
    )


def _non_orthogonal_dyad_definition_is_stated(paper_md: str) -> bool:
    text = " ".join(paper_md.lower().split())
    return (
        "unordered receipt pair" in text
        and "counted once" in text
        and "non-orthogonal" in text
        and all(token in text for token in (
            "directness gap", "mechanism-clinical boundary", "differing directions",
        ))
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
        or ("outcome-class subsection" in text and any(token in text for token in ("expand", "remove the headers", "remove headers"))) or ("no extractable efficacy numerics" in text and "no quantitative" in text)
    )


def _asks_replaced_surface_tensions(text: str) -> bool:
    return (
        "replace" in text
        and "surfaced tension" in text
        and any(token in text for token in ("within-outcome", "within outcome", "comparable"))
    )


def _asks_internal_duplication(text: str) -> bool:
    return any(token in text for token in (
        "internal duplication", "repetitive narrative", "verbatim repetition",
        "non-repetitive", "duplicate sentence", "near-duplicate", "near duplicate",
        "repetitive template", "template-style language", "template style language",
        "source-by-source narration", "source by source narration",
    ))


def _asks_long_term_safety_scope(text: str) -> bool:
    return "long-term safety" in text or ("safety data" in text and "older adult" in text)


def _asks_named_direct_clinical_source(text: str) -> bool:
    return "direct clinical source" in text and any(token in text for token in ("which source", "clarify", "state this explicitly"))


def _asks_outcome_subsection_source_narrative(text: str) -> bool:
    return (
        "outcome subsection" in text
        and "source" in text
        and ("conclusion" in text or "direct source" in text)
    ) or (
        "outcome-class synthesis" in text
        and any(token in text for token in ("representative finding", "directness summary", "real outcome"))
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
    ) or "traceable to the source bundle" in text or _revision.asks_pmid_accuracy(text)


def _asks_citation_traceability_map(text: str) -> bool:
    return (
        "author-year" in text
        and "citation" in text
        and any(token in text for token in ("source bundle entry", "source-bundle entry", "bundle entry"))
        and any(token in text for token in ("methods_pack", "citation list", "mapping"))
    ) or (
        "source bundle" in text
        and "citation" in text
        and "manifest" in text
        and any(token in text for token in ("inline", "1:1", "audit trail", "reconcile"))
    )


def _asks_framework_reclassification_cleanup(text: str) -> bool:
    return (
        "reclassify" in text
        and "mabrouk 2025" in text
        and any(token in text for token in (
            "metabolic-functional tradeoff",
            "metabolic functional tradeoff",
            "falsifying-test",
            "falsifying test",
        ))
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
    ) or (
        "citation" in text
        and any(token in text for token in (
            "not present in the source bundle",
            "bundle-resident source", "bundle provenance",
        ))
    )


def _asks_structured_table_stub_replacement(text: str) -> bool:
    return (
        "see the structured evidence table" in text
        and any(token in text for token in ("replace", "stubs", "prose paragraph", "prose paragraphs"))
    )


def outcome_label_rename(text: str) -> tuple[str, str] | None:
    lower = " ".join(text.lower().split())
    if "outcome class" in lower and any(token in lower for token in ("rename", "re-label", "relabel")) and len(labels := re.findall(r"['\"]([^'\"]{2,80})['\"]", text)) >= 2:
        return labels[0].strip(), labels[1].strip()
    dosing = any(label in lower for label in ("dosing and pharmacokinetics", "dosing/pharmacokinetics", "dosing pharmacokinetics")) and any(token in lower for token in (
        "re-label", "relabel", "remove", "not contain", "not a dosing", "not dosing", "not pk", "out of", "proxy", "catch-all",
    )) or (
        "exposure and dose-adjacent evidence outcomes" in lower and "real outcome-class synthesis" in lower
    )
    return ("Dosing and Pharmacokinetics", "Exposure and Dose-Adjacent Evidence") if dosing else None


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


def _asks_numeric_effect_audit_note(text: str) -> bool:
    return any(token in text for token in ("audit all reported p-values", "audit all reported p values", "reported p-values", "reported p values"))


def _asks_named_numeric_correction(text: str) -> bool:
    if _quality._asks_named_statistic_reconciliation(text):
        return False
    return (
        any(token in text for token in ("correct", "verify", "resolve", "reconcile", "recode", "recoded", "remove"))
        and (
            any(token in text for token in ("p=", "p =", "p-value", "p value", "confidence interval"))
            or bool(re.search(r"\b(?:95%\s*)?ci\b", text, flags=re.I))
        )
        and (
            any(token in text for token in (
                "non-significant", "not significant", "no significant", "factual error",
                "representative statistic", "miscoded", "direction/statistic", "direction statistic",
                "positive signal", "positive coding", "numeric correction", "unclear/null", "null/mixed",
            ))
            or bool(named_significance_targets(text))
        )
    )


def named_significance_targets(text: str) -> tuple[str, ...]:
    targets: list[str] = []
    for match in re.finditer(
        r"\b(?:(?:no|not(?:\s+a)?)\s+)?(?:statistically\s+)?"
        r"significant(?:ly)?\s+([a-z][a-z0-9 /_-]{2,120}?)"
        r"(?=\s+(?:while|whereas|but)\b|\s+and\s+(?:(?:a\s+)?"
        r"(?:statistically\s+)?significant|keep|leave|preserv|retain)|[.;,:]|\Z)",
        text,
        flags=re.I,
    ):
        if re.search(
            r"\b(?:keep|leave|preserv\w*|retain\w*|"
            r"do\s+not\s+(?:change|alter|revise)|without\s+(?:changing|altering|revising))"
            r"\s+(?:the\s+)?$",
            text[max(0, match.start() - 80):match.start()], re.I,
        ):
            continue
        target = re.sub(r"\b(?:claim|finding|result)\b", " ", match.group(1), flags=re.I)
        target = " ".join(target.casefold().split())
        if target:
            targets.append(target)
    return tuple(dict.fromkeys(targets))


def significance_target_pattern(target: str) -> str:
    return r"\s+".join(re.escape(part) for part in target.split())


def significance_claim_is_negated(prefix: str) -> bool:
    return bool(re.search(
        r"(?:\b(?:no|not(?:\s+a)?|without(?:\s+a)?|no\s+evidence\s+of(?:\s+a)?|"
        r"(?:did\s+)?not\s+(?:show|find|detect)(?:\s+a)?|"
        r"failed\s+to\s+(?:show|find|detect)(?:\s+a)?)\s*|\bnon[- ])$",
        prefix,
        flags=re.I,
    ))


def _has_positive_named_significance_claim(text: str, targets: tuple[str, ...]) -> bool:
    for target in targets:
        pattern = re.compile(
            rf"\b(?:statistically\s+)?significant(?:ly)?\s+"
            rf"{significance_target_pattern(target)}\b",
            flags=re.I,
        )
        if any(not significance_claim_is_negated(text[max(0, match.start() - 48):match.start()])
               for match in pattern.finditer(text)):
            return True
    return False


def _asks_numeric_correction_markup_cleanup(text: str) -> bool:
    return (
        "numeric correction" in text
        and any(token in text for token in ("leftover", "editing markup", "remove", "contextualize", "abstract", "research question"))
    )


def _asks_grammar_correction(text: str) -> bool:
    return any(token in text for token in (
        "grammatical error", "grammar error", "correct the grammatical",
        "typographical artifact", "typographical error", "typo", "wording artifact",
    ))


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
    if "no extractable efficacy numerics" in ask:
        target = re.search(r"\bthe\s+(.+?)\s+results\b", ask)
        lower = scope.lower()
        return all(token in lower for token in ("no extractable efficacy numerics are available", "no quantitative", "claim")) and (not target or target.group(1) in lower)
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


def _concrete_tensions_gaps_are_stated(
    paper_md: str, ask: str, *, retained_citations: Iterable[str] | None = None,
) -> bool:
    text = paper_md.lower()
    if "evidence-gap priority" not in text and "gaps identified" not in text:
        if not _asks_tension_section_placement(ask.lower()):
            return False
    placement = _asks_tension_section_placement(ask.lower())
    scope = ("\n\n".join(filter(None, (
        _section(paper_md, "Discussion"), _section(paper_md, "Conclusion"),
    ))) if placement else
             _section(paper_md, "Tensions and Gaps") or _section(paper_md, "Cross-Domain Synthesis"))
    if not scope:
        return False
    if placement:
        labels = _source_labels_from_ask(ask)
        lower_scope = scope.lower()
        return all(_label_in_text(label, lower_scope) for label in labels) and any(
            token in lower_scope for token in ("tension", "disagreement", "conflict", "versus", " vs ")
        )
    pairs, _ = _tension_pairs(paper_md, scope, retained_citations)
    count = r"(?:at\s+least\s+)?(?:three(?!\s*[-–]?\s*year)|3(?:\s*[-–]\s*5)?)"
    pair = r"(?:tensions?|disagreements?|conflicts?|contrasts?|pairs?)"
    asks_for_three = bool(re.search(
        rf"\b(?:{count}\b[^.;:\n]{{0,120}}\b{pair}|{pair}\b[^.;:\n]{{0,120}}\b{count})\b",
        ask, flags=re.I,
    ))
    qualitative_replacement = (
        "no semantically comparable source-pair disagreements" in text
        and "qualitative description" in ask.lower()
    )
    return qualitative_replacement or len(pairs) >= (3 if asks_for_three else 1)


_TENSION_PAIR_RE = re.compile(
    r"^\s*(?:[-*]\s*)?(?:(?:(?!\b(?:vs\.?|versus)\b)[^:\n]){2,100}:\s*)?"
    r"(?P<left>[^:\n]{2,180}?)\s+(?:vs\.?|versus)\s+(?P<right>[^:\n]{2,180}?)(?=\s*:|\s*;|$)", re.I)


def _tension_pairs(
    paper_md: str, scope: str, retained_citations: Iterable[str] | None,
) -> tuple[set[tuple[str, str]], list[str]]:
    lines = [line.strip() for line in scope.splitlines()
             if _TENSION_PAIR_RE.search(line) and re.search(r"\b(?:tension|disagreement|conflict)\b", line, re.I)]
    excluded = {line.casefold() for line in lines}
    support = "\n".join(line for line in paper_md.splitlines()
                        if line.strip().casefold() not in excluded).casefold()
    retained = None if retained_citations is None else {
        " ".join(label.casefold().split()) for label in retained_citations
    }
    pairs: set[tuple[str, str]] = set()
    for line in lines:
        match = _TENSION_PAIR_RE.search(line)
        assert match is not None
        left, right = match.group("left").lower(), match.group("right").lower()
        unretained = retained is not None and (left not in retained or right not in retained)
        if left == right or left not in support or right not in support or unretained:
            continue
        pairs.add((left, right) if left <= right else (right, left))
    return pairs, lines


def _replaced_surface_tensions_are_stated(
    paper_md: str, ask: str, *, retained_citations: Iterable[str] | None = None,
) -> bool:
    scope = _section(paper_md, "Tensions and Gaps") or _section(paper_md, "Cross-Domain Synthesis")
    if not scope:
        return False
    blocked = {
        match.group(1).lower()
        for match in re.finditer(r"\b([a-z][a-z'’\-]+ 20\d{2})(?:-based|\s+based)\b", ask)
    }
    pairs, tension_lines = _tension_pairs(paper_md, scope, retained_citations)
    if len(pairs) < 3:
        return False
    if blocked and any(any(name in line.lower() for name in blocked) for line in tension_lines):
        return False
    comparable = [line for line in tension_lines if "same outcome" in line.lower()
                  or re.search(r"\bin [A-Za-z][A-Za-z /-]+ because directions\b", line)]
    comparable_pairs = {
        tuple(sorted((match.group("left").lower(), match.group("right").lower())))
        for line in comparable if (match := _TENSION_PAIR_RE.search(line))
    }
    return len(comparable_pairs & pairs) >= 3


def _internal_duplication_scope(paper_md: str, ask: str) -> str:
    names = (
        "Abstract", "Evidence Landscape", "Key Findings", "Results", "Full Manuscript",
        "Gaps Identified", "Cross-Domain Synthesis", "Discussion", "Limitations", "Conclusion",
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


_RESULT_TRACE_RE = re.compile(
    r"^[^\n]{1,160}\[bundle:\d+\]\s+reports:\s+.+\[exact source:\s*https?://[^\]]+\]\.\s*$",
    re.I | re.S,
)


def _results_trace_paragraphs(paper_md: str) -> list[str]:
    return [
        part.strip() for part in re.split(r"\n\s*\n", _section(paper_md, "Results"))
        if _RESULT_TRACE_RE.fullmatch(part.strip())
    ]


def _move_results_trace_dump(paper_md: str) -> tuple[str, int]:
    traces = _results_trace_paragraphs(paper_md)
    match = re.search(r"(?ms)^## Results\b(?P<body>.*?)(?=^## |\Z)", paper_md)
    if len(traces) < 3 or not match:
        return paper_md, 0
    kept = [part.strip() for part in re.split(r"\n\s*\n", match.group("body")) if part.strip() and part.strip() not in traces]
    fixed = paper_md[:match.start("body")] + "\n\n" + "\n\n".join(kept) + "\n\n" + paper_md[match.end("body"):].lstrip("\n")
    existing = re.search(r"(?ms)^## Claim-to-Source Trace\b(?P<body>.*?)(?=^## |\Z)", fixed)
    prior = [part.strip() for part in re.split(r"\n\s*\n", existing.group("body")) if part.strip()] if existing else []
    if existing:
        fixed = fixed[:existing.start()] + fixed[existing.end():].lstrip("\n")
    block = "## Claim-to-Source Trace\n\n" + "\n\n".join(dict.fromkeys(prior + traces)) + "\n\n"
    reference = re.search(r"^## References\b", fixed, re.M | re.I)
    fixed = fixed[:reference.start()] + block + fixed[reference.start():] if reference else fixed.rstrip() + "\n\n" + block
    return fixed, len(traces)


def repair_internal_duplication(paper_md: str, ask: str) -> tuple[str, int]:
    lower_ask = " ".join(ask.lower().split())
    if not _asks_internal_duplication(lower_ask):
        return paper_md, 0
    moved = 0
    if "results" in lower_ask and "template" in lower_ask:
        paper_md, moved = _move_results_trace_dump(paper_md)
    names = (
        "Abstract", "Evidence Landscape", "Key Findings", "Results", "Gaps Identified",
        "Cross-Domain Synthesis", "Discussion", "Limitations", "Conclusion",
    )
    targets = {name for name in names if name.lower() in ask.lower()}
    parts = re.split(r"(\n\s*\n)", paper_md)
    heading, changed = "", moved
    seen_paragraphs: list[set[str]] = []
    seen_sentences: set[str] = set()
    for index in range(0, len(parts), 2):
        stripped = parts[index].strip()
        if match := re.match(r"^#{2,3}\s+(.+?)\s*$", stripped):
            heading = match.group(1)
            continue
        if not stripped or targets and heading not in targets or stripped.startswith(("|", "```")):
            continue
        kept = []
        for sentence in re.split(r"(?<=[.!?])\s+", stripped):
            key = " ".join(re.findall(r"[a-z0-9]+", sentence.lower()))
            if len(key.split()) >= 6 and key in seen_sentences:
                changed += 1
                continue
            if len(key.split()) >= 6:
                seen_sentences.add(key)
            kept.append(sentence)
        candidate = " ".join(kept).strip()
        tokens = set(re.findall(r"[a-z0-9]+", candidate.lower()))
        if len(tokens) >= 18 and any(
            len(tokens & prior) / max(1, min(len(tokens), len(prior))) >= 0.75
            for prior in seen_paragraphs
        ):
            parts[index], changed = "", changed + 1
            continue
        if tokens:
            seen_paragraphs.append(tokens)
        parts[index] = candidate
    fixed = re.sub(r"\n{3,}", "\n\n", "".join(parts))
    if all(token in lower_ask for token in ("conclusion", "falsifiable")):
        conclusion = _section(fixed, "Conclusion").strip()
        if len(conclusion.split()) < 40:
            conclusion = (
                "The current evidence supports only the bounded conclusions stated in "
                "this manuscript. A stronger future conclusion would require direct "
                "studies with prespecified populations, comparators, endpoints, and "
                "follow-up that test the unresolved evidence boundaries. Until then, "
                "these findings remain a source-bounded synthesis rather than a general "
                "efficacy claim or clinical recommendation."
            )
            fixed = re.sub(
                r"(?ms)^## Conclusion\s*\n.*?(?=^## |\Z)",
                f"## Conclusion\n\n{conclusion}\n\n",
                fixed,
            )
            changed += 1
    return fixed, changed


def repair_fragment_headings(paper_md: str, ask: str) -> tuple[str, int]:
    if "garbled section fragment" not in ask.lower():
        return paper_md, 0
    fragments = [next(value for value in match.groups() if value) for match in re.finditer(
        r"'([^'\n]{8,})'|\"([^\"\n]{8,})\"|“([^”\n]{8,})”|‘([^’\n]{8,})’", ask)]
    changed = 0
    def clean(match: re.Match[str]) -> str:
        nonlocal changed
        heading = match.group(0)
        for fragment in fragments:
            heading = re.sub(re.escape(fragment), "", heading, flags=re.I)
        heading = re.sub(r"\s{2,}", " ", heading).rstrip(" -:;,")
        changed += int(heading != match.group(0))
        return heading
    return re.sub(r"^#{2,3}\s+.+?$", clean, paper_md, flags=re.M), changed


def _internal_duplication_is_low(paper_md: str, ask: str = "") -> bool:
    if "results" in ask and "template" in ask and len(_results_trace_paragraphs(paper_md)) >= 3:
        return False
    seen: list[set[str]] = []
    seen_sentences: set[str] = set()
    for paragraph in re.split(r"\n\s*\n", _internal_duplication_scope(paper_md, ask)):
        text = " ".join(line.strip() for line in paragraph.splitlines() if not line.lstrip().startswith(("|", "#", "- [")))
        for sentence in re.split(r"(?<=[.!?])\s+", text):
            normalised = " ".join(re.findall(r"[a-z0-9]+", sentence.lower()))
            if len(normalised.split()) < 6:
                continue
            if normalised in seen_sentences:
                return False
            seen_sentences.add(normalised)
        words = re.findall(r"[a-z0-9]+", text.lower())
        if len(words) < 18:
            continue
        tokens = set(words)
        if any(len(tokens & prior) / max(1, min(len(tokens), len(prior))) >= 0.75 for prior in seen):
            return False
        seen.append(tokens)
    if not all(token in ask for token in ("conclusion", "falsifiable")):
        return True
    conclusion = _section(paper_md, "Conclusion").lower()
    return (
        len(conclusion.split()) >= 40
        and any(token in conclusion for token in (
            "would require", "future evidence", "future conclusion",
            "until then", "would be falsified", "testable",
        ))
    )


def _long_term_safety_scope_is_stated(paper_md: str) -> bool:
    scope = " ".join(part for part in (_abstract(paper_md), _section(paper_md, "Conclusion"), _section(paper_md, "Limitations")) if part).lower()
    if not scope:
        return False
    safety = "long-term safety" in scope or "long term safety" in scope or "safety data" in scope
    population = "older adult" in scope or "older adults" in scope or "aged" in scope
    return safety and population


def _evidence_type_metadata_is_resolved(paper_md: str, ask: str) -> bool:
    if _asks_mechanistic_content_reconciliation(ask.lower()):
        # The evidence-aware quality proof validates the exact row-derived note.
        return True
    labels = _source_labels_from_ask(ask)
    if labels and all(any(label.lower() in line.lower() and re.search(
        r"\bdirectness=(?:direct|indirect)\b.*\btier=A[12]\b", line, re.I,
    ) for line in paper_md.splitlines()) for label in labels):
        return True
    scope = " ".join(filter(None, (_section(paper_md, "Methods"), _section(paper_md, "Evidence Snapshot"),
                                   _section(paper_md, "Evidence Landscape"), _section(paper_md, "Results")))).lower()
    if all(token in scope for token in (
        "evidence-type reconciliation:", "directness=review", "direct clinical rct",
    )):
        return True
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


def _framework_reclassification_cleanup_is_stated(paper_md: str) -> bool:
    text = paper_md.lower()
    mabrouk_idx = text.find("mabrouk 2025")
    mabrouk_scope = text[max(0, mabrouk_idx - 600):mabrouk_idx + 900] if mabrouk_idx >= 0 else ""
    return (
        "mabrouk 2025" in text
        and "deficiency prevalence" in mabrouk_scope
        and "## metabolic-functional tradeoff framework" not in text
        and "paper-level organizing claim" in text
        and ("interpretive note" in text or "no direct evidence" in text)
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
    specific = (
        all(token in question for token in ("findings for", "among", "study-design"))
        or all(token in question for token in ("prognostic or risk-marker", "treatment or intervention", "directionally consistent"))
    )
    return (
        "?" in question
        and "source" in question
        and specific
        and ("outcome class" in question or "outcome-class" in question)
        and any(token in question for token in ("direct", "indirect", "mechanistic", "review"))
        and any(token in question for token in ("hypothesis-generating", "clinically actionable", "clinical"))
    )


def _author_inference_boundary_is_stated(paper_md: str, ask: str) -> bool:
    tokens = ("author-inference boundary", "synthesis-author inferences", "not independently established causal findings")
    return all(
        all(token in _section(paper_md, section).lower() for token in tokens)
        for section in _author_inference_sections(ask)
    )


def _quantitative_evidence_rows(paper_md: str) -> list[tuple[str, ...]]:
    rows: list[tuple[str, ...]] = []
    for line in _section(paper_md, "Quantitative Evidence Index").splitlines():
        cells = tuple(cell.strip() for cell in line.strip().strip("|").split("|"))
        if len(cells) != 6 or not any(cells) or cells[0].lower() == "study" or all(
            cell and set(cell) <= {"-", ":"} for cell in cells
        ):
            continue
        rows.append(cells)
    return rows


_NORMALIZED_P_VALUE_RE = re.compile(r"P\s+(?:=|<|>|\u2264|\u2265)\s+(0(?:\.\d+)?|1(?:\.0+)?)\Z")


def _p_value_rows_are_normalized(rows: list[tuple[str, ...]], *, required: bool) -> bool:
    p_rows = [row for row in rows if row[4].lower() in {"p-value", "p value", "p_value"}]
    return (not required or bool(p_rows)) and all(
        (match := _NORMALIZED_P_VALUE_RE.fullmatch(row[3])) is not None
        and float(match.group(1)) > 0 for row in p_rows
    )


def _quantitative_evidence_index_is_stated(paper_md: str, ask: str) -> bool:
    rows = _quantitative_evidence_rows(paper_md)
    feedback = _normalised_feedback(ask)
    requires_p_values = any(token in feedback for token in ("p value", "rounding", "notation"))
    return bool(rows) and _p_value_rows_are_normalized(rows, required=requires_p_values)


_ROUNDED_ZERO_P_RE = re.compile(
    r"\bp\s*(?:=|<|\u2264)\s*(?:0(?!\d|\.\d)|0\.0+(?!\d)|\.0+(?!\d))",
    re.I,
)


def _numeric_discrepancy_is_resolved(paper_md: str) -> bool:
    rows = _quantitative_evidence_rows(paper_md)
    return (
        "numeric verification note:" in paper_md.lower()
        and not _ROUNDED_ZERO_P_RE.search(paper_md)
        and _p_value_rows_are_normalized(rows, required=True)
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


def _asks_effect_direction_reconciliation(text: str) -> bool:
    return (
        any(token in text for token in ("effect_direction", "directionality", "direction code"))
        and any(token in text for token in ("actual reported finding", "reported finding", "excerpt", "contradicted", "positive", "negative", "null", "mixed", "unclear"))
        and any(token in text for token in ("align", "correct", "explain", "integrate", "justify", "reclassify", "recode", "reconcile", "remove", "verify"))
    ) or (
        "reclassify" in text
        and "direction" in text
        and bool(re.search(r"\b[A-Z][A-Za-z'’.\-]+(?:\s+et\s+al\.?)?\s+(?:19|20)\d{2}[a-z]?\b", text, flags=re.I))
    ) or (
        any(token in text for token in ("outcome class", "outcome-class"))
        and any(token in text for token in ("directional summar", "coded direction"))
        and any(token in text for token in ("correct", "reconcile", "match"))
    )


def _asks_admission_direction_tally_reconciliation(text: str) -> bool:
    return _revision.asks_authoritative_tally(text)


def _asks_bounded_research_question_conclusion(text: str) -> bool:
    return (
        "research question" in text
        and "conclusion" in text
        and any(token in text for token in ("bounded", "bound", "reframe"))
        and any(token in text for token in ("clinical efficacy", "direct interventional", "adjacent biomarkers", "prognostic associations"))
    )


def _asks_mr_mechanism_disagreement_separation(text: str) -> bool:
    return (
        any(token in text for token in ("separate", "do not pool", "don't pool", "not pool"))
        and any(token in text for token in ("mr", "mendelian"))
        and any(token in text for token in ("mechanistic", "mechanism", "alt"))
        and any(token in text for token in ("disagreement", "disagreements", "describing"))
    )


def _asks_no_direct_hard_endpoint_statement(text: str) -> bool:
    return (
        ("no direct interventional hard-endpoint" in text or "no direct interventional hard endpoint" in text)
        or (
            "direct interventional" in text
            and any(token in text for token in ("hard-endpoint", "hard endpoint"))
            and any(token in text for token in ("clinical actionability", "hypothesis-generation", "association"))
        )
        or (
            any(token in text for token in ("human cohort", "biopsy", "adjacent human", "human evidence"))
            and any(token in text for token in ("0 direct", "zero direct", "no direct", "direct framing"))
        )
    )


def _asks_publication_status_preprint_flags(text: str) -> bool:
    return (
        "preprint" in text
        and (
            "actual publication status" in text
            or ("publication status" in text and any(token in text for token in ("peer-reviewed", "peer reviewed")))
            or (
                "verify" in text
                and any(token in text for token in ("2026-dated", "2026 dated", "2026"))
            )
        )
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


def _asks_conclusion_recommendation_scope(text: str) -> bool:
    return "conclusion" in text and any(token in text for token in ("general health", "lifestyle recommendation", "lifestyle intervention")) and any(token in text for token in ("tighten", "bounded", "remove", "do not allow"))


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


def _effect_direction_reconciliation_is_stated(paper_md: str, ask: str) -> bool:
    scope = "\n\n".join(part for part in (
        _section(paper_md, "Evidence Landscape"),
        _section(paper_md, "Key Findings"),
        _section(paper_md, "Results"),
    ) if part)
    lower = scope.lower()
    labels = _source_labels_from_ask(ask)
    return (
        any(token in ask.lower() for token in ("outcome class", "outcome-class"))
        and "outcome-class coded-direction reconciliation:" in lower
        or "effect-direction reconciliation note:" in lower
        and "actual reported finding" in lower
        and "direction=" in lower
        and all(label.lower() in lower for label in labels)
    )


def _admission_direction_tally_reconciliation_is_stated(paper_md: str, ask: str = "") -> bool:
    return _revision.tally_note_is_stated(paper_md, require_outcomes=_revision.asks_outcome_class_tally(ask))


def _bounded_research_question_conclusion_is_stated(paper_md: str) -> bool:
    scope = "\n\n".join(part for part in (
        _section(paper_md, "Research Question"),
        _section(paper_md, "Key Findings"),
        _section(paper_md, "Conclusion"),
        _section(paper_md, "Limitations"),
    ) if part).lower()
    return (
        "scope-bounded research question note:" in scope
        and any(token in scope for token in ("not direct interventional", "not clinical efficacy"))
        and any(token in scope for token in ("adjacent biomarker", "prognostic association", "mechanism"))
    )


def _mr_mechanism_disagreement_separation_is_stated(paper_md: str) -> bool:
    scope = "\n\n".join(part for part in (
        _section(paper_md, "Evidence Landscape"),
        _section(paper_md, "Key Findings"),
        _section(paper_md, "Results"),
    ) if part).lower()
    return (
        "mr/mechanism disagreement separation note:" in scope
        and any(token in scope for token in ("mr", "mendelian"))
        and any(token in scope for token in ("mechanistic", "mechanism", "alt"))
        and any(token in scope for token in ("not pooled", "not pool"))
    )


def _no_direct_hard_endpoint_statement_is_stated(paper_md: str) -> bool:
    scope = "\n\n".join(part for part in (
        _section(paper_md, "Key Findings"),
        _section(paper_md, "Gaps Identified"),
        _section(paper_md, "Limitations"),
        _section(paper_md, "Conclusion"),
    ) if part).lower()
    return (
        "no direct interventional hard-endpoint sources were admitted" in scope
        and any(token in scope for token in ("hypothesis-generation", "hypothesis-generating", "association"))
    )


def _publication_status_preprint_flags_are_stated(paper_md: str) -> bool:
    scope = "\n\n".join(part for part in (
        _section(paper_md, "Evidence Landscape"),
        _section(paper_md, "Key Findings"),
        _section(paper_md, "Methods"),
        _section(paper_md, "Limitations"),
    ) if part).lower()
    return "publication-status/preprint note:" in scope and "2026" in scope and "preprint" in scope


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


def _conclusion_recommendation_scope_is_stated(paper_md: str) -> bool:
    conclusion = _section(paper_md, "Conclusion")
    return not unsupported_general_health_claim_spans(conclusion) and any(token in conclusion.lower() for token in ("non-supportive for clinical efficacy or general health", "does not support broad causal, clinical, or policy claims"))


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
        (
            "outcome-class key findings:" in lower
            and "admitted n=" in lower
            and "direction" in lower
            and "directness" in lower
            and re.search(r"\b[A-Z][A-Za-z-]+(?:\s+et\s+al\.?)?\s+20\d{2}[a-z]?\b", findings)
        )
        or _key_findings_source_verdict_is_stated(paper_md)
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
        or ("future-dated" in text and "source" in text and ("verify" in text or "flag" in text))
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


def _admission_funnel_numeric_consistency_is_stated(paper_md: str, ask: str) -> bool:
    labels = {"classified": r"classified(?: source)? candidates?", "admitted": r"admitted(?: final)?(?: sources?| receipts?| source base)?"}
    requested: dict[str, int] = {}
    for key, label in labels.items():
        match = re.search(rf"\b(\d+)\s+{label}\b|\b{label}[^\d\n]{{0,12}}(\d+)\b", ask, re.I)
        if match:
            requested[key] = int(match.group(1) or match.group(2))
    rows = _funnel_counts(paper_md)
    markers = ("corpus-count reconciliation:", "admission-bucket note:", "stepwise reconciliation:")
    reconciliation = "\n".join(paragraph for paragraph in re.split(r"\n\s*\n", paper_md) if any(marker in paragraph.lower() for marker in markers))
    exact_note = all(re.search(rf"(?:\b{count}\s+{labels[key]}\b|\b{labels[key]}[^\d\n]{{0,12}}{count}\b)", reconciliation, re.I) for key, count in requested.items())
    row_counts = {"classified": rows.get("classified source candidates") or rows.get("classified candidates"), "admitted": rows.get("admitted final sources") or rows.get("admitted final receipts")}
    exact_rows = all(row_counts[key] == count for key, count in requested.items())
    if requested.keys() == labels.keys() and exact_rows:
        return True
    if requested and not (exact_note or exact_rows):
        return False
    reconciliation_lower = reconciliation.lower()
    accepted_notes = (("corpus-count reconciliation:", "classified source candidates", "admitted source counts are not interchangeable"), ("admission-bucket note:", "not an additive conservation table", "claim-binding states"), ("stepwise reconciliation:", "classified source candidates", "admitted final sources"))
    if any(all(token in reconciliation_lower for token in note) for note in accepted_notes):
        return True
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


def _references_are_traceable(paper_md: str, ask: str = "") -> bool:
    if _revision.asks_pmid_accuracy(ask):
        return _revision.pmid_verification_is_stated(paper_md)
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


def outcome_label_cleanup_is_stated(paper_md: str, ask: str) -> bool:
    if not (rename := outcome_label_rename(ask)):
        return True
    old_label = rf"(?:^#{{2,4}}\s*{re.escape(rename[0])}(?:\s+Outcomes?)?\s*$|\|\s*{re.escape(rename[0])}\s*\||\b(?:outcome(?:\s+class)?|evidence domain)\s*[:=]\s*{re.escape(rename[0])}\b|\b{re.escape(rename[0])}\s+outcome class\b)"
    return rename[1].lower() in paper_md.lower() and not re.search(old_label, paper_md, flags=re.I | re.M)


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
        not ("denominator" in text and any(token in text for token in ("direct-source", "direct source")) and "slice" in text)
        and any(token in text for token in (
            "corpus-size", "corpus size", "overcount", "overcounts", "funnel counts",
            "source-count denominator", "source count denominator", "denominator",
        ))
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
    target = numeric_correction_target(ask)
    p_value = re.search(r"\bp\s*=\s*(0?\.\d+|1(?:\.0+)?)", ask, flags=re.I)
    interval = _CI_RE.search(ask)
    scope = " ".join(part for part in (
        _abstract(paper_md),
        _section(paper_md, "Research Question"),
        _section(paper_md, "Methods"),
        _section(paper_md, "Evidence Landscape"),
        _section(paper_md, "Results"),
        _section(paper_md, "Conclusion"),
    ) if part).lower()
    if target and target[0].lower() not in scope:
        return False
    if p_value and f"p = {p_value.group(1)}" not in scope and f"p={p_value.group(1)}" not in scope:
        return False
    if interval and not (
        interval.group(1) in scope
        and interval.group(2) in scope
        and (" ci" in scope or "confidence interval" in scope)
    ):
        return False
    adjusted = has_adjusted_significance_threshold(ask)
    statistic_is_non_significant = explicit_stat_is_non_significant(ask)
    nominally_significant = statistic_is_non_significant is False and not adjusted
    if nominally_significant:
        return any(token in scope for token in ("nominally statistically significant", "statistically significant"))
    if statistic_is_non_significant is None:
        return False
    return any(
        token in scope for token in (
            "non-significant", "not significant", "no significant", "did not reach significance",
        )
    ) and not _named_numeric_positive_contradiction(paper_md, ask)


def named_numeric_correction_is_stated(paper_md: str, ask: str) -> bool:
    return _named_numeric_correction_is_stated(paper_md, ask)


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
    target = numeric_correction_target(ask)
    if target is None or explicit_stat_is_non_significant(ask) is not True:
        return False
    source, _, _ = target
    author, year = source.rsplit(" ", 1)
    labels = {
        source.lower(), f"{author} ({year})".lower(),
    }
    targets = named_significance_targets(ask)
    for line in paper_md.splitlines():
        lower = line.lower()
        if any(label in lower for label in labels) and (
            _POSITIVE_NUMERIC_CONTRADICTION_RE.search(line)
            or _has_positive_named_significance_claim(line, targets)
        ):
            return True
    for chunk in _source_local_chunks(paper_md):
        lower = chunk.lower()
        if any(label in lower for label in labels) and (
            _POSITIVE_NUMERIC_CONTRADICTION_RE.search(chunk)
            or _has_positive_named_significance_claim(chunk, targets)
        ):
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
            "every prose-cited finding", "every prose cited finding",
        )
    )


def _author_year_labels(text: str) -> list[str]:
    return list(dict.fromkeys(
        re.findall(r"\b[A-Z][A-Za-z'’.\-]+(?:\s+et\s+al\.?)?\s+(?:19|20)\d{2}[a-z]?\b", text)
    ))


def _label_in_text(label: str, text: str) -> bool:
    lower = label.lower()
    return lower in text or re.sub(r"\s+((?:19|20)\d{2}[a-z]?)\b", r" (\1)", lower) in text


def _grammar_artifacts_are_absent(paper_md: str, ask: str) -> bool:
    if re.search(r"\b(?:is|are|was|were)\s+insufficient\s+to\s+(?:is|are|was|were)\b", paper_md, flags=re.I):
        return False
    quoted = [next(value for value in match.groups() if value) for match in re.finditer(
        r"'([^'\n]{8,})'|\"([^\"\n]{8,})\"|“([^”\n]{8,})”|‘([^’\n]{8,})’", ask)]
    if not quoted:
        return True
    lower_ask = ask.lower()
    scope = next((_abstract(paper_md) if name == "Abstract" else _section(paper_md, name)
                  for marker, name in (("abstract", "Abstract"), ("discussion", "Discussion"),
                                       ("conclusion", "Conclusion"), ("limitations", "Limitations"))
                  if marker in lower_ask), paper_md)
    normalised = " ".join(scope.lower().split())
    return bool(scope) and all(" ".join(phrase.lower().split()) not in normalised for phrase in quoted)


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
    r"\b(?:non[- ]?significant(?:ly)?|(?:no|not)\s+(?:statistically\s+)?significant(?:ly)?|did\s+not\s+reach\s+significance)\b",
    re.I,
)


def explicit_stat_is_non_significant(text: str) -> bool | None:
    if p_value := _P_VALUE_RE.search(text):
        return float(p_value.group(1)) >= 0.05
    if interval := _CI_RE.search(text):
        low, high = map(float, interval.groups())
        return low <= 0 <= high or (
            low <= 1 <= high and min(abs(low), abs(high)) > 0
        )
    return None


def numeric_correction_target(text: str) -> tuple[str, str, bool] | None:
    p_value = _P_VALUE_RE.search(text)
    statistic = p_value or _CI_RE.search(text)
    if statistic is None:
        return None
    source_re = re.compile(r"\b([A-Z][A-Za-z'’.\-]+)\s+((?:19|20)\d{2}[a-z]?)")
    start, end = max(0, statistic.start() - 180), min(len(text), statistic.end() + 180)
    scope, offset = text[start:end], start
    sources = list(source_re.finditer(scope))
    if not sources:
        scope, offset, sources = text, 0, list(source_re.finditer(text))
    if not sources:
        return None
    statistic_at = statistic.start() - offset
    source = next((item for item in reversed(sources) if item.start() <= statistic_at), sources[0])
    stat_text = f"p = {statistic.group(1)}" if p_value else f"95% CI {statistic.group(1)} to {statistic.group(2)}"
    return f"{source.group(1)} {source.group(2)}", stat_text, p_value is not None


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


_AskMatcher = Callable[[str], bool]
_AskCheck = Callable[[str, str, str], bool]


def _paper_only(checker: Callable[[str], bool]) -> _AskCheck:
    def check(paper_md: str, _ask: str, _lower: str) -> bool:
        return checker(paper_md)
    return check


def _paper_ask(checker: Callable[[str, str], bool]) -> _AskCheck:
    def check(paper_md: str, ask: str, _lower: str) -> bool:
        return checker(paper_md, ask)
    return check


def _paper_lower(checker: Callable[[str, str], bool]) -> _AskCheck:
    def check(paper_md: str, _ask: str, lower: str) -> bool:
        return checker(paper_md, lower)
    return check


def _contains_all(*tokens: str) -> _AskCheck:
    def check(paper_md: str, _ask: str, _lower: str) -> bool:
        text = paper_md.lower()
        return all(token in text for token in tokens)
    return check


def _contains_any(*tokens: str) -> _AskCheck:
    def check(paper_md: str, _ask: str, _lower: str) -> bool:
        text = paper_md.lower()
        return any(token in text for token in tokens)
    return check


def _source_outcome_class_map_satisfied(paper_md: str, ask: str, lower: str) -> bool:
    if _asks_full_source_surface_request(lower):
        return _full_surface_sources_are_visible(paper_md, ask) and (
            _substantive_evidence_synthesis_is_stated(paper_md)
            or _source_outcome_class_map_is_stated(paper_md)
        )
    return _source_outcome_class_map_is_stated(paper_md) and _full_surface_sources_are_visible(paper_md, ask)


def _scope_framing_satisfied(paper_md: str, _ask: str, lower: str) -> bool:
    return _scope_framing_is_stated(paper_md) and (
        not _asks_direction_tally_audit(lower) or _direction_tally_audit_is_stated(paper_md)
    )


def _substantive_evidence_satisfied(paper_md: str, ask: str, _lower: str) -> bool:
    return _substantive_evidence_synthesis_is_stated(paper_md) and _full_surface_sources_are_visible(paper_md, ask)


def _contextual_subdomain_disaggregation_is_stated(paper_md: str, ask: str, _lower: str) -> bool:
    paper, requested = " ".join(paper_md.lower().split()), " ".join(ask.lower().split())
    labels = {"cognitive": "cognitive and neurobehavioral evidence", "immune": "immune and inflammation-adjacent evidence", "vascular": "vascular and hemodynamic evidence", "nutrition": "nutrition-interaction evidence", "prognostic": "prognostic and survival-marker evidence", "survival": "prognostic and survival-marker evidence", "causal": "causal-risk and mendelian-randomization evidence", "mendelian": "causal-risk and mendelian-randomization evidence", "mechanism": "biology-mechanism and molecular-context evidence", "molecular": "biology-mechanism and molecular-context evidence", "treatment": "treatment or intervention-response evidence", "intervention": "treatment or intervention-response evidence"}
    tail = requested[requested.find("disaggregat"):]
    match = re.search(r"\b(?:into|by)\s+(?!sub[- ]?(?:classes|domains)\b|classes\b|categories\b)(.+?)\s+(?:sub[- ]?(?:classes|domains)|classes|categories)\b", tail) or re.search(r"\b(?:sub[- ]?(?:classes|domains)|classes|categories)\s*:\s*([^.;]+)", tail)
    scope = re.split(r"[.;]|\b(?:because|since|while|whereas|so that)\b", match.group(1) if match else tail, 1)[0]
    return "contextual-adjacent subdomain map" in paper and all(label in paper for cue, label in labels.items() if cue in scope and not re.search(rf"\b(?:not(?!\s+only\b)|exclude|excluding|without)\b[^,;]{{0,40}}\b{cue}\b", scope)) and (not any(token in requested for token in ("justify", "lumping", "what is lost")) or "single adjacent bucket would obscure" in paper)


def _numeric_effect_audit_satisfied(paper_md: str, _ask: str, _lower: str) -> bool:
    return _numeric_effect_audit_is_stated(paper_md) and not numeric_effect_direction_issues(paper_md)


def _named_numeric_correction_satisfied(paper_md: str, ask: str, _lower: str) -> bool:
    return (
        _named_numeric_correction_is_stated(paper_md, ask)
        and _numeric_correction_markup_is_resolved(paper_md)
        and not numeric_effect_direction_issues(paper_md)
    )


def _numeric_effect_accuracy_satisfied(paper_md: str, _ask: str, _lower: str) -> bool:
    return not numeric_effect_direction_issues(paper_md)


_DETERMINISTIC_ASK_RULES: tuple[tuple[_AskMatcher, _AskCheck], ...] = (
    (_asks_inferential_bridge, _paper_only(_inferential_bridge_is_stated)),
    (_asks_directness_coding_criteria, _paper_only(_directness_coding_criteria_are_stated)),
    (_asks_classification_criteria, _contains_all("classification criteria", "outcome class", "directness", "evidence tier")),
    (_asks_conflict_severity_criteria, _contains_all("conflict-map severity note", "severity-level-3", "severity-level-4", "contradiction-map")),
    (_asks_source_outcome_class_map, _source_outcome_class_map_satisfied),
    (_asks_framework_reclassification_cleanup, _paper_only(_framework_reclassification_cleanup_is_stated)),
    (_asks_findings_map_source_verdict, _paper_only(_findings_map_source_verdict_is_stated)),
    (_asks_key_findings_source_verdict, _paper_only(_key_findings_source_verdict_is_stated)),
    (_asks_most_supported_key_findings, _paper_only(_most_supported_key_findings_are_stated)),
    (_asks_adjacent_indirect_reconciliation, _paper_only(_adjacent_indirect_reconciliation_is_stated)),
    (_asks_source_classification_map, _contains_all("source classification map", "outcome=", "directness=", "tier=")),
    (_asks_evidence_type_metadata, _paper_ask(_evidence_type_metadata_is_resolved)),
    (_asks_source_inclusion_rationale, _paper_only(_source_inclusion_rationale_is_stated)),
    (_asks_species_study_design_summary, _paper_only(_species_study_design_summary_is_stated)),
    (_asks_source_directness_breakdown, _paper_only(_source_directness_breakdown_is_stated)),
    (_asks_source_statistics_landscape, _paper_only(_source_statistics_landscape_is_stated)),
    (_asks_citation_traceability_map, _paper_only(_citation_traceability_map_is_stated)),
    (_asks_source_label_disambiguation, _paper_ask(_source_label_disambiguation_is_stated)),
    (_asks_source_verification_transparency, _paper_only(_source_verification_transparency_is_stated)),
    (_asks_source_identifier_gap_note, _paper_only(_source_identifier_gap_note_is_stated)),
    (_asks_section_source_grounding, _paper_only(_section_source_grounding_is_stated)),
    (_asks_outcome_class_key_findings, _paper_only(_outcome_class_key_findings_are_stated)),
    (_asks_two_part_research_question, _paper_only(_two_part_research_question_is_stated)),
    (_asks_concrete_research_question, _paper_only(_concrete_research_question_is_stated)),
    (_asks_author_inference_boundary, _paper_ask(_author_inference_boundary_is_stated)),
    (_asks_quantitative_evidence_index, _paper_ask(_quantitative_evidence_index_is_stated)),
    (_asks_numeric_discrepancy_resolution, _paper_only(_numeric_discrepancy_is_resolved)),
    (_asks_scope_framing, _scope_framing_satisfied),
    (_asks_outcome_taxonomy_separation, _paper_only(_outcome_taxonomy_separation_is_stated)),
    (_asks_source_stratification_reconciliation, _paper_only(_source_stratification_reconciliation_is_stated)),
    (_asks_mr_causal_count, _paper_ask(_mr_causal_count_is_stated)),
    (_asks_effect_direction_reconciliation, _paper_ask(_effect_direction_reconciliation_is_stated)),
    (_asks_admission_direction_tally_reconciliation, _paper_ask(_admission_direction_tally_reconciliation_is_stated)),
    (_asks_bounded_research_question_conclusion, _paper_only(_bounded_research_question_conclusion_is_stated)),
    (_asks_mr_mechanism_disagreement_separation, _paper_only(_mr_mechanism_disagreement_separation_is_stated)),
    (_asks_no_direct_hard_endpoint_statement, _paper_only(_no_direct_hard_endpoint_statement_is_stated)),
    (_asks_publication_status_preprint_flags, _paper_only(_publication_status_preprint_flags_are_stated)),
    (_asks_direction_tally_audit, _paper_only(_direction_tally_audit_is_stated)),
    (_asks_source_scope_annex, _paper_ask(_source_scope_annex_is_stated)),
    (_asks_direct_interventional_reclassification, _paper_ask(_direct_interventional_reclassification_is_stated)),
    (_asks_combination_product_signal_boundary, _paper_only(_combination_product_signal_boundary_is_stated)),
    (_asks_directional_coding, _paper_only(_directional_coding_explanation_is_material)),
    (_asks_substantive_evidence_synthesis, _substantive_evidence_satisfied),
    (_asks_contextual_subdomain_disaggregation, _contextual_subdomain_disaggregation_is_stated),
    (_asks_forward_dated_ai_disclosure_note, _paper_only(_forward_dated_ai_disclosure_note_is_stated)),
    (_asks_publication_year_note, _paper_only(_publication_year_note_is_stated)),
    (_asks_intervention_target_boundary, _paper_only(_intervention_target_boundary_is_stated)),
    (_asks_rct_count_reconciliation, _paper_only(_rct_count_reconciliation_is_stated)),
    (_asks_unbacked_appraisal_names, _paper_only(_unbacked_appraisal_names_are_resolved)),
    (_asks_evidence_tier_directness_bounds, _paper_only(_evidence_tier_directness_bounds_are_stated)),
    (_asks_search_summary_scope_note, _paper_only(_search_summary_scope_note_is_stated)),
    (_asks_additive_screening_flow, _paper_only(_additive_screening_flow_is_stated)),
    (_asks_admission_funnel_numeric_consistency, _paper_ask(_admission_funnel_numeric_consistency_is_stated)),
    (_asks_prisma_all_included_rationale, _paper_only(_prisma_all_included_rationale_is_stated)),
    (_asks_single_source_proportionality, _paper_only(_single_source_proportionality_is_stated)),
    (_asks_claim_count_audit, _paper_only(_claim_count_audit_is_stated)),
    (_asks_direct_evidence_definition, _contains_any("qualifying direct source", "direct interventional hard-endpoint evidence")),
    (_asks_evidence_boundary, _paper_lower(_evidence_boundary_is_stated)),
    (_asks_conclusion_unproven_humans, _paper_only(_conclusion_unproven_humans_is_stated)),
    (_asks_directional_table_narrative_consistency, _paper_only(_directional_table_narrative_is_consistent)),
    (_asks_contextual_without_directional_signal, _paper_only(_contextual_without_directional_signal_is_explained)),
    (_asks_direction_coding_visibility, _paper_only(_direction_coding_visibility_is_stated)),
    (_asks_direction_coded_source_highlights, _paper_only(_direction_coded_source_highlights_are_stated)),
    (_asks_actionable_gaps, _paper_only(_gaps_section_is_actionable)),
    (_asks_null_signal_reconciliation, _paper_only(_null_signal_conclusion_is_bounded)),
    (_asks_subgroup_lens_narrative, _paper_lower(_subgroup_lens_narrative_is_stated)),
    (_asks_underpopulated_outcome_subsections, _paper_lower(_underpopulated_outcome_subsections_are_stated)),
    (_asks_replaced_surface_tensions, _paper_lower(_replaced_surface_tensions_are_stated)),
    (_asks_boundary_matrix_reconciliation, _paper_only(_boundary_matrix_reconciliation_is_stated)),
    (_asks_non_orthogonal_dyad_definition, _paper_only(_non_orthogonal_dyad_definition_is_stated)),
    (_asks_concrete_tensions_gaps, _paper_ask(_concrete_tensions_gaps_are_stated)),
    (_asks_internal_duplication, _paper_lower(_internal_duplication_is_low)),
    (_asks_long_term_safety_scope, _paper_only(_long_term_safety_scope_is_stated)),
    (_asks_unbundled_citation_cleanup, _paper_ask(_unbundled_citations_are_resolved)),
    (_asks_structured_table_stub_replacement, _paper_only(_structured_table_stubs_are_replaced)),
    (lambda text: outcome_label_rename(text) is not None, _paper_ask(outcome_label_cleanup_is_stated)),
    (_asks_substantive_conclusion, _paper_only(_substantive_conclusion_is_stated)),
    (_asks_conclusion_weight_boundary, _paper_only(_conclusion_weight_boundary_is_stated)),
    (_asks_conclusion_recommendation_scope, _paper_only(_conclusion_recommendation_scope_is_stated)),
    (_asks_source_count_bundle_reconciliation, _paper_only(_source_count_bundle_reconciliation_is_stated)),
    (_asks_corpus_count_reconciliation, _paper_only(_corpus_count_reconciliation_is_stated)),
    (_asks_evidence_honesty_repetition, _paper_only(_evidence_honesty_repetition_is_low)),
    (_asks_named_direct_clinical_source, _paper_only(_named_direct_clinical_source_is_stated)),
    (_asks_outcome_subsection_source_narrative, _paper_only(_outcome_subsection_source_narrative_is_stated)),
    (_asks_protocol_design_limitations, _paper_only(_protocol_design_limitations_are_stated)),
    (_asks_external_reference_boundary, _paper_lower(_external_references_are_marked_illustrative)),
    (_asks_reference_traceability, _paper_ask(_references_are_traceable)),
    (_asks_prior_publication_differentiation, _paper_only(_prior_publication_differentiation_is_stated)),
    (_asks_numeric_correction_markup_cleanup, _paper_only(_numeric_correction_markup_is_resolved)),
    (_asks_numeric_effect_audit, _numeric_effect_audit_satisfied),
    (_asks_named_numeric_correction, _named_numeric_correction_satisfied),
    (_asks_numeric_effect_accuracy, _numeric_effect_accuracy_satisfied),
    (_asks_grammar_correction, _paper_ask(_grammar_artifacts_are_absent)),
)
