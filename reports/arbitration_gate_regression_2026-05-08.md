# Arbitration Gate Regression — 2026-05-08

## Scope

Verifies the third-layer arbitrator is a bounded judge, not a hidden prose or
verdict override.

## Runtime Defaults

- Reviewer: `deepseek/deepseek-v4-pro`
- Reviewer fallback: `mistralai/mistral-small-2603`
- Arbitrator default: `mistralai/mistral-small-2603`

Legacy `GRANITE_*` env names remain aliases only.

## Safety Boundary

The arbitrator may only return:

- `APPLY`
- `REJECT`
- `ESCALATE`

It cannot write replacement content. If it returns malformed JSON, extra
replacement fields, invalid verdicts, no rationale, timeout, or network error,
the pipeline fails closed to `ESCALATE`.

## Evidence

- DeepSeek reviewer live smoke: parsed JSON response, `n_patches=0`.
- Mistral arbitrator live smoke: valid `APPLY` decision under bounded input.
- Targeted tests: `104 passed`.
- Ruff: clean.
- `full_paper.final_verdict.json` now carries arbitration counts and optional
  `arbitration_log`.

## No Fake L5 Inflation

Arbitration does not bypass the existing L5 rules. L5 still requires:

- AAA verdict
- no unresolved P1 review patches
- no auto-strip surgery
- clean journal-surface gate
- logged arbitration if a third model was consulted

Unlogged arbitration is treated as a provenance defect, not a clean cert.
