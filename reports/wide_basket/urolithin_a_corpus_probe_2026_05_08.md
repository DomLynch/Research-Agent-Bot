# Urolithin A Corpus Probe — 2026-05-08

## Result

Urolithin A moved from a dead dry-run corpus to a viable candidate corpus after calibrated seeding.

| Check | Before | After |
|---|---:|---:|
| Dry-run receipts | 0 | 14 |
| Non-orthogonal tensions | 0 | 16 |
| Quant-claim files | 0 | 122 |
| Parsed section files | 0 | 122 |

## Retrieval Funnel

| Stage | Count |
|---|---:|
| Retrieved post-dedupe | 1591 |
| Classified keep | 122 |
| Core on thesis | 14 |
| Background mechanism | 74 |
| Adjacent clinical | 34 |
| Off thesis / reject | 1469 |
| PMCID resolved | 63 |
| Abstract fallbacks | 62 |
| Quant claims extracted | 122 |
| Fetch failures | 59 |

## Dry-Run Receipt Mix

The dry-run built 14 receipts and 16 non-orthogonal tensions. The strongest direct receipt is `PMC9133463` (`A1`, direct, muscle function, positive). The remaining promoted evidence is mostly mechanistic or indirect, with outcomes spanning muscle function, cardiometabolic markers, and immune/inflammatory mechanisms.

## Audit Read

This is not yet an AAA claim. It is a corpus recovery pass: the topic is now runable and should proceed to a full synthesis only after a second audit of receipt quality and public-surface behavior.

No topic-specific Python was added. The corpus changed through calibrated seeding and existing classifier/retrieval paths.

## Next Step

Full synthesis was run locally at `runs/synthesis-urolithin_a-v06-2026-05-08T12-19-07Z`.

| Check | Result |
|---|---|
| Final verdict | AAA |
| Maturity | L4 — Analytically Certified |
| Stage-1 audit | 14/14, score 10.0 |
| Stage-2 consistency | P1=0, P2=0 |
| Reviewer unresolved P1 | 0 |
| Auto-stripped | 2 |
| Journal surface | fail |
| Final words | 14,414 |

## L4 Blockers

The corpus recovery succeeded, but the first full render is not journal-ready:

- three duplicate public-body paragraphs were detected by the journal surface gate
- public Methods rendered at 134/300 words in this run; the deterministic Methods renderer has since been expanded for future runs

The correct next action is rerun after the Methods-depth patch and duplicate-prose root-cause fix land. Do not manually edit this run into L5.
