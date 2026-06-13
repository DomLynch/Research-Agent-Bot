from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import daily_research_paper_submit as submit  # type: ignore[import-not-found]  # noqa: E402


_ROOT_CANDIDATES = [
    Path(os.environ["RESEARKA_PREFLIGHT_QA_ROOT"]) if os.environ.get("RESEARKA_PREFLIGHT_QA_ROOT") else None,
    REPO.parent / "Polish - Research agent",
    Path("/opt/researka-preflight-qa"),
    REPO.parent / "researka-preflight-qa",
]
# Hermetic: the external researka-preflight-qa repo is absent in many checkouts
# (CI, /tmp worktrees). Resolve tolerantly and skip this module's tests rather
# than raising StopIteration at import, which previously halted collection of
# the ENTIRE suite. Set RESEARKA_PREFLIGHT_QA_ROOT to run them.
PREFLIGHT_ROOT = next((path for path in _ROOT_CANDIDATES if path and path.is_dir()), None)
pytestmark = pytest.mark.skipif(
    PREFLIGHT_ROOT is None,
    reason="external researka-preflight-qa repo not present (set RESEARKA_PREFLIGHT_QA_ROOT)",
)


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


def test_payload_adds_reference_bib_citations_to_source_bundle(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RESEARKA_ARTICLE_TYPE_V3", "research_synthesis")
    run = tmp_path / "synthesis-aerobic_exercise-v06-test"
    run.mkdir()
    run.joinpath("full_paper.md").write_text(
        "# Research Synthesis: Aerobic Exercise\n\n"
        "## Abstract\n\nThis may be limited.\n\n"
        "## Methods\n\nReferences include DOI 10.1001/jama.2010.1923.\n\n"
        "## Results\n\nThis may be limited.\n\n"
        "## Discussion\n\nContext only.\n\n"
        "## Limitations\n\nLimited.\n\n"
        "## Conclusion\n\nBounded.\n",
        encoding="utf-8",
    )
    run.joinpath("manifest.json").write_text(
        '{"topic":"aerobic_exercise","receipts":[]}', encoding="utf-8",
    )
    run.joinpath("citation_registry.json").write_text("{}", encoding="utf-8")
    run.joinpath("references.bib").write_text(
        "@misc{context_ref,\n"
        "  title = {Context reference. DOI: 10.1001/jama.2010.1923.},\n"
        "  year = {2010}\n"
        "}\n",
        encoding="utf-8",
    )

    payload = submit.build_payload(run)  # type: ignore[attr-defined]

    assert any(
        row.get("doi") == "10.1001/jama.2010.1923"
        for row in payload["source_bundle"]
    )


def test_final_preflight_hook_cleans_payload_in_enforce_mode(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RESEARKA_PREFLIGHT_QA", "enforce")
    monkeypatch.setenv("RESEARKA_PREFLIGHT_QA_ROOT", str(PREFLIGHT_ROOT))
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


def test_final_preflight_hook_reports_bad_payload_in_enforce_mode(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RESEARKA_PREFLIGHT_QA", "enforce")
    monkeypatch.setenv("RESEARKA_PREFLIGHT_QA_ROOT", str(PREFLIGHT_ROOT))
    run = tmp_path / "run"
    run.mkdir()

    payload, report = submit._run_preflight_qa(  # type: ignore[attr-defined]
        _payload("This may cite DOI 10.9999/missing."),
        run,
    )

    assert payload is not None
    assert report and report["status"] == "pass"
    assert "doi_not_in_source_bundle" in {r["code"] for r in report["advisories"]}
    assert "doi_not_in_source_bundle" in payload["metadata"]["preflight_qa"]["advisory_codes"]


def test_final_preflight_live_mode_is_advisory_only(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RESEARKA_PREFLIGHT_QA", "live")
    monkeypatch.setenv("RESEARKA_PREFLIGHT_QA_ROOT", str(PREFLIGHT_ROOT))
    run = tmp_path / "run"
    run.mkdir()

    payload, report = submit._run_preflight_qa(  # type: ignore[attr-defined]
        _payload("This may cite DOI 10.9999/missing."),
        run,
    )

    assert payload is not None
    assert report and report["status"] == "pass"
    assert "doi_not_in_source_bundle" in {r["code"] for r in report["advisories"]}
    assert "doi_not_in_source_bundle" in payload["metadata"]["preflight_qa"]["advisory_codes"]


def test_final_preflight_hook_missing_tool_reports_without_crashing(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.setenv("RESEARKA_PREFLIGHT_QA", "enforce")
    monkeypatch.setenv("RESEARKA_PREFLIGHT_QA_ROOT", str(tmp_path / "missing"))
    run = tmp_path / "run"
    run.mkdir()

    payload, report = submit._run_preflight_qa(_payload("Body."), run)  # type: ignore[attr-defined]

    assert payload is not None
    assert report and report["status"] == "pass"
    assert "preflight_tool_missing" in {r["code"] for r in report["advisories"]}
    assert "preflight_tool_missing" in payload["metadata"]["preflight_qa"]["advisory_codes"]
