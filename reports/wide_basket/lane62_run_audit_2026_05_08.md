# Lane 62 Run Audit — 2026-05-08

## Result

The new wide-basket runs are analytically useful but not yet journal-ready. Most were rendered before the deterministic public Methods-depth patch, so the recurring blocker is `Methods 134/300`.

| Topic | Run | Verdict | Maturity | Main Blockers |
|---|---|---|---|---|
| protein_nutrition | `synthesis-protein_nutrition-v06-2026-05-08T12-13-27Z` | AAA | L4 | duplicate paragraph, Methods 134/300, Conclusion 240/250 |
| resistance_training | `synthesis-resistance_training-v06-LANE62B-2026-05-08T12-13-29Z` | TSP-Agent unresolved | L3 | 2 unresolved P1, Methods 134/300, Conclusion 213/250 |
| intermittent_fasting | `synthesis-intermittent_fasting-v06-LANE62C-2026-05-08T12-10-00Z` | Trust-Spine Pass | L3 | audit 13/14, duplicate paragraphs, Methods 134/300 |
| zone2_training | `synthesis-zone2_training-v06-LANE62D-2026-05-08T000000Z` | AAA | L4 | Methods 134/300 only |
| acarbose | `synthesis-acarbose-v06-LANE62E-2026-05-08T12-13-43Z` | AAA | L4 | Methods 134/300 only |
| urolithin_a | `synthesis-urolithin_a-v06-2026-05-08T12-19-07Z` | AAA | L4 | duplicate paragraphs, Methods 134/300 |
| collagen_peptides | `synthesis-collagen_peptides-v06-2026-05-08T12-39-21Z` | incomplete | n/a | no final verdict |

## Interpretation

Path 2 continues to improve corpus depth, but the widened corpus makes public manuscript gates stricter. This is not a science regression; it is the surface/compiler layer correctly refusing L5 when public Methods or duplicate public prose fails the journal-ready contract.

## Fixes Landed After These Runs

- Deterministic public Methods expanded above the 300-word floor.
- Exact duplicate public-body paragraph cleanup added after restoration/backfill paths.
- Bundle Schema validator added; current run directories fail closed until public bundle files are generated.

## Next Validation

Rerun the cleanest candidates first after the fixes:

1. `zone2_training`
2. `acarbose`
3. `urolithin_a`
4. `protein_nutrition`

Zone2 and acarbose are the fastest validation targets because their sampled blockers were Methods-depth only.
