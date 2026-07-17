"""Compatibility facade for the runtime retraction checker."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent import retraction_check as _impl  # noqa: E402
from agent.retraction_check import (  # noqa: E402
    RetractionCheckUnavailable,
    cited_dois,
    retracted_cited_sources,
    retracted_dois,
)

_fetch_openalex = _impl._fetch_openalex
_fetch_pubmed_retractions = _impl._fetch_pubmed_retractions

__all__ = ["RetractionCheckUnavailable", "cited_dois", "retracted_cited_sources", "retracted_dois"]
