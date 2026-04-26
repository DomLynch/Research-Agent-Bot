from __future__ import annotations

from pathlib import Path

from agent.extractor import StructuredExtractor


class FakeProvider:
    def __init__(self) -> None:
        self.calls = 0

    def complete_json(self, *, system_prompt: str, user_prompt: str):
        self.calls += 1
        return (
            {
                "primary_outcome": "all-cause mortality",
                "population": "older adults with diabetes",
                "intervention": "metformin",
                "comparator": "placebo",
                "methods_summary": "double-blind randomized trial",
                "risk_of_bias": "low randomization, low blinding, high attrition",
                "effects": [
                    {
                        "outcome": "all-cause mortality",
                        "metric": "HR",
                        "value": "0.77",
                        "ci_low": "0.65",
                        "ci_high": "0.91",
                        "p_value": "0.002",
                        "n": "1240",
                        "source_span": "HR 0.77 (95% CI 0.65-0.91, p=0.002) in older adults.",
                    }
                ],
                "source_doi": "10.1000/test",
            },
            {"usage": {}},
        )


def test_structured_extractor_caches_by_identity(tmp_path: Path) -> None:
    provider = FakeProvider()
    extractor = StructuredExtractor(cache_dir=tmp_path, provider=provider)
    entry = {
        "doi": "10.1000/test",
        "title": "Metformin and mortality",
        "excerpt": "Abstract text",
        "full_text": "Methods older adults placebo. Results HR 0.77 (95% CI 0.65-0.91).",
        "full_text_sections": {"methods": "older adults placebo", "results": "HR 0.77 (95% CI 0.65-0.91)"},
        "source_type": "pubmed",
    }

    first = extractor.extract(entry)
    second = extractor.extract(entry)

    assert first is not None
    assert first["effects"][0]["metric"] == "HR"
    assert second is not None
    assert provider.calls == 1


def test_structured_extractor_enriches_entries(tmp_path: Path) -> None:
    extractor = StructuredExtractor(cache_dir=tmp_path, provider=FakeProvider())
    entries = [
        {
            "doi": "10.1000/test",
            "title": "Metformin and mortality",
            "excerpt": "Abstract text",
            "full_text": "Methods older adults placebo. Results HR 0.77 (95% CI 0.65-0.91).",
            "full_text_sections": {"methods": "older adults placebo", "results": "HR 0.77 (95% CI 0.65-0.91)"},
            "source_type": "pubmed",
        },
        {"title": "No full text", "excerpt": "Abstract only", "source_type": "pubmed"},
    ]

    enriched, stats = extractor.enrich_entries(entries, limit=2)

    assert stats["attempted"] == 1
    assert stats["found"] == 1
    assert enriched[0]["extraction"]["population"] == "older adults with diabetes"
    assert "extraction" not in enriched[1]
