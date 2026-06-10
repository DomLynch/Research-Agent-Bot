# Model Stack Decision - 2026-05-09

## Decision

Use this stack for the current synthesis/review path:

1. Writer / extractor: `mimo-v2.5-pro`
2. Final-layer reviewer: `google/gemini-3.1-flash-lite:exacto`
3. Fallback + bounded arbitrator: `mistralai/mistral-small-2603`

`scripts/final_reviewer.py` and `scripts/granite_arbitrator.py` keep legacy
names for compatibility. The runtime defaults have moved off Grok and IBM
Granite.

## Evidence

Committed defaults:

- `agent/settings.py`: `MIMO_MODEL` defaults to `mimo-v2.5-pro`.
- `agent/settings.py`: `FINAL_LAYER_REVIEWER_MODEL` defaults to
  `google/gemini-3.1-flash-lite:exacto`.
- `agent/settings.py`: `FALLBACK_MODEL` defaults to
  `mistralai/mistral-small-2603`.
- `scripts/final_reviewer.py`: `review_paper(...)` defaults to Gemini
  3.1 Flash Lite Exacto with high thinking and Mistral fallback.
- `scripts/run_v06_synthesis.py`: arbitration model defaults to Mistral when
  `ARBITRATOR_ENABLED` is explicitly enabled.

Committed validation:

- Offline arbitration benchmark: `20/20` pass.
- Offline decision distribution: `APPLY 14 / REJECT 2 / ESCALATE 4`.
- Fail-closed fixture: `5/5` pass.
- Live Mistral ordered sample: `5/5` pass.
- Live Mistral mixed sample: `5/6` pass; the miss was conservative
  `ESCALATE` on an expected `REJECT`.
- OpenRouter lists Gemini 3.1 Flash Lite Exacto as
  `google/gemini-3.1-flash-lite:exacto`, released 2026-05-07, with
  1,048,576-token context and thinking levels including `high`.
- DeepSeek replay evidence was not adequate for primary reviewer status:
  12/15 live replay cases timed out at 30 seconds and 0/3 evaluated cases
  passed expected severity/type recall.
- Kimi K2.6 was considered but not shipped as the current default after the
  user redirected to Gemini Exacto.
- Arbitrator comparison after the ambiguous-target prompt change:
  Mistral Small 7/10, IBM Granite 4/10, Mistral Medium 3/10. Mistral Small
  stays default; Medium and Granite do not beat it on current evidence.

Evidence files:

- `reports/model_stack_validation_2026-05-08.md`
- `reports/model_stack_validation_2026-05-08.json`
- `reports/model_stack_validation_2026-05-08.failclosed.json`
- `reports/model_stack_validation_2026-05-08.live_mistral.json`
- `reports/model_stack_validation_2026-05-08.live_mistral_mixed.json`
- `reports/model_stack_validation_2026-05-08.live_deepseek.json`
- `reports/model_stack_validation_2026-05-08.live_deepseek_review.json`
- `reports/deepseek_reviewer_replay_2026-05-08.md`
- `reports/deepseek_reviewer_replay_2026-05-09.live.json`
- `validation/arbitrator_comparison_2026-05-09.json`

## Cost Rationale

The local pricing table in `scripts/final_reviewer.py` records:

- Grok 4.3: `$3.00` input / `$15.00` output per million tokens.
- Gemini 3.1 Flash Lite Exacto: `$0.25` input / `$1.50` output per million
  tokens.
- Mistral Small 2603: `$0.15` input / `$0.60` output per million tokens.

Gemini Exacto is the final reviewer because the requested model supports a
quality-first Exacto route, large context, and high thinking while remaining
cheaper than Grok. Mistral is the arbitrator/fallback because the arbitration
task is narrow: judge an existing patch, do not write new prose.

## Safety Boundary

The arbitrator is judge-only. It may return only:

- `APPLY`
- `REJECT`
- `ESCALATE`

It must never write replacement scientific content. Bad JSON, invalid verdict,
missing rationale, invalid confidence, low-confidence non-ESCALATE, forbidden
rewrite keys, timeout, or transport error all fail closed to `ESCALATE`.

## No Fake L5 Inflation

Mistral cannot silently inflate L5 because it does not assign certification. It
only proposes a closed-set decision on an already-proposed patch. The pipeline
still requires:

- persisted arbitration log when the arbitrator fires
- exact patch application only, never model-authored rewrite
- deterministic shape checks before application
- post-apply audit
- zero unresolved P1 review patches
- zero auto-strip surgery for L5
- clean journal-surface gate

Conservative `ESCALATE` blocks clean certification rather than upgrading it.

## Known Limits

- Gemini Exacto is newly selected and still needs a reviewer replay before it
  can be called Grok-equivalent.
- DeepSeek is demoted because reviewer recall/latency validation was weak.
- Numeric review recall still depends on deterministic numeric gates.
- Mistral mixed-sample live validation is small (`6` cases).
- Legacy names (`grok_*`, `granite_*`) remain in code and JSON fields.
- `ARBITRATOR_ENABLED` is an explicit runtime gate; default model is Mistral
  when arbitration is enabled.

## Rollback / Fallback Plan

Keep Grok as an explicit escalation model for suspiciously clean long papers
or failed replay thresholds. Do not claim Gemini Exacto is Grok-equivalent
until a replay set clears the agreed recall bar with acceptable latency.
