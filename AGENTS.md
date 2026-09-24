# AGENTS.md

## Purpose
Research Agent Bot produces audited, source-grounded biomedical research papers.
The current mission is Ivy-League / senior-PhD-grade paper quality: deep corpus,
formal methods, quantitative synthesis where justified, calibrated prose, and a
full trust-spine audit trail.

Researka/public reader/provenance is downstream. This repo's job is the research
agent and paper engine.

## Current State - 2026-08-13
- Last pre-switch clean baseline: `415621b2`.
- Current branch target: Codex GPT-6 Sol High writer/extractor,
  GPT-5.6 Terra Medium review and GLM Flash technical fallback.
- Service: `research-agent-bot.service`.
- Live endpoint: deploy-safe live status page, HTTP 200 by design.
- Basket: 18 full AAA/L5+ primary topics plus 1 scoped topic in cross-topic V1.
- Flagship: rapamycin AAA/L6 reproducibly journal-ready baseline; current
  paper-quality sprint has lifted runner-admitted receipts from 16 to 40 via
  source-validated vocabulary and qualification fixes.
- Writer/extractor: `gpt-6-sol`, High reasoning, via Codex ChatGPT login;
  `WRITER_PROVIDER=codex` and `WRITER_MODEL`/`WRITER_TIMEOUT_SEC` configure it.
  No API-key writer fallback. Old `MIMO_*`/`MINIMAX_*`
  environment variables are ignored; legacy Settings field names remain internal.
- Release configuration uses Codex; pin `CODEX_WRITER_BIN` to the VPS CLI below.
- Outgoing gates read `/etc/research-agent-bot/research-agent-bot.env` only (no
  unit `Environment=`/drop-ins: `EnvironmentFile=` overrides them):
  `RESEARKA_RUNTIME_ROOT=/opt/researka-v2` runs Core's own claim-trace guard and
  `RESEARKA_PREFLIGHT_QA=live` (alias of `enforce`) blocks on preflight criticals.
- Current judge/final reviewer: `gpt-5.6-terra`, Medium reasoning via Codex;
  `z-ai/glm-5.3-flash` is bounded OpenRouter technical-failure fallback.
  A valid negative review never triggers failover. Sol/Terra share a model family;
  separate review calls are not independent-provider scientific verification.
- Generated topic-pack V1 shipped but full generated-pack synthesis remains gated.
- Cross-topic meta-synthesis V1 shipped; auto-selection must use only fully
  certified 14/14 runs.

## Session Start
- Read this file and `PROJECT_STATE.md` before code changes.
- Read `docs/active_50_task_plan_2026-05-09.md` after compaction or handover.
- Read `docs/DESIGN-001.md` before trust-spine or paper-generation changes.
- Read `FAILURES/research-agent-v1.md` before re-architecting LLM-touching code.
- Use knowledge MCP `get_playbook()` + `get_aaa_protocol()` at session start when
  available.

## Hard Rule
```text
LLM PROPOSES. CODE DISPOSES.
- Role assignment: registry override > deterministic abstract classifier. Never LLM.
- Fact identity: extracted by LLM, schema-validated, source-text-traced.
- Paper claims: gated by claim_graph / manifests / verdict JSON.
- Markdown is rendering, not source of truth.
```

## Non-Negotiables
- Python >= 3.11.
- Runtime dependency discipline: prefer stdlib and existing deps; justify any new
  dependency in `DECISIONS.md`.
- LOC thresholds are advisory: `agent/` 25,269 total / 800 per file; `scripts/`
  40,231 total / 5,700 per file; combined 65,500. `make quality` reports
  overages. Do not compress or delete correct code solely to satisfy a count.
  Behavior, evidence, import boundaries, complexity and duplication still gate release.
- Soft budgets: file ~300 cloc, function ~50 cloc.
- All cross-stage objects should be explicit dataclasses or schema-shaped dicts.
- No imports from `agent_legacy/` or `agent_archived/`.
- LLMs may write, review, or arbitrate; they do not assign categorical truth,
  certify maturity, silently elevate L5/L6, or introduce unsupported numerics.
- Any new paper-quality tooling should generalize beyond rapamycin unless it is
  explicitly topic-pack data.

## Active Critical Path
1. Keep repo clean, synced, and reproducible.
2. Keep release-green blockers closed: cross-topic run selection,
   state docs, full tests, and deploy sync.
3. Make the rapamycin paper genuinely candidate-publication-ready.
4. Preserve trust-spine gates while improving corpus depth, RoB/GRADE,
   meta-analysis, field engagement, cross-paper tension prose, and voice.

## Verification Commands
```bash
git status --short
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check agent scripts tests
.venv/bin/python scripts/run_cross_topic_meta_synthesis.py
ssh -i ~/.ssh/binance_futures_tool root@49.12.7.18 \
'cd /opt/research-agent-bot && git rev-parse --short HEAD && git status --short && systemctl is-active research-agent-bot.service && curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8791/'
```

Focused investigations may install `.[diagnostics]`: use Hypothesis for state
transitions, pytest-randomly for order dependence, coverage for the failing
branch, VizTracer for controlled replay, and py-spy for a live stuck process.

## Deploy Notes
- VPS public IP: `49.12.7.18`; Tailscale IP: `100.96.74.1`.
- SSH key: `~/.ssh/binance_futures_tool`.
- Live path: `/opt/research-agent-bot`.
- Mirror path: `/root/Research-Agent-Bot`.
- Never deploy from a dirty state.
- Verify service status and HTTP 200 live status endpoint after deploy.


## Never run destructive git on VPS /opt

`/opt/research-agent-bot` is the live publishing checkout. NEVER run
`git stash`, `git checkout <ref>`, `git clean`, or `git reset` there to test
or compare code. Incidents: a `git stash` for an A/B test left /opt in a
merge-conflicted state mid-drought, and the cleanup dropped a teammate's
pre-existing stash (recovered only via `git fsck --unreachable`).

To A/B a change against production state, copy the tree first:
    cp -a /opt/research-agent-bot /tmp/ab && cd /tmp/ab && <experiment>
Deploy to /opt only via `git fetch && git reset --hard origin/<branch>` after
the change is committed and pushed. Read-only commands (`git log`, `status`,
`show`, `pytest`) are fine in place.

## Never bundle a status check with a destructive command

Put the check and the destructive action in SEPARATE calls, and read the check
before acting on it.

On 2026-08-07 a single command did:

    ps ... | grep run_v06_synthesis   # "is anything mid-flight?"
    pkill -f "mode fresh --run-synthesis"

Both ran before the output could be read. A liraglutide synthesis WAS
mid-flight and was killed. The guard was written, executed, and useless,
because a guard you cannot read is not a guard.

Applies to pkill/kill, rm -rf, git reset --hard, systemctl stop, DROP/DELETE.
Same rule as "never deploy from a dirty state": verify in one call, act in the
next.
