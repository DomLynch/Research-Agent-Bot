from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import apply_consistency_fixes as fixes  # noqa: E402


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
