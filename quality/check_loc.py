"""Report advisory source-size thresholds; size alone never blocks release."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Existing thresholds retained for visibility, not increased to hide growth.
DIRECTORY_THRESHOLDS = {"agent": (25269, 800), "scripts": (40231, 5700)}
COMBINED_THRESHOLD = 65500


def _count_loc(path: Path) -> int:
    return sum(
        bool(line.strip()) and not line.lstrip().startswith("#")
        for line in path.read_text(encoding="utf-8").splitlines()
    )


def report(root: Path = ROOT) -> None:
    combined = 0
    for directory, (total_threshold, file_threshold) in DIRECTORY_THRESHOLDS.items():
        folder = root / directory
        if not folder.is_dir():
            raise FileNotFoundError(folder)
        counts = {
            path: _count_loc(path)
            for path in sorted(folder.rglob("*.py"))
            if "__pycache__" not in path.parts
        }
        total = sum(counts.values())
        combined += total
        _report_size(directory, total, total_threshold)
        for path, count in counts.items():
            if count > file_threshold:
                _report_size(str(path.relative_to(root)), count, file_threshold)
    _report_size("agent/ + scripts/", combined, COMBINED_THRESHOLD)


def _report_size(label: str, count: int, threshold: int) -> None:
    status = "WARNING" if count > threshold else "INFO"
    print(f"{status}: {label}: {count} effective LOC (advisory threshold {threshold})")


if __name__ == "__main__":
    report()
