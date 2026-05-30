"""Retraction gate (paper-qa 'retractions' borrow — recreated, not vendored).

v3's corpus carries no retraction flag, so this asks OpenAlex (the corpus's own
source) whether any DOI a paper cites is_retracted, in one batched query, and
returns the retracted ones. Citing retracted science is a hard integrity
failure, so the submit gate blocks on a non-empty result.

Fail-open: any network/parse error returns [] — an OpenAlex outage must never
block the whole submission pipeline. Topic-agnostic; no per-topic knowledge.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path

_OPENALEX = "https://api.openalex.org/works"


def _bare_doi(doi: str) -> str:
    """Normalise to the bare 10.xxx form (OpenAlex returns full https://doi.org/ URLs)."""
    return doi.strip().lower().removeprefix("https://doi.org/").removeprefix("doi.org/")


def cited_dois(run_dir: Path) -> list[str]:
    """Bare DOIs of the sources cited in the run's citation registry."""
    try:
        reg = json.loads((run_dir / "citation_registry.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out = {
        _bare_doi(str(e["source_doi"]))
        for e in (reg.values() if isinstance(reg, dict) else [])
        if isinstance(e, dict) and e.get("source_doi")
    }
    return sorted(d for d in out if d)


def _fetch_openalex(dois: list[str]) -> list[dict]:
    flt = urllib.parse.quote("doi:" + "|".join(dois), safe="|:./")
    url = f"{_OPENALEX}?filter={flt}&select=doi,is_retracted&per-page=200"
    with urllib.request.urlopen(urllib.request.Request(url, headers={"Accept": "application/json"}), timeout=30) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    return body.get("results", []) if isinstance(body, dict) else []


def retracted_dois(dois: list[str], *, fetch: Callable[[list[str]], list[dict]] = _fetch_openalex) -> list[str]:
    """Subset of `dois` OpenAlex flags is_retracted. Fail-open ([]) on any error."""
    clean = sorted({_bare_doi(d) for d in dois if d and d.strip()})
    if not clean:
        return []
    try:
        results = fetch(clean)
    except (OSError, ValueError, KeyError, TypeError, urllib.error.URLError):
        return []
    return sorted({
        _bare_doi(str(w.get("doi") or ""))
        for w in (results if isinstance(results, list) else [])
        if isinstance(w, dict) and w.get("is_retracted") and w.get("doi")
    })


def retracted_cited_sources(run_dir: Path, *, fetch: Callable[[list[str]], list[dict]] = _fetch_openalex) -> list[str]:
    """Retracted DOIs cited by the paper in `run_dir` (empty = clean / fail-open)."""
    return retracted_dois(cited_dois(run_dir), fetch=fetch)
