# L6 Campaign v1

`reports/l6_campaign/` is a local evidence pack for reproducibility triage.
It does not promote runs or edit pipeline artifacts.

## Claim Boundary

- L5 is a clean single-run journal-ready result under the certification code.
- L6 is an adjacent same-topic pair that passes:

```bash
PYTHONPATH=. python3 scripts/certification_report.py --consecutive \
  runs/<run-a>/full_paper.md \
  runs/<run-b>/full_paper.md
```

Batch-reporter candidates are not L6 claims. They only identify run pairs
worth sending through the real consecutive certification gate.

## Outputs

- `campaign_inventory.json`: all 2+ run topics, verdict fields, maturity
  levels, journal-surface status, Grok fields, missing-verdict sample.
- `l6_batch_report.json` / `.md`: pure final-verdict L5 streak triage.
- `per_topic_batch/*.json` / `.md`: the same triage split by eligible topic.
- `cert_outputs/*.json`: raw consecutive certification stdout per candidate.
- `campaign_summary.json` / `.md`: human and machine campaign summaries.
- `smoke_outputs/*.json`: fixed smoke checks, including rapamycin PATHA8/9/10.

## Non-Goals

- No reruns are launched by the campaign report.
- No certification artifacts are written back into run directories.
- No topic-specific Python logic is added.
- No deployment, push, or commit is performed.
