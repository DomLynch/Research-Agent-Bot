# Final Model-Stack Audit - 2026-05-08

## Verdict

Pass, with naming debt.

The configured production stack is:

1. Writer/extractor: `mimo-v2.5-pro`
2. Final-layer reviewer: `deepseek/deepseek-v4-pro`
3. Third-layer arbitration/fallback: `mistralai/mistral-small-2603`

## Evidence Read

- `agent/settings.py`
  - `mimo_model` default: `mimo-v2.5-pro`
  - `final_layer_reviewer_model` default: `deepseek/deepseek-v4-pro`
  - `fallback_model` default: `mistralai/mistral-small-2603`
  - `judge_model` still defaults to `google/gemma-4-31b-it`; this is separate from the final-layer reviewer path.
- `scripts/grok_reviewer.py`
  - `review_with_grok(...)` default model is `deepseek/deepseek-v4-pro`.
  - fallback model is `mistralai/mistral-small-2603`.
  - function/module names remain Grok-era compatibility names.
- `scripts/granite_arbitrator.py`
  - module docstring states the module name is legacy and runtime default is Mistral Small 4.
  - arbitrator decisions are closed-set: `APPLY`, `REJECT`, `ESCALATE`.
  - forbidden replacement-content keys fail closed.
- `scripts/arbitration_validation_harness.py`
  - live arbitration default is `mistralai/mistral-small-2603`.
  - `GRANITE_*` env names remain compatibility aliases.
  - every decision row includes an `arbitration_log_entry`.
- `reports/model_stack_validation_2026-05-08.md`
  - confirms MiMo -> DeepSeek -> Mistral stack.

## Validation Evidence

| Check | Result |
|---|---:|
| Offline arbitration benchmark | 20/20 pass |
| Offline distribution | APPLY 14 / REJECT 2 / ESCALATE 4 |
| Fail-closed fixture | 5/5 pass |
| Live Mistral ordered sample | 5/5 pass |
| Live Mistral mixed sample | 5/6 pass |
| Mixed-sample miss | expected REJECT, got conservative ESCALATE |
| Live DeepSeek HTTP smoke | HTTP 200, parsed `{"patches":[]}` |
| Live DeepSeek reviewer function | OK, 0 patches, cost `$0.00119` |

Historical IBM Granite live runs on the earlier fixture scored 2/10 and 3/10.
The comparison is not perfectly controlled because the fixture and prompt were
later hardened, but Mistral's current live mixed sample is materially stronger
and its only miss was conservative.

## Fail-Closed Boundary

The arbitrator is judge-only.

Allowed output:

```json
{"verdict": "APPLY|REJECT|ESCALATE", "rationale": "...", "confidence": 0.0}
```

Fail-closed cases verified:

- malformed JSON
- invalid verdict
- missing or empty rationale
- invalid confidence
- low-confidence non-ESCALATE decision
- forbidden rewrite/replacement-content fields
- HTTP/transport error

Fail-closed result is `ESCALATE`, not silent patch application.

## Residual Naming Debt

- `scripts/grok_reviewer.py` is now the DeepSeek final-layer reviewer path but
  keeps Grok-era names for compatibility.
- `scripts/granite_arbitrator.py` now defaults to Mistral Small 4 but keeps the
  Granite-era module/class names.
- `GRANITE_*` env aliases still exist for backward compatibility.
- JSON/report fields using `grok_*` counters remain legacy names and should be
  renamed only in a compatibility-safe schema migration.

## Audit Conclusion

Mistral is adding value as a bounded third-layer judge, not as a semantic
override. It should remain live only with persisted arbitration logs, closed-set
decisions, and post-apply deterministic audits. This does not justify fake L5
inflation.
