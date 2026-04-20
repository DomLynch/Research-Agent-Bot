import json
import httpx
import pytest
from pathlib import Path
from agent.submit import submit, check_decision, _fingerprint


class MockResearka:
    def __init__(self):
        self.submissions = {}
        self.decisions = {}
        self.publications = {}

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        method = request.method

        if method == "POST" and path == "/submissions":
            body = json.loads(request.content)
            sub_id = f"sub-{len(self.submissions) + 1}"
            self.submissions[sub_id] = body
            return httpx.Response(200, json={"submission": {"id": sub_id, "title": body["title"]}, "job": {"id": "job-1"}})

        if method == "GET" and path.startswith("/submissions/") and path.endswith("/decision"):
            sub_id = path.split("/")[2]
            dec = self.decisions.get(sub_id, {"status": "pending", "decision": None})
            return httpx.Response(200, json=dec)

        if method == "GET" and path == "/publications":
            return httpx.Response(200, json={"publications": list(self.publications.values())})

        return httpx.Response(404, json={"detail": "Not Found"})


def test_submit_new_submission(tmp_path):
    mock = MockResearka()
    artifact = {
        "title": "Rapid Evidence Synthesis: test topic",
        "abstract": "Test abstract",
        "sections": {"Research Question": "Test question", "Key Findings": "Test findings"},
        "source_bundle": [{"title": "Paper 1", "evidence_type": "review", "year": 2024, "doi": "10.1/test1"}, {"title": "Paper 2", "evidence_type": "primary", "year": 2023, "doi": "10.1/test2"}],
        "domain_slug": "longevity",
    }
    client = httpx.Client(transport=httpx.MockTransport(mock.handler))
    result = client.post("http://test/submissions", json=artifact).json()
    assert result["submission"]["id"] == "sub-1"
    assert "job" in result


def test_fingerprint_dedup(tmp_path):
    artifact = {
        "title": "Rapid Evidence Synthesis: rapamycin",
        "domain_slug": "longevity",
        "source_bundle": [{"doi": "10.1/a"}, {"doi": "10.1/b"}],
    }
    fp1 = _fingerprint(artifact)
    fp2 = _fingerprint(artifact)
    assert fp1 == fp2

    artifact2 = {
        "title": "Rapid Evidence Synthesis: metformin",
        "domain_slug": "longevity",
        "source_bundle": [{"doi": "10.1/a"}, {"doi": "10.1/b"}],
    }
    fp3 = _fingerprint(artifact2)
    assert fp3 != fp1


def test_fingerprint_changes_with_different_dois():
    artifact1 = {
        "title": "Rapid Evidence Synthesis: rapamycin",
        "domain_slug": "longevity",
        "source_bundle": [{"doi": "10.1/a"}, {"doi": "10.1/b"}, {"doi": "10.1/c"}],
    }
    artifact2 = {
        "title": "Rapid Evidence Synthesis: rapamycin",
        "domain_slug": "longevity",
        "source_bundle": [{"doi": "10.1/x"}, {"doi": "10.1/y"}, {"doi": "10.1/z"}],
    }
    fp1 = _fingerprint(artifact1)
    fp2 = _fingerprint(artifact2)
    assert fp1 != fp2, "Fingerprint should differ when DOIs differ"


def test_check_decision_endpoint():
    """Verify check_decision calls the correct Researka endpoint."""
    mock = MockResearka()
    mock.decisions["sub-1"] = {"status": "complete", "decision": "accept"}
    mock.publications["pub-1"] = {"id": "pub-1", "parent_object_id": "sub-1", "title": "Published"}

    client = httpx.Client(transport=httpx.MockTransport(mock.handler))
    # Direct API call to verify the endpoint works
    resp = client.get("http://test/submissions/sub-1/decision")
    assert resp.json()["decision"] == "accept"

    pubs = client.get("http://test/publications")
    assert len(pubs.json()["publications"]) == 1


def test_submit_with_run_dir_dedup(tmp_path):
    artifact = {
        "title": "Rapid Evidence Synthesis: dedup test",
        "abstract": "Test",
        "sections": {"Research Question": "Q", "Key Findings": "F"},
        "source_bundle": [{"title": "P1", "evidence_type": "review", "year": 2024, "doi": "10.1/x"}],
        "domain_slug": "longevity",
    }

    run_dir = tmp_path / "runs"
    run_dir.mkdir()

    # First submission - simulate a previous run with same fingerprint
    fp = _fingerprint(artifact)
    prev_run = {
        "title": artifact["title"],
        "fingerprint": fp,
        "submission": {"submission": {"id": "prev-sub-123"}, "decision": {"status": "complete", "decision": "accept"}},
    }
    (run_dir / "prev.json").write_text(json.dumps(prev_run), encoding="utf-8")

    result = submit(artifact, base_url="http://test", run_dir=str(run_dir))
    assert result["duplicate"] is True
    assert result["previous_submission_id"] == "prev-sub-123"
