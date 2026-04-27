# PROJECT_STATE.md

## Current Objective
**Proof 001 — Metformin Claim Court.** Build a deterministic claim-court pipeline that produces one publishable metformin artifact end-to-end (`paper.md` + 7 mandatory JSON receipts). The agent compiles structured evidence; SPAR adjudicates; markdown is rendering, not source of truth. Three greens (metformin → rapamycin → everolimus) before any RFC outreach.

Full design: [`docs/DESIGN-001.md`](docs/DESIGN-001.md) (DRAFT v2, sign-off pending).

## Pipeline (Proof 001, 9 stages)
```
topic_pack ingest (toml)  →  retrieve  →  evidence_cards (registry override → deterministic) →
fact extraction (LLM proposes, schema disposes)  →  claim_graph compile  →
thesis tournament (6-dim, deterministic selector)  →  citation_trace (TrialRegistryClient /
DrugAliasClient / LiteratureClient — MCP/httpx/fixture backends)  →  SPAR (3 agents,
explicit tie-break, dissent always published)  →  drafting (claim-graph-guarded prose)  →
render + bundle
```

## Hard rule
```
LLM PROPOSES. CODE DISPOSES.
- Role assignment: registry override > deterministic abstract classifier. Never LLM.
- Fact identity: extracted by LLM, schema-validated, source-text-traced.
- Claim membership in paper.md: gated by claim_graph.json. LLM cannot add claims.
```

## Constraints
- Hard ceiling: **4,800 LOC runtime** for `agent/` (raised from 3,500 to fund the claim-court features per DECISIONS.md 2026-04-27). Test LOC budgeted separately.
- Soft per-file budget: **300 LOC** (v4 Rule 54).
- Soft per-function budget: **50 LOC** (v4 Rule 54).
- Runtime dep: `httpx` only. **Topic packs use stdlib `tomllib` (TOML, not YAML)** — no PyYAML.
- Python ≥ 3.11, stdlib `dataclasses` (frozen+slots).

## Status — 2026-04-27 — Day 1 + reviewer fixes complete; Day 2 unblocked

**HEAD:** `941f21c` on `origin/main`
**Tag:** `v1.1-final` → `89ee064` (preserves V1.1 LLM-coupled state for archaeology)
**Tests:** 186/186 passing in 0.28s. ruff clean. git diff --check clean.
**Runtime LOC:** 2,519 / 4,800 ceiling (47% headroom)

**Commit log of the rebuild:**

| Commit | Date | What |
|---|---|---|
| `89ee064` | 2026-04-26 | V1.1 final (tagged `v1.1-final`) |
| `d941ae2` | 2026-04-27 | Day 0: archive LLM-coupled spine, deploy-safe stub |
| `a9eb7ab` | 2026-04-27 | Day 1: schemas, topic_pack TOML, planted-failure corpus |
| `941f21c` | 2026-04-27 | Day 1 fixes: 4 P1 + 1 P2 reviewer blockers |
| (P1.A/B fixes) | 2026-04-27 | This commit — stale state claims, SPAR dissent membership/minority |

**Archived to `agent_archived/proof001/`** (per [FAILURES/research-agent-v1.md](FAILURES/research-agent-v1.md)):
- 6 modules: `relevance.py`, `llm.py`, `judge.py`, `draft.py`, `qa.py`, `app.py`
- 3 test files: `test_judge.py`, `test_draft.py`, `test_qa.py`
- Reason: LLMs were inside the trust spine; structural bug class V1.1 could not close.

**Active `agent/`:**
- `types.py` (KEEP — frozen-dataclass invariants, role↔fact-kind pairing)
- `retrieve.py` + `sources/` (KEEP — async parallel retrieval, 4 adapters)
- `schemas.py` (NEW Day 1 — 6 frozen-dataclasses, ClaimGraph + SPAR invariants, tie-break)
- `topic_pack.py` (NEW Day 1 — stdlib `tomllib` loader, MappingProxyType-protected overrides)
- `bundle.py` (GUT on Day 2 — split into evidence_cards / role_classifier / registry_overrides / text_signals)
- `render.py` (GUT on Day 5 — pure claim_graph → markdown, no LLM hooks)
- `settings.py` (KEEP, may extend for `TRACE_BACKEND` env var)
- `app.py` (deploy-safe stub — HTTP 503 paused page)

**Runtime status — distinguish two states (P1.4 fix from reviewer audit):**

| State | What's there | How to verify |
|---|---|---|
| **GitHub `main`** (`941f21c`) | Deploy-safe stub. `agent.app dashboard` serves HTTP 503 "service paused". | `python -m agent.app dashboard --port 8791` then `curl :8791/` → 503 |
| **VPS live (`research-agent.domlynch.com`)** | **Still V1.1** — deploy step pending since Day 0 push (2026-04-27). | `curl -s -o /dev/null -w "%{http_code}\n" https://research-agent.domlynch.com/` → `200` until the VPS pulls. |

To deploy the stub: SSH into VPS, `cd /opt/research-agent-bot && git pull && systemctl restart research-agent-bot`. Reverts to V1.1 via `git checkout v1.1-final && systemctl restart research-agent-bot`. Either path is reversible.

## Day plan (5 days, target — not deadline)
| Day | Ship | Done when | Status |
|---|---|---|---|
| **0** | Tag `v1.1-final`. Archive 6 LLM-coupled modules + 3 test files. Deploy-safe `app.py` stub. Post-mortem. DECISIONS.md entry. | Tag exists; deterministic tests green; `agent.app dashboard` runs as paused-stub. | ✅ `d941ae2` |
| **1** | `schemas.py` + `topic_pack.py` + `topic_packs/metformin.toml` + planted-failure fixtures + tests. Bundle.py 4-file split DEFERRED to Day 2 (paired with evidence_cards rename). | All 6 schemas frozen, `tomllib` parses topic pack, planted-failure cases 1+4 caught at topic_pack layer. | ✅ `a9eb7ab` + `941f21c` (fixes) + this commit |
| **2** | `evidence_cards.py` (refactor of bundle.py) + `role_classifier.py`, `registry_overrides.py`, `text_signals.py` (split) + `validators.py` + `compiler.py` (deterministic) + `trace_clients.py` fixture backend. Real metformin retrieval E2E. | ≥12 sources retrieved; cards classify correctly; planted case 1 caught at evidence_cards (in addition to topic_pack layer). | 🟢 Ready |
| 3 | `citation_trace.py` against `trace_clients.py` (fixture + httpx backends). MCP backend wired but optional. **First LLM stage:** fact extraction (LLM proposes, schema disposes). | Citation_trace catches planted cases 2, 3; httpx backend smoke-tests against clinicaltrials.gov. | — |
| 4 | `thesis_tournament.py` + `spar.py` + writer prompt with quality-bar block + judge checklist. Plant-corpus prompt iteration. `gap_analysis.py` only if time permits (non-gating). | All 5 planted failures caught; thesis tournament selects defensible thesis on real corpus. | — |
| 5 | `submit_adapter.py` + gutted `render.py` + new `app.py` + `mcp_server.py` + first end-to-end metformin run. | `runs/metformin-001/` contains 8 mandatory outputs; SPAR verdict accept_clean or accept_caveated; quality bar met against MASTERS / MET-PREVENT / Konopka 2019 standard. | — |

## Eval gates (Proof 001 ship criteria)
- Role accuracy 10/10 (no protocol cited as result; every NCT in topic pack hits override)
- Citation accuracy 10/10 (every NCT/DOI resolves; every numeric traces to source)
- Numeric fidelity 9/10
- Directness discipline 10/10
- Planted failures 5/5 caught at the gate they should be caught at
- Final artifact quality 8.5+/10 against the 7-paper Quality Reference Corpus
- Receipt completeness 8/8 mandatory (paper.md + 7 JSON; gap_analysis.json bonus 9th)

## Stop conditions
- Proof 001 fails any gate → iterate Proof 001. **Do not start rapamycin.**
- 001 + 002 green, 003 (everolimus) red → likely topic-pack issue (RAD001 alias, oncology indirectness). Fix and re-run.
- All 3 green → publish RFCs. Until then, no outreach.
- Cost per run >$0.05 sustained → re-route Mistral judge calls; if still >$0.05, switch to Gemma self-host before continuing.

## Archived V1.1 status (preserved for archaeology)
- V1.1 shipped 2026-04-26 at commit `89ee064` (now tagged `v1.1-final`).
- Three-LLM pipeline: relevance (MiMo→Gemma→Mistral) + writer (MiMo→Mistral) + judge (Gemma→MiMo→Mistral).
- 166 tests green, deployed at `research-agent.domlynch.com`, $0.002–0.005 per draft.
- **Why archived:** LLMs were inside the trust spine; categorical decisions (role assignment, citation identity, final adjudication) cannot be reliably routed through model judgment. Three failure modes never closed: protocol-as-results, mechanism-inflated-to-clinic, off-domain extrapolation. Full post-mortem in [`FAILURES/research-agent-v1.md`](FAILURES/research-agent-v1.md).

## Legacy
The pre-V1.1 codebase remains at `agent_legacy/` for git archaeology. The Day 0 V1.1 archive is at `agent_archived/proof001/`. New code MUST NOT import from either. CI guard: `tests/test_no_legacy_imports.py` blocks both packages with three targeted tests (combined, legacy-only, archived-only).

## Next validation step
Day 2: ship `evidence_cards.py` (refactor of `bundle.py` adding the registry-override layer) + the 4-file split (`role_classifier.py`, `registry_overrides.py`, `text_signals.py`) + `validators.py` (verb-ban / role-match pure functions consuming topic_pack outputs) + `compiler.py` deterministic part + `trace_clients.py` fixture backend. Run real metformin retrieval end-to-end via existing `retrieve.py`; verify ≥12 sources surface and cards classify correctly. **Done-when:** planted case 1 caught at `evidence_cards` (second layer of defense in addition to the topic_pack layer that already catches it).
