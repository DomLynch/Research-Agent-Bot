# Basket Lane A Remaining Topics - 2026-05-08

Scope: topic-pack retrieval hardening plus safe reruns. No shared Python edited. No commit/deploy.

## Contract Read

- Re-read `AGENTS.md`.
- Re-read `PROJECT_STATE.md`.
- Re-read `reports/basket_status_2026-05-08.md`.

Latest basket status at start: 13 AAA topics, 9 L5 topics, 1 L6 topic, 2 ship-blocked topics, and `sleep_health` with no latest run.

## Diagnosis

| Topic | Latest status before this lane | Existing corpus | Current strict dry-run | Failure class |
|---|---:|---:|---:|---|
| `sleep_health` | no run | 35 parsed / 35 quant | 0 receipts | extraction confidence / classifier survival |
| `aspirin` | SHIP-BLOCKED old run | 43 parsed / 43 quant | 1 receipt, 14 claims | corpus floor, not manuscript |
| `senolytics` | SHIP-BLOCKED old run | 59 parsed / 59 quant | 0 receipts | extraction confidence / classifier survival |
| `taurine` | L2 | 38 parsed / 38 quant | 2 receipts, 17 claims, 1 tension | corpus floor |
| `spermidine` | L2 | 54 parsed / 54 quant | 2 receipts, 22 claims, 0 tensions | corpus floor |
| `sauna_heat_therapy` | L2 | 49 parsed / 49 quant | 1 receipt, 2 claims | corpus floor + numeric density |
| `everolimus` | L2 | 9 parsed / 9 quant | 1 receipt, 10 claims | corpus floor + off-target oncology survivor |
| `aerobic_exercise` | L2 | 151 parsed / 151 quant | 5 receipts, 37 claims, 3 tensions | corpus floor + topic contamination |
| `vitamin_d` | L2 unresolved | 84 parsed / 84 quant | 2 receipts, 28 claims | corpus floor + prior review flags |
| `collagen_peptides` | L2 | 70 parsed / 70 quant | 3 receipts, 24 claims, 1 tension | corpus floor under current strict path |
| `intermittent_fasting` | L3 | 233 parsed / 233 quant | 76 receipts, 1038 claims, 1755 tensions | rich corpus; numeric density / patch ambiguity |
| `resistance_training` | L3 | 290 parsed / 290 quant | 78 receipts, 1008 claims, 1375 tensions | rich corpus; journal surface / unresolved review |

Root finding: most low-level topics have enough parsed files but almost no `binding_confidence="high"` claims. Topic-pack changes improve future retrieval/extraction, but they do not rewrite existing `quant_claims`.

## Topic-Pack Changes

Minimal TOML-only changes were applied to:

- `topic_packs/sleep_health.toml`
- `topic_packs/aspirin.toml`
- `topic_packs/senolytics.toml`
- `topic_packs/taurine.toml`
- `topic_packs/spermidine.toml`
- `topic_packs/sauna_heat_therapy.toml`
- `topic_packs/everolimus.toml`

Changes were limited to aliases, active-arm synonyms, search queries, retrieval topic/scope terms, and background allow-list terms.

Intent:

- `sleep_health`: add CBT-I long form, ISI/PSQI, AHI/CPAP, sleep-efficiency endpoints.
- `aspirin`: add ASPREE disability-free survival, dementia, hemorrhage, ARRIVE/ASCEND queries.
- `senolytics`: add D+Q variants, UBX0101, BCL-xL, IPF/DKD senolytic trial terms.
- `taurine`: add plasma taurine, deficiency, blood-pressure/meta-analysis, muscle-function terms.
- `spermidine`: add SmartAge, spermidine-rich wheat germ, Bruneck, cognitive decline terms.
- `sauna_heat_therapy`: add Finnish sauna, KIHD/Kuopio, Waon therapy, hot-water immersion, endothelial endpoints.
- `everolimus`: add TORC1, Mannick, RAD001 vaccine, RTB101 respiratory-infection endpoint terms.

## Commands Run

Validation:

```bash
.venv/bin/python - <<'PY'
from agent.topic_pack import load_topic_pack
for t in ["sleep_health","aspirin","senolytics","taurine","spermidine","sauna_heat_therapy","everolimus"]:
    load_topic_pack(f"topic_packs/{t}.toml")
PY
```

Dry-runs:

```bash
.venv/bin/python scripts/run_v06_synthesis.py --topic sleep_health --dry-run
.venv/bin/python scripts/run_v06_synthesis.py --topic aspirin --dry-run
.venv/bin/python scripts/run_v06_synthesis.py --topic senolytics --dry-run
.venv/bin/python scripts/run_v06_synthesis.py --topic taurine --dry-run
.venv/bin/python scripts/run_v06_synthesis.py --topic spermidine --dry-run
.venv/bin/python scripts/run_v06_synthesis.py --topic sauna_heat_therapy --dry-run
.venv/bin/python scripts/run_v06_synthesis.py --topic everolimus --dry-run
.venv/bin/python scripts/run_v06_synthesis.py --topic collagen_peptides --dry-run
```

Safe full reruns:

```bash
GRANITE_ARBITRATOR_ENABLED=1 GRANITE_ARBITRATOR_TIMEOUT_SEC=60 .venv/bin/python scripts/run_v06_synthesis.py --topic aspirin --out-dir runs/synthesis-aspirin-v06-LANEA2-2026-05-08T1
GRANITE_ARBITRATOR_ENABLED=1 GRANITE_ARBITRATOR_TIMEOUT_SEC=60 .venv/bin/python scripts/run_v06_synthesis.py --topic taurine --out-dir runs/synthesis-taurine-v06-LANEA2-2026-05-08T1
GRANITE_ARBITRATOR_ENABLED=1 GRANITE_ARBITRATOR_TIMEOUT_SEC=60 .venv/bin/python scripts/run_v06_synthesis.py --topic spermidine --out-dir runs/synthesis-spermidine-v06-LANEA2-2026-05-08T1
```

`sleep_health` and `senolytics` were not full-rendered because dry-run still built zero receipts.

## Rerun Results

| Topic | Run | Verdict | L | Stage-1 | JS | Receipts | Claims | Tensions | Patch state | Public leakage |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|---:|
| `aspirin` | `runs/synthesis-aspirin-v06-LANEA2-2026-05-08T1` | Trust-Spine Pass | L2 | 14/14, 10.0 | pass | 1 | 14 | 0 | 0 review patches | clean |
| `taurine` | `runs/synthesis-taurine-v06-LANEA2-2026-05-08T1` | Trust-Spine Pass | L2 | 14/14, 10.0 | pass | 2 | 17 | 1 | 4 proposed / 4 applied / 0 flagged / 0 strips | clean |
| `spermidine` | `runs/synthesis-spermidine-v06-LANEA2-2026-05-08T1` | Trust-Spine Pass - Agent Review Unresolved | L2 | 13/14, 9.3 | pass | 2 | 22 | 0 | 18 proposed / 5 applied / 3 flagged / 8 strips / 11 arbitrated | clean |

`spermidine` should not be promoted over the prior `runs/synthesis-spermidine-v06-LANEA-2026-05-08T1` run, which was cleaner at 14/14. The rerun exposed stochastic manuscript/review instability on the same too-thin two-receipt corpus.

## Double Audit

Pass 1 verified these files for each completed rerun:

- `full_paper.final_verdict.json`
- `full_paper.audit.json`
- `full_paper.journal_surface.json`
- `full_paper.review_patch_log.json` when present
- `numeric_claim_quarantine.json`
- `qei_quarantined.json`
- `manifest.json`

Pass 2 scanned manuscript body before `## Search Provenance` for:

- underscore slug artifacts
- malformed `000 mg` / `000 mg/day`
- duplicate Quantitative Evidence Index headings
- template/platform leakage: `deterministic evidence summary`, `no LLM authorship`, `LLM proposes`, `code disposes`, `Trust-Spine Pass`, `A2A-AAA certification`

All three completed reruns were clean on public-leakage scans.

## Targeted Checks

```bash
.venv/bin/python -m pytest tests/test_topic_pack.py tests/test_topic_pack_generator.py tests/test_brief_topic_matcher.py -q
# 44 passed

git diff --check -- topic_packs/sleep_health.toml topic_packs/aspirin.toml topic_packs/senolytics.toml topic_packs/taurine.toml topic_packs/spermidine.toml topic_packs/sauna_heat_therapy.toml topic_packs/everolimus.toml reports/basket_lane_A_remaining_topics_2026-05-08.md
# clean
```

## Blockers

| Topic class | Topics | Blocker | Next best move |
|---|---|---|---|
| Zero high-confidence receipts | `sleep_health`, `senolytics` | Existing quant claims are `none`/`partial`, no high-confidence effect claims | reseed/re-extract with patched topic packs; inspect extractor confidence reasons |
| Thin high-confidence corpus | `aspirin`, `taurine`, `spermidine`, `sauna_heat_therapy`, `everolimus`, `vitamin_d`, `collagen_peptides`, `aerobic_exercise` | current strict path does not meet 10/50/10 floor | rerun corpus discovery/extraction, not more paper rendering |
| Rich but manuscript-blocked | `intermittent_fasting`, `resistance_training`, plus L4 surface-fail topics | enough receipts/claims/tensions; failing density/surface/review lottery | manuscript/QEI numeric-density stabilization and review-patch ambiguity fixes |

## Conclusion

This lane hardened the future retrieval specs but did not convert additional topics to AAA. The limiting factor for the requested low-level topics is not evidence prose; it is high-confidence claim survival in the existing extracted corpus.

Recommended next lane:

1. Run corpus discovery/extraction for `sleep_health`, `senolytics`, `aspirin`, `taurine`, `spermidine`, `sauna_heat_therapy`, and `everolimus` using the patched topic packs.
2. Require dry-run floor before full render: at least 10 receipts, 50 high-confidence claims, 10 tensions.
3. Spend full writer/review calls only after that floor is met.
