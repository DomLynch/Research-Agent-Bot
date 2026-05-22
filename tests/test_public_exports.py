from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import researka_reader_manifest as reader  # type: ignore[import-not-found]  # noqa: E402


def test_reader_manifest_shape_excludes_secrets_and_generated(
    tmp_path: Path,
) -> None:
    (tmp_path / "paper.md").write_text("paper", encoding="utf-8")
    (tmp_path / "manifest.json").write_text(
        json.dumps({"topic": "demo-topic"}),
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text("secret=value", encoding="utf-8")
    (tmp_path / "osf_publish_result.json").write_text("{}", encoding="utf-8")

    manifest = reader.build_reader_manifest(
        tmp_path,
        public_url="https://researka.io/topic/demo-topic/2026-05-08",
        osf={"url": "https://osf.io/abc123/", "doi": "10.17605/OSF.IO/ABC123"},
    )

    assert manifest["schema"] == "researka.reader_manifest.v1"
    assert manifest["run_id"] == tmp_path.name
    assert manifest["topic"] == "demo-topic"
    assert manifest["json_ld"]["@type"] == "ScholarlyArticle"
    assert manifest["json_ld"]["identifier"] == "10.17605/OSF.IO/ABC123"
    assert manifest["entrypoints"]["paper"] == "paper.md"
    assert manifest["entrypoints"]["manifest"] == "manifest.json"
    paths = [item["path"] for item in manifest["files"]]
    assert paths == ["manifest.json", "paper.md"]
    assert "secret" not in json.dumps(manifest)


def test_reader_manifest_write_is_not_self_included(tmp_path: Path) -> None:
    (tmp_path / "paper.md").write_text("paper", encoding="utf-8")

    out = reader.write_reader_manifest(tmp_path, public_url="https://example.test/p")
    manifest = json.loads(out.read_text(encoding="utf-8"))

    assert out == tmp_path / reader.MANIFEST_NAME
    assert manifest["public_url"] == "https://example.test/p"
    assert [item["path"] for item in manifest["files"]] == ["paper.md"]


def test_dw_register_payload_is_offline_shape_only(tmp_path: Path) -> None:
    (tmp_path / "paper.md").write_text("paper", encoding="utf-8")
    manifest = reader.build_reader_manifest(tmp_path)

    payload = reader.build_dw_register_payload(
        manifest,
        public_url="https://osf.io/abc123/",
        osf={"osf_node_id": "abc123", "osf_url": "https://osf.io/abc123/"},
    )

    assert payload["schema"] == "derivation_web.register_public_bundle.v1"
    assert payload["idempotency_key"].startswith("dw-register:")
    assert payload["reader_manifest_schema"] == "researka.reader_manifest.v1"
    assert payload["topic"] == "unknown"
    assert payload["osf"]["node_id"] == "abc123"
    assert payload["aggregate_files"][0]["path"] == "paper.md"
    assert payload["dw"]["append_only"] is True
    assert payload["dw"]["step"]["step_type"] == "register"
    assert "secret" not in json.dumps(payload).lower()


def test_reader_manifest_cli_accepts_public_url_and_osf_result(tmp_path: Path) -> None:
    (tmp_path / "paper.md").write_text("paper", encoding="utf-8")
    osf_result = tmp_path / "osf_publish_result.json"
    osf_result.write_text(
        json.dumps({"url": "https://osf.io/abc123/", "doi": "10.17605/OSF.IO/ABC123"}),
        encoding="utf-8",
    )

    assert reader.main(
        [
            str(tmp_path),
            "--public-url",
            "https://researka.io/paper",
            "--osf-result",
            str(osf_result),
        ]
    ) == 0

    data = json.loads((tmp_path / reader.MANIFEST_NAME).read_text(encoding="utf-8"))
    assert data["public_url"] == "https://researka.io/paper"
    assert data["json_ld"]["isBasedOn"] == "https://osf.io/abc123/"
