"""Tests for render.py — markdown output structure."""
from __future__ import annotations

from agent.render import SECTION_ORDER, render
from agent.types import Draft, EvidenceItem, Source


def _bundle() -> list[EvidenceItem]:
    s1 = Source(ref=1, title="RCT title", year=2024, url="https://example.org/1",
                source="pubmed", doi="10.1/x", pmid="123", venue="NEJM")
    s2 = Source(ref=2, title="Protocol title", year=2024, url="https://clinicaltrials.gov/study/NCT001",
                source="clinicaltrials", nct="NCT001")
    return [
        EvidenceItem(source=s1, abstract="ok", design="rct",
                     role="published_results", tier="A1", direct=True, strict=True),
        EvidenceItem(source=s2, abstract="ok", design="registry",
                     role="registered_pending", tier="B", direct=True, strict=True),
    ]


def _draft() -> Draft:
    return Draft(
        topic="t", domain="d", criteria="",
        title="A research title",
        abstract=["First sentence [1].", "Second sentence [2]."],
        sections={
            "introduction": ["intro [1]."],
            "methods": ["methods text."],
            "findings": ["findings [1]."],
            "limitations": ["limits [2]."],
            "conclusion": ["calibrated [1]."],
        },
        bundle=_bundle(),
        facts=[],
    )


def test_render_includes_title():
    md = render(_draft())
    assert md.startswith("# A research title")


def test_render_includes_all_required_sections():
    md = render(_draft())
    for key in SECTION_ORDER:
        # Title-cased section header
        assert f"## {key.title()}" in md, f"missing section {key}"


def test_render_includes_evidence_table():
    md = render(_draft())
    assert "## Evidence" in md
    # Header row now includes risk-of-bias column; direct column dropped.
    assert "| Ref | Role | Tier | Design | RoB | Source | Year |" in md
    # Both refs are direct=True so both surface
    assert "| [1] | published_results |" in md
    assert "| [2] | registered_pending |" in md


def test_render_evidence_table_split_into_two_sections():
    """Direct human evidence and mechanistic support each get their own
    sub-table — reviewer flagged that mixing them inflates the evidence base."""
    from agent.types import EvidenceItem, Source
    direct = EvidenceItem(
        source=Source(ref=1, title="Direct trial", year=2024, url="", source="pubmed"),
        abstract="x", design="rct", role="published_results", tier="A2",
        direct=True, strict=True,
    )
    indirect = EvidenceItem(
        source=Source(ref=2, title="Animal study", year=2024, url="", source="pubmed"),
        abstract="x", design="mechanistic", role="mechanistic", tier="C",
        direct=False, strict=False,
    )
    d = _draft()
    d.bundle = [direct, indirect]
    md = render(d)
    # Both sub-tables present
    assert "### Direct Human Outcomes" in md
    assert "### Mechanistic / Preclinical Support" in md
    # Direct ref in the human section, mechanistic ref in the support section
    assert "| [1] | published_results |" in md
    assert "| [2] | mechanistic |" in md
    # Mechanistic background note is present
    assert "Background only" in md or "biological plausibility" in md


def test_render_includes_bibliography_with_links():
    md = render(_draft())
    assert "## Sources" in md
    assert "https://doi.org/10.1/x" in md
    assert "https://pubmed.ncbi.nlm.nih.gov/123/" in md
    assert "https://clinicaltrials.gov/study/NCT001" in md


def test_render_footer_carries_meta_when_provided():
    md = render(_draft(), meta={
        "model": "mimo-v2.5-pro",
        "prompt_version": "v1/2026-04-26",
        "estimated_cost_usd": 0.0123,
        "input_tokens": 500,
        "output_tokens": 200,
    })
    assert "writer=mimo-v2.5-pro" in md
    assert "cost=$0.0123" in md
    assert "in=500" in md


def test_render_renders_extra_sections_after_required():
    d = _draft()
    d.sections["safety"] = ["safety note [1]."]
    md = render(d)
    assert "## Safety" in md
    # Required sections still come first
    assert md.index("## Conclusion") < md.index("## Safety")
