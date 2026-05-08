#!/usr/bin/env python3
"""Cron scaffold for publishing eligible run directories to OSF."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import osf_publish

REPO = Path(__file__).resolve().parent.parent
DEFAULT_RUNS_DIR = REPO / "runs"


def iter_eligible_runs(runs_dir: Path, *, force: bool = False) -> list[Path]:
    """Return child run dirs without an OSF publish result."""
    root = runs_dir.resolve()
    if not root.is_dir():
        raise NotADirectoryError(root)
    return [
        path
        for path in sorted(root.iterdir(), key=lambda p: p.name)
        if path.is_dir() and (force or not (path / osf_publish.RESULT_NAME).exists())
    ]


def publish_eligible(
    runs_dir: Path,
    *,
    dry_run: bool = True,
    force: bool = False,
) -> list[dict]:
    """Publish or plan every eligible run by delegating to osf_publish.run()."""
    outcomes = []
    for run_dir in iter_eligible_runs(runs_dir, force=force):
        paths = osf_publish.run(
            run_dir,
            dry_run=dry_run,
            snapshot_only=False,
            force=force,
        )
        outcomes.append({"run_dir": run_dir, "paths": paths})
    return outcomes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-dir", default=str(DEFAULT_RUNS_DIR))
    parser.add_argument(
        "--live",
        action="store_true",
        help="Publish live; requires OSF_PUBLISH_LIVE=1 and OSF_PAT.",
    )
    parser.add_argument("--force", action="store_true", help="Reprocess published runs")
    args = parser.parse_args(argv)
    try:
        outcomes = publish_eligible(
            Path(args.runs_dir),
            dry_run=not args.live,
            force=args.force,
        )
    except (OSError, RuntimeError) as exc:
        print(f"osf publish cron failed: {exc}", file=sys.stderr)
        return 2
    for item in outcomes:
        print(f"planned: {item['run_dir']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
