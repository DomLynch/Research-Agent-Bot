# L6 Retrofit Report

Generated: `2026-05-08T11:47:57Z`

L6 is confirmed only when the real consecutive certification gate returns `l6_reproducibly_journal_ready=true`.

| Topic | Status | Runs | L5+ | Candidate pairs | Confirmed pair | Reason |
|---|---|---:|---:|---:|---|---|
| acarbose | blocked | 2 | 2 | 1 |  | candidate pair did not pass clean L6 gate |
| aerobic_exercise | no_data | 1 | 0 | 0 |  | no adjacent L5 pair and latest run is not L5 |
| aspirin | no_data | 7 | 0 | 0 |  | no adjacent L5 pair and latest run is not L5 |
| berberine | needs_rerun | 2 | 1 | 0 |  | latest run is L5; one adjacent L5 rerun could form a pair |
| caloric_restriction | confirmed_l6 | 8 | 5 | 2 | synthesis-caloric_restriction-v06-PATH1FIX2-2026-05-07T19-08-03Z, synthesis-caloric_restriction-v06-CONTRIB-2026-05-08T00-58-42Z | real consecutive certification gate passed |
| corpus | no_data | 1 | 0 | 0 |  | no adjacent L5 pair and latest run is not L5 |
| creatine | confirmed_l6 | 12 | 7 | 3 | synthesis-creatine-v06-PATH2RICHFIX2-2026-05-07T22-34-47Z, synthesis-creatine-v06-PATH2RICHFIX3-2026-05-07T22-44-26Z | real consecutive certification gate passed |
| diagnostic | no_data | 1 | 0 | 0 |  | no adjacent L5 pair and latest run is not L5 |
| e2e | no_data | 1 | 0 | 0 |  | no adjacent L5 pair and latest run is not L5 |
| everolimus | no_data | 11 | 0 | 0 |  | no adjacent L5 pair and latest run is not L5 |
| glp1 | confirmed_l6 | 19 | 8 | 4 | synthesis-glp1-v06-PATH2RICHFIX-2026-05-07T22-00-20Z, synthesis-glp1-v06-CONTRIB-2026-05-08T00-58-42Z | real consecutive certification gate passed |
| intermittent_fasting | blocked | 2 | 2 | 1 |  | candidate pair did not pass clean L6 gate |
| metformin | confirmed_l6 | 116 | 8 | 3 | synthesis-metformin-v06-PATHABASKET84-2026-05-07T09-56-19Z, synthesis-metformin-v06-PATH2RICH-2026-05-07T21-35-47Z | real consecutive certification gate passed |
| nad_precursors | confirmed_l6 | 4 | 2 | 1 | synthesis-nad_precursors-v06-PATH1-2026-05-07T17-23-53Z, synthesis-nad_precursors-v06-PATH1FIX-2026-05-07T17-40-21Z | real consecutive certification gate passed |
| omega3 | confirmed_l6 | 9 | 4 | 3 | synthesis-omega3-v06-PATH2-2026-05-07T15-59-34Z, synthesis-omega3-v06-PATH2RICH-2026-05-07T21-07-13Z | real consecutive certification gate passed |
| protein_nutrition | confirmed_l6 | 3 | 2 | 1 | synthesis-protein_nutrition-v06-FIXED-2026-05-05T23-37-32Z, synthesis-protein_nutrition-v06-WIDEBASKET-2026-05-07T23-01-16Z | real consecutive certification gate passed |
| publication | no_data | 1 | 0 | 0 |  | no adjacent L5 pair and latest run is not L5 |
| rapamycin | confirmed_l6 | 95 | 18 | 7 | synthesis-rapamycin-v06-CORPUSFIX20-2026-05-07T02-10-00Z, synthesis-rapamycin-v06-CORPUSFIX21-2026-05-07T02-35-00Z | real consecutive certification gate passed |
| reports | no_data | 1 | 0 | 0 |  | no adjacent L5 pair and latest run is not L5 |
| resistance_training | blocked | 5 | 4 | 2 |  | candidate pair did not pass clean L6 gate |
| senolytics | no_data | 1 | 0 | 0 |  | no adjacent L5 pair and latest run is not L5 |
| statins | confirmed_l6 | 28 | 6 | 3 | synthesis-statins-v06-PATH2RICHFIX2-2026-05-07T20-21-40Z, synthesis-statins-v06-PATH2RICHFIX3-2026-05-07T20-44-41Z | real consecutive certification gate passed |
| vitamin_d | no_data | 1 | 0 | 0 |  | no adjacent L5 pair and latest run is not L5 |
| zone2_training | needs_rerun | 3 | 1 | 0 |  | latest run is L5; one adjacent L5 rerun could form a pair |

## Blocked Candidate Details

- `acarbose` pair `['synthesis-acarbose-v06-ACTIVE-2026-05-05T22-49-00Z', 'synthesis-acarbose-v06-PATH1-2026-05-07T17-01-11Z']`: synthesis-acarbose-v06-ACTIVE-2026-05-05T22-49-00Z: flagged_patches=4; synthesis-acarbose-v06-PATH1-2026-05-07T17-01-11Z: flagged_patches=1
- `intermittent_fasting` pair `['synthesis-intermittent_fasting-v06-ACTIVE-2026-05-05T22-34-23Z', 'synthesis-intermittent_fasting-v06-WIDEBASKET-2026-05-07T23-15-06Z']`: synthesis-intermittent_fasting-v06-ACTIVE-2026-05-05T22-34-23Z: flagged_patches=3
- `resistance_training` pair `['synthesis-resistance_training-v06-ACTIVE-2026-05-05T22-34-24Z', 'synthesis-resistance_training-v06-WIDEBASKET-2026-05-07T23-31-33Z']`: synthesis-resistance_training-v06-ACTIVE-2026-05-05T22-34-24Z: flagged_patches=2; synthesis-resistance_training-v06-WIDEBASKET-2026-05-07T23-31-33Z: flagged_patches=1
- `resistance_training` pair `['synthesis-resistance_training-v06-WIDEBASKETFIX2-2026-05-07T23-58-31Z', 'synthesis-resistance_training-v06-WIDEBASKETFIX3-2026-05-08T00-10-29Z']`: synthesis-resistance_training-v06-WIDEBASKETFIX2-2026-05-07T23-58-31Z: flagged_patches=1

## Next Reruns

- `berberine`: `python3 scripts/run_v06_synthesis.py --topic berberine`
- `zone2_training`: `python3 scripts/run_v06_synthesis.py --topic zone2_training`
