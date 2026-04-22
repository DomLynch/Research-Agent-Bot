from __future__ import annotations

from typing import Any

import httpx

UNPAYWALL_API = "https://api.unpaywall.org/v2"


class UnpaywallAdapter:
    def __init__(self, *, timeout_sec: float = 12.0, transport: httpx.BaseTransport | None = None) -> None:
        self.client = httpx.Client(
            timeout=timeout_sec,
            transport=transport,
            headers={"User-Agent": "researka-reference-agent/0.1"},
        )

    def resolve(self, doi: str) -> dict[str, Any] | None:
        if not doi:
            return None
        try:
            response = self.client.get(f"{UNPAYWALL_API}/{doi}", params={"email": "research-agent@researka.org"})
            if response.status_code == 404:
                return None
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError:
            return None
        best = data.get("best_oa_location")
        if not best:
            return None
        return {
            "doi": doi,
            "oa_url": best.get("url"),
            "version": best.get("version"),
            "license": best.get("license"),
            "host_type": best.get("host_type"),
            "is_oa": data.get("is_oa", False),
        }
