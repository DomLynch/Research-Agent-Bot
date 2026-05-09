"""Tests for the Phase 6 template-language detector + CLI gate."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from agent.template_language import (
    DENYLIST_ALWAYS,
    DENYLIST_CONDITIONAL,
    Hit,
    detect_template_language,
    has_blocking_severity,
    hit_to_dict,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
GATE_SCRIPT = REPO_ROOT / "scripts" / "template_language_gate.py"


# ---- Detector unit tests ---------------------------------------------------


def test_detects_generic_research_cliche_with_line_number() -> None:
    text = "Sentence one is fine.\nFurther research is needed here.\nThird line."
    hits = detect_template_language(text)
    assert len(hits) == 1
    h = hits[0]
    assert h.line_number == 2
    assert h.category == "generic_research_cliche"
    assert h.severity == "P2"
    assert "further research is needed" in h.phrase.lower()


def test_detects_unsupported_authority_p1() -> None:
    text = "It is clear that rapamycin works."
    hits = detect_template_language(text)
    assert len(hits) == 1
    assert hits[0].severity == "P1"
    assert hits[0].category == "unsupported_authority"


def test_detects_ai_summary_tell_in_conclusion() -> None:
    text = "In conclusion, we adopt the framework."
    hits = detect_template_language(text)
    assert any(h.category == "ai_summary_tell" for h in hits)


def test_vague_limitation_flagged_when_no_specifics() -> None:
    text = "The evidence base is limited."
    hits = detect_template_language(text)
    assert len(hits) == 1
    assert hits[0].category == "vague_limitation"
    assert hits[0].severity == "P2"


def test_vague_limitation_not_flagged_when_specifics_present() -> None:
    text = "The evidence base is limited to 3 RCTs with n<100 over 12 months."
    hits = detect_template_language(text)
    assert hits == []


def test_specific_recommendation_not_flagged() -> None:
    text = (
        "Future trials should measure arterial stiffness over >=2 years in 200 patients."
    )
    hits = detect_template_language(text)
    assert hits == []


def test_ignores_text_inside_code_fences() -> None:
    text = "```\nfurther research is needed\nit is clear that\n```\nNormal sentence here."
    hits = detect_template_language(text)
    assert hits == []


def test_ignores_text_inside_table_rows() -> None:
    text = "| further research is needed | x |\n| it is clear that | y |"
    hits = detect_template_language(text)
    assert hits == []


def test_ignores_text_after_references_heading() -> None:
    text = (
        "Body content with no hits.\n\n## References\n\n"
        "Further research is needed in this reference text.\n"
        "It is clear that this works."
    )
    hits = detect_template_language(text)
    assert hits == []


def test_ignores_audit_metadata_section() -> None:
    text = (
        "## AI-Use Disclosure\n\n"
        "Further research is needed inside the disclosure.\n"
        "It is clear that this is metadata.\n"
    )
    hits = detect_template_language(text)
    assert hits == []


def test_skip_section_ends_at_next_top_level_heading() -> None:
    text = (
        "## References\n\nFurther research is needed in references (skipped).\n\n"
        "## Appendix\n\nIt is clear that the appendix has prose to flag."
    )
    hits = detect_template_language(text)
    assert len(hits) == 1
    assert hits[0].category == "unsupported_authority"


def test_multiple_hits_across_lines_preserve_line_numbers() -> None:
    text = (
        "Line 1: nothing.\n"
        "Line 2: it is clear that.\n"
        "Line 3: further research is needed.\n"
    )
    hits = detect_template_language(text)
    assert len(hits) == 2
    by_line = {h.line_number: h.category for h in hits}
    assert by_line[2] == "unsupported_authority"
    assert by_line[3] == "generic_research_cliche"


def test_p1_p2_blocking_severity_helper() -> None:
    p1_hit = Hit("x", "unsupported_authority", "P1", 1, "x", "r")
    p2_hit = Hit("x", "vague_limitation", "P2", 1, "x", "r")
    p3_hit = Hit("x", "ai_summary_tell", "P3", 1, "x", "r")  # type: ignore[arg-type]
    assert has_blocking_severity([p1_hit])
    assert has_blocking_severity([p2_hit])
    assert not has_blocking_severity([p3_hit])
    assert not has_blocking_severity([])


def test_hit_to_dict_returns_serializable() -> None:
    h = Hit("phrase", "vague_limitation", "P2", 7, "sent", "reason")
    d = hit_to_dict(h)
    json.dumps(d)  # should not raise
    assert d["line_number"] == 7
    assert d["severity"] == "P2"


def test_denylist_categories_cover_all_required() -> None:
    """Every required category from the brief is present in the denylist."""
    cats = {entry[1] for entry in DENYLIST_ALWAYS} | {
        entry[1] for entry in DENYLIST_CONDITIONAL
    }
    assert cats == {
        "generic_research_cliche",
        "ai_summary_tell",
        "vague_limitation",
        "unsupported_authority",
    }


# ---- CLI tests -------------------------------------------------------------


def _run_gate(input_path: Path, json_out: Path, md_out: Path | None = None) -> tuple[int, str, str]:
    cmd = [sys.executable, str(GATE_SCRIPT), str(input_path), "--json", str(json_out)]
    if md_out is not None:
        cmd += ["--md", str(md_out)]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return proc.returncode, proc.stdout, proc.stderr


def test_cli_clean_paper_exits_zero(tmp_path: Path) -> None:
    paper = tmp_path / "clean.md"
    paper.write_text("Rapamycin extends mouse lifespan by 14% (Harrison 2009).\n")
    rc, _, _ = _run_gate(paper, tmp_path / "out.json")
    assert rc == 0


def test_cli_dirty_paper_exits_one_and_writes_outputs(tmp_path: Path) -> None:
    paper = tmp_path / "dirty.md"
    paper.write_text("It is clear that rapamycin works.\nFurther research is needed.\n")
    json_out = tmp_path / "out.json"
    md_out = tmp_path / "out.md"
    rc, _, _ = _run_gate(paper, json_out, md_out)
    assert rc == 1
    assert json_out.is_file()
    assert md_out.is_file()
    payload = json.loads(json_out.read_text())
    assert payload["summary"]["blocking"] is True
    assert payload["summary"]["total_hits"] == 2
    md_text = md_out.read_text()
    assert "Template-Language Audit" in md_text
    assert "P1" in md_text
    assert "P2" in md_text


def test_cli_missing_input_exits_two(tmp_path: Path) -> None:
    rc, _, stderr = _run_gate(tmp_path / "does_not_exist.md", tmp_path / "out.json")
    assert rc == 2
    assert "not found" in stderr.lower()


def test_cli_json_payload_shape(tmp_path: Path) -> None:
    paper = tmp_path / "p.md"
    paper.write_text("It is clear that this fires.\n")
    json_out = tmp_path / "out.json"
    _run_gate(paper, json_out)
    payload = json.loads(json_out.read_text())
    assert payload["source"].endswith("p.md")
    assert "hits" in payload and "summary" in payload
    assert isinstance(payload["hits"], list)
    assert payload["hits"][0]["category"] == "unsupported_authority"
