"""Compatibility entry point for the V3 publication submit bridge."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from publishing import submission as _implementation  # noqa: E402
from agent.observability import run_observed  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(run_observed("publishing_submit", _implementation.main))

sys.modules[__name__] = _implementation
