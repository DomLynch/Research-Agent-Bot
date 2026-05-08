# Model Stack Validation — 2026-05-08

## Scope

Validates the current default stack:

1. Writer/extractor: `mimo-v2.5-pro`
2. Final reviewer: `deepseek/deepseek-v4-pro`
3. Fallback/arbitrator: `mistralai/mistral-small-2603`

The arbitrator remains judge-only: `APPLY`, `REJECT`, or `ESCALATE`.

## Results

| Check | Result |
|---|---:|
| Offline arbitration benchmark | 20/20 pass |
| Offline agreement | 100% |
| Offline distribution | APPLY 14 / REJECT 2 / ESCALATE 4 |
| Fail-closed fixture | 5/5 pass |
| Fail-closed count | 4 |
| Live Mistral sample | 5/5 pass |
| Live Mistral distribution | APPLY 4 / ESCALATE 1 |
| Live Mistral mixed sample | 5/6 pass |
| Mixed-sample miss | expected REJECT, returned conservative ESCALATE |

## Coverage

The benchmark includes urolithin A, metformin, GLP-1, statins, rapamycin,
omega-3, and senolytics. Cases cover safe deletion, numeric simplification,
duplicate-prose removal, semantic replacement escalation, explicit reject, bad
JSON, invalid verdict, rewrite attempt, low-confidence APPLY, and transport
failure.

## Evidence Files

- `tests/fixtures/model_stack_arbitration_benchmark_2026-05-08.json`
- `tests/fixtures/model_stack_fail_closed_cases_2026-05-08.json`
- `reports/model_stack_validation_2026-05-08.json`
- `reports/model_stack_validation_2026-05-08.failclosed.json`
- `reports/model_stack_validation_2026-05-08.live_mistral.json`
- `reports/model_stack_validation_2026-05-08.live_mistral_mixed.json`

## Tests

```bash
.venv/bin/python -m pytest \
  tests/test_arbitration_validation_harness.py \
  tests/test_granite_arbitrator.py
# 26 passed

.venv/bin/python -m ruff check \
  tests/test_arbitration_validation_harness.py \
  tests/test_granite_arbitrator.py \
  scripts/arbitration_validation_harness.py \
  scripts/granite_arbitrator.py
# all checks passed
```

## Decision

Mistral Small 4 is adding value as a bounded arbitration reviewer. It is not
used as a broad semantic authority and does not silently inflate L5: all
decisions are logged in arbitration-log-compatible shape and unsafe classes
fail closed. The mixed live sample shows one miss, but it was conservative
escalation rather than unsafe patch application.
