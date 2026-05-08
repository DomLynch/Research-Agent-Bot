"""Topic Maturity Ladder L0-L6.

Universal maturity badges from corpus + audit + reproducibility
signals. Higher levels imply lower gates have cleared:

  L0 — UNSEEDED        no receipts
  L1 — SEEDED          receipts exist, but no high-confidence claims
  L2 — PARTIAL         claims exist, but below certification floor
  L3 — FLOOR-MET       cert floor met, but verdict not AAA
                       (audit failures or unresolved Grok flags)
  L4 — ANALYTICAL      verdict == "AAA", but journal-surface or
                       surgery gate still requires editorial work
  L5 — JOURNAL-READY   AAA + zero unresolved Grok + zero auto-strip
                       surgery + clean journal-surface gate
  L6 — REPRODUCIBLE    at least two consecutive clean L5 runs
"""
from __future__ import annotations

from typing import Any

# Default cert floors (mirror run_v06_synthesis._compute_unified_verdict).
# Centralized here so callers without access to the orchestrator can
# still derive maturity locally (e.g. dashboard).
_DEFAULT_MIN_RECEIPTS = 10
_DEFAULT_MIN_CLAIMS = 50
_DEFAULT_MIN_TENSIONS = 10

_LEVEL_LABELS: dict[int, str] = {
    0: "L0 — UNSEEDED",
    1: "L1 — SEEDED",
    2: "L2 — PARTIAL",
    3: "L3 — FLOOR-MET",
    4: "L4 — ANALYTICALLY CERTIFIED",
    5: "L5 — JOURNAL-READY",
    6: "L6 — REPRODUCIBLY JOURNAL-READY",
}

_LEVEL_DESCRIPTIONS: dict[int, str] = {
    0: "No receipts in the manifest — corpus has not been seeded yet.",
    1: "Receipts exist but no high-confidence claims have been "
       "extracted — extraction has not run cleanly.",
    2: "Claims exist but the corpus is below the certification floor "
       "(receipts / claims / tensions). AAA blocked on substance, "
       "not on audit.",
    3: "Corpus meets the certification floor, but the verdict is "
       "below AAA — audit failures, P1 issues, or unresolved Grok "
       "patches are in the way.",
    4: "Analytical AAA — audits and corpus floors pass, but a "
       "journal-surface or surgery gate still requires editorial work.",
    5: "Journal-Ready — AAA plus zero unresolved Grok flags plus "
       "zero auto-strip surgery. No structural patching was needed "
       "to clear the gates. Suitable for peer-reviewed submission.",
    6: "Reproducibly Journal-Ready — at least two consecutive clean "
       "L5-grade runs under the same certification gate.",
}


def compute_maturity_level(
    manifest: dict[str, Any],
    *,
    verdict: str,
    grok_unresolved_p1: int = 0,
    auto_stripped_count: int = 0,
    cert_floors: dict[str, int] | None = None,
    journal_surface_pass: bool = True,
    consecutive_aaa_count: int = 1,
) -> int:
    """Pure function: returns 0-5 from one run's manifest + verdict
    signals. `verdict` is the UnifiedVerdict.verdict string ("AAA",
    "Trust-Spine Pass", "SHIP-BLOCKED", etc.). Cert floors honored
    via max(default, override) — packs may RAISE but not LOWER.
    L6 is topic-level reproducibility and is computed across runs.
    """
    _ = consecutive_aaa_count
    n_rec = int(manifest.get("n_receipts", 0))
    n_claims = int(manifest.get("n_high_confidence_claims_total", 0))
    n_tens = int(manifest.get("n_non_orthogonal_tensions", 0))
    floors = cert_floors or {}
    min_rec = max(
        _DEFAULT_MIN_RECEIPTS,
        floors.get("min_receipts", _DEFAULT_MIN_RECEIPTS),
    )
    min_claims = max(
        _DEFAULT_MIN_CLAIMS,
        floors.get("min_high_conf_claims", _DEFAULT_MIN_CLAIMS),
    )
    min_tens = max(
        _DEFAULT_MIN_TENSIONS,
        floors.get("min_non_orthogonal_tensions", _DEFAULT_MIN_TENSIONS),
    )
    floor_clean = (
        n_rec >= min_rec
        and n_claims >= min_claims
        and n_tens >= min_tens
    )

    if n_rec == 0:
        return 0
    if n_claims == 0:
        return 1
    if not floor_clean:
        return 2
    if verdict != "AAA":
        return 3
    # AAA achieved — distinguish L4 from L5 on hardening signals
    if (
        grok_unresolved_p1 == 0
        and auto_stripped_count == 0
        and journal_surface_pass
    ):
        return 5
    return 4


def format_maturity_label(level: int) -> str:
    """Human-readable badge — `L4 — AAA` etc."""
    return _LEVEL_LABELS.get(level, f"L{level} — UNKNOWN")


def format_maturity_description(level: int) -> str:
    """One-sentence description suitable for a dashboard tooltip /
    final_verdict.md row."""
    return _LEVEL_DESCRIPTIONS.get(
        level, "Unknown maturity level — falling out of the ladder.",
    )


def is_journal_ready(level: int) -> bool:
    """Single source of truth for the Journal-Ready gate.

    Slice 3 cert standard: only L5 clears Journal-Ready. AAA alone
    (L4) is *internally* publishable but may carry surgery scars
    (auto-stripped sentences) that a journal reviewer would catch.
    """
    return level >= 5


__all__ = [
    "compute_maturity_level",
    "format_maturity_label",
    "format_maturity_description",
    "is_journal_ready",
]
