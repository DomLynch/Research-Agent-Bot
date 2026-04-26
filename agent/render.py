"""Markdown rendering: Draft -> publishable .md.

The rendered artifact carries:
  - Title + abstract
  - 5 standard sections
  - Evidence table (ref / role / tier / direct / source / year)
  - Bibliography with hyperlinks
  - Footer with model, prompt version, cost

No reformatting of LLM prose — it ships as the LLM wrote it (already QA-passed).
"""
from __future__ import annotations

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
    # Render any extra sections the LLM added that aren't in the standard set.
    for key, sentences in draft.sections.items():
        if key in SECTION_ORDER:
            continue
        cleaned = [s.strip() for s in sentences if s.strip()]
        if cleaned:
            parts.append(f"## {key.title()}\n\n" + " ".join(cleaned))
    return "\n\n".join(parts)


def _evidence_table(items: list[EvidenceItem]) -> str:
    header = (
        "| Ref | Role | Tier | Design | Direct | Source | Year |\n"
        "|-----|------|------|--------|--------|--------|------|"
    )
    rows = [
        f"| [{it.source.ref}] | {it.role} | {it.tier} | {it.design} | "
        f"{'yes' if it.direct else 'no'} | {it.source.source} | "
        f"{it.source.year if it.source.year else '—'} |"
        for it in items
    ]
    return "## Evidence\n\n" + header + "\n" + "\n".join(rows)


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
        bits.append(f"model={meta['model']}")
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
    parts = [
        f"# {draft.title.strip()}",
        _abstract_block(draft),
        _section_block(draft),
        _evidence_table(draft.bundle),
        _bibliography(draft.bundle),
    ]
    footer = _footer(meta or {})
    if footer:
        parts.append(footer)
    return "\n\n".join(p for p in parts if p)
