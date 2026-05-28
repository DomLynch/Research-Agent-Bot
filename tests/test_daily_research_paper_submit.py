from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path
from typing import Any
from urllib.request import Request

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import daily_research_paper_submit as daily  # type: ignore[import-not-found]  # noqa: E402


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _run(root: Path, name: str = "synthesis-topic-v06-test") -> Path:
    run = root / name
    run.mkdir(parents=True)
    (run / "full_paper.md").write_text(
        "# Research Synthesis: Topic\n\n## Abstract\n\nFull abstract.\n\n## References\n\nR01.",
        encoding="utf-8",
    )
    _write_json(run / "manifest.json", {
        "topic": "topic",
        "n_receipts": 12,
        "n_high_confidence_claims_total": 34,
        "n_non_orthogonal_tensions": 5,
        "receipts": [{"receipt_id": "r1", "outcome_class": "longevity", "n_claims": 9, "effect_direction": "mixed", "directness": "direct"}],
    })
    _write_json(run / "citation_registry.json", {
        "r1": {"receipt_id": "r1", "body_citation": "Smith 2026", "reference_id": "R01", "source_year": 2026, "source_doi": "10.1/x", "source_pmid": "123"}
    })
    _write_json(run / "full_paper.audit.json", {"p1_pass": True, "n_pass": 14, "n_total": 14})
    _write_json(run / "full_paper.journal_surface.json", {"passed": True, "issues": []})
    _write_json(run / "full_paper.final_verdict.json", {"verdict": "AAA"})
    _write_json(run / "pre_submit_gate.json", {"result": {"passed": True}})
    return run


def test_dry_run_selects_eligible_research_paper(tmp_path: Path) -> None:
    _run(tmp_path)

    ledger = daily.run_cycle(runs_root=tmp_path, date="2026-05-23")

    assert ledger["status"] == "dry_run_selected"
    assert ledger["submitted"] == 0
    assert ledger["published"] == 0
    assert (tmp_path / daily.LEDGER_DIR / "2026-05-23.json").exists()


def test_payload_uses_researka_v2_submission_contract(tmp_path: Path) -> None:
    run = _run(tmp_path)

    payload = daily.build_payload(run)

    assert payload["article_type"] == "rapid_evidence_synthesis"
    assert payload["author_agent_id"] == "agent-v3-full-paper"
    assert payload["metadata"]["artifact_type"] == "research_paper"
    assert payload["sections"]["Full Manuscript"].startswith("## Research Synthesis")
    assert payload["sections"]["Research Question"]
    assert payload["author_signature"].startswith("sha256:")
    assert payload["source_bundle"][0]["doi"] == "10.1/x"
    assert payload["source_bundle"][0]["evidence_type"] == "primary"
    assert "published" not in payload


def test_payload_carries_revision_metadata_when_present(tmp_path: Path) -> None:
    run = _run(tmp_path)
    _write_json(run / "researka_revision_request.json", {
        "artifactId": "art-1",
        "submissionId": "sub-1",
        "source_run": "old-run",
        "title": "Research Synthesis: Topic",
        "feedback": "Add clearer caveats and resubmit.",
    })

    payload = daily.build_payload(run)

    assert payload["metadata"]["revision_of"] == {
        "artifactId": "art-1",
        "submissionId": "sub-1",
        "source_run": "old-run",
        "title": "Research Synthesis: Topic",
    }
    assert payload["metadata"]["revision_feedback"] == "Add clearer caveats and resubmit."


def test_successful_post_records_submitted_not_published(tmp_path: Path) -> None:
    _run(tmp_path)

    ledger = daily.run_cycle(
        runs_root=tmp_path,
        date="2026-05-23",
        submit=True,
        submitter=lambda payload: {"ok": True, "status": 201, "response": {"id": "obj-1", "title": payload["title"]}},
        remote_loader=lambda: (set(), None),
    )

    assert ledger["status"] == "submitted_to_researka"
    assert ledger["submitted"] == 1
    assert ledger["published"] == 0
    records = json.loads((tmp_path / daily.LEDGER_DIR / "_submitted_fingerprints.json").read_text(encoding="utf-8"))
    assert records[0]["topic"] == "topic"


def test_duplicate_fingerprint_is_not_resubmitted(tmp_path: Path) -> None:
    run = _run(tmp_path)
    fp = daily.build_payload(run)["metadata"]["content_hash"]
    _write_json(tmp_path / daily.LEDGER_DIR / "_submitted_fingerprints.json", [{"fingerprint": fp}])

    ledger = daily.run_cycle(runs_root=tmp_path, date="2026-05-23")

    assert ledger["status"] == "no_eligible_research_paper"
    assert ledger["considered"][0]["status"] == "duplicate_submission_fingerprint"


def test_researka_rejection_records_and_skips_same_paper(tmp_path: Path) -> None:
    _run(tmp_path)

    ledger = daily.run_cycle(
        runs_root=tmp_path,
        date="2026-05-23",
        submit=True,
        submitter=lambda _payload: {"ok": False, "status": 422, "response": "gate rejected"},
        remote_loader=lambda: (set(), None),
    )

    assert ledger["status"] == "submission_rejected_by_researka"
    assert ledger["submitted"] == 0
    assert ledger["considered"][0]["status"] == "submission_rejected_by_researka"
    assert ledger["revision_feedback"] == "gate rejected"
    rejected = json.loads((tmp_path / daily.LEDGER_DIR / daily.REJECTED_FINGERPRINTS).read_text(encoding="utf-8"))
    assert rejected[0]["topic"] == "topic"

    retry = daily.run_cycle(runs_root=tmp_path, date="2026-05-24")

    assert retry["status"] == "no_eligible_research_paper"
    assert retry["considered"][0]["status"] == "researka_rejected_fingerprint"


def test_researka_revise_records_feedback_and_skips_same_paper(tmp_path: Path) -> None:
    _run(tmp_path)

    ledger = daily.run_cycle(
        runs_root=tmp_path,
        date="2026-05-23",
        submit=True,
        submitter=lambda _payload: {
            "ok": False,
            "status": 422,
            "response": {"decision": "revise", "checklist": ["tighten headline", "resubmit"]},
        },
        remote_loader=lambda: (set(), None),
    )

    assert ledger["status"] == "submission_revise_requested"
    assert "tighten headline" in ledger["revision_feedback"]
    assert ledger["considered"][0]["status"] == "submission_revise_requested"
    records = json.loads((tmp_path / daily.LEDGER_DIR / daily.REVISION_FINGERPRINTS).read_text(encoding="utf-8"))
    assert records[0]["topic"] == "topic"
    assert "resubmit" in records[0]["feedback"]

    retry = daily.run_cycle(runs_root=tmp_path, date="2026-05-24")

    assert retry["status"] == "no_eligible_research_paper"
    assert retry["considered"][0]["status"] == "researka_revision_fingerprint"


def test_remote_publication_dedupe_blocks_resubmission_without_local_seed(tmp_path: Path) -> None:
    run = _run(tmp_path)
    fp = daily.build_payload(run)["metadata"]["content_hash"]

    ledger = daily.run_cycle(
        runs_root=tmp_path,
        date="2026-05-23",
        submit=True,
        submitter=lambda _payload: {"ok": True, "status": 201, "response": {}},
        remote_loader=lambda: ({fp}, None),
    )

    assert ledger["status"] == "no_eligible_research_paper"
    assert ledger["submitted"] == 0
    assert ledger["published"] == 0
    assert ledger["considered"][0]["status"] == "duplicate_remote_publication"


def test_remote_publication_dedupe_blocks_same_title_rerun(tmp_path: Path) -> None:
    run = _run(tmp_path)
    marker = daily._title_marker(daily.build_payload(run)["title"])

    ledger = daily.run_cycle(
        runs_root=tmp_path,
        date="2026-05-23",
        submit=True,
        submitter=lambda _payload: {"ok": True, "status": 201, "response": {}},
        remote_loader=lambda: ({marker}, None),
    )

    assert ledger["status"] == "no_eligible_research_paper"
    assert ledger["submitted"] == 0
    assert ledger["considered"][0]["status"] == "duplicate_remote_publication"


def test_selection_skips_stale_older_runs_for_same_topic(tmp_path: Path) -> None:
    older = _run(tmp_path, name="synthesis-topic-v06-older")
    newer = _run(tmp_path, name="synthesis-topic-v06-newer")
    os.utime(older, (1, 1))
    os.utime(newer, (2, 2))

    ledger = daily.run_cycle(
        runs_root=tmp_path,
        date="2026-05-23",
        submit=True,
        submitter=lambda _payload: {"ok": True, "status": 201, "response": {}},
        remote_loader=lambda: ({daily.build_payload(newer)["metadata"]["content_hash"]}, None),
    )

    statuses = [row["status"] for row in ledger["considered"]]
    assert "duplicate_remote_publication" in statuses
    assert "superseded_topic_run" in statuses
    assert ledger["submitted"] == 0


def test_selection_submits_older_retry_when_newer_retry_fails_gates(tmp_path: Path) -> None:
    older = _run(tmp_path, name="synthesis-topic-v06-R2")
    newer = _run(tmp_path, name="synthesis-topic-v06-R3")
    _write_json(newer / "full_paper.journal_surface.json", {"passed": False, "issues": ["short_conclusion"]})
    os.utime(older, (1, 1))
    os.utime(newer, (2, 2))

    ledger = daily.run_cycle(
        runs_root=tmp_path,
        date="2026-05-28",
        submit=True,
        submitter=lambda _payload: {"ok": True, "status": 201, "response": {}},
        remote_loader=lambda: (set(), None),
    )

    assert ledger["status"] == "submitted_to_researka"
    assert ledger["candidate"]["run"] == older.name
    assert [row["status"] for row in ledger["considered"]] == [
        "journal_surface_not_passed",
        "submitted_to_researka",
    ]


def test_submit_holds_when_remote_dedupe_fails(tmp_path: Path) -> None:
    _run(tmp_path)

    ledger = daily.run_cycle(
        runs_root=tmp_path,
        date="2026-05-23",
        submit=True,
        submitter=lambda _payload: {"ok": True, "status": 201, "response": {}},
        remote_loader=lambda: (set(), "timeout"),
    )

    assert ledger["status"] == "remote_dedupe_failed"
    assert ledger["submitted"] == 0
    assert ledger["published"] == 0


def test_submit_without_token_is_held(tmp_path: Path, monkeypatch) -> None:
    _run(tmp_path)
    for name in daily.TOKEN_ENVS:
        monkeypatch.delenv(name, raising=False)
    calls = 0

    def remote_loader() -> tuple[set[str], str | None]:
        nonlocal calls
        calls += 1
        return set(), None

    ledger = daily.run_cycle(
        runs_root=tmp_path,
        date="2026-05-23",
        submit=True,
        remote_loader=remote_loader,
    )

    assert ledger["status"] == "submit_not_configured"
    assert ledger["submitted"] == 0
    assert ledger["published"] == 0
    assert calls == 0


def test_http_submitter_sends_runtime_key_headers_and_idempotency(monkeypatch) -> None:
    seen: dict[str, Any] = {}

    class Response:
        status = 201

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return b'{"id":"obj-1"}'

    def fake_urlopen(req: Request, timeout: int) -> Response:
        seen["timeout"] = timeout
        seen["headers"] = dict(req.header_items())
        return Response()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    result = daily._submitter("https://api.example/submissions", "secret", "agent-v3")(
        {"title": "paper", "metadata": {"content_hash": "sha256:abc"}},
    )

    assert result["ok"] is True
    assert seen["headers"]["Authorization"] == "Bearer secret"
    assert seen["headers"]["X-api-key"] == "secret"
    assert seen["headers"]["X-agent-slug"] == "agent-v3"
    assert seen["headers"]["Idempotency-key"] == "sha256:abc"
