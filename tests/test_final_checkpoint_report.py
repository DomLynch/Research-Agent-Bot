from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import final_checkpoint_report as checkpoint  # noqa: E402


def test_checkpoint_combines_local_github_vps_and_l6(
    tmp_path: Path, monkeypatch
) -> None:
    l6 = tmp_path / "l6.json"
    l6.write_text(
        json.dumps(
            {
                "topics": [
                    {"topic": "alpha", "status": "confirmed_l6"},
                    {"topic": "beta", "status": "blocked"},
                    {"topic": "gamma", "status": "needs_rerun"},
                ]
            }
        ),
        encoding="utf-8",
    )

    def fake_run(cmd: list[str], cwd: Path, timeout_s: int) -> dict:
        text = " ".join(cmd)
        if "rev-parse --short HEAD" in text:
            return {"returncode": 0, "stdout": "abc123\n", "stderr": ""}
        if "branch --show-current" in text:
            return {"returncode": 0, "stdout": "main\n", "stderr": ""}
        if "status --short" in text:
            return {"returncode": 0, "stdout": " M x.py\n?? y.py\n", "stderr": ""}
        if "remote get-url origin" in text:
            return {"returncode": 0, "stdout": "git@example/repo\n", "stderr": ""}
        if "rev-parse HEAD" in text:
            return {"returncode": 0, "stdout": "abcdef\n", "stderr": ""}
        if "ls-remote" in text:
            return {
                "returncode": 0,
                "stdout": "abcdef\trefs/heads/main\n",
                "stderr": "",
            }
        return {"returncode": 0, "stdout": "vps ok\n", "stderr": ""}

    monkeypatch.setattr(checkpoint, "_run", fake_run)
    report = checkpoint.build_checkpoint(
        repo=tmp_path,
        l6_report=l6,
        vps_cmd=["ssh", "host", "true"],
    )
    assert report["local"]["dirty_count"] == 2
    assert report["github"]["matches_local_head"] is True
    assert report["vps"]["status"] == "ok"
    assert report["l6"]["confirmed_l6"] == ["alpha"]


def test_checkpoint_markdown_is_observational(tmp_path: Path) -> None:
    report = {
        "generated_at": "now",
        "local": {"branch": "main", "head": "abc", "dirty_count": 0},
        "github": {
            "remote": "origin",
            "remote_head": "abc",
            "matches_local_head": True,
            "status": "ok",
        },
        "vps": {"status": "not_configured"},
        "l6": {"confirmed_l6": ["alpha"], "blocked": [], "needs_rerun": []},
    }
    out = tmp_path / "reports" / "l6_final_checkpoint.md"
    checkpoint.write_checkpoint(report, out)
    text = out.read_text(encoding="utf-8")
    assert "Final Checkpoint Report" in text
    assert "does not deploy, push, promote" in text
