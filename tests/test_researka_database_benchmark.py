from __future__ import annotations

from agent.types import RawHit
from scripts.researka_database_benchmark import BenchmarkQuestion, score_question


def test_score_question_tracks_hits_lanes_and_expected_terms() -> None:
    q = BenchmarkQuestion(
        "rapa", "rapamycin lifespan mice", ("rapamycin", "lifespan"),
    )
    hits = [
        RawHit(
            source="researka_database",
            title="Rapamycin lifespan in mice",
            abstract="Dose-dependent rapamycin lifespan effects.",
            year=2014,
            url="https://doi.org/10/x",
            doi="10/x",
            raw={"lane": "established"},
        ),
        RawHit(
            source="researka_database",
            title="Alternative rapamycin regimens",
            abstract="Glucose homeostasis in aged mice.",
            year=2024,
            url="https://doi.org/10/y",
            doi="10/y",
            raw={"lane": "semantic"},
        ),
    ]
    result = score_question(q, hits)
    assert result.hit_count == 2
    assert result.lanes == ("established", "semantic")
    assert result.expected_term_hit is True
    assert result.top_titles[0] == "Rapamycin lifespan in mice"


def test_score_question_flags_missing_expected_terms() -> None:
    q = BenchmarkQuestion("nmn", "NAD NMN aging", ("nad", "nmn"))
    hit = RawHit(
        source="researka_database",
        title="Aging biomarkers",
        abstract="Biological age in older adults.",
        year=2021,
        url="https://example.test",
        raw={"lane": "semantic"},
    )
    assert score_question(q, [hit]).expected_term_hit is False
