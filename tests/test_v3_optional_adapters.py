from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import v3_optional_adapters as adapters  # type: ignore[import-not-found]  # noqa: E402


def test_docling_fallback_skips_without_source(tmp_path: Path) -> None:
    result = adapters.write_docling_paper_sections(
        source_uri="",
        parsed_dir=tmp_path,
        paper_id="P1",
        metadata={},
        reason="no_pmcid",
    )
    assert result == {"status": "skipped", "reason": "no_source_uri"}
    assert list(tmp_path.iterdir()) == []


def test_docling_fallback_skips_when_not_installed(tmp_path: Path) -> None:
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"%PDF-1.4\n")
    result = adapters.write_docling_paper_sections(
        source_uri=str(source),
        parsed_dir=tmp_path / "parsed",
        paper_id="P1",
        metadata={},
        reason="fulltext_unavailable",
    )
    assert result["status"] in {"skipped", "failed", "passed"}
    if result["status"] == "skipped":
        assert result["reason"] == "docling_not_installed"


def test_scispacy_normalizer_uses_cache(tmp_path: Path) -> None:
    cache = tmp_path / "biomed_normalization.json"
    first = adapters.normalize_biomed_terms("Rapamycin affects mTOR signaling.", cache)
    second = adapters.normalize_biomed_terms("Rapamycin affects mTOR signaling.", cache)
    assert first == second
    assert second["status"] in {"passed", "fallback"}
    assert json.loads(cache.read_text(encoding="utf-8"))["cache_key"] == first["cache_key"]


def test_structured_output_adapter_reports_schema_errors(tmp_path: Path) -> None:
    result = adapters.validate_structured_output(
        {"passed": "yes"},
        {"passed": "bool", "gates": "dict"},
        tmp_path / "structured_output_contract.json",
    )
    assert result["status"] == "failed"
    assert "type:passed:expected_bool" in result["errors"]
    assert "missing:gates" in result["errors"]


def test_offline_eval_harness_is_no_dependency_smoke(tmp_path: Path) -> None:
    (tmp_path / "full_paper.md").write_text("## Conclusion\nFuture work should test this.\n", encoding="utf-8")
    result = adapters.run_offline_eval_harness(
        tmp_path,
        {
            "passed": True,
            "gates": {
                "raw_pipe_tables": {"status": "advisory"},
                "falsifier_or_next_study": {"status": "passed"},
            },
        },
        tmp_path / "offline_eval_harness.json",
    )
    assert result["status"] == "passed"
    assert set(result["optional_eval_tools"]) == {"deepeval", "dspy", "textgrad"}
