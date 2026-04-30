# AGENTS.md

## Purpose
Research Agent Bot — Proof 001 build window. The bot compiles deterministic evidence (`claim_graph.json`); SPAR adjudicates; markdown is rendering, not source of truth. Optimize for correctness, reversibility, and low LOC.

**Runtime state — distinguish GitHub `main` from VPS live:**

| State | What's there | Verify |
|---|---|---|
| **GitHub `main`** | Deploy-safe stub (`agent.app dashboard` returns HTTP 503 "service paused"). | `python -m agent.app dashboard --port 8791` → `curl :8791/` returns 503 |
| **VPS live** (`research-agent.domlynch.com`) | **Still V1.1** — deploy step pending since the Day 0 push. | `curl -s -o /dev/null -w "%{http_code}\n" https://research-agent.domlynch.com/` returns `200` |

The stub is on `main` ready to pull whenever VPS parity is wanted. Until then, do not assume the live endpoint reflects the Proof 001 architecture. See PROJECT_STATE.md "Runtime status" for current commit hash and deploy command.

Read [`docs/DESIGN-001.md`](docs/DESIGN-001.md) (DRAFT v2) for the full architecture before any code change. Read [`FAILURES/research-agent-v1.md`](FAILURES/research-agent-v1.md) before re-architecting any LLM-touching component.

## Hard rule (posted at top of every prompt that touches the trust spine)
```
LLM PROPOSES. CODE DISPOSES.
- Role assignment: registry override > deterministic abstract classifier. Never LLM.
- Fact identity: extracted by LLM, schema-validated, source-text-traced.
- Claim membership in paper.md: gated by claim_graph.json. LLM cannot add claims.
```

## Non-Negotiables
- Python ≥ 3.11 only.
- Runtime dep: `httpx` only. Topic packs use stdlib `tomllib` (TOML, not YAML — no PyYAML).
- Hard ceiling: **12,000 LOC runtime** in `agent/` (raised 2026-04-30 per DECISIONS.md Day 10.17; previous 3,500 → 4,800 → 5,500 → 7,500 → 8,000 → 8,500 → 10,000 → 12,000 to fund the synthesis layer + multi-receipt mode + Day 10.10 trust-spine ordering + Day 10.16 full-paper writer + Day 10.17 audit-quality expansion). Per-file hard cap 600 LOC.
- Soft per-file budget 300 LOC; per-function 50 LOC (v4 Rule 54).
- All cross-stage objects are frozen dataclasses (`@dataclass(frozen=True, slots=True)`).
- Source of truth is `claim_graph.json`. Markdown is downstream rendering only.
- Three judge agents in SPAR (Evidence Auditor, Domain Skeptic, Final Judge); Methodologist / Statistician / Domain Advocate / Translation Judge / Editor are deferred to Proof 002+.
- Dissent in any 2-1 SPAR verdict is **always published** verbatim in `spar_review.json`.
- `citation_trace.py` is backend-agnostic via `trace_clients.py` Protocol layer (TrialRegistryClient / DrugAliasClient / LiteratureClient). Backend selected by env var `TRACE_BACKEND ∈ {mcp, http, fixture}`.
- No imports from `agent_legacy/` or `agent_archived/`. CI guard: `tests/test_no_legacy_imports.py` (Day 1: extend to also block `agent_archived`).
- Multiple LLMs are allowed — but only outside the categorical-decision spine. They generate prose, score thesis candidates, and serve as SPAR voices. They never assign roles, decide citation identity, or rule on tier elevation.

## Pipeline (Proof 001)
```
Stage 0  topic_pack ingest          DETERMINISTIC (tomllib)
Stage 1  source retrieve+normalize  DETERMINISTIC (existing retrieve.py + sources/)
Stage 2  evidence_cards             DETERMINISTIC + REGISTRY OVERRIDE
Stage 3  fact extraction            LLM proposes, schema disposes
Stage 4  claim graph compile        DETERMINISTIC edges + LLM attack surfaces
Stage 5  thesis tournament          LLM generates, deterministic selector
Stage 6  citation_trace             DETERMINISTIC (trace_clients backends)
Stage 7  SPAR adjudication          3 LLM agents, deterministic tie-break
Stage 8  drafting                   LLM writes prose from claim_graph only
Stage 9  render + bundle            DETERMINISTIC
```

## Safety Rails (preserved from V1)
Three env-gate controls checked before expensive work begins:

| Env var | Default | Effect |
|---|---|---|
| `BOT_ENABLED` | `true` | Kill switch — `false`/`0`/`no`/`off` blocks all runs immediately |
| `BOT_SUBMIT_ENABLED` | `true` | Submit switch — currently routes to Researka stub adapter only |
| `DAILY_COST_CAP_USD` | `10.0` | Cost cap — blocks run if today's `runs/*.json` costs already >= cap |

Plus added in Proof 001:

| Env var | Default | Effect |
|---|---|---|
| `TRACE_BACKEND` | `fixture` | Selects `trace_clients` backend: `fixture` (CI default), `http` (VPS), `mcp` (dev/Codex) |

All `BOT_*` flags accept `true`, `1`, `yes`, `on` (case-insensitive) as truthy.

## Quality bar
The 7-paper Quality Reference Corpus at [`docs/quality-reference/metformin/README.md`](docs/quality-reference/metformin/README.md) defines the prose standard. Embedded gold passages from MASTERS, Konopka 2019, MILES, MET-PREVENT, Mohammed 2021 feed `agent/prompts/writer_quality_bar.md` and `agent/prompts/judge_quality_checklist.md` at runtime. The bot retrieves its own evidence; quality is judged against these 7.

## Stop conditions
- Proof 001 fails any eval gate → iterate Proof 001. **Do not start rapamycin.**
- All 3 proofs (metformin / rapamycin / everolimus) green → publish RFCs. Until then, no outreach.
- Cost per run >$0.05 sustained → re-route to Gemma self-host before continuing.

## Archive policy (v4 Rule 58)
- `agent_legacy/` — pre-V1.1 codebase, retained for adapter archaeology.
- `agent_archived/proof001/` — V1.1 LLM-coupled spine, retained for prompt/pattern archaeology. README at root explains contents and replacement modules.
- New code in `agent/` MUST NOT import from either archive directory.
