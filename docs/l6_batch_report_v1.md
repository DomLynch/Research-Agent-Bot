# L6 Batch Report v1

`scripts/l6_batch_report.py` is a read-only reporter for topic-level
reproducibility candidates.

## L5 vs L6

- **L5** is a single-run journal-ready verdict from
  `full_paper.final_verdict.json`.
- **L6** is a topic-level reproducibility claim: at least two consecutive
  L5 runs for the same topic.
- The batch reporter only surfaces **L6 candidates** from existing verdict
  JSON. It does not certify them.
- `under_claimed_l6=true` means the latest adjacent run pair looks like an
  L6 candidate from final-verdict JSON, but the latest run is still labeled
  below maturity level 6.

## Inputs

Pass one or more run directories. Runs are grouped by `manifest.json.topic`,
then by `full_paper.final_verdict.json.topic`, then by run-dir name fallback.

## Outputs

- JSON: schema `l6_batch_report.v1`
- Markdown: topic summary plus per-run rows

## Research Contribution Summary

Research-contribution status may be shown as a separate summary field. It is
not pipeline integration and does not affect L6 candidate status.

## Next Certification Command

Use the real certification gate for any surfaced candidate:

```bash
python3 scripts/certification_report.py --consecutive \
  runs/<topic-run-a>/full_paper.md \
  runs/<topic-run-b>/full_paper.md
```
