"""Retraction gate (paper-qa 'retractions' borrow — recreated, not vendored).

v3's corpus carries no retraction flag, so this asks OpenAlex (the corpus's own
source) whether any DOI a paper cites is_retracted, in one batched query, and
returns the retracted ones. Citing retracted science is a hard integrity
failure, so the submit gate blocks on a non-empty result.

Callers may request strict mode so an unavailable check blocks publication.
Topic-agnostic; no per-topic knowledge.
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path

_OPENALEX = "https://api.openalex.org/works"
_DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\]|>]+", re.I)


class RetractionCheckUnavailable(RuntimeError):
    pass


def _bare_doi(doi: str) -> str:
    """Normalise to the bare 10.xxx form (OpenAlex returns full https://doi.org/ URLs)."""
    return doi.strip().lower().removeprefix("https://doi.org/").removeprefix("doi.org/")


def cited_dois(run_dir: Path, *, strict: bool = False) -> list[str]:
    """Bare DOIs of the sources cited in the run's citation registry."""
    try:
        reg = json.loads((run_dir / "citation_registry.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        if strict:
            raise RetractionCheckUnavailable(str(exc)) from exc
        return []
    if not isinstance(reg, dict) or any(not isinstance(row, dict) for row in reg.values()):
        if strict:
            raise RetractionCheckUnavailable("malformed citation registry")
        reg = {}
    out = {
        _bare_doi(str(e["source_doi"]))
        for e in reg.values()
        if e.get("source_doi")
    }
    try:
        paper = (run_dir / "full_paper.md").read_text(encoding="utf-8")
    except OSError as exc:
        if strict:
            raise RetractionCheckUnavailable(str(exc)) from exc
    else:
        references = re.search(r"(?ms)^##\s+References\b(.*?)(?=^##\s+|\Z)", paper)
        if strict and references is None:
            raise RetractionCheckUnavailable("references section missing")
        if references:
            out.update(
                _bare_doi(match.group(0).rstrip(".,;:)"))
                for match in _DOI_RE.finditer(references.group(1))
            )
    return sorted(d for d in out if d)


def _fetch_openalex(dois: list[str]) -> list[dict]:
    flt = urllib.parse.quote("doi:" + "|".join(dois), safe="|:./")
    url = f"{_OPENALEX}?filter={flt}&select=doi,is_retracted&per-page=200"
    with urllib.request.urlopen(urllib.request.Request(url, headers={"Accept": "application/json"}), timeout=30) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    if not isinstance(body, dict) or not isinstance(body.get("results"), list):
        raise ValueError("malformed OpenAlex response")
    return body["results"]


def retracted_dois(
    dois: list[str], *, fetch: Callable[[list[str]], list[dict]] = _fetch_openalex,
    strict: bool = False,
) -> list[str]:
    """Subset OpenAlex flags retracted; strict mode surfaces lookup failure."""
    clean = sorted({_bare_doi(d) for d in dois if d and d.strip()})
    if not clean:
        return []
    try:
        results = fetch(clean)
    except (OSError, ValueError, KeyError, TypeError, urllib.error.URLError) as exc:
        if strict:
            raise RetractionCheckUnavailable(str(exc)) from exc
        return []
    if not isinstance(results, list):
        if strict:
            raise RetractionCheckUnavailable("malformed retraction result")
        results = []
    valid: list[dict] = []
    for row in results:
        if (
            not isinstance(row, dict)
            or not row.get("doi")
            or type(row.get("is_retracted")) is not bool
        ):
            if strict:
                raise RetractionCheckUnavailable("malformed retraction result row")
            continue
        valid.append(row)
    seen = {_bare_doi(str(row["doi"])) for row in valid}
    if strict and set(clean) - seen:
        raise RetractionCheckUnavailable("incomplete retraction result")
    return sorted({
        _bare_doi(str(w.get("doi") or ""))
        for w in valid if w["is_retracted"]
    })


def retracted_cited_sources(
    run_dir: Path, *, fetch: Callable[[list[str]], list[dict]] = _fetch_openalex,
    strict: bool = False,
) -> list[str]:
    """Retracted DOIs cited by the paper in `run_dir`."""
    return retracted_dois(cited_dois(run_dir, strict=strict), fetch=fetch, strict=strict)
