# Overnight Basket Queue - 2026-05-08

Scope: report-only planning lane. No synthesis code, topic-pack code, run directories, or active artifacts were modified.

## Inputs Checked

- `reports/basket_status_2026-05-08.md`
- `reports/basket_lane_A_remaining_topics_2026-05-08.md`
- latest `runs/synthesis-*` directories by mtime
- `topic_packs/*.toml`
- latest available `full_paper.final_verdict.json`, `manifest.json`, and `_extract_report.json`

## Remaining Non-AAA Inventory

| Topic | Latest run | Current status | Maturity | Receipts | Claims | Tensions | Notes |
|---|---|---:|---:|---:|---:|---:|---|
| aspirin | `synthesis-aspirin-v06-RECOVERY-2026-05-08T1` | no final verdict | n/a | 0 | n/a | n/a | 907 candidates, 230 PMCID resolved; likely incomplete/recovery run |
| sleep_health | `synthesis-sleep_health-v06-RECOVERY-2026-05-08T1` | no final verdict | n/a | 0 | n/a | n/a | 1200 candidates, 358 PMCID resolved; survival gate likely strict |
| spermidine | `synthesis-spermidine-v06-RECOVERY-2026-05-08T1` | no final verdict | n/a | 0 | n/a | n/a | 915 candidates, 582 PMCID resolved; rich retrieval but low receipt survival |
| taurine | `synthesis-taurine-v06-RECOVERY-2026-05-08T1` | no final verdict | n/a | 0 | n/a | n/a | 1200 candidates, 419 PMCID resolved; rich retrieval but low receipt survival |
| aerobic_exercise | `synthesis-aerobic_exercise-v06-DIAG-2026-05-05T23-06-41Z` | Trust-Spine Pass | L2 | 5 | 37 | 1 | retrieval exists; evidence floor not met |
| collagen_peptides | `synthesis-collagen_peptides-v06-2026-05-08T12-39-21Z` | Trust-Spine Pass | L2 | 13 | 46 | 11 | close to floor; claims are just below 50 |
| everolimus | `synthesis-everolimus-v06-LANEA-2026-05-08T1` | Trust-Spine Pass | L2 | 1 | 10 | n/a | likely over-pruned by oncology/transplant boundaries |
| intermittent_fasting | `synthesis-intermittent_fasting-v06-LANEA-2026-05-08T2` | Trust-Spine Pass | L3 | 76 | 1038 | 1755 | floor-rich; needs render/review cleanup, not more retrieval first |
| resistance_training | `synthesis-resistance_training-v06-LANE62B-2026-05-08T12-13-29Z` | TSP-Agent Unresolved | L3 | 78 | 1008 | 1375 | floor-rich; journal surface/review blocker |
| sauna_heat_therapy | `synthesis-sauna_heat_therapy-v06-LANEA-2026-05-08T1` | Trust-Spine Pass | L2 | 1 | 2 | n/a | retrieval present; receipt survival is weak |
| vitamin_d | `synthesis-vitamin_d-v06-DIAG-2026-05-05T23-22-44Z` | TSP-Agent Unresolved | L2 | 2 | 28 | n/a | broad field, current pack likely under-selects direct trials |

## AAA But Not Journal-Ready Queue

These are not non-AAA, but they are useful overnight targets because they are corpus-rich and already above the evidence floor.

| Topic | Latest run | Current status | Maturity | Receipts | Claims | Tensions | Primary risk |
|---|---|---:|---:|---:|---:|---:|---|
| protein_nutrition | `synthesis-protein_nutrition-v06-2026-05-08T12-13-27Z` | AAA | L4 | 92 | 674 | 1202 | journal surface failed |
| zone2_training | `synthesis-zone2_training-v06-LANE62D-2026-05-08T000000Z` | AAA | L4 | 36 | 444 | 184 | journal surface failed |
| acarbose | `synthesis-acarbose-v06-LANE62E-2026-05-08T12-13-43Z` | AAA | L4 | 19 | 285 | 105 | journal surface failed |

Excluded: `senolytics` latest actual run is already AAA/L5 (`synthesis-senolytics-v06-RECOVERY-2026-05-08T1`, 43 receipts). Do not spend overnight render calls there unless a regression check is explicitly requested.

## Ranked Overnight Queue

Priority is expected corpus yield plus probability of producing useful AAA/L4+ output under floor gates.

| Rank | Topic | Action class | Expected yield | Floor risk | Recommendation |
|---:|---|---|---:|---|---|
| 1 | resistance_training | render cleanup | very high | low | Dry-run first, then full render only if surface blockers are absent or repairable |
| 2 | protein_nutrition | journal cleanup | very high | low | Dry-run first; likely one compiler/surface pass away |
| 3 | intermittent_fasting | render cleanup | very high | low | Dry-run first; watch patch ambiguity and numeric density |
| 4 | sleep_health | survival debug | high | high | Reseed/classify/dry-run only until receipts survive |
| 5 | taurine | survival debug | high | high | Reseed/classify/dry-run only; do not full render from zero-receipt recovery |
| 6 | spermidine | survival debug | high | high | Reseed/classify/dry-run only; likely synonym/precursor issue |
| 7 | aspirin | survival debug | high | high | Reseed/classify/dry-run only; likely trial/outcome boundary issue |
| 8 | zone2_training | journal cleanup | medium-high | low | Dry-run first; avoid redundant retrieval |
| 9 | aerobic_exercise | corpus expansion | medium | medium-high | Reseed/classify/dry-run; full render only after floor |
| 10 | vitamin_d | corpus expansion | medium | high | Reseed/classify/dry-run; require direct trial survival before render |
| 11 | collagen_peptides | near-floor expansion | medium | medium | Reseed/classify/dry-run; likely can clear claim floor |
| 12 | acarbose | journal cleanup | medium | low | Dry-run first; already analytically strong |
| 13 | sauna_heat_therapy | corpus expansion | low-medium | high | Reseed/classify/dry-run; likely needs pack term review |
| 14 | everolimus | boundary audit | low-medium | high | Reseed/classify/dry-run; likely excludes useful immunosenescence literature |
| 15 | senolytics | monitor only | high | none | Already AAA/L5; no overnight render unless regression requested |
| 16 | metformin | monitor only | high | none | Already AAA/L5; optional L6/reproducibility accounting only |
| 17 | glp1 | monitor only | high | none | Already AAA/L5; optional reproducibility accounting only |
| 18 | statins | monitor only | high | none | Already AAA/L5; optional reproducibility accounting only |

Do not pad the queue to 20 with clean AAA/L5 topics. That burns writer calls without expanding the basket.

## Missing Terms And Synonym Risks

These are TOML-only recommendations for later pack edits. No topic-specific Python is recommended.

| Topic | Likely missing or under-weighted terms |
|---|---|
| aspirin | `alternate-day aspirin`, `disability-free survival`, `major hemorrhage`, `intracranial bleeding`, `gastrointestinal bleeding`, `MACE`, `colorectal cancer prevention` |
| sleep_health | `polysomnography`, `sleep fragmentation`, `Pittsburgh Sleep Quality Index`, `PSQI`, `insomnia severity index`, `ISI`, `CBT-I`, `obstructive sleep apnea`, `CPAP`, `actigraphy` |
| spermidine | `spermine`, `putrescine`, `polyamine intake`, `polyamine metabolism`, `Bruneck study`, `wheat germ extract`, `autophagy inducer` |
| taurine | `serum taurine`, `plasma taurine`, `urinary taurine`, `taurine transporter`, `SLC6A6`, `TauT`, `taurine chloramine`, `taurine deficiency` |
| aerobic_exercise | `VO2 peak`, `VO2peak`, `cardiorespiratory fitness`, `aerobic training`, `walking intervention`, `6-minute walk`, `moderate-intensity continuous training` |
| collagen_peptides | `FORTIGEL`, `VERISOL`, `BODYBALANCE`, `Peptan`, `collagen hydrolysate`, `skin elasticity`, `joint pain`, `osteoarthritis` |
| everolimus | `RAD001`, `Mannick`, `resTORbio`, `immunosenescence`, `TORC1 immune function`, `vaccine response`; audit transplant/oncology excludes before loosening |
| intermittent_fasting | `5:2 diet`, `fasting-mimicking diet`, `FMD`, `time-restricted feeding`, `early time-restricted feeding`, `caloric restriction confound` |
| protein_nutrition | `HMB`, `beta-hydroxy-beta-methylbutyrate`, `casein`, `protein-energy malnutrition`, `PROT-AGE`, `EAA`, `BCAA`, `leucine-enriched` |
| resistance_training | `progressive resistance training`, `RET`, `strength exercise`, `chair rise`, `SPPB`, `gait speed`, `1RM`, `multicomponent exercise` |
| sauna_heat_therapy | `Kuopio`, `KIHD`, `Laukkanen`, `passive heating`, `thermal therapy`, `hot bath`, `heat acclimation`, `infrared sauna` |
| vitamin_d | `VITAL`, `DO-HEALTH`, `D-Health`, `ViDA`, `25(OH)D`, `calcitriol`, `falls prevention`, `fracture prevention` |
| zone2_training | `lactate threshold`, `ventilatory threshold`, `maximal fat oxidation`, `MFO`, `fat oxidation`, `aerobic base training`, `MICT` |
| acarbose | `STOP-NIDDM`, `ACE trial`, `postprandial hyperglycemia`, `cardiovascular events`, `alpha-glucosidase inhibitor` |

## Floor-Gated Command Profiles

Use these profiles instead of one-off topic-specific scripts.

### Profile A - Rich Topic Render Cleanup

For: `resistance_training`, `protein_nutrition`, `intermittent_fasting`, `zone2_training`, `acarbose`.

```bash
TOPIC=resistance_training
STAMP=OVERNIGHT-2026-05-09T01

.venv/bin/python scripts/run_v06_synthesis.py --topic "$TOPIC" --dry-run

# Only after dry-run confirms receipts >= 10, claims >= 50, tensions >= 10,
# no P1 blocker, and no obvious journal-surface placeholder issue:
GRANITE_ARBITRATOR_ENABLED=1 \
GRANITE_ARBITRATOR_TIMEOUT_SEC=60 \
.venv/bin/python scripts/run_v06_synthesis.py \
  --topic "$TOPIC" \
  --out-dir "runs/synthesis-${TOPIC}-v06-${STAMP}"
```

### Profile B - Corpus Survival Debug

For: `sleep_health`, `taurine`, `spermidine`, `aspirin`, `aerobic_exercise`, `vitamin_d`, `collagen_peptides`, `sauna_heat_therapy`, `everolimus`.

```bash
TOPIC=sleep_health
STAMP=OVERNIGHT-2026-05-09T02

.venv/bin/python scripts/seed_topic_corpus.py --topic "$TOPIC" --max-per-source 35
.venv/bin/python scripts/run_corpus_classifier.py --topic "$TOPIC"
.venv/bin/python scripts/run_v06_synthesis.py --topic "$TOPIC" --dry-run

# Stop here unless dry-run reports receipts >= 10, claims >= 50, tensions >= 10.
# Only then:
GRANITE_ARBITRATOR_ENABLED=1 \
GRANITE_ARBITRATOR_TIMEOUT_SEC=60 \
.venv/bin/python scripts/run_v06_synthesis.py \
  --topic "$TOPIC" \
  --out-dir "runs/synthesis-${TOPIC}-v06-${STAMP}"
```

### Profile C - Monitor Only

For: `senolytics`, `metformin`, `glp1`, `statins`.

```bash
# No overnight render.
# Optional only: inspect latest verdict and L6/consecutive status.
.venv/bin/python scripts/certification_report.py --help
```

## Proposed Batch Order

Batch 1, likely payoff:

```text
resistance_training, protein_nutrition, intermittent_fasting, zone2_training, acarbose
```

Batch 2, high-candidate survival debug:

```text
sleep_health, taurine, spermidine, aspirin
```

Batch 3, medium/near-floor expansion:

```text
aerobic_exercise, collagen_peptides, vitamin_d
```

Batch 4, high-risk tail:

```text
sauna_heat_therapy, everolimus
```

## Stop Rules

Stop a topic before full render if any condition is true:

1. Dry-run receipts < 10.
2. Dry-run claims < 50.
3. Dry-run tensions < 10.
4. Any P1 numeric traceability failure appears before review.
5. Journal surface shows placeholder prose, duplicate headings, malformed numerics, or topic slug leakage.
6. Grok/Granite path returns bad JSON, timeout, or missing log path.
7. Patch path would create L5 without persisted arbitration or repair provenance.
8. The latest run directory has no final verdict after extraction/classification completes.

Do not full-render zero-receipt recovery runs directly.

## Rollback Rules

- Do not use `git reset --hard` or `git checkout --` during overnight queue work.
- If a new run fails before commit, leave the run directory for audit unless disk pressure requires removal.
- If disk pressure requires cleanup, remove only the new uncommitted `runs/synthesis-<topic>-v06-OVERNIGHT-*` directory and log the removal in the operator notes.
- Keep clean AAA/L5 topic runs untouched.
- Revert only via a forward commit if a committed report or config needs correction.

## Time And Cost Estimate

| Work class | Topics | Time per topic | Expected cost per topic | Notes |
|---|---:|---:|---:|---|
| Rich render cleanup | 5 | 30-90 min | $0.05-$0.20 | highest chance of L4/L5 improvement |
| Survival debug dry-run | 9 | 10-35 min | <$0.05 until full render | do not full-render unless floor passes |
| Monitor only | 4 | 2-5 min | $0 | no writer calls |

Expected gated overnight run:

- Wall time: 6-12 hours with parallel lanes.
- Spend: about $0.75-$2.50 if only floor-passing topics render.
- Worst-case if every topic full-renders: 14-22 hours and $2-$5, but this is not recommended.

## Double Audit

### Data Sanity Audit

- Current queue uses actual latest run directories, not only static reports.
- `senolytics` is excluded from the active queue because latest actual run is AAA/L5.
- `aspirin`, `sleep_health`, `spermidine`, and `taurine` are treated as no-verdict recovery runs, not as successful zero-receipt topics.
- Rich floor-passing topics are separated from thin corpus topics to avoid unnecessary reseed churn.

### Safety Audit

- No topic-specific Python is proposed.
- Synonym fixes are TOML-only recommendations for a later patch lane.
- Full render appears only after explicit dry-run floor gates.
- Granite/third-review path is required to fail closed and persist provenance; it is not allowed to silently inflate L5.

## Exact Recommendation

Run Batch 1 first with Profile A. It has the highest chance of overnight certification wins because the evidence floors are already met.

Run Batch 2 only through reseed/classify/dry-run until receipt survival is proven. Do not full-render those topics from current no-verdict recovery state.

Patch TOML synonyms in a separate reviewed lane before expensive reruns for `sleep_health`, `taurine`, `spermidine`, `aspirin`, `vitamin_d`, `sauna_heat_therapy`, and `everolimus`.
