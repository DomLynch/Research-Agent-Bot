"""Fix #41-44 — depth quality gates for the audit.

The grok-smart run hit AAA mechanically while delivering a 310-word
Discussion + 525-word Cross-Domain Synthesis (desk-reject territory).
The fat aaa-real2 baseline had 1,048 + 1,172 words. AAA verifies
integrity; these new gates verify depth."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import audit_v06_paper as audit  # noqa: E402


def _build_paper(
    *,
    discussion_words: int = 1000,
    cross_domain_words: int = 1000,
    intro_words: int = 1000,
    methods_words: int = 1000,
) -> str:
    """Synthetic paper with controllable section sizes."""
    fluff = "word " * 100  # 100 words per chunk
    sections = [
        "## Abstract\n\n" + fluff[:200],
        "## Introduction\n\n" + ("word " * intro_words),
        "## Background\n\n" + ("word " * 500),
        "## Methods\n\n" + ("word " * methods_words),
        "## Results\n\n" + ("word " * 1500),
        "## Cross-Domain Synthesis\n\n" + ("word " * cross_domain_words),
        "## Discussion\n\n" + ("word " * discussion_words),
        "## Limitations\n\n" + ("word " * 500),
        "## Conclusion\n\n" + ("word " * 300),
        "## References\n\n- entry",
    ]
    return "\n\n".join(sections)


# ============ Fix #41 — Q11 Discussion depth ===========================


def test_q11_passes_when_discussion_at_floor() -> None:
    """Discussion ≥800 words → Q11 PASS."""
    paper = _build_paper(discussion_words=800)
    ok, msg = audit._check_discussion_depth(paper)
    assert ok is True
    assert "≥800" in msg


def test_q11_passes_when_discussion_well_above_floor() -> None:
    """Discussion 1500 words → Q11 PASS."""
    paper = _build_paper(discussion_words=1500)
    ok, _msg = audit._check_discussion_depth(paper)
    assert ok is True


def test_q11_fails_when_discussion_anemic() -> None:
    """Discussion 310 words (the actual grok-smart regression)
    → Q11 FAIL."""
    paper = _build_paper(discussion_words=310)
    ok, msg = audit._check_discussion_depth(paper)
    assert ok is False
    assert "310" in msg


def test_q11_fails_when_no_discussion_section() -> None:
    paper = "## Abstract\n\nfoo.\n\n## References\n\nbar.\n"
    ok, msg = audit._check_discussion_depth(paper)
    assert ok is False
    assert "not found" in msg


# ============ Fix #42 — Q12 Cross-Domain depth =========================


def test_q12_passes_when_cross_domain_at_floor() -> None:
    paper = _build_paper(cross_domain_words=800)
    ok, _msg = audit._check_cross_domain_depth(paper)
    assert ok is True


def test_q12_fails_when_cross_domain_anemic() -> None:
    """Cross-Domain 525 words (actual grok-smart regression) → FAIL."""
    paper = _build_paper(cross_domain_words=525)
    ok, msg = audit._check_cross_domain_depth(paper)
    assert ok is False
    assert "525" in msg


def test_q12_fails_when_no_cross_domain_section() -> None:
    paper = "## Discussion\n\nfoo.\n\n## References\n\nbar.\n"
    ok, msg = audit._check_cross_domain_depth(paper)
    assert ok is False
    assert "not found" in msg


# ============ Fix #43 — Q13 analytical ratio ==========================


def test_q13_passes_when_analytical_ratio_at_15pct() -> None:
    """Discussion 1000 + Cross-Domain 1000 = 2000 / 13000 ≈ 15.4%."""
    paper = _build_paper(
        discussion_words=1000, cross_domain_words=1000,
        intro_words=500, methods_words=1000,
    )
    ok, msg = audit._check_analytical_ratio(paper)
    assert ok is True
    assert "%" in msg


def test_q13_fails_when_analytical_ratio_below_15pct() -> None:
    """Discussion 310 + Cross-Domain 525 = 835 in 12k paper ≈ 7%."""
    paper = _build_paper(
        discussion_words=310, cross_domain_words=525,
        intro_words=2000, methods_words=2000,
    )
    ok, msg = audit._check_analytical_ratio(paper)
    assert ok is False
    assert "≥15%" in msg


# ============ Fix #44 — Q10 adaptive hedge density =====================


def test_q10_threshold_is_4_when_corpus_unambiguous(
    monkeypatch, tmp_path,
) -> None:
    """Q10 threshold reverts to 4 when the corpus has decisive
    effect_directions across most receipts."""
    qdir = tmp_path / "qc"
    qdir.mkdir()
    import json as _json
    # 3 receipts, each with high-conf claims of `direction=positive`
    for i in range(3):
        (qdir / f"P{i}.quant_claims.json").write_text(_json.dumps({
            "claims": [
                {"binding_confidence": "high", "direction": "positive"}
                for _ in range(5)
            ],
        }))
    monkeypatch.setattr(audit, "QUANT_DIR", qdir)
    assert audit._adaptive_hedge_threshold() == 4


def test_q10_threshold_is_6_when_corpus_mixed_uncertain(
    monkeypatch, tmp_path,
) -> None:
    """Q10 threshold becomes 6 when >50% of receipts have mostly
    mixed/unclear/null claim directions."""
    qdir = tmp_path / "qc"
    qdir.mkdir()
    import json as _json
    # 3 receipts: 2 mixed-dominant, 1 positive-dominant → 67% uncertain
    for i in range(2):
        (qdir / f"M{i}.quant_claims.json").write_text(_json.dumps({
            "claims": [
                {"binding_confidence": "high", "direction": "mixed"}
                for _ in range(5)
            ],
        }))
    (qdir / "P.quant_claims.json").write_text(_json.dumps({
        "claims": [
            {"binding_confidence": "high", "direction": "positive"}
            for _ in range(5)
        ],
    }))
    monkeypatch.setattr(audit, "QUANT_DIR", qdir)
    assert audit._adaptive_hedge_threshold() == 6


def test_q10_threshold_falls_back_to_4_when_no_claims(
    monkeypatch, tmp_path,
) -> None:
    """Defensive: empty corpus → ≥4 (backward-compat)."""
    qdir = tmp_path / "empty"
    qdir.mkdir()
    monkeypatch.setattr(audit, "QUANT_DIR", qdir)
    assert audit._adaptive_hedge_threshold() == 4


# ============ End-to-end: catches the grok-smart regression =============


def test_audit_catches_grok_smart_anemic_pattern() -> None:
    """End-to-end: a paper with 310-word Discussion + 525-word
    Cross-Domain (the actual grok-smart numbers) fails Q11 + Q12 +
    Q13 simultaneously. Stage-1 score drops; AAA blocked."""
    paper = _build_paper(discussion_words=310, cross_domain_words=525)
    report = audit.audit(paper)
    failed = [c for c in report["checks"] if not c["passed"]]
    failed_names = {c["name"] for c in failed}
    assert "Q11_discussion_depth" in failed_names
    assert "Q12_cross_domain_depth" in failed_names
    assert "Q13_analytical_ratio" in failed_names
