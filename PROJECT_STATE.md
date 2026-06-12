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
- LOC budget documented in `DECISIONS.md` and enforced at 29,150 cloc.
- `AGENTS.md`, `PROJECT_STATE.md`, and active task plan match current mission.
- Full suite and ruff pass.
- Commit pushed and VPS paths synced clean.
