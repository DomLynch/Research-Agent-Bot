from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import release_watchdog_deep as deep  # noqa: E402


def test_dirty_lane_classification() -> None:
    rows = deep.parse_status(
        "A  docs/release_watchdog_v2.md\n"
        "?? reports/release_watchdog_deep/report.md\n"
        "A  scripts/reader_publication_report.py\n"
    )
    assert [row["lane"] for row in rows] == ["release_watchdog_deep", "release_watchdog_deep", "reader"]
    assert rows[0]["staged"] is True


def test_secret_scan_avoids_plain_token_false_positive(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "note.md").write_text("This mentions token handling only.", encoding="utf-8")
    assert deep.scan_secrets(tmp_path, ["docs"]) == []


def test_secret_scan_catches_osf_pat_assignment(tmp_path: Path) -> None:
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "bad.py").write_text("OSF_PAT=" + "a" * 32, encoding="utf-8")
    assert deep.scan_secrets(tmp_path, ["scripts"]) == [
        {"path": "scripts/bad.py", "patterns": "osf_pat_assignment"}
    ]


def test_secret_scan_catches_bare_pat_shape(tmp_path: Path) -> None:
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "bad.txt").write_text("A" * 30 + "b" * 30 + "1" * 20, encoding="utf-8")
    assert deep.scan_secrets(tmp_path, ["reports"]) == [
        {"path": "reports/bad.txt", "patterns": "bare_80char_mixed_token"}
    ]


def test_osf_placement_warns_on_runtime_secret_use(tmp_path: Path) -> None:
    (tmp_path / "agent").mkdir()
    (tmp_path / "agent" / "bad.py").write_text(
        'token = os.environ["OSF_PAT"]\nbase = "https://api.osf.io/v2"\n',
        encoding="utf-8",
    )
    assert deep.scan_osf_placement(tmp_path) == [
        {"path": "agent/bad.py", "patterns": "osf_pat,osf_api"}
    ]


def test_osf_placement_rejects_bot_side_publisher_surface(tmp_path: Path) -> None:
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "osf_publish.py").write_text(
        'token = os.environ["OSF_PAT"]\nbase = "https://api.osf.io/v2"\n',
        encoding="utf-8",
    )
    assert deep.scan_osf_placement(tmp_path) == [
        {"path": "scripts/osf_publish.py", "patterns": "osf_pat,osf_api"}
    ]


def test_large_file_warning(tmp_path: Path) -> None:
    path = tmp_path / "big.bin"
    path.write_bytes(b"x" * 12)
    rows = [{"path": "big.bin", "lane": "other"}]
    assert deep.large_file_warnings(tmp_path, rows, 10) == [
        {"path": "big.bin", "bytes": 12, "lane": "other"}
    ]


def test_sha_and_vps_200_acceptance(tmp_path: Path) -> None:
    tri = {
        "local": {"head": "abc12345"},
        "vps": [{
            "path": "/opt/research-agent-bot",
            "head": "abc12345",
            "dirty_count": 0,
            "service": "active",
            "http": "200",
        }],
    }
    report = deep.build_report(
        repo=tmp_path,
        status_text="",
        sha_text="local_full=abc123456789\norigin_full=abc123456789\n",
        tri_sync=tri,
        secret_roots=[],
    )
    assert report["verdict"] == "PASS"
    assert report["sha"]["vps_match"] is True
    assert report["osf_placement_warnings"] == []


def test_vps_503_blocks_live_release(tmp_path: Path) -> None:
    tri = {
        "local": {"head": "abc12345"},
        "vps": [{
            "path": "/opt/research-agent-bot",
            "head": "abc12345",
            "dirty_count": 0,
            "service": "active",
            "http": "503",
        }],
    }
    report = deep.build_report(
        repo=tmp_path,
        status_text="",
        sha_text="local_full=abc123456789\norigin_full=abc123456789\n",
        tri_sync=tri,
        secret_roots=[],
    )
    assert report["verdict"] == "BLOCKED"
    assert "VPS warning(s)" in report["blockers"]


def test_sha_mismatch_blocks() -> None:
    report = deep.build_report(
        repo=Path("."),
        status_text="",
        sha_text="local_full=a\norigin_full=b\n",
        tri_sync={"local": {}, "vps": []},
        secret_roots=[],
    )
    assert "local/origin full SHA mismatch" in report["blockers"]


def test_cli_writes_outputs(tmp_path: Path) -> None:
    status = tmp_path / "status.txt"
    status.write_text("", encoding="utf-8")
    sha = tmp_path / "sha.txt"
    sha.write_text("local_full=a\norigin_full=a\n", encoding="utf-8")
    tri = tmp_path / "tri.json"
    tri.write_text(json.dumps({"local": {}, "vps": []}), encoding="utf-8")
    out_json = tmp_path / "report.json"
    out_md = tmp_path / "report.md"
    assert deep.main(
        [
            "--repo",
            str(tmp_path),
            "--status",
            str(status),
            "--sha",
            str(sha),
            "--tri-sync-json",
            str(tri),
            "--out-json",
            str(out_json),
            "--out-md",
            str(out_md),
        ]
    ) == 0
    assert json.loads(out_json.read_text(encoding="utf-8"))["verdict"] == "PASS"
    assert "# Release Watchdog Deep Report" in out_md.read_text(encoding="utf-8")
