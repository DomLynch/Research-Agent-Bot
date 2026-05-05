"""Fix #1 reviewer-P1: unified final verdict = worst(stage1, stage2).

Discriminating tests: each test isolates one specific verdict path so
a regression in the verdict logic is immediately attributable. Pre-fix
the orchestrator only printed stage-1's verdict; PMCID body leaks
caught only by stage-2 silently passed."""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import run_v06_synthesis as orch  # noqa: E402


@dataclass
class _FakeIssue:
    severity: str = "P1"


def _stage1_report(*, p1_pass: bool, n_pass: int, n_total: int = 10) -> dict:
    """Build a stage-1 audit report with N passing / N total checks."""
    checks = []
    for i in range(n_total):
        checks.append({
            "name": f"Q{i+1}",
            "passed": i < n_pass,
            "p1": i < 5,
            "detail": "",
        })
    return {
        "p1_pass": p1_pass,
        "score_out_of_10": float(n_pass),
        "checks": checks,
    }


def test_all_green_returns_aaa() -> None:
    """Stage-1 perfect + stage-2 empty → AAA."""
    s1 = _stage1_report(p1_pass=True, n_pass=10)
    u = orch._compute_unified_verdict(s1, [])
    assert u.verdict == "AAA"
    assert u.all_green is True
    assert u.p1_clean is True


def test_stage1_p1_fail_blocks_ship() -> None:
    """Stage-1 fails any P1 → SHIP-BLOCKED, regardless of stage-2."""
    s1 = _stage1_report(p1_pass=False, n_pass=4)
    u = orch._compute_unified_verdict(s1, [])
    assert u.verdict == "SHIP-BLOCKED"
    assert u.p1_clean is False


def test_stage2_p1_blocks_even_if_stage1_passes() -> None:
    """Pre-fix bug: stage-1 reported AAA while stage-2 had 53 PMCID
    body leaks (P1-grade for academic output). Now stage-2 P1 alone
    blocks ship."""
    s1 = _stage1_report(p1_pass=True, n_pass=10)
    issues = [_FakeIssue("P1")]
    u = orch._compute_unified_verdict(s1, issues)
    assert u.verdict == "SHIP-BLOCKED"
    assert u.stage2_p1 == 1


def test_stage1_p2_only_returns_trust_spine_pass() -> None:
    """P1 clean in both stages, but stage-1 has P2 fails → Trust-Spine
    Pass (not AAA — AAA is reserved for all-green)."""
    s1 = _stage1_report(p1_pass=True, n_pass=8)  # 2 P2 fails
    u = orch._compute_unified_verdict(s1, [])
    assert u.verdict == "Trust-Spine Pass"
    assert u.all_green is False


def test_stage2_p2_only_returns_trust_spine_pass() -> None:
    """Stage-1 perfect, stage-2 has P2 notes → Trust-Spine Pass."""
    s1 = _stage1_report(p1_pass=True, n_pass=10)
    issues = [_FakeIssue("P2"), _FakeIssue("P2"), _FakeIssue("P2")]
    u = orch._compute_unified_verdict(s1, issues)
    assert u.verdict == "Trust-Spine Pass"
    assert u.stage2_p2 == 3
    assert u.stage2_p1 == 0


def test_format_includes_both_stages_and_reason() -> None:
    """Markdown must surface BOTH stages AND the reason line so a
    reader can see WHY the verdict landed where it did."""
    s1 = _stage1_report(p1_pass=True, n_pass=10)
    issues = [_FakeIssue("P1")]
    u = orch._compute_unified_verdict(s1, issues)
    md = orch._format_unified_verdict(u)
    assert "SHIP-BLOCKED" in md
    assert "Stage-1 audit" in md
    assert "Stage-2 consistency" in md
    assert "P1 issues=1" in md
    assert "**Reason:**" in md and u.reason in md


# ----- Reviewer-fix discriminating tests (post-2x review) ---------------


def test_empty_checks_does_not_return_aaa() -> None:
    """Empty stage1 checks → cannot be AAA (would be vacuous success).
    Pre-fix: `n_pass==0 and n_total==0` evaluated as all-green and
    returned AAA — a real fail-open bug. Now requires positive evidence."""
    s1 = {"p1_pass": True, "score_out_of_10": 0.0, "checks": []}
    u = orch._compute_unified_verdict(s1, [])
    assert u.verdict != "AAA"
    assert u.all_green is False
    assert "ZERO checks" in u.reason


def test_unknown_severity_is_treated_as_blocking() -> None:
    """Fail-closed for unknown severities. Future reviewer prompts may
    introduce 'P0' or 'CRITICAL' — they MUST block ship by default."""
    s1 = _stage1_report(p1_pass=True, n_pass=10)
    issues = [_FakeIssue("P0"), _FakeIssue("CRITICAL"), _FakeIssue("WTF")]
    u = orch._compute_unified_verdict(s1, issues)
    assert u.verdict == "SHIP-BLOCKED"
    assert u.stage2_p1 == 3  # all three counted as blocking
    assert u.stage2_unknown_severity_count == 1  # only "WTF" is unknown
    # Reason must mention unknown for telemetry
    assert "unknown-severity" in u.reason or "incl." in u.reason


def test_missing_stage1_keys_fails_closed() -> None:
    """Pre-fix `stage1_report['p1_pass']` raised KeyError on partial
    reports (e.g., schema drift, error path returning {'error': ...}).
    Now we read with .get() defaults and treat missing as failure."""
    u = orch._compute_unified_verdict({}, [])
    assert u.verdict == "SHIP-BLOCKED"
    assert u.stage1_p1_pass is False
    # None passed because no checks defined
    u2 = orch._compute_unified_verdict(None, [])
    assert u2.verdict == "SHIP-BLOCKED"


def test_p3_and_info_are_nonblocking() -> None:
    """P3/INFO severities are explicit non-blockers (not unknown). They
    must not shift the verdict, not bump stage2_p1, not appear as
    unknown."""
    s1 = _stage1_report(p1_pass=True, n_pass=10)
    issues = [_FakeIssue("P3"), _FakeIssue("INFO")]
    u = orch._compute_unified_verdict(s1, issues)
    # No stage-2 P1/P2 → still all-green AAA (P3/INFO are noise)
    assert u.verdict == "AAA"
    assert u.stage2_p1 == 0
    assert u.stage2_p2 == 0
    assert u.stage2_unknown_severity_count == 0


# ---------- Certification floors (2026-05-05 wave 7 reviewer fix) --------

def test_aaa_blocked_when_below_cert_floor() -> None:
    """All audits clean but corpus thin → Trust-Spine Pass, not AAA.
    Reviewer-mandated floor: ≥10 receipts, ≥50 claims, ≥10 tensions."""
    s1 = _stage1_report(p1_pass=True, n_pass=10, n_total=10)
    v = orch._compute_unified_verdict(
        s1, [], grok_unresolved_p1=0,
        n_receipts=3, n_high_conf_claims=18,
        n_non_orthogonal_tensions=3,
    )
    assert v.verdict == "Trust-Spine Pass"
    assert "below certification floor" in v.reason


def test_aaa_clears_when_above_cert_floor() -> None:
    """Same all-green audits + corpus above floor → AAA."""
    s1 = _stage1_report(p1_pass=True, n_pass=10, n_total=10)
    v = orch._compute_unified_verdict(
        s1, [], grok_unresolved_p1=0,
        n_receipts=15, n_high_conf_claims=134,
        n_non_orthogonal_tensions=42,
    )
    assert v.verdict == "AAA"


def test_cert_floor_overridable_via_topic_pack() -> None:
    """Topic pack can lower or raise floors via cert_floors arg."""
    s1 = _stage1_report(p1_pass=True, n_pass=10, n_total=10)
    # Lowered floor → corpus that was previously below now passes
    v = orch._compute_unified_verdict(
        s1, [], grok_unresolved_p1=0,
        n_receipts=3, n_high_conf_claims=18,
        n_non_orthogonal_tensions=3,
        cert_floors={
            "min_receipts": 3, "min_high_conf_claims": 15,
            "min_non_orthogonal_tensions": 3,
        },
    )
    assert v.verdict == "AAA"
