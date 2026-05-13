"""Tests for agent.human_signoff — author accountability record.

Stdlib-only. Universal — accepts any author name; no domain-specific
field requirements.
"""
from __future__ import annotations

import json
from pathlib import Path

from agent.human_signoff import (  # type: ignore[import-not-found]
    SIGNOFF_FILENAME,
    HumanSignoff,
    SignoffIssue,
    load,
    load_and_validate,
    validate,
    write,
)


def _ready(**over: object) -> HumanSignoff:
    """A fully-ready signoff (all review bits True)."""
    base: dict = dict(
        author="Dom Lynch",
        reviewed=True,
        evidence_claims_reviewed=True,
        conflicts_declared=True,
        ready_to_submit=True,
    )
    base.update(over)
    return HumanSignoff(**base)  # type: ignore[arg-type]


# ---- from_dict + universal-rename alias ----------------------------------


def test_from_dict_universal_field_name_accepted() -> None:
    raw = {
        "author": "Dom Lynch", "reviewed": True,
        "evidence_claims_reviewed": True,
        "conflicts_declared": True, "ready_to_submit": True,
    }
    s = HumanSignoff.from_dict(raw)
    assert s.evidence_claims_reviewed is True
    assert s.author == "Dom Lynch"


def test_from_dict_legacy_clinical_alias_migrates() -> None:
    """Universal-no-hardcoding migration: legacy biomedical-only field
    name `clinical_claims_reviewed` still loads into the universal
    `evidence_claims_reviewed` slot."""
    raw = {
        "author": "Dom Lynch", "reviewed": True,
        "clinical_claims_reviewed": True,  # legacy field
        "conflicts_declared": True, "ready_to_submit": True,
    }
    s = HumanSignoff.from_dict(raw)
    assert s.evidence_claims_reviewed is True


def test_from_dict_defaults_to_unreviewed() -> None:
    s = HumanSignoff.from_dict({})
    assert s.author == ""
    assert s.reviewed is False
    assert s.evidence_claims_reviewed is False
    assert s.conflicts_declared is False
    assert s.ready_to_submit is False
    assert s.timestamp == ""


# ---- validate ------------------------------------------------------------


def test_validate_passes_fully_ready_signoff() -> None:
    assert validate(_ready()) == ()


def test_validate_flags_empty_author() -> None:
    codes = {i.code for i in validate(_ready(author=""))}
    assert "empty_author" in codes


def test_validate_flags_not_ready() -> None:
    codes = {i.code for i in validate(_ready(ready_to_submit=False))}
    assert "not_ready" in codes


def test_validate_flags_ready_without_review() -> None:
    """Cannot mark ready_to_submit while denying any review bit."""
    s = _ready(reviewed=False)
    codes = {i.code for i in validate(s)}
    assert "ready_without_review" in codes


def test_validate_flags_ready_without_evidence_review() -> None:
    s = _ready(evidence_claims_reviewed=False)
    codes = {i.code for i in validate(s)}
    assert "ready_without_review" in codes


def test_validate_flags_ready_without_conflicts_declared() -> None:
    s = _ready(conflicts_declared=False)
    codes = {i.code for i in validate(s)}
    assert "ready_without_review" in codes


# ---- write / load round trip --------------------------------------------


def test_write_stamps_timestamp_when_absent(tmp_path: Path) -> None:
    s = _ready()  # no timestamp
    out = write(tmp_path, s)
    assert out.name == SIGNOFF_FILENAME
    loaded = load(tmp_path)
    assert loaded is not None
    # timestamp is ISO-8601-shaped, contains 'T' and ends with offset
    assert "T" in loaded.timestamp and (
        loaded.timestamp.endswith("+00:00") or "Z" in loaded.timestamp
    )


def test_write_preserves_explicit_timestamp(tmp_path: Path) -> None:
    s = _ready(timestamp="2026-05-13T00:00:00+00:00")
    write(tmp_path, s)
    loaded = load(tmp_path)
    assert loaded is not None
    assert loaded.timestamp == "2026-05-13T00:00:00+00:00"


def test_load_returns_none_when_absent(tmp_path: Path) -> None:
    assert load(tmp_path) is None


def test_load_returns_none_on_bad_json(tmp_path: Path) -> None:
    (tmp_path / SIGNOFF_FILENAME).write_text("{not json")
    assert load(tmp_path) is None


def test_load_returns_none_when_top_level_not_dict(tmp_path: Path) -> None:
    (tmp_path / SIGNOFF_FILENAME).write_text(json.dumps([1, 2, 3]))
    assert load(tmp_path) is None


# ---- load_and_validate ---------------------------------------------------


def test_load_and_validate_reports_missing_file(tmp_path: Path) -> None:
    s, issues = load_and_validate(tmp_path)
    assert s is None
    assert any(i.code == "signoff_missing" for i in issues)


def test_load_and_validate_passes_ready_signoff(tmp_path: Path) -> None:
    write(tmp_path, _ready())
    s, issues = load_and_validate(tmp_path)
    assert s is not None
    assert issues == ()


# ---- shape guards --------------------------------------------------------


def test_signoff_is_frozen_and_immutable() -> None:
    import pytest
    s = _ready()
    with pytest.raises(AttributeError):
        s.author = "other"  # type: ignore[misc]


def test_issue_is_frozen_and_immutable() -> None:
    import pytest
    i = SignoffIssue(field="author", code="empty_author", detail="x")
    with pytest.raises(AttributeError):
        i.code = "y"  # type: ignore[misc]


def test_no_domain_assumption_in_field_names() -> None:
    """Universal-no-hardcoding: the field names must not encode a
    specific scientific domain. evidence_claims_reviewed is universal;
    clinical_claims_reviewed is biomedical-only and is only accepted
    as a legacy alias in from_dict."""
    s = _ready()
    fields = {f for f in s.__dataclass_fields__}
    assert "clinical_claims_reviewed" not in fields, (
        "biomedical-only field name leaked into universal schema"
    )
    assert "evidence_claims_reviewed" in fields
