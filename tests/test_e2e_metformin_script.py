"""Regression tests for `scripts/e2e_metformin_proof_001.py` helpers.

Both reviewer P1s in Day 5.3 lived in this script, not the agent layer:

  - P1-1: `--max-items` could silently drop canonical trials when the cap
    was below the canonical-set size; the fix raises `_CapTooSmallError`.
    The detection helper must scan source.nct + source.url + abstract
    (same surfaces lookup_override / trace_nct_exists use), or canonical
    trials whose NCT is only in the abstract get missed.

  - P1-2: `_format_path` must handle paths outside REPO_ROOT — earlier the
    unconditional `relative_to(REPO_ROOT)` raised ValueError before the
    pipeline even started for any `--output-dir /tmp/...`.

These tests pin both behaviors so future edits can't drift them back.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from agent.topic_pack import load_topic_pack
from agent.types import EvidenceItem, Source
from scripts.e2e_metformin_proof_001 import (
    REPO_ROOT,
    _CapTooSmallError,
    _attempt_sort_key,
    _format_path,
    _ranked_for_extraction,
)

REPO = Path(__file__).resolve().parent.parent
METFORMIN_PACK = load_topic_pack(REPO / "topic_packs" / "metformin.toml")


def _mk(ref: int, *, nct: str | None = None, abstract: str = "") -> EvidenceItem:
    return EvidenceItem(
        source=Source(
            ref=ref, title=f"t{ref}", year=2024,
            url=f"https://example.com/{ref}",
            source="openalex", nct=nct,
        ),
        abstract=abstract,
        design="rct", role="published_results", tier=1,
        direct=True, strict=False,
    )


# ----- P1-1: canonical detection + cap behavior --------------------------


def test_cap_below_canonical_count_raises_with_explicit_floor() -> None:
    """All 4 canonical NCTs in the corpus, cap=3 → must raise.

    Without the surface-scan helper, only 2 of the 4 (those with
    populated source.nct) would be detected, and cap=3 would silently
    succeed while dropping a canonical entry. This test fails on that
    drift.
    """
    items = [
        _mk(1, nct="NCT02308228"),                                  # MASTERS via source.nct
        _mk(2, abstract="Trial NCT04264897 details..."),            # TAME via abstract
        _mk(3, abstract="See ISRCTN29932357 registration."),        # MET-PREVENT via abstract
        _mk(4, nct="NCT01765946"),                                  # MILES via source.nct
        _mk(5, abstract="Some non-canonical paper"),
    ]
    with pytest.raises(_CapTooSmallError) as exc_info:
        _ranked_for_extraction(items, 3, pack=METFORMIN_PACK)
    msg = str(exc_info.value)
    assert "4 present" in msg
    assert ">= 4" in msg


def test_cap_equal_to_canonical_count_keeps_all_canonical() -> None:
    """cap == len(canonical) preserves every canonical and drops only
    non-canonical items."""
    items = [
        _mk(1, nct="NCT02308228"),
        _mk(2, abstract="NCT04264897"),
        _mk(3, abstract="ISRCTN29932357"),
        _mk(4, nct="NCT01765946"),
        _mk(5),  # non-canonical
        _mk(6),  # non-canonical
    ]
    out = _ranked_for_extraction(items, 4, pack=METFORMIN_PACK)
    refs = {it.source.ref for it in out}
    assert refs == {1, 2, 3, 4}, (
        f"cap=4 must keep refs 1-4 (canonical), drop 5-6, got {refs}"
    )


def test_cap_above_total_returns_everything() -> None:
    items = [_mk(i) for i in range(1, 4)]
    out = _ranked_for_extraction(items, 10, pack=METFORMIN_PACK)
    assert [it.source.ref for it in out] == [1, 2, 3]


def test_cap_none_is_passthrough() -> None:
    items = [_mk(i) for i in range(1, 4)]
    out = _ranked_for_extraction(items, None, pack=METFORMIN_PACK)
    assert out is items  # short-circuit, not even a copy


def test_canonical_via_isrctn_in_url_also_counts() -> None:
    """Surface-scan also reads ISRCTNs in source.url (the path
    registry_overrides.lookup_override uses for the EuropePMC trial
    landing pages where the ID is in the URL, not the abstract)."""
    item = EvidenceItem(
        source=Source(
            ref=1, title="t", year=2024,
            url="https://www.isrctn.com/ISRCTN29932357",
            source="europepmc", nct=None,
        ),
        abstract="No ID here.",
        design="rct", role="published_results", tier=1,
        direct=True, strict=False,
    )
    # cap=1 with this single canonical item must succeed (1 canonical, cap=1).
    out = _ranked_for_extraction([item], 1, pack=METFORMIN_PACK)
    assert [it.source.ref for it in out] == [1]


# ----- P1-2: _format_path handles outside-repo paths ---------------------


def test_format_path_relative_for_in_repo() -> None:
    p = REPO_ROOT / "runs" / "metformin-001-x"
    assert _format_path(p) == "runs/metformin-001-x"


def test_format_path_absolute_for_outside_repo() -> None:
    """The earlier `relative_to(REPO_ROOT)` raised ValueError for any
    path outside the repo. _format_path now falls back to an absolute
    string instead of crashing the run."""
    outside = Path("/tmp/proof001-elsewhere").resolve()
    assert _format_path(outside) == str(outside)


# ----- Day 9.2: best-of-N attempt ranking --------------------------------


def _md(verdict: str, *, gate=False, claims=4, failed=0, sid="r-1") -> dict:
    return {
        "spar_verdict": verdict,
        "gate_override": gate,
        "n_claims": claims,
        "n_failed_traces": failed,
        "submission_id": sid,
    }


def test_attempt_sort_accept_clean_beats_accept_caveated() -> None:
    """Verdict rank dominates: any accept_clean wins over any
    accept_caveated, regardless of claim count or trace stats."""
    clean = _md("accept_clean", claims=2, sid="A")
    caveated = _md("accept_caveated", claims=10, failed=0, sid="B")
    best = min([clean, caveated], key=_attempt_sort_key)
    assert best["submission_id"] == "A"


def test_attempt_sort_accept_beats_reject_even_with_failed_traces() -> None:
    """An accept with 1 failed trace still beats a reject with 0
    failed traces — verdict is the primary axis, not trace count."""
    accept = _md("accept_caveated", failed=1, sid="A")
    reject = _md("reject_critical", failed=0, sid="B")
    best = min([accept, reject], key=_attempt_sort_key)
    assert best["submission_id"] == "A"


def test_attempt_sort_gate_override_breaks_tie_within_verdict() -> None:
    """Two accept_caveated runs — the one without gate_override wins
    because gate_override=True means SPAR was forced (code-disposed)
    rather than judges genuinely accepting."""
    natural = _md("accept_caveated", gate=False, sid="A")
    gated = _md("accept_caveated", gate=True, sid="B")
    best = min([natural, gated], key=_attempt_sort_key)
    assert best["submission_id"] == "A"


def test_attempt_sort_more_claims_wins_at_equal_quality() -> None:
    """When verdict + gate + failed-traces all tie, the run with more
    claims (richer artifact) wins. This is what makes the picker
    prefer a substantive paper over a thin one."""
    thin = _md("accept_caveated", claims=2, sid="A")
    rich = _md("accept_caveated", claims=8, sid="B")
    best = min([thin, rich], key=_attempt_sort_key)
    assert best["submission_id"] == "B"


def test_attempt_sort_deterministic_on_full_tie() -> None:
    """Identical metadata except submission_id: the lexicographically
    smaller submission_id wins. This is the deterministic tiebreak so
    repeating the same N runs picks the same best receipt every time."""
    a = _md("accept_clean", sid="zzz-aaa")
    b = _md("accept_clean", sid="aaa-zzz")
    best = min([a, b], key=_attempt_sort_key)
    assert best["submission_id"] == "aaa-zzz"


def test_attempt_sort_unknown_verdict_ranks_last() -> None:
    """Defensive: a metadata blob with a missing/unknown verdict must
    not silently win over a real verdict. It's ranked at the bottom."""
    unknown = _md("", sid="A")  # empty / missing
    reject = _md("reject_critical", sid="B")
    best = min([unknown, reject], key=_attempt_sort_key)
    assert best["submission_id"] == "B"
