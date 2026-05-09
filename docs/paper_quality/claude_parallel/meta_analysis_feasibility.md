# Meta-Analysis Feasibility Audit — Rapamycin Outcomes

**Status:** Provisional. Anchored on the AAA4 (3-receipt) corpus and the post-rescue 34-receipt corpus; effect-size pooling is currently NOT performed and the AAA4 paper correctly notes this.
**Generated:** 2026-05-09
**Purpose:** Identify which outcomes are plausibly poolable, which are not poolable and why, and what source-text fields the extraction pipeline must capture before any meta-analysis can run. This is the comparable-effect audit the gap-analysis doc (`docs/paper_quality/rapamycin_gap_analysis.md`) calls for.

---

## Why this audit matters

The AAA4 paper takes a defensible posture: "the paper correctly avoids pooling, but it needs a comparable-effect audit explaining which outcome families are not poolable and why" (gap analysis, Section 6). A 2026 rapamycin review *without* a comparable-effect audit reads as either methodologically naïve or strategically silent. This audit makes the non-pooling decision explicit and defensible.

The audit also identifies the small set of outcomes that *are* plausibly poolable, so future renders can incorporate selective meta-analysis where genuinely comparable effects exist.

---

## Pooling preconditions

For two or more studies to be poolable in a meta-analysis, the following must hold:

1. **Same outcome** at the same level of specificity (e.g., HbA1c percentage points, not "glycemic control").
2. **Same comparator** (placebo vs placebo across studies; not "placebo or no intervention").
3. **Comparable population** at the relevant level (older adults, defined consistently; not "older adults" mixed with "transplant patients").
4. **Same effect metric** (mean difference for continuous; risk ratio or odds ratio for binary; hazard ratio for time-to-event).
5. **Effect estimate with measurement of uncertainty** — point estimate plus 95% CI, or SE, or SD per arm with n per arm.
6. **Comparable timepoint** — endpoint measured at similar follow-up duration.
7. **Comparable intervention parameters** — dose, route, regimen sufficiently similar that pooling does not average across mechanistically different treatments.

Failure on any one precondition forces the studies into a non-poolable bucket; the analysis must then narratively synthesise rather than mathematically combine.

---

## Outcome-by-outcome feasibility assessment

### Pool candidate 1 — Influenza vaccine antibody titer (immune outcome)

**Status:** **Plausibly poolable** if Mannick 2014 + Mannick 2018 (PIE) + any 2019–2026 follow-on enter the corpus.

**Studies likely to qualify:**
- Mannick 2014 (everolimus + influenza vaccine, n ≈ 218): titer log fold change at 6 weeks post-vaccination.
- Mannick 2018 / PIE (RTB101 ± everolimus, n ≈ 264): vaccine response as secondary; primary endpoint was infection rate.

**Same outcome?** Yes if studies report the same primary readout (typically log titer fold change for H1N1, H3N2, B/Yamagata strains). Strain-specific titer is the norm.

**Same comparator?** Yes (placebo).

**Comparable population?** Yes (older adults, generally ≥65, generally living in community).

**Same effect metric?** Yes if extracted as standardised mean difference (SMD) on log titer.

**Required fields:**
- Mean log-titer fold change per arm per strain.
- SD or SE per arm per strain.
- n per arm.
- Time post-vaccination (typically 6 weeks).

**Pooling caveat:** Different rapalogs (everolimus, RTB101, sirolimus) have different mTORC1/mTORC2 selectivity profiles. Subgroup analysis by rapalog is methodologically necessary. A simple fixed-effect pool across rapalogs would be misleading.

**Pre-specified analysis plan:** Random-effects meta-analysis with rapalog as a moderator; SMD on log titer; 3 strains analysed separately or as composite.

**Recommendation:** Add to corpus, extract effect estimates with CIs, produce a forest plot for vaccine response stratified by rapalog. This is the highest-value pooling target.

---

### Pool candidate 2 — Respiratory tract infection rate (immune outcome)

**Status:** **Plausibly poolable, but with a load-bearing inconsistency** between PIE (Mannick 2018) and PROTECTOR (Mannick 2021 phase 3).

**Studies likely to qualify:**
- Mannick 2018 / PIE: positive on RTI rate.
- Mannick 2021 / PROTECTOR: negative on RTI rate (much larger trial).
- Any subsequent follow-on RTI trial.

**Same outcome?** Yes (RTI events per person per follow-up period, typically 16–52 weeks).

**Same comparator?** Yes.

**Comparable population?** Yes (older adults).

**Same effect metric?** Risk ratio or rate ratio.

**Required fields:** Event count per arm; person-time per arm; n per arm.

**Pooling caveat:** The PIE-vs-PROTECTOR replication failure is itself the most important finding in the field. A simple pool would average a positive phase 2 and a negative phase 3 to a non-significant intermediate effect, which would mislead readers. The methodologically correct posture is: report both individual results, narratively synthesise the discordance, and flag the meta-analysis as either inappropriate or to be performed with phase 2 / phase 3 subgrouping.

**Recommendation:** Do not pool naïvely. Instead, present both results in a forest plot with explicit phase-2-vs-phase-3 subgrouping; treat the absence of a pooled estimate as itself a finding.

---

### Pool candidate 3 — HbA1c change (cardiometabolic outcome)

**Status:** **Marginal — likely non-poolable** at current corpus.

**Studies in corpus:**
- Stanfield 2026 / RAPA-EX-01: weekly sirolimus + exercise vs placebo + exercise; HbA1c at 12 weeks (verify duration); bidirectional p-values.

**Studies needed for pooling:** ≥1 additional RCT measuring HbA1c with placebo comparator; PEARL (Moel 2025) is unlikely to qualify because BMI was the primary endpoint.

**Same outcome?** Yes if reported as HbA1c change (% or mmol/mol, convertible).

**Same comparator?** Stanfield 2026 has placebo + exercise; a hypothetical second trial with placebo only would be a different comparator. Pooling across "placebo with exercise co-intervention" and "placebo without exercise" would create comparator heterogeneity.

**Comparable population?** Older adults broadly comparable.

**Required fields:**
- Mean HbA1c change per arm.
- SD or SE per arm per timepoint.
- n per arm at each timepoint.
- Co-intervention status (with / without exercise).

**Pooling caveat:** Stanfield 2026's bidirectional results within a single trial preclude a clean point estimate even before pooling. The trial would need to be re-extracted with explicit subgroup-level effect estimates rather than overall p-values.

**Recommendation:** Defer pooling. Until at least one other rapamycin-vs-placebo HbA1c RCT enters the corpus, narrative synthesis is the correct posture.

---

### Pool candidate 4 — BMI change (cardiometabolic outcome)

**Status:** **Non-poolable** at current corpus.

**Studies in corpus:**
- Moel 2025 / PEARL: BMI null at 12 months, n ≈ 80.

**Studies needed:** ≥1 additional rapamycin RCT with BMI as a measured endpoint.

**Required fields:** Mean BMI change per arm + SD + n + duration.

**Pooling caveat:** Even with one additional study, BMI is the lowest-SNR endpoint per Framework 3 in `novel_framework_candidates.md`; pooling two underpowered null results adds little.

**Recommendation:** Do not pool. Note as "single study; very low certainty" per GRADE OG-3 BMI subgroup.

---

### Pool candidate 5 — Mouse lifespan extension (preclinical outcome)

**Status:** **Plausibly poolable across ITP sites and across non-ITP replications.**

**Studies likely to qualify:**
- Harrison 2009 (ITP, three sites: Jackson, UTHSCSA, U-Michigan, encapsulated rapamycin in feed).
- Miller 2014 (dose-response in heterogeneous-stock mice).
- Strong 2020 (encapsulated rapamycin formulation).
- Anisimov 2011 (independent replication, non-heterogeneous strain).
- Komarova 2012 (cancer-prone mice).
- Bitto 2016 (transient mid-life dosing).

**Same outcome?** Yes (median lifespan; 90th percentile lifespan; maximum lifespan).

**Same comparator?** Yes (control feed or vehicle).

**Comparable population?** Mice — but strain matters. ITP heterogeneous stock vs Anisimov 129/Sv vs Komarova p53+/- are genuinely different populations.

**Same effect metric?** Hazard ratio (Cox PH) or median ratio (lifespan).

**Required fields:**
- Median lifespan (or hazard ratio) per arm with 95% CI.
- Sample size per arm.
- Strain.
- Dose (continuous; encapsulated; mg/kg or ppm).
- Age at start.
- Duration of dosing.

**Pooling caveat:** Strain heterogeneity is meaningful — pooling across heterogeneous-stock + 129/Sv + p53+/- requires random-effects with strain as moderator. Sex stratification is also non-optional given the Harrison 2009 14% male / 9% female asymmetry.

**Pre-specified analysis plan:** Random-effects meta-analysis of lifespan hazard ratios with strain and sex as moderators; ITP vs non-ITP subgroup; encapsulated vs non-encapsulated subgroup.

**Recommendation:** Add the relevant preclinical receipts (per `missing_literature_audit.md` Tier 1–2) and produce a preclinical forest plot for the supplement. The preclinical case can be quantitatively pooled in a way the human case cannot.

---

### Pool candidate 6 — mTOR pathway substrate inhibition (mechanistic outcome)

**Status:** **Likely non-poolable** due to assay heterogeneity.

**Studies likely to qualify:**
- Kell 2026 (PBMC mTOR signaling reduction, observational).
- Mannick 2014 / 2018 secondary endpoints (PBMC mTOR substrate phosphorylation, if reported).
- Possibly transplant-medicine literature (irrelevant population for geroprotection).

**Required fields:** S6K1-T389 phosphorylation fold change (or equivalent); 4E-BP1 phosphorylation; assay platform.

**Pooling caveat:** Different studies use different antibodies, different cell types (PBMC vs adipose vs muscle), different units (raw band intensity, ratio to total protein, fold change relative to baseline). Mechanical heterogeneity of assays precludes pooling without harmonisation.

**Recommendation:** Do not pool. Narrative synthesis with attention to assay heterogeneity is correct.

---

### Pool candidate 7 — Adverse event rates (safety outcome)

**Status:** **Plausibly poolable for common AEs, non-poolable for rare AEs.**

**Studies that report AEs:** All RCTs typically report a tabulated AE list per arm.

**Required fields:**
- Event count per arm per AE category.
- Person-time per arm.
- Standardised AE category (MedDRA preferred terms).

**Pooling caveat:** Many trials report AEs only descriptively; standardised MedDRA mapping is non-trivial. Mucositis, mouth ulcers, mild hyperglycemia are commonly reported and plausibly poolable across rapalog trials.

**Recommendation:** Pool common dose-limiting AEs (mucositis, hyperglycemia) across rapalog trials with rapalog as moderator. Useful for safety summary in the paper.

---

## Outcomes confirmed non-poolable

| Outcome | Reason |
|---|---|
| "Cardiometabolic" composite | Composite is too heterogeneous; pool individual sub-endpoints only. |
| Mechanistic biomarkers (mTOR signaling, DNA-damage markers) | Assay heterogeneity; different cell types; different units. |
| "Healthspan" composite | Composite endpoint definitions differ across trials; pooling averages across non-comparable constructs. |
| Cognitive function (Cohort: post-expansion only) | Different instruments (MoCA, MMSE, DSST, ADAS-Cog) measure overlapping but non-identical constructs. |
| Physical function (Cohort: post-expansion only) | Different instruments (gait speed, grip strength, frailty index) measure different constructs; pool only within instrument family if ≥3 studies. |
| Lifespan (human) | No human RCT data; pooling across observational cohorts requires cohort-specific confounder models. |

---

## Pooling priority for the next paper render

Given the corpus and the field, the prioritised pool list is:

1. **Mouse lifespan (preclinical pool, supplement only).** Highest data quality, lowest pooling risk. Random-effects with strain/sex moderator. Required: 4–5 receipts from `missing_literature_audit.md` Tier 1–2.
2. **Influenza vaccine antibody titer (immune pool, main paper).** High value because it answers Mannick's framework directly. Required: Mannick 2014 + Mannick 2018 PIE secondary + any subsequent receipts.
3. **Common AEs (safety pool, supplement).** Useful for the safety profile section. Required: AE table extraction across all rapalog RCTs in corpus.

The remaining outcomes should be narrative-synthesised with a comparable-effect audit explaining the non-pooling decision per outcome.

---

## Required fields for the extraction pipeline

The bot's `quant_claims` schema needs to extend to capture, per study per outcome:

| Field | Type | Required for pooling? |
|---|---|---|
| effect_estimate | float | Yes |
| effect_estimate_ci_lower | float | Yes |
| effect_estimate_ci_upper | float | Yes |
| effect_estimate_se | float | Alternative to CI |
| effect_metric | enum {MD, SMD, RR, OR, HR, rate ratio} | Yes |
| n_treatment | int | Yes |
| n_control | int | Yes |
| comparator_type | enum {placebo, active, none} | Yes |
| timepoint_value | float | Yes |
| timepoint_unit | enum {weeks, months, years} | Yes |
| outcome_units | string | Yes (for harmonisation) |
| co_interventions | list[string] | Yes (e.g., exercise) |
| population_age_mean | float | Yes |
| population_age_sd | float | Yes |
| dose_value | float | Yes |
| dose_unit | string | Yes |
| dose_regimen | enum {daily, weekly, intermittent, transient} | Yes |

Most current `quant_claims` records have p-values and "direction" tokens but lack the effect estimate + CI. **This is the rate-limiting bottleneck for any meta-analysis.**

---

## Activation plan for meta-analysis tooling

The bot does not currently have meta-analysis code. Adding it:

1. **Schema extension.** Add the 17 fields above to `quant_claims`. (~30 LOC schema; per-paper extraction prompt update.)
2. **Pooling-eligibility classifier.** Per (outcome, study) pair, evaluate the 7 preconditions deterministically. Output: poolable / not poolable + reason. (~120 LOC)
3. **Random-effects meta-analysis runner.** DerSimonian-Laird random-effects estimator; forest plot generation. ~150 LOC plus matplotlib or equivalent.
4. **Heterogeneity reporter.** I², τ², subgroup analysis hooks. (~80 LOC)
5. **Output integration.** Add `full_paper.meta_analysis.json` and `full_paper.forest_plots/` to the bundle. (~50 LOC)

Total scope: ~430 LOC plus matplotlib dependency. Most of the LOC is in the pooling-eligibility classifier; the actual meta-analysis math is mature and short.

**Caution:** Adding meta-analysis tooling is high-blast-radius (per playbook v4 escalation triggers — new dependency, new output type, new audit gate). It should be gated behind a topic-pack opt-in flag (`[meta_analysis] enabled = true`) and behind a per-outcome poolability threshold (≥3 studies after RoB 2; ≥2 with RoB low or some-concerns).

---

## Recommended changes to the AAA4 paper before meta-analysis activation

Even before automated meta-analysis, the paper should:

1. **Add a "Comparable-Effect Audit" subsection** in Methods naming each outcome as poolable / non-poolable / TBD with the reason per outcome (drawn from this audit).
2. **Replace silent non-pooling with explicit reasoning** — currently the paper does not pool and does not say why; the audit should be visible.
3. **Pre-flag the preclinical pool as a future-supplement target** (mouse lifespan is the lowest-risk and highest-value pool).
4. **Add a note to Limitations** that the corpus does not currently support primary meta-analysis of human outcomes, with reasoning.

These changes make the non-pooling decision *defensible* rather than *missing*, which is the senior-reviewer expectation.

---

## What this audit refuses to claim

- That meta-analysis should be performed on the current corpus. It cannot be, except possibly for mouse lifespan if the corpus expands.
- That the pooling preconditions I have applied are the only valid ones. Different methodological schools (Cochrane vs Joanna Briggs vs informal "vote-counting") apply different thresholds; this audit uses Cochrane standards.
- That the post-expansion 34-receipt corpus will automatically yield poolable outcomes. The Tier-1 papers in `missing_literature_audit.md` must include effect estimates with CIs in their reported results; if they report only p-values, pooling remains blocked.

---

## Falsifying conditions

This audit is wrong if:

1. **The corpus already contains effect estimates with CIs** that I have missed by reading only the synthesis description. Mitigation: re-run the audit against the source-text extraction once the post-rescue 34-receipt manifest is rendered.
2. **Pre-specified pooling targets in the field have already been published** — e.g., if Lee et al. 2024 already pooled rapamycin vaccine response, this audit would be partially redundant. Mitigation: cross-check Lee 2024's pooling decisions before activating the bot's meta-analysis tooling.
3. **The PIE-vs-PROTECTOR inconsistency I treat as fatal to RTI rate pooling is wrong** — if the field has converged on a pre-specified subgroup explanation that justifies pooling, the audit's recommendation needs to update.

---

**Provisional flag:** All pooling recommendations are conditional on the post-expansion corpus including the relevant Tier-1 papers from `missing_literature_audit.md` and on those papers reporting effect estimates with CIs. Without those preconditions, the comparable-effect audit must remain narrative-only.
