from __future__ import annotations

import dataclasses
import json
from importlib import import_module
from pathlib import Path
from typing import Any, cast

import agent.revision_evidence as revision_evidence
import pytest
from agent.revision_evidence import (
    SNAPSHOT_DIR,
    create_revision_evidence_snapshot,
    load_revision_evidence,
    receipt_contract_mismatches,
    reviewer_unavailable_source_dois,
)
from agent.synthesis_schemas import ReceiptSummary


def _receipt() -> ReceiptSummary:
    return ReceiptSummary(
        receipt_id="r1", receipt_path="r1.quant_claims.json", topic="statins",
        thesis_text="Bound claim.", spar_verdict="accept_clean", n_claims=2,
        n_failed_traces=0, canonical_trial_id=None, evidence_tier="A1",
        directness="direct", outcome_class="cardiometabolic",
        effect_direction="positive", p_values=("P < 0.05",),
        population_summary="adults", source_title="Trial", source_year=2024,
        source_doi="10.1/example", source_pmid="123", source_venue="Journal",
    )


def _contract(receipt: ReceiptSummary) -> dict[str, object]:
    return {
        key: list(value) if key == "p_values" else value
        for key, value in dataclasses.asdict(receipt).items()
    }


def test_revision_review_uses_complete_verified_abstract_without_contract_mutation(tmp_path: Path) -> None:
    from agent.revision_contract import evidence_rows
    from agent.revision_quality import _revision_note, resolved_effect_direction

    raw = tmp_path / "raw"
    raw.mkdir()
    abstract = "Baseline characteristics were similar (P > .05). Negative symptoms improved (P < . 001)."
    (raw / "r1.quant_claims.json").write_text('{"paper_id":"r1"}')
    sections = {"abstract": abstract, "results": "100% survival in both arms."}
    tables = [{"caption": "Trial outcomes", "rows": [["Survival", "100%"]]}]
    (raw / "r1.paper_sections.json").write_text(json.dumps({"sections": sections, "tables": tables}))
    (raw / "citation_registry.json").write_text('{"r1":{"body_citation":"Trial 2024"}}')
    manifest: dict[str, Any] = {"topic": "statins", "receipts": [{**_contract(_receipt()), "thesis_text": "Baseline P > .05."}],
                "revision_evidence_snapshot": {"required": True}}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    assert create_revision_evidence_snapshot(tmp_path, quant_dir=raw, parsed_dir=raw,
        citation_registry=raw / "citation_registry.json", receipt_ids={"r1"})["passed"]
    snapshot = tmp_path / SNAPSHOT_DIR
    before = {p: p.read_bytes() for p in snapshot.rglob("*") if p.is_file()}
    rows = evidence_rows(tmp_path, manifest)
    assert rows[0]["verified_abstract"] == abstract
    assert rows[0]["verified_source_sections"] == sections
    assert rows[0]["verified_source_tables"] == tables
    assert rows[0]["thesis_text"] == "Baseline P > .05."
    assert manifest["receipts"][0]["thesis_text"] == "Baseline P > .05."
    note = _revision_note("statistic", rows[0], 1, "Correct representative statistic consistent with the source excerpt (P < .001 for negative-symptom improvement).")
    assert note and "retains P < .001" in note[1]
    assert before == {p: p.read_bytes() for p in before}
    assert resolved_effect_direction({**rows[0], "effect_direction": "null", "verified_abstract": "Higher inflammation caused harm (P < .05)."}) == "null"
    assert resolved_effect_direction({**rows[0], "effect_direction": "null", "thesis_text": "Higher inflammation can cause harm.", "p_values": ["P < .001"]}) == "null"
    from agent.revision_consistency import disputed_p_value_near_sources, remove_disputed_p_values_near_sources
    ask = "Correct Trial 2024 P = .01 to be consistent with the source excerpt (P = .01)."
    text = "Trial 2024 reports a result P = .01."
    assert not disputed_p_value_near_sources(ask, text, ["Trial 2024"], ["Trial 2024"])
    assert remove_disputed_p_values_near_sources(ask, text, ["Trial 2024"], ["Trial 2024"]) == text
    (snapshot / "parsed" / "r1.paper_sections.json").write_text('{"sections":{"abstract":"invented result"}}')
    with pytest.raises(ValueError, match="snapshot_parsed:r1"):
        evidence_rows(tmp_path, manifest)
    assert evidence_rows(tmp_path / "legacy", {"receipts": manifest["receipts"]}) == manifest["receipts"]


def test_reviewer_unavailable_source_dois_are_explicit_and_exact() -> None:
    feedback = (
        "Submitted evidence has no independently available authoritative text: "
        "doi:10.1000/blocked, doi:10.1000/second."
    )
    blocked = reviewer_unavailable_source_dois(feedback)

    assert blocked == {"10.1000/blocked", "10.1000/second"}
    assert reviewer_unavailable_source_dois(
        "No independently available authoritative text: [10.1000/blocked]. "
        "Verified replacement DOI: 10.1000/keep",
    ) == {"10.1000/blocked"}
    assert reviewer_unavailable_source_dois(
        "No independently available authoritative text: 10.1000/blocked; "
        "retain verified DOI 10.1000/keep",
    ) == {"10.1000/blocked"}
    assert reviewer_unavailable_source_dois(
        "No independently available authoritative text: 10.1000/blocked; "
        "however, DOI 10.1000/keep is verified; the verified DOI 10.1000/also-keep",
    ) == {"10.1000/blocked"}
    assert reviewer_unavailable_source_dois(
        "No independently available authoritative text: 10.1000/one; 10.1000/two",
    ) == {"10.1000/one", "10.1000/two"}
    assert reviewer_unavailable_source_dois(
        "Verify these DOI sources against authoritative abstracts: 10.1000/blocked",
    ) == set()


_CLASS_RECODE_ASK = (
    "Reclassify protocol-only, multi-ingredient, within-group-only, and observational "
    "records under the stated directness criteria, recalculate all direct/indirect totals, "
    "and either provide per-source risk-of-bias judgments or remove A1/decision-grade quality implications."
)


@pytest.fixture
def class_recode_rows(tmp_path: Path, request) -> dict[str, dict[str, Any]]:
    from agent.publication_evidence import source_proof_fields

    titles = {
        "protocol": "Trial rationale and study design",
        "combination": "Multi-ingredient supplementation in adults: a randomized trial",
        "observational": "A prospective cohort study of older adults",
        "within": "Pilot supplementation study in adults",
        "trial": "A randomized controlled trial in adults",
        "unknown": "Effects of supplementation",
    }
    rows = {f"r_{key}": {**_contract(_receipt()), "receipt_id": f"r_{key}", "source_title": title}
            for key, title in titles.items()}
    raw = tmp_path / "raw"
    raw.mkdir()
    abstract = getattr(request, "param", "Methods: Only within-group comparisons were performed in this study of supplementation in adults.")
    (raw / "r_within.quant_claims.json").write_text('{"paper_id":"r_within"}')
    (raw / "r_within.paper_sections.json").write_text(json.dumps({"sections": {"abstract": abstract}}))
    (raw / "citation_registry.json").write_text('{}')
    (tmp_path / "manifest.json").write_text(json.dumps({"topic": "statins", "receipts": [rows["r_within"]]}))
    assert create_revision_evidence_snapshot(tmp_path, quant_dir=raw, parsed_dir=raw,
        citation_registry=raw / "citation_registry.json", receipt_ids={"r_within"})["passed"]
    lock = load_revision_evidence(tmp_path, quant_dir=raw, parsed_dir=raw)
    proof_row = {"title": titles["within"], "pmid": "123", "doi": "10.1/example", "excerpt": abstract}
    proof_row.update(source_proof_fields(proof_row, origin="pubmed", evidence=lock,
        topic="statins", receipt_id="r_within"))
    rows["r_within"].update(proof_row)
    return rows


@pytest.mark.parametrize(("ask", "expected"), [
    (_CLASS_RECODE_ASK, {"protocol", "combination", "within", "observational"}),
    ("Reclassify observational records under the directness criteria.", {"observational"}),
    ("Reclassify multi-ingredient records under the directness criteria.", {"combination"}),
    ("Reclassify within-group-only records under the directness criteria.", {"within"}),
    ("Recode all observational studies as indirect evidence.", {"observational"}),
    ("Reclassify protocol-only records as indirect evidence.", {"protocol"}),
    ("Correct the evidence classification of multi-ingredient records.", {"combination"}),
    ("Reclassify multi-ingredient and observational evidence; reconcile directness criteria.", set()),
    ("Recode the multi-ingredient and observational studies to correct their evidence tier.", {"combination", "observational"}),
    ("Reclassify observational records without changing their directness.", set()),
    ("Do not " + _CLASS_RECODE_ASK.lower(), set()),
    ("Never " + _CLASS_RECODE_ASK.lower(), set()),
    ("Discuss multi-ingredient and observational records under the directness criteria.", set()),
    ("Reclassify the Methods headings; discuss observational directness criteria.", set()),
    ("Reclassify protocol-only records under the directness criteria; do not reclassify observational records.", {"protocol"}),
    ("Reclassify observational records except selected studies under the directness criteria.", set()),
])
def test_source_validated_class_recode_authorization(class_recode_rows, ask, expected) -> None:
    authorized_receipt_contract_fields_by_receipt = import_module("scripts.revision_coverage").authorized_receipt_contract_fields_by_receipt

    before = json.dumps(class_recode_rows, sort_keys=True)
    allowed = authorized_receipt_contract_fields_by_receipt(ask, class_recode_rows)
    assert allowed == {f"r_{key}": {"directness", "evidence_tier"} for key in expected}
    assert json.dumps(class_recode_rows, sort_keys=True) == before


def test_class_recode_rejects_unverified_evidence_and_identity_drift(class_recode_rows) -> None:
    authorized_receipt_contract_fields_by_receipt = import_module("scripts.revision_coverage").authorized_receipt_contract_fields_by_receipt

    within = class_recode_rows["r_within"]
    for changes in (
        {"excerpt": within["excerpt"] + " Invented details."},
        {"pmid": "999"},
        {"title": "A different source"},
        {"evidence_origin": "model"},
    ):
        row = {**within, **changes, "verified_abstract": within["excerpt"]}
        assert authorized_receipt_contract_fields_by_receipt(_CLASS_RECODE_ASK, {"r_within": row}) == {}
    row = {**class_recode_rows["r_unknown"], "directness": "indirect", "evidence_tier": "B2",
           "thesis_text": within["excerpt"], "verified_abstract": within["excerpt"]}
    assert authorized_receipt_contract_fields_by_receipt(_CLASS_RECODE_ASK, {"observational_id": row}) == {}


@pytest.mark.parametrize(("class_recode_rows", "expected"), [
    ("Methods: This prospective observational cohort study followed older adults receiving supplementation for six months.", True),
    ("Methods: Adults received a multi-ingredient supplement or placebo in this randomized clinical trial.", True),
    ("Background: Only within-group comparisons were performed in previous trials. Methods: We studied supplementation in adults.", False),
    ("Methods: No multi-ingredient supplement was administered in this clinical study of older adults.", False),
    ("Methods: Only within-group comparisons were performed at baseline in this randomized controlled trial of adults.", False),
], indirect=["class_recode_rows"])
def test_class_recode_uses_own_verified_methods_not_background(class_recode_rows, expected) -> None:
    authorize = import_module("scripts.revision_coverage").authorized_receipt_contract_fields_by_receipt
    rows = {"r_within": class_recode_rows["r_within"]}
    assert authorize(_CLASS_RECODE_ASK, rows) == ({"r_within": {"directness", "evidence_tier"}} if expected else {})


@pytest.mark.parametrize("ask", [
    "Reclassify observational records except cohort_a under the directness criteria.",
    "Reclassify observational records excluding Study A as indirect evidence.",
    "Reclassify observational records in women under the directness criteria.",
    "Recode observational studies as indirect evidence among older adults.",
    "Reclassify observational records under the directness criteria for women.",
    "Reclassify cohort_a as indirect evidence only if it enrolled adults.",
    "Reclassify cohort_a as indirect evidence unless it was randomized.",
    "Reclassify observational records, not cohort_a, under the directness criteria.",
    "Reclassify observational records, not Study A, under the directness criteria.",
    'Reclassify observational records, not "cohort_a", under the directness criteria.',
    "Reclassify observational records, not (cohort_a), under the directness criteria.",
    "Reclassify observational records, not the cohort_a, under the directness criteria.",
    "Reclassify observational records, not cohort_a or cohort_b, under the directness criteria.",
])
def test_recode_restrictions_precede_named_and_class_authorization(ask) -> None:
    authorize = import_module("scripts.revision_coverage").authorized_receipt_contract_fields_by_receipt
    rows = {"cohort_a": {"source_title": "Prospective cohort study in women"},
            "cohort_b": {"source_title": "Prospective cohort study in men"}}
    aliases = {"cohort_a": ("Study A",)}
    assert authorize(ask, rows, aliases) == {}
    assert authorize("Reclassify cohort_a as indirect evidence.", rows, aliases) == {
        "cohort_a": {"directness", "evidence_tier"},
    }
    assert authorize("Recode cohort_a as a primary RCT, not a review; correct directness and tier.", rows, aliases) == {
        "cohort_a": {"directness", "evidence_tier"},
    }


@pytest.mark.parametrize(("template", "allowed"), [
    ("Reclassify {title} as indirect evidence.", True),
    ("Reclassify {title} as indirect evidence for older adults.", False),
    ("Reclassify observational records except {title} under the directness criteria.", False),
])
def test_recode_masks_source_identity_but_not_external_restrictions(template, allowed) -> None:
    authorize = import_module("scripts.revision_coverage").authorized_receipt_contract_fields_by_receipt
    title = "Effects of supplementation in women"
    rows = {"r1": {"source_title": title}}
    assert authorize(template.format(title=title), rows, {"r1": ("Effects",)}) == (
        {"r1": {"directness", "evidence_tier"}} if allowed else {}
    )


def test_snapshot_source_methods_reach_runner_authorization(tmp_path: Path) -> None:
    from agent.publication_evidence import source_proof_is_valid

    coverage = import_module("scripts.revision_coverage")
    authorize = coverage.authorized_receipt_contract_fields_by_receipt
    raw = tmp_path / "raw"
    raw.mkdir()
    row = _contract(_receipt())
    abstract = "Methods: Only within-group comparisons were performed in this study of supplementation in adults."
    (raw / "r1.quant_claims.json").write_text('{"paper_id":"r1"}')
    (raw / "r1.paper_sections.json").write_text(json.dumps({"sections": {"abstract": abstract}}))
    (raw / "citation_registry.json").write_text('{}')
    (tmp_path / "manifest.json").write_text(json.dumps({"topic": "statins", "receipts": [row]}))
    assert create_revision_evidence_snapshot(tmp_path, quant_dir=raw, parsed_dir=raw,
        citation_registry=raw / "citation_registry.json", receipt_ids={"r1"})["passed"]
    lock = load_revision_evidence(tmp_path, quant_dir=raw, parsed_dir=raw, expected_topic="statins")
    assert not lock.errors
    assert authorize(_CLASS_RECODE_ASK, lock.receipt_rows) == {}
    before = {p: p.read_bytes() for p in (tmp_path / SNAPSHOT_DIR).rglob("*") if p.is_file()}
    frozen_rows = json.dumps(lock.receipt_rows, sort_keys=True)
    enriched = coverage.snapshot_recode_rows(lock)
    assert source_proof_is_valid(enriched["r1"])
    assert enriched["r1"]["excerpt"] == abstract
    assert all(enriched["r1"][key] == value for key, value in lock.receipt_rows["r1"].items())
    assert authorize(_CLASS_RECODE_ASK, enriched) == {"r1": {"directness", "evidence_tier"}}
    assert json.dumps(lock.receipt_rows, sort_keys=True) == frozen_rows
    assert before == {p: p.read_bytes() for p in before}
    (lock.parsed_dir / "r1.paper_sections.json").write_text('{"sections":{"abstract":"tampered"}}')
    assert coverage.snapshot_recode_rows(lock) == {}


def test_snapshot_hashes_quant_and_parsed_inputs(tmp_path: Path, monkeypatch) -> None:
    quant = tmp_path / "current" / "quant_claims"
    parsed = tmp_path / "current" / "parsed"
    quant.mkdir(parents=True)
    parsed.mkdir(parents=True)
    (quant / "r1.quant_claims.json").write_text('{"paper_id":"r1"}')
    (parsed / "r1.paper_sections.json").write_text('{"paper_id":"r1"}')
    citations = tmp_path / "citation_registry.json"
    citations.write_text('{"r1":{"body_citation":"Trial 2024"}}')
    source = tmp_path / "source"
    source.mkdir()
    (source / "manifest.json").write_text(json.dumps({
        "topic": "statins",
        "receipts": [_contract(_receipt())],
        "revision_evidence_snapshot": {
            "required": True,
            "manifest": f"{SNAPSHOT_DIR}/manifest.json",
        },
    }))

    report = create_revision_evidence_snapshot(
        source, quant_dir=quant, parsed_dir=parsed,
        citation_registry=citations, receipt_ids={"r1"},
    )
    lock = load_revision_evidence(
        source, quant_dir=quant, parsed_dir=parsed, expected_topic="statins",
    )

    assert report["passed"] is True
    assert lock.mode == "snapshot"
    assert lock.errors == ()
    assert lock.citation_registry is not None
    snapshot_manifest = source / SNAPSHOT_DIR / "manifest.json"
    snapshot_bytes = snapshot_manifest.read_bytes()
    snapshot_manifest.write_bytes(b"\xff")
    assert "snapshot_manifest:UnicodeDecodeError" in load_revision_evidence(
        source, quant_dir=quant, parsed_dir=parsed,
    ).errors
    snapshot_manifest.write_bytes(snapshot_bytes)
    source_manifest = json.loads((source / "manifest.json").read_text())
    assert "source_topic_mismatch" in load_revision_evidence(
        source, quant_dir=quant, parsed_dir=parsed, expected_topic="aspirin",
    ).errors
    source_manifest["topic"] = "aspirin"
    (source / "manifest.json").write_text(json.dumps(source_manifest))
    assert "source_manifest_topic_drift" in load_revision_evidence(
        source, quant_dir=quant, parsed_dir=parsed, expected_topic="statins",
    ).errors
    source_manifest["topic"] = "statins"
    source_manifest["receipts"][0]["spar_verdict"] = "reject"
    source_manifest["receipts"][0]["n_failed_traces"] = 4
    (source / "manifest.json").write_text(json.dumps(source_manifest))
    contract_drift = load_revision_evidence(
        source, quant_dir=quant, parsed_dir=parsed, expected_topic="statins",
    ).errors
    assert "source_manifest_contract_drift:r1" in contract_drift
    source_manifest["receipts"][0]["spar_verdict"] = "accept_clean"
    source_manifest["receipts"][0]["n_failed_traces"] = 0
    del source_manifest["receipts"][0]["n_claims"]
    (source / "manifest.json").write_text(json.dumps(source_manifest))
    assert "source_manifest_contract_drift:r1" in load_revision_evidence(
        source, quant_dir=quant, parsed_dir=parsed, expected_topic="statins",
    ).errors
    source_manifest["receipts"][0]["n_claims"] = 2
    source_manifest["receipts"][0]["n_claims"] = 3
    (source / "manifest.json").write_text(json.dumps(source_manifest))
    drifted = load_revision_evidence(source, quant_dir=quant, parsed_dir=parsed)
    assert drifted.receipt_rows["r1"]["n_claims"] == 2
    assert "source_manifest_contract_drift:r1" in drifted.errors
    source_manifest["receipts"][0]["n_claims"] = 2
    (source / "manifest.json").write_text(json.dumps(source_manifest))
    snapshot_payload = json.loads(snapshot_manifest.read_text())
    snapshot_payload["receipt_contracts"]["r1"]["n_claims"] = 3
    snapshot_manifest.write_text(json.dumps(snapshot_payload))
    assert "snapshot_receipt_contracts" in load_revision_evidence(
        source, quant_dir=quant, parsed_dir=parsed,
    ).errors
    snapshot_payload["receipt_contracts"]["r1"]["n_claims"] = 2
    snapshot_payload["receipt_contracts_sha256"] = revision_evidence._json_sha256(
        snapshot_payload["receipt_contracts"],
    )
    snapshot_manifest.write_text(json.dumps(snapshot_payload))
    lock.citation_registry.write_text('{"r1":{"body_citation":"Tampered"}}')
    assert "snapshot_citation_registry" in load_revision_evidence(
        source, quant_dir=quant, parsed_dir=parsed,
    ).errors
    lock.citation_registry.write_text('{"r1":{"body_citation":"Trial 2024"}}')
    (lock.quant_dir / "r1.quant_claims.json").write_text('{"paper_id":"changed"}')
    assert "snapshot_quant_claims:r1" in load_revision_evidence(
        source, quant_dir=quant, parsed_dir=parsed,
    ).errors
    (lock.quant_dir / "r1.quant_claims.json").write_text('{"paper_id":"r1"}')
    real_sha256 = revision_evidence._sha256
    monkeypatch.setattr(
        revision_evidence,
        "_sha256",
        lambda path: (_ for _ in ()).throw(OSError("unreadable"))
        if path.name == "r1.quant_claims.json"
        else real_sha256(path),
    )
    assert "snapshot_quant_claims:r1" in load_revision_evidence(
        source, quant_dir=quant, parsed_dir=parsed,
    ).errors
    monkeypatch.setattr(revision_evidence, "_sha256", real_sha256)
    (source / SNAPSHOT_DIR / "manifest.json").unlink()
    missing = load_revision_evidence(source, quant_dir=quant, parsed_dir=parsed)
    assert missing.mode == "invalid"
    assert missing.errors == ("required_snapshot_missing",)


def test_legacy_contract_detects_same_id_content_drift() -> None:
    receipt = _receipt()
    rows = {receipt.receipt_id: _contract(receipt)}

    assert receipt_contract_mismatches([receipt], rows) == []
    assert receipt_contract_mismatches(
        [dataclasses.replace(receipt, effect_direction="negative")], rows,
    ) == ["r1:effect_direction"]
    assert receipt_contract_mismatches(
        [dataclasses.replace(receipt, effect_direction="negative")], rows,
        allowed_fields={"effect_direction"},
    ) == []
    assert receipt_contract_mismatches(
        [dataclasses.replace(receipt, thesis_text="Drifted claim.")], rows,
    ) == ["r1:thesis_text"]
    assert receipt_contract_mismatches(
        [dataclasses.replace(receipt, population_summary="different population")], rows,
    ) == ["r1:population_summary"]


def test_snapshot_allows_only_explicitly_authorized_contract_field(tmp_path: Path) -> None:
    quant = tmp_path / "quant"
    parsed = tmp_path / "parsed"
    source = tmp_path / "source"
    source.mkdir()

    def _write(path: Path, value: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))

    _write(quant / "r1.quant_claims.json", {"paper_id": "r1"})
    _write(parsed / "r1.paper_sections.json", {"paper_id": "r1"})
    _write(source / "citation_registry.json", {"r1": {"body_citation": "Trial 2024"}})
    manifest: dict[str, Any] = {
        "topic": "statins", "receipts": [_contract(_receipt())],
        "revision_evidence_snapshot": {"required": True},
    }
    _write(source / "manifest.json", manifest)
    create_revision_evidence_snapshot(
        source, quant_dir=quant, parsed_dir=parsed,
        citation_registry=source / "citation_registry.json", receipt_ids={"r1"},
        topic="statins",
    )
    manifest["receipts"][0]["effect_direction"] = "negative"
    _write(source / "manifest.json", manifest)

    assert "source_manifest_contract_drift:r1" in load_revision_evidence(
        source, quant_dir=quant, parsed_dir=parsed, expected_topic="statins",
    ).errors
    assert load_revision_evidence(
        source, quant_dir=quant, parsed_dir=parsed, expected_topic="statins",
        authorized_contract_fields={"r1": {"effect_direction"}},
    ).errors == ()


def test_contract_allows_only_deterministic_animal_directness_normalization() -> None:
    animal = dataclasses.replace(
        _receipt(),
        directness="indirect",
        source_title="Randomized veterinary trial in overweight cats",
        population_summary="overweight cats",
    )
    legacy_animal = _contract(dataclasses.replace(animal, directness="direct"))

    assert receipt_contract_mismatches([animal], {"r1": legacy_animal}) == []
    assert receipt_contract_mismatches(
        [dataclasses.replace(_receipt(), directness="indirect")],
        {"r1": _contract(_receipt())},
    ) == ["r1:directness"]


def test_legacy_contract_rejects_cross_topic_revision(tmp_path: Path) -> None:
    source = tmp_path / "legacy"
    source.mkdir()
    (source / "manifest.json").write_text(json.dumps({
        "topic": "statins", "receipts": [_contract(_receipt())],
    }))

    lock = load_revision_evidence(
        source, quant_dir=tmp_path / "quant", parsed_dir=tmp_path / "parsed",
        expected_topic="aspirin",
    )

    assert lock.mode == "invalid"
    assert lock.errors == ("source_topic_mismatch",)


def test_non_object_source_manifest_fails_closed(tmp_path: Path) -> None:
    payloads: tuple[object, ...] = ([], None, "bad")
    for index, payload in enumerate(payloads):
        source = tmp_path / str(index)
        source.mkdir()
        (source / "manifest.json").write_text(json.dumps(payload))

        lock = load_revision_evidence(
            source, quant_dir=tmp_path / "quant", parsed_dir=tmp_path / "parsed",
        )

        assert lock.mode == "invalid"
        assert lock.errors == ("source_manifest:ValueError",)


def test_malformed_n_claims_contracts_fail_closed(tmp_path: Path) -> None:
    receipt = _receipt()
    valid_row = _contract(receipt)
    for value in (True, 1.0, -1):
        malformed_receipt = dataclasses.replace(receipt, n_claims=cast(int, value))
        assert receipt_contract_mismatches(
            [malformed_receipt], {"r1": valid_row},
        ) == ["r1:n_claims"]
    for value in (True, 1.0, -1):
        row = _contract(receipt)
        row["n_claims"] = value
        assert receipt_contract_mismatches([receipt], {"r1": row}) == ["r1:n_claims"]
        source = tmp_path / str(value)
        source.mkdir()
        (source / "manifest.json").write_text(json.dumps({"receipts": [row]}))
        lock = load_revision_evidence(
            source, quant_dir=tmp_path / "quant", parsed_dir=tmp_path / "parsed",
        )
        assert lock.mode == "invalid"
        assert lock.errors == ("source_manifest:ValueError",)
