"""Slice 37 — role-aware receipt admission.

Reviewer doctrine 2026-05-16: the receipt-builder was binary
("high-confidence claim or nothing") which starved vitamin_d-like
topics where most papers are reviews / mechanistic / context. Fix:
admit `partial`-confidence claims when the paper is in the corpus
classifier's keep-set (core_on_thesis / adjacent_clinical /
background_mechanism). Universal — no per-topic logic.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace


def _seed_topic_dirs(topic_root: Path) -> None:
    """Create the minimum directory + file shape the script expects."""
    (topic_root / "parsed").mkdir(parents=True, exist_ok=True)
    (topic_root / "quant_claims").mkdir(parents=True, exist_ok=True)


def _set_active_topic(topic_root: Path, topic: str) -> None:
    """Monkey-patch the script's _set_topic-equivalent globals."""
    import importlib
    mod = importlib.import_module("scripts.run_v06_synthesis")
    mod._set_topic(topic)
    # Override the corpus dirs to point at our fixture
    setattr(mod, "QUANT_DIR", topic_root / "quant_claims")
    setattr(mod, "PARSED_DIR", topic_root / "parsed")


def test_slice37_partial_claim_admitted_when_paper_is_in_keep_class(tmp_path: Path) -> None:
    """Partial-confidence claims become receipts when the paper is in
    corpus_classifier's keep-set (core/adjacent/background)."""
    root = tmp_path / "vitamin_d"
    _seed_topic_dirs(root)
    # Manifest with one DOI-keyed entry in core_on_thesis
    (root / "corpus_manifest.json").write_text(json.dumps({
        "topic": "vitamin_d",
        "entries": [{
            "paper_id": "NCT12345", "doi": "10.1000/test1",
            "pmid": None, "classification": "core_on_thesis",
        }],
    }))
    # Extract report maps PMC → DOI
    (root / "_extract_report.json").write_text(json.dumps({
        "active_paper_ids": ["PMC9999_review_paper"],
        "papers_resolved": {"PMC9999": {"doi": "10.1000/test1", "title": "Vitamin D Review"}},
    }))
    (root / "parsed" / "PMC9999_review_paper.paper_sections.json").write_text(json.dumps({
        "paper_id": "PMC9999_review_paper", "title": "Vitamin D Review", "abstract": "Vitamin D evidence.",
    }))
    # Quant claims with ONLY partial-binding claims (no high)
    (root / "quant_claims" / "PMC9999_review_paper.quant_claims.json").write_text(json.dumps({
        "paper_id": "PMC9999_review_paper",
        "claims": [
            {"binding_confidence": "partial", "claim_type": "effect_size",
             "endpoint": "muscle strength", "raw_text": "improved by 10%"},
        ],
    }))
    _set_active_topic(root, "vitamin_d")
    import importlib
    mod = importlib.import_module("scripts.run_v06_synthesis")
    class_map = mod._load_paper_class_map()
    assert "PMC9999" in class_map, f"PMC9999 should resolve via DOI join; got {class_map}"
    receipts = mod.build_receipts_from_quant_claims(topic="vitamin_d")
    assert len(receipts) == 1
    assert receipts[0].receipt_id == "PMC9999_review_paper"
    # Partial-only paper → tier ≤ B2 (review-tier or below); never A* (primary)
    assert receipts[0].evidence_tier in ("B2", "C1", "C2", "C")
    assert receipts[0].directness in ("review", "indirect", "mechanistic")


def test_slice37_partial_claim_rejected_when_paper_not_in_keep_class(tmp_path: Path) -> None:
    """When the classifier puts a paper in off_thesis / reject (or the
    paper has no class entry at all), partial-binding claims do NOT
    create a receipt — the original strict gate still holds."""
    root = tmp_path / "vitamin_d"
    _seed_topic_dirs(root)
    # Manifest has an OFF-THESIS entry (not in keep-set)
    (root / "corpus_manifest.json").write_text(json.dumps({
        "topic": "vitamin_d",
        "entries": [{
            "paper_id": "NCT00001", "doi": "10.1000/offtopic",
            "pmid": None, "classification": "off_thesis",
        }],
    }))
    (root / "_extract_report.json").write_text(json.dumps({
        "active_paper_ids": ["PMC8888_off_topic_paper"],
        "papers_resolved": {"PMC8888": {"doi": "10.1000/offtopic", "title": "Off-topic"}},
    }))
    (root / "quant_claims" / "PMC8888_off_topic_paper.quant_claims.json").write_text(json.dumps({
        "paper_id": "PMC8888_off_topic_paper",
        "claims": [{"binding_confidence": "partial", "claim_type": "effect_size"}],
    }))
    _set_active_topic(root, "vitamin_d")
    import importlib
    mod = importlib.import_module("scripts.run_v06_synthesis")
    receipts = mod.build_receipts_from_quant_claims(topic="vitamin_d")
    assert receipts == []


def test_slice37_high_confidence_paper_keeps_primary_tier(tmp_path: Path) -> None:
    """High-confidence claims still produce primary-tier receipts —
    the Slice 37 downgrade only applies to partial-only papers."""
    root = tmp_path / "vitamin_d"
    _seed_topic_dirs(root)
    (root / "corpus_manifest.json").write_text(json.dumps({
        "topic": "vitamin_d",
        "entries": [{
            "paper_id": "NCT55555", "doi": "10.1000/primary",
            "pmid": None, "classification": "core_on_thesis",
        }],
    }))
    (root / "_extract_report.json").write_text(json.dumps({
        "active_paper_ids": ["PMC7777_primary_rct"],
        "papers_resolved": {"PMC7777": {"doi": "10.1000/primary", "title": "Vitamin D Primary RCT"}},
    }))
    (root / "parsed" / "PMC7777_primary_rct.paper_sections.json").write_text(json.dumps({
        "paper_id": "PMC7777_primary_rct", "title": "Vitamin D Primary RCT", "abstract": "Vitamin D trial.",
    }))
    (root / "quant_claims" / "PMC7777_primary_rct.quant_claims.json").write_text(json.dumps({
        "paper_id": "PMC7777_primary_rct",
        "claims": [
            {"binding_confidence": "high", "claim_type": "effect_size",
             "endpoint": "all-cause mortality", "raw_text": "HR 0.85"},
            {"binding_confidence": "partial", "claim_type": "p_value",
             "raw_text": "p=0.04"},
        ],
    }))
    _set_active_topic(root, "vitamin_d")
    import importlib
    mod = importlib.import_module("scripts.run_v06_synthesis")
    receipts = mod.build_receipts_from_quant_claims(topic="vitamin_d")
    assert len(receipts) == 1
    # Should NOT be downgraded to B2 — paper has a high-conf claim
    assert receipts[0].evidence_tier != "B2" or receipts[0].directness != "review"


def test_receipt_builder_excludes_retracted_and_off_topic_active_arm_noise(tmp_path: Path) -> None:
    """Runtime receipt admission refuses retracted titles and stale corpus rows
    that do not mention the active topic synonym. This prevents a bad topic-pack
    alias/corpus cache from feeding unrelated papers to the writer."""
    root = tmp_path / "coenzyme_q10"
    _seed_topic_dirs(root)
    (root / "_extract_report.json").write_text(json.dumps({
        "active_paper_ids": ["PMC1_good", "PMC2_statin", "PMC3_retracted"],
    }))
    for pid, title in {
        "PMC1_good": "Coenzyme Q10 improves inflammatory biomarkers",
        "PMC2_statin": "The impact of statin use on mortality",
        "PMC3_retracted": "Retracted Article: Coenzyme Q10 supplement trial",
    }.items():
        (root / "parsed" / f"{pid}.paper_sections.json").write_text(json.dumps({
            "paper_id": pid, "title": title, "abstract": title,
        }))
        (root / "quant_claims" / f"{pid}.quant_claims.json").write_text(json.dumps({
            "paper_id": pid,
            "claims": [{"binding_confidence": "high", "claim_type": "effect_size",
                        "endpoint": "mortality", "arm": "coenzyme q10", "direction": "decrease"}],
        }))
    _set_active_topic(root, "coenzyme_q10")
    import importlib
    mod = importlib.import_module("scripts.run_v06_synthesis")
    setattr(mod, "_TOPIC_PACK", SimpleNamespace(
        active_arm_synonyms=frozenset({"coenzyme q10"}),
        placebo_arm_synonyms=frozenset({"placebo", "control"}),
        canonical_rct_paper_ids=frozenset(),
    ))

    receipts = mod.build_receipts_from_quant_claims(topic="coenzyme_q10")

    assert [r.receipt_id for r in receipts] == ["PMC1_good"]
