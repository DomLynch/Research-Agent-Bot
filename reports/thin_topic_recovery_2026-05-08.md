# Thin Topic Recovery - 2026-05-08

Decision: no full synthesis render started. Floor is `>=10` receipts,
`>=50` dry-run high-confidence claims, and `>=10` non-orthogonal tensions.

Active reseed processes were present for `aspirin`, `taurine`, `spermidine`,
and `sleep_health`, so those topics are marked pending and their current
dry-run floor is not guessed. `senolytics` completed during this lane and was
dry-run twice.

## Status Table

`candidate count` comes from `_extract_report.json.n_unique_candidates`.
`extracted/quant count` is `_extract_report.json.n_extracted / quant_claims
files / high-binding quant claims`. Classifier classes are `core/bg/adj/off/rej`;
`corpus_classification.json` is used where available, otherwise
`corpus_manifest.json.funnel` is used.

| topic | candidate count | extracted/quant count | classifier classes | dry-run receipts/claims/tensions | floor | next action |
|---|---:|---:|---|---:|---|---|
| `everolimus` | 111 | 111 / 112 / 24 | 22/48/41/1/0 from `corpus_classification.json` | 5 / 24 / 2 | FAIL | Do not render; add receipt-grade aging/immune-aging mTOR papers before rerun. |
| `aspirin` | 327 | 27 / 43 / 14 | 7/0/4/4/1 from `corpus_classification.json` | pending active reseed | PENDING | Let active reseed finish, then rerun classifier/dry-run; ignore old `AAA*` run names. |
| `taurine` | 112 | 38 / 38 / 17 | 86/694/677/2871/39 from manifest | pending active reseed | PENDING | Let active reseed finish, then rerun dry-run; current target is broader human supplementation outcome diversity. |
| `spermidine` | 108 | 54 / 54 / 22 | 29/491/395/1908/31 from manifest | pending active reseed | PENDING | Let active reseed finish, then rerun dry-run; prioritize direct spermidine trials over indirect/null evidence. |
| `sleep_health` | 101 | 35 / 35 / 0 | 527/43/1733/1085/8 from manifest | pending active reseed | PENDING | Let active reseed finish, then inspect high-binding collapse before dry-run promotion. |
| `senolytics` | 543 | 542 / 561 / 186 | 54/234/255/3350/28 from manifest | 43 / 186 / 252 | PASS | Numerically floor-passing; queue for a guarded full render only with explicit directness/tier caveats, because most receipts are B2/C1 indirect or mechanistic. |
| `sauna_heat_therapy` | 291 | 49 / 49 / 2 | 50/31/241/2016/14 from manifest | 1 / 2 / 0 | FAIL | Do not render; fix high-binding collapse and add stronger human sauna endpoint papers. |

## Sidecars Read

| topic | latest dry-run sidecar | latest full-run sidecar | status |
|---|---|---|---|
| `everolimus` | `reports/wide_basket/everolimus_dry_run_audit2_2026_05_08.txt` = 1 / 10 / 0, stale versus current dry-run 5 / 24 / 2 | `runs/synthesis-everolimus-v06-LANEA-2026-05-08T1/manifest.json` = 1 receipt / 0 tensions | current completed dry-run still floor-fail |
| `aspirin` | none found | `runs/synthesis-aspirin-v06-LANEA2-2026-05-08T1/manifest.json` = 1 receipt / 0 tensions | pending active reseed |
| `taurine` | `reports/wide_basket/taurine_dry_run_audit2_2026_05_08.txt` = 2 / 17 / 1 | `runs/synthesis-taurine-v06-LANEA2-2026-05-08T1/manifest.json` = 2 receipts / 1 tension | pending active reseed |
| `spermidine` | `reports/wide_basket/spermidine_dry_run_audit2_2026_05_08.txt` = 2 / 22 / 0 | `runs/synthesis-spermidine-v06-LANEA2-2026-05-08T1/manifest.json` = 2 receipts / 0 tensions | pending active reseed |
| `sleep_health` | `reports/wide_basket/sleep_health_dry_run_audit2_2026_05_08.txt` = 0 / 0 / 0 | none found | pending active reseed |
| `senolytics` | none found; current dry-run command output = 43 / 186 / 252 | `runs/synthesis-senolytics-v06-proof005-2026-05-04T12-17-51Z/manifest.json` = 1 receipt / 0 tensions | completed numeric floor pass; not AAA by tier/directness |
| `sauna_heat_therapy` | `reports/wide_basket/sauna_heat_therapy_dry_run_audit2_2026_05_08.txt` = 1 / 2 / 0 | `runs/synthesis-sauna_heat_therapy-v06-LANEA-2026-05-08T1/manifest.json` = 1 receipt / 0 tensions | completed floor-fail |

## Audit Notes

- Audit 1: no L2/L3 or stale full-render directory was promoted as AAA.
- Audit 2: active reseed processes were not interrupted and pending topics were
  not promoted from partial output.
- No L6 backfill, model-stack docs, or topic-pack TOMLs were edited.
- Only this report was changed.
