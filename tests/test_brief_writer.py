"""BRIEFS-V1 Phase 4 writer/renderer skeleton tests."""
from __future__ import annotations

from agent.briefs import parse_question, write_brief


def _receipts() -> list[dict]:
    return [
        {
            "receipt_id": "direct-rct",
            "citation_token": "Smith 2024",
            "outcome_class": "cardiometabolic",
            "evidence_tier": "A1",
            "directness": "direct",
            "effect_direction": "positive",
            "n_claims": 12,
        },
        {
            "receipt_id": "indirect-review",
            "citation_token": "Jones 2023",
            "outcome_class": "cardiometabolic",
            "evidence_tier": "B1",
            "directness": "review",
            "effect_direction": "mixed",
            "n_claims": 8,
        },
    ]


def test_write_brief_renders_expected_sections() -> None:
    q = parse_question("GLP-1 receptor agonists for cardiovascular outcomes")
    draft = write_brief(q, topic="glp1", receipts=_receipts())
    md = draft.body_md
    assert md.startswith("# Evidence Brief:")
    for heading in (
        "## Question", "## Direct Evidence",
        "## Indirect and Extrapolated Evidence",
        "## Tensions and Unknowns", "## Bottom Line", "## Provenance",
    ):
        assert heading in md


def test_write_brief_separates_direct_and_indirect_receipts() -> None:
    q = parse_question("GLP-1 receptor agonists for cardiovascular outcomes")
    md = write_brief(q, topic="glp1", receipts=_receipts()).body_md
    assert md.find("Smith 2024") < md.find("Jones 2023")
    assert "tier=A1" in md
    assert "directness=review" in md


def test_write_brief_empty_receipts_fail_closed() -> None:
    q = parse_question("metformin for cognition")
    md = write_brief(q, topic="metformin", receipts=[]).body_md
    assert "No matching receipts" in md
    assert "should not infer beyond the filtered corpus" in md


def test_brief_draft_to_dict_is_json_ready() -> None:
    q = parse_question("metformin for mortality")
    draft = write_brief(q, topic="metformin", receipts=_receipts()[:1])
    payload = draft.to_dict()
    assert payload["query"]["interventions"] == ["metformin"]
    assert payload["topic"] == "metformin"
    assert payload["n_receipts"] == 1
    assert payload["receipt_ids"] == ["direct-rct"]
