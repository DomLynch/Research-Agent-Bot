"""Compatibility wrapper for the journal finalizer implementation.

The implementation lives in scripts/journal_finalizer.py (pipeline tooling),
while production and tests import ``agent.journal_finalizer``. ``import_module``
keeps the dependency dynamic (no static ``import-not-found`` when ``scripts`` is
off the mypy path), the ``sys.modules`` swap makes callers receive the real
module, and the module-level ``__getattr__`` forwards every symbol — including
the private ``_phase_*`` helpers — so both callers and mypy see them without
enumerating internals. The previous explicit per-symbol ``getattr`` lines only
covered a hand-maintained subset, so mypy reported ``has no attribute`` for the
rest.
"""
from __future__ import annotations

import importlib
import sys
from typing import Any

_impl = importlib.import_module("scripts.journal_finalizer")
sys.modules[__name__] = _impl


def __getattr__(name: str) -> Any:
    return getattr(_impl, name)
