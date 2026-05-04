"""ChEMBL adapter — drug bioactivity database (EMBL-EBI).

Endpoint: https://www.ebi.ac.uk/chembl/api/data/molecule/search.json
Free, no auth.

Used as a SUPPORTING source — ChEMBL gives drug-name → mechanism
+ target + bioactivity data, useful for the Background section's
mechanism narrative and for cross-checking drug aliases. Not a
primary literature source (no abstracts), but adds drug-pharmacology
provenance that pure-literature sources miss.

Returns RawHit-shaped records where the 'abstract' field contains
a synthetic mechanism summary built from ChEMBL fields.
"""
from __future__ import annotations

from typing import Any

import httpx

from agent.sources._base import clean_text, safe_get_json
from agent.types import RawHit

_CHEMBL_SEARCH_URL = (
    "https://www.ebi.ac.uk/chembl/api/data/molecule/search.json"
)


class ChemblClient:
    name = "chembl"

    async def search(
        self,
        client: httpx.AsyncClient,
        query: str,
        *,
        limit: int,
    ) -> list[RawHit]:
        params = {
            "q": clean_text(query, limit=240),
            "limit": str(max(1, min(limit, 10))),
        }
        data = await safe_get_json(
            client, _CHEMBL_SEARCH_URL, params=params, timeout=15.0,
        )
        if data is None:
            return []
        molecules = data.get("molecules", [])
        return [
            hit for hit in (
                self._parse(m, query=query) for m in molecules
            )
            if hit
        ]

    def _parse(
        self, record: dict[str, Any], *, query: str,
    ) -> RawHit | None:
        mol_id = record.get("molecule_chembl_id")
        pref_name = clean_text(
            record.get("pref_name"), limit=200,
        )
        if not pref_name:
            return None
        # Synthesize abstract from ChEMBL fields (no real abstract).
        max_phase = record.get("max_phase")
        synonyms = record.get("molecule_synonyms", []) or []
        synonym_names = [
            s.get("synonym") for s in synonyms[:5]
            if s.get("synonym")
        ]
        therapeutic_flag = record.get(
            "therapeutic_flag", False,
        )
        first_approval = record.get("first_approval")
        atc = record.get(
            "atc_classifications", [],
        ) or []

        abstract_lines = [
            f"ChEMBL drug-pharmacology entry for {pref_name} "
            f"({mol_id}).",
        ]
        if synonym_names:
            abstract_lines.append(
                f"Synonyms: {', '.join(synonym_names)}."
            )
        if max_phase is not None:
            abstract_lines.append(
                f"Maximum clinical-development phase reached: "
                f"{max_phase}."
            )
        if first_approval:
            abstract_lines.append(
                f"First regulatory approval: {first_approval}."
            )
        if therapeutic_flag:
            abstract_lines.append(
                "Listed as a therapeutic agent in ChEMBL."
            )
        if atc:
            abstract_lines.append(
                f"ATC classification(s): {', '.join(atc[:3])}."
            )
        abstract_lines.append(
            "Source: ChEMBL drug-bioactivity registry (EMBL-EBI). "
            "Use as supporting pharmacology provenance, not as "
            "primary clinical evidence."
        )
        abstract = " ".join(abstract_lines)
        return RawHit(
            source=self.name,
            title=f"{pref_name} ({mol_id}) — ChEMBL drug entry",
            abstract=abstract,
            year=int(first_approval) if first_approval else None,
            url=(
                f"https://www.ebi.ac.uk/chembl/compound_report_card/"
                f"{mol_id}/"
            ),
            doi=None,
            pmid=None,
            nct=None,
            venue="ChEMBL drug registry",
            raw=record,
        )
