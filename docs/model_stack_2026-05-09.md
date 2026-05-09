# Model Stack Decision - 2026-05-09

## Decision

Use this stack for the current synthesis/review path:

1. Writer / extractor: `mimo-v2.5-pro`
2. Final-layer reviewer: `deepseek/deepseek-v4-pro`
3. Fallback + bounded arbitrator: `mistralai/mistral-small-2603`

`scripts/grok_reviewer.py` and `scripts/granite_arbitrator.py` keep legacy
names for compatibility. The runtime defaults have moved off Grok and IBM
Granite.

## Evidence

Committed defaults:

- `agent/settings.py`: `MIMO_MODEL` defaults to `mimo-v2.5-pro`.
- `agent/settings.py`: `FINAL_LAYER_REVIEWER_MODEL` defaults to
  `deepseek/deepseek-v4-pro`.
- `agent/settings.py`: `FALLBACK_MODEL` defaults to
  `mistralai/mistral-small-2603`.
- `scripts/grok_reviewer.py`: `review_with_grok(...)` defaults to DeepSeek
  with Mistral fallback.
- `scripts/run_v06_synthesis.py`: arbitration model defaults to Mistral when
  `ARBITRATOR_ENABLED` is explicitly enabled.

Committed validation:

- Offline arbitration benchmark: `20/20` pass.
- Offline decision distribution: `APPLY 14 / REJECT 2 / ESCALATE 4`.
- Fail-closed fixture: `5/5` pass.
- Live Mistral ordered sample: `5/5` pass.
- Live Mistral mixed sample: `5/6` pass; the miss was conservative
  `ESCALATE` on an expected `REJECT`.
- Live DeepSeek smoke: HTTP 200, parsed `{"patches":[]}`.
- Live DeepSeek reviewer function: OK, `0` patches on synthetic smoke,
  cost `$0.00119`.
- DeepSeek replay spot-check: 3 known-defect snippets, 2/3 surfaced an issue;
  unsupported numeric recall remains unproven.
- DeepSeek 15-case live replay: 12/15 cases timed out at 30 seconds; 3/15
  evaluated; 0/3 passed expected severity/type recall. This is not adequate
  evidence to trust DeepSeek as the sole replacement for Grok on reviewer
  recall.
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

The local pricing table in `scripts/grok_reviewer.py` records:

- Grok 4.3: `$3.00` input / `$15.00` output per million tokens.
- DeepSeek V4 Pro: `$0.435` input / `$0.87` output per million tokens.
- Mistral Small 2603: `$0.15` input / `$0.60` output per million tokens.

DeepSeek is the final reviewer because it is materially cheaper than Grok while
still producing structured patch JSON in live smoke checks. Mistral is the
arbitrator/fallback because the arbitration task is narrow: judge an existing
patch, do not write new prose.

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

- DeepSeek has smoke validation and a bounded 15-case replay, but the live
  replay timed out on 12/15 cases and passed 0/3 evaluated cases.
- The replay spot-check missed one unsupported numeric snippet, so numeric
  review recall still depends on deterministic numeric gates.
- Mistral mixed-sample live validation is small (`6` cases).
- Legacy names (`grok_*`, `granite_*`) remain in code and JSON fields.
- `ARBITRATOR_ENABLED` is an explicit runtime gate; default model is Mistral
  when arbitration is enabled.

## Rollback / Fallback Plan

Keep DeepSeek as a low-cost reviewer candidate only behind measured validation.
For production-critical L5 runs, use Grok as fallback when DeepSeek times out,
returns zero patches on a long manuscript, or fails a replay threshold. Do not
claim DeepSeek is Grok-equivalent until a replay set clears the agreed recall
bar with acceptable latency.
