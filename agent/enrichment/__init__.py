"""Post-corpus enrichment clients.

These clients take known identifiers (PMIDs, DOIs, drug names, topic
keywords) and return structured metadata to enrich the corpus AFTER
discovery. They do NOT participate in the SourceAggregator fan-out —
they have a different shape than corpus discovery (RawHit → metadata
dict, not RawHit → RawHit).

Modules (all free, no signup required for low-volume use):
- icite:          citation metrics (RCR, NIH percentile) per PMID
- rxnorm:         drug aliases / brand names / synonyms
- reporter:       NIH grants metadata (audit/funding-disclosure layer)
- opencitations:  bibliographic metadata + ORCIDs per DOI
- openfda:        FAERS adverse-event reports (drug safety axis)
"""
