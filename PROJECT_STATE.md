# PROJECT_STATE.md

## Current Objective
Make Research Agent Bot produce genuinely world-class biomedical research papers.
Immediate sprint: clear release-green blockers, then raise the rapamycin paper
from a certified AAA/L6 artifact to candidate-publication quality.

## Success Condition
- Repo clean and tri-synced across MacBook, GitHub, VPS `/opt`, and VPS `/root`.
- Full pytest and ruff pass.
- Cross-topic meta-synthesis auto-selects only fully certified 14/14 runs.
- Rapamycin paper sprint has an executable plan and first high-impact paper
  quality slice completed without weakening the trust spine.

## Current Truth - 2026-05-09
```text
Last pre-switch clean baseline: 415621b2
Current branch target: model-agnostic final-reviewer naming
Final deployed commit: verify with git rev-parse --short HEAD after deploy
Service: research-agent-bot.service active
Endpoint: HTTP 200 live status page
Full pytest at current branch validation: 2961 passed, 5 warnings
Ruff: clean
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
- LOC budgets documented in `DECISIONS.md` and enforced at 29,250 cloc for
  `agent/` and 41,000 cloc for `scripts/`.
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
