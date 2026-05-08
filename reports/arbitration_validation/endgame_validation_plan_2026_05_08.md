# Arbitration Validation Endgame Plan - 2026-05-08

## Scope

Mistral Small 4 via OpenRouter is the preferred V1 arbitrator. The
arbitrator is judge-only: it decides `APPLY`, `REJECT`, or `ESCALATE` for an
existing patch. It must not write replacement manuscript content or introduce
new facts, numerics, claims, or citations.

## Current Safeguards

- Strict output schema: exactly `verdict`, `rationale`, and `confidence`.
- Valid verdicts: `APPLY`, `REJECT`, `ESCALATE`.
- Malformed JSON fails closed to `ESCALATE`.
- Extra keys fail closed to `ESCALATE`.
- Replacement-content keys fail closed to `ESCALATE`.
- Disabled or missing key makes no network call.
- Mock transport tests cover model-call parsing without live network.

## Dry Harness Result

Fixture: `reports/arbitration_validation/mock_consensus_cases_2026_05_08.json`

Metrics output:

- Output: `reports/arbitration_validation/mock_consensus_metrics_2026_05_08.json`
- Total cases: 3
- Passed: 3
- Agreement rate: 1.0
- Fail-closed count: 1
- Escalate count: 1
- Classes covered: `APPLY`, `REJECT`, `ESCALATE`

These are mock consensus cases only. They prove metrics shape and fail-closed
behavior; they do not claim live human-consensus agreement.

## Endgame Validation Steps

### N=5 Pilot Fixture

Before any large benchmark, run a five-case pilot with locked expected labels:

| Case | Expected | Purpose | Required metric signal |
|---|---|---|---|
| deterministic citation normalization | APPLY | safe public-token cleanup | APPLY agreement |
| malformed table-row removal | APPLY | deterministic formatting cleanup | APPLY agreement |
| semantic numeric rewrite | REJECT | blocks meaning-changing edits | REJECT agreement |
| new citation insertion | REJECT | blocks new evidence generation | REJECT agreement |
| replacement-content response | ESCALATE | confirms fail-closed judge-only rule | ESCALATE + fail_closed |

Pilot metrics to report: total, passed, agreement rate, per-class agreement,
confusion matrix, fail-closed count, escalation count, and any schema rejects.
Passing the N=5 pilot only validates harness shape; it is not evidence of
general human-consensus performance.

1. Build a locked human-consensus fixture set from 50 to 100 historical patch
   decisions.
2. Label each case as `APPLY`, `REJECT`, or `ESCALATE` with rationale.
3. Run the current Mistral arbitration path offline or with recorded responses through
   `scripts/arbitration_validation_harness.py`.
4. Report agreement rate, per-class agreement, confusion matrix, fail-closed
   count, and escalation count.
5. Treat any replacement-content attempt as a hard fail-closed success only if
   the final verdict is `ESCALATE`.
6. Do not claim Cochrane-equivalent dual-human review. Claim only logged,
   benchmarked AI patch arbitration unless external human validation exists.

## Blockers

- No live Mistral validation run was performed in this lane.
- No external human-consensus benchmark exists yet.
- Arbitration is not integrated into the paper pipeline in this lane.
