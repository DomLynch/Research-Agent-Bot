# Rapamycin Paper Gap Analysis - 2026-05-09

## Decision

The rapamycin L6 certification is valid for trust-spine reproducibility, but
the current representative paper is not yet top-tier aging-journal ready.
The next sprint should treat it as a candidate manuscript, not a platform
demo.

## Evidence Base

- Current representative run: `runs/synthesis-rapamycin-v06-PATHA10-2026-05-07T09-38-47Z`.
- Current certified state: `AAA / L6`, `14/14` audit, 16 receipts, 72
  high-confidence claims, 31 non-orthogonal tensions.
- Current local corpus after classifier refresh: 287 parsed records; 18
  core, 96 background mechanism, 39 adjacent clinical, 134 off-thesis.
- Current receipt funnel: 287 quant-claim files; 154 active/classified
  candidates; 16 accepted high-confidence receipt papers; 49 candidate papers
  with no claims, 89 candidate papers with partial/none-only bindings.
- Fresh hardening run:
  `runs/synthesis-rapamycin-v06-WORLDCLASS-P0C-2026-05-09T2026-05-09T07-48-06Z`
  reached internal `AAA / L5`, `14/14` audit, journal-surface pass, and no
  unresolved P1/P2 reviewer issues after the patch-boundary guard.
- External field benchmark: Lee, Hodzic Kuerec, and Maier's 2024 Lancet
  Healthy Longevity systematic review screened 18,400 unique articles and
  included 19 human studies on rapamycin/rapalogs for aging-related outcomes:
  https://www.sciencedirect.com/science/article/pii/S2666756823002581
- External framework benchmark: Mannick and Lamming's 2023 Nature Aging review
  centers the mTORC1-benefit versus mTORC2-toxicity boundary and low/intermittent
  dosing translation:
  https://pmc.ncbi.nlm.nih.gov/articles/PMC10330278/
- External methods benchmark: the 2022 musculoskeletal systematic review
  emphasizes heterogeneity in age, indication, and dosing protocols in human
  rapamycin/rapalog evidence:
  https://pmc.ncbi.nlm.nih.gov/articles/PMC9637607/

## Desk-Rejection Risks

1. Public manuscript surface can drift from stored run verdicts. PATHA10 failed
   under the current local journal-surface gate for methods/meta prose and
   public slug artifacts. Fresh renders must be judged by today's gate; the
   P0C hardening run now clears that internal surface gate.

2. Methods/provenance drift. PATHA10 includes operational provenance in the
   public body and stale commit/run language. Public Methods should describe
   evidence handling only; audit machinery belongs in appendices and artifacts.

3. Corpus depth is below review-article expectations. Retrieval has enough
   breadth, but receipt qualification admits only 16 papers. The bottleneck is
   claim binding/extraction, not search.

4. Receipt role and outcome labels need correction pressure. Surrogate
   biological shifts must not be rendered as clinical benefit; preclinical
   species must not be labeled as adult human populations.

5. RoB/GRADE are scaffold-level. Table 4 currently derives risk labels from
   tier/directness, not source-text Cochrane RoB 2 / ROBINS-I signaling
   questions.

6. Meta-analysis posture is incomplete. The paper correctly avoids pooling, but
   it needs a comparable-effect audit explaining which outcome families are not
   poolable and why. Pooling should be added only where effect measures are
   genuinely comparable.

7. Field engagement is thin. Mannick, Lamming, Kennedy, Kaeberlein, Selman, and
   Blagosklonny need to appear as field positions, not just names in citations.

8. Cross-paper synthesis is too matrix-first. The 31-pair matrix should move to
   supplemental support; the public paper needs the top 4-5 clinically meaningful
   tensions narrated with dose, population, endpoint, and follow-up context.

## 72-Hour Priority

1. Regenerate a fresh rapamycin paper under current gates and fail it honestly
   if surface/provenance issues remain.
2. Use `receipt_funnel.json` to attack the extraction/binding bottleneck before
   expanding retrieval terms.
3. Replace public Methods/provenance with manuscript-facing evidence handling.
4. Add a not-poolable audit before attempting meta-analysis.
5. Add named field-engagement and a falsifiable organizing framework.
6. Promote top-5 tension narratives; keep the full matrix supplemental.

## Not Fixable Honestly in One Pass

- Claiming a Cochrane-grade systematic review without dual screening,
  PROSPERO-style protocol registration, and source-text RoB/GRADE.
- Claiming universal clinical benefit from rapamycin from surrogate or
  preclinical evidence.
- Reaching 60-80 receipts by search expansion alone; current data show the
  limiting gate is high-confidence claim qualification.
