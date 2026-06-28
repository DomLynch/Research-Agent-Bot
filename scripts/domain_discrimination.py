"""Deterministic domain-discrimination layer for v3 papers.

The goal is not to invent new claims. It selects an evidence schema from the
topic/receipts, surfaces a thesis-shaped interpretation, and exposes obvious
label sanity risks before the manuscript reaches readers.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class DomainSchema:
    key: str
    name: str
    terms: tuple[str, ...]
    axes: tuple[str, ...]
    falsifier: str
    thesis: str
    contribution: str


SCHEMAS: tuple[DomainSchema, ...] = (
    DomainSchema(
        "exercise_cognition",
        "Exercise-Cognition Comparator Framework",
        ("exercise", "training", "aerobic", "zone 2", "cognition", "cognitive"),
        ("Modality", "Cognitive domain", "Comparator", "Population", "Dose", "Follow-up"),
        "active-comparator trials showing the same cognitive effect across domains and doses",
        "Comparator choice and cognitive-domain selection determine whether exercise signals persist beyond inactive-control contrasts.",
        "Separates exercise modality, active comparator, cognitive endpoint, and dose so positive and null findings are not pooled as one intervention class.",
    ),
    DomainSchema(
        "photobiomodulation",
        "Photobiomodulation Dose-Physics Framework",
        ("photobiomodulation", "red light", "pbm", "laser", "wavelength", "fluence", "irradiance"),
        ("Wavelength", "Fluence", "Irradiance", "Target tissue", "Device", "Duration"),
        "protocol-stratified trials showing comparable effects across wavelength, fluence, tissue target, and device class",
        "Photobiomodulation evidence is uninterpretable unless wavelength, fluence, target tissue, and device protocol are treated as intervention-defining variables.",
        "Prevents skin, retinal, transcranial, muscle, and in-vitro light protocols from being collapsed into a single effect direction.",
    ),
    DomainSchema(
        "sasp",
        "SASP Mechanism-Context Framework",
        ("sasp", "senescence-associated secretory", "senomorphic", "senolytic", "secretome"),
        ("Cell type", "SASP factor", "Trigger", "Disease context", "Senomorphic/senolytic role"),
        "human studies linking a defined SASP factor and cell context to a clinical endpoint",
        "SASP should be interpreted as a cell-type and secretome-factor mechanism map before it is framed as a clinical-efficacy intervention.",
        "Separates mechanistic/context sources from clinical intervention claims so secretome biology does not masquerade as direct efficacy evidence.",
    ),
    DomainSchema(
        "telomere_cancer",
        "Telomere-Cancer Tradeoff Framework",
        ("telomere", "telomerase", "alt", "cancer", "tumor", "oncology"),
        ("Cancer risk", "Prognosis", "MR/causality", "Intervention risk", "Telomerase/ALT biology"),
        "direct human evidence showing that telomere modification improves aging-relevant outcomes without increasing cancer risk",
        "Cancer relevance splits into risk, prognosis, causality, and intervention hazard; combining them obscures the central tradeoff.",
        "Separates risk, prognosis, causal inference, and intervention-safety evidence before drawing any geroscience conclusion.",
    ),
    DomainSchema(
        "plasma_exchange",
        "Therapeutic Plasma Exchange Indication Framework",
        ("therapeutic plasma exchange", "plasma exchange", "tpe", "apheresis", "replacement fluid"),
        ("Indication", "Replacement fluid", "Session protocol", "Safety", "Biomarker/longevity relevance"),
        "protocolized geroscience trials separating indication, exchange protocol, replacement fluid, and safety outcomes",
        "TPE has established indication-specific clinical uses, but the geroscience case depends on protocol and biomarker relevance rather than generic TPE literature.",
        "Separates clinical indication, procedure design, safety, and biomarker claims so acute-care evidence is not relabeled as longevity evidence.",
    ),
    DomainSchema(
        "microbiome",
        "Microbiome Context Framework",
        ("microbiome", "probiotic", "gut", "akkermansia", "strain"),
        ("Outcome", "Host state", "Preparation", "Dose", "Strain", "Model"),
        "a direct human trial showing the same effect across host states, preparations, doses, and strains",
        "Microbiome signals require host-state, preparation, strain, dose, and model separation before claims can generalize.",
        "Prevents strain/preparation-specific signals from being read as class-wide microbiome effects.",
    ),
    DomainSchema(
        "geroscience",
        "Endpoint-Sensitivity Framework",
        ("geroscience", "aging", "longevity", "biomarker"),
        ("Mechanism", "Intermediate biomarker", "Function", "Clinical outcome"),
        "a direct clinical study aligning mechanism, biomarker, function, and clinical outcome",
        "The corpus is best interpreted by separating mechanism, biomarker movement, functional outcomes, and hard clinical endpoints.",
        "Makes the directness boundary explicit instead of treating all aging-adjacent evidence as equal.",
    ),
)


def select_domain_schema(topic: str, receipts: list[dict[str, Any]]) -> DomainSchema:
    topic_text = topic.lower()
    receipt_text = " ".join(_receipt_text(r) for r in receipts[:50]).lower()
    ranked = sorted(
        (
            (
                sum(1 for term in schema.terms if _term_hit(term, topic_text)),
                sum(1 for term in schema.terms if _term_hit(term, receipt_text)),
                schema,
            )
            for schema in SCHEMAS
        ),
        key=lambda item: (item[0] * 3 + item[1], item[0], item[1]),
        reverse=True,
    )
    if not ranked:
        return SCHEMAS[-1]
    topic_hits, receipt_hits, schema = ranked[0]
    if topic_hits == 0 and receipt_hits < 2:
        return SCHEMAS[-1]
    return schema if topic_hits or receipt_hits else SCHEMAS[-1]


def build_domain_discrimination(
    topic: str, receipts: list[dict[str, Any]],
) -> dict[str, Any]:
    schema = select_domain_schema(topic, receipts)
    issues = classification_sanity_issues(schema, receipts)
    return {
        "schema": "researka.domain_discrimination.v1",
        "topic": topic,
        "domain_schema": asdict(schema),
        "thesis": schema.thesis,
        "novel_contribution": schema.contribution,
        "classification_sanity": {
            "status": "review" if issues else "passed",
            "issues": issues,
        },
    }


def classification_sanity_issues(
    schema: DomainSchema, receipts: list[dict[str, Any]],
) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    for receipt in receipts:
        text = _receipt_text(receipt).lower()
        source = _source_name(receipt)
        directness = str(receipt.get("directness") or "").lower()
        outcome = str(receipt.get("outcome_class") or receipt.get("endpoint") or "").lower()
        direction = str(receipt.get("effect_direction") or "").lower()
        if directness.startswith("direct") and re.search(r"\b(systematic review|meta-analysis|umbrella review|review)\b", text):
            issues.append(_issue(source, "directness", "review-like source coded direct"))
        if schema.key == "exercise_cognition" and re.search(r"\b(pharmacokinetic|dosing|drug|plasma concentration)\b", outcome):
            issues.append(_issue(source, "outcome", "exercise source assigned drug/dosing outcome label"))
        if schema.key == "plasma_exchange" and "longevity" in outcome and re.search(r"\b(covid|acute|infection|icu)\b", text):
            issues.append(_issue(source, "outcome", "acute-care TPE source assigned longevity label"))
        if direction == "positive" and re.search(r"\bp\s*(?:=|>|>=|greater than)\s*0?\.(?:0[5-9]|[1-9]\d)\b", text):
            issues.append(_issue(source, "direction", "non-significant p-value coded positive"))
    return issues


def apply_domain_surface(
    paper_md: str, topic: str, receipts: list[dict[str, Any]],
) -> tuple[str, dict[str, Any], bool]:
    payload = build_domain_discrimination(topic, receipts)
    if not receipts or "## Domain Interpretation Framework" in paper_md:
        return paper_md, payload, False
    block = render_domain_surface(payload, receipts)
    match = re.search(r"^##\s+Discussion\b", paper_md, flags=re.M)
    if not match:
        match = re.search(r"^##\s+(?:Limitations|Conclusion|References)\b", paper_md, flags=re.M)
    if not match:
        return paper_md.rstrip() + "\n\n" + block + "\n", payload, True
    return paper_md[:match.start()] + block + "\n\n" + paper_md[match.start():], payload, True


def render_domain_surface(payload: dict[str, Any], receipts: list[dict[str, Any]]) -> str:
    schema = payload["domain_schema"]
    issues = payload["classification_sanity"]["issues"]
    lines = [
        "## Domain Interpretation Framework",
        "",
        f"**Schema:** {schema['name']}.",
        f"**Thesis:** {payload['thesis']}",
        f"**Synthesis contribution:** {payload['novel_contribution']}",
        f"**Interpretive dimensions:** {', '.join(schema['axes'])}.",
        "",
        "### Classification Sanity Check",
        "",
    ]
    if issues:
        lines.extend(
            f"- {issue['source']}: {issue['field']} review - {issue['reason']}."
            for issue in issues[:8]
        )
    else:
        lines.append("- No deterministic source-label mismatch was detected.")
    lines.extend(["", "### Public Study Extraction Table", "", *_table_rows(receipts)])
    return "\n".join(lines).rstrip() + "\n"


def _table_rows(receipts: list[dict[str, Any]]) -> list[str]:
    rows = [
        "| Source | Design | Population | Intervention/exposure | Comparator | Endpoint | Follow-up | Effect | Direction | Directness | Risk of bias | Why it matters |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for receipt in receipts[:12]:
        endpoint = _field(receipt, "endpoint", "outcome_class")
        directness = _field(receipt, "directness")
        rows.append("| " + " | ".join(_pipe(cell) for cell in (
            _source_name(receipt),
            _field(receipt, "study_design", "design", "evidence_tier"),
            _field(receipt, "population", "species"),
            _field(receipt, "intervention", "exposure", "intervention_or_exposure"),
            _field(receipt, "comparator", "control"),
            endpoint,
            _field(receipt, "follow_up", "duration"),
            _field(receipt, "effect", "finding", "signal_summary"),
            _field(receipt, "effect_direction"),
            directness,
            _field(receipt, "risk_of_bias", "rob", "quality"),
            f"{directness or 'contextual'} evidence for {endpoint or 'the mapped endpoint'}",
        )) + " |")
    return rows


def _issue(source: str, field: str, reason: str) -> dict[str, str]:
    return {"source": source, "field": field, "reason": reason}


def _receipt_text(receipt: dict[str, Any]) -> str:
    keys = (
        "title", "citation_token", "receipt_id", "paper_id", "study_design",
        "design", "outcome_class", "endpoint", "population", "intervention",
        "exposure", "effect", "finding", "effect_direction", "directness",
    )
    return " ".join(str(receipt.get(key) or "") for key in keys)


def _term_hit(term: str, haystack: str) -> bool:
    return re.search(rf"\b{re.escape(term)}\b", haystack) is not None if len(term) <= 3 else term in haystack


def _source_name(receipt: dict[str, Any]) -> str:
    return _field(receipt, "citation_token", "receipt_id", "title", "paper_id") or "source"


def _field(receipt: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = str(receipt.get(key) or "").strip()
        if value:
            return value
    return ""


def _pipe(text: str) -> str:
    text = re.sub(r"\s+", " ", str(text)).strip()
    return text.replace("|", "/")[:120] or "-"
