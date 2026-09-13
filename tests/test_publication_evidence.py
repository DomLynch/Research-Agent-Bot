import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from agent.publication_evidence import SOURCE_IDENTITY_FIELDS, source_proof_fields, source_proof_is_valid
from agent.revision_evidence import RevisionEvidenceLock

ABSTRACT = "The randomized trial assessed treatment outcomes in the enrolled adult population."
RESULT = "At follow-up, the primary outcome improved by 12 percent in the treatment group."
INTERNAL_FIELDS = {"pmcid", "source_snapshot_locator", "source_passage_locator", "excerpt_is_complete_field"}


@pytest.fixture
def frozen_source(tmp_path):
    parsed = tmp_path / "run" / "revision_evidence_snapshot" / "parsed"
    parsed.mkdir(parents=True)
    evidence = RevisionEvidenceLock(
        tmp_path / "run", {"r1": {"topic": "test"}}, tmp_path, parsed, None, "snapshot",
    )

    def make(sections, **metadata):
        raw = json.dumps({"sections": sections, **metadata}).encode()
        (parsed / "r1.paper_sections.json").write_bytes(raw)
        return evidence, raw

    return make


def proof(row, evidence, origin="full_text"):
    return source_proof_fields(row, origin=origin, evidence=evidence, topic="test", receipt_id="r1")


@pytest.mark.parametrize(("sections", "row", "metadata", "origin", "locator"), [
    ({"abstract": ABSTRACT, "results": RESULT}, {"excerpt": ABSTRACT, "pmid": "12345678"}, {},
     "pubmed", "https://pubmed.ncbi.nlm.nih.gov/12345678/"),
    ({"abstract": ABSTRACT, "results": RESULT}, {"excerpt": RESULT, "pmcid": "pmc1234567"}, {},
     "full_text", "https://pmc.ncbi.nlm.nih.gov/articles/PMC1234567/"),
    ({"results": RESULT}, {"excerpt": RESULT, "doi": "10.1234/study"}, {},
     "full_text", "https://doi.org/10.1234/study"),
    ({"methods": RESULT}, {"excerpt": RESULT}, {"source_pdf": "https://publisher.example/paper.pdf"},
     "full_text", "https://publisher.example/paper.pdf"),
    ({"abstract": ABSTRACT}, {"excerpt": ABSTRACT, "url": "https://publisher.example/paper"}, {},
     "publisher", "https://publisher.example/paper"),
    ({"results": ABSTRACT, "Abstract": ABSTRACT}, {"excerpt": ABSTRACT, "source_type": "pubmed", "id": "12345678"}, {},
     "pubmed", "https://pubmed.ncbi.nlm.nih.gov/12345678/"),
])
def test_proof_matches_frozen_section_and_retrievable_locator(frozen_source, sections, row, metadata, origin, locator):
    evidence, raw = frozen_source(sections, **metadata)
    row = {"title": "Frozen source", "quote": row["excerpt"], **row}
    fields = proof(row, evidence)
    assert fields["evidence_origin"] == origin
    assert fields["source_record_locator"] == locator
    assert not INTERNAL_FIELDS.intersection(SOURCE_IDENTITY_FIELDS)
    assert "pmcid" not in fields
    assert fields["source_snapshot_locator"] == "revision-snapshot:run:test:r1"
    assert fields["source_passage_locator"] in {f"sections.{name}" for name in sections}
    if origin != "full_text":
        assert fields["source_passage_locator"].lower() == "sections.abstract"
    assert (evidence.parsed_dir / "r1.paper_sections.json").read_bytes() == raw
    assert fields["source_record_hash"] == "sha256:" + hashlib.sha256(raw).hexdigest()
    assert fields["source_content_hash"] == "sha256:" + hashlib.sha256(row["excerpt"].encode()).hexdigest()
    assert fields["quote_verified"] is True
    assert fields["excerpt_is_complete_field"] is True
    assert source_proof_is_valid({**row, **fields})
    assert source_proof_is_valid({key: value for key, value in {**row, **fields}.items() if key not in INTERNAL_FIELDS})
    assert not source_proof_is_valid({**row, **fields, "source_record_locator": locator + "changed"})
    assert not source_proof_is_valid({**row, **fields, "quote": "A different unverified source quotation."})


@pytest.mark.parametrize(("sections", "metadata"), [
    ({"abstract": ABSTRACT}, {"title": RESULT}), ({}, {"title": RESULT}),
    ({"abstract": RESULT.partition("improved")[0], "results": "improved" + RESULT.partition("improved")[2]}, {}),
])
def test_excerpt_absent_from_a_single_section_has_no_proof(frozen_source, sections, metadata):
    evidence, _ = frozen_source(sections, **metadata)
    assert proof({"excerpt": RESULT, "doi": "10.1234/study"}, evidence) == {}


def test_proof_requires_retrievable_locator_and_intact_snapshot(frozen_source):
    evidence, _ = frozen_source({"results": RESULT}, source_pdf="/local/source.pdf")
    assert proof({"excerpt": RESULT, "title": "Local snapshot only"}, evidence) == {}
    row = {"excerpt": RESULT, "doi": "10.1234/study"}
    assert proof(row, replace(evidence, errors=("hash_mismatch",))) == {}
    assert proof(row, replace(evidence, mode="live")) == {}
    assert proof(row, replace(evidence, receipt_rows={"r1": {"topic": "other"}})) == {}
    (evidence.parsed_dir / "r1.paper_sections.json").unlink()
    assert proof(row, evidence) == {}


def test_complete_sections_can_travel_together_without_fabricated_splices(frozen_source):
    evidence, _ = frozen_source({"abstract": ABSTRACT, "results": RESULT})
    row = {"excerpt": ABSTRACT + "\n\n" + RESULT, "quote": RESULT, "doi": "10.1234/study"}
    fields = proof(row, evidence)
    assert fields["source_passage_locator"] == "sections.abstract;sections.results"
    assert fields["excerpt_is_complete_field"] is True
    assert source_proof_is_valid({**row, **fields})
    for excerpt in (ABSTRACT + "\n\n" + RESULT.replace("12", "21"),
                    ABSTRACT + "\n\n" + RESULT.partition(", ")[2],
                    ABSTRACT + "\n\n" + RESULT + " Invented context."):
        assert proof({**row, "excerpt": excerpt}, evidence) == {}
        assert not source_proof_is_valid({**row, **fields, "excerpt": excerpt})


@pytest.mark.parametrize("locator", ["https://[", "file:///local/source.pdf", "revision-snapshot:run:test:r1"])
def test_invalid_locator_does_not_block_doi_fallback(frozen_source, locator):
    evidence, _ = frozen_source({"results": RESULT}, source_pdf=locator)
    assert proof({"excerpt": RESULT}, evidence) == {}
    row = {"excerpt": RESULT, "doi": "https://doi.org/10.1234/study"}
    fields = proof(row, evidence, origin="pubmed")
    assert fields["evidence_origin"] == "full_text"
    assert fields["source_record_locator"] == "https://doi.org/10.1234/study"
    assert source_proof_is_valid({**row, **fields})


def test_build_payload_strips_internal_proof_fields(frozen_source, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    from scripts.publishing import submission

    evidence, _ = frozen_source({"abstract": ABSTRACT, "results": RESULT})
    source = {"title": "Frozen source", "excerpt": RESULT, "quote": RESULT, "pmcid": "PMC1234567"}
    source.update(proof(source, evidence))
    run = evidence.source_run
    (run / "full_paper.md").write_text(f"# Frozen source\n\n## Abstract\n\n{RESULT}\n")
    (run / "manifest.json").write_text(json.dumps({"topic": "test", "n_receipts": 1}))
    monkeypatch.setattr(submission, "_source_bundle", lambda *args, **kwargs: [dict(source)])
    payload = submission.build_payload(run, enrich_sources=False)
    outgoing = payload["source_bundle"][0]
    assert not INTERNAL_FIELDS.intersection(outgoing)
    assert source["source_snapshot_locator"] == "revision-snapshot:run:test:r1"
    assert source["source_passage_locator"] == "sections.results"
    assert outgoing["source_identity_hash"] == source["source_identity_hash"]
    assert source_proof_is_valid(outgoing)
