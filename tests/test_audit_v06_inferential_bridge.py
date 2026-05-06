from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import audit_v06_paper as audit  # noqa: E402


def test_q14_passes_when_bridge_absent() -> None:
    ok, msg = audit._check_inferential_bridge_contract("## Discussion\n\nNo bridge.")
    assert ok
    assert "no Inferential Bridge" in msg


def test_q14_accepts_tagged_d1_claim() -> None:
    paper = """
## Inferential Bridge

1. [D1_inferential_bridge | confidence=low] Conserved pathway logic is
   plausible. [mechanism_anchor: r1] [conservation: Canon 2020]
   Existing human signal: none identified.
   Testability: Run prospective validation. [testability: explicit]

## Methods
"""
    ok, msg = audit._check_inferential_bridge_contract(paper)
    assert ok, msg


def test_q14_rejects_missing_conservation_tag() -> None:
    paper = """
## Inferential Bridge

1. [D1_inferential_bridge | confidence=low] Conserved pathway logic is
   plausible. [mechanism_anchor: r1]
   Testability: Run prospective validation. [testability: explicit]
"""
    ok, msg = audit._check_inferential_bridge_contract(paper)
    assert not ok
    assert "conservation" in msg


def test_q14_rejects_new_inferred_numeric() -> None:
    paper = """
## Inferential Bridge

1. [D1_inferential_bridge | confidence=low] The pathway may improve
   outcomes by 12 percent. [mechanism_anchor: r1] [conservation: Canon 2020]
   Testability: Run prospective validation. [testability: explicit]
"""
    ok, msg = audit._check_inferential_bridge_contract(paper)
    assert not ok
    assert "numeric" in msg
