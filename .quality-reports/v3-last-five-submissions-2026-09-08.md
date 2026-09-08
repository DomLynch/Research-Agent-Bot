# V3: Last Five Submissions and Repair Checklist

Audit date: 2026-09-08. Read-only production audit; no submissions, verdicts,
application code, provider settings or deployment jobs changed in this audit.
These are the five latest unique submissions, not five distinct topics.
The defect lists below summarize Core's stored reviews, not a new independent
source-by-source scientific adjudication.

## Decision and Feedback Receipt

| Submitted (Dubai) | Submission | Topic | Latest verdict | Required fixes | Revision allowed |
|---|---|---|---|---:|---|
| Sep 7 14:19 | 5011371c-05c8-487e-a312-3cdcc625a7c6 | Resveratrol | REVISE | 6 | Yes |
| Sep 6 18:15 | 59cf3989-08f8-45ee-9dd3-ee6739a5d139 | BNT162b2 | REJECT | 9 | No |
| Sep 6 17:46 | 3183d0a6-c4f6-4a7a-be1d-43522277ffff | Senescence | REJECT | 8 | No |
| Sep 6 17:04 | eac2d1ad-5c60-47e0-9182-c532a2e6e647 | Plasma exchange | REJECT | 9 | No |
| Sep 6 13:03 | 0eec3d87-6330-46fc-a37e-a5218a1c32fd | Plasma exchange, earlier | REVISE | 8 | Yes, but a newer same-topic rejection exists |

V3's live ledger contains all 40 corrections. Each list's SHA256 matches the
independent Core developer's fresh database extraction, using
`json.dumps(required_revisions, ensure_ascii=True, separators=(",", ":"))`.

| Submission | Matching SHA256 |
|---|---|
| 5011371c | 2961262d75b7cd5262a451bc1732a32acf4445f992f4d96d0fc2ee6d197fd27e |
| 59cf3989 | 31810e1e5fde0e9c019544f428a700bbaefa0861cb4cda281c9f8604ba746efe |
| 3183d0a6 | d09ddf21520ad0482a494b6b25b157c59674c16e4de8c508c2a5914d322b812f |
| eac2d1ad | c636d4e7d202f698a81bec32d8d592de04ab632d0a9accd393acc4cd216b6fc3 |
| 0eec3d87 | e2483a84ec3d95a01039fbd75619eb9092926274eb87a0e59b34ebaca4eb45f6 |

Live ledger: `/opt/research-agent-bot/runs/_daily_research_paper_ledger/_submitted_fingerprints.json`.
It contained 316 records at inspection. The submission list and decisions also
matched the independent Core last-five query.

## Does V3 Receive and Use the Feedback?

- Resveratrol: six request copies reference 5011371c. The latest inspected run,
  `synthesis-resveratrol_measurement_methods-v06-DAILY-2026-09-08T08-20-25Z`,
  contains all six exact corrections in `researka_revision_request.json`.
  All six are fully present in the text passed to the writer. No final manuscript
  or revision-coverage verdict exists in this failed run.
- BNT162b2: the nine current corrections are stored in the submission ledger.
  Older repair requests contain one technical DOI-reconciliation instruction,
  not this later nine-item editorial review. The latest inspected old repair
  started Sep 7 09:39 Dubai; Core's current review was created at 10:21 and its
  decision at 10:30. The timing does NOT establish dropped feedback.
- Senescence: eight current corrections are stored. No matching repair request
  was found. Core currently disallows resubmission, so not automatically retrying
  this rejected submission is correct behavior.
- Newer plasma: nine current corrections are stored; no matching new repair
  request was found. Its submitted manuscript carries the earlier submission's
  technical DOI request, not its own subsequent nine-item rejection.
- Earlier plasma: its one-item technical repair was marked covered and resubmitted
  as eac2d1ad on Sep 6. Core's current eight-item review was created Sep 7 10:33
  Dubai, after that resubmission. The old one-item pass does NOT mean eight
  scientific corrections were applied. Do not use the older allowed revision
  to evade the newer same-topic rejection.

All five current correction lists fit below the writer's 4,000-character cap:
1,469 / 2,812 / 2,301 / 2,613 / 3,097 characters respectively. Truncation is not
the explanation for these five failures.

## First Target: Resveratrol, Six Corrections

Owner: V3. All items remain open until checked in the final submitted payload.
Existing code improvements or intermediate logs are not completion evidence.

- [ ] R1: Correct Samaei 2020's Findings Map statistic and significance. Distinguish
  baseline balance from the source's negative-symptom endpoint; explain any recoding.
- [ ] R2: Rebuild the Quantitative Evidence Index using the cited study's own
  endpoint, arms/comparator, estimate, uncertainty and significance. Exclude
  background-study numbers, detached SDs and arbitrary p-value tokens.
- [ ] R3: Correct protocol-only, multi-ingredient, within-group and observational
  evidence roles; recalculate totals. Supply genuine source-quality assessments
  or remove unsupported decision-grade implications.
- [ ] R4: Correct cognitive allocation: separate Evans 2016 protocol from completed
  Evans 2017, Huhn 2018 and Zaw 2021 cognition studies; regenerate derived tables.
- [ ] R5: Reconcile 37 admitted versus 35 displayed records, including Rao 2025
  and Nikniaz 2023; calculate completeness from the final table, not a stale count.
- [ ] R6: Report real database yields, deduplication, screening process, full-text
  availability and non-admission reasons. Do not invent a 37/37/37 search funnel.

Completion evidence: final artifact/payload hash; each correction mapped to its
exact section/table row and supporting source or search record; no contradictory
prose/table versions; current revision coverage; then the normal Core decision.

## BNT162b2, Nine Corrections

Core must authorize the correction route before a revised submission is sent.

- [ ] B1: Reproduce and document the actual search, or describe a non-systematic
  curated-corpus synthesis honestly instead of claiming an unperformed search.
- [ ] B2: Reclassify all 66 sources, notably Wei 2023 and Placido 2022; regenerate
  all counts, direction profiles, boundary matrices and load-bearing lists.
- [ ] B3: Replace isolated p-values/claim counts with study-level quantitative
  records containing design, population, arms, endpoint, effect, CI and follow-up.
- [ ] B4: Correct the contextual/dosing null-dominance claim and separate genuine
  conflicting estimates from differences in population, endpoint or directness.
- [ ] B5: Give every exact Discussion statistic a local source trace, including
  the named Barda, Moreira, Vargas-Herrera, Yamamoto, Harris, Chiu and Nelli examples.
- [ ] B6: Perform design-appropriate risk-of-bias appraisal or explicitly remove
  decision-grade claims and describe the evidence as hypothesis-generating.
- [ ] B7: Align the question, adult/pediatric populations, geroscience scope and
  conclusions; do not imply direct aging outcomes absent from the corpus.
- [ ] B8: Remove broad booster recommendations or bound them to the studied
  populations, schedules, variants, comparators, endpoints and follow-up.
- [ ] B9: Remove the unsupported 200-per-arm/12-month recommendation or provide
  an endpoint-specific power calculation and defensible follow-up rationale.

## Senescence, Eight Corrections

Core owns reconsideration under the newer repairability policy. A narrower map
still must correct the evidence; acknowledging animal limitations is insufficient.

- [ ] S1: Document actual sources, queries, dates, deduplication, screening and flow.
- [ ] S2: Define a coherent eligible subgroup/population/intervention/outcome;
  re-screen 42 sources and separate unrelated or animal/contextual material.
- [ ] S3: Correct design, population, directness and outcomes, including Rotger,
  San-Millan, Diniz, Liu, Lutz and Cheung; regenerate derived counts and tensions.
- [ ] S4: Provide a source-linked quantitative index with design, population,
  comparator, endpoint, estimate, uncertainty, follow-up and quality judgments.
- [ ] S5: Source or remove frailty-prevalence numbers and the fixed study-size
  proposal; do not treat 12 months as substantiating a longevity endpoint.
- [ ] S6: Appraise source quality by study design and explain/use the tier taxonomy.
- [ ] S7: Rewrite Abstract and Conclusion to answer the bounded question and
  distinguish clinical actionability from mechanistic plausibility.
- [ ] S8: Replace unrelated pairwise comparisons with shared-construct comparisons,
  or label them evidence gaps rather than disagreements.

## Newer Plasma Exchange, Nine Corrections

Core must clarify the old review's route: item 1 permits a heterogeneous endpoint
map, whereas item 8 demands an adverse-event synthesis. A newer policy alone does
not rewrite that historical feedback. Material numeric errors still require repair.

- [ ] P1: Choose a supported endpoint-map scope or perform a genuinely safety-
  focused extraction with event definitions, denominators, severity and attribution.
- [ ] P2: Separate completed trials, observational studies, case series, protocols,
  reviews and mechanistic evidence; do not infer high quality from automatic labels.
- [ ] P3: Correct endpoint/value attribution throughout the quantitative index,
  including Gubensek, Marrodan, Boada and Davies; retain complete source traces.
- [ ] P4: Correct direction coding and distinguish intervention effects from
  prognostic associations, background citations, feasibility and biomarker findings.
- [ ] P5: Replace the cross-disease acute-mortality 'longevity conflict' with
  indication- and estimand-matched comparisons or explicit evidence gaps.
- [ ] P6: Provide the real retrieval-to-inclusion disposition and exclusion reasons.
- [ ] P7: Perform design-appropriate quality appraisal and use it in the conclusions.
- [ ] P8: Make Abstract, Results, Discussion and Conclusion agree with the selected
  supported scope and explicitly report whether usable safety rates exist.
- [ ] P9: Separate human outcomes, biomarkers, reviews and preclinical evidence;
  correct Khamis 2020's mechanistic classification.

## Earlier Plasma Exchange, Eight Corrections

These remain relevant evidence requirements, not permission to bypass the newer rejection.

- [ ] E1: Specify the adverse-event estimand or make an evidence-gap map explicit
  in title, eligibility, Abstract, Results and Conclusion.
- [ ] E2: Reconcile selection counts and record-level inclusion/exclusion reasons.
- [ ] E3: Separate study design, topic/outcome/population directness and actual
  quality appraisal instead of universal A1/direct labels.
- [ ] E4: Correct endpoint/value/arm attribution, including Cegolon, Stahl,
  Marrodan and Gubensek; delete quantitative rows without sufficient support.
- [ ] E5: Correct intervention-direction coding, including adjusted-null results
  and citations of earlier studies; recompute profiles and tension rankings.
- [ ] E6: Add a safety table, distinguishing reported events from missing reporting
  and qualitative reassurance; do not infer zero events from absent reporting.
- [ ] E7: Distinguish independent studies from repeated publications of the same
  trial, particularly AMBAR; maintain study and publication denominators.
- [ ] E8: Make Abstract and Conclusion state the limits on a transferable adverse-
  event rate while describing the specific completed safety evidence accurately.

## Current Operational and Policy Gaps

- V3 active prompt import reports `reviewer-v13-repairability`.
- GET https://api.researka.org/contracts/current returned HTTP 200 and
  `reviewer-v15-explicit-repairability`. The common 4/5 acceptance floor remains;
  the newer explicit bounded evidence-map repair rule is not mirrored in V3's
  current prompt. Treat alignment as a concrete follow-up, not proof it explains
  all historical verdicts.
- Live logs show repeated `Codex writer timed out after 180s`; the latest inspected
  Resveratrol run did not finish a manuscript. This is separate from Core's reviews.
- Live `/opt` was `cf2fbd85` at inspection. `b3f8907f` and its configured deadline
  change were queued for lock-protected deployment, not yet proven live.

## Execution Order and Stop Conditions

1. Finish the already tested deployment without editing a checkout mid-run;
   verify the effective writer deadline and one completed writing call.
2. Align active V3 instructions with Core's published policy without weakening
   evidence or acceptance requirements.
3. Complete R1-R6 on one frozen Resveratrol source set. Mark each done only with
   final-payload evidence. No new full draft merely to claim activity.
4. Submit that verified revision through Core's permitted parent route once;
   record the new decision and reopen only explicit unresolved material findings.
5. Core separately reassesses the old terminal rejections and contradictory
   correction routes. V3 must not bypass `resubmission.allowed=false`.

## Audit Coverage and Checks

- Discovery: knowledge playbook/AAA and local repository instructions; three
  distinct Semble searches for decision retrieval, saved feedback and repair
  consumption; CodeGraph traced shared gate/report and revision entry points.
- Pass 1: five latest V3 ledger IDs/counts/feedback hashes matched Core's independent
  DB extraction. Executable assertions: 5/5 lists, 40/40 corrections.
- Pass 2: inspected request files, historical lineage, gate contents, prompt
  assembly/cap, live policy import and writer logs; Core confirmed the historical
  review timestamps. Resveratrol brief: 6/6 complete; final manuscript absent.
- No source edits, new model calls, live resubmissions or production mutations in
  this audit. A full test-suite rerun would not establish repair of these papers.
- Profilers, AST mutation/coverage tools and an index rebuild were unnecessary:
  this was a bounded state/feedback audit, not a new code or performance change.
