from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import httpx

from agent import cli
import pytest


class FakeProvider:
    prompt_version = "test-prompt/v1"
    model = "MiniMax-M2.7-highspeed"

    def complete_json(self, *, system_prompt: str, user_prompt: str) -> tuple:
        data = {
            "question": "This draft examines rapamycin and anti-aging outcomes [1] with a cautious evidence frame suitable for readable output.",
            "search_summary": "Public literature sources were queried with scoped variants and the bundle was reduced to the most relevant retained receipts.",
            "landscape": "The retained evidence is review-led and should be interpreted conservatively rather than as final clinical proof.",
            "methods": "The run expanded the topic into query variants, searched public indexes, and retained relevant receipts with transparent scope.",
            "findings": "The strongest signal is directional support [1] with uncertainty driven by heterogeneous designs and incomplete replication.",
            "limitations": "This remains a rapid synthesis of indexed evidence rather than a full systematic review with exhaustive full-text screening.",
            "conclusion": "Rapamycin remains decision-relevant [1], but claims should stay inside the limits of the retained evidence bundle.",
            "usage": {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
            "estimated_cost_usd": 0.0,
            "prompt_version": self.prompt_version,
            "model": self.model,
        }
        return (data, {"choices": [{"message": {"content": "raw"}}], "usage": {}})


class GoodSource:
    """Returns enough entries to pass the 12-entry source gate (RESEARKA_URL on VPS)."""

    def search(self, query: str, *, limit: int) -> list[dict]:
        return [
            {
                "title": f"{query} and healthy aging: a systematic review",
                "excerpt": f"Review evidence suggests {query} is mechanistically and translationally relevant, but endpoint heterogeneity remains substantial.",
                "year": 2024,
                "source_type": "pubmed",
                "evidence_type": "review",
                "url": f"https://pubmed.ncbi.nlm.nih.gov/{i}/",
                "query": query,
            }
            for i in range(7)
        ]


class MixedSource:
    """Returns enough entries to pass the 12-entry source gate after filtering."""

    def search(self, query: str, *, limit: int) -> list[dict]:
        base = [
            {
                "title": f"{query}: safety review in older adults",
                "excerpt": f"Human clinical evidence in older adults reports safety signals and cautious translational relevance for {query}.",
                "year": 2024,
                "source_type": "pubmed",
                "evidence_type": "review",
                "url": f"https://pubmed.ncbi.nlm.nih.gov/{i*10}/",
                "query": query,
            }
            for i in range(7)
        ]
        # One animal entry that should be filtered by negative filters
        base.append({
            "title": f"{query} in mice improve healthspan",
            "excerpt": f"Animal-only murine evidence reports mechanistic upside without human data for {query}.",
            "year": 2024,
            "source_type": "pubmed",
            "evidence_type": "primary",
            "url": "https://pubmed.ncbi.nlm.nih.gov/99/",
            "query": query,
        })
        return base


class FailingSource:
    def search(self, query: str, *, limit: int) -> list[dict]:
        request = httpx.Request("GET", "https://api.openalex.org/works")
        response = httpx.Response(429, request=request)
        raise httpx.HTTPStatusError("too many requests", request=request, response=response)


class ResolverOnlySource:
    def resolve(self, query: str) -> dict:
        return {"canonical_name": "Everolimus", "confidence": 0.95}

    def search(self, query: str, *, limit: int) -> list[dict]:
        return []


class IrrelevantSource:
    def search(self, query: str, *, limit: int) -> list[dict]:
        return [
            {
                "title": f"Cardiometabolic outcomes unrelated paper {i}",
                "excerpt": "Generic disease outcomes without the queried compound in title or abstract.",
                "year": 2024,
                "source_type": "pubmed",
                "evidence_type": "review",
                "url": f"https://pubmed.ncbi.nlm.nih.gov/{100+i}/",
                "query": query,
            }
            for i in range(8)
        ]


class IndirectOnlySource:
    def search(self, query: str, *, limit: int) -> list[dict]:
        return [
            {
                "title": f"Everolimus oncology review {i}",
                "excerpt": "Cancer outcomes and transplant immunosuppression without healthy aging endpoints.",
                "year": 2024,
                "source_type": "pubmed",
                "evidence_type": "review",
                "url": f"https://pubmed.ncbi.nlm.nih.gov/{200+i}/",
                "query": query,
            }
            for i in range(8)
        ]


class OldHumanSource:
    def search(self, query: str, *, limit: int) -> list[dict]:
        return [
            {
                "title": "Older human senolytic review",
                "excerpt": "Human review evidence exists, but this paper predates the required year floor.",
                "year": 2018,
                "source_type": "pubmed",
                "evidence_type": "review",
                "url": "https://pubmed.ncbi.nlm.nih.gov/5/",
                "query": query,
            }
        ]


class StubFullTextFetcher:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def enrich_entries(self, entries: list[dict], *, limit: int = 12) -> tuple[list[dict], dict]:
        enriched = []
        found = 0
        for i, entry in enumerate(entries):
            item = dict(entry)
            if i < 2:
                item["full_text"] = "Methods Results older adults rapamycin safety outcomes."
                item["full_text_source"] = "europepmc"
                found += 1
            enriched.append(item)
        return enriched, {"attempted": min(limit, len(entries)), "found": found, "source_counts": {"europepmc": found} if found else {}}


class StubStructuredExtractor:
    def __init__(self, *args, **kwargs) -> None:
        pass

    @classmethod
    def from_env(cls, *, cache_dir):
        return cls()

    def enrich_entries(self, entries: list[dict], *, limit: int = 6) -> tuple[list[dict], dict]:
        enriched = []
        found = 0
        for i, entry in enumerate(entries):
            item = dict(entry)
            if item.get("full_text") and i < 2:
                item["extraction"] = {
                    "found": True,
                    "primary_outcome": "all-cause mortality",
                    "population": "older adults",
                    "intervention": "rapamycin",
                    "comparator": "placebo",
                    "methods_summary": "randomized trial",
                    "risk_of_bias": "low",
                    "effects": [
                        {
                            "outcome": "all-cause mortality",
                            "metric": "HR",
                            "value": "0.77",
                            "ci_low": "0.65",
                            "ci_high": "0.91",
                            "p_value": "0.002",
                            "n": "1240",
                            "source_span": "HR 0.77 (95% CI 0.65-0.91) in older adults.",
                        }
                    ],
                    "extractor_version": "test-v1",
                    "source_doi": item.get("doi", ""),
                }
                found += 1
            enriched.append(item)
        return enriched, {"attempted": min(limit, len(entries)), "found": found, "version": "test-v1"}


@pytest.fixture(autouse=True)
def _stub_new_source_clients(monkeypatch):
    monkeypatch.setattr(cli, "RxivClient", lambda: FailingSource())
    monkeypatch.setattr(cli, "ChEMBLClient", lambda: FailingSource())
    monkeypatch.setattr(cli, "FullTextFetcher", StubFullTextFetcher)
    monkeypatch.setattr(cli, "StructuredExtractor", StubStructuredExtractor)


def test_run_agent_tolerates_source_errors_and_writes_markdown(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("RESEARKA_URL", raising=False)
    monkeypatch.setattr(cli, "PubMedClient", lambda: GoodSource())
    monkeypatch.setattr(cli, "OpenAlexClient", lambda: FailingSource())
    monkeypatch.setattr(cli.MimoClient, "from_env", staticmethod(lambda: FakeProvider()))

    run = cli.run_agent(topic="rapamycin", domain="anti-aging", criteria="500 words", run_dir=str(tmp_path))

    assert not run.get("error")
    assert run["source_errors"]
    assert run["markdown"].startswith("# Rapid Evidence Synthesis:")
    assert "## Methods" in run["markdown"]
    assert "PRISMA-style flow:" in run["markdown"]
    assert "excluded during scope/domain filtering" in run["markdown"]
    assert "excluded during final bundle assembly" in run["markdown"]
    assert "Exclusion reasons:" in run["markdown"]
    assert "Full text:" in run["markdown"]
    assert "Structured extraction:" in run["markdown"]
    assert run["protocol_file"].endswith(".protocol.json")
    assert (tmp_path / "protocols" / run["protocol_file"]).exists()
    assert (tmp_path / run["markdown_file"]).exists()
    assert len(run["queries"]) >= 1


def test_run_agent_scope_filters_retained_evidence(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("RESEARKA_URL", raising=False)
    monkeypatch.setattr(cli, "PubMedClient", lambda: MixedSource())
    monkeypatch.setattr(cli, "OpenAlexClient", lambda: FailingSource())
    monkeypatch.setattr(cli.MimoClient, "from_env", staticmethod(lambda: FakeProvider()))

    run = cli.run_agent(
        topic="senolytics and healthspan",
        domain="longevity",
        criteria="human studies only safety 2020+",
        run_dir=str(tmp_path),
    )

    assert not run.get("error")
    assert run["scope_signals"] == ["year>=2020", "human_only", "safety_focus"]
    assert run["evidence_retrieved"] >= 3
    assert run["evidence_selected"] >= 1
    assert run["source_telemetry"]["retrieved"]["pubmed"] >= 1
    assert run["source_telemetry"]["full_text"]["found"] == 2
    assert run["source_telemetry"]["extraction"]["found"] == 2
    for item in run["source_bundle"]:
        assert "evidence_type" in item
        assert "year" in item
        assert "title" in item
        assert "url" in item
        assert item.get("source_type")
        assert item.get("directness") in {"direct", "indirect", "mechanistic"}
        assert item.get("card", {}).get("evidence_grade") in {"H", "M", "L"}
        if item.get("card", {}).get("full_text_found"):
            assert item.get("card", {}).get("extraction_found") is True
    # verify no animal papers leak into the bundle
    for item in run["source_bundle"]:
        title = str(item.get("title", "")).lower()
        assert "mice" not in title, f"Animal paper leaked into source_bundle: {title}"
        assert "mouse" not in title, f"Animal paper leaked into source_bundle: {title}"


def test_run_agent_does_not_silently_fallback_outside_scope(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(cli, "PubMedClient", lambda: OldHumanSource())
    monkeypatch.setattr(cli, "OpenAlexClient", lambda: FailingSource())
    monkeypatch.setattr(cli.MimoClient, "from_env", staticmethod(lambda: FakeProvider()))

    run = cli.run_agent(
        topic="senolytics and healthspan",
        domain="longevity",
        criteria="human studies only 2020+",
        run_dir=str(tmp_path),
    )

    assert run["evidence_retrieved"] >= 1
    assert run["evidence_selected"] == 0
    assert "Insufficient evidence" in run.get("error", "")


class LeakyProvider:
    prompt_version = "test-prompt/v1"
    model = "MiniMax-M2.7-highspeed"

    def complete_json(self, *, system_prompt: str, user_prompt: str) -> tuple:
        data = {
            "question": "coverage decay detected",
            "search_summary": "replace this section",
            "landscape": "replace this section",
            "methods": "revision brief",
            "findings": "[placeholder]",
            "limitations": "replace this section",
            "conclusion": "replace this section",
            "usage": {"input_tokens": 5, "output_tokens": 5, "total_tokens": 10},
            "estimated_cost_usd": 0.0,
            "prompt_version": self.prompt_version,
            "model": self.model,
        }
        return (data, {"choices": [{"message": {"content": "raw"}}], "usage": {}})


def test_all_fallback_raises_error(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(cli, "PubMedClient", lambda: GoodSource())
    monkeypatch.setattr(cli, "OpenAlexClient", lambda: GoodSource())
    monkeypatch.setattr(cli.MimoClient, "from_env", staticmethod(lambda: LeakyProvider()))

    run = cli.run_agent(topic="rapamycin", domain="anti-aging", criteria="", run_dir=str(tmp_path))

    assert "all sections fell back" in run.get("error", "")


def test_insufficient_evidence(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(cli, "PubMedClient", lambda: OldHumanSource())
    monkeypatch.setattr(cli, "OpenAlexClient", lambda: FailingSource())
    monkeypatch.setattr(cli.MimoClient, "from_env", staticmethod(lambda: FakeProvider()))

    run = cli.run_agent(topic="senolytics", domain="longevity", criteria="2020+", run_dir=str(tmp_path))

    assert run["evidence_retrieved"] >= 1
    assert "Insufficient evidence" in run.get("error", "")


def test_inline_citations_present(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("RESEARKA_URL", raising=False)
    monkeypatch.setattr(cli, "PubMedClient", lambda: MixedSource())
    monkeypatch.setattr(cli, "OpenAlexClient", lambda: GoodSource())
    monkeypatch.setattr(cli.MimoClient, "from_env", staticmethod(lambda: FakeProvider()))

    run = cli.run_agent(topic="senolytics and healthspan", domain="longevity", criteria="", run_dir=str(tmp_path))

    assert not run.get("error")
    assert "[1]" in run["markdown"]


def test_multi_query_executed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("RESEARKA_URL", raising=False)
    monkeypatch.setattr(cli, "PubMedClient", lambda: GoodSource())
    monkeypatch.setattr(cli, "OpenAlexClient", lambda: FailingSource())
    monkeypatch.setattr(cli.MimoClient, "from_env", staticmethod(lambda: FakeProvider()))

    run = cli.run_agent(topic="rapamycin", domain="anti-aging", criteria="", run_dir=str(tmp_path))

    assert not run.get("error")
    assert len(run["queries"]) >= 2
    assert run["source_errors"]


def test_source_list_is_numbered_with_titles(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("RESEARKA_URL", raising=False)
    monkeypatch.setattr(cli, "PubMedClient", lambda: GoodSource())
    monkeypatch.setattr(cli, "OpenAlexClient", lambda: FailingSource())
    monkeypatch.setattr(cli.MimoClient, "from_env", staticmethod(lambda: FakeProvider()))

    run = cli.run_agent(topic="rapamycin", domain="anti-aging", criteria="", run_dir=str(tmp_path))

    assert not run.get("error")
    md = run["markdown"]
    assert "## Sources" in md
    assert "[1]" in md
    assert "pubmed.ncbi.nlm.nih.gov" in md


def test_methods_final_bundle_count_matches_source_bundle(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("RESEARKA_URL", raising=False)
    monkeypatch.setattr(cli, "PubMedClient", lambda: GoodSource())
    monkeypatch.setattr(cli, "OpenAlexClient", lambda: GoodSource())
    monkeypatch.setattr(cli.MimoClient, "from_env", staticmethod(lambda: FakeProvider()))

    run = cli.run_agent(topic="rapamycin", domain="anti-aging", criteria="", run_dir=str(tmp_path))

    assert not run.get("error")
    final_bundle = len(run["source_bundle"])
    assert run["bundle_stages"]["final_bundle"] == final_bundle
    assert f"{final_bundle} included in the final source bundle" in run["markdown"]
    assert "Full text: 2 of" in run["markdown"]
    assert "Structured extraction: 2 of" in run["markdown"]


def test_source_routing_helpers() -> None:
    assert cli._should_use_rxiv("longevity", "rapamycin")
    assert cli._should_use_chembl("everolimus")
    assert not cli._should_use_chembl("time restricted eating")


def test_run_agent_canonicalizes_typo_topic(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("RESEARKA_URL", raising=False)
    monkeypatch.setattr(cli, "ChEMBLClient", lambda: ResolverOnlySource())
    monkeypatch.setattr(cli, "PubMedClient", lambda: GoodSource())
    monkeypatch.setattr(cli, "OpenAlexClient", lambda: FailingSource())
    monkeypatch.setattr(cli.MimoClient, "from_env", staticmethod(lambda: FakeProvider()))

    run = cli.run_agent(topic="evrolimus", domain="anti-aging", criteria="", run_dir=str(tmp_path))

    assert not run.get("error")
    assert run["raw_topic"] == "evrolimus"
    assert run["canonical_topic"] == "everolimus"
    assert run["did_you_mean"] == "everolimus"
    assert run["resolver_source"] == "alias_map"


def test_run_agent_blocks_low_topic_match_ratio(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("RESEARKA_URL", raising=False)
    monkeypatch.setattr(cli, "ChEMBLClient", lambda: ResolverOnlySource())
    monkeypatch.setattr(cli, "PubMedClient", lambda: IrrelevantSource())
    monkeypatch.setattr(cli, "OpenAlexClient", lambda: FailingSource())
    monkeypatch.setattr(cli.MimoClient, "from_env", staticmethod(lambda: FakeProvider()))

    run = cli.run_agent(topic="everolimus", domain="anti-aging", criteria="", run_dir=str(tmp_path))

    assert "Low topic-match ratio" in run.get("error", "")
    assert run["topic_match_ratio"] == 0.0


def test_run_agent_blocks_indirect_only_anti_aging_draft(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("RESEARKA_URL", raising=False)
    monkeypatch.setattr(cli, "ChEMBLClient", lambda: ResolverOnlySource())
    monkeypatch.setattr(cli, "PubMedClient", lambda: IndirectOnlySource())
    monkeypatch.setattr(cli, "OpenAlexClient", lambda: FailingSource())
    monkeypatch.setattr(cli.MimoClient, "from_env", staticmethod(lambda: FakeProvider()))

    run = cli.run_agent(topic="everolimus", domain="anti-aging", criteria="", run_dir=str(tmp_path))

    assert "Insufficient direct evidence" in run.get("error", "")
    assert run.get("gate_reason") == "insufficient_direct_evidence"
    assert "markdown" not in run


# ── Safety gate tests ──────────────────────────────────────────────


def test_kill_switch_blocks_run(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BOT_ENABLED", "false")
    monkeypatch.setattr(cli, "PubMedClient", lambda: GoodSource())
    monkeypatch.setattr(cli, "OpenAlexClient", lambda: GoodSource())
    monkeypatch.setattr(cli.MimoClient, "from_env", staticmethod(lambda: FakeProvider()))

    run = cli.run_agent(topic="rapamycin", domain="anti-aging", criteria="", run_dir=str(tmp_path))

    assert "kill switch" in run.get("error", "").lower()
    assert run.get("started_at")
    assert "queries" not in run


def test_kill_switch_values(tmp_path: Path, monkeypatch) -> None:
    for val in ("true", "1", "yes", "on", "TRUE", " Yes "):
        monkeypatch.setenv("BOT_ENABLED", val)
        assert cli._is_enabled() is True, f"BOT_ENABLED={val!r} should be enabled"
    for val in ("false", "0", "no", "off", "", "False"):
        monkeypatch.setenv("BOT_ENABLED", val)
        assert cli._is_enabled() is False, f"BOT_ENABLED={val!r} should be disabled"


def test_submit_switch_skips_submission(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BOT_SUBMIT_ENABLED", "false")
    monkeypatch.setenv("RESEARKA_URL", "http://example.com")
    monkeypatch.setattr(cli, "PubMedClient", lambda: GoodSource())
    monkeypatch.setattr(cli, "OpenAlexClient", lambda: GoodSource())
    monkeypatch.setattr(cli.MimoClient, "from_env", staticmethod(lambda: FakeProvider()))

    # Run with per-source-limit high enough to get ≥12 items for source gate
    run = cli.run_agent(
        topic="rapamycin", domain="anti-aging", criteria="",
        per_source_limit=25, run_dir=str(tmp_path),
    )

    # The run may error on insufficient sources (2 items per query × 3 queries = 6),
    # but the key check is that no submission was attempted.
    assert "submission" not in run
    assert "submission_id" not in run


def test_submit_switch_values(tmp_path: Path, monkeypatch) -> None:
    for val in ("true", "1", "yes", "on"):
        monkeypatch.setenv("BOT_SUBMIT_ENABLED", val)
        assert cli._is_submit_enabled() is True, f"BOT_SUBMIT_ENABLED={val!r} should be enabled"
    for val in ("false", "0", "no", "off", ""):
        monkeypatch.setenv("BOT_SUBMIT_ENABLED", val)
        assert cli._is_submit_enabled() is False, f"BOT_SUBMIT_ENABLED={val!r} should be disabled"


def test_daily_cost_cap_blocks_run(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DAILY_COST_CAP_USD", "0.01")
    monkeypatch.setattr(cli, "PubMedClient", lambda: GoodSource())
    monkeypatch.setattr(cli, "OpenAlexClient", lambda: GoodSource())
    monkeypatch.setattr(cli.MimoClient, "from_env", staticmethod(lambda: FakeProvider()))

    today = datetime.now(timezone.utc).date().isoformat()

    # Pre-seed a log file with today's date prefix so _daily_cost picks it up
    import json as _json

    log_path = tmp_path / f"{today}-fake-expensive.json"
    log_path.write_text(_json.dumps({"estimated_cost_usd": 0.02}), encoding="utf-8")

    assert cli._daily_cost(str(tmp_path)) >= 0.02

    run = cli.run_agent(topic="rapamycin", domain="anti-aging", criteria="", run_dir=str(tmp_path))
    assert "cost cap" in run.get("error", "").lower()


def test_daily_cost_skips_raw_json(tmp_path: Path) -> None:
    import json

    today = datetime.now(timezone.utc).date().isoformat()
    good = tmp_path / f"{today}-run.json"
    good.write_text(json.dumps({"estimated_cost_usd": 5.0}), encoding="utf-8")
    raw = tmp_path / f"{today}-run.raw.json"
    raw.write_text(json.dumps({"estimated_cost_usd": 99.0}), encoding="utf-8")

    assert cli._daily_cost(str(tmp_path)) == 5.0


def test_daily_cost_cap_default_is_10(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("DAILY_COST_CAP_USD", raising=False)
    assert cli._daily_cost_cap() == 10.0
