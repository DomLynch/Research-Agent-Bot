# Research Agent Bot A-Z Handover

Last updated: 2026-06-06, Asia/Dubai.

This handover is for a new developer who needs to become productive on Research Agent Bot v3 quickly. It covers the project boundary, architecture, runtime code, live deployment, current operational truth, historical decisions, known risks, and the next sensible work.

## 0. Read This First

Research Agent Bot is an audited biomedical evidence-synthesis engine. It is not a generic LLM writing demo. Its job is to produce source-grounded research papers with machine-readable audit sidecars, then submit eligible papers to Researka.

The short mental model:

```text
database/source retrieval
  -> topic pack
  -> corpus seeding and source admission
  -> quant claim extraction and receipt funnel
  -> synthesis compiler and paper writer
  -> deterministic gates
  -> Researka submission
  -> Researka review/publication
  -> bot ledger reconciliation
```

The critical boundary:

```text
Research Agent Bot = paper producer, source admission, gates, submit bridge, ledgers.
Researka v2 = review, acceptance, publication records, public paper API/page.
RESEARKA.ORG Website = public UI/display.
Researka Database = evidence/fact corpus and source adapter.
Researka Integrity = external integrity/gate service, separate repo/service.
```

Never collapse those into one "publishing failed" bucket. Most past issues were boundary bugs: bot ledger drift, Researka review behavior, duplicate/intake decisions, or source-selection under-sampling. The public page and API are downstream truth for publication, while bot ledgers are local operational truth and can drift.

## 1. Current Live Snapshot

Snapshot commands were run from the MacBook and VPS during this handover.

Current repo/deploy state at snapshot:

```text
MacBook path: /Users/domininclynch/Desktop/Business/Research Agent Bot
Branch: codex/019e0b4c/main
HEAD: 7b719c3fa798
origin/main: 7b719c3fa798
Dirty state: 0 local changes before this handover doc

VPS live path: /opt/research-agent-bot
VPS mirror path: /root/Research-Agent-Bot
VPS lowercase symlink: /root/research-agent-bot -> /root/Research-Agent-Bot
VPS /opt/VPS: git checkout present
All checked VPS paths: HEAD 7b719c3fa798, dirty=0
```

Current active systemd lanes:

```text
research-agent-paper-fresh.timer: active
research-agent-paper-revise.timer: active
research-agent-paper-reconcile.timer: active
research-agent-paper-daily-submit.timer: active
```

Current timer cadence:

```text
fresh:     every 4h at 00:00, 04:00, 08:00, 12:00, 16:00, 20:00
revise:    every 4h at 00:15, 04:15, 08:15, 12:15, 16:15, 20:15
reconcile: every hour at :05, :20, :35, :50
daily submit bridge: 09:15 and 22:15
```

The fresh service is the primary autonomous lane:

```bash
/opt/research-agent-bot/.venv/bin/python scripts/daily_research_paper_cycle.py \
  --mode fresh --run-synthesis --submit --max-attempts 0 --cycle-budget-sec 6000
```

The revise service handles actionable Researka revise decisions without blocking the fresh lane:

```bash
/opt/research-agent-bot/.venv/bin/python scripts/daily_research_paper_cycle.py \
  --mode revise --run-synthesis --submit --max-revise-attempts 2 --cycle-budget-sec 2400
```

The reconcile service fixes bot ledger drift from public publication truth:

```bash
/opt/research-agent-bot/.venv/bin/python scripts/daily_research_paper_cycle.py \
  --reconcile-publications
```

The daily submit bridge submits eligible already-built candidates:

```bash
/opt/research-agent-bot/.venv/bin/python scripts/daily_research_paper_submit.py --submit
```

Latest known completed publication at snapshot:

```text
Topic: resveratrol_biomarker_effects
Fresh ledger: runs/_daily_research_paper_cycle_ledger/2026-06-06-fresh.json
Fresh status: published
Daily ledger: runs/_daily_research_paper_ledger/2026-06-06.json
Daily status: published
Submission id: 8f5a3193-46bd-43a3-8d4d-c3e5240ca299
Decision: accept
Publication id: 75290622-273a-4e57-9a84-36d920af19b1
Public URL: https://researka.org/papers/75290622-273a-4e57-9a84-36d920af19b1
DOI: 10.17605/OSF.IO/9AUYH
```

The same ledger has publication reconciliation:

```text
publication_reconciliation.source = remote_publications
publication_reconciliation.matched = title:research synthesis: resveratrol biomarker effects - full paper
```

At the time of the live check, a fresh 16:00 run was in progress on `gait_speed_longevity`. Journal output showed:

```text
Receipt funnel: admitted=31 strict_high=65 primary_tier=7
Built 31 receipts
run dir: runs/synthesis-gait_speed_longevity-v06-DAILY-2026-06-06T12-02-57Z
```

That is an in-progress runtime snapshot, not a completed publication claim. Re-check before reporting its outcome.

Important ledger detail: this deploy uses date-scoped JSON files under `runs/`, not root-level `latest_*.json` files. Do not check `/opt/research-agent-bot/_daily...`; check `/opt/research-agent-bot/runs/_daily...`.

## 2. Repositories And Paths

Main local repo:

```text
/Users/domininclynch/Desktop/Business/Research Agent Bot
```

Live VPS repo:

```text
/opt/research-agent-bot
```

VPS mirror:

```text
/root/Research-Agent-Bot
/root/research-agent-bot -> /root/Research-Agent-Bot
```

Other related workspaces:

```text
/Users/domininclynch/Desktop/Business/Researka v2
/Users/domininclynch/Desktop/Business/Researka Database
/Users/domininclynch/Desktop/Business/RESEARKA.ORG Website
/Users/domininclynch/Desktop/Business/Researka-Integrity
/Users/domininclynch/Desktop/Business/Research agent bot v4
```

Use the right repo for the right issue:

```text
Bot selected wrong source or failed pre-submit: Research Agent Bot.
Accepted/public API changed or review decision is strange: Researka v2.
Public page display is wrong but API is right: RESEARKA.ORG Website.
Fact counts/topic coverage/selector matching: Researka Database.
External acceptance or integrity checks: Researka-Integrity.
Shared alpha-agent future/domain packs: Research agent bot v4.
```

## 3. Operating Contract

The local `AGENTS.md` and `PROJECT_STATE.md` are required reading. They are partly stale on exact May 9 state, but still define the contract.

Core rule:

```text
LLM PROPOSES. CODE DISPOSES.

Role assignment: registry override > deterministic abstract classifier. Never LLM.
Fact identity: extracted by LLM, schema-validated, source-text-traced.
Paper claims: gated by claim_graph / manifests / verdict JSON.
Markdown is rendering, not source of truth.
```

Practical consequences:

- Never use generated markdown as the only truth.
- Use JSON sidecars and ledgers for status.
- LLMs may write, repair, review, or summarize, but deterministic code owns categorical truth.
- Do not lower gates to force publication.
- Do not backdate a previously blocked paper. Requeue/resubmit with a real current timestamp.
- If public API and bot ledger disagree, call it sync drift and reconcile it.
- Do not auto-commit arbitrary dirty state.

The root README summarizes the pipeline:

```text
topic pack
  -> source retrieval and corpus seeding
  -> source admission and evidence-tier classification
  -> claim cards, citation registry, and tension matrix
  -> v3 synthesis compiler
  -> public manuscript plus supplemental evidence tables
  -> deterministic surface, audit, and pre-submit gates
  -> Researka submission
```

## 4. Code Map

Top-level areas:

```text
agent/      runtime package
scripts/    orchestration, CLI, deployment/runtime jobs
tests/      regression tests
docs/       design notes, handovers, plans
runs/       generated outputs and ledgers, usually not source code
topic_packs/ and topic_packs_db/  manual and generated topic packs
corpora/    fetched/seeding corpus material
```

Key runtime modules:

```text
agent/sources/aggregator.py       source registry and multi-source fanout
agent/sources/researka.py         Researka Database fact/topic/corpus adapter
agent/topic_pack.py               topic pack schema/loader
agent/topic_pack_generator.py     generated pack logic
agent/topic_pack_store.py         immutable generated pack records
agent/corpus_pipeline.py          discovery/corpus orchestration
agent/wave_retrieval.py           wave retrieval over topic specs
agent/synthesis.py                synthesis logic
agent/paper_writer.py             full-paper writer
agent/paper_writer_prompts.py     section prompt specs
agent/journal_finalizer.py        final paper/publisher outputs
agent/journal_surface_gate.py     journal surface checks
agent/final_gate.py               deterministic pre-cert/final gate
agent/publication_scorer.py       publication-readiness scoring
agent/quality_methods_bundle.py   RoB/GRADE/quality methods bundle
agent/template_language.py        template-language gate
agent/final_status.py             final status objects
agent/citation_trace.py           source/citation trace
agent/risk_of_bias_schema.py      RoB schema and hard tool/design coupling
agent/meta_analysis.py            effect pooling primitives
```

Key orchestration scripts:

```text
scripts/daily_research_paper_cycle.py     v3 fresh/revise/reconcile lane
scripts/daily_research_paper_submit.py    submit eligible built candidates
scripts/run_v06_synthesis.py              build one synthesis run
scripts/materialize_fact_topic_packs.py   turn database facts into generated packs
scripts/seed_topic_corpus.py              seed/fetch corpus for a topic
scripts/fetch_oa_corpus.py                open-access corpus fetch
scripts/quant_claim_extract.py            claim extraction from corpus
scripts/tri_sync_status.py                sync/status helper
```

Most operational behavior lives in `scripts/daily_research_paper_cycle.py` and `scripts/daily_research_paper_submit.py`. Start there for publication/run questions.

## 5. Source And Database Layer

The source registry lives in `agent/sources/aggregator.py`.

Researka Database is registered as a normal default-enabled source, but auth gated:

```python
"researka": (
    ResearkaClient(), True, "RESEARKA_DATABASE_TOKEN",
)
```

The adapter lives in `agent/sources/researka.py` and calls:

```text
https://database.researka.org/api/v1/tier2/facts/search
https://database.researka.org/api/v1/papers/topic
https://database.researka.org/api/v1/search
```

It uses:

```text
RESEARKA_DATABASE_TOKEN
```

and optionally direct database env:

```text
RESEARKA_DATABASE_DSN
RESEARKA_DATABASE_URL
```

The adapter returns `RawHit(source="researka")` and adds database facts to `raw["database_facts"]`. It scores hits by tier1 fact presence, fact count, and abstract length.

Live DB access proof from the VPS runtime:

```text
RESEARKA_DATABASE_TOKEN_PRESENT True
RESEARKA_DATABASE_DSN_PRESENT True
RESEARKA_REGISTRY currently_enabled=True
DB_SEARCH_STATUS ok
DB_SEARCH_HITS 5
HIT researka facts 6 paper_id 10.1089/rej.2012.1397 ...
HIT researka facts 2 paper_id 10.1007/s00508-016-1096-4 ...
HIT researka facts 2 paper_id 10.1111/j.1532-5415.2012.04209.x ...
```

Important nuance: final paper citation artifacts may not literally contain the string `researka` or `database_facts`. Database use happens upstream in retrieval/selection and fact-backed topic packs; final citations are papers, DOIs, PMIDs, and receipt IDs. Do not falsely require a final paper to expose `researka` as a citation source label.

Recent database status reported separately:

```text
Tier 1 strict facts: 11,187
Tier 2 facts: 203,098
Longevity topics with at least 3 strict Tier 1 facts: 110 / 110
Weak topics remaining: 0
```

Treat those counts as database-project truth. Reconfirm from the database repo/API before making new public claims.

## 6. Topic Packs

There are two topic-pack sources:

```text
topic_packs/*.toml
topic_packs_db/*/latest.json
```

`scripts/daily_research_paper_cycle.py` discovers both manual and generated packs. Generated packs are only eligible if their metadata marks them publishable.

Generated pack materialization:

```bash
.venv/bin/python scripts/materialize_fact_topic_packs.py --help
```

This script can use SQL/direct database env or API endpoints. It builds generated pack records from fact-backed topics and skips low-information topics. It is the bridge between the database coverage work and bot topic selection.

When debugging "there must be more receipts" issues, do not only raise a threshold or retry the same bad candidate. Check:

```text
1. Is the topic in manual packs or generated packs?
2. Did generated_pack_publishable pass?
3. Did the selector broaden past title-exact matching?
4. Did corpus seeding pull a broad enough candidate set?
5. Did quant extraction classify enough high-confidence claims?
6. Did source precision quarantine off-topic claims?
```

The June database selector bug was not "no papers exist." It was overly strict title matching. That was fixed and deployed before this handover.

## 7. Corpus And Receipt Funnel

Receipt quality is central. The bot does not just need a pile of papers; it needs enough admitted receipts with usable claims and acceptable source-topic precision.

Current important floors in `scripts/daily_research_paper_cycle.py`:

```text
PREFLIGHT_MIN_RECEIPTS = 15
PREFLIGHT_MIN_QUANT_CLAIMS = 10
SOURCE_TOPIC_REPAIR_FLOOR = 0.50
```

Researka's submit floor has been discussed as 12 receipts minimum, but the bot intentionally aims above the bare floor. That is why you see 15 in the bot preflight path: it gives buffer against thin/unstable source bundles.

Recent accepted Resveratrol run evidence:

```text
receipt_funnel.counts.admitted_receipts = 12
receipt_funnel.counts.original_strict_high_confidence_receipts = 24
receipt_funnel.counts.primary_tier_receipts = 4
pre_submit_gate.inputs.n_receipts = 12
pre_submit_gate journal_readiness_contract feasibility_preflight = pass
paper_quality_score.score_out_of_100 = 100.0
```

This means the system can still publish at the Researka floor when the deterministic gate says it is eligible. The 15 preflight target is not the public platform's hard minimum; it is an internal repair/search target.

Repair principle:

```text
If repair starts with 7 receipts, continue from 7 and add 8, 9, 10...
Do not throw away the good receipts and restart from zero.
```

That behavior was added during the June repair work. It matters because large corpus availability does not help if repair loops discard progress.

## 8. Synthesis Outputs

A completed synthesis run directory looks like:

```text
runs/synthesis-<topic>-v06-DAILY-<timestamp>/
```

Common outputs:

```text
full_paper.md                         reader-facing manuscript
full_paper.docx                       portable document export
full_paper.audit.json                 audit details
full_paper.consistency.json           consistency checks
full_paper.final_verdict.json         final verdict
full_paper.journal_surface.json       journal surface gate
structured_evidence_tables.md         supplemental evidence detail
manifest.json                         source of truth for receipts/run metadata
paper_ir.json                         typed paper IR
paper_quality_score.json              deterministic quality score
pre_submit_gate.json                  pre-submit status
pre_submit_gate.md                    readable gate summary
public_export_manifest.json           export readiness
citation_registry.json                citation registry
contradiction_map.json                contradiction/tension detail
evidence_table.csv                    portable evidence table
references.bib                        bibliography
audit/receipt_funnel.json             receipt funnel
audit/publication_score.json          publication score
audit/quality_methods.json            RoB/GRADE quality methods
audit/template_language_gate.json     template-language checks
debug/*.json                          repair/reviewer/debug sidecars
readable/*.md                         human-readable audit summaries
```

Markdown is for humans. JSON sidecars are the trust spine.

## 9. Gates And Submission Eligibility

Submission is a separate act from publication.

Definitions:

```text
selected = bot picked a candidate/run
submit eligible = deterministic bot gates allow POST to Researka
submitted = submit bridge POSTed to Researka intake
accepted = Researka review decision accepted it
published = Researka public publication exists/API/page resolves
ledger reconciled = bot ledger reflects public publication truth
```

`scripts/daily_research_paper_submit.py` states the key boundary: a successful POST means "submitted", not "published".

Pre-submit gate responsibilities:

```text
- source/citation integrity
- receipt count floor
- source-topic precision
- null-coding/source-bundle reconciliation
- journal surface pass
- audit gates
- publication proof/duplicate checks
- remote previously rejected/submitted/published fingerprints
```

Submit bridge responsibilities:

```text
- choose an eligible candidate
- dedupe local/rejected/revision/published fingerprints
- supersede older topic runs
- build payload
- POST to Researka
- write daily ledger
```

The payload includes:

```text
domain_slug
sections/body_markdown
source bundle
content hash/idempotency key
agent slug
```

## 10. Researka Review And Publication

Researka review/publication is downstream. The bot must not rewrite old review history.

Important recent rule:

```text
If a paper was wrongly blocked by an old gate, requeue/resubmit it truthfully now.
Do not backdate it.
Do not mutate old historical decisions.
```

Reviewer-gate issue fixed June 5:

```text
revise now means concrete required revisions.
If reviewer says revise with no actionable required_revisions, that reviewer response is malformed unless strict accept contract is already met.
```

That stopped the "revise with nothing to revise" path.

For publication truth, check:

```text
https://researka.org/api/publications
https://researka.org/papers/<publication_id>
https://researka.org/submissions/<submission_id>/decision
```

When public API says published but bot ledger says `published=0`, the issue is bot ledger sync drift, not public publishing failure.

## 11. Publication Ledger Reconciliation

Reconciliation lives in `scripts/daily_research_paper_cycle.py`.

Behavior:

```text
reconcile_publication_ledgers()
  -> fetch remote public publications
  -> match local ledgers by title/fingerprint/submission markers
  -> set published=1
  -> clear stale no_submission_reason
  -> write publication_reconciliation block
```

This was recently hardened because multiple papers were public while old bot ledgers still carried stale fields like:

```text
published=0
no_submission_reason="journal_surface_not_passed"
```

The correct state for a public paper is:

```text
status="published"
published=1
no_submission_reason absent/cleared
publication_reconciliation.source="remote_publications"
```

The reconcile timer runs every 15 minutes. If heartbeat noise keeps reporting stale ledgers, first run:

```bash
ssh -i ~/.ssh/binance_futures_tool root@100.96.74.1 \
  'cd /opt/research-agent-bot && .venv/bin/python scripts/daily_research_paper_cycle.py --reconcile-publications'
```

Then re-read the exact date-scoped ledger under:

```text
runs/_daily_research_paper_cycle_ledger/
runs/_daily_research_paper_ledger/
```

Do not trust root-level `latest` paths unless you verified they exist on that deploy.

## 12. Systemd Operations

View timers:

```bash
ssh -i ~/.ssh/binance_futures_tool root@100.96.74.1 \
  'systemctl list-timers "research-agent-paper*" --all'
```

View unit definitions:

```bash
ssh -i ~/.ssh/binance_futures_tool root@100.96.74.1 \
  'systemctl cat research-agent-paper-fresh.timer research-agent-paper-revise.timer research-agent-paper-reconcile.timer research-agent-paper-daily-submit.timer research-agent-paper-fresh.service research-agent-paper-revise.service research-agent-paper-reconcile.service research-agent-paper-daily-submit.service'
```

View current status:

```bash
ssh -i ~/.ssh/binance_futures_tool root@100.96.74.1 \
  'systemctl status research-agent-paper-fresh.service --no-pager -l'
```

View logs:

```bash
ssh -i ~/.ssh/binance_futures_tool root@100.96.74.1 \
  'journalctl -u research-agent-paper-fresh.service -n 120 --no-pager'
```

Manual fresh run:

```bash
ssh -i ~/.ssh/binance_futures_tool root@100.96.74.1 \
  'cd /opt/research-agent-bot && set -a && . /etc/research-agent-bot/research-agent-bot.env && set +a && .venv/bin/python scripts/daily_research_paper_cycle.py --mode fresh --run-synthesis --submit --max-attempts 0 --cycle-budget-sec 6000'
```

Manual revise run:

```bash
ssh -i ~/.ssh/binance_futures_tool root@100.96.74.1 \
  'cd /opt/research-agent-bot && set -a && . /etc/research-agent-bot/research-agent-bot.env && set +a && .venv/bin/python scripts/daily_research_paper_cycle.py --mode revise --run-synthesis --submit --max-revise-attempts 2 --cycle-budget-sec 2400'
```

Manual reconciliation:

```bash
ssh -i ~/.ssh/binance_futures_tool root@100.96.74.1 \
  'cd /opt/research-agent-bot && set -a && . /etc/research-agent-bot/research-agent-bot.env && set +a && .venv/bin/python scripts/daily_research_paper_cycle.py --reconcile-publications'
```

Use `/etc/research-agent-bot/research-agent-bot.env` on VPS. Never print tokens.

## 13. Git And Deploy Discipline

Standard local checks:

```bash
git status --short
.venv/bin/python -m ruff check agent scripts tests
.venv/bin/python -m mypy --no-incremental --explicit-package-bases --ignore-missing-imports scripts/run_v06_synthesis.py scripts/table_renderer.py agent/journal_surface_gate.py
.venv/bin/python -m pytest -q
```

Deploy discipline:

```text
1. Start from clean local tree.
2. Commit intentionally.
3. Push branch/main as intended.
4. Fast-forward live VPS checkouts.
5. Verify HEAD and dirty=0 on MacBook, GitHub, /opt, /root.
6. Verify timers/services.
7. Verify public API/page if publication behavior was touched.
```

Canonical SSH:

```bash
ssh -o BatchMode=yes -o ConnectTimeout=8 -i ~/.ssh/binance_futures_tool root@49.12.7.18
ssh -o BatchMode=yes -o ConnectTimeout=8 -i ~/.ssh/binance_futures_tool root@100.96.74.1
```

The public SSH endpoint may intermittently refuse extra concurrent connections. Use the Tailscale IP before declaring VPS unreachable.

Current recent commits at handover:

```text
7b719c3f Let publication reconciliation scan all dates
731bf6e3 Harden stale published ledger regression
fd9c150c Use public publications API for v3 reconciliation
e407ccd7 Reconcile v3 publication ledgers between runs
ab5816db Preserve receipt repair progress
33e83618 Extend receipt preflight repair
29af0bb5 Guard publication proof fingerprints
3afab572 Reconcile public publication ledger drift
a8591a0d Auto-repair null coding reconciliation before submit
8851d2f6 Block high-null source-bundle mismatch submissions
```

## 14. Monitoring And Heartbeats

The monitoring task checks:

```text
fresh lane service
revise lane service
latest cycle ledgers
latest Researka review/publication status
MacBook/GitHub/VPS HEAD
dirty state on /opt, /opt/VPS, /root paths
public API/page proof
```

Classification rule:

```text
NOTIFY if:
- blocker
- sync drift
- dirty state
- missing/non-git target
- acceptance/publication evidence
- failed/incomplete submission

DONT_NOTIFY only if:
- all checked components healthy/clean/in-sync
- no blocker
- no publication/status evidence to surface
```

If a publication just happened, even if healthy, it is evidence to surface.

Common heartbeat false positives to avoid:

```text
- Claiming /opt/VPS or /root/research-agent-bot status without actually checking them.
- Looking for ledgers under repo root instead of runs/.
- Treating accepted/public API proof as "ledger clean" without reading the bot ledger.
- Treating status="published" with stale no_submission_reason as clean.
- Reporting service health from one command without raw status snippets.
```

## 15. History And Why The System Looks Like This

Early V0/V1:

```text
V0 produced credibility-fatal contradictions, e.g. one artifact could describe the same source as both a completed published RCT and an unpublished protocol.
The fix was not more prompt tuning. The fix was a deterministic-first architecture.
```

Proof 001:

```text
Archived LLM-coupled trust-spine modules.
Introduced deterministic claim court, typed claim graph, citation trace, and SPAR court.
Markdown became rendering, not truth.
```

Day 10 paper engine:

```text
The user needed full research papers, not short structured briefs.
The project added synthesis schemas, paper writer, audit gates, receipt funnel, journal surface gate, RoB/GRADE, meta-analysis primitives, template-language gate, and publication scoring.
```

May 9 state:

```text
AGENTS.md and PROJECT_STATE.md still describe the paper-quality mission and old rapamycin sprint.
They are contractually important but not fully current on June v3 ops/timers/publication automation.
```

June 2026 v3 ops:

```text
The bot moved into fresh/revise/reconcile/daily-submit lanes.
Fresh lane should always attempt new papers.
Revise lane should process real actionable revise requests without blocking fresh.
Reconcile lane should keep bot ledgers aligned with public Researka truth.
```

Important June fixes:

```text
Reviewer revise gate:
  "revise" now requires concrete required_revisions.

Wrongly blocked historical papers:
  requeue as new truthful submissions; do not backdate.

Receipt repair:
  repair should continue from existing good receipts, not restart at zero.

Null coding/source-bundle reconciliation:
  auto-repair before submit, and block high-null mismatches.

Publication proof:
  guard remote fingerprints and use public publications API for reconciliation.

Ledger drift:
  published public papers must set published=1 and clear stale no_submission_reason.

Database selector:
  bug was too-strict title matching, not lack of facts/papers.
```

## 16. Known Current Risks

1. Some source topics still hit source-topic precision blockers. Example seen recently:

```text
fasting_metabolism_effects
source_precision_repair_incomplete
source_topic_precision_low:0/120<0.50
off_topic_quant_claims_quarantined=240
```

This is not a Researka publication failure. It is the bot refusing a bad source bundle.

2. The latest active run at handover (`gait_speed_longevity`) was still in progress. Check its ledger and public API before saying whether it published.

3. `AGENTS.md` and `PROJECT_STATE.md` contain stale May 9 operational details. They still define the architecture/contract, but live service names and lane structure are newer.

4. Final citation artifacts do not necessarily expose database provenance labels. Database proof must be checked through adapter configuration, generated packs, source/retrieval stats, or query probes.

5. There are multiple git paths on VPS. Verify every path before reporting sync state.

6. Publication truth requires both bot ledger and Researka public API/page. One side alone is not enough for "all good".

## 17. Debug Playbooks

### "Did It Publish?"

Check in this order:

```bash
# 1. Latest bot ledgers
ssh -i ~/.ssh/binance_futures_tool root@100.96.74.1 \
  'cd /opt/research-agent-bot && ls -lt runs/_daily_research_paper_cycle_ledger/*.json runs/_daily_research_paper_ledger/*.json | head'

# 2. Read newest fresh/daily JSON
ssh -i ~/.ssh/binance_futures_tool root@100.96.74.1 \
  'cd /opt/research-agent-bot && python3 - <<PY
import json, pathlib
for p in sorted(pathlib.Path("runs/_daily_research_paper_cycle_ledger").glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True)[:5]:
    d=json.loads(p.read_text())
    print(p, d.get("status"), d.get("topic_slug"), d.get("submitted"), d.get("published"), d.get("publication_url"), d.get("no_submission_reason"))
PY'
```

Then check Researka public API and page using the submission/publication id from the ledger.

Answer format should separate:

```text
candidate selected
submit eligible
submitted
accepted
publicly published
bot ledger reconciled
```

### "Why Was It Blocked?"

Read:

```text
pre_submit_gate.json
full_paper.final_verdict.json
full_paper.journal_surface.json
audit/receipt_funnel.json
debug/numeric_claim_quarantine.json
debug/qei_quarantined.json
cycle ledger no_submission_reason
```

Common blockers:

```text
source_topic_precision_low
too few receipts
too few quant claims
journal_surface_not_passed
high-null source-bundle mismatch
duplicate/previously published fingerprint
remote reject or revise decision
```

### "Public API Published, Ledger Says Not Published"

This is sync drift. Run reconcile:

```bash
ssh -i ~/.ssh/binance_futures_tool root@100.96.74.1 \
  'cd /opt/research-agent-bot && set -a && . /etc/research-agent-bot/research-agent-bot.env && set +a && .venv/bin/python scripts/daily_research_paper_cycle.py --reconcile-publications'
```

Then check the date-scoped ledger. Expected repaired fields:

```text
status=published
published=1
no_submission_reason cleared
publication_reconciliation present
```

### "Reviewer Said Revise But Gave No Revisions"

That should now be rejected as malformed reviewer output unless the paper already meets strict accept contract. Check:

```text
runtime_core/workflow.py in Researka v2
runtime_core/reviewer_panel.py in Researka v2
```

This is a Researka review-layer concern, not bot source selection.

### "There Are 22M Facts, Why Only 7 Receipts?"

Do not assume the database lacks evidence. Check the funnel:

```text
topic enumeration
generated pack publishability
query/topic matching
candidate source count
claim extraction count
claim confidence
source-topic precision
receipt admission
repair continuation
```

The bot can see the database if:

```text
RESEARKA_DATABASE_TOKEN present
Researka source registry currently_enabled=True
ResearkaClient search_result returns status ok and hits
```

But database access does not guarantee every topic will pass source precision.

## 18. New Developer First Few Hours

Hour 0-1:

```text
Read:
- AGENTS.md
- PROJECT_STATE.md
- README.md
- docs/HANDOVER_AZ_2026-06-06.md

Then run:
- git status --short --branch
- git log --oneline -20
```

Hour 1-2:

```text
Read code:
- scripts/daily_research_paper_cycle.py
- scripts/daily_research_paper_submit.py
- agent/sources/aggregator.py
- agent/sources/researka.py
- agent/journal_surface_gate.py
- agent/final_gate.py
```

Hour 2-3:

```text
Inspect one successful run:
- runs/synthesis-resveratrol_biomarker_effects-v06-DAILY-2026-06-06T08-03-43Z/
- manifest.json
- audit/receipt_funnel.json
- pre_submit_gate.json
- full_paper.final_verdict.json
- paper_quality_score.json
- full_paper.md
```

Hour 3-4:

```text
Verify live:
- timers
- service status
- newest date-scoped ledgers
- Researka publication API/page
- DB adapter probe
- MacBook/GitHub/VPS HEAD and dirty state
```

End of first day:

```text
Be able to explain:
- what a topic pack is
- what a receipt is
- why source precision can block a topic
- what submit eligible means
- why accepted != published
- why public published != bot ledger reconciled
- how to run fresh/revise/reconcile manually
- where to find hard evidence for a publication
```

## 19. Future State

Most valuable next work:

1. Keep ledger reconciliation boring.

```text
No stale published=0 after public publication.
No stale no_submission_reason on published ledgers.
Date-scoped ledger lookup should be easy and maybe exposed by a helper.
```

2. Improve source precision repair.

```text
When a topic has facts but bad source-topic precision, broaden/adjust retrieval intelligently.
Keep good receipts.
Quarantine off-topic quant claims.
Do not lower precision floors just to publish.
```

3. Make database utilization more observable.

```text
Expose source stats in ledgers/run artifacts.
Show how many candidates came from researka/database vs public APIs.
Keep final citations paper-native, but preserve upstream source provenance in audit sidecars.
```

4. Refresh project docs.

```text
AGENTS.md and PROJECT_STATE.md should be updated from May 9 paper-quality sprint language to June v3 lane ops while preserving the trust-spine rule.
```

5. Add a status helper.

```text
One script should print:
- HEAD/dirty for all paths
- timer/service state
- newest ledgers
- latest submission decision
- latest public publication
- DB adapter status
```

This would reduce heartbeat hallucination risk.

6. v4 future.

```text
Research-Agent-Bot-v4 should become one shared alpha core with domain packs, not cloned bots per domain.
For v3, keep longevity default stable unless explicitly migrating.
```

## 20. Do Not Do These

```text
Do not backdate publications.
Do not rewrite old Researka decisions.
Do not claim publication from a submit POST.
Do not claim clean sync without checking MacBook, GitHub, /opt, /opt/VPS, /root paths.
Do not report /opt/VPS or /root/research-agent-bot if you did not actually verify them.
Do not lower receipt/source precision gates just because the corpus is large.
Do not treat final markdown as source of truth.
Do not print secrets from /etc/research-agent-bot/research-agent-bot.env.
Do not edit unrelated dirty files.
Do not merge Researka platform/public UI bugs into bot fixes.
```

## 21. Minimal Command Packet

Use this to orient quickly:

```bash
cd "/Users/domininclynch/Desktop/Business/Research Agent Bot"
git status --short --branch
git log --oneline --decorate -10

ssh -o BatchMode=yes -o ConnectTimeout=8 -i ~/.ssh/binance_futures_tool root@100.96.74.1 '
set -e
cd /opt/research-agent-bot
echo "NOW=$(date -Is)"
echo "HEAD=$(git rev-parse --short=12 HEAD)"
echo "BRANCH=$(git branch --show-current)"
echo "DIRTY=$(git status --porcelain | wc -l | tr -d " ")"
systemctl is-active research-agent-paper-fresh.timer research-agent-paper-revise.timer research-agent-paper-reconcile.timer research-agent-paper-daily-submit.timer
systemctl is-active research-agent-paper-fresh.service research-agent-paper-revise.service research-agent-paper-reconcile.service research-agent-paper-daily-submit.service || true
ls -lt runs/_daily_research_paper_cycle_ledger/*.json runs/_daily_research_paper_ledger/*.json | head -20
'
```

Database probe:

```bash
ssh -i ~/.ssh/binance_futures_tool root@100.96.74.1 '
cd /opt/research-agent-bot
set -a && . /etc/research-agent-bot/research-agent-bot.env && set +a
.venv/bin/python - <<PY
import asyncio, httpx, os
from agent.sources.aggregator import list_available_sources
from agent.sources.researka import ResearkaClient
print("RESEARKA_DATABASE_TOKEN_PRESENT", bool(os.getenv("RESEARKA_DATABASE_TOKEN")))
print("RESEARKA_REGISTRY", [s for s in list_available_sources() if s["name"] == "researka"])
async def main():
    async with httpx.AsyncClient(timeout=30.0) as http:
        res = await ResearkaClient().search_result(http, "gait speed longevity", limit=5)
    print("DB_SEARCH_STATUS", res.status)
    print("DB_SEARCH_HITS", len(res.hits))
    for h in res.hits[:3]:
        print("HIT", h.source, "facts", len(h.raw.get("database_facts") or []), "paper_id", h.raw.get("paper_id"), "title", h.title[:80])
asyncio.run(main())
PY
'
```

## 22. Glossary

```text
Topic pack:
  Structured topic definition used to drive retrieval and synthesis.

Generated pack:
  Topic pack materialized from database facts/topic coverage.

Receipt:
  One admitted contributing paper with extracted claims and tier/directness coding.

Strict high:
  Higher-confidence claim/source admission class.

Primary tier:
  Stronger evidence tier receipts used to judge depth.

Source-topic precision:
  Whether extracted claims/sources are actually on the intended topic.

Pre-submit gate:
  Deterministic check before the bot can POST to Researka.

Submit bridge:
  Code that posts eligible papers to Researka intake.

Revise lane:
  Bot lane that handles real actionable Researka revise decisions.

Fresh lane:
  Bot lane that attempts new papers regardless of revise backlog.

Reconcile lane:
  Bot lane that aligns local ledgers with Researka public publication truth.

Publication drift:
  Public Researka API/page and bot ledgers disagree.

Trust spine:
  Machine-readable audit sidecars and deterministic gates that own truth.
```

## 23. Evidence Used For This Handover

This handover was built from:

```text
CodeGraph structural context for Research Agent Bot.
Vibe Coding Playbook v4 via knowledge MCP.
Local AGENTS.md, PROJECT_STATE.md, README.md, DECISIONS.md.
Live MacBook git status/log.
Live VPS git/timer/service/ledger checks over SSH.
Live Researka Database adapter probe from the VPS runtime.
Recent operational memory around June reviewer-gate, ledger drift, and database selector fixes.
```

Most important live snippets:

```text
LOCAL_BRANCH=codex/019e0b4c/main
LOCAL_HEAD=7b719c3fa798
GITHUB_HEAD=7b719c3fa798
VPS_HEAD=7b719c3fa798
VPS_DIRTY=0

research-agent-paper-fresh.timer active
research-agent-paper-revise.timer active
research-agent-paper-reconcile.timer active
research-agent-paper-daily-submit.timer active

runs/_daily_research_paper_cycle_ledger/2026-06-06-fresh.json:
  status=published
  mode=fresh
  submitted=1
  published=1
  publication_reconciliation.source=remote_publications

runs/_daily_research_paper_ledger/2026-06-06.json:
  status=published
  submitted=1
  published=1
  submission_id=8f5a3193-46bd-43a3-8d4d-c3e5240ca299

DB_SEARCH_STATUS ok
DB_SEARCH_HITS 5
```

Before making a fresh "current" claim, rerun the status commands. This document is a handover snapshot, not a live dashboard.
