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
    to corpus-only Q2 behaviour).

    Refactor 2026-05-04: load_registry now auto-merges the active
    topic pack's bg-lit entries when audit_v06_paper._ACTIVE_TOPIC
    is set. Pass topic='__none__' (a topic with no pack file) to
    suppress the auto-merge for this isolation test."""
    nowhere = Path("/tmp/this-file-does-not-exist-bglit.json")
    assert bg.load_registry(nowhere, topic="__none__") == {}


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


def test_receipt_supported_numeric_does_not_require_background_citation(
    tmp_path: Path,
) -> None:
    reg = _registry(vaccine={
        "numeric": "20%",
        "citation_token": "Schulz 2010",
    })
    qdir = tmp_path / "quant_claims"
    qdir.mkdir()
    rid = "PMID25540326_mtor_inhibition_improves_immune_function"
    (qdir / f"{rid}.quant_claims.json").write_text(json.dumps({
        "claims": [{
            "binding_confidence": "high",
            "raw_text": "20%",
            "numeric_values": [20.0],
        }],
    }))
    manifest = {
        "receipts": [{
            "receipt_id": rid,
            "citation_token": "Mannick 2014",
        }],
    }
    paper = (
        "Mannick 2014 reported about 20% improvement in vaccine "
        "response."
    )
    unsourced = bg.find_unsourced_background_uses(
        paper,
        reg,
        manifest=manifest,
        quant_claims_dir=qdir,
    )
    assert unsourced == []


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
        e.numeric = "0.9 m/s"  # type: ignore[misc]
    # kw_only enforcement: positional construction fails
    with pytest.raises(TypeError):
        bg.BackgroundLitEntry(  # type: ignore[misc]
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


# ----- Fix #21 follow-up: skip markdown tables ------------------------


def test_unsourced_check_skips_markdown_table_rows() -> None:
    """Fix #21 follow-up: Table 5 cells contain corpus numerics that
    happen to match background_literature entries (e.g. '7%' for the
    HbA1c target). Those numerics are corpus-authorised, NOT
    background-context, and stripping the table for that would tank
    Q9 density. The detector skips paragraphs dominated by `|` rows."""
    reg = _registry(hba1c={
        "numeric": "7%",
        "citation_token": "ADA 2024",
    })
    paper = (
        "Real prose paragraph here. No background numerics.\n\n"
        "## Table 5: Numeric Index\n\n"
        "| Citation | Section | Type | Value | Units |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| Walton 2019 | abstract | percentage | 7% | % |\n"
        "| Konopka 2019 | abstract | percentage | 7% | % |\n"
    )
    # 7% appears in the table multiple times, ADA 2024 doesn't appear
    # at all → if we DID NOT skip tables, this would produce findings.
    findings = bg.find_unsourced_background_uses(paper, reg)
    assert findings == [], (
        f"table rows must NOT trigger unsourced finding, got: {findings}"
    )


def test_unsourced_check_skips_sentences_inside_long_table_cells() -> None:
    reg = _registry(hba1c={
        "numeric": "7%",
        "citation_token": "ADA 2024",
    })
    paper = (
        "A guideline recommends HbA1c below 7% for this population.\n\n"
        "| Study | Finding |\n"
        "| --- | --- |\n"
        "| Lee 2026 | The trial measured HbA1c. "
        "More patients reached HbA1c <7% after 24 weeks. |\n"
    )
    findings = bg.find_unsourced_background_uses(paper, reg)
    assert len(findings) == 1
    assert findings[0][2].startswith("A guideline recommends")


def test_unsourced_check_still_flags_prose_unsourced_use() -> None:
    """Regression check: skipping tables MUST NOT skip real prose
    sentences. A naked `7%` in a prose paragraph (no ADA 2024 in
    same sentence) is still unsourced."""
    reg = _registry(hba1c={
        "numeric": "7%",
        "citation_token": "ADA 2024",
    })
    paper = (
        "Diabetes guidelines target HbA1c below 7% in older adults.\n"
    )
    findings = bg.find_unsourced_background_uses(paper, reg)
    assert len(findings) == 1


def test_strip_reuses_numeric_index_only_within_one_call(tmp_path, monkeypatch) -> None:
    from apply_consistency_fixes import _strip_unsourced_background_sentences

    registry = _registry(target={"numeric": "7%", "citation_token": "ADA 2024"})
    monkeypatch.setattr(bg, "load_registry", lambda *, topic=None: registry)
    manifest = {"receipts": [{"receipt_id": "r1", "citation_token": "Trial 2025"}]}
    source = tmp_path / "r1.quant_claims.json"
    source.write_text(json.dumps({"claims": [{
        "binding_confidence": "high", "numeric_values": [7],
    }]}))
    build_index = bg._receipt_numeric_tokens_by_citation
    builds = []

    def counted_index(*args):
        builds.append(1)
        return build_index(*args)

    monkeypatch.setattr(bg, "_receipt_numeric_tokens_by_citation", counted_index)
    paper = "Trial 2025 reported 7%. Another study reported 7%. Context remains."
    kwargs = {"manifest": manifest, "quant_claims_dir": tmp_path}
    assert _strip_unsourced_background_sentences(paper, **kwargs) == (
        "Trial 2025 reported 7%. Context remains."
    )
    assert len(builds) == 1
    source.unlink()
    assert _strip_unsourced_background_sentences(paper, **kwargs) == "Context remains."
    assert len(builds) == 2


def test_is_table_dominated_helper() -> None:
    """Coverage of the markdown-table heuristic. ≥50% of non-blank
    lines start with `|` → table-dominated."""
    table = (
        "| col |\n| --- |\n| a |\n| b |"
    )
    prose = "This is real text. With multiple sentences."
    mixed_table_heavy = (
        "Caption text\n| col |\n| --- |\n| a |\n| b |"
    )
    mixed_prose_heavy = (
        "Sentence 1.\nSentence 2.\nSentence 3.\n| col |"
    )
    assert bg._is_table_dominated(table) is True
    assert bg._is_table_dominated(prose) is False
    assert bg._is_table_dominated(mixed_table_heavy) is True  # 4/5
    assert bg._is_table_dominated(mixed_prose_heavy) is False  # 1/4
    assert bg._is_table_dominated("") is False  # empty


# ---- #6: background-ref typing + Schulz fabrication removal -------------


def test_seed_registry_drops_fabricated_schulz_attrition() -> None:
    """#6: rct_attrition_typical attributed a fabricated '20%' attrition
    statistic to Schulz 2010 (CONSORT 2010 states no such figure). It must
    not be in the seed registry — guards the fabrication from re-entering."""
    reg = bg.load_registry(topic="__none__")
    offenders = [
        e for e in reg.values()
        if e.citation_token == "Schulz 2010" and e.numeric == "20%"
    ]
    assert offenders == []


def test_seed_entry_kind_typing() -> None:
    """#6: methodological references carry kind='reference'; numeric
    thresholds default to kind='threshold' — so code can label by kind
    instead of stamping every entry a 'clinical threshold'."""
    reg = bg.load_registry(topic="__none__")
    assert reg["surrogate_endpoint_caution"].kind == "reference"
    assert reg["gait_speed_frailty_cutoff"].kind == "threshold"


def test_background_kinds_phrase_matches_the_data() -> None:
    assert bg.background_kinds_phrase({"threshold"}) == (
        "Canonical reference values"
    )
    assert bg.background_kinds_phrase({"reference"}) == (
        "Methodological references"
    )
    assert bg.background_kinds_phrase({"threshold", "reference"}) == (
        "Canonical reference values and methodological references"
    )
    assert bg.background_kinds_phrase(set()) == "Background references"
