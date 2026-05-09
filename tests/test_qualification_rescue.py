from __future__ import annotations

import json

import qualification_rescue as rescue


def test_validate_claim_accepts_source_exact_effect() -> None:
    sections = {
        "abstract": (
            "Rapamycin treatment significantly increased post infection "
            "survival rate (p=0.0015)."
        ),
    }
    claim, reason = rescue._validate_claim(
        raw={
            "claim_type": "p_value",
            "raw_text": "p=0.0015",
            "source_sentence": sections["abstract"],
            "source_section": "abstract",
            "endpoint": "pathogen survival",
            "arm": "rapamycin",
            "direction": "increase",
        },
        paper_id="P1",
        sections=sections,
        endpoint_map={"pathogen survival": "immune"},
        allowed_arms={"rapamycin", "placebo"},
        model="test-model",
    )
    assert reason == "accepted"
    assert claim is not None
    assert claim["binding_confidence"] == "high"
    assert claim["numeric_values"] == [0.0015]


def test_validate_claim_parses_leading_dot_p_value() -> None:
    sections = {
        "results": "Rapamycin treatment reduced hypertrophy (p = .012).",
    }
    claim, reason = rescue._validate_claim(
        raw={
            "claim_type": "p_value",
            "raw_text": "p = .012",
            "source_sentence": sections["results"],
            "source_section": "results",
            "endpoint": "cardiac function",
            "arm": "rapamycin",
            "direction": "decrease",
        },
        paper_id="P1",
        sections=sections,
        endpoint_map={"cardiac function": "cardiometabolic"},
        allowed_arms={"rapamycin"},
        model="test-model",
    )
    assert reason == "accepted"
    assert claim is not None
    assert claim["numeric_values"] == [0.012]


def test_validate_claim_rejects_non_source_or_unknown_endpoint() -> None:
    sections = {"abstract": "Rapamycin increased survival (p=0.0015)."}
    claim, reason = rescue._validate_claim(
        raw={
            "claim_type": "p_value",
            "raw_text": "p=0.0015",
            "source_sentence": "Rapamycin increased survival (p=0.0015).",
            "source_section": "abstract",
            "endpoint": "invented endpoint",
            "arm": "rapamycin",
            "direction": "increase",
        },
        paper_id="P1",
        sections=sections,
        endpoint_map={"pathogen survival": "immune"},
        allowed_arms={"rapamycin"},
        model="test-model",
    )
    assert claim is None
    assert reason == "unknown_endpoint"


def test_validate_claim_rejects_prose_fragment_as_raw_text() -> None:
    sentence = (
        "Proteome half-lives of old hearts significantly increased after "
        "short-term CR (30%) or rapamycin (12%)."
    )
    claim, reason = rescue._validate_claim(
        raw={
            "claim_type": "percentage",
            "raw_text": "Proteome half-lives of old hearts significantly increased after short-term CR (30%) or rapamycin (12%)",
            "source_sentence": sentence,
            "source_section": "abstract",
            "endpoint": "proteome turnover",
            "arm": "rapamycin",
            "direction": "increase",
        },
        paper_id="P1",
        sections={"abstract": sentence},
        endpoint_map={"proteome turnover": "mechanism"},
        allowed_arms={"rapamycin"},
        model="test-model",
    )
    assert claim is None
    assert reason == "bad_raw_text_shape"


def test_validate_claim_rejects_number_belonging_to_prior_comparator() -> None:
    sentence = (
        "However, proteome half-lives of old hearts significantly increased "
        "after short-term CR (30%) or rapamycin (12%)."
    )
    claim, reason = rescue._validate_claim(
        raw={
            "claim_type": "percentage",
            "raw_text": "30%",
            "source_sentence": sentence,
            "source_section": "abstract",
            "endpoint": "proteome turnover",
            "arm": "rapamycin",
            "direction": "increase",
        },
        paper_id="P1",
        sections={"abstract": sentence},
        endpoint_map={"proteome turnover": "mechanism"},
        allowed_arms={"rapamycin"},
        model="test-model",
    )
    assert claim is None
    assert reason == "arm_does_not_precede_raw_text"


def test_apply_claims_appends_without_duplicate(tmp_path) -> None:
    quant = tmp_path / "P1.quant_claims.json"
    quant.write_text(json.dumps({
        "paper_id": "P1",
        "doi": "",
        "claims_count_by_type": {},
        "claims": [],
    }))
    paper = rescue.CandidatePaper("P1", tmp_path / "P1.paper_sections.json", quant, "", "")
    claim = {
        "claim_id": "c1",
        "claim_type": "p_value",
        "raw_text": "p=0.01",
        "numeric_values": [0.01],
        "units": "",
        "source_section": "abstract",
        "source_offset": 10,
        "sentence": "Rapamycin increased survival (p=0.01).",
        "context_window": "Rapamycin increased survival (p=0.01).",
        "claim_role": "effect",
        "endpoint": "pathogen survival",
        "arm": "rapamycin",
        "direction": "increase",
        "binding_confidence": "high",
    }
    rescue._apply_claims(paper, [claim, claim])
    data = json.loads(quant.read_text())
    assert len(data["claims"]) == 1
    assert data["claims_count_by_type"] == {"p_value": 1}


def test_apply_claims_upgrades_matching_partial_claim(tmp_path) -> None:
    quant = tmp_path / "P1.quant_claims.json"
    sentence = "Sirolimus treatment increased CD8 T cells (p = .031)."
    quant.write_text(json.dumps({
        "paper_id": "P1",
        "doi": "",
        "claims_count_by_type": {"p_value": 1},
        "claims": [{
            "claim_id": "old",
            "claim_type": "p_value",
            "raw_text": "p = .031",
            "numeric_values": [0.031],
            "units": "",
            "source_section": "results",
            "source_offset": 10,
            "sentence": sentence,
            "context_window": sentence,
            "claim_role": "duration",
            "endpoint": "T-cell function",
            "arm": "sirolimus",
            "direction": "increase",
            "binding_confidence": "partial",
        }],
    }))
    paper = rescue.CandidatePaper("P1", tmp_path / "P1.paper_sections.json", quant, "", "")
    replacement = {
        "claim_id": "new",
        "claim_type": "p_value",
        "raw_text": "p = .031",
        "numeric_values": [0.031],
        "units": "",
        "source_section": "results",
        "source_offset": 10,
        "sentence": sentence,
        "context_window": sentence,
        "claim_role": "effect",
        "endpoint": "T-cell function",
        "arm": "sirolimus",
        "direction": "increase",
        "binding_confidence": "high",
    }
    rescue._apply_claims(paper, [replacement])
    data = json.loads(quant.read_text())
    assert len(data["claims"]) == 1
    assert data["claims"][0]["claim_id"] == "new"
    assert data["claims"][0]["binding_confidence"] == "high"
