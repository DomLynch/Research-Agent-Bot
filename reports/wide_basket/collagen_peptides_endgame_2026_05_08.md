# Collagen Peptides Endgame Audit — 2026-05-08

Lane accounting: wide-basket collagen_peptides corpus recovery and synthesis-quality check. This report preserves the wider 62-task tracker context and only updates this topic's endgame status.

## Corpus Recovery

| Stage | Before tune | After tune |
|---|---:|---:|
| Dry-run receipts | 3 | 13 |
| Non-orthogonal tensions | 1 | 11 |
| Retrieved candidates | n/a | 2391 |
| Classified keep | n/a | 434 |
| Core pool | n/a | 79 |
| Background pool | n/a | 128 |
| Adjacent pool | n/a | 227 |
| PMCID resolved | n/a | 144 |
| Abstract fallbacks | n/a | 300 |
| Extracted quant claims | 70 previous corpus files | 433 |
| Extract failures | n/a | 290 |

Tuning used the existing universal corpus seeding path for the collagen topic pack. No shared classifier or synthesis code was edited.

## Synthesis Status

| Item | Result |
|---|---:|
| Run dir | `runs/synthesis-collagen_peptides-v06-2026-05-08T12-39-21Z` |
| Receipts | 13 |
| High-confidence claims | 46 |
| Non-orthogonal tensions | 11 |
| Final words (`wc -w`) | 13261 |
| Final verdict | Trust-Spine Pass |
| Maturity | L2 — partial |
| Journal ready | no |
| Journal surface | pass |
| Reviewer unresolved P1 | 0 |
| Review auto-strips | 0 |
| Consistency issues | 0 |
| Numeric quarantine | 16 |
| QEI quarantine | 10 |

## Evidence Audit

| Gate | Evidence | Read |
|---|---|---|
| Manifest consistency | Complete manifest/audit/verdict/surface/patch/quarantine set | Pass |
| Trust spine | Stage-1 14/14, stage-2 P1=0/P2=0, score 10.0/10 | Pass |
| Reviewer layer | 5 patches proposed; applied=3, rejected=0, flagged=2, auto_stripped=0 | No unresolved P1 |
| Journal surface | `passed=true`, no issues | Pass |
| Corpus floor | high-confidence claims 46/50 | Blocks AAA/L4+ |
| Numerics | audit says 39/39 traced; 16 numeric claims quarantined | No unsafe numeric promotion found |
| Citation artifacts | placeholder scan for TODO/PLACEHOLDER/citation-needed patterns clean | No template/citation placeholder found |

## No-Regression Read

| Rule | Result |
|---|---|
| No public template prose | Pass by scan; no TODO/PLACEHOLDER/public-template markers found |
| No citation artifacts | Pass by scan; no citation-needed or placeholder citation markers found |
| No unsafe numerics | Pass at audit layer; quarantine sidecars are present and non-empty |
| No fake AAA | Pass: verdict remains Trust-Spine Pass/L2 because corpus is still short |

## Blocker

Collagen is no longer a 3-receipt thin false-ready topic, but it is still not AAA-ready. The remaining blocker is corpus depth: high-confidence claims are short by 4, and the funnel shows many closed-access or unindexed candidates (`n_abstract_fallback=300`, `failures=290`).

Do not publish as AAA. Treat this as a viable partial synthesis with a corpus-expansion backlog.

## Next Validation

Run one more corpus-recovery pass focused on universal open-access/abstract fallback handling and trial-resolution coverage, then rerun dry-run. Full rerun is justified only if high-confidence claims reach at least 50 without degrading citation/numeric gates.
