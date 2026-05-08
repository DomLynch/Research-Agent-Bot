"""Fixture-only BRIEFS-V1 bundle e2e tests."""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import generate_brief  # noqa: E402


def _run_dir(tmp_path: Path) -> Path:
    run = tmp_path / "runs" / "synthesis-demo-v06-L5"
    run.mkdir(parents=True)
    (run / "full_paper.md").write_text("# Demo paper\n", encoding="utf-8")
    (run / "citation_registry.json").write_text(
        json.dumps({
            "Alpha 2024": {"receipt_id": "demo-r1"},
            "Beta 2023": {"receipt_id": "demo-r2"},
            "RegistryOnly 2022": {"receipt_id": "registry-only"},
        }),
        encoding="utf-8",
    )
    (run / "manifest.json").write_text(
        json.dumps({
            "topic": "demo",
            "n_receipts": 2,
            "receipts": [
                {
                    "receipt_id": "demo-r1",
                    "paper_id": "paper-1",
                    "citation_token": "Alpha 2024",
                    "source_title": "Demo cognition trial in older adults",
                    "outcome_class": "cognitive",
                    "evidence_tier": "A1",
                    "directness": "direct",
                    "effect_direction": "positive",
                    "n_claims": 3,
                },
                {
                    "receipt_id": "demo-r2",
                    "paper_id": "paper-2",
                    "citation_token": "Beta 2023",
                    "source_title": "Demo mortality review",
                    "outcome_class": "longevity",
                    "evidence_tier": "B",
                    "directness": "indirect",
                    "effect_direction": "mixed",
                    "n_claims": 2,
                },
            ],
        }),
        encoding="utf-8",
    )
    return run


def test_generate_brief_fixture_e2e_writes_stable_bundle(tmp_path: Path) -> None:
    run = _run_dir(tmp_path)
    out = tmp_path / "brief-out"

    rc = generate_brief.main([
        "--question", "demo intervention for cognition in older adults 65+",
        "--source-paper", str(run / "full_paper.md"),
        "--output-dir", str(out),
    ])

    assert rc == 0
    assert sorted(path.name for path in out.iterdir()) == [
        "brief.audit.json",
        "brief.citations.json",
        "brief.md",
        "brief.provenance.json",
        "numeric_quarantine.json",
    ]
    provenance = json.loads((out / "brief.provenance.json").read_text())
    citations = json.loads((out / "brief.citations.json").read_text())
    quarantine = json.loads((out / "numeric_quarantine.json").read_text())
    assert provenance["schema"] == "researka.brief_provenance.v1"
    assert provenance["source_run"] == run.name
    assert provenance["source_manifest"] == "manifest.json"
    assert provenance["source_manifest_sha256"]
    assert provenance["source_citation_registry"] == "citation_registry.json"
    assert provenance["source_citation_registry_sha256"]
    assert provenance["brief_receipt_ids"] == ["demo-r1"]
    assert provenance["citation_whitelist"] == ["Alpha 2024"]
    assert [c["citation_token"] for c in citations] == ["Alpha 2024"]
    assert quarantine == []


def test_generate_brief_fails_if_body_cites_unfiltered_receipt(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run = _run_dir(tmp_path)
    original_writer = generate_brief.write_brief

    def bad_writer(query, *, topic, receipts):
        draft = original_writer(query, topic=topic, receipts=receipts)
        return type(draft)(
            query=draft.query,
            topic=draft.topic,
            receipts=draft.receipts,
            body_md=draft.body_md + "\nLeaked citation: Beta 2023.\n",
        )

    monkeypatch.setattr(generate_brief, "write_brief", bad_writer)
    try:
        generate_brief.generate_brief_bundle(
            question="demo intervention for cognition in older adults 65+",
            source_paper=run,
            output_dir=tmp_path / "brief-out",
        )
    except RuntimeError as exc:
        assert "outside filtered whitelist" in str(exc)
    else:
        raise AssertionError("expected citation whitelist failure")


def test_generate_brief_fails_if_body_cites_registry_only_token(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run = _run_dir(tmp_path)
    original_writer = generate_brief.write_brief

    def bad_writer(query, *, topic, receipts):
        draft = original_writer(query, topic=topic, receipts=receipts)
        return type(draft)(
            query=draft.query,
            topic=draft.topic,
            receipts=draft.receipts,
            body_md=draft.body_md + "\nLeaked citation: RegistryOnly 2022.\n",
        )

    monkeypatch.setattr(generate_brief, "write_brief", bad_writer)
    try:
        generate_brief.generate_brief_bundle(
            question="demo intervention for cognition in older adults 65+",
            source_paper=run,
            output_dir=tmp_path / "brief-out",
        )
    except RuntimeError as exc:
        assert "RegistryOnly 2022" in str(exc)
    else:
        raise AssertionError("expected citation registry whitelist failure")


def test_generate_brief_numeric_quarantine_present_is_typed(
    tmp_path: Path,
) -> None:
    run = _run_dir(tmp_path)
    (run / "numeric_claim_quarantine.json").write_text(
        json.dumps([{"numeric": "42%", "reason": "fixture unsafe numeric"}]),
        encoding="utf-8",
    )
    paths = generate_brief.generate_brief_bundle(
        question="demo intervention for cognition in older adults 65+",
        source_paper=run,
        output_dir=tmp_path / "brief-out",
    )
    quarantine = json.loads(paths["numeric_quarantine"].read_text())
    assert quarantine["schema"] == "researka.brief_numeric_quarantine.v1"
    assert quarantine["source_numeric_quarantine"] == "numeric_claim_quarantine.json"
    assert quarantine["source_numeric_quarantine_sha256"]
    assert quarantine["items"] == [
        {"numeric": "42%", "reason": "fixture unsafe numeric"},
    ]


def test_generate_brief_numeric_quarantine_malformed_fails_closed(
    tmp_path: Path,
) -> None:
    run = _run_dir(tmp_path)
    (run / "numeric_quarantine.json").write_text(
        json.dumps({"bad": "shape"}),
        encoding="utf-8",
    )
    try:
        generate_brief.generate_brief_bundle(
            question="demo intervention for cognition in older adults 65+",
            source_paper=run,
            output_dir=tmp_path / "brief-out",
        )
    except ValueError as exc:
        assert "malformed numeric quarantine" in str(exc)
    else:
        raise AssertionError("expected malformed quarantine failure")
