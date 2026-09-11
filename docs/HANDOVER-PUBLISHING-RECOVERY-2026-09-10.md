# V3 standardized publishing — continuation audited 2026-09-11

The shared fixes are deployed. **Publishing recovery and unattended cross-topic
repeatability are not yet proven.** Both VPS checkouts are clean at
`49d1c12031b3f3cd8d62bb0ede83799471205c4f` (runtime code commit); the dashboard returned HTTP 200 and
all six publishing timers were restored. Deployment is not a public paper.

The user requested steps 1–5 with an audit after each, then explicitly rejected
manuscript-specific shepherding. Continue with shared engine rules, unchanged
source facts, normal review decisions and canonical submission history.

## Five-step audit

### Current continuation, September 11

The ordinary fresh run started September 10 at 23:43:57 on `b92dd6e7` and selected
`telomere_cardiovascular_effects` itself. Its first manuscript completed in 1,733
seconds with local `publication_ready`, but the publishing bridge blocked it:
`researka_claim_trace_insufficient:cited=11/11,aligned=8/11,required=9`.
Its subsequent attempts failed quality gates. The scheduler mislabeled those
valid negative outcomes `synthesis_failed`, so systemd restarted the whole cycle
after its bounded attempts ended. Later ordinary selection also tried resistance
training. Local readiness did not establish publishing eligibility.

The last observed fresh cycle ended at 09:26:55 Dubai with zero submissions. A
temporary `Restart=no` hold allowed that worker to finish without another restart;
no active manuscript was interrupted. All six loaded publishing workers were
then verified idle before deploying `49d1c120` to both clean VPS checkouts. The
temporary hold was removed, the original fresh one-topic/10,800-second override
was preserved, and all six timers were verified active at 09:28:36. The prior
fresh failure and drought failure remain visible; neither was reset to fake health.

The shared fix distinguishes software failure (`local_gate_execution_failed`,
CLI exit 70, visibly failed without restart), a quality rejection after bounded
retries (`local_gate_blocked`, no-submission exit 3), and transient failure (exit 2).
It adds no runtime LOC. Audit: 16 focused tests, required quality 347, Ruff and
typing passed. A real systemd diagnostic verified software exit 70 stays failed
with zero restarts. CLI mutation and cycle tests preserve transient retries and
bound repeated quality failures. Deployment: `/tmp/v3-gate-exit-deploy.log`;
checks: `/tmp/v3-gate-exit-{focused,quality,mypy}.log`.

The remaining publication blocker is scientific repair integrity. A frozen
resistance-training payload reproduces exactly `cited=16/16,aligned=15/16` when
the original verified grounding context is loaded. The failing claim combines
different study arms into a contradiction. The original writer distinguished
the groups but expanded their abbreviations incorrectly; reviewer patch P03
removed one qualifier, and P04 was applied through the repair loop, leaving a
partial contrasting clause. The final publication block is valid and remains.
The exact replacement proposed during that repair was not retained in the log,
so do not claim the precise deletion mechanism has been established.
The source is frozen at
`runs/synthesis-resistance_training-v06-DAILY-2026-09-10T23-02-48Z`; inspect its
`debug/full_paper.review_patches.json`, `debug/full_paper.review_patch_log.json`,
`prose_grounding_review.json`, and `researka_preflight_input.json` together.
An initial replay omitted grounding context and returned 4/16; it is invalid as
a production-equivalent result and was superseded by the exact 15/16 replay.

No manuscript, source fact, threshold or reviewer outcome was overridden. The
public feed checked after midnight still listed August 15 as V3's latest public
publication. A new accepted public artifact and cross-topic repeatability remain
unverified; steps 3 and 5 must not be marked complete.

### Step status

| Step | Evidence | Remaining condition |
|---|---|---|
| 1. Reconciliation | Bounded reconciliation is deployed. Earlier two real passes covered 80 distinct IDs in 57–58 seconds. The 17:06 UTC receipt completed in 52.065 seconds, with no runtime error and 205 deferred records. | The deferred backlog remains; do not equate a bounded successful pass with every historical record reconciled. |
| 2. Source records before prose | Shared source-role, comparator, direction and author-record rules pass focused checks. Five unchanged corpora compile without a crash. | Missing endpoint facts remain unknown. Do not promote an unknown direction or treat a protocol as completed efficacy evidence. |
| 3. Manuscript completeness | Shared rendering fixes now reach completed, locally ready manuscripts through ordinary production selection, including the September 10 19:45:59Z telomere run. | Publishing preflight still rejects unresolved scientific claims. The training trace identifies loss of study-arm distinctions during reviewer repair; repair integrity remains open. |
| 4. Publishing contract | Actual public contract, latest Resveratrol decision, 15 recent ledger submissions and current semaglutide decision audited. | Public calibration is invalid and unbound to the current judge release. No calibrated-current-judge claim is supported. |
| 5. Production and repeatability | Both VPS copies have the same clean release, a responding dashboard and six active timers. The September 11 09:26 fresh cycle ended with zero submissions; its quality failure now maps to a bounded no-submission outcome instead of an automatic whole-cycle restart. | A new accepted public artifact and unattended repeatability remain unproven. Missing certification artifacts, unmet revisions and scientific checks still block available runs. |

## Shared changes and review

The runtime delta from `b8be7c45` to `a41bee86455f2a68be983dee55a49345eee67870`
is 253 added and 201 deleted physical lines: 52 net added lines across 15 runtime
files. The preceding release was 42 net lines; an older running note incorrectly
said 56. There are no new runtime study-name or submission-ID overrides.

- Evidence directions use source-owned outcome findings. Significant benefit or
  harm alongside explicit null endpoints can be mixed. Baseline, population,
  dose, duration and protocol records cannot establish an outcome. Missing
  endpoint mappings and ambiguous p-value bounds remain unclear.
- Randomized contrasts determine what an intervention trial isolates. A target
  given to both arms does not make a randomized adjunct effect direct evidence
  for that target. Configured aliases and source-defined abbreviations work
  without named-study exceptions; dose comparisons remain distinguishable.
- Protocol/design/baseline reports stay contextual through classification,
  outcome refinement, Findings Map and final rendering, including when upstream
  structured metadata calls them randomized trials. Frozen real-source fixtures
  and completed-trial controls cover this path.
- The actual research question and Methods records exist before the Abstract.
  The same question is persisted and used by the grounding reviewer. Mixed or
  unknown populations are described as the populations represented by admitted
  sources; the majority population no longer excludes retained minorities.
- Generic text cleanup no longer interprets `vs. a` inside a source quotation as
  a broken sentence and deletes through a decimal. Table rows, abbreviations,
  decimal values and table spacing are preserved. Previously corrupted evidence
  still fails its evidence gate; the gate was not suppressed.
- Shared section word counting counts prose and link labels, excluding URL
  destinations. The Abstract cap remains 300 words, Results floor 400 and
  Conclusion floor 180. A 301-word Abstract still fails; a 399-word Results
  section cannot clear its floor by adding a long URL.
- Reviewer wording that a named source remains miscoded despite contrary findings
  authorizes only the requested direction field. It does not unlock other source
  fields or apply a source-specific runtime correction.

Audit passes included baseline failure reproduction, real-source replay, anonymous
IDs, negative controls, propagation review and source-hash verification. The
quote-corruption trace identified `strip_sentence_fragments` as the actual writer
of the damaged text. No original validation manuscript was manually corrected.

Preceding release checks: **553 focused tests passed in 12.79 seconds; required
quality passed 347 tests; Ruff and typing passed for both changed modules.** The
preceding release also passed typing across 131 source files. LOC,
complexity and duplication budgets were not raised. Logs:
`/tmp/v3-locator-and-arms-{focused,quality,mypy}.log`.
The earlier 5,019-test run took 158.32 seconds and preceded these final follow-ups;
it is not a full-suite receipt for the final release. Repeated broad testing is
not required without a new relevant failure or change.

## Sixth-topic production audit and shared finalizer recovery

The ordinary fresh service selected `telomere_cardiovascular_effects` itself at
22:20 Dubai. Its source preflight admitted 32 receipts, including 4 direct and
5 primary-tier receipts. Run:
`/opt/research-agent-bot/runs/synthesis-telomere_cardiovascular_effects-v06-DAILY-2026-09-10T18-22-59Z`.
The run generated and reviewed a manuscript, then exited 7 after 2,390 seconds
with `local_gate_execution_failed`: finalization did not converge in 40 passes.
Its controller incorrectly treated this software failure as writer-fixable and
started R2. After independently verifying the service invocation and process
family, that redundant retry was stopped. No submission occurred in R1.

Root cause: `_hedge_preclinical_translation` treated punctuation inside a DOI URL
as a sentence ending and inserted a caveat inside the link. Subsequent cleanup
truncated the URL; source-trace repair then appended another locator each pass.
The fix masks URL spans for sentence-boundary detection while preserving original
text offsets. A shared surface helper removes incomplete repeated locator
prefixes only when the complete surviving URL matches that prefix. The helper is
used by both writer finalization and ordinary publisher repair. No iteration
limit, evidence gate, word floor, reviewer decision or model setting was relaxed.

The scheduler now reads the existing benchmark exit receipt, preserves the exact
software error, stops that cycle and does not regenerate the same or another topic
after `local_gate_execution_failed`. Transient synthesis retries remain covered.

Two replay audits used an isolated copy and the frozen source snapshot. The first
ran the Stage 5 callback plus finalizer; the second used ordinary
`_repair_existing_run`, which finished in 3.34 seconds without a model call.
Both produced manuscript SHA256
`a64f2008f8d5188bde236d5beeae3645615d8944c517c09d7af26c325e55b930`.
The only manuscript change was deletion of 1,053 characters representing 39
incomplete locator prefixes. All 66 frozen source files, the manifest and numeric
quarantine were unchanged. Surface checks pass; a second finalization changes
nothing. The local overall verdict still does not certify journal readiness.

An earlier local diagnostic accidentally used the default corpus directory and
quarantined three extra claims. That diagnostic is invalid as a native receipt.
It only affected an isolated copy and was superseded by the frozen-source replay.

Latest relevant checks: 914 passed / 2 existing XPASS before the small extraction;
16 targeted regressions passed after simplification; 433 finalizer, surface and
consistency tests passed after wiring ordinary repair. Required quality passed
347 tests; Ruff, typing, LOC and complexity passed without raised budgets.
Logs: `/tmp/v3-finalizer-{focused,regression,shared-repair-focused,quality}.log`
and `/tmp/v3-finalizer-{mypy,shared-mypy}.log`.
Replay receipts: `.tmp/v3-standardized/frozen-source-finalizer-replay.json` and
`.tmp/v3-standardized/ordinary-repair-replay.json`.
Deployment: `/tmp/v3-shared-recovery-deploy.log`, both checkouts clean at `a41bee86`,
dashboard HTTP 200, six timers restored.

At 23:29:29 Dubai the normal `research-agent-paper-daily-submit.service` was
started with its unchanged configuration and canonical ledgers, without a forced
candidate. It finished at 23:30:52 with `no_eligible_research_paper`, zero submitted,
zero published (exit 3, accepted by the existing service contract). The canonical
receipt is `/opt/research-agent-bot/runs/_daily_research_paper_ledger/2026-09-10.json`.
It considered 179 run records: 105 missing required artifacts, 28 topics already
consumed in the window, 15 failed surface checks, 15 unverified/unmet revision
coverage, 13 audit failures, 2 final-status failures and 1 preflight-QA block.
These are run records, not 179 distinct papers or independent experiments.

The sixth-topic R1 still lacks the final surface, verdict and pre-submit gate
files because its production run stopped before writing them. The ordinary
publisher correctly refuses that incomplete certification set. The isolated
repair receipt proves manuscript recovery; it does not fill the production
certification gap or bypass the full quality gate. R2 remains an incomplete,
stopped generation. No original production manuscript was manually patched.

The next acceptance check is a complete ordinary run on the deployed fix, followed
by its real Core decision and public artifact. Existing timers remain active.
Do not report steps 3/5 or publishing recovery complete from the repair or test
receipts alone.

## Cross-topic validation on fixed code

All five source-only CLI preflights passed with source hashes unchanged. Receipt
counts below come from the canonical `receipt_funnel.json`, not the raw compiler
count in the temporary driver's entry record.

| Topic | Admitted receipts | Direct receipts | Current meaning |
|---|---:|---:|---|
| Resistance training | 19 | 12 | Native b398 run completed; final generic arm-label fix makes this 13 direct. |
| Semaglutide effects | 31 | 11 | Writer timed out; existing Core revision must be respected. |
| Vaccine effects | 24 | 3 | Normal candidate policy blocks: direct-source floor is 4. |
| Plasma exchange adverse rates | 27 | 16 | Source preflight only; no new full manuscript result. |
| Senescence subgroups | 43 | 3 | Empty-excerpt crash fixed; normal direct-source floor still blocks. |

These are 144 receipt entries, not necessarily 144 distinct studies and not five
publishable papers. The temporary driver incorrectly labelled 29 raw plasma
records as admitted; the canonical admitted count is 27. The aggregate receipt
`.tmp/v3-standardized/native-followups-preflight-audit.json` uses the correct count.

Validation runtime: `/tmp/v3-native-followups-20260910` on the VPS, preserved at `b3984ff6`.
The ordinary `_run_synthesis` path uses each topic's normal configuration, with
no review-type override, source edits or manual manuscript edits. Parent drivers
own the child exit status and persist `shared_native_receipt.json`; the bound is
10,800 seconds. This is a validation harness, not the production scheduler.

- Training ran 17:27:48–18:01:01 UTC, exited 0, 13,299 final words and 22 writer calls.
- Semaglutide ran 17:27:51–17:52:22 UTC, exited 9: a Codex writer call exceeded 600 seconds.
- Both source-hash checks passed. Both process families finished; neither was submitted.
- No paid fallback, timeout increase or blind full-manuscript restart was applied.
- Logs: `/tmp/v3-followups-full-{resistance_training,semaglutide_effects}.log`.
- Outputs: `runs/synthesis-{topic}-followups-full-20260910` under that runtime.

The vaccine full run was an avoidable harness mistake: it bypassed the existing
normal candidate-policy check before drafting. After independently confirming
`direct_receipts_below_floor`, only its inspected process family was stopped at
17:46:26 UTC. The controller recorded exit -15 and unchanged source hashes. This
is a negative eligibility result and an incomplete manuscript, not a completed
full validation. No production worker was stopped. Receipts:
`/tmp/v3-vaccine-ineligible-{process-audit,stop}.json`.

The previous native training/semaglutide runs at `5b17ab66` both completed with
local gate exit 7. Training's Abstract counted 40 URL components as words;
semaglutide's source quote was corrupted by generic cleanup. Their local
scientific reviews were respectively REVISE 26/30 and ACCEPT 27/30. These are
local reviews, not Core decisions. Source hashes were unchanged and neither was
submitted. Their actual negative results led to the shared fixes above.

## Final shared audit after native completion

The broader comparator audit found that bare dosage, intensity and group labels
were being mistaken for named alternative interventions. These labels no longer
establish an adjunct contrast. Named adjunct trials still classify as indirect.
Source-defined shorthand such as `resistance group` now resolves from `resistance
training` when followed by a group/arm label. A real three-arm online exercise
RCT exposed this omission and is now a frozen regression fixture.

Read-only A/B compilation across all five frozen corpora changed exactly one
field: that online exercise trial became direct instead of indirect. Every
receipt ID was preserved; the other four topics had no changed compiled records.
This does not rewrite the b398 manuscript or its frozen contracts. Receipt:
`.tmp/v3-standardized/v3-anonymous-arm-five-topic-replay.json`.

The completed training manuscript initially failed submission preflight:
`researka_claim_trace_insufficient:cited=24/25,aligned=18/25,required=20`.
Its 27 stored semantic assessments were all supported; policy, source, context
and reviewed-input hashes matched. A diagnostic identified a shared identity
bug: uppercase DOI locators added to the rendered manuscript were not stripped
when the reviewed source used lowercase, so identical reviewed claims lost their
approval keys. The checker now treats the cited DOI locator's letter case as
presentation. Scientific text, different sources and negative decisions remain
strictly bound and have regression coverage.

An unchanged-manuscript replay of that shared checker change moved the complete
submission preflight from the trace failure to `eligible` in 0.416 seconds.
Manuscript SHA-256 remained
`f2c73f0b1abdd92ffc2ed0eda030ffe4ba0a551e4af31e7c6526a03ec90e211c`.
No model was asked to revise its decision, no threshold was lowered, and no
submission occurred. Receipt:
`.tmp/v3-standardized/v3-doi-locator-native-replay.json`.

This is a genuine generic gate correction, but not a final-release public-paper
receipt: the separate arm-label correction changes one retained source's role,
so the earlier native manuscript cannot certify that final source classification.
Use the normal production pipeline for the next full generation and review.

## Canonical publication state

Latest Resveratrol submission `237883b1-d115-4f1b-8a6d-190874cf6144` is
REVISE / REVISE_TECHNICAL / NOT_PUBLISHED. Its three asks concern source direction
labels and stale Methods scope. No individual manuscript was edited to force
these through after the user's cross-topic correction.

Semaglutide submission `dfb5094a-d15d-424f-9906-bcaf2c5de37c`, refreshed at
17:51:22 UTC, remains REVISE / NOT_PUBLISHED, with resubmission allowed. Its
intake failures identify a protocol used as primary evidence and unmatched DOI
citations. Empty `required_revisions` does not mean no blocker: inspect
`gate_failures`. Full receipt: `/tmp/v3-semaglutide-canonical-decision.json`.
Do not submit the new validation manuscript through an empty isolated ledger.

The earlier production training R2 at
`runs/synthesis-resistance_training-v06-DAILY-2026-09-10T15-44-01Z-R2` returned local
`publication_ready`, but the normal bridge blocked submission with
`researka_claim_trace_insufficient:cited=20/20,aligned=14/20,required=16`.
Grounding review identified real unsupported age and outcome details. Preserve
that block. Local readiness alone is not submission readiness or publication.

The 19:41 Dubai audit of 15 recent distinct canonical-ledger submissions found
8 REVISE, 7 REJECT and no fetch errors. This dated sample is not a success-rate
measurement for the new release or all of Core's history.

Public contract: https://api.researka.org/contracts/current
Submission policy v2, reviewer-v15-explicit-repairability; research syntheses
require 120 characters per required section, at least 2,000 body words and
12 citations. `/public/contracts/current` was the wrong route, not an outage.

Public calibration: https://api.researka.org/calibration
The exposed July 16 evaluation has `valid=false`, incomplete metrics, invalid
timeline, no human signoff and no binding to the current judge release. Its 13/30
result is not current-judge accuracy. The current release references a different
freeze receipt. Core, website, model and provider configuration were not changed.

## Continuation and operating constraints

1. Native results and final shared source/identity replays are collected. The
   next full generation must use the final shared release through normal policy;
   do not manually rewrite the earlier paper or its frozen evidence records.
2. A completed eligible candidate may use the ordinary production publisher,
   canonical lock and ledgers. Preserve prior REVISE/REJECT history, remote
   deduplication, scientific checks and the frozen package. A dry-run selection
   returns before final publishing checks and is not proof of eligibility.
3. Inspect Core's actual decision and public artifact after any real submission.
   A valid negative remains blocking; do not relabel it as a recovery success.
4. Refresh this handover with final native outcomes and remaining blockers.

Actual service names are `research-agent-paper-{fresh,revise,reconcile,prepare,
daily-submit,drought-guard}.service`. Require `LoadState=loaded` when checking
idle state; nonexistent `research-agent-bot-fresh.service` returning inactive is
not evidence. Read worker state separately before any code deployment.

The prepare worker last exited 75 after waiting 900 seconds for its lock; the
unit treated this as failure and retried. No unit-status workaround was applied.
The drought guard correctly reports the lack of public publication since August
15. Do not clear it merely to create a healthy-looking dashboard.

Deployment receipt: `/tmp/v3-final-shared-deploy.log`. Discovery and review
receipts are under `.quality-reports/`, including fragment, scope/word-budget,
checkpoint, design-report and universal source-rule audits. These and
`.tmp/v3-standardized/` are local supporting artifacts, not tracked package files.
