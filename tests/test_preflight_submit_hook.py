from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import daily_research_paper_submit as submit  # type: ignore[import-not-found]  # noqa: E402


def _payload(body: str) -> dict:
    return {
        "title": "Research Synthesis",
        "abstract": "This may be limited.",
        "artifact_type": "research_paper",
        "article_type": "research_synthesis",
        "body_markdown": body,
        "sections": {"Abstract": "This may be limited."},
        "source_bundle": [{"title": "Limited source", "doi": "10.1000/abc", "excerpt": "limited"}],
        "author_agent_id": "agent-v3-full-paper",
        "metadata": {"source_citation_hash": "sha256:sources", "content_hash": "sha256:old"},
    }


def test_final_preflight_hook_cleans_payload_in_enforce_mode(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RESEARKA_PREFLIGHT_QA", "enforce")
    run = tmp_path / "run"
    run.mkdir()

    payload, report = submit._run_preflight_qa(  # type: ignore[attr-defined]
        _payload("## Result\n\nThis may be limited.\n\nThis may be limited."),
        run,
    )

    assert report and report["status"] == "pass"
    assert payload is not None
    assert payload["body_markdown"].count("This may be limited.") == 1
    assert payload["metadata"]["preflight_qa"]["status"] == "pass"
    assert payload["metadata"]["content_hash"] != "sha256:old"


def test_final_preflight_hook_blocks_bad_payload_in_enforce_mode(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RESEARKA_PREFLIGHT_QA", "enforce")
    run = tmp_path / "run"
    run.mkdir()

    payload, report = submit._run_preflight_qa(  # type: ignore[attr-defined]
        _payload("This may cite DOI 10.9999/missing."),
        run,
    )

    assert payload is None
    assert report and report["status"] == "block"
    assert "doi_not_in_source_bundle" in {r["code"] for r in report["blocked_reasons"]}
