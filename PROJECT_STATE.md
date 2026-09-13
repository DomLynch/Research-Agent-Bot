# PROJECT_STATE.md

## Final Review and Admission Rendering - 2026-09-13
Methods now renders the original candidate assessment and the current retained-source
assessment. The complete intermediate history stays in the source decision log;
no historical decisions are invented or discarded. This replaces the earlier
cleanup exemptions: both prose deduplicators and the surface gate retain their
normal behavior. Three topic fixtures verify stable rendering and mismatch rejection.
The source reviewer skips empty lines while still checking short unsupported claims.

The corrected 13:49Z resistance-training revision has 45 supported substantive
source statements, no unsupported statements, and passes both normal revision asks.
The exact frozen package and Core preflight pass without outgoing text changes.
The normal dry run selects it as eligible, linked to parent d85c342d.
The previous real submission attempt sent nothing because duplicated Methods
paragraphs failed the surface gate; this rendering correction resolves that failure.
Submission acknowledgement and Core publication remain separate verification steps.
Validation: 370 focused tests and 5,362 full-suite tests pass (2 xpassed);
quality and mypy pass with unchanged LOC budgets.

## Source Sentence Spacing - 2026-09-13
The 13:49Z linked revision cleared the abstract floor but stopped before submission:
Core preflight inserted one missing space in a source finding, invalidating the
frozen payload. Shared source typesetting now performs that normalization before
final review. It matches Core's exact cleaned body and is stable on a second pass;
raw evidence, quantities and approval requirements remain unchanged.
Validation: 516 focused checks and 5,358 full-suite tests pass (2 xpassed),
with quality and mypy passing. Renewed review and Core acceptance are separate.

## Final Source-Row Review - 2026-09-13
Shared writing targets are 220–260 words for the Abstract and 400–500 for
the Conclusion, leaving repair margin while acceptance gates remain unchanged.
Findings Map rows now enter the existing source reviewer as complete displayed
rows, including direction, directness and finding. Unapproved rows block Core
preflight. Review runs again after the final repair pass, then the exact package
is frozen with its updated claim-support state. Changed rows invalidate approval.
The primary reviewer rejected the original MCI row and accepted the regenerated
row against identical evidence; a separate audit accepted all 19 regenerated
rows in three requests below the unchanged 300,000-character limit.

Numeric drift extraction no longer splits alphanumeric identifiers into numbers;
standalone values and attached recognized units remain checked. This addresses
the observed quarantine of `20E` as numeric `20`. The completed 13:15Z run still
failed locally with Abstract 139/150 words and submitted nothing. The scheduler
started another normal linked revision at 13:49Z on the previous release.
These code changes, their deployment and Core acceptance remain separate states.
Release verification: 5,355 tests passed, 2 xpassed; quality, mypy across 183
source files, and both import boundaries pass without budget increases.

## Comparable Findings and Delivery Recovery - 2026-09-13
Core received parent-linked revision `d85c342d-f646-4012-a89b-7ee4c6d04413`
and requested two scientific corrections: an unmatched-intervention contrast
and a Findings Map row displaying the alternative arm's result. The earlier
admission/coverage requests did not recur. This is REVISE, not publication.
Normal identical retry reconciled Core's 409 to that submission ID and cleared
the uncertain-delivery ledger. Submission acknowledgement timeout is 180 seconds;
an observed response previously took 96 seconds, exceeding the old 60 seconds.

The shared matrix excludes indirect-only pairs from target-intervention
direction conflicts. Reported direct-source contrasts require comparator review.
Findings retain contiguous own-result context without requiring every sentence
to contain a recognised statistic. Export preserves complete source fields when
both abstract context and fuller Results are needed; each field must trace to
the frozen record. Heterogeneity totals now use the displayed table's domains.
Removed unsupported reviewer-name absence boilerplate. Gates and budgets remain
unchanged. Frozen-run replay retains 19/19 source proofs and all 19 admitted rows;
new generated contribution text no longer asserts the Chen/Denben conflict.
An old manuscript's already-written headline still needs normal revision;
code deployment, fresh manuscript review and Core acceptance remain separate.
Final validation: 5,349 tests passed, 2 xpassed; quality, mypy (183 source files),
both import boundaries and unchanged LOC/complexity budgets pass.

## Author-Record Quantities - 2026-09-13
Quantitative preflight now recognizes uncited non-empirical Methods statements
with a current, exact author-context review. It no longer requires the
manuscript source count to appear in an external study. Cited/empirical effect
quantities still require matching source evidence, including when a prose judge
incorrectly approves them. Count edits or changed Methods records invalidate
author approval. Full suite: 5,344 passed, 2 xpassed; 396 focused and 51 isolated
VPS checks pass, as do quality and mypy. Every preflight and frozen-package check
passes on the exact final manuscript in the isolated live-data replay.

## Mixed-Evidence Scope Rendering - 2026-09-13
The finalizer no longer inserts a blanket review-level/causal/policy disclaimer
merely because direct and indirect studies coexist. The Findings Map retains
actual classifications and scientific review still checks each claim. This
removes the stock text that submission preparation stripped and finalization
reinserted. The exact latest-run replay is idempotent with complete source
accounting and a passing surface check. Three-topic regression and existing
zero-direct/null guard tests pass: 673 focused; full suite 5,339 passed,
2 xpassed. Quality and mypy pass. Core review remains required.

## Quantitative Source Handoff - 2026-09-13
Source projection ranks recorded sections by QEI quote coverage, then complete
receipt findings, so an early abstract summary cannot hide fuller result passages.
Quote and typed-statistic checks normalize source typesetting and preserve
complete adjacent-sentence context. Mutated values, operators, comparisons and
noncontiguous passages remain blocked. Focused checks: 879 passed; full suite:
5,336 passed, 2 xpassed. Quality, mypy and both import boundaries pass with
unchanged budgets. Exact latest outgoing table replay: 27 rows, zero failures;
19/19 source proofs remain valid. Changed evidence invalidates prior prose review
as intended; fresh review and Core submission are separate remaining steps.

## Revision Parent Handoff - 2026-09-13
The cycle now persists its complete revision request before synthesis. This
fixes the ordering regression where final payload freezing encountered the
writer's feedback-only sidecar before the parent was attached. The writer keeps
the full request unchanged. Three-topic checks invoke that real helper and
serialize the parent before synthesis returns; focused cycle: 481 passed,
2 xpassed; full suite 5,330 passed, 2 xpassed, quality and mypy pass.
Publication still requires all normal outgoing checks and Core review.

## Scoped Revision Discovery - 2026-09-13
Explicit revision topics now restrict direct decision polling before its time
budget is consumed by unrelated submission history. Whole-history reconciliation
keeps its existing fair polling. Scoped lookup failures remain explicit, even
when another record succeeded; an incomplete discovery is no longer reported as
an empty revision queue. Regression cases span three topics and 257 unrelated
records, with both explicit and run-derived topic metadata. Focused cycle checks:
478 passed, 2 xpassed; full suite 5,327 passed, 2 xpassed. Quality and mypy
pass. No scientific gate, polling deadline or round cap changed.

## Explicit Revision Topic Selection - 2026-09-13
The revise CLI now honors an explicit topic by filtering source records before
choosing a pending request. A missing matching request stops without rotating
to another topic. A request with a known submission ID cannot borrow a different
known parent through title matching; historical records with no submission ID
retain the existing title-based recovery behavior. Normal revision budgets,
source locking and submission gates remain active.
Focused cycle checks: 470 passed, 2 xpassed, including same-title cross-topic
collisions and absent requested revisions. Full suite: 5,319 passed, 2 xpassed;
quality 347 passed, mypy 183 files, unchanged complexity and LOC limits.
The VPS cycle suite passes 470 tests in an isolated checkout. An earlier run
in the live checkout exposed tests reading production revision history through
an import-bound default; the offline fixture now isolates that default too.
The initial unfiltered service invocation selected another frozen revision and
was stopped before submission. This is not proof of a fresh duplicate or of a
completed resistance-training revision.

## Shared Revision Rendering and Lineage - 2026-09-13
Findings Map rendering now uses the public header that the final surface gate
accepts, so late table regeneration cannot undo the earlier header repair.
Admission Methods use a readable decision-log label and derive assessed,
excluded and included counts from the recorded dated decisions. Historical
retrieval totals remain separate; no missing screening history is invented.
Submission refuses missing/conflicting revision parents and no longer allows a
manually selected changed payload to become an unlinked fresh duplicate while
the topic is pending or has recorded revision feedback.
The exact September 13 resistance-training draft passes the full text-phase
surface check and source-admission check, and is stable on a second pass.
Full regression: 5,306 passed, 2 xpassed; the final focused check including an
additional empty-request case passes 403 tests. Quality, mypy and both Import
Linter boundaries pass; diff-cover is report-only (18 executable changed lines,
100% covered). These are local receipts, not Core acceptance or publication.


## Retained Writer Repairs and Bounded Revisions - 2026-09-09
Writer retries retain validated sentences and request only missing/corrected
content. Exhausted sections now fail explicitly instead of emitting placeholders;
source support, numeric validation and strict final section checks remain required.
Review and repair prompts share a valid JSON contract, and reviewers receive
source excerpts rather than just evidence labels. Final minimums are 400 words
for Results and 180 for Conclusion; higher writing targets remain unchanged
(Conclusion retry threshold 250, prompt target 280-380).
The revise service now limits both topics and review rounds to one per 10800-second
cycle. Previously one round per topic still allowed several papers to consume the
same deadline. A deadline recheck after preparation prevents starting synthesis
with an already exhausted budget. Timeouts and unmet scientific corrections can
still block an individual paper; these changes do not establish publication.

## Full-Context Revision Verification - 2026-09-08
Revision judging now receives the complete manuscript, frozen source sections and
tables, and outgoing payload fields. A deterministic keyword pass cannot override
a semantic failure. Coverage receipts bind all asks, manuscript, evidence and
payload; missing or stale receipts cannot be recertified by the finalizer or
submission refresh. Enrichment changes are checked against the actual outgoing
payload. Explicit class-wide evidence-role corrections can authorize only the
requested fields for source-verified classes; identities remain frozen.
Offline Resveratrol replay: the complete-context Terra check improved from 0/6
to 1/6 after existing deterministic repair (missing Findings Map rows). This is
not a completed manuscript repair or publication receipt. Live v15/600-second
timeout deployment completed at 16:20 Dubai; this verification patch is separate.
Local verification: 4,661 passed, 38 skipped, 2 xpassed; quality 343 passed,
Ruff/mypy and unchanged LOC/complexity/duplication budgets passed.
Authorized recoding does not prove scientific correction: the multi-ingredient
Resveratrol record still remains A1/direct in the receipt regeneration canary.

## Configured Writer Deadlines - 2026-09-08
Two live Sol calls stopped at the configured 180-second limit. The section
wrapper now respects the configured provider timeout plus 60 seconds of headroom,
instead of cancelling every longer call at 240 seconds. Deployment targets
`WRITER_TIMEOUT_SEC=600`; existing per-cycle budgets and scientific gates stay
unchanged. The legacy shared timeout setting also bounds extractor/judge calls.
Local verification: 4,753 passed, 2 xpassed, 16 warnings (seed 909); quality,
mypy and LOC checks passed. Independent cancellation/retry audit passed.
Deployment and a complete live manuscript still need separate receipts.

## Source-Bound Revision Repairs - 2026-09-08
Primary-outcome declarations now take precedence over incidental statistic counts;
background-study results do not set the current study's endpoint directions.
Explicit protocol metadata takes precedence over a topic-pack trial hint, and
review-authorized outcome corrections refresh their derived endpoint fields.
The quantitative evidence index excludes detached SDs, baseline-balance results
and duplicate source statements. Findings Map statistics must match the cited
source clause, including outcome and comparator, in the final outgoing payload.
This is not a universal semantic validator for every table or prose paragraph.
Offline Resveratrol replay preserved 37 source identities/proofs; the regenerated
Findings Map passes this payload check and is unchanged by a second repair pass.
Numeric source titles are treated as bibliography only in the unique Source
column; the same text in a finding still requires source support. Repairs respect
the actual table header and preserve repeated annotation columns by position.
The randomized suite passed 4,751 tests (seed 909), with 2 xpasses and 16 existing
warnings. Quality, type and unchanged LOC gates passed. A pre-existing randomized
test failure was localized to leaked topic globals and fixed in test teardown.
Independent review passed after checking signed statistics, comparator positions,
escaped table cells, duplicate maps and source-label/bundle-index agreement.
The core patch is deployed at `cf2fbd85`; the table-layout follow-up has separate
local checks and an independent PASS (74 focused tests), not a deployment receipt.
The normal Resveratrol recovery failed before submission at 12:04 Dubai time:
the configured Codex writer call exceeded 180 seconds. A scheduled revision is
running separately; no new publication or complete manuscript repair is proven.

## Source Attribution and Shared Review Policy - 2026-09-07
Writer sections, final review, patch repair and revision coverage now consume
`reviewer-v13-repairability`: all six categories require at least 4/5, supported
claims and no unresolved major issues. Optional style suggestions do not block.
Result tables quarantine quotations describing other studies; protocols and
case series are no longer promoted by references to earlier randomized trials.
Authorized classification corrections preserve the revision's source identities.
Offline Resveratrol replay removed three unowned result rows and preserved
payload idempotence; this does not establish publication or replace normal review.
Fresh checks: 4,667 passed, 2 xpassed, 16 warnings (seed 907); Ruff and mypy pass.
`make quality` passed with no new/worsened complexity or clone findings and
278 focused tests. Pytest randomization is now enabled by the dev dependencies;
profiling remains optional. One earlier order-sensitive finalizer-test failure
did not reproduce in the final suite and remains unlocalized.
Deployment and the corrected submission require separate live receipts.

## Refactor Verification - 2026-09-05
The backed-up simplification gives post-review repair one bounded finalizer
controller, then refreshes derived artifacts from the settled manuscript.
Publishing selection is read-only; preparation and submission are explicit,
with shared legacy-ledger projections and the existing submission lock.
Scientific thresholds, provider routing and schedules are unchanged.

Backup: `~/Desktop/_ARCHIVE/V3-2026-09-05/Research Agent Bot backup 2026-09-05.dgPgrd`.
Checks and audit: `~/Desktop/_ARCHIVE/V3-2026-09-05/Research Agent Bot Audit - 2026-09-05`.
These are pre-deployment checks, not a live publication receipt.
Live recovery still requires a representative writer run and public outcome.

## Canonical Checkout and Revision Gates - 2026-09-05
Run V3 commands from `/Users/domininclynch/Desktop/Business/Research Agent Bot`.
The archived backup is an ancestor; its only dirty test change already exists here.
Revision refresh decisions already share `agent/revision_contract.py:gate_report`.
Keep the wrappers' distinct contracts: finalizer returns whether its sidecar changed;
submission returns whether verification completed. Their behavioral regression tests
cover matching verdicts, stale approvals, failed verification, idempotence and locks.
Optional diagnostics include a generated lifecycle test; randomization requires
explicit `-p randomly`. No provider, schedule or publication threshold changed.

## Writer Route - 2026-09-05
Implemented writer target is `gpt-5.6-sol` with High reasoning through Codex CLI
and the service user's ChatGPT login. Terra Medium reviews through Codex; GLM
review fallback remains on OpenRouter. Codex runs without tools, hooks, project instructions,
or inherited provider keys; timeout/cancellation kills and reaps its process group.
Subscription failures stop the writer, never trigger a paid writer fallback. Token usage
and subscription billing are recorded; zero API cost does not mean unlimited quota.
Codex CLI >=0.153.1 is required (`CODEX_WRITER_BIN` can pin its location).
Explicit rollback: `WRITER_PROVIDER=openrouter`, `WRITER_MODEL=z-ai/glm-5.3-flash`.
No publication gate or schedule changed. Model migration alone is not publication proof.

Release checks passed 2026-09-06: VPS ChatGPT authorization and the normal writer
path produced a validated 335-word abstract and 1,125-word Cross-Domain section.
Abstract recovery preserves the evidence payload and uses source-exact sentences
only after grounding rejection, within the existing retry budget. The primary
prompt no longer cites external papers as evidence of our own synthesis methods.
Mac suite: 4,523 passed, 2 xpassed; isolated VPS: 135 passed, 1 skipped.
Ruff, mypy, unchanged LOC caps, and independent transport/recovery audit passed.
This verifies writer integration, not a complete paper or daily publication cadence.

## Current Objective
Reviewer migration 2026-09-06: judge, final review and rejected-patch repair use
Terra Medium via the same isolated Codex adapter. Sol High writer is unchanged.
GLM 5.3 Flash is the OpenRouter fallback on technical failure only; review
decisions and scientific gates are unchanged. Both GPT roles consume the shared
Codex subscription allowance. This does not change Researka's external panel.
Rollback: set JUDGE_MODEL and FINAL_LAYER_REVIEWER_MODEL to google/gemma-4-31b-it;
set FALLBACK_MODEL and FINAL_LAYER_FALLBACK_MODEL to mistralai/mistral-small-2603.

Make Research Agent Bot produce genuinely world-class biomedical research papers.
Immediate sprint: clear release-green blockers, then raise the rapamycin paper
from a certified AAA/L6 artifact to candidate-publication quality.

## Success Condition
- Repo clean and tri-synced across MacBook, GitHub, VPS `/opt`, and VPS `/root`.
- Full pytest and ruff pass.
- Cross-topic meta-synthesis auto-selects only fully certified 14/14 runs.
- Rapamycin paper sprint has an executable plan and first high-impact paper
  quality slice completed without weakening the trust spine.

## Current Truth - 2026-08-13
```text
Last pre-switch clean baseline: 415621b2
Current branch target: MiMo v2.5 Pro writer/extractor with independent Gemma review
Final deployed commit: verify with git rev-parse --short HEAD after deploy
Service: research-agent-bot.service active
Endpoint: HTTP 200 live status page
Validation: run from the current checkout before deployment
```

## Canonical deploy branch (#9, 2026-06-13)
The v3 producer deploys from `origin/codex/019e9ce8/main`; the Mac mirror
tracks `claude/3809304f/main` and the VPS `/opt` + `/root` reset to
`origin/codex/019e9ce8/main`. These hold identical content — treat
`codex/019e9ce8/main` as the single source of truth. `origin/claude/finalizer-surface-fix`
(@ b586c114) is a STALE ancestor, not a separate colleague branch; do not deploy
or "sync" from it, and do not force-delete remote refs (another session may
reference them) — consolidation is by convention, not by pruning.

## Finalizer cycle stability (2026-07-18)
The journal finalizer now canonicalizes a repeated repair cycle before its
final sidecar refresh, then fails closed unless the refreshed paper is unchanged
and journal-surface valid. This prevents stale pre-refresh sidecars from causing
unbounded service retries while preserving the final publication gate.

## External source-authority retry (2026-07-18)
When Researka reports an editorial source-verifier outage, permits resubmission,
and requests no content revision, V3 reuses the unchanged gate-passed package
for up to three timer windows. Retry state stays in the revision sidecar and the
request receives a parent-scoped idempotency key; all local gates still run.

## Topic-wide revision blast fence (2026-07-27)
V3 permits at most three successful submissions per normalized topic in a rolling
24-hour window, across new review IDs and title variants. External verifier
retries remain separately bounded, and legacy ledger topics derive from run names.

An immutable revision receipt contract may change `effect_direction` only when
the reviewer explicitly requests direction-code reconciliation. Source identity,
receipt membership, and every other contract field remain frozen, and the
authorized changes are recorded in `revision_evidence_continuity.json`.

Revision discovery checks the newest submitted record for every topic instead
of a fixed ledger tail, so older unresolved reviewer requests remain actionable.

## Source-owned revision trace repair (2026-07-28)
Reviewer requests for more exact major-claim traces are repaired from each
source row's own result-bearing excerpt plus its stable DOI/PMID. The repair
does not infer source support from nearby prose, and repair epoch 12 reopens
requests exhausted before this engine change exactly once.

## System Boundary
```text
research-agent-bot = paper-producing synthesis engine
Researka public reader/provenance = downstream publishing surface
OSF publisher = sibling service
```

This sprint is not public-reader or platform work. It is paper quality work.

## Trust Spine
```text
LLM PROPOSES. CODE DISPOSES.
claim_graph / manifests / verdict JSON are source of truth.
Markdown is downstream rendering.
No raw-paper shortcut claims in cross-topic or final-paper prose.
```

## Shipped Capabilities
- Generated topic-pack V1: deterministic classification, adaptive expansion,
  immutable pack records, safe `scripts/synthesize.py`.
- AAA-SCOP track: scoped certification for thin but useful topics without
  inflating full AAA/L5.
- Reviewer stack: MiMo writer/extractor, configured final-layer reviewer with
  high thinking, and Mistral-small bounded fallback only when primary review fails.
- Cross-topic meta-synthesis V1: read-only certified-run aggregation, convergence
  detector, contradiction detector, deterministic renderer.
- Rapamycin: AAA/L6 reproducibly journal-ready flagship.
- Basket: 18 primary AAA/L5+ topics plus taurine as scoped support in the
  corrected cross-topic input set.

## Current Risks
1. Full pytest must stay green after the LOC budget correction.
2. Cross-topic V1 was safe but initially selected some stale pre-cert runs; this
   branch fixes auto-selection to require explicit cert track and 14/14 audit.
3. Cross-topic labels remain coarse; V2 detector work is not part of this paper
   sprint unless it directly improves rapamycin.
4. Rapamycin has certification strength and now 40 runner-admitted receipts
   after source-validated qualification rescue. It is not yet "world-class
   paper complete": real RoB/GRADE generation, quantitative pooling/forest
   plots, and the publication scorer as a hard pre-submit gate remain blocking
   paper-quality tasks.
5. Gemini Exacto is the selected reviewer but still needs replay validation
   before being called Grok-equivalent; deterministic gates remain the
   production-critical certification layer.
6. Tension-count drift follow-up: some manifests have reported
   `n_non_orthogonal_tensions` above a recomputed
   `build_tension_matrix(...).non_orthogonal()` count (observed 47 vs 18 on a
   fasting run). Because evidence-map routing uses this density, reconcile the
   manifest writer before tuning that routing threshold.

## Operational Decision - 2026-07-09
- Do not reopen the Evidence Map / brief escape valve as the default drought
  fix. That restores throughput by lowering the public-grade bar, which
  conflicts with the current standardized A-grade publishing goal.
- The direct-source preflight is an absolute floor
  (`PREFLIGHT_MIN_DIRECT_RECEIPTS = 4`), not a direct-share ratio. Rich corpora
  with enough direct receipts should pass source fit even when they include many
  adjacent/context receipts.
- Current publish recovery should prioritize source-bundle mapping failures and
  reviewer-revision execution before relaxing public surface gates.

## Operational Decision - 2026-07-10
- Corpus repair extracts `core` clinical candidates before adjacent/background
  candidates; raw retrieval order must not consume the repair budget.
- Receipt repair continues while total, primary-tier, or direct-core counts
  improve. The shared direct-evidence floor remains 4.
- A source bundle may carry at most 3 non-direct tail rows (15%) only when at
  least 4 topic-specific direct rows remain; off-topic direct rows still block.
- The same reviewer request is quarantined after 3 failed revise attempts
  across timer windows. Mixed writer fixes are not terminal scope resets.

## Operational Decision - 2026-07-14
- Candidate preparation is separate from publishing: the prepare timer repairs
  and receipt-validates up to 3 topics between fresh windows.
- Prepared status expires after 24 hours and is invalidated by threshold changes.
  Fresh still reruns every synthesis, surface, reviewer, and submission gate.
- The drought report exposes prepared supply so an empty frontier is visible
  before it becomes another multi-day public-output gap.

## Operational Decision - 2026-07-15
- Reviewer revisions reuse an immutable, hash-verified evidence snapshot;
  later corpus or threshold changes cannot silently change the submitted claim
  set. A source-precision revision may rebuild once, then its next round locks.
- Pre-snapshot legacy runs validate every contract field still present plus the
  exact receipt and citation sets, then snapshot immediately. Contract fields
  absent from an old manifest cannot be reconstructed and remain explicitly
  identified as `legacy_contract` rather than treated as newly verified.
- Retryable revise failures carry `RESEARCH_AGENT_REVISION_REPAIR_EPOCH`.
  Increment that epoch only after a material repair-engine upgrade to reopen
  old retryable requests once; terminal safety decisions never reopen. Epoch 8
  scopes reviewer-authorized public outcome renames to the manuscript while
  preserving raw supplement audit labels. Revision renders preserve
  their corpus strategy instead of inheriting a prior numeric-density downshift.

## Operational Decision - 2026-07-17
- Strict retraction checks use OpenAlex first, then Crossref Retraction Watch,
  then PubMed only when PubMed indexes every cited DOI; provider failure remains
  fail-closed unless another provider covers every cited DOI.
- A newer hard-terminal revision status overrides stale repairable history, and
  every terminal attempt is excluded for the rest of its timer window.
- Scope-only topic terms no longer qualify generic sources or generated packs;
  tension pairs require manuscript-supported labels resolving to retained receipts.
- Finalization upgrades repeated generic animal qualifiers to one source-named,
  idempotent qualifier; malformed parentheticals and duplicate canonical
  outcome rows block before submission and finalization must reach a fixed point.
- Unpaywall enrichment is DOI-only, post-discovery, requires a valid contact
  email, and never counts as an independent source; its weekly smoke fails closed.
  No evidence threshold was lowered.
- Treat repeated `journal_surface_failed` log entries as retries, not independent
  candidates: count unique final artifacts, inspect exact issue codes, then replay
  failures through the current finalizer before changing production logic.
- Repair reproducible surface defects at their universal generator/finalizer source.
  Never relax the journal-surface gate merely to increase publication volume.

## Operational Decision - 2026-07-24
- V3 has one public product: a full research synthesis. The receipt probe uses
  the writer's canonical review-type classifier before the paid writer; compact
  candidates become `needs_corpus_expansion` and never enter public synthesis.
- `researka_publish_ready` excludes the optional external-journal declaration;
  `journal_submission_ready` includes it. The V3 submit bridge uses the former.
- A 24-hour V3 accepted-public-paper drought fails visibly, runs bounded
  candidate preparation, and starts at most one fresh attempt when no V3 lane
  is active. Recovery never lowers evidence or publication gates.
- GitHub CI runs on both `main` and canonical `codex/019e9ce8/main` during the
  branch migration.
- Publication policy is a typed shared contract in `agent/publishing/policy.py`.
  Candidate preparation, fresh ranking, and daily-submit surface checks consume
  that contract; compact/full and evidence-floor meanings must not be redefined
  inside lane scripts.
- Drought triage derives a unique-candidate conversion funnel from existing lane
  ledgers. It does not write another independent truth source, and retries do
  not inflate blocker or stage counts.
- The P1 publication-control decomposition is live: the two operational CLIs
  are compatibility wrappers over `publishing/fresh_lane.py` and
  `publishing/submission.py`; topic supply, candidate preparation, revision,
  reconciliation, event telemetry, and policy have dedicated modules.
  Further extraction must reduce LOC, preserve public behavior, pass the full
  suite, and deploy only between live cycles.

## Operational Decision - 2026-07-27
- Fresh permanently excludes an exact topic after any successful submission;
  only sibling topic variants can return after the 21-day family cooldown.
  Reviewer-requested updates belong to revise, and legacy submission rows derive
  missing topics from their run names.

## Active Plan
Source of task truth: `docs/active_50_task_plan_2026-05-09.md`.

Priority order:
1. Keep release-green state clean and deployed.
2. Continue rapamycin corpus qualification from 40 runner-admitted receipts
   toward the 50+ stretch target.
3. Only then activate RoB/GRADE, meta-analysis, field engagement, tension
   elaboration, and template-language gates on the richer corpus.

## Verification Commands
```bash
git status --short
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check agent scripts tests
.venv/bin/python scripts/run_cross_topic_meta_synthesis.py
ssh -i ~/.ssh/binance_futures_tool root@49.12.7.18 \
'cd /opt/research-agent-bot && git rev-parse --short HEAD && git status --short && systemctl is-active research-agent-bot.service && curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8791/'
```

## Definition of Done for Current Cleanup
- `select_best_runs()` excludes stale runs missing certification track or complete
  14/14 audit.
- Meta-synthesis artifact regenerated from corrected run set.
- LOC budgets documented in `DECISIONS.md` and enforced at 25,000 effective LOC
  for `agent/`, 41,000 for `scripts/`, and 66,000 combined.
- `AGENTS.md`, `PROJECT_STATE.md`, and active task plan match current mission.
- Full suite and ruff pass.
- Commit pushed and VPS paths synced clean.

## Deployment verification status — 2026-08-07

`662f930e` (source-specificity axis tokens) is **deployed and verified at the
receipt-funnel stage, NOT end-to-end to a published paper.**

Verified: liraglutide_adverse_effects primary-tier receipts 1 -> 25+ via a live
`run_v06_synthesis --dry-run` probe; full suite 4198 passed (4243 collected); both
cross-subject-leakage directions covered by tests.

NOT verified: no paper has published since deploy. This is not attributable to
`662f930e` — `journal_finalizer` fails to converge on every manuscript
regardless of evidence quality, so no change to evidence selection can produce
a publication until that is fixed. Reverting `662f930e` would restore the
primary-tier starvation (every probed topic scored 0-2 against a floor of 3)
without unblocking publication, so it stays deployed.

Open blocker: `journal_finalizer` repair loop oscillates between two
surface-invalid states. Current failure, now stated explicitly rather than as
`exit=7 local_gate_execution_failed`:
`structure_surface: section too short: Cross-Domain Synthesis 535/850 words`.

Ruled out by test, do not retry blind:
- terminal `_phase_b_lane_qualifier` pass (identical cycle; reverted unshipped)
- disabling `review_noise_control.restore_surface_floors` (identical cycle)

LOCALIZED 2026-08-07. The manuscript arrives with ONE fault. Measured on the
pristine liraglutide paper before any repair phase runs:

    pristine issues: ['structure_surface']   # Cross-Domain Synthesis 535/850

Every other fault is MANUFACTURED by the repair stack. Running each phase
independently against that pristine text:

    _phase_a_methods_replace                INTRODUCES ['pipeline_jargon']
    _phase_d_evidence_honesty_guard         INTRODUCES ['duplicate_paragraph']
    _phase_f_reconcile_results_table        INTRODUCES ['public_artifact']
    _phase_l_strengthen_analytical_sections INTRODUCES ['grammar_artifact']

So the loop cannot converge because the repairs damage the manuscript faster
than they fix it. This is the audit's thesis with direct evidence: the fix is to
shrink the repair stack, not to add another phase.

Phase behaviour IS deterministic — an earlier claim that sidecar state made
localization non-reproducible was WRONG and is retracted. A/B on pristine copies
gave identical issue sets and identical sidecar hashes.

## BLOCKED — publication gated on journal_finalizer, 2026-08-07

Status: **BLOCKED, not done.** Evidence selection is fixed and deployed; no
paper can publish because `journal_finalizer` cannot converge.

Known defect, reproducible, deliberately NOT fixed:
`_phase_f_reconcile_results_table` (scripts/journal_finalizer.py:5558) turns one
`structure_surface` fault into eleven. It groups receipts by `outcome_class` and
rebuilds `## Results` with a subsection per group, so each group becomes a
short section. More receipts => more outcome groups => more short subsections.

Note the interaction: `662f930e` raised liraglutide from 5 admitted receipts to
68, which INCREASES the number of outcome groups and therefore makes this phase
amplify harder. Fixing evidence selection made this defect more visible, not
less.

Three fixes attempted and reverted, each failing its own test — do not retry
blind:
1. terminal `_phase_b_lane_qualifier` pass (identical cycle)
2. disabling `review_noise_control.restore_surface_floors` (identical cycle)
3. phase-by-phase culprit scan gated on a state that never occurs

CONCRETE NEXT ACTION: make `_phase_f_reconcile_results_table` stop emitting one
subsection per outcome group when that would create sections below the surface
floor — either merge small groups into a single subsection or render them as
table rows rather than headed sections. Verify with:

    cp -r runs/synthesis-liraglutide_adverse_effects-v06-DAILY-2026-08-06T18-18-34Z /tmp/x
    .venv/bin/python -c "import sys;sys.path.insert(0,'scripts');sys.path.insert(0,'.');\
    import journal_finalizer as J;from pathlib import Path;d=Path('/tmp/x');\
    t=(d/'full_paper.md').read_text();o,_=J._phase_f_reconcile_results_table(t,d);\
    print(sorted(i.code for i in J._surface_report(o,d).issues))"

Success = that list does not grow relative to the pristine `['structure_surface']`.

## ROOT CAUSE FOUND 2026-08-07 — topic-anchor mismatch, not short sections

Four fixes failed because the diagnosis was wrong. The 11 `structure_surface`
faults are NOT 11 short sections. Actual breakdown after
`_phase_f_reconcile_results_table` on the real liraglutide run:

    missing Results outcome section: Liraglutide Adverse Effects / Cardiometabolic
    missing Results outcome section: Liraglutide Adverse Effects / Safety
    missing Results outcome section: Liraglutide Adverse Effects / Longevity
    missing ... / Contextual Adjacent Evidence, ... / Animal/Preclinical Context
    unexpected Results outcome section: cardiometabolic
    unexpected Results outcome section: safety
    unexpected Results outcome section: longevity
    unexpected Results outcome section: contextual other, animal preclinical context
    section too short: Cross-Domain Synthesis 295/850 words

The SAME five sections are reported missing (under the expected name) and
unexpected (under the emitted name). Only ONE genuine short section exists.

Mechanism: `agent/journal_surface_gate._results_outcome_section_issue_messages`
derives expected sections from the TABLE's "Outcome class" column.
`_phase_f_reconcile_results_table` writes that cell as
`f"{topic_anchor} / {display}"` but writes the H3 heading as bare `display`.
`_outcome_key()` of the two never matches. Only manifests when `topic_anchor`
is non-empty, so it is a regression from when anchors were added to table rows
without updating headings or the gate.

FIX OPTIONS (untested):
 a) strip a leading "<anchor> / " when deriving expected keys in the gate
    (keeps the human-readable anchored table, matches existing headings)
 b) emit the anchored form in the H3 heading (verbose, redundant in a paper
    already titled for that topic)
 c) drop the anchor from the table cell (loses disambiguation)
Option (a) looks right. Verify with the command in the BLOCKED section above;
success = the missing/unexpected pairs disappear, leaving only the single
Cross-Domain Synthesis short-section fault.

## ROOT CAUSE 2026-08-07 (evening) — THE WRITER EMITS STUBS

Every downstream gate we fixed this week sits below a writer that produces
~15-word sections. From a live liraglutide run (/tmp/pub4.log):

    [paper_writer] introduction              done — 15 words   (floor 400)
    [paper_writer] background                done — 17 words   (floor 300)
    [paper_writer] results                   done — 243 words  (floor 500)
    [paper_writer] cross_domain_synthesis    done — 14 words   (floor 850)
    [paper_writer] discussion                done — 18 words   (floor 800)
    [paper_writer] limitations_full          done — 14 words
    [paper_writer] conclusion                done — 16 words

DETERMINISTIC sections on the SAME run are full size:

    quantitative_results_table (deterministic)  709 words
    references_full            (deterministic) 2110 words
    methods                    (deterministic)  258 words

So the pipeline is healthy and the corpus is healthy; the LLM-written sections
are stubs. The backstop rescues discussion (18 -> 838) and conclusion
(16 -> 325) with deterministic anchors, but its cross-domain anchor is only
~150-250 words and cannot bridge 14 -> 850. That single unbridged section is
what fails Stage 5c and hangs the finalizer repair loop.

NOT the model or the credentials. A direct call to the configured writer
(MiniMax-M3 @ https://api.minimax.io/anthropic, /v1/messages) returned a full,
well-formed 120-word answer on request. The key is present and valid, and no
error/timeout/429 appears anywhere in the run log — the calls "succeed" and
return near-empty content.

The uniformity (15/17/14/18/14/16 words) looks like one sentence per section,
i.e. a preamble or refusal-shaped reply being accepted as the section body.

START HERE NEXT. Do not add more gate/floor/finalizer fixes above this. Capture
the raw provider response for one section call (agent/llm_client.py ~line 264
builds the payload; max_tokens defaults to 4096, so truncation is unlikely) and
compare the prompt actually sent against the working direct call. Historical
runs prove the writer CAN do this: 691 of 723 papers cleared the 850-word
Cross-Domain floor, median 1015 words. This is a regression, not a limit.

## 2026-08-08 — year fix landed; blocker moved

f1a2f1ad (calendar years no longer count as fabricated numerics) produced the
first healthy writer output of the week:

    section                 before -> after
    results                    243 -> 2427
    cross_domain_synthesis      14 -> 905   (floor 850, now PASSING)
    abstract                    89 -> 267

Stage 5c no longer reports "section too short". It now reports:

    unresolved surface issues: structure_surface:
      missing required section: Cross-Domain Synthesis

So the writer produces 905 words but the section does not survive into the
rendered manuscript as a "## Cross-Domain Synthesis" heading. The gate matches
^##; the model emits its own "# Cross-Domain Synthesis: <subtitle>" inside
body_md (observed directly when probing the writer chain), and the builder also
prepends the canonical heading. Suspect a duplicate/!=level heading collision in
the render or finalizer section splitter. START HERE.

STILL STUBS, different cause: introduction (15 words, floor 800) and background
(19, floor 700) go through _write_scoped_section, whose extra validators
(_check_scoped_paragraph: topic_alias_under_count needs the topic name >=2x,
and missing_hedge_phrase) are NOT instrumented. Add the same rejection logging
there next -- the year fix does not cover them.

## 2026-08-08 (later) — both writer fixes live; ONE blocker left

f1a2f1ad (calendar years) + 0d64c018 (lead-entity alias) produced a healthy
manuscript. Section word counts on the latest run:

    abstract                372   (was 89)
    background              161   (was 17)
    results                2317   (was 243)
    cross_domain_synthesis  964   (was 14; floor 850)

Remaining Stage 5c blocker, verbatim:

    unresolved surface issues:
      structure_surface: missing required section: Cross-Domain Synthesis;
      structure_surface: section too short: Conclusion 88/250 words

The Cross-Domain one is the blocker that matters and it is NOT a length problem
any more: the writer produces 964 words but the section does not appear in the
rendered manuscript under a "## Cross-Domain Synthesis" heading, which is what
_section_body() matches (regex ^##\s+<heading>\b).

Confirmed lead: when the writer chain is probed directly, the model returns
body_md beginning with its OWN heading:

    "# Cross-Domain Synthesis: Liraglutide Adverse Effects Across ..."

while build_anchored_from_parsed separately prepends the canonical
"## Cross-Domain Synthesis". So the rendered section likely carries a nested or
duplicated heading, and either the renderer or a finalizer phase drops/rewrites
one of them. NEXT STEP: dump the rendered full_paper.md around Cross-Domain and
compare heading levels; strip any model-emitted leading heading in
build_anchored_from_parsed before prepending the canonical one.

Introduction is still a 15-word fallback (1 remaining) -- separate cause, not
yet diagnosed; it survives both fixes.

### Heading-collision theory DISPROVEN (2026-08-08)

Do not chase it. Checked the rendered full_paper.md directly:

    grep -nE "^#{1,4}.*Cross-Domain" full_paper.md   -> 0 matches (ANY level)

The section is not mis-levelled or duplicated, it is ABSENT. The rendered paper
runs Results -> Endpoint-Sensitivity Framework -> Discussion, 14 "##" sections,
9661 words, with no Cross-Domain Synthesis at all. So stripping a model-emitted
heading in build_anchored_from_parsed would fix nothing.

The writer logs 964 words for cross_domain_synthesis, so the section is built
and then dropped between section assembly and full_paper.md. NEXT: trace the
section list in agent/paper_writer.render_full_paper -- find where
cross_domain_synthesis is ordered/emitted and why it is skipped while
discussion/conclusion survive. Check whether it is gated on something
(e.g. a matrix/tension precondition) that silently omits the section rather
than emitting a short one.

### 2026-08-08 SAME-RUN evidence — corrects two wrong theories

Run synthesis-liraglutide_adverse_effects-v06-DAILY-2026-08-08T06-43-47Z-R2,
log and rendered paper from the SAME run (earlier comparisons mixed two runs
and were invalid):

    cross-domain headings in full_paper.md : 1     <- present
    total "##" sections                    : 14
    paper words                            : 9781
    writer built cross_domain_synthesis    : 964 words
    rendered cross_domain_synthesis        : 680 words

WRONG THEORY 1 (heading collision): there is exactly ONE heading. Not duplicated,
not mis-levelled.
WRONG THEORY 2 (section dropped): it renders. Not dropped by section ordering;
_FULL_PAPER_SECTION_ORDER includes it and the paper rendered full, not thin.

REAL REMAINING ISSUE: the finalizer repair stack SHRINKS the section, 964 -> 680
against an 850 floor. Same erosion seen earlier (295 -> 256). Stage 5c now reads:

    structure_surface: section too short: Cross-Domain Synthesis 680/850 words
    structure_surface: empty heading: Conclusion

NEXT: measure per-phase word delta on the RENDERED section (a phase harness over
journal_finalizer phases applied to this run dir), find which phase removes ~280
words from cross_domain_synthesis, and stop it removing content from a section
already under its floor. Note an earlier per-phase probe found only
_phase_l_strengthen_analytical_sections changing this section (+220), so the
loss likely happens in the post-loop passes
(_phase_m_strip_surface_duplicate_paragraphs / review_noise_control) rather than
the numbered phases.

### Finalizer EXONERATED for the 964 -> 680 loss (2026-08-08)

Measured on the rendered artifact of run ...2026-08-08T06-43-47Z-R2:

    rendered Cross-Domain: 680 words (floor 850)
      +0  _phase_m_strip_surface_duplicate_paragraphs
      +0  _phase_m_repair_surface_artifacts
      +0  review_noise_control.apply_review_noise_control

An earlier per-phase probe over the numbered _phase_* functions found only
_phase_l_strengthen_analytical_sections changing this section, and it ADDS
(+220). So neither the numbered phases nor the post-loop passes remove the
~280 words.

CONCLUSION: the loss is UPSTREAM, inside the writer. _write_anchored_section
keeps the best-scoring attempt (logged 964) and THEN calls
_run_citation_fix_pass, which re-invokes build_anchored_from_parsed on a fresh
LLM response and overwrites `best` with whatever it returns -- including a
shorter section. That is the prime suspect and is where to look next:
agent/paper_writer.py, the `best = await _run_citation_fix_pass(...)`
assignment right after the retry loop. Consider keeping the longer of the two
rather than unconditionally replacing, since the word floor is the binding gate.

Do NOT re-investigate journal_finalizer for this. It is measured clean.

### _run_citation_fix_pass ELIMINATED as the 964 -> 680 suspect

Read the implementation (agent/paper_writer_citations.py run_citation_fix_pass).
It is fully guarded and CANNOT shrink a section:

    if section is None or not background_lit_entries: return section
    if not issues:                                    return section
    if not parsed:                                    return section
    if new_section is None:                           return section
    if len(new_issues) < len(issues):                 return new_section
    return section                                    # otherwise original

The replacement requires a STRICT reduction in citation-issue count, with an
explicit comment that this defends against the LLM rewriting the section.
So the earlier note naming it as prime suspect was WRONG -- disregard it.

Measured-clean list for the 964 -> 680 loss now covers: all numbered
journal_finalizer _phase_* functions, the three post-loop passes, and
run_citation_fix_pass.

REMAINING candidates, unmeasured:
 1. The "964 words" log line is emitted by _log_section_done against the
    in-memory SynthesisSection; the rendered figure counts the section body in
    full_paper.md AFTER _strip_rendered_citation_markers() runs in
    render_full_paper. That strip removes inline "_Cited: `id`_" markers, which
    the builder appends after EVERY paragraph -- roughly 4-6 words per
    paragraph. That is a plausible mechanical explanation for a ~280-word gap
    and is CHEAP TO CHECK FIRST: count the markers in the section.
 2. section_word_count() in paper_writer_helpers drops the first line before
    counting, so writer-side and gate-side word counts are not measuring the
    same text. Compare the two definitions before assuming content was lost.

Check (1) before touching any code: the loss may not be content loss at all.

### ROOT CAUSE of 964 vs 680: writer and gate count different text (2026-08-08)

Both checks EXECUTED against run ...06-43-47Z-R2, not inferred:

  A) rendered Cross-Domain = 680 words; "_Cited:" markers remaining = 0;
     writer-logged = 964; gap = 284.
  B) run_citation_fix_pass executed with a shrinking rewrite: 302 -> 302 words.
     The guard HOLDS. That suspect is eliminated by execution.

The gap is a MEASUREMENT MISMATCH, not lost content:

  writer  agent/paper_writer_helpers.section_word_count():
            len(body.split()) over lines[1:], on text that STILL CONTAINS the
            per-paragraph "  _Cited: `id`, `id`_" markers the builder appends.
  gate    agent/journal_surface_gate._section_issue_messages():
            len(re.findall(r"\b\w+\b", body)) on full_paper.md, i.e. AFTER
            render_full_paper calls _strip_rendered_citation_markers().

So the writer stops retrying when IT measures 964 >= 850, and the gate then
measures 680 < 850 and fails. The writer is satisfied by text the gate never
sees. Same failure family as the outcome-anchor keying and axis-token bugs:
two components measuring the same thing differently.

FIX (small, shippable): make section_word_count() strip rendered citation
markers before counting and count with the same \b\w+\b rule the gate uses, so
the retry loop optimises the number the gate will actually apply. The helper
already imports strip_rendered_citation_markers in the same module.
Add a test asserting writer count == gate count for a section containing
_Cited: markers.

Do NOT raise the floor or pad the section; the counts simply need to agree.

### 2026-08-08 — parity fix worked; "finalizer exonerated" was WRONG

339d7246 (writer counts words the way the gate does) had a large effect. The
retry loop now optimises the enforced number:

    introduction            15 -> 935 words   (was a placeholder ALL WEEK)
    cross_domain_synthesis  14 -> 932
    results                243 -> 2429
    abstract                89 -> 368

But Stage 5c still fails:

    section too short: Cross-Domain Synthesis 679/850 words
    empty heading: Conclusion

Writer builds 932 (markers stripped, gate rule). Rendered is 679. So ~253 words
are still lost between section assembly and full_paper.md.

RETRACTION: the earlier "finalizer EXONERATED" note is INVALID. That probe
applied journal_finalizer phases to an ALREADY-FINALIZED full_paper.md, so
+0 deltas prove nothing -- the phases had already run. The erosion happens on
the FIRST finalizer pass over the fresh render, which was never measured.

NEXT (do this properly): capture the section body at three points in ONE run --
(a) SynthesisSection.body_md as built, (b) full_paper.md immediately after
render_full_paper and BEFORE journal_finalizer, (c) after the finalizer. That
isolates render-vs-finalizer in a single measurement instead of comparing
across runs or across already-processed artifacts, which has produced three
wrong conclusions today.

Background is still a 19-word placeholder (1 remaining fallback), separate cause.

### novel_numeric rejections are NOT a bug — do not "fix" them (2026-08-08)

Diagnostics showed paragraphs rejected with novel_numeric:1.22mmol/l, 3.8kg,
n=125. Checked whether those values exist in the run corpus:

    value 1.22 in receipt_funnel.json: 0 times
    value 3.8                        : 0 times
    value 125                        : 0 times

They are absent. The model INVENTED them. The guard is doing exactly what it
exists for -- keeping fabricated clinical values out of a published biomedical
paper. Loosening numeric traceability to make a section reach its word floor
would trade the trust spine for word count. DO NOT DO IT.

The calendar-year fix (f1a2f1ad) was correct because a year is bibliographic and
can never appear in a receipt numeric set. A dose or sample size is a factual
claim and MUST trace. The two are not the same case.

Correct response to these rejections: the retry prompt should tell the model to
use only corpus numerics, or the section should be allowed to be shorter --
never to admit untraceable numbers.

### RETRACTION: novel_numeric rejections ARE a bug after all (2026-08-08)

The note above ("NOT a bug -- do not fix") is WRONG and must not be relied on.
Its evidence was a grep against a receipt_funnel.json that DID NOT EXIST in that
run dir; grep returned 0 matches because there was no file, not because the
values were absent.

Re-run against a run that actually has the file
(...2026-08-08T06-06-26Z-R2/receipt_funnel.json, 5155 bytes):

    1.22  occurrences: 0
    3.8   occurrences: 3     <- PRESENT in corpus, still rejected
    125   occurrences: 1     <- PRESENT in corpus, still rejected

So _check_anchored_paragraph rejects values that DO trace to receipts. That is a
matching/normalisation defect, not fabrication. Likely causes: the accepted set
is built only from receipt.p_values + receipt.thesis_text
(_accepted_numeric_tokens), so a value appearing elsewhere in the funnel is not
admitted; and unit-bearing tokens ("3.8kg") normalise differently from a bare
"3.8" in the source.

NEXT: compare the exact token the paragraph emits against _accepted_numeric_tokens
for the same run, then widen the accepted set to the numerics actually present in
the receipts rather than loosening the guard. Do NOT simply allow untraceable
numbers -- 1.22 really is absent, so the guard must still reject that one.

LESSON: verify the file exists before trusting a zero-match grep. This is the
second time today a missing/mismatched artifact produced a confident wrong
conclusion.

### CORRECTION 3: the retraction overcorrected (2026-08-08)

The retraction above claimed 3.8 appeared 3 times in the corpus and was being
wrongly rejected. That count came from `grep -o "3.8"` with an UNESCAPED dot,
which matches any character -- it was counting 328, 3x8, etc.

With `grep -o "3\.8"` the real counts against
...2026-08-08T06-06-26Z-R2/receipt_funnel.json are:

    n=125 : 1   PRESENT  -> was wrongly rejected; fixed by ad1417dc
    3.8   : 0   ABSENT   -> correctly rejected (model invented it)
    1.22  : 0   ABSENT   -> correctly rejected

So the anti-fabrication guard was substantially CORRECT. Only the enrolment case
was a real defect: population_summary was omitted from _accepted_numeric_tokens,
so a paragraph citing its own sample size read as fabricated. ad1417dc fixes
exactly that and nothing more, which is the right scope.

Do not widen the numeric guard further on the strength of the retraction note --
it was based on a bad regex.

LESSON (third time today): escape dots in grep, and verify the file exists
before trusting a count. Three wrong conclusions today came from bad evidence
gathering, not bad reasoning: mismatched run artifacts, a grep on a missing
file, and an unescaped regex dot.

### Rollback path for the 2026-08-08 writer fixes

Branch `revert/2026-08-08-writer-fixes` = 08cf76e7 = the pre-session state.

    ssh -i ~/.ssh/binance_futures_tool root@49.12.7.18 \
      "cd /opt/research-agent-bot && git reset --hard 08cf76e7"

NOT executed, deliberately. Assessed on the merits, rolling back reintroduces
four verified defects, each covered by a test that fails when the fix is
reverted (full suite 4211 passed):

  54882949 pricing    -- exit=7 "no pricing configured for reviewer model
                         google/gemma-4-31b-it" killed every run at the final gate
  f1a2f1ad years      -- novel_numeric:2025/2015 discarded EVERY paragraph
                         citing a study date
  339d7246 wordcount  -- writer optimised a count the gate never applied
  f0be358d bare-para  -- one unwrapped paragraph -> 15-word placeholder section
  ad1417dc enrolment  -- n=125, present in corpus, rejected as fabricated

Measured effect of keeping them: introduction 15 -> 935 words,
cross_domain_synthesis 14 -> 932.

The rollback fixes no defect and reverses those. Anyone with the authority to
degrade the live publisher can run the one-liner above; it is left as a decision,
not a default.
