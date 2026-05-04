"""Post-corpus enrichment clients.

These clients take known identifiers (PMIDs, drug names, topic keywords)
and return structured metadata to enrich the corpus AFTER discovery.
They do NOT participate in the SourceAggregator fan-out — they have a
different shape than corpus discovery (RawHit → metadata dict, not
RawHit → RawHit).

Modules:
- icite:    citation metrics (RCR, NIH percentile) per PMID
- rxnorm:   drug aliases / brand names / synonyms
- reporter: NIH grants metadata (audit/funding-disclosure layer)
"""
