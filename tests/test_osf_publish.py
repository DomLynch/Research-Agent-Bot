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
    assert plan["planned_files"] == [
        {
            "file_url": None,
            "path": "paper.md",
            "sha256": plan["planned_files"][0]["sha256"],
            "size": 6,
        }
    ]
    assert "OSF_PAT" not in json.dumps(plan)


def test_dry_run_ignores_pat_and_excludes_generated_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OSF_PAT", "dummy")
    (tmp_path / "paper.md").write_text("public", encoding="utf-8")
    (tmp_path / osf.RESULT_NAME).write_text("{}", encoding="utf-8")
    (tmp_path / "researka_reader_manifest.json").write_text("{}", encoding="utf-8")

    paths = osf.run(tmp_path, dry_run=True, snapshot_only=False, force=True)

    snapshot = json.loads(paths["snapshot"].read_text(encoding="utf-8"))
    plan = json.loads(paths["plan"].read_text(encoding="utf-8"))
    assert [item["path"] for item in snapshot["files"]] == ["paper.md"]
    assert [item["path"] for item in plan["planned_files"]] == ["paper.md"]
    serialized = json.dumps({"snapshot": snapshot, "plan": plan})
    assert "dummy" not in serialized
    assert osf.RESULT_NAME not in serialized
    assert "researka_reader_manifest.json" not in serialized


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
    assert plan["aggregate_sha"] == "a" * 64
    assert plan["aggregate_sha256"] == "a" * 64
    assert len(plan["idempotency_key"]) == 64
    assert plan["planned_files"][0]["file_url"] is None
    assert osf._auth_headers("dummy")["Authorization"] == (
        "Bearer dummy"
    )
    assert "dummy" not in plan_path.read_text(encoding="utf-8")


def test_snapshot_only_does_not_write_plan(tmp_path: Path) -> None:
    (tmp_path / "paper.md").write_text("public", encoding="utf-8")
    paths = osf.run(tmp_path, dry_run=False, snapshot_only=True)
    assert paths["snapshot"] == tmp_path / "bundle_snapshot.json"
    assert paths["plan"] is None
    assert not (tmp_path / "osf_publish_plan.json").exists()


def test_snapshot_only_ignores_existing_publish_result(tmp_path: Path) -> None:
    (tmp_path / "paper.md").write_text("public", encoding="utf-8")
    (tmp_path / osf.RESULT_NAME).write_text("{}", encoding="utf-8")

    paths = osf.run(tmp_path, dry_run=False, snapshot_only=True)

    assert paths["snapshot"] == tmp_path / "bundle_snapshot.json"
    assert paths["result"] is None


def test_live_mode_fails_closed_without_pat(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OSF_PAT", raising=False)
    monkeypatch.setenv(osf.LIVE_ENV, "1")
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
        "files": [{"path": "paper.md", "size": 6, "sha256": "b" * 64}],
    }
    captured = {"uploads": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers["authorization"]
        captured["url"] = str(request.url)
        if request.method == "PUT":
            captured["uploads"] += 1
            return httpx.Response(
                201,
                json={"data": {"links": {"html": "https://osf.io/abc123/files/paper/"}}},
            )
        captured["idempotency"] = request.headers.get("idempotency-key")
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
        token="dummy",
        client=client,
        base_url="https://api.test/v2",
    )
    assert captured["auth"] == "Bearer dummy"
    assert len(captured["idempotency"]) == 64
    assert result["node_id"] == "abc123"
    assert result["osf_node_id"] == "abc123"
    assert result["url"] == "https://osf.io/abc123/"
    assert result["osf_url"] == "https://osf.io/abc123/"
    assert result["uploaded_files"] == [
        {"path": "paper.md", "file_url": "https://osf.io/abc123/files/paper/"}
    ]
    assert result["errors"] == []
    assert captured["uploads"] == 1
    assert "dummy" not in json.dumps(result)


def test_live_run_writes_result_with_mock_transport(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OSF_PAT", "dummy")
    monkeypatch.setenv(osf.LIVE_ENV, "1")
    (tmp_path / "paper.md").write_text("public", encoding="utf-8")
    seen_paths = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PUT":
            seen_paths.append(str(request.url))
            return httpx.Response(
                201,
                json={"data": {"links": {"html": "https://osf.io/file/"}}},
            )
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
    assert result["url"] == "https://osf.io/abc123/"
    assert len(result["idempotency_key"]) == 64
    assert result["planned_files"][0]["path"] == "paper.md"
    assert len(seen_paths) == 1
    assert "bundle_snapshot.json" not in seen_paths[0]
    assert "osf_publish_plan.json" not in seen_paths[0]
    assert "osf_publish_result.json" not in seen_paths[0]
    assert "dummy" not in json.dumps(result)


def test_run_skips_existing_result_unless_forced(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OSF_PAT", raising=False)
    result_path = tmp_path / osf.RESULT_NAME
    result_path.write_text("{}", encoding="utf-8")
    paths = osf.run(tmp_path, dry_run=True, snapshot_only=False)
    assert paths == {"snapshot": None, "plan": None, "result": result_path}
    assert not (tmp_path / "bundle_snapshot.json").exists()
    assert not (tmp_path / osf.PLAN_NAME).exists()

    (tmp_path / "paper.md").write_text("public", encoding="utf-8")
    paths = osf.run(tmp_path, dry_run=True, snapshot_only=False, force=True)
    assert paths["plan"] == tmp_path / osf.PLAN_NAME


def test_upload_file_retries_transient_without_leaking_token(tmp_path: Path) -> None:
    (tmp_path / "paper.md").write_text("public", encoding="utf-8")
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, json={"detail": "slow down dummy"})
        return httpx.Response(
            201,
            json={"data": {"links": {"html": "https://osf.io/file/"}}},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    uploaded = osf.upload_file(
        client,
        node_id="abc123",
        run_dir=tmp_path,
        rel_path="paper.md",
        token="dummy",
        files_url="https://files.test/v1",
    )
    assert len(calls) == 2
    assert uploaded == {"path": "paper.md", "file_url": "https://osf.io/file/"}


def test_live_result_errors_do_not_include_token(tmp_path: Path) -> None:
    (tmp_path / "paper.md").write_text("public", encoding="utf-8")
    snapshot = {
        "file_count": 1,
        "total_size": 6,
        "aggregate_sha256": "a" * 64,
        "files": [{"path": "paper.md", "size": 6, "sha256": "b" * 64}],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PUT":
            return httpx.Response(500, json={"detail": "dummy"})
        return httpx.Response(
            201,
            json={"data": {"id": "abc123", "links": {"html": "https://osf.io/abc123/"}}},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = osf.publish_live(
        tmp_path,
        snapshot,
        token="dummy",
        client=client,
        base_url="https://api.test/v2",
        files_url="https://files.test/v1",
    )
    assert result["errors"] == ["paper.md: HTTP 500"]
    assert "dummy" not in json.dumps(result)


def test_main_dry_run_writes_plan_without_pat(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OSF_PAT", raising=False)
    (tmp_path / "paper.md").write_text("public", encoding="utf-8")
    assert osf.main(["--run-dir", str(tmp_path)]) == 0
    assert (tmp_path / osf.PLAN_NAME).exists()


def test_live_mode_requires_env_gate_before_pat(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OSF_PAT", "dummy")
    monkeypatch.delenv(osf.LIVE_ENV, raising=False)
    (tmp_path / "paper.md").write_text("public", encoding="utf-8")
    with pytest.raises(RuntimeError, match=osf.LIVE_ENV):
        osf.run(tmp_path, dry_run=False, snapshot_only=False)
    assert not (tmp_path / osf.RESULT_NAME).exists()


def test_live_auth_failure_writes_no_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OSF_PAT", "dummy")
    monkeypatch.setenv(osf.LIVE_ENV, "1")
    (tmp_path / "paper.md").write_text("public", encoding="utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "dummy"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(httpx.HTTPStatusError):
        osf.run(tmp_path, dry_run=False, snapshot_only=False, client=client)
    assert not (tmp_path / osf.RESULT_NAME).exists()


def test_live_network_failure_writes_no_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OSF_PAT", "dummy")
    monkeypatch.setenv(osf.LIVE_ENV, "1")
    (tmp_path / "paper.md").write_text("public", encoding="utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("network down", request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(httpx.ConnectError):
        osf.run(tmp_path, dry_run=False, snapshot_only=False, client=client)
    assert not (tmp_path / osf.RESULT_NAME).exists()


def test_main_live_http_error_prints_safe_class_not_body(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("OSF_PAT", "dummy")
    monkeypatch.setenv(osf.LIVE_ENV, "1")
    (tmp_path / "paper.md").write_text("public", encoding="utf-8")

    def fail_publish(*args, **kwargs):
        request = httpx.Request("POST", "https://api.test/v2/nodes/")
        response = httpx.Response(401, json={"detail": "dummy"}, request=request)
        raise httpx.HTTPStatusError("dummy leaked body", request=request, response=response)

    monkeypatch.setattr(osf, "publish_live", fail_publish)

    assert osf.main(["--run-dir", str(tmp_path), "--live"]) == 2
    err = capsys.readouterr().err
    assert "HTTP 401" in err
    assert "dummy" not in err
