"""Tests for the Phase 4 quality-method schemas (RoB + GRADE) and the
markdown table renderers."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from agent.grade_schema import (
    VALID_CERTAINTY,
    DowngradeAdjustment,
    GradeAssessment,
    UpgradeAdjustment,
    starting_certainty_for_design,
)
from agent.risk_of_bias_schema import (
    DOMAINS_BY_TOOL,
    ROB2_DOMAINS,
    ROBINS_I_DOMAINS,
    SYRCLE_DOMAINS,
    DomainAssessment,
    StudyAssessment,
    assert_studies_unique,
    required_domains_for,
)
from scripts.render_quality_tables import (
    grades_from_json,
    render_grade_table,
    render_rob_table,
    studies_from_json,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
RENDER_SCRIPT = REPO_ROOT / "scripts" / "render_quality_tables.py"


def _all_low(tool: str) -> tuple[DomainAssessment, ...]:
    return tuple(DomainAssessment(d, "low") for d in DOMAINS_BY_TOOL[tool])


# ---- RoB schema tests ------------------------------------------------------


def test_valid_rct_rob2_record() -> None:
    s = StudyAssessment("Moel 2025", "rct", "rob2", _all_low("rob2"), "low")
    assert tuple(s.domain_map().keys()) == ROB2_DOMAINS


def test_valid_observational_robins_i_record() -> None:
    s = StudyAssessment("Kell 2026", "observational", "robins_i",
                        _all_low("robins_i"), "some_concerns")
    assert tuple(s.domain_map().keys()) == ROBINS_I_DOMAINS


def test_valid_animal_syrcle_record() -> None:
    s = StudyAssessment("Harrison 2009", "animal", "syrcle", _all_low("syrcle"), "low")
    assert tuple(s.domain_map().keys()) == SYRCLE_DOMAINS


def test_invalid_domain_rating_raises() -> None:
    with pytest.raises(ValueError, match="invalid rating"):
        DomainAssessment("randomization", "bogus")  # type: ignore[arg-type]


def test_invalid_overall_rating_raises() -> None:
    with pytest.raises(ValueError, match="invalid overall_rating"):
        StudyAssessment("X", "rct", "rob2", _all_low("rob2"),
                        overall_rating="bogus")  # type: ignore[arg-type]


def test_missing_required_domain_raises() -> None:
    partial = (DomainAssessment("randomization", "low"),)
    with pytest.raises(ValueError, match="missing required domain"):
        StudyAssessment("X", "rct", "rob2", partial, "low")


def test_unknown_domain_raises() -> None:
    extra = _all_low("rob2") + (DomainAssessment("bogus", "low"),)
    with pytest.raises(ValueError, match="unknown domain"):
        StudyAssessment("X", "rct", "rob2", extra, "low")


def test_duplicate_domain_raises() -> None:
    dupe = _all_low("rob2") + (DomainAssessment("randomization", "high"),)
    with pytest.raises(ValueError, match="duplicate"):
        StudyAssessment("X", "rct", "rob2", dupe, "low")


def test_invalid_tool_raises() -> None:
    with pytest.raises(ValueError, match="invalid tool"):
        StudyAssessment("X", "rct", "bogus_tool", (), "low")  # type: ignore[arg-type]


def test_invalid_design_raises() -> None:
    with pytest.raises(ValueError, match="invalid design"):
        StudyAssessment("X", "bogus_design", "rob2",  # type: ignore[arg-type]
                        _all_low("rob2"), "low")


def test_empty_study_id_raises() -> None:
    with pytest.raises(ValueError, match="study_id"):
        StudyAssessment("", "rct", "rob2", _all_low("rob2"), "low")


def test_required_domains_for_helper() -> None:
    assert required_domains_for("rob2") == ROB2_DOMAINS
    assert required_domains_for("robins_i") == ROBINS_I_DOMAINS
    assert required_domains_for("syrcle") == SYRCLE_DOMAINS
    with pytest.raises(ValueError):
        required_domains_for("bogus")


def test_assert_studies_unique_catches_duplicates() -> None:
    s1 = StudyAssessment("dup", "rct", "rob2", _all_low("rob2"), "low")
    s2 = StudyAssessment("dup", "rct", "rob2", _all_low("rob2"), "high")
    with pytest.raises(ValueError, match="duplicate study_id"):
        assert_studies_unique([s1, s2])


# ---- GRADE schema tests ----------------------------------------------------


@pytest.mark.parametrize("downgrades,expected", [
    ((DowngradeAdjustment("rob", 1), DowngradeAdjustment("inconsistency", 1)), "low"),
    ((DowngradeAdjustment("rob", 2), DowngradeAdjustment("inconsistency", 2),
      DowngradeAdjustment("indirectness", 1)), "very_low"),
    ((), "high"),
])
def test_grade_downgrade_math(downgrades, expected) -> None:
    g = GradeAssessment("o", "high", downgrades=downgrades)
    assert g.final_certainty == expected


def test_grade_clamps_at_high() -> None:
    g = GradeAssessment("x", "low", upgrades=(
        UpgradeAdjustment("large_effect", 1),
        UpgradeAdjustment("dose_response", 1),
        UpgradeAdjustment("plausible_confounding", 1),
    ))
    assert g.final_certainty == "high"


def test_grade_low_plus_one_equals_moderate() -> None:
    g = GradeAssessment("x", "low", upgrades=(UpgradeAdjustment("large_effect", 1),))
    assert g.final_certainty == "moderate"


def test_invalid_downgrade_reason_raises() -> None:
    with pytest.raises(ValueError, match="invalid downgrade reason"):
        DowngradeAdjustment("bogus", 1)  # type: ignore[arg-type]


def test_invalid_downgrade_levels_raises() -> None:
    with pytest.raises(ValueError, match="downgrade levels"):
        DowngradeAdjustment("rob", 3)


def test_invalid_upgrade_reason_raises() -> None:
    with pytest.raises(ValueError, match="invalid upgrade reason"):
        UpgradeAdjustment("bogus", 1)  # type: ignore[arg-type]


def test_invalid_upgrade_levels_raises() -> None:
    with pytest.raises(ValueError, match="upgrade levels"):
        UpgradeAdjustment("large_effect", 2)


def test_invalid_starting_certainty_raises() -> None:
    with pytest.raises(ValueError, match="invalid starting_certainty"):
        GradeAssessment("x", "bogus")  # type: ignore[arg-type]


def test_empty_outcome_raises() -> None:
    with pytest.raises(ValueError, match="outcome"):
        GradeAssessment("", "high")


def test_starting_certainty_for_design_helper() -> None:
    assert starting_certainty_for_design("rct") == "high"
    assert starting_certainty_for_design("observational") == "low"
    assert starting_certainty_for_design("animal") == "low"
    with pytest.raises(ValueError):
        starting_certainty_for_design("bogus")


def test_valid_certainty_values_complete() -> None:
    assert VALID_CERTAINTY == frozenset({"high", "moderate", "low", "very_low"})


# ---- Renderer tests --------------------------------------------------------


def test_render_rob_table_includes_all_required_domains() -> None:
    studies = [
        StudyAssessment("Moel 2025", "rct", "rob2", _all_low("rob2"), "low"),
        StudyAssessment("Kell 2026", "observational", "robins_i",
                        _all_low("robins_i"), "some_concerns"),
        StudyAssessment("Harrison 2009", "animal", "syrcle", _all_low("syrcle"), "low"),
    ]
    md = render_rob_table(studies)
    assert "## ROB2" in md and "## ROBINS_I" in md and "## SYRCLE" in md
    for tool, domains in DOMAINS_BY_TOOL.items():
        for d in domains:
            assert d in md, f"missing {d} (tool={tool})"
    for sid in ("Moel 2025", "Kell 2026", "Harrison 2009"):
        assert sid in md


def test_render_rob_table_empty() -> None:
    assert "No studies provided" in render_rob_table([])


def test_render_grade_table_includes_all_outcomes() -> None:
    grades = [
        GradeAssessment("Lifespan", "low",
                        downgrades=(DowngradeAdjustment("indirectness", 2),)),
        GradeAssessment("HbA1c", "high",
                        downgrades=(DowngradeAdjustment("inconsistency", 1),)),
        GradeAssessment("AE", "high"),
    ]
    md = render_grade_table(grades)
    for outcome in ("Lifespan", "HbA1c", "AE"):
        assert outcome in md
    assert "very_low" in md and "moderate" in md and "high" in md


def test_render_grade_table_empty() -> None:
    assert "No outcomes provided" in render_grade_table([])


def test_studies_from_json_roundtrip() -> None:
    payload = [{
        "study_id": "S1", "design": "rct", "tool": "rob2", "overall_rating": "low",
        "domains": [{"domain": d, "rating": "low"} for d in ROB2_DOMAINS],
    }]
    studies = studies_from_json(payload)
    assert len(studies) == 1 and studies[0].study_id == "S1"


def test_grades_from_json_roundtrip() -> None:
    payload = [{
        "outcome": "X", "starting_certainty": "high",
        "downgrades": [{"reason": "rob", "levels": 1}], "upgrades": [],
    }]
    grades = grades_from_json(payload)
    assert grades[0].final_certainty == "moderate"


def test_studies_from_json_invalid_rating_raises() -> None:
    payload = [{
        "study_id": "S1", "design": "rct", "tool": "rob2", "overall_rating": "low",
        "domains": [{"domain": "randomization", "rating": "bogus"}],
    }]
    with pytest.raises(ValueError, match="invalid rating"):
        studies_from_json(payload)


def test_render_cli_writes_outputs(tmp_path: Path) -> None:
    rob_input = tmp_path / "rob.json"
    rob_input.write_text(json.dumps([{
        "study_id": "S1", "design": "rct", "tool": "rob2", "overall_rating": "low",
        "domains": [{"domain": d, "rating": "low"} for d in ROB2_DOMAINS],
    }]))
    grade_input = tmp_path / "grade.json"
    grade_input.write_text(json.dumps([{
        "outcome": "Y", "starting_certainty": "high",
        "downgrades": [], "upgrades": [],
    }]))
    rob_out = tmp_path / "rob.md"
    grade_out = tmp_path / "grade.md"
    proc = subprocess.run(
        [sys.executable, str(RENDER_SCRIPT),
         "--rob", str(rob_input), "--grade", str(grade_input),
         "--rob-out", str(rob_out), "--grade-out", str(grade_out)],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "S1" in rob_out.read_text()
    assert "Y" in grade_out.read_text()
