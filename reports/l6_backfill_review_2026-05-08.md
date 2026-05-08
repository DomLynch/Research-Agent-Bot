# L6 Backfill Review — 2026-05-08

Status: verified from existing artifacts. No synthesis rerun required.

## Gate Used

Command:

```bash
.venv/bin/python scripts/certification_report.py --consecutive \
  runs/synthesis-rapamycin-v06-PATHA8-2026-05-07T09-02-06Z/full_paper.md \
  runs/synthesis-rapamycin-v06-PATHA9-2026-05-07T09-20-53Z/full_paper.md \
  runs/synthesis-rapamycin-v06-PATHA10-2026-05-07T09-38-47Z/full_paper.md
```

Result:

- `certified: true`
- `n_runs: 3`
- `n_aaa_certified: 3`
- `n_l5_certified: 3`
- `all_aaa_consecutive: true`
- `l6_reproducibly_journal_ready: true`
- `selected_pair`: PATHA9 + PATHA10
- `l6_blockers: []`
- `maturity_level: 6`
- `maturity_label: L6 — REPRODUCIBLY JOURNAL-READY`
- `certification_gate_version: l6-reproducibility-v1`

## Run-Level Evidence

| Run | Verdict | Maturity | Receipts | Claims | Tensions | Reviewer P1 | Auto-strips | Flagged | JS pass |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| PATHA8 | AAA | 6 | 16 | 72 | 31 | 0 | 0 | 0 | true |
| PATHA9 | AAA | 6 | 16 | 72 | 31 | 0 | 0 | 0 | true |
| PATHA10 | AAA | 6 | 16 | 72 | 31 | 0 | 0 | 0 | true |

## Decision

Rapamycin PATHA8/9/10 qualify for L6 under the current consecutive-run gate.
The current final verdict sidecars already show L6, so no additional backfill
script is needed.

## Limits

- This is a reproducibility label, not a scientific-novelty upgrade.
- It verifies consecutive clean L5 behavior for the existing artifact cohort.
- It does not prove cross-model concordance or cross-corpus reproducibility.
