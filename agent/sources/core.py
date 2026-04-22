from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import httpx


CORE_URL = "https://api.core.ac.uk/v3/works"


def _clean(value: Any, *, limit: int = 20000) -> str:
    return " ".join(str(value or "").split()).strip()[:limit]


class COREClient:
    def __init__(
        self,
        *,
        cache_dir: str | Path,
        timeout_sec: float = 12.0,
        transport: httpx.BaseTransport | None = None,
        api_key: str | None = None,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.api_key = api_key or os.getenv("CORE_API_KEY", "")
        self.client = httpx.Client(
            timeout=timeout_sec,
            transport=transport,
            headers={
                "User-Agent": "researka-reference-agent/0.1",
                **({"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}),
            },
        )

    def _cache_path(self, doi: str) -> Path:
        digest = hashlib.sha256(doi.lower().encode("utf-8")).hexdigest()
        return self.cache_dir / f"{digest}.json"

    def fetch_by_doi(self, doi: str | None) -> dict[str, Any] | None:
        doi = _clean(doi, limit=300)
        if not doi or not self.api_key:
            return None
        cache_path = self._cache_path(doi)
        if cache_path.exists():
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            return payload if payload.get("found") else None

        response = self.client.get(CORE_URL, params={"q": f"doi:{doi}", "limit": 1})
        if response.status_code in {401, 403, 404}:
            cache_path.write_text(json.dumps({"found": False, "reason": f"http_{response.status_code}"}), encoding="utf-8")
            return None
        response.raise_for_status()
        results = response.json().get("results") or []
        if not results:
            cache_path.write_text(json.dumps({"found": False, "reason": "no_results"}), encoding="utf-8")
            return None
        first = results[0]
        text = _clean(first.get("fullText"))
        download_url = _clean(first.get("downloadUrl"), limit=600)
        if not text and not download_url:
            cache_path.write_text(json.dumps({"found": False, "reason": "empty"}), encoding="utf-8")
            return None
        payload = {
            "found": True,
            "text": text,
            "sections": {},
            "download_url": download_url,
        }
        cache_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload
