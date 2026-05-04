"""Tests for scripts/corpus_filter.py — universal off-topic mechanistic filter.

Discriminating tests focused on the conservative-bias contract:
- Off-topic mechanistic noise (TBI / burn wound / stroke neurovascular review)
  should be FLAGGED.
- Clinical RCTs / cohort studies / target-trial emulations should be KEPT.
- Mechanistic papers that ALSO mention clinical outcomes should be KEPT
  (the conservative rescue).
- Empty / non-existent parsed dir → empty set, no crash.
- Topic pack keywords (expected_evidence_slots) protect on-topic papers.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = _REPO_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from corpus_filter import filter_corpus  # noqa: E402


_STATIN_PACK = """\
topic = "statins"
class_ = "hmg_coa_reductase_inhibitor"
aliases = ["statin", "atorvastatin", "rosuvastatin"]
expected_evidence_slots = [
  "human_rcts",
  "human_observational",
  "human_mechanism",
  "preclinical_lifespan",
  "safety_tolerability",
  "primary_prevention",
  "secondary_prevention",
]
special_rules = []
forbidden_verbs_for_protocol_role = []
forbidden_verbs_for_results_role_with_protocol_keywords = []
"""


def _write_paper(
    parsed_dir: Path,
    paper_id: str,
    title: str,
    abstract: str,
) -> None:
    parsed_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "paper_id": paper_id,
        "title": title,
        "sections": {"abstract": abstract},
    }
    (parsed_dir / f"{paper_id}.paper_sections.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


@pytest.fixture
def workspace(tmp_path: Path) -> tuple[Path, Path]:
    """Create a tmp parsed/ dir and a tmp topic_pack toml. Return both paths."""
    parsed = tmp_path / "parsed"
    pack = tmp_path / "statins.toml"
    pack.write_text(_STATIN_PACK, encoding="utf-8")
    return parsed, pack


# --- True positives: off-topic mechanistic noise should be flagged ---------


def test_off_topic_tbi_paper_is_flagged(workspace: tuple[Path, Path]) -> None:
    parsed, pack = workspace
    _write_paper(
        parsed,
        "PMC_TBI_001",
        "The neuroprotective effect of statin in traumatic brain injury",
        "Traumatic brain injury (TBI) is a clinical issue. Statins enhance "
        "outcomes in animal research. We reviewed the literature on statin "
        "use after TBI in animal studies.",
    )
    flagged = filter_corpus(parsed, pack)
    assert "PMC_TBI_001" in flagged


def test_burn_wound_paper_is_flagged(workspace: tuple[Path, Path]) -> None:
    parsed, pack = workspace
    _write_paper(
        parsed,
        "PMC_BURN_001",
        "Effects of rosuvastatin on burn wound healing",
        "Burn injuries cause severe complications. The process of burn wound "
        "recovery is intricate. We investigated rosuvastatin in burn injury.",
    )
    flagged = filter_corpus(parsed, pack)
    assert "PMC_BURN_001" in flagged


# --- Conservative rescue: mechanistic + clinical signal → KEEP -------------


def test_mechanistic_paper_with_rct_signal_is_kept(
    workspace: tuple[Path, Path],
) -> None:
    """An in-vitro / animal paper that ALSO reports a randomized trial result
    must NOT be flagged — conservative bias, false positives are worse."""
    parsed, pack = workspace
    _write_paper(
        parsed,
        "PMC_MIXED_001",
        "Statin in MCF7 breast cancer cells with companion RCT cohort",
        "We tested simvastatin in MCF7 cells. We also report a randomized "
        "controlled trial in 200 women with primary prevention indication "
        "showing reduced cardiovascular mortality.",
    )
    flagged = filter_corpus(parsed, pack)
    assert "PMC_MIXED_001" not in flagged


def test_clinical_rct_paper_is_kept(workspace: tuple[Path, Path]) -> None:
    parsed, pack = workspace
    _write_paper(
        parsed,
        "PMC_RCT_001",
        "STAREE: A Randomized Trial of Statins for Primary Prevention in "
        "Older People",
        "The STAREE trial is a randomized, double-blind, placebo-controlled "
        "trial of atorvastatin for primary prevention of cardiovascular "
        "events in community-dwelling older adults.",
    )
    flagged = filter_corpus(parsed, pack)
    assert "PMC_RCT_001" not in flagged


def test_cohort_observational_paper_is_kept(
    workspace: tuple[Path, Path],
) -> None:
    parsed, pack = workspace
    _write_paper(
        parsed,
        "PMC_OBS_001",
        "Association between statin use and incident cancer in older adults",
        "We conducted a target trial emulation cohort study in healthy older "
        "adults. Statin initiators were compared with non-initiators in a "
        "registry-based observational study showing reduced cancer "
        "incidence.",
    )
    flagged = filter_corpus(parsed, pack)
    assert "PMC_OBS_001" not in flagged


# --- Edge cases -----------------------------------------------------------


def test_empty_parsed_dir_returns_empty_set(
    workspace: tuple[Path, Path],
) -> None:
    parsed, pack = workspace
    parsed.mkdir(parents=True, exist_ok=True)
    flagged = filter_corpus(parsed, pack)
    assert flagged == set()


def test_nonexistent_parsed_dir_returns_empty_set(tmp_path: Path) -> None:
    pack = tmp_path / "statins.toml"
    pack.write_text(_STATIN_PACK, encoding="utf-8")
    flagged = filter_corpus(tmp_path / "does_not_exist", pack)
    assert flagged == set()


def test_malformed_paper_json_is_skipped_not_crashed(
    workspace: tuple[Path, Path],
) -> None:
    parsed, pack = workspace
    parsed.mkdir(parents=True, exist_ok=True)
    (parsed / "BROKEN.paper_sections.json").write_text(
        "{not valid json", encoding="utf-8"
    )
    _write_paper(
        parsed,
        "PMC_TBI_002",
        "Statin in traumatic brain injury",
        "TBI animal study only.",
    )
    flagged = filter_corpus(parsed, pack)
    assert "PMC_TBI_002" in flagged


# --- Universality: no statin-specific code paths --------------------------


def test_filter_works_for_aspirin_pack_with_same_lexicon(
    tmp_path: Path,
) -> None:
    """Same code, different topic pack — universality contract."""
    parsed = tmp_path / "parsed"
    pack = tmp_path / "aspirin.toml"
    pack.write_text(
        'topic = "aspirin"\n'
        'class_ = "salicylate_nsaid"\n'
        'aliases = ["aspirin", "acetylsalicylic acid"]\n'
        'expected_evidence_slots = ["human_rcts", "primary_prevention"]\n'
        'special_rules = []\n'
        'forbidden_verbs_for_protocol_role = []\n'
        'forbidden_verbs_for_results_role_with_protocol_keywords = []\n',
        encoding="utf-8",
    )
    _write_paper(
        parsed,
        "PMC_ASPREE",
        "ASPREE: aspirin for primary prevention in healthy older people",
        "ASPREE was a randomized clinical trial of low-dose aspirin in "
        "older adults for primary prevention of cardiovascular events.",
    )
    _write_paper(
        parsed,
        "PMC_TBI_ASP",
        "Aspirin in traumatic brain injury rodent study",
        "We administered aspirin to rats with TBI in a preclinical mouse "
        "model.",
    )
    flagged = filter_corpus(parsed, pack)
    assert "PMC_ASPREE" not in flagged
    assert "PMC_TBI_ASP" in flagged
