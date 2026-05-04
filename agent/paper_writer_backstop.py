"""Fix #55 v2: orchestrator-side section-rerender backstop.

The writer's per-section retry loop (SECTION_RETRY_BUDGET=2, so
3 attempts max) sometimes still produces below-floor Discussion /
Conclusion / Cross-Domain sections, especially on thin corpora.
This backstop runs AFTER all sections render: for each audit-gated
section that came in below its Q-audit floor, attempt ONE more
rerender with an aggressive audit-aware prompt that names the
exact word target. Single retry (4th attempt) — bounds wall time.

Pure helper module: takes the rendered sections + writer context,
returns a possibly-updated sections dict. No I/O beyond the LLM
calls themselves; the caller in render_full_paper handles logging
and disk writes.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import httpx

from agent.llm_client import CallSpec, CostLedger
from agent.paper_writer_helpers import (
    section_word_count as _section_word_count,
)
from agent.synthesis_schemas import (
    ReceiptSummary, SectionName, SynthesisSection,
)


# Audit-gated section floors. Map: section name → minimum words to
# clear the corresponding Q-audit check. Discussion + Cross-Domain
# Synthesis are gated by Q11 / Q12 at 800 words. Conclusion has an
# informal floor (no Q-gate but the writer's SECTION_WORD_FLOORS
# uses 250).
AUDIT_GATED_FLOORS: Mapping[str, int] = {
    "cross_domain_synthesis": 800,  # Q12 audit floor
    "discussion": 800,               # Q11 audit floor
    "conclusion": 200,               # informal floor
}


def build_backstop_prompt(
    base_prompt: str, section_name: str, prev_words: int,
    floor: int,
) -> str:
    """Append a CRITICAL AUDIT REQUIREMENT block to the section's
    base prompt, naming the exact target word count + the audit
    consequence."""
    return (
        base_prompt
        + f"\n\n## CRITICAL AUDIT REQUIREMENT\n\n"
        f"The previous attempt produced ONLY {prev_words} words "
        f"for the {section_name.upper()} section. The Researka "
        f"audit will FAIL the entire paper if this section is "
        f"below {floor} words. You MUST produce at LEAST "
        f"{floor + 100} words of substantive prose. Add more "
        f"paragraphs. Make each paragraph 8-12 sentences. Do NOT "
        f"pad with restated literature; cite once and add new "
        f"analysis. The audit gate is non-negotiable."
    )


async def apply_section_backstop(
    sections: dict[SectionName, SynthesisSection],
    *,
    user_prompt: str,
    section_prompts: Mapping[str, str],
    topic: str,
    accepted: Sequence[ReceiptSummary],
    chain: Sequence[CallSpec],
    client: httpx.AsyncClient | None,
    ledger: CostLedger | None,
    seed: int | None,
    background_lit_entries: Sequence[Any] | None,
    write_anchored_fn,
    write_scoped_fn,
) -> dict[SectionName, SynthesisSection]:
    """Apply the audit-aware backstop. Returns the updated sections
    dict (in-place mutation; same object returned for chaining).

    For each AUDIT_GATED_FLOORS section currently below floor,
    attempts ONE more rerender with the audit-aware prompt. Keeps
    whichever attempt produces more words (never makes the section
    shorter than what the writer's main loop produced)."""
    for sec_name, floor in AUDIT_GATED_FLOORS.items():
        cur = sections.get(sec_name)
        if cur is None:
            continue
        words = _section_word_count(cur)
        if words >= floor:
            continue
        print(
            f"[paper_writer] BACKSTOP: {sec_name} at {words} "
            f"words (floor {floor}); attempting final "
            "audit-aware rerender",
            flush=True,
        )
        backstop_prompt = build_backstop_prompt(
            section_prompts[sec_name], sec_name, words, floor,
        )
        try:
            if sec_name == "cross_domain_synthesis":
                new_section = await write_anchored_fn(
                    name=sec_name,
                    heading="## Cross-Domain Synthesis",
                    system_prompt=backstop_prompt,
                    user_prompt=user_prompt,
                    accepted=accepted, chain=chain, client=client,
                    ledger=ledger, seed=seed,
                    fallback_body=cur.body_md,
                    background_lit_entries=background_lit_entries,
                )
            elif sec_name == "discussion":
                new_section = await write_scoped_fn(
                    name=sec_name, heading="## Discussion",
                    system_prompt=backstop_prompt,
                    user_prompt=user_prompt,
                    topic=topic, accepted=accepted, chain=chain,
                    client=client, ledger=ledger, seed=seed,
                    fallback_body=cur.body_md,
                    background_lit_entries=background_lit_entries,
                )
            elif sec_name == "conclusion":
                new_section = await write_scoped_fn(
                    name=sec_name, heading="## Conclusion",
                    system_prompt=backstop_prompt,
                    user_prompt=user_prompt,
                    topic=topic, accepted=accepted, chain=chain,
                    client=client, ledger=ledger, seed=seed,
                    fallback_body=cur.body_md,
                    background_lit_entries=background_lit_entries,
                )
            else:
                continue
            new_words = _section_word_count(new_section)
            if new_words > words:
                sections[sec_name] = new_section
                print(
                    f"[paper_writer] BACKSTOP: {sec_name} "
                    f"{words} → {new_words} words",
                    flush=True,
                )
            else:
                print(
                    f"[paper_writer] BACKSTOP: {sec_name} "
                    f"rerender did not improve ({words} → "
                    f"{new_words}); keeping original",
                    flush=True,
                )
        except Exception as e:  # pragma: no cover — best-effort
            print(
                f"[paper_writer] BACKSTOP: {sec_name} rerender "
                f"failed ({type(e).__name__}: {e}); keeping "
                "original",
                flush=True,
            )
    return sections


__all__ = [
    "AUDIT_GATED_FLOORS",
    "build_backstop_prompt",
    "apply_section_backstop",
]
