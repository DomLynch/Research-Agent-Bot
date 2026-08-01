from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import paper_audit_pack as pap  # type: ignore[import-not-found]  # noqa: E402

_REGISTRY = {
    "r1": {"reference_id": "R01", "body_citation": "Bitto 2016", "source_doi": "10.7554/eLife.16351", "source_year": 2016},
    "r2": {"reference_id": "R02", "body_citation": "Smith 2020", "source_pmid": "12345678", "source_year": 2020},
    "r3": {"reference_id": "R03", "body_citation": "NoId 2019"},  # unresolved (no doi/pmid/pmcid)
}
_GREEN_VERDICT = {"all_green": True, "journal_ready": True, "p1_clean": True, "maturity_level": 5, "maturity_label": "L5"}


def _run(tmp_path: Path, *, verdict: dict[str, Any], registry: dict[str, Any] = _REGISTRY,
         audit: dict[str, Any] | None = None) -> Path:
    run = tmp_path / "synthesis-foo-v06-DAILY-2026-05-30T00-00-00Z"
    run.mkdir(parents=True)
    (run / "citation_registry.json").write_text(json.dumps(registry), encoding="utf-8")
    (run / "full_paper.final_verdict.json").write_text(json.dumps(verdict), encoding="utf-8")
    (run / "full_paper.audit.json").write_text(json.dumps(audit or {"p1_pass": True, "score_out_of_10": 9.4}), encoding="utf-8")
    return run


def test_reference_audit_counts_resolved_and_unresolved(tmp_path: Path) -> None:
    pack = pap.compose_audit_pack(_run(tmp_path, verdict=_GREEN_VERDICT), retracted=[])
    assert pack["reference_audit"] == {
        "total": 3, "resolved": 2, "unresolved": 1, "retracted": [],
        "retraction_check_available": True,
    }


def test_all_green_journal_ready_ships(tmp_path: Path) -> None:
    resolved = {key: value for key, value in _REGISTRY.items() if key != "r3"}
    pack = pap.compose_audit_pack(
        _run(tmp_path, verdict=_GREEN_VERDICT, registry=resolved), retracted=[],
    )
    assert pack["ship_recommendation"].startswith("SHIP")


def test_unresolved_reference_blocks_ship(tmp_path: Path) -> None:
    pack = pap.compose_audit_pack(_run(tmp_path, verdict=_GREEN_VERDICT), retracted=[])
    assert pack["ship_recommendation"] == "BLOCK — unresolved references"


def test_unavailable_retraction_check_blocks_ship(tmp_path: Path) -> None:
    resolved = {key: value for key, value in _REGISTRY.items() if key != "r3"}

    def unavailable(_run_dir: Path) -> list[str]:
        raise OSError("offline")

    pack = pap.compose_audit_pack(
        _run(tmp_path, verdict=_GREEN_VERDICT, registry=resolved),
        retracted_fetch=unavailable,
    )
    assert pack["reference_audit"]["retraction_check_available"] is False
    assert pack["ship_recommendation"] == "BLOCK — retraction check unavailable"


def test_retracted_source_blocks_and_is_listed(tmp_path: Path) -> None:
    pack = pap.compose_audit_pack(_run(tmp_path, verdict=_GREEN_VERDICT), retracted=["10.7554/eLife.16351"])
    assert pack["reference_audit"]["retracted"] == ["R01"]
    assert pack["ship_recommendation"] == "BLOCK — cites a retracted source"


def test_not_p1_clean_blocks(tmp_path: Path) -> None:
    pack = pap.compose_audit_pack(_run(tmp_path, verdict={**_GREEN_VERDICT, "p1_clean": False}), retracted=[])
    assert pack["ship_recommendation"].startswith("BLOCK")


def test_below_journal_ready_is_caveat(tmp_path: Path) -> None:
    resolved = {key: value for key, value in _REGISTRY.items() if key != "r3"}
    pack = pap.compose_audit_pack(
        _run(
            tmp_path,
            verdict={**_GREEN_VERDICT, "journal_ready": False},
            registry=resolved,
        ),
        retracted=[],
    )
    assert pack["ship_recommendation"].startswith("CAVEAT")


def test_write_audit_pack_emits_json_and_md(tmp_path: Path) -> None:
    run = _run(tmp_path, verdict=_GREEN_VERDICT)
    out = pap.write_audit_pack(run, retracted=[])
    assert out == run / "paper_audit.json"
    assert (run / "paper_audit.md").is_file()
    pack = json.loads(out.read_text(encoding="utf-8"))
    assert pack["paper_verdict"]["maturity_level"] == 5 and pack["paper_verdict"]["audit_score"] == 9.4
    assert "Paper Audit Pack" in (run / "paper_audit.md").read_text(encoding="utf-8")


def test_missing_sidecars_failsafe(tmp_path: Path) -> None:
    run = tmp_path / "synthesis-empty-v06-DAILY-2026-05-30T00-00-00Z"
    run.mkdir(parents=True)
    pack = pap.compose_audit_pack(run, retracted=[])  # no sidecars at all
    assert pack["reference_audit"]["total"] == 0
    assert pack["ship_recommendation"].startswith("BLOCK")  # nothing green -> block
