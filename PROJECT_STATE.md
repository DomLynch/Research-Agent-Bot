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

## Status — 2026-04-27 — Day 2.1 + 2.2 complete (bundle.py split + registry-override moat); Day 2.3-2.5 pending

**HEAD:** `0ffcd5a` on `origin/main`
**Tag:** `v1.1-final` → `89ee064` (preserves V1.1 LLM-coupled state for archaeology)
**Tests:** 206/206 passing in 0.29s. ruff clean. git diff --check clean.
**Runtime LOC:** 2,768 / 4,800 ceiling (42% headroom)

**Commit log of the rebuild:**

| Commit | Date | What |
|---|---|---|
| `89ee064` | 2026-04-26 | V1.1 final (tagged `v1.1-final`) |
| `d941ae2` | 2026-04-27 | Day 0: archive LLM-coupled spine, deploy-safe stub |
| `a9eb7ab` | 2026-04-27 | Day 1: schemas, topic_pack TOML, planted-failure corpus |
| `941f21c` | 2026-04-27 | Day 1 fixes: 4 P1 + 1 P2 reviewer blockers |
| `9cff619` | 2026-04-27 | Day 1 fixes 2: PROJECT_STATE drift + SPAR dissent membership/minority |
| `0ffcd5a` | 2026-04-27 | Day 2.1+2.2: bundle.py 4-file split + registry-override moat (planted case 1 double-locked) |

**Archived to `agent_archived/proof001/`** (per [FAILURES/research-agent-v1.md](FAILURES/research-agent-v1.md)):
- 6 modules: `relevance.py`, `llm.py`, `judge.py`, `draft.py`, `qa.py`, `app.py`
- 3 test files: `test_judge.py`, `test_draft.py`, `test_qa.py`
- Reason: LLMs were inside the trust spine; structural bug class V1.1 could not close.

**Active `agent/` (post-Day 2.1+2.2):**
- `types.py` (KEEP — frozen-dataclass invariants, role↔fact-kind pairing)
- `retrieve.py` + `sources/` (KEEP — async parallel retrieval, 4 adapters)
- `schemas.py` (Day 1 — 6 frozen-dataclasses, ClaimGraph + SPAR invariants, tie-break, dissent membership/minority guard)
- `topic_pack.py` (Day 1 — stdlib `tomllib` loader, MappingProxyType-protected overrides)
- `text_signals.py` (Day 2.1 NEW — regex/marker constants extracted from bundle.py)
- `role_classifier.py` (Day 2.1 NEW — `classify_role` + `classify_design`)
- `evidence_cards.py` (Day 2.1 — renamed from bundle.py; high-level `bundle()` builder + tier/direct/strict + risk_of_bias + confidence_verdict + rank_for_writer)
- `registry_overrides.py` (Day 2.2 NEW — registry-pinned override layer; the moat)
- `render.py` (GUT on Day 5 — pure claim_graph → markdown, no LLM hooks)
- `settings.py` (KEEP, may extend for `TRACE_BACKEND` env var)
- `app.py` (deploy-safe stub — HTTP 503 paused page)

`bundle.py` was renamed via `git mv` to `evidence_cards.py` and refactored to import from the 3 new sibling modules. No behavior change in the rename; the registry-override layer is the only behavioral addition.

**Runtime status — distinguish two states:**

| State | What's there | How to verify |
|---|---|---|
| **GitHub `main`** (`0ffcd5a`) | Deploy-safe stub. `agent.app dashboard` serves HTTP 503 "service paused". | `python -m agent.app dashboard --port 8791` then `curl :8791/` → 503 |
| **VPS live (`research-agent.domlynch.com`)** | **Still V1.1** — deploy step pending since Day 0 push (2026-04-27). | `curl -s -o /dev/null -w "%{http_code}\n" https://research-agent.domlynch.com/` → `200` until the VPS pulls. |

To deploy the stub: SSH into VPS, `cd /opt/research-agent-bot && git pull && systemctl restart research-agent-bot`. Reverts to V1.1 via `git checkout v1.1-final && systemctl restart research-agent-bot`. Either path is reversible.

**Planted-failure case status:**

| Case | What | Layer 1 | Layer 2 | Layer 3 (Day 2.3) |
|---|---|---|---|---|
| 1 | TAME protocol cited as results | ✅ `topic_pack` registry whitelist | ✅ `evidence_cards` registry override during `bundle()` | ☐ `validators.py` verb-ban on prose claims |
| 2 | Fabricated NCT | — | — | (Day 3 `citation_trace` via `TrialRegistryClient`) |
| 3 | Inflated p-value | — | — | (Day 3 `citation_trace` p-value text-grep) |
| 4 | Alias drift ("Glufomin") | ✅ `topic_pack` alias whitelist | (Day 3 `DrugAliasClient`) | — |
| 5 | Off-domain extrapolation | (Day 2.3) `validators` directness check | (Day 2.5 E2E surfaces it) | — |

## Day plan (5 days, target — not deadline)
| Day | Ship | Done when | Status |
|---|---|---|---|
| **0** | Tag `v1.1-final`. Archive 6 LLM-coupled modules + 3 test files. Deploy-safe `app.py` stub. Post-mortem. DECISIONS.md entry. | Tag exists; deterministic tests green; `agent.app dashboard` runs as paused-stub. | ✅ `d941ae2` |
| **1** | `schemas.py` + `topic_pack.py` + `topic_packs/metformin.toml` + planted-failure fixtures + tests. Bundle.py 4-file split DEFERRED to Day 2 (paired with evidence_cards rename). | All 6 schemas frozen, `tomllib` parses topic pack, planted-failure cases 1+4 caught at topic_pack layer. | ✅ `a9eb7ab` + `941f21c` + `9cff619` |
| **2** | `evidence_cards.py` (refactor of bundle.py) + 4-file split + registry_overrides + `validators.py` + `compiler.py` (deterministic) + `trace_clients.py` fixture backend. Real metformin retrieval E2E. | ≥12 sources retrieved; cards classify correctly; planted case 1 caught at evidence_cards (in addition to topic_pack layer). | **PARTIAL** — 2.1+2.2 ✅ `0ffcd5a` (bundle split + registry override; planted case 1 double-locked); 2.3+2.4+2.5 ☐ pending |
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

Day 2.1+2.2 SHIPPED at `0ffcd5a`: bundle.py 4-file split (text_signals, role_classifier, evidence_cards) + registry-override moat (registry_overrides). Planted case 1 double-locked at topic_pack and evidence_cards layers. 206/206 tests green.

Day 2.3-2.5 PENDING:
- **Day 2.3 — `agent/validators.py`** (~180 LOC): pure-function gates that consume topic_pack outputs. Three checks for v0:
  - `check_verb_ban(claim_text, evidence_item, pack)` — case 1's third defense layer (catches "TAME demonstrated…" in prose if the registry override didn't already)
  - `check_role_claim_match(claim, evidence_item)` — direct/indirect/mechanistic must align with the evidence role
  - `check_alias_drift(claim_text, pack)` — case 4's belt-and-suspenders against unrecognized drug aliases in prose
- **Day 2.4 — `agent/trace_clients.py`** (~150 LOC) fixture backend: 3 Protocol interfaces (TrialRegistryClient / DrugAliasClient / LiteratureClient) + fixture-backed implementations for CI/dev. httpx + MCP backends are Day 3.
- **Day 2.5 — End-to-end smoke**: real metformin retrieval via existing `retrieve.py` → `bundle()` with topic_pack → assert ≥12 sources surfaced, classifications correct. This closes the Day 2 done-when criterion that's still ☐.

**Day 2 ship criterion (DESIGN-001 §19):** ≥12 sources retrieved; cards classify correctly; planted case 1 caught at evidence_cards.
- Cards classify correctly: ✅ (snapshot tests + new layered test)
- Planted case 1 caught at evidence_cards: ✅ (`test_planted_case_1_second_layer_catch`)
- ≥12 sources retrieved: ☐ (Day 2.5 E2E smoke)
