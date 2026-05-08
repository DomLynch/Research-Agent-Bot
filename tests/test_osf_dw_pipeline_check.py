from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import osf_dw_pipeline_check as check  # noqa: E402


SOURCE = (REPO / "scripts" / "osf_dw_pipeline_check.py").read_text(encoding="utf-8")


def _run_dir(tmp_path: Path) -> Path:
    (tmp_path / "paper.md").write_text("paper", encoding="utf-8")
    (tmp_path / "manifest.json").write_text(
        json.dumps({"topic": "demo-topic"}),
        encoding="utf-8",
    )
    (tmp_path / "bundle_snapshot.json").write_text("{}", encoding="utf-8")
    (tmp_path / "osf_publish_plan.json").write_text("{}", encoding="utf-8")
    (tmp_path / "osf_publish_result.json").write_text("{}", encoding="utf-8")
    (tmp_path / "researka_reader_manifest.json").write_text("{}", encoding="utf-8")
    return tmp_path


def test_pipeline_check_builds_dry_run_shapes(tmp_path: Path) -> None:
    result = check.build_check(
        _run_dir(tmp_path),
        public_url="https://researka.io/topic/demo-topic/v1",
        osf_node_id="abc123",
        osf_url="https://osf.io/abc123/",
    )

    assert result["ok"] is True
    assert result["errors"] == []
    assert result["dry_run_only"] is True
    assert result["live_mode"] == "not supported by verifier"
    assert result["upstream_live_gate"] == {
        "cli_flag": "--live",
        "env_var": "OSF_PUBLISH_LIVE",
    }
    assert result["idempotency_stable"] == {
        "osf_idempotency_key": True,
        "dw_idempotency_key": True,
    }
    assert result["secret_scan"]["passed"] is True
    assert len(result["osf_plan"]["idempotency_key"]) == 64
    assert result["dw_payload"]["idempotency_key"].startswith("dw-register:")
    assert result["reader_manifest"]["public_url"] == (
        "https://researka.io/topic/demo-topic/v1"
    )
    assert result["dw_payload"]["osf"] == {
        "node_id": "abc123",
        "url": "https://osf.io/abc123/",
        "doi": None,
    }


def test_generated_publisher_artifacts_are_not_uploaded(tmp_path: Path) -> None:
    result = check.build_check(
        _run_dir(tmp_path),
        public_url="https://researka.io/topic/demo-topic/v1",
    )

    assert "paper.md" in result["osf_plan"]["planned_paths"]
    assert "manifest.json" in result["osf_plan"]["planned_paths"]
    assert not (set(result["osf_plan"]["planned_paths"]) & check.GENERATED_NAMES)
    assert not (set(result["reader_manifest"]["paths"]) & check.GENERATED_NAMES)


def test_validation_reports_missing_required_slots() -> None:
    errors = check._validate(  # noqa: SLF001
        {"planned_files": [{"path": "paper.md"}]},
        {
            "public_url": None,
            "files": [{"path": "osf_publish_plan.json"}],
        },
        {"osf": {"url": "https://osf.io/abc123/"}},
    )

    assert "osf plan missing idempotency_key" in errors
    assert "dw payload missing idempotency_key" in errors
    assert "public_url missing" in errors
    assert any("generated artifacts" in error for error in errors)
    assert "dw payload missing osf slots" in errors


def test_secret_scan_helper_detects_token_markers() -> None:
    assert check.contains_secret_marker("Authorization: Bearer abc") is True
    assert check.contains_secret_marker("clean report") is False


def test_verifier_source_does_not_read_tokens_or_env() -> None:
    assert "\nimport os\n" not in SOURCE
    assert "os.environ" not in SOURCE


def test_cli_prints_sanitized_report_without_tokens(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setenv("OSF_PAT", "dummy")
    monkeypatch.setenv("DW_API_TOKEN", "dummy")

    rc = check.main(
        [
            str(_run_dir(tmp_path)),
            "--public-url",
            "https://researka.io/topic/demo-topic/v1",
            "--osf-node-id",
            "abc123",
        ]
    )

    out = capsys.readouterr().out
    assert rc == 0
    assert json.loads(out)["ok"] is True
    assert "dummy" not in out


def test_latest_omega3_or_cr_real_run_dry_smoke() -> None:
    runs = sorted(
        [
            *REPO.glob("runs/synthesis-omega3-*"),
            *REPO.glob("runs/synthesis-cr-*"),
            *REPO.glob("runs/synthesis-creatine-*"),
        ]
    )
    if not runs:
        pytest.skip("no omega3/CR run dirs available")
    result = check.build_check(
        runs[-1],
        public_url="https://researka.io/dry-run",
        osf_node_id="dryrun",
        osf_url="https://osf.io/dryrun/",
    )
    assert result["ok"] is True
    assert result["osf_plan"]["file_count"] > 0
