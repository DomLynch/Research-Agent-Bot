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
| Live DeepSeek reviewer smoke | HTTP 200; parsed `{"patches":[]}` |
| Live DeepSeek reviewer function | OK; 0 patches on synthetic smoke |
| DeepSeek smoke cost | $0.00119 |
| DeepSeek model resolved | `deepseek/deepseek-v4-pro-20260423` |
| Live DeepSeek reviewer path | 0 patches; `$0.00119` |

## Coverage

The benchmark includes urolithin A, metformin, GLP-1, statins, rapamycin,
omega-3, and senolytics. Cases cover safe deletion, numeric simplification,
duplicate-prose removal, semantic replacement escalation, explicit reject, bad
JSON, invalid verdict, rewrite attempt, low-confidence APPLY, and transport
failure.

Historical IBM Granite live runs on the earlier 10-case fixture scored 2/10 and
3/10. That comparison is not perfectly controlled because the benchmark and
prompt have since been hardened, but the current live Mistral mixed sample is
materially better and its only miss was conservative escalation rather than
unsafe application.

## Evidence Files

- `tests/fixtures/model_stack_arbitration_benchmark_2026-05-08.json`
- `tests/fixtures/model_stack_fail_closed_cases_2026-05-08.json`
- `reports/model_stack_validation_2026-05-08.json`
- `reports/model_stack_validation_2026-05-08.failclosed.json`
- `reports/model_stack_validation_2026-05-08.live_mistral.json`
- `reports/model_stack_validation_2026-05-08.live_mistral_mixed.json`
- `reports/model_stack_validation_2026-05-08.live_deepseek.json`
- `reports/model_stack_validation_2026-05-08.live_deepseek_review.json`
- `reports/model_stack_validation_2026-05-08.live_deepseek_review.json`

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

Recommendation: keep Mistral live for arbitration under the current fail-closed
contract. Do not use it to override smart-gate refusals without the persisted
arbitration log and post-apply audit.
