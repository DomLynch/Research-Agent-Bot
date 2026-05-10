"""Sequential AAA sweep for N topics × 2 passes (L6 reproducibility).

Drives `run_v06_synthesis.py` then `paper_quality_runtime.py` for each
topic, capturing verdict + key gate signals. Writes a single rolling
summary `logs/aaa_sweep_<TS>.json` so an external watcher can tail it.

Stdlib + httpx (a project dep). No new API; just shells the existing
release pipeline.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import shlex
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

DEFAULT_TOPICS = (
    "metformin", "rapamycin", "glp1", "statins", "acarbose",
    "aspirin", "caloric_restriction", "resistance_training",
    "omega3", "berberine",
)


def _run(cmd: list[str], cwd: Path, log_path: Path) -> int:
    """Run a subprocess, tee stderr+stdout to log. Returns exit code."""
    with log_path.open("a") as f:
        f.write(f"\n\n=== {dt.datetime.now(dt.timezone.utc).isoformat()} :: "
                f"{' '.join(shlex.quote(c) for c in cmd)} ===\n")
        f.flush()
        proc = subprocess.run(  # noqa: S603 - trusted local cmd
            cmd, cwd=str(cwd), stdout=f, stderr=subprocess.STDOUT,
        )
    return proc.returncode


def _read_verdict(out_dir: Path) -> dict:
    """Pull the headline gates from a finished run dir."""
    def _read(name: str) -> dict:
        p = out_dir / name
        if not p.exists():
            return {}
        try:
            return json.loads(p.read_text())
        except (OSError, json.JSONDecodeError):
            return {}

    fv = _read("full_paper.final_verdict.json")
    js = _read("full_paper.journal_surface.json")
    tg = _read("template_language_gate.json")
    ps = _read("pre_submit_gate.json")
    pub = _read("publication_score.json")

    return {
        "verdict": fv.get("verdict"),
        "stage1_pass_rate": fv.get("stage1_pass_rate"),
        "stage1_score": fv.get("stage1_score"),
        "stage2_p1": fv.get("stage2_p1"),
        "stage2_p2": fv.get("stage2_p2"),
        "all_green": fv.get("all_green"),
        "journal_ready": fv.get("journal_ready"),
        "maturity_label": fv.get("maturity_label"),
        "certification_track": fv.get("certification_track"),
        "journal_surface_passed": js.get("passed"),
        "template_blocking": (
            tg.get("summary", {}).get("blocking") if isinstance(tg.get("summary"), dict) else None
        ),
        "template_total_hits": (
            tg.get("summary", {}).get("total_hits") if isinstance(tg.get("summary"), dict) else None
        ),
        "paper_quality_gate": (
            ps.get("result", {}).get("paper_quality_gate") if isinstance(ps.get("result"), dict) else None
        ),
        "formal_sr_methods": (
            ps.get("result", {}).get("formal_sr_methods") if isinstance(ps.get("result"), dict) else None
        ),
        "publication_verdict": (
            pub.get("result", {}).get("verdict") if isinstance(pub.get("result"), dict) else None
        ),
        "rubric_total": (
            pub.get("result", {}).get("rubric_total") if isinstance(pub.get("result"), dict) else None
        ),
    }


def _classify_l6(pass_a: dict, pass_b: dict) -> str:
    """L6 requires two consecutive AAA-verdict runs, both clean."""
    if pass_a.get("verdict") == "AAA" and pass_b.get("verdict") == "AAA":
        if pass_a.get("all_green") and pass_b.get("all_green"):
            return "L6 — REPRODUCIBLY JOURNAL-READY"
        return "L5 (twice) — pending all-green parity"
    if pass_a.get("verdict") == "AAA" or pass_b.get("verdict") == "AAA":
        return "L5 (once)"
    return "below-L5"


def _write_summary(summary_path: Path, payload: dict) -> None:
    summary_path.write_text(json.dumps(payload, indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Sequential 10-topic × 2-pass AAA sweep.",
    )
    parser.add_argument(
        "--topics", nargs="*", default=list(DEFAULT_TOPICS),
        help="Topics to run (default: 10 canonical).",
    )
    parser.add_argument(
        "--passes", type=int, default=2, help="Runs per topic (default 2 for L6).",
    )
    parser.add_argument(
        "--label", default="AAA10x2",
        help="Run-label prefix added to each out_dir.",
    )
    args = parser.parse_args(argv)

    started = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    summary_path = REPO / "logs" / f"aaa_sweep_{started}.json"
    log_path = REPO / "logs" / f"aaa_sweep_{started}.log"
    summary_path.parent.mkdir(parents=True, exist_ok=True)

    summary: dict = {
        "started_at": started,
        "topics": args.topics,
        "passes": args.passes,
        "label": args.label,
        "log_path": str(log_path.relative_to(REPO)),
        "results": {},
    }
    _write_summary(summary_path, summary)
    print(f"[sweep] log={log_path}\n[sweep] summary={summary_path}", flush=True)

    for topic in args.topics:
        summary["results"][topic] = {"passes": []}
        for n in range(1, args.passes + 1):
            ts = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
            out_dir = (
                REPO / "runs"
                / f"synthesis-{topic}-v06-{args.label}-pass{n}-{ts}"
            )
            print(f"[sweep] {topic} pass{n} → {out_dir.name}", flush=True)
            rc = _run(
                ["python3", "scripts/run_v06_synthesis.py",
                 "--topic", topic, "--out-dir", str(out_dir)],
                cwd=REPO, log_path=log_path,
            )
            entry: dict = {
                "pass": n, "out_dir": str(out_dir.relative_to(REPO)),
                "synth_exit": rc,
            }
            if rc == 0 and (out_dir / "full_paper.md").exists():
                rc_q = _run(
                    ["python3", "scripts/paper_quality_runtime.py",
                     str(out_dir)],
                    cwd=REPO, log_path=log_path,
                )
                entry["adapter_exit"] = rc_q
                entry["gates"] = _read_verdict(out_dir)
            else:
                entry["adapter_exit"] = -1
                entry["gates"] = {}
            summary["results"][topic]["passes"].append(entry)
            _write_summary(summary_path, summary)
            print(
                f"[sweep] {topic} pass{n} synth_rc={rc} "
                f"verdict={entry['gates'].get('verdict')} "
                f"paper_quality_gate={entry['gates'].get('paper_quality_gate')}",
                flush=True,
            )
        # L6 classification once both passes done.
        passes_done = summary["results"][topic]["passes"]
        if len(passes_done) >= 2:
            summary["results"][topic]["l6_classification"] = _classify_l6(
                passes_done[0]["gates"], passes_done[1]["gates"],
            )
            _write_summary(summary_path, summary)

    summary["finished_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    _write_summary(summary_path, summary)
    print(f"[sweep] DONE: {summary_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
