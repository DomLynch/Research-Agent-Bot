# Basket Execution Lane A - 2026-05-08

Scope: run/report artifacts only. No core trust-spine code, topic packs, or compiler code edited.

## Inputs

- Project context read: `AGENTS.md`, `PROJECT_STATE.md`
- Basket source read: `reports/basket_status_2026-05-08.md`
- Primary batch selected from no-run / no-PATH2 topics:
  - `sleep_health`
  - `spermidine`
  - `taurine`
  - `sauna_heat_therapy`
  - `everolimus`
- Added one rich surface-blocked regression case:
  - `intermittent_fasting`

## Commands Run

```bash
GRANITE_ARBITRATOR_ENABLED=1 GRANITE_ARBITRATOR_TIMEOUT_SEC=60 .venv/bin/python scripts/run_v06_synthesis.py --topic sleep_health --out-dir runs/synthesis-sleep_health-v06-LANEA-2026-05-08T1
GRANITE_ARBITRATOR_ENABLED=1 GRANITE_ARBITRATOR_TIMEOUT_SEC=60 .venv/bin/python scripts/run_v06_synthesis.py --topic spermidine --out-dir runs/synthesis-spermidine-v06-LANEA-2026-05-08T1
GRANITE_ARBITRATOR_ENABLED=1 GRANITE_ARBITRATOR_TIMEOUT_SEC=60 .venv/bin/python scripts/run_v06_synthesis.py --topic taurine --out-dir runs/synthesis-taurine-v06-LANEA-2026-05-08T1
GRANITE_ARBITRATOR_ENABLED=1 GRANITE_ARBITRATOR_TIMEOUT_SEC=60 .venv/bin/python scripts/run_v06_synthesis.py --topic sauna_heat_therapy --out-dir runs/synthesis-sauna_heat_therapy-v06-LANEA-2026-05-08T1
GRANITE_ARBITRATOR_ENABLED=1 GRANITE_ARBITRATOR_TIMEOUT_SEC=60 .venv/bin/python scripts/run_v06_synthesis.py --topic everolimus --out-dir runs/synthesis-everolimus-v06-LANEA-2026-05-08T1
GRANITE_ARBITRATOR_ENABLED=1 GRANITE_ARBITRATOR_TIMEOUT_SEC=60 .venv/bin/python scripts/run_v06_synthesis.py --topic intermittent_fasting --out-dir runs/synthesis-intermittent_fasting-v06-LANEA-2026-05-08T2
```

`GRANITE_*` variables are legacy compatibility aliases. Current arbitration
defaults route through the Mistral bounded judge.

Dry-run triage also checked: `senolytics`, `vitamin_d`, `aerobic_exercise`, `collagen_peptides`, `aspirin`, `resistance_training`, `intermittent_fasting`, `protein_nutrition`.

## Results

| Topic | Run dir | Verdict | Maturity | Stage-1 | JS | Receipts | Claims | Tensions | Patches | Mistral path | Public leakage |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| sleep_health | none | pre-render fail | none | n/a | n/a | 0 | 0 | 0 | n/a | n/a | n/a |
| spermidine | `runs/synthesis-spermidine-v06-LANEA-2026-05-08T1` | Trust-Spine Pass | L2 | 14/14, 10.0 | pass | 2 | 22 | 0 | 7 proposed, 3 applied, 0 flagged, 0 strips | 0 | clean |
| taurine | `runs/synthesis-taurine-v06-LANEA-2026-05-08T1` | Trust-Spine Pass | L2 | 14/14, 10.0 | pass | 2 | 17 | 1 | 6 proposed, 6 applied, 0 flagged, 0 strips | 0 | clean |
| sauna_heat_therapy | `runs/synthesis-sauna_heat_therapy-v06-LANEA-2026-05-08T1` | Trust-Spine Pass | L2 | 13/14, 9.3 | pass | 1 | 2 | 0 | 5 proposed, 3 applied, 1 flagged, 1 strip | 1 | clean |
| everolimus | `runs/synthesis-everolimus-v06-LANEA-2026-05-08T1` | Trust-Spine Pass | L2 | 13/14, 9.3 | pass | 1 | 10 | 0 | 6 proposed, 5 applied, 0 flagged, 0 strips | 0 | clean |
| intermittent_fasting | `runs/synthesis-intermittent_fasting-v06-LANEA-2026-05-08T2` | Trust-Spine Pass | L3 | 13/14, 9.3 | pass | 76 | 1038 | 1755 | 4 proposed, 2 applied, 2 flagged, 0 strips | 0 | clean |

## Per-Topic Notes

### sleep_health

Failed before render: current strict path built zero receipts and reported `No high-confidence claims found`. This is not a manuscript compiler problem. The current corpus has 35 parsed/quant files, but the high-confidence survival path admits none.

Recommended next fix: audit the sleep topic pack plus classifier survival reasons. Do not spend writer calls until dry-run builds at least 10 receipts.

### spermidine

Surface-clean but corpus-thin. The run passed all audit checks and journal surface, but final verdict stayed L2 because the evidence floor was missed: 2/10 receipts, 22/50 claims, 0/10 tensions, only two outcome classes, no A-tier/direct receipts.

Recommended next fix: broaden retrieval around dietary spermidine, polyamine intake, cognition, mortality, autophagy, and human cohort evidence; then dry-run before another full render.

### taurine

Surface-clean but corpus-thin. The run passed 14/14 and journal surface, but final verdict stayed L2: 2/10 receipts, 17/50 claims, 1/10 tensions.

Recommended next fix: expand beyond supplementation trials into taurine abundance/deficiency, aging cohorts, cardiometabolic endpoints, and frailty/muscle outcomes.

### sauna_heat_therapy

Corpus and numeric density blocker. The run had only 1 receipt, 2 claims, 0 tensions. Stage-1 failed Q9 numeric density: 2.1 numerics/1000 words, threshold 8.0.

The arbitration path fired once on a P1 numeric patch. It returned `REJECT`, but the pipeline treated deletion-reject as escalation and still auto-stripped the unsafe region. This is the correct no-fake-L5 behavior: the third-layer judgment was logged, but did not silently override the trust spine.

Recommended next fix: retrieval expansion should prioritize sauna cohort mortality papers, Finnish sauna studies, passive heat therapy RCTs, vascular-function studies, and cardiometabolic heat-acclimation endpoints.

### everolimus

Corpus and numeric density blocker. The run had only 1 receipt, 10 claims, 0 tensions. Stage-1 failed Q9 numeric density: 4.7 numerics/1000 words, threshold 8.0.

Recommended next fix: the current topic pack excludes much transplant/oncology noise, but the surviving anti-aging corpus is too narrow. Add RTB101/immunosenescence/vaccine-response and mTOR inhibitor aging terms, then dry-run.

### intermittent_fasting

Rich corpus, still not AAA. The run built 76 receipts, 1038 claims, and 1755 tensions, but stayed L3 because Stage-1 failed Q9 numeric density: 7.3 numerics/1000 words, threshold 8.0.

Patch log had two flagged patches, but both were non-P1: P2 citation ambiguity and P3 capitalization ambiguity. Arbitration did not fire because there was no flagged P1 after smart-gate. Public leakage checks were clean: no underscore slug artifacts, malformed `000 mg` numerics, duplicate QEI headings, or template/meta leakage in the manuscript body.

Recommended next fix: this is a manuscript-density/QEI selection issue, not a corpus issue. The rich corpus is already present; improve numeric surfacing without weakening traceability.

## Dry-Run Triage

| Topic | Dry-run result | Interpretation |
|---|---:|---|
| senolytics | 0 receipts | classifier/retrieval survival blocker |
| vitamin_d | 2 receipts | corpus-thin under strict high-confidence path |
| aerobic_exercise | 5 receipts | below floor, mixed topic contamination visible |
| collagen_peptides | 3 receipts | below floor |
| aspirin | 1 receipt | below floor |
| resistance_training | 78 receipts, 1375 tensions | rich surface-blocked candidate for next execution lane |
| intermittent_fasting | 76 receipts, 1755 tensions | rich candidate, executed in this lane |
| protein_nutrition | 92 receipts, 1202 tensions | rich surface-blocked candidate for next execution lane |

## Double Audit

Audit pass 1: verified each completed run's `full_paper.final_verdict.json`, `full_paper.audit.json`, `full_paper.journal_surface.json`, `full_paper.review_patch_log.json`, and `manifest.json`.

Audit pass 2: scanned manuscript body before `## Search Provenance` for:

- underscore slug artifacts
- malformed `000 mg` / `000 mg/day` numerics
- duplicate Quantitative Evidence Index headings
- template/platform leakage: `deterministic evidence summary`, `no LLM authorship`, `LLM proposes`, `code disposes`, `Trust-Spine Pass`, `A2A-AAA certification`

All completed Lane A manuscripts were clean on those public-surface scans.

## Conclusion

Lane A did not add new AAA topics. It did identify the split cleanly:

1. `sleep_health`, `spermidine`, `taurine`, `sauna_heat_therapy`, `everolimus`, `senolytics`, `vitamin_d`, `aerobic_exercise`, `collagen_peptides`, and `aspirin` need retrieval/classifier survival work before more full renders.
2. `intermittent_fasting`, `resistance_training`, and `protein_nutrition` are already rich enough; their next work is manuscript-gate and numeric-density stabilization.
3. The Mistral arbitration path is wired into the run path and logged when a flagged P1 exists. In the sauna run it added a third-reviewer judgment without inflating certification.

Open risk: this lane used the current dirty working tree, including other workers' uncommitted topic-pack and compiler changes. The report should be treated as a sprint diagnostic, not a clean-baseline benchmark.
