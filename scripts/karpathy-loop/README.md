# Karpathy Loop Harness

Measures `composite_score` (and 5 sub-metrics) for every gold topic so you can
see the impact of code changes in git diffs — no live API calls, no fixture
regeneration.

## Usage

All commands run from the repo root.

```bash
# Take a snapshot (writes scripts/karpathy-loop/snapshots/<sha>_<ts>.json)
PYTHONPATH=. python scripts/karpathy_loop.py snapshot

# Compare two snapshots
PYTHONPATH=. python scripts/karpathy_loop.py diff snap_A.json snap_B.json

# Pretty-print a diff
PYTHONPATH=. python scripts/karpathy_loop.py report diff_*.json
```

## Metrics

| Metric | Weight | What it measures |
|---|---|---|
| `study_overlap` | 0.10 | DoI coverage vs gold `included_dois` |
| `quantitative_fidelity` | 0.25 | Numeric values in draft match gold |
| `direction_agreement` | 0.20 | Conclusion direction vs gold |
| `limitation_overlap` | 0.15 | Limitation coverage vs gold |
| `bundle_contract_score` | 0.30 | Bundle hygiene: dedupe, topic-fit, tier distribution, and A1 presence |
| `composite_score` | — | Weighted average of the above |

## Baseline

Current composite_score across 10 gold topics: **~0.54**.

## Output structure

```
scripts/karpathy-loop/
├── snapshots/    # timestamped score snapshots (gitignored)
├── diffs/        # pairwise diffs between snapshots (gitignored)
└── README.md
```

## Troubleshooting

- Ensure `PYTHONPATH=.` is set — the script imports from `tests/` indirectly.
- Path has spaces — the script handles this internally via `Path` objects.
- If fixtures were updated, re-run `snapshot` to get a new baseline.
