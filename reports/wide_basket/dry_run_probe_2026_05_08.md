# Wide Basket Dry-Run Probe — 2026-05-08

Read-only probe command: `python scripts/run_v06_synthesis.py --topic <topic> --dry-run`.

## Passed Receipt Floor

| Topic | Receipts | Tensions | Read |
|---|---:|---:|---|
| resistance_training | 78 | 1375 | full synthesis candidate |
| protein_nutrition | 92 | 1202 | full synthesis candidate |
| intermittent_fasting | 76 | 1755 | full synthesis candidate |
| zone2_training | 36 | 184 | full synthesis candidate |
| acarbose | 19 | 105 | viable but thinner |
| berberine | 15 | 77 | viable but thinner |

## Corpus Tune First

| Topic | Receipts | Tensions | Reason |
|---|---:|---:|---|
| collagen_peptides | 3 | 1 | below receipt floor |
| taurine | 2 | 1 | below receipt floor |
| spermidine | 2 | 0 | below receipt floor |
| everolimus | 1 | 0 | below receipt floor |
| sauna_heat_therapy | 1 | 0 | below receipt floor |
| sleep_health | 0 | 0 | no high-confidence claims |
| urolithin_a | 0 | 0 | no high-confidence claims |

Next full-run priority: `protein_nutrition`, `resistance_training`, `intermittent_fasting`, `zone2_training`, then `acarbose` / `berberine`.
