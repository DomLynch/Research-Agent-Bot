"""Paginated retrieval + resume cursor — Slice 8 step A
(2026-05-05).

End-game retrieval: pull until source-exhausted or 200K safety cap,
with per-source/topic/query cursor state files so a 6-hour pull
can be interrupted and resumed.

Pageability matrix:

  pubmed              offset (retstart)        ✓
  europepmc           cursorMark               cursor-attribute fwd
  openalex            cursor                   cursor-attribute fwd
  crossref            offset                   ✓
  semantic_scholar    offset                   ✓
  (others)            single-page max          non-paged (documented)

For the paginator's purposes: "pageable" sources receive
incrementing offset and we loop until they return < page_size.
"Non-pageable" sources return their first-page max and the paginator
records that fact in the cursor file.

Universal across topics + domains. Pure-Python orchestrator;
the per-source HTTP work happens in agent/sources/* adapters.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator

import httpx

from agent.retrieval_modes import (
    GLOBAL_SAFETY_CAP, RetrievalParams, resolve_params,
)
from agent.sources.aggregator import (
    AggregatedHit, _build_registry, _dedupe_key, _merge_and_dedupe,
)
from agent.types import RawHit

# Sources that natively support page-by-page offset retrieval. These
# are the ones the paginator drives in a true loop. Other sources
# return their first-page max and stop (paginator skips them after
# one call to avoid duplicate-fetch waste).
PAGEABLE_SOURCES: frozenset[str] = frozenset((
    "pubmed", "crossref", "semantic_scholar",
))

# Page sizes that work well for each source's API quotas. Universal
# across topics — set by API capability, not topic.
_DEFAULT_PAGE_SIZE: dict[str, int] = {
    "pubmed": 1000,         # retmax up to 9999, but 1000/page is polite
    "crossref": 1000,       # rows up to 1000
    "semantic_scholar": 100,  # limit cap is 100
}


def _state_dir(repo_root: Path) -> Path:
    """Where cursor state files live. runs/.cursors/ is gitignored."""
    d = repo_root / "runs" / ".cursors"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _state_path(
    repo_root: Path, *, topic: str, source: str, query: str,
) -> Path:
    """Cursor file path: runs/.cursors/<topic>__<source>__<qhash>.json"""
    h = hashlib.sha1(query.encode("utf-8")).hexdigest()[:12]
    return _state_dir(repo_root) / f"{topic}__{source}__{h}.json"


@dataclass(slots=True)
class _PaginationState:
    """Per-source per-query pagination state. Lives in a sidecar
    JSON file so a 6-hour pull can resume after interrupt."""
    topic: str
    source: str
    query: str
    next_offset: int = 0
    pages_fetched: int = 0
    total_returned: int = 0
    exhausted: bool = False
    last_error: str | None = None


def _load_state(path: Path) -> _PaginationState | None:
    if not path.exists():
        return None
    try:
        d = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return _PaginationState(**d)


def _save_state(path: Path, state: _PaginationState) -> None:
    """Atomic-ish write: temp → rename. Best-effort on failure."""
    try:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({
            "topic": state.topic, "source": state.source,
            "query": state.query, "next_offset": state.next_offset,
            "pages_fetched": state.pages_fetched,
            "total_returned": state.total_returned,
            "exhausted": state.exhausted,
            "last_error": state.last_error,
        }, indent=2))
        os.replace(tmp, path)
    except OSError:
        pass  # best-effort — pagination still works without state


async def paginate_one_source(
    client: httpx.AsyncClient,
    *,
    source_name: str,
    source_client: Any,
    topic: str,
    query: str,
    safety_cap: int,
    page_size: int | None = None,
    repo_root: Path,
    on_page: callable | None = None,
) -> tuple[list[RawHit], _PaginationState]:
    """Run pagination loop for a single source. Resumes from cursor
    file if present. Stops when source is exhausted (returns <
    page_size) OR safety_cap is reached."""
    page_size = page_size or _DEFAULT_PAGE_SIZE.get(
        source_name.lower(), 100,
    )
    state_path = _state_path(
        repo_root, topic=topic, source=source_name, query=query,
    )
    state = _load_state(state_path) or _PaginationState(
        topic=topic, source=source_name, query=query,
    )
    if state.exhausted:
        return [], state
    pageable = source_name.lower() in PAGEABLE_SOURCES
    out: list[RawHit] = []
    while True:
        if state.total_returned >= safety_cap:
            state.last_error = "safety_cap_reached"
            break
        try:
            if pageable:
                hits = await source_client.search(
                    client, query,
                    limit=page_size, offset=state.next_offset,
                )
            else:
                # Non-pageable: only call once per query.
                if state.pages_fetched > 0:
                    state.exhausted = True
                    break
                hits = await source_client.search(
                    client, query, limit=page_size,
                )
        except (httpx.HTTPError, ValueError, OSError, TypeError) as e:
            state.last_error = f"{type(e).__name__}: {str(e)[:100]}"
            break
        out.extend(hits)
        state.pages_fetched += 1
        state.total_returned += len(hits)
        if on_page is not None:
            on_page(state, hits)
        if not pageable or len(hits) < page_size:
            state.exhausted = True
            break
        state.next_offset += page_size
        # Persist after every page so an interrupt is recoverable.
        _save_state(state_path, state)
    _save_state(state_path, state)
    return out, state


@dataclass(slots=True)
class PaginatedDiscoveryReport:
    """Summary of a paginated discovery run."""
    hits: tuple[AggregatedHit, ...] = ()
    per_source_state: dict[str, _PaginationState] = field(
        default_factory=dict,
    )
    safety_cap_triggered: bool = False
    total_raw_hits: int = 0


async def paginated_discover(
    query: str,
    *,
    topic: str,
    repo_root: Path,
    enabled_sources: list[str] | None = None,
    params: RetrievalParams | None = None,
    timeout: float = 120.0,
) -> PaginatedDiscoveryReport:
    """Drive each enabled source through its full pagination loop.
    Per-source cursor state is persisted to disk so an interrupt
    can resume. Honors GLOBAL_SAFETY_CAP across all sources combined."""
    p = params or resolve_params("calibrated")
    registry = _build_registry()
    if enabled_sources is None:
        enabled_sources = [
            name for name, (_, default_en, auth_env) in registry.items()
            if default_en and (
                auth_env is None or os.environ.get(auth_env)
            )
        ]
    per_source_state: dict[str, _PaginationState] = {}
    cap_triggered = False
    raw_per_source: list[list[RawHit]] = []

    async with httpx.AsyncClient(
        timeout=timeout,
        headers={
            "User-Agent": "researka/1.0 (paginated discovery)",
        },
    ) as client:
        for name in enabled_sources:
            if name not in registry:
                continue
            src_client, _, _ = registry[name]
            # Per-source remaining cap = global - what others have used
            used_so_far = sum(
                s.total_returned for s in per_source_state.values()
            )
            remaining = max(0, p.safety_cap - used_so_far)
            if remaining <= 0:
                cap_triggered = True
                break
            hits, state = await paginate_one_source(
                client,
                source_name=name, source_client=src_client,
                topic=topic, query=query,
                safety_cap=min(remaining, p.safety_cap),
                repo_root=repo_root,
            )
            per_source_state[name] = state
            raw_per_source.append(hits)
            if (state.last_error or "") == "safety_cap_reached":
                cap_triggered = True

    aggregated = _merge_and_dedupe(raw_per_source, stats={})
    if len(aggregated) > p.safety_cap:
        cap_triggered = True
        aggregated = aggregated[: p.safety_cap]
    return PaginatedDiscoveryReport(
        hits=tuple(aggregated),
        per_source_state=per_source_state,
        safety_cap_triggered=cap_triggered,
        total_raw_hits=sum(s.total_returned for s in per_source_state.values()),
    )


def clear_cursor_state(
    *, topic: str, repo_root: Path, source: str | None = None,
) -> int:
    """Delete cursor state for a topic (optionally narrowed to a
    single source). Returns count deleted. Used by `--restart`
    flag in seed_topic_corpus."""
    d = _state_dir(repo_root)
    pattern = (
        f"{topic}__{source}__*.json" if source
        else f"{topic}__*.json"
    )
    n = 0
    for p in d.glob(pattern):
        try:
            p.unlink()
            n += 1
        except OSError:
            pass
    return n


__all__ = [
    "PAGEABLE_SOURCES",
    "PaginatedDiscoveryReport",
    "paginate_one_source",
    "paginated_discover",
    "clear_cursor_state",
]
