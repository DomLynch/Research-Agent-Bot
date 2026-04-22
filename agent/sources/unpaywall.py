from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import httpx


UNPAYWALL_URL = "https://api.unpaywall.org/v2/{doi}"


def _clean(value: Any, *, limit: int = 1200) -> str:
    return " ".join(str(value or "").split()).strip()[:limit]


class UnpaywallClient:
    def __init__(
        self,
        *,
        cache_dir: str | Path,
        timeout_sec: float = 12.0,
        transport: httpx.BaseTransport | None = None,
        email: str = "noreply@researka.org",
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.email = email
        self.client = httpx.Client(
            timeout=timeout_sec,
            transport=transport,
            headers={"User-Agent": "researka-reference-agent/0.1"},
        )

    def _cache_path(self, doi: str) -> Path:
        digest = hashlib.sha256(doi.lower().encode("utf-8")).hexdigest()
        return self.cache_dir / f"{digest}.json"

    def resolve(self, doi: str | None) -> dict[str, Any] | None:
        doi = _clean(doi, limit=300)
        if not doi:
            return None
        cache_path = self._cache_path(doi)
        if cache_path.exists():
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            return payload if payload.get("is_oa") else None

        response = self.client.get(UNPAYWALL_URL.format(doi=doi), params={"email": self.email})
        if response.status_code == 404:
            cache_path.write_text(json.dumps({"is_oa": False, "reason": "not_found"}), encoding="utf-8")
            return None
        response.raise_for_status()
        data = response.json()
        location = data.get("best_oa_location") or {}
        payload = {
            "doi": doi,
            "is_oa": bool(data.get("is_oa")),
            "oa_status": _clean(data.get("oa_status"), limit=40),
            "location_url": _clean(location.get("url"), limit=600),
            "best_pdf_url": _clean(location.get("url_for_pdf"), limit=600),
            "html_url": _clean(location.get("url"), limit=600),
        }
        cache_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload if payload["is_oa"] else None
