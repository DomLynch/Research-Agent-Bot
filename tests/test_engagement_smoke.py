"""Smoke tests against the real AAA4 rapamycin bundle.

Read-only. Loads `bundles/synthesis-rapamycin-v06-AAA4-2026-05-04T15-50-14Z/`
artifacts and runs the planning primitives against actual corpus shape
to verify the modules don't break on real data and produce honest
findings even when the corpus lacks framework-anchor authors.

The tests skip cleanly if the bundle is absent (e.g., shallow checkout).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.field_engagement import FIELD_FRAMEWORK_REGISTRY, evaluate_engagement

REPO_ROOT = Path(__file__).resolve().parent.parent
AAA4 = REPO_ROOT / "bundles" / "synthesis-rapamycin-v06-AAA4-2026-05-04T15-50-14Z"
MANIFEST = AAA4 / "manifest.json"
CITATIONS = AAA4 / "citation_registry.json"


def _load_aaa4() -> tuple[dict, dict]:
    if not MANIFEST.is_file():
        pytest.skip(f"AAA4 bundle not present at {AAA4}")
    return (
        json.loads(MANIFEST.read_text(encoding="utf-8")),
        json.loads(CITATIONS.read_text(encoding="utf-8")),
    )


def _enriched_receipts() -> list[dict]:
    """Real AAA4 receipts enriched with body_citation tokens from the
    citation registry — the same enrichment the writer module would do."""
    manifest, citations = _load_aaa4()
    enriched: list[dict] = []
    for receipt in manifest.get("receipts", []):
        rid = receipt.get("receipt_id", "")
        cite = citations.get(rid, {}) if isinstance(citations, dict) else {}
        e = dict(receipt)
        body_cite = cite.get("body_citation")
        if isinstance(body_cite, str):
            e["citation_token"] = body_cite
        enriched.append(e)
    return enriched


# ---- AAA4 manifest shape sanity -------------------------------------------


def test_aaa4_manifest_loads_and_has_receipts() -> None:
    manifest, _ = _load_aaa4()
    receipts = manifest.get("receipts", [])
    assert len(receipts) == 3
    # Each receipt has the fields evaluate_engagement expects
    for r in receipts:
        assert "receipt_id" in r
        assert "outcome_class" in r
        assert "effect_direction" in r


def test_aaa4_citation_registry_has_body_citations() -> None:
    _, citations = _load_aaa4()
    assert isinstance(citations, dict)
    body_citations = [
        v.get("body_citation") for v in citations.values()
        if isinstance(v, dict)
    ]
    # AAA4 bundle: Moel 2025, Stanfield 2026, Kell 2026
    assert "Moel 2025" in body_citations
    assert any("Kell" in c for c in body_citations if c)


# ---- evaluate_engagement on real corpus -----------------------------------


def test_evaluate_engagement_runs_on_aaa4_without_crashing() -> None:
    """Smoke: real-shape data does not break the function."""
    enriched = _enriched_receipts()
    results = evaluate_engagement(receipts=enriched)
    # Always returns one result per registered framework.
    assert len(results) == len(FIELD_FRAMEWORK_REGISTRY)
    valid_statuses = {"support", "challenge", "extends", "insufficient"}
    for e in results:
        assert e.status in valid_statuses


def test_evaluate_engagement_on_aaa4_correctly_reports_insufficient() -> None:
    """The AAA4 corpus has Moel/Stanfield/Kell — none of which are framework
    anchor authors. Honest finding: every framework is "insufficient" on this
    corpus. This is the gap the corpus expansion lane is meant to close."""
    enriched = _enriched_receipts()
    results = evaluate_engagement(receipts=enriched)
    by_name = {e.framework_name: e for e in results}
    for fw in ("Mannick", "Lamming", "Kennedy", "Kaeberlein", "Lopez-Otin"):
        assert by_name[fw].status == "insufficient", (
            f"{fw} unexpectedly resolved to {by_name[fw].status} on AAA4 "
            f"(expected insufficient — AAA4 has no {fw}-anchored receipts)"
        )


def test_evaluate_engagement_lights_up_when_framework_anchor_added() -> None:
    """Demonstrate the function would correctly identify Mannick if the
    corpus expansion landed Mannick 2018 (PIE trial) as a receipt."""
    enriched = _enriched_receipts()
    enriched.append({
        "receipt_id": "PMC_PROJECTED_Mannick_2018_PIE",
        "citation_token": "Mannick 2018",
        "outcome_class": "immune",
        "effect_direction": "positive",
        "evidence_tier": "A1",
        "directness": "direct",
    })
    results = evaluate_engagement(receipts=enriched)
    by_name = {e.framework_name: e for e in results}
    assert by_name["Mannick"].status == "support"
    assert "PMC_PROJECTED_Mannick_2018_PIE" in by_name["Mannick"].matched_receipts
