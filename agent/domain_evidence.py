"""Domain evidence adapters — Wave 7 Evidence Factory slice 5
(2026-05-05).

Decouples the corpus classifier from biomedical-specific signal
lists so the pipeline can synthesize across other research domains
with their own evidence hierarchies. Four built-in profiles ship
with the platform; topic packs reference a profile by `name`.

  biomedical    A1=Cochrane/large RCT > A2=meta-analysis > B1=cohort
                > B2=case-control > C=expert opinion. Direct =
                clinical trial; mechanism = preclinical / in vitro.

  economics     A1=well-identified RCT > A2=diff-in-diff /
                synthetic-control > B1=instrumental variables >
                B2=observational > C=theoretical model. Direct =
                causal estimate; mechanism = theory paper.

  management    A1=field experiment > A2=multi-firm panel >
                B1=case study > B2=expert survey > C=consultant
                report. Direct = field study; mechanism = theory.

  cs_ai         A1=ablation+benchmark+held-out test > A2=multi-
                benchmark replication > B1=single benchmark >
                B2=qualitative demo > C=position paper. Direct =
                empirical, mechanism = theoretical.

Universal: a topic pack picks ONE profile via `domain = "..."`. The
corpus classifier, role classifier, and evidence-tier guards all
read from that profile so the same pipeline code services every
domain. No per-domain `if` ladders in the runtime.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class DomainProfile:
    name: str
    tier_hierarchy: tuple[str, ...]   # ordered strongest → weakest
    directness_levels: tuple[str, ...]
    core_clinical_signals: tuple[str, ...]
    mechanism_signals: tuple[str, ...]
    reject_signals: tuple[str, ...] = field(default_factory=tuple)

    def is_high_tier(self, tier: str) -> bool:
        """True if `tier` is in the top two slots of the hierarchy
        (A1/A2 in biomedical, equivalent strongest tiers elsewhere)."""
        if not tier:
            return False
        for i, t in enumerate(self.tier_hierarchy):
            if t == tier and i < 2:
                return True
        return False


# ---------- Biomedical profile (default) -----------------------------

BIOMEDICAL = DomainProfile(
    name="biomedical",
    tier_hierarchy=("A1", "A2", "B1", "B2", "C1", "C2"),
    directness_levels=("direct", "indirect", "review", "mechanistic"),
    core_clinical_signals=(
        "randomized controlled trial", "randomised controlled trial",
        " rct ", "(rct)", "cohort study", "case-control study",
        "meta-analysis", "systematic review",
        "all-cause mortality", "primary prevention",
        "secondary prevention", "incident cancer",
        "incidence of", "real-world evidence", "trial emulation",
        "biobank", "registry-based",
    ),
    mechanism_signals=(
        "in vitro", "cell culture", "molecular mechanism",
        "signaling pathway", "kinase activity", "expression of",
        "transcriptional", "protein interaction", "receptor binding",
        "knockout mouse", "transgenic mouse", "pharmacokinetics",
        "pharmacodynamics", "wistar rat", "wistar rats",
        "drosophila", "c. elegans", "yeast",
    ),
    reject_signals=(
        "traumatic brain injury", " tbi ", "tbi-",
        "burn wound", "cerebral cavernous malformation",
        "atrial fibrillation", "cardioversion", "stroke patients",
        "neurovascular unit", "blood-brain barrier",
    ),
)


# ---------- Economics profile ----------------------------------------

ECONOMICS = DomainProfile(
    name="economics",
    tier_hierarchy=("RCT", "DiD", "IV", "Obs", "Theory"),
    directness_levels=(
        "causal_estimate", "quasi_experimental", "observational",
        "theoretical",
    ),
    core_clinical_signals=(
        "randomized field experiment", "randomized experiment",
        "difference-in-differences", "diff-in-diff",
        "synthetic control", "instrumental variable",
        "regression discontinuity", "rdd",
        "natural experiment", "policy experiment",
        "causal effect", "treatment effect estimate",
    ),
    mechanism_signals=(
        "theoretical model", "structural model", "calibration",
        "general equilibrium", "agent-based model",
        "simulation", "stylized fact",
    ),
)


# ---------- Management profile ---------------------------------------

MANAGEMENT = DomainProfile(
    name="management",
    tier_hierarchy=("FieldExp", "Panel", "Case", "Survey", "Opinion"),
    directness_levels=(
        "field_experiment", "panel_study", "case_study",
        "survey", "opinion",
    ),
    core_clinical_signals=(
        "field experiment", "field study",
        "multi-firm panel", "longitudinal study",
        "treatment effect", "quasi-experiment",
        "controlled trial", "randomized assignment",
    ),
    mechanism_signals=(
        "theoretical framework", "conceptual model",
        "literature review", "narrative synthesis",
        "consultant report", "white paper",
    ),
)


# ---------- CS / AI profile ------------------------------------------

CS_AI = DomainProfile(
    name="cs_ai",
    tier_hierarchy=(
        "AblationBench", "MultiBench", "SingleBench", "Demo",
        "Position",
    ),
    directness_levels=(
        "empirical_full", "empirical_partial", "empirical_demo",
        "theoretical",
    ),
    core_clinical_signals=(
        "ablation study", "ablation analysis",
        "held-out test set", "benchmark evaluation",
        "leaderboard", "multi-benchmark",
        "reproducibility", "statistical significance",
        "confidence interval",
    ),
    mechanism_signals=(
        "theoretical analysis", "complexity bound",
        "convergence proof", "lemma", "proposition",
        "qualitative example", "case study",
    ),
)


_PROFILES: dict[str, DomainProfile] = {
    p.name: p for p in (BIOMEDICAL, ECONOMICS, MANAGEMENT, CS_AI)
}


def get_profile(name: str | None) -> DomainProfile:
    """Resolve a profile name to a DomainProfile. Falls back to
    BIOMEDICAL when name is None or unknown — that's the platform's
    default and the historical assumption.
    """
    if not name:
        return BIOMEDICAL
    return _PROFILES.get(name.lower(), BIOMEDICAL)


def list_profiles() -> tuple[str, ...]:
    return tuple(_PROFILES.keys())


__all__ = [
    "DomainProfile", "BIOMEDICAL", "ECONOMICS", "MANAGEMENT", "CS_AI",
    "get_profile", "list_profiles",
]
