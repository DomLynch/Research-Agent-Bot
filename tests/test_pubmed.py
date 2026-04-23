from __future__ import annotations

import httpx

from agent.sources.pubmed import PubMedClient


def _mock_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if "esearch.fcgi" in str(request.url):
            return httpx.Response(200, json={"esearchresult": {"idlist": ["40147475"]}})
        if "efetch.fcgi" in str(request.url):
            return httpx.Response(
                200,
                text="""<?xml version="1.0"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>40147475</PMID>
      <Article>
        <Journal>
          <JournalIssue><PubDate><Year>2025</Year></PubDate></JournalIssue>
          <JournalTitle>Lancet Healthy Longev</JournalTitle>
        </Journal>
        <ArticleTitle>Metformin and physical performance in older people (MET-PREVENT)</ArticleTitle>
        <Abstract>
          <AbstractText Label="BACKGROUND">Background sentence.</AbstractText>
          <AbstractText Label="METHODS">Methods sentence.</AbstractText>
          <AbstractText Label="FINDINGS">Mean 4-m walk speed at 4 months was 0.57 m/s in metformin versus 0.58 m/s in placebo (adjusted treatment effect 0.001 m/s [95% CI -0.06 to 0.06]; p=0.96).</AbstractText>
          <AbstractText Label="INTERPRETATION">Metformin did not improve 4-m walk speed.</AbstractText>
        </Abstract>
        <ELocationID EIdType="doi">10.1016/j.lanhl.2025.100695</ELocationID>
      </Article>
    </MedlineCitation>
  </PubmedArticle>
</PubmedArticleSet>""",
            )
        raise AssertionError(f"unexpected URL {request.url}")

    return httpx.MockTransport(handler)


def test_pubmed_client_preserves_structured_results_sections() -> None:
    client = PubMedClient(transport=_mock_transport())
    entries = client.search("metformin aging older adults", limit=1)
    assert len(entries) == 1
    excerpt = entries[0]["excerpt"]
    assert "FINDINGS:" in excerpt
    assert "INTERPRETATION:" in excerpt
    assert "0.001 m/s [95% CI -0.06 to 0.06]; p=0.96" in excerpt
