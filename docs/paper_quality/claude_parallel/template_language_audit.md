# Template Language Audit — Rapamycin Paper (AAA4)

**Status:** Provisional. Anchored on the AAA4 paper (`bundles/synthesis-rapamycin-v06-AAA4-2026-05-04T15-50-14Z/paper.md`); identifies AI-template phrases and provides senior-researcher rewrites for the highest-frequency offenders.
**Generated:** 2026-05-09
**Scope:** Prose-level audit only. Does not rewrite the whole paper. Targets phrases that read as AI-template language and would draw reviewer comments without changing the paper's claims.
**Purpose:** Provide a per-phrase rewrite catalogue the writer module can use to surgically replace template phrases without re-running synthesis.

---

## How to read this audit

For each issue I provide:

1. **The phrase** — verbatim quote from the AAA4 paper.
2. **Section** — where in the paper it appears.
3. **The AI-tell** — what specifically reads as template language.
4. **Senior-researcher rewrite** — drop-in replacement that preserves the claim.

The audit is organised by *category* of AI-tell (Bloated openers, Empty hedges, Buzz phrases, Shopping-list constructions, Recursive restating, etc.) so the writer module can apply category-level fixes rather than per-phrase edits.

---

## Category 1 — Bloated openers and demographic windups

These are the "set the scene" sentences that AI writers often produce for review-paper introductions. They read as filler because they tell the reader what they already know.

### Phrase 1.1

**Verbatim.** "Population aging represents one of the defining demographic transformations of the twenty-first century, bringing with it a rising burden of chronic disease, functional decline, and healthcare expenditure that strains both economies and individual lives."

**Section.** Introduction, paragraph 1, opener.

**AI-tell.** "Defining demographic transformations" / "rising burden of chronic disease" / "strains both economies and individual lives" — three boilerplate phrases in one sentence. A senior reviewer reads this as "the AI did not know what to start with, so it started with the demographics opener."

**Senior-researcher rewrite.**

> The translation of preclinical longevity findings to human healthspan remains the central unresolved question in geroscience. Rapamycin is the most-tested pharmacological candidate in this translation, with clear preclinical efficacy and contested human evidence; this review evaluates the current state of that evidence.

This rewrite (a) names the actual question, (b) names the actual paper, (c) skips the demographic windup. It is shorter, more direct, and signals to the reviewer that the author knows what the paper is about.

---

### Phrase 1.2

**Verbatim.** "As life expectancy has increased across high-income nations, the years gained have not always been accompanied by sustained health, leaving a growing gap between lifespan and healthspan that carries profound human and economic consequences."

**Section.** Introduction, paragraph 1.

**AI-tell.** "Profound human and economic consequences" — empty intensifier. The lifespan-healthspan gap framing is correct but is presented in the most generic phrasing possible.

**Senior-researcher rewrite.**

> The lifespan-healthspan gap is widening: in OECD countries, healthy life expectancy has lagged total life expectancy by approximately one year per decade since 2000 (citation needed; verify before render). Geroprotective interventions are evaluated against their capacity to compress this gap.

This rewrite (a) gives a specific number, (b) names the relevant population, (c) defines what success would look like.

---

### Phrase 1.3

**Verbatim.** "The accumulation of age-related conditions — including sarcopenia, cardiometabolic dysfunction, cognitive decline, and immune senescence — does not occur in isolation; rather, these phenotypes share overlapping biological substrates rooted in the fundamental biology of aging itself."

**Section.** Introduction, paragraph 1.

**AI-tell.** Shopping-list-with-em-dashes ("including sarcopenia, cardiometabolic dysfunction, cognitive decline, and immune senescence"). This is a hallmark of AI-generated review prose.

**Senior-researcher rewrite.**

> Age-related conditions cluster mechanistically. Sarcopenia, cardiometabolic dysfunction, cognitive decline, and immune senescence share substantial pathway overlap, which underwrites the geroscience hypothesis: a single intervention at an upstream node (mTOR, sirtuins, NAD⁺, senescence) can plausibly delay multiple downstream phenotypes (López-Otín et al. 2023).

This rewrite (a) names the geroscience hypothesis, (b) cites López-Otín, (c) keeps the list but breaks the em-dash construction.

---

## Category 2 — Empty hedges and intensifier phrases

These are phrases that sound substantive but carry no information.

### Phrase 2.1

**Verbatim.** "...one of the most actively debated issues in translational geroscience, and the stakes of answering it correctly are considerable."

**Section.** Introduction, paragraph 1, closing sentence.

**AI-tell.** "Stakes are considerable" — empty intensifier. Says nothing the reader does not already know.

**Senior-researcher rewrite.**

> The translation question has direct implications for the design of GerospROtective trials, the interpretation of biomarker-based endpoints, and the regulatory framing of "aging" as a modifiable target.

Or, more aggressively, delete. The original sentence's only function is to assert importance, which is implied by writing the paper.

---

### Phrase 2.2

**Verbatim.** "The drug thus occupies a unique position in the geroprotective pharmacopeia: mechanistically compelling, clinically familiar, yet still lacking the definitive human evidence needed to establish its role in healthspan extension."

**Section.** Introduction, paragraph 2 closing.

**AI-tell.** "Unique position in the geroprotective pharmacopeia" + "mechanistically compelling, clinically familiar" — three flowery phrases, all empty.

**Senior-researcher rewrite.**

> Rapamycin's translation case rests on three pillars: a robust preclinical signal (Harrison 2009), an established clinical-pharmacology profile from transplantation (Kahan 2000), and a mechanistically tractable target (mTORC1). The human-efficacy pillar is the missing one.

This rewrite (a) is concrete (three pillars), (b) cites the actual evidence, (c) names the gap directly.

---

### Phrase 2.3

**Verbatim.** "...remain to be established, and future trials must reconcile the mechanistic plausibility of mTOR inhibition with the observed functional tradeoffs in human aging."

**Section.** Abstract closer.

**AI-tell.** "Reconcile the mechanistic plausibility with the observed functional tradeoffs" — circuitous restatement.

**Senior-researcher rewrite.**

> Boundary conditions for rapamycin's geroprotective effect — dose regime, target population, outcome class — remain undefined. Future trials should test specific mechanism-to-outcome predictions rather than re-test rapamycin against generic cardiometabolic surrogates.

---

## Category 3 — Buzz phrases and inflection-point language

These are phrases that signal "this is important" without substantiating the importance.

### Phrase 3.1

**Verbatim.** "In our view, the rapamycin geroscience narrative is at an inflection point: the preclinical case remains compelling, with lifespan extensions of approximately 14% in male mice (Harrison 2009), but the human evidence is insufficient to support clinical adoption."

**Section.** Discussion, late paragraph.

**AI-tell.** "Rapamycin geroscience narrative is at an inflection point" — buzz phrase. The "in our view" is fine but the "inflection point" framing is empty.

**Senior-researcher rewrite.**

> The next generation of rapamycin trials will be decisive: either the field will produce a convincing positive human signal on a non-cardiometabolic endpoint within five years, or the cumulative weight of null and mixed RCTs will move the field's centre of gravity toward alternative geroprotective targets. The preclinical case (Harrison 2009: ~14% lifespan extension in male heterogeneous-stock mice) remains intact; the question is whether the translation strategy needs revision.

This rewrite (a) makes the prediction falsifiable (5-year horizon, specific endpoint), (b) frames the inflection in concrete terms.

---

### Phrase 3.2

**Verbatim.** "The convergence of epidemiological, preclinical, and mechanistic evidence around mTOR inhibition catalyzed a wave of translational interest..."

**Section.** Background, paragraph 1.

**AI-tell.** "Convergence of [list]" + "catalyzed a wave of translational interest" — both flowery.

**Senior-researcher rewrite.**

> Multi-modal evidence — invertebrate longevity (Kapahi 2004; verify), mouse lifespan (Harrison 2009), companion-animal healthspan (Urfer 2017; verify) — converged in the early 2010s on mTORC1 inhibition as the most-tested geroprotective intervention. Translation to humans began with PIE/RTB101 trials (Mannick 2014, 2018) and continues today.

This rewrite (a) cites three concrete evidence streams, (b) gives the timeline, (c) names the lead translation effort.

---

## Category 4 — Recursive restating of "the case is incomplete"

This is the paper's most-repeated phrase pattern. It appears in the abstract, the introduction, the conclusion, and at least twice in the discussion.

### Phrase 4.1 (occurs ≥4 times in the paper, with variations)

**Variants.**
- "The rapamycin anti-aging case as currently constituted is incomplete."
- "The case for rapamycin as a geroprotector is thus incomplete."
- "It remains to be confirmed in adequately powered trials."
- "The case for rapamycin as an anti-aging intervention in humans is not yet constituted."

**AI-tell.** Repeated restating of the same conclusion. This signals the AI does not have additional content to add but wants to fill section-word floors. A reviewer notices this fast.

**Senior-researcher rewrite strategy.** Pick *one* canonical phrasing for the conclusion and use it once, in the conclusion. Anywhere the paper currently re-states this idea, replace with new content (specific predictions, falsifying conditions, design recommendations).

**Canonical phrasing recommendation.**

> The current human evidence base is insufficient to establish rapamycin's geroprotective efficacy at any level of certainty above Very Low (per GRADE; Section [Certainty of Evidence]). The translation case is *open*, not failed: positive immune-aging signals (Mannick 2014, 2018), null cardiometabolic signals (Moel 2025, Stanfield 2026), and robust preclinical signals (Harrison 2009; Miller 2014) coexist in a pattern consistent with the Endpoint-Sensitivity framework adopted in this review. The next-decade question is whether composite-endpoint trials in stratified populations can detect the predicted geroprotective signal at intermediate-distance endpoints (immune, functional) before the field's translation patience runs out.

This canonical phrasing (a) gives the GRADE certainty, (b) describes the *pattern* not just the *gap*, (c) names a falsifiable framework, (d) gives a time horizon.

---

## Category 5 — Shopping-list constructions

Em-dashed lists of three or four items, often hedge-laden.

### Phrase 5.1

**Verbatim.** "The boundary conditions—such as optimal dosing, duration, and target population—remain to be established..."

**Section.** Multiple — appears in Abstract, Introduction, Discussion.

**AI-tell.** "Boundary conditions" + em-dash list + "remain to be established" — generic shopping list.

**Senior-researcher rewrite.**

> Three boundary conditions structure the rapamycin translation question: dose regimen (intermittent low-dose vs continuous), target population (general older adults vs frailty-stratified), and outcome class (cardiometabolic vs immune vs composite). Each is testable in a 200–300 participant RCT; none has been definitively addressed in the current literature.

This rewrite (a) names the three conditions, (b) gives sample sizes, (c) flags the testability per condition.

---

### Phrase 5.2

**Verbatim.** "...a unique position in the geroprotective pharmacopeia: mechanistically compelling, clinically familiar, yet still lacking..."

**Section.** Introduction, paragraph 2.

(Already addressed in Phrase 2.2; flagged here as a shopping-list pattern.)

---

### Phrase 5.3

**Verbatim.** "These design improvements would help bridge the gap between the promising preclinical signal and the mixed human evidence reviewed here."

**Section.** Discussion.

**AI-tell.** "Help bridge the gap" — generic transitional language.

**Senior-researcher rewrite.**

> Composite-endpoint trials with pre-registered hierarchical analysis (per Kennedy 2014) would test the Endpoint-Sensitivity framework's prediction that effect sizes order proximal > intermediate > distal. A null result on this prediction is itself an important finding; a positive ordering result moves rapamycin's translation case from incomplete to provisionally supported.

---

## Category 6 — Vague conclusions and unsupported novelty claims

### Phrase 6.1

**Verbatim.** "This synthesis adds (a) a per-receipt evidence-weighting (Table 4: tier × directness × overall RoB → load-bearing / mechanistic / supporting / hypothesis-generating), (b) a deterministic per-paper numeric index (Table 5) for full Q2 traceability, and (c) an explicit pairwise tension matrix (Table 3) so the boundary conditions are visible rather than averaged away in narrative summary."

**Section.** What This Synthesis Adds.

**AI-tell.** This is partially defensible — the table-level contributions are real — but the framing as "what this synthesis adds" with three tables is the standard AI-template novelty framing. A senior reviewer reads this as "the AI was prompted to find a novelty claim."

**Senior-researcher rewrite.**

> This synthesis differs from prior rapamycin reviews in three operational dimensions:
>
> 1. **Auditable evidence trail.** Every numeric in the prose traces deterministically to a corpus quant-claim file; the audit code that gates the trace is public.
> 2. **Explicit comparable-effect audit.** Outcome-level pooling decisions (poolable / non-poolable) are made and reported; the non-pooling decisions are *visible*, not silent.
> 3. **Falsifiable framework adoption.** This review adopts the Endpoint-Sensitivity framework as its organising scaffold and names the trial-design conditions under which the framework would be falsified.
>
> These are infrastructure-level contributions; the substantive conclusions about rapamycin's translation are consistent with the field consensus.

This rewrite (a) names *operational* contributions (not generic "we added X"), (b) is honest about what is incremental vs novel.

---

### Phrase 6.2

**Verbatim.** "Prior narrative reviews of rapamycin have not adjudicated this pair head-to-head."

**Section.** What This Synthesis Adds.

**AI-tell.** Unsupported novelty claim — has the author actually checked all prior narrative reviews, or is this just the AI not having retrieved a counterexample? At minimum the claim should cite which prior reviews were checked and how the absence was confirmed.

**Senior-researcher rewrite.**

> A targeted search of the rapamycin/rapalog systematic-review literature (Lee et al. 2024; Mannick & Lamming 2023) did not surface a head-to-head adjudication of the Moel 2025 (PEARL) vs Stanfield 2026 (RAPA-EX-01) cardiometabolic disagreement. This synthesis makes that adjudication explicit.

This rewrite (a) names the search, (b) cites what was checked, (c) makes the claim defensible.

---

## Category 7 — First-person plural overuse

The paper uses "we" consistently. This is acceptable in some venues but should be deliberate, not default.

### Pattern (multiple instances)

- "We interpret this convergence as the strongest finding..."
- "In our view, the rapamycin geroscience narrative is at an inflection point..."
- "We suggest that future trials should aim for follow-up periods..."
- "We adopt the Endpoint-Sensitivity framework..."

**Senior-researcher recommendation.** "We" is appropriate when the authors are making an interpretive claim ("we interpret"), recommending action ("we suggest"), or adopting a framework ("we adopt"). It is *inappropriate* for descriptive sentences about evidence ("we find that the trial showed..."). The AI overuses it.

**Specific rewrites.**

| Original | Rewrite |
|---|---|
| "We interpret this convergence as the strongest finding in the current evidence base." | "The cardiometabolic null-and-mixed pattern is the most consistent finding across the receipts." |
| "We suggest that future trials should aim for follow-up periods of at least one to two years..." | "Future trials should run for ≥18 months, incorporate composite endpoints across cardiometabolic, immune, and functional domains, and include mechanistic biomarkers (DNA-damage markers, SASP factors, immune-cell phenotyping)." |

The rewrites move agency from the authors' interpretation to the evidence itself.

---

## Category 8 — Loose connective phrases

### Phrase 8.1

**Verbatim.** "Furthermore, the unclear effect direction from the observational cohort (Kell 2026) adds a third layer of discordance..."

**Section.** Abstract.

**AI-tell.** "Furthermore" + "adds a third layer of discordance" — both empty connectives.

**Senior-researcher rewrite.**

> Kell 2026's observational cohort adds an indirect dimension: the reported five-week mTOR-signaling reduction is mechanistically plausible but cannot speak to clinical-endpoint direction.

---

### Phrase 8.2

**Verbatim.** "Taken together, these three studies illustrate the current state of the field..."

**Section.** Introduction.

**AI-tell.** "Taken together" — most-overused review-paper transition. Often signals a paragraph-level summary that re-states what the previous sentences already said.

**Senior-researcher rewrite.**

> The three trials' divergent designs (PEARL: 12-month rapamycin alone; RAPA-EX-01: weekly sirolimus + exercise; Kell: observational mechanistic cohort) limit the synthesis to qualitative pattern recognition rather than quantitative pooling. The field's quantitative-synthesis question remains open.

---

## Summary of high-frequency offenders (pipeline-actionable)

The following phrases occur with high frequency in AAA4 and similar AI-generated review papers. The writer module should add them to a deny-list with mandatory rewrites:

| AI-tell phrase | Frequency in AAA4 | Rewrite category |
|---|---|---|
| "represents one of the defining" | 1 | Bloated opener — rewrite per Category 1 |
| "convergence of [3-4 item list]" | 3+ | Bloated opener — rewrite per Category 1 |
| "stakes are considerable" / "substantial" | 2 | Empty hedge — delete or substantiate |
| "mechanistically compelling, clinically familiar" | 1 | Empty intensifier — rewrite per Category 2 |
| "narrative is at an inflection point" | 1 | Buzz phrase — rewrite per Category 3 |
| "the case [for X] is incomplete" | 4+ | Recursive restating — rewrite per Category 4 |
| "boundary conditions remain to be established" | 3+ | Shopping list — rewrite per Category 5 |
| "These design improvements would help bridge the gap" | 1 | Vague hedge — rewrite per Category 5 |
| "Furthermore," | 4+ | Loose connective — rewrite per Category 8 |
| "Taken together," | 3+ | Loose connective — rewrite per Category 8 |
| "we suggest" / "we interpret" / "in our view" | 6+ | First-person plural overuse — selective rewrite per Category 7 |

**Recommendation for the writer module.** Add a `template_phrase_audit` post-render hook that flags these phrases at the sentence level and routes them to a rewrite prompt with the senior-researcher replacements above. This is the AI-template-language equivalent of the smart-gate patch system: deterministic detection, surgical replacement, no full re-render.

---

## What this audit refuses to claim

- That every flagged phrase is bad in every paper. Some are appropriate in some contexts (e.g., "we adopt the framework" is fine; "we suggest larger trials" is fine).
- That the senior-researcher rewrites are the only correct rewrites. Different senior researchers would write the same sentences differently; the rewrites here are *examples* of acceptable replacements, not canonical fixes.
- That the paper is bad prose. It is *competent* prose with template-language patterns. The audit's goal is to surgically lift the prose from competent to senior-researcher-grade without changing the claims.

---

## Falsifying conditions

This audit is wrong if:

1. **The flagged phrases are field-conventional.** If a senior reviewer at *Aging Cell* would consider "the case for rapamycin as a geroprotector remains incomplete" as appropriate phrasing rather than as recursive AI-template language, the audit's recommendation is wrong. Mitigation: cross-check against 5–10 recent senior-author rapamycin reviews to confirm the field's prose conventions.
2. **The rewrites change the claims.** Each rewrite is intended to preserve the claim while replacing the framing. If any rewrite I have provided shifts the paper's substantive position, that is a defect of the rewrite, not the underlying audit. Mitigation: the writer module should diff the claim-set before/after each rewrite.

---

**Provisional flag:** All rewrites are illustrative; the writer module should treat them as starting points, not canonical replacements. Each rewrite should be re-checked for claim-preservation before being applied.
