# Model Stack Switch — 2026-05-08

Current default stack:

1. Writer/extractor: `mimo-v2.5-pro`
2. Final-layer reviewer: `deepseek/deepseek-v4-pro`
3. Fallback + bounded arbitrator: `mistralai/mistral-small-2603`

## Verification

- DeepSeek reviewer smoke: live OpenRouter call succeeded, JSON parsed, `n_patches=0`, estimated cost `$0.001105`.
- Mistral arbitrator smoke: live OpenRouter call succeeded, verdict `APPLY`, fail-closed `false`.
- Targeted tests: `104 passed`.
- Ruff: clean on changed reviewer/arbitrator/settings surfaces.

## Boundary

Mistral arbitration remains judge-only. It may only return `APPLY`, `REJECT`, or `ESCALATE`; it never writes replacement scientific content. Bad JSON, timeout, invalid verdict, non-unique patch targets, or failed post-apply audit fail closed.
