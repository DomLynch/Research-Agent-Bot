from __future__ import annotations

import re
from typing import Any


REVIEWISH_TITLE_RE = re.compile(
    r"\b(review|overview|perspective|commentary|therapeutic paradox|narrative|role of|pathophysiology|"
    r"therapeutic frontiers?|therapeutic potential|path to the clinic|current perspectives?)\b",
    re.IGNORECASE,
)


def is_reviewish_title(value: Any) -> bool:
    return bool(REVIEWISH_TITLE_RE.search(str(value or "")))
