#!/usr/bin/env python3
"""Read-only MacBook/GitHub/VPS tri-sync status check."""
from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

SERVICE = "research-agent-bot.service"
LOCAL_HTTP = "http://127.0.0.1:8791/"


def count_dirty(porcelain: str) -> int:
    return sum(1 for line in porcelain.splitlines() if line.strip())


def parse_ahead_behind(text: str) -> tuple[int | None, int | None]:
    parts = text.replace("\t", " ").split()
    if len(parts) != 2:
        return (None, None)
    try:
        return (int(parts[0]), int(parts[1]))
    except ValueError:
        return (None, None)


def classify_sync(
    *,
    dirty_count: int,
    ahead: int | None,
    behind: int | None,
    head: str | None = None,
    origin: str | None = None,
) -> str:
    if dirty_count:
        return "dirty"
    if ahead is None or behind is None:
        return "unknown"
    if ahead and behind:
        return "diverged"
    if ahead:
        return "ahead"
    if behind:
        return "behind"
    if head and origin and head != origin:
        return "sha_mismatch"
    return "synced"


def parse_key_values(text: str) -> dict[str, str]:
    data: dict[str, str] = {}
    for line in text.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip()
    return data


def parse_int(text: str | None) -> int | None:
    if text is None:
        return None
    try:
        return int(text.strip())
    except ValueError:
        return None


def _run(args: list[str], *, cwd: Path) -> str:
    return subprocess.run(
        args,
        cwd=cwd,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout.strip()


def _run_or_none(args: list[str], *, cwd: Path) -> str | None:
    try:
        return _run(args, cwd=cwd)
    except (OSError, subprocess.CalledProcessError):
        return None


def _upstream_ref(repo: Path, override: str | None = None) -> str:
    if override:
        return override
    return _run_or_none(["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"], cwd=repo) or "origin/main"


def local_status(repo: Path, upstream_ref: str | None = None) -> dict[str, Any]:
    repo = repo.resolve()
    upstream_ref = _upstream_ref(repo, upstream_ref)
    head = _run_or_none(["git", "rev-parse", "--short=8", "HEAD"], cwd=repo)
    upstream = _run_or_none(["git", "rev-parse", "--short=8", upstream_ref], cwd=repo)
    porcelain = _run_or_none(["git", "status", "--porcelain"], cwd=repo) or ""
    counts = _run_or_none(
        ["git", "rev-list", "--left-right", "--count", f"HEAD...{upstream_ref}"],
        cwd=repo,
    )
    ahead, behind = parse_ahead_behind(counts or "")
    dirty = count_dirty(porcelain)
    return {
        "repo": str(repo),
        "head": head,
        "upstream_ref": upstream_ref,
        "upstream_head": upstream,
        "origin_main": upstream,
        "dirty_count": dirty,
        "ahead": ahead,
        "behind": behind,
        "state": classify_sync(
            dirty_count=dirty,
            ahead=ahead,
            behind=behind,
            head=head,
            origin=upstream,
        ),
    }


def _remote_probe_command(path: str) -> str:
    qpath = shlex.quote(path)
    return "; ".join(
        [
            f"cd {qpath} || exit 2",
            "printf 'path=%s\\n' \"$PWD\"",
            "printf 'head='; git rev-parse --short=8 HEAD || true",
            "printf 'dirty='; git status --porcelain | wc -l | tr -d ' '",
            f"printf 'service='; systemctl is-active {SERVICE} || true",
            f"printf 'http='; curl -s -o /dev/null -w '%{{http_code}}' {LOCAL_HTTP} || true; printf '\\n'",
        ]
    )


def probe_vps(
    *,
    host: str,
    path: str,
    ssh_key: str | None = None,
) -> dict[str, Any]:
    cmd = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
    ]
    if ssh_key:
        cmd.extend(["-i", ssh_key])
    cmd.extend([host, _remote_probe_command(path)])
    try:
        output = subprocess.run(
            cmd,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout
        data = parse_key_values(output)
        return {
            "path": data.get("path", path),
            "head": data.get("head"),
            "dirty_count": parse_int(data.get("dirty")),
            "service": data.get("service"),
            "http": data.get("http"),
            "error": None,
        }
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        return {
            "path": path,
            "head": None,
            "dirty_count": None,
            "service": None,
            "http": None,
            "error": exc.__class__.__name__,
        }


def build_status(args: argparse.Namespace) -> dict[str, Any]:
    status: dict[str, Any] = {"local": local_status(Path(args.repo), upstream_ref=args.upstream_ref), "vps": []}
    if args.vps_host:
        for path in (args.opt_path, args.root_path):
            if path:
                status["vps"].append(
                    probe_vps(host=args.vps_host, path=path, ssh_key=args.ssh_key)
                )
    return status


def render_text(status: dict[str, Any]) -> str:
    local = status["local"]
    lines = [
        "Tri-sync status",
        f"local_head: {local['head']}",
        f"upstream_ref: {local.get('upstream_ref', 'origin/main')}",
        f"upstream_head: {local.get('upstream_head') or local.get('origin_main')}",
        f"dirty_count: {local['dirty_count']}",
        f"ahead_behind: {local['ahead']}/{local['behind']}",
        f"local_state: {local['state']}",
    ]
    for item in status["vps"]:
        lines.extend(
            [
                f"vps_path: {item['path']}",
                f"  head: {item['head']}",
                f"  dirty_count: {item['dirty_count']}",
                f"  service: {item['service']}",
                f"  http: {item['http']}",
                f"  error: {item['error']}",
            ]
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".", help="Local repo path")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    parser.add_argument("--vps-host", help="Optional SSH host, e.g. root@49.12.7.18")
    parser.add_argument("--ssh-key", help="Optional SSH private key path")
    parser.add_argument("--upstream-ref", help="Optional git ref to compare against; defaults to @{upstream}")
    parser.add_argument("--opt-path", default="/opt/research-agent-bot")
    parser.add_argument("--root-path", default="/root/Research-Agent-Bot")
    args = parser.parse_args(argv)
    status = build_status(args)
    if args.json:
        print(json.dumps(status, indent=2, sort_keys=True))
    else:
        print(render_text(status))
    return 0


if __name__ == "__main__":
    sys.exit(main())
