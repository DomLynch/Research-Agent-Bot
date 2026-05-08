"""Read-only local/GitHub/VPS checkpoint report."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence


def build_checkpoint(
    *,
    repo: Path,
    l6_report: Path,
    vps_cmd: Sequence[str] | None = None,
    timeout_s: int = 8,
) -> dict[str, Any]:
    return {
        "schema": "final_checkpoint_report.v1",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "local": _local_status(repo, timeout_s),
        "github": _github_status(repo, timeout_s),
        "vps": _vps_status(vps_cmd, timeout_s),
        "l6": _l6_status(l6_report),
    }


def render_markdown(report: dict[str, Any]) -> str:
    local = report["local"]
    github = report["github"]
    vps = report["vps"]
    l6 = report["l6"]
    lines = [
        "# Final Checkpoint Report",
        "",
        f"Generated: `{report['generated_at']}`",
        "",
        "## Local",
        "",
        f"- Branch: `{local.get('branch', 'unknown')}`",
        f"- HEAD: `{local.get('head', 'unknown')}`",
        f"- Dirty entries: `{local.get('dirty_count', 0)}`",
        "",
        "## GitHub",
        "",
        f"- Remote: `{github.get('remote', 'unknown')}`",
        f"- Remote HEAD: `{github.get('remote_head', 'unknown')}`",
        f"- Matches local HEAD: `{github.get('matches_local_head', False)}`",
        f"- Status: `{github.get('status', 'unknown')}`",
        "",
        "## VPS",
        "",
        f"- Status: `{vps.get('status', 'not_checked')}`",
    ]
    if vps.get("stdout"):
        lines.append(f"- Output: `{vps['stdout'][:300]}`")
    if vps.get("stderr"):
        lines.append(f"- Error: `{vps['stderr'][:300]}`")
    lines += [
        "",
        "## L6",
        "",
        f"- Confirmed topics: `{', '.join(l6.get('confirmed_l6', []))}`",
        f"- Blocked topics: `{', '.join(l6.get('blocked', []))}`",
        f"- Needs rerun: `{', '.join(l6.get('needs_rerun', []))}`",
        "",
        "## Claim Boundary",
        "",
        "This checkpoint is observational. It does not deploy, push, promote "
        "certificates, or mutate run directories.",
    ]
    return "\n".join(lines).rstrip() + "\n"


def write_checkpoint(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_markdown(report), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument(
        "--l6-report", type=Path, default=Path("reports/l6_retrofit/report.json")
    )
    parser.add_argument(
        "--out", type=Path, default=Path("reports/l6_final_checkpoint.md")
    )
    parser.add_argument("--timeout-s", type=int, default=8)
    parser.add_argument("--vps-cmd", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    report = build_checkpoint(
        repo=args.repo,
        l6_report=args.l6_report,
        vps_cmd=args.vps_cmd or _default_vps_cmd(),
        timeout_s=args.timeout_s,
    )
    write_checkpoint(report, args.out)
    print(render_markdown(report), end="")
    return 0


def _local_status(repo: Path, timeout_s: int) -> dict[str, Any]:
    head = _run(["git", "rev-parse", "--short", "HEAD"], repo, timeout_s)
    branch = _run(["git", "branch", "--show-current"], repo, timeout_s)
    status = _run(["git", "status", "--short"], repo, timeout_s)
    dirty = [line for line in status["stdout"].splitlines() if line]
    return {
        "head": head["stdout"].strip() or "unknown",
        "branch": branch["stdout"].strip() or "unknown",
        "dirty_count": len(dirty),
        "dirty_sample": dirty[:20],
    }


def _github_status(repo: Path, timeout_s: int) -> dict[str, Any]:
    remote = _run(["git", "remote", "get-url", "origin"], repo, timeout_s)
    branch = _run(["git", "branch", "--show-current"], repo, timeout_s)
    local = _run(["git", "rev-parse", "HEAD"], repo, timeout_s)
    remote_head = _run(
        ["git", "ls-remote", "origin", f"refs/heads/{branch['stdout'].strip()}"],
        repo,
        timeout_s,
    )
    sha = remote_head["stdout"].split()[0] if remote_head["stdout"].strip() else ""
    return {
        "remote": remote["stdout"].strip(),
        "remote_head": sha[:8] if sha else "unknown",
        "matches_local_head": bool(sha and local["stdout"].strip() == sha),
        "status": "ok" if remote_head["returncode"] == 0 else "unavailable",
        "stderr": remote_head["stderr"],
    }


def _vps_status(vps_cmd: Sequence[str] | None, timeout_s: int) -> dict[str, Any]:
    if not vps_cmd:
        return {"status": "not_configured"}
    result = _run(list(vps_cmd), Path("."), timeout_s)
    return {
        "status": "ok" if result["returncode"] == 0 else "unavailable",
        "returncode": result["returncode"],
        "stdout": result["stdout"].strip(),
        "stderr": result["stderr"].strip(),
    }


def _l6_status(path: Path) -> dict[str, list[str]]:
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"confirmed_l6": [], "blocked": [], "needs_rerun": []}
    return {
        status: sorted(
            {t["topic"] for t in report.get("topics", []) if t.get("status") == status}
        )
        for status in ("confirmed_l6", "blocked", "needs_rerun")
    }


def _default_vps_cmd() -> list[str] | None:
    value = os.environ.get("FINAL_CHECKPOINT_VPS_CMD")
    return value.split() if value else None


def _run(cmd: list[str], cwd: Path, timeout_s: int) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            text=True,
            capture_output=True,
            timeout=timeout_s,
            check=False,
        )
        return {
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }
    except (subprocess.SubprocessError, FileNotFoundError) as exc:
        return {"returncode": 127, "stdout": "", "stderr": str(exc)}


if __name__ == "__main__":
    raise SystemExit(main())
