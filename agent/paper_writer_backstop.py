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

import asyncio
from collections.abc import Mapping, Sequence
from typing import Any, TYPE_CHECKING, cast

if TYPE_CHECKING:  # pragma: no cover
    import httpx

from agent.deterministic_anchors import (
    build_cross_domain_anchor, build_discussion_anchor,
)
from agent.llm_client import CallSpec, CostLedger
from agent.paper_writer_helpers import (
    section_word_count as _section_word_count,
)
from agent.synthesis_schemas import (
    ReceiptSummary, SectionName, SynthesisSection, TensionMatrix,
)


# Audit/public-surface section floors. Map: section name → minimum words to
# clear the strictest downstream gate. Cross-Domain is 850 because the
# journal-surface gate is stricter than Q12's 800-word audit floor.
AUDIT_GATED_FLOORS: Mapping[str, int] = {
    "cross_domain_synthesis": 850,
    "discussion": 800,               # Q11 audit floor
    "conclusion": 250,
}
BACKSTOP_CALL_TIMEOUT_SEC = 90.0


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
    matrix: TensionMatrix | None = None,
    chain: Sequence[CallSpec],
    client: "httpx.AsyncClient | None",
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
        section_name = cast(SectionName, sec_name)
        cur = sections.get(section_name)
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
                new_section = await asyncio.wait_for(
                    write_anchored_fn(
                        name=sec_name,
                        heading="## Cross-Domain Synthesis",
                        system_prompt=backstop_prompt,
                        user_prompt=user_prompt,
                        accepted=accepted, chain=chain, client=client,
                        ledger=ledger, seed=seed,
                        fallback_body=cur.body_md,
                        background_lit_entries=background_lit_entries,
                    ),
                    timeout=BACKSTOP_CALL_TIMEOUT_SEC,
                )
            elif sec_name == "discussion":
                new_section = await asyncio.wait_for(
                    write_scoped_fn(
                        name=sec_name, heading="## Discussion",
                        system_prompt=backstop_prompt,
                        user_prompt=user_prompt,
                        topic=topic, accepted=accepted, chain=chain,
                        client=client, ledger=ledger, seed=seed,
                        fallback_body=cur.body_md,
                        background_lit_entries=background_lit_entries,
                    ),
                    timeout=BACKSTOP_CALL_TIMEOUT_SEC,
                )
            elif sec_name == "conclusion":
                new_section = await asyncio.wait_for(
                    write_scoped_fn(
                        name=sec_name, heading="## Conclusion",
                        system_prompt=backstop_prompt,
                        user_prompt=user_prompt,
                        topic=topic, accepted=accepted, chain=chain,
                        client=client, ledger=ledger, seed=seed,
                        fallback_body=cur.body_md,
                        background_lit_entries=background_lit_entries,
                    ),
                    timeout=BACKSTOP_CALL_TIMEOUT_SEC,
                )
            else:
                continue
            new_words = _section_word_count(new_section)
            if new_words > words:
                sections[section_name] = new_section
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

    # Final structural fallback (Wave 7, 2026-05-05): if cross_domain
    # / discussion is STILL below floor after the audit-aware
    # rerender, append a deterministic corpus-derived anchor
    # paragraph. Universal across topics, no LLM cost, no
    # fabrication risk — every value traces to receipts/matrix.
    if matrix is not None:
        for sec_name, anchor_fn in (
            ("cross_domain_synthesis", build_cross_domain_anchor),
            ("discussion", build_discussion_anchor),
        ):
            section_name = cast(SectionName, sec_name)
            cur = sections.get(section_name)
            if cur is None:
                continue
            words = _section_word_count(cur)
            floor = AUDIT_GATED_FLOORS.get(sec_name, 800)
            if words >= floor:
                continue
            anchor_md = anchor_fn(accepted, matrix)
            if not anchor_md:
                continue
            new_body = cur.body_md.rstrip() + "\n\n" + anchor_md + "\n"
            sections[section_name] = SynthesisSection(
                name=section_name, body_md=new_body, anchors=cur.anchors,
            )
            new_words = _section_word_count(sections[section_name])
            print(
                f"[paper_writer] BACKSTOP: {sec_name} appended "
                f"deterministic anchor ({words} → {new_words} "
                "words); structural Q11/Q12 backstop",
                flush=True,
            )

    return sections


__all__ = [
    "AUDIT_GATED_FLOORS",
    "BACKSTOP_CALL_TIMEOUT_SEC",
    "build_backstop_prompt",
    "apply_section_backstop",
]
