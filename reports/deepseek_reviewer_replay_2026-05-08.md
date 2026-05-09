# DeepSeek Reviewer Replay - 2026-05-08

## Verdict

Partial pass.

DeepSeek is not smoke-only anymore: a small live replay was run against three
known prior defect snippets. It surfaced issues in 2/3 cases, but missed one
unsupported numeric. This is useful evidence, not a full recall benchmark.

## Existing Committed Evidence

- `reports/model_stack_validation_2026-05-08.live_deepseek.json`
  - HTTP 200
  - requested `deepseek/deepseek-v4-pro`
  - resolved `deepseek/deepseek-v4-pro-20260423`
  - parsed `{"patches":[]}`
- `reports/model_stack_validation_2026-05-08.live_deepseek_review.json`
  - reviewer function status `ok`
  - model used `deepseek/deepseek-v4-pro`
  - `0` patches on synthetic clean smoke
  - cost `$0.001187`

Those files prove live connectivity and JSON parsing. They do not prove recall
against prior Grok-flagged defects.

## Replay Run

Command shape used:

```bash
.venv/bin/python - <<'PY'
# called scripts.grok_reviewer.review_with_grok(...) with:
# model=deepseek/deepseek-v4-pro
# fallback_model=mistralai/mistral-small-2603
# three small known-defect manuscript snippets
PY
```

No API key or secret value was printed or written.

## Replay Cases

| Case | Prior defect class | DeepSeek result | Read |
|---|---|---:|---|
| `metformin_broken_citation_token` | malformed citation token `(Metformin 2019b 2019)` | 1 P1 patch | Caught issue, but typed as `structure`, not precise citation repair |
| `glp1_unsupported_numeric_effect` | unsupported `71.0%` effect estimate | 0 patches | Missed |
| `senolytics_placeholder_prose` | `_Conclusion failed scoped validation._` residue | 1 P1 patch | Caught correctly as formatting deletion |

Replay cost:

- metformin snippet: `$0.001453`
- GLP-1 snippet: `$0.001812`
- senolytics snippet: `$0.001248`
- total: about `$0.00451`

## Interpretation

DeepSeek is viable as a low-cost final reviewer and can catch obvious public
surface defects. The replay does not establish high recall for numeric defects.
Therefore DeepSeek should remain an adversarial reviewer, not the trust source
for numeric integrity.

Numeric trust still belongs to deterministic gates:

- numeric traceability audit
- numeric quarantine
- QEI/public-render exclusion
- post-apply audit

## Cheapest Next Validation

Build a committed `tests/fixtures/deepseek_reviewer_replay_2026-05-08.json`
with 15-20 historical P1 snippets and expected issue classes, then run a bounded
live replay that records:

- recall by defect class
- patch type accuracy
- P1/P2 severity accuracy
- false-positive rate on clean snippets
- cost per case

Suggested command pattern:

```bash
.venv/bin/python scripts/deepseek_reviewer_replay.py \
  tests/fixtures/deepseek_reviewer_replay_2026-05-08.json \
  --limit 20 \
  --output reports/deepseek_reviewer_replay_2026-05-09.json
```

That script does not exist yet. Until it does, live replay should stay small and
manual to avoid accidental full-paper review cost.
