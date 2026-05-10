"""Aging-specific benchmark for the private Researka Database source.

This is deliberately not a generic "beat Elicit" claim. It measures the
asymmetric job this DB should do for the synthesis bot: return useful,
aging-relevant paper hits and pre-ranked lanes for questions the bot will ask.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx

from agent.sources.researka_database import ResearkaDatabaseClient
from agent.types import RawHit


@dataclass(frozen=True, slots=True)
class BenchmarkQuestion:
    id: str
    question: str
    expected_terms: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class QuestionResult:
    id: str
    question: str
    hit_count: int
    lanes: tuple[str, ...]
    expected_term_hit: bool
    top_titles: tuple[str, ...]


QUESTIONS: tuple[BenchmarkQuestion, ...] = (
    BenchmarkQuestion("rapamycin_lifespan_mice", "rapamycin lifespan mice dose sex", ("rapamycin", "lifespan")),
    BenchmarkQuestion("rapamycin_glucose_homeostasis", "rapamycin glucose homeostasis aging mice", ("rapamycin", "glucose")),
    BenchmarkQuestion("mtor_autophagy_aging", "mTOR autophagy aging longevity", ("mtor", "autophagy")),
    BenchmarkQuestion("senolytics_fisetin", "fisetin senolytic older adults aging", ("fisetin", "senolytic")),
    BenchmarkQuestion("dasatinib_quercetin", "dasatinib quercetin senescent cells frailty", ("dasatinib", "quercetin")),
    BenchmarkQuestion("metformin_aging", "metformin aging lifespan healthspan", ("metformin", "aging")),
    BenchmarkQuestion("metformin_tame", "metformin TAME trial aging outcomes", ("metformin", "trial")),
    BenchmarkQuestion("nad_nmn", "NAD NMN nicotinamide riboside aging human trial", ("nad", "aging")),
    BenchmarkQuestion("sirtuins_resveratrol", "sirtuin resveratrol lifespan aging", ("sirtuin", "resveratrol")),
    BenchmarkQuestion("spermidine_autophagy", "spermidine autophagy aging cognition", ("spermidine", "autophagy")),
    BenchmarkQuestion("caloric_restriction", "caloric restriction longevity biomarkers humans", ("caloric", "restriction")),
    BenchmarkQuestion("intermittent_fasting", "intermittent fasting aging metabolic health older adults", ("fasting", "metabolic")),
    BenchmarkQuestion("epigenetic_clock", "epigenetic clock biological age intervention", ("epigenetic", "age")),
    BenchmarkQuestion("telomere_aging", "telomere length aging mortality", ("telomere", "aging")),
    BenchmarkQuestion("frailty_intervention", "frailty intervention older adults clinical trial", ("frailty", "older")),
    BenchmarkQuestion("sarcopenia_muscle", "sarcopenia muscle aging resistance exercise", ("sarcopenia", "muscle")),
    BenchmarkQuestion("osteoporosis_aging", "osteoporosis aging older adults intervention", ("osteoporosis", "aging")),
    BenchmarkQuestion("menopause_aging", "menopause aging healthspan biomarkers", ("menopause", "aging")),
    BenchmarkQuestion("dementia_aging", "dementia aging neurodegeneration biomarkers", ("dementia", "aging")),
    BenchmarkQuestion("alzheimer_rapamycin", "Alzheimer rapamycin mTOR aging", ("alzheimer", "rapamycin")),
    BenchmarkQuestion("inflammaging", "inflammaging immune aging mortality", ("inflammaging", "immune")),
    BenchmarkQuestion("clonal_hematopoiesis", "clonal hematopoiesis aging disease", ("clonal", "aging")),
    BenchmarkQuestion("older_cancer_vulnerability", "older adults cancer vulnerability geriatric oncology", ("older", "cancer")),
    BenchmarkQuestion("semaglutide_aging", "semaglutide aging obesity older adults", ("semaglutide", "obesity")),
    BenchmarkQuestion("healthspan_biomarkers", "healthspan biomarkers aging intervention", ("healthspan", "biomarker")),
)


def score_question(q: BenchmarkQuestion, hits: list[RawHit]) -> QuestionResult:
    lanes = tuple(sorted({str(h.raw.get("lane") or "") for h in hits if h.raw.get("lane")}))
    haystack = "\n".join(f"{h.title}\n{h.abstract}" for h in hits).lower()
    expected_hit = all(term.lower() in haystack for term in q.expected_terms)
    return QuestionResult(
        id=q.id,
        question=q.question,
        hit_count=len(hits),
        lanes=lanes,
        expected_term_hit=expected_hit,
        top_titles=tuple(h.title for h in hits[:3]),
    )


async def run_benchmark(*, limit: int) -> dict[str, object]:
    client = ResearkaDatabaseClient()
    if not os.environ.get("RESEARKA_DATABASE_TOKEN"):
        raise SystemExit("RESEARKA_DATABASE_TOKEN is required")
    async with httpx.AsyncClient(timeout=30) as http:
        results = [
            score_question(q, await client.search(http, q.question, limit=limit))
            for q in QUESTIONS
        ]
    n = len(results)
    with_hits = sum(1 for r in results if r.hit_count > 0)
    expected_hits = sum(1 for r in results if r.expected_term_hit)
    three_lane = sum(1 for r in results if len(r.lanes) >= 2)
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "question_count": n,
        "with_hits": with_hits,
        "expected_term_hits": expected_hits,
        "multi_lane_results": three_lane,
        "hit_rate": round(with_hits / n, 3),
        "expected_term_rate": round(expected_hits / n, 3),
        "multi_lane_rate": round(three_lane / n, 3),
        "results": [asdict(r) for r in results],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--output", type=Path, default=Path("reports/researka_database_benchmark_latest.json"))
    args = parser.parse_args(argv)
    report = asyncio.run(run_benchmark(limit=args.limit))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(
        "questions={question_count} hit_rate={hit_rate} "
        "expected_term_rate={expected_term_rate} multi_lane_rate={multi_lane_rate} "
        "output={output}".format(**report, output=args.output),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
