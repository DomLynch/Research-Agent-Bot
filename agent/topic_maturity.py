"""Topic Maturity Ladder L0-L5 — Wave 7 reviewer fix (2026-05-05).

Evidence Factory slice 3: every topic gets a maturity badge derived
from its corpus + audit signals, so the operator can see at a glance
whether the topic is unseeded, partial, audit-blocked, or
journal-ready. Universal across topics — driven by manifest signals
+ unified verdict, no per-topic logic.

Levels (monotonic — higher level always implies all lower-level
gates have been cleared):

  L0 — UNSEEDED        no receipts
  L1 — SEEDED          receipts exist, but no high-confidence claims
  L2 — PARTIAL         claims exist, but below certification floor
  L3 — FLOOR-MET       cert floor met, but verdict not AAA
                       (audit failures or unresolved Grok flags)
  L4 — AAA             verdict == "AAA"
  L5 — JOURNAL-READY   AAA + zero unresolved Grok + zero auto-strip
                       surgery (i.e. no fragile body that needed
                       structural patching to pass)

Journal-Ready is the strictest tier we expose; it gates "this run is
ready to send to a peer-reviewed journal without further review."
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
    4: "L4 — AAA",
    5: "L5 — JOURNAL-READY",
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
    4: "AAA verdict — all audits clean and the corpus meets every "
       "floor. Suitable for internal release.",
    5: "Journal-Ready — AAA plus zero unresolved Grok flags plus "
       "zero auto-strip surgery. No structural patching was needed "
       "to clear the gates. Suitable for peer-reviewed submission.",
}


def compute_maturity_level(
    manifest: dict[str, Any],
    *,
    verdict: str,
    grok_unresolved_p1: int = 0,
    auto_stripped_count: int = 0,
    cert_floors: dict[str, int] | None = None,
) -> int:
    """Pure function: returns 0-5 from manifest + unified-verdict
    signals. `verdict` is the UnifiedVerdict.verdict string ("AAA",
    "Trust-Spine Pass", "SHIP-BLOCKED", etc.). Cert floors honored
    via max(default, override) — packs may RAISE but not LOWER.
    """
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
    if grok_unresolved_p1 == 0 and auto_stripped_count == 0:
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
