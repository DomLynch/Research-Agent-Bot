# V3 Unattended Publishing Handover - 2026-07-02

Audience: GPT Pro / external audit.

Scope: Research Agent Bot v3 only. Do not use this packet as proof for v4, v5,
or v6. Do not borrow proof from other agent lanes.

## Codex Follow-Up - 2026-07-02

This supersedes the earlier red-gate snapshot below. A later same-topic revise
published `aerobic_exercise_training_effects`, so the live consistency gate can
turn green while the original fresh lane remains `submitted=1, published=0`.

Implemented follow-up:

- dated reconcile artifacts are written for dated reconcile runs, including
  no-op runs;
- reconcile output now includes compact review decision counts/examples with
  submission IDs where available;
- throughput output now includes `public.surface_mix` so brief-vs-full-synthesis
  drift is visible in the normal report.

Remaining product issue: recent accepts are predominantly evidence briefs. That
is an honest direct-evidence downgrade, not a ledger bug; restoring full
Research Syntheses requires stronger direct, on-entity corpus supply.

## Executive State

V3 is publicly publishing again, but full unattended consistency is not proven.

Current gate state at the latest audit pass:

```text
GATE_PASS False
GATE_BLOCKERS ['fresh:not_published']
GATE_PUBLIC_ACCEPTS 7
GATE_PUBLIC_ACCEPTS_AFTER_MIN 3
TODAY_OBSERVED {'local_published': 1, 'local_submitted': 3, 'observed_published': 2, 'public_accepts': 2}
LANE daily-submit no_eligible_research_paper None 2026-07-01T22:15:19.653057+00:00 0 0 None None
LANE fresh submitted_to_researka 2026-07-02T04:00:00.637767+00:00 None 1 0 aerobic_exercise_training_effects None
LANE revise no_revise_pending 2026-07-02T04:15:00.329684+00:00 None 0 0 None None
```

Plain English:

- Public side: healthy enough to show 2 v3 accepts on Brain date 2026-07-02.
- Local/gate side: still false because the latest completed fresh lane is
  `submitted_to_researka` with `published=0`.
- Sync side: clean across MacBook, GitHub, VPS `/opt`, and VPS `/root`.
- Exact SHA caveat: requested SHA `1d70e4658d757cc3afa53358d702965972b1a23c`
  is not the live head. It is a clean ancestor, 32 commits behind live
  `2d6fc62673d4b473efbd432a3bb4cbed6783869f`.

## Current Live Sync

Canonical branch:

```text
origin/codex/019e9ce8/main
```

Latest synced code before this handover doc:

```text
2d6fc62673d4b473efbd432a3bb4cbed6783869f
```

Verified sync before writing this doc:

```text
LOCAL_SYNC live=2d6fc62673d4b473efbd432a3bb4cbed6783869f origin=2d6fc62673d4b473efbd432a3bb4cbed6783869f origin_match=yes dirty=0 exact_requested=no ancestor_rc=0 commits_after=32
VPS_SYNC repo=/opt/research-agent-bot live=2d6fc62673d4b473efbd432a3bb4cbed6783869f dirty=0 exact_requested=no ancestor_rc=0 commits_after=32
VPS_SYNC repo=/root/Research-Agent-Bot live=2d6fc62673d4b473efbd432a3bb4cbed6783869f dirty=0 exact_requested=no ancestor_rc=0 commits_after=32
```

Important interpretation:

- This is clean synced descendant verification.
- It is not exact-SHA verification of `1d70e4658d757cc3afa53358d702965972b1a23c`.
- If the audit must be exact to `1d70e4658d757cc3afa53358d702965972b1a23c`,
  the current live tree does not satisfy that premise.

## Public Evidence

Endpoint:

```text
https://researka.org/api/publications
```

Latest fetch:

```text
HTTP/2 200
PUBLIC_TOTAL_ROWS 141
V3_ACCEPTS_TOTAL 117
V3_ACCEPTS_AFTER_MIN 3
V3_ACCEPTS_BRAIN_2026_07_02 2
```

Latest v3 public rows:

```text
utc=2026-07-01T22:13:46.641128+00:00
brain=2026-07-02T02:13:46.641128+04:00
doi=10.17605/OSF.IO/FP9EA
title=Hypothesis-Generating Brief: Ramadan Fasting Effects
url=https://researka.org/papers/60d2c379-d1f7-471e-9252-90414e695085

utc=2026-07-01T20:09:49.444490+00:00
brain=2026-07-02T00:09:49.444490+04:00
doi=10.17605/OSF.IO/XD9WQ
title=Adjacent Evidence Brief: Calcium Supplementation Effects - full paper
url=https://researka.org/papers/798fcdb7-5e51-43e8-978e-937dfca0ad1c

utc=2026-06-29T21:21:25.951612+00:00
brain=2026-06-30T01:21:25.951612+04:00
doi=10.17605/OSF.IO/4U3AE
title=Adjacent Evidence Brief: Physical Exercise Effects - full paper
url=https://researka.org/papers/ba5db8d2-cb82-4c8c-9e0f-d9b682baf215
```

Public evidence says v3 is publishing. It does not by itself prove the unattended
fresh lane and ledger/reconcile proof chain is fully consistent.

## Latest Gate And Lane State

Gate command:

```bash
cd /opt/research-agent-bot
.venv/bin/python scripts/daily_research_paper_throughput_report.py \
  --date 2026-07-02 \
  --consistency-public-accept-baseline 4 \
  --consistency-min-started-at 2026-06-29T16:30:00+00:00
```

Latest gate output:

```text
GATE_PASS False
GATE_BLOCKERS ['fresh:not_published']
GATE_PUBLIC_ACCEPTS 7
GATE_PUBLIC_ACCEPTS_AFTER_MIN 3
TODAY_OBSERVED {'local_published': 1, 'local_submitted': 3, 'observed_published': 2, 'public_accepts': 2}
```

Latest lane receipts:

```text
daily-submit:
  status=no_eligible_research_paper
  started_at=None
  updated_at=2026-07-01T22:15:19.653057+00:00
  submitted=0
  published=0

fresh:
  status=submitted_to_researka
  started_at=2026-07-02T04:00:00.637767+00:00
  submitted=1
  published=0
  topic=aerobic_exercise_training_effects

revise:
  status=no_revise_pending
  started_at=2026-07-02T04:15:00.329684+00:00
  submitted=0
  published=0
```

Service log evidence:

```text
Jul 02 08:19:14 Brain python[2913693]: [daily-v3-cycle] status=submitted_to_researka attempted_topic=aerobic_exercise_training_effects submitted_topic=aerobic_exercise_training_effects submitted=1 published=0
Jul 02 08:19:14 Brain systemd[1]: Finished research-agent-paper-fresh.service - Research Agent v3 FRESH lane - always attempt a new paper (never blocked by revise backlog).
```

Service status at last check:

```text
research-agent-paper-fresh.service active=inactive failed=inactive
research-agent-paper-fresh.timer active=active failed=active enabled=enabled
research-agent-paper-revise.service active=inactive failed=inactive
research-agent-paper-revise.timer active=active failed=active enabled=enabled
research-agent-paper-daily-submit.service active=inactive failed=inactive
research-agent-paper-daily-submit.timer active=active failed=active enabled=enabled
research-agent-paper-reconcile.service active=inactive failed=inactive
research-agent-paper-reconcile.timer active=active failed=active enabled=enabled
```

No failed v3 units were listed by:

```bash
systemctl --failed --no-legend | grep -E "research-agent|paper|v3"
```

## Reconcile State

Latest reconcile log:

```text
Jul 02 10:05:14 Brain python[2959779]: [daily-v3-cycle] status=no_publication_reconciliation_needed checked=71 updated=0 ledgers=-
```

Current artifact check:

```text
runs/_daily_research_paper_cycle_ledger/2026-07-02-reconcile.json: missing
```

Interpretation:

- The reconcile service is running and reporting a no-op state.
- There is no dedicated current-date reconcile JSON artifact.
- Audit question: is the missing reconcile artifact expected by design, or should
  reconcile persist a current-date ledger even on no-op?
- Do not use the reconcile log alone to claim full unattended consistency unless
  the audit accepts log-only reconcile proof.

## Progress Made

The branch now has public proof that v3 can publish on Brain date 2026-07-02:

- Ramadan Fasting Effects accepted/public.
- Calcium Supplementation Effects accepted/public.
- Public API shows 2 v3 public accepts on Brain date 2026-07-02.
- Mac/GitHub/VPS sync is clean.

Recent v3-relevant commits:

```text
2d6fc626 Cover v3 source-bundle preflight cooldowns
97a2aabe Skip v3 source-bundle preflight repeats
fafdd2c6 Cover v3 same-topic downstream gate
d10e1c00 Fix v3 Ramadan audit gates
84200aa3 Qualify v3 findings map lane notes
6af0b361 Fix terminal v3 finalizer surface cleanup
1889526f Clean unsupported domain frames before submit
e66be5dd Assert generated backstops satisfy domain preflight
```

## Main Remaining Challenges

1. Fresh lane proof gap.
   - Latest fresh lane submitted `aerobic_exercise_training_effects`.
   - The ledger says `submitted=1`, `published=0`.
   - Gate blocks on `fresh:not_published`.
   - Public side has accepted papers, but the latest fresh ledger is not aligned
     with a public receipt.

2. Local/public count mismatch.
   - `local_published=1`
   - `observed_published=2`
   - `public_accepts=2`
   - Audit should verify whether this is expected lag, a ledger reconciliation
     gap, or a bug in the throughput accounting.

3. Reconcile artifact ambiguity.
   - Reconcile logs no-op.
   - Dedicated `2026-07-02-reconcile.json` is missing.
   - Audit should decide whether missing artifact is expected behavior.

4. Exact deployed SHA caveat.
   - Requested SHA `1d70e4658d757cc3afa53358d702965972b1a23c` is not live.
   - Live tree is clean synced descendant `2d6fc62673d4b473efbd432a3bb4cbed6783869f`.
   - Audit should decide whether "after deployed SHA" means descendant is
     acceptable or exact SHA is required.

## Files And Code Pointers

V3 cycle and ledger:

- `scripts/daily_research_paper_cycle.py`
  - fresh/revise/reconcile command implementation.
  - log prefix: `[daily-v3-cycle]`.
  - source-bundle cooldown handling includes `source_bundle_topic_mismatch`.

V3 submit/preflight:

- `scripts/daily_research_paper_submit.py`
  - Researka payload preflight.
  - source bundle topic status, mismatch reasons, and capped cycle behavior.

Throughput/gate:

- `scripts/daily_research_paper_throughput_report.py`
  - consistency gate.
  - public API counting.
  - `fresh:not_published` blocker.
  - local/public observed count comparison.

Finalizer / surface cleanup:

- `scripts/journal_finalizer.py`
  - final paper cleanup and surface constraints.

Tests:

- `tests/test_daily_research_paper_cycle.py`
- `tests/test_daily_research_paper_submit.py`
- `tests/test_daily_research_paper_throughput_report.py`
- `tests/test_journal_finalizer.py`

Deploy/service units:

- `deploy/research-agent-paper-fresh.service`
- `deploy/research-agent-paper-fresh.timer`
- `deploy/research-agent-paper-revise.service`
- `deploy/research-agent-paper-revise.timer`
- `deploy/research-agent-paper-daily-submit.service`
- `deploy/research-agent-paper-daily-submit.timer`
- `deploy/research-agent-paper-reconcile.service`
- `deploy/research-agent-paper-reconcile.timer`

Runtime ledgers on VPS:

```text
/opt/research-agent-bot/runs/_daily_research_paper_cycle_ledger/2026-07-02-fresh.json
/opt/research-agent-bot/runs/_daily_research_paper_cycle_ledger/2026-07-02-revise.json
/opt/research-agent-bot/runs/_daily_research_paper_cycle_ledger/2026-07-02-daily-submit.json
/opt/research-agent-bot/runs/_daily_research_paper_cycle_ledger/2026-07-02-reconcile.json  # currently missing
```

## Full Diff Surface Since Requested SHA

Requested SHA:

```text
1d70e4658d757cc3afa53358d702965972b1a23c
```

Live code SHA before this handover doc:

```text
2d6fc62673d4b473efbd432a3bb4cbed6783869f
```

Files changed between requested SHA and live SHA:

```text
.github/workflows/karpathy-pr.yml
.github/workflows/weekly-reports.yml
agent/outcome_class_remap.py
agent/paper_writer_claim_repair.py
agent/paper_writer_deterministic.py
agent/paper_writer_prompts.py
pyproject.toml
scripts/audit_v06_paper.py
scripts/coverage_audit.py  # deleted
scripts/daily_research_paper_cycle.py
scripts/daily_research_paper_submit.py
scripts/daily_research_paper_throughput_report.py
scripts/generate_eval_corpus.py  # deleted
scripts/generate_fixtures.py  # deleted
scripts/journal_finalizer.py
scripts/review_noise_control.py
scripts/revision_coverage.py
scripts/run_v06_synthesis.py
tests/test_audit_v06_numeric_coverage.py
tests/test_daily_research_paper_cycle.py
tests/test_daily_research_paper_submit.py
tests/test_daily_research_paper_throughput_report.py
tests/test_journal_finalizer.py
tests/test_journal_surface_gate.py
tests/test_outcome_class_remap.py
tests/test_paper_writer_claim_repair.py
tests/test_revision_coverage.py
tests/test_topic_parameterization.py
```

Important: this is the full branch drift since `1d70e465...`, not all of it is
v3-specific. For a strict v3 audit, prioritize the v3 scripts/tests listed above.

## Commands For GPT Pro Audit

Sync check:

```bash
cd /Users/domininclynch/Desktop/Business/Research\ Agent\ Bot
git status --short
git rev-parse HEAD
git ls-remote origin refs/heads/codex/019e9ce8/main
ssh -i ~/.ssh/binance_futures_tool root@100.96.74.1 \
'for d in /opt/research-agent-bot /root/Research-Agent-Bot; do cd "$d"; echo "$d $(git rev-parse HEAD) dirty=$(git status --short | wc -l)"; done'
```

Gate check:

```bash
ssh -i ~/.ssh/binance_futures_tool root@100.96.74.1 \
'cd /opt/research-agent-bot && .venv/bin/python scripts/daily_research_paper_throughput_report.py --date 2026-07-02 --consistency-public-accept-baseline 4 --consistency-min-started-at 2026-06-29T16:30:00+00:00'
```

Service check:

```bash
ssh -i ~/.ssh/binance_futures_tool root@100.96.74.1 \
'for u in research-agent-paper-fresh.service research-agent-paper-fresh.timer research-agent-paper-revise.service research-agent-paper-revise.timer research-agent-paper-daily-submit.service research-agent-paper-daily-submit.timer research-agent-paper-reconcile.service research-agent-paper-reconcile.timer; do echo "$u active=$(systemctl is-active "$u") failed=$(systemctl is-failed "$u") enabled=$(systemctl is-enabled "$u" 2>/dev/null || true)"; done'
```

Public API check:

```bash
curl -sS -D /tmp/researka_headers.txt -o /tmp/researka_publications.json https://researka.org/api/publications
sed -n '1,4p' /tmp/researka_headers.txt
```

## Questions GPT Pro Should Answer

1. Should `submitted_to_researka` with `submitted=1 published=0` be treated as
   a failed scheduled lane, pending public receipt, or accounting lag?
2. Why is public `observed_published=2` while `local_published=1`?
3. Should reconcile create a dated JSON artifact even when it has
   `no_publication_reconciliation_needed`?
4. Is the consistency gate correct to block on `fresh:not_published` when public
   evidence already shows two v3 accepts on the current Brain date?
5. Are the source-bundle cooldown changes sufficient to prevent repeated
   no-output topic attempts without over-suppressing good topics?
6. Does the exact-SHA caveat invalidate the audit premise, or is a clean synced
   descendant acceptable?

## Current Verdict

Do not claim full unattended consistency complete yet.

Claim that is supported:

```text
v3 is publicly publishing, with 2 accepted/public papers on Brain date 2026-07-02.
```

Claim that is not yet supported:

```text
Every scheduled v3 lane has clean ledger/reconcile proof matching public receipts
after baseline 2026-06-29T16:30:00Z.
```

## Handover Publication Note

This packet is intended to live on the canonical GitHub branch
`codex/019e9ce8/main` and be deployed to both VPS mirrors:

```text
/opt/research-agent-bot
/root/Research-Agent-Bot
```

After updating this document, verify MacBook, GitHub, VPS `/opt`, and VPS
`/root` all report the same commit SHA and `dirty=0`.
