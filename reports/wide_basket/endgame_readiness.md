# Wide Basket Deep Execution Plan

## Inventory

- topic packs: 25
- run dirs: 282
- mapped topics: 18
- run topics without pack: none
- queue manifest topics: 18
- queue topics without pack: none

## First 10 Run-Now Topics

| order | topic | priority | latest run | receipts | pack risk | next command |
| ---: | --- | ---: | --- | ---: | --- | --- |
| 1 | `resistance_training` | 164 | `synthesis-resistance_training-v06-WIDEBASKETFIX3-2026-05-08T00-10-29Z` | 78 | no_canonical_trials | `python scripts/run_v06_synthesis.py --topic resistance_training --dry-run` |
| 2 | `protein_nutrition` | 164 | `synthesis-protein_nutrition-v06-WIDEBASKET-2026-05-07T23-01-16Z` | 92 | no_canonical_trials | `python scripts/run_v06_synthesis.py --topic protein_nutrition --dry-run` |
| 3 | `intermittent_fasting` | 164 | `synthesis-intermittent_fasting-v06-WIDEBASKET-2026-05-07T23-15-06Z` | 76 | no_canonical_trials | `python scripts/run_v06_synthesis.py --topic intermittent_fasting --dry-run` |
| 4 | `zone2_training` | 149 | `synthesis-zone2_training-v06-PATH1FIX-2026-05-07T18-11-50Z` | 36 | no_canonical_trials | `python scripts/run_v06_synthesis.py --topic zone2_training --dry-run` |
| 5 | `acarbose` | 132 | `synthesis-acarbose-v06-PATH1-2026-05-07T17-01-11Z` | 19 | no_canonical_trials | `python scripts/run_v06_synthesis.py --topic acarbose --dry-run` |
| 6 | `berberine` | 129 | `synthesis-berberine-v06-PATH1-2026-05-07T17-14-38Z` | 15 | no_canonical_trials | `python scripts/run_v06_synthesis.py --topic berberine --dry-run` |
| 7 | `everolimus` | 119 | `none` | 0 | none | `python scripts/run_v06_synthesis.py --topic everolimus --dry-run` |
| 8 | `taurine` | 114 | `none` | 0 | no_canonical_trials | `python scripts/run_v06_synthesis.py --topic taurine --dry-run` |
| 9 | `spermidine` | 114 | `none` | 0 | no_canonical_trials | `python scripts/run_v06_synthesis.py --topic spermidine --dry-run` |
| 10 | `sleep_health` | 114 | `none` | 0 | no_canonical_trials | `python scripts/run_v06_synthesis.py --topic sleep_health --dry-run` |

Acceptance gates for run-now dry runs:

- manifest exists
- receipts >= 10
- js_pass != false
- grok_flags == 0
- dry-run artifacts complete

## Corpus Tune First

| topic | latest failure | pack bottlenecks | tune command |
| --- | --- | --- | --- |
| `aspirin` | corpus-thin | artifact-blocked | `python scripts/seed_topic_corpus.py --topic aspirin --max-per-source 35` |
| `nad_precursors` | corpus-thin | artifact-blocked | `python scripts/seed_topic_corpus.py --topic nad_precursors --max-per-source 35` |
| `senolytics` | grok | artifact-blocked | `python scripts/seed_topic_corpus.py --topic senolytics --max-per-source 35` |
| `aerobic_exercise` | corpus-thin | no_canonical_trials | `python scripts/seed_topic_corpus.py --topic aerobic_exercise --max-per-source 35` |
| `vitamin_d` | grok | no_canonical_trials | `python scripts/seed_topic_corpus.py --topic vitamin_d --max-per-source 35` |

## L6 Reruns

| topic | latest rich | next command | acceptance gates |
| --- | --- | --- | --- |
| `metformin` | `synthesis-metformin-v06-PATH2RICHFIX5-2026-05-08TCLASSIFIER` | `python scripts/run_v06_synthesis.py --topic metformin --dry-run` | manifest exists; receipts >= 10; js_pass != false; grok_flags == 0; maturity_level >= 5 |
| `glp1` | `synthesis-glp1-v06-PATH2RICHFIX5-2026-05-08T08-10-00Z` | `python scripts/run_v06_synthesis.py --topic glp1 --dry-run` | manifest exists; receipts >= 10; js_pass != false; grok_flags == 0; maturity_level >= 5 |
| `rapamycin` | `synthesis-rapamycin-v06-PATH2RICHFIX4-2026-05-08TCLASSIFIER` | `python scripts/run_v06_synthesis.py --topic rapamycin --dry-run` | manifest exists; receipts >= 10; js_pass != false; grok_flags == 0; maturity_level >= 5 |

## All Topics

| topic | bucket | status | aliases | queries | canonical trials | latest failure | failure bucket | latest rich failure | rich delta |
| --- | --- | --- | ---: | ---: | ---: | --- | --- | --- | --- |
| `acarbose` | run_now | ready | 3 | 5 | 0 | pass | none | not-run | maturity , receipts  |
| `aerobic_exercise` | corpus_tune_first | needs corpus tuning | 6 | 5 | 0 | corpus-thin | thin_corpus | not-run | maturity , receipts  |
| `aspirin` | corpus_tune_first | needs corpus tuning | 8 | 10 | 4 | corpus-thin | thin_corpus | not-run | maturity , receipts  |
| `berberine` | run_now | ready | 3 | 5 | 0 | pass | none | not-run | maturity , receipts  |
| `caloric_restriction` | rich_monitor | rich baseline present | 5 | 5 | 0 | pass | none | pass | maturity 0, receipts 36 |
| `collagen_peptides` | run_now | ready | 5 | 5 | 0 | not-run | not_run | not-run | maturity , receipts  |
| `creatine` | rich_monitor | rich baseline present | 4 | 5 | 0 | grok | grok | pass | maturity 0, receipts 0 |
| `everolimus` | run_now | ready | 7 | 6 | 1 | not-run | not_run | not-run | maturity , receipts  |
| `glp1` | l6_rerun | needs L6 confirmation | 16 | 7 | 6 | corpus-thin | thin_corpus | pass | maturity 0, receipts 0 |
| `intermittent_fasting` | run_now | ready | 6 | 5 | 0 | pass | none | not-run | maturity , receipts  |
| `metformin` | l6_rerun | needs L6 confirmation | 5 | 6 | 4 | pass | none | pass | maturity 1, receipts 28 |
| `nad_precursors` | corpus_tune_first | needs corpus tuning | 13 | 7 | 3 | corpus-thin | thin_corpus | not-run | maturity , receipts  |
| `omega3` | rich_monitor | rich baseline present | 7 | 5 | 0 | js | surface_gate | pass | maturity 0, receipts 29 |
| `protein_nutrition` | run_now | ready | 6 | 5 | 0 | pass | none | not-run | maturity , receipts  |
| `rapamycin` | l6_rerun | needs L6 confirmation | 5 | 6 | 4 | grok | grok | pass | maturity 0, receipts 0 |
| `resistance_training` | run_now | ready | 5 | 5 | 0 | pass | none | not-run | maturity , receipts  |
| `sauna_heat_therapy` | run_now | ready | 5 | 5 | 0 | not-run | not_run | not-run | maturity , receipts  |
| `senolytics` | corpus_tune_first | needs corpus tuning | 11 | 7 | 3 | grok | grok | not-run | maturity , receipts  |
| `sleep_health` | run_now | ready | 7 | 5 | 0 | not-run | not_run | not-run | maturity , receipts  |
| `spermidine` | run_now | ready | 3 | 5 | 0 | not-run | not_run | not-run | maturity , receipts  |
| `statins` | rich_monitor | rich baseline present | 11 | 13 | 4 | grok | grok | pass | maturity 0, receipts 31 |
| `taurine` | run_now | ready | 3 | 5 | 0 | not-run | not_run | not-run | maturity , receipts  |
| `urolithin_a` | run_now | ready | 4 | 5 | 0 | not-run | not_run | not-run | maturity , receipts  |
| `vitamin_d` | corpus_tune_first | needs corpus tuning | 5 | 5 | 0 | grok | grok | not-run | maturity , receipts  |
| `zone2_training` | run_now | ready | 5 | 5 | 0 | pass | none | not-run | maturity , receipts  |
