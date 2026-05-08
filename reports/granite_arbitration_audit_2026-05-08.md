# Granite Arbitration Audit — 2026-05-08

## Scope

Lane B audited the legacy IBM Granite arbitration mechanics and provenance. This was a
report/validation lane only: no live secrets, no Python edits, no commits, no
deploys.

## Decision

Granite is wired and useful only as a bounded third-reviewer signal. It is not
safe as an unconstrained semantic reviewer.

The live wrapper currently enforces the right boundary:

- verdicts are closed set: `APPLY`, `REJECT`, `ESCALATE`
- model output with replacement/new-content keys fails closed
- malformed JSON fails closed to `ESCALATE`
- disabled config makes no network call
- timeout/network failure fails closed to `ESCALATE`
- `APPLY` can only use Grok's exact `after` text or exact deletion, then must
  pass deterministic post-apply audit
- non-deletion semantic/numeric/structure rewrites are blocked
- non-unique `before` targets are blocked except bounded delete-all cases

## Files Inspected

- `scripts/granite_arbitrator.py`
- `scripts/arbitration_validation_harness.py`
- `scripts/run_v06_synthesis.py`
- `tests/test_granite_arbitrator.py`
- `tests/test_arbitration_validation_harness.py`
- `tests/test_grok_repair_loop.py`
- `runs/synthesis-urolithin_a-v06-PATH2RICH2-2026-05-08TGRANITE/full_paper.arbitration_log.json`
- `runs/synthesis-statins-v06-PATH2RICH3-2026-05-08TSTRICT/full_paper.arbitration_log.json`
- `runs/synthesis-statins-v06-PATH2RICH4-2026-05-08TSTRICT/full_paper.arbitration_log.json`

## Validation Commands

```bash
python3 scripts/arbitration_validation_harness.py tests/fixtures/arbitration_benchmark.jsonl --output reports/granite_arbitration_validation_offline_2026-05-08.json
python3 scripts/arbitration_validation_harness.py tests/fixtures/validation_bad_json_cases_2026-05-08.json --output reports/granite_arbitration_validation_bad_json_2026-05-08.json
python3 -m pytest tests/test_granite_arbitrator.py
python3 -m pytest tests/test_arbitration_validation_harness.py tests/test_grok_repair_loop.py
```

Additional no-network timeout smoke:

```text
{'verdict': 'ESCALATE', 'fail_closed': True, 'rationale': 'granite arbitrator call failed'}
```

## Test Results

| Check | Result |
|---|---:|
| Offline artifact-derived arbitration fixture | 10/10 passed |
| Bad-JSON fail-closed fixture | 1/1 passed |
| `tests/test_granite_arbitrator.py` | 13 passed |
| `tests/test_arbitration_validation_harness.py` | 7 passed |
| `tests/test_grok_repair_loop.py` | 16 passed |
| Targeted tests total | 36 passed |

## Fixture Case Table

| Case | Type | Expected | Actual | Result |
|---|---|---:|---:|---:|
| `synthesis-rapamycin-v06-PATH2RICHFIX3-2026-05-08TCLASSIFIER:P02` | structure | APPLY | APPLY | PASS |
| `synthesis-urolithin_a-v06-2026-05-08T14-37-21Z:P02` | numeric | APPLY | APPLY | PASS |
| `synthesis-rapamycin-v06-ENDGAME-2026-05-05T20-30-00Z:P08` | citation | REJECT | REJECT | PASS |
| `synthesis-rapamycin-v06-ENDGAME-2026-05-05T20-30-00Z:P09` | citation | REJECT | REJECT | PASS |
| `synthesis-creatine-v06-Q14VALID-2026-05-06T12-19-00Z:P01` | formatting | ESCALATE | ESCALATE | PASS |
| `synthesis-creatine-v06-Q14VALID-2026-05-06T12-19-00Z:P05` | claim | ESCALATE | ESCALATE | PASS |
| `synthesis-metformin-v06-FINAL-2026-05-05T21-15-00Z:P05` | structure | ESCALATE | ESCALATE | PASS |
| `synthesis-metformin-v06-aaa-real-2026-05-03T16-00-40Z:P01` | claim | ESCALATE | ESCALATE | PASS |
| `synthesis-rapamycin-v06-PATH2RICHFIX3-2026-05-08TCLASSIFIER:P03` | structure | ESCALATE | ESCALATE | PASS |
| `synthesis-metformin-v06-phd-2026-05-03T16-58-57Z:P01` | citation | ESCALATE | ESCALATE | PASS |

## Live Run Log Audit

| Run | Verdict | Arbitration entries | Model decisions | Pipeline effects |
|---|---|---:|---|---|
| `synthesis-urolithin_a-v06-PATH2RICH2-2026-05-08TGRANITE` | AAA / L4 | 1 | 1 APPLY | 1 blocked apply-shape |
| `synthesis-urolithin_a-v06-PATH2RICH3-2026-05-08TGRANITE` | AAA / L5 | 0 | none | none |
| `synthesis-urolithin_a-v06-PATH2RICH5-2026-05-08TGRANITE` | AAA / L5 | 0 | none | none |
| `synthesis-statins-v06-PATH2RICH3-2026-05-08TSTRICT` | TSP / L3 | 3 | 3 APPLY | 3 blocked non-unique-before |
| `synthesis-statins-v06-PATH2RICH4-2026-05-08TSTRICT` | AAA / L5 | 3 | 3 APPLY | 3 blocked non-unique-before |
| `synthesis-metformin-v06-PATH2RICH6-2026-05-08TSTRICT` | AAA / L4 | 0 | none | none |

Interpretation: Granite fired on real runs, but the deterministic wrapper
blocked unsafe model APPLY decisions. I found no evidence that Granite silently
inflated a verdict by overriding the smart-gate.

## Provenance

Persisted today:

- `full_paper.arbitration_log.json` stores per-decision model, patch id,
  decision, rationale, confidence, fail-closed flag, input hash, timestamp, and
  pipeline effect.
- `full_paper.review_patch_log.json` stores arbitration counts and the relative
  arbitration log path.

Gap:

- `full_paper.final_verdict.json` currently exposes Grok fields such as
  `grok_unresolved_p1` and `grok_flagged`, but does not carry arbitration
  counts or the arbitration log path. That is not a certification correctness
  bug because `review_patch_log` has the provenance, but the final verdict is
  under-informative.

Recommended small fix later:

- Add `arbitration: {n_arbitrated, n_apply, n_reject, n_escalate, log_path}` to
  the final verdict provenance block, copied from `full_paper.review_patch_log.json`.

## Value-Add Assessment

Granite adds real value in three narrow ways:

1. It records a third-reviewer opinion when Grok and the smart-gate disagree.
2. It can safely resolve exact public-surface patches/deletions when the
   deterministic wrapper and post-apply audit permit it.
3. It gives an auditable rationale for why a contested patch was applied,
   rejected, escalated, or blocked by wrapper policy.

Granite does not yet add reliable broad semantic judgment:

- Previous live raw Granite benchmark: 2/10 agreement, no escalations.
- Previous live tuned Granite benchmark: 3/10 agreement, still over-decided.
- Therefore the model must remain bounded by wrapper rules and deterministic
  post-apply audit.

## Fake-L5 Inflation Review

Pass 1: The wrapper blocks non-deletion semantic/numeric/structure rewrites,
non-unique targets, post-apply audit regressions, malformed JSON, and network
errors. That prevents a model APPLY from becoming silent manuscript surgery.

Pass 2: Existing live arbitration logs show blocked APPLY decisions, not silent
applications. Runs that reached L5 either had no arbitration or had logged,
blocked arbitration entries. I found no evidence of Granite-driven fake L5.

Remaining risk: final verdict JSON should expose arbitration provenance directly
so external readers do not need to inspect `review_patch_log` to see that a
third model was involved.

## Bottom Line

Granite is live-gated, logged, and bounded. It is adding audit-trail value and
limited repair value, but it should stay conservative: judge only, never
rewrite, fail closed, and no L5 credit without persisted arbitration provenance.
The active default has since moved to Mistral Small 4 under the same bounded
judge-only contract.
