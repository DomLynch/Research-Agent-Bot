"""Semantic must-contain probes per topic.

These tests assert the SHAPE of evidence the bundle should surface for each
golden topic — not specific PMIDs (which rot when papers retract or
re-classify). A probe says, e.g., "for metformin, at least one direct
human RCT post-2020 with frailty/sarcopenia/physical-performance content
must be in the writer's top-N slice."

If retrieval drops the canonical evidence (e.g. MILES, MASTERS-like trials,
Hickson IPF pilot), these probes fail before any LLM cost is incurred. CI
catches the regression at the bundle layer, not at the artifact layer.

The probes are intentionally LIBERAL on details (multiple title-tokens
accepted, multi-year windows) so they pass when retrieval finds new
qualifying evidence, not just yesterday's specific paper.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.bundle import bundle, rank_for_writer
from agent.retrieve import normalize_and_dedup
from agent.types import EvidenceItem, RawHit

FIXTURES = Path(__file__).resolve().parent / "fixtures"

# The same loader used by test_bundle.py — adapter priority order so PMIDs
# survive cross-source dedup.
_ADAPTER_PRIORITY = ("pubmed", "openalex", "europepmc", "clinicaltrials")


def _load_topic(slug: str) -> list[RawHit]:
    hits: list[RawHit] = []
    for source in _ADAPTER_PRIORITY:
        path = FIXTURES / slug / f"{source}.json"
        if not path.exists():
            continue
        for entry in json.loads(path.read_text(encoding="utf-8")):
            hits.append(RawHit(**entry))
    return hits


def _build(topic_slug: str, topic_query: str, domain: str) -> list[EvidenceItem]:
    hits = _load_topic(topic_slug)
    sources, abstracts, raw_signals = normalize_and_dedup(hits)
    return bundle(
        sources, abstracts,
        topic=topic_query, domain=domain, raw_signals=raw_signals,
    )


def _matches_shape(
    items: list[EvidenceItem],
    *,
    title_any: tuple[str, ...] = (),
    role_in: tuple[str, ...] = (),
    year_min: int | None = None,
    direct: bool | None = None,
    source_in: tuple[str, ...] = (),
) -> list[EvidenceItem]:
    """Return items matching all of the given shape constraints."""
    out: list[EvidenceItem] = []
    for it in items:
        title_l = (it.source.title or "").lower()
        if title_any and not any(t in title_l for t in title_any):
            continue
        if role_in and it.role not in role_in:
            continue
        if year_min is not None:
            year = it.source.year or 0
            if year < year_min:
                continue
        if direct is not None and it.direct != direct:
            continue
        if source_in and it.source.source not in source_in:
            continue
        out.append(it)
    return out


# Topic queries match capture_fixtures.py + the snapshot test config.
_TOPICS = {
    "metformin": ("metformin aging older adults", "aging older adults human"),
    "rapamycin": ("rapamycin older adults", "aging older adults human"),
    "senolytics": ("senolytics dasatinib quercetin older adults", "aging older adults human"),
    "semaglutide_weight": ("semaglutide weight loss adults", "obesity adults human"),
    "vitamin_d_mortality": ("vitamin D supplementation mortality elderly", "aging older adults human"),
}


# --- per-topic must-contain probes -----------------------------------------


def test_metformin_must_contain_direct_rct_on_frailty_or_sarcopenia():
    """Metformin longevity synthesis MUST surface a direct human RCT or
    registered trial on frailty / sarcopenia / physical-performance /
    healthspan endpoints. MILES, MASTERS-like, NCT02570672, NCT03451006
    all qualify under this shape."""
    topic_q, domain = _TOPICS["metformin"]
    items = _build("metformin", topic_q, domain)
    matches = _matches_shape(
        items,
        title_any=(
            "frailty", "sarcopenia", "physical", "performance",
            "muscle", "miles", "longevity", "geroprotective",
        ),
        role_in=("published_results", "registered_pending"),
        direct=True,
        year_min=2015,
    )
    assert matches, (
        "metformin bundle missing direct human evidence on frailty/sarcopenia/"
        "physical-performance/muscle/MILES (year >= 2015). Retrieval gap; "
        "writer will produce a weak synthesis."
    )


def test_metformin_top_writer_slice_dominated_by_direct_results():
    """The top-N slice the writer sees must lead with direct published_results
    or registered trials, not mechanistic noise."""
    topic_q, domain = _TOPICS["metformin"]
    items = _build("metformin", topic_q, domain)
    top = rank_for_writer(items, n=10)
    direct_results = [
        it for it in top
        if it.direct and it.role in {"published_results", "registered_pending", "review"}
    ]
    assert len(direct_results) >= 5, (
        f"top-10 writer slice for metformin has only {len(direct_results)} "
        f"direct results/trials/reviews — writer will drown in mechanistic noise"
    )


def test_rapamycin_must_contain_rapaex_pair():
    """The RAPA-EX results paper AND a protocol paper must both survive
    retrieval + bundle. This is the V0 contradiction case."""
    topic_q, domain = _TOPICS["rapamycin"]
    items = _build("rapamycin", topic_q, domain)
    by_pmid = {it.source.pmid: it for it in items if it.source.pmid}
    assert by_pmid.get("41985884"), "RAPA-EX-01 results paper missing from rapamycin bundle"
    assert by_pmid.get("41985884").role == "published_results", (
        f"RAPA-EX-01 misclassified as {by_pmid['41985884'].role}"
    )
    assert by_pmid.get("39354527"), "RAPA-EX protocol paper missing from rapamycin bundle"
    assert by_pmid.get("39354527").role == "published_protocol", (
        f"RAPA-EX protocol misclassified as {by_pmid['39354527'].role}"
    )


def test_senolytics_must_contain_dasatinib_quercetin_human_trial():
    """Senolytics synthesis MUST surface a direct human trial of D+Q
    (Hickson IPF pilot, Justice 2019, or a more recent D+Q RCT)."""
    topic_q, domain = _TOPICS["senolytics"]
    items = _build("senolytics", topic_q, domain)
    matches = _matches_shape(
        items,
        title_any=("dasatinib", "senolytic", "d + q", "d+q", "ipf", "senescent"),
        role_in=("published_results", "registered_pending"),
        direct=True,
        year_min=2018,
    )
    assert matches, (
        "senolytics bundle missing direct human trial of dasatinib+quercetin "
        "or any registered senolytics trial post-2018"
    )


def test_semaglutide_weight_must_contain_recent_rct():
    """Semaglutide weight-loss synthesis MUST surface a recent RCT
    (STEP / SUSTAIN family) reporting weight outcomes."""
    topic_q, domain = _TOPICS["semaglutide_weight"]
    items = _build("semaglutide_weight", topic_q, domain)
    matches = _matches_shape(
        items,
        title_any=(
            "semaglutide", "step", "sustain", "weight", "obesity",
            "body weight", "wegovy", "ozempic",
        ),
        role_in=("published_results", "review"),
        direct=True,
        year_min=2020,
    )
    assert len(matches) >= 2, (
        f"semaglutide bundle missing recent (>=2020) direct RCT/review "
        f"on weight outcome — found {len(matches)}"
    )


def test_vitamin_d_must_contain_mortality_evidence():
    """Vitamin D synthesis MUST surface direct human mortality / RCT or
    meta-analysis evidence — VITAL, supplementation trials, or pooled
    Cochrane / Bjelakovic-family meta-analyses."""
    topic_q, domain = _TOPICS["vitamin_d_mortality"]
    items = _build("vitamin_d_mortality", topic_q, domain)
    matches = _matches_shape(
        items,
        title_any=(
            "vitamin d", "cholecalciferol", "ergocalciferol",
            "25-hydroxyvitamin", "mortality", "vital",
        ),
        role_in=("published_results", "review", "registered_pending"),
        direct=True,
        year_min=2015,
    )
    assert len(matches) >= 3, (
        f"vitamin D bundle has only {len(matches)} direct vitamin-D mortality/"
        f"trial/review items post-2015 — retrieval gap"
    )


# --- bundle-shape sanity: every topic must have SOME direct results --------


@pytest.mark.parametrize("slug,topic_q,domain", [
    (s, q, d) for s, (q, d) in _TOPICS.items()
])
def test_every_topic_has_at_least_one_direct_published_result(
    slug: str, topic_q: str, domain: str,
):
    """Floor: every golden topic MUST have at least one direct published
    result (or registered trial) in its bundle. Below this floor there's
    nothing for the writer to synthesize from and the draft will be filler."""
    items = _build(slug, topic_q, domain)
    direct_evidence = _matches_shape(
        items,
        role_in=("published_results", "registered_pending"),
        direct=True,
    )
    assert direct_evidence, (
        f"{slug}: bundle has zero direct published_results/registered_pending "
        f"— pipeline cannot produce a credible synthesis"
    )
