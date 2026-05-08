# Reproduce L6 Campaign

## Batch Inventory

```bash
python3 scripts/l6_batch_report.py --format json $(find runs -mindepth 1 -maxdepth 1 -type d)
```

## Candidate Certification Commands

### acarbose

```bash
PYTHONPATH=. python3 scripts/certification_report.py --consecutive runs/synthesis-acarbose-v06-ACTIVE-2026-05-05T22-49-00Z/full_paper.md runs/synthesis-acarbose-v06-PATH1-2026-05-07T17-01-11Z/full_paper.md
```

### caloric_restriction

```bash
PYTHONPATH=. python3 scripts/certification_report.py --consecutive runs/synthesis-caloric_restriction-v06-CONTRIBFIX-2026-05-08T01-57-25Z/full_paper.md runs/synthesis-caloric_restriction-v06-PATH2RICHFIX2-2026-05-08T15-10-00Z/full_paper.md
```

### intermittent_fasting

```bash
PYTHONPATH=. python3 scripts/certification_report.py --consecutive runs/synthesis-intermittent_fasting-v06-ACTIVE-2026-05-05T22-34-23Z/full_paper.md runs/synthesis-intermittent_fasting-v06-WIDEBASKET-2026-05-07T23-15-06Z/full_paper.md
```

### nad_precursors

```bash
PYTHONPATH=. python3 scripts/certification_report.py --consecutive runs/synthesis-nad_precursors-v06-PATH1-2026-05-07T17-23-53Z/full_paper.md runs/synthesis-nad_precursors-v06-PATH1FIX-2026-05-07T17-40-21Z/full_paper.md
```

### omega3

```bash
PYTHONPATH=. python3 scripts/certification_report.py --consecutive runs/synthesis-omega3-v06-PATH2RICHFIX2-2026-05-08TCLASSIFIER/full_paper.md runs/synthesis-omega3-v06-PATH2RICHFIX2-2026-05-08T14-00-00Z/full_paper.md
```

### protein_nutrition

```bash
PYTHONPATH=. python3 scripts/certification_report.py --consecutive runs/synthesis-protein_nutrition-v06-FIXED-2026-05-05T23-37-32Z/full_paper.md runs/synthesis-protein_nutrition-v06-WIDEBASKET-2026-05-07T23-01-16Z/full_paper.md
```

### resistance_training

```bash
PYTHONPATH=. python3 scripts/certification_report.py --consecutive runs/synthesis-resistance_training-v06-WIDEBASKETFIX2-2026-05-07T23-58-31Z/full_paper.md runs/synthesis-resistance_training-v06-WIDEBASKETFIX3-2026-05-08T00-10-29Z/full_paper.md
```

## Smoke Commands

### rapamycin_PATHA8_9_10

```bash
python3 scripts/l6_batch_report.py --format json runs/synthesis-rapamycin-v06-PATHA8-2026-05-07T09-02-06Z runs/synthesis-rapamycin-v06-PATHA9-2026-05-07T09-20-53Z runs/synthesis-rapamycin-v06-PATHA10-2026-05-07T09-38-47Z
```

### acarbose_candidate_pair

```bash
python3 scripts/l6_batch_report.py --format json runs/synthesis-acarbose-v06-ACTIVE-2026-05-05T22-49-00Z runs/synthesis-acarbose-v06-PATH1-2026-05-07T17-01-11Z
```
