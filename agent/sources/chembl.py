from __future__ import annotations

import html
import re
from typing import Any

import httpx


CHEMBL_BASE = "https://www.ebi.ac.uk/chembl/api/data"


def _clean_text(value: Any, *, limit: int = 1600) -> str:
    text = str(value or "")
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    return " ".join(text.split()).strip()[:limit]


def _molecule_title(molecule: dict[str, Any], query: str) -> str:
    return _clean_text(molecule.get("pref_name") or query, limit=300)


def _mechanism_excerpt(mechanisms: list[dict[str, Any]], indications: list[dict[str, Any]], query: str) -> str:
    parts: list[str] = []
    if mechanisms:
        mech = mechanisms[0]
        action = _clean_text(mech.get("action_type"), limit=80)
        moa = _clean_text(mech.get("mechanism_of_action"), limit=220)
        if moa:
            prefix = f"{action.lower()}:" if action else "mechanism:"
            parts.append(f"{prefix} {moa}")
    if indications:
        labels = [_clean_text(item.get("efo_term"), limit=80) for item in indications[:3]]
        labels = [label for label in labels if label]
        if labels:
            parts.append(f"indications: {', '.join(labels)}")
    if not parts:
        parts.append(f"compound evidence for {query}")
    return _clean_text(". ".join(parts))


class ChEMBLClient:
    def __init__(self, *, timeout_sec: float = 12.0, transport: httpx.BaseTransport | None = None) -> None:
        self.client = httpx.Client(timeout=timeout_sec, transport=transport, headers={"User-Agent": "researka-reference-agent/0.1"})

    def _get(self, path: str, **params: Any) -> dict[str, Any]:
        response = self.client.get(f"{CHEMBL_BASE}/{path}", params=params)
        response.raise_for_status()
        return response.json()

    def search(self, query: str, *, limit: int = 4) -> list[dict[str, Any]]:
        molecules = self._get("molecule/search.json", q=_clean_text(query, limit=120), limit=max(1, min(limit * 2, 20))).get("molecules", [])
        entries: list[dict[str, Any]] = []
        for molecule in molecules:
            chembl_id = _clean_text(molecule.get("molecule_chembl_id"), limit=40)
            title = _molecule_title(molecule, query)
            if not chembl_id or not title:
                continue
            mechanisms = self._get("mechanism.json", molecule_chembl_id=chembl_id, limit=3).get("mechanisms", [])
            indications = self._get("drug_indication.json", molecule_chembl_id=chembl_id, limit=3).get("drug_indications", [])
            excerpt = _mechanism_excerpt(mechanisms, indications, query)
            if not excerpt:
                continue
            year = molecule.get("first_approval")
            entries.append(
                {
                    "id": chembl_id,
                    "title": title,
                    "excerpt": excerpt,
                    "url": f"{CHEMBL_BASE}/molecule/{chembl_id}.json",
                    "doi": None,
                    "year": int(year) if isinstance(year, int) else None,
                    "query": _clean_text(query, limit=240),
                    "source_type": "chembl",
                    "evidence_type": "mechanism",
                    "journal": "ChEMBL",
                    "authors": [],
                }
            )
            if len(entries) >= limit:
                break
        return entries
