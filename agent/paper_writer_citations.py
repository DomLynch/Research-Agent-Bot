"""Background-literature citation helpers for the paper writer.

Two related concerns isolated here:

  Fix #18a — `_build_background_lit_block`: format the registry
              entries as a writer-facing block so MiMo SEES the
              allowed background citations + the use rule
              (numeric MUST share a sentence with citation_token).

  Fix #20  — `_run_citation_fix_pass`: after MiMo writes a section,
              detect any background numeric used WITHOUT its
              canonical citation in the same sentence, then do ONE
              re-prompt with explicit fix guidance. Closes the loop
              between writer + Stage-2 auto-fixer (which previously
              stripped offending sentences and tanked Q9 density).

Extracted from agent/paper_writer.py to honor the 600 LOC per-file
hard cap. The writer module imports these helpers and threads
`background_lit_entries` into each section render."""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import httpx

from agent.llm_client import CallSpec, CostLedger
from agent.synthesis_schemas import SynthesisSection


def build_background_lit_block(entries: Sequence[Any] | None) -> str:
    """Fix #18a: format the background_literature registry entries as
    a writer-facing block. Each entry exposes its numeric, the
    REQUIRED citation token, and a one-line use rule. Empty when
    no entries provided (caller falls back to corpus-only writing)."""
    if not entries:
        return ""
    lines = [
        "",
        "ALLOWED BACKGROUND CITATIONS (canonical clinical thresholds):",
        "These are pre-vetted background-context numerics. You MAY use",
        "any of these IF AND ONLY IF you include the corresponding",
        "citation_token in the SAME sentence as the numeric. If you",
        "use the numeric without the citation_token, the audit gates",
        "WILL strip the sentence.",
        "",
    ]
    for e in entries:
        lines.append(
            f"  - numeric: {e.numeric!r}\n"
            f"    citation_token: {e.citation_token!r} "
            f"(use exactly this string in the same sentence)\n"
            f"    context: {e.context}"
        )
    return "\n".join(lines)


def check_unsourced_background_uses(
    section_md: str, entries: Sequence[Any] | None,
) -> list[tuple[str, str, str]]:
    """Fix #20: detect background-lit numerics used in `section_md`
    without their canonical citation_token in the SAME sentence.

    Wraps scripts/background_literature.find_unsourced_background_uses
    so the writer can run the same gate the Stage-2 audit runs — but
    BEFORE the auto-fixer strips the offending sentence (which was
    tanking Q9 numeric density). Returns the list of
    (numeric, citation_token, sentence_snippet) tuples; empty = clean."""
    if not entries:
        return []
    import sys
    from pathlib import Path
    sys.path.insert(0, str(
        Path(__file__).resolve().parent.parent / "scripts",
    ))
    import background_literature as _bg  # type: ignore[import-not-found]  # noqa: E402
    registry = {e.key: e for e in entries}
    return _bg.find_unsourced_background_uses(section_md, registry)


def build_citation_fix_prompt(
    base_user_prompt: str,
    issues: list[tuple[str, str, str]],
) -> str:
    """Fix #20: append a load-bearing citation-fix block to the user
    prompt so MiMo retries the section while KEEPING the numeric (so
    Q9 density stays high) AND adding the canonical citation in the
    same sentence (so Stage-2 admits it). Concrete example included
    so MiMo doesn't get clever."""
    fix_lines = [
        "",
        "================================================================",
        "CITATION FIX REQUIRED — your previous attempt used these "
        "background numerics without including the canonical citation",
        "in the SAME sentence:",
        "",
    ]
    for numeric, cite, snippet in issues:
        fix_lines.append(
            f"  - Numeric: {numeric}\n"
            f"    Required citation_token "
            f"(must appear in same sentence): {cite!r}\n"
            f"    You wrote: '...{snippet}...'\n"
        )
    fix_lines.extend([
        "Re-write the section. KEEP the numerics in (do NOT delete them — "
        "the paper needs the density), but EVERY use of these numerics "
        "MUST include the citation_token in the SAME sentence. Example: "
        "'Walk-speed below 0.8 m/s indicates frailty risk "
        "(Studenski 2011).' If you cannot include the citation, drop the "
        "numeric and describe qualitatively instead.",
        "================================================================",
    ])
    return base_user_prompt + "\n" + "\n".join(fix_lines)


async def run_citation_fix_pass(
    section: SynthesisSection | None,
    *,
    base_user_prompt: str,
    system_prompt: str,
    builder_fn,
    background_lit_entries: Sequence[Any] | None,
    chain: Sequence[CallSpec],
    client: httpx.AsyncClient | None,
    ledger: CostLedger | None,
    seed: int | None,
    call_llm_fn,
) -> SynthesisSection | None:
    """Fix #20: One-shot re-prompt to add missing background citations.

    If the section uses background-literature numerics without the
    canonical citation token in the same sentence, do ONE additional
    LLM call with explicit fix instructions. Return the improved
    section if it strictly reduces the issue count; otherwise the
    original. Cap at 1 attempt — runaway re-prompts would explode
    cost; if MiMo still won't comply after 1 fix attempt the Stage-2
    auto-fixer remains the safety net (less density but still safe).

    `call_llm_fn` is injected to keep this module free of paper_writer's
    private LLM helper (avoids a circular import). It must have the
    signature `(*, system_prompt, user_prompt, chain, client, ledger,
    seed) -> dict | None`. `builder_fn(parsed_dict) -> SynthesisSection
    | None` rebuilds the section from a parsed JSON dict."""
    if section is None or not background_lit_entries:
        return section
    issues = check_unsourced_background_uses(
        section.body_md, background_lit_entries,
    )
    if not issues:
        return section
    fix_prompt = build_citation_fix_prompt(base_user_prompt, issues)
    parsed = await call_llm_fn(
        system_prompt=system_prompt, user_prompt=fix_prompt,
        chain=chain, client=client, ledger=ledger, seed=seed,
    )
    if not parsed:
        return section
    new_section = builder_fn(parsed)
    if new_section is None:
        return section
    new_issues = check_unsourced_background_uses(
        new_section.body_md, background_lit_entries,
    )
    # Accept only if strictly improved — defends against the LLM
    # rewriting the section in a way that changes meaning without
    # actually fixing the citation problem.
    if len(new_issues) < len(issues):
        return new_section
    return section


__all__ = [
    "build_background_lit_block",
    "build_citation_fix_prompt",
    "check_unsourced_background_uses",
    "run_citation_fix_pass",
]
