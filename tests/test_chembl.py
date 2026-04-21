from __future__ import annotations

import httpx

from agent.sources.chembl import ChEMBLClient, _mechanism_excerpt, _molecule_title


def _molecule(chembl_id: str = "CHEMBL1908360", pref_name: str = "Everolimus", first_approval: int = 2009) -> dict:
    return {"molecule_chembl_id": chembl_id, "pref_name": pref_name, "first_approval": first_approval}


def test_molecule_title_pref_name():
    assert _molecule_title(_molecule(pref_name="Rapamycin"), "rapamycin") == "Rapamycin"


def test_mechanism_excerpt_uses_mechanism_and_indications():
    text = _mechanism_excerpt(
        [{"action_type": "INHIBITOR", "mechanism_of_action": "mTOR inhibitor"}],
        [{"efo_term": "renal cell carcinoma"}, {"efo_term": "tuberous sclerosis"}],
        "everolimus",
    )
    assert "mTOR inhibitor" in text
    assert "renal cell carcinoma" in text


def test_search_returns_entries():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/molecule/search.json"):
            return httpx.Response(200, json={"molecules": [_molecule()]})
        if request.url.path.endswith("/mechanism.json"):
            return httpx.Response(200, json={"mechanisms": [{"action_type": "INHIBITOR", "mechanism_of_action": "mTOR inhibitor"}]})
        if request.url.path.endswith("/drug_indication.json"):
            return httpx.Response(200, json={"drug_indications": [{"efo_term": "renal cell carcinoma"}]})
        raise AssertionError(request.url)

    client = ChEMBLClient(transport=httpx.MockTransport(handler))
    results = client.search("everolimus", limit=3)
    assert len(results) == 1
    assert results[0]["source_type"] == "chembl"
    assert results[0]["evidence_type"] == "mechanism"
    assert "mTOR inhibitor" in results[0]["excerpt"]


def test_search_respects_limit():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/molecule/search.json"):
            return httpx.Response(200, json={"molecules": [_molecule(chembl_id=f"CHEMBL{i}") for i in range(5)]})
        if request.url.path.endswith("/mechanism.json"):
            return httpx.Response(200, json={"mechanisms": [{"mechanism_of_action": "mTOR inhibitor"}]})
        if request.url.path.endswith("/drug_indication.json"):
            return httpx.Response(200, json={"drug_indications": []})
        raise AssertionError(request.url)

    client = ChEMBLClient(transport=httpx.MockTransport(handler))
    results = client.search("everolimus", limit=2)
    assert len(results) == 2
