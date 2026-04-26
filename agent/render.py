"""Markdown rendering: Draft -> publishable .md.

The artifact carries the trust-layer fields requested by reviewers:
  - Eligibility / counts adjudication block (Methods)
  - Evidence table with risk-of-bias column, direct-only filter
  - Excluded sources section with rationale (relevance classifier output
    when available; otherwise category-based label)
  - Adjudication block (when --judge ran)
  - Confidence verdict at the end
  - Footer with model, prompt version, total cost
"""
from __future__ import annotations

from agent.bundle import confidence_verdict, risk_of_bias
from agent.types import Draft, EvidenceItem

SECTION_ORDER = ("introduction", "methods", "findings", "limitations", "conclusion")
SECTION_TITLES = {
    "introduction": "Introduction",
    "methods": "Methods",
    "findings": "Findings",
    "limitations": "Limitations",
    "conclusion": "Conclusion",
}


def _abstract_block(draft: Draft) -> str:
    return " ".join(s.strip() for s in draft.abstract if s.strip())


def _section_block(draft: Draft) -> str:
    parts: list[str] = []
    for key in SECTION_ORDER:
        sentences = [s.strip() for s in draft.sections.get(key, []) if s.strip()]
        if not sentences:
            continue
        parts.append(f"## {SECTION_TITLES[key]}\n\n" + " ".join(sentences))
    for key, sentences in draft.sections.items():
        if key in SECTION_ORDER:
            continue
        cleaned = [s.strip() for s in sentences if s.strip()]
        if cleaned:
            parts.append(f"## {key.title()}\n\n" + " ".join(cleaned))
    return "\n\n".join(parts)


def _eligibility_block(items: list[EvidenceItem], meta: dict[str, object]) -> str:
    """Counts that anchor the audit: how many sources made which cut."""
    n_total = len(items)
    n_direct = sum(1 for it in items if it.direct)
    n_strict = sum(1 for it in items if it.strict)
    n_results = sum(1 for it in items if it.role == "published_results")
    n_pending = sum(
        1 for it in items if it.role in {"registered_pending", "published_protocol"}
    )
    n_review = sum(1 for it in items if it.role == "review")
    relevance = meta.get("relevance") if isinstance(meta, dict) else None
    rel_line = ""
    if isinstance(relevance, dict) and relevance.get("applied"):
        rel_line = (
            f" — relevance pre-filter: {relevance.get('core', 0)} core, "
            f"{relevance.get('background', 0)} background, "
            f"{relevance.get('excluded', 0)} excluded"
        )
    return (
        "## Eligibility\n\n"
        f"- **Total sources**: {n_total}\n"
        f"- **Direct evidence**: {n_direct}\n"
        f"- **Strict (passes year + directness gates)**: {n_strict}\n"
        f"- **Published results**: {n_results}; **registered/protocol**: "
        f"{n_pending}; **reviews**: {n_review}{rel_line}"
    )


def _evidence_table(items: list[EvidenceItem]) -> str:
    """Direct-only evidence table with risk-of-bias column."""
    direct = [it for it in items if it.direct]
    indirect_count = len(items) - len(direct)
    header = (
        "| Ref | Role | Tier | Design | RoB | Source | Year |\n"
        "|-----|------|------|--------|-----|--------|------|"
    )
    if not direct:
        return (
            "## Evidence\n\n"
            f"_No direct evidence in the eligible bundle. {indirect_count} "
            "sources are indirect / off-topic; see Excluded Sources._"
        )
    rows = [
        f"| [{it.source.ref}] | {it.role} | {it.tier} | {it.design} | "
        f"{risk_of_bias(it)} | {it.source.source} | "
        f"{it.source.year if it.source.year else '—'} |"
        for it in direct
    ]
    note = ""
    if indirect_count:
        note = (
            f"\n\n_{indirect_count} additional source"
            f"{'s' if indirect_count != 1 else ''} excluded as indirect / "
            "off-topic — see Excluded Sources below._"
        )
    return "## Evidence\n\n" + header + "\n" + "\n".join(rows) + note


def _excluded_sources_block(
    items: list[EvidenceItem], meta: dict[str, object]
) -> str:
    """List of indirect sources with rationale."""
    indirect = [it for it in items if not it.direct]
    if not indirect:
        return ""
    relevance = meta.get("relevance") if isinstance(meta, dict) else None
    by_ref: dict[int, str] = {}
    if isinstance(relevance, dict):
        raw = relevance.get("by_ref") or {}
        if isinstance(raw, dict):
            for k, v in raw.items():
                try:
                    by_ref[int(k)] = str(v)
                except (TypeError, ValueError):
                    continue
    lines = ["## Excluded Sources", "", "Indirect / off-topic for this question. Background context only — not cited as evidence.", ""]
    for it in indirect:
        rel = by_ref.get(it.source.ref) or _category_label(it)
        lines.append(
            f"- [{it.source.ref}] **{it.source.title[:130]}** "
            f"— *{rel}* (role={it.role}, tier={it.tier}, "
            f"{it.source.source} {it.source.year or '—'})"
        )
    return "\n".join(lines)


def _category_label(item: EvidenceItem) -> str:
    """Short human-readable reason when no LLM classification is available."""
    if item.role == "mechanistic":
        return "preclinical / mechanistic"
    if item.role == "review":
        return "indirect — narrative review"
    if item.role in {"registered_pending", "published_protocol"}:
        return "indirect — pending / off-topic"
    return "indirect — off-topic for question"


def _confidence_block(items: list[EvidenceItem]) -> str:
    label, rationale = confidence_verdict(items)
    return (
        "## Confidence\n\n"
        f"**Verdict: {label} confidence.** {rationale}"
    )


def _qa_failures_block(meta: dict[str, object]) -> str:
    """When QA fails (even after revision), surface every blocking failure
    so the human reviewer can see exactly what the deterministic gates
    flagged. Empty when QA approved."""
    if meta.get("qa_approved", True):
        return ""
    failures = meta.get("qa_failures") or []
    if not isinstance(failures, list):
        return ""
    blocks = [f for f in failures if isinstance(f, dict) and f.get("severity") == "block"]
    if not blocks:
        return ""
    lines = [
        "## QA Failures",
        "",
        f"_{len(blocks)} blocking issue{'s' if len(blocks) != 1 else ''} "
        "remained after one revision attempt._",
        "",
    ]
    for f in blocks:
        code = str(f.get("code", "?"))
        msg = str(f.get("message", ""))[:300]
        lines.append(f"- **`{code}`**: {msg}")
    return "\n".join(lines)


def _adjudication_block(meta: dict[str, object]) -> str:
    """Surface the judge's verdict, or visibly mark a skipped judge."""
    judge = meta.get("judge") if isinstance(meta, dict) else None
    # Visibly mark when judge was skipped — silent skip would hide the
    # second QC layer being missing.
    if not isinstance(judge, dict) or not judge.get("model"):
        return (
            "## Adjudication\n\n"
            "_Judge SKIPPED — `OPENROUTER_API_KEY` not configured. The second "
            "layer of quality control is not active for this run; treat the "
            "draft as QA-approved but not externally adjudicated._"
        )
    parts = [
        "## Adjudication",
        "",
        f"- **Reviewer model**: {judge.get('model')}",
        f"- **Approved**: {judge.get('approved')}",
        f"- **Score**: {judge.get('score', 0)}/10",
    ]
    summary = str(judge.get("summary") or "").strip()
    if summary:
        parts.append(f"- **Summary**: {summary}")
    issues = judge.get("blocking_issues") or []
    if issues:
        parts.append("- **Material issues**:")
        for i in issues[:5]:
            parts.append(f"    - {str(i)[:200]}")
    return "\n".join(parts)


def _bibliography(items: list[EvidenceItem]) -> str:
    lines = ["## Sources", ""]
    for it in items:
        s = it.source
        ident_parts: list[str] = []
        if s.doi:
            ident_parts.append(f"DOI: [{s.doi}](https://doi.org/{s.doi})")
        if s.pmid:
            ident_parts.append(
                f"PMID: [{s.pmid}](https://pubmed.ncbi.nlm.nih.gov/{s.pmid}/)"
            )
        if s.nct:
            ident_parts.append(
                f"NCT: [{s.nct}](https://clinicaltrials.gov/study/{s.nct})"
            )
        venue = f" — *{s.venue}*" if s.venue else ""
        year = f" ({s.year})" if s.year else ""
        idents = ". ".join(ident_parts) + "." if ident_parts else ""
        lines.append(
            f"{s.ref}. **{s.title}**{venue}{year}. "
            f"[link]({s.url}). {idents}".strip()
        )
    return "\n".join(lines)


def _footer(meta: dict[str, object]) -> str:
    bits: list[str] = []
    if meta.get("model"):
        bits.append(f"writer={meta['model']}")
    judge = meta.get("judge") if isinstance(meta, dict) else None
    if isinstance(judge, dict) and judge.get("model"):
        bits.append(f"judge={judge['model']}")
    if meta.get("prompt_version"):
        bits.append(f"prompt={meta['prompt_version']}")
    if meta.get("estimated_cost_usd") is not None:
        bits.append(f"cost=${float(meta['estimated_cost_usd']):.4f}")
    if meta.get("input_tokens"):
        bits.append(f"in={meta['input_tokens']}")
    if meta.get("output_tokens"):
        bits.append(f"out={meta['output_tokens']}")
    return "---\n*" + " · ".join(bits) + "*" if bits else ""


def render(draft: Draft, *, meta: dict[str, object] | None = None) -> str:
    """Render Draft as publishable markdown."""
    meta = meta or {}
    parts: list[str] = [
        f"# {draft.title.strip()}",
        _abstract_block(draft),
        _section_block(draft),
        _eligibility_block(draft.bundle, meta),
        _evidence_table(draft.bundle),
        _excluded_sources_block(draft.bundle, meta),
        _confidence_block(draft.bundle),
        _adjudication_block(meta),
        _qa_failures_block(meta),
        _bibliography(draft.bundle),
    ]
    footer = _footer(meta)
    if footer:
        parts.append(footer)
    return "\n\n".join(p for p in parts if p)
