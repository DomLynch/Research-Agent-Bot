"""Tests for agent.target_journal_pack — submission-pack schema + validator.

Stdlib-only, no LLM. Universal — no domain assumptions about journal
name, article type, or content.
"""
from __future__ import annotations

import json
from pathlib import Path

from agent.target_journal_pack import (  # type: ignore[import-not-found]
    PACK_FILENAME,
    PackIssue,
    TargetJournalPack,
    load,
    load_and_validate,
    validate,
    write,
)


# ---- helpers --------------------------------------------------------------


def _valid_pack(**over: object) -> TargetJournalPack:
    base = dict(
        journal="Aging Cell",
        article_type="Original Research",
        abstract_max_words=250,
        main_word_limit=6000,
        reference_style="Vancouver",
    )
    base.update(over)
    return TargetJournalPack(**base)  # type: ignore[arg-type]


# ---- TargetJournalPack.from_dict + defaults -------------------------------


def test_from_dict_round_trips_minimum_fields() -> None:
    raw = {
        "journal": "Nature Aging",
        "article_type": "Review",
        "abstract_max_words": 200,
        "main_word_limit": 5000,
        "reference_style": "AMA",
    }
    p = TargetJournalPack.from_dict(raw)
    assert p.journal == "Nature Aging"
    assert p.article_type == "Review"
    assert p.abstract_max_words == 200
    assert p.main_word_limit == 5000
    assert p.reference_style == "AMA"
    # Defaults
    assert p.requires_prisma is False
    assert p.requires_ai_disclosure is False
    assert p.allows_supplement is True
    assert p.notes == ""


def test_from_dict_empty_yields_invalid_pack() -> None:
    """No required field present → all-empty pack; validation catches it."""
    p = TargetJournalPack.from_dict({})
    issues = validate(p)
    codes = {i.code for i in issues}
    assert "empty_journal" in codes
    assert "empty_article_type" in codes
    assert "empty_reference_style" in codes
    assert "nonpositive_abstract_cap" in codes
    assert "nonpositive_main_cap" in codes


# ---- validate (universal, no domain logic) -------------------------------


def test_validate_passes_minimum_complete_pack() -> None:
    assert validate(_valid_pack()) == ()


def test_validate_flags_abstract_exceeds_main() -> None:
    p = _valid_pack(abstract_max_words=7000, main_word_limit=6000)
    codes = {i.code for i in validate(p)}
    assert "abstract_exceeds_main" in codes


def test_validate_flags_nonpositive_caps() -> None:
    p = _valid_pack(abstract_max_words=0, main_word_limit=-10)
    codes = {i.code for i in validate(p)}
    assert "nonpositive_abstract_cap" in codes
    assert "nonpositive_main_cap" in codes


def test_validate_flags_whitespace_only_journal() -> None:
    p = _valid_pack(journal="   ")
    codes = {i.code for i in validate(p)}
    assert "empty_journal" in codes


def test_validate_accepts_optional_flags_in_either_state() -> None:
    """requires_prisma / requires_ai_disclosure / allows_supplement
    are policy bits — both True and False must validate."""
    for prisma in (True, False):
        for ai in (True, False):
            for sup in (True, False):
                p = _valid_pack(
                    requires_prisma=prisma,
                    requires_ai_disclosure=ai,
                    allows_supplement=sup,
                )
                assert validate(p) == ()


# ---- load / write round trip ---------------------------------------------


def test_write_then_load_round_trip(tmp_path: Path) -> None:
    pack = _valid_pack(requires_prisma=True, allows_supplement=False)
    out = write(tmp_path, pack)
    assert out.name == PACK_FILENAME
    loaded = load(tmp_path)
    assert loaded == pack


def test_load_returns_none_when_file_absent(tmp_path: Path) -> None:
    assert load(tmp_path) is None


def test_load_returns_none_on_unreadable_json(tmp_path: Path) -> None:
    (tmp_path / PACK_FILENAME).write_text("{not json")
    assert load(tmp_path) is None


def test_load_returns_none_when_top_level_not_a_dict(tmp_path: Path) -> None:
    (tmp_path / PACK_FILENAME).write_text(json.dumps(["nope"]))
    assert load(tmp_path) is None


# ---- load_and_validate convenience ---------------------------------------


def test_load_and_validate_reports_missing_file(tmp_path: Path) -> None:
    pack, issues = load_and_validate(tmp_path)
    assert pack is None
    assert any(i.code == "pack_missing" for i in issues)


def test_load_and_validate_passes_clean_pack(tmp_path: Path) -> None:
    write(tmp_path, _valid_pack())
    pack, issues = load_and_validate(tmp_path)
    assert pack is not None
    assert issues == ()


# ---- shape guards ---------------------------------------------------------


def test_pack_is_frozen_and_immutable() -> None:
    import pytest
    p = _valid_pack()
    with pytest.raises(AttributeError):
        p.journal = "other"  # type: ignore[misc]


def test_issue_is_frozen_and_immutable() -> None:
    import pytest
    i = PackIssue(field="journal", code="empty_journal", detail="x")
    with pytest.raises(AttributeError):
        i.code = "y"  # type: ignore[misc]


def test_no_journal_allowlist_universal() -> None:
    """Universal-no-hardcoding: validate() must accept ANY non-empty
    journal name. No allowlist of specific journals."""
    for name in ("Aging Cell", "Materials Today", "Journal of Climate",
                 "Quarterly Journal of Economics", "Custom New Venue 2026"):
        assert validate(_valid_pack(journal=name)) == ()
