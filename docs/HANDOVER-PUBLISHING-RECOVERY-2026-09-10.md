# V3 standardized publishing — audit at 2026-09-10 21:52 Dubai

The shared fixes are deployed. **Publishing recovery and unattended cross-topic
repeatability are not yet proven.** Both VPS checkouts are clean at
`b3984ff6608c67da8c0a379d3a266b20d8d7e950`; the dashboard returned HTTP 200 and
all six publishing timers were restored. Deployment is not a public paper.

The user requested steps 1–5 with an audit after each, then explicitly rejected
manuscript-specific shepherding. Continue with shared engine rules, unchanged
source facts, normal review decisions and canonical submission history.

## Five-step audit

| Step | Evidence | Remaining condition |
|---|---|---|
| 1. Reconciliation | Bounded reconciliation is deployed. Earlier two real passes covered 80 distinct IDs in 57–58 seconds. The 17:06 UTC receipt completed in 52.065 seconds, with no runtime error and 205 deferred records. | The deferred backlog remains; do not equate a bounded successful pass with every historical record reconciled. |
| 2. Source records before prose | Shared source-role, comparator, direction and author-record rules pass focused checks. Five unchanged corpora compile without a crash. | Missing endpoint facts remain unknown. Do not promote an unknown direction or treat a protocol as completed efficacy evidence. |
| 3. Manuscript completeness | Two earlier ordinary full runs exposed reproducible shared defects in quote cleanup and URL word counting; both defects are fixed and regression checked. | Full training and semaglutide runs on the deployed code are active. No completed result on this release yet. |
| 4. Publishing contract | Actual public contract, latest Resveratrol decision, 15 recent ledger submissions and current semaglutide decision audited. | Public calibration is invalid and unbound to the current judge release. No calibrated-current-judge claim is supported. |
| 5. Production and repeatability | Both VPS copies have the same clean release, healthy dashboard and six active timers. | A new accepted public artifact and unattended repeatability remain unproven. |

## Shared changes and review

The runtime delta from `b8be7c45` to `b3984ff6` is 56 net added lines across 12
runtime files. There are no new runtime study-name or submission-ID overrides.

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

Latest release checks: **443 focused tests passed in 14.00 seconds; required
quality passed 347 checks; Ruff and typing passed (131 source files).** LOC,
complexity and duplication budgets were not raised. Logs:
`/tmp/v3-native-followups-{focused,quality,mypy}.log`.
The earlier 5,019-test run took 158.32 seconds and preceded these final follow-ups;
it is not a full-suite receipt for the final release. Repeated broad testing is
not required without a new relevant failure or change.

## Cross-topic validation on fixed code

All five source-only CLI preflights passed with source hashes unchanged. Receipt
counts below come from the canonical `receipt_funnel.json`, not the raw compiler
count in the temporary driver's entry record.

| Topic | Admitted receipts | Direct receipts | Current meaning |
|---|---:|---:|---|
| Resistance training | 19 | 12 | Full normal generation active; source-count requirements pass. |
| Semaglutide effects | 31 | 11 | Full normal generation active; existing Core revision must be respected. |
| Vaccine effects | 24 | 3 | Normal candidate policy blocks: direct-source floor is 4. |
| Plasma exchange adverse rates | 27 | 16 | Source preflight only; no new full manuscript result. |
| Senescence subgroups | 43 | 3 | Empty-excerpt crash fixed; normal direct-source floor still blocks. |

These are 144 receipt entries, not necessarily 144 distinct studies and not five
publishable papers. The temporary driver incorrectly labelled 29 raw plasma
records as admitted; the canonical admitted count is 27. The aggregate receipt
`.tmp/v3-standardized/native-followups-preflight-audit.json` uses the correct count.

Current runtime: `/tmp/v3-native-followups-20260910` on the VPS, fixed at `b3984ff6`.
The ordinary `_run_synthesis` path uses each topic's normal configuration, with
no review-type override, source edits or manual manuscript edits. Parent drivers
own the child exit status and persist `shared_native_receipt.json`; the bound is
10,800 seconds. This is a validation harness, not the production scheduler.

- Training started 17:27:48 UTC; driver 2410413, synthesis child 2410430.
- Semaglutide started 17:27:51 UTC; driver 2410414, child 2410702.
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

1. Collect the two complete native results without restarting or altering code
   merely to fit a manuscript. Review actual gates, source hashes and grounding.
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

Deployment receipt: `/tmp/v3-shared-fixes-deploy.log`. Discovery and review
receipts are under `.quality-reports/`, including fragment, scope/word-budget,
checkpoint, design-report and universal source-rule audits. These and
`.tmp/v3-standardized/` are local supporting artifacts, not tracked package files.
