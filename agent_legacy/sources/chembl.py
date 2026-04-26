from __future__ import annotations

from difflib import SequenceMatcher
import html
import re
from typing import Any

import httpx


CHEMBL_BASE = "https://www.ebi.ac.uk/chembl/api/data"
_QUERY_STOPWORDS = {
    "and", "or", "anti", "aging", "anti-aging", "longevity", "healthspan", "effects", "effect",
    "outcomes", "outcome", "clinical", "trial", "trials", "adults", "adult", "human", "humans",
    "studies", "study", "relevance", "evidence", "older", "patients", "patient",
}


def _clean_text(value: Any, *, limit: int = 1600) -> str:
    text = str(value or "")
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    return " ".join(text.split()).strip()[:limit]


def _molecule_title(molecule: dict[str, Any], query: str) -> str:
    return _clean_text(molecule.get("pref_name") or query, limit=300)


def _normalize_name(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", _clean_text(value, limit=240).lower())


def _query_focus(query: str) -> str:
    tokens = [tok for tok in re.sub(r"[^a-z0-9]+", " ", str(query or "").lower()).split() if tok and tok not in _QUERY_STOPWORDS]
    if not tokens:
        return _clean_text(query, limit=120)
    return max(tokens, key=len)


def _match_score(query: str, molecule: dict[str, Any]) -> float:
    focus = _normalize_name(query)
    title = _normalize_name(_molecule_title(molecule, query))
    if not focus or not title:
        return 0.0
    if focus == title:
        return 1.0
    if focus in title or title in focus:
        return 0.94
    return SequenceMatcher(None, focus, title).ratio()


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

    def _search_molecules(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
        return self._get("molecule/search.json", q=_clean_text(query, limit=120), limit=max(1, min(limit, 20))).get("molecules", [])

    def resolve(self, query: str) -> dict[str, Any] | None:
        focus = _query_focus(query)
        molecules = self._search_molecules(focus, limit=10)
        best: dict[str, Any] | None = None
        best_score = 0.0
        for molecule in molecules:
            score = _match_score(focus, molecule)
            if score > best_score:
                best = molecule
                best_score = score
        if not best or best_score < 0.88:
            return None
        return {
            "chembl_id": _clean_text(best.get("molecule_chembl_id"), limit=40),
            "canonical_name": _molecule_title(best, focus),
            "confidence": round(best_score, 3),
        }

    def search(self, query: str, *, limit: int = 4) -> list[dict[str, Any]]:
        focus = _query_focus(query)
        molecules = self._search_molecules(focus, limit=max(1, min(limit * 3, 20)))
        entries: list[dict[str, Any]] = []
        ranked = sorted(
            ((molecule, _match_score(focus, molecule)) for molecule in molecules),
            key=lambda item: item[1],
            reverse=True,
        )
        if not ranked or ranked[0][1] < 0.88:
            return []
        for molecule in molecules:
            score = _match_score(focus, molecule)
            if score < 0.88:
                continue
            chembl_id = _clean_text(molecule.get("molecule_chembl_id"), limit=40)
            title = _molecule_title(molecule, focus)
            if not chembl_id or not title:
                continue
            mechanisms = self._get("mechanism.json", molecule_chembl_id=chembl_id, limit=3).get("mechanisms", [])
            indications = self._get("drug_indication.json", molecule_chembl_id=chembl_id, limit=3).get("drug_indications", [])
            excerpt = _mechanism_excerpt(mechanisms, indications, focus)
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
