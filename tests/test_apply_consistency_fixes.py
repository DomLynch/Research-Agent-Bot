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
