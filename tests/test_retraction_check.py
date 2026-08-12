from __future__ import annotations

import json
import urllib.error
from email.message import Message
from pathlib import Path
from typing import Any

import pytest

from agent import retraction_check as rc
from agent import retraction_check as retraction_impl


def _fetch(results: list[dict[str, Any]]):
    def fake(_dois: list[str]) -> list[dict[str, Any]]:
        return results
    return fake


def test_retracted_dois_flags_only_retracted() -> None:
    fetch = _fetch([
        {"doi": "https://doi.org/10.1/x", "is_retracted": True},
        {"doi": "https://doi.org/10.2/y", "is_retracted": False},
    ])
    assert rc.retracted_dois(["10.1/X", "10.2/y"], fetch=fetch) == ["10.1/x"]


def test_retracted_dois_empty_when_none_retracted() -> None:
    fetch = _fetch([{"doi": "https://doi.org/10.1/x", "is_retracted": False}])
    assert rc.retracted_dois(["10.1/x"], fetch=fetch) == []
    assert rc.retracted_dois(["10.1/x"], fetch=fetch, strict=True) == []


def test_openalex_retries_rate_limit() -> None:
    attempts = 0
    sleeps: list[float] = []

    class Response:
        def __enter__(self) -> Response:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps({"results": [{"doi": "https://doi.org/10.1/x", "is_retracted": False}]}).encode()

    def open_url(_request: object, *, timeout: int) -> Response:
        nonlocal attempts
        assert timeout == 30
        attempts += 1
        if attempts < 3:
            headers = Message()
            headers["Retry-After"] = "0"
            raise urllib.error.HTTPError("https://api.openalex.org", 429, "rate limited", headers, None)
        return Response()

    assert rc._fetch_openalex(["10.1/x"], open_url=open_url, sleeper=sleeps.append) == [
        {"doi": "https://doi.org/10.1/x", "is_retracted": False},
    ]
    assert attempts == 3
    assert sleeps == [1.0, 1.0]


def test_openalex_does_not_wait_past_daily_budget_window() -> None:
    headers = Message()
    headers["Retry-After"] = "31734"

    def open_url(_request: object, *, timeout: int) -> object:
        raise urllib.error.HTTPError("https://api.openalex.org", 429, "budget exhausted", headers, None)

    with pytest.raises(urllib.error.HTTPError):
        rc._fetch_openalex(["10.1/x"], open_url=open_url, sleeper=lambda _delay: pytest.fail("must not sleep"))


def test_crossref_retractions_are_complete_and_rate_limited() -> None:
    payloads: list[dict[str, object] | None] = [
        {"message": {"updated-by": []}},
        {"message": {"updated-by": [{"type": "retraction", "source": "retraction-watch"}]}},
        None,
    ]
    sleeps: list[float] = []

    class Response:
        def __init__(self, payload: dict[str, object]) -> None:
            self.payload = payload

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(self.payload).encode()

    def open_url(request: object, *, timeout: int) -> Response:
        payload = payloads.pop(0)
        if payload is None:
            raise urllib.error.HTTPError(str(request), 404, "missing", Message(), None)
        return Response(payload)

    assert retraction_impl._fetch_crossref_retractions(
        ["10.1/good", "10.2/bad", "10.3/missing"], open_url=open_url, sleeper=sleeps.append,
    ) == (["10.2/bad"], ["10.3/missing"])
    assert sleeps == [0.21, 0.21]


def test_retracted_dois_strict_rejects_incomplete_results() -> None:
    with pytest.raises(rc.RetractionCheckUnavailable):
        rc.retracted_dois(["10.1/x"], fetch=_fetch([]), strict=True)
    with pytest.raises(rc.RetractionCheckUnavailable):
        rc.retracted_dois(
            ["10.1/x", "10.2/missing"],
            fetch=_fetch([{"doi": "10.1/x", "is_retracted": True}]), strict=True,
        )


@pytest.mark.parametrize("row", [
    {"doi": "https://doi.org/10.1/x"},
    {"doi": "https://doi.org/10.1/x", "is_retracted": "false"},
    {"is_retracted": False},
    "not-a-row",
])
def test_retracted_dois_strict_rejects_malformed_rows(row: object) -> None:
    with pytest.raises(rc.RetractionCheckUnavailable):
        rc.retracted_dois(["10.1/x"], fetch=lambda _dois: [row], strict=True)  # type: ignore[list-item]


def test_retracted_dois_failopen_on_fetch_error() -> None:
    def boom(_dois: list[str]) -> list[dict[str, Any]]:
        raise OSError("network down")
    assert rc.retracted_dois(["10.1/x"], fetch=boom) == []  # fail-open: never block
    with pytest.raises(rc.RetractionCheckUnavailable):
        rc.retracted_dois(["10.1/x"], fetch=boom, strict=True)


def test_retracted_dois_empty_input() -> None:
    assert rc.retracted_dois([], fetch=_fetch([])) == []


def test_checked_retracted_dois_preserves_fallback_without_run_artifacts() -> None:
    assert rc.checked_retracted_dois(
        ["10.1/good", "10.2/bad"],
        fetch=_fetch([{"doi": "10.1/good", "is_retracted": False}]),
        crossref_fetch=lambda _dois: (["10.2/bad"], []),
        pubmed_fetch=lambda _dois: pytest.fail("complete Crossref coverage must not call PubMed"),
        strict=True,
    ) == ["10.2/bad"]


def test_exclude_retracted_filters_records_by_normalized_doi() -> None:
    rows = [{"doi": "10.1/good"}, {"doi": "https://doi.org/10.2/BAD"}]
    kept, blocked = rc.exclude_retracted(
        rows, doi_of=lambda row: row["doi"],
        checker=lambda _dois, strict: ["10.2/bad"],
    )
    assert kept == [rows[0]]
    assert blocked == ["10.2/bad"]


def test_cited_dois_reads_registry(tmp_path: Path) -> None:
    reg = {
        "r1": {"source_doi": "10.7554/eLife.16351"},
        "r2": {"source_doi": "https://doi.org/10.1/ABC"},
        "r3": {"source_doi": ""},          # ignored
        "r4": {"body_citation": "no doi"},  # ignored
    }
    (tmp_path / "citation_registry.json").write_text(json.dumps(reg), encoding="utf-8")
    assert rc.cited_dois(tmp_path) == ["10.1/abc", "10.7554/elife.16351"]


def test_retracted_cited_sources_end_to_end(tmp_path: Path) -> None:
    (tmp_path / "citation_registry.json").write_text(
        json.dumps({"r1": {"source_doi": "10.1/good"}, "r2": {"source_doi": "10.2/bad"}}), encoding="utf-8")
    fetch = _fetch([
        {"doi": "https://doi.org/10.1/good", "is_retracted": False},
        {"doi": "https://doi.org/10.2/bad", "is_retracted": True},
    ])
    assert rc.retracted_cited_sources(tmp_path, fetch=fetch) == ["10.2/bad"]


def test_strict_check_falls_back_to_pubmed_when_openalex_is_unavailable(tmp_path: Path) -> None:
    (tmp_path / "citation_registry.json").write_text(
        json.dumps({"r1": {"source_doi": "10.1/good"}}), encoding="utf-8",
    )
    (tmp_path / "full_paper.md").write_text(
        "## References\n\n- Good study. DOI: 10.1/good.\n", encoding="utf-8",
    )

    def unavailable(_dois: list[str]) -> list[dict[str, Any]]:
        raise OSError("OpenAlex quota exhausted")

    def crossref_unavailable(_dois: list[str]) -> tuple[list[str], list[str]]:
        raise OSError("Crossref unavailable")

    assert rc.retracted_cited_sources(
        tmp_path,
        fetch=unavailable,
        crossref_fetch=crossref_unavailable,
        pubmed_fetch=lambda dois: [] if dois == ["10.1/good"] else pytest.fail("wrong DOI set"),
        strict=True,
    ) == []


def test_strict_check_uses_crossref_before_pubmed(tmp_path: Path) -> None:
    (tmp_path / "citation_registry.json").write_text(
        json.dumps({"r1": {"source_doi": "10.1/bad"}}), encoding="utf-8",
    )
    (tmp_path / "full_paper.md").write_text("## References\n\n- Bad. DOI: 10.1/bad.\n", encoding="utf-8")

    assert rc.retracted_cited_sources(
        tmp_path,
        fetch=lambda _dois: (_ for _ in ()).throw(OSError("OpenAlex unavailable")),
        crossref_fetch=lambda dois: (["10.1/bad"], []) if dois == ["10.1/bad"] else pytest.fail("wrong DOI set"),
        pubmed_fetch=lambda _dois: pytest.fail("complete Crossref coverage must not call PubMed"),
        strict=True,
    ) == ["10.1/bad"]


def test_pubmed_fallback_requires_complete_doi_coverage() -> None:
    responses = iter([
        {"esearchresult": {"count": "1", "idlist": ["123"]}},
    ])

    class Response:
        def __init__(self, payload: dict[str, Any]) -> None:
            self.payload = payload

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(self.payload).encode("utf-8")

    def open_url(_request: object, *, timeout: int) -> Response:
        assert timeout == 30
        return Response(next(responses))

    with pytest.raises(rc.RetractionCheckUnavailable, match="incomplete PubMed DOI coverage"):
        rc._fetch_pubmed_retractions(["10.1/a", "10.2/b"], open_url=open_url)


def test_pubmed_fallback_maps_retracted_pmid_back_to_doi() -> None:
    payloads = iter([
        json.dumps({"esearchresult": {"count": "2", "idlist": ["123", "456"]}}).encode(),
        json.dumps({"esearchresult": {"count": "1", "idlist": ["456"]}}).encode(),
        b"<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>456</PMID></MedlineCitation>"
        b"<PubmedData><ArticleIdList><ArticleId IdType='doi'>10.2/B</ArticleId>"
        b"</ArticleIdList></PubmedData></PubmedArticle></PubmedArticleSet>",
    ])

    class Response:
        def __init__(self, payload: bytes) -> None:
            self.payload = payload

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return self.payload

    def open_url(_request: object, *, timeout: int) -> Response:
        assert timeout == 30
        return Response(next(payloads))

    assert rc._fetch_pubmed_retractions(
        ["10.1/a", "10.2/b"], open_url=open_url,
    ) == ["10.2/b"]


def test_cited_dois_missing_registry_is_empty(tmp_path: Path) -> None:
    assert rc.cited_dois(tmp_path) == []
    with pytest.raises(rc.RetractionCheckUnavailable):
        rc.cited_dois(tmp_path, strict=True)


@pytest.mark.parametrize("registry", [[], {"r1": "not-a-row"}])
def test_cited_dois_strict_rejects_malformed_registry(
    tmp_path: Path, registry: object,
) -> None:
    (tmp_path / "citation_registry.json").write_text(json.dumps(registry), encoding="utf-8")
    with pytest.raises(rc.RetractionCheckUnavailable):
        rc.cited_dois(tmp_path, strict=True)


def test_background_reference_doi_is_checked(tmp_path: Path) -> None:
    (tmp_path / "citation_registry.json").write_text("{}", encoding="utf-8")
    (tmp_path / "full_paper.md").write_text(
        "## References\n\n### Background References\n\n"
        "- Context only (https://doi.org/10.1234/BAD).\n",
        encoding="utf-8",
    )
    fetch = _fetch([{
        "doi": "https://doi.org/10.1234/bad",
        "is_retracted": True,
    }])

    assert rc.retracted_cited_sources(tmp_path, fetch=fetch, strict=True) == ["10.1234/bad"]
