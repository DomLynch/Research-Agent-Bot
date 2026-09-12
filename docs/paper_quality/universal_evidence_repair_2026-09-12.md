# Universal evidence repair — audit record, 12 September 2026

Status: the main repair is deployed at `d25972bd`; audited table-prefix and endpoint follow-ups are awaiting an idle worker for deployment. The resistance-training resubmission and publication outcome remain pending.

## Scope and source receipt

Core submission: `9d8747ec-87a8-4b82-977b-eba1b607b33b`, reviewed REVISE on 11 September.
Frozen evidence: `synthesis-resistance_training-v06-DAILY-2026-09-11T06-02-04Z`.
Production baseline: `57cad401bd8c65f11d470446f0b884366ce0f31e`.

Success requires corrected source records, regeneration, verification of the final outgoing manuscript and source bundle, one normal revision submission, and an observed reviewer/publication outcome. Deployment or a test pass alone is insufficient.

## Audit pass 1: reproduce the reported defects

1. Selection: 3,255 retrieved records and 19 admitted sources are recorded at different stages; no complete prospective full-text screening chain is established. The existing selection ledger and exclusions are rendered as a curated evidence map, with no PRISMA-ScR designation. No exclusion counts are invented. Full-length section floors remain unchanged.
2. Directions: numeric-only extraction discarded qualitative outcomes and let baseline balance imply a null finding. The shared extraction now retains source-owned endpoint clauses, binds the reported direction and any unambiguous p-value to that clause, and preserves mixed favorable/null findings. Unknown endpoints or ambiguous comparisons remain unclear. There are no study-name or submission-ID branches in runtime code.
3. Directness: shared-background interventions and combination-versus-usual-care designs do not identify the effect of one component. Randomized status alone does not establish direct target evidence. Explicit target-only and multigroup controls remain covered by regression checks.
4. Statistics: Claussen's exact beta/CI values exist in the frozen abstract but the submitted excerpt previously selected another section. QEI proposals now use a source passage that can travel in the publication bundle. Full results remain available to the semantic judge to detect contradictions. Unsupported figures are omitted; source files and estimates are never altered to make them pass.

The frozen-record replay rebuilt the following classifications through the normal receipt builder, retaining all 19 source identities:

| Source | Previous direction → rebuilt | Previous directness → rebuilt |
|---|---|---|
| Zhang 2025 | unclear → positive | direct → direct |
| Denben 2023 | unclear → unclear | indirect → indirect |
| Salter 2024 | unclear → positive | direct → indirect |
| Longrak 2024 | unclear → positive | direct → direct |
| Lander 2026 | unclear → positive | indirect → indirect |
| Jacob 2025 | unclear → unclear | indirect → indirect |
| Hwang 2018 | unclear → mixed | direct → indirect |
| Fan 2024 | unclear → positive | indirect → indirect |
| Claussen 2025 | unclear → positive | direct → direct |
| Lee 2024 | unclear → positive | indirect → indirect |
| Arroniz 2025 | unclear → unclear | direct → direct |
| An 2025 | unclear → positive | direct → direct |
| Lai 2023 | null → positive | direct → direct |
| Oh 2023 | unclear → positive | direct → direct |
| EVALUATION of ONLINE AEROBIC 2023 | unclear → unclear | direct → direct |
| Kang 2025 | unclear → unclear | protocol → protocol |
| Expanding Access to Strength 2025 | unclear → unclear | direct → direct |
| Chen 2026 | unclear → mixed | direct → indirect |
| Kenville 2024 | unclear → unclear | direct → indirect |

The existing QEI was independently revalidated: 15 rows retained, four rows omitted because their complete result/design support was absent from the publishable passage. The retained table passes the outgoing source-trace check. This is a component replay, not the final regenerated manuscript or a Core acceptance.

## Audit pass 2: adversarial and integration checks

- Changed endpoint, source, estimate, confidence interval, significance, comparison, or missing supporting passage fails the outgoing table check.
- Formatter-only P/p changes and correctly quoted ± dispersion remain valid.
- Tables outside the Findings Map/QEI are checked; bare untraced estimates cannot bypass validation. Author-generated extraction-count statements and selection counts remain subject to the separate ledger/manifest checks; they are not estimates from a cited study.
- Small numeric magnitudes do not imply a null effect: changing units cannot change the classification. Explicit nonsignificant outcomes retain null; contradictory significance statements stay unclear.
- Background studies, protocols, baseline balance, hypothetical statements, and another endpoint's p-value cannot supply an outcome direction.
- Global review instructions unlock only the requested classification fields and their derived endpoint/source-clause records. Frozen source identity, unrequested tier, and other contract fields remain locked.
- Existing whole-suite checks exposed stale expectations for source markers and newly retained qualitative endpoints. Expectations were updated only for those intentional outputs, preserving tests of source identity and background exclusion.

## Release checks and live outcome

Release checks on deployed `d25972bd`: 5,109 tests passed, 2 xpassed, 16 warnings (160.76 seconds); `make quality` passed (347 checks, Ruff, complexity with no new/worsened findings, duplication and unchanged LOC budgets); mypy passed across 180 source files. Changed quantitative-cell/source negative controls, source classifications, selection framing, and ordinary submission preparation were audited. No source-ID exception or gate/budget increase was introduced. The withdrawn apply_patches experiment is absent from the final diff.

The older resistance-training revision finished on the pre-repair baseline without submission: all four coverage asks remained unmet. The first normal worker after deployment selected an older HPV revision. It is still drafting; it is not the requested resistance-training validation. A one-shot operational wrapper will select the canonical resistance-training request through the existing `run_cycle` revision-loader seam, retaining all history caps, source locks, semantic review, and submission gates.

## Follow-up endpoint audit

The source-level `mixed` label concealed an incorrect endpoint sign: "greater reductions in fat mass" was read as an increase. The shared vocabulary and endpoint binding now preserve the reduction. Explicit muscle-area increases are recognized; Longrak becomes positive. Chen remains mixed with favorable fat-mass and strength outcomes and a null hypertrophy outcome. Contradictory significance, overlapping endpoint aliases, multiple comparisons, scientific-notation p-values, and adjusted p-values have focused negative/positive controls. These are general parser rules, not source-specific runtime cases.

A replay of all 19 frozen sources regenerates a Findings Map with no unbound rows. Fifteen revalidated QEI rows pass the outgoing check; four unsupported rows are omitted. An exact `finding=` rendering prefix is normalized without changing the quoted source text. Final follow-up release check: 5,123 passed, 2 xpassed, 16 warnings in 164.51 seconds. `make quality` passes (347 tests, Ruff, no new/worsened complexity or duplication, unchanged LOC ceilings); mypy passes across 180 source files. The final focused significance-parser checks pass (77 tests).

Production handoff: the six publishing timers are temporarily paused to allow the active HPV worker to finish before the next deployment. No worker was interrupted. Restore all six timers after the targeted normal revision is launched, or before ending work if deployment cannot proceed. No new acceptance or publication has been observed.

## Source-review input audit follow-up

The September 12 regenerated manuscript stopped locally at Abstract 125/150
words. Its recorded preparation diff showed loss before final review. Two
regressions reproduced: the semantic statement selector omitted uncited scope
sentences later removed by cleanup, and the prose reviewer reused the QEI source
selector, which excluded studies without numerical abstract results. The frozen
Zhang abstract documents randomized allocation but was absent from that packet.

Prose review now includes Abstract/Conclusion sentences and uses the existing
verified revision evidence reader for every retained source, including complete
source sections and tables. Citation identity remains tied to the frozen
registry. The policy clarifies intervention attribution versus the original
study's direct comparison. Existing negative, altered-text, corrupted-snapshot,
and stale-policy checks remain fail-closed. No word floor, source classification,
review verdict, provider, budget, or runtime LOC limit changes.

Audit pass 1: both input regressions failed before the change and passed after it;
62 focused prose and universal evidence tests passed. Audit pass 2: reviewed
source identity, negative decisions, cache invalidation, and downstream cleanup;
quality (347 tests), type checks and unchanged complexity/LOC gates passed.
The live replay and Core decision require separate receipts.

## Final outgoing manuscript audit

The real outgoing gate caught issues beyond the general 14/14 audit: remaining
unclear result profiles, four rendered claim-count metadata cells, a protocol's
proposed follow-up presented as a finding, and an author Methods source count
misread as an external effect statistic. No submission was sent.

The general fixes preserve numeric comparison signs while removing XML tags for
classification, recognize plural null findings and comparative gains, separate
contrasting result clauses, and distinguish improved adverse endpoints from
increased adverse endpoints. Demographic balance stays population context;
significance on another endpoint cannot establish a result. Actual frozen Jacob,
Arroniz, remote-training, Zhang and protocol records extend the regression set;
metformin and direction/negation controls cover broader behavior.

Receipt/source wording variants share the existing metadata rule. Protocols use
the recorded claim summary rather than future numerical recommendations. Methods
source-count adjectives use the existing corpus-count treatment; patient counts
and percentages remain quantitative claims, and changed author counts cannot
reuse a prior semantic approval.

Audit pass 1 reproduced these failures from the exact outgoing body. Audit pass
2 checked baseline balance, adverse-outcome polarity, cross-endpoint significance,
XML numeric signs, protocol attribution and changed-count approval invalidation.
The rebuilt table projection passes the complete outgoing quantitative trace.
This is component proof, not a regenerated manuscript or a Core decision.

Final exact local checks for this outgoing-gate follow-up: 5,166 passed, 2 xpassed,
16 warnings in 156.59 seconds; 122 focused regressions passed. `make quality`
passed with 347 gate tests, no new/worsened complexity or duplication findings,
and unchanged LOC budgets. Mypy passed for 181 source files. Runtime changes
contain no author, submission-ID, or paper-specific branches.

### Final preparation audit: presentation equivalence

The 15:18 UTC normal rebuild preserved all 19 frozen sources and regenerated the
corrected profiles. Its final gate stopped before submission. Auditing the actual
preparation diff and source review found three general presentation defects:

- Adjacent author citations acquired bundle markers and spaces, invalidating the
  approval key for two supported Abstract sentences. The key now normalizes only
  missing adjacency spacing before known source labels; changed wording, source
  sets and citation placement still invalidate approval.
- The methodology gate treated `not a systematic scoping review` as a positive
  self-claim. Explicit local negation is excluded; positive claims and `not only`
  claims remain blocked when stronger than the declared review type.
- A source's `P =.23` and the rendered `P = 0.23` were treated as different claim
  contexts. Leading-zero decimal presentation now matches while numbers,
  operators, endpoints and comparators remain bound to the authentic passage.

Three distinct Semble queries and CodeGraph localization preceded each affected
surface. For citation handling, queries covered approval keys, bundle rendering,
and changed-claim tests. For methodology, queries covered negated review types,
self-claim qualifiers, and gate tests. For numeric binding, queries covered
source-bound contexts, leading-zero rendering, and changed-comparator tests.
The exact query receipts are in `.quality-reports/universal-publishing-context.md`.

The real citation renderer regression failed before its fix. The methodology and
decimal regression group reproduced four failures before those fixes. All 300
focused checks then passed. A deterministic replay restored the original writer
Abstract from the recorded preparation diff: both approved sentences survive,
the rejected unqualified power sentence remains excluded, and all outgoing
quantitative table checks pass. The replay does not replace full pipeline review
or constitute a Core submission. Runtime LOC and scientific thresholds are unchanged.

Final presentation-fix verification: 5,181 tests passed, 2 XPASS and 16 existing
warnings in 157.12 seconds; `make quality` passed with no new/worsened complexity
or duplication findings and unchanged LOC limits; mypy passed 181 source files.
The 300 focused checks and actual frozen-run preparation replay passed before
release. Live final review, Core resubmission and public publication remain
separate outstanding evidence at this checkpoint.

### Final source-profile audit

The final semantic revision check still blocked three source profiles despite the earlier local pipeline pass. A replay against all 19 frozen records reproduced unclear labels for Denben, Kenville and the online three-arm RCT. Shared endpoint definitions, source-local abbreviation expansion and endpoint-start direction binding now recover their own reported outcomes. Neutral cortisol polarity stays unknown; changed and null outcomes produce a mixed source profile. The online trial reports favorable comparative point estimates but does not supply uncertainty for those contrasts: these are descriptive directions, and the classification criteria explicitly distinguish them from significance. Its separate aerobic memory trend (p=.065) stays unclear. No numerical values, source identities, review verdicts or thresholds were changed.

Two audit passes covered authentic source records and adversarial cross-topic controls: missing/zero/negative estimates, explicit negation, reported nonsignificance/CI, source-local abbreviation conflicts and neutral biomarker polarity. Full tests:5187passed,2XPASS,16warnings,seed69495797. Type-only clarifications subsequently passed97focused checks; mypy agent scripts181files passed. Quality passed347checks with unchanged complexity, duplication andLOC ceilings. The randomized vocabulary fixture now restores replaced modules as well as environment, fixing the independently reproduced CI contamination defect.

These are implementation and component receipts. Normal regeneration, final outgoing correction verification, Core review and public publication remain separate live acceptance checks.


## Final manuscript audit follow-up

The source classifier received complete own-study results, but writer receipts
filtered out findings not recognized by the numeric extractor. Receipt generation
now supplies every identified own-result excerpt. A real-source regression proved
the missing cognitive contrasts were absent before the fix and present afterward;
claim counts and extracted statistics remain unchanged.

QEI proposal and review now require one endpoint and comparison per row, allowing
paired baseline/follow-up values for before/after comparisons. Estimates spanning
distinct measures under one endpoint label must be split into exact source clauses
or omitted. Review cache fingerprints now bind both proposal and review policies,
so an old approval cannot survive changed rules. Regression tests reproduced stale
approval under both changed policies before the fix. Shared publication guidance
retains source abbreviations unless their definitions are supplied.

First review checked source identity, frozen contracts, exact-span requirements,
normal negative-review handling and unchanged numeric/classification gates. Second
review checked cache reuse/invalidation, before/after comparison preservation and
the repair controller's exclusive lock plus author hold before submission.
No source-specific runtime exception or publication threshold change is included.
Live manuscript repair and Core publication require separate receipts.

The final audit also reproduced an outcome-summary omission: `build_thesis`
truncated each direction to its two most common outcome classes. It now renders
all observed classes in frequency order, retaining one label per class. Three
regression cases cover positive, negative and null summaries with a third class
that the previous implementation omitted. This changes generated summaries, not
source classifications, counts, evidence or acceptance thresholds.


## Recorded Methods and external audit follow-up

The Methods summary read only receipt-funnel counters while the retrieval table
read the frozen retrieval audit. With no flat retrieval counter, this produced
"Recorded stages: none" alongside a recorded 3,255-record pool. The builder now
uses the audit's recorded retrieval count when the flat count is missing. It does
not convert extraction counts into screened/excluded counts or infer historical
record-level linkage. Incomplete-flow prose states this boundary explicitly.
Eligibility now identifies retained protocols as planned-study context, never
completed-outcome evidence, matching the existing protocol classification.

The Arroniz discrepancy reported by a literal-number probe is decimal presentation:
the frozen abstract contains P =.23, P <.01 and P =.06; the manuscript adds leading
zeros. The scientific values are unchanged. Source-owned endpoint, comparator and
confidence-interval support still require the ordinary final outgoing check.

## Malformed reviewer responses

The final replay reproduced `prose_semantic_review_invalid`: JSON parsing succeeded,
but the assessment schema failed outside the established technical fallback path.
Prose and QEI review now explicitly number their input rows and validate assessment
coverage inside that existing path. Strict schema checks remain after the call;
a valid negative assessment returns immediately and never triggers fallback.
The existing attempt limits and the prohibition on paid writer fallback are unchanged.

HTTP-transport regressions exercise malformed-primary/negative-fallback, a valid
negative primary, and exhausted malformed responses. They also verify exact numbered
inputs and unchanged source context. The first audit checked these boundaries and
cache validity; the second checked all callers, type checking, runtime LOC and
complexity. No manuscript-specific retry, approval or threshold is introduced.
