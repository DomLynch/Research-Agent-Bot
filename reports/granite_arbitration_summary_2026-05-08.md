# Arbitration Summary — 2026-05-08

## Status

- Pipeline wire: live-gated behind `GRANITE_ARBITRATOR_ENABLED=1`.
- Model default: `mistralai/mistral-small-2603` via OpenRouter-compatible API.
- Legacy model override remains available via `GRANITE_ARBITRATOR_MODEL`.
- Boundary: judge-only `APPLY` / `REJECT` / `ESCALATE`; no rewrite content accepted.
- Audit: every call writes `full_paper.arbitration_log.json`; review logs include arbitration counts.

## Validation

- Offline harness: 10/10 agreement on fixture parser and expected labels.
- Live raw Granite smoke: 2/10 agreement; model over-decided and never escalated.
- Live tuned Granite prompt smoke: 3/10 agreement; improved deletion handling, still over-decides.
- Mistral Small 2603 is now the default model candidate for the same wrapper.

## Safety Decision

No arbitrator model is trusted as a free semantic judge. The pipeline wrapper now permits:

- `APPLY` only for exact-after public-surface patches or exact deletion patches.
- No non-empty claim/numeric/structure rewrites from the arbitrator.
- `REJECT` on deletion patches is treated as `ESCALATE`, so unsafe text still fails closed.
- Any timeout, malformed JSON, bad verdict, non-unique `before`, or post-apply audit regression falls back to existing fail-closed behavior.

## Value

Arbitration adds value as a logged third-reviewer signal and can resolve narrow public-surface/deletion disputes. It is not allowed to replace deterministic gates or certify semantic rewrites.
