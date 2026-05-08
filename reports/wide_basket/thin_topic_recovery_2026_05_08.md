# Thin Topic Corpus Recovery — 2026-05-08

Scope: taurine, spermidine, sleep_health, sauna_heat_therapy, everolimus,
collagen_peptides. `urolithin_a` was excluded from writes to avoid conflict
with the main workspace seed/dry-run.

No Python or topic-pack edits were made. Because the active write scope was
reports/run artifacts only, query/alias improvements are listed as next
actions rather than applied.

## Dry-Run Audit

Command shape, run twice per topic:

```bash
python3 scripts/run_v06_synthesis.py --topic <topic> --dry-run
```

| topic | audit 1 receipts | audit 1 tensions | audit 2 receipts | audit 2 tensions | status |
|---|---:|---:|---:|---:|---|
| taurine | 2 | 1 | 2 | 1 | SCOP/thin |
| spermidine | 2 | 0 | 2 | 0 | SCOP/thin |
| sleep_health | 0 | 0 | 0 | 0 | no high-confidence claims |
| sauna_heat_therapy | 1 | 0 | 1 | 0 | SCOP/thin |
| everolimus | 1 | 0 | 1 | 0 | SCOP/thin |
| collagen_peptides | 3 | 1 | 3 | 1 | SCOP/thin |

## Funnel Table

| topic | retrieved | keep | core | bg | adj | fulltext fetched | quant files | quant claims | receipts | receipt claims | tensions |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| taurine | 1662 | 250 | 9 | 138 | 103 | 38 | 38 | 1905 | 2 | 17 | 1 |
| spermidine | 1734 | 227 | 6 | 119 | 102 | 54 | 54 | 2434 | 2 | 22 | 0 |
| sleep_health | 2959 | 101 | 24 | 0 | 77 | 35 | 35 | 1719 | 0 | 0 | 0 |
| sauna_heat_therapy | 2352 | 322 | 50 | 31 | 241 | 49 | 49 | 2368 | 1 | 2 | 0 |
| everolimus | 1670 | 76 | 3 | 31 | 42 | 9 | 9 | 999 | 1 | 10 | 0 |
| collagen_peptides | 2399 | 408 | 28 | 130 | 250 | 70 | 70 | 5372 | 3 | 24 | 1 |

`fulltext fetched` is `_extract_report.n_extracted`. `core/bg/adj` are from
`corpus_manifest.json.funnel.extractable_*`.

## Bottlenecks

| topic | exact bottleneck | evidence |
|---|---|---|
| taurine | corpus has many extracted claims, but only 17 high-binding claims survive into 2 direct immune receipts | 38 quant files, 1905 quant claims, binding high=17, dry-run receipts=2 |
| spermidine | high-binding claim pool is too small and produces no non-orthogonal tensions | 54 quant files, 2434 quant claims, binding high=22, receipts=2, tensions=0 |
| sleep_health | extraction produced claims, but none survive high-confidence receipt construction | 35 quant files, 1719 quant claims, binding high=0, receipts=0 |
| sauna_heat_therapy | broad retrieval and many extracted papers, but only 2 high-binding claims survive | 49 quant files, 2368 quant claims, binding high=2, receipts=1 |
| everolimus | topic is corpus-thin at extraction stage and only one paper survives receipt construction | 9 quant files, 999 quant claims, binding high=10, receipts=1 |
| collagen_peptides | large extracted corpus, but high-binding claims concentrate into 3 receipts | 70 quant files, 5372 quant claims, binding high=24, receipts=3 |

## Before / After

No query or alias changes were applied in this lane because topic-pack/corpus
files were outside the active write scope. The second audit therefore serves
as the after/no-change confirmation.

| topic | before receipts/tensions | after receipts/tensions | delta |
|---|---:|---:|---:|
| taurine | 2 / 1 | 2 / 1 | 0 / 0 |
| spermidine | 2 / 0 | 2 / 0 | 0 / 0 |
| sleep_health | 0 / 0 | 0 / 0 | 0 / 0 |
| sauna_heat_therapy | 1 / 0 | 1 / 0 | 0 / 0 |
| everolimus | 1 / 0 | 1 / 0 | 0 / 0 |
| collagen_peptides | 3 / 1 | 3 / 1 | 0 / 0 |

## Promotion Decision

No topic is promoted to full synthesis. Promotion threshold was >=10 receipts
with usable tensions; the best result was collagen_peptides at 3 receipts and
1 tension.

## Next Actions

- Keep `urolithin_a` read-only until the main workspace integration lands.
- For sleep_health and sauna_heat_therapy, inspect why high-binding effect
  claims are not produced despite 24 and 50 extractable core records.
- For taurine, spermidine, and collagen_peptides, tune topic-pack aliases or
  corpus selection toward interventional human supplementation papers, then
  re-run dry-runs.
- For everolimus, recover an on-domain longevity/immune-aging corpus rather
  than oncology/stent papers before attempting synthesis.

## Evidence Files

- `reports/wide_basket/taurine_dry_run_2026_05_08.txt`
- `reports/wide_basket/taurine_dry_run_audit2_2026_05_08.txt`
- `reports/wide_basket/spermidine_dry_run_2026_05_08.txt`
- `reports/wide_basket/spermidine_dry_run_audit2_2026_05_08.txt`
- `reports/wide_basket/sleep_health_dry_run_2026_05_08.txt`
- `reports/wide_basket/sleep_health_dry_run_audit2_2026_05_08.txt`
- `reports/wide_basket/sauna_heat_therapy_dry_run_2026_05_08.txt`
- `reports/wide_basket/sauna_heat_therapy_dry_run_audit2_2026_05_08.txt`
- `reports/wide_basket/everolimus_dry_run_2026_05_08.txt`
- `reports/wide_basket/everolimus_dry_run_audit2_2026_05_08.txt`
- `reports/wide_basket/collagen_peptides_dry_run_2026_05_08.txt`
- `reports/wide_basket/collagen_peptides_dry_run_audit2_2026_05_08.txt`
