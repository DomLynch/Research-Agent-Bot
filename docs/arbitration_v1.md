# Arbitration v1

IBM Granite arbitration is a judge-only helper for deciding whether an
existing patch should `APPLY`, `REJECT`, or `ESCALATE`.

## Environment

- `OPENROUTER_API_KEY` enables calls and supplies the OpenRouter key.
- `OPENROUTER_BASE_URL` defaults to `https://openrouter.ai/api/v1`.
- `GRANITE_ARBITRATOR_MODEL` defaults to `ibm-granite/granite-4.1-8b`.

No live network calls are required for tests. Unit tests use `httpx.MockTransport`.

## Contract

- Input contains `patch_id`, exact `before`, exact `after`, `refusal`,
  `rationale`, and `context_hash`.
- Output is strict JSON with exactly `verdict`, `rationale`, and `confidence`.
- `verdict` must be exactly one of `APPLY`, `REJECT`, or `ESCALATE`.
- Invalid JSON, invalid verdicts, missing rationales, invalid confidence, or
  attempted replacement content fail closed to `ESCALATE`.
- Audit entries record `patch_id`, `decision`, `rationale`, `model`,
  `created_at`, deterministic `input_hash`, and schema version. Sidecars use
  `schema_version=arbitration_log_sidecar.v1` and an `arbitrations` list.

## Non-goals

- No new scientific content.
- No rewriting, improving, or replacing patch text.
- No new facts, numerics, estimates, claims, or citations.
- No pipeline integration in v1.
- No secret, token, hidden prompt, or source leakage.
