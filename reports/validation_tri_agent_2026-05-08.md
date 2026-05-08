# Tri-Agent Validation Evidence — 2026-05-08

## Scope

This lane validates the local arbitration harness and recorded tri-agent patch-decision fixtures. It does not use live web/API calls and does not claim Cochrane-equivalent human consensus.

## Inputs

| Input | Purpose |
|---|---|
| `tests/fixtures/arbitration_benchmark.jsonl` | 10 artifact-derived patch cases from historical runs |
| `tests/fixtures/validation_bad_json_cases_2026-05-08.json` | 1 synthetic malformed-JSON fail-closed guard |
| `docs/validation_reference_plan_2026-05-08.md` | No-network plan for future N=10 Cochrane-like validation |

The 10 benchmark cases cover all three verdict classes:

| Expected verdict | Count |
|---|---:|
| APPLY | 2 |
| REJECT | 2 |
| ESCALATE | 6 |

All 10 benchmark rows include: `before`, `after`, reviewer rationale, smart-gate reason, expected verdict, manual judgment reason, model response, and source run. All referenced source run directories exist locally.

## Commands Run

```bash
.venv/bin/python scripts/arbitration_validation_harness.py tests/fixtures/arbitration_benchmark.jsonl --output reports/validation_tri_agent_2026-05-08.json
.venv/bin/python scripts/arbitration_validation_harness.py tests/fixtures/validation_bad_json_cases_2026-05-08.json --output reports/validation_tri_agent_bad_json_2026-05-08.json
.venv/bin/python -m pytest tests/test_arbitration_validation_harness.py
```

## Results

Artifact-derived benchmark:

| Metric | Result |
|---|---:|
| Total cases | 10 |
| Passed | 10 |
| Overall agreement | 100% |
| APPLY agreement | 2/2 |
| REJECT agreement | 2/2 |
| ESCALATE agreement | 6/6 |
| Escalate count | 6 |
| Fail-closed count | 0 |

Confusion matrix:

| Expected | APPLY | ESCALATE | REJECT |
|---|---:|---:|---:|
| APPLY | 2 | 0 | 0 |
| ESCALATE | 0 | 6 | 0 |
| REJECT | 0 | 0 | 2 |

Malformed-JSON guard:

| Metric | Result |
|---|---:|
| Total synthetic guard cases | 1 |
| Passed | 1 |
| Bad-JSON rejection rate | 1/1 |
| Fail-closed rate | 1/1 |
| Actual verdict | ESCALATE |

Tests:

```text
tests/test_arbitration_validation_harness.py: 7 passed
```

## What This Supports

- The offline validation harness correctly parses JSON and JSONL fixtures.
- The recorded benchmark covers APPLY, REJECT, and ESCALATE decisions.
- Malformed arbitrator JSON fails closed to ESCALATE.
- The local fixture schema is now locked by test coverage.

## What This Does Not Support

- No live Mistral arbitration call was made in this lane.
- No external human-reviewer consensus was measured.
- No RoB 2, GRADE, or pooled-effect agreement was measured.
- No Cochrane-equivalent dual-human-review claim is justified.
- The 100% agreement is agreement with recorded fixture labels/model responses, not independent live-model accuracy.

## Methodology Boundary

The correct claim is:

> Researka has a local, reproducible validation harness for tri-agent patch arbitration, with 10 artifact-derived benchmark cases and explicit fail-closed malformed-JSON coverage.

The incorrect claim is:

> Researka's tri-agent system has been externally validated against Cochrane or human expert consensus.

## Next Validation Step

Populate the N=10 Cochrane-like reference plan with manually transcribed local review data, then compute RoB, GRADE, and effect-estimate agreement against Researka outputs. Until that exists, the validation evidence is limited to patch-arbitration mechanics.
