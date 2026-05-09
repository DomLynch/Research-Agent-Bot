# GRADE Manual Pilot — Rapamycin Outcome Groups

**Status:** Provisional. Reasoning from the AAA4 paper's synthesis description, public abstracts, and field knowledge — *not* from completed source-text RoB 2 (which is itself a precondition for full GRADE). Use as a template for the source-text GRADE pass.
**Generated:** 2026-05-09
**Tool:** GRADE (Grading of Recommendations, Assessment, Development, and Evaluations) Working Group framework.
**Purpose:** Apply outcome-level certainty assessment to the rapamycin evidence base; identify which outcomes can credibly carry "high"/"moderate"/"low"/"very low" certainty labels in the next paper render; enumerate the data needed to upgrade certainty.

---

## Why this pilot matters

The AAA4 paper does not currently apply GRADE. RoB 2 is study-level; GRADE is outcome-level. Both are required for a senior-PhD-grade systematic review. This pilot completes the conceptual pair: RoB 2 (per study; in `rob2_manual_pilot.md`) → GRADE (per outcome; here).

GRADE matters because the paper's load-bearing claims are *outcome-class* claims ("rapamycin's cardiometabolic effects are null/mixed"), not study-level claims. Without GRADE, the certainty attached to each outcome-class claim is undefined, and "null/mixed" is unanchored against an evidence-quality benchmark.

---

## GRADE framework (one-paragraph refresher)

GRADE produces an outcome-level certainty rating: High, Moderate, Low, or Very Low.

**Starting certainty:**
- RCT body of evidence → starts at **High**.
- Observational body of evidence → starts at **Low**.

**Five downgrade factors** (each can drop certainty by 1 or 2 levels):
1. **Risk of bias** — across-study RoB 2 / ROBINS-I summary.
2. **Inconsistency** — heterogeneity of effects across studies (statistical I², overlap of CIs, direction of effect).
3. **Indirectness** — match of population, intervention, comparator, outcome to the question.
4. **Imprecision** — CI width relative to MID (minimal important difference); sample size; event count.
5. **Publication bias** — funnel plot asymmetry; small-study effects; trial-registry-vs-publication discrepancy.

**Three upgrade factors** (only for observational; can lift certainty by 1 level each):
1. Large effect (RR ≥ 2 or ≤ 0.5).
2. Dose-response gradient.
3. Plausible confounding would reduce the observed effect.

**Final certainty** is the bottom-line judgment about whether the evidence is sufficient to inform a clinical recommendation.

---

## Outcome groups for the rapamycin paper

Per the brief, seven outcome groups are relevant. I assess each.

| # | Outcome group | Currently in corpus? | Receipts available |
|---|---|---|---|
| OG-1 | Lifespan / mortality | No human data | Harrison 2009 (mouse) |
| OG-2 | Immune function | Partial — observational only | Kell 2026; +Mannick 2014/2018 if corpus expanded |
| OG-3 | Cardiometabolic | Yes | Moel 2025, Stanfield 2026, Kell 2026 |
| OG-4 | Cognition / ADRD | No data | Corpus expansion required |
| OG-5 | Physical function | No data | Corpus expansion required |
| OG-6 | Skin aging / senescence | No data | Corpus expansion required |
| OG-7 | Adverse effects | Partial — within-trial only | All RCTs report safety; not a primary endpoint |

---

## Per-outcome GRADE pilot

### OG-1. Lifespan / mortality

**Question:** Does rapamycin extend lifespan or reduce all-cause mortality in humans?

**Body of evidence in current corpus:** Zero direct human evidence. Indirect inference from Harrison 2009 (mouse, ITP, ~14% male, ~9% female lifespan extension) and from observational geroscience cohorts.

**Starting certainty (for human outcome):** Indirect; treat as observational + indirect. Start at Very Low.

#### Downgrade assessment (for the human outcome based on mouse data):

| Domain | Downgrade | Reasoning |
|---|---|---|
| Risk of bias | -0 | Harrison 2009 is methodologically strong (ITP design); SYRCLE rollup is Low–Some concerns. |
| Inconsistency | -0 to -1 | The mouse evidence is consistent within ITP and broadly replicable (Anisimov 2011, Komarova 2012 if in corpus); inconsistency is between mouse and (absent) human data. |
| Indirectness | -2 | Mouse → human is the load-bearing indirectness; species, tissue exposure, lifespan interpretation differ fundamentally. |
| Imprecision | -1 | No human data; statistical imprecision is undefined; conceptual imprecision is high. |
| Publication bias | -0 | NIA ITP is structurally protected from publication bias by mandate. |

**Starting at Low for indirect-from-RCT-but-different-species:** -2 indirectness, -1 imprecision, ≈ Very Low.

**Final certainty for the human outcome:** **Very Low.**
- Interpretation: We are *very uncertain* whether rapamycin extends human lifespan. The mouse evidence is robust but does not transfer.
- Trial design implication: To upgrade certainty, a multi-decade RCT in humans with mortality endpoint is required; this is impractical at conventional trial scales.
- Alternative path: Composite healthspan endpoint trials with surrogate endpoints validated against eventual mortality.

#### Cited support and gap

- Harrison 2009 supports the *mouse* claim with high certainty.
- The translation gap is the rate-limiting factor; no current human RCT has lifespan as primary.

---

### OG-2. Immune function

**Question:** Does rapamycin improve immune function (vaccine response, infection rate, or immune cell function) in older adults?

**Body of evidence in current corpus:**
- Kell 2026 (observational, B2): five-week mTOR-signaling reduction; DNA-damage resilience.

**Body of evidence with corpus expansion (per `missing_literature_audit.md`):**
- Mannick 2014 (RCT, A1): everolimus + influenza vaccine response in older adults.
- Mannick 2018 / PIE (RCT, A1): RTB101 + everolimus, respiratory tract infection rate.
- Mannick 2021 / PROTECTOR (RCT, A1): negative phase 3 of RTB101 (verify identifier).

**Starting certainty (with corpus expansion):**
- For mechanistic biomarkers (mTOR signaling, DNA-damage markers): Low (observational + mechanistic indirectness).
- For vaccine response: High (RCT direct).
- For respiratory infection rate: High (RCT direct), but with the PIE-vs-PROTECTOR replication concern.

#### Downgrade assessment for vaccine response (post-corpus-expansion):

| Domain | Downgrade | Reasoning |
|---|---|---|
| Risk of bias | -1 | Industry sponsorship across both Mannick 2014 and Mannick 2018; RoB 2 some concerns on Domain 5 (selective reporting). |
| Inconsistency | -1 | Different rapalogs (everolimus, RTB101, sirolimus) tested across trials; effect-size comparison non-trivial. |
| Indirectness | -0 | Vaccine response is a direct, validated immune-function readout. |
| Imprecision | -0 to -1 | Mannick 2014 n ≈ 218; reasonable precision. |
| Publication bias | -1 | resTORbio company history (PIE positive → PROTECTOR negative → company wound down) raises specific publication-bias concern. |

**Final certainty (with corpus expansion):** **Low to Moderate.**
- Interpretation: There is *some* evidence rapamycin/rapalogs improve vaccine response in older adults, but the certainty is limited by replication failure and industry sponsorship.

#### Downgrade assessment for respiratory infection rate (post-expansion):

| Domain | Downgrade | Reasoning |
|---|---|---|
| Risk of bias | -1 | Same as above. |
| Inconsistency | -2 | PIE 2018 positive; PROTECTOR phase 3 negative. This is the load-bearing inconsistency. |
| Indirectness | -0 | Direct clinical endpoint. |
| Imprecision | -0 | Adequate sample sizes. |
| Publication bias | -1 | Company-program structural risk. |

**Final certainty:** **Very Low.**
- Interpretation: The PIE-vs-PROTECTOR inconsistency is fatal to "moderate" certainty; the field treats this as a negative replication.

#### Without corpus expansion (current AAA4 corpus):

- Only Kell 2026, observational, mechanistic biomarker.
- Starting certainty: Low. -2 indirectness (biomarker not clinical endpoint), -1 imprecision (n unspecified, single cohort).
- **Final certainty:** **Very Low.**

---

### OG-3. Cardiometabolic outcomes

**Question:** Does rapamycin improve cardiometabolic outcomes (BMI, HbA1c, lipids, blood pressure) in older adults?

**Body of evidence:**
- Moel 2025 / PEARL (RCT, A1): null on BMI, n ≈ 80, 12 months.
- Stanfield 2026 / RAPA-EX-01 (RCT, A1): mixed HbA1c, weekly sirolimus + exercise.
- Kell 2026 (observational, B2): no clinical cardiometabolic endpoint reported.

**Starting certainty:** High (two A1 RCTs).

#### Downgrade assessment:

| Domain | Downgrade | Reasoning |
|---|---|---|
| Risk of bias | -1 | Moel 2025 some concerns on Domains 2/3/5; Stanfield 2026 high risk on Domain 5 (multiple-p-value reporting). |
| Inconsistency | -1 to -2 | Moel null + Stanfield bidirectional = inconsistent direction. |
| Indirectness | -1 | BMI is far from mTOR substrate; HbA1c is closer but still distal (per `novel_framework_candidates.md` Framework 3). The endpoints chosen may be the wrong endpoints for detecting geroprotection. |
| Imprecision | -1 | Moel n ≈ 80; CIs wide for a 12-month single-site trial. |
| Publication bias | -0 | Geroscience trials are typically pre-registered; both PEARL and RAPA-EX-01 are likely on ClinicalTrials.gov. |

**Net downgrade:** -4 to -5 levels from High.

**Final certainty:** **Very Low.**
- Interpretation: We have *very low certainty* in any specific cardiometabolic effect of rapamycin. The null-mixed pattern across two RCTs with the limitations above is consistent with no effect, with detection failure due to wrong-endpoint selection, or with a true small effect lost to imprecision.
- The paper's current claim ("null findings dominate cardiometabolic") should be reframed as "Very Low certainty of any cardiometabolic effect."

#### Subgroup considerations

If the paper splits cardiometabolic into BMI vs HbA1c vs lipids vs blood pressure:

- BMI: 1 RCT (Moel 2025 null). Starting certainty High; -2 imprecision (single trial small n); -1 indirectness (BMI is the most distal endpoint per Framework 3). **Low certainty of null.**
- HbA1c: 1 RCT (Stanfield 2026 mixed) + indirect mechanistic data. Starting High; -2 inconsistency (within-trial bidirectional); -1 indirectness; -1 RoB. **Very Low certainty of any effect.**
- Lipids, BP: not reported with effect-size data in the current corpus. **No assessment possible.**

---

### OG-4. Cognition / ADRD (Alzheimer's disease and related dementias)

**Question:** Does rapamycin improve cognitive function or reduce ADRD risk?

**Body of evidence in current corpus:** Zero.

**Starting certainty:** Cannot be assessed.

**Path to assessment:** Corpus expansion to include 2–3 specific papers:
- Kaeberlein lab small RCTs in healthy older adults (cognitive secondary endpoints).
- Halloran et al. (mouse cognitive function under rapamycin).
- ADRD-specific rapamycin papers (TAME-style metformin trial parallel).

**Without these:** The paper cannot make any cognition claim. Recommendation: explicit "no evidence in current synthesis" note in Limitations, not silent omission.

---

### OG-5. Physical function (gait speed, grip strength, frailty)

**Question:** Does rapamycin preserve physical function in older adults?

**Body of evidence in current corpus:** Zero.

**Starting certainty:** Cannot be assessed.

**Path to assessment:** Corpus expansion to include trials with physical-function endpoints:
- Stanfield 2026 may report secondary functional endpoints — verify.
- Possible companion-animal data (Urfer 2017, dogs, owner-reported function).

**Without these:** Same as OG-4 — explicit no-evidence note required.

---

### OG-6. Skin aging / senescence

**Question:** Does rapamycin reduce skin senescence or improve skin-aging markers?

**Body of evidence in current corpus:** Zero.

**Starting certainty:** Cannot be assessed in the human-relevant outcome class.

**Adjacent evidence:** Topical rapamycin papers exist (e.g., Chung et al. small RCTs of topical rapamycin in skin aging) — verify and consider for corpus expansion if the paper's scope includes topical applications.

---

### OG-7. Adverse effects

**Question:** What is the safety profile of rapamycin in geroprotective doses?

**Body of evidence:** All three current RCTs report safety as a non-primary endpoint. Mannick 2014 reports specific adverse-event profile for everolimus (well-characterised). Transplant-medicine literature provides high-dose continuous-exposure safety data (Kahan 2000).

**Starting certainty:** Moderate (across-trial safety reporting in RCTs is typically reliable for common AEs; rare AEs require larger samples).

#### Downgrade assessment:

| Domain | Downgrade | Reasoning |
|---|---|---|
| Risk of bias | -0 | Safety reporting in RCTs follows standardised protocols (CONSORT). |
| Inconsistency | -0 to -1 | Different rapalogs, dose regimens; AE comparability non-trivial. |
| Indirectness | -1 | Transplant-dose safety does not transfer to geroprotective-dose safety; geroprotective-dose AE data are sparse. |
| Imprecision | -1 | Total n across geroprotective trials is in the low hundreds; rare AEs not detectable. |
| Publication bias | -0 | Safety reporting is mandated in trial registration. |

**Final certainty:** **Low to Moderate.**
- Interpretation: For common AEs at geroprotective doses (mucositis, mouth ulcers, mild glycemic perturbation), certainty is moderate. For rare or long-term AEs, certainty is low. For dose-dependent AEs (continuous vs intermittent), certainty is low pending dose-finding evidence.

---

## Cross-outcome GRADE summary table

| Outcome group | Current corpus certainty | Post-expansion certainty | Limiting factor |
|---|---|---|---|
| OG-1 Lifespan | Very Low (mouse → human) | Unchanged (no human RCT possible at scale) | Indirectness |
| OG-2 Immune function | Very Low | Low to Moderate (vaccine response); Very Low (RTI rate, post-PROTECTOR) | RoB 2 (industry); inconsistency (PIE vs PROTECTOR) |
| OG-3 Cardiometabolic — BMI | Low | Unchanged | Imprecision; indirectness |
| OG-3 Cardiometabolic — HbA1c | Very Low | Low (with PIE/PROTECTOR adverse effects on glycemia) | Inconsistency; selective reporting |
| OG-4 Cognition/ADRD | Cannot assess | Low (provisional with expansion) | Absence of corpus data |
| OG-5 Physical function | Cannot assess | Low (provisional with expansion) | Absence of corpus data |
| OG-6 Skin/senescence | Cannot assess | Low (provisional, topical only) | Absence of corpus data |
| OG-7 Adverse effects | Low | Moderate (common AEs); Low (rare AEs) | Total n for rare AE detection |

---

## What is missing in the corpus before full GRADE can run

For each outcome group, GRADE requires:

1. **At least 2 studies per outcome** to assess inconsistency (a single study cannot have within-corpus inconsistency).
2. **Source-text RoB 2** per study (per `rob2_manual_pilot.md`).
3. **Effect-size with CI** per study per outcome — currently extracted as p-values and "direction" tokens; full effect-size + CI extraction is required.
4. **Comparable-effect audit** per outcome (per `meta_analysis_feasibility.md`, forthcoming): are the studies measuring the same thing in the same units?
5. **Publication-bias signal** per outcome — funnel plot if ≥10 studies, or trial-registry-vs-publication audit if <10.
6. **Trial registration metadata** per RCT — ClinicalTrials.gov NCT ID, registration date vs first-result date.

Of these six requirements, the AAA4 paper currently has:
- ✓ Studies per outcome — partial (cardiometabolic has 3; others 0–1).
- ✗ Source-text RoB 2 — not run.
- ✗ Full effect-size + CI extraction — partial (p-values yes; full effect-size with CI no).
- ✗ Comparable-effect audit — not run.
- ✗ Publication-bias signal — not run.
- ✗ Trial registration metadata — not extracted.

**Net assessment:** GRADE can be applied at the *concept* level today but cannot be applied at the *quantitative* level without the source-text data fields above.

---

## Activation plan for `scripts/grade_assessment.py`

The current scaffold (per the handover doc, scaffold-only) needs:

1. **Outcome-group taxonomy.** Define the seven outcome groups above as a topic-pack-extensible enum. (~50 LOC)
2. **Effect-size extraction schema.** Extend `quant_claims` to capture: effect estimate, 95% CI, n, comparator, timepoint, units. (~30 LOC schema; extractor prompt update.)
3. **Comparable-effect aggregator.** For each (outcome, study) pair, classify as "comparable" or "non-comparable" against an outcome-group reference (e.g., HbA1c in mmol/mol or %; BMI in kg/m²). (~80 LOC)
4. **Downgrade-rule engine.** Apply the five downgrade factors deterministically given source-text fields. (~150 LOC — most of the work is in encoding "two studies disagree by X% direction" as a deterministic inconsistency signal.)
5. **Upgrade-rule engine.** For observational evidence: large-effect, dose-response, plausible-confounder rules. (~50 LOC)
6. **Output integration.** Add a `full_paper.grade.json` to the bundle alongside `full_paper.audit.json`. Render as Table 6 in the paper.

Total scope: ~360 LOC + extractor prompt updates. Most of the LOC is the rule engine; the extraction is shared with the RoB 2 activation.

---

## Recommended changes to the AAA4 paper before GRADE activation

Even before automated GRADE, the paper should:

1. **Replace "null findings dominate cardiometabolic" with "Very Low certainty of any cardiometabolic effect"** in the abstract and conclusion.
2. **Add a "Certainty of Evidence" subsection** that names each outcome group, its current certainty (Low / Very Low / Cannot assess), and the limiting factor.
3. **Move the implicit certainty signals (tier × directness) into a Limitations note** that GRADE will replace.
4. **Pre-flag the source-text GRADE pass as future work** rather than claiming GRADE-equivalent in the current paper.

These changes lower desk-rejection risk by being explicit about the certainty-assessment gap.

---

## Falsifying conditions

This pilot is wrong if:

1. **My downgrade reasoning is non-standard** for the field. GRADE has been criticised for inter-rater variability; my judgments should be cross-checked against a published rapamycin GRADE assessment (e.g., Lee et al. 2024 if applicable).
2. **The corpus expansion does not surface sufficient studies per outcome group** to enable inconsistency assessment. If OG-4 (cognition) gets only one study post-expansion, GRADE cannot meaningfully run on that outcome.
3. **The outcome groups are mis-specified.** The seven OGs above are reasonable for a rapamycin paper; alternative groupings (e.g., split immune function into vaccine response, T-cell function, infection rate) would change the per-outcome assessment.

---

## What this pilot refuses to claim

- That GRADE is fully applicable to the current corpus. It is not; the source-text data fields above are precondition.
- That my certainty judgments are stable across raters. GRADE is well-known for inter-rater variability.
- That "Very Low certainty" implies "no effect." It implies "we are not certain about any effect, in either direction."
- That the paper can claim Cochrane-grade systematic-review status with this manual pilot. It cannot; the source-text pass and the effect-size + CI extraction are precondition.

---

**Provisional flag:** All certainty judgments above are provisional. The pilot is intended as a methodological scaffold, not a finished GRADE assessment. The next render of the rapamycin paper should run source-text GRADE and replace these provisional judgments wholesale.
