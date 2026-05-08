# Topic Pack Audit — 2026-05-08

Scope: biomedical retrieval defaults plus narrow TOML-only tuning for tasks 43-46. No Python was changed in this lane. `urolithin_a` and `statins` were intentionally excluded because another lane already owns them.

## Default Pattern

High-performing packs (`caloric_restriction`, `omega3`, `metformin`, `glp1`, `rapamycin`, `creatine`) share the same shape:

- 5-10 topic-specific `corpus_search_queries`
- 4-8 canonical `topic_terms`, including aliases and formulation names
- broad human-aging `scope_terms`: older adults, frailty, function, cognition, cardiometabolic, mortality, inflammation
- standard evidence types: RCT, cohort, observational, meta-analysis, systematic review
- conservative excludes for pediatric/pregnancy/case-report/off-context noise
- explicit `[retrieval.background].allow` so mechanism and field-history papers are retrieved as background, not elevated to direct clinical evidence

The reusable template is now captured in `topic_packs/_biomedical_default.toml`. It is loader-safe but uses a sentinel topic and sentinel alias; it is a copy/reference template, not a synthesis target.

Current caveat: existing basket-audit helpers glob `topic_packs/*.toml`, so they will see this sentinel unless the caller passes an explicit real-topic list or a future Python lane adds an underscore-file skip rule. This lane did not edit Python by instruction.

## Patched Packs

| Topic | Gap Found | TOML Patch | Expected Effect |
|---|---|---|---|
| `senolytics` | Good base pack, but terms under-covered senescence-biomarker vocabulary and hard human species filter worked against the pack's declared preclinical/mechanistic evidence slots. | Added senescent-cell/SASP/p16INK4a vocabulary, three clinical/safety queries, broader tissue/function/safety scope, two background mechanisms, removed hard `species = ["humans"]`. | Higher recall for D+Q/fisetin/navitoclax human studies plus background mechanism without topic-specific Python. |
| `spermidine` | Too few synonyms; dietary spermidine and wheat-germ exposure literature likely missed. Hard human filter narrowed mechanism background. | Added dietary/wheat-germ/polyamine aliases, three queries, memory/inflammation scopes, background biology, removed hard species filter. | Better mix of supplement trials, dietary cohorts, and mechanistic autophagy background. |
| `nad_precursors` | Stronger than most under-tuned packs, but missed full NAD-name vocabulary and mitochondrial/function outcomes. Hard human filter blocked mechanism background. | Added nicotinamide adenine dinucleotide term, three function/mechanism/inflammation queries, mitochondrial and inflammation scopes, two background mechanisms, removed hard species filter. | Better NR/NMN/NAD coverage and stronger mechanism pool for D1 bridge context without opening the floodgate to legacy niacin lipid-therapy papers. |
| `taurine` | Too narrow for the recent taurine-aging literature; deficiency/abundance and blood-pressure/mortality vocabulary under-covered. | Added taurine deficiency/abundance terms, three queries, blood-pressure/mitochondrial scopes, two background mechanisms, removed hard species filter. | Better recovery of supplementation, cohort, and preclinical lifespan signals. |
| `collagen_peptides` | Clinically relevant terms like bioactive/specific collagen peptides and resistance-training co-interventions were missing. | Added bioactive/specific collagen aliases, four skin/bone/osteoarthritis/resistance-training queries, broader scope, two background mechanisms. | Better human RCT recall across skin, joint, bone, and muscle-function outcomes. |
| `vitamin_d` | Human evidence base is large, but named large-trial/query vocabulary was under-specified. | Added vitamin D3, VITAL/DO-HEALTH/D-Health, muscle, infection, cancer, bone-density scopes and queries. | Higher chance of retrieving landmark trial/meta-analysis corpus rather than generic low-value supplementation papers. |
| `berberine` | Mostly cardiometabolic, but dyslipidemia/insulin-resistance/inflammation vocabulary was narrow. | Added supplementation alias, four dyslipidemia/metabolic/inflammation queries, broader scope, PCSK9/inflammation background. | Better human metabolic trial/meta-analysis recall while preserving traditional-formula exclusion. |
| `acarbose` | Missed alpha-glucosidase plural, STOP-NIDDM, diabetes-prevention, and ITP/preclinical lifespan context. | Added plural alias, four queries, date floor 1990, diabetes-prevention/postprandial scopes, background ITP/microbiome terms, removed hard species filter. | Better recovery of older foundational human diabetes-prevention/CV papers and lifespan-mechanism background. |
| `sleep_health` | Topic was broad but missed sleep apnea/CPAP, actigraphy, sleep efficiency, and cardiovascular outcome vocabulary. | Added sleep-apnea/OSA/CPAP aliases, five queries, broader topic/scope terms, background physiology. | Better retrieval across sleep duration, insomnia treatment, apnea treatment, cognition, frailty, and mortality. |
| `intermittent_fasting` | Missed early time-restricted feeding/eTRF vocabulary and lean-mass/adherence safety outcomes. Hard human filter narrowed fasting-biology background. | Added eTRF/time-restricted feeding aliases, four queries, lean-mass/adherence/inflammation/circadian scopes, two background mechanisms, removed hard species filter. | Better human TRE/ADF/periodic-fasting retrieval plus background physiology without conflating with caloric restriction. |

## Packs Reviewed But Not Patched

| Topic | Reason |
|---|---|
| `caloric_restriction` | High-performing reference pack; no change. |
| `omega3` | High-performing reference pack; no change. |
| `metformin` | High-performing reference pack; no change. |
| `glp1` | High-performing reference pack; no change. |
| `rapamycin` | High-performing reference pack; no change. |
| `creatine` | High-performing reference pack; no change. |
| `urolithin_a` | Excluded by instruction; already owned by another active lane. |
| `statins` | Excluded by instruction; already owned by another active lane. |
| `aspirin`, `everolimus`, `aerobic_exercise`, `protein_nutrition`, `resistance_training`, `sauna_heat_therapy`, `zone2_training` | Already have enough query/scope/background shape for the next synthesis pass; leave until actual funnel data shows a drop-off. |

## No Python Hardcoding

All changes are data-plane only:

- no classifier changes
- no retrieval Python changes
- no topic-specific Python branches
- no special-case paper IDs added
- no changes to `urolithin_a` or `statins`
- no basket-queue skip logic added; `_biomedical_default.toml` must be excluded by caller until loader inheritance exists

The intended future inheritance path is:

1. keep `_biomedical_default.toml` as the reviewable template;
2. when the loader supports inheritance, real packs can opt into it explicitly;
3. until then, packs copy only the relevant defaults and override topic-specific aliases, outcomes, safety constraints, canonical trials, and background allow-list.

## Remaining Human Spot-Checks Before Task 47

- `senolytics`: confirm broader senescence terms do not over-admit oncology-only navitoclax/dasatinib papers.
- `nad_precursors`: check that broader NAD-name vocabulary improves recall without drowning NR/NMN-specific evidence.
- `sleep_health`: check OSA/CPAP evidence is separated from insomnia/sleep-duration claims.
- `intermittent_fasting`: check TRE/eTRF/ADF are not merged without boundary-condition language.
- `acarbose`: check older foundational papers improve corpus richness without making diabetes-treatment-only trials dominate.
- `_biomedical_default.toml`: exclude from Task 47 synthesis queues; it is a template sentinel, not a topic.
