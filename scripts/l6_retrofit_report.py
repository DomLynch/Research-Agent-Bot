"""Read-only L6 retrofit scanner over existing run artifacts."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

CertRunner = Callable[[tuple[Path, Path], Path, int], dict[str, Any]]


def build_report(
    run_dirs: Sequence[Path],
    *,
    run_cert: bool = False,
    output_dir: Path | None = None,
    timeout_s: int = 60,
    cert_runner: CertRunner | None = None,
) -> dict[str, Any]:
    groups: dict[str, list[Path]] = {}
    for run_dir in run_dirs:
        if run_dir.is_dir():
            groups.setdefault(_topic_for_run(run_dir), []).append(run_dir)
    topics = [
        _topic_status(
            topic,
            dirs,
            run_cert=run_cert,
            output_dir=output_dir,
            timeout_s=timeout_s,
            cert_runner=cert_runner or _run_consecutive_cert,
        )
        for topic, dirs in sorted(groups.items())
    ]
    return {
        "schema": "l6_retrofit_report.v1",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "claim_boundary": (
            "confirmed_l6 requires certification_report --consecutive with "
            "l6_reproducibly_journal_ready=true; adjacent L5 pairs without "
            "that gate are candidate_only"
        ),
        "counts": _counts(topics),
        "topics": topics,
    }


def render_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# L6 Retrofit Report",
        "",
        f"Generated: `{report['generated_at']}`",
        "",
        "L6 is confirmed only when the real consecutive certification gate "
        "returns `l6_reproducibly_journal_ready=true`.",
        "",
        "| Topic | Status | Runs | L5+ | Candidate pairs | Confirmed pair | Reason |",
        "|---|---|---:|---:|---:|---|---|",
    ]
    for topic in report["topics"]:
        lines.append(
            f"| {topic['topic']} | {topic['status']} | {topic['n_runs']} | "
            f"{topic['n_l5_or_higher']} | {len(topic['candidate_pairs'])} | "
            f"{', '.join(topic.get('confirmed_pair') or [])} | "
            f"{topic.get('reason', '')} |"
        )
    lines += ["", "## Blocked Candidate Details", ""]
    blocked = [t for t in report["topics"] if t["status"] == "blocked"]
    if not blocked:
        lines.append("- None.")
    for topic in blocked:
        for cert in topic.get("certifications", []):
            blockers = cert.get("eligibility_blockers") or cert.get("blockers") or []
            lines.append(
                f"- `{topic['topic']}` pair `{cert['pair']}`: "
                f"{'; '.join(blockers) or 'not L6-ready under clean L5 gate'}"
            )
    lines += ["", "## Next Reruns", ""]
    for topic in report["topics"]:
        if topic["status"] == "needs_rerun":
            lines.append(
                f"- `{topic['topic']}`: "
                f"`python3 scripts/run_v06_synthesis.py --topic {topic['topic']}`"
            )
    return "\n".join(lines).rstrip() + "\n"


def write_report(report: Mapping[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "report.md").write_text(render_markdown(report), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-dir", type=Path, default=Path("runs"))
    parser.add_argument("--out-dir", type=Path, default=Path("reports/l6_retrofit"))
    parser.add_argument("--run-cert", action="store_true")
    parser.add_argument("--timeout-s", type=int, default=60)
    args = parser.parse_args(argv)
    run_dirs = sorted(p for p in args.runs_dir.iterdir() if p.is_dir())
    report = build_report(
        run_dirs,
        run_cert=args.run_cert,
        output_dir=args.out_dir,
        timeout_s=args.timeout_s,
    )
    write_report(report, args.out_dir)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def _topic_status(
    topic: str,
    run_dirs: Sequence[Path],
    *,
    run_cert: bool,
    output_dir: Path | None,
    timeout_s: int,
    cert_runner: CertRunner,
) -> dict[str, Any]:
    rows = [_row(p) for p in sorted(run_dirs, key=_run_sort_key)]
    pairs = _candidate_pairs(rows)
    certs = []
    if run_cert:
        certs = [
            _certify_pair(topic, pair, output_dir, timeout_s, cert_runner)
            for pair in pairs
        ]
    confirmed = next((c for c in certs if c.get("l6_confirmed")), None)
    n_l5 = sum(1 for r in rows if r["maturity_level"] >= 5)
    status, reason = _status(rows, pairs, certs, confirmed)
    return {
        "topic": topic,
        "status": status,
        "reason": reason,
        "n_runs": len(rows),
        "n_l5_or_higher": n_l5,
        "latest_run": rows[-1]["run_dir"] if rows else "",
        "latest_maturity_level": rows[-1]["maturity_level"] if rows else 0,
        "candidate_pairs": [list(pair) for pair in pairs],
        "confirmed_pair": confirmed.get("pair", []) if confirmed else [],
        "certifications": certs,
        "runs": rows,
    }


def _status(
    rows: Sequence[Mapping[str, Any]],
    pairs: Sequence[tuple[str, str]],
    certs: Sequence[Mapping[str, Any]],
    confirmed: Mapping[str, Any] | None,
) -> tuple[str, str]:
    if confirmed:
        return "confirmed_l6", "real consecutive certification gate passed"
    if certs and pairs:
        return "blocked", "candidate pair did not pass clean L6 gate"
    if pairs:
        return "candidate_only", "adjacent L5 pair found; real gate not run"
    if rows and rows[-1]["maturity_level"] >= 5:
        return (
            "needs_rerun",
            "latest run is L5; one adjacent L5 rerun could form a pair",
        )
    return "no_data", "no adjacent L5 pair and latest run is not L5"


def _candidate_pairs(rows: Sequence[Mapping[str, Any]]) -> list[tuple[str, str]]:
    pairs = []
    for prev, cur in zip(rows, rows[1:]):
        if prev["maturity_level"] >= 5 and cur["maturity_level"] >= 5:
            pairs.append((str(prev["run_dir"]), str(cur["run_dir"])))
    return pairs


def _certify_pair(
    topic: str,
    pair: tuple[str, str],
    output_dir: Path | None,
    timeout_s: int,
    cert_runner: CertRunner,
) -> dict[str, Any]:
    paths = (
        Path("runs") / pair[0] / "full_paper.md",
        Path("runs") / pair[1] / "full_paper.md",
    )
    if not all(p.exists() for p in paths):
        return {
            "pair": list(pair),
            "l6_confirmed": False,
            "reason": "missing full_paper.md",
        }
    result = cert_runner(paths, output_dir or Path("reports/l6_retrofit"), timeout_s)
    parsed = result.get("parsed", {})
    eligibility_blockers = _eligibility_blockers(parsed, pair)
    return {
        "pair": list(pair),
        "returncode": result.get("returncode"),
        "stdout_path": result.get("stdout_path", ""),
        "stderr_path": result.get("stderr_path", ""),
        "l6_confirmed": bool(parsed.get("l6_reproducibly_journal_ready")),
        "certified": bool(parsed.get("certified")),
        "maturity_level": parsed.get("maturity_level", 0),
        "blockers": parsed.get("l6_blockers", []),
        "eligibility_blockers": eligibility_blockers,
        "reason": parsed.get("reason", ""),
        "topic": topic,
    }


def _run_consecutive_cert(
    paths: tuple[Path, Path],
    output_dir: Path,
    timeout_s: int,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = "__".join(p.parent.name for p in paths)
    stdout_path = output_dir / f"{stem}.cert.stdout.json"
    stderr_path = output_dir / f"{stem}.cert.stderr.txt"
    env = os.environ.copy()
    env["PYTHONPATH"] = "." + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
    )
    cmd = [
        "python3",
        "scripts/certification_report.py",
        "--consecutive",
        *map(str, paths),
    ]
    try:
        proc = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            env=env,
            text=True,
            timeout=timeout_s,
        )
        stdout_path.write_text(proc.stdout, encoding="utf-8")
        stderr_path.write_text(proc.stderr, encoding="utf-8")
        parsed = _loads(proc.stdout)
        return {
            "returncode": proc.returncode,
            "parsed": parsed,
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
        }
    except subprocess.TimeoutExpired as exc:
        stderr_path.write_text(str(exc), encoding="utf-8")
        return {
            "returncode": 124,
            "parsed": {},
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
        }


def _row(run_dir: Path) -> dict[str, Any]:
    final = _read_json(run_dir / "full_paper.final_verdict.json")
    return {
        "run_dir": run_dir.name,
        "generated_at": _generated_at(run_dir),
        "verdict": str(final.get("verdict") or final.get("final_verdict") or "missing"),
        "maturity_level": _maturity_level(final),
        "journal_surface_pass": bool(
            final.get("journal_surface_pass", final.get("journal_ready", False))
        ),
        "grok_unresolved_p1": int(final.get("grok_unresolved_p1", 0) or 0),
        "stage2_p1": int(final.get("stage2_p1", 0) or 0),
        "stage2_p2": int(final.get("stage2_p2", 0) or 0),
        "has_final_verdict": bool(final),
        "has_full_paper_md": (run_dir / "full_paper.md").exists(),
    }


def _eligibility_blockers(
    parsed: Mapping[str, Any],
    pair: tuple[str, str],
) -> list[str]:
    blockers = []
    selected = set(parsed.get("selected_pair") or pair)
    for run in parsed.get("runs", []):
        if run.get("run_id") not in selected:
            continue
        reasons = []
        if not _aaa_certified(run):
            reasons.append("single-run AAA cert failed")
        if run.get("flagged_patches", 0):
            reasons.append(f"flagged_patches={run['flagged_patches']}")
        if run.get("auto_stripped_patches", 0):
            reasons.append(f"auto_stripped_patches={run['auto_stripped_patches']}")
        if not run.get("journal_surface_pass", False):
            reasons.append("journal_surface_pass=false")
        if reasons:
            blockers.append(f"{run.get('run_id')}: {', '.join(reasons)}")
    return blockers


def _aaa_certified(run: Mapping[str, Any]) -> bool:
    return bool(
        run.get("aaa_pass")
        and run.get("q2_full")
        and run.get("stage2_clean")
        and run.get("grok_clean")
        and run.get("no_regression_pass")
        and run.get("old_defect_scan_clean")
    )


def _topic_for_run(run_dir: Path) -> str:
    for name in ("manifest.json", "full_paper.final_verdict.json"):
        data = _read_json(run_dir / name)
        if data.get("topic"):
            return str(data["topic"])
    match = re.match(r"(?:synthesis-)?([A-Za-z0-9_]+)", run_dir.name)
    return match.group(1) if match else run_dir.name


def _generated_at(run_dir: Path) -> str:
    for name in ("manifest.json", "full_paper.final_verdict.json"):
        data = _read_json(run_dir / name)
        for key in ("generated_at", "finished_at", "timestamp_iso", "timestamp"):
            if data.get(key):
                return str(data[key])
    return run_dir.name


def _run_sort_key(run_dir: Path) -> tuple[str, str]:
    return (_generated_at(run_dir), run_dir.name)


def _maturity_level(final: Mapping[str, Any]) -> int:
    value = final.get("maturity_level", final.get("level", 0))
    return int(value) if isinstance(value, int | float) else 0


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _loads(text: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _counts(topics: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    return {
        "topics": len(topics),
        "confirmed_l6": sum(t["status"] == "confirmed_l6" for t in topics),
        "candidate_only": sum(t["status"] == "candidate_only" for t in topics),
        "blocked": sum(t["status"] == "blocked" for t in topics),
        "needs_rerun": sum(t["status"] == "needs_rerun" for t in topics),
        "no_data": sum(t["status"] == "no_data" for t in topics),
    }


if __name__ == "__main__":
    raise SystemExit(main())
