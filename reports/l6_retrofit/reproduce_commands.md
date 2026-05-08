# L6 Retrofit Reproduce Commands

## Full Retrofit

```bash
python3 scripts/l6_retrofit_report.py --run-cert --timeout-s 60 --out-dir reports/l6_retrofit
```

## Pair Gates

### acarbose - L5

```bash
PYTHONPATH=. python3 scripts/certification_report.py --consecutive runs/synthesis-acarbose-v06-ACTIVE-2026-05-05T22-49-00Z/full_paper.md runs/synthesis-acarbose-v06-PATH1-2026-05-07T17-01-11Z/full_paper.md
```

### caloric_restriction - L6

```bash
PYTHONPATH=. python3 scripts/certification_report.py --consecutive runs/synthesis-caloric_restriction-v06-PATH1FIX2-2026-05-07T19-08-03Z/full_paper.md runs/synthesis-caloric_restriction-v06-CONTRIB-2026-05-08T00-58-42Z/full_paper.md
```

### caloric_restriction - L6

```bash
PYTHONPATH=. python3 scripts/certification_report.py --consecutive runs/synthesis-caloric_restriction-v06-CONTRIBFIX-2026-05-08T01-57-25Z/full_paper.md runs/synthesis-caloric_restriction-v06-PATH2RICHFIX2-2026-05-08T15-10-00Z/full_paper.md
```

### creatine - L5

```bash
PYTHONPATH=. python3 scripts/certification_report.py --consecutive runs/synthesis-creatine-v06-PATH2RICHFIX-2026-05-07T22-22-17Z/full_paper.md runs/synthesis-creatine-v06-PATH2RICHFIX2-2026-05-07T22-34-47Z/full_paper.md
```

### creatine - L6

```bash
PYTHONPATH=. python3 scripts/certification_report.py --consecutive runs/synthesis-creatine-v06-PATH2RICHFIX2-2026-05-07T22-34-47Z/full_paper.md runs/synthesis-creatine-v06-PATH2RICHFIX3-2026-05-07T22-44-26Z/full_paper.md
```

### creatine - L6

```bash
PYTHONPATH=. python3 scripts/certification_report.py --consecutive runs/synthesis-creatine-v06-PATH2RICHFIX3-2026-05-07T22-44-26Z/full_paper.md runs/synthesis-creatine-v06-PATH2RICHFIX-2026-05-08T07-55-00Z/full_paper.md
```

### glp1 - L5

```bash
PYTHONPATH=. python3 scripts/certification_report.py --consecutive runs/synthesis-glp1-v06-PATHABASKETFIX-2026-05-07T11-03-43Z/full_paper.md runs/synthesis-glp1-v06-PATH2RICH-2026-05-07T21-45-16Z/full_paper.md
```

### glp1 - L5

```bash
PYTHONPATH=. python3 scripts/certification_report.py --consecutive runs/synthesis-glp1-v06-PATH2RICH-2026-05-07T21-45-16Z/full_paper.md runs/synthesis-glp1-v06-PATH2RICHFIX-2026-05-07T22-00-20Z/full_paper.md
```

### glp1 - L6

```bash
PYTHONPATH=. python3 scripts/certification_report.py --consecutive runs/synthesis-glp1-v06-PATH2RICHFIX-2026-05-07T22-00-20Z/full_paper.md runs/synthesis-glp1-v06-CONTRIB-2026-05-08T00-58-42Z/full_paper.md
```

### glp1 - L6

```bash
PYTHONPATH=. python3 scripts/certification_report.py --consecutive runs/synthesis-glp1-v06-CONTRIBFIX-2026-05-08T01-22-44Z/full_paper.md runs/synthesis-glp1-v06-PATH2RICHFIX2-2026-05-08T06-14-00Z/full_paper.md
```

### intermittent_fasting - L5

```bash
PYTHONPATH=. python3 scripts/certification_report.py --consecutive runs/synthesis-intermittent_fasting-v06-ACTIVE-2026-05-05T22-34-23Z/full_paper.md runs/synthesis-intermittent_fasting-v06-WIDEBASKET-2026-05-07T23-15-06Z/full_paper.md
```

### metformin - L5

```bash
PYTHONPATH=. python3 scripts/certification_report.py --consecutive runs/synthesis-metformin-v06-CODEXFIX8-2026-05-05T19-42-41Z/full_paper.md runs/synthesis-metformin-v06-CODEXFIX9-2026-05-05T20-00-00Z/full_paper.md
```

### metformin - L6

```bash
PYTHONPATH=. python3 scripts/certification_report.py --consecutive runs/synthesis-metformin-v06-PATHABASKET84-2026-05-07T09-56-19Z/full_paper.md runs/synthesis-metformin-v06-PATH2RICH-2026-05-07T21-35-47Z/full_paper.md
```

### metformin - L6

```bash
PYTHONPATH=. python3 scripts/certification_report.py --consecutive runs/synthesis-metformin-v06-PATH2RICHFIX2-2026-05-08TCLASSIFIER/full_paper.md runs/synthesis-metformin-v06-PATH2RICHFIX3-2026-05-08TCLASSIFIER/full_paper.md
```

### nad_precursors - L6

```bash
PYTHONPATH=. python3 scripts/certification_report.py --consecutive runs/synthesis-nad_precursors-v06-PATH1-2026-05-07T17-23-53Z/full_paper.md runs/synthesis-nad_precursors-v06-PATH1FIX-2026-05-07T17-40-21Z/full_paper.md
```

### omega3 - L6

```bash
PYTHONPATH=. python3 scripts/certification_report.py --consecutive runs/synthesis-omega3-v06-PATH2-2026-05-07T15-59-34Z/full_paper.md runs/synthesis-omega3-v06-PATH2RICH-2026-05-07T21-07-13Z/full_paper.md
```

### omega3 - L6

```bash
PYTHONPATH=. python3 scripts/certification_report.py --consecutive runs/synthesis-omega3-v06-PATH2RICH-2026-05-07T21-07-13Z/full_paper.md runs/synthesis-omega3-v06-PATH2RICHFIX2-2026-05-08TCLASSIFIER/full_paper.md
```

### omega3 - L6

```bash
PYTHONPATH=. python3 scripts/certification_report.py --consecutive runs/synthesis-omega3-v06-PATH2RICHFIX2-2026-05-08TCLASSIFIER/full_paper.md runs/synthesis-omega3-v06-PATH2RICHFIX2-2026-05-08T14-00-00Z/full_paper.md
```

### protein_nutrition - L6

```bash
PYTHONPATH=. python3 scripts/certification_report.py --consecutive runs/synthesis-protein_nutrition-v06-FIXED-2026-05-05T23-37-32Z/full_paper.md runs/synthesis-protein_nutrition-v06-WIDEBASKET-2026-05-07T23-01-16Z/full_paper.md
```

### rapamycin - L6

```bash
PYTHONPATH=. python3 scripts/certification_report.py --consecutive runs/synthesis-rapamycin-v06-CORPUSFIX20-2026-05-07T02-10-00Z/full_paper.md runs/synthesis-rapamycin-v06-CORPUSFIX21-2026-05-07T02-35-00Z/full_paper.md
```

### rapamycin - L6

```bash
PYTHONPATH=. python3 scripts/certification_report.py --consecutive runs/synthesis-rapamycin-v06-CORPUSFIX28-2026-05-07T08-00-00Z/full_paper.md runs/synthesis-rapamycin-v06-CORPUSFIX29-2026-05-07T08-40-00Z/full_paper.md
```

### rapamycin - L6

```bash
PYTHONPATH=. python3 scripts/certification_report.py --consecutive runs/synthesis-rapamycin-v06-PATHA4-2026-05-07T14-40-00Z/full_paper.md runs/synthesis-rapamycin-v06-PATHA5-2026-05-07T07-57-42Z/full_paper.md
```

### rapamycin - L6

```bash
PYTHONPATH=. python3 scripts/certification_report.py --consecutive runs/synthesis-rapamycin-v06-PATHA7-2026-05-07T08-35-28Z/full_paper.md runs/synthesis-rapamycin-v06-PATHA8-2026-05-07T09-02-06Z/full_paper.md
```

### rapamycin - L6

```bash
PYTHONPATH=. python3 scripts/certification_report.py --consecutive runs/synthesis-rapamycin-v06-PATHA8-2026-05-07T09-02-06Z/full_paper.md runs/synthesis-rapamycin-v06-PATHA9-2026-05-07T09-20-53Z/full_paper.md
```

### rapamycin - L6

```bash
PYTHONPATH=. python3 scripts/certification_report.py --consecutive runs/synthesis-rapamycin-v06-PATHA9-2026-05-07T09-20-53Z/full_paper.md runs/synthesis-rapamycin-v06-PATHA10-2026-05-07T09-38-47Z/full_paper.md
```

### rapamycin - L6

```bash
PYTHONPATH=. python3 scripts/certification_report.py --consecutive runs/synthesis-rapamycin-v06-PATHA10-2026-05-07T09-38-47Z/full_paper.md runs/synthesis-rapamycin-v06-PATH2RICH-2026-05-07T21-23-53Z/full_paper.md
```

### resistance_training - L5

```bash
PYTHONPATH=. python3 scripts/certification_report.py --consecutive runs/synthesis-resistance_training-v06-ACTIVE-2026-05-05T22-34-24Z/full_paper.md runs/synthesis-resistance_training-v06-WIDEBASKET-2026-05-07T23-31-33Z/full_paper.md
```

### resistance_training - L5

```bash
PYTHONPATH=. python3 scripts/certification_report.py --consecutive runs/synthesis-resistance_training-v06-WIDEBASKETFIX2-2026-05-07T23-58-31Z/full_paper.md runs/synthesis-resistance_training-v06-WIDEBASKETFIX3-2026-05-08T00-10-29Z/full_paper.md
```

### statins - L5

```bash
PYTHONPATH=. python3 scripts/certification_report.py --consecutive runs/synthesis-statins-v06-PATH2RICHFIX-2026-05-07T19-57-05Z/full_paper.md runs/synthesis-statins-v06-PATH2RICHFIX2-2026-05-07T20-21-40Z/full_paper.md
```

### statins - L6

```bash
PYTHONPATH=. python3 scripts/certification_report.py --consecutive runs/synthesis-statins-v06-PATH2RICHFIX2-2026-05-07T20-21-40Z/full_paper.md runs/synthesis-statins-v06-PATH2RICHFIX3-2026-05-07T20-44-41Z/full_paper.md
```

### statins - L6

```bash
PYTHONPATH=. python3 scripts/certification_report.py --consecutive runs/synthesis-statins-v06-PATH2RICHFIX3-2026-05-07T20-44-41Z/full_paper.md runs/synthesis-statins-v06-PATH2RICHFIX4-2026-05-08TCLASSIFIER/full_paper.md
```

## Reruns

```bash
python3 scripts/run_v06_synthesis.py --topic berberine
```

```bash
python3 scripts/run_v06_synthesis.py --topic zone2_training
```
