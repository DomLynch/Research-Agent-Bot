# Wide Basket Expansion Report

## Executive Summary

- Topic packs inventoried: 25
- Synthesis run dirs inventoried: 282
- Run topics mapped to packs: 18
- Unmapped run topics: none
- Existing rich topics: caloric_restriction, creatine, glp1, metformin, omega3, rapamycin, statins
- Next no-rich queue topics: 18
- Cert regressions vs oldest acceptable baseline: 0
- Corpus regressions vs oldest acceptable baseline: 0
- L6 reruns needed: 3
- Latest-rich journal-surface blocks: 0

## Evidence Richness Ranking

| rank | topic | best_receipts | best_maturity | runs | rich_runs |
| ---: | --- | ---: | ---: | ---: | ---: |
| 1 | `protein_nutrition` | 92 | 5 | 3 | 0 |
| 2 | `resistance_training` | 78 | 5 | 5 | 0 |
| 3 | `intermittent_fasting` | 76 | 5 | 2 | 0 |
| 4 | `statins` | 53 | 5 | 28 | 7 |
| 5 | `caloric_restriction` | 47 | 5 | 8 | 1 |
| 6 | `metformin` | 45 | 5 | 96 | 6 |
| 7 | `omega3` | 45 | 5 | 9 | 3 |
| 8 | `zone2_training` | 36 | 5 | 3 | 0 |
| 9 | `glp1` | 29 | 5 | 19 | 6 |
| 10 | `acarbose` | 19 | 5 | 2 | 0 |
| 11 | `rapamycin` | 16 | 5 | 79 | 5 |
| 12 | `creatine` | 15 | 5 | 12 | 7 |
| 13 | `berberine` | 15 | 5 | 2 | 0 |
| 14 | `nad_precursors` | 15 | 5 | 4 | 0 |
| 15 | `aerobic_exercise` | 5 | 2 | 1 | 0 |

## Next 18 Topic Queue

| order | topic | status | corpus | latest failure | latest run |
| ---: | --- | --- | --- | --- | --- |
| 1 | `acarbose` | ready | medium | pass | `synthesis-acarbose-v06-PATH1-2026-05-07T17-01-11Z` |
| 2 | `berberine` | ready | medium | pass | `synthesis-berberine-v06-PATH1-2026-05-07T17-14-38Z` |
| 3 | `collagen_peptides` | ready | medium | not-run | `none` |
| 4 | `everolimus` | ready | medium | not-run | `none` |
| 5 | `intermittent_fasting` | ready | medium | pass | `synthesis-intermittent_fasting-v06-WIDEBASKET-2026-05-07T23-15-06Z` |
| 6 | `protein_nutrition` | ready | medium | pass | `synthesis-protein_nutrition-v06-WIDEBASKET-2026-05-07T23-01-16Z` |
| 7 | `resistance_training` | ready | medium | pass | `synthesis-resistance_training-v06-WIDEBASKETFIX3-2026-05-08T00-10-29Z` |
| 8 | `sauna_heat_therapy` | ready | medium | not-run | `none` |
| 9 | `sleep_health` | ready | medium | not-run | `none` |
| 10 | `spermidine` | ready | medium | not-run | `none` |
| 11 | `taurine` | ready | medium | not-run | `none` |
| 12 | `urolithin_a` | ready | medium | not-run | `none` |
| 13 | `zone2_training` | ready | medium | pass | `synthesis-zone2_training-v06-PATH1FIX-2026-05-07T18-11-50Z` |
| 14 | `aspirin` | needs corpus tuning | high | corpus-thin | `synthesis-aspirin-v06-proof006-2026-05-04T16-05-37Z` |
| 15 | `nad_precursors` | needs corpus tuning | high | corpus-thin | `synthesis-nad_precursors-v06-proof006-2026-05-04T12-24-14Z` |
| 16 | `senolytics` | needs corpus tuning | high | grok | `synthesis-senolytics-v06-proof005-2026-05-04T12-17-51Z` |
| 17 | `aerobic_exercise` | needs corpus tuning | medium | corpus-thin | `synthesis-aerobic_exercise-v06-DIAG-2026-05-05T23-06-41Z` |
| 18 | `vitamin_d` | needs corpus tuning | medium | grok | `synthesis-vitamin_d-v06-DIAG-2026-05-05T23-22-44Z` |

## Top 10 Next Run Commands

### acarbose
```bash
python scripts/seed_topic_corpus.py --topic acarbose --max-per-source 25
python scripts/run_v06_synthesis.py --topic acarbose --dry-run
```

### berberine
```bash
python scripts/seed_topic_corpus.py --topic berberine --max-per-source 25
python scripts/run_v06_synthesis.py --topic berberine --dry-run
```

### collagen_peptides
```bash
python scripts/seed_topic_corpus.py --topic collagen_peptides --max-per-source 25
python scripts/run_v06_synthesis.py --topic collagen_peptides --dry-run
```

### everolimus
```bash
python scripts/seed_topic_corpus.py --topic everolimus --max-per-source 25
python scripts/run_v06_synthesis.py --topic everolimus --dry-run
```

### intermittent_fasting
```bash
python scripts/seed_topic_corpus.py --topic intermittent_fasting --max-per-source 25
python scripts/run_v06_synthesis.py --topic intermittent_fasting --dry-run
```

### protein_nutrition
```bash
python scripts/seed_topic_corpus.py --topic protein_nutrition --max-per-source 25
python scripts/run_v06_synthesis.py --topic protein_nutrition --dry-run
```

### resistance_training
```bash
python scripts/seed_topic_corpus.py --topic resistance_training --max-per-source 25
python scripts/run_v06_synthesis.py --topic resistance_training --dry-run
```

### sauna_heat_therapy
```bash
python scripts/seed_topic_corpus.py --topic sauna_heat_therapy --max-per-source 25
python scripts/run_v06_synthesis.py --topic sauna_heat_therapy --dry-run
```

### sleep_health
```bash
python scripts/seed_topic_corpus.py --topic sleep_health --max-per-source 25
python scripts/run_v06_synthesis.py --topic sleep_health --dry-run
```

### spermidine
```bash
python scripts/seed_topic_corpus.py --topic spermidine --max-per-source 25
python scripts/run_v06_synthesis.py --topic spermidine --dry-run
```

## Needs Corpus Tuning

| topic | reason | suggested first action |
| --- | --- | --- |
| `aspirin` | latest failure=corpus-thin; queries=10 | `python scripts/seed_topic_corpus.py --topic aspirin --max-per-source 35` |
| `nad_precursors` | latest failure=corpus-thin; queries=7 | `python scripts/seed_topic_corpus.py --topic nad_precursors --max-per-source 35` |
| `senolytics` | latest failure=grok; queries=7 | `python scripts/seed_topic_corpus.py --topic senolytics --max-per-source 35` |
| `aerobic_exercise` | latest failure=corpus-thin; queries=5 | `python scripts/seed_topic_corpus.py --topic aerobic_exercise --max-per-source 35` |
| `vitamin_d` | latest failure=grok; queries=5 | `python scripts/seed_topic_corpus.py --topic vitamin_d --max-per-source 35` |

## Rich vs Oldest Acceptable Baseline

| topic | latest rich | baseline | maturity delta | receipt delta | JS |
| --- | --- | --- | ---: | ---: | --- |
| `caloric_restriction` | `synthesis-caloric_restriction-v06-PATH2RICHFIX2-2026-05-08T15-10-00Z` | `synthesis-caloric_restriction-v06-ACTIVE-2026-05-05T22-49-00Z` | 0 | 36 | true |
| `creatine` | `synthesis-creatine-v06-PATH2RICHFIX3-2026-05-08T09-10-00Z` | `synthesis-creatine-v06-ACTIVE-2026-05-05T22-47-50Z` | 0 | 0 | true |
| `glp1` | `synthesis-glp1-v06-PATH2RICHFIX5-2026-05-08T08-10-00Z` | `synthesis-glp1-v06-ACTIVE3-2026-05-05T22-18-50Z` | 0 | 0 | true |
| `metformin` | `synthesis-metformin-v06-PATH2RICHFIX5-2026-05-08TCLASSIFIER` | `synthesis-metformin-v06-2026-05-02T16-49-37Z` | 1 | 28 | true |
| `omega3` | `synthesis-omega3-v06-PATH2RICHFIX2-2026-05-08TCLASSIFIER` | `synthesis-omega3-v06-PATH2-2026-05-07T15-59-34Z` | 0 | 29 | true |
| `rapamycin` | `synthesis-rapamycin-v06-PATH2RICHFIX4-2026-05-08TCLASSIFIER` | `synthesis-rapamycin-v06-CORPUSFIX15-2026-05-07T00-05-00Z` | 0 | 0 | true |
| `statins` | `synthesis-statins-v06-PATH2RICHFIX4-2026-05-08TCLASSIFIER` | `synthesis-statins-v06-PATH2FIX2-2026-05-07T16-35-54Z` | 0 | 31 | true |

## L6 Rerun Plan

- `glp1`: rerun latest rich path after confirming no JS/Grok drift; current latest rich `synthesis-glp1-v06-PATH2RICHFIX5-2026-05-08T08-10-00Z` is L5 but not L6 by local consecutive-run heuristic.
- `metformin`: rerun latest rich path after confirming no JS/Grok drift; current latest rich `synthesis-metformin-v06-PATH2RICHFIX5-2026-05-08TCLASSIFIER` is L5 but not L6 by local consecutive-run heuristic.
- `rapamycin`: rerun latest rich path after confirming no JS/Grok drift; current latest rich `synthesis-rapamycin-v06-PATH2RICHFIX4-2026-05-08TCLASSIFIER` is L5 but not L6 by local consecutive-run heuristic.

## Publication And OSF Cross-Reference

- Reader publication report exists: 6 rows; not public-static-ready: metformin, statins.
- OSF provenance drill exists: 11/11 dry-run checks OK; live proven remains separate from this basket queue.

## Missing Pack Watchlist

These are not queued because no topic pack exists locally:

- `alpha_ketoglutarate`: needs-pack
- `glynac`: needs-pack
- `coq10`: needs-pack
- `melatonin`: needs-pack
- `magnesium`: needs-pack
- `glycine`: needs-pack
- `fisetin_standalone`: needs-pack
- `quercetin_standalone`: needs-pack
- `hyaluronic_acid`: needs-pack
- `dhea`: needs-pack

## Corpus-Thin Investigation Plan

- Reseed each needs-corpus topic with a higher `--max-per-source` before synthesis.
- For aspirin and nad_precursors, check whether low receipt count is from filter strictness vs missing canonical role overrides.
- For senolytics and vitamin_d, inspect Grok failures before widening corpus; a wider corpus may not fix role/verdict issues.

## No-Topic-Hardcoding Audit

- Queue topics come from `topic_packs/*.toml` minus local `*RICH*` run topics.
- Rich/baseline comparisons come from run-dir names and artifact JSON only.
- Missing-pack watchlist is advisory and excluded from queue JSON.

## Next Rerun Order

1. Run the first 10 ready queue topics above in dry-run mode.
2. Then run remaining ready no-rich topics: `taurine`, `urolithin_a`, `zone2_training`.
3. Reseed and rerun needs-corpus topics only after corpus tuning.
4. Run L6 confirmations for: `glp1`, `metformin`, `rapamycin`.
