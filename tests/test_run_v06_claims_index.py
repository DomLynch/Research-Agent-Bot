"""Fix #21 follow-up: _build_claims_by_citation high-confidence filter.

Q2 numeric integrity trace uses ONLY high-confidence claims (see
scripts/audit_v06_paper._load_corpus_numerics). Table 5 must do the
same — otherwise it surfaces medium/low-confidence claim numerics
that Q2 then fails to trace, producing a Q2 false-fail."""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import run_v06_synthesis as orch  # noqa: E402
import citation_registry as cr  # noqa: E402


@dataclass(frozen=True)
class _Receipt:
    receipt_id: str
    source_year: int | None = None
    source_doi: str | None = None
    source_pmid: str | None = None
    source_pmcid: str | None = None
    source_journal: str | None = None
    title: str | None = None


def _write_quant_file(parent: Path, paper_id: str, claims: list) -> None:
    parent.mkdir(parents=True, exist_ok=True)
    (parent / f"{paper_id}.quant_claims.json").write_text(json.dumps({
        "paper_id": paper_id, "claims": claims,
    }))


def test_build_claims_by_citation_filters_high_confidence_only(
    tmp_path: Path, monkeypatch,
) -> None:
    """Mixed-confidence claims → only `high` ones surface to Table 5.
    Aligns with Q2's high-confidence-only trace logic."""
    quant_dir = tmp_path / "qc"
    _write_quant_file(quant_dir, "Walton_2019", [
        {"claim_id": "h1", "claim_type": "p_value",
         "raw_text": "p < 0.001", "binding_confidence": "high"},
        {"claim_id": "m1", "claim_type": "percentage",
         "raw_text": "17.7%", "binding_confidence": "medium"},
        {"claim_id": "l1", "claim_type": "p_value",
         "raw_text": "p = 0.31", "binding_confidence": "low"},
    ])
    monkeypatch.setattr(orch, "QUANT_DIR", quant_dir)

    receipts = [_Receipt(receipt_id="Walton_2019", source_year=2019)]
    registry = cr.build_registry(receipts)
    out = orch._build_claims_by_citation(receipts, registry)
    assert "Walton 2019" in out
    claims = out["Walton 2019"]
    # Only the high-confidence claim survives
    assert len(claims) == 1
    assert claims[0]["claim_id"] == "h1"
    assert claims[0]["binding_confidence"] == "high"


def test_build_claims_skips_paper_with_no_high_conf_claims(
    tmp_path: Path, monkeypatch,
) -> None:
    """A paper whose JSON has only medium/low confidence claims
    yields an empty list (NOT skipped from the dict — Table 5
    will simply render zero rows for it)."""
    quant_dir = tmp_path / "qc"
    _write_quant_file(quant_dir, "Walton_2019", [
        {"claim_id": "m1", "claim_type": "percentage",
         "raw_text": "17.7%", "binding_confidence": "medium"},
    ])
    monkeypatch.setattr(orch, "QUANT_DIR", quant_dir)

    receipts = [_Receipt(receipt_id="Walton_2019", source_year=2019)]
    registry = cr.build_registry(receipts)
    out = orch._build_claims_by_citation(receipts, registry)
    assert out["Walton 2019"] == []


def test_post_finalizer_auto_fixable_issues_are_repaired(
    tmp_path: Path, monkeypatch,
) -> None:
    """Finalizer-side mutations get one last deterministic fix pass
    before final verdict sidecars are computed."""
    paper_path = tmp_path / "full_paper.md"
    paper_path.write_text("Bad finalizer numeric 123.")
    issue = SimpleNamespace(auto_fixable=True)

    monkeypatch.setattr(orch, "_strip_rendered_citation_markers", lambda md: md)
    monkeypatch.setattr(
        orch._audit_v06, "_format_summary", lambda _audit: "audit-md",
    )
    monkeypatch.setattr(
        orch._consistency_audit,
        "run_audit",
        lambda *args, **kwargs: [issue],
    )
    monkeypatch.setattr(
        orch._consistency_fixer,
        "apply_fixes",
        lambda *args, **kwargs: (
            "Clean finalizer paper.",
            [{"fix_type": "numeric_role_guard_strip", "n_changes": 1}],
        ),
    )

    fixed, log = orch._repair_post_finalizer_auto_fixables(
        paper_path.read_text(),
        {"topic": "cardio"},
        paper_path,
        lambda _md: {"checks": []},
        quant_claims_dir=tmp_path / "quant_claims",
    )

    assert fixed == "Clean finalizer paper."
    assert paper_path.read_text() == "Clean finalizer paper."
    assert log[0]["fix_type"] == "numeric_role_guard_strip"
    assert (tmp_path / "full_paper.post_finalizer_fixed_log.json").is_file()


def test_build_claims_handles_missing_quant_file(
    tmp_path: Path, monkeypatch,
) -> None:
    """A receipt without a corresponding quant_claims file is
    silently skipped — defensive."""
    quant_dir = tmp_path / "qc"
    quant_dir.mkdir()
    monkeypatch.setattr(orch, "QUANT_DIR", quant_dir)

    receipts = [_Receipt(receipt_id="MissingPaper_2020", source_year=2020)]
    registry = cr.build_registry(receipts)
    out = orch._build_claims_by_citation(receipts, registry)
    # Receipt skipped because no JSON found → not in dict
    assert "MissingPaper 2020" not in out
