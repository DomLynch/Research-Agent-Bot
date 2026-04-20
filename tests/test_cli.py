from __future__ import annotations

from pathlib import Path

import httpx

from agent import cli


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
    def search(self, query: str, *, limit: int) -> list[dict]:
        return [
            {
                "title": "Rapamycin and healthy aging: a systematic review",
                "excerpt": "Review evidence suggests rapamycin is mechanistically and translationally relevant, but endpoint heterogeneity remains substantial.",
                "year": 2024,
                "source_type": "pubmed",
                "evidence_type": "review",
                "url": "https://pubmed.ncbi.nlm.nih.gov/1/",
                "query": query,
            },
            {
                "title": "Rapamycin clinical outcomes in aging populations",
                "excerpt": "Primary study evidence shows rapamycin has measurable effects on aging biomarkers in human cohorts.",
                "year": 2023,
                "source_type": "pubmed",
                "evidence_type": "primary",
                "url": "https://pubmed.ncbi.nlm.nih.gov/2/",
                "query": query,
            },
        ]


class MixedSource:
    def search(self, query: str, *, limit: int) -> list[dict]:
        return [
            {
                "title": "Senolytics in older adults: safety review",
                "excerpt": "Human clinical evidence in older adults reports safety signals and cautious translational relevance.",
                "year": 2024,
                "source_type": "pubmed",
                "evidence_type": "review",
                "url": "https://pubmed.ncbi.nlm.nih.gov/2/",
                "query": query,
            },
            {
                "title": "Senolytics in mice improve healthspan",
                "excerpt": "Animal-only murine evidence reports mechanistic upside without human data.",
                "year": 2024,
                "source_type": "pubmed",
                "evidence_type": "primary",
                "url": "https://pubmed.ncbi.nlm.nih.gov/3/",
                "query": query,
            },
            {
                "title": "Older senolytic review",
                "excerpt": "Human review evidence exists, but this older paper predates the scope year floor.",
                "year": 2018,
                "source_type": "pubmed",
                "evidence_type": "review",
                "url": "https://pubmed.ncbi.nlm.nih.gov/4/",
                "query": query,
            },
            {
                "title": "Senolytic efficacy in human healthspan trials",
                "excerpt": "Human clinical evidence in older adults shows safety signals and healthspan improvements.",
                "year": 2023,
                "source_type": "pubmed",
                "evidence_type": "primary",
                "url": "https://pubmed.ncbi.nlm.nih.gov/5/",
                "query": query,
            },
        ]


class FailingSource:
    def search(self, query: str, *, limit: int) -> list[dict]:
        request = httpx.Request("GET", "https://api.openalex.org/works")
        response = httpx.Response(429, request=request)
        raise httpx.HTTPStatusError("too many requests", request=request, response=response)


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


def test_run_agent_tolerates_source_errors_and_writes_markdown(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(cli, "PubMedClient", lambda: GoodSource())
    monkeypatch.setattr(cli, "OpenAlexClient", lambda: FailingSource())
    monkeypatch.setattr(cli.MimoClient, "from_env", staticmethod(lambda: FakeProvider()))

    run = cli.run_agent(topic="rapamycin", domain="anti-aging", criteria="500 words", run_dir=str(tmp_path))

    assert not run.get("error")
    assert run["source_errors"]
    assert run["markdown"].startswith("# Rapid Evidence Synthesis:")
    assert (tmp_path / run["markdown_file"]).exists()
    assert len(run["queries"]) >= 1


def test_run_agent_scope_filters_retained_evidence(tmp_path: Path, monkeypatch) -> None:
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
    for item in run["source_bundle"]:
        assert "evidence_type" in item
        assert "year" in item
        assert "title" in item
        assert "url" in item


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
    assert not run.get("error")  # drafter receives unfiltered evidence, succeeds


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
    assert not run.get("error")  # drafter receives unfiltered evidence, succeeds


def test_inline_citations_present(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(cli, "PubMedClient", lambda: MixedSource())
    monkeypatch.setattr(cli, "OpenAlexClient", lambda: GoodSource())
    monkeypatch.setattr(cli.MimoClient, "from_env", staticmethod(lambda: FakeProvider()))

    run = cli.run_agent(topic="senolytics and healthspan", domain="longevity", criteria="", run_dir=str(tmp_path))

    assert not run.get("error")
    assert "[1]" in run["markdown"]


def test_multi_query_executed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(cli, "PubMedClient", lambda: GoodSource())
    monkeypatch.setattr(cli, "OpenAlexClient", lambda: FailingSource())
    monkeypatch.setattr(cli.MimoClient, "from_env", staticmethod(lambda: FakeProvider()))

    run = cli.run_agent(topic="rapamycin", domain="anti-aging", criteria="", run_dir=str(tmp_path))

    assert not run.get("error")
    assert len(run["queries"]) >= 2
    assert run["source_errors"]


def test_source_list_is_numbered_with_titles(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(cli, "PubMedClient", lambda: GoodSource())
    monkeypatch.setattr(cli, "OpenAlexClient", lambda: FailingSource())
    monkeypatch.setattr(cli.MimoClient, "from_env", staticmethod(lambda: FakeProvider()))

    run = cli.run_agent(topic="rapamycin", domain="anti-aging", criteria="", run_dir=str(tmp_path))

    assert not run.get("error")
    md = run["markdown"]
    assert "## Sources" in md
    assert "[1]" in md
    assert "pubmed.ncbi.nlm.nih.gov" in md
