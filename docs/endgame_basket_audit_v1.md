# Endgame Basket Audit V1

Read-only audit for a basket of synthesis run directories. The script does not
discover topics or encode topic-specific conclusions; pass the run dirs to audit.

## Summary

```bash
python scripts/endgame_basket_audit.py runs/<rich-run-a> runs/<rich-run-b> \
  --format markdown \
  --json-out /tmp/endgame_basket.json \
  --markdown-out /tmp/endgame_basket.md
```

## Rich vs Baseline

```bash
python scripts/endgame_basket_audit.py runs/<rich-run> \
  --baseline runs/<prior-baseline-run> \
  --format json
```

Baseline comparison is topic-matched. If several baselines are supplied for the
same topic, the latest sorted baseline row wins.

## No-Regression Rubric

Treat a next basket rerun as ready only when:

- no run has a JS or repeated Grok failure;
- L5 topics either have a consecutive L5 pair or are explicitly queued for rerun;
- corpus-rich runs do not regress maturity or receipt count against the baseline;
- corpus-thin is backed by explicit corpus gaps, low receipts, or low high-confidence claims;
- generated JSON and Markdown agree on weakest run and classifier signal.

## Outputs

JSON contains `runs`, `weakest`, `l5_not_l6`, `cert_regressed`,
`thin_false_positive_suspects`, and universal classifier fix fields.

Markdown contains the same summary in a reviewable table plus readiness flags.
