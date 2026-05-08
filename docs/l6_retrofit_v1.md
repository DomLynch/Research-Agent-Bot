# L6 Retrofit v1

`scripts/l6_retrofit_report.py` scans existing run directories without
mutating them. It makes historical L6 under-claiming visible by checking
adjacent same-topic L5 pairs.

## Claim Boundary

- `confirmed_l6`: the pair passed the real consecutive gate with
  `l6_reproducibly_journal_ready=true`.
- `candidate_only`: an adjacent L5 pair exists, but the real gate was not run.
- `blocked`: an adjacent L5 pair exists, but the real gate did not confirm L6.
- `needs_rerun`: the latest run is L5 and one more adjacent L5 could form a
  candidate pair.
- `no_data`: no adjacent L5 pair and latest run is not L5.

The retrofit report may claim a topic has local L6 evidence only for
`confirmed_l6` rows. It is not a publication claim and does not certify
scientific truth.

## Reproduce

```bash
python3 scripts/l6_retrofit_report.py \
  --run-cert \
  --timeout-s 60 \
  --out-dir reports/l6_retrofit
```

Single-pair reproduction:

```bash
PYTHONPATH=. python3 scripts/certification_report.py --consecutive \
  runs/<run-a>/full_paper.md \
  runs/<run-b>/full_paper.md
```

## Rerun Commands

Use these only for topics marked `needs_rerun`:

```bash
python3 scripts/run_v06_synthesis.py --topic berberine
python3 scripts/run_v06_synthesis.py --topic zone2_training
```

## Non-Goals

- No writes to `runs/`.
- No certificate promotion in place.
- No OSF, journal, reader, or publication-surface mutation.
- No topic-specific Python branches.
