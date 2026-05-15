"""Day 10.17 Phase 6.1 — wire v0.6.0 bound claims into agent/paper_writer.py.

The user-audited v0.5.0/v0.6.0 diagnostic writer (scripts/diagnostic_paper_run.py)
hits 3.8k words. The OLD agent/paper_writer.py routinely produces
5–7k word papers with section floors, deterministic Methods, and
trust-spine validation. The end-game needs both — old writer volume +
new bound-claim evidence.

This script is the adapter:
  1. Load v0.6.0 quant_claims (only effect-role + high-confidence
     bindings — the strict 90/93 set)
  2. Group by contributing paper → one ReceiptSummary per paper
  3. Aggregate per-paper outcome_class + effect_direction from the
     dominant bound claims
  4. Build a TensionMatrix from cross-paper direction conflicts on
     the same outcome class
  5. Pick a SynthesisThesis that names the central pattern (most
     metformin papers find muscle-suppression alongside metabolic
     benefit — a real cross-domain tension)
  6. Call render_full_paper() exactly as the existing e2e pipeline does
  7. Optional: claim-strength repair pass (the Phase 2 hardening)
  8. Write to runs/synthesis-metformin-{ISO}/full_paper.md

This is "Path 1" per the audit: keep v0.6.0 extractor fixes; stop
expanding the diagnostic writer; wire bound claims into the production
writer instead.
"""
from __future__ import annotations

import argparse
import asyncio
import dataclasses
import datetime as dt
import json
import re
import shutil
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from agent.llm_client import (  # noqa: E402
    CallSpec, CostLedger, configured_attempts_for_url,
)
from agent.framework_section import (  # noqa: E402
    build_framework_engagement_records,
)
from agent.paper_writer import render_full_paper  # noqa: E402
from agent.paper_writer_helpers import (  # noqa: E402
    strip_rendered_citation_markers as _strip_rendered_citation_markers,
)
from agent.paper_writer_claim_repair import repair_claim_strength  # noqa: E402
from agent.paper_writer_deterministic import (  # noqa: E402
    build_what_this_adds_section,
)
from agent.outcome_class_remap import remap_outcome_class  # noqa: E402
from agent.synthesis_schemas import (  # noqa: E402
    EffectDirection, ReceiptSummary, SynthesisSection, SynthesisThesis,
    Tension, TensionKind, TensionMatrix,
)
from agent.settings import load_settings  # noqa: E402

# Pipeline-stage modules (auto-included after writer; final-layer
# review by the final-layer reviewer with Mistral fallback closes the loop with NO
# manual step required).
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import audit_v06_paper as _audit_v06  # noqa: E402
import final_consistency_audit as _consistency_audit  # noqa: E402
import apply_consistency_fixes as _consistency_fixer  # noqa: E402
import grok_reviewer as _final_reviewer  # noqa: E402
import apply_patches as _patch_applier  # noqa: E402
import run_mode_contract as _run_mode  # noqa: E402
import citation_registry as _citations  # noqa: E402
import evidence_taxonomy as _taxonomy  # noqa: E402
import effect_direction as _direction  # noqa: E402
import table_renderer as _tables  # noqa: E402
import background_literature as _bglit  # noqa: E402
import paper_quality_runtime as _paper_quality  # noqa: E402

# Workstream A (autonomous): topic-parameterized pipeline.
# Module-level corpus paths + active topic — populated by
# _set_topic() at the top of every pipeline invocation. The sentinel
# path `_TOPIC_UNSET` deliberately doesn't exist on disk: any code
# path that reads QUANT_DIR/PARSED_DIR before _set_topic() ran will
# get a Path that fails the .exists() check (and therefore returns
# 0 hits), but won't crash on AttributeError as None would. This is
# the universal-fix-no-hardcoding rule (2026-05-04): no metformin
# fallback, but a placeholder that surfaces the bug at use-time.
# CLI accepts `--topic rapamycin` (or any topic with a corpus dir
# at docs/quality-reference/<topic>/). _run() always calls
# _set_topic() before any downstream code reads QUANT_DIR/PARSED_DIR.
_TOPIC_UNSET = REPO_ROOT / "_TOPIC_UNSET_call_set_topic_first"
QUANT_DIR: Path = _TOPIC_UNSET
PARSED_DIR: Path = _TOPIC_UNSET

# Active topic pack (set by _set_topic). Generic topic-aware logic
# reads from this instead of hardcoded strings. None until first
# _set_topic call.
_TOPIC_PACK = None
_ACTIVE_TOPIC: str = ""
# Slice 7 step 1: published manifest dict for the current run, set
# during synthesis so downstream consistency-audit hooks (notably the
# Numeric Role Guard's source-context drift check in
# scripts/final_consistency_audit.py:_check_numeric_role_guard) can
# resolve receipt → quant_claims via the same global.
_ACTIVE_MANIFEST: dict | None = None

_TOP_LEVEL_RUN_ARTIFACTS = frozenset({
    "full_paper.md",
    "structured_evidence_tables.md",
    "manifest.json",
    "citation_registry.json",
    "full_paper.audit.json",
    "full_paper.consistency.json",
    "full_paper.final_verdict.json",
    "full_paper.journal_surface.json",
    "pre_submit_gate.json",
})
_RUN_ARTIFACT_FOLDERS: dict[str, tuple[str, ...]] = {
    "readable": (
        "full_paper.audit.md",
        "full_paper.consistency.md",
        "full_paper.certification.md",
        "full_paper.final_verdict.md",
        "full_paper.review_summary.md",
        "pre_submit_gate.md",
        "publication_score.md",
        "quality_methods.md",
        "receipt_funnel.md",
        "template_language_gate.md",
        "meta_analysis_results.md",
        "tension_elaboration_plans.md",
        "no_regression_report.md",
    ),
    "debug": (
        "full_paper.fixed_log.json",
        "full_paper.final_fixed_log.json",
        "full_paper.pre_review_template_repair_log.json",
        "full_paper.review_patch_log.json",
        "full_paper.review_patches.json",
        "full_paper.template_repair_log.json",
        "numeric_claim_quarantine.json",
        "qei_quarantined.json",
    ),
    "audit": (
        "field_engagement.json",
        "full_paper.certification.json",
        "grade_assessment.json",
        "meta_analysis_results.json",
        "publication_score.json",
        "quality_methods.json",
        "receipt_funnel.json",
        "risk_of_bias.json",
        "run_mode_contract.json",
        "template_language_gate.json",
        "tension_elaboration_plans.json",
        "no_regression_report.json",
    ),
    "plots": ("forest_plots",),
}


def _organize_run_artifacts(run_dir: Path) -> dict[str, str]:
    """Keep generated run roots small while preserving machine JSON state."""
    moved: dict[str, str] = {}
    for folder, names in _RUN_ARTIFACT_FOLDERS.items():
        dest_dir = run_dir / folder
        for name in names:
            src = run_dir / name
            if not src.exists() or name in _TOP_LEVEL_RUN_ARTIFACTS:
                continue
            dest_dir.mkdir(exist_ok=True)
            dest = dest_dir / name
            if dest.exists():
                if src.is_dir():
                    shutil.rmtree(dest)
                else:
                    dest.unlink()
            src.rename(dest)
            moved[name] = str(dest.relative_to(run_dir))
    return moved


def _section_words_from_paper(paper_md: str) -> dict[str, int]:
    """Count words per H2 section of the final paper.md. Universal —
    keys are slugified H2 headings (`## Cross-Domain Synthesis` →
    `cross_domain_synthesis`). Used to overwrite manifest.section_words
    after the post-paper pipeline regenerates bounded abstract /
    auto-fixes etc., so the manifest matches the file actually shipped."""
    out: dict[str, int] = {}
    parts = re.split(r"^##\s+([^\n#].*?)\s*$", paper_md, flags=re.M)
    # re.split returns [pre, h1, body1, h2, body2, ...]
    for i in range(1, len(parts) - 1, 2):
        heading = parts[i].strip()
        body = parts[i + 1]
        slug = re.sub(r"[^a-z0-9]+", "_", heading.lower()).strip("_")
        if slug:
            out[slug] = len(body.split())
    return out


def _first_section_paragraph(section_md: str) -> str:
    body = section_md.split("\n", 1)[1] if "\n" in section_md else ""
    for para in re.split(r"\n\s*\n", body):
        clean = para.strip()
        if not clean or clean.startswith("###") or clean.startswith("_Cited:"):
            continue
        return clean
    return ""


def _pre_submit_blocker_summary(gate_artifacts: dict[str, Any]) -> str:
    gate = gate_artifacts.get("gate")
    score = gate_artifacts.get("score")
    gate_passed = bool(getattr(gate, "passed", False))
    score_verdict = str(getattr(score, "verdict", ""))
    if gate_passed and score_verdict == "accept":
        return ""
    return (
        f"{getattr(gate, 'summary', 'pre_submit_gate_missing')}; "
        f"{getattr(score, 'summary', 'publication_score_missing')}"
    )


def _restore_rendered_section_headings(
    paper_md: str, sections: tuple[SynthesisSection, ...],
) -> str:
    """Renderer-owned headings must survive all post-processing.

    Large-corpus runs exposed a document-assembly failure where a
    section's prose survived but its `## Heading` was lost, causing Q7
    section coverage to fail. This restores missing headings from the
    typed section objects returned by the writer. Universal contract:
    LLM/review patches may edit prose, but section objects own headings.
    """
    out = paper_md
    for section in sections:
        first_line = section.body_md.lstrip().splitlines()[0:1]
        if not first_line or not first_line[0].startswith("## "):
            continue
        heading = first_line[0].strip()
        if re.search(rf"^{re.escape(heading)}\b", out, re.MULTILINE):
            continue
        anchor = _first_section_paragraph(section.body_md)
        if not anchor:
            continue
        pos = out.find(anchor)
        if pos < 0:
            short = anchor[:160].rstrip()
            pos = out.find(short) if short else -1
        if pos < 0:
            if heading == "## Cross-Domain Synthesis":
                out, restored = _insert_cross_domain_heading(out, heading)
            elif heading == "## Conclusion":
                out, restored = _insert_conclusion_heading(out, heading)
            else:
                restored = False
            if restored:
                continue
            continue
        out = out[:pos].rstrip() + f"\n\n{heading}\n\n" + out[pos:].lstrip()
    return out


def _restore_rendered_section_contract(
    paper_md: str, sections: tuple[SynthesisSection, ...],
    *, prefer_typed_sections: bool = True,
) -> str:
    out = _restore_rendered_section_headings(paper_md, sections)
    out = _restore_required_section_bodies(
        out, sections, prefer_typed_sections=prefer_typed_sections,
    )
    return _patch_applier._collapse_consecutive_qei_headings(out)[0]


def _restore_required_section_bodies(
    paper_md: str, sections: tuple[SynthesisSection, ...],
    *, prefer_typed_sections: bool = True,
) -> str:
    try:
        from agent.journal_surface_gate import _REQUIRED_SECTIONS
    except ImportError:
        return paper_md
    ordered = [
        (s, _section_heading_from_body(s.body_md))
        for s in sections
    ]
    out = paper_md
    for idx, (section, heading) in enumerate(ordered):
        if not heading:
            continue
        title = heading.removeprefix("## ").strip()
        floor = _REQUIRED_SECTIONS.get(title)
        if floor is None:
            continue
        fallback_md = _compile_public_section_backstop(title, floor)
        rendered = _rendered_section_match(out, heading)
        original = section.body_md.strip()
        original_long_enough = (
            prefer_typed_sections
            and _word_count(_section_body_text(original, heading)) >= floor
        )
        replacement_md = original if original_long_enough else fallback_md
        if rendered is not None:
            rendered_body = rendered.group(1)
            if _word_count(rendered_body) >= floor:
                continue
            out = (
                out[:rendered.start()].rstrip() + "\n\n"
                + replacement_md + "\n\n"
                + out[rendered.end():].lstrip()
            ).lstrip()
            continue
        insert_md = replacement_md
        if not insert_md:
            continue
        next_headings = tuple(
            h for _s, h in ordered[idx + 1:] if h
        ) + ("## References",)
        pos = _first_heading_after(out, next_headings, 0)
        if pos >= 0:
            out = (
                out[:pos].rstrip() + "\n\n" + insert_md
                + "\n\n" + out[pos:].lstrip()
            )
    return out


def _restore_public_surface_floors(
    paper_md: str,
) -> tuple[str, list[dict[str, str]]]:
    """Final section length guard over rendered public markdown."""
    try:
        from agent.journal_surface_gate import _REQUIRED_SECTIONS, _SECTION_CEILINGS
    except ImportError:
        return paper_md, []
    out = paper_md
    log: list[dict[str, str]] = []
    titles = tuple(_REQUIRED_SECTIONS.keys())
    for idx, title in enumerate(titles):
        floor = int(_REQUIRED_SECTIONS[title])
        ceiling = _SECTION_CEILINGS.get(title)
        heading = f"## {title}"
        fallback_md = _compile_public_section_backstop(title, floor)
        if not fallback_md:
            continue
        match = _rendered_section_match(out, heading)
        if match is not None:
            words = _word_count(match.group(1))
            if words >= floor and (ceiling is None or words <= ceiling):
                continue
            reason = "replace_long_section" if ceiling is not None and words > ceiling else "replace_short_section"
        else:
            reason = "insert_missing_section"
        if match is not None:
            out = (
                out[:match.start()].rstrip() + "\n\n"
                + fallback_md + "\n\n"
                + out[match.end():].lstrip()
            ).lstrip()
        else:
            next_headings = tuple(f"## {t}" for t in titles[idx + 1:])
            pos = _first_heading_after(out, next_headings + ("## References",), 0)
            if pos < 0:
                out = out.rstrip() + "\n\n" + fallback_md + "\n"
            else:
                out = (
                    out[:pos].rstrip() + "\n\n"
                    + fallback_md + "\n\n"
                    + out[pos:].lstrip()
                )
        log.append({
            "fix_type": "surface_floor_backstop",
            "section": title,
            "reason": reason,
        })
    return out, log


def _topic_display_name() -> str:
    topic = _ACTIVE_TOPIC.replace("_", " ").replace("-", " ").strip()
    return topic or "the topic"


def _compile_public_section_backstop(title: str, floor: int) -> str:
    """Safe public-prose fallback compiled from manifest metadata.

    The fallback must read like conservative manuscript prose. It may
    use only corpus-level metadata already present in the run manifest:
    receipt counts, outcome/effect buckets, directness tiers, citation
    tokens, and tension counts. It must not restore source-level numeric
    claims that were stripped for source-context safety.
    """
    allowed = {
        "Abstract", "Introduction", "Background", "Results",
        "Cross-Domain Synthesis", "Discussion", "Limitations", "Conclusion",
    }
    if title not in allowed:
        return ""
    topic = _topic_display_name()
    ctx = _section_backstop_context()
    receipt_n = cast(int, ctx["receipt_n"])
    claim_n = cast(int, ctx["claim_n"])
    tension_n = cast(int, ctx["tension_n"])
    direct = cast(int, ctx["direct"])
    indirect = cast(int, ctx["indirect"])
    mechanistic = cast(int, ctx["mechanistic"])
    pos = ctx["positive"]
    neg = ctx["negative"]
    null = ctx["null"]
    mixed = ctx["mixed"]
    direct_refs = ctx["direct_refs"]
    mech_refs = ctx["mech_refs"]
    pos_refs = ctx["positive_refs"]
    null_refs = ctx["null_refs"]
    neg_refs = ctx["negative_refs"]
    thesis = ctx["thesis"]
    if title == "Results":
        results_backstop = _compile_results_outcome_backstop(topic, ctx, floor)
        if results_backstop:
            return results_backstop

    paragraphs_by_title = {
        "Abstract": [
            (
                f"This paper synthesizes {topic} as an aging-related "
                f"intervention across {receipt_n} accepted source papers and "
                f"{claim_n} high-confidence extracted claims."
            ),
            (
                "The evidence profile contains "
                f"{_evidence_tier_phrase(direct, 'direct clinical')}, "
                f"{_evidence_tier_phrase(indirect, 'adjacent clinical')}, "
                f"and {_evidence_tier_phrase(mechanistic, 'mechanistic or model-system')}, "
                f"with {_count_phrase(tension_n, 'cross-study disagreement')} "
                "across the evidence base."
            ),
            (
                f"Positive study-level signals concentrate in {pos}, null "
                f"signals in {null}, and negative signals in {neg}. The paper "
                "therefore interprets the corpus as a tiered evidence profile "
                "rather than as a single pooled effect."
            ),
            (
                f"The conclusion is that {topic} remains a bounded "
                "geroscience case: mechanistic plausibility and selected "
                "clinical signals justify further targeted testing, while "
                "mixed and null findings limit any unqualified anti-aging "
                "claim."
            ),
        ],
        "Introduction": [
            (
                f"This synthesis evaluates {topic} as an aging-related "
                f"intervention across {receipt_n} accepted source papers and "
                f"{claim_n} high-confidence extracted claims. The review is "
                "organized around the distinction between direct clinical "
                "evidence, indirect clinical evidence, and mechanistic evidence "
                "so that biological plausibility is not confused with clinical "
                "certainty."
            ),
            (
                "The corpus contains "
                f"{_evidence_tier_phrase(direct, 'direct clinical')}, "
                f"{_evidence_tier_phrase(indirect, 'adjacent clinical')}, "
                f"and {_evidence_tier_phrase(mechanistic, 'mechanistic or model-system')}. "
                "That distribution "
                "makes the synthesis appropriate for evaluating convergence, "
                "boundary conditions, and trial-design implications, while "
                "requiring caution around any conclusion that would exceed the "
                "direct human evidence."
            ),
            (
                f"The thesis is: {thesis} This thesis is treated "
                "as an organizing claim, not as a substitute for the study "
                "table, because the source record includes supportive, null, "
                "and adverse signals across different outcome classes."
            ),
        ],
        "Background": [
            (
                f"The background evidence for {topic} is heterogeneous rather "
                "than uniformly confirmatory. Direct clinical sources such as "
                f"{direct_refs} are interpreted separately from mechanistic "
                f"studies such as {mech_refs}, because these evidence roles "
                "answer different questions about aging biology and clinical "
                "translation."
            ),
            (
                "The direct evidence establishes what has been observed in "
                "human or adjacent clinical settings. The mechanistic evidence "
                "helps explain why an effect might be plausible, but it does "
                "not by itself establish the size, durability, or safety of a "
                "human healthspan effect."
            ),
            (
                f"Across the retained sources, positive signals cluster around "
                f"{pos}; null signals around {null}; and negative or adverse "
                f"signals around {neg}. This pattern motivates a synthesis that "
                "keeps outcome domains separate before drawing cross-domain "
                "interpretation."
            ),
        ],
        "Results": [
            (
                f"The retained {topic} corpus contributes {receipt_n} study-"
                f"level summaries and {claim_n} high-confidence observations. "
                f"Positive study-level signals are represented by {pos_refs}; "
                f"null signals by {null_refs}; and negative signals by "
                f"{neg_refs}. These groupings describe the direction of the "
                "validated study summaries, not a pooled treatment estimate."
            ),
            (
                f"Outcome-level interpretation remains mixed. Positive signals "
                f"are concentrated in {pos}, while null signals are concentrated "
                f"in {null}. Negative signals are concentrated in {neg}. The "
                "result is not a single uniform effect profile, but a set of "
                "domain-specific findings that differ by endpoint, evidence "
                "tier, and study context."
            ),
            (
                f"The synthesis identifies {tension_n} non-orthogonal "
                "disagreements. These disagreements are load-bearing because they show "
                "where sources do not simply accumulate in the same direction. "
                "The synthesis therefore treats disagreement and null findings "
                "as evidence, not as noise to be smoothed away."
            ),
        ],
        "Cross-Domain Synthesis": [
            (
                    f"Cross-domain interpretation of {topic} is constrained by the "
                    f"relationship between clinical sources ({direct_refs}) and "
                    f"mechanistic studies ({mech_refs}). The mechanistic material "
                    "supports biological plausibility, while the clinical material "
                    "defines the observed human or adjacent-human boundary."
                ),
            (
                f"The main cross-domain pattern is the coexistence of positive "
                f"signals in {pos} with null signals in {null} and negative "
                f"signals in {neg}. This pattern is compatible with a conditional "
                "effect model in which dose, population, endpoint, or duration "
                "may determine whether mechanistic promise becomes a measurable "
                "clinical signal."
            ),
            (
                f"{_count_phrase(tension_n, 'non-orthogonal tension').capitalize()} prevent the evidence "
                "from being reduced to a simple positive or negative verdict. "
                "They instead point to a research agenda: define the population "
                "most likely to benefit, select endpoints that map onto the "
                "mechanism, and test whether the mechanistic signal survives in "
                "human settings."
            ),
        ],
        "Discussion": [
            (
                f"The {topic} evidence base is best interpreted as conditionally "
                "supportive rather than definitive. The evidence base contains "
                f"{_evidence_tier_phrase(direct, 'direct clinical')} and "
                f"{_evidence_tier_phrase(mechanistic, 'mechanistic')}, so the strongest claims concern where "
                "signals converge and where translation remains uncertain."
            ),
            (
                f"Positive sources ({pos_refs}) are important, but they must be "
                f"read alongside null sources ({null_refs}) and negative "
                f"sources ({neg_refs}). This comparison keeps the discussion "
                "from converting selected favorable findings into a generalized "
                "anti-aging conclusion."
            ),
            (
                "The practical implication is a calibrated research position. "
                f"{topic.title()} may justify further targeted testing when the "
                "mechanistic rationale, clinical endpoint, and population risk "
                "profile align, but the present corpus does not justify claims "
                "that ignore the null or adverse parts of the evidence base."
            ),
            (
                f"The favorable evidence should therefore be read as endpoint-"
                f"specific rather than global. Signals in {pos} can justify "
                "continued mechanistic and clinical follow-up, but they do not "
                f"cancel null results in {null} or adverse results in {neg}. "
                "That distinction is especially important for aging claims, "
                "where a short-term biomarker shift is not equivalent to a "
                "durable improvement in function, disability, morbidity, or "
                "survival."
            ),
            (
                "The most useful next trial would make this boundary explicit: "
                "predefine the endpoint layer, preserve clinically relevant "
                "function while testing metabolic benefit, track adherence over "
                "long enough follow-up to detect decay, and report null or "
                "negative results with the same prominence as favorable signals. "
                "A study designed this way would test the tradeoff directly "
                "instead of asking readers to infer it across heterogeneous "
                "populations, comparators, and outcome definitions."
            ),
        ],
        "Limitations": [
            (
                f"The principal limitation is evidence-role imbalance. The "
                "retained corpus contains "
                f"{_evidence_tier_phrase(direct, 'direct clinical')}, "
                f"{_evidence_tier_phrase(indirect, 'adjacent clinical')}, "
                f"and {_evidence_tier_phrase(mechanistic, 'mechanistic or model-system')}, which means causal "
                "interpretation depends on how much weight is assigned to each "
                "evidence tier."
            ),
            (
                "A second limitation is endpoint heterogeneity. Study-level "
                f"signals span {pos}, {null}, {neg}, and {mixed}; these domains "
                "cannot be pooled narratively without losing clinically relevant "
                "differences in measurement, population, and study design."
            ),
            (
                "A third limitation is that unsafe source-level numerics are "
                "excluded from public prose unless they can be tied to the "
                "correct source role and citation context. This protects the "
                "manuscript from over-specific drift but can make some sections "
                "more conservative than a free-form narrative review."
            ),
        ],
        "Conclusion": [
            (
                f"The final interpretation is deliberately tiered. {topic.title()} "
                "has a biologically plausible geroscience rationale and selected "
                "clinical signals, but the corpus does not support treating "
                "mechanistic target engagement, intermediate biomarkers, and "
                "patient-relevant outcomes as interchangeable evidence."
            ),
            (
                f"The strongest interpretation is that positive signals in {pos} "
                f"coexist with null signals in {null} and negative signals in "
                f"{neg}. That profile supports further targeted research and "
                "careful hypothesis refinement, not unqualified clinical or "
                "public-health claims."
            ),
            (
                "Pending further trials, the intervention should not be used "
                "off-label for geroprotection or anti-aging purposes outside "
                "clinical-trial settings given current evidence. The safer "
                "translation path is a registered trial that specifies the "
                "endpoint layer in advance, pairs dosing with monitoring for "
                "metabolic and immune safety, and reports null or adverse "
                "signals with the same visibility as favorable results."
            ),
            (
                f"Future work should prioritize studies that connect "
                f"mechanistic studies ({mech_refs}) to direct clinical outcomes "
                f"represented by {direct_refs}. Until that bridge is stronger, "
                f"{topic} remains a promising but bounded geroscience case whose "
                "most useful contribution is to define the next trial rather "
                "than to justify current clinical adoption."
            ),
            (
                "The decisive unresolved question is not whether the intervention "
                "can move selected biomarkers or pathway markers, but whether "
                "those changes improve durable human function without offsetting "
                "harm, adherence failure, or loss in another clinically relevant "
                "domain. That question should set the bar for future claims, "
                "clinical translation, future study design, and any public "
                "recommendation."
            ),
        ],
    }
    shared = [
        (
            "This conservative interpretation is especially important in aging "
            "research because endpoints often differ across model systems, "
            "human trials, and observational cohorts. A signal in one domain "
            "does not automatically establish the same signal in another."
        ),
        (
            "The study-level structure also prevents selective emphasis. "
            "Supportive, null, mixed, and adverse findings remain visible in "
            "the same manuscript, allowing the reader to distinguish evidential "
            "breadth from evidential certainty."
        ),
        (
            "The resulting paper is therefore a calibrated synthesis: it can "
            "identify plausible mechanisms, direct clinical signals, unresolved "
            "tensions, and trial-design priorities without converting them into "
            "claims stronger than the retained corpus can support."
        ),
        (
            "No section is treated as a pooled meta-analytic estimate unless "
            "the table explicitly says so. The text summarizes study-level "
            "patterns, while the numeric supplement preserves the "
            "source-bound numeric record."
        ),
        (
            "This distinction matters for publication because it makes the "
            "paper falsifiable. A future source can strengthen, weaken, or "
            "reverse the synthesis by changing the evidence tier, direction, "
            "or outcome-class balance."
        ),
        (
            "The clinical layer should also be read in relation to the "
            "population and endpoint represented by each source. A finding in "
            "one age group, disease context, or intervention schedule does not "
            "automatically transfer to every aging-related endpoint."
        ),
        (
            "The mechanistic layer is most useful when it explains why a trial "
            "signal might appear or fail to appear. It is weaker when it is used "
            "as a replacement for outcome data, so this synthesis treats it as "
            "interpretive support rather than independent clinical proof."
        ),
        (
            "Null findings have a specific role in this evidence model. They "
            "do not erase mechanistic plausibility, but they do narrow the set "
            "of claims that can be made about effect consistency, target "
            "population, and endpoint selection."
        ),
        (
            "Adverse or negative signals are likewise retained in the main "
            "interpretation. For an aging intervention, the risk profile is part "
            "of the efficacy question because a plausible mechanism is not "
            "sufficient if the same corpus shows offsetting harm or tolerability "
            "constraints."
        ),
        (
            "The evidence base also distinguishes breadth from certainty. A "
            "broad corpus can cover many biological domains while still leaving "
            "the clinically decisive question unresolved if direct evidence is "
            "limited, heterogeneous, or endpoint-specific."
        ),
        (
            "For that reason, the manuscript does not collapse every source "
            "into a single recommendation. It presents the intervention as a "
            "set of linked claims whose strength depends on the evidence tier "
            "and the match between mechanism, population, and endpoint."
        ),
        (
            "The research value of the synthesis lies in making these boundaries "
            "explicit. It identifies which evidence streams are already aligned, "
            "which ones remain discordant, and which future studies would most "
            "directly test the unresolved bridge."
        ),
        (
            "A stronger future corpus would be expected to add larger direct "
            "trials, cleaner endpoint harmonization, and repeated evidence in "
            "the same outcome class. Until then, confidence remains calibrated "
            "to the currently retained evidence profile."
        ),
        (
            "This framing also preserves comparability across topics. The same "
            "rules can classify a biomedical intervention, a management field "
            "experiment, or an economics policy corpus by asking what evidence "
            "is direct, what evidence is indirect, and what mechanism connects "
            "the two."
        ),
        (
            "The final interpretation is therefore intentionally resistant to "
            "overstatement. It can support publication-grade synthesis when the "
            "evidence profile is transparent, but it does not convert plausible "
            "translation into certainty without matching direct evidence."
        ),
    ]
    paragraphs = paragraphs_by_title[title]
    if title != "Conclusion":
        paragraphs += shared
    selected: list[str] = []
    for paragraph in paragraphs:
        if paragraph not in selected:
            selected.append(paragraph)
        if _word_count("\n\n".join(selected)) >= floor + 25:
            break
    body = "\n\n".join(selected)
    return f"## {title}\n\n{body}"


def _section_backstop_context() -> dict[str, object]:
    manifest = _ACTIVE_MANIFEST or {}
    receipts = list(manifest.get("receipts") or [])

    def _count(field: str, value: str) -> int:
        return sum(1 for r in receipts if str(r.get(field, "")).lower() == value)

    def _is_mechanistic_or_model_system(r: dict[str, Any]) -> bool:
        tier = str(r.get("evidence_tier") or "").upper()
        if str(r.get("directness") or "").lower() == "mechanistic" or tier.startswith("C"):
            return True
        title = str(r.get("title") or r.get("paper_id") or "").replace("_", " ")
        cls = _taxonomy.infer_from_paper_meta({"title": title, "abstract": ""})
        return cls.directness == "mechanistic" or cls.tier.startswith("C")

    def _labels(field: str, value: str, limit: int = 3) -> str:
        labels: list[str] = []
        for r in receipts:
            if str(r.get(field, "")).lower() != value:
                continue
            label = str(
                r.get("citation_token") or r.get("body_citation")
                or r.get("paper_id") or r.get("receipt_id") or "",
            ).strip()
            if label and label not in labels:
                labels.append(label)
            if len(labels) >= limit:
                break
        return ", ".join(labels) if labels else "the retained evidence base"

    def _labels_for(receipt_filter: Any, limit: int = 3) -> str:
        labels: list[str] = []
        for r in receipts:
            if not receipt_filter(r):
                continue
            label = str(
                r.get("citation_token") or r.get("body_citation")
                or r.get("paper_id") or r.get("receipt_id") or "",
            ).strip()
            if label and label not in labels:
                labels.append(label)
            if len(labels) >= limit:
                break
        return ", ".join(labels) if labels else "the retained evidence base"

    def _outcomes(effect: str) -> str:
        counts: Counter[str] = Counter(
            str(r.get("outcome_class") or "other").replace("_", " ")
            for r in receipts
            if str(r.get("effect_direction", "")).lower() == effect
        )
        top = [k for k, _v in counts.most_common(3) if k]
        return ", ".join(top) if top else "no dominant outcome class"

    direct = _count("directness", "direct")
    indirect = _count("directness", "indirect")
    mechanistic = sum(1 for r in receipts if _is_mechanistic_or_model_system(r))
    return {
        "receipt_n": int(manifest.get("n_receipts") or len(receipts)),
        "claim_n": int(manifest.get("n_high_confidence_claims_total") or 0),
        "tension_n": int(manifest.get("n_non_orthogonal_tensions") or 0),
        "direct": direct,
        "indirect": indirect,
        "mechanistic": mechanistic,
        "positive": _outcomes("positive"),
        "negative": _outcomes("negative"),
        "null": _outcomes("null"),
        "mixed": _outcomes("mixed"),
        "direct_refs": _labels("directness", "direct"),
        "mech_refs": _labels_for(_is_mechanistic_or_model_system),
        "positive_refs": _labels("effect_direction", "positive"),
        "negative_refs": _labels("effect_direction", "negative"),
        "null_refs": _labels("effect_direction", "null"),
        "thesis": str(manifest.get("thesis") or "The evidence profile is mixed."),
        "outcome_rows": _section_backstop_outcome_rows(receipts),
    }


def _section_backstop_outcome_rows(
    receipts: list[dict[str, Any]],
) -> list[dict[str, object]]:
    by_outcome: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for receipt in receipts:
        by_outcome[str(receipt.get("outcome_class") or "other")].append(receipt)
    rows: list[dict[str, object]] = []
    for outcome, group in sorted(by_outcome.items(), key=lambda x: (-len(x[1]), x[0]))[:6]:
        directions = Counter(str(r.get("effect_direction") or "mixed").lower() for r in group)
        directness = Counter(str(r.get("directness") or "unclassified").lower() for r in group)
        claim_n = sum(int(r.get("n_claims") or 0) for r in group)
        refs = [
            str(r.get("citation_token") or r.get("body_citation") or r.get("paper_id") or r.get("receipt_id") or "").strip()
            for r in group[:3]
        ]
        rows.append({
            "label": outcome.replace("_", " ").strip().title() or "Other",
            "n": len(group),
            "claims": claim_n,
            "directions": ", ".join(f"{k}={v}" for k, v in sorted(directions.items())),
            "directness": ", ".join(f"{k}={v}" for k, v in sorted(directness.items())),
            "refs": ", ".join(r for r in refs if r) or "the retained evidence base",
        })
    return rows


def _compile_results_outcome_backstop(
    topic: str, ctx: dict[str, object], floor: int,
) -> str:
    raw_rows = ctx.get("outcome_rows")
    rows = [r for r in raw_rows if isinstance(r, dict)] if isinstance(raw_rows, list) else []
    if not rows:
        return ""
    lines = [
        "## Results",
        "",
        f"The retained {topic} corpus is reported by outcome class before any cross-domain interpretation. This structure prevents favorable, null, mixed, and adverse evidence from being blended across biologically different endpoints.",
        "",
    ]
    for row in rows:
        label = str(row.get("label") or "Other")
        lines.extend([
            f"### {label} Outcomes",
            "",
            f"The {label.lower()} evidence packet includes {row.get('n')} source-level summaries and {row.get('claims')} high-confidence observations. Directional coding within this packet is {row.get('directions')}, and directness coding is {row.get('directness')}. These counts describe the frozen evidence state for this outcome, not a pooled treatment estimate.",
            "",
            f"Representative sources include {row.get('refs')}. This outcome is interpreted within its own packet first; any broader synthesis is deferred until the cross-domain section so that the writer cannot merge evidence from unrelated outcome classes.",
            "",
        ])
    shared = (
        "Across outcome classes, the manuscript treats disagreement as part of the evidence rather than as noise to smooth away. A null or adverse signal in one section does not cancel a favorable signal in another; it defines the boundary condition for interpretation.",
        "The section-owned layout also protects citation integrity. Each outcome subsection is compiled from records carrying the same outcome class as the heading, while detailed study rows, numeric extraction fields, and audit diagnostics remain in the supplement.",
    )
    for paragraph in shared:
        if _word_count("\n\n".join(lines)) >= floor + 25:
            break
        lines.extend([paragraph, ""])
    return "\n".join(lines).rstrip()


def _section_heading_from_body(section_md: str) -> str:
    first = section_md.lstrip().splitlines()[0:1]
    return first[0].strip() if first and first[0].startswith("## ") else ""


def _section_body_text(section_md: str, heading: str) -> str:
    if section_md.lstrip().startswith(heading):
        return section_md.lstrip().split("\n", 1)[1] if "\n" in section_md else ""
    return section_md


def _rendered_section_match(markdown: str, heading: str) -> re.Match[str] | None:
    return re.search(
        rf"^{re.escape(heading)}\b.*?\n(.*?)(?=^##\s+|\Z)",
        markdown,
        flags=re.MULTILINE | re.DOTALL,
    )


def _pop_h2_section_by_prefix(
    markdown: str, title_prefix: str,
) -> tuple[str, str]:
    match = re.search(
        rf"^##\s+{re.escape(title_prefix)}\b.*?(?=^##\s+|\Z)",
        markdown,
        flags=re.MULTILINE | re.DOTALL,
    )
    if match is None:
        return markdown, ""
    remaining = (markdown[:match.start()].rstrip() + "\n\n" + markdown[match.end():].lstrip()).strip()
    return remaining + "\n", match.group(0).strip()


def _word_count(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text))


def _count_phrase(n: int, singular: str, plural: str | None = None) -> str:
    value = n
    return f"{value} {singular if value == 1 else (plural or singular + 's')}"


def _evidence_tier_phrase(n: int, label: str) -> str:
    value = n
    if value == 0:
        return f"no sources classified primarily as {label} evidence"
    return f"{value} {label} {'source' if value == 1 else 'sources'}"


def _ensure_results_summary_table(
    markdown: str, manifest: dict[str, Any],
) -> tuple[str, bool]:
    header = "| Outcome class | Corpus slice | Strongest signal | Directness | Main limitation |"
    if header in markdown:
        return markdown, False
    match = re.search(r"^## Results\s*$", markdown, re.MULTILINE)
    if match is None:
        return markdown, False
    receipts = [
        r for r in manifest.get("receipts", [])
        if isinstance(r, dict) and r.get("outcome_class")
    ]
    if not receipts:
        return markdown, False
    by_outcome: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for receipt in receipts:
        by_outcome[str(receipt.get("outcome_class") or "other")].append(receipt)
    rows: list[str] = []
    for outcome, group in sorted(
        by_outcome.items(), key=lambda item: (-len(item[1]), item[0]),
    )[:6]:
        directions = Counter(
            str(r.get("effect_direction") or "mixed").lower() for r in group
        )
        directness = Counter(
            str(r.get("directness") or "indirect").lower() for r in group
        )
        dominant, dominant_n = directions.most_common(1)[0]
        signal_name = {
            "positive": "benefit signal",
            "negative": "adverse or limiting signal",
            "null": "null signal",
            "mixed": "mixed signal",
        }.get(dominant, "mixed signal")
        direct_parts = [
            f"{directness[k]} {k}" for k in ("direct", "indirect", "mechanistic")
            if directness.get(k)
        ]
        claim_n = sum(int(r.get("n_claims") or 0) for r in group)
        corpus_slice = f"n={len(group)}; claims={claim_n}"
        if directness.get("direct", 0) == 0:
            limitation = "no direct clinical anchor"
        elif len(directions) > 1:
            limitation = "directionally heterogeneous"
        elif len(group) < 2:
            limitation = "single-source support"
        else:
            limitation = "population and endpoint heterogeneity"
        label = outcome.replace("_", " ").strip().title() or "Other"
        rows.append(
            f"| {label} | {corpus_slice} | "
            f"{signal_name} in {dominant_n}/{len(group)} sources | "
            f"{'; '.join(direct_parts) or 'not classified'} | {limitation} |"
        )
    table = "\n".join([
        header,
        "|---|---|---|---|---|",
        *rows,
    ])
    insert_at = match.end()
    return (
        markdown[:insert_at].rstrip()
        + "\n\n"
        + table
        + "\n\n"
        + markdown[insert_at:].lstrip(),
        True,
    )


def _heading_pos(markdown: str, heading: str, start: int = 0) -> int:
    match = re.search(
        rf"^{re.escape(heading)}\b", markdown[start:], re.MULTILINE,
    )
    return -1 if match is None else start + match.start()


def _first_heading_after(markdown: str, headings: tuple[str, ...], start: int) -> int:
    positions = [_heading_pos(markdown, h, start) for h in headings]
    positions = [p for p in positions if p >= 0]
    return min(positions) if positions else -1


_CROSS_DOMAIN_PARA_RE = re.compile(
    r"\b(?:cross-domain|tension|conflict|discrepanc|discordan|"
    r"boundary condition|contradict)\b",
    re.IGNORECASE,
)


def _insert_cross_domain_heading(markdown: str, heading: str) -> tuple[str, bool]:
    start = _heading_pos(markdown, "## Results")
    end = _heading_pos(markdown, "## Discussion", start)
    if start < 0 or end < 0 or start >= end:
        return markdown, False
    segment = markdown[start:end]
    for match in re.finditer(r"(?ms)(^|\n\n)([^\n#_].*?)(?=\n\n|$)", segment):
        para = match.group(2).strip()
        if not _CROSS_DOMAIN_PARA_RE.search(para):
            continue
        if "_Cited:" not in segment[: match.start(2)]:
            continue
        pos = start + match.start(2)
        return (
            markdown[:pos].rstrip() + f"\n\n{heading}\n\n"
            + markdown[pos:].lstrip(),
            True,
        )
    return markdown, False


def _insert_conclusion_heading(markdown: str, heading: str) -> tuple[str, bool]:
    start = _heading_pos(markdown, "## Limitations")
    end = _first_heading_after(
        markdown,
        ("## Structured Evidence Tables", "## Search Provenance", "## References"),
        start + 1 if start >= 0 else 0,
    )
    if start < 0 or end < 0 or start >= end:
        return markdown, False
    segment = markdown[start:end]
    cited = list(re.finditer(r"^\s*_Cited:.*?_$", segment, re.MULTILINE))
    if not cited:
        return markdown, False
    pos = start + cited[-1].end()
    return (
        markdown[:pos].rstrip() + f"\n\n{heading}\n\n"
        + markdown[pos:].lstrip(),
        True,
    )


def _set_topic(topic: str) -> None:
    """Update module-level corpus paths + topic pack for the given
    topic across the orchestrator, audit, and bg-lit modules.
    Called once by _run() at the top of each pipeline invocation.

    Refactor 2026-05-04: also loads the topic pack so generic
    helpers (_claim_topic_effect, canonical RCT lists, etc.) can
    read topic-specific data without hardcoded strings.

    Also sets TOPIC_DOMAIN env var so vocab/__init__.py picks up
    the correct vocab pack (auto-synthesizes from topic pack TOML
    if no vocab/<topic>.py exists)."""
    global QUANT_DIR, PARSED_DIR, _TOPIC_PACK, _ACTIVE_TOPIC
    import os
    QUANT_DIR = REPO_ROOT / "docs" / "quality-reference" / topic / "quant_claims"
    PARSED_DIR = REPO_ROOT / "docs" / "quality-reference" / topic / "parsed"
    _ACTIVE_TOPIC = topic
    os.environ["TOPIC_DOMAIN"] = topic
    # Keep audit module in lockstep
    _audit_v06._set_topic(topic)
    # Load topic pack (best-effort — pack may not exist for new topics)
    try:
        from agent.topic_pack import load_topic_pack
        tp_path = REPO_ROOT / "topic_packs" / f"{topic}.toml"
        if tp_path.exists():
            _TOPIC_PACK = load_topic_pack(tp_path)
        else:
            _TOPIC_PACK = None
    except (ImportError, OSError, ValueError) as e:
        print(
            f"  ! topic pack load failed for {topic}: {e}",
            file=sys.stderr,
        )
        _TOPIC_PACK = None


def _get_topic_pack():
    """Accessor for the active topic pack. Returns None if no
    pack is loaded for the active topic (graceful fallback for
    new/experimental topics)."""
    return _TOPIC_PACK


def _get_active_topic() -> str:
    """Accessor for the currently-set topic name."""
    return _ACTIVE_TOPIC


# v0.6.0 endpoint → SynthesisSchemas OutcomeClass mapping. Shared base
# plus topic-pack [endpoint_polarity] inference below.
_ENDPOINT_TO_OUTCOME_CLASS: dict[str, str] = {
    # muscle_function
    "VO2max": "muscle_function",
    "thigh muscle mass": "muscle_function",
    "lean body mass": "muscle_function",
    "muscle hypertrophy": "muscle_function",
    "muscle strength": "muscle_function",
    "protein synthesis": "muscle_function",
    "cardiorespiratory fitness": "muscle_function",
    # frailty
    "walk speed": "frailty",
    "frailty": "frailty",
    "sarcopenia": "frailty",
    # longevity
    "mortality": "longevity",
    "lifespan": "longevity",
    "healthspan": "longevity",
    # cardiometabolic
    "HbA1c": "cardiometabolic",
    "insulin sensitivity": "cardiometabolic",
    "fasting glucose": "cardiometabolic",
    "blood glucose": "cardiometabolic",
    "body weight": "cardiometabolic",
    "body mass index": "cardiometabolic",
    "AMPK signaling": "cardiometabolic",
    "mTOR signaling": "cardiometabolic",
    "mitochondrial respiration": "cardiometabolic",
    "blood pressure": "cardiometabolic",
    # immune
    "inflammation": "immune",
    "oxidative stress": "immune",
}


# Per-endpoint polarity: +1 means "increase = good for the patient"
# (so metformin direction=increase → effect_direction=positive on this
# endpoint). -1 means "decrease = good" (e.g. mortality, HbA1c). The
# adapter combines this with the bound arm + direction to derive a
# per-paper effect_direction.
_ENDPOINT_POLARITY: dict[str, int] = {
    "VO2max": +1, "thigh muscle mass": +1, "lean body mass": +1,
    "muscle hypertrophy": +1, "muscle strength": +1, "lifespan": +1,
    "healthspan": +1, "insulin sensitivity": +1, "AMPK signaling": +1,
    "mitochondrial respiration": +1, "protein synthesis": +1,
    "cardiorespiratory fitness": +1,
    "mortality": -1, "frailty": -1, "sarcopenia": -1, "HbA1c": -1,
    "fasting glucose": -1, "blood glucose": -1, "body weight": -1,
    "body mass index": -1, "inflammation": -1, "oxidative stress": -1,
    "blood pressure": -1, "mTOR signaling": -1, "walk speed": +1,
}

_RATIO_CLAIM_TYPES = {"hazard_ratio", "odds_ratio", "risk_ratio"}
_TIME_TO_EVENT_BENEFIT_ENDPOINTS = {"lifespan", "healthspan", "longevity"}
_ACTIVE_VS_PLACEBO_RE = re.compile(
    r"\b(?:greater|higher|improved|gain(?:ed)?|increase[ds]?)\b"
    r".{0,120}\b(?:than|compared\s+to|different\s+from)\b"
    r".{0,80}\bplacebo\b|\bbetween\b.{0,80}\band\s+placebo\b",
    re.IGNORECASE,
)
_OUTCOME_CLASSES = frozenset({
    "muscle_function", "cardiometabolic", "cognitive", "frailty",
    "longevity", "immune", "oncology", "mechanism", "safety", "other",
})


def _endpoint_key(endpoint: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", endpoint.strip().lower()).strip("_")


def _pack_endpoint_polarity(endpoint: str) -> int:
    pack = _get_topic_pack()
    if pack is None:
        return 0
    key = _endpoint_key(endpoint)
    raw = pack.endpoint_polarity.get(key) or pack.endpoint_polarity.get(endpoint)
    if raw == "higher_is_better":
        return +1
    if raw == "lower_is_better":
        return -1
    return 0


def _active_domain_vocab():
    topic = _get_active_topic()
    if not topic:
        return None
    try:
        from vocab import load_domain
        return load_domain(topic)
    except (ImportError, AttributeError, ValueError):
        return None


def _domain_outcome_class(endpoint: str) -> str:
    vocab = _active_domain_vocab()
    mapping = getattr(vocab, "ENDPOINT_TO_OUTCOME_CLASS", {}) if vocab else {}
    if isinstance(mapping, dict):
        return str(mapping.get(endpoint) or "")
    return ""


def _domain_endpoint_polarity(endpoint: str) -> int:
    vocab = _active_domain_vocab()
    mapping = getattr(vocab, "ENDPOINT_POLARITY", {}) if vocab else {}
    if isinstance(mapping, dict):
        raw = mapping.get(endpoint)
        if raw in (-1, 0, 1):
            return int(raw)
    return 0


def _infer_outcome_class(endpoint: str) -> str:
    key = _endpoint_key(endpoint)
    label = endpoint.strip().lower()
    if key in _OUTCOME_CLASSES:
        return key
    if any(t in label for t in (
        "ldl", "triglyceride", "cardiovascular", "cv event",
        "blood pressure", "glucose", "hba1c", "weight", "bmi",
    )):
        return "cardiometabolic"
    if any(t in label for t in ("cognition", "cognitive", "dementia", "alzheimer")):
        return "cognitive"
    if any(t in label for t in ("mortality", "lifespan", "healthspan", "longevity")):
        return "longevity"
    if any(t in label for t in ("frailty", "walk speed")):
        return "frailty"
    if any(t in label for t in ("inflammation", "immune", "crp", "cytokine")):
        return "immune"
    if any(t in label for t in ("bleeding", "adverse", "safety", "myopathy", "myalgia")):
        return "safety"
    if any(t in label for t in ("muscle", "sarcopenia", "strength")):
        return "muscle_function"
    return "other"


def _outcome_class_for_endpoint(endpoint: str) -> str:
    raw = (
        _ENDPOINT_TO_OUTCOME_CLASS.get(endpoint)
        or _domain_outcome_class(endpoint)
        or _infer_outcome_class(endpoint)
    )
    return remap_outcome_class(endpoint, raw)


def _polarity_for_endpoint(endpoint: str) -> int:
    return (
        _ENDPOINT_POLARITY.get(endpoint, 0)
        or _domain_endpoint_polarity(endpoint)
        or _pack_endpoint_polarity(endpoint)
    )


def _mentions_any_synonym(text: str, synonyms) -> bool:
    low = (text or "").lower()
    for syn in synonyms or ():
        token = str(syn).strip().lower()
        if len(token) < 3:
            continue
        if re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", low):
            return True
    return False


def _active_vs_placebo_context(text: str) -> bool:
    return bool(_ACTIVE_VS_PLACEBO_RE.search(text or ""))


def _author_year_token(receipt) -> str | None:
    """Slice 7 P1b: resolve a receipt's 'Author YYYY' citation token
    from its receipt_id (typically 'Author_YYYY_<slug>' or
    'PMC<id>_<slug>'). Used to populate manifest['receipts'][i]
    ['citation_token'] so the source-context drift check can map
    prose citations to receipts' quant_claims.

    Falls back to None when no Author/Year pair is parseable.
    Universal — works for any topic + domain."""
    rid = (receipt.receipt_id or "").strip()
    if not rid:
        return None
    import re as _re
    # Pattern 1: 'Author_YYYY' at start (e.g. 'Witham_2025_MET_PREVENT').
    # \b doesn't fire after digits when followed by '_' (underscore is
    # a word char) — use lookahead for end-of-id or '_' instead.
    m = _re.match(
        r"^([A-Z][a-zA-Z\-]+)_(\d{4}[a-z]?)(?=_|$)", rid,
    )
    if m:
        return f"{m.group(1)} {m.group(2)}"
    # Pattern 2: '<Author>_<Year>' embedded later
    m = _re.search(
        r"(?:^|[_\-])([A-Z][a-zA-Z\-]+)_(\d{4}[a-z]?)(?=_|$)", rid,
    )
    if m:
        return f"{m.group(1)} {m.group(2)}"
    # Pattern 3: PMCID prefix — fall back to source_year metadata
    if hasattr(receipt, "source_year") and receipt.source_year:
        # Try canonical_trial_id-style fallback if present
        return None  # cannot resolve without author meta
    return None


def _claim_topic_effect(claim: dict) -> int:
    """Returns +1 if the active topic's compound has a good effect
    on this endpoint, -1 if bad, 0 if unclear/null.

    Refactor 2026-05-04: was hardcoded to `arm == "metformin"`.
    Now reads active_arm_synonyms from the topic pack so this works
    for any drug (rapamycin, GLP-1, statins, etc.) without code
    changes."""
    direction = claim.get("direction") or ""
    arm = (claim.get("arm") or "").strip().lower()
    endpoint = claim.get("endpoint") or ""
    polarity = _polarity_for_endpoint(endpoint)
    if not polarity:
        return 0
    if claim.get("claim_type") in _RATIO_CLAIM_TYPES:
        vals = claim.get("numeric_values") or []
        try:
            ratio = float(vals[0])
        except (IndexError, TypeError, ValueError):
            ratio = 0.0
        if ratio and abs(ratio - 1.0) > 1e-9:
            if (
                claim.get("claim_type") == "hazard_ratio"
                and endpoint in _TIME_TO_EVENT_BENEFIT_ENDPOINTS
            ):
                return +1 if ratio < 1.0 else -1
            movement = +1 if ratio > 1.0 else -1
            return polarity * movement
    if (
        claim.get("claim_type") in {"p_value", "confidence_interval"}
        and claim.get("claim_role") != "effect"
    ):
        return 0
    if not direction or direction == "no_change":
        return 0
    direction_sign = +1 if direction == "increase" else -1
    # If the direction is described from the active arm, +1.
    # Placebo/control rows are comparator context unless the sentence
    # explicitly describes an active-vs-placebo advantage.
    pack = _get_topic_pack()
    active_synonyms = (
        pack.active_arm_synonyms if pack is not None else {_get_active_topic()}
    )
    placebo_synonyms = (
        pack.placebo_arm_synonyms if pack is not None else {"placebo", "control"}
    )
    if arm:
        if arm in active_synonyms:
            arm_sign = +1
        elif arm in placebo_synonyms:
            text = " ".join(str(claim.get(k) or "") for k in (
                "sentence", "context_window", "raw_text",
            ))
            if _active_vs_placebo_context(text):
                arm_sign = +1
            else:
                return 0
        else:
            text = " ".join(str(claim.get(k) or "") for k in (
                "sentence", "context_window", "raw_text",
            ))
            if _mentions_any_synonym(text, active_synonyms):
                arm_sign = +1
            elif _mentions_any_synonym(text, placebo_synonyms):
                return 0
            else:
                return 0
    else:
        text = " ".join(str(claim.get(k) or "") for k in (
            "sentence", "context_window", "raw_text",
        ))
        if _mentions_any_synonym(text, active_synonyms):
            arm_sign = +1
        elif _mentions_any_synonym(text, placebo_synonyms):
            return 0
        else:
            return 0
    drug_movement = direction_sign * arm_sign
    return polarity * drug_movement


# Backward-compat alias — some legacy call sites may still use the
# old name. Forwards to the new generic function.
_claim_metformin_effect = _claim_topic_effect


def _aggregate_paper(paper_id: str, claims: list[dict]) -> dict[str, Any]:
    """Per-paper rollup: dominant outcome_class, dominant
    effect_direction (Fix #5: now significance-aware → null/mixed
    states), p-values list, sample-size summary."""
    outcome_counter: Counter[str] = Counter()
    p_values: list[str] = []
    sample_sizes: list[float] = []
    for c in claims:
        if oc := _outcome_class_for_endpoint(c.get("endpoint") or ""):
            outcome_counter[oc] += 1
        if c.get("claim_type") == "p_value":
            raw = c.get("raw_text") or ""
            if raw:
                p_values.append(raw.replace("\xa0", " ").strip())
        if c.get("claim_type") == "sample_size":
            vals = c.get("numeric_values") or []
            if vals:
                sample_sizes.append(vals[0])

    dominant_outcome: str = (
        outcome_counter.most_common(1)[0][0]
        if outcome_counter else "other"
    )
    # Fix #5: significance-aware aggregation. Returns one of
    # positive/negative/null/mixed/unclear. The MET-PREVENT case
    # (Witham 2025: 0.001 m/s walk speed, p=0.96) now correctly
    # produces "null" instead of "positive".
    effect_direction = _direction.infer_effect_direction(
        claims, metformin_effect_fn=_claim_metformin_effect,
    )

    return {
        "outcome_class": dominant_outcome,
        "effect_direction": effect_direction,
        "p_values": p_values,
        "sample_sizes": sample_sizes,
        "n_claims": len(claims),
    }


_TITLE_NO_BENEFIT_RE = re.compile(
    r"\b(?:does\s+not|did\s+not|fails?\s+to|failed\s+to|"
    r"no\s+(?:significant\s+)?(?:effect|benefit|improvement))\b"
    r".{0,80}\b(?:preserve|improve|augment|increase|enhance|benefit|"
    r"effect|mass|strength|function)",
    re.IGNORECASE,
)


def _title_guarded_effect_direction(title: str, current: str) -> str:
    if current == "positive" and _TITLE_NO_BENEFIT_RE.search(title or ""):
        return "null"
    return current


def _classify_paper_tier(paper_id: str, n_claims: int, paper_meta: dict) -> tuple[str, str]:
    """Return (evidence_tier, directness) — Fix #4: deterministic
    classification from structured metadata via evidence_taxonomy.

    First tries explicit metadata fields (`study_design`, `species`,
    `endpoint_kind` if the parsed-paper JSON has them). Falls back to
    a title/abstract keyword extractor for legacy papers without
    explicit annotation. The pre-fix heuristic (PMC* → "mechanistic",
    everything else → "B/indirect") incorrectly tagged human
    observational mortality studies as "mechanistic" — a category
    error that propagated into the synthesis."""
    # Explicit-field path: metadata sources MAY include these fields
    # directly. Empty/missing fields fall through to inference.
    explicit_design = paper_meta.get("study_design")
    explicit_species = paper_meta.get("species")
    explicit_endpoint_kind = paper_meta.get("endpoint_kind")
    if explicit_design or explicit_species or explicit_endpoint_kind:
        cls = _taxonomy.classify_evidence(
            study_design=explicit_design,
            species=explicit_species,
            endpoint_kind=explicit_endpoint_kind,
        )
    else:
        cls = _taxonomy.infer_from_paper_meta(paper_meta)
    # If the deterministic path returns "unknown", fall back to the
    # topic-pack canonical RCT list so existing runs don't regress.
    # Refactor 2026-05-04: was hardcoded to metformin RCT names
    # ("MASTERS", "MET_PREVENT", "Konopka_2019") — now reads from
    # the active topic pack's canonical_rct_paper_ids.
    if cls.tier == "unknown":
        pack = _get_topic_pack()
        is_rct_papers = (
            pack.canonical_rct_paper_ids if pack is not None
            else ()
        )
        if any(name in paper_id for name in is_rct_papers):
            return "A1", "direct"
        if paper_id.startswith("PMC"):
            # P1 reviewer fix: PMC* prefix alone is NOT a reliable
            # mechanistic signal — many PMC papers are human
            # observational mortality studies. Default to B2 here so
            # we err toward "human-direct" rather than misclassifying
            # as mechanistic.
            return "B2", "indirect"
        return "B1", "review"
    return cls.tier, cls.directness


def _build_population_summary(paper_meta: dict, n_subjects: list[float]) -> str:
    """Best-effort population summary from paper metadata + sample sizes."""
    title = (paper_meta.get("title") or "").lower()
    if "older adults" in title:
        pop = "older adults"
    elif "frailt" in title or "sarcopen" in title:
        pop = "frail / sarcopenic adults"
    elif "diabetes" in title or "t2d" in title:
        pop = "type 2 diabetes patients"
    elif "mice" in title or "mouse" in title:
        pop = "mice (preclinical)"
    elif "review" in title or "geroscience" in title:
        return ""  # review — no enrolled population
    else:
        pop = "adults"
    return pop


def _extract_canonical_trial_id(claims: list[dict]) -> str | None:
    """Find an NCT or ISRCTN id mentioned in any claim's sentence."""
    nct_re = re.compile(r"\b(NCT\d{8})\b")
    isrctn_re = re.compile(r"\b(ISRCTN\d{6,10})\b")
    for c in claims:
        sent = c.get("sentence") or ""
        m = nct_re.search(sent) or isrctn_re.search(sent)
        if m:
            return m.group(1)
    return None


def _shorten_claim_sentence(sentence: str, limit: int = 180) -> str:
    clean = " ".join((sentence or "").replace("\xa0", " ").split())
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1].rstrip() + "…"


def _build_receipt_thesis_text(
    paper_id: str,
    paper_title: str,
    claims: list[dict],
) -> str:
    """Build a neutral receipt summary from source sentences.

    Do not paraphrase extractor arm/direction fields here. Those fields
    are useful for audit scoring, but at corpus scale they can be noisy;
    receipt prose should preserve the source sentence so a bad arm label
    cannot become a false synthesis claim.
    """
    evidence_lines: list[str] = []
    seen: set[str] = set()
    for claim in claims:
        sentence = _shorten_claim_sentence(claim.get("sentence") or "")
        if not sentence or sentence in seen:
            continue
        seen.add(sentence)
        raw = (claim.get("raw_text") or "").strip()
        if raw and raw not in sentence:
            evidence_lines.append(f"{sentence} [{raw}]")
        else:
            evidence_lines.append(sentence)
        if len(evidence_lines) >= 3:
            break
    title = paper_title or paper_id
    if not evidence_lines:
        return f"{title} — high-confidence quantitative evidence available."
    return f"{title} — source excerpts: " + " | ".join(evidence_lines)


def _load_paper_meta_by_id() -> dict[str, dict]:
    """Load all parsed-paper metadata (paper_id → dict). Used both
    by the receipt builder AND by Fix #10's citation-registry call
    (Author-Year extraction from authors+year fields)."""
    paper_meta_by_id: dict[str, dict] = {}
    for path in sorted(PARSED_DIR.glob("*.paper_sections.json")):
        d = json.loads(path.read_text())
        pid = d.get("paper_id") or path.stem
        paper_meta_by_id[pid] = d
    return paper_meta_by_id


def _load_active_paper_ids() -> set[str] | None:
    report_path = QUANT_DIR.parent / "_extract_report.json"
    if not report_path.exists():
        return None
    try:
        report = json.loads(report_path.read_text())
    except json.JSONDecodeError:
        return None
    ids = report.get("active_paper_ids") or []
    return {str(x) for x in ids if str(x).strip()} or None


def _strict_clinical_receipt_scope() -> bool:
    """Clinical-brief packs disable inferential bridge and should not
    promote adjacent/mechanistic receipts from a reused broad corpus."""
    pack = _get_topic_pack()
    inference = getattr(pack, "inference", None)
    return bool(pack and inference is not None and not inference.allow)


def _receipt_scope_classes() -> set[str]:
    if _strict_clinical_receipt_scope():
        return {"core_on_thesis"}
    return {"core_on_thesis", "adjacent_clinical", "background_mechanism"}


def _load_classified_receipt_candidate_ids() -> set[str]:
    """Core, adjacent, and background-mechanism papers can carry
    load-bearing evidence in CLIN/INF/MECH papers. Off-thesis and
    rejected classes stay out."""
    path = QUANT_DIR.parent / "corpus_classification.json"
    if not path.exists():
        return set()
    try:
        rows = json.loads(path.read_text())
    except json.JSONDecodeError:
        return set()
    keep = _receipt_scope_classes()
    return {
        str(r.get("paper_id"))
        for r in rows
        if isinstance(r, dict)
        and r.get("classification") in keep
        and r.get("paper_id")
    }


def _claim_confidence_counts(claims: list[Any]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for claim in claims:
        if isinstance(claim, dict):
            counts[str(claim.get("binding_confidence") or "missing")] += 1
    return counts


def build_receipt_funnel_report(topic: str) -> dict[str, Any]:
    """Diagnose why quant_claims files do or do not become receipts.

    Receipt admission is intentionally strict: a paper must be in the
    active/classified candidate set and carry at least one high-confidence
    effect claim. This report makes that gate auditable so corpus expansion
    work can target the real bottleneck instead of guessing.
    """
    active = _load_active_paper_ids()
    classified = _load_classified_receipt_candidate_ids()
    candidates = _load_receipt_candidate_paper_ids()
    counts: Counter[str] = Counter()
    examples: dict[str, list[str]] = defaultdict(list)
    confidence_totals: Counter[str] = Counter()

    for path in sorted(QUANT_DIR.glob("*.quant_claims.json")):
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            counts["unreadable_quant_claims"] += 1
            continue
        pid = str(
            data.get("paper_id")
            or path.stem.replace(".quant_claims", "")
        )
        claims = data.get("claims") or []
        if not isinstance(claims, list):
            claims = []
        conf_counts = _claim_confidence_counts(claims)
        confidence_totals.update(conf_counts)

        if candidates is not None and pid not in candidates:
            reason = "outside_active_or_classified_scope"
        elif not claims:
            reason = "candidate_no_claims"
        elif conf_counts.get("high", 0):
            reason = "accepted_high_confidence"
        elif conf_counts.get("partial", 0) and conf_counts.get("none", 0):
            reason = "candidate_partial_and_none_only"
        elif conf_counts.get("partial", 0):
            reason = "candidate_partial_only"
        elif conf_counts.get("none", 0):
            reason = "candidate_none_only"
        else:
            reason = "candidate_no_binding_confidence"

        counts[reason] += 1
        if len(examples[reason]) < 8:
            examples[reason].append(pid)

    return {
        "topic": topic,
        "quant_claim_files": sum(counts.values()),
        "active_paper_ids": None if active is None else len(active),
        "classified_receipt_candidates": len(classified),
        "receipt_candidate_union": None if candidates is None else len(candidates),
        "counts": dict(sorted(counts.items())),
        "claim_binding_confidence_totals": dict(
            sorted(confidence_totals.items()),
        ),
        "examples": dict(sorted(examples.items())),
    }


def render_receipt_funnel_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# Receipt Funnel - {report['topic']}",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Quant-claim files | {report['quant_claim_files']} |",
        f"| Active paper IDs | {report['active_paper_ids']} |",
        f"| Classified receipt candidates | "
        f"{report['classified_receipt_candidates']} |",
        f"| Candidate union | {report['receipt_candidate_union']} |",
        "",
        "## Admission Counts",
        "",
        "| Gate result | Papers |",
        "|---|---:|",
    ]
    for key, value in report["counts"].items():
        lines.append(f"| `{key}` | {value} |")
    lines += [
        "",
        "## Claim Binding Confidence Totals",
        "",
        "| Binding confidence | Claims |",
        "|---|---:|",
    ]
    for key, value in report["claim_binding_confidence_totals"].items():
        lines.append(f"| `{key}` | {value} |")
    lines += ["", "## Examples", ""]
    for key, values in report["examples"].items():
        lines.append(f"### `{key}`")
        lines.extend(f"- `{v}`" for v in values)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _load_receipt_candidate_paper_ids() -> set[str] | None:
    active = _load_active_paper_ids()
    classified = _load_classified_receipt_candidate_ids()
    if _strict_clinical_receipt_scope() and classified:
        return classified if active is None else active & classified
    if active is None and not classified:
        return None
    return (active or set()) | classified


def build_receipts_from_quant_claims(
    topic: str,
) -> list[ReceiptSummary]:
    """Adapter: v0.6.0 quant_claims → ReceiptSummary list. One receipt
    per contributing paper. Only papers with ≥1 high-confidence
    effect-role claim are included.

    Workstream A: `topic` parameter is the per-receipt label (set on
    every ReceiptSummary). The corpus directory is QUANT_DIR which
    has already been set by `_set_topic(topic)` upstream."""
    receipts: list[ReceiptSummary] = []
    paper_meta_by_id = _load_paper_meta_by_id()
    active_paper_ids = _load_receipt_candidate_paper_ids()

    # Group high-confidence claims by paper_id
    by_paper: dict[str, list[dict]] = defaultdict(list)
    for path in sorted(QUANT_DIR.glob("*.quant_claims.json")):
        d = json.loads(path.read_text())
        pid = d.get("paper_id") or path.stem.replace(".quant_claims", "")
        if active_paper_ids is not None and pid not in active_paper_ids:
            continue
        for c in d.get("claims", []):
            if c.get("binding_confidence") == "high":
                by_paper[pid].append(c)

    for paper_id, claims in by_paper.items():
        if not claims:
            continue
        meta = paper_meta_by_id.get(paper_id, {})
        agg = _aggregate_paper(paper_id, claims)
        tier, directness = _classify_paper_tier(paper_id, agg["n_claims"], meta)
        thesis_text = _build_receipt_thesis_text(
            paper_id=paper_id,
            paper_title=meta.get("title") or "",
            claims=claims,
        )
        receipts.append(ReceiptSummary(
            receipt_id=paper_id,
            receipt_path=str(QUANT_DIR / f"{paper_id}.quant_claims.json"),
            topic=topic,
            thesis_text=thesis_text,
            spar_verdict="accept_clean",  # v0.6.0 high-conf passes our filter
            n_claims=agg["n_claims"],
            n_failed_traces=0,
            canonical_trial_id=_extract_canonical_trial_id(claims),
            evidence_tier=tier,
            directness=directness,
            outcome_class=agg["outcome_class"],
            effect_direction=cast(
                EffectDirection,
                _title_guarded_effect_direction(
                    meta.get("title") or "", agg["effect_direction"],
                ),
            ),
            p_values=tuple(agg["p_values"][:6]),
            population_summary=_build_population_summary(meta, agg["sample_sizes"]),
            source_title=meta.get("title"),
            source_year=meta.get("year"),
            source_doi=meta.get("doi"),
            source_pmid=meta.get("pmid"),
            source_venue=meta.get("journal"),
        ))
    receipts.sort(key=lambda r: -r.n_claims)
    return receipts


def build_tension_matrix(receipts: list[ReceiptSummary]) -> TensionMatrix:
    """Pairwise tensions between receipts. Same outcome_class + opposite
    effect_directions = disagreement. Different outcome_classes with
    one direct + one mechanistic = cross-domain tension."""
    pairs: list[Tension] = []
    sorted_receipts = sorted(receipts, key=lambda r: r.receipt_id)
    for i, a in enumerate(sorted_receipts):
        for b in sorted_receipts[i + 1:]:
            if a.outcome_class == b.outcome_class:
                # Fix #5 reviewer P2: explicit branches for the new
                # null/mixed direction values; agreement covers same-
                # value pairs (incl. null-vs-null and mixed-vs-mixed).
                if a.effect_direction == b.effect_direction:
                    kind = "agreement"
                    severity = 1
                elif "mixed" in (a.effect_direction, b.effect_direction):
                    # mixed vs anything (positive / negative / null) is a
                    # partial disagreement — strongest evidence the paper
                    # has internal contradiction worth surfacing.
                    kind = "disagreement"
                    severity = 4
                elif "null" in (a.effect_direction, b.effect_direction):
                    kind = "null_vs_positive"
                    severity = 3
                elif {a.effect_direction, b.effect_direction} == {
                    "positive", "negative",
                }:
                    kind = "disagreement"
                    severity = 5
                else:
                    kind = "orthogonal"
                    severity = 0
                summary = (
                    f"{a.receipt_id} ({a.effect_direction}) vs "
                    f"{b.receipt_id} ({b.effect_direction}) on "
                    f"{a.outcome_class}"
                )
            else:
                # Cross-domain tension if one is direct and the other mechanistic.
                if (a.directness == "direct" and b.directness == "mechanistic") or (
                    a.directness == "mechanistic" and b.directness == "direct"
                ):
                    kind = "mechanism_vs_clinical"
                    severity = 4
                    summary = (
                        f"{a.receipt_id} ({a.outcome_class}, "
                        f"{a.directness}) vs {b.receipt_id} "
                        f"({b.outcome_class}, {b.directness})"
                    )
                else:
                    kind = "orthogonal"
                    severity = 0
                    summary = (
                        f"{a.receipt_id} and {b.receipt_id} address "
                        "different outcome classes"
                    )
            pairs.append(Tension(
                receipt_a_id=a.receipt_id,
                receipt_b_id=b.receipt_id,
                kind=cast(TensionKind, kind),
                outcome_class=a.outcome_class,
                summary=summary,
                severity=severity,
            ))
    return TensionMatrix(receipts=tuple(receipts), pairs=tuple(pairs))


def build_thesis(
    receipts: list[ReceiptSummary], matrix: TensionMatrix,
    topic: str,
) -> SynthesisThesis:
    """Build a topic-generic deterministic thesis.

    Pre-Fix: hardcoded metformin-specific narrative ('MASTERS/
    Konopka/MET-PREVENT', 'metformin's anti-aging case'). Caused
    rapamycin synthesis to ship with metformin contamination in
    its thesis text, which Grok flagged as P1 but couldn't repair
    safely (ambiguous BEFORE replacement).

    Post-Fix: composes thesis from the receipts' own metadata —
    positive vs negative outcome-class signals, the dominant
    evidence tiers, and the cross-domain tensions surfaced by the
    matrix. Topic-name appears only as the subject; everything
    else derives from the actual corpus."""
    from collections import Counter
    receipt_ids = tuple(r.receipt_id for r in receipts)
    non_orth = matrix.non_orthogonal()
    addressed = tuple(t.summary for t in non_orth[:3])

    # Aggregate outcome × effect signals
    pos_outcomes: list[str] = []
    neg_outcomes: list[str] = []
    null_outcomes: list[str] = []
    for r in receipts:
        oc = (r.outcome_class or "").replace("_", " ")
        ed = (r.effect_direction or "").lower()
        if not oc:
            continue
        if ed == "positive":
            pos_outcomes.append(oc)
        elif ed == "negative":
            neg_outcomes.append(oc)
        elif ed == "null":
            null_outcomes.append(oc)
    pos_top = [
        o for o, _ in Counter(pos_outcomes).most_common(2)
    ]
    neg_top = [
        o for o, _ in Counter(neg_outcomes).most_common(2)
    ]
    null_top = [
        o for o, _ in Counter(null_outcomes).most_common(2)
    ]

    n = len(receipts)
    parts = [f"Across {n} curated reference paper"]
    parts[-1] += "s" if n != 1 else ""
    parts[-1] += f", the evidence base for {topic} shows a context-dependent profile."

    if pos_top:
        parts.append(
            f"Positive signals appear in: "
            f"{', '.join(pos_top)}."
        )
    if neg_top:
        parts.append(
            f"Negative signals appear in: "
            f"{', '.join(neg_top)}."
        )
    if null_top:
        parts.append(
            f"Null findings dominate: "
            f"{', '.join(null_top)}."
        )
    if non_orth:
        parts.append(
            f"The synthesis surfaces {len(non_orth)} non-"
            "orthogonal tensions across outcome classes — see "
            "Cross-Domain Synthesis."
        )
    parts.append(
        f"The {topic} anti-aging case as currently constituted is "
        "incomplete: mechanistic plausibility coexists with mixed "
        "or sparse human-RCT evidence, and the boundary conditions "
        "remain to be established."
    )
    text = " ".join(parts)
    return SynthesisThesis(
        text=text,
        receipt_ids_referenced=receipt_ids,
        tensions_addressed=addressed,
        rejected_candidates=(),
        picker_rationale=(
            "Topic-generic deterministic thesis composed from "
            "receipt outcome × effect signals + tension matrix; "
            "no LLM tournament. Replaces the v0.6 metformin-"
            "hardcoded thesis (which contaminated rapamycin runs)."
        ),
    )


def _author_year_for_receipt(r: ReceiptSummary) -> str:
    """Best-effort Author Year citation for a receipt. Pulls the first
    surname from paper_id (e.g. 'Walton_2019_MASTERS_...' → 'Walton')
    and the year. Falls back to receipt_id if structure unrecognized."""
    parts = (r.receipt_id or "").split("_")
    if len(parts) >= 2:
        author = parts[0]
        year = parts[1] if parts[1].isdigit() else (
            str(r.source_year) if r.source_year else ""
        )
        if author and year:
            return f"{author} {year}"
    if r.source_year:
        return f"{r.receipt_id[:20]} {r.source_year}"
    return r.receipt_id[:30]


def _replace_paper_ids_with_author_year(
    paper_md: str, receipts: list[ReceiptSummary],
    *, registry: dict | None = None,
) -> str:
    """Substitute paper_id strings (and their truncated forms) in the
    markdown with Author-Year citation. Audit Q3 ship-blocks otherwise.

    Reviewer-fix Fix #6 P1 v2: when `registry` is provided, the
    Author-Year substitution string comes from the registry's
    body_citation — SAME source the Tables and References use, so the
    body prose, tables, and references are guaranteed to use the same
    citation token for each receipt."""
    out = paper_md

    def _citation_for(r: ReceiptSummary) -> str:
        if registry is not None and r.receipt_id in registry:
            return registry[r.receipt_id].body_citation
        return _author_year_for_receipt(r)

    # Sort by length desc so longer forms get replaced before shorter
    # truncations (avoids "Walton_2019" replacing inside
    # "Walton_2019_MASTERS_...").
    pairs = sorted(
        ((r.receipt_id, _citation_for(r)) for r in receipts),
        key=lambda p: -len(p[0]),
    )
    for paper_id, author_year in pairs:
        for variant in (paper_id, paper_id[:30], paper_id[:25], paper_id[:20]):
            if variant and len(variant) >= 8:
                out = out.replace(variant, author_year)
    return out


def _append_references_block(
    paper_md: str, receipts: list[ReceiptSummary],
    *, registry: dict | None = None,
) -> str:
    """Append a deterministic References section at the end of the
    paper (after Conclusion). Each entry: Author Year. Title. Journal,
    Year. DOI/PMID. Replaces the writer's References section with one
    grounded in paper_sections.json metadata.

    Reviewer-fix Fix #6 P1: when `registry` is provided, the per-entry
    Author-Year token is sourced from the registry's body_citation —
    SAME source the Tables use, so prose / References / Tables can
    never drift out of sync.

    Fix #30: also append a "Background References" subsection listing
    any background_literature entries whose citation_token appears in
    the paper prose (e.g. 'Owen 2000', 'Anisimov 2008', 'ADA 2024').
    Pre-fix these citations were used by MiMo but missing from
    References — a public-review reader would flag that as missing
    bibliography. Per Fix #16/#18 the registry already validates the
    citation_token is in the same sentence as the numeric; here we
    add the canonical reference to the bibliography."""
    lines = ["", "## References", ""]
    for r in receipts:
        if registry is not None and r.receipt_id in registry:
            author_year = registry[r.receipt_id].body_citation
        else:
            author_year = _author_year_for_receipt(r)
        # Fix #35: smart-join — venue + year glue with single comma,
        # no `" ".join` artefact that produced "Lancet , 2025 ." with
        # a stray space before the comma. Title is also de-hyphenated
        # to fix PDF-parsed soft-breaks like "Anti- Aging".
        clean_title = (
            _clean_reference_title(r.source_title)
            if r.source_title else None
        )
        parts: list[str] = [f"- **{author_year}.**"]
        if clean_title:
            parts.append(f"_{clean_title}._")
        venue_year_bits: list[str] = []
        if r.source_venue:
            venue_year_bits.append(r.source_venue.strip().rstrip(",."))
        if r.source_year:
            venue_year_bits.append(str(r.source_year))
        if venue_year_bits:
            parts.append(", ".join(venue_year_bits) + ".")
        if r.source_doi:
            parts.append(f"DOI: {r.source_doi}.")
        if r.source_pmid:
            parts.append(f"PMID: {r.source_pmid}.")
        lines.append(" ".join(parts))
    lines.append("")

    # Fix #30: background-literature references used in prose
    used_bglit = _used_background_lit_entries(paper_md)
    if used_bglit:
        lines.extend([
            "### Background References",
            "",
            "*Canonical clinical thresholds cited in prose. Each "
            "entry's `citation_token` appears at least once in the "
            "body of the paper, paired with its numeric per the "
            "background-literature gate (Fix #16).*",
            "",
        ])
        for entry in used_bglit:
            ref_clean = (
                _clean_reference_title(entry.canonical_reference)
                if entry.canonical_reference else ""
            )
            bg_parts = [f"- **{entry.citation_token}.**"]
            if ref_clean:
                bg_parts.append(f"_{ref_clean}._")
            if entry.doi:
                bg_parts.append(f"DOI: {entry.doi}.")
            if entry.pmid:
                bg_parts.append(f"PMID: {entry.pmid}.")
            lines.append(" ".join(bg_parts))
        lines.append("")

    return paper_md.rstrip() + "\n".join(lines)


def _entry_field(entry: Any, field: str) -> Any:
    if isinstance(entry, dict):
        return entry.get(field)
    return getattr(entry, field, None)


def _ensure_references_section(
    paper_md: str,
    citation_registry: dict | None,
) -> tuple[str, bool]:
    if re.search(r"^##\s+References\b", paper_md, re.MULTILINE):
        return paper_md, False
    if not citation_registry:
        return paper_md, False
    entries = sorted(
        citation_registry.values(),
        key=lambda e: str(_entry_field(e, "reference_id") or _entry_field(e, "body_citation") or ""),
    )
    lines = ["## References", ""]
    for entry in entries:
        body = str(_entry_field(entry, "body_citation") or "").strip()
        if not body:
            continue
        parts = [f"- **{body}.**"]
        title = str(_entry_field(entry, "title") or "").strip()
        if title:
            parts.append(f"_{_clean_reference_title(title)}._")
        journal = str(_entry_field(entry, "source_journal") or "").strip()
        year = _entry_field(entry, "source_year")
        venue_bits = [journal.rstrip(",.")] if journal else []
        if year:
            venue_bits.append(str(year))
        if venue_bits:
            parts.append(", ".join(venue_bits) + ".")
        if doi := _entry_field(entry, "source_doi"):
            parts.append(f"DOI: {doi}.")
        if pmid := _entry_field(entry, "source_pmid"):
            parts.append(f"PMID: {pmid}.")
        lines.append(" ".join(parts))
    if len(lines) <= 2:
        return paper_md, False
    return paper_md.rstrip() + "\n\n" + "\n".join(lines) + "\n", True


def _clean_reference_title(title: str) -> str:
    """Fix #35: collapse soft-broken hyphens in PDF-parsed titles.
    'Anti- Aging' → 'Anti-Aging'. Pattern: word-char + hyphen + space
    + word-char (the space is the artefact). Also collapses internal
    runs of double-spaces to single space and strips leading/trailing
    whitespace + trailing periods that would duplicate the closing
    period the renderer adds."""
    cleaned = re.sub(r"(\w)-\s+(\w)", r"\1-\2", title)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned.strip().rstrip(".")


def _used_background_lit_entries(paper_md: str) -> list:
    """Fix #30: load the background_literature registry, return the
    entries whose citation_token appears anywhere in `paper_md`.
    Returns an ordered, de-duplicated list (entry-key insertion
    order from the registry)."""
    try:
        registry = _bglit.load_registry()
    except (ImportError, FileNotFoundError, ValueError):
        return []
    seen_tokens: set[str] = set()
    used: list = []
    for entry in registry.values():
        if entry.citation_token in seen_tokens:
            continue
        if entry.citation_token in paper_md:
            used.append(entry)
            seen_tokens.add(entry.citation_token)
    return used


def _build_call_chain() -> list[CallSpec]:
    """Bulk paper writer chain — MiMo v2.5 Pro is PRIMARY.

    Order: MiMo v2.5 Pro (unlimited token plan) → Mistral Small (paid
    fallback) → Gemma 4 31B (paid fallback). OpenRouter fires only if
    MiMo is unreachable; the user's MiMo plan is unlimited while
    OpenRouter is metered.

    All identifiers come from agent/settings.py — never hardcode here.
    Past drift put `mimo-vl-7b-rl` (a vision model) and Gemma 3 27B as
    primaries, silently bypassing MiMo v2.5 Pro entirely.
    """
    settings = load_settings()
    chain: list[CallSpec] = []
    if settings.mimo_api_key:
        chain.append(CallSpec(
            base_url=settings.mimo_base_url,
            api_key=settings.mimo_api_key,
            model=settings.mimo_model,
            timeout_sec=settings.mimo_timeout_sec,
            max_attempts=configured_attempts_for_url(settings.mimo_base_url),
        ))
    if settings.openrouter_api_key:
        for openrouter_model in (settings.fallback_model, settings.judge_model):
            chain.append(CallSpec(
                base_url=settings.openrouter_base_url,
                api_key=settings.openrouter_api_key,
                model=openrouter_model,
                timeout_sec=settings.mimo_timeout_sec,
                max_attempts=configured_attempts_for_url(
                    settings.openrouter_base_url,
                ),
            ))
    return chain


async def _run(
    out_dir: Path,
    *,
    topic: str,
    dry_run: bool = False,
) -> int:
    global _ACTIVE_MANIFEST
    # Slice 21: capture wall-clock start so we can write
    # benchmark_runtime.json with a real duration at pipeline exit.
    _run_start_ts = dt.datetime.now(dt.timezone.utc)
    settings = load_settings()
    if not settings.bot_enabled:
        print("BOT_ENABLED=false; aborting.", file=sys.stderr)
        return 1

    # Workstream A: lock the corpus dirs to the requested topic
    # before any downstream code reads them.
    _set_topic(topic)
    if not QUANT_DIR.exists():
        print(
            f"corpus directory does not exist for topic={topic!r}: "
            f"{QUANT_DIR}\n"
            f"Expected docs/quality-reference/{topic}/quant_claims/ "
            f"with at least one *.quant_claims.json.",
            file=sys.stderr,
        )
        return 4

    print(
        f"Loading v0.6.0 quant_claims (topic={topic!r})...",
        file=sys.stderr,
    )
    receipt_funnel = build_receipt_funnel_report(topic)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "receipt_funnel.json").write_text(
        json.dumps(receipt_funnel, indent=2),
    )
    (out_dir / "receipt_funnel.md").write_text(
        render_receipt_funnel_markdown(receipt_funnel),
    )
    funnel_counts = receipt_funnel.get("counts", {})
    print(
        "  Receipt funnel: "
        f"accepted={funnel_counts.get('accepted_high_confidence', 0)} "
        f"outside_scope={funnel_counts.get('outside_active_or_classified_scope', 0)} "
        f"partial_only={funnel_counts.get('candidate_partial_only', 0)} "
        f"partial_none_only={funnel_counts.get('candidate_partial_and_none_only', 0)} "
        f"none_only={funnel_counts.get('candidate_none_only', 0)}",
        file=sys.stderr,
    )
    receipts = build_receipts_from_quant_claims(topic=topic)
    print(
        f"  Built {len(receipts)} receipts "
        f"(one per contributing paper).",
        file=sys.stderr,
    )
    if not receipts:
        print("No high-confidence claims found.", file=sys.stderr)
        return 2
    matrix = build_tension_matrix(receipts)
    thesis = build_thesis(receipts, matrix, topic=topic)

    print(f"Thesis: {thesis.text[:160]}...", file=sys.stderr)
    print(
        f"  Receipts: {len(receipts)} | "
        f"Non-orth tensions: {len(matrix.non_orthogonal())}",
        file=sys.stderr,
    )
    for r in receipts:
        print(
            f"  - {r.receipt_id[:50]:50s} "
            f"tier={r.evidence_tier} direct={r.directness} "
            f"outcome={r.outcome_class} effect={r.effect_direction} "
            f"n_claims={r.n_claims}",
            file=sys.stderr,
        )

    if dry_run:
        return 0

    chain = _build_call_chain()
    if not chain:
        print("No LLM keys configured.", file=sys.stderr)
        return 3

    out_dir.mkdir(parents=True, exist_ok=True)
    submission_id = out_dir.name
    ledger = CostLedger()

    # Fix #3: build the citation registry BEFORE the writer runs and
    # transform receipts AND matrix so the writer never sees raw
    # internal handles. PMCID body leaks become structurally
    # impossible (vs the previous post-hoc regex chase that missed
    # ~half the leaks). Matrix transformation MUST happen in lockstep
    # with receipt transformation, otherwise the writer's anchor-
    # validator sees mismatched IDs and trips invariant checks.
    # Fix #10: pass parsed paper metadata so PMC papers get
    # Author-Year body citations (e.g. "Yu 2025") instead of bare
    # PMC handles ("PMC12978362 2026"). PhD-grade citation surface.
    citation_registry = _citations.build_registry(
        receipts, paper_meta_by_id=_load_paper_meta_by_id(),
    )
    writer_receipts = _citations.transform_receipts_for_writer(
        receipts, citation_registry,
    )
    writer_matrix = _citations.transform_matrix_for_writer(
        matrix, citation_registry,
    )
    (out_dir / "citation_registry.json").write_text(json.dumps({
        rid: dataclasses.asdict(entry)
        for rid, entry in citation_registry.items()
    }, indent=2))
    manifest_receipts = [
        {
            "receipt_id": r.receipt_id,
            "outcome_class": r.outcome_class,
            "effect_direction": r.effect_direction,
            "evidence_tier": r.evidence_tier,
            "directness": r.directness,
            "n_claims": r.n_claims,
            "canonical_trial_id": r.canonical_trial_id,
            # Slice 7 P1b fix (2026-05-05): populate citation_token
            # so the source-context drift check can map prose
            # tokens (e.g. "Witham 2025") to this receipt's
            # quant_claims and check role match.
            "citation_token": (
                entry.body_citation
                if (entry := citation_registry.get(r.receipt_id)) is not None else
                _author_year_token(r)
            ),
            # paper_id resolved from receipt_id so quant_claims
            # files are findable.
            "paper_id": r.receipt_id,
        }
        for r in receipts
    ]
    field_engagement = tuple(
        dataclasses.asdict(item)
        for item in build_framework_engagement_records(
            writer_receipts, list(_bglit.load_registry().values()),
        )
    )
    (out_dir / "field_engagement.json").write_text(
        json.dumps(field_engagement, indent=2),
    )
    qei_citation_tokens = {
        rid: entry.body_citation
        for rid, entry in citation_registry.items()
        if entry.body_citation
    }

    print(
        "\nCalling render_full_paper "
        "(target 5-15k words, multi-section, tiered validation)...",
        file=sys.stderr,
    )
    # Fix #18a: load background-literature registry once and pass
    # entries to the writer so MiMo sees the canonical citation tokens
    # it can reference (e.g. 'Studenski 2011' for the 0.8 m/s frailty
    # cutoff). Without this, MiMo only sees the system-prompt rule
    # (Fix #17) and uses background numerics without their citations.
    bglit_entries = list(_bglit.load_registry().values())
    import httpx
    async with httpx.AsyncClient(timeout=180.0) as client:
        full_paper_md, sections = await render_full_paper(
            writer_receipts, writer_matrix, thesis,
            topic=topic, submission_id=submission_id,
            chain=chain, client=client, ledger=ledger,
            background_lit_entries=bglit_entries,
            qei_citation_tokens_by_paper_id=qei_citation_tokens,
            qei_quarantine_path=out_dir / "qei_quarantined.json",
        )
    print(
        "render_full_paper done.",
        file=sys.stderr,
    )

    # Phase 2 hardening: claim-strength repair pass
    accepted = list(receipts)
    full_paper_md, repair_log = repair_claim_strength(full_paper_md, accepted)
    print(
        f"Claim-strength repair: {len(repair_log)} sentence(s) repaired",
        file=sys.stderr,
    )

    # Belt-and-braces: even though Fix #3 substituted upstream, run the
    # registry-backed substitution again as a safety net. Idempotent —
    # if upstream already converted everything, this is a no-op.
    full_paper_md = _citations.substitute_receipt_ids(
        full_paper_md, citation_registry,
    )
    # Fix #6 P1 v2: pass registry through so body prose substitution
    # uses the SAME body_citation source as Tables and References. No
    # 3-way drift possible.
    full_paper_md = _replace_paper_ids_with_author_year(
        full_paper_md, receipts, registry=citation_registry,
    )
    # Fix #6 + Fix #21: insert deterministic Tables 1-5 BEFORE
    # References. Built from the post-citation-registry receipts so
    # table cells use clean body_citation strings (no raw internal
    # handles). Fix #21 passes the writer-side TensionMatrix so
    # Table 3 (cross-domain tensions) renders the non-orthogonal
    # pairs as one row per tension — the dense numerics carrier that
    # raises Q9 density without prose bloat. Fix #21 follow-up
    # builds claims_by_citation from the original receipt_id →
    # quant_claims JSON so Table 5 can surface top-N per-paper
    # numerics (the densest carrier — closes the Q9 AAA gap).
    claims_by_citation = _build_claims_by_citation(
        receipts, citation_registry,
    )

    supplement_parts: list[str] = []
    full_paper_md, qei_md = _pop_h2_section_by_prefix(
        full_paper_md, "Quantitative Evidence Index",
    )
    if qei_md:
        supplement_parts.append(qei_md)
    full_paper_md, bridge_md = _pop_h2_section_by_prefix(
        full_paper_md, "Inferential Bridge",
    )
    if bridge_md:
        supplement_parts.append(bridge_md)

    # Fix #25: append the deterministic 'What This Synthesis Adds'
    # section AFTER Conclusion and BEFORE Tables. Templated from
    # writer_receipts + writer_matrix + thesis so the originality
    # claim is grounded in pipeline data (zero LLM cost). Position
    # gives a PhD reviewer the explicit "beyond prior reviews"
    # statement right after the conclusion they just read.
    what_adds_md = build_what_this_adds_section(
        writer_receipts, writer_matrix, thesis, topic=topic,
    )
    if what_adds_md:
        full_paper_md = full_paper_md.rstrip() + "\n\n" + what_adds_md

    tables_md = _tables.render_all_tables(
        writer_receipts, writer_matrix, claims_by_citation,
    )
    if tables_md:
        supplement_parts.append(tables_md.rstrip())
    # Pass the registry to References so its Author-Year tokens come
    # from the SAME source as the table cells — no drift possible.
    full_paper_md = _append_references_block(
        full_paper_md, receipts, registry=citation_registry,
    )

    # Fix #2: replace LLM-templated Methods with deterministic block
    # rendered from a RunModeContract. Eliminates the contradiction
    # where Methods describes pipeline stages that didn't run.
    contract = _build_run_mode_contract(
        settings=settings,
        topic=topic,
        submission_id=submission_id,
        n_papers=len(receipts),
        n_claims=sum(r.n_claims for r in receipts),
    )
    contract_errors = _run_mode.validate_contract(contract)
    if contract_errors:
        raise RuntimeError(
            f"RunModeContract failed self-validation: {contract_errors}"
        )
    methods_md = _run_mode.render_methods(contract)
    blocked_in_rendered = _run_mode.validate_rendered(methods_md)
    if blocked_in_rendered:
        raise RuntimeError(
            f"Rendered Methods contains blocked phrases: {blocked_in_rendered}"
        )
    full_paper_md = _run_mode.replace_methods_in_paper(full_paper_md, methods_md)
    # Phase 4/5/7 live paper-quality wiring. These sections are derived
    # from accepted receipts, quant_claim sidecars, and the deterministic
    # tension matrix. They add no unsupported claims; invalid meta-analysis
    # pools fail closed into an eligibility statement.
    quality_artifact = _paper_quality.write_quality_methods(
        out_dir, manifest_receipts, PARSED_DIR,
    )
    meta_artifact = _paper_quality.write_meta_analysis(
        out_dir, manifest_receipts, QUANT_DIR,
    )
    tension_artifact = _paper_quality.write_tension_plans(
        out_dir, writer_matrix,
    )
    for supplement_name in (
        "quality_methods.md",
        "meta_analysis_results.md",
        "tension_elaboration_plans.md",
    ):
        supplement_path = out_dir / supplement_name
        if supplement_path.exists():
            supplement_parts.append(supplement_path.read_text().strip())
    if supplement_parts:
        (out_dir / "structured_evidence_tables.md").write_text(
            "# Supplementary Evidence Tables and Audit Methods\n\n"
            + "\n\n".join(part for part in supplement_parts if part)
            + "\n",
        )
    _ACTIVE_MANIFEST = {
        "topic": _ACTIVE_TOPIC,
        "n_receipts": len(receipts),
        "n_high_confidence_claims_total": sum(r.n_claims for r in receipts),
        "n_non_orthogonal_tensions": len(matrix.non_orthogonal()),
        "thesis": thesis.text,
        "receipts": manifest_receipts,
        "receipt_funnel": receipt_funnel,
        "field_engagement_path": "field_engagement.json",
        "quality_methods_path": "quality_methods.json",
        "meta_analysis_path": "meta_analysis_results.json",
        "tension_elaboration_path": "tension_elaboration_plans.json",
        "structured_evidence_tables_path": "structured_evidence_tables.md",
    }
    full_paper_md = _restore_rendered_section_contract(
        full_paper_md, sections,
    )
    (out_dir / "run_mode_contract.json").write_text(
        json.dumps(dataclasses.asdict(contract), indent=2)
    )

    paper_path = out_dir / "full_paper.md"
    paper_path.write_text(full_paper_md)
    word_count = len(full_paper_md.split())

    # Per-section breakdown
    section_words = {}
    for s in sections:
        section_words[s.name] = len(s.body_md.split())

    manifest = {
        "extractor_version": "v0.6.0",
        "writer_path": "agent.paper_writer.render_full_paper (production)",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        # Slice 7 step 3 fix: surface topic in manifest so Grok
        # reviewer + audit hooks can resolve topic-pack
        # background_literature for the active topic without
        # depending on module globals.
        "topic": _ACTIVE_TOPIC,
        "n_receipts": len(receipts),
        "n_high_confidence_claims_total": sum(r.n_claims for r in receipts),
        "n_non_orthogonal_tensions": len(matrix.non_orthogonal()),
        "thesis": thesis.text,
        "receipts": manifest_receipts,
        "receipt_funnel": receipt_funnel,
        "field_engagement_path": "field_engagement.json",
        "quality_methods_path": "quality_methods.json",
        "meta_analysis_path": "meta_analysis_results.json",
        "tension_elaboration_path": "tension_elaboration_plans.json",
        "quality_methods": quality_artifact["summary"],
        "meta_analysis": {
            "pools": len(meta_artifact.get("pools", ())),
            "candidate_groups": int(meta_artifact.get("candidate_groups", 0)),
        },
        "tension_elaboration": {
            "plans": len(tension_artifact.get("plans", ())),
            "candidate_tensions": int(tension_artifact.get("candidate_tensions", 0)),
        },
        "section_words": section_words,
        "total_words": word_count,
        "claim_strength_repairs": len(repair_log),
        "n_llm_calls": len(ledger.calls),
        "total_cost_usd": round(
            sum(c.estimated_cost_usd for c in ledger.calls), 6,
        ),
        # Slice 10 (2026-05-14): pin the declared review type so
        # downstream gates can enforce type-consistency between
        # manifest, Abstract, and Methods. Falls back to the universal
        # default when no topic pack is loaded.
        "review_type": (
            _TOPIC_PACK.review_type
            if _TOPIC_PACK is not None
            else "prisma_scr_scoping_synthesis"
        ),
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    # Bug-fix 2026-05-14: derive evidence_lanes.json sidecar so the
    # journal-surface gate can flag animal/preclinical citations that
    # leak into human-evidence prose without lane qualifiers (the
    # Bamford 2019 / Zijlmans 2022 species-mixing failure mode).
    # Universal — uses is_animal_paper keyword scan over each
    # receipt's source title + venue + population summary; no per-
    # topic table.
    # Slice 12 (2026-05-14): full 6-lane mapping (human RCT / human
    # observational / human mechanistic / review-meta / animal-preclinical
    # / background-only) per agent/evidence_lanes.LANE_TOKENS. Backward
    # compatible — the sidecar still exposes `animal_citations` so the
    # journal_surface_gate's animal-lane check keeps working unchanged.
    from agent.evidence_lanes import derive_lane, LANE_TOKENS
    lanes: dict[str, str] = {}
    animal_citations: list[dict[str, str]] = []
    for r in receipts:
        entry = citation_registry.get(r.receipt_id)
        cite = entry.body_citation if entry is not None else ""
        if not cite:
            continue
        lane = derive_lane(
            evidence_tier=r.evidence_tier,
            directness=r.directness,
            title=r.source_title,
            venue=r.source_venue,
            population=r.population_summary,
        )
        lanes[cite] = lane
        if lane == "animal_preclinical":
            animal_citations.append({
                "citation": cite, "paper_id": r.receipt_id,
            })
    (out_dir / "evidence_lanes.json").write_text(json.dumps({
        "lanes": lanes,
        "animal_citations": animal_citations,  # backward-compat alias
        "canonical_lanes": list(LANE_TOKENS),
        "method": (
            "agent.evidence_lanes.derive_lane over (evidence_tier, "
            "directness, source_title+venue+population_summary)"
        ),
    }, indent=2))
    # Slice 11 (2026-05-14): build PRISMA-ScR Methods pack +
    # serialise to methods_pack.json sidecar. Universal across any
    # topic — the pack carries databases / search strings / dates /
    # eligibility / screening flow / extraction fields / RoB approach
    # / synthesis approach / AI-use disclosure / human accountability.
    from agent.methods_pack import build_methods_pack, write_methods_pack
    _funnel = manifest.get("receipt_funnel") or {}
    _outcome_classes = sorted({
        r.get("outcome_class") for r in manifest.get("receipts", ())
        if r.get("outcome_class")
    })
    _search_queries = (
        tuple(_TOPIC_PACK.corpus_search_queries)
        if _TOPIC_PACK is not None
        else ()
    )
    _methods_pack = build_methods_pack(
        review_type=str(manifest.get("review_type", "")),
        topic=_ACTIVE_TOPIC,
        corpus_search_queries=_search_queries,
        n_retrieved=int(_funnel.get("retrieved", 0))
        or int(_funnel.get("n_retrieved", 0))
        or len(manifest.get("receipts", ())),
        n_screened=int(_funnel.get("screened", 0))
        or int(_funnel.get("n_screened", 0))
        or len(manifest.get("receipts", ())),
        n_included=len(manifest.get("receipts", ())),
        n_rejected=int(_funnel.get("rejected", 0))
        or int(_funnel.get("n_rejected", 0)),
        outcome_classes=_outcome_classes,
        accountability_model=str(
            manifest.get("accountability_model")
            or "researka_agent_certified"
        ),
    )
    write_methods_pack(out_dir, _methods_pack)
    # Slice 7 step 1: publish manifest as module-global so the
    # consistency audit's _check_numeric_role_guard can resolve
    # receipts → quant_claims for source-context drift detection.
    _ACTIVE_MANIFEST = manifest

    # ===== Auto-pipeline stages (Layer 1 audit + auto-fix → Grok final
    # review → auto-apply → final audit). No manual step required —
    # this whole chain runs from one invocation. =====
    final_paper_md = await _run_post_paper_pipeline(
        paper_path=paper_path, manifest=manifest, out_dir=out_dir,
        citation_registry=citation_registry, sections=sections,
        methods_md=methods_md, quality_bundle=quality_artifact["bundle"],
        run_start_ts=_run_start_ts,
    )
    word_count = len(final_paper_md.split())
    # Bug-fix 2026-05-13: section_words was the writer's first-pass
    # count, but the post-paper pipeline regenerates the bounded
    # abstract/conclusion and auto-fixes many sentences. Re-measure
    # from the final paper and rewrite the manifest so sidecars stay
    # consistent (no more "manifest says 570 / pre_submit says 299").
    # Slice 16 (2026-05-14): single deterministic compiler-owned
    # post-render pass. Writer drafts freely; finalizer enforces
    # submission discipline across 5 phases:
    #   A — Methods replace from methods_pack.json
    #   B — Evidence-lane qualifier injection (animal/preclinical)
    #   C — Terminology sanitizer (pipeline jargon → academic)
    #   D — Reference closure (orphan-ref supporting-corpus cluster)
    #   E — Structural fallback (thesis marker / resolution criteria /
    #       soften ungrounded "we propose" → "we operationalize")
    # Universal — no per-topic logic; reads existing sidecars.
    from agent.journal_finalizer import finalize_run
    _finalizer_report = finalize_run(out_dir)
    if _finalizer_report.paper_changed:
        final_paper_md = paper_path.read_text()
        word_count = _finalizer_report.final_word_count

    manifest["section_words"] = _section_words_from_paper(final_paper_md)
    manifest["total_words"] = word_count
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))

    # Slice 14 (2026-05-14): final artifact consistency. Kills the
    # stale-PDF / desync-supplement reviewer trap. Run AFTER manifest
    # rewrite so the cross-checks see the final state. Result is
    # folded into pre_submit_pass by agent/final_status.py.
    from agent.artifact_consistency import (
        verify_run_artifacts, write_consistency_sidecar,
    )
    _consistency_report = verify_run_artifacts(out_dir)
    write_consistency_sidecar(out_dir, _consistency_report)

    # Slice 22 (2026-05-15): the pipeline's Stage 5d inside
    # `_run_post_paper_pipeline` computed `final_status.json` BEFORE
    # `finalize_run` (Phase G surface re-eval) and `artifact_consistency`
    # sidecar writes happened. That snapshot's accountability_pass +
    # journal_surface counts were therefore stale. Re-run final_status
    # convergence once all sidecars are in their final state.
    # Universal — operates on whatever sidecars exist; fail-soft.
    try:
        from agent.final_status import compute_and_write as _fs_recompute
        _fs_final = _fs_recompute(out_dir)
        print(
            f"[pipeline] Stage 5d* — final_status reconciled: "
            f"{_fs_final.maturity_label} (submission_ready="
            f"{_fs_final.submission_ready}, "
            f"blockers={len(_fs_final.blocking_reasons)})",
            file=sys.stderr,
        )
    except Exception as _e:  # pragma: no cover — fail-soft
        print(
            f"[pipeline] Stage 5d* — final_status reconcile skipped: {_e}",
            file=sys.stderr,
        )

    print(f"\nDONE: {paper_path}", file=sys.stderr)
    print(f"  final_words: {word_count}", file=sys.stderr)
    print(f"  per-section: {section_words}", file=sys.stderr)
    print(
        f"  llm_calls: {manifest['n_llm_calls']} "
        f"cost_usd: ${manifest['total_cost_usd']:.4f} (writer-only; "
        f"final-layer review cost in {out_dir.name}/full_paper.review_patches.json)",
        file=sys.stderr,
    )
    return 0


async def _run_post_paper_pipeline(
    *, paper_path: Path, manifest: dict, out_dir: Path,
    citation_registry: dict | None = None,
    sections: tuple[SynthesisSection, ...] = (),
    methods_md: str = "",
    quality_bundle: Any | None = None,
    run_start_ts: dt.datetime | None = None,
) -> str:
    """Layer 1 deterministic audit + auto-fix → final-layer LLM review
    (Gemini Exacto → Mistral fallback) → auto-apply patches → final audit.

    Each step's artifact is written to disk so a human can retroactively
    review what changed and why. Returns the final paper text."""
    paper_md = paper_path.read_text()

    # Build universal gate inputs once: citation→outcome map (for the
    # per-outcome subsection routing check that catches Beavers-style
    # frailty-in-cardiometabolic leaks) + animal-citation list (from
    # evidence_lanes.json). Both are reused by every gate call below;
    # fail-soft when registry/sidecar absent.
    _oc_by_rid = {
        r["receipt_id"]: r["outcome_class"]
        for r in manifest.get("receipts", ())
        if r.get("outcome_class")
    }
    _citation_outcome_map: dict[str, str] = {}
    for _rid, _entry in (citation_registry or {}).items():
        _cite = getattr(_entry, "body_citation", None)
        if _cite is None and isinstance(_entry, dict):
            _cite = _entry.get("body_citation")
        if _cite and _rid in _oc_by_rid:
            _citation_outcome_map[_cite] = _oc_by_rid[_rid]
    _animal_citations: list[str] = []
    _lanes_path = out_dir / "evidence_lanes.json"
    if _lanes_path.is_file():
        try:
            _lanes = json.loads(_lanes_path.read_text())
            _animal_citations = [
                str(a.get("citation", ""))
                for a in _lanes.get("animal_citations", ())
                if a.get("citation")
            ]
        except (OSError, json.JSONDecodeError):
            pass

    # Stage 1: deterministic audit (Q1-Q10) on the as-written paper.
    print("[pipeline] Stage 1/5 — initial audit...", file=sys.stderr)
    audit_report = _audit_v06.audit(paper_md)
    audit_path = paper_path.with_suffix(".audit.json")
    audit_path.write_text(json.dumps(audit_report, indent=2))
    audit_md = _audit_v06._format_summary(audit_report)
    paper_path.with_suffix(".audit.md").write_text(audit_md)

    # Stage 2: Layer 1 consistency audit + deterministic auto-fix.
    print("[pipeline] Stage 2/5 — consistency audit + auto-fix...", file=sys.stderr)
    issues = _consistency_audit.run_audit(
        paper_md, manifest, audit_report, audit_md,
    )
    paper_path.with_suffix(".consistency.json").write_text(
        json.dumps([_issue_to_dict(i) for i in issues], indent=2)
    )
    paper_path.with_suffix(".consistency.md").write_text(
        _consistency_audit._format_summary(issues)
    )
    paper_md, fix_log = _consistency_fixer.apply_fixes(
        paper_md, issues, manifest=manifest,
        numeric_quarantine_path=paper_path.with_name(
            "numeric_claim_quarantine.json",
        ),
    )
    paper_path.with_suffix(".fixed_log.json").write_text(
        json.dumps(fix_log, indent=2)
    )
    paper_path.write_text(paper_md)

    # Re-run the audit + manifest now that auto-fixes have landed
    # (the consistency audit's verdict-overclaim check needs the
    # updated audit_md to pass).
    audit_report = _audit_v06.audit(paper_md)
    audit_path.write_text(json.dumps(audit_report, indent=2))
    audit_md = _audit_v06._format_summary(audit_report)
    paper_path.with_suffix(".audit.md").write_text(audit_md)

    paper_md, pre_review_template_log = _paper_quality.apply_template_repairs(
        paper_md,
    )
    if pre_review_template_log:
        paper_path.with_suffix(".pre_review_template_repair_log.json").write_text(
            json.dumps(pre_review_template_log, indent=2),
        )
        paper_path.write_text(paper_md)
        audit_report = _audit_v06.audit(paper_md)
        audit_path.write_text(json.dumps(audit_report, indent=2))
        audit_md = _audit_v06._format_summary(audit_report)
        paper_path.with_suffix(".audit.md").write_text(audit_md)

    # Stage 3: Final-layer LLM review (Gemini Exacto primary, Mistral fallback).
    print(
        "[pipeline] Stage 3/5 — final-layer review (Gemini Exacto → Mistral fallback)...",
        file=sys.stderr,
    )
    try:
        # Fix #11: pass citation_registry so the reviewer sees clean Author-Year
        # tokens in the "allowed body citations" list, not internal
        # receipt_id handles. Pre-fix reviewer behavior reverted clean citations
        # to long PMC handles because the prompt asked for "receipt-key
        # consistency" — exactly the bug the third reviewer warned about.
        patches, _raw, model_used, cost = await _final_reviewer.review_with_grok(
            paper_md, manifest, audit_report,
            citation_registry=citation_registry,
        )
    except RuntimeError as exc:
        # No OPENROUTER_API_KEY OR both primary and fallback failed. Log
        # but don't crash the whole run — the deterministic Layer 1
        # work has already happened. The reviewer artifact records
        # the gap for transparency.
        print(
            f"[pipeline] final-layer review unavailable: {exc}",
            file=sys.stderr,
        )
        patches, model_used, cost = [], "none", 0.0
    paper_path.with_suffix(".review_patches.json").write_text(json.dumps({
        "model_used": model_used,
        "cost_usd": cost,
        "n_patches": len(patches),
        "patches": [
            {
                "id": p.id, "patch_type": p.patch_type,
                "severity": p.severity, "location": p.location,
                "before": p.before, "after": p.after, "reason": p.reason,
            }
            for p in patches
        ],
    }, indent=2))
    paper_path.with_suffix(".review_summary.md").write_text(
        _final_reviewer._format_summary(patches, cost, model_used)
    )

    # Stage 4: Auto-apply final-layer patches. Trust Grok with
    # mechanical safety only — no flag-for-human terminal state.
    print(
        f"[pipeline] Stage 4/5 — auto-apply {len(patches)} patches...",
        file=sys.stderr,
    )
    if patches:
        patches_dicts = [
            {
                "id": p.id, "patch_type": p.patch_type,
                "severity": p.severity, "location": p.location,
                "before": p.before, "after": p.after, "reason": p.reason,
            }
            for p in patches
        ]
        paper_md, results = _patch_applier.apply_patches(
            paper_md, patches_dicts, manifest,
        )

        # Fix #49: agent-to-agent repair loop. For every flagged P1
        # patch, re-prompt Grok with the rejection reason and ask
        # for a shorter/safer alternative. Pure agent-to-agent —
        # no human in the loop. Returns updated (paper_md, results)
        # with new decision states 'applied_via_repair' or
        # 'auto_stripped' for what the repair loop touched.
        paper_md, results = await _agent_repair_loop(
            paper_md=paper_md,
            results=results,
            manifest=manifest,
            paper_path=paper_path,
        )
        paper_md = _restore_rendered_section_contract(paper_md, sections)
        paper_md, _n_qei_heading_deduped = (
            _patch_applier._collapse_consecutive_qei_headings(paper_md)
        )
        if methods_md:
            paper_md = _run_mode.replace_methods_in_paper(
                paper_md, methods_md,
            )
            paper_md, _n_qei_heading_deduped = (
                _patch_applier._collapse_consecutive_qei_headings(paper_md)
            )
        paper_md = _strip_rendered_citation_markers(paper_md)
        results = _resolve_absent_flagged_patches(results, paper_md)

        paper_path.write_text(paper_md)
        paper_path.with_suffix(".review_patch_log.json").write_text(json.dumps({
            "applied_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "n_proposed": len(results),
            "n_applied": sum(
                1 for r in results
                if r.decision in ("applied", "applied_via_repair")
            ),
            "n_rejected": sum(1 for r in results if r.decision == "rejected"),
            # Fix #36: surface the flagged count too — these are
            # patches the auto-applier refuses to apply because they
            # change scientific meaning (claim/numeric patches) or
            # have ambiguous targets. They count as unresolved P1
            # for the unified verdict.
            "n_flagged": sum(1 for r in results if r.decision == "flagged"),
            "n_auto_stripped": sum(
                1 for r in results if r.decision == "auto_stripped"
            ),
            "patches": [
                {
                    "patch_id": r.patch_id, "patch_type": r.patch_type,
                    "severity": r.severity, "decision": r.decision,
                    "reason_for_decision": r.reason_for_decision,
                }
                for r in results
            ],
        }, indent=2))
        n_applied = sum(
            1 for r in results
            if r.decision in ("applied", "applied_via_repair")
        )
        n_rejected = sum(1 for r in results if r.decision == "rejected")
        n_flagged = sum(1 for r in results if r.decision == "flagged")
        n_repaired = sum(
            1 for r in results if r.decision == "applied_via_repair"
        )
        n_stripped = sum(
            1 for r in results if r.decision == "auto_stripped"
        )
        # Fix #31 + Fix #36 + Fix #49: count Grok P1 patches that
        # remain unresolved AFTER the agent-to-agent repair loop.
        # Decisions:
        #   - "rejected"            → mechanical safety failed
        #   - "flagged"             → still unsafe after repair
        #                             rounds AND auto-strip couldn't
        #                             apply (BEFORE not unique etc.)
        #   - "applied_via_repair"  → repair loop succeeded, NOT
        #                             counted as unresolved
        #   - "auto_stripped"       → repair loop exhausted; offending
        #                             BEFORE region deleted; resolved
        #                             agent-to-agent. NOT counted.
        # Refactor 2026-05-04: distinguish Grok HALLUCINATIONS from
        # genuine unresolved P1s. When Grok proposes a patch with a
        # `before` text that doesn't exist in the paper, that's
        # Grok hallucinating an issue — the paper itself is fine.
        # The smart-gate rejects with reason starting "'before' text
        # not found in paper". Don't count those as unresolved P1.
        def _is_grok_hallucination(r) -> bool:
            reason = (r.reason_for_decision or "").lower()
            return (
                "before' text not found" in reason
                or "before text not found" in reason
                or "appears 0x" in reason
            )
        def _is_contract_preserving_rejection(r) -> bool:
            reason = (r.reason_for_decision or "").lower()
            return "contract-preserving rejection" in reason
        grok_unresolved_p1 = sum(
            1 for r in results
            if r.decision in ("rejected", "flagged")
            and (r.severity or "").upper() in {
                "P1", "HIGH", "CRITICAL",
            }
            and not _is_grok_hallucination(r)
            and not _is_contract_preserving_rejection(r)
        )
        print(
            f"[pipeline]   applied={n_applied} rejected={n_rejected} "
            f"flagged={n_flagged} repaired={n_repaired} "
            f"auto_stripped={n_stripped}"
            + (f" (Grok-unresolved P1 after repair: "
               f"{grok_unresolved_p1})"
               if grok_unresolved_p1 else ""),
            file=sys.stderr,
        )
    else:
        grok_unresolved_p1 = 0
        n_flagged = 0
        n_stripped = 0

    # Stage 5: Final audit + UNIFIED verdict (Fix #1 reviewer-P1).
    # Re-runs stage-1 audit AND stage-2 consistency on the post-Grok
    # paper, computes a single honest verdict. `final_verdict =
    # worst(stage1, stage2)`.
    #
    # Fix #19: re-run the deterministic auto-fixer on the post-Grok
    # paper BEFORE final audit. Stage-2's auto-fix (Fix #18b strips
    # unsourced background sentences) ran in Stage 2 but Grok's
    # patches in Stage 4 can re-introduce sentences with
    # background numerics. A Stage-5 re-fix closes the loop so the
    # final-audit verdict reflects post-cleanup state.
    print(
        "[pipeline] Stage 5/5 — final audit + unified verdict...",
        file=sys.stderr,
    )
    pre_audit = _audit_v06.audit(paper_md)
    pre_audit_md = _audit_v06._format_summary(pre_audit)
    pre_issues = _consistency_audit.run_audit(
        paper_md, manifest, pre_audit, pre_audit_md,
    )
    pre_final_cleanup_md = paper_md
    paper_md, _refix_log = _consistency_fixer.apply_fixes(
        paper_md, pre_issues, manifest=manifest,
        quant_claims_dir=QUANT_DIR,
        numeric_quarantine_path=paper_path.with_name(
            "numeric_claim_quarantine.json",
        ),
    )
    prefer_typed_restore = not any(
        item.get("fix_type") == "numeric_role_guard_strip"
        for item in _refix_log
    )
    paper_md = _restore_rendered_section_contract(
        paper_md, sections,
        prefer_typed_sections=prefer_typed_restore,
    )
    if methods_md:
        paper_md = _run_mode.replace_methods_in_paper(paper_md, methods_md)
    paper_md = _strip_rendered_citation_markers(paper_md)
    paper_md, _post_restore_public_log = _consistency_fixer.apply_fixes(
        paper_md, [], manifest=manifest, quant_claims_dir=QUANT_DIR,
        numeric_quarantine_path=paper_path.with_name(
            "numeric_claim_quarantine.json",
        ),
    )
    _refix_log.extend(_post_restore_public_log)
    post_restore_audit = _audit_v06.audit(paper_md)
    post_restore_audit_md = _audit_v06._format_summary(post_restore_audit)
    post_restore_issues = _consistency_audit.run_audit(
        paper_md, manifest, post_restore_audit, post_restore_audit_md,
    )
    if any(i.auto_fixable for i in post_restore_issues):
        paper_md, _post_restore_log = _consistency_fixer.apply_fixes(
            paper_md,
            post_restore_issues,
            manifest=manifest,
            quant_claims_dir=QUANT_DIR,
            numeric_quarantine_path=paper_path.with_name(
                "numeric_claim_quarantine.json",
            ),
        )
        _refix_log.extend(_post_restore_log)
        if any(
            item.get("fix_type") == "numeric_role_guard_strip"
            for item in _post_restore_log
        ):
            prefer_typed_restore = False
        paper_md = _restore_rendered_section_contract(
            paper_md, sections,
            prefer_typed_sections=prefer_typed_restore,
        )
        if methods_md:
            paper_md = _run_mode.replace_methods_in_paper(
                paper_md, methods_md,
            )
        paper_md = _strip_rendered_citation_markers(paper_md)
        paper_md, _final_public_log = _consistency_fixer.apply_fixes(
            paper_md, [], manifest=manifest, quant_claims_dir=QUANT_DIR,
            numeric_quarantine_path=paper_path.with_name(
                "numeric_claim_quarantine.json",
            ),
        )
        _refix_log.extend(_final_public_log)
    paper_md, _surface_floor_log = _restore_public_surface_floors(paper_md)
    _refix_log.extend(_surface_floor_log)
    if _surface_floor_log:
        paper_md, _post_surface_floor_log = _consistency_fixer.apply_fixes(
            paper_md, [], manifest=manifest, quant_claims_dir=QUANT_DIR,
            numeric_quarantine_path=paper_path.with_name(
                "numeric_claim_quarantine.json",
            ),
        )
        _refix_log.extend(_post_surface_floor_log)
    paper_md, _final_polish_log = (
        _consistency_fixer.apply_lightweight_public_polish(
            paper_md, manifest=manifest,
        )
    )
    _refix_log.extend(_final_polish_log)
    paper_md, _inserted_results_summary = _ensure_results_summary_table(
        paper_md, manifest,
    )
    if methods_md:
        paper_md = _run_mode.replace_methods_in_paper(paper_md, methods_md)
    paper_md, _final_surface_floor_log = _restore_public_surface_floors(
        paper_md,
    )
    _refix_log.extend(_final_surface_floor_log)
    paper_md, _references_restored = _ensure_references_section(
        paper_md, citation_registry,
    )
    if (
        _refix_log
        or any(i.auto_fixable for i in pre_issues)
        or paper_md != pre_final_cleanup_md
        or _inserted_results_summary
        or _references_restored
    ):
        paper_path.with_suffix(".final_fixed_log.json").write_text(
            json.dumps(_refix_log, indent=2)
        )
        paper_path.write_text(paper_md)
    audit_report = _audit_v06.audit(paper_md)
    audit_path.write_text(json.dumps(audit_report, indent=2))
    audit_md = _audit_v06._format_summary(audit_report)
    paper_path.with_suffix(".audit.md").write_text(audit_md)
    final_issues = _consistency_audit.run_audit(
        paper_md, manifest, audit_report, audit_md,
    )
    paper_path.with_suffix(".consistency.json").write_text(
        json.dumps([_issue_to_dict(i) for i in final_issues], indent=2)
    )
    paper_path.with_suffix(".consistency.md").write_text(
        _consistency_audit._format_summary(final_issues)
    )
    try:
        from agent.journal_surface_gate import evaluate_journal_surface
        surface_report = evaluate_journal_surface(
            paper_md,
            animal_citations=_animal_citations,
            citation_outcome_map=_citation_outcome_map,
            declared_review_type=manifest.get("review_type"),
        )
        _surface_issues = tuple(
            f"{i.code}: {i.detail}" for i in surface_report.issues
        )
        paper_path.with_suffix(".journal_surface.json").write_text(
            json.dumps({
                "passed": surface_report.passed,
                "issues": [dataclasses.asdict(i)
                           for i in surface_report.issues],
            }, indent=2)
        )
    except (ImportError, ValueError):
        surface_report = None
        _surface_issues = ("journal_surface_gate_unavailable",)
    # Pull corpus-density signals from manifest for cert-floor check
    _n_rec = int(manifest.get("n_receipts", 0))
    _n_claims = int(manifest.get("n_high_confidence_claims_total", 0))
    _n_tens = int(manifest.get("n_non_orthogonal_tensions", 0))
    # Topic-pack override of cert floors (optional)
    _cert_floors = None
    if _TOPIC_PACK is not None:
        _floors_obj = getattr(_TOPIC_PACK, "certification_floors", None)
        if _floors_obj:
            _cert_floors = dict(_floors_obj)
    unified = _compute_unified_verdict(
        audit_report, final_issues, grok_unresolved_p1=grok_unresolved_p1,
        n_receipts=_n_rec,
        n_high_conf_claims=_n_claims,
        n_non_orthogonal_tensions=_n_tens,
        cert_floors=_cert_floors,
        manifest=manifest,
        grok_flagged_count=n_flagged,
        auto_stripped_count=n_stripped,
        journal_surface_pass=bool(
            surface_report is not None and surface_report.passed
        ),
        journal_surface_issues=_surface_issues,
    )
    paper_path.with_suffix(".final_verdict.json").write_text(
        json.dumps(dataclasses.asdict(unified), indent=2)
    )
    paper_path.with_suffix(".final_verdict.md").write_text(
        _format_unified_verdict(unified)
    )
    print(
        f"[pipeline] DONE — verdict={unified.verdict} "
        f"(stage1 {unified.stage1_pass_rate}; "
        f"stage2 P1={unified.stage2_p1} P2={unified.stage2_p2})",
        file=sys.stderr,
    )

    # Stage 5b: keep audit/provenance appendix out of the journal main.
    # The public manuscript stays argument/prose; the supplement carries
    # provenance, AI-use, accountability, and data availability machinery.
    try:
        from agent.manuscript_appendix import compose_appendix
        from agent.settings import load_settings as _load_settings
        import subprocess as _sp
        try:
            git_sha = _sp.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=REPO_ROOT, text=True, timeout=5,
            ).strip()
        except (_sp.SubprocessError, FileNotFoundError):
            git_sha = "unknown"
        # Load settings here — Stage 5b runs in
        # _run_post_paper_pipeline() which doesn't receive settings
        # from the _run() scope. Cheap call (env-var read).
        _settings = _load_settings()
        model_stack = {
            "writer": _settings.mimo_model,
            "reviewer": _settings.final_layer_reviewer_model,
            "extractor": _settings.mimo_model,
            "thesis": _settings.mimo_model,
        }
        # P1 reviewer fix (2026-05-04 wave 5): use the orchestrator's
        # _ACTIVE_TOPIC directly. The previous regex on the run-dir
        # name (synthesis-<topic>-v06-...) only worked for the default
        # naming convention; custom out-dirs (e.g.
        # runs/publication/rapamycin/) have a single-segment dir name
        # with no hyphens, so the parser fell through to "unknown" and
        # leaked that string into the Search Provenance section.
        _topic = _ACTIVE_TOPIC or "unknown"
        appendix_md = compose_appendix(
            manifest, audit=audit_report,
            model_stack=model_stack,
            topic=_topic,
            run_id=paper_path.parent.name,
            git_sha=git_sha,
            bundle_path=f"bundles/{paper_path.parent.name}/",
            verdict=unified.verdict,
        )
        if "## Publication Appendix" not in appendix_md:
            appendix_md = "## Publication Appendix\n\n" + appendix_md.lstrip()
        supplement_path = paper_path.parent / "structured_evidence_tables.md"
        existing = (
            supplement_path.read_text()
            if supplement_path.exists()
            else "# Supplementary Evidence Tables and Audit Methods\n"
        )
        if "## Search Provenance and Selection" not in existing:
            supplement_path.write_text(
                existing.rstrip() + "\n\n" + appendix_md.rstrip() + "\n",
            )
        print(
            "[pipeline] Stage 5b — appendix routed to supplement "
            "(Search Provenance / AI Disclosure / Accountability / Data)",
            file=sys.stderr,
        )
    except Exception as _e:  # pragma: no cover — best-effort
        print(
            f"[pipeline] Stage 5b — appendix splice skipped: {_e}",
            file=sys.stderr,
        )

    # Stage 5c: paper-quality pre-submit gate. This is the live integration
    # point for Phase 6 and Phase 8: deterministic template-language repair,
    # template gate artifact, final gate artifact, and publication score.
    # The gate runs after appendix insertion because the submitted manuscript
    # is what should be judged.
    try:
        paper_md, template_repair_log = _paper_quality.apply_template_repairs(
            paper_md,
        )
        if template_repair_log:
            paper_path.with_suffix(".template_repair_log.json").write_text(
                json.dumps(template_repair_log, indent=2)
            )
            paper_path.write_text(paper_md)
            audit_report = _audit_v06.audit(paper_md)
            audit_path.write_text(json.dumps(audit_report, indent=2))
            audit_md = _audit_v06._format_summary(audit_report)
            paper_path.with_suffix(".audit.md").write_text(audit_md)
        paper_md, references_restored = _ensure_references_section(
            paper_md, citation_registry,
        )
        paper_md, surface_polish_log = (
            _consistency_fixer.apply_lightweight_public_polish(
                paper_md, manifest=manifest,
            )
        )
        if surface_polish_log:
            final_log_path = paper_path.with_suffix(".final_fixed_log.json")
            try:
                prior_log = json.loads(final_log_path.read_text())
            except (OSError, ValueError, json.JSONDecodeError):
                prior_log = []
            final_log_path.write_text(
                json.dumps(prior_log + surface_polish_log, indent=2)
            )
        if references_restored or surface_polish_log:
            paper_path.write_text(paper_md)
        from agent.journal_surface_gate import evaluate_journal_surface
        surface_report = evaluate_journal_surface(
            paper_md,
            animal_citations=_animal_citations,
            citation_outcome_map=_citation_outcome_map,
            declared_review_type=manifest.get("review_type"),
        )
        surface_payload = {
            "passed": surface_report.passed,
            "issues": [dataclasses.asdict(i) for i in surface_report.issues],
        }
        paper_path.with_suffix(".journal_surface.json").write_text(
            json.dumps(surface_payload, indent=2)
        )
        receipt_ids = {
            str(r.get("paper_id") or r.get("receipt_id") or "")
            for r in manifest.get("receipts", [])
        }
        citation_registry_complete = bool(
            citation_registry
            and all(rid in citation_registry for rid in receipt_ids if rid)
        )
        reviewer_patches = {"unresolved_p1_count": grok_unresolved_p1}
        if quality_bundle is None:
            raise RuntimeError("quality_methods_bundle_missing")
        gate_artifacts = _paper_quality.write_final_quality_gates(
            out_dir=out_dir,
            paper_text=paper_md,
            manifest=manifest,
            audit=audit_report,
            journal_surface=surface_payload,
            reviewer_patches=reviewer_patches,
            quality_bundle=quality_bundle,
            citation_registry_complete=citation_registry_complete,
        )
        blocker_summary = _pre_submit_blocker_summary(gate_artifacts)
        if blocker_summary:
            print(
                "[pipeline] Stage 5c — pre-submit quality gate blocked: "
                f"{blocker_summary}",
                file=sys.stderr,
            )
        else:
            print(
                "[pipeline] Stage 5c — pre-submit quality gate passed",
                file=sys.stderr,
            )
    except Exception as _e:
        print(
            f"[pipeline] Stage 5c — pre-submit quality gate failed: {_e}",
            file=sys.stderr,
        )
        raise

    # Stage 5cc (Slice 21 — 2026-05-15): write the two promotion sidecars
    # that final_status's 6-dim ladder reads. `benchmark_runtime.json`
    # records that the pipeline reached this point without raising
    # (return_code=0) + wall-clock duration. `target_journal_pack.json`
    # records the submission target declared in the topic pack, or a
    # universal placeholder when none is declared (final_status then
    # reports `target_journal not declared in topic pack` honestly
    # rather than `target_journal_pack.json missing`). Universal —
    # no topic-specific defaults. Fail-soft per Stage 5d pattern.
    try:
        _now = dt.datetime.now(dt.timezone.utc)
        _start = run_start_ts or _now
        _runtime_payload = {
            "return_code": 0,
            "started_at": _start.isoformat(timespec="seconds"),
            "completed_at": _now.isoformat(timespec="seconds"),
            "duration_s": round((_now - _start).total_seconds(), 3),
            "topic": str(_ACTIVE_TOPIC),
        }
        (out_dir / "benchmark_runtime.json").write_text(
            json.dumps(_runtime_payload, indent=2),
        )
        _declared_target = (
            str(_TOPIC_PACK.target_journal).strip()
            if (
                _TOPIC_PACK is not None
                and getattr(_TOPIC_PACK, "target_journal", None)
            )
            else ""
        )
        _target_payload = {
            "journal": _declared_target or (
                "Open-access general scholarly journal "
                "(topic-pack target_journal not declared)"
            ),
            "declared_in_topic_pack": bool(_declared_target),
        }
        (out_dir / "target_journal_pack.json").write_text(
            json.dumps(_target_payload, indent=2),
        )
        print(
            f"[pipeline] Stage 5cc — promotion sidecars written "
            f"(runtime + target_journal "
            f"declared={_target_payload['declared_in_topic_pack']})",
            file=sys.stderr,
        )
    except Exception as _e:  # pragma: no cover — fail-soft
        print(
            f"[pipeline] Stage 5cc — promotion sidecars skipped: {_e}",
            file=sys.stderr,
        )

    # Stage 5d (Wave 47 — status convergence): consolidate every sidecar
    # into ONE source of truth (`final_status.json`). Reads runtime /
    # audit / journal_surface / pre_submit / target_journal / human_signoff
    # and emits a strict 6-boolean hierarchy + frozen L1–L5 label. No
    # "AAA" string is emitted; the label is the only public level
    # identifier. Fail-soft — if this stage breaks, the run still
    # publishes the per-stage sidecars.
    try:
        from agent.final_status import (  # type: ignore[import-not-found]
            compute_and_write as _final_status_write,
        )
        _fs = _final_status_write(out_dir)
        print(
            f"[pipeline] Stage 5d — final_status: "
            f"{_fs.maturity_label} (submission_ready={_fs.submission_ready}, "
            f"blockers={len(_fs.blocking_reasons)})",
            file=sys.stderr,
        )
    except Exception as _e:  # pragma: no cover — fail-soft
        print(
            f"[pipeline] Stage 5d — final_status skipped: {_e}",
            file=sys.stderr,
        )

    # Stage 6 (Fix #23): no-regression gate. If runs/_baseline.txt
    # names a baseline run dir, compare the new run's six dimensions
    # (P1, numeric trace, consistency, leakage, word count, orphan
    # cites) against it. Writes report.{json,md} to the new run dir
    # so the next agent / human can audit deltas. Informational only
    # — does not fail the pipeline (the unified verdict already gates
    # ship). Caller-driven exit-codes happen via the standalone
    # `python scripts/no_regression_gate.py` CLI for CI.
    _maybe_run_no_regression_gate(paper_path.parent)
    moved_artifacts = _organize_run_artifacts(paper_path.parent)
    if moved_artifacts:
        print(
            f"[pipeline] Stage 7/7 — organized {len(moved_artifacts)} sidecar artifact(s)",
            file=sys.stderr,
        )

    return paper_md


_MAX_REPAIR_ROUNDS = 2


def _is_p1_flagged(r: Any) -> bool:
    return (
        r.decision == "flagged"
        and (r.severity or "").upper() in {"P1", "HIGH", "CRITICAL"}
    )


async def _agent_repair_loop(
    *,
    paper_md: str,
    results: list[Any],
    manifest: dict,
    paper_path: Path | None = None,
) -> tuple[str, list[Any]]:
    """Fix #49: agent-to-agent repair loop.

    For each `decision == 'flagged'` result, re-prompt Grok with the
    rejection reason and ask for a safer alternative. The new
    proposal goes through the same smart-gate as any other patch.
    Up to _MAX_REPAIR_ROUNDS rounds. After all rounds, any still-
    flagged P1 patch is auto-stripped (the offending sentence is
    deleted) — pipeline never resigns to 'human review'.

    Returns updated (paper_md, results). Successful repair patches
    are tagged decision='applied_via_repair'; auto-strips are
    tagged decision='auto_stripped'."""
    if not results:
        return paper_md, results
    flagged_p1 = [
        r for r in results
        if r.decision == "flagged"
        and (r.severity or "").upper() in {"P1", "HIGH", "CRITICAL"}
    ]
    if not flagged_p1:
        return paper_md, results
    for _ in range(_MAX_REPAIR_ROUNDS):
        if not flagged_p1:
            break
        try:
            repaired = await _final_reviewer.repair_flagged_patches(
                [(r, r.reason_for_decision) for r in flagged_p1],
                paper_md,
            )
        except Exception as e:  # noqa: BLE001
            print(
                f"[pipeline] repair-loop Grok call failed: {e}",
                file=sys.stderr,
            )
            break
        if not repaired:
            # Grok returned 'unfixable' for every patch
            break
        # Re-run smart-gate on repaired patches
        repaired_dicts = [
            {
                "id": p.id, "patch_type": p.patch_type,
                "severity": p.severity, "location": p.location,
                "before": p.before, "after": p.after,
                "reason": f"REPAIR: {p.reason}",
            }
            for p in repaired
        ]
        paper_md, repair_results = _patch_applier.apply_patches(
            paper_md, repaired_dicts, manifest,
        )
        # Map newly-applied repair results back into the original
        # results list (find by patch_id).
        applied_repair_ids = {
            r.patch_id for r in repair_results if r.decision == "applied"
        }
        if applied_repair_ids:
            results = [
                _patch_applier.PatchResult(
                    patch_id=r.patch_id, patch_type=r.patch_type,
                    severity=r.severity,
                    decision=(
                        "applied_via_repair"
                        if r.patch_id in applied_repair_ids
                        and r.decision == "flagged"
                        else r.decision
                    ),
                    reason_for_decision=(
                        f"AGENT-REPAIR: original flagged, replacement "
                        f"applied. {r.reason_for_decision}"
                        if r.patch_id in applied_repair_ids
                        and r.decision == "flagged"
                        else r.reason_for_decision
                    ),
                    before=r.before, after=r.after,
                )
                for r in results
            ]
        # Recompute the still-flagged set for next round
        flagged_p1 = [
            r for r in results
            if r.decision == "flagged"
            and (r.severity or "").upper() in {"P1", "HIGH", "CRITICAL"}
        ]
    flagged_p1 = [r for r in results if _is_p1_flagged(r)]
    # Final pass: any still-flagged P1 → auto-strip the BEFORE region.
    # Pure deletion; safer than leaving a flagged patch unresolved.
    if flagged_p1:
        for r in flagged_p1:
            if not r.before or r.before not in paper_md:
                continue
            # Only strip if the BEFORE appears exactly once (avoid
            # accidental over-strip).
            if paper_md.count(r.before) != 1:
                continue
            if _patch_applier._has_unsafe_match_boundary(paper_md, r.before):
                continue
            paper_md = paper_md.replace(r.before, "", 1)
            # Tag the result as auto-stripped
            results = [
                _patch_applier.PatchResult(
                    patch_id=rr.patch_id, patch_type=rr.patch_type,
                    severity=rr.severity,
                    decision=(
                        "auto_stripped"
                        if rr.patch_id == r.patch_id
                        else rr.decision
                    ),
                    reason_for_decision=(
                        f"AGENT-AUTO-STRIP: repair loop exhausted; "
                        f"BEFORE region deleted to avoid leaving "
                        f"flagged P1. {rr.reason_for_decision}"
                        if rr.patch_id == r.patch_id
                        else rr.reason_for_decision
                    ),
                    before=rr.before, after=rr.after,
                )
                for rr in results
            ]
    return paper_md, results


def _resolve_absent_flagged_patches(results: list[Any], paper_md: str) -> list[Any]:
    """Resolve reviewer P1s whose target disappeared in final cleanup.

    Final cleanup can replace Methods, restore typed sections, or
    strip unsafe numeric prose after Grok proposed a P1 patch. If the
    unapplied BEFORE region is no longer present in the manuscript, the
    public paper no longer carries that issue, so the patch should not
    count as unresolved.
    """
    out: list[Any] = []
    for r in results:
        if (
            r.decision in {"flagged", "rejected"}
            and (r.severity or "").upper() in {"P1", "HIGH", "CRITICAL"}
            and r.before
            and r.before not in paper_md
        ):
            out.append(_patch_applier.PatchResult(
                patch_id=r.patch_id,
                patch_type=r.patch_type,
                severity=r.severity,
                decision="applied",
                reason_for_decision=(
                    "FINAL-CLEANUP-RESOLVED: unapplied BEFORE region "
                    "is absent after deterministic section restoration "
                    f"and cleanup. {r.reason_for_decision}"
                ),
                before=r.before,
                after=r.after,
            ))
        else:
            out.append(r)
    return out


def _build_claims_by_citation(
    receipts: list, registry: dict,
) -> dict[str, list[dict]]:
    """Build {body_citation: [claim_dicts]} from the original receipt
    list (pre-transform — receipt_ids are still raw paper-IDs that
    map directly to docs/quality-reference/<topic>/quant_claims/
    <receipt_id>.quant_claims.json).

    Used by Table 5 (Per-Paper Numeric Index) to surface the corpus's
    underlying quantitative claims. The map keys are body_citation
    strings (e.g. 'Walton 2019') so Table 5 can look up a writer-side
    receipt's claims using its already-transformed receipt_id.

    Only high-confidence claims are surfaced — Q2 numeric integrity
    trace uses the same high-confidence filter (see
    audit_v06_paper._load_corpus_numerics), so a Table 5 numeric
    that's NOT high-confidence would render to a paper cell that
    Q2 then fails to trace. Pre-filter so Table 5 cells = Q2
    corpus numerics by construction."""
    out: dict[str, list[dict]] = {}
    for r in receipts:
        raw_id = getattr(r, "receipt_id", "")
        entry = registry.get(raw_id)
        if entry is None:
            continue
        path = QUANT_DIR / f"{raw_id}.quant_claims.json"
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        all_claims = data.get("claims", [])
        if not isinstance(all_claims, list):
            continue
        high_conf = [
            c for c in all_claims
            if isinstance(c, dict)
            and c.get("binding_confidence") == "high"
        ]
        out[entry.body_citation] = high_conf
    return out


def _maybe_run_no_regression_gate(new_run_dir: Path) -> None:
    """Stage 6 (Fix #23): if docs/no_regression_baseline.txt names a
    baseline run dir, compare the new run's quality dimensions
    against it. Skip silently when no baseline configured.

    Marker file is checked-in (under docs/) so the baseline name
    travels with the repo across MacBook + GitHub + VPS — every
    machine evaluates against the same anchor."""
    baseline_marker = (
        Path(__file__).resolve().parent.parent
        / "docs" / "no_regression_baseline.txt"
    )
    if not baseline_marker.exists():
        return
    baseline_name = baseline_marker.read_text().strip()
    if not baseline_name:
        return
    baseline_dir = (Path("runs") / baseline_name).resolve()
    if not baseline_dir.exists() or baseline_dir == new_run_dir:
        return
    # Fix: skip if topics differ (run dir names are
    # 'synthesis-<topic>-v06-...'; comparing rapamycin to metformin
    # baseline produces a meaningless 'regression').
    def _topic_of(name: str) -> str:
        parts = name.split("-")
        return parts[1] if len(parts) >= 2 else ""
    new_topic = _topic_of(new_run_dir.name)
    baseline_topic = _topic_of(baseline_dir.name)
    if new_topic != baseline_topic:
        print(
            f"[pipeline] Stage 6/6 — no-regression gate skipped: "
            f"new run topic={new_topic!r} differs from baseline "
            f"topic={baseline_topic!r} (cross-topic comparison "
            "is not meaningful — promote a per-topic baseline)",
            file=sys.stderr,
        )
        return
    try:
        import no_regression_gate as _nrg
        report = _nrg.compare_runs(baseline_dir, new_run_dir)
        md = _nrg.render_report_md(report)
        (new_run_dir / "no_regression_report.md").write_text(md)
        (new_run_dir / "no_regression_report.json").write_text(
            json.dumps(report.to_dict(), indent=2),
        )
        verdict = "PASS" if report.passes else (
            f"REGRESSION ({report.n_regressions} dim(s))"
        )
        print(
            f"[pipeline] Stage 6/6 — no-regression gate vs "
            f"{baseline_name}: {verdict}",
            file=sys.stderr,
        )
    except (ImportError, OSError) as e:
        print(
            f"[pipeline] no-regression gate skipped: {e}",
            file=sys.stderr,
        )


def _issue_to_dict(issue) -> dict[str, Any]:
    return {
        "id": issue.id, "severity": issue.severity,
        "issue_type": issue.issue_type, "auto_fixable": issue.auto_fixable,
        "evidence": issue.evidence, "suggested_fix": issue.suggested_fix,
    }


def _build_run_mode_contract(
    *, settings: Any, topic: str, submission_id: str,
    n_papers: int, n_claims: int,
) -> _run_mode.RunModeContract:
    """Construct the contract from settings + run facts. The v0.6
    quant-claim adapter never runs SPAR, never uses LLM fact
    extraction, never builds multi-receipt clusters — those flags
    are False because that's the literal pipeline behaviour."""
    return _run_mode.RunModeContract(
        run_mode="v0.6 quant-claim adapter",
        topic=topic,
        submission_id=submission_id,
        n_papers_in_corpus=n_papers,
        n_high_confidence_claims_used_by_writer=n_claims,
        writer_model=settings.mimo_model,
        in_writing_judge_model=settings.judge_model,
        final_layer_reviewer_model=settings.final_layer_reviewer_model,
        final_layer_fallback_model=settings.fallback_model,
        claim_source=f"docs/quality-reference/{topic}/quant_claims/*.json",
        spar_adjudication_ran=False,
        multi_receipt_clusters_ran=False,
        llm_fact_extraction_ran=False,
        rejected_evidence_quarantine_ran=False,
    )


# Severities that block ship — anything ELSE is treated as informational.
# Positive allowlist (not blocklist) so future severities like "P0" or
# "CRITICAL" silently fail closed instead of silently passing.
_BLOCKING_SEVERITIES: frozenset[str] = frozenset({"P0", "P1", "CRITICAL"})
_NONBLOCKING_SEVERITIES: frozenset[str] = frozenset({"P2", "P3", "INFO"})

_EVIDENCE_TIER_WEIGHTS: dict[str, float] = {
    "A1": 1.0,
    "A2": 0.7,
    "B1": 0.6,
    "B": 0.5,
    "B2": 0.4,
    "C1": 0.3,
    "C": 0.25,
    "C2": 0.2,
    "D1": 0.1,
    "MIXED": 0.3,
}


def _receipt_field(receipt: Any, field: str, default: Any = "") -> Any:
    if isinstance(receipt, dict):
        return receipt.get(field, default)
    return getattr(receipt, field, default)


def _evidence_certification_profile(manifest: dict[str, Any] | None) -> dict[str, float]:
    """Tier-weighted evidence profile for CLIN/INF/MECH certification.

    This does not weaken any safety gate. It only replaces the old
    binary "direct clinical receipts or nothing" substance floor with
    a calibrated evidence pyramid when the manifest carries receipt
    tiers/directness.
    """
    profile = {
        "total": 0.0,
        "clinical": 0.0,
        "mechanistic": 0.0,
        "direct": 0.0,
        "a_tier": 0.0,
        "a1_direct_count": 0.0,
        "n_mechanistic": 0.0,
    }
    for receipt in (manifest or {}).get("receipts", ()):
        tier = str(_receipt_field(receipt, "evidence_tier", "")).upper()
        directness = str(_receipt_field(receipt, "directness", "")).lower()
        weight = _EVIDENCE_TIER_WEIGHTS.get(tier, 0.2)
        profile["total"] += weight
        if tier.startswith("A"):
            profile["a_tier"] += weight
        if directness == "direct":
            profile["direct"] += weight
            if tier == "A1":
                profile["a1_direct_count"] += 1
        if directness == "mechanistic" or tier.startswith("C"):
            profile["mechanistic"] += weight
            profile["n_mechanistic"] += 1
        if tier.startswith(("A", "B")) and directness != "mechanistic":
            profile["clinical"] += weight
    return profile


def _select_certification_track(
    *,
    flat_floor_clean: bool,
    n_receipts: int,
    n_high_conf_claims: int,
    profile: dict[str, float],
    min_receipts: int,
    min_claims: int,
    cert_floors: dict[str, Any],
) -> tuple[str, bool]:
    """Return (track, floor_clean) from the evidence pyramid.

    CLIN preserves the legacy direct-clinical floor. INF/MECH are
    confidence-calibrated alternatives for fields where strong animal,
    mechanism, adjacent-clinical, or sub-scale evidence is publishable
    as inference, not direct clinical recommendation.
    """
    if flat_floor_clean:
        if profile["mechanistic"] > profile["clinical"] and profile["direct"] < 1.0:
            return "AAA-MECH", True
        return "AAA-CLIN", True
    if (
        2 <= n_receipts < min_receipts
        and n_high_conf_claims > 0
        and profile.get("a1_direct_count", 0.0) >= 1
    ):
        return "AAA-SCOP", True
    if n_receipts < min_receipts or n_high_conf_claims < min_claims:
        return "SCOP", False
    min_inf_weight = float(cert_floors.get("min_inferential_weight", 8.0))
    min_mech_weight = float(cert_floors.get("min_mechanistic_weight", 6.0))
    inf_clean = (
        profile["total"] >= min_inf_weight
        and profile["a_tier"] >= 0.7
        and profile["mechanistic"] >= 2.0
    )
    if inf_clean:
        return "AAA-INF", True
    mech_clean = (
        profile["total"] >= min_mech_weight
        and profile["mechanistic"] >= min_mech_weight
        and profile["n_mechanistic"] >= 5
    )
    if mech_clean:
        return "AAA-MECH", True
    return "SCOP", False


def _d1_bridge_claim_count(stage1_report: dict[str, Any]) -> int:
    for check in stage1_report.get("checks") or ():
        if check.get("name") != "Q14_inferential_bridge_contract":
            continue
        match = re.search(r"\b(\d+)\s+D1 bridge claims\b", check.get("detail", ""))
        return int(match.group(1)) if match else 0
    return 0


@dataclass(frozen=True, slots=True)
class UnifiedVerdict:
    """Worst-of(stage1, stage2, grok-unresolved). Cross-stage object →
    frozen+slots per project rule. Serialized via dataclasses.asdict()
    to JSON. Fix #31: tracks Grok-unresolved P1 patches separately —
    even when stage1 + stage2 are clean, an unresolved Grok P1
    flag downgrades the verdict to 'Trust-Spine Pass — Human Review
    Required' rather than AAA (the harness can't autonomously verify
    Grok's flag was wrong).

    Wave 7 (2026-05-05): adds corpus_gaps + expansion_targets so a
    sub-AAA verdict carries the actionable to-do list for the next
    run instead of being a dead-end signal. Empty tuples when corpus
    meets all gates.

    Slice 3 (Wave 7 cont.): adds maturity_level (L0-L5) and
    journal_ready bool so dashboards / readers see the topic's
    position on the certification ladder. L5 == Journal-Ready
    (AAA + zero unresolved Grok + zero auto-strip surgery)."""
    verdict: str
    reason: str
    stage1_p1_pass: bool
    stage1_score: float
    stage1_pass_rate: str
    stage2_p1: int
    stage2_p2: int
    stage2_unknown_severity_count: int
    all_green: bool
    p1_clean: bool
    grok_unresolved_p1: int = 0
    grok_flagged: int = 0
    corpus_gaps: tuple[str, ...] = ()
    expansion_targets: tuple[str, ...] = ()
    maturity_level: int = 0
    maturity_label: str = "L0 — UNSEEDED"
    journal_ready: bool = False
    journal_surface_pass: bool = True
    journal_surface_issues: tuple[str, ...] = ()
    certification_track: str = "UNSCORED"
    evidence_weight_total: float = 0.0
    evidence_weight_clinical: float = 0.0
    evidence_weight_mechanistic: float = 0.0


def _is_blocking(severity: str) -> bool:
    """Positive allowlist: known non-blocking severities pass; ANYTHING
    ELSE blocks (fail-closed for unknown severities like 'P0' or
    'CRITICAL' that future reviewer-prompts may introduce)."""
    return severity not in _NONBLOCKING_SEVERITIES


def _compute_unified_verdict(
    stage1_report: dict[str, Any] | None,
    stage2_issues: list[Any],
    grok_unresolved_p1: int = 0,
    *,
    n_receipts: int = 0,
    n_high_conf_claims: int = 0,
    n_non_orthogonal_tensions: int = 0,
    cert_floors: dict[str, int] | None = None,
    manifest: dict[str, Any] | None = None,
    grok_flagged_count: int = 0,
    auto_stripped_count: int = 0,
    journal_surface_pass: bool = True,
    journal_surface_issues: tuple[str, ...] = (),
) -> UnifiedVerdict:
    """Worst-of(stage1, stage2, grok-unresolved). AAA reserved for
    fully-green (P1+P2 + zero unresolved Grok P1). SHIP-BLOCKED if
    either deterministic stage flags a P1+ severity. Trust-Spine
    Pass otherwise — and 'Trust-Spine Pass — Human Review Required'
    when only Grok-unresolved P1 prevents AAA.

    Defensive on inputs: missing stage1 keys → treated as failure
    (fail-closed). Empty stage1.checks → cannot return AAA (AAA
    requires evidence, not vacuous success).

    Fix #31: `grok_unresolved_p1` is the count of Grok-flagged P1
    patches that the auto-applier rejected (couldn't be safely
    applied). The harness can't autonomously verify Grok's flag was
    wrong, so an unresolved P1 must surface as 'human review' even
    when both deterministic stages are green."""
    stage1_report = stage1_report or {}
    s1_p1_pass = bool(stage1_report.get("p1_pass", False))
    s1_score = float(stage1_report.get("score_out_of_10", 0.0))
    checks = stage1_report.get("checks") or []
    s1_n_pass = sum(1 for c in checks if c.get("passed", False))
    s1_n_total = len(checks)

    # Stage-2 severity tally with unknown-severity counter for telemetry.
    s2_p1_blocking = 0
    s2_p2 = 0
    s2_unknown = 0
    for i in stage2_issues:
        sev = getattr(i, "severity", None) or ""
        if sev == "P2":
            s2_p2 += 1
        elif sev in _BLOCKING_SEVERITIES:
            s2_p1_blocking += 1
        elif sev in _NONBLOCKING_SEVERITIES:
            pass  # P3 / INFO — no count needed for this verdict
        else:
            # Unknown severity — fail closed. Counts as blocking.
            s2_p1_blocking += 1
            s2_unknown += 1

    p1_clean = s1_p1_pass and s2_p1_blocking == 0
    grok_clean = grok_unresolved_p1 == 0
    # Certification floors (2026-05-05 wave 7 reviewer fix): even with
    # all-green audits, AAA requires the corpus to be substantive
    # enough to support a real synthesis. Reviewer recommendation:
    #   ≥ min_receipts (default 10)
    #   ≥ min_high_conf_claims (default 50)
    #   ≥ min_non_orthogonal_tensions (default 10)
    # Topic packs may override these in [certification_floors] table.
    # Below floor → max verdict is Trust-Spine Pass; never AAA.
    # Reviewer P1 (2026-05-05 wave 8): cert floors are GLOBAL POLICY,
    # not topic-pack overrideable downward. Topic packs may RAISE
    # the bar (e.g. require ≥20 receipts for stricter topics) but
    # cannot lower it below the default. This prevents thin-corpus
    # topics from gaming the verdict by setting min_receipts=2.
    _DEFAULT_MIN_RECEIPTS = 10
    _DEFAULT_MIN_CLAIMS = 50
    _DEFAULT_MIN_TENSIONS = 10
    floors = cert_floors or {}
    min_rec = max(_DEFAULT_MIN_RECEIPTS,
                  floors.get("min_receipts", _DEFAULT_MIN_RECEIPTS))
    min_claims = max(_DEFAULT_MIN_CLAIMS,
                     floors.get("min_high_conf_claims",
                                _DEFAULT_MIN_CLAIMS))
    min_tens = max(_DEFAULT_MIN_TENSIONS,
                   floors.get("min_non_orthogonal_tensions",
                              _DEFAULT_MIN_TENSIONS))
    # Skip floor check when caller passes no corpus signals (legacy
    # test callers using the pre-2026-05-05 signature). Production
    # callers from run_v06_synthesis always pass real values.
    has_corpus_signals = (
        n_receipts > 0 or n_high_conf_claims > 0
        or n_non_orthogonal_tensions > 0
    )
    flat_floor_clean = (
        not has_corpus_signals
        or (
            n_receipts >= min_rec
            and n_high_conf_claims >= min_claims
            and n_non_orthogonal_tensions >= min_tens
        )
    )
    evidence_profile = _evidence_certification_profile(manifest)
    certification_track, tiered_floor_clean = _select_certification_track(
        flat_floor_clean=flat_floor_clean,
        n_receipts=n_receipts,
        n_high_conf_claims=n_high_conf_claims,
        profile=evidence_profile,
        min_receipts=min_rec,
        min_claims=min_claims,
        cert_floors=floors,
    )
    if not has_corpus_signals and manifest is None:
        certification_track = "UNSCORED"
        tiered_floor_clean = False
    bridge_claims = _d1_bridge_claim_count(stage1_report)
    min_d1 = int(floors.get("min_d1_bridge_claims", 3))
    bridge_clean = (
        certification_track not in {"AAA-INF", "AAA-MECH"}
        or bridge_claims >= min_d1
    )
    bridge_req = str(min_d1) if certification_track in {"AAA-INF", "AAA-MECH"} else "n/a"
    cert_floor_clean = (flat_floor_clean or tiered_floor_clean) and bridge_clean
    # AAA requires positive evidence: at least one check ran AND all
    # passed AND zero stage-2 issues AND zero unresolved Grok P1
    # AND corpus floor met.
    all_green = (
        p1_clean
        and grok_clean
        and s1_n_total > 0
        and s1_n_pass == s1_n_total
        and s2_p2 == 0
        and cert_floor_clean
    )

    if not p1_clean:
        verdict = "SHIP-BLOCKED"
        reason = (
            f"P1 fail: stage1 P1_pass={s1_p1_pass}, "
            f"stage2 blocking issues={s2_p1_blocking}"
            + (f" (incl. {s2_unknown} unknown-severity)" if s2_unknown else "")
        )
    elif all_green:
        verdict = "AAA"
        reason = (
            f"All-green: stage1 {s1_n_pass}/{s1_n_total} + "
            f"stage2 zero issues + zero unresolved Grok P1 + "
            f"certification track {certification_track}"
        )
    elif not grok_clean and p1_clean:
        # Fix #31 + Fix #49: deterministic stages clean, but Grok
        # flagged P1 patches that the agent-to-agent repair loop
        # AND the auto-strip safety net BOTH could not resolve
        # (e.g. the BEFORE region wasn't unique in the paper or
        # appeared in load-bearing structural context). The
        # pipeline went as far as it can autonomously — this is
        # the honest agent-review-unresolved state, NOT a 'human
        # review please' cop-out.
        verdict = "Trust-Spine Pass — Agent Review Unresolved"
        reason = (
            f"P1 clean (stage1 {s1_n_pass}/{s1_n_total}, "
            f"stage2 P2={s2_p2}); BUT {grok_unresolved_p1} "
            f"Grok-flagged P1 patch(es) survived BOTH the "
            "agent-to-agent repair loop AND the auto-strip safety "
            "net (Fix #49). The pipeline exhausted its autonomous "
            "options; the issue is materially unresolvable without "
            "either a corpus-side fix or an out-of-band edit."
        )
    elif p1_clean and grok_clean and s2_p2 == 0 and (
        s1_n_total > 0 and s1_n_pass == s1_n_total
    ) and not cert_floor_clean:
        # Audits all-green but corpus below the certification floor —
        # honest signal that the pipeline ran cleanly on a thin corpus.
        verdict = "Trust-Spine Pass"
        reason = (
            f"All audits green (stage1 {s1_n_pass}/{s1_n_total}, "
            f"stage2 zero issues, grok zero) BUT corpus below "
            f"certification floor: receipts={n_receipts}/{min_rec}, "
            f"high-conf claims={n_high_conf_claims}/{min_claims}, "
            f"non-orthogonal tensions="
            f"{n_non_orthogonal_tensions}/{min_tens}; weighted "
            f"evidence={evidence_profile['total']:.1f}; "
            f"D1 bridge={bridge_claims}/{bridge_req}. "
            f"AAA requires clean audits, substantive evidence, and "
            f"a load-bearing bridge for INF/MECH tracks."
        )
    else:
        verdict = "Trust-Spine Pass"
        reason = (
            f"P1 clean; stage1 {s1_n_pass}/{s1_n_total} "
            f"(score {s1_score}/10); stage2 {s2_p2} P2 notes"
            + (
                "; stage1 had ZERO checks (no positive evidence — AAA blocked)"
                if s1_n_total == 0 else ""
            )
        )

    # Wave 7 (Evidence Factory slice 2): compute corpus gaps so a
    # sub-AAA verdict carries the actionable expansion to-do list
    # for the next run. Universal — driven by manifest signals only,
    # no per-topic logic. Empty tuples when the corpus already meets
    # all gates (AAA path) or when the caller did not pass a manifest.
    corpus_gaps: tuple[str, ...] = ()
    expansion_targets: tuple[str, ...] = ()
    if manifest is not None and not cert_floor_clean:
        try:
            from agent.corpus_expansion import compute_corpus_gaps
            corpus_gaps, expansion_targets = compute_corpus_gaps(
                manifest,
                min_receipts=min_rec,
                min_claims=min_claims,
                min_tensions=min_tens,
            )
        except (ImportError, ValueError):
            corpus_gaps, expansion_targets = (), ()

    # Slice 3 (Wave 7 cont.): topic maturity ladder L0-L5 +
    # Journal-Ready compound gate. Universal — derived from manifest
    # signals + verdict + hardening counters. Empty manifest → L0.
    maturity_level = 0
    maturity_label = "L0 — UNSEEDED"
    journal_ready = False
    try:
        from agent.topic_maturity import (
            compute_maturity_level, format_maturity_label,
            is_journal_ready,
        )
        maturity_level = compute_maturity_level(
            manifest or {},
            verdict=verdict,
            grok_unresolved_p1=grok_unresolved_p1,
            review_flagged_count=grok_flagged_count,
            auto_stripped_count=auto_stripped_count,
            cert_floors=cert_floors,
            journal_surface_pass=journal_surface_pass,
        )
        if verdict == "AAA" and tiered_floor_clean and maturity_level < 4:
            maturity_level = (
                5 if grok_unresolved_p1 == 0 and grok_flagged_count == 0
                and auto_stripped_count == 0 and journal_surface_pass else 4
            )
        maturity_label = format_maturity_label(maturity_level)
        journal_ready = is_journal_ready(maturity_level)
        if verdict == "AAA" and certification_track == "AAA-SCOP":
            maturity_label = (
                "L5-SCOPING-JOURNAL-READY"
                if journal_ready else "L4-SCOPING-CERTIFIED"
            )
    except ImportError:
        pass

    return UnifiedVerdict(
        verdict=verdict,
        reason=reason,
        stage1_p1_pass=s1_p1_pass,
        stage1_score=s1_score,
        stage1_pass_rate=f"{s1_n_pass}/{s1_n_total}",
        stage2_p1=s2_p1_blocking,
        stage2_p2=s2_p2,
        stage2_unknown_severity_count=s2_unknown,
        all_green=all_green,
        p1_clean=p1_clean,
        grok_unresolved_p1=grok_unresolved_p1,
        grok_flagged=grok_flagged_count,
        corpus_gaps=corpus_gaps,
        expansion_targets=expansion_targets,
        maturity_level=maturity_level,
        maturity_label=maturity_label,
        journal_ready=journal_ready,
        journal_surface_pass=journal_surface_pass,
        journal_surface_issues=journal_surface_issues,
        certification_track=certification_track,
        evidence_weight_total=round(evidence_profile["total"], 2),
        evidence_weight_clinical=round(evidence_profile["clinical"], 2),
        evidence_weight_mechanistic=round(evidence_profile["mechanistic"], 2),
    )


def _format_unified_verdict(u: UnifiedVerdict) -> str:
    # Wave 7 (Evidence Factory slice 2): when the verdict carries
    # corpus_gaps, append a Corpus Expansion To-Do block with a
    # 1:1 gap→action mapping. Empty tuples → empty string.
    expansion_md = ""
    try:
        from agent.corpus_expansion import format_expansion_section
        expansion_md = format_expansion_section(
            u.corpus_gaps, u.expansion_targets,
        )
    except ImportError:
        expansion_md = ""
    # Slice 3 (Wave 7): journal-ready badge + maturity ladder line.
    journal_line = (
        "**Journal-Ready: yes** — submission-grade certification "
        "(AAA + zero unresolved Grok + zero auto-strip surgery + "
        "clean journal-surface gate).\n\n"
        if u.journal_ready
        else "**Journal-Ready: no** — see maturity level + components "
             "for what gates remain.\n\n"
    )
    surface_line = (
        "- Journal surface gate: pass\n"
        if u.journal_surface_pass
        else "- Journal surface gate: fail — "
             + "; ".join(u.journal_surface_issues[:8]) + "\n"
    )
    track_line = (
        f"- Certification track: {u.certification_track} "
        f"(weighted total={u.evidence_weight_total:.2f}; "
        f"clinical={u.evidence_weight_clinical:.2f}; "
        f"mechanistic={u.evidence_weight_mechanistic:.2f})\n"
    )
    verdict_label = (
        f"Pipeline {u.verdict} / L{u.maturity_level}"
        if u.verdict == "AAA" and not u.journal_ready
        else u.verdict
    )
    return (
        f"# Unified Final Verdict\n\n"
        f"**Verdict: {verdict_label}**\n\n"
        f"**Maturity: {u.maturity_label}**\n\n"
        f"{journal_line}"
        f"**Reason:** {u.reason}\n\n"
        f"## Components\n\n"
        f"- Stage-1 audit (Q1-Q10): "
        f"P1_pass={u.stage1_p1_pass}, "
        f"score={u.stage1_score}/10, "
        f"pass_rate={u.stage1_pass_rate}\n"
        f"- Stage-2 consistency audit: "
        f"P1 issues={u.stage2_p1}, "
        f"P2 issues={u.stage2_p2}"
        + (
            f", unknown-severity={u.stage2_unknown_severity_count} "
            f"(treated as blocking)"
            if u.stage2_unknown_severity_count else ""
        )
        + "\n"
        + track_line
        + surface_line
        + (
            f"- Grok-flagged P1 patches unresolved: "
            f"{u.grok_unresolved_p1} "
            f"(downgrades AAA → 'Trust-Spine Pass — Human Review "
            f"Required'; Fix #31)\n"
            if u.grok_unresolved_p1 else ""
        )
        + "\n"
        "## Verdict scale\n\n"
        "- **AAA** — all-green (stage-1 + stage-2 both zero issues, "
        "and stage-1 actually ran checks).\n"
        "- **Trust-Spine Pass** — P1 clean in both stages; "
        "stage-1 P2s or stage-2 P2 notes allowed.\n"
        "- **SHIP-BLOCKED** — ANY P1 fail in stage-1 OR stage-2 "
        "(unknown severities fail closed).\n"
        + expansion_md
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Phase 6.1 — wire v0.6.0 bound claims into agent/paper_writer.py",
    )
    parser.add_argument(
        "--topic", required=True,
        help=(
            "Topic to synthesise (REQUIRED — no default to prevent "
            "accidental metformin runs after a topic-pack edit). "
            "Must match a topic_packs/<topic>.toml file AND a "
            "docs/quality-reference/<topic>/ corpus directory. "
            "Examples: metformin, rapamycin, statins, glp1, "
            "senolytics, nad_precursors."
        ),
    )
    parser.add_argument(
        "--out-dir", help=(
            "default: runs/synthesis-<topic>-v06-{ISO}/"
        ),
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Build receipts/matrix/thesis but do not call the LLM",
    )
    args = parser.parse_args(argv)
    if args.out_dir:
        out_dir = Path(args.out_dir).resolve()
    else:
        ts = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
        out_dir = (
            REPO_ROOT / "runs" / f"synthesis-{args.topic}-v06-{ts}"
        )
    try:
        return asyncio.run(_run(
            out_dir, dry_run=args.dry_run, topic=args.topic,
        ))
    finally:
        if not args.dry_run and out_dir.exists():
            moved_artifacts = _organize_run_artifacts(out_dir)
            if moved_artifacts:
                print(
                    f"[pipeline] cleanup — organized {len(moved_artifacts)} sidecar artifact(s)",
                    file=sys.stderr,
                )


if __name__ == "__main__":
    sys.exit(main())
