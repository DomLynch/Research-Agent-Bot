"""Retrieval modes + universal safety cap + marginal-yield stopper.

Slice 6 step 1 (Wave 7 cont., 2026-05-05). The Evidence Factory's
retrieval foundation. Replaces the toy `--limit 30 / --max-per-source
15` defaults with three principled modes:

  smoke        100 papers, dev/test only — for fast iteration
  calibrated   default. Source exhaustion bounded by marginal-yield
               stop (last N pages produce <2% new-deduped or
               <1% core_on_thesis → STOP) + 200K safety cap.
  exhaustive   no marginal-yield stop; pull until every source is
               exhausted or the 200K safety cap fires. Use only when
               an operator explicitly wants to ingest the full
               available universe (e.g. for offline dataset builds).
  snowball     followup mode — references + cited-by from already-
               accepted core papers. Same 200K ceiling.

The 200K is a UNIVERSAL CIRCUIT BREAKER, not a per-topic target.
A bad query that accidentally matches 800K papers will be cut off
at 200K and an alert will surface — but the platform won't melt the
disk first. Calibrated queries should never come close.

Universal across topics + domains. Pure-Python, no IO, no LLM.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# Universal circuit breaker — applies to every topic, every domain.
# Override only for tests/dev (override is exposed via RetrievalParams,
# never hardcoded against in retrieval code).
GLOBAL_SAFETY_CAP = 200_000

# Smoke-test limit — fast retrieval for unit tests, integration
# checks, and "did I break the seed pipeline?" sanity runs. Not a
# production mode.
SMOKE_TEST_LIMIT = 100

# Default page size requested from sources. Sources may return less
# (rate-limit, server-side cap) but never more.
DEFAULT_PAGE_SIZE = 100

RetrievalMode = Literal["smoke", "calibrated", "exhaustive", "snowball"]

VALID_MODES: frozenset[RetrievalMode] = frozenset(
    ("smoke", "calibrated", "exhaustive", "snowball"),
)


@dataclass(frozen=True, slots=True)
class RetrievalParams:
    """Resolved retrieval parameters for a single seed run.

    Built from the mode + (optional) operator overrides. Caller
    passes this to the aggregator instead of mode-specific
    branching at every source-call site.
    """
    mode: RetrievalMode
    safety_cap: int                # hard upper bound on retrieved
    page_size: int                 # per-page request size
    use_marginal_yield_stop: bool  # apply MarginalYieldStopper
    use_wave_orchestration: bool   # run Precision/Recall/Background/...
    description: str               # human-readable label

    @property
    def is_smoke(self) -> bool:
        return self.mode == "smoke"


def resolve_params(
    mode: RetrievalMode = "calibrated",
    *,
    safety_cap_override: int | None = None,
    page_size_override: int | None = None,
) -> RetrievalParams:
    """Resolve a mode → RetrievalParams. Overrides allow tests to
    inject smaller caps without globally redefining the constant."""
    if mode not in VALID_MODES:
        raise ValueError(
            f"Unknown retrieval mode {mode!r}. "
            f"Valid: {sorted(VALID_MODES)}"
        )
    if mode == "smoke":
        cap = safety_cap_override or SMOKE_TEST_LIMIT
        return RetrievalParams(
            mode=mode, safety_cap=cap,
            page_size=page_size_override or 25,
            use_marginal_yield_stop=False,
            use_wave_orchestration=False,
            description=(
                f"smoke-test mode (cap={cap}, no waves, no yield-stop)"
            ),
        )
    if mode == "calibrated":
        cap = safety_cap_override or GLOBAL_SAFETY_CAP
        return RetrievalParams(
            mode=mode, safety_cap=cap,
            page_size=page_size_override or DEFAULT_PAGE_SIZE,
            use_marginal_yield_stop=True,
            use_wave_orchestration=True,
            description=(
                f"calibrated (default): wave-based + marginal-yield "
                f"stop, safety cap={cap}"
            ),
        )
    if mode == "exhaustive":
        cap = safety_cap_override or GLOBAL_SAFETY_CAP
        return RetrievalParams(
            mode=mode, safety_cap=cap,
            page_size=page_size_override or DEFAULT_PAGE_SIZE,
            use_marginal_yield_stop=False,
            use_wave_orchestration=True,
            description=(
                f"exhaustive: wave-based, no marginal-yield stop, "
                f"safety cap={cap}"
            ),
        )
    # snowball
    cap = safety_cap_override or GLOBAL_SAFETY_CAP
    return RetrievalParams(
        mode=mode, safety_cap=cap,
        page_size=page_size_override or DEFAULT_PAGE_SIZE,
        use_marginal_yield_stop=True,
        use_wave_orchestration=False,
        description=(
            f"snowball: references + cited-by from accepted core "
            f"papers, safety cap={cap}"
        ),
    )


# ---------- marginal-yield stopper ---------------------------------

@dataclass(slots=True)
class _PageStat:
    """One page's contribution stats. Internal to MarginalYieldStopper."""
    seen: int                    # candidates returned this page
    new_deduped: int             # not seen in earlier pages
    core_candidates: int         # passed metadata-only topic-fit


@dataclass(slots=True)
class MarginalYieldStopper:
    """Sliding-window stop rule: when the LAST `window_size` pages
    consistently produce too few new / on-thesis papers, we have
    diminishing returns — STOP.

    Default rules (any one triggers stop):
      - Last `window_size` pages avg <2% new-deduped per page
      - Last `window_size` pages avg <1% core-candidate per page
      - Last `window_size` pages avg >95% noise (off-thesis or seen)

    These thresholds are the "stop hauling junk" rule. Tuning is
    via constructor — defaults are conservative (do NOT stop too
    early; calibrated queries usually keep producing).
    """
    window_size: int = 5
    new_dedup_pct_floor: float = 0.02
    core_candidate_pct_floor: float = 0.01
    noise_pct_ceiling: float = 0.95
    _pages: list[_PageStat] = field(default_factory=list)

    def record_page(
        self, *, seen: int, new_deduped: int, core_candidates: int,
    ) -> None:
        self._pages.append(_PageStat(
            seen=seen, new_deduped=new_deduped,
            core_candidates=core_candidates,
        ))

    def should_stop(self) -> tuple[bool, str]:
        """Returns (stop, reason). Reason is empty when not stopping."""
        if len(self._pages) < self.window_size:
            return False, ""
        window = self._pages[-self.window_size:]
        total_seen = sum(p.seen for p in window) or 1
        new_dedup_pct = sum(p.new_deduped for p in window) / total_seen
        core_pct = sum(p.core_candidates for p in window) / total_seen
        noise_pct = 1.0 - new_dedup_pct
        if new_dedup_pct < self.new_dedup_pct_floor:
            return True, (
                f"marginal yield: last {self.window_size} pages "
                f"averaged {new_dedup_pct:.1%} new-deduped "
                f"(floor {self.new_dedup_pct_floor:.0%})"
            )
        if core_pct < self.core_candidate_pct_floor:
            return True, (
                f"core candidate yield: last {self.window_size} "
                f"pages averaged {core_pct:.1%} core-candidate "
                f"(floor {self.core_candidate_pct_floor:.0%})"
            )
        if noise_pct > self.noise_pct_ceiling:
            return True, (
                f"noise saturation: last {self.window_size} pages "
                f"were {noise_pct:.1%} duplicates / off-thesis "
                f"(ceiling {self.noise_pct_ceiling:.0%})"
            )
        return False, ""

    def stats(self) -> dict[str, float | int]:
        """Diagnostic snapshot for logs / dashboards."""
        if not self._pages:
            return {"pages": 0, "total_seen": 0}
        total_seen = sum(p.seen for p in self._pages)
        total_new = sum(p.new_deduped for p in self._pages)
        total_core = sum(p.core_candidates for p in self._pages)
        return {
            "pages": len(self._pages),
            "total_seen": total_seen,
            "total_new_deduped": total_new,
            "total_core_candidates": total_core,
            "overall_new_dedup_pct": (
                total_new / total_seen if total_seen else 0.0
            ),
            "overall_core_pct": (
                total_core / total_seen if total_seen else 0.0
            ),
        }


__all__ = [
    "GLOBAL_SAFETY_CAP",
    "SMOKE_TEST_LIMIT",
    "DEFAULT_PAGE_SIZE",
    "RetrievalMode",
    "VALID_MODES",
    "RetrievalParams",
    "resolve_params",
    "MarginalYieldStopper",
]
