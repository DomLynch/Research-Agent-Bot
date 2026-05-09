from __future__ import annotations

import json
import re

import qualification_rescue as rescue


def _patterns(*labels: str) -> dict[str, re.Pattern[str]]:
    return {label: re.compile(re.escape(label), re.IGNORECASE) for label in labels}


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
        endpoint_patterns={
            "pathogen survival": re.compile(r"post infection survival|survival rate"),
        },
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
        endpoint_patterns={"cardiac function": re.compile(r"hypertrophy")},
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
        endpoint_patterns=_patterns("pathogen survival"),
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
        endpoint_patterns={"proteome turnover": re.compile(r"proteome|half-lives")},
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
        endpoint_patterns={"proteome turnover": re.compile(r"proteome|half-lives")},
        allowed_arms={"rapamycin"},
        model="test-model",
    )
    assert claim is None
    assert reason == "arm_does_not_precede_raw_text"


def test_validate_claim_accepts_preceding_arm_context_for_survival() -> None:
    prior = (
        "Rapamycin was administered in food to genetically heterogeneous mice "
        "and produced significant increases in life span."
    )
    sentence = "Median survival was extended by an average of 10% in males."
    claim, reason = rescue._validate_claim(
        raw={
            "claim_type": "percentage",
            "raw_text": "10%",
            "source_sentence": sentence,
            "source_section": "abstract",
            "source_context": prior,
            "endpoint": "lifespan",
            "arm": "rapamycin",
            "direction": "increase",
        },
        paper_id="P1",
        sections={"abstract": f"{prior} {sentence}"},
        endpoint_map={"lifespan": "longevity"},
        endpoint_patterns={"lifespan": re.compile(r"median\s+survival", re.IGNORECASE)},
        allowed_arms={"rapamycin"},
        model="deterministic",
    )
    assert reason == "accepted"
    assert claim is not None
    assert claim["arm"] == "rapamycin"


def test_validate_claim_rejects_context_arm_without_carry_forward_cue() -> None:
    prior = "Rapamycin was administered in food."
    sentence = "Female mice weighed 10% less than controls."
    claim, reason = rescue._validate_claim(
        raw={
            "claim_type": "percentage",
            "raw_text": "10%",
            "source_sentence": sentence,
            "source_section": "abstract",
            "source_context": prior,
            "endpoint": "body weight",
            "arm": "rapamycin",
            "direction": "decrease",
        },
        paper_id="P1",
        sections={"abstract": f"{prior} {sentence}"},
        endpoint_map={"body weight": "cardiometabolic"},
        endpoint_patterns={"body weight": re.compile(r"weigh", re.IGNORECASE)},
        allowed_arms={"rapamycin"},
        model="deterministic",
    )
    assert claim is None
    assert reason == "arm_not_in_sentence"


def test_repair_existing_partials_promotes_contextual_survival_claim(tmp_path) -> None:
    prior = (
        "Rapamycin was administered in food to genetically heterogeneous mice "
        "from the age of 9 months and produced significant increases in life span."
    )
    sentence = "Median survival was extended by an average of 10% in males."
    parsed = tmp_path / "P1.paper_sections.json"
    parsed.write_text(json.dumps({
        "paper_id": "P1",
        "sections": {"abstract": f"{prior} {sentence}"},
    }))
    quant = tmp_path / "P1.quant_claims.json"
    quant.write_text(json.dumps({
        "paper_id": "P1",
        "claims": [{
            "claim_type": "percentage",
            "raw_text": "10%",
            "sentence": sentence,
            "source_section": "abstract",
            "claim_role": "unknown",
            "endpoint": "",
            "arm": "",
            "direction": "increase",
            "binding_confidence": "partial",
        }],
    }))
    paper = rescue.CandidatePaper("P1", parsed, quant, "", "")
    row = rescue._repair_existing_partials(
        paper,
        endpoint_map={"lifespan": "longevity"},
        endpoint_patterns={"lifespan": re.compile(r"median\s+survival", re.IGNORECASE)},
        arms={"rapamycin"},
        max_chars=1000,
    )
    assert row["accepted"] == 1
    claim = row["claims"][0]
    assert claim["binding_confidence"] == "high"
    assert claim["endpoint"] == "lifespan"
    assert claim["rescue_method"] == "deterministic_partial_repair_v1"


def test_repair_existing_partials_rejects_discussion_background(tmp_path) -> None:
    sentence = "Rapamycin extends lifespan by 10% or more in mice."
    parsed = tmp_path / "P1.paper_sections.json"
    parsed.write_text(json.dumps({
        "paper_id": "P1",
        "sections": {"discussion": sentence},
    }))
    quant = tmp_path / "P1.quant_claims.json"
    quant.write_text(json.dumps({
        "paper_id": "P1",
        "claims": [{
            "claim_type": "percentage",
            "raw_text": "10%",
            "sentence": sentence,
            "source_section": "discussion",
            "endpoint": "lifespan",
            "arm": "rapamycin",
            "direction": "increase",
            "binding_confidence": "partial",
        }],
    }))
    row = rescue._repair_existing_partials(
        rescue.CandidatePaper("P1", parsed, quant, "", ""),
        endpoint_map={"lifespan": "longevity"},
        endpoint_patterns={"lifespan": re.compile(r"lifespan", re.IGNORECASE)},
        arms={"rapamycin"},
        max_chars=1000,
    )
    assert row["accepted"] == 0
    assert row["rejected"] == {"source_section_not_allowed": 1}


def test_validate_claim_rejects_endpoint_without_source_support() -> None:
    sentence = (
        "RAD001 treatment counter-regulated expression of 37% of the "
        "age-regulated genes in the kidney."
    )
    claim, reason = rescue._validate_claim(
        raw={
            "claim_type": "percentage",
            "raw_text": "37%",
            "source_sentence": sentence,
            "source_section": "abstract",
            "endpoint": "mTOR signaling",
            "arm": "RAD001",
            "direction": "decrease",
        },
        paper_id="P1",
        sections={"abstract": sentence},
        endpoint_map={"mTOR signaling": "cardiometabolic"},
        endpoint_patterns={"mTOR signaling": re.compile(r"\bmTOR\b", re.IGNORECASE)},
        allowed_arms={"rad001"},
        model="test-model",
    )
    assert claim is None
    assert reason == "endpoint_not_in_sentence"


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
