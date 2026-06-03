# Research Agent Bot v3 Handover

Date: 2026-06-03

Purpose: hand off the v3 internal publishing bot so a new development track can build the customer-facing web interface without confusing bot runtime, Researka review, public publication, and website display.

## Executive Status

v3 is the internal paper-producing synthesis engine. It is not the customer-facing website.

Current verified repo state:

```text
local branch: codex/019e0b4c/main
local/root/opt/GitHub HEAD: 5986b416
local/root/opt dirty: 0
/opt tracked ignored generated files: 0
/opt/VPS: missing or not a Git repo
```

Current verified v3 schedule:

```text
fresh lane: every 4 hours at 00/4:00
revise lane: every 4 hours at 00/4:15
live unit path: /opt/research-agent-bot
mirror path: /root/Research-Agent-Bot
```

Current verified publishing/review state from the last monitor pass:

```text
2026-06-03 decisions: reject=1, revise=1
latest public v3 decision: revise
latest title: Research Synthesis: Plasma Proteomic Age Clocks — full paper
latest reviewedAt: 2026-06-03T09:15:12.115278+04:00
latest artifactId: 79f80c0c-dccb-4846-96a7-b3407de8cfa4
latest local sirtuin run: submission_ready=false, no receipt, no daily_cycle_status
```

Interpretation: infrastructure is clean and scheduled; the content pipeline still needs quality/submit-readiness work for failed runs. Do not treat a green timer as proof of public publication.

## Ownership Boundaries

Keep these separate:

- Bot candidate generation: v3 creates runs under `runs/synthesis-*`.
- Submit eligibility: deterministic gates decide `submission_ready`.
- Researka submission: `researka_submission_receipt.json` or submit ledger proves a POST happened.
- Researka review decision: public `/reviews` page or `_decisions_by_day.json` records revise/reject/accept.
- Public website display: the web app renders accepted/review records downstream; it does not prove the bot generated or submitted correctly.

## Primary Repos And Paths

Bot repo:

```text
/Users/domininclynch/Desktop/Business/Research Agent Bot
/opt/research-agent-bot
/root/Research-Agent-Bot
```

Likely customer-facing repo candidates:

```text
/Users/domininclynch/Desktop/Business/RESEARKA.ORG Website
/Users/domininclynch/Desktop/Business/researka-platform-main
/Users/domininclynch/Desktop/Business/Website - Researka.org
```

Observed web-app signals:

- `RESEARKA.ORG Website` contains public components and data loaders such as `components/AcceptedArtifactPage.tsx`, `components/ReviewRecordCard.tsx`, `lib/publicRecords.ts`, `lib/backendRecords.ts`, `pages/index.tsx`, `pages/submit.tsx`, `pages/verify.tsx`, and `pages/methods.tsx`.
- `researka-platform-main` is the broader platform repo with richer auth/types/specs and historical failure notes.
- `Website - Researka.org` appears to be another Next app copy. Confirm ownership before building there.

Recommendation for the new customer-facing track: start by auditing `RESEARKA.ORG Website` and `researka-platform-main`, then choose one canonical web repo. Do not wire UI directly to v3 run folders unless the surface is explicitly internal.

## v3 Architecture Map

Pipeline:

```text
topic pack
  -> source retrieval / corpus seeding
  -> source admission / evidence-tier classification
  -> claim cards / citation registry / tension matrix
  -> v3 synthesis compiler
  -> full paper and supplements
  -> deterministic audit / journal surface / final status
  -> Researka submission bridge
  -> Researka review decision
```

Core orchestration:

- `scripts/daily_research_paper_cycle.py`
  - Main fresh/revise lane orchestrator.
  - Owns mode selection, topic picking, revise routing, preflight thresholds, cooldowns, blocker histograms, daily throughput, decision polling, and revise-reason rollup.
  - Important constants: `PREFLIGHT_MIN_RECEIPTS`, `PREFLIGHT_MIN_QUANT_CLAIMS`, `PREFLIGHT_MIN_TENSIONS`, `MAX_REVISE_ROUNDS`, `DECISIONS_BY_DAY`, `REVISE_REASONS`.

- `scripts/daily_research_paper_submit.py`
  - Submit bridge.
  - Selects ready runs, builds Researka payload, prevents duplicate/rejected/revision fingerprint resubmits, and records submit ledgers.
  - A successful POST means submitted, not accepted.

- `scripts/run_v06_synthesis.py`
  - Main synthesis runner used by the daily cycle.
  - Produces run directories and paper sidecars.

Paper/trust spine:

- `agent/journal_finalizer.py`
  - Builds final paper sections and prose repair paths.

- `agent/journal_surface_gate.py`
  - Deterministic surface/prose gate. Recent work tightened grammar artifact detection.

- `agent/final_status.py`
  - One source of truth for `submission_ready`.

- `agent/submission_package.py`
  - Composes submission package from final status, paper, and required sidecars.

- `scripts/revision_coverage.py`
  - Maps reviewer requests to deterministic repair/coverage checks.

Data/source access:

- `agent/sources/researka.py`
  - Uses Researka DB endpoints, including `/api/v1/search` and `/api/v1/tier2/facts/search`.

- `scripts/materialize_fact_topic_packs.py`
  - Materializes fact-backed topic packs from DB/topic-group endpoints.

- `docs/quality-reference/`
  - Runtime-generated corpus cache. This is intentionally ignored/untracked after `5986b416`.

## Live Systemd Units

Deployed unit files in repo:

```text
deploy/research-agent-paper-fresh.timer
deploy/research-agent-paper-revise.timer
deploy/research-agent-paper-fresh.service
deploy/research-agent-paper-revise.service
```

Timer schedule:

```ini
# fresh
OnCalendar=*-*-* 00/4:00:00

# revise
OnCalendar=*-*-* 00/4:15:00
```

Service commands:

```text
fresh:
/opt/research-agent-bot/.venv/bin/python scripts/daily_research_paper_cycle.py --mode fresh --run-synthesis --submit --max-attempts 5 --cycle-budget-sec 6000

revise:
/opt/research-agent-bot/.venv/bin/python scripts/daily_research_paper_cycle.py --mode revise --run-synthesis --submit --max-revise-attempts 2 --cycle-budget-sec 2400
```

Environment file:

```text
/etc/research-agent-bot/research-agent-bot.env
```

Important observed keys:

```text
RESEARKA_AGENT_SLUG_V3=agent-v3-full-paper-live
AGENT_ID=agent-v3-full-paper-live
```

Do not paste secrets from the env file into tickets, handovers, or model context.

## Current Ledgers And Artifacts

Cycle ledger dir:

```text
runs/_daily_research_paper_cycle_ledger/
```

Important files:

```text
_decisions_by_day.json
_revise_reasons.json
_daily_throughput_summary.json
_blocker_histogram.json
_handled_revision_requests.json
```

Observed current issue:

```text
runs/_daily_research_paper_cycle_ledger/2026-06-03.json was absent in the latest check.
```

That means do not assume per-day cycle status exists. Use `_decisions_by_day.json`, public `/reviews`, and latest run sidecars together.

Run dirs:

```text
runs/synthesis-<topic>-v06-DAILY-<timestamp>/
```

Key sidecars:

```text
full_paper.md
final_status.json
full_paper.audit.json
pre_submit_gate.json
journal_surface.json
researka_submission_receipt.json
daily_cycle_status.json
manifest.json
claim_graph.json
citation_registry.json
```

If `final_status.json` says `submission_ready=false` and there is no `researka_submission_receipt.json`, the run did not submit.

## Recent History

Recent commits at handoff:

```text
5986b416 Stop tracking generated corpus cache
fcd81c8b Tighten grammar surface artifact gate
5cecd412 Add prose surface gate regressions
4fe2221d Keep conflict severity note public safe
215fa799 Fix synthesis mypy script imports
1e155d9e Handle conflict severity revision asks
3a3875cc Tighten evidence honesty revise coverage
```

Meaning:

- `5986b416` fixed repo cleanliness by untracking already-ignored generated corpus/log files. Runtime cache remains on `/opt` but Git is clean.
- `fcd81c8b` and `5cecd412` are prose/surface-gate work.
- The bot moved from a 2-hour cadence to a 4-hour internal publishing cadence.
- The fresh/revise lanes are separated and staggered; revise should not block fresh.

## Known Current Blockers / Risks

1. `/opt/VPS` monitor target is missing or not a Git repo.
   - Current monitor output: `OPT_VPS_MISSING_OR_NOT_GIT=1`.
   - Decide whether this path is obsolete and remove it from the monitor, or restore the expected repo.

2. Latest run did not submit.
   - Latest observed sirtuin run had `submission_ready=false`.
   - Missing `researka_submission_receipt.json`, `daily_cycle_status.json`, and `journal_surface.json`.
   - This is a pipeline/readiness problem, not a timer outage.

3. Latest public review is `revise`.
   - Public `/reviews` page showed Plasma Proteomic Age Clocks revised at `2026-06-03T09:15:12+04`.
   - Some revise records have empty `requiredRevisions`; route carefully.

4. Accept/publication truth must be checked from public Researka data, not screenshots or local submissions alone.

5. Project state docs are stale.
   - `AGENTS.md` and `PROJECT_STATE.md` still contain May 9 mission details and old service naming in places.
   - This handover supersedes those sections for June 3 operational truth, but the files should be formally updated in a separate doc-cleanup slice.

## Verification Commands

Local/GitHub:

```bash
cd "/Users/domininclynch/Desktop/Business/Research Agent Bot"
git rev-parse --short=8 HEAD
git status --short
git ls-remote --heads origin codex/019e0b4c/main claude/3809304f/main
```

VPS sync/services:

```bash
ssh -i ~/.ssh/binance_futures_tool root@49.12.7.18 '
cd /root/Research-Agent-Bot && git rev-parse --short=8 HEAD && git status --short
cd /opt/research-agent-bot && git rev-parse --short=8 HEAD && git status --short
systemctl show research-agent-paper-fresh.timer research-agent-paper-revise.timer -p Id -p ActiveState -p SubState -p NextElapseUSecRealtime
systemctl show research-agent-paper-fresh.service research-agent-paper-revise.service -p Id -p ActiveState -p SubState -p Result -p NRestarts -p ExecMainStatus
'
```

Public review:

```bash
ssh -i ~/.ssh/binance_futures_tool root@49.12.7.18 '
cd /opt/research-agent-bot
set -a && . /etc/research-agent-bot/research-agent-bot.env && set +a
PYTHONPATH=scripts:. python3 - <<PY
from scripts.daily_research_paper_cycle import _latest_reviews_by_title, _review_ts
latest, err = _latest_reviews_by_title()
print("ERR", err)
for row in sorted(latest.values(), key=_review_ts)[-5:]:
    print(row.get("reviewedAt"), row.get("decision"), row.get("agentId"), row.get("title"), row.get("artifactId"))
PY
'
```

Latest run sidecars:

```bash
ssh -i ~/.ssh/binance_futures_tool root@49.12.7.18 '
cd /opt/research-agent-bot
python3 - <<PY
import json
from pathlib import Path
for p in sorted(Path("runs").glob("synthesis-*/final_status.json"), key=lambda x: x.stat().st_mtime, reverse=True)[:5]:
    d=json.loads(p.read_text())
    print(p)
    print({"submission_ready": d.get("submission_ready"), "status": d.get("status"), "reason": d.get("reason")})
    print("receipt", (p.parent/"researka_submission_receipt.json").exists(), "daily_cycle_status", (p.parent/"daily_cycle_status.json").exists(), "surface", (p.parent/"journal_surface.json").exists())
PY
'
```

## Customer-Facing Track Recommendation

Do not start by redesigning the bot. Start by building a thin customer-facing status/reader layer around already-public truths.

Smallest useful vertical slice:

1. Choose canonical web repo.
   - Likely first target: `RESEARKA.ORG Website`.
   - Verify against `researka-platform-main` before committing to avoid duplicate frontend work.

2. Build an internal/public dashboard page with four separate columns:
   - Generated run
   - Submit eligibility / receipt
   - Researka review decision
   - Public accepted/published brief

3. Data contract for the web layer:
   - Do not read arbitrary local `runs/` directly for public users.
   - Prefer Researka public/backend records for customer-facing pages.
   - Use bot ledgers only for internal operator dashboard/debug views.

4. UX principle:
   - Show exactly what happened, not an optimistic status.
   - Use labels like `generated`, `not submission-ready`, `submitted`, `revise`, `reject`, `accept`, `published`.
   - Avoid saying `published` when only `submitted` is proven.

5. First customer-facing pages to build:
   - Public accepted briefs index.
   - Individual brief page with provenance/evidence panels.
   - Review decision record page.
   - Internal operator lane dashboard.
   - Topic/publication queue health page.

Existing web files likely relevant:

```text
RESEARKA.ORG Website/components/AcceptedArtifactPage.tsx
RESEARKA.ORG Website/components/ReviewRecordCard.tsx
RESEARKA.ORG Website/components/EvidenceTransparencyPanel.tsx
RESEARKA.ORG Website/components/ProvenancePanel.tsx
RESEARKA.ORG Website/lib/publicRecords.ts
RESEARKA.ORG Website/lib/backendRecords.ts
RESEARKA.ORG Website/lib/trustData.ts
RESEARKA.ORG Website/pages/index.tsx
RESEARKA.ORG Website/pages/verify.tsx
RESEARKA.ORG Website/pages/methods.tsx
```

## Suggested New-Track First Prompt

```text
We are starting the customer-facing Researka web track. Read:
1. /Users/domininclynch/Desktop/Business/Research Agent Bot/docs/HANDOVER_v3_to_customer_facing_2026-06-03.md
2. /Users/domininclynch/Desktop/Business/RESEARKA.ORG Website/PROJECT_STATE.md
3. /Users/domininclynch/Desktop/Business/RESEARKA.ORG Website/package.json

Goal: build a small, truthful customer-facing interface for accepted briefs and review decisions.
Non-goal: do not change v3 bot generation/scheduling.
Success: public UI separates generated/submitted/reviewed/accepted/published states and does not overclaim.
Use minimal LOC, no hardcoding, and verify with tests plus browser screenshot.
```

## Open Cleanup Tasks Before Heavy Web Work

- Decide whether `/opt/VPS` is obsolete. If obsolete, remove it from the monitor instructions. If required, restore it as a real Git checkout.
- Update `AGENTS.md` and `PROJECT_STATE.md` to reflect June 3 reality: v3 paper lanes, 4-hour schedule, `/opt` + `/root` paths, current branch, public review truth.
- Add a compact operator status command/script so heartbeats do not reimplement long shell snippets every time.
- Investigate why the latest local sirtuin run lacks `journal_surface.json`, `daily_cycle_status.json`, and `researka_submission_receipt.json`.
- Treat empty `requiredRevisions` revise decisions as a distinct state in revise routing/reporting.

## What Not To Do

- Do not merge v3 bot internals into the customer-facing website.
- Do not use local run folders as public source of truth unless a backend API intentionally exposes them.
- Do not call a paper published because the bot submitted it.
- Do not reintroduce tracked generated corpus cache files.
- Do not deploy from a dirty tree.
- Do not paste VPS passwords or API tokens into docs, tickets, or model context.
