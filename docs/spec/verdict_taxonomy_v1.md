# Verdict Taxonomy v1

Status: draft spec. L0-L6 are current operational targets. L7-L8 are planned
trust events that require stronger validation evidence before public claims.

## Levels

| Level | Label | Meaning | Minimum evidence |
|---:|---|---|---|
| L0 | Unseeded | No usable run artifact. | No receipts or no completed run. |
| L1 | Seeded | Receipts exist, but extraction or claim graph is insufficient. | Manifest or corpus seed exists. |
| L2 | Partial | Claims exist but corpus or audit floor is not met. | Some traceable claims, below synthesis floor. |
| L3 | Floor-met | Corpus floor is met, but certification is blocked. | Audit/review/verdict identifies remaining blockers. |
| L4 | Analytically certified | AAA verdict passes, but clean journal-ready criteria are not met. | Full audit pass, no unresolved P1, known surgery or maturity limitation. |
| L5 | Journal-ready single run | One run passes cleanly with no unresolved P1, no auto-strips, and clean public surface. | Final verdict JSON/MD plus clean audit/review logs. |
| L6 | Reproducibly journal-ready | Two or more consecutive same-topic L5 runs pass without material regression. | Consecutive certification report naming run pair(s). |
| L7 | Cross-model concordant | Planned: L6 plus independent model-family review agrees on verdict-critical claims. | Not claimed until benchmarked and logged. |
| L8 | Cross-corpus reproducible | Planned: cross-model plus independently assembled corpus preserves thesis and verdict class. | Not claimed until second-corpus report exists. |

## No Fake L5 Inflation

L5 is not a reward for good prose. It requires a clean single-run trust event.
The following block L5:

- reviewer unresolved P1
- flagged review patches that remain unresolved after repair/arbitration
- reviewer auto-strip or equivalent surgery
- journal-surface failure
- malformed public numerics or leaked internal labels
- missing final verdict artifact
- unlogged arbitration decision on verdict-critical patch

Third-model arbitration can resolve a contested patch only when the deterministic
boundary accepts the result and writes the log. It must not silently erase the
fact that a patch was contested.

## Cert Math

Required machine-readable fields:

- `verdict`
- `maturity_level`
- `maturity_label`
- `journal_ready`
- `audit_score`
- `audit_pass_count`
- `audit_total_count`
- `grok_unresolved_p1`
- `grok_auto_stripped`
- `journal_surface_pass`
- `arbitration_count` when applicable

L6 requires a separate consecutive-run report over consecutive clean L5 runs.
Batch dashboards may nominate L6 candidates but do not upgrade final verdicts
by themselves.

## Scientific Novelty Boundary

The maturity level is a trust/maturity label, not a novelty score. A narrow but
stable paper can be L6; a richer and more original paper can remain L4 if it
required surgery or lacks reproducibility evidence.
