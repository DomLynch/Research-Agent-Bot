from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import apply_consistency_fixes as fixes  # type: ignore[import-not-found]  # noqa: E402


def test_public_snake_case_labels_normalize_in_body_only() -> None:
    paper = (
        "## Discussion\n\n"
        "The intervention remains a nutritional_supplement with a p_value label.\n\n"
        "## Publication Appendix\n\n"
        "`nutritional_supplement` may remain in machine metadata.\n"
    )
    new_md, n = fixes._normalize_public_snake_case_labels(paper)
    assert n == 2
    assert "nutritional supplement" in new_md
    assert "p-value label" in new_md
    assert "`nutritional_supplement` may remain" in new_md


def test_valid_d1_block_accepts_public_mechanism_anchor_tag() -> None:
    block = (
        "1. [D1_inferential_bridge | confidence=low] Conserved pathway logic. "
        "[mechanism anchor: A 2020] [conservation: B 2021]\n"
        "Testability: Run validation. [testability: explicit]"
    )
    assert fixes._valid_d1_block(block)


def test_lightweight_polish_journalizes_public_counter_terms() -> None:
    paper = (
        "## Cross-Domain Synthesis\n\n"
        "Across the 47 accepted sources, the effect-direction distribution "
        "from SPAR-adjudicated sources was mixed. The corpus's tension matrix "
        "contains 1081 pairwise tensions across the source set, of which 237 "
        "were classified as severe (severity >=3). These non-orthogonal "
        "tensions define the framework.\n\n"
        "## References\n\nDOI: 10.1/example.\n"
    )
    out, log = fixes.apply_lightweight_public_polish(
        paper, manifest={"n_non_orthogonal_tensions": 366},
    )
    assert "accepted sources" not in out
    assert "SPAR-adjudicated sources" not in out
    assert "tension matrix" not in out
    assert "1081 pairwise comparisons" in out
    assert "237 severe comparisons" in out
    assert "366 public cross-study disagreements" in out
    assert "DOI: 10.1/example." in out
    assert any(i["fix_type"] == "public_evidence_term_normalization" for i in log)


def test_lightweight_polish_removes_orphan_table_and_overclaim_language() -> None:
    paper = (
        "## Abstract\n\n"
        "The topic is the most robust non-pharmacological intervention for "
        "extending lifespan across species. Eligible studies were identified "
        "through systematic search.\n\n"
        "## Results\n\n"
        "Table 2 presents per-study endpoint evidence. Endpoints are "
        "summarized in Table 2.\n\n"
        "## References\n\n"
        "- Smith 2024.\n"
    )
    out, log = fixes.apply_lightweight_public_polish(paper)
    assert "most robust non-pharmacological intervention" not in out
    assert "extending lifespan across species" not in out
    assert "one of the most extensively studied non-pharmacological intervention" in out
    assert "systematic search" not in out
    assert "structured corpus search" in out
    assert "Table 2" not in out
    assert "The synthesis presents per-study endpoint evidence" in out
    assert "summarized in the evidence synthesis" in out
    assert any(i["fix_type"] == "orphan_table_reference_normalization" for i in log)


def test_lightweight_polish_splits_dense_conclusion_transitions() -> None:
    paper = (
        "## Conclusion\n\n"
        "The final claim remains bounded. The recommended next step is a "
        "prospective study. Until such evidence accrues, clinical use should "
        "remain cautious.\n"
    )
    out, log = fixes.apply_lightweight_public_polish(paper)
    assert "\n\nThe recommended next step is" in out
    assert "\n\nUntil such evidence accrues," in out
    assert any(i["fix_type"] == "conclusion_paragraph_split" for i in log)


def test_lightweight_polish_repairs_surface_contract_defects() -> None:
    paper = (
        "## Results\n\n"
        "| Outcome class | Corpus slice | Strongest signal |\n"
        "|---|---|---|\n"
        "| Cardiometabolic | n=14; claims=20 | mixed |\n\n"
        "### Cardiometabolic Outcomes\n\n"
        "The cardiometabolic evidence base spans 15 curated references.\n\n"
        "Meta-analytic evidence corroborates the glycemic signal.\n\n"
        "## Conclusion\n\n"
        "It separates endpoint-specific evidence from broad treatment claims. "
        "The final interpretation remains bounded.\n\n"
        "## References\n\n"
        "- Smith 2024.\n"
    )
    out, log = fixes.apply_lightweight_public_polish(paper)
    assert "spans 14 curated references" in out
    assert "Meta-analytic evidence corroborates" not in out
    assert "It separates endpoint-specific evidence" not in out
    fix_types = {i["fix_type"] for i in log}
    assert "results_count_claim_alignment" in fix_types
    assert "thin_analytic_paragraph_strip" in fix_types
    assert "conclusion_scope_leak_strip" in fix_types


def test_lightweight_polish_completes_known_background_references() -> None:
    paper = (
        "## Discussion\n\n"
        "ADA 2024 contextualizes the glycemic endpoint.\n\n"
        "## References\n\n"
        "- Smith 2024.\n"
    )
    out, log = fixes.apply_lightweight_public_polish(paper)
    assert "ADA 2024 contextualizes" in out
    assert "### Background References" in out
    assert "- **ADA 2024.**" in out
    assert any(i["fix_type"] == "background_reference_completion" for i in log)


def test_lightweight_polish_completes_near_floor_conclusion_only() -> None:
    near_floor = " ".join(f"conclusion{i}" for i in range(240))
    paper = f"## Conclusion\n\n{near_floor}\n\n## References\n\n- Smith 2024.\n"
    out, log = fixes.apply_lightweight_public_polish(paper)
    assert "broad clinical extrapolation" in out
    assert "gaps.\n\n## References" in out
    assert any(i["fix_type"] == "near_floor_conclusion_completion" for i in log)


def test_lightweight_polish_repairs_heading_glue() -> None:
    out, log = fixes.apply_lightweight_public_polish(
        "## Results\n\n### Cardiometabolic Outcomes\n\nDone.## References\n\n- Smith 2024.\n",
    )
    assert "### Cardiometabolic Outcomes" in out
    assert "Done.\n\n## References" in out
    assert any(i["fix_type"] == "heading_boundary_normalization" for i in log)


def test_lightweight_polish_repairs_accidental_h3_split() -> None:
    out, log = fixes.apply_lightweight_public_polish("## Results\n\n#\n\n## Immune Outcomes\n\nText.\n")
    assert "### Immune Outcomes" in out
    assert "#\n\n## Immune Outcomes" not in out
    assert any(i["fix_type"] == "heading_boundary_normalization" for i in log)
