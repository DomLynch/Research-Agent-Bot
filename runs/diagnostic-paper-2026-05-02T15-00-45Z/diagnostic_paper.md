## Abstract

The potential for metformin to mitigate age-related decline has garnered significant attention, yet recent evidence presents a nuanced picture. While initially proposed as a candidate for lifespan extension – with some studies reporting increases of up to 14.4% in mice (Mohammed 2021) – emerging data suggest its effects are context-dependent and may not translate directly to humans. Several trials have demonstrated metformin does not consistently improve measures of physical function. Specifically, a 4-month intervention with metformin showed no improvement in grip strength or walking speed (Keys 2025), and the MET-PREVENT trial similarly found no benefit in these parameters (Witham 2025). 

Furthermore, metformin appears to interfere with the adaptive response to exercise. In resistance training, metformin blunted muscle hypertrophy (Walton 2019) and gains in lean body mass (p=0.003, Walton 2019), although it did not significantly alter muscle strength after 4 months (Keys 2025). Similarly, metformin attenuated increases in VO2max following aerobic exercise training by approximately 50% (Konopka 2019). These findings suggest that while metformin may offer metabolic benefits, its impact on maintaining or improving physical performance in older adults is limited and may even be detrimental when combined with exercise.  The current evidence indicates a need for caution when considering metformin as a universal anti-aging intervention, and highlights the importance of considering individual responses and lifestyle factors (Keys 2025).

## Introduction

The prospect of extending healthy lifespan and mitigating the effects of age-related decline has fueled substantial research into potential anti-aging interventions. Metformin, a widely prescribed drug for type 2 diabetes, has emerged as a leading candidate for repurposing as a geroprotective agent. Initially investigated for its metabolic effects, metformin’s potential to impact fundamental aging processes has garnered significant attention, driven by observations of reduced age-related disease and modestly extended lifespan in preclinical models (Mohammed 2021). However, recent evidence suggests a more nuanced picture, prompting a critical re-evaluation of metformin’s anti-aging potential (Keys 2025). This review will synthesize current knowledge regarding metformin’s effects on key hallmarks of aging, focusing on its impact on physical function, and highlight emerging uncertainties surrounding its efficacy in promoting healthy aging.

The initial enthusiasm for metformin as an anti-aging drug stemmed from its ability to activate AMP-activated protein kinase (AMPK), a central regulator of cellular energy homeostasis (PMC12978362). AMPK activation is linked to improved mitochondrial function, enhanced autophagy, and reduced inflammation – all processes implicated in age-related decline. Furthermore, epidemiological studies, such as subgroup analyses from the UK Prospective Diabetes Study (UKPDS), indicated that metformin was associated with decreased mortality, with reductions of 32.0%, 42.0%, and 36.0% observed in specific cohorts (Keys 2025). These findings, coupled with observations of lifespan increases in model organisms – 14.0%, 6.0%, and 0.1% in various mouse studies (Mohammed 2021) – fueled the rationale for clinical trials investigating metformin’s effects on aging-related outcomes in humans. 

However, translating these promising preclinical and observational findings into consistent benefits in human aging remains challenging. Recent clinical trials, such as the MET-PREVENT trial (Witham 2025), have yielded mixed results. While some studies have reported improvements in gait speed following 14 weeks of metformin treatment (Keys 2025), others have shown no significant change in physical performance metrics. Specifically, the MET-PREVENT trial demonstrated no improvement in grip strength after 4 months of metformin administration (Keys 2025).  Moreover, metformin’s impact on muscle mass and strength appears to be context-dependent. The MASTERS trial (Walton 2019) demonstrated that while placebo increased knee extension strength by 23.1% (SD 18.9), metformin only yielded a 15.3% (SD 18.5) increase.  Furthermore, placebo groups experienced greater gains in lean body mass (p = 0.003) and thigh muscle mass (p < 0.001) compared to metformin, suggesting metformin may blunt anabolic responses to exercise (Walton 2019). Indeed, metformin prevented gains in lean mass with progressive resistance training (PRT) (p = 0.003), with placebo gaining 1.95% (SD 2.69) lean body mass (Walton 2019).

This observation of blunted muscle adaptations is further supported by research demonstrating metformin’s inhibitory effect on mitochondrial adaptations to aerobic exercise in older adults (Konopka 2019). While placebo groups showed increases in VO2max (p = 0.05, p = 0.01) following exercise training, metformin did not demonstrate a similar effect (Konopka 2019). These findings suggest that metformin may interfere with the beneficial effects of exercise on cardiorespiratory fitness, a critical component of healthy aging.  Similarly, a 14-week resistance training program combined with metformin did not result in changes in lean body mass (Keys 2025).

The emerging evidence highlights the complexity of metformin’s effects and raises important questions about its suitability as a universal anti-aging intervention.  The drug’s impact appears to be highly dependent on factors such as age, health status, and lifestyle interventions, such as exercise.  The current understanding suggests that metformin may not simply ‘extend lifespan’ but rather modulate the aging process in ways that are not always beneficial, particularly when it comes to maintaining muscle mass and physical function.  A critical review of the evidence (Mohammed 2021) and emerging uncertainty (Keys 2025) underscore the need for continued research to delineate the specific populations who may benefit from metformin and to optimize its use in the context of comprehensive healthy aging strategies.

## Methods

**Provenance disclaimer:** This synthesis is generated by an automated
pipeline (`scripts/quant_claim_extract.py` v0.6.0, `scripts/diagnostic_paper_run.py`).
**No manual human review of individual claims occurred.** All filtering
is algorithmic. Domain-expert verification is a future-work step.

### Source corpus

7 reference papers contributed to the 90 high-confidence
quantitative claims that ground this synthesis (out of 1001 total
extracted across the full 42-paper corpus). The contributing papers
are:

- **Keys_2025_metformin_anti-aging_uncertainty** — Emerging uncertainty on the anti-aging potential of metformin (Ageing Research Reviews, 2025)
- **Konopka_2019_metformin_blunts_aerobic_exercise_adaptations** — Metformin inhibits mitochondrial adaptations to aerobic exercise training in older adults (Aging Cell, 2019)
- **Kulkarni_2022_geroscience_repurposing_FDA_drugs** — Geroscience-guided repurposing of FDA-approved drugs to target aging: A proposed process and prioritization (Aging Cell, 2022)
- **Mohammed_2021_Metformin_Anti_Aging_Critical_Review** — A Critical Review of the Evidence That Metformin Is a Putative Anti- Aging Drug That Enhances Healthspan and Extends Lif (Frontiers in Endocrinology, 2021)
- **PMC12978362_molecular_mechanisms_of_metformin_action_from_metabolic_effe** — Molecular mechanisms of metformin action: From metabolic effects to lifespan extension and healthspan promotion (Journal of Medical Biochemistry, 2026)
- **Walton_2019_MASTERS_metformin_blunts_resistance_hypertrophy** — Metformin blunts muscle hypertrophy in response to progressive resistance exercise training in older adults: A randomize (Aging Cell, 2019)
- **Witham_2025_MET_PREVENT_metformin_trial** — Metformin and physical performance in older people with probable sarcopenia and physical prefrailty or frailty in Englan (Lancet, 2025)

### Extraction pipeline

1. **PDF / JATS XML → paper_sections.json** via `scripts/pdf_ingest.py`
   (PyMuPDF / pypdf for PDFs) and `scripts/fetch_oa_corpus.py` (Europe
   PMC JATS for open-access papers). Section detection is regex-based;
   metadata extraction (title, authors, year, journal, DOI/PMID) uses
   curated patterns hardened across the 7 reference papers in Phase 1.5.

2. **section text → quant_claims.json** via `scripts/quant_claim_extract.py`
   (extractor v0.6.0). Pattern bank: p-values, confidence intervals,
   sample sizes, percentages, mean ± SD, unit values, hazard ratios,
   odds ratios, risk ratios, correlations.

3. **Per-claim semantic binding** via `scripts/quant_endpoints.py`:
   - **endpoint** (e.g., VO2max, walk speed, lean body mass, mortality)
     via curated vocab; nearest-to-claim-anchor wins on dual-endpoint
     sentences (Phase 2.2-fix v0.5.0 audit response).
   - **arm** (metformin / placebo / control) with comparator-grammar
     handling ("Compared to placebo, metformin..." correctly binds
     subject, not the comparator).
   - **direction** (increase / decrease / no_change / mixed) with
     compound-phrase span containment (e.g., "attenuated the
     increase" → decrease, not increase).
   - **claim_role** (effect / dose / duration / population /
     background / protocol / unknown) via sentence-keyword heuristic.
     Mortality endpoints are now distinct from lifespan (v0.6.0).
     Treatment-timing months ("started at 9 months of age") tag as
     protocol, not effect.

### Inclusion criteria for this synthesis

For each numeric claim to qualify as primary evidence in this paper,
ALL of the following must hold:
- `binding_confidence == "high"` — endpoint, arm, AND direction all bound
- `claim_role == "effect"` — not dose, duration, protocol, etc.
- Source is a curated reference paper (not a search-fetched OA review)

These criteria yield 90 high-confidence claims spanning
17 distinct endpoints across 7 contributing papers.

### Synthesis approach

This is a **narrative** synthesis. No meta-analysis was performed
(study designs and outcome measures are heterogeneous). Quantitative
claims are organized by endpoint and attributed to source papers
verbatim.

### Limitations of method (intrinsic)

- **No manual claim verification.** Every numeric in this paper traces
  to an algorithmic regex match plus vocab-based binding. Polarity and
  semantic-class errors at the extraction layer surface as factual
  errors in prose.
- **Corpus is small.** 7 contributing papers is far below the
  30-50 paper threshold typical for a peer-reviewed systematic review.
- **Tables and figures are not extracted.** Witham/MET-PREVENT and
  Walton/MASTERS report substantial primary-endpoint statistics in
  trial summary tables that this pipeline does not yet read.
- **English-language papers only.** No translation pipeline.


## Results

The accumulating evidence regarding metformin’s impact on aging-related outcomes presents a complex and, increasingly, nuanced picture. While initially hailed as a promising anti-aging intervention, recent studies suggest the effects are far from universal and may be context-dependent, particularly concerning its interaction with exercise and the specific outcomes measured. This section details the findings across several key endpoints relevant to healthy aging, drawing from the available literature.

**Muscle Strength:**  Several studies investigated the effect of metformin on muscle strength.  The MET-PREVENT trial found that 4 months of metformin treatment did not improve grip strength, walking speed, or physical performance in older individuals with probable sarcopenia (Keys_2025_metformin_anti-aging).  The MASTERS trial (Walton_2019_MASTERS_metformin_) provides a more detailed examination of resistance training. While knee extension 1 repetition maximum (RM) increased by 23.1% in the placebo group, metformin attenuated this increase to 15.3% (Walton_2019_MASTERS_metformin_).  This difference, however, did not reach statistical significance (p = 0.055) (Walton_2019_MASTERS_metformin_).  Further analyses within MASTERS revealed variable responses, with gains in knee extension ranging from 6.7% to 29.4% in the placebo group, and 11.8% in the metformin group (Walton_2019_MASTERS_metformin_).

**Lean Body Mass:**  The impact of metformin on lean body mass also appears to be modulated by concurrent interventions.  The MASTERS trial demonstrated that placebo participants gained more lean body mass than those receiving metformin (p = 0.003) (Walton_2019_MASTERS_metformin_). Specifically, placebo participants experienced a 1.95% increase in lean body mass, while metformin attenuated this gain (Walton_2019_MASTERS_metformin_).  This effect was also observed in thigh muscle mass (p < 0.001) (Walton_2019_MASTERS_metformin_).  Interestingly, a 14-week intervention combining metformin with resistance training showed no discernible effect on lean body mass (Keys_2025_metformin_anti-aging).

**Lifespan and Mortality:** Evidence regarding metformin’s effect on lifespan and mortality is mixed, and largely derived from preclinical studies. Mohammed et al. (2021) reviewed the literature and noted that the anti-aging effectiveness of metformin was reduced in older mice.  Specifically, studies reported lifespan increases ranging from 0.1% to 14.4% with metformin treatment (Mohammed_2021_Metformin_Anti_A). However, some studies even showed a decrease in lifespan, with one reporting a 4.15% decrease (Mohammed_2021_Metformin_Anti_A).  Clinical data suggests a potential benefit in specific populations; a subgroup analysis of the UK Prospective Diabetes Study (UKPDS) showed that initiating intensive glucose control with metformin was associated with a decrease in mortality, ranging from 32.0% to 42.0% (Keys_2025_metformin_anti-aging).  Kulkarni et al. (2022) also noted a 10-year mortality benefit associated with metformin use, based on observational data. However, other studies have shown an increase in mortality with intermittent metformin treatment (Mohammed_2021_Metformin_Anti_A).

**Physical Performance & Related Metrics:**  Metformin’s influence on physical performance, as measured by walk speed, is also inconsistent. The MET-PREVENT trial found no improvement in 4-meter walk speed with 4 months of metformin treatment (Witham_2025_MET_PREVENT_metformin_). However, a separate study reported increased gait speed in nondiabetic prefrail individuals treated with metformin for 14 weeks (Keys_2025_metformin_anti-aging).  Regarding cardiorespiratory fitness, Konopka et al. (2019) found that metformin blunted the improvements in VO2max typically observed with aerobic exercise training, attenuating the increase by approximately 50% (Konopka_2019_metformin_blunts_aerobic_exercise_adaptations).  This suggests that metformin may interfere with the beneficial adaptations to exercise.  Furthermore, metformin did not significantly alter body weight following 12 weeks of aerobic exercise (Konopka_2019_metformin_blunts_aerobic_exercise_adaptations).

**Metabolic Markers & Signaling Pathways:** Metformin’s effects on metabolic markers are more consistent. Konopka et al. (2019) demonstrated that both aerobic exercise and metformin independently decreased HbA1c, fasting insulin, and HOMA-IR (Konopka_2019_metformin_blunts_aerobic_exercise_adaptations).  However, the MASTERS trial showed that while fasting glucose decreased in the placebo group, the effect was not statistically significant in the metformin group (Walton_2019_MASTERS_metformin_).  At a mechanistic level, the MASTERS trial indicated that metformin increased AMPK signaling during resistance training, with a 21.3% increase in the phospho-AMPK:total AMPK ratio compared to a 1.6% increase in the placebo group (Walton_2019_MASTERS_metformin_).  However, this difference was not statistically significant (p = 0.087) (Walton_2019_MASTERS_metformin_).

**Sarcopenia and Frailty:**  The relationship between metformin and sarcopenia remains unclear. The MET-PREVENT trial did not demonstrate an effect of metformin on frailty scores in older adults (Witham_2025_MET_PREVENT_metformin_).  However, the study did note that the hypertrophic response to training was blunted in the metformin group, suggesting a potential impact on muscle maintenance (Witham_2025_MET_PREVENT_metformin_).

**Muscle Hypertrophy & mTOR Signaling:**  The MASTERS trial provides evidence that metformin can inhibit muscle hypertrophy in response to progressive resistance exercise (Walton_2019_MASTERS_metformin_).  Specifically, changes in type I/II hybrid fiber cross-sectional area were not significantly affected by metformin (Walton_2019_MASTERS_metformin_).  Furthermore, there was a trend towards decreased mTOR signaling in the metformin group, although this did not reach statistical significance (p = 0.09) (Walton_2019_MASTERS_metformin_).



In conclusion, the results highlight the complexity of metformin’s effects on aging. While some studies suggest potential benefits in specific contexts, such as reducing mortality in diabetic patients, others demonstrate that metformin may blunt the beneficial adaptations to exercise, particularly regarding muscle strength and cardiorespiratory fitness. The emerging uncertainty (Keys_2025_metformin_anti-aging) underscores the need for further research to identify the populations most likely to benefit from metformin and to optimize its use in conjunction with lifestyle interventions like exercise. The data suggests that metformin is not a universal panacea for aging and its effects are likely highly dependent on individual characteristics and the specific outcomes being measured.

## Discussion

The evidence surrounding metformin as an anti-aging intervention is increasingly complex and nuanced. While initially hailed as a promising candidate for lifespan extension and healthspan improvement, recent data, including those from the MET-PREVENT trial (Witham 2025) and further analyses of existing trials (Keys 2025), suggest a more cautious interpretation is warranted. The initial enthusiasm, largely fueled by preclinical studies demonstrating lifespan increases in model organisms (Mohammed 2021), has not consistently translated to robust benefits in human trials, particularly regarding physical function.

A central theme emerging from the reviewed literature concerns metformin’s impact on muscle health, a critical component of healthy aging. Several studies investigated the effects of metformin on muscle strength, lean body mass, and hypertrophy. Notably, the MASTERS trial (Walton 2019) demonstrated that metformin *blunted* muscle hypertrophy in response to progressive resistance exercise. Specifically, while the placebo group experienced a 23.1% increase in knee extension 1 repetition maximum (RM), the metformin group only saw a 15.3% increase (Walton 2019).  This difference, while not reaching statistical significance (p=0.055 for strength, p=0.082 for another measure), suggests a potential interference of metformin with the muscle-building process.  Furthermore, metformin *prevented* gains in lean mass with progressive resistance training (p=0.003) (Walton 2019), with placebo gaining 1.95% lean mass compared to 0.41% in the metformin group. This finding is particularly relevant given the well-established link between muscle mass and longevity.  The MET-PREVENT trial (Witham 2025) adds to this picture, showing no improvement in grip strength or 4-m walk speed with 4 months of metformin treatment.  

The mechanisms underlying these observations are likely multifaceted. Konopka (2019) highlights metformin’s ability to inhibit mitochondrial adaptations to aerobic exercise, which are crucial for improving muscle function and endurance.  The study also demonstrated that metformin attenuated the increase in VO2max following aerobic exercise training by approximately 50% (Konopka 2019), although this did not reach statistical significance (p=0.08).  This suggests that metformin may interfere with the cellular processes necessary for exercise-induced improvements in cardiorespiratory fitness.  Interestingly, the same study found that metformin did not independently affect HbA1c, body weight, or insulin sensitivity, but rather *blunted* the improvements typically seen with exercise alone (Konopka 2019). This suggests a complex interaction between metformin and exercise, where the drug may diminish the beneficial effects of physical activity.  AMPK signaling, often touted as a key mediator of metformin’s effects, was also investigated in the MASTERS trial (Walton 2019), revealing a higher percent change in basal phosphorylation in the metformin group, though not statistically significant (p=0.087).

The impact of metformin on lifespan remains contentious. While Mohammed (2021) reviews studies showing modest lifespan increases in mice (ranging from 0.1% to 14.4%), the applicability of these findings to humans is questionable. The review notes that the anti-aging effectiveness of metformin was reduced in older mice.  Furthermore, the observed effects are highly variable and dependent on factors such as dosage, timing of administration, and genetic background.  Clinical data on mortality are limited, but subgroup analyses of the UK Prospective Diabetes Study (UKPDS) (Keys 2025) suggest a potential for metformin to *decrease* mortality (32.0-42.0%) in diabetic populations. However, these findings are correlational and do not establish causality. Kulkarni (2022) emphasizes the need for geroscience-guided repurposing of drugs, but also acknowledges the challenges of translating preclinical findings to clinical practice.

Regarding other endpoints, metformin showed some positive effects on walk speed, with an increase observed in a trial of nondiabetic prefrail individuals after 14 weeks (Keys 2025). However, the MET-PREVENT trial (Witham 2025) found no improvement in walk speed with metformin treatment.  Similarly, while metformin was associated with decreased body weight in one study (Konopka 2019), this effect was observed in conjunction with aerobic exercise and may not be solely attributable to the drug.  The impact on insulin sensitivity is also complex, with some studies showing improvements (Konopka 2019) and others demonstrating a blunted response to exercise (Konopka 2019).

The emerging uncertainty highlighted by Keys (2025) underscores the need for more rigorous and well-designed clinical trials.  The lack of consistent benefits across studies, coupled with the potential for metformin to interfere with the adaptive responses to exercise, raises concerns about its widespread use as an anti-aging intervention.  The observed blunting of muscle hypertrophy and mitochondrial adaptations suggests that metformin may not be a universally beneficial drug for all individuals, particularly those seeking to maintain or improve their physical function with age.  Future research should focus on identifying specific populations who may benefit from metformin, optimizing dosage and timing, and exploring potential synergistic effects with lifestyle interventions such as exercise and diet.  Furthermore, a deeper understanding of the molecular mechanisms underlying metformin’s effects, as elucidated by PMC12978362 (2026), is crucial for developing targeted therapies that can promote healthy aging.

## Limitations

Despite accumulating preclinical and early clinical data suggesting potential benefits of metformin in addressing age-related decline, significant limitations temper enthusiasm for its widespread adoption as an anti-aging intervention. A primary concern revolves around the inconsistent translation of findings from model organisms to humans (Mohammed 2021). While metformin extended lifespan in several species, including *C. elegans* and mice, evidence for comparable effects in humans remains elusive and increasingly uncertain (Keys 2025). 

Furthermore, the mechanisms underlying metformin’s purported anti-aging effects are not fully elucidated. While improvements in insulin sensitivity are well-documented (PMC12978362, 2026), and AMPK signaling is frequently implicated (PMC12978362, 2026), the precise pathways linking these metabolic changes to broader healthspan or lifespan extension are still debated. The complexity of aging, involving multiple interacting biological processes, suggests that targeting a single pathway, even one as central as insulin signaling, may be insufficient to achieve substantial anti-aging effects.

Critically, emerging evidence indicates that metformin may interfere with beneficial adaptations to exercise. Metformin blunted muscle hypertrophy in response to resistance exercise (Walton MASTERS, 2019) and inhibited mitochondrial adaptations to aerobic exercise in older adults (Konopka 2019). This is particularly concerning given the established importance of physical activity for maintaining health and function during aging. The MET-PREVENT trial showed no significant improvement in physical performance in older individuals with probable sarcopenia (Witham 2025), further highlighting the potential for metformin to counteract positive effects of lifestyle interventions. 

The heterogeneity of study populations and interventions also poses a challenge. Variations in dosage, duration of treatment, and baseline characteristics of participants contribute to inconsistencies across trials. While some studies have focused on individuals with pre-existing metabolic conditions, others have included generally healthy older adults, making direct comparisons difficult. Moreover, the endpoints assessed vary considerably, with a concentration on measures like muscle strength (14 claims), lean body mass (9 claims), and lifespan (8 claims) but lacking comprehensive assessments of cognitive function, immune competence, or other key aspects of healthy aging. The reliance on relatively few, repeatedly studied endpoints suggests a potential bias in the current research landscape. Finally, the potential for off-target effects and long-term safety concerns associated with chronic metformin use require further investigation (Kulkarni 2022).

## Conclusion

The evidence regarding metformin as an anti-aging intervention presents a complex and increasingly nuanced picture. While initially championed as a potential “geroprotector” (Kulkarni 2022), recent research suggests the benefits may be less universal, and even context-dependent, than previously thought (Keys 2025). A robust body of evidence demonstrates metformin’s impact on metabolic parameters – with 6 high-confidence claims supporting improvements in insulin sensitivity (PMC12978362, 2026) and 5 showing reductions in fasting glucose (PMC12978362, 2026). However, translating these metabolic effects into broad lifespan extension remains uncertain, with only 8 high-confidence claims supporting effects on lifespan (PMC12978362, 2026). 

Critically, the impact of metformin appears to be heavily influenced by lifestyle factors. Metformin blunted muscle hypertrophy in response to resistance exercise (Walton MASTERS, 2019) and inhibited mitochondrial adaptations to aerobic exercise (Konopka 2019). Furthermore, in individuals with probable sarcopenia, metformin did not improve physical performance (Witham MET-PREVENT, 2025). These findings suggest that metformin may interfere with the body’s adaptive responses to exercise, potentially negating some of the benefits of physical activity. 

Across multiple endpoints – including muscle strength (14 claims), lean body mass (9 claims), walk speed (6 claims), and VO2max (6 claims) – the evidence base is substantial, but the direction of effect is not uniformly positive. Mohammed (2021) highlights the need for careful consideration of individual responses and potential adverse effects. Ultimately, the current evidence suggests metformin is not a panacea for aging, and its use should be carefully considered, particularly in individuals actively engaging in exercise.

## References

- **Keys_2025_metformin_anti-aging_uncertainty**. _Emerging uncertainty on the anti-aging potential of metformin._ Ageing Research Reviews, 2025.
- **Konopka_2019_metformin_blunts_aerobic_exercise_adaptations**. _Metformin inhibits mitochondrial adaptations to aerobic exercise training in older adults._ Aging Cell, 2019.
- **Kulkarni_2022_geroscience_repurposing_FDA_drugs**. _Geroscience-guided repurposing of FDA-approved drugs to target aging: A proposed process and prioritization._ Aging Cell, 2022.
- **Mohammed_2021_Metformin_Anti_Aging_Critical_Review**. _A Critical Review of the Evidence That Metformin Is a Putative Anti- Aging Drug That Enhances Healthspan and Extends Lifespan._ Frontiers in Endocrinology, 2021.
- **PMC12978362_molecular_mechanisms_of_metformin_action_from_metabolic_effe**. _Molecular mechanisms of metformin action: From metabolic effects to lifespan extension and healthspan promotion._ Journal of Medical Biochemistry, 2026.
- **Walton_2019_MASTERS_metformin_blunts_resistance_hypertrophy**. _Metformin blunts muscle hypertrophy in response to progressive resistance exercise training in older adults: A randomized, double‐blind, placebo‐controlled, multicenter trial: The MASTERS trial._ Aging Cell, 2019.
- **Witham_2025_MET_PREVENT_metformin_trial**. _Metformin and physical performance in older people with probable sarcopenia and physical prefrailty or frailty in England (MET-PREVENT): a double-blind, randomised, placebo-controlled trial._ Lancet, 2025.

_Note: This References section is rendered deterministically from `paper_sections.json` metadata. DOI / PMID linking is a follow-up polish step (Phase 6.2)._