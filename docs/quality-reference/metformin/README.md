# Quality Reference Corpus — Metformin

**Purpose:** these 7 papers define the **quality bar** for Proof 001's `paper.md`. They are NOT the bot's input — the bot does its own retrieval. They are the standard the writer prompt and SPAR judge checklist measure against.

**This file is metadata only.** The PDFs themselves are not committed (binary bloat); they live in the founder's local `~/Downloads/` and can be re-acquired via DOI/PMID below. The structured fields here (`expected_role`, `expected_tier`, `gold_passages`) feed `agent/prompts/writer_quality_bar.md` and `agent/prompts/judge_quality_checklist.md` at build time.

---

## 1. Walton 2019 — MASTERS

- **DOI:** 10.1111/acel.13039
- **PMID:** 31557380
- **Trial registry:** NCT02308228
- **Journal:** Aging Cell, 2019;18:e13039
- **Type:** Original RCT
- **Expected classification:**
  - role: `published_results`
  - design: `rct`
  - tier: `A1`
  - direct: `true`
  - strict: `true`
- **Demonstrates:** Numeric precision; explicit negative finding without spin
- **Gold passages:**
  - "These results underscore the benefits of PRT in older adults, but metformin negatively impacts the hypertrophic response to resistance training in healthy older individuals."
  - "Metformin led to an increase in AMPK signaling, and a trend for blunted increases in mTORC1 signaling in response to PRT."

## 2. Konopka 2019

- **DOI:** 10.1111/acel.12880
- **PMID:** 30548390
- **Journal:** Aging Cell, 2019;18:e12880
- **Type:** Original RCT
- **Expected classification:**
  - role: `published_results`
  - design: `rct`
  - tier: `A1`
  - direct: `true`
  - strict: `true`
- **Demonstrates:** Honest hedging on p=0.08; surfaces 58/42 responder split
- **Gold passages:**
  - "Metformin attenuated the increase in VO₂max following 12 weeks of AET by approximately 50%, although this did not reach statistical significance (p = 0.08)."
  - "There was a dichotomous response to AET with metformin where 58% of participants were positive responders with increased insulin sensitivity and 42% responded negatively with decreased insulin sensitivity."

## 3. Kulkarni 2018 — MILES

- **DOI:** 10.1111/acel.12723
- **PMID:** 29316247
- **Trial registry:** NCT01765946
- **Journal:** Aging Cell, 2018;17:e12723
- **Type:** Original RCT (crossover, n=14)
- **Expected classification:**
  - role: `published_results`
  - design: `rct`
  - tier: `A1`
  - direct: `true` (mechanistic-direct)
  - strict: `true`
- **Demonstrates:** Validation-gap acknowledgment; mechanism vs clinic separation
- **Gold passage:**
  - "These findings remain to be validated in other tissues and study designs and do not yet allow us to identify the primary site of action of metformin."

## 4. Witham 2025 — MET-PREVENT

- **DOI:** 10.1016/j.lanhl.2025.100695
- **Trial registry:** ISRCTN29932357
- **Journal:** Lancet Healthy Longevity, 2025;6:100695
- **Type:** Original RCT
- **Expected classification:**
  - role: `published_results`
  - design: `rct`
  - tier: `A1`
  - direct: `true`
  - strict: `true`
- **Demonstrates:** Clean null reporting with full CI; adverse event accounting
- **Gold passages:**
  - "Mean 4-m walk speed at 4 months was 0.57 m/s (SD 0.19) in the metformin group and 0.58 m/s (0.24) in the placebo group (adjusted treatment effect 0.001 m/s [95% CI –0.06 to 0.06]; p=0.96)."
  - "Metformin did not improve 4-m walk speed and was poorly tolerated in this population."

## 5. Kulkarni 2022 — Geroscience-guided repurposing

- **DOI:** 10.1111/acel.13596
- **Journal:** Aging Cell, 2022;21:e13596
- **Type:** Methodology / framework review
- **Expected classification:**
  - role: `review`
  - design: `review`
  - tier: `B`
  - direct: `false` (indirect)
  - strict: `false`
- **Demonstrates:** Regulatory framing; methodology rigor

## 6. Keys 2025 — Emerging uncertainty

- **DOI:** 10.1016/j.arr.2025.102817
- **Journal:** Ageing Research Reviews, 2025;111:102817
- **Type:** Critical review
- **Expected classification:**
  - role: `review`
  - design: `review`
  - tier: `B`
  - direct: `false`
  - strict: `false`
- **Demonstrates:** Review-level synthesis with proper hedging

## 7. Mohammed 2021 — Critical review

- **DOI:** 10.3389/fendo.2021.718942
- **Journal:** Frontiers in Endocrinology, 2021;12:718942
- **Type:** Critical review
- **Expected classification:**
  - role: `review`
  - design: `review`
  - tier: `B`
  - direct: `false`
  - strict: `false`
- **Demonstrates:** Separating direct from indirect mechanisms in conclusion
- **Gold passage:**
  - "The beneficial effects of metformin on aging and healthspan are primarily indirect via its effects on cellular metabolism and result from its anti-hyperglycemic action..."

---

## How these are wired into the build

1. **Writer prompt** (`agent/prompts/writer_quality_bar.md`) embeds the gold passages verbatim with the instruction "your output must read at this caliber." Loaded at runtime by `compiler.py` Stage 8.

2. **SPAR judge checklist** (`agent/prompts/judge_quality_checklist.md`) keys 7 specific quality questions to these papers (e.g., "does the draft round any p-value to 'essentially zero' — Konopka p=0.08 must NOT be reported as significant"). Loaded by `spar.py` Stage 7.

3. **Classification regression test** — `tests/test_quality_reference_classification.py` asserts that if any of these 7 papers shows up in the bot's actual retrieval, `evidence_cards.py` classifies them according to the `Expected classification` block above. Catches role-classifier drift.

## Re-acquiring the PDFs

Each paper's DOI resolves on Sci-Hub mirrors / institutional access / arXiv / publisher OA. Local copies are not required for the build — the structured metadata above is what actually feeds the prompts.

## Phase 1 / 1.5 — `parsed/` artifacts

`scripts/pdf_ingest.py` (Day 10.17 Phase 1) reads each PDF in `pdfs/` and writes a `paper_sections.json` artifact into `parsed/`. The PDFs themselves are gitignored (binary, copyrighted) but the `parsed/` JSON IS tracked — it serves as:

1. The Phase 2+ claim-extraction input (so downstream stages don't need PyMuPDF).
2. The committed audit record of what the parser extracted at each commit, useful for catching parser regressions in CI.
3. A way for cloners without the PDFs to still see what the parser saw.

To regenerate after parser changes:

```bash
for pdf in docs/quality-reference/metformin/pdfs/*.pdf; do
  python scripts/pdf_ingest.py "$pdf" \
    --out "docs/quality-reference/metformin/parsed/$(basename "$pdf" .pdf).paper_sections.json"
done
```

Per-paper gold checks live in `tests/test_pdf_ingest.py::test_per_paper_metadata_matches_readme_gold` — they cross-check the `paper_sections.json` against the metadata block above.

## Phase 2 — `quant_claims/` artifacts

`scripts/quant_claim_extract.py` (Day 10.17 Phase 2) reads each `parsed/*.paper_sections.json` and emits structured quantitative-claim records to `quant_claims/{paper_id}.quant_claims.json`. Each record carries:

- `claim_type` — one of `p_value | confidence_interval | sample_size | mean_sd | percentage | unit_value`
- `numeric_values` — tuple of floats (1 for scalar claims, 2 for CI bounds / mean±SD pairs)
- `units` — SI/clinical unit token (`%`, `m/s`, `mmHg`, etc.) or `""` for dimensionless
- `source_section` + `source_offset` + `sentence` + `context_window` — source-text traceability

The extractor is deterministic regex (NOT LLM) per the AGENTS.md "code disposes" rule — Phase 2 produces gold-benchmark data for Phase 4, so reproducibility is non-negotiable.

To regenerate after extractor changes:

```bash
for parsed in docs/quality-reference/metformin/parsed/*.json; do
  name=$(basename "$parsed" .paper_sections.json)
  python scripts/quant_claim_extract.py "$parsed" \
    --out "docs/quality-reference/metformin/quant_claims/${name}.quant_claims.json"
done
```

Per-paper reasonableness (current corpus, v0.2):

| Paper | total | p_value | CI | n= | % | mean±SD | unit |
|---|---|---|---|---|---|---|---|
| Walton MASTERS (RCT) | 180 | 75 | 0 | 12 | 65 | 1 | 27 |
| Konopka 2019 (RCT) | 196 | 35 | 0 | 21 | 26 | 59 | 55 |
| Witham MET-PREVENT (Lancet RCT) | 210 | 3 | 3 | 17 | 110 | 0 | 77 |
| Kulkarni 2022 (review) | 54 | 5 | 0 | 2 | 35 | 5 | 7 |
| Keys 2025 (review) | 54 | 1 | 0 | 8 | 24 | 0 | 21 |
| Mohammed 2021 (review) | 33 | 0 | 0 | 0 | 17 | 0 | 16 |
| MILES 2018 (short take) | 5 | 0 | 0 | 1 | 0 | 0 | 4 |

**Known limitations (v0.1 / v0.2):**
- Tables are NOT extracted (Phase 1 captures captions only). Witham puts most stats inside trial summary tables, hence the small `p_value` count for a heavy-stats paper.
- Hazard ratios, odds ratios, Cohen's d, correlation coefficients deferred to Phase 2.1 (see `# TODO(phase 2.1)` in extractor).
- References section is intentionally skipped (citation-year false positives).
