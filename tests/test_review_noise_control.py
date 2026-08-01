from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import review_noise_control as noise  # noqa: E402


def test_table_dedup_includes_timepoint() -> None:
    table = """| Study | Endpoint | Arm | Timepoint | Value |
|---|---|---|---|---|
| Smith | HbA1c | active | 3 months | -0.2 |
| Smith | HbA1c | active | 6 months | -0.4 |
| Smith | HbA1c | active | 6 months | -0.4 |"""

    fixed, removed = noise._dedupe_duplicate_table_rows(table)

    assert removed == 1
    assert "3 months" in fixed
    assert fixed.count("6 months") == 1
