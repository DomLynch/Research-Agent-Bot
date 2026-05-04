"""RxNorm enrichment — drug normalization (RXCUI + aliases).

Base: https://rxnav.nlm.nih.gov/REST/
No auth. JSON response (append `.json` to the path).

Per NLM's RxNav docs (lhncbc.nlm.nih.gov/RxNav/APIs/RxNormAPIs.html,
fetched 2026-05-04), no license is needed for the standard RxNorm
endpoints. Use cases for Researka:

1. Topic-pack alias auto-population — given a drug name like "aspirin",
   pull all branded names + synonyms from RxNorm so we don't manually
   maintain `aliases = [...]` in topic_packs/<topic>.toml.

2. Active-arm canonicalization — when synthesizing across multiple
   trials, different drug brand names (e.g. Bayer / Ecotrin / generic
   ASA) all collapse to the same RXCUI for active-arm matching.

3. Disambiguation — RxNorm's RXCUI is the medical-vocabulary canonical
   ID; no risk of "atorvastatin" vs "Lipitor" being treated as separate
   compounds in the claim graph.

This client is for offline/build-time use (TOML expansion, vocab seed),
not the per-run discovery loop.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import httpx

_RXNAV_BASE = "https://rxnav.nlm.nih.gov/REST"


@dataclass(frozen=True, slots=True)
class DrugConcept:
    """All canonical names + brand variants for one RXCUI."""
    rxcui: str
    canonical_name: str
    brand_names: tuple[str, ...] = field(default_factory=tuple)
    synonyms: tuple[str, ...] = field(default_factory=tuple)
    ingredients: tuple[str, ...] = field(default_factory=tuple)


class RxNormClient:
    """Resolve a drug name to RxNorm RXCUI + all related aliases.

    Usage:
        client = RxNormClient()
        async with httpx.AsyncClient() as h:
            concept = await client.lookup(h, "aspirin")
            print(concept.brand_names)  # → ('Bayer Aspirin', 'Ecotrin', ...)
    """

    name = "rxnorm"

    async def lookup(
        self,
        client: httpx.AsyncClient,
        drug_name: str,
    ) -> DrugConcept | None:
        """Find RXCUI by name then fetch all related concepts.
        Returns None if RxNorm doesn't recognize the name."""
        rxcui = await self._find_rxcui(client, drug_name)
        if rxcui is None:
            return None
        return await self._fetch_related(client, rxcui, drug_name)

    async def _find_rxcui(
        self, client: httpx.AsyncClient, name: str,
    ) -> str | None:
        url = f"{_RXNAV_BASE}/rxcui.json"
        try:
            response = await client.get(
                url, params={"name": name}, timeout=15.0,
            )
            if response.status_code != 200:
                return None
            data = response.json()
        except (httpx.HTTPError, ValueError):
            return None
        ids = (
            data.get("idGroup", {}).get("rxnormId", []) or []
        )
        return str(ids[0]) if ids else None

    async def _fetch_related(
        self,
        client: httpx.AsyncClient,
        rxcui: str,
        canonical: str,
    ) -> DrugConcept | None:
        url = f"{_RXNAV_BASE}/rxcui/{rxcui}/allrelated.json"
        try:
            response = await client.get(url, timeout=15.0)
            if response.status_code != 200:
                return None
            data = response.json()
        except (httpx.HTTPError, ValueError):
            return None
        groups = (
            data.get("allRelatedGroup", {}).get("conceptGroup", [])
            or []
        )
        # tty (term type) values:
        #   BN = Brand Name
        #   SY = Synonym
        #   IN = Ingredient
        #   SCD = Semantic Clinical Drug (full description, skip)
        brand_names: list[str] = []
        synonyms: list[str] = []
        ingredients: list[str] = []
        for group in groups:
            tty = group.get("tty", "")
            concepts = group.get("conceptProperties") or []
            names = [
                str(c.get("name", "")).strip()
                for c in concepts
                if c.get("name")
            ]
            if tty == "BN":
                brand_names.extend(names)
            elif tty == "SY":
                synonyms.extend(names)
            elif tty == "IN":
                ingredients.extend(names)
        # Dedupe while preserving order, cap at 50 per category.
        return DrugConcept(
            rxcui=rxcui,
            canonical_name=canonical,
            brand_names=tuple(_unique_first(brand_names)[:50]),
            synonyms=tuple(_unique_first(synonyms)[:50]),
            ingredients=tuple(_unique_first(ingredients)[:50]),
        )


def _unique_first(items: list[str]) -> list[str]:
    """Dedupe preserving first-seen order; case-sensitive equality."""
    seen: set[str] = set()
    out: list[str] = []
    for s in items:
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out
