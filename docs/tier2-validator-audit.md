# Tier 2 Validator Audit

## Scope
- Branch: `gpt-tier2-citation-roles`
- Slice:
  - citation roles
  - advisory citation validator
  - Europe PMC -> Unpaywall -> CORE full-text cascade

## Code Audit
- New modules:
  - `agent/citation_roles.py`
  - `agent/validator.py`
  - `agent/sources/unpaywall.py`
  - `agent/sources/core.py`
- Modified runtime surfaces:
  - `agent/drafter.py`
  - `agent/cli.py`
  - `agent/evidence_cards.py`
  - `agent/fulltext.py`

## Judge Pass
- Focused Phase A suite:
  - `79 passed`
  - validates role precedence, prompt grouping, validator behavior, and advisory run-log wiring
- Focused Phase B suite:
  - `30 passed`
  - validates Europe PMC fallback, Unpaywall JATS, Unpaywall PDF-only, CORE adapter, and CLI compatibility
- Full suite:
  - `330 passed, 6 skipped`
  - `ruff` clean

## Live Smoke
- Full-text cascade smoke on real DOIs:
  - `10.1038/s41586-020-2649-2 -> europepmc, parseable_text=True`
  - `10.1371/journal.pbio.3002669 -> europepmc, parseable_text=True`
- This confirms the cascade still works on live network requests after the refactor.

## Karpathy Loop Record
- Before snapshot:
  - `scripts/karpathy-loop/snapshots/20260422_061652_snapshot.json`
- After snapshot:
  - `scripts/karpathy-loop/snapshots/20260422_063158_snapshot.json`
- Diff:
  - `scripts/karpathy-loop/diffs/20260422_063209_diff.json`

## Metric Delta
- `composite_score`: `+0.0000`
- `quantitative_fidelity`: `+0.0000`
- `direction_agreement`: `+0.0000`
- `limitation_overlap`: `+0.0000`
- `study_overlap`: `+0.0000`

This flat delta is expected. Gold fixtures were **not** regenerated because `MIMO_API_KEY` is unset in this shell, so the harness is still scoring the pre-Tier-2 drafts.

## Blocker
- `scripts/generate_fixtures.py --all` is blocked in this environment:
  - `MIMO_API_KEY` missing
- Because of that, the live benchmark delta for Tier 2 is not measured yet.

## Remaining Risks
- Citation validation is advisory only. It logs violations but does not yet block or rewrite the draft.
- Unpaywall PDF-only hits improve coverage telemetry but do not help extraction until a PDF parser lands.
- CORE adapter is env-gated and unexercised without `CORE_API_KEY`.

## Next Required Step
1. Export `MIMO_API_KEY` in this shell.
2. Regenerate all 10 gold fixtures.
3. Rerun the Karpathy-loop snapshot/diff.
4. Re-audit:
   - `quantitative_fidelity`
   - `citation_violations`
   - role-language failures on metformin-aging and everolimus-style topics
