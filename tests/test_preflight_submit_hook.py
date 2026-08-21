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
requires_preflight = pytest.mark.skipif(
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


def test_payload_source_bundle_excludes_cited_only_references(tmp_path: Path, monkeypatch) -> None:
    """source_bundle is the RETAINED/on-topic source set (== receipts), so a
    cited external reference that is NOT a retained source must NOT be padded
    into it or retain an outgoing locator — otherwise the public surface certifies more "sources on topic"
    than the evidence base has (the 13-receipts-but-22-bundle mismatch). Such
    cited references remain in the body's ## References, not this count."""
    monkeypatch.setenv("RESEARKA_ARTICLE_TYPE_V3", "research_synthesis")
    run = tmp_path / "synthesis-aerobic_exercise-v06-test"
    run.mkdir()
    run.joinpath("full_paper.md").write_text(
        "# Research Synthesis: Aerobic Exercise\n\n"
        "## Abstract\n\nThis may be limited.\n\n"
        "## Methods\n\nReferences include DOI 10.1001/jama.2010.1923, "
        "https://doi.org/10.1001/jama.2010.1923, and https://pubmed.ncbi.nlm.nih.gov/99999999/.\n\n"
        "## Results\n\nThis may be limited.\n\n"
        "## Discussion\n\nContext only.\n\n"
        "## Limitations\n\nLimited.\n\n"
        "## Conclusion\n\nBounded.\n",
        encoding="utf-8",
    )
    run.joinpath("manifest.json").write_text(
        '{"topic":"aerobic_exercise","receipts":[],"n_receipts":0}', encoding="utf-8",
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

    # cited-only reference is NOT counted as a retained source; bundle stays
    # equal to the (here zero) receipt set.
    assert not any(
        row.get("doi") == "10.1001/jama.2010.1923"
        for row in payload["source_bundle"]
    )
    assert len(payload["source_bundle"]) == 0
    assert "10.1001/jama.2010.1923" not in payload["body_markdown"]
    assert "99999999" not in payload["body_markdown"]


@requires_preflight
def test_final_preflight_hook_cleans_payload_in_enforce_mode(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RESEARKA_PREFLIGHT_QA", "enforce")
    monkeypatch.setenv("RESEARKA_PREFLIGHT_QA_ROOT", str(PREFLIGHT_ROOT))
    run = tmp_path / "run"
    run.mkdir()

    original = _payload("## Abstract\n\nThis may be limited.\n\nThis may be limited.\n\n## Result\n\nBounded.")
    original["abstract"] = "This may be limited. This may be limited."
    payload, report = submit._run_preflight_qa(original, run)  # type: ignore[attr-defined]

    assert report and report["status"] == "pass"
    assert payload is not None
    assert payload["body_markdown"].count("This may be limited.") == 1
    assert payload["abstract"] == payload["sections"]["Abstract"]
    assert payload["metadata"]["preflight_qa"]["status"] == "pass"
    assert payload["metadata"]["content_hash"] != "sha256:old"
    persisted = submit._read_json(run / "researka_preflight_cleaned_payload.json")  # type: ignore[attr-defined]
    assert persisted["abstract"] == payload["abstract"]
    assert report["cleaned_hash"] == payload["metadata"]["submission_payload_hash"]


@requires_preflight
def test_final_preflight_hook_blocks_bad_payload_in_enforce_mode(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RESEARKA_PREFLIGHT_QA", "enforce")
    monkeypatch.setenv("RESEARKA_PREFLIGHT_QA_ROOT", str(PREFLIGHT_ROOT))
    run = tmp_path / "run"
    run.mkdir()

    payload, report = submit._run_preflight_qa(  # type: ignore[attr-defined]
        _payload("This may cite DOI 10.9999/missing."),
        run,
    )

    assert payload is None
    assert report and report["status"] == "blocked"
    assert "doi_not_in_source_bundle" in {r["code"] for r in report["advisories"]}
    assert report["blocked_reasons"] == ["doi_not_in_source_bundle"]
    assert submit._read_json(run / "researka_preflight_report.json")["status"] == "blocked"  # type: ignore[attr-defined]


@requires_preflight
def test_final_preflight_live_mode_blocks_critical_advisory(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RESEARKA_PREFLIGHT_QA", "live")
    monkeypatch.setenv("RESEARKA_PREFLIGHT_QA_ROOT", str(PREFLIGHT_ROOT))
    run = tmp_path / "run"
    run.mkdir()

    payload, report = submit._run_preflight_qa(  # type: ignore[attr-defined]
        _payload("This may cite DOI 10.9999/missing."),
        run,
    )

    assert payload is None
    assert report and report["status"] == "blocked"
    assert "doi_not_in_source_bundle" in {r["code"] for r in report["advisories"]}
    assert report["blocked_reasons"] == ["doi_not_in_source_bundle"]


def test_payload_canonicalizes_nested_source_locator(tmp_path: Path, monkeypatch) -> None:
    doi = "10.1002/14651858.cd016141"
    parenthetical_doi = "10.1000/foo(bar)"
    run = tmp_path / "synthesis-metformin-v06-test"
    run.mkdir()
    run.joinpath("full_paper.md").write_text(
        "Devall 2026 [bundle:1] reported the result "
        f"[exact source: http://doi.org/10.1002/14651858 [exact source: http://doi.org/{doi}]. CD016141]. "
        f"[kept](http://doi.org/{parenthetical_doi}) and [drop](https://doi.org/10.1000/drop).",
        encoding="utf-8",
    )
    run.joinpath("manifest.json").write_text('{"topic":"metformin"}', encoding="utf-8")
    monkeypatch.setattr(submit, "_source_bundle", lambda *_args, **_kwargs: [{"doi": doi}, {"doi": parenthetical_doi}])

    cleaned = submit.build_payload(run)["body_markdown"]  # type: ignore[attr-defined]

    assert cleaned.count(f"[exact source: https://doi.org/{doi}]") == 1
    assert "http://doi.org/10.1002/14651858 [exact source:" not in cleaned
    assert f"[kept](https://doi.org/{parenthetical_doi})" in cleaned
    assert "10.1000/drop" not in cleaned
    assert "[drop]()" not in cleaned
    assert submit.payload_revision_ask_satisfied(
        run, "Every DOI/PMID cited in the manuscript must appear in the source bundle; missing: doi:10.1002/14651858."
    )
    assert not submit.payload_revision_ask_satisfied(
        run, "Every DOI cited must appear in the source bundle and include authoritative evidence text."
    )
    assert not submit.payload_revision_ask_satisfied(
        run, "Every DOI cited must appear in the source bundle and include the source abstract."
    )
    assert not submit.payload_revision_ask_satisfied(
        run, "Every DOI cited must appear in the source bundle, and unsupported claims must be removed."
    )
    assert not submit.payload_revision_ask_satisfied(
        run, "Every DOI cited must appear in the source bundle; plus unsupported claims must be removed."
    )


def test_final_preflight_hook_missing_tool_blocks_enforce_mode(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.setenv("RESEARKA_PREFLIGHT_QA", "enforce")
    monkeypatch.setenv("RESEARKA_PREFLIGHT_QA_ROOT", str(tmp_path / "missing"))
    run = tmp_path / "run"
    run.mkdir()

    payload, report = submit._run_preflight_qa(_payload("Body."), run)  # type: ignore[attr-defined]

    assert payload is None
    assert report and report["status"] == "blocked"
    assert report["blocked_reasons"] == ["preflight_tool_missing"]
    assert "preflight_tool_missing" in {r["code"] for r in report["advisories"]}
