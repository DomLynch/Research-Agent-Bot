"""Fix #16: background-literature registry — the external-context lane.

Discriminating tests for the registry loader, numeric-set extraction,
and the unsourced-use check that Stage-2 wires into the audit."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import background_literature as bg  # noqa: E402


def _registry(**entries: dict) -> dict[str, bg.BackgroundLitEntry]:
    """Build a registry from inline dicts, bypassing the seed JSON.
    Fills in defaults for required fields not specified by callers."""
    out: dict[str, bg.BackgroundLitEntry] = {}
    for k, v in entries.items():
        kwargs = {
            "key": k,
            "context": v.get("context", "test context"),
            "canonical_reference": v.get(
                "canonical_reference", "Test Reference 2024.",
            ),
            "numeric": v["numeric"],
            "citation_token": v["citation_token"],
            "doi": v.get("doi"),
            "pmid": v.get("pmid"),
        }
        out[k] = bg.BackgroundLitEntry(**kwargs)
    return out


def test_load_registry_returns_empty_when_seed_missing() -> None:
    """A non-existent seed file → empty registry (caller falls back
    to corpus-only Q2 behaviour)."""
    nowhere = Path("/tmp/this-file-does-not-exist-bglit.json")
    assert bg.load_registry(nowhere) == {}


def test_load_registry_parses_seed_json() -> None:
    """Round-trip: write a small seed, load, verify field mapping."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False,
    ) as f:
        json.dump({
            "test_entry": {
                "numeric": "0.8 m/s",
                "context": "frailty cutoff",
                "citation_token": "Studenski 2011",
                "canonical_reference": "Studenski et al. JAMA 2011.",
                "doi": "10.1001/jama.2010.1923",
            },
        }, f)
        path = Path(f.name)
    try:
        reg = bg.load_registry(path)
        assert "test_entry" in reg
        e = reg["test_entry"]
        assert e.numeric == "0.8 m/s"
        assert e.citation_token == "Studenski 2011"
        assert e.doi == "10.1001/jama.2010.1923"
    finally:
        path.unlink()


def test_numeric_values_includes_normalized_digit_form() -> None:
    """`0.8 m/s` produces both '0.8 m/s' and '0.8' for tolerant
    matching against paper text."""
    reg = _registry(test={
        "numeric": "0.8 m/s",
        "citation_token": "Studenski 2011",
    })
    nums = bg.numeric_values(reg)
    assert "0.8 m/s" in nums
    assert "0.8" in nums


def test_unsourced_use_detected_when_citation_missing() -> None:
    """The whole point: if `0.8 m/s` appears in body without
    `Studenski 2011` in same sentence, return as unsourced use."""
    reg = _registry(gait={
        "numeric": "0.8 m/s",
        "citation_token": "Studenski 2011",
    })
    paper = "Walk-speed declines below 0.8 m/s indicate frailty risk."
    unsourced = bg.find_unsourced_background_uses(paper, reg)
    assert len(unsourced) == 1
    numeric, cite, snippet = unsourced[0]
    assert numeric == "0.8 m/s"
    assert cite == "Studenski 2011"


def test_sourced_use_admitted_when_citation_in_same_sentence() -> None:
    """When the canonical citation IS in the sentence, the use is
    admitted (no issue returned)."""
    reg = _registry(gait={
        "numeric": "0.8 m/s",
        "citation_token": "Studenski 2011",
    })
    paper = (
        "Walk-speed declines below 0.8 m/s "
        "(Studenski 2011) indicate frailty risk."
    )
    unsourced = bg.find_unsourced_background_uses(paper, reg)
    assert unsourced == []


def test_citation_in_different_sentence_does_not_count() -> None:
    """Sentence-level scope: citation in NEXT sentence ≠ same sentence."""
    reg = _registry(gait={
        "numeric": "0.8 m/s",
        "citation_token": "Studenski 2011",
    })
    paper = (
        "Walk-speed declines below 0.8 m/s indicate frailty risk. "
        "This threshold derives from Studenski 2011."
    )
    unsourced = bg.find_unsourced_background_uses(paper, reg)
    assert len(unsourced) == 1


def test_paper_without_any_background_use_is_clean() -> None:
    """If the paper never mentions the background numeric, no issue."""
    reg = _registry(gait={
        "numeric": "0.8 m/s",
        "citation_token": "Studenski 2011",
    })
    paper = "## Discussion\n\nQualitative analysis of metformin trials.\n"
    assert bg.find_unsourced_background_uses(paper, reg) == []


def test_empty_registry_returns_no_issues() -> None:
    """Empty registry → check is a no-op."""
    paper = "Walk-speed below 0.8 m/s indicates frailty."
    assert bg.find_unsourced_background_uses(paper, {}) == []


def test_entry_is_frozen_kw_only() -> None:
    """Cross-stage object → frozen+slots+kw_only per project rule."""
    e = bg.BackgroundLitEntry(
        key="x", numeric="0.8 m/s",
        citation_token="Studenski 2011",
        canonical_reference="Test 2024",
        context="",
    )
    with pytest.raises(Exception):  # FrozenInstanceError
        e.numeric = "0.9 m/s"
    # kw_only enforcement: positional construction fails
    with pytest.raises(TypeError):
        bg.BackgroundLitEntry(  # type: ignore[call-arg]
            "x", "0.8 m/s", "ctx", "Studenski 2011", "ref",
        )


def test_seeded_registry_loads_canonical_thresholds() -> None:
    """Smoke: the shipped seed JSON loads with at least 10 entries
    including the load-bearing 0.8 m/s frailty cutoff."""
    reg = bg.load_registry()
    assert len(reg) >= 10, f"seed registry too small: {len(reg)}"
    # The whole motivating example
    by_numeric = {e.numeric: e for e in reg.values()}
    assert "0.8 m/s" in by_numeric
    assert by_numeric["0.8 m/s"].citation_token.startswith("Studenski")


# ----- Fix #18a: writer-side block formatter ---------------------------


def test_build_background_lit_block_emits_required_fields() -> None:
    """Block must surface numeric + citation_token + use rule for
    every entry — that's what MiMo needs to write 'X (Author YYYY)'."""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from agent.paper_writer import _build_background_lit_block
    entries = [
        bg.BackgroundLitEntry(
            key="x", numeric="0.8 m/s",
            citation_token="Studenski 2011",
            canonical_reference="Studenski et al. JAMA 2011.",
            context="frailty walk-speed cutoff",
        ),
    ]
    block = _build_background_lit_block(entries)
    assert "ALLOWED BACKGROUND CITATIONS" in block
    assert "0.8 m/s" in block
    assert "Studenski 2011" in block
    assert "frailty walk-speed cutoff" in block
    # Use rule must mention 'same sentence' so MiMo doesn't get clever
    assert "SAME sentence" in block or "same sentence" in block


def test_build_background_lit_block_empty_when_no_entries() -> None:
    """No entries → empty block (caller falls back to corpus-only)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from agent.paper_writer import _build_background_lit_block
    assert _build_background_lit_block(None) == ""
    assert _build_background_lit_block([]) == ""
