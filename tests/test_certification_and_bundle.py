"""Researka Certified A2A-AAA — cert + public bundle tests.

Covers:
  - certification_report.certify_run on a real AAA run
  - certification_report.certify_consecutive on 2 AAA runs
  - failure-reason composition for non-AAA runs
  - old-defect scan catches the reviewer-flagged 0.13 m/s pattern
  - export_public_bundle copies all required artifacts
  - bundle README composition includes cert status + run summary

Most data-dependent tests skip gracefully when the run dir isn't
present (CI/VPS won't have local runs/).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import certification_report as cert  # noqa: E402
import export_public_bundle as bundle  # noqa: E402


# Pick the most-recent fix54-repro run as the canonical AAA fixture
def _latest_aaa_run() -> Path | None:
    """Return the most-recent run dir whose final_verdict.json says
    AAA. Used as a real-world fixture; skip tests when absent."""
    runs_dir = REPO / "runs"
    if not runs_dir.exists():
        return None
    candidates = []
    for d in runs_dir.iterdir():
        if not d.is_dir():
            continue
        verdict_path = d / "full_paper.final_verdict.json"
        if not verdict_path.exists():
            continue
        try:
            v = json.loads(verdict_path.read_text())
            if v.get("verdict") == "AAA":
                candidates.append(d)
        except (OSError, json.JSONDecodeError):
            continue
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


_AAA_RUN = _latest_aaa_run()
_skip_no_aaa = pytest.mark.skipif(
    _AAA_RUN is None,
    reason="no AAA run dir present (runs/ is gitignored on CI/VPS)",
)


# =========== Cert: pure-function tests (always run) ================


def test_old_defect_scan_catches_walk_speed_pattern() -> None:
    """The reviewer-flagged 'this walk speed value is below the 0.8'
    pattern must be caught by the old-defect scanner — defends
    against regression on the C13 cross-sentence misread."""
    paper = (
        "## Frailty\n\n"
        "MET-PREVENT showed 0.13 m/s improvement. "
        "This walk speed value is below the 0.8 m/s threshold "
        "associated with frailty.\n"
    )
    hits = cert._scan_old_defects(paper)
    ids = [h["id"] for h in hits]
    assert "walk_speed_parenthetical_threshold" in ids


def test_old_defect_scan_clean_on_legitimate_paper() -> None:
    """A paper that mentions 0.8 m/s legitimately (no anaphor + no
    threshold-comparison phrasing pointing back to a change value)
    must NOT trip the old-defect scan."""
    paper = (
        "## Methods\n\n"
        "We compared baseline gait speed (0.78 m/s) against the "
        "0.8 m/s normative cutoff and found no significant "
        "difference at 12 weeks.\n"
    )
    hits = cert._scan_old_defects(paper)
    assert hits == []


def test_old_defect_scan_catches_internal_run_tag() -> None:
    """Internal pipeline language ('Submission: synthesis-...') must
    not leak into prose — should be in supplement only."""
    paper = (
        "## Header\n\n**Submission:** `synthesis-metformin-v06-"
        "fix54-verify-2026-05-04T09-11-00Z`\n"
    )
    hits = cert._scan_old_defects(paper)
    ids = [h["id"] for h in hits]
    assert "internal_run_tag_in_prose" in ids


def test_consecutive_requires_two_runs() -> None:
    """The A2A-AAA gate refuses to certify with <2 runs."""
    result = cert.certify_consecutive([])
    assert result["certified"] is False
    assert "need" in result["reason"].lower()


def _passing_cert(
    run_id: str, *, auto_stripped: int = 0,
) -> cert.CertificationVerdict:
    return cert.CertificationVerdict(
        run_id=run_id, git_sha="deadbeef",
        timestamp_iso="2026-01-01T00:00:00Z",
        final_verdict="AAA",
        aaa_pass=True,
        q2_traceability_pct=100.0, q2_full=True,
        stage1_pass_rate="14/14",
        stage2_p1=0, stage2_p2=0, stage2_clean=True,
        grok_unresolved_p1=0, grok_clean=True,
        no_regression_pass=True,
        old_defect_scan_clean=True,
        auto_stripped_patches=auto_stripped,
    )


def test_consecutive_l5_runs_surface_l6(monkeypatch) -> None:
    """Two clean single-run certs surface L6 reproducibility."""
    monkeypatch.setattr(
        cert, "certify_run",
        lambda p: _passing_cert(p.parent.name),
    )
    result = cert.certify_consecutive([
        Path("run-a/full_paper.md"),
        Path("run-b/full_paper.md"),
    ])
    assert result["certified"] is True
    assert result["l6_reproducibly_journal_ready"] is True
    assert result["maturity_level"] == 6
    assert result["maturity_label"] == "L6 — REPRODUCIBLY JOURNAL-READY"


def test_consecutive_auto_strip_blocks_l6_only(monkeypatch) -> None:
    """AAA can remain consecutive while L6 refuses strip-scarred runs."""
    vals = [_passing_cert("run-a"), _passing_cert("run-b", auto_stripped=1)]
    monkeypatch.setattr(cert, "certify_run", lambda p: vals.pop(0))
    result = cert.certify_consecutive([
        Path("run-a/full_paper.md"),
        Path("run-b/full_paper.md"),
    ])
    assert result["certified"] is True
    assert result["l6_reproducibly_journal_ready"] is False
    assert result["maturity_level"] == 5


def test_failure_reasons_lists_all_failed_criteria() -> None:
    """If a verdict has multiple failures, _failure_reasons surfaces
    each one — important for actionable cert.md output."""
    bad = cert.CertificationVerdict(
        run_id="test-run", git_sha="deadbeef",
        timestamp_iso="2026-01-01T00:00:00Z",
        final_verdict="Trust-Spine Pass",
        aaa_pass=False,
        q2_traceability_pct=85.0, q2_full=False,
        stage1_pass_rate="11/13",
        stage2_p1=2, stage2_p2=1, stage2_clean=False,
        grok_unresolved_p1=1, grok_clean=False,
        no_regression_pass=False,
        old_defect_scan_clean=False,
        old_defect_hits=[
            {"id": "x", "description": "y", "sample": "z"}
        ],
    )
    reasons = cert._failure_reasons(bad)
    assert len(reasons) >= 5
    assert any("AAA" in r for r in reasons)
    assert any("Q2" in r for r in reasons)
    assert any("stage2" in r for r in reasons)
    assert any("grok" in r.lower() for r in reasons)
    assert any("no_regression" in r for r in reasons)
    assert any("old_defect" in r for r in reasons)


# =========== Cert: data-dependent tests (skip if no run) ===========


@_skip_no_aaa
def test_certify_run_on_real_aaa_run() -> None:
    """End-to-end on the most-recent AAA run dir."""
    paper_path = _AAA_RUN / "full_paper.md"
    verdict = cert.certify_run(paper_path)
    assert verdict.aaa_pass, (
        f"Real AAA run dir {_AAA_RUN.name} cert says aaa_pass=False"
    )
    assert verdict.q2_full, "Q2 must be 100% on AAA run"
    assert verdict.stage2_clean, "Stage-2 must be 0/0 on AAA run"
    # If old_defect_scan fails, the run was wrongly verdicted AAA —
    # important regression signal
    if not verdict.old_defect_scan_clean:
        pytest.fail(
            f"AAA run has old-defect hits: "
            f"{[h['id'] for h in verdict.old_defect_hits]}"
        )


@_skip_no_aaa
def test_write_certification_creates_both_artifacts() -> None:
    """certify + write_certification → JSON + MD next to paper."""
    paper_path = _AAA_RUN / "full_paper.md"
    verdict = cert.certify_run(paper_path)
    json_p, md_p = cert.write_certification(paper_path, verdict)
    assert json_p.exists()
    assert md_p.exists()
    assert json_p.suffix == ".json"
    assert md_p.suffix == ".md"
    # JSON round-trip
    loaded = json.loads(json_p.read_text())
    assert loaded["run_id"] == _AAA_RUN.name
    assert loaded["final_verdict"] == "AAA"


# =========== Bundle: data-dependent tests ==========================


@_skip_no_aaa
def test_export_bundle_copies_all_required_files(
    tmp_path: Path,
) -> None:
    """Bundle exporter must copy every required file. Optional
    files (cert, no_reg) may be skipped if absent."""
    # Make sure cert exists on the source so this test exercises
    # the full path
    cert.write_certification(
        _AAA_RUN / "full_paper.md",
        cert.certify_run(_AAA_RUN / "full_paper.md"),
    )
    out_dir = tmp_path / "test_bundle"
    result = bundle.export_bundle(_AAA_RUN, out_dir)
    assert result["missing_required"] == [], (
        f"Bundle missing required files: {result['missing_required']}"
    )
    # Required files must all be in out_dir
    for src_name, dst_name in bundle._FILE_MAP.items():
        if src_name in bundle._OPTIONAL:
            continue
        assert (out_dir / dst_name).exists(), (
            f"Required bundled file missing: {dst_name}"
        )
    # README composed
    assert (out_dir / "README.md").exists()


@_skip_no_aaa
def test_bundle_readme_includes_cert_status(tmp_path: Path) -> None:
    """The composed README must include the cert verdict + run
    summary so a reader can scan-verify in seconds."""
    cert.write_certification(
        _AAA_RUN / "full_paper.md",
        cert.certify_run(_AAA_RUN / "full_paper.md"),
    )
    out_dir = tmp_path / "test_bundle"
    bundle.export_bundle(_AAA_RUN, out_dir)
    readme = (out_dir / "README.md").read_text()
    assert "Researka Public Bundle" in readme
    assert "Final verdict:" in readme
    assert "Run-level summary" in readme
    assert "How to verify" in readme
    assert "trust-spine" in readme.lower()


@_skip_no_aaa
def test_bundle_self_contained_no_repo_references(
    tmp_path: Path,
) -> None:
    """A bundle should be opaque — no references to the parent repo
    paths in the README. Means a reader can move bundle to OSF /
    Zenodo and links still work."""
    cert.write_certification(
        _AAA_RUN / "full_paper.md",
        cert.certify_run(_AAA_RUN / "full_paper.md"),
    )
    out_dir = tmp_path / "test_bundle"
    bundle.export_bundle(_AAA_RUN, out_dir)
    readme = (out_dir / "README.md").read_text()
    # Should NOT contain absolute paths from the dev's machine
    assert "/Users/" not in readme
    assert "/opt/" not in readme
    # Should NOT contain "../runs/" pointers
    assert "../runs/" not in readme


# =========== Bundle: file-map invariant ============================


def test_bundle_file_map_has_no_duplicate_destinations() -> None:
    """Every src→dst mapping must produce a unique destination
    filename (no two source files clobber each other in the bundle).
    """
    dst_names = list(bundle._FILE_MAP.values())
    assert len(dst_names) == len(set(dst_names)), (
        f"Duplicate bundle destinations: "
        f"{[n for n in dst_names if dst_names.count(n) > 1]}"
    )


def test_bundle_optional_set_is_subset_of_file_map() -> None:
    """_OPTIONAL must reference only filenames that actually exist
    in _FILE_MAP — sanity check against typos."""
    src_names = set(bundle._FILE_MAP.keys())
    assert bundle._OPTIONAL.issubset(src_names), (
        f"_OPTIONAL has filenames not in _FILE_MAP: "
        f"{bundle._OPTIONAL - src_names}"
    )


def test_bundle_synthesizes_empty_patch_log_when_review_had_no_decisions(
    tmp_path: Path,
) -> None:
    """Runs with no review decisions still export a public patch_log.json."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    for src_name in bundle._FILE_MAP:
        if src_name in bundle._OPTIONAL or src_name == "full_paper.review_patch_log.json":
            continue
        path = run_dir / src_name
        path.write_text("{}" if src_name.endswith(".json") else "ok\n")
    (run_dir / "full_paper.review_patches.json").write_text('{"n_patches": 0}')

    out_dir = tmp_path / "bundle"
    result = bundle.export_bundle(run_dir, out_dir)

    assert result["missing_required"] == []
    log = json.loads((out_dir / "patch_log.json").read_text())
    assert log["n_proposed"] == 0
    assert log["patches"] == []
