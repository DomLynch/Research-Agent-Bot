"""Fail-closed retraction checks for cited DOI sources."""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path

_OPENALEX = "https://api.openalex.org/works"
_CROSSREF = "https://api.crossref.org/works"
_PUBMED = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
_DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\]|>]+", re.I)


class RetractionCheckUnavailable(RuntimeError):
    pass


def _bare_doi(doi: str) -> str:
    return doi.strip().lower().removeprefix("https://doi.org/").removeprefix("doi.org/")


def cited_dois(run_dir: Path, *, strict: bool = False) -> list[str]:
    """Return every DOI cited by a completed paper run."""
    try:
        registry = json.loads((run_dir / "citation_registry.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        if strict:
            raise RetractionCheckUnavailable(str(exc)) from exc
        return []
    if not isinstance(registry, dict) or any(not isinstance(row, dict) for row in registry.values()):
        if strict:
            raise RetractionCheckUnavailable("malformed citation registry")
        registry = {}
    dois = {_bare_doi(str(row["source_doi"])) for row in registry.values() if row.get("source_doi")}
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
            dois.update(_bare_doi(match.group(0).rstrip(".,;:)")) for match in _DOI_RE.finditer(references.group(1)))
    return sorted(doi for doi in dois if doi)


def _fetch_openalex(
    dois: list[str], *, open_url: Callable[..., object] = urllib.request.urlopen,
    sleeper: Callable[[float], object] = time.sleep,
) -> list[dict]:
    params = {"filter": "doi:" + "|".join(dois), "select": "doi,is_retracted", "per-page": "200"}
    for env, param in (("OPENALEX_API_KEY", "api_key"), ("OPENALEX_MAILTO", "mailto")):
        if value := os.environ.get(env, "").strip():
            params[param] = value
    request = urllib.request.Request(
        f"{_OPENALEX}?{urllib.parse.urlencode(params, safe='|:./')}",
        headers={"Accept": "application/json"},
    )
    payload: object = {}
    for attempt in range(6):
        try:
            with open_url(request, timeout=30) as response:  # type: ignore[attr-defined]
                payload = json.loads(response.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as exc:
            if exc.code not in {429, 500, 502, 503, 504} or attempt == 5:
                raise
            delay = 2**attempt
            try:
                delay = float((exc.headers.get("Retry-After") if exc.headers else None) or delay)
            except (TypeError, ValueError):
                pass
            if delay > 30:
                raise
            sleeper(max(1.0, delay))
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise ValueError("malformed OpenAlex response")
    return payload["results"]


def _fetch_crossref_retractions(
    dois: list[str], *, open_url: Callable[..., object] = urllib.request.urlopen,
    sleeper: Callable[[float], object] = time.sleep,
) -> tuple[list[str], list[str]]:
    """Return retracted and uncovered DOIs from Crossref/Retraction Watch."""
    clean = sorted({_bare_doi(doi) for doi in dois if doi.strip()})
    retracted: list[str] = []
    missing: list[str] = []
    mailto = os.environ.get("CROSSREF_MAILTO", "").strip()
    for index, doi in enumerate(clean):
        url = f"{_CROSSREF}/{urllib.parse.quote(doi, safe='/')}"
        if mailto:
            url += "?" + urllib.parse.urlencode({"mailto": mailto})
        request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "Researka-V3/1.0"})
        payload: object = {}
        for attempt in range(3):
            try:
                with open_url(request, timeout=30) as response:  # type: ignore[attr-defined]
                    payload = json.loads(response.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    missing.append(doi)
                    break
                if exc.code not in {429, 500, 502, 503, 504} or attempt == 2:
                    raise
                sleeper(min(10.0, max(1.0, 2**attempt)))
        if index + 1 < len(clean):
            sleeper(0.21)
        if doi in missing:
            continue
        message = payload.get("message") if isinstance(payload, dict) else None
        if not isinstance(message, dict):
            raise ValueError("malformed Crossref response")
        updates = message.get("updated-by")
        if isinstance(updates, list) and any(
            isinstance(row, dict) and str(row.get("type") or "").lower() == "retraction" for row in updates
        ):
            retracted.append(doi)
    return retracted, missing


def _fetch_pubmed_retractions(
    dois: list[str], *, open_url: Callable[..., object] = urllib.request.urlopen,
) -> list[str]:
    """Use PubMed only when it indexes every DOI, otherwise fail closed."""
    clean = sorted({_bare_doi(doi) for doi in dois if doi.strip()})
    if not clean:
        return []
    query = " OR ".join(f'"{doi}"[doi]' for doi in clean)

    def request(endpoint: str, params: dict[str, str]) -> bytes:
        params = {"db": "pubmed", **params}
        if key := os.environ.get("NCBI_API_KEY", "").strip():
            params["api_key"] = key
        req = urllib.request.Request(
            f"{_PUBMED}/{endpoint}.fcgi",
            data=urllib.parse.urlencode(params).encode(),
        )
        for attempt in range(3):
            try:
                with open_url(req, timeout=30) as response:  # type: ignore[attr-defined]
                    return response.read()
            except urllib.error.HTTPError as exc:
                if exc.code != 429 or attempt == 2:
                    raise
                time.sleep(min(5.0, max(0.5, float(exc.headers.get("Retry-After") or 1))))
        raise RetractionCheckUnavailable("PubMed retry budget exhausted")

    def search(term: str) -> list[str]:
        try:
            result = json.loads(request("esearch", {
                "retmode": "json", "retmax": str(len(clean)), "term": term,
            }).decode())["esearchresult"]
            ids = [str(value) for value in result["idlist"] if str(value).isdigit()]
            if int(result["count"]) != len(ids):
                raise ValueError("incomplete PubMed result")
            return ids
        except (OSError, ValueError, KeyError, TypeError, urllib.error.URLError, json.JSONDecodeError) as exc:
            raise RetractionCheckUnavailable(f"PubMed search unavailable: {exc}") from exc

    if len(search(f"({query})")) != len(clean):
        raise RetractionCheckUnavailable("incomplete PubMed DOI coverage")
    retracted_pmids = search(f"({query}) AND retracted publication[pt]")
    if not retracted_pmids:
        return []
    try:
        root = ET.fromstring(request("efetch", {"retmode": "xml", "id": ",".join(retracted_pmids)}))
    except (OSError, ET.ParseError, urllib.error.URLError) as exc:
        raise RetractionCheckUnavailable(f"PubMed details unavailable: {exc}") from exc
    found = {
        str(article.findtext(".//PMID") or "").strip(): _bare_doi(str(doi.text or ""))
        for article in root.findall(".//PubmedArticle")
        if (doi := next((node for node in article.findall(".//ArticleId") if node.attrib.get("IdType", "").lower() == "doi"), None)) is not None
    }
    if set(retracted_pmids) - found.keys():
        raise RetractionCheckUnavailable("incomplete PubMed retraction details")
    return sorted(found.values())


def retracted_dois(
    dois: list[str], *, fetch: Callable[[list[str]], list[dict]] = _fetch_openalex,
    strict: bool = False,
) -> list[str]:
    clean = sorted({_bare_doi(doi) for doi in dois if doi.strip()})
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
        if not isinstance(row, dict) or not row.get("doi") or type(row.get("is_retracted")) is not bool:
            if strict:
                raise RetractionCheckUnavailable("malformed retraction result row")
            continue
        valid.append(row)
    seen = {_bare_doi(str(row["doi"])) for row in valid}
    if strict and set(clean) - seen:
        raise RetractionCheckUnavailable("incomplete retraction result")
    return sorted(_bare_doi(str(row["doi"])) for row in valid if row["is_retracted"])


def retracted_cited_sources(
    run_dir: Path, *, fetch: Callable[[list[str]], list[dict]] = _fetch_openalex,
    crossref_fetch: Callable[[list[str]], tuple[list[str], list[str]]] = _fetch_crossref_retractions,
    pubmed_fetch: Callable[[list[str]], list[str]] = _fetch_pubmed_retractions,
    strict: bool = False,
) -> list[str]:
    dois = cited_dois(run_dir, strict=strict)
    try:
        return retracted_dois(dois, fetch=fetch, strict=strict)
    except RetractionCheckUnavailable as primary:
        try:
            crossref_retracted, missing = crossref_fetch(dois)
            return sorted({*crossref_retracted, *(pubmed_fetch(missing) if missing else [])})
        except (OSError, ValueError, KeyError, TypeError, RetractionCheckUnavailable) as secondary:
            try:
                return pubmed_fetch(dois)
            except (OSError, ValueError, KeyError, TypeError, RetractionCheckUnavailable) as fallback:
                raise RetractionCheckUnavailable(
                    f"OpenAlex unavailable ({primary}); Crossref unavailable ({secondary}); "
                    f"PubMed unavailable ({fallback})"
                ) from fallback
