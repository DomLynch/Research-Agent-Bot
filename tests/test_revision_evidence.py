from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import cast

import agent.revision_evidence as revision_evidence
from agent.revision_evidence import (
    SNAPSHOT_DIR,
    create_revision_evidence_snapshot,
    load_revision_evidence,
    receipt_contract_mismatches,
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
    snapshot_manifest = source / SNAPSHOT_DIR / "manifest.json"
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
