# Arbitration v1

Mistral arbitration is a judge-only helper for deciding whether an
existing patch should `APPLY`, `REJECT`, or `ESCALATE`.

## Environment

- `ARBITRATOR_ENABLED=1` enables live arbitration. Default is off.
- `GRANITE_ARBITRATOR_ENABLED=1` remains accepted as a legacy alias.
- `ARBITRATOR_API_KEY` supplies an arbitrator-specific API key when present.
- `GRANITE_API_KEY` remains accepted as a legacy alias.
- `OPENROUTER_API_KEY` is the fallback key via OpenRouter.
- `OPENROUTER_BASE_URL` defaults to `https://openrouter.ai/api/v1`.
- `ARBITRATOR_MODEL` defaults to `mistralai/mistral-small-2603`.
- `GRANITE_ARBITRATOR_MODEL` remains accepted as a legacy alias.
- `ARBITRATOR_TIMEOUT_SEC` defaults to `60`.
- `GRANITE_ARBITRATOR_TIMEOUT_SEC` remains accepted as a legacy alias.

No keys are committed. No live network calls are required for tests. Unit tests
use `httpx.MockTransport`.

## Contract

- Input contains `patch_id`, exact `before`, exact `after`, `refusal`,
  `rationale`, `context_hash`, and bounded local `paper_context`.
- Output is strict JSON with exactly `verdict`, `rationale`, and `confidence`.
- `verdict` must be exactly one of `APPLY`, `REJECT`, or `ESCALATE`.
- Invalid JSON, invalid verdicts, missing rationales, invalid confidence, or
  attempted replacement content fail closed to `ESCALATE`.
- `APPLY` can only apply the exact existing `after` text, only when `before`
  appears once, and only after deterministic post-apply audit passes.
- `REJECT` preserves the original manuscript text and records that the arbitrator
  rejected the reviewer patch.
- `ESCALATE`, timeout, malformed output, or failed post-apply audit falls back
  to the existing fail-closed path.
- Audit entries record `patch_id`, `decision`, `rationale`, `model`,
  `created_at`, deterministic `input_hash`, and schema version. Sidecars use
  `schema_version=arbitration_log_sidecar.v1` and an `arbitrations` list.
- The synthesis pipeline writes `full_paper.arbitration_log.json` and includes
  arbitration counts in `full_paper.review_patch_log.json`.

## Non-goals

- No new scientific content.
- No rewriting, improving, or replacing patch text.
- No new facts, numerics, estimates, claims, or citations.
- No secret, token, hidden prompt, or source leakage.
- No silent L5 inflation: every arbitration decision must be logged.

## Validation Harness

`scripts/arbitration_validation_harness.py` runs offline fixtures where each
case contains a model response and either `human_consensus_verdict`,
`consensus_verdict`, or `expected_verdict`. It reports agreement rate,
fail-closed count, escalation count, per-verdict agreement, and a confusion
matrix. This is a benchmark harness only; it does not prove clinical validity
without externally reviewed consensus fixtures.
