from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import osf_publish as osf  # noqa: E402


def test_dry_run_writes_snapshot_and_plan_without_pat(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OSF_PAT", raising=False)
    (tmp_path / "paper.md").write_text("public", encoding="utf-8")
    paths = osf.run(tmp_path, dry_run=True, snapshot_only=False)
    assert paths["snapshot"] == tmp_path / "bundle_snapshot.json"
    assert paths["plan"] == tmp_path / "osf_publish_plan.json"
    assert paths["result"] is None
    plan = json.loads((tmp_path / "osf_publish_plan.json").read_text())
    assert plan["mode"] == "dry-run"
    assert plan["file_count"] == 1
    assert "OSF_PAT" not in json.dumps(plan)


def test_plan_and_header_helpers_do_not_store_pat(tmp_path: Path) -> None:
    (tmp_path / "paper.md").write_text("public", encoding="utf-8")
    snapshot = {
        "file_count": 1,
        "total_size": 6,
        "aggregate_sha256": "a" * 64,
        "files": [{"path": "paper.md", "size": 6, "sha256": "b" * 64}],
    }
    plan = osf.build_plan(tmp_path, snapshot, base_url="https://api.test/v2/")
    plan_path = osf.write_plan(tmp_path, plan)
    assert plan_path == tmp_path / osf.PLAN_NAME
    assert plan["osf_api"] == "https://api.test/v2"
    assert osf._auth_headers("test-secret-token")["Authorization"] == (
        "Bearer test-secret-token"
    )
    assert "test-secret-token" not in plan_path.read_text(encoding="utf-8")


def test_snapshot_only_does_not_write_plan(tmp_path: Path) -> None:
    (tmp_path / "paper.md").write_text("public", encoding="utf-8")
    paths = osf.run(tmp_path, dry_run=False, snapshot_only=True)
    assert paths["snapshot"] == tmp_path / "bundle_snapshot.json"
    assert paths["plan"] is None
    assert not (tmp_path / "osf_publish_plan.json").exists()


def test_live_mode_fails_closed_without_pat(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OSF_PAT", raising=False)
    (tmp_path / "paper.md").write_text("public", encoding="utf-8")
    with pytest.raises(RuntimeError, match="OSF_PAT"):
        osf.run(tmp_path, dry_run=False, snapshot_only=False)


def test_publish_live_uses_bearer_pat_but_never_returns_it(
    tmp_path: Path,
) -> None:
    (tmp_path / "paper.md").write_text("public", encoding="utf-8")
    snapshot = {
        "file_count": 1,
        "total_size": 6,
        "aggregate_sha256": "a" * 64,
        "files": [],
    }
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers["authorization"]
        captured["url"] = str(request.url)
        return httpx.Response(
            201,
            json={
                "data": {
                    "id": "abc123",
                    "links": {"html": "https://osf.io/abc123/"},
                },
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = osf.publish_live(
        tmp_path,
        snapshot,
        token="test-secret-token",
        client=client,
        base_url="https://api.test/v2",
    )
    assert captured["auth"] == "Bearer test-secret-token"
    assert captured["url"] == "https://api.test/v2/nodes/"
    assert result["osf_node_id"] == "abc123"
    assert "test-secret-token" not in json.dumps(result)


def test_live_run_writes_result_with_mock_transport(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OSF_PAT", "test-secret-token")
    (tmp_path / "paper.md").write_text("public", encoding="utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            201,
            json={"data": {"id": "abc123", "links": {"html": "https://osf.io/abc123/"}}},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    paths = osf.run(
        tmp_path,
        dry_run=False,
        snapshot_only=False,
        client=client,
    )
    result = json.loads((tmp_path / "osf_publish_result.json").read_text())
    assert paths["result"] == tmp_path / "osf_publish_result.json"
    assert result["osf_url"] == "https://osf.io/abc123/"
    assert "test-secret-token" not in json.dumps(result)


def test_main_dry_run_writes_plan_without_pat(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OSF_PAT", raising=False)
    (tmp_path / "paper.md").write_text("public", encoding="utf-8")
    assert osf.main(["--run-dir", str(tmp_path), "--dry-run"]) == 0
    assert (tmp_path / osf.PLAN_NAME).exists()
