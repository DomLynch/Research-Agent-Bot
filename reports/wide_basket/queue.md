# Wide Basket Queue

## Inventory

- topic packs: 25
- run dirs: 282
- rich topics: caloric_restriction, creatine, glp1, metformin, omega3, rapamycin, statins
- unmapped run topics: none

## Evidence Richness

| topic | best_receipts | best_maturity | runs | rich_runs |
| --- | --- | --- | --- | --- |
| protein_nutrition | 92 | 5 | 3 | 0 |
| resistance_training | 78 | 5 | 5 | 0 |
| intermittent_fasting | 76 | 5 | 2 | 0 |
| statins | 53 | 5 | 28 | 7 |
| caloric_restriction | 47 | 5 | 8 | 1 |
| metformin | 45 | 5 | 96 | 6 |
| omega3 | 45 | 5 | 9 | 3 |
| zone2_training | 36 | 5 | 3 | 0 |
| glp1 | 29 | 5 | 19 | 6 |
| acarbose | 19 | 5 | 2 | 0 |
| rapamycin | 16 | 5 | 79 | 5 |
| creatine | 15 | 5 | 12 | 7 |
| berberine | 15 | 5 | 2 | 0 |
| nad_precursors | 15 | 5 | 4 | 0 |
| aerobic_exercise | 5 | 2 | 1 | 0 |
| vitamin_d | 2 | 2 | 1 | 0 |
| aspirin | 1 | 5 | 7 | 0 |
| senolytics | 1 | 4 | 1 | 0 |
| collagen_peptides | 0 | 0 | 0 | 0 |
| everolimus | 0 | 0 | 0 | 0 |

## Next Queue

| topic | status | corpus_expectation | latest_run | latest_failure | notes |
| --- | --- | --- | --- | --- | --- |
| acarbose | ready | medium | synthesis-acarbose-v06-PATH1-2026-05-07T17-01-11Z | pass | latest local signal does not block queueing |
| berberine | ready | medium | synthesis-berberine-v06-PATH1-2026-05-07T17-14-38Z | pass | latest local signal does not block queueing |
| collagen_peptides | ready | medium |  | not-run | topic pack has enough corpus queries; no local run yet |
| everolimus | ready | medium |  | not-run | topic pack has enough corpus queries; no local run yet |
| intermittent_fasting | ready | medium | synthesis-intermittent_fasting-v06-WIDEBASKET-2026-05-07T23-15-06Z | pass | latest local signal does not block queueing |
| protein_nutrition | ready | medium | synthesis-protein_nutrition-v06-WIDEBASKET-2026-05-07T23-01-16Z | pass | latest local signal does not block queueing |
| resistance_training | ready | medium | synthesis-resistance_training-v06-WIDEBASKETFIX3-2026-05-08T00-10-29Z | pass | latest local signal does not block queueing |
| sauna_heat_therapy | ready | medium |  | not-run | topic pack has enough corpus queries; no local run yet |
| sleep_health | ready | medium |  | not-run | topic pack has enough corpus queries; no local run yet |
| spermidine | ready | medium |  | not-run | topic pack has enough corpus queries; no local run yet |
| taurine | ready | medium |  | not-run | topic pack has enough corpus queries; no local run yet |
| urolithin_a | ready | medium |  | not-run | topic pack has enough corpus queries; no local run yet |
| zone2_training | ready | medium | synthesis-zone2_training-v06-PATH1FIX-2026-05-07T18-11-50Z | pass | latest local signal does not block queueing |
| aspirin | needs corpus tuning | high | synthesis-aspirin-v06-proof006-2026-05-04T16-05-37Z | corpus-thin | latest failure=corpus-thin; queries=10 |
| nad_precursors | needs corpus tuning | high | synthesis-nad_precursors-v06-proof006-2026-05-04T12-24-14Z | corpus-thin | latest failure=corpus-thin; queries=7 |
| senolytics | needs corpus tuning | high | synthesis-senolytics-v06-proof005-2026-05-04T12-17-51Z | grok | latest failure=grok; queries=7 |
| aerobic_exercise | needs corpus tuning | medium | synthesis-aerobic_exercise-v06-DIAG-2026-05-05T23-06-41Z | corpus-thin | latest failure=corpus-thin; queries=5 |
| vitamin_d | needs corpus tuning | medium | synthesis-vitamin_d-v06-DIAG-2026-05-05T23-22-44Z | grok | latest failure=grok; queries=5 |

## Rich vs Baseline

| topic | latest_rich | baseline | maturity_delta | receipt_delta | journal_surface |
| --- | --- | --- | --- | --- | --- |
| caloric_restriction | synthesis-caloric_restriction-v06-PATH2RICHFIX2-2026-05-08T15-10-00Z | synthesis-caloric_restriction-v06-ACTIVE-2026-05-05T22-49-00Z | 0 | 36 | true |
| creatine | synthesis-creatine-v06-PATH2RICHFIX3-2026-05-08T09-10-00Z | synthesis-creatine-v06-ACTIVE-2026-05-05T22-47-50Z | 0 | 0 | true |
| glp1 | synthesis-glp1-v06-PATH2RICHFIX5-2026-05-08T08-10-00Z | synthesis-glp1-v06-ACTIVE3-2026-05-05T22-18-50Z | 0 | 0 | true |
| metformin | synthesis-metformin-v06-PATH2RICHFIX5-2026-05-08TCLASSIFIER | synthesis-metformin-v06-2026-05-02T16-49-37Z | 1 | 28 | true |
| omega3 | synthesis-omega3-v06-PATH2RICHFIX2-2026-05-08TCLASSIFIER | synthesis-omega3-v06-PATH2-2026-05-07T15-59-34Z | 0 | 29 | true |
| rapamycin | synthesis-rapamycin-v06-PATH2RICHFIX4-2026-05-08TCLASSIFIER | synthesis-rapamycin-v06-CORPUSFIX15-2026-05-07T00-05-00Z | 0 | 0 | true |
| statins | synthesis-statins-v06-PATH2RICHFIX4-2026-05-08TCLASSIFIER | synthesis-statins-v06-PATH2FIX2-2026-05-07T16-35-54Z | 0 | 31 | true |

## Rerun Flags

- L6 reruns needed: 3
- journal-surface blocks: 0
- cert regressions: 0
- corpus regressions: 0
