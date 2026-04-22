from agent.drafter import _bundle_entry, _classify_directness
from agent.evidence_cards import build_card
from agent.submit import _quality_gate


def test_classify_directness_marks_aging_rct_direct():
    item = {
        "title": "Metformin and aging in older adults: randomized controlled trial",
        "excerpt": "Older adults receiving metformin had aging biomarker outcomes assessed.",
        "evidence_type": "primary",
        "year": 2024,
    }
    card = build_card(item)
    directness = _classify_directness(item, card, "longevity", ["metformin", "aging"])
    assert directness == "direct"


def test_classify_directness_marks_oncology_review_indirect():
    item = {
        "title": "Hyperinsulinemia in obesity, inflammation, and cancer",
        "excerpt": "Review discussing inflammation, aging, and cancer pathways without metformin intervention trials.",
        "evidence_type": "review",
        "year": 2021,
        "source_type": "openalex",
    }
    card = build_card(item)
    directness = _classify_directness(item, card, "longevity", ["metformin", "longevity"])
    assert directness == "indirect"


def test_classify_directness_marks_chembl_mechanistic():
    item = {
        "title": "Everolimus mechanism of action",
        "excerpt": "mTOR inhibitor mechanism in oncology indications.",
        "evidence_type": "mechanism",
        "source_type": "chembl",
        "year": 2025,
    }
    card = build_card(item)
    directness = _classify_directness(item, card, "longevity", ["everolimus", "aging"])
    assert directness == "mechanistic"


def test_classify_directness_marks_protocol_indirect():
    item = {
        "title": "Metformin and longevity: protocol for a randomized trial in older adults",
        "excerpt": "Rationale and study design for healthy aging outcomes.",
        "evidence_type": "primary",
        "year": 2024,
    }
    card = build_card(item)
    directness = _classify_directness(item, card, "longevity", ["metformin", "longevity"])
    assert directness == "indirect"


def test_quality_gate_fires_on_classifier_generated_indirect_only_bundle():
    topic_tokens = ["everolimus", "aging"]
    items = [
        {
            "title": f"Everolimus oncology review {i}",
            "excerpt": "Cancer outcomes and transplant immunosuppression without healthy aging endpoints.",
            "evidence_type": "review" if i % 2 == 0 else "primary",
            "year": 2024,
            "source_type": "openalex",
            "doi": f"10.1/onco{i}",
        }
        for i in range(8)
    ]
    bundle = [_bundle_entry(item, topic_tokens, "longevity") for item in items]
    artifact = {
        "title": "Rapid Evidence Synthesis: everolimus",
        "domain_slug": "longevity",
        "source_bundle": bundle,
    }
    assert _quality_gate(artifact, current_year=2026, topic="everolimus aging") == "indirect_only_bundle"
