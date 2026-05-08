# Verdict L0-L8 Spec v1

Status: draft.

Verdict levels describe evidence maturity. They are not marketing labels and
must be independently verifiable from artifacts.

| Level | Name | Verifiable criteria |
|---:|---|---|
| L0 | Missing | No usable synthesis artifact. |
| L1 | Draft | Paper exists, but required audit or manifest is missing. |
| L2 | Trust-spine pass | Audit artifact exists and core trace checks pass, but public/journal gates remain open. |
| L3 | Journal-surface pass | Public paper surface has no known placeholder, internal, or demo leakage. |
| L4 | Analytically certified | Deterministic audit passes all required checks for the run. |
| L5 | Single-run journal-ready | One run has final verdict pass, audit P1 pass, reader-ready bundle, and no unresolved critical flags. |
| L6 | Reproducible | Two adjacent same-topic L5 runs pass with no material regression in receipts, tensions, verdict, or audit. |
| L7 | Cross-model | L6 plus independent cross-model review/arbitration agrees on verdict-critical claims. |
| L8 | Cross-corpus | L7 plus a second independently assembled corpus preserves the thesis class and verdict level. |

## Required Evidence by Level

- L5 requires one immutable bundle and `full_paper.final_verdict.md/json`.
- L6 requires a pair report naming both run ids and the regression checks.
- L7 requires model identity, prompt/version, arbitration log, and disagreement
  handling.
- L8 requires corpus construction notes, corpus hash/manifest, and comparison
  report.

Batch reports may nominate candidates. They do not upgrade a verdict level
unless the level-specific evidence exists.
