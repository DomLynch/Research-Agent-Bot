# Basket Validation V1

Read-only scripts for comparing synthesis runs across a topic basket.

## Stability Matrix

```bash
python scripts/basket_stability_matrix.py runs/<run-a> runs/<run-b> \
  --group-runs \
  --format csv \
  --json-out /tmp/basket.json \
  --csv-out /tmp/basket.csv
```

Baseline comparison:

```bash
python scripts/basket_stability_matrix.py runs/<new-run> \
  --baseline runs/<baseline-run> \
  --format json
```

Columns include verdict, maturity level, L5 flag, consecutive L5 streak, L6 candidate flag, receipts, tensions, reviewer flags, JS pass, quarantine count, and baseline deltas.

CSV and JSON exports are deterministic for fixture tests and offline review:

```bash
python scripts/basket_stability_matrix.py runs/<run-a> runs/<run-b> \
  --group-runs \
  --json-out /tmp/basket_stability.json \
  --csv-out /tmp/basket_stability.csv
```

Regression means maturity level dropped or receipt count dropped against the topic-matched baseline. It is a triage signal, not a certification verdict.

## Failure Triage

```bash
python scripts/basket_failure_triage.py runs/<run-a> runs/<run-b> \
  --format csv \
  --json-out /tmp/triage.json
```

Failure classes are intentionally coarse and topic-agnostic:

- `js`
- `grok`
- `corpus-thin`
- `backfill`
- `verdict`
- `pass`

Both scripts read existing run artifacts only. They do not modify runs.
