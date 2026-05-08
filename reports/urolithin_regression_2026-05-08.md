# Urolithin A Regression Check — 2026-05-08

Run checked:

`runs/synthesis-urolithin_a-v06-PATH2RICH5-2026-05-08TGRANITE`

## Result

- Verdict: `AAA`
- Maturity: `L5 — JOURNAL-READY`
- Stage-1 audit: `14/14`, score `10.0/10`
- Numeric traceability: `75/75` numerics trace to corpus
- Journal surface: pass
- Final-layer flags: `0`

## Prior Blockers

| Prior issue | Current result |
|---|---|
| Untraceable `57%` numeric | fixed: Q2 reports `percentage=15/15` and no untraceable numerics |
| malformed `000 mg` / `000 mg/day` | not present in manuscript scan |
| duplicate QEI heading | not present in manuscript scan |
| public topic-slug artifact | journal surface pass; remaining slug strings are appendix/provenance metadata, not journal body |

## Caveat

The run directory name still contains `TGRANITE` as historical naming. Runtime
defaults have moved to DeepSeek final review and Mistral arbitration.
