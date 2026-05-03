"""Fix #17: writer-prompt hardening — every section system prompt
must carry the NUMERIC_DISCIPLINE_RULE so MiMo doesn't introduce bare
out-of-corpus numerics from training data.

This is the writer-side enforcement of Fix #16's external-context
lane. The audit gates catch violations after the fact; this prompt
change reduces violations at generation time."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agent.paper_writer_prompts import (  # noqa: E402
    ABSTRACT_SYSTEM_PROMPT,
    BACKGROUND_SYSTEM_PROMPT,
    CONCLUSION_SYSTEM_PROMPT,
    CROSS_DOMAIN_SYNTHESIS_SYSTEM_PROMPT,
    DISCUSSION_SYSTEM_PROMPT,
    INTRODUCTION_SYSTEM_PROMPT,
    LIMITATIONS_FULL_SYSTEM_PROMPT,
    NUMERIC_DISCIPLINE_RULE,
    RESULTS_SYSTEM_PROMPT,
)


_ALL_SECTION_PROMPTS = (
    ("ABSTRACT", ABSTRACT_SYSTEM_PROMPT),
    ("INTRODUCTION", INTRODUCTION_SYSTEM_PROMPT),
    ("BACKGROUND", BACKGROUND_SYSTEM_PROMPT),
    ("RESULTS", RESULTS_SYSTEM_PROMPT),
    ("CROSS_DOMAIN_SYNTHESIS", CROSS_DOMAIN_SYNTHESIS_SYSTEM_PROMPT),
    ("DISCUSSION", DISCUSSION_SYSTEM_PROMPT),
    ("LIMITATIONS_FULL", LIMITATIONS_FULL_SYSTEM_PROMPT),
    ("CONCLUSION", CONCLUSION_SYSTEM_PROMPT),
)


def test_every_section_prompt_starts_with_numeric_discipline() -> None:
    """The rule MUST be the FIRST thing the model sees — that's the
    strongest attention slot. If a future refactor moves it down,
    this test fires."""
    for name, prompt in _ALL_SECTION_PROMPTS:
        assert prompt.startswith(NUMERIC_DISCIPLINE_RULE), (
            f"{name}_SYSTEM_PROMPT does not start with "
            "NUMERIC_DISCIPLINE_RULE — Fix #17 protection lost"
        )


def test_numeric_discipline_rule_names_specific_forbidden_examples() -> None:
    """The rule is concrete: it names actual MiMo-hallucination
    patterns from the latest E2E (0.8 m/s, 95% sensitivity, 1500 mg)."""
    assert "0.8 m/s" in NUMERIC_DISCIPLINE_RULE
    assert "1500 mg" in NUMERIC_DISCIPLINE_RULE
    assert "95% sensitivity" in NUMERIC_DISCIPLINE_RULE


def test_numeric_discipline_rule_names_canonical_citation_tokens() -> None:
    """Rule shows MiMo the SHAPE of acceptable citation tokens, with
    real examples from the seeded background_literature.json."""
    # At least one canonical citation example MUST be in the rule
    examples = ("Studenski 2011", "Cesari 2009", "Cruz-Jentoft 2019")
    assert any(c in NUMERIC_DISCIPLINE_RULE for c in examples), (
        "Rule should show at least one real citation token example"
    )


def test_numeric_discipline_rule_describes_qualitative_fallback() -> None:
    """When MiMo can't trace a numeric, it should fall back to
    qualitative description rather than dropping the point."""
    # Word should appear naming the qualitative-only escape hatch
    assert "qualitatively" in NUMERIC_DISCIPLINE_RULE


def test_numeric_discipline_rule_is_self_contained() -> None:
    """The rule should be readable in isolation (the writer sees it
    prepended; if it depends on context elsewhere in the prompt, that
    coupling will silently break)."""
    # Self-contained means: contains its own header, contains its own
    # examples, contains its own escape-hatch description.
    assert "HARD NUMERIC DISCIPLINE" in NUMERIC_DISCIPLINE_RULE
    assert "(a)" in NUMERIC_DISCIPLINE_RULE  # corpus lane
    assert "(b)" in NUMERIC_DISCIPLINE_RULE  # background lane


def test_section_prompts_remain_distinct_after_rule_prepend() -> None:
    """Sanity: prepending the same shared rule must not collapse
    distinct section prompts. After the shared rule, each section
    must still have its unique structural guidance."""
    bodies = [p[len(NUMERIC_DISCIPLINE_RULE):] for _, p in _ALL_SECTION_PROMPTS]
    assert len(set(bodies)) == len(bodies), (
        "Section prompts collapsed to identical bodies after the "
        "rule prepend — likely a refactor regression"
    )


def test_each_section_prompt_still_names_its_section() -> None:
    """After the prepend, each section prompt body must still name
    its target section (Abstract/Introduction/Results/etc.)."""
    section_keywords = {
        "ABSTRACT": "ABSTRACT",
        "INTRODUCTION": "INTRODUCTION",
        "BACKGROUND": "BACKGROUND",
        "RESULTS": "RESULTS",
        "CROSS_DOMAIN_SYNTHESIS": "CROSS-DOMAIN",
        "DISCUSSION": "DISCUSSION",
        "LIMITATIONS_FULL": "LIMITATIONS",
        "CONCLUSION": "CONCLUSION",
    }
    for name, prompt in _ALL_SECTION_PROMPTS:
        kw = section_keywords[name]
        assert kw in prompt.upper(), (
            f"{name} prompt no longer mentions the section keyword "
            f"{kw!r} after Fix #17 prepend"
        )


# ============ Fix #21 follow-up #2: Discussion hedge guidance =========


def test_discussion_prompt_has_explicit_hedge_density_block() -> None:
    """Q10 hedge density check expects ≥4 distinct hedge phrases in
    the Discussion section. The prompt MUST tell MiMo this — without
    explicit guidance, hedges land stochastically (observed range
    2/14 to 7/14 across runs)."""
    assert "HEDGE-DENSITY" in DISCUSSION_SYSTEM_PROMPT
    # Q10 word list at minimum
    for hedge in ("may", "might", "suggests", "appears", "uncertain",
                   "warrants", "limited"):
        assert hedge in DISCUSSION_SYSTEM_PROMPT.lower(), (
            f"DISCUSSION_SYSTEM_PROMPT no longer mentions hedge "
            f"phrase {hedge!r} — Q10 reliability regressed"
        )
    assert "≥4" in DISCUSSION_SYSTEM_PROMPT or "at least 4" in (
        DISCUSSION_SYSTEM_PROMPT.lower()
    )
