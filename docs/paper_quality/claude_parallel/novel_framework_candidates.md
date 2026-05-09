# Novel Framework Candidates for the Rapamycin Paper

**Status:** Provisional design document for the paper's organizing framework. Five candidate frameworks evaluated; one recommended as the load-bearing scaffold.
**Generated:** 2026-05-09
**Purpose:** Replace the implicit "we just synthesised what was retrieved" structure of the AAA4 paper with an explicit, falsifiable organizing framework that a senior reviewer can evaluate as a *contribution*, not just a curation.

---

## Why this matters

A senior-PhD-grade review on rapamycin in 2026 cannot be a literature dump. The field already has half a dozen narrative reviews from the named labs (Mannick, Lamming, Kennedy, Kaeberlein) covering the same evidence base. To clear desk-rejection at *Aging Cell* or *Nature Aging*, the paper must do one of:

1. Apply a **methodological framework** that other reviews have not (e.g., source-text RoB 2 + GRADE + comparable-effect audit) — this is the *infrastructure* contribution.
2. Apply an **organizing framework** that reorganizes existing tensions in a way that generates new predictions — this is the *intellectual* contribution.
3. Both.

Researka's audit-trail-as-trust-mechanism is the methodological contribution. This document is the intellectual contribution. The paper needs one organizing framework that:

- Names a falsifiable claim about rapamycin's clinical translation.
- Explains, parsimoniously, why our corpus shows the pattern it does (null cardiometabolic + mixed cardiometabolic + indirect immune + robust preclinical).
- Generates at least one trial-design recommendation that follows from the framework, not from generic "more trials needed" hedging.
- Survives engagement with the eight named frameworks in `field_framework_dossier.md`.

---

## Five candidate frameworks

### Framework 1 — Dose-Regime Framework

**Thesis.** Rapamycin's geroprotective signal is dose-regime-dependent, not dose-amount-dependent. The relevant variable is the cumulative mTORC2 disruption integral (dose × duration × continuity) rather than peak concentration or weekly dose. Intermittent dosing with sufficient inter-dose recovery preserves mTORC1 inhibition while allowing mTORC2 to recover; chronic continuous dosing — even at low concentration — drives cumulative mTORC2 disruption that offsets benefit.

**Contradictions explained.**
- Stanfield 2026's bidirectional HbA1c effects under weekly + exercise: cumulative mTORC2 disruption emerges from the regimen's interaction with exercise-driven metabolic flux, even at intermittent dose.
- PEARL (Moel 2025) null on BMI: BMI is insensitive to mTORC1 modulation; the regimen was protective against mTORC2 disruption (per Mannick 2018 dose-finding) and so produced neither benefit nor harm in measurable cardiometabolic markers.
- Kell 2026's clean five-week mTOR-signaling reduction without glycemic perturbation: short-duration intermittent dosing engages mTORC1 in immune cells before the cumulative-AUC threshold for mTORC2 disruption is reached.
- Harrison 2009 vs. transplant-medicine continuous-dosing experience: same drug, opposite metabolic profile, because continuous high-trough dosing is in the chronic-mTORC2-disruption regime.

**Falsifying experiment.** A four-arm RCT of equivalent cumulative weekly dose under different temporal distributions: (a) 5 mg once weekly, (b) 1 mg daily, (c) 5 mg daily for one week, then three weeks off, (d) 35 mg once monthly. If the framework holds, regimens (a) and (c) should produce equivalent mTORC1 substrate inhibition with no Akt-Ser473 / PKC mTORC2-substrate disruption; regimen (b) should produce mTORC2 disruption and glycemic dysregulation; regimen (d) should produce neither. Single-arm pharmacodynamic substudy is sufficient (n ≈ 60); no clinical endpoint required.

**Weaknesses.**
1. Reduces a multi-domain question to a single pharmacokinetic axis. Real human variability (FKBP12 expression, drug metabolism, microbiome) introduces noise the framework does not absorb.
2. Borrows heavily from Lamming's published position; the novel claim is *cumulative AUC matters more than peak dose*, but this is a refinement of Lamming, not a competitor framework.
3. Cannot explain the inferential bridge (mouse data → human prediction) on its own, because dose translation across species is itself unsettled.

---

### Framework 2 — mTORC1/mTORC2 Tradeoff as Two-Drug Reframing

**Thesis.** Rapamycin should be conceptualized as two drugs sharing one molecule: a fast-onset, fast-offset mTORC1 inhibitor (the geroprotective drug) and a slow-onset, slow-offset mTORC2 inhibitor (the toxicity drug). Trial design and dosing should optimize for separating the two drugs in time. The paper's tensions resolve when you stop treating "rapamycin effect" as a single thing.

**Contradictions explained.**
- Same as Framework 1, but at a more conceptual level: every observed effect can be decomposed into a mTORC1 component (which the regimen optimizes for) and a mTORC2 component (which the regimen tries to minimize).
- Sex asymmetry (Harrison 2009: 14% male / 9% female): female mice may have shifted FKBP12/FKBP51 stoichiometry that alters the mTORC1/mTORC2 selectivity of the same dose. The framework predicts sex-specific dose-finding rather than treating sex as noise.
- Bitto 2016 transient dosing extending lifespan in middle-aged mice: short-pulse dosing achieves mTORC1 inhibition before mTORC2 disruption emerges; the framework predicts pulse dosing should be at least as good as chronic dosing per unit cumulative dose.

**Falsifying experiment.** A three-arm crossover trial with pharmacodynamic readout: each subject receives, in randomized order, (a) rapamycin 5 mg weekly × 12 weeks, (b) RapaLink-1 or other mTORC1-selective compound at matched mTORC1 inhibition, (c) placebo. Primary readout is the ratio of S6K1-T389 phosphorylation (mTORC1 substrate) to Akt-S473 phosphorylation (mTORC2 substrate) in PBMCs and adipose biopsy. Framework predicts arm (a) and arm (b) produce equivalent geroprotective biomarker changes (DNA-damage resilience, autophagy markers); only arm (a) produces measurable Akt-S473 reduction; therefore the geroprotective effect is mTORC1-only.

**Weaknesses.**
1. Requires mTORC1-selective comparator drug, which may not exist in clinically usable form by the trial date.
2. Frames rapamycin as "two drugs," which is anatomically true but rhetorically risky — readers may parse it as overclaiming the field's mechanistic certainty.
3. Sub-suming Mannick's framework rather than complementing it; risks reading as a takedown rather than a synthesis.

---

### Framework 3 — Endpoint-Sensitivity Framework (recommended; see below)

**Thesis.** Rapamycin's geroprotective effect manifests with different signal-to-noise ratios across different endpoint families. The signal-to-noise ratio is highest for endpoints proximal to mTOR pathway substrate (PBMC mTOR signaling, autophagy markers), intermediate for endpoints affected by mTOR through one or two intermediate steps (immune function, vaccine response, infection rate, DNA-damage repair), and lowest for endpoints affected through many intermediate steps with high biological variability (BMI, HbA1c, blood pressure, gait speed). Single-domain trials of rapamycin against low-SNR endpoints structurally underdetect benefit; multi-domain composite-endpoint trials of the *correct* endpoint family detect it.

**Contradictions explained.**
- PEARL (Moel 2025) null on BMI: BMI is the lowest-SNR endpoint; null is the predicted result regardless of whether geroprotection is occurring.
- Stanfield 2026 mixed HbA1c: HbA1c is intermediate-SNR; bidirectional results under co-intervention reflect noise dominating signal at this endpoint distance.
- Kell 2026 clean mTOR-signaling reduction: PBMC mTOR substrate is the highest-SNR endpoint; signal is detectable in five weeks at n likely below 30.
- Mannick 2014/2018 positive flu-vaccine response: vaccine response is intermediate-SNR but with mechanism-driven directionality (mTOR inhibition → reduced PD-1 → improved naïve-T-cell response); the trial's positive signal is consistent with the framework rather than anomalous.
- Harrison 2009 (mouse lifespan): lifespan is the highest-SNR composite endpoint in any species because every aging hallmark contributes to it; the preclinical signal is robust because the endpoint integrates across all hallmarks.

**Falsifying experiment.** A single-cohort RCT with pre-specified endpoint hierarchy: enroll 200 adults aged 65+ on weekly sirolimus 5 mg vs. placebo for 12 months. Measure all of: (a) PBMC S6K1-T389 inhibition (proximal), (b) immune-function composite (vaccine response, infection rate, T-cell exhaustion markers), (c) cardiometabolic composite (HbA1c, BMI, lipids), (d) functional composite (gait speed, grip strength, frailty). The framework predicts effect sizes (a) > (b) > (c) ≈ (d) at 12 months, with (c) and (d) requiring 24+ month follow-up to detect. If the cardiometabolic composite shows larger effect than the immune composite at 12 months, the framework is falsified.

**Weaknesses.**
1. The "signal-to-noise" framing is a metaphor for biological proximity to pathway substrate; making it quantitative requires effect-size estimates per endpoint family, which the corpus does not yet provide.
2. The framework predicts a *specific ordering* of effect sizes, which is bold; a single trial can falsify it definitively.
3. Risks oversimplifying — some endpoints (e.g., autophagy markers) may have high biological proximity but low between-subject reproducibility, breaking the SNR ordering.

---

### Framework 4 — Tissue-Context Framework

**Thesis.** Rapamycin's net systemic effect is the sum of tissue-specific mTOR responses, and tissues differ substantially in their mTOR setpoint, FKBP12/FKBP51 stoichiometry, and downstream substrate sensitivity. The paper's null-or-mixed cardiometabolic findings reflect the dominance of liver and skeletal-muscle mTORC2 effects on systemic glucose handling, while the cleaner immune findings reflect PBMC mTORC1 dominance with low mTORC2 setpoint.

**Contradictions explained.**
- HbA1c bidirectionality (Stanfield 2026): liver mTORC2 disruption drives hepatic gluconeogenesis up; muscle mTORC2 disruption drives glucose uptake down; the net HbA1c signal reflects the balance between two opposing tissue-level responses, which varies by individual fitness baseline.
- BMI null (Moel 2025): adipose mTOR effects are buffered by hypothalamic feedback; BMI is the wrong tissue's readout for a drug whose adipose-tissue effect is small relative to its hepatic and muscle effects.
- Kell 2026 immune-cell mTOR reduction without glycemic data: the paper measured one tissue's response; the framework predicts other-tissue responses would have shown different directionalities.
- Cognitive endpoints (absent from corpus): CNS rapamycin penetrance is poor, so cognitive effects should lag peripheral effects by ≥2 trial-duration units; if the corpus expansion adds cognitive trials, expect them to be null at trial durations < 18 months.

**Falsifying experiment.** A multi-tissue biomarker substudy nested in any of the above trials: paired adipose biopsy + skeletal muscle biopsy + PBMC isolation, with mTORC1-substrate (S6K1-T389, 4E-BP1) and mTORC2-substrate (Akt-S473, PKCα) phosphorylation measured per tissue at baseline and at 12 weeks. Framework predicts substantial inter-tissue heterogeneity in the mTORC1/mTORC2 ratio response within the same subject; failure to find such heterogeneity falsifies the tissue-context claim.

**Weaknesses.**
1. Requires tissue biopsies, which limit clinical-trial enrolment and increase cost.
2. The framework is descriptively correct but generates few actionable trial-design recommendations beyond "measure more tissues."
3. Tissue-specific data is often unavailable for human rapamycin trials (transplant pharmacokinetic literature notwithstanding); the framework is testable in principle but expensive in practice.

---

### Framework 5 — Reserve-Capacity Framework (Population-Specificity)

**Thesis.** Rapamycin's geroprotective effect size is proportional to baseline mTOR pathway hyperactivity in the relevant tissue. Older adults with metabolic syndrome, chronic low-grade inflammation, or established immune aging benefit more (because their mTOR pathway is more "open to closing") than healthier or younger controls. The framework predicts an inverse relationship between baseline health and rapamycin benefit, which is testable but rarely tested.

**Contradictions explained.**
- PEARL (Moel 2025) null on BMI: enrolment was relatively healthy adults; the framework predicts negligible effect in this population.
- RAPA-EX-01 (Stanfield 2026) mixed: older adults (more hyperactive mTOR baseline) but with exercise co-intervention that itself lowers mTOR pathway activity; framework predicts variable effect because the exercise normalises baseline.
- Kell 2026 clean immune effect: ageing immune cells have well-documented mTOR hyperactivity (PD-1 upregulation, naïve T-cell loss); the framework predicts the largest effect in this tissue.
- Harrison 2009 (heterogeneous-stock mice): heterogeneity in mTOR baseline across the JAX cohort produces variable individual responses, which average to a ~14% / 9% group effect; the framework predicts higher-mTOR-baseline subgroup mice show effects 2–3× larger than the cohort average.

**Falsifying experiment.** Stratified RCT enrolment by baseline mTOR pathway markers: pre-screen for high vs low PBMC S6K1-T389 phosphorylation, randomize within strata. Framework predicts effect-size ratio of 2–3× between high-baseline and low-baseline strata. Cohort size n ≈ 200 per stratum is sufficient to detect a 2× effect-size ratio at α = 0.05, β = 0.2.

**Weaknesses.**
1. Pre-screening for mTOR pathway markers is logistically expensive; few trials have done this.
2. The framework is consistent with all observed data but is not the most parsimonious explanation for any single observation.
3. Risks endorsing rapamycin as a "metabolic syndrome drug" rather than a geroprotective drug, which is a clinical-positioning issue.

---

## Cross-framework comparison

| Framework | Falsifiability | Novelty over field | Power to explain corpus | Trial-design generativity | Defensibility |
|---|---|---|---|---|---|
| 1. Dose-Regime | High (single PK trial) | Medium (refines Lamming) | High | High | High |
| 2. mTORC1/mTORC2 Two-Drug | Medium (needs comparator) | Medium-high | Medium | Medium | Medium |
| 3. Endpoint-Sensitivity | High (single trial with hierarchy) | High | High | High | High |
| 4. Tissue-Context | Medium-high (requires biopsies) | Medium | High | Low (descriptive) | Medium-high |
| 5. Reserve-Capacity | High (stratified trial) | Medium-high | Medium-high | Medium | Medium |

---

## Recommendation: adopt Framework 3 (Endpoint-Sensitivity) as the load-bearing scaffold

**Why Framework 3 wins.**

1. **Maximum falsifiability per trial.** Framework 3 makes a *specific ordering* prediction (proximal > intermediate > distal effect sizes) that a single trial can confirm or falsify. Framework 1 also has high falsifiability but requires a multi-arm PK trial; Framework 3 requires a single-arm trial with hierarchical endpoint measurement.

2. **Reorganises the existing tensions parsimoniously.** Every load-bearing tension in our corpus (PEARL null vs Stanfield mixed vs Kell positive vs Harrison robust) maps onto a single axis (endpoint distance from mTOR substrate). The other frameworks explain tensions across multiple axes.

3. **Trial-design generativity.** Framework 3 generates a concrete, fundable trial design (200 adults, 12-month, hierarchical endpoint composite) that addresses all major desk-rejection concerns: composite endpoint, pre-specified hierarchy, mechanistic-clinical link, sensible duration, plausible n.

4. **Compatible with all eight field frameworks.** Framework 3 incorporates Mannick (immune-aging-first as the intermediate-SNR endpoint), Lamming (mTORC2 disruption as a distal noise source), Kennedy (composite endpoints as the structural fix), and López-Otín (hallmarks as an integrative organising principle for the endpoint hierarchy). It is *additive* rather than *competitive* relative to the field.

5. **Rhetorical fit with the corpus.** Framework 3 lets the paper frame the cardiometabolic-only AAA4 corpus as *evidence in favour of the framework* (we found null/mixed because we measured low-SNR endpoints), rather than as a corpus weakness. The post-rescue 34-receipt corpus, which includes immune and mechanistic receipts, lets the paper *demonstrate* the SNR ordering using its own evidence.

**Where Framework 3 falls short.**

- The SNR ordering is *predicted*, not measured; the paper must be careful to call it a hypothesis rather than a finding.
- The "signal-to-noise" framing is metaphorical for biological proximity; rigorous formalization requires effect-size estimates per endpoint family, which the corpus may not yet support.
- A single contradicting trial would falsify the framework; the paper should explicitly name what would falsify it, and cite that as a strength.

**Recommended ancillary frameworks.**

- Framework 1 (Dose-Regime) as a *secondary* organizing axis for the Discussion's dose-translation paragraph. This pairs naturally with Framework 3's endpoint-hierarchy axis to form a 2D framework: endpoint distance × dose regime.
- Framework 5 (Reserve-Capacity) as a *Limitations* section anchor for population-specificity questions.

---

## Drop-in section language for the paper's framework introduction

> The rapamycin-aging literature contains a recurring tension: preclinical lifespan extension is robust and replicated, but human RCTs against cardiometabolic surrogate endpoints have produced null or mixed results. We propose that this tension reflects an Endpoint-Sensitivity gradient: rapamycin's geroprotective effect manifests with high signal-to-noise ratio at endpoints proximal to mTOR pathway substrate (autophagy markers, PBMC mTOR signaling), with intermediate signal-to-noise at endpoints affected through one or two intermediate steps (immune function, DNA-damage resilience, vaccine response), and with low signal-to-noise at endpoints affected through many intermediate steps with high biological variability (BMI, HbA1c, blood pressure, gait speed). Under this framework, the consistent null findings against cardiometabolic surrogates are predicted, not anomalous; the consistent mechanistic findings against PBMC and DNA-damage endpoints are confirmatory, not isolated; and the cross-species translation gap reflects the difficulty of measuring the high-SNR composite endpoint (lifespan) in humans rather than a failure of mechanism. This framework reorganises the corpus's three load-bearing tensions and generates a falsifiable trial-design prediction (effect-size ordering: proximal > intermediate > distal at 12 months) that future work can definitively test.

---

## What this framework refuses to claim

- That rapamycin is geroprotective in humans. Insufficient evidence.
- That cardiometabolic null findings are unimportant. They are predicted, not unimportant.
- That the SNR ordering is monotonic for every endpoint. Some intermediate-distance endpoints may have higher noise than some distal endpoints.
- That this framework supersedes the eight field frameworks in `field_framework_dossier.md`. It is additive; it pairs naturally with López-Otín's hallmarks (which provide the biological mapping for the endpoint hierarchy) and with Lamming's mTORC1/mTORC2 distinction (which drives the noise floor at distal endpoints).

---

## Falsifying conditions for the framework

The Endpoint-Sensitivity framework is falsified if any of the following hold in adequately powered future trials:

1. A randomized trial against any cardiometabolic endpoint (BMI, HbA1c) shows effect sizes ≥ those at PBMC mTOR substrate level under matched dose/duration.
2. Within a single trial, the effect-size ordering is not proximal > intermediate > distal at any time point ≥ 6 months.
3. The corpus expansion to 34 receipts surfaces direct human evidence that rapamycin produces no measurable effect at *any* endpoint distance, including PBMC mTOR substrate. This would suggest the drug does not engage in human tissue at the dose tested, which would falsify all five candidate frameworks simultaneously and is a more fundamental finding.

---

**Provisional flag:** All effect-size ordering predictions in this document are *predictions*, not findings. The framework is recommended as the paper's load-bearing scaffold because it is the most falsifiable and most generative; it is not yet validated by the corpus.
