from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import bundle_snapshot as snap  # noqa: E402


def test_build_snapshot_is_deterministic_and_ignores_mtime(
    tmp_path: Path,
) -> None:
    (tmp_path / "b.txt").write_text("beta", encoding="utf-8")
    (tmp_path / "a.txt").write_text("alpha", encoding="utf-8")
    first = snap.build_snapshot(tmp_path)
    os.utime(tmp_path / "a.txt", (1, 1))
    second = snap.build_snapshot(tmp_path)
    assert first == second
    assert [f["path"] for f in first["files"]] == ["a.txt", "b.txt"]


def test_build_snapshot_records_sha256_and_size(tmp_path: Path) -> None:
    payload = b"abc"
    (tmp_path / "paper.md").write_bytes(payload)
    result = snap.build_snapshot(tmp_path)
    assert result["file_count"] == 1
    assert result["total_size"] == 3
    assert result["files"][0] == {
        "path": "paper.md",
        "size": 3,
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def test_build_snapshot_excludes_secrets_and_generated_outputs(
    tmp_path: Path,
) -> None:
    (tmp_path / "paper.md").write_text("public", encoding="utf-8")
    (tmp_path / ".env").write_text("OSF_PAT=secret", encoding="utf-8")
    (tmp_path / "api_token.txt").write_text("secret", encoding="utf-8")
    (tmp_path / "private.pem").write_text("secret", encoding="utf-8")
    (tmp_path / snap.SNAPSHOT_NAME).write_text("old", encoding="utf-8")
    result = snap.build_snapshot(tmp_path)
    assert [f["path"] for f in result["files"]] == ["paper.md"]


def test_helpers_classify_and_hash_files(tmp_path: Path) -> None:
    (tmp_path / "nested").mkdir()
    payload = b"public"
    public = tmp_path / "nested" / "paper.md"
    public.write_bytes(payload)
    assert snap.is_secret_path(Path("private/token.txt"))
    assert not snap.is_secret_path(Path("nested/paper.md"))
    assert snap.iter_snapshot_files(tmp_path) == [Path("nested/paper.md")]
    assert snap.sha256_file(public) == hashlib.sha256(payload).hexdigest()


def test_write_snapshot_round_trips_json(tmp_path: Path) -> None:
    (tmp_path / "paper.md").write_text("public", encoding="utf-8")
    path = snap.write_snapshot(tmp_path)
    assert path == tmp_path / snap.SNAPSHOT_NAME
    assert json.loads(path.read_text(encoding="utf-8")) == snap.build_snapshot(
        tmp_path,
    )


def test_main_writes_snapshot(tmp_path: Path) -> None:
    (tmp_path / "paper.md").write_text("public", encoding="utf-8")
    assert snap.main([str(tmp_path)]) == 0
    assert (tmp_path / snap.SNAPSHOT_NAME).exists()
