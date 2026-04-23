from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import httpx


DOAJ_SEARCH_URL = "https://doaj.org/api/search/journals/"


def _clean(value: Any, *, limit: int = 300) -> str:
    return " ".join(str(value or "").split()).strip()[:limit]


def _norm_title(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", _clean(value, limit=240).lower())


class DOAJClient:
    def __init__(
        self,
        *,
        cache_dir: str | Path,
        timeout_sec: float = 12.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.client = httpx.Client(
            timeout=timeout_sec,
            transport=transport,
            headers={"User-Agent": "researka-reference-agent/0.1"},
        )

    def _cache_path(self, journal_title: str) -> Path:
        digest = hashlib.sha256(_norm_title(journal_title).encode("utf-8")).hexdigest()
        return self.cache_dir / f"{digest}.json"

    def lookup_journal(self, journal_title: str | None) -> dict[str, Any] | None:
        journal_title = _clean(journal_title, limit=240)
        if not journal_title:
            return None
        cache_path = self._cache_path(journal_title)
        if cache_path.exists():
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            return payload if payload.get("indexed") else None
        try:
            response = self.client.get(f"{DOAJ_SEARCH_URL}{journal_title}", params={"pageSize": 5})
            if response.status_code != 200:
                cache_path.write_text(json.dumps({"indexed": False, "reason": f"http_{response.status_code}"}), encoding="utf-8")
                return None
            results = response.json().get("results") or []
        except (httpx.HTTPError, ValueError):
            return None
        target = _norm_title(journal_title)
        payload: dict[str, Any] | None = None
        for result in results:
            bibjson = result.get("bibjson") or {}
            title = _clean(bibjson.get("title"), limit=240)
            if not title or _norm_title(title) != target:
                continue
            license_block = (bibjson.get("license") or [{}])[0] if isinstance(bibjson.get("license"), list) else {}
            payload = {
                "indexed": True,
                "title": title,
                "publisher": _clean(bibjson.get("publisher"), limit=200),
                "license": _clean(license_block.get("type"), limit=80),
                "seal": bool(bibjson.get("doaj_seal")),
            }
            break
        cache_path.write_text(json.dumps(payload or {"indexed": False, "reason": "no_match"}, indent=2), encoding="utf-8")
        return payload

    def annotate_entries(self, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        annotated: list[dict[str, Any]] = []
        for entry in entries:
            cloned = dict(entry)
            meta = self.lookup_journal(cloned.get("journal"))
            if meta:
                cloned["journal_quality"] = "doaj-indexed"
                cloned["doaj_indexed"] = True
                cloned["doaj_meta"] = meta
            annotated.append(cloned)
        return annotated
