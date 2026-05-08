# Statins PATH2 Rich Rerun — 2026-05-08

## Scope

Long-horizon worker lane for statins only. No shared Python edits were made in this lane.

## Commands Run

```bash
.venv/bin/python scripts/seed_topic_corpus.py --topic statins --limit 2000 --max-per-source 120
.venv/bin/python scripts/run_corpus_classifier.py --topic statins
GRANITE_ARBITRATOR_ENABLED=1 .venv/bin/python scripts/run_v06_synthesis.py --topic statins --out-dir runs/synthesis-statins-v06-PATH2RICH-2026-05-08TSTATINS-WORKER
```

`GRANITE_ARBITRATOR_ENABLED` is a legacy env alias. The current third-layer
default is the bounded Mistral arbitration path when arbitration is enabled.

## Corpus Funnel

| Stage | Count |
|---|---:|
| Retrieved | 1,535 |
| Kept after calibrated retrieval | 786 |
| Core hits | 235 |
| Background hits | 111 |
| Adjacent clinical hits | 440 |
| PMCID resolved | 91 |
| Abstract fallbacks | 714 |
| Quant claims extracted | 782 |
| Fetch/extract failures | 695 |

Classifier output over the accumulated statins corpus:

| Class | Count |
|---|---:|
| core_on_thesis | 325 |
| background_mechanism | 155 |
| adjacent_clinical | 580 |
| off_thesis | 37 |
| reject | 2 |

## Synthesis Result

Run directory:

```text
runs/synthesis-statins-v06-PATH2RICH-2026-05-08TSTATINS-WORKER/
```

| Metric | Result |
|---|---:|
| Final verdict | AAA |
| Maturity | L5 — JOURNAL-READY |
| Journal ready | true |
| Certification track | AAA-CLIN |
| Receipts | 70 |
| High-confidence claims | 468 |
| Non-orthogonal tensions | 628 |
| Evidence weight | 37.6 |
| Clinical weight | 36.4 |
| Mechanistic weight | 1.2 |
| Final word count | 37,850 |
| Writer calls / cost | 24 / $0.1374 |

Stage audits:

| Gate | Result |
|---|---|
| Stage-1 audit | 14/14, 10.0/10 |
| Numeric traceability | 152/152, 100% |
| Stage-2 consistency | 0 P1, 0 P2 |
| Journal surface | pass, 0 issues |
| Reviewer unresolved P1 | 0 |
| Reviewer auto-strips | 0 |

Final-layer review:

| Patch state | Count |
|---|---:|
| Proposed | 6 |
| Applied | 4 |
| Rejected | 1 |
| Flagged | 1 |
| Arbitrated by Mistral path | 0 |
| Auto-stripped | 0 |

The flagged patch was P05, a P2 numeric deletion that passed the simplification gate but was not applied because post-apply audit regressed Stage-2 issue count from 0 to 1. This did not create an unresolved P1 and did not block the unified L5 verdict.

## Surface Audit

Manual grep checks on `full_paper.md`:

| Check | Result |
|---|---|
| `000 mg` / `000 mg/day` | 0 |
| duplicate QEI headings | 0; one heading only |
| raw table slugs in main body | 0 |
| `deterministic evidence summary` | 0 |
| platform/meta leakage in manuscript body | 0 |
| platform/provenance appendix language | present, expected in appended disclosure |

One appendix/public-surface caveat remains: the single QEI heading is rendered as `Quantitative Evidence Index — statins` and one provenance table row contains `muscle_function`. The current journal surface gate passes these, and they occur outside the scientific body, but a journal-only export should humanize them before external submission.

## Interpretation

Path 2 worked for statins. The earlier thin-corpus state is gone: the current run uses 70 receipts with 468 bound claims and 628 tensions, and the final artifact certifies as AAA/L5 on the current gates.

The main residual risk is not corpus size. It is public-packaging polish: the appended audit/provenance sections are acceptable for a Researka bundle, but a conventional journal export should move them to supplement and humanize appendix labels.

## Verification

```bash
.venv/bin/python -m pytest tests/test_topic_pack.py tests/test_seed_topic_corpus.py tests/test_corpus_classifier.py tests/test_journal_surface_gate.py tests/test_unified_verdict.py
# 111 passed
```

Second-pass artifact assertions were run against the verdict, audit, manifest, surface gate, review patch log, extract report, and classifier output. All reported counts above match the generated artifacts.
