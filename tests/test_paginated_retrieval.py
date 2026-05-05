"""Tests for agent/paginated_retrieval.py — Slice 8 step A.

No live HTTP; sources patched. Verifies pagination loop, exhaustion
detection, safety-cap enforcement, and resume-cursor state files.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from agent.paginated_retrieval import (
    PAGEABLE_SOURCES, _load_state, _state_path,
    clear_cursor_state, paginated_discover,
    paginate_one_source,
)
from agent.types import RawHit


def _hit(*, source: str, doi: str | None = None) -> RawHit:
    return RawHit(
        title="T", abstract="A", doi=doi, pmid=None, nct=None,
        year=2024, url=f"https://example/{source}/{doi}",
        venue=None, source=source, raw={},
    )


class _PageableSrc:
    """Fake source that supports offset pagination, returning
    `total` distinct hits across pages of `page_size`."""
    def __init__(self, name: str, total: int):
        self.name = name
        self.total = total
        self.calls: list[tuple[int, int]] = []

    async def search(self, client, query, *, limit, offset=0):
        self.calls.append((limit, offset))
        n = max(0, min(limit, self.total - offset))
        return [
            _hit(source=self.name, doi=f"{self.name}/{offset + i}")
            for i in range(n)
        ]


class _NonPageableSrc:
    """Fake source that doesn't support offset (signature has no
    offset kwarg). Paginator should call once and stop."""
    def __init__(self, name: str, total: int):
        self.name = name
        self.total = total
        self.calls = 0

    async def search(self, client, query, *, limit):
        self.calls += 1
        n = max(0, min(limit, self.total))
        return [
            _hit(source=self.name, doi=f"{self.name}/{i}")
            for i in range(n)
        ]


# ---------- paginate_one_source -------------------------------------

def test_paginate_pageable_source_walks_full_set(tmp_path):
    """A pageable source with 250 hits and page_size=100 → 3 pages."""
    src = _PageableSrc("pubmed", total=250)

    async def _run():
        return await paginate_one_source(
            client=None, source_name="pubmed", source_client=src,
            topic="t", query="q", safety_cap=10_000,
            page_size=100, repo_root=tmp_path,
        )
    hits, state = asyncio.run(_run())
    assert len(hits) == 250
    assert state.exhausted is True
    assert len(src.calls) == 3
    assert src.calls == [(100, 0), (100, 100), (100, 200)]


def test_paginate_safety_cap_stops_loop(tmp_path):
    src = _PageableSrc("pubmed", total=1_000_000)

    async def _run():
        return await paginate_one_source(
            client=None, source_name="pubmed", source_client=src,
            topic="t", query="q", safety_cap=250, page_size=100,
            repo_root=tmp_path,
        )
    hits, state = asyncio.run(_run())
    # Safety-cap stops the LOOP after the page that breaches it. Two
    # pages of 100 fit (200 ≤ 250); the third would push to 300.
    assert len(hits) <= 300
    assert state.last_error == "safety_cap_reached"


def test_paginate_non_pageable_source_called_once(tmp_path):
    """For non-pageable sources, the paginator runs exactly one
    call regardless of remaining cap (avoids duplicate fetches)."""
    src = _NonPageableSrc("doaj", total=100)

    async def _run():
        return await paginate_one_source(
            client=None, source_name="doaj", source_client=src,
            topic="t", query="q", safety_cap=10_000,
            page_size=100, repo_root=tmp_path,
        )
    hits, state = asyncio.run(_run())
    assert src.calls == 1
    assert state.exhausted is True


def test_paginate_writes_cursor_state(tmp_path):
    src = _PageableSrc("pubmed", total=300)

    async def _run():
        return await paginate_one_source(
            client=None, source_name="pubmed", source_client=src,
            topic="metformin", query="metformin AND aging",
            safety_cap=10_000, page_size=100, repo_root=tmp_path,
        )
    asyncio.run(_run())
    sp = _state_path(
        tmp_path, topic="metformin", source="pubmed",
        query="metformin AND aging",
    )
    assert sp.exists()
    state = _load_state(sp)
    assert state.exhausted is True
    assert state.total_returned == 300


def test_paginate_resumes_from_cursor(tmp_path):
    """If the cursor file says exhausted=True, the paginator returns
    immediately without calling the source."""
    sp = _state_path(
        tmp_path, topic="t", source="pubmed", query="q",
    )
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text(json.dumps({
        "topic": "t", "source": "pubmed", "query": "q",
        "next_offset": 500, "pages_fetched": 5,
        "total_returned": 500, "exhausted": True, "last_error": None,
    }))
    src = _PageableSrc("pubmed", total=1_000_000)

    async def _run():
        return await paginate_one_source(
            client=None, source_name="pubmed", source_client=src,
            topic="t", query="q", safety_cap=10_000,
            page_size=100, repo_root=tmp_path,
        )
    hits, state = asyncio.run(_run())
    assert hits == []
    assert src.calls == []  # no calls — exhausted state honored


def test_clear_cursor_state(tmp_path):
    """clear_cursor_state(topic=) deletes the cursor files."""
    for src in ("pubmed", "crossref"):
        sp = _state_path(tmp_path, topic="x", source=src, query="q")
        sp.parent.mkdir(parents=True, exist_ok=True)
        sp.write_text("{}")
    n = clear_cursor_state(topic="x", repo_root=tmp_path)
    assert n == 2
    # Second call: nothing left to delete
    assert clear_cursor_state(topic="x", repo_root=tmp_path) == 0


# ---------- pageable matrix is explicit ----------------------------

def test_pageable_sources_set_is_explicit():
    """The pageable allowlist is a frozen set — adding a source is
    a deliberate API-capability check, not a regex match."""
    assert PAGEABLE_SOURCES == frozenset(
        ("pubmed", "crossref", "semantic_scholar"),
    )


# ---------- paginated_discover: end-to-end mock --------------------

def test_paginated_discover_aggregates_across_sources(
    tmp_path, monkeypatch,
):
    """Multiple sources, each pageable, paginated independently and
    deduped at the end."""
    a = _PageableSrc("pubmed", total=120)
    b = _PageableSrc("crossref", total=80)

    fake = {
        "pubmed": (a, True, None),
        "crossref": (b, True, None),
    }
    monkeypatch.setattr(
        "agent.paginated_retrieval._build_registry", lambda: fake,
    )

    async def _run():
        return await paginated_discover(
            "rapamycin AND aging",
            topic="rapamycin", repo_root=tmp_path,
        )
    report = asyncio.run(_run())
    # 120 + 80 = 200 distinct (different DOI prefixes, no overlap)
    assert len(report.hits) == 200
    assert "pubmed" in report.per_source_state
    assert "crossref" in report.per_source_state
    assert report.per_source_state["pubmed"].exhausted is True
    assert report.per_source_state["crossref"].exhausted is True
