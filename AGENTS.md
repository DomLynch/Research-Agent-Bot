# AGENTS.md

## Purpose
Research Agent Bot produces audited, source-grounded biomedical research papers.
The current mission is Ivy-League / senior-PhD-grade paper quality: deep corpus,
formal methods, quantitative synthesis where justified, calibrated prose, and a
full trust-spine audit trail.

Researka/public reader/provenance is downstream. This repo's job is the research
agent and paper engine.

## Current State - 2026-05-09
- Last pre-switch clean baseline: `415621b2`.
- Current branch target: Gemini Exacto reviewer switch; verify the exact deployed
  commit with `git rev-parse --short HEAD` after deploy.
- Service: `research-agent-bot.service`.
- Live endpoint: deploy-safe live status page, HTTP 200 by design.
- Basket: 18 full AAA/L5+ primary topics plus 1 scoped topic in cross-topic V1.
- Flagship: rapamycin AAA/L6 reproducibly journal-ready baseline; current
  paper-quality sprint has lifted runner-admitted receipts from 16 to 40 via
  source-validated vocabulary and qualification fixes.
- Current reviewer target: `google/gemini-3.1-flash-lite:exacto` with high
  thinking; Mistral Small is bounded fallback only, not a third arbitrator.
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
- Current runtime LOC ceiling: 29,685 cloc in `agent/`; test-enforced per-file
  hard cap: 920.
- Current `scripts/` LOC ceiling: 41,310 cloc; test-enforced per-file hard cap:
  5,700.
- Soft budgets: file ~300 cloc, function ~50 cloc.
- All cross-stage objects should be explicit dataclasses or schema-shaped dicts.
- No imports from `agent_legacy/` or `agent_archived/`.
- LLMs may write, review, or arbitrate; they do not assign categorical truth,
  certify maturity, silently elevate L5/L6, or introduce unsupported numerics.
- Any new paper-quality tooling should generalize beyond rapamycin unless it is
  explicitly topic-pack data.

## Active Critical Path
1. Keep repo clean, synced, and reproducible.
2. Keep release-green blockers closed: cross-topic run selection, LOC budget,
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

## Deploy Notes
- VPS public IP: `49.12.7.18`; Tailscale IP: `100.96.74.1`.
- SSH key: `~/.ssh/binance_futures_tool`.
- Live path: `/opt/research-agent-bot`.
- Mirror path: `/root/Research-Agent-Bot`.
- Never deploy from a dirty state.
- Verify service status and HTTP 200 live status endpoint after deploy.
