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


def test_cert_floor_topic_pack_can_raise_only_not_lower() -> None:
    """Reviewer P1 (2026-05-05 wave 8): cert floors are global policy.
    Topic packs may RAISE the bar but cannot lower it. A pack saying
    min_receipts=3 gets max(default=10, pack=3) = 10, so a 3-receipt
    corpus still fails the floor."""
    s1 = _stage1_report(p1_pass=True, n_pass=10, n_total=10)
    # Pack tries to LOWER floor — must be ignored
    v = orch._compute_unified_verdict(
        s1, [], grok_unresolved_p1=0,
        n_receipts=3, n_high_conf_claims=18,
        n_non_orthogonal_tensions=3,
        cert_floors={
            "min_receipts": 3, "min_high_conf_claims": 15,
            "min_non_orthogonal_tensions": 3,
        },
    )
    assert v.verdict == "Trust-Spine Pass"
    assert "below certification floor" in v.reason


def test_cert_floor_topic_pack_can_raise_above_default() -> None:
    """A pack RAISING floor above default works — stricter topics
    can require more corpus."""
    s1 = _stage1_report(p1_pass=True, n_pass=10, n_total=10)
    v = orch._compute_unified_verdict(
        s1, [], grok_unresolved_p1=0,
        n_receipts=12, n_high_conf_claims=60,
        n_non_orthogonal_tensions=12,
        cert_floors={
            "min_receipts": 20,
            "min_high_conf_claims": 100,
            "min_non_orthogonal_tensions": 15,
        },
    )
    assert v.verdict == "Trust-Spine Pass"


# ---------- Wave 7 / Slice 2: corpus_gaps + expansion_targets -------

def test_corpus_gaps_default_empty_when_no_manifest_passed() -> None:
    """Back-compat: callers that don't pass manifest get empty tuples,
    not None — UnifiedVerdict.corpus_gaps is `tuple[str, ...] = ()`."""
    s1 = _stage1_report(p1_pass=True, n_pass=10, n_total=10)
    v = orch._compute_unified_verdict(s1, [])
    assert v.corpus_gaps == ()
    assert v.expansion_targets == ()


def test_corpus_gaps_populated_when_manifest_below_floor() -> None:
    """Sub-AAA verdict carries the actionable to-do list. Universal —
    no drug names, gaps are derived purely from manifest signals."""
    s1 = _stage1_report(p1_pass=True, n_pass=10, n_total=10)
    manifest = {
        "n_receipts": 3, "n_high_confidence_claims_total": 12,
        "n_non_orthogonal_tensions": 1,
        "receipts": [
            {"outcome_class": "longevity", "evidence_tier": "B1",
             "directness": "review", "receipt_id": "X_2024"},
        ],
    }
    v = orch._compute_unified_verdict(
        s1, [], grok_unresolved_p1=0,
        n_receipts=3, n_high_conf_claims=12,
        n_non_orthogonal_tensions=1,
        manifest=manifest,
    )
    assert v.verdict == "Trust-Spine Pass"
    assert len(v.corpus_gaps) >= 3  # receipts + claims + tensions
    assert len(v.expansion_targets) == len(v.corpus_gaps)
    assert any("Receipts" in g for g in v.corpus_gaps)


def test_aaa_path_emits_no_corpus_gaps() -> None:
    """An AAA-clearing run should emit empty corpus_gaps even when
    manifest is passed — gaps are diagnostic, not noise."""
    s1 = _stage1_report(p1_pass=True, n_pass=10, n_total=10)
    manifest = {
        "n_receipts": 15,
        "n_high_confidence_claims_total": 134,
        "n_non_orthogonal_tensions": 42,
        "receipts": [
            {"outcome_class": "muscle_function", "evidence_tier": "A1",
             "directness": "direct", "receipt_id": f"P{i}"}
            for i in range(5)
        ] + [
            {"outcome_class": "cardiometabolic", "evidence_tier": "A1",
             "directness": "direct", "receipt_id": f"Q{i}"}
            for i in range(5)
        ] + [
            {"outcome_class": "longevity", "evidence_tier": "A2",
             "directness": "direct", "receipt_id": f"R{i}"}
            for i in range(5)
        ],
    }
    v = orch._compute_unified_verdict(
        s1, [], grok_unresolved_p1=0,
        n_receipts=15, n_high_conf_claims=134,
        n_non_orthogonal_tensions=42,
        manifest=manifest,
    )
    assert v.verdict == "AAA"
    assert v.corpus_gaps == ()
    assert v.expansion_targets == ()


def test_format_unified_verdict_includes_expansion_section() -> None:
    """When the verdict carries gaps, the rendered markdown must
    contain the Corpus Expansion To-Do block (Slice 2 wiring)."""
    s1 = _stage1_report(p1_pass=True, n_pass=10, n_total=10)
    manifest = {
        "n_receipts": 3, "n_high_confidence_claims_total": 12,
        "n_non_orthogonal_tensions": 1, "receipts": [],
    }
    v = orch._compute_unified_verdict(
        s1, [], grok_unresolved_p1=0,
        n_receipts=3, n_high_conf_claims=12,
        n_non_orthogonal_tensions=1, manifest=manifest,
    )
    md = orch._format_unified_verdict(v)
    assert "Corpus Expansion To-Do" in md
    assert "Gap:" in md
    assert "Action:" in md


def test_format_unified_verdict_omits_expansion_when_no_gaps() -> None:
    """AAA path → no expansion section in the rendered markdown."""
    s1 = _stage1_report(p1_pass=True, n_pass=10, n_total=10)
    v = orch._compute_unified_verdict(s1, [])
    md = orch._format_unified_verdict(v)
    assert "Corpus Expansion To-Do" not in md


# ---------- Wave 7 / Slice 3: maturity ladder + Journal-Ready -------

def test_l5_journal_ready_on_clean_aaa_run() -> None:
    """AAA + manifest above floor + zero grok + zero auto-strip → L5."""
    s1 = _stage1_report(p1_pass=True, n_pass=10, n_total=10)
    manifest = {
        "n_receipts": 15, "n_high_confidence_claims_total": 134,
        "n_non_orthogonal_tensions": 42,
        "receipts": [
            {"outcome_class": ["a", "b", "c"][i % 3],
             "evidence_tier": "A1", "directness": "direct",
             "receipt_id": f"P{i}"} for i in range(15)
        ],
    }
    v = orch._compute_unified_verdict(
        s1, [], grok_unresolved_p1=0,
        n_receipts=15, n_high_conf_claims=134,
        n_non_orthogonal_tensions=42,
        manifest=manifest, auto_stripped_count=0,
    )
    assert v.verdict == "AAA"
    assert v.maturity_level == 5
    assert v.maturity_label == "L5 — JOURNAL-READY"
    assert v.journal_ready is True


def test_l4_aaa_but_surgery_blocks_journal_ready() -> None:
    """AAA but auto-strip had to remove sentences → L4, not journal-ready."""
    s1 = _stage1_report(p1_pass=True, n_pass=10, n_total=10)
    manifest = {
        "n_receipts": 15, "n_high_confidence_claims_total": 134,
        "n_non_orthogonal_tensions": 42,
        "receipts": [
            {"outcome_class": ["a", "b", "c"][i % 3],
             "evidence_tier": "A1", "directness": "direct",
             "receipt_id": f"P{i}"} for i in range(15)
        ],
    }
    v = orch._compute_unified_verdict(
        s1, [], grok_unresolved_p1=0,
        n_receipts=15, n_high_conf_claims=134,
        n_non_orthogonal_tensions=42,
        manifest=manifest, auto_stripped_count=4,
    )
    assert v.maturity_level == 4
    assert v.journal_ready is False


def test_l4_aaa_but_surface_gate_blocks_journal_ready() -> None:
    """Analytical AAA remains AAA, but Journal-Ready is capped by
    manuscript-surface failures."""
    s1 = _stage1_report(p1_pass=True, n_pass=10, n_total=10)
    manifest = {
        "n_receipts": 15, "n_high_confidence_claims_total": 134,
        "n_non_orthogonal_tensions": 42,
        "receipts": [
            {"outcome_class": ["a", "b", "c"][i % 3],
             "evidence_tier": "A1", "directness": "direct",
             "receipt_id": f"P{i}"} for i in range(15)
        ],
    }
    v = orch._compute_unified_verdict(
        s1, [], grok_unresolved_p1=0,
        n_receipts=15, n_high_conf_claims=134,
        n_non_orthogonal_tensions=42,
        manifest=manifest, auto_stripped_count=0,
        journal_surface_pass=False,
        journal_surface_issues=("qei_surface: endpoint/unit mismatch",),
    )
    assert v.verdict == "AAA"
    assert v.maturity_level == 4
    assert v.journal_ready is False
    md = orch._format_unified_verdict(v)
    assert "Journal surface gate: fail" in md


def test_l2_when_corpus_thin() -> None:
    """Below cert floor with claims → L2."""
    s1 = _stage1_report(p1_pass=True, n_pass=10, n_total=10)
    manifest = {
        "n_receipts": 3, "n_high_confidence_claims_total": 12,
        "n_non_orthogonal_tensions": 1, "receipts": [],
    }
    v = orch._compute_unified_verdict(
        s1, [], grok_unresolved_p1=0,
        n_receipts=3, n_high_conf_claims=12,
        n_non_orthogonal_tensions=1, manifest=manifest,
    )
    assert v.maturity_level == 2
    assert v.journal_ready is False


def test_format_unified_verdict_renders_maturity_badge_and_journal_line() -> None:
    """Both the maturity badge and the journal-ready line must
    appear in the rendered markdown."""
    s1 = _stage1_report(p1_pass=True, n_pass=10, n_total=10)
    manifest = {
        "n_receipts": 15, "n_high_confidence_claims_total": 134,
        "n_non_orthogonal_tensions": 42,
        "receipts": [
            {"outcome_class": ["a", "b", "c"][i % 3],
             "evidence_tier": "A1", "directness": "direct",
             "receipt_id": f"P{i}"} for i in range(15)
        ],
    }
    v = orch._compute_unified_verdict(
        s1, [], grok_unresolved_p1=0,
        n_receipts=15, n_high_conf_claims=134,
        n_non_orthogonal_tensions=42,
        manifest=manifest, auto_stripped_count=0,
    )
    md = orch._format_unified_verdict(v)
    assert "**Maturity:" in md
    assert "L5 — JOURNAL-READY" in md
    assert "**Journal-Ready: yes**" in md


def test_format_unified_verdict_journal_ready_no_when_thin() -> None:
    """Thin corpus → 'Journal-Ready: no' surfaces explicitly."""
    s1 = _stage1_report(p1_pass=True, n_pass=10, n_total=10)
    manifest = {
        "n_receipts": 3, "n_high_confidence_claims_total": 12,
        "n_non_orthogonal_tensions": 1, "receipts": [],
    }
    v = orch._compute_unified_verdict(
        s1, [], grok_unresolved_p1=0,
        n_receipts=3, n_high_conf_claims=12,
        n_non_orthogonal_tensions=1, manifest=manifest,
    )
    md = orch._format_unified_verdict(v)
    assert "**Journal-Ready: no**" in md
