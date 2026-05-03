"""Fix #31 — Grok-unresolved P1 patches downgrade AAA → Trust-Spine
Pass — Human Review Required.

Trust-spine principle: the harness can autonomously verify Stage-1 +
Stage-2 audits (deterministic checks). It CANNOT autonomously verify
that a Grok-flagged P1 was a false positive. Therefore an unresolved
Grok P1 surfaces as 'human review required', not as AAA."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import run_v06_synthesis as orch  # noqa: E402


def _full_audit() -> dict:
    """A clean Stage-1 audit — all 10 checks passed."""
    return {
        "score_out_of_10": 10.0,
        "p1_pass": True,
        "checks": [
            {"name": f"Q{i+1}", "p1": True, "passed": True,
             "detail": "ok"} for i in range(10)
        ],
        "n_pass": 10, "n_total": 10,
    }


def test_aaa_when_grok_clean() -> None:
    """All-green stages + zero Grok-unresolved P1 → AAA."""
    v = orch._compute_unified_verdict(
        _full_audit(), [], grok_unresolved_p1=0,
    )
    assert v.verdict == "AAA"
    assert v.all_green is True


def test_grok_unresolved_p1_blocks_aaa() -> None:
    """All-green stages + 1 Grok-unresolved P1 → 'Trust-Spine Pass —
    Human Review Required'. NOT AAA."""
    v = orch._compute_unified_verdict(
        _full_audit(), [], grok_unresolved_p1=1,
    )
    assert v.verdict == "Trust-Spine Pass — Human Review Required"
    assert v.all_green is False
    assert v.grok_unresolved_p1 == 1


def test_verdict_reason_names_grok_count() -> None:
    """The reason string surfaces the count so a reader sees WHY
    AAA was blocked."""
    v = orch._compute_unified_verdict(
        _full_audit(), [], grok_unresolved_p1=3,
    )
    assert "3 Grok-flagged P1" in v.reason
    assert "Human review required" in v.reason


def test_grok_unresolved_p1_field_serializes() -> None:
    """The field must round-trip through JSON for archival."""
    import dataclasses
    v = orch._compute_unified_verdict(
        _full_audit(), [], grok_unresolved_p1=2,
    )
    d = dataclasses.asdict(v)
    assert d["grok_unresolved_p1"] == 2
    assert d["verdict"] == (
        "Trust-Spine Pass — Human Review Required"
    )


def test_default_grok_unresolved_p1_is_zero() -> None:
    """Backward-compat: callers that don't pass grok_unresolved_p1
    get 0 (behaviour unchanged from pre-Fix-#31 callers)."""
    v = orch._compute_unified_verdict(_full_audit(), [])
    assert v.grok_unresolved_p1 == 0
    assert v.verdict == "AAA"


def test_p1_blocking_dominates_grok_unresolved() -> None:
    """If Stage-1 P1 fails AND Grok has unresolved P1 → SHIP-BLOCKED
    (P1 dominates; Grok-only downgrade only matters when stages
    are clean)."""
    audit = _full_audit()
    audit["p1_pass"] = False
    audit["checks"][0]["passed"] = False
    v = orch._compute_unified_verdict(
        audit, [], grok_unresolved_p1=1,
    )
    assert v.verdict == "SHIP-BLOCKED"


def test_format_unified_verdict_surfaces_grok_count() -> None:
    """Markdown rendering must include the Grok-unresolved row when
    >0 (transparency for human reviewer)."""
    v = orch._compute_unified_verdict(
        _full_audit(), [], grok_unresolved_p1=2,
    )
    md = orch._format_unified_verdict(v)
    assert "Grok-flagged P1 patches unresolved: 2" in md
    assert "Human Review Required" in md


def test_format_omits_grok_row_when_zero() -> None:
    """When grok_unresolved_p1 == 0 the markdown is unchanged
    (no noise row for the common case)."""
    v = orch._compute_unified_verdict(
        _full_audit(), [], grok_unresolved_p1=0,
    )
    md = orch._format_unified_verdict(v)
    assert "Grok-flagged P1 patches unresolved" not in md
