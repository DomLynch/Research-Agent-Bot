"""Deprecated compatibility shim; use scripts.final_reviewer."""
from __future__ import annotations

import warnings
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from final_reviewer import *  # noqa: F401, F403
from final_reviewer import review_paper

review_with_grok = review_paper
warnings.warn(
    "scripts.grok_reviewer is deprecated; import from scripts.final_reviewer",
    DeprecationWarning,
    stacklevel=2,
)
