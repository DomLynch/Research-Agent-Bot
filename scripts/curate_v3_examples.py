"""Curate a tiny public examples folder from verified v3 run exports."""
from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
DEFAULT_OUT = REPO / "examples" / "v3"
KEEP = {
    "full_paper.md",
    "paper_ir.json",
    "paper_quality_score.json",
    "public_export_manifest.json",
    "structured_evidence_tables.md",
    "references.bib",
    "evidence_table.csv",
    "contradiction_map.json",
}


def curate_examples(
    runs_dir: Path, out_dir: Path = DEFAULT_OUT, *, limit: int = 3, min_score: float = 80.0,
) -> list[Path]:
    candidates = sorted(
        (row for row in (_candidate(run, min_score) for run in runs_dir.glob("synthesis-*")) if row),
        key=lambda row: (-row[0], row[1].name),
    )[:limit]
    written: list[Path] = []
    out_dir.mkdir(parents=True, exist_ok=True)
    for score, run in candidates:
        target = out_dir / _slug(run.name)
        target.mkdir(parents=True, exist_ok=True)
        for name in KEEP:
            src = run / name
            if src.is_file():
                shutil.copy2(src, target / name)
        (target / "full_paper.md").write_text(
            _clean_public_manuscript((run / "full_paper.md").read_text(encoding="utf-8")),
            encoding="utf-8",
        )
        (target / "README.md").write_text(_readme(run, score), encoding="utf-8")
        written.append(target)
    return written


def _candidate(run: Path, min_score: float) -> tuple[float, Path] | None:
    score = _read_json(run / "paper_quality_score.json")
    manifest = _read_json(run / "public_export_manifest.json")
    value = score.get("score_out_of_100")
    if not isinstance(value, int | float) or value < min_score:
        return None
    if not isinstance(manifest.get("files"), dict):
        return None
    if not (run / "full_paper.md").is_file() or not (run / "paper_ir.json").is_file():
        return None
    return float(value), run


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _clean_public_manuscript(markdown: str) -> str:
    out = markdown
    for heading in ("Quantitative Evidence Index", "Structured Evidence Tables", "Inferential Bridge"):
        out = re.sub(rf"(?ms)^##\s+{re.escape(heading)}\b.*?(?=^##\s+|\Z)", "", out)
    out = re.sub(r"(?ms)^\|.+?\|\n\|[-:| ]+\|\n(?:\|.*?\|\n?)+", "", out)
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    return out + "\n"


def _slug(name: str) -> str:
    return name.removeprefix("synthesis-").split("-v", 1)[0].replace("_", "-")


def _readme(run: Path, score: float) -> str:
    return (
        f"# {run.name}\n\n"
        f"Curated v3 example copied from `{run.name}`.\n\n"
        f"- Paper quality score: {score:.1f}/100\n"
        "- Includes cleaned manuscript, PaperIR, export manifest, evidence CSV, "
        "references, contradiction map, and supplement when present.\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-dir", type=Path, default=REPO / "runs")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--min-score", type=float, default=80.0)
    args = parser.parse_args(argv)
    written = curate_examples(args.runs_dir, args.out_dir, limit=args.limit, min_score=args.min_score)
    print("\n".join(str(path) for path in written))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
