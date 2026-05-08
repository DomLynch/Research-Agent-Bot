# L6 Reproducibility Campaign

Generated: `2026-05-08T11:34:14Z`

## Honest Claim Boundary

- L5: one run is clean journal-ready under the certification code, including no flagged or auto-stripped patch scars.
- L6: an adjacent same-topic pair passes `PYTHONPATH=. python3 scripts/certification_report.py --consecutive ...` with `l6_reproducibly_journal_ready=true`.
- Batch candidates are triage evidence only; they are not L6 claims until the real consecutive gate passes.

## Counts

- `alternating_topics`: 6
- `candidate_cert_blocked`: 3
- `candidate_missing_artifacts`: 0
- `certified_l6_today`: 4
- `l5_journal_surface_failure_topics`: 0
- `one_more_l5_topics`: 7
- `runs_missing_final_verdict`: 87
- `runs_with_final_verdict`: 247
- `top_level_run_dirs`: 334
- `topics_total_with_verdict`: 18
- `topics_with_2plus_runs`: 15
- `under_claimed_l6_topics`: 7

## L6 Claims We Can Honestly Make Today

- `caloric_restriction`: `L6 — REPRODUCIBLY JOURNAL-READY`; pair `['synthesis-caloric_restriction-v06-CONTRIBFIX-2026-05-08T01-57-25Z', 'synthesis-caloric_restriction-v06-PATH2RICHFIX2-2026-05-08T15-10-00Z']`
- `nad_precursors`: `L6 — REPRODUCIBLY JOURNAL-READY`; pair `['synthesis-nad_precursors-v06-PATH1-2026-05-07T17-23-53Z', 'synthesis-nad_precursors-v06-PATH1FIX-2026-05-07T17-40-21Z']`
- `omega3`: `L6 — REPRODUCIBLY JOURNAL-READY`; pair `['synthesis-omega3-v06-PATH2RICHFIX2-2026-05-08TCLASSIFIER', 'synthesis-omega3-v06-PATH2RICHFIX2-2026-05-08T14-00-00Z']`
- `protein_nutrition`: `L6 — REPRODUCIBLY JOURNAL-READY`; pair `['synthesis-protein_nutrition-v06-FIXED-2026-05-05T23-37-32Z', 'synthesis-protein_nutrition-v06-WIDEBASKET-2026-05-07T23-01-16Z']`

## Batch Under-Claimed Candidates

- `acarbose`: tail L5 streak `2`, pair `['synthesis-acarbose-v06-ACTIVE-2026-05-05T22-49-00Z', 'synthesis-acarbose-v06-PATH1-2026-05-07T17-01-11Z']`
- `caloric_restriction`: tail L5 streak `2`, pair `['synthesis-caloric_restriction-v06-CONTRIBFIX-2026-05-08T01-57-25Z', 'synthesis-caloric_restriction-v06-PATH2RICHFIX2-2026-05-08T15-10-00Z']`
- `intermittent_fasting`: tail L5 streak `2`, pair `['synthesis-intermittent_fasting-v06-ACTIVE-2026-05-05T22-34-23Z', 'synthesis-intermittent_fasting-v06-WIDEBASKET-2026-05-07T23-15-06Z']`
- `nad_precursors`: tail L5 streak `2`, pair `['synthesis-nad_precursors-v06-PATH1-2026-05-07T17-23-53Z', 'synthesis-nad_precursors-v06-PATH1FIX-2026-05-07T17-40-21Z']`
- `omega3`: tail L5 streak `4`, pair `['synthesis-omega3-v06-PATH2RICHFIX2-2026-05-08TCLASSIFIER', 'synthesis-omega3-v06-PATH2RICHFIX2-2026-05-08T14-00-00Z']`
- `protein_nutrition`: tail L5 streak `2`, pair `['synthesis-protein_nutrition-v06-FIXED-2026-05-05T23-37-32Z', 'synthesis-protein_nutrition-v06-WIDEBASKET-2026-05-07T23-01-16Z']`
- `resistance_training`: tail L5 streak `2`, pair `['synthesis-resistance_training-v06-WIDEBASKETFIX2-2026-05-07T23-58-31Z', 'synthesis-resistance_training-v06-WIDEBASKETFIX3-2026-05-08T00-10-29Z']`

## Real Certification Results

- `acarbose`: AAA_CONSECUTIVE_ONLY; pair `['synthesis-acarbose-v06-ACTIVE-2026-05-05T22-49-00Z', 'synthesis-acarbose-v06-PATH1-2026-05-07T17-01-11Z']`; synthesis-acarbose-v06-ACTIVE-2026-05-05T22-49-00Z: flagged_patches=4; synthesis-acarbose-v06-PATH1-2026-05-07T17-01-11Z: flagged_patches=1; output `reports/l6_campaign/cert_outputs/acarbose.certification_stdout.json`
- `caloric_restriction`: L6_READY; pair `['synthesis-caloric_restriction-v06-CONTRIBFIX-2026-05-08T01-57-25Z', 'synthesis-caloric_restriction-v06-PATH2RICHFIX2-2026-05-08T15-10-00Z']`; passes consecutive L6 gate; output `reports/l6_campaign/cert_outputs/caloric_restriction.certification_stdout.json`
- `intermittent_fasting`: AAA_CONSECUTIVE_ONLY; pair `['synthesis-intermittent_fasting-v06-ACTIVE-2026-05-05T22-34-23Z', 'synthesis-intermittent_fasting-v06-WIDEBASKET-2026-05-07T23-15-06Z']`; synthesis-intermittent_fasting-v06-ACTIVE-2026-05-05T22-34-23Z: flagged_patches=3; output `reports/l6_campaign/cert_outputs/intermittent_fasting.certification_stdout.json`
- `nad_precursors`: L6_READY; pair `['synthesis-nad_precursors-v06-PATH1-2026-05-07T17-23-53Z', 'synthesis-nad_precursors-v06-PATH1FIX-2026-05-07T17-40-21Z']`; passes consecutive L6 gate; output `reports/l6_campaign/cert_outputs/nad_precursors.certification_stdout.json`
- `omega3`: L6_READY; pair `['synthesis-omega3-v06-PATH2RICHFIX2-2026-05-08TCLASSIFIER', 'synthesis-omega3-v06-PATH2RICHFIX2-2026-05-08T14-00-00Z']`; passes consecutive L6 gate; output `reports/l6_campaign/cert_outputs/omega3.certification_stdout.json`
- `protein_nutrition`: L6_READY; pair `['synthesis-protein_nutrition-v06-FIXED-2026-05-05T23-37-32Z', 'synthesis-protein_nutrition-v06-WIDEBASKET-2026-05-07T23-01-16Z']`; passes consecutive L6 gate; output `reports/l6_campaign/cert_outputs/protein_nutrition.certification_stdout.json`
- `resistance_training`: AAA_CONSECUTIVE_ONLY; pair `['synthesis-resistance_training-v06-WIDEBASKETFIX2-2026-05-07T23-58-31Z', 'synthesis-resistance_training-v06-WIDEBASKETFIX3-2026-05-08T00-10-29Z']`; synthesis-resistance_training-v06-WIDEBASKETFIX2-2026-05-07T23-58-31Z: flagged_patches=1; output `reports/l6_campaign/cert_outputs/resistance_training.certification_stdout.json`

## One More L5 Rerun Needed

1. `rapamycin` — latest run is L5 but no adjacent second L5 at tail — `python3 scripts/run_v06_synthesis.py --topic rapamycin`
2. `metformin` — latest run is L5 but no adjacent second L5 at tail — `python3 scripts/run_v06_synthesis.py --topic metformin`
3. `glp1` — latest run is L5 but no adjacent second L5 at tail — `python3 scripts/run_v06_synthesis.py --topic glp1`
4. `creatine` — latest run is L5 but no adjacent second L5 at tail — `python3 scripts/run_v06_synthesis.py --topic creatine`
5. `statins` — latest run is L5 but no adjacent second L5 at tail — `python3 scripts/run_v06_synthesis.py --topic statins`
6. `zone2_training` — latest run is L5 but no adjacent second L5 at tail — `python3 scripts/run_v06_synthesis.py --topic zone2_training`
7. `berberine` — latest run is L5 but no adjacent second L5 at tail — `python3 scripts/run_v06_synthesis.py --topic berberine`

## Alternation / Stochastic Risk

- `caloric_restriction`: resets `2`, recent maturity pattern `[5, 3, 3, 5, 5, 3, 5, 5]`
- `creatine`: resets `3`, recent maturity pattern `[5, 4, 5, 5, 5, 5, 4, 5]`
- `glp1`: resets `3`, recent maturity pattern `[5, 5, 4, 5, 5, 3, 4, 5]`
- `metformin`: resets `4`, recent maturity pattern `[3, 5, 5, 3, 5, 5, 4, 5]`
- `rapamycin`: resets `10`, recent maturity pattern `[5, 5, 5, 5, 4, 5, 4, 5]`
- `statins`: resets `2`, recent maturity pattern `[5, 3, 5, 5, 5, 5, 3, 5]`

## L5 Journal-Surface Batch Failures

- None among maturity >=5 verdict rows.

## Focus Topic Status

- `caloric_restriction`: runs `8`, L5+ `5`, tail streak `2`, candidate `True`, first rich/PATH status `synthesis-caloric_restriction-v06-CONTRIBFIX-2026-05-08T01-57-25Z` = `L5 AAA`
- `creatine`: runs `12`, L5+ `7`, tail streak `1`, candidate `False`, first rich/PATH status `synthesis-creatine-v06-PATHABASKET84-2026-05-07T10-25-19Z` = `L5 AAA`
- `glp1`: runs `19`, L5+ `8`, tail streak `1`, candidate `False`, first rich/PATH status `synthesis-glp1-v06-PATHABASKET84-2026-05-07T10-08-10Z` = `L3 Trust-Spine Pass — Agent Review Unresolved`
- `metformin`: runs `68`, L5+ `8`, tail streak `1`, candidate `False`, first rich/PATH status `synthesis-metformin-v06-PATHABASKET84-2026-05-07T09-56-19Z` = `L5 AAA`
- `omega3`: runs `9`, L5+ `4`, tail streak `4`, candidate `True`, first rich/PATH status `synthesis-omega3-v06-PATHABASKET84-2026-05-07T10-48-05Z` = `L2 Trust-Spine Pass`
- `rapamycin`: runs `75`, L5+ `18`, tail streak `1`, candidate `False`, first rich/PATH status `synthesis-rapamycin-v06-PATHA1-2026-05-07T12-45-00Z` = `L3 Trust-Spine Pass`
- `statins`: runs `26`, L5+ `6`, tail streak `1`, candidate `False`, first rich/PATH status `synthesis-statins-v06-PATHABASKET84-2026-05-07T10-36-32Z` = `L2 Trust-Spine Pass`

## Missing Final Verdict Files

- `87` top-level run dirs lack `full_paper.final_verdict.json`; see `campaign_inventory.json`.

## Reproduce

```bash
python3 scripts/l6_batch_report.py --format json $(find runs -mindepth 1 -maxdepth 1 -type d)
PYTHONPATH=. python3 scripts/certification_report.py --consecutive runs/<run-a>/full_paper.md runs/<run-b>/full_paper.md
```

## Exact Candidate Certification Commands

```bash
PYTHONPATH=. python3 scripts/certification_report.py --consecutive runs/synthesis-acarbose-v06-ACTIVE-2026-05-05T22-49-00Z/full_paper.md runs/synthesis-acarbose-v06-PATH1-2026-05-07T17-01-11Z/full_paper.md
```
```bash
PYTHONPATH=. python3 scripts/certification_report.py --consecutive runs/synthesis-caloric_restriction-v06-CONTRIBFIX-2026-05-08T01-57-25Z/full_paper.md runs/synthesis-caloric_restriction-v06-PATH2RICHFIX2-2026-05-08T15-10-00Z/full_paper.md
```
```bash
PYTHONPATH=. python3 scripts/certification_report.py --consecutive runs/synthesis-intermittent_fasting-v06-ACTIVE-2026-05-05T22-34-23Z/full_paper.md runs/synthesis-intermittent_fasting-v06-WIDEBASKET-2026-05-07T23-15-06Z/full_paper.md
```
```bash
PYTHONPATH=. python3 scripts/certification_report.py --consecutive runs/synthesis-nad_precursors-v06-PATH1-2026-05-07T17-23-53Z/full_paper.md runs/synthesis-nad_precursors-v06-PATH1FIX-2026-05-07T17-40-21Z/full_paper.md
```
```bash
PYTHONPATH=. python3 scripts/certification_report.py --consecutive runs/synthesis-omega3-v06-PATH2RICHFIX2-2026-05-08TCLASSIFIER/full_paper.md runs/synthesis-omega3-v06-PATH2RICHFIX2-2026-05-08T14-00-00Z/full_paper.md
```
```bash
PYTHONPATH=. python3 scripts/certification_report.py --consecutive runs/synthesis-protein_nutrition-v06-FIXED-2026-05-05T23-37-32Z/full_paper.md runs/synthesis-protein_nutrition-v06-WIDEBASKET-2026-05-07T23-01-16Z/full_paper.md
```
```bash
PYTHONPATH=. python3 scripts/certification_report.py --consecutive runs/synthesis-resistance_training-v06-WIDEBASKETFIX2-2026-05-07T23-58-31Z/full_paper.md runs/synthesis-resistance_training-v06-WIDEBASKETFIX3-2026-05-08T00-10-29Z/full_paper.md
```
