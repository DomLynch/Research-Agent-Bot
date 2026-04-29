# Metformin Canonical Corpus — Day 10.13 Predeclared Benchmark

**Purpose:** This is the predeclared benchmark corpus for the metformin
synthesis end-game test. It is the 7-paper Quality Reference Corpus from
[`docs/quality-reference/metformin/README.md`](../../../docs/quality-reference/metformin/README.md),
fetched from PubMed and committed verbatim. AAA discipline (per the
Day 10.12 reviewer's framing): the canonical corpus must be declared
BEFORE the run, and ALL papers' fates must be reported — passes,
failures, and rejection rationales — without selective omission.

**Anti-gaming contract:**
- This file lists every paper in the corpus before any run.
- The `--canonical-corpus metformin` flag in
  `scripts/e2e_metformin_proof_001.py` reads the
  `tests/fixtures/metformin_canonical/` fixture and runs the
  multi-receipt pipeline ONLY against those 7 papers.
- Any paper rejected by SPAR is recorded in
  `multi_receipt_manifest.json` and quarantined in the synthesis
  paper's `Rejected / Contested Evidence` section. Rejection
  rationales are visible in each `cluster_NN/spar_review.json`.
- We do not swap papers in or out after the fact. If a canonical
  paper unexpectedly fails, that is a finding, not a reason to
  curate it out.

## The 7 papers (predeclared)

| # | Key            | PMID      | DOI                          | NCT          | Type           | Expected role        | Tier |
|---|----------------|-----------|------------------------------|--------------|----------------|----------------------|------|
| 1 | MASTERS        | 31557380  | 10.1111/acel.13039           | NCT02308228  | RCT            | published_results    | A1   |
| 2 | Konopka_2019   | 30548390  | 10.1111/acel.12880           | —            | RCT            | published_results    | A1   |
| 3 | MILES          | 29383869  | 10.1111/acel.12723           | NCT01765946  | RCT (n=14)     | published_results    | A1   |
| 4 | MET_PREVENT    | 40147475  | 10.1016/j.lanhl.2025.100695  | —            | RCT            | published_results    | A1   |
| 5 | Kulkarni_2022  | 35343051  | 10.1111/acel.13596           | —            | Methodology    | review               | B    |
| 6 | Keys_2025      | 40582648  | 10.1016/j.arr.2025.102817    | —            | Critical review | review               | B    |
| 7 | Mohammed_2021  | 34421827  | 10.3389/fendo.2021.718942    | —            | Critical review | review               | B    |

## Why these 7 papers

Per the user's repeated mandate ("comparable to the 5 top-tier examples
i gave u"), these are the metformin papers the bot is supposed to
match in caliber. The first 4 are the canonical RCTs; the last 3 are
the high-quality reviews that frame what the field has and has not yet
established. A synthesis paper drawing on these 7 sources is, by
construction, drawing on the strongest available evidence for metformin
in aging — the same evidence base the user's reference reviews drew on.

## Reproducing the corpus

The PubMed e-utilities `efetch.fcgi` returns each paper's title +
abstract + venue. We committed the fetched fixture
(`tests/fixtures/metformin_canonical/pubmed.json`) so runs are
reproducible without network access. To re-fetch (if the abstracts
ever change upstream), run the fetcher one-off snippet documented in
`PROJECT_STATE.md` Day 10.13 section.
