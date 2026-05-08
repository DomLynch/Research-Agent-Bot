# Wide Basket Execution V2

Read-only execution planning for the 24h wide-basket lane.

## Build The Deep Report

```bash
python scripts/wide_basket_deep_audit.py \
  --json-out reports/wide_basket_deep/report.json \
  --markdown-out reports/wide_basket_deep/report.md
```

The audit reads:

- `topic_packs/*.toml` for aliases, search queries, canonical trials,
  retrieval scope/exclusion terms, and expected evidence slots;
- `runs/synthesis-*` for verdict, maturity, receipts, claims, tensions,
  JS pass, reviewer flags, strips, quarantine counts, and local L6 status.

## Execution Buckets

- `run_now`: no rich rerun yet, no blocking latest local artifact, and no low
  search-query pack bottleneck.
- `corpus_tune_first`: latest local or latest rich artifact is JS/reviewer/thin
  blocked, or the pack is structurally under-specified.
- `l6_rerun`: latest rich artifact is L5 and pass-like, but not locally L6.
- `rich_monitor`: latest rich artifact is already pass-like and locally stable.

## Dry-Run Acceptance Gates

- `manifest.json` exists.
- receipts are at least 10.
- JS/journal-surface status is not false.
- reviewer unresolved flags are 0.
- dry-run artifacts complete before any live synthesis is considered.

## Command Shape

```bash
python scripts/seed_topic_corpus.py --topic <topic> --max-per-source 25
python scripts/run_v06_synthesis.py --topic <topic> --dry-run
```

For `corpus_tune_first`, start with:

```bash
python scripts/seed_topic_corpus.py --topic <topic> --max-per-source 35
```

Do not use this report as a publication gate. It is a queue and readiness
diagnostic only.
