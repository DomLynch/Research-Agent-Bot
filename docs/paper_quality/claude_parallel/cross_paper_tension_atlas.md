# Cross-Paper Tension Atlas — Rapamycin Literature

**Status:** Provisional. The top 10 tensions in the rapamycin-aging literature, with the papers involved, the numeric conflict, the most plausible explanation under current understanding, and the future experiment that would resolve it.
**Generated:** 2026-05-09
**Purpose:** Replace the AAA4 paper's matrix-first cross-paper synthesis with a narratively-driven top-10 tension list (per gap-analysis Section 8) that the paper can reproduce in its Discussion. Each tension is internally consistent — same intervention, different conclusions — making it a load-bearing question rather than a methodological artefact.

---

## How to read this atlas

Each tension is structured as:

1. **Tension name** — short label.
2. **Papers involved** — the two or more studies that produce the conflict.
3. **The numeric conflict** — quantitative or directional disagreement.
4. **Plausible explanation** — the most parsimonious mechanism that resolves the tension under current evidence.
5. **What future experiment resolves it** — concrete trial design that would settle the question.

The 10 tensions are ordered by *severity for the paper's narrative*: the first three are load-bearing for the AAA4 corpus; the remaining seven require corpus expansion to be addressable.

The Endpoint-Sensitivity framework (per `novel_framework_candidates.md` Framework 3) is invoked where it offers the most parsimonious explanation.

---

## Tension 1 — PEARL null on BMI vs RAPA-EX-01 mixed on HbA1c

**Papers involved.**
- Moel 2025 (PEARL): n ≈ 80, weekly sirolimus 5 mg, 12 months, primary endpoint BMI; result null.
- Stanfield 2026 (RAPA-EX-01): older adults, weekly sirolimus + structured exercise, multiple HbA1c results with bidirectional p-values (p < 0.001, p = 0.025, p = 0.012, p = 0.036, p = 0.030).

**Numeric conflict.** PEARL: 35.1% of placebo-arm participants showed no change in BMI; treatment-arm not reported in synthesis. RAPA-EX-01: HbA1c moved in both directions in the placebo arm with multiple significant p-values; treatment-arm direction not unified.

**Plausible explanation.**
Under the Endpoint-Sensitivity framework: BMI is the lowest-SNR endpoint in the cardiometabolic family (very distal from mTOR substrate); HbA1c is intermediate-SNR. The exercise co-intervention in RAPA-EX-01 perturbs the metabolic baseline and unmasks otherwise-undetectable HbA1c effects, producing the bidirectional pattern. PEARL's null is *predicted* by the framework (wrong endpoint at the wrong distance for a 12-month trial); RAPA-EX-01's mixed signal is *predicted* under the dose-regime + co-intervention interaction.

Alternative explanations:
- Population difference (PEARL: general adults; RAPA-EX-01: older adults specifically).
- Multiple-comparisons artefact in RAPA-EX-01 (per `rob2_manual_pilot.md` Domain 5).
- Co-intervention confounding in RAPA-EX-01 (exercise is itself glycemic).

**Resolving experiment.** Three-arm RCT: (a) sirolimus 5 mg weekly + structured exercise, (b) sirolimus 5 mg weekly + sham exercise (e.g., flexibility-only), (c) placebo + structured exercise. Primary endpoint: HbA1c at 6 and 12 months with pre-registered analysis plan. Sample size ≈ 200 per arm to detect a clinically meaningful HbA1c difference (≥0.3% absolute) at α = 0.05, β = 0.2. The three-arm design isolates the rapamycin effect from the exercise effect.

---

## Tension 2 — Mechanistic engagement (Kell 2026) vs clinical endpoint absence

**Papers involved.**
- Kell 2026: observational cohort, mTOR signaling reduction at five weeks, DNA-damage resilience improvement; B2 evidence tier.
- Moel 2025 (PEARL): null on cardiometabolic clinical endpoints.
- Stanfield 2026 (RAPA-EX-01): mixed on cardiometabolic clinical endpoints.

**Numeric conflict.** Kell: short-duration mechanistic engagement is detected with cohort sizes likely in the 20–50 range. PEARL/RAPA-EX-01: clinical-endpoint signals null/mixed despite n ≈ 80 and 12 months.

**Plausible explanation.**
Under the Endpoint-Sensitivity framework: mTOR pathway substrate (PBMC S6K1-T389, autophagy markers, DNA-damage repair) sits closer to the drug action and shows signal in shorter trials with smaller cohorts. Cardiometabolic clinical endpoints sit further downstream and require larger cohorts and longer durations. The "mechanistic-clinical translation gap" is structurally predicted, not anomalous.

Alternative explanations:
- Kell 2026 confounded by indication (per `rob2_manual_pilot.md` ROBINS-I assessment).
- Cardiometabolic endpoints are simply not the right endpoints for rapamycin.

**Resolving experiment.** Single-cohort RCT with hierarchical endpoint hierarchy: enroll 200 adults aged 65+, weekly sirolimus 5 mg vs placebo, 12 months. Measure all of: PBMC mTOR substrate (proximal); immune function composite (intermediate); cardiometabolic composite (distal); functional composite (distal). Framework predicts effect sizes proximal > intermediate > distal at 12 months. A composite endpoint with pre-specified hierarchy directly tests the framework.

---

## Tension 3 — Preclinical robustness (Harrison 2009) vs human translation gap

**Papers involved.**
- Harrison 2009: heterogeneous-stock mice, ITP, three sites, ~14% male / ~9% female lifespan extension, encapsulated rapamycin.
- All current human RCTs in the corpus: null / mixed on cardiometabolic; mechanistic only on immune.

**Numeric conflict.** Mouse: median lifespan extension of 14% in males, statistically robust across three independent sites and across multiple ITP cohorts (Miller 2014, Strong 2020 if in corpus). Human: zero RCT signal on lifespan-relevant clinical endpoints at conventional cohort sizes and durations.

**Plausible explanation.**
Three non-mutually-exclusive hypotheses:
1. **Endpoint mismatch.** Lifespan in mice integrates across all aging hallmarks; humans cannot be tested on lifespan at conventional trial scales. Human trials test surrogate endpoints that may not capture the integrated benefit.
2. **Dose mismatch.** Mice received continuous encapsulated rapamycin; humans receive intermittent weekly oral. The cumulative AUC and mTORC2 disruption profile differ between the two regimens.
3. **Species mismatch.** Mouse mTOR signaling differs from human mTOR signaling in tissue distribution, FKBP12 stoichiometry, and downstream pathway architecture.

The Endpoint-Sensitivity framework treats hypothesis 1 as primary; the dose-regime framework (per Mannick & Lamming 2023) treats hypothesis 2 as primary; hypothesis 3 is the reserve explanation.

**Resolving experiment.** This is the field's grand challenge. The closest tractable resolution is a 5-year multi-domain RCT in humans with composite healthspan endpoints validated against 10-year mortality. Sample size ≥ 1,000; cost is high; institutional sponsorship required (NIH, Wellcome Trust, philanthropic). Kennedy's TAME-style trial design (originally for metformin) is the template.

---

## Tension 4 — Mannick 2018 PIE positive vs Mannick 2021 PROTECTOR negative (RTI rate)

**Papers involved (corpus expansion required).**
- Mannick 2018 / PIE: RTB101 + everolimus, n ≈ 264, 16 weeks, primary endpoint RTI rate; positive.
- Mannick 2021 / PROTECTOR: RTB101 phase 3, much larger n, primary endpoint RTI rate; negative.

**Numeric conflict.** PIE: RTI rate reduction with statistical significance. PROTECTOR: no statistical reduction in RTI rate at scale. resTORbio's subsequent corporate wind-down is consistent with the field reading the negative phase 3 as definitive.

**Plausible explanation.**
Three non-mutually-exclusive hypotheses:
1. **Phase-2 type-I error.** The PIE positive result was a true-positive subgroup or a chance positive at n ≈ 264; phase 3 corrected it.
2. **Population shift.** Phase 3 enrolled a different population (perhaps younger, healthier, or with different baseline RTI risk) in which the effect did not transfer.
3. **Compound shift.** RTB101 dose, schedule, or formulation differed between PIE and PROTECTOR in ways that altered the effect.

The field's reading is hypothesis 1: phase-2 type-I error, replicated null at scale.

**Resolving experiment.** The replication failure has effectively been definitive; further trials with RTB101 are unlikely. The relevant follow-on is: does the effect transfer to other rapalogs (sirolimus, everolimus)? An n ≈ 1,000 sirolimus + influenza vaccination trial in older adults with RTI rate as primary would be the next test of the framework. Mannick's group is one of the few likely to run this.

---

## Tension 5 — Sex asymmetry in mouse lifespan (Harrison 2009) vs unstratified human trials

**Papers involved.**
- Harrison 2009: 14% male / 9% female median lifespan extension.
- Selman 2009 (corpus expansion required): S6K1 KO produces *female-specific* lifespan extension, opposite directionality of Harrison.
- All human rapamycin RCTs: do not stratify by sex in primary analyses.

**Numeric conflict.** Mouse pharmacological intervention (rapamycin): male > female effect. Mouse genetic intervention (S6K1 KO): female > male effect. Human pharmacological intervention: sex-blind.

**Plausible explanation.**
The pharmacological vs genetic asymmetry suggests that rapamycin and S6K1 KO operate via partially-overlapping but non-identical pathways. Rapamycin inhibits mTORC1 broadly (including 4E-BP1, ribosomal biogenesis, lipid metabolism); S6K1 KO removes one downstream substrate. The sex-specific effects of each may be driven by sex differences in compensatory pathway engagement, in FKBP12/FKBP51 stoichiometry, or in androgen/estrogen signaling interactions with mTORC1.

In humans, this predicts:
- Sex-stratified rapamycin effects exist but the direction is unknown.
- Pre-specified sex stratification is essential in any human rapamycin trial; pooled analyses risk averaging two opposing-direction subgroups to a near-null aggregate.

**Resolving experiment.** Add pre-specified sex stratification to all rapamycin geroprotective trials. The minimum analysis is a primary-endpoint × sex interaction term with 80% power to detect a 50% sex-difference in effect. Sample size implications: typically requires doubling trial cohort vs sex-blind primary analysis.

---

## Tension 6 — Mid-life transient dosing (Bitto 2016) larger effect than chronic late-life dosing

**Papers involved (corpus expansion required).**
- Bitto 2016: 3-month transient rapamycin in 20-month-old mice, ~60% female median lifespan extension, ~35% male.
- Harrison 2009: continuous lifelong rapamycin from 9 months in heterogeneous-stock mice, ~14% / ~9% extension.

**Numeric conflict.** Transient mid-life intervention produces *larger* effect than continuous lifelong intervention. This is counterintuitive under naïve "more drug = more benefit" reasoning.

**Plausible explanation.**
1. **Adaptation / compensatory pathway engagement.** Continuous rapamycin triggers compensatory pathway upregulation (autophagy chronic, feedback loop activation) that offsets benefit; transient dosing avoids the compensation.
2. **Mid-life timing.** mTOR hyperactivity in mid-life mice is at a tractable point in the aging trajectory; intervention earlier may be too early (no benefit available yet) and later may be too late (damage accumulated).
3. **mTORC2 sparing.** Transient dosing limits cumulative mTORC2 disruption (per Lamming 2012); chronic dosing accumulates mTORC2 damage that offsets mTORC1 benefit.

**Resolving experiment.** Mouse-level: dose-timing factorial trial with three intervention onsets (early-life, mid-life, late-life) and three durations (transient, intermittent, chronic). Lifespan as primary. This has not been published as a single integrated study; conducting it would resolve the timing-vs-duration question directly.

For humans: the timing question is intractable at conventional trial durations. The relevant translation question is whether intermittent dosing in older adults captures the Bitto 2016 advantage; the existing Mannick 2014/2018 protocols already test this implicitly.

---

## Tension 7 — RTB101 (mTORC1-selective) vs sirolimus (rapamycin) — different selectivity, mixed outcomes

**Papers involved (corpus expansion required).**
- RTB101 trials (Mannick 2018, 2021): mTORC1-selective compound, mixed clinical outcomes.
- Sirolimus trials (Stanfield 2026, observational cohorts): non-selective rapamycin/mTORC1 inhibitor with chronic mTORC2 disruption potential.

**Numeric conflict.** mTORC1-selective compound was hypothesised to deliver geroprotective benefit *without* the metabolic costs of mTORC2 disruption. The PIE-vs-PROTECTOR replication failure undermines this hypothesis.

**Plausible explanation.**
Two hypotheses:
1. **The hypothesis was wrong.** Geroprotective benefit may require *some* mTORC2 engagement that mTORC1-selectivity removes.
2. **The compound was not as selective as claimed.** Real-world tissue distribution and metabolism of RTB101 may not match in vitro selectivity.
3. **The benefit hypothesis was right but the trial design was wrong.** The phase 3 endpoint (RTI rate) may not have been the right test of mTORC1-selective geroprotection.

**Resolving experiment.** Pharmacodynamic head-to-head: compare RTB101 vs sirolimus at matched mTORC1 substrate inhibition (S6K1-T389 phosphorylation) and measure mTORC2 substrate (Akt-S473) plus a clinical endpoint (vaccine response, infection rate). If mTORC1-selective produces equivalent clinical benefit with reduced mTORC2 disruption, hypothesis 1 is false; if both produce equivalent benefit, hypothesis 1 is open.

---

## Tension 8 — Companion dog data (DAP/Urfer 2017) vs human RCT data

**Papers involved (corpus expansion required).**
- Urfer 2017: short-term rapamycin in 24 middle-aged companion dogs with cardiac function and safety endpoints.
- Creevy 2022: DAP cohort design.
- Human RCTs (Moel, Stanfield, Mannick): mixed cardiometabolic, mixed immune.

**Numeric conflict.** Dogs (preliminary): rapamycin short-term safe, with reported cardiac function effects. Humans: no consistent functional endpoint signal.

**Plausible explanation.**
1. **Endpoint sensitivity.** Companion dogs are measured on owner-reported function, which is a different sensitivity profile than human cardiometabolic biomarkers.
2. **Population.** Middle-aged dogs are at a different aging trajectory point than older human adults.
3. **Translation gap.** Dog → human translation is itself a translation step that may attenuate effect.

**Resolving experiment.** The DAP cohort, by 2030, will have multi-year functional and lifespan data on companion dogs receiving long-term rapamycin. This is the cleanest non-human-RCT evidence base the field will produce in this decade. Patience is the resolution; the trial is already running.

---

## Tension 9 — Continuous transplant dosing (Kahan 2000) vs intermittent geroprotective dosing (Mannick 2014)

**Papers involved.**
- Kahan 2000: transplant immunosuppression, continuous high-trough sirolimus (5–15 ng/mL).
- Mannick 2014 / 2018: intermittent low-dose everolimus / RTB101 in older adults for vaccine response or RTI.

**Numeric conflict.** Continuous high-trough dosing produces well-documented metabolic toxicity (hyperglycemia, dyslipidemia, mucositis, mouth ulcers). Intermittent low-dose dosing produces minimal metabolic toxicity in geroscience trials. Same drug, opposite metabolic profile.

**Plausible explanation.**
This is the canonical Lamming framework prediction (Lamming 2012; Mannick & Lamming 2023): mTORC1-mediated benefit accumulates linearly with cumulative AUC; mTORC2-mediated toxicity emerges non-linearly past a cumulative-exposure threshold. Intermittent low-dose dosing stays below the threshold; continuous high-dose dosing exceeds it.

**Resolving experiment.** Pharmacodynamic dose-finding study in humans: titrate intermittent dose upward while monitoring mTORC1 substrate (S6K1-T389) and mTORC2 substrate (Akt-S473) phosphorylation. The threshold dose at which mTORC2 disruption emerges is the upper bound of geroprotective dosing. Sample size ≈ 30 per dose; total cohort ≈ 150.

---

## Tension 10 — Cancer-prevention pathway vs aging-deceleration pathway

**Papers involved (corpus expansion required).**
- Komarova 2012: rapamycin extends lifespan in p53+/- (cancer-prone) mice.
- Harrison 2009: rapamycin extends lifespan in heterogeneous-stock mice (mostly non-cancer-prone).
- Wilkinson 2012 (verify): rapamycin slows multiple aging phenotypes in mice including cancer incidence.

**Numeric conflict.** Same effect (lifespan extension), different proximate cause: cancer prevention in cancer-prone mice (Komarova) vs aging deceleration in heterogeneous mice (Harrison). The same drug at the same dose has different mechanism of action by population.

**Plausible explanation.**
Rapamycin operates through multiple aging hallmarks simultaneously. In cancer-prone mice, its anti-tumour effect dominates the lifespan signal. In heterogeneous mice, its broader aging-deceleration effect dominates. The two effects are not in conflict; they are complementary.

For humans, the implication is that rapamycin's translation case may differ in cancer-elevated populations (e.g., Lynch syndrome, BRCA carriers, post-cancer-treatment) versus general older adults. Currently no human rapamycin RCT in cancer-elevated populations exists.

**Resolving experiment.** Population-stratified RCT: rapamycin vs placebo in cancer-prone subpopulation (e.g., Lynch syndrome carriers) with cancer-incidence and cancer-recurrence endpoints. This is a well-defined trial that would isolate the cancer-prevention pathway from the broader aging-deceleration pathway.

---

## Cross-tension synthesis

The 10 tensions cluster into four meta-categories:

| Meta-category | Tensions | What they share |
|---|---|---|
| **Endpoint-distance** | 1, 2, 3 | The endpoint chosen determines whether signal is detected; the Endpoint-Sensitivity framework predicts the pattern. |
| **Replication-and-scale** | 4 | Phase 2 positive does not predict phase 3 positive; n matters more than direction. |
| **Population-and-timing** | 5, 6, 8, 10 | Sex, age, baseline frailty, cancer-proneness, and timing of intervention all modify effect. |
| **Dose-regime** | 7, 9 | Intermittent vs chronic, mTORC1-selective vs non-selective, low vs high dose all modify the benefit-toxicity profile. |

The paper's narrative should structure the Discussion around these four meta-categories rather than the matrix of all 10 individual tensions. This is the gap-analysis Section 8 recommendation: "the public paper needs the top 4-5 clinically meaningful tensions narrated with dose, population, endpoint, and follow-up context."

---

## Drop-in section header for the paper

```markdown
## Cross-Paper Tensions

The rapamycin literature contains a series of internally consistent
disagreements — same intervention, different conclusions — that the
field has not yet resolved. We summarise the four meta-categories of
tension that structure the current evidence; the full ten-tension
atlas is provided in Supplementary Table S2.

### Endpoint-distance tensions
[Tensions 1, 2, 3 narrated together; ~400-500 words]

### Replication-at-scale tensions
[Tension 4 narrated with PIE-PROTECTOR detail; ~200-300 words]

### Population-and-timing tensions
[Tensions 5, 6, 8, 10 narrated together; ~400-500 words]

### Dose-regime tensions
[Tensions 7, 9 narrated together; ~200-300 words]

These four meta-categories yield a single design implication: the next
generation of rapamycin trials should pre-specify endpoint-hierarchy,
sex stratification, dose-regime arm separation, and population
enrichment. Trials that conflate these axes will continue to produce
ambiguous results.
```

---

## What this atlas refuses to claim

- That all 10 tensions are equally important. They are not; the meta-categorisation above ranks them. The paper should narrate the meta-categories, not all 10.
- That the plausible explanations I have given are the only valid ones. They are the most parsimonious under current evidence; alternative explanations exist for each.
- That the resolving experiments are the only valid future experiments. They are the most direct tests of the resolving hypotheses; other designs exist.

---

## Falsifying conditions

This atlas is wrong if:

1. **Any of the tensions are not actually disagreements** — e.g., if PIE 2018 and PROTECTOR 2021 used materially different primary endpoints or populations, the tension is not a replication failure but a different question. Mitigation: source-text verification of each cited paper's primary endpoint and population.
2. **My most-parsimonious explanations have been superseded by recent field consensus.** If, for example, Mannick & Lamming 2023 has converged on a specific resolving hypothesis for the cardiometabolic-immune divergence, the atlas's plausible explanations are wrong. Mitigation: cross-check against the field's most-recent senior reviews.
3. **The Endpoint-Sensitivity framework is wrong.** Several tensions invoke it as the most parsimonious explanation. If the framework is falsified by future evidence (per `novel_framework_candidates.md` Framework 3), several tension explanations need updating.

---

**Provisional flag:** All tension narratives are conditional on the AAA4 corpus + post-rescue 34-receipt expansion + verification of the Tier-1 papers per `missing_literature_audit.md`. Tensions 4–10 require corpus expansion to be addressable in the rendered paper.
