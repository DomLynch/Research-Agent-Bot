# Endgame Task Ledger - 2026-05-08

## Current State

| Item | State |
|---|---|
| Current local HEAD | `32ee6475` |
| Branch | `main` |
| Dirty state before this ledger | clean except two existing untracked final-audit reports |
| Active synthesis processes at ledger time | none found |
| Source reports read | `basket_status_2026-05-08.md`, `targeted_regression_cases_2026-05-08.md`, `model_stack_validation_2026-05-08.md`, `model_stack_switch_2026-05-08.md`, `final_model_stack_audit_2026-05-08.md`, `final_dirty_state_audit_2026-05-08.md`, `osf_publisher_service/readiness.md`, `open_spec_methods_package.md`, `spec_validation_2026_05_08.md`, `topic_pack_generator_probe_2026-05-08.md` |

## Completed Task Groups

1. Reviewer stack moved to the current production shape: MiMo writer/extractor, DeepSeek final reviewer, Mistral bounded arbitration/fallback.
2. Arbitration boundary hardened: closed-set `APPLY` / `REJECT` / `ESCALATE`, no rewrite payloads, bad JSON and transport errors fail closed.
3. Legacy IBM Granite path audited and deprecated as a default; Mistral live samples outperformed the older Granite smoke runs.
4. L6 reproducibility backfill shipped for the rapamycin PATHA series.
5. Targeted regression cases recovered: urolithin_a, metformin, GLP-1, and statins all reached AAA/L5 on current targeted reports.
6. Statins and urolithin_a retrieval packs were tuned and produced rich L5 runs.
7. Basket inventory/reporting landed for current topic state.
8. Topic-pack generator V1 landed as dry-run only; curated TOML packs remain authoritative.
9. OSF publisher is kept as an independent sibling service; bot remains synthesis-only and DW remains provenance-only.
10. Open-spec and methodology docs were drafted for bundle schema, tri-agent/reviewer protocol, verdict taxonomy, JSON-LD citation, and OSF service boundaries.

## Tests Already Reported

| Surface | Reported verification |
|---|---|
| Model stack switch | `104 passed`; ruff clean on reviewer/arbitrator/settings surfaces |
| Arbitration harness + arbitrator | `26 passed`; ruff clean on touched arbitration files |
| Topic-pack generator | `9 passed`; ruff clean |
| OSF publisher scaffold | `20 passed`; ruff clean; scoped secret scan clean |
| Statins retrieval/classifier/surface/verdict | `111 passed` |
| Targeted regression cases | Artifact-level pass across urolithin_a, metformin, GLP-1, statins |
| Spec validation | JSON-LD fixtures pass; bundle schema validation fails closed on non-public sample bundles |

## Model Stack State

| Layer | Current default |
|---|---|
| Writer / extractor | `mimo-v2.5-pro` |
| Final-layer reviewer | `deepseek/deepseek-v4-pro` |
| Third-layer arbitration / fallback | `mistralai/mistral-small-2603` |

Legacy names remain in code and JSON compatibility fields: `grok_*`, `scripts/grok_reviewer.py`, `scripts/granite_arbitrator.py`, and `GRANITE_*` env aliases. They should not be read as current model defaults.

## Basket State

Latest basket report:

| Metric | Count |
|---|---:|
| Real topic packs | 25 |
| Topics with latest run | 24 |
| AAA topics | 13 |
| L5 topics | 9 |
| L6 topics | 1 |
| Ship-blocked topics | 2 |
| Latest-run receipts | 658 |
| Latest-run tensions | 6,855 |

Confirmed strong current topics include: caloric_restriction, creatine, GLP-1, metformin, NAD precursors, omega3, rapamycin, statins, and urolithin_a.

## Remaining Blockers

1. Fresh tri-sync evidence for current HEAD `32ee6475` is still required before a deploy-ready claim.
2. Existing untracked final-audit reports need owner review before commit.
3. OSF publisher is dry-run ready only; no live OSF call or live provenance write-back has been verified.
4. Bundle Schema 1.0 public bundle validation is fail-closed because sample synthesis dirs lack the public bundle files.
5. Several basket topics remain thin, missing recent rich runs, or surface-blocked: acarbose, aerobic_exercise, aspirin, collagen_peptides, everolimus, intermittent_fasting, protein_nutrition, resistance_training, sauna_heat_therapy, senolytics, sleep_health, spermidine, taurine, vitamin_d, zone2_training.
6. Journal-only export still needs packaging separation from Researka audit/provenance appendices.

## Next Gate

Run a read-only final checkpoint: local status, targeted tests for touched files, origin match, VPS `/opt` + `/root` HEAD/dirty state, and service status. Do not claim final deploy readiness until that passes.
