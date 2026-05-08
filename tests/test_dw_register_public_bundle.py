from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import dw_register_public_bundle as dwreg  # noqa: E402
import researka_reader_manifest as reader  # noqa: E402


def _write_manifest(tmp_path: Path) -> Path:
    (tmp_path / "full_paper.md").write_text("paper", encoding="utf-8")
    manifest_path = reader.write_reader_manifest(
        tmp_path,
        public_url="https://osf.io/abc123/",
    )
    return manifest_path


def test_dry_run_payload_shape_has_idempotency_key(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path)

    payload = dwreg.build_payload(manifest_path)

    assert payload["schema"] == "derivation_web.register_public_bundle.v1"
    assert payload["run_id"] == tmp_path.name
    assert payload["idempotency_key"].startswith("dw-register:")
    assert payload["dw"]["append_only"] is True
    assert payload["dw"]["artifact"]["kind"] == "registry_record"
    assert payload["dw"]["step"]["step_type"] == "register"
    assert payload["aggregate_files"][0]["path"] == "full_paper.md"
    assert payload["public_url"] == "https://osf.io/abc123/"
    assert payload["osf"] == {"node_id": None, "url": None, "doi": None}


def test_cli_dry_run_prints_payload_without_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest_path = _write_manifest(tmp_path)
    token = "TEST_TOKEN_VALUE"
    monkeypatch.setenv("DW_API_TOKEN", token)

    assert dwreg.main([str(manifest_path)]) == 0

    out = capsys.readouterr().out
    assert json.loads(out)["run_id"] == tmp_path.name
    assert token not in out


def test_live_mock_post_uses_token_but_never_returns_it(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path)
    payload = dwreg.build_payload(manifest_path)
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers["authorization"]
        captured["idempotency"] = request.headers["idempotency-key"]
        captured["body"] = json.loads(request.content)
        return httpx.Response(201, json={"id": "dw_reg_123"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    token = "TEST_TOKEN_VALUE"
    result = dwreg.post_payload(
        payload,
        api_url="https://dw.test/api/register-public-bundle",
        token=token,
        client=client,
    )

    assert captured["auth"] == f"Bearer {token}"
    assert captured["idempotency"] == payload["idempotency_key"]
    assert captured["body"]["idempotency_key"] == payload["idempotency_key"]
    assert result["registered"] is True
    assert result["response_id"] == "dw_reg_123"
    assert token not in json.dumps(result)


def test_live_mock_post_endpoint_failure_does_not_return_token(
    tmp_path: Path,
) -> None:
    manifest_path = _write_manifest(tmp_path)
    payload = dwreg.build_payload(manifest_path)
    token = "TEST_TOKEN_VALUE"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == f"Bearer {token}"
        return httpx.Response(500, json={"error": token})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(httpx.HTTPStatusError) as exc:
        dwreg.post_payload(
            payload,
            api_url="https://dw.test/api/register-public-bundle",
            token=token,
            client=client,
        )
    assert token not in str(exc.value)


def test_malformed_manifest_fails_closed(tmp_path: Path) -> None:
    manifest = tmp_path / reader.MANIFEST_NAME
    manifest.write_text("{not json", encoding="utf-8")

    with pytest.raises(ValueError, match="malformed"):
        dwreg.build_payload(manifest)


def test_missing_manifest_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="malformed or missing"):
        dwreg.build_payload(tmp_path)


def test_wrong_schema_fails_closed(tmp_path: Path) -> None:
    manifest = tmp_path / reader.MANIFEST_NAME
    manifest.write_text(json.dumps({"schema": "wrong", "files": []}), encoding="utf-8")

    with pytest.raises(ValueError, match="schema"):
        dwreg.build_payload(manifest)


def test_live_cli_requires_env_without_printing_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest_path = _write_manifest(tmp_path)
    monkeypatch.delenv("DW_API_URL", raising=False)
    token = "TEST_TOKEN_VALUE"
    monkeypatch.setenv("DW_API_TOKEN", token)

    assert dwreg.main([str(manifest_path), "--live"]) == 2

    err = capsys.readouterr().err
    assert "RuntimeError" in err
    assert token not in err


def test_live_cli_endpoint_failure_prints_no_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest_path = _write_manifest(tmp_path)
    token = "TEST_TOKEN_VALUE"
    monkeypatch.setenv("DW_API_URL", "https://dw.test/api/register-public-bundle")
    monkeypatch.setenv("DW_API_TOKEN", token)

    def fail_post(*_args, **_kwargs):
        request = httpx.Request("POST", "https://dw.test/api/register-public-bundle")
        response = httpx.Response(500, json={"error": token}, request=request)
        raise httpx.HTTPStatusError("server failed", request=request, response=response)

    monkeypatch.setattr(dwreg, "post_payload", fail_post)

    assert dwreg.main([str(manifest_path), "--live"]) == 2

    err = capsys.readouterr().err
    assert "HTTPStatusError" in err
    assert token not in err
