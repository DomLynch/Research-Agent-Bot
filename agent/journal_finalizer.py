"""Compatibility wrapper for the journal finalizer implementation.

The implementation lives in scripts/ because it is pipeline tooling, while
existing production and tests import agent.journal_finalizer.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

_impl = importlib.import_module("journal_finalizer")

globals().update({
    name: value
    for name, value in vars(_impl).items()
    if not (name.startswith("__") and name.endswith("__"))
})

FinalizerLogEntry: Any = getattr(_impl, "FinalizerLogEntry")
FinalizerReport: Any = getattr(_impl, "FinalizerReport")
finalize_run: Any = getattr(_impl, "finalize_run")
_phase_b_lane_qualifier: Any = getattr(_impl, "_phase_b_lane_qualifier")
_phase_g_refresh_sidecars: Any = getattr(_impl, "_phase_g_refresh_sidecars")
_phase_h_topic_slug_normalise: Any = getattr(_impl, "_phase_h_topic_slug_normalise")
_phase_i_split_concatenated_headings: Any = getattr(
    _impl, "_phase_i_split_concatenated_headings",
)
_phase_k_route_outcome_paragraphs: Any = getattr(
    _impl, "_phase_k_route_outcome_paragraphs",
)
sys.modules[__name__] = _impl

__all__ = [
    name for name in globals()
    if not (name.startswith("__") and name.endswith("__"))
]
