"""Build a deterministic cross-topic meta-synthesis bundle."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from agent.contradiction_detector import detect_cross_topic_contradictions
from agent.convergence_detector import detect_mechanism_convergences
from agent.cross_topic_aggregator import build_field_manifest, load_topic_run_summary
from agent.meta_writer import render_cross_topic_meta_synthesis

REPO_ROOT = Path(__file__).resolve().parents[1]
VALID_CERTIFICATION_TRACKS = frozenset({
    "AAA-CLIN",
    "AAA-INF",
    "AAA-MECH",
    "AAA-SCOP",
})


def select_best_runs(runs_root: Path) -> tuple[Path, ...]:
    best: dict[str, tuple[tuple[int, int, int, str, str], Path]] = {}
    for path in sorted(runs_root.glob("synthesis-*-v06-*")):
        if not path.is_dir():
            continue
        summary = load_topic_run_summary(path)
        if not _is_auto_selectable(summary, path):
            continue
        rank = _rank(summary, path)
        if rank[0] <= 0:
            continue
        current = best.get(summary.topic)
        if current is None or rank > current[0]:
            best[summary.topic] = (rank, path)
    return tuple(path for _, path in sorted(best.values(), key=lambda item: item[1].name))


def build_meta_synthesis(run_dirs: tuple[Path, ...], out_dir: Path) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = build_field_manifest(tuple(run_dirs))
    convergences = detect_mechanism_convergences(manifest)
    contradictions = detect_cross_topic_contradictions(manifest)
    md = render_cross_topic_meta_synthesis(manifest, convergences, contradictions)
    audit = {
        "n_topics": len(manifest.topics),
        "n_primary_topics": sum(t.eligibility == "full_aaa_primary" for t in manifest.topics),
        "n_analytical_topics": sum(t.eligibility == "analytical_support" for t in manifest.topics),
        "n_scoped_topics": sum(t.eligibility == "scoped_support" for t in manifest.topics),
        "n_excluded_topics": sum(t.eligibility == "excluded" for t in manifest.topics),
        "n_convergences": len(convergences),
        "n_contradictions": len(contradictions),
        "scoped_in_primary_conclusions": False,
        "new_raw_paper_claims": False,
    }
    matrix = {
        "convergences": [c.to_dict() for c in convergences],
        "contradictions": [c.to_dict() for c in contradictions],
    }
    _write_json(out_dir / "cross_topic_manifest.json", manifest.to_dict())
    _write_json(out_dir / "cross_topic_matrix.json", matrix)
    _write_json(out_dir / "cross_topic_audit.json", audit)
    (out_dir / "cross_topic_meta_synthesis.md").write_text(md, encoding="utf-8")
    return audit


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build cross-topic meta-synthesis")
    parser.add_argument(
        "--runs-root", type=Path, default=REPO_ROOT / "runs",
        help="Directory containing synthesis run folders",
    )
    parser.add_argument(
        "--out-dir", type=Path,
        default=REPO_ROOT / "runs" / "meta-synthesis-geroscience-2026-05-09",
    )
    parser.add_argument(
        "--run-dir", type=Path, action="append", default=[],
        help="Explicit synthesis run dir; repeat for multiple topics",
    )
    args = parser.parse_args(argv)
    run_dirs = tuple(args.run_dir) if args.run_dir else select_best_runs(args.runs_root)
    audit = build_meta_synthesis(run_dirs, args.out_dir)
    print(json.dumps(audit, indent=2, sort_keys=True))
    return 0


def _rank(summary, path: Path) -> tuple[int, int, int, str, str]:
    eligibility_rank = {
        "full_aaa_primary": 4,
        "analytical_support": 3,
        "scoped_support": 2,
        "excluded": 0,
    }[summary.eligibility]
    return (
        eligibility_rank,
        summary.maturity_level,
        summary.n_receipts,
        _run_time_key(path.name),
        path.name,
    )


def _is_auto_selectable(summary, path: Path) -> bool:
    if summary.eligibility == "excluded":
        return False
    if summary.certification_track not in VALID_CERTIFICATION_TRACKS:
        return False
    return _audit_is_complete(path)


def _audit_is_complete(path: Path) -> bool:
    audit_path = path / "full_paper.audit.json"
    if not audit_path.exists():
        return False
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    n_pass = int(audit.get("n_pass") or 0)
    n_total = int(audit.get("n_total") or 0)
    return n_total >= 14 and n_pass == n_total and audit.get("p1_pass") is not False


def _run_time_key(run_id: str) -> str:
    match = re.search(
        r"(20\d{2})-(\d{2})-(\d{2})T(?:(\d{2})-(\d{2})-(\d{2})Z|(\d{1,2}))",
        run_id,
    )
    if not match:
        return ""
    year, month, day, hour, minute, second, short_hour = match.groups()
    if short_hour is not None:
        hour = short_hour.zfill(2)
        minute = "00"
        second = "00"
    return f"{year}{month}{day}{hour}{minute}{second}"


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
