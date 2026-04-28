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
- Hard ceiling: **5,500 LOC runtime** for `agent/` (raised 2026-04-28 to fund Day 4 writer + GateOverride trust-spine; previous 3,500 → 4,800 → 5,500 history in DECISIONS.md). Test LOC budgeted separately.
- Soft per-file budget: **300 LOC** (v4 Rule 54). Hard per-file cap: **600 LOC**.
- Soft per-function budget: **50 LOC** (v4 Rule 54).
- Runtime dep: `httpx` only. **Topic packs use stdlib `tomllib` (TOML, not YAML)** — no PyYAML.
- Python ≥ 3.11, stdlib `dataclasses` (frozen+slots).

## Status — 2026-04-28 — Day 5.2 shipped (full-pipeline E2E + specificity proof + sensitivity reaffirmed; reviewer-cleared); Day 5.3 next

**State verified through:** the most recent entry in the commit log table below.
*Structural break (Day 3.1-fixes-2): the previous "State verified through: \<hash\>"
field was reintroducing drift on every slice because each slice's commit hash
isn't known until after the commit lands. The commit log table IS the canonical
source of truth — pointing at "the most recent entry" is self-correcting:
`git log -1 --oneline` matches the table's bottom row, no manual sync required.*
*(field describes state up to and including the most recent commit listed
in the log table below. The current HEAD will appear in the next slice's
update. See commit message of e1bb56f for the amend-bootstrap rationale.)*

**Tag:** `v1.1-final` → `89ee064` (preserves V1.1 LLM-coupled state for archaeology)
**Tests:** 578/578 passing in 0.49s. ruff clean. git diff --check clean.
**Runtime LOC (cloc-style, the canonical count enforced by `tests/test_loc_budget.py`):** 5,257 / **5,500** ceiling (4.4% headroom; Day 5.4 render gut reclaims ~270 cloc).

**Per-file (cloc-style, soft cap 300, hard cap 600):**
- `spar.py` 397, `citation_trace.py` 355, `fact_extractor.py` 327 — all over soft cap; all under 600 hard cap. Each carries load-bearing prompts and/or trust-spine gates. Splitting would couple tightly-related logic.
- `writer.py` 259 — **back under the soft cap** after Day 4-fix P1 removed the LLM call layer (was 437).
- `schemas.py` 280, `render.py` 278, `evidence_cards.py` 261, `llm_client.py` 239
- `trace_clients/_httpx.py` 225, `topic_pack.py` 218, `validators.py` 207
- `thesis_tournament.py` 139, `trace_clients/_fixture.py` 126, `trace_clients/__init__.py` 79, `trace_clients/protocols.py` 75

**Commit log of the rebuild:**

| Commit | Date | What |
|---|---|---|
| `89ee064` | 2026-04-26 | V1.1 final (tagged `v1.1-final`) |
| `d941ae2` | 2026-04-27 | Day 0: archive LLM-coupled spine, deploy-safe stub |
| `a9eb7ab` | 2026-04-27 | Day 1: schemas, topic_pack TOML, planted-failure corpus |
| `941f21c` | 2026-04-27 | Day 1 fixes: 4 P1 + 1 P2 reviewer blockers |
| `9cff619` | 2026-04-27 | Day 1 fixes 2: PROJECT_STATE drift + SPAR dissent membership/minority |
| `0ffcd5a` | 2026-04-27 | Day 2.1+2.2: bundle.py 4-file split + registry-override moat (case 1 double-locked) |
| `25dd964` | 2026-04-27 | Day 2 state-fixes: PROJECT_STATE + AGENTS handover drift after 0ffcd5a |
| `9918c12` | 2026-04-27 | Day 2.3: validators.py — case 1 triple-locked + cases 3/4 local layers |
| `7dbaeac` | 2026-04-27 | Day 2.3 state-fixes: PROJECT_STATE drift after 9918c12 + LOC docstring |
| `e1bb56f` | 2026-04-27 | Day 2.4: trace_clients.py — 3 Protocols + fixture backends; planted cases 2 & 4 fixture-layer coverage |
| `d0c571f` | 2026-04-27 | Day 2.4 state-followup: PROJECT_STATE HEAD → e1bb56f (post-amend hash) |
| `5b06bda` | 2026-04-27 | Day 2.4 fixes: corpus-guard P1 (missing corpus ≠ missing record) + PROJECT_STATE label P3 |
| `c0cc11e` | 2026-04-27 | Day 2.5: E2E metformin smoke (fixture replay; 8 tests) |
| `7fe3c02` | 2026-04-27 | Day 2.5b: live-API smoke + honest fixture-vs-live distinction (script + baseline) |
| `555c73a` | 2026-04-27 | Day 3.0: registry override scans abstract for NCT/ISRCTN — closes live-smoke finding (MASTERS now pinned via abstract) |
| `979055b` | 2026-04-27 | Day 3.0 fixes: case-insensitive registry IDs (P2) + PROJECT_STATE refresh (P3) |
| `361f5f7` | 2026-04-27 | Day 3.0 state cleanup: state-through 979055b + drop stale lower section |
| `788868a` | 2026-04-27 | Day 3.1: citation_trace.py — moat orchestrator; cases 2/3/4 external layer |
| `af2e329` | 2026-04-27 | Day 3.1 fixes: 3 P1 trust-spine bugs in citation_trace + PROJECT_STATE drift (P2) |
| `0a2c263` | 2026-04-27 | Day 3.1 fixes-2: structural break on state-through drift + 2 P3 doc cleanups |
| `1537196` | 2026-04-27 | Day 3.2a: deterministic compiler — facts → Claims → ClaimGraph (1:1, thesis-pick by score tuple) |
| `325afb9` | 2026-04-27 | Day 3.2b: llm_client.py — single-dep LLM surface (chat_json + chain + CostLedger) |
| `207ffbf` | 2026-04-27 | Day 3.2c: fact_extractor.py — first LLM in spine; ref/kind PINNED + 4 code-disposes layers |
| `848dba6` | 2026-04-28 | Day 3.2c-fix: P1 p_value field bypass + P2 estimate/ci field bypass; 4 trace layers → 7 |
| `f66a4ca` | 2026-04-28 | Day 3.2c-fix-state: LOC counter correction (cloc-style 3,799/4,800; 21% headroom) |
| `743b35e` | 2026-04-28 | Day 3.2c-fix-2: malformed p_value grammar gate (rejects `'NS'`/`'1.2'`/`'not reported'` BEFORE source-trace) + commit table drift |
| `acfe508` | 2026-04-28 | 3.1-fixes-3: verb-boundary + yield-zero design-decision docs + regression tests (428 tests) |
| `211592c` | 2026-04-28 | Day 3.3a: split `trace_clients.py` → package (`__init__` / `protocols` / `_fixture`); refactor only |
| `c6328a9` | 2026-04-28 | Day 3.3b: httpx backends — `_httpx.py` (CT.gov v2 / ChEMBL / Europe PMC) + 20 MockTransport tests |
| `70e897a` | 2026-04-28 | Day 3.3c: live smoke 6/6 green vs CT.gov / ChEMBL / Europe PMC |
| `9e3caf8` | 2026-04-28 | Day 3.4: Day-3 E2E pipeline test (real corpus → ClaimGraph → traces) — Day 3 ✅ COMPLETE |
| `2ac7ad1` | 2026-04-28 | Day 3 cleanup: 3 reviewer P2 niggles (≥6 claims + e2e_day3_pipeline.py + state drift) |
| `49677b2` | 2026-04-28 | Day 4.1: thesis tournament — 6-dim deterministic selector + compiler wire-in (drops `_pick_thesis`) |
| `a1dfcf4` | 2026-04-28 | Day 4.2: SPAR — 3-judge panel orchestration with dissent always published |
| `bc5e080` | 2026-04-28 | Day 4.2-fix: trust-spine trace gate (GateOverride schema) + strict flagged_claims + state drift |
| `dd73dd7` | 2026-04-28 | Day 4-prep: raise LOC ceiling 4,800 → 5,500 (DECISIONS.md) + state drift |
| `57a8e30` | 2026-04-28 | Day 4.3: writer.py — claim-graph-gated prose with gate_override prominence |
| `132d552` | 2026-04-28 | Day 4.3-fix: strict claim-binding contract — sentences are `{claim_ids, text}` objects |
| `a110178` | 2026-04-28 | Day 4.4: planted-failures end-to-end — Day 4 done-when criteria met (later supersededby 4-fix P2 real-pipeline rewrite) |
| `2b21319` | 2026-04-28 | Day 4-fix: gut writer LLM (P1 deterministic) + real-pipeline planted-failure E2E (P2) + specificity proof |
| `1987105` | 2026-04-28 | Day 5.1: orchestrator — single-call pipeline + 8 mandatory receipts (3 P1 + 4 P2 reviewer-cleared) |
| `2a01f17` | 2026-04-28 | Day 5.1-fix: claim-text overlap gate (P1) + atomic paper.md (P2) + force_overwrite (Gap-1) + state drift (P3) |

**Archived to `agent_archived/proof001/`** (per [FAILURES/research-agent-v1.md](FAILURES/research-agent-v1.md)):
- 6 modules: `relevance.py`, `llm.py`, `judge.py`, `draft.py`, `qa.py`, `app.py`
- 3 test files: `test_judge.py`, `test_draft.py`, `test_qa.py`
- Reason: LLMs were inside the trust spine; structural bug class V1.1 could not close.

**Active `agent/` (post-Day 2.4):**
- `types.py` (KEEP — frozen-dataclass invariants, role↔fact-kind pairing)
- `retrieve.py` + `sources/` (KEEP — async parallel retrieval, 4 adapters)
- `schemas.py` (Day 1 — 6 frozen-dataclasses, ClaimGraph + SPAR invariants, tie-break, dissent membership/minority guard)
- `topic_pack.py` (Day 1 — stdlib `tomllib` loader, MappingProxyType-protected overrides)
- `text_signals.py` (Day 2.1 — regex/marker constants extracted from bundle.py)
- `role_classifier.py` (Day 2.1 — `classify_role` + `classify_design`)
- `evidence_cards.py` (Day 2.1 — renamed from bundle.py; `bundle()` builder + tier/direct/strict + risk_of_bias + confidence_verdict + rank_for_writer + topic_pack-aware override gate)
- `registry_overrides.py` (Day 2.2 — registry-pinned override layer; the moat)
- `validators.py` (Day 2.3 — pure-function gates: verb-ban, role-claim-match, alias-drift, p-value-in-source; Day 3.1 promoted `PVALUE_RE` to public for citation_trace reuse)
- `trace_clients/` package (Day 3.3a split + Day 3.3b httpx — `protocols.py` (75 cloc — Protocols + result dataclasses + TraceBackendError + TrialStatus), `_fixture.py` (126 cloc — fixture backends + corpus loader + missing-corpus guard), `_httpx.py` (225 cloc — `HttpxTrialRegistryClient` (CT.gov v2 `/studies/{nctId}`, ISRCTN skipped), `HttpxDrugAliasClient` (ChEMBL `/molecule/search`), `HttpxLiteratureClient` (Europe PMC `/search?query=DOI:...|EXT_ID:...`); 4xx/5xx → TraceBackendError; 404/empty → None; `_get_json` shared error mapper), `__init__.py` (79 cloc — public re-exports + env-var selectors with lazy `_httpx` import). `TRACE_BACKEND=http` now positively wired; `mcp` still raises (optional / deferred))
- `citation_trace.py` (Day 3.1 — moat orchestrator; 5 trace functions [nct_exists, role_match, p_value_in_text, percentage_in_text, alias_match] + trace_claim + trace_claim_graph + summary; closes external layers for planted cases 2/3/4. Day 3.1-fixes: nct_exists yields per-id traces from source.nct + URL ISRCTN + abstract-NCTs; flags has_results=False contradiction for published_results role; alias_match skips canonical trial acronyms)
- `compiler.py` (Day 3.2a + Day 4.1b — deterministic facts → Claims → ClaimGraph: 1:1 fact-to-claim mapping, kind→claim_type / role+direct→directness / (role,design,tier)→confidence; CompileError on orphan refs. Day 4.1b wired in `thesis_tournament.pick_thesis` and dropped the in-module 3-dim heuristic. `compile_claim_graph` now accepts optional `items_by_ref` to enable the 6th dim (recency))
- `thesis_tournament.py` (Day 4.1 — 6-dim deterministic thesis selector: directness > tier > confidence > replication (-len(supporting_refs)) > recency (baseline_year - latest_year) > specificity (-min(50, word_count)), tiebreak by claim_id. `pick_thesis(claims, items_by_ref=None)` returns the chosen claim_id; `score_all` exposes per-claim scores for SPAR audit consumption.)
- `orchestrator.py` (Day 5.1 + 5.1-fix — 285 cloc — single-call pipeline driver. `run_proof(items, *, topic, domain, pack, output_dir, submission_id, extract_chain, spar_chain, registry, drug_client, client, force_overwrite=False) -> RunReceipts`. 5.1-fix P2 made paper.md atomic via `_atomic_write_text` (was `write_text` — partial-paper crash could strand output dir). 5.1-fix Gap-1 added `force_overwrite` opt-in for controlled re-runs (default False refuses to clobber prior receipts). Wires extract → compile → trace → SPAR → write; emits 8 mandatory JSON receipts (paper.md / claim_graph / citation_traces / spar_review / evidence_cards / cost_log / fact_extraction_log / run_metadata). Audit-trail guards: refuses to clobber existing receipts (P1-3); calls `assert_invariants` post-extraction so a published_results item with no fact fails loud (P1-1); wraps CompileError + ClaimGraphInvariantError as OrchestratorError per the contract (P1-2); writes diagnostic `fact_extraction_log` + `cost_log` even on extraction failure (P2-3); zero-facts error surfaces a rejection-category histogram (P2-2); writer rejections on the deterministic path raise (P2-4 — should be impossible per writer contract, but the guard catches regressions); atomic writes via tmp+rename (P2-1). Caller does retrieve+bundle; orchestrator does trust-spine.)
- `writer.py` (Day 4.3 → 4.3-fix → **4-fix P1** — 259 cloc, **down from 437** because the LLM was removed entirely. The reviewer caught that even strict per-sentence `claim_ids` binding could be circumvented: an LLM declaring a valid claim_id and citing a valid `[N]` could STILL write a novel claim text outside the graph (self-declared binding without text-to-claim verification is insufficient). Fix: writer is now PURELY DETERMINISTIC. Every sentence in the output is a `Claim.text` from the graph, attached to its `supporting_refs`. No LLM call at write time → no novel claims possible. `write_paper(graph, items, traces, spar, *, pack, topic) -> tuple[str, list[WriterRejection]]` is now SYNC. Routes by SPAR verdict: `accept_*` renders the paper (Title + Thesis + Findings + Background + References, with within-section sort by directness > tier > confidence > claim_id matching the thesis tournament); `reject_*` / any `gate_override` renders a structured rejection notice with the gate banner prominent. RENDER_VERSION = "writer/2026-04-28-deterministic".)
- `spar.py` (Day 4.2 + 4.2-fix — 397 cloc — 3-judge panel orchestration. `run_spar(graph, traces, *, topic, submission_id, chain, ledger)`: Auditor + Skeptic in `asyncio.gather`; Final Judge runs after both with their reviews appended as PANEL CONTEXT. Each judge returns `{verdict, score, rationale, flagged_claims}`; `_parse_judge_review` validates strictly (verdict ∈ {accept,reject}, score 1-10 int, non-empty rationale, list-typed flagged_claims with **strict reject of non-string entries** per 4.2-fix P2 — pre-fix silently filtered them, hiding malformed signal). `_validate_flagged_against_graph` rejects unknown claim_ids (4.2-fix P2 second half — hallucinated ids corrupt the audit). Verdict by deterministic `compute_spar_verdict`; `_identify_dissent` for 2-1 splits. **`_enforce_trace_gate` (4.2-fix P1) — TRUST-SPINE GATE**: when traces failed AND panel returned accept_*, code disposes with a `GateOverride` (schema-validated): canonical verdict forced to `reject_critical`, dissent suppressed, panel votes preserved verbatim in `reviews`, original `pre_gate_verdict` recorded for audit. PROMPT_VERSION = "spar/2026-04-28". `reviews_to_dict` is the wire shape for `runs/<topic>/spar_review.json` and surfaces `gate_override` for trail visibility.)
- `llm_client.py` (Day 3.2b — single-dep LLM surface: httpx OpenAI-compatible `chat_json` + `CallSpec` chain with skip-on-empty-key fallback + `CostLedger` (cost_log.json shape) + robust `extract_json` (strips `<think>` / fences / prose); `build_extract_chain(settings)` yields MiMo→Mistral; judge/write chains land Day 4)
- `fact_extractor.py` (Day 3.2c → 3.2c-fix-2 → **5.1-fix P1** — first LLM in the spine. CODE DISPOSES via EIGHT layers: (0) **claim-text source trace** via `_claim_supported_by_abstract` — bag-of-words content overlap ≥50% (5.1-fix P1 closes the "novel claim with no numeric fields" hole — pre-fix, the LLM could emit `Metformin prevents dementia` from an HbA1c abstract because no field-level traces fired and the deterministic writer rendered Claim.text verbatim), (1) ref/kind PINNED, (2) schema check on claim, (3) `check_verb_ban`, (4) `check_p_value_in_source` on claim text, (5) `_check_p_value_field` two-stage (grammar gate + tuple match), (6) estimate substring trace, (7) ci substring trace, plus within-item dedupe.)
- `render.py` (GUT on Day 5 — pure claim_graph → markdown, no LLM hooks)
- `settings.py` (KEEP, may extend `TRACE_BACKEND` documentation)
- `app.py` (deploy-safe stub — HTTP 503 paused page)

`bundle.py` was renamed via `git mv` to `evidence_cards.py` and refactored to import from the 3 new sibling modules.

**Runtime status — distinguish two states:**

| State | What's there | How to verify |
|---|---|---|
| **GitHub `main`** (latest commit-log entry) | Deploy-safe stub. `agent.app dashboard` serves HTTP 503 "service paused". | `python -m agent.app dashboard --port 8791` then `curl :8791/` → 503 |
| **VPS live (`research-agent.domlynch.com`)** | **Still V1.1** — deploy step pending since Day 0 push (2026-04-27). | `curl -s -o /dev/null -w "%{http_code}\n" https://research-agent.domlynch.com/` → `200` until the VPS pulls. |

To deploy the stub: SSH into VPS, `cd /opt/research-agent-bot && git pull && systemctl restart research-agent-bot`. Reverts to V1.1 via `git checkout v1.1-final && systemctl restart research-agent-bot`. Either path is reversible.

**Planted-failure case status (post-Day 3.1) — all 5 cases caught at multiple layers:**

| Case | What | Local layers (live) | Fixture layer (Day 2.4) | External layer (Day 3.1) |
|---|---|---|---|---|
| 1 | TAME protocol cited as results | **TRIPLE-LOCKED:** ✅ `topic_pack` whitelist + ✅ `evidence_cards` registry override (incl. abstract NCT scan) + ✅ `validators.check_verb_ban` prose-level | ✅ `FixtureTrialRegistryClient` returns TAME with `has_results=False` | ✅ **`citation_trace.trace_nct_exists` FAILS** when `item.role='published_results'` AND `record.has_results=False` (4th defense — protocol-as-results contradiction at trace layer) |
| 2 | Fabricated NCT | — | ✅ `FixtureTrialRegistryClient.get_trial("NCT99999999") → None` (planted absence) | ✅ **`citation_trace.trace_nct_exists` → `passed=False`** |
| 3 | Inflated p-value | ✅ `validators.check_p_value_in_source` (local exact-match) | — | ✅ **`citation_trace.trace_p_value_in_text` per-pvalue trace** |
| 4 | Alias drift ("Glufomin") | ✅ `topic_pack` alias whitelist + ✅ `validators.check_alias_drift` (apposition pattern) | ✅ `FixtureDrugAliasClient.lookup("Glufomin") → None` | ✅ **`citation_trace.trace_alias_match` → `passed=False`** |
| 5 | Off-domain extrapolation | ✅ `evidence_cards` topic-anchor gate + ✅ `validators.check_role_claim_match` directness contract | — | ✅ `citation_trace.trace_role_match` re-checks at trace time |

## Day plan (5 days, target — not deadline)
| Day | Ship | Done when | Status |
|---|---|---|---|
| **0** | Tag `v1.1-final`. Archive 6 LLM-coupled modules + 3 test files. Deploy-safe `app.py` stub. Post-mortem. DECISIONS.md entry. | Tag exists; deterministic tests green; `agent.app dashboard` runs as paused-stub. | ✅ `d941ae2` |
| **1** | `schemas.py` + `topic_pack.py` + `topic_packs/metformin.toml` + planted-failure fixtures + tests. Bundle.py 4-file split DEFERRED to Day 2 (paired with evidence_cards rename). | All 6 schemas frozen, `tomllib` parses topic pack, planted-failure cases 1+4 caught at topic_pack layer. | ✅ `a9eb7ab` + `941f21c` + `9cff619` |
| **2** | `evidence_cards.py` (refactor of bundle.py) + 4-file split + registry_overrides + `validators.py` + `compiler.py` (deterministic) + `trace_clients.py` fixture backend. Real metformin retrieval E2E. | ≥12 sources retrieved; cards classify correctly; planted case 1 caught at evidence_cards (in addition to topic_pack layer). | **✅ COMPLETE (fixture + live both green after Day 3.0)** — 2.1+2.2 `0ffcd5a` + 2.3 `9918c12` + 2.4 `e1bb56f` + 2.4-fixes `5b06bda` + 2.5 fixture-replay `c0cc11e` (40 sources, MASTERS pinned, perf 0.4 ms / 11.1 ms) + 2.5b live `7fe3c02` (script + baseline) + Day 3.0 abstract-NCT fix `555c73a` (live MASTERS now pinned to published_results / A1) |
| 3 | `citation_trace.py` against `trace_clients/*` (fixture + httpx backends). MCP backend optional. **First LLM stage:** fact extraction (LLM proposes, schema disposes). | Citation_trace catches planted cases 2, 3; httpx backend smoke-tests against clinicaltrials.gov. | **✅ COMPLETE** — 3.0 → 3.2c-fix-2 → 3.1-fixes-3 → 3.3a → 3.3b → 3.3c live smoke 6/6 green + **3.4 Day-3 E2E** (this slice — `tests/test_e2e_day3_pipeline.py` 7 tests: fixture-replay corpus → bundle → hand-curated Facts → compile_claims → compile_claim_graph → trace_claim_graph; verifies thesis-pick selects MASTERS direct A1; nct_exists fires for canonical NCT02308228; planted case 4 (Glufomin drift) flagged via trace_alias_match; sub-second perf baseline). LLM extraction stage covered by Day 3.2c unit tests + opt-in live smoke; Day 4 (SPAR + thesis tournament + writer) next. |
| 4 | `thesis_tournament.py` + `spar.py` + writer prompt with quality-bar block + judge checklist. Plant-corpus prompt iteration. `gap_analysis.py` only if time permits (non-gating). | All 5 planted failures caught; thesis tournament selects defensible thesis on real corpus. | **✅ COMPLETE** — 4.1 `49677b2` + 4.2 `a1dfcf4` + 4.2-fix `bc5e080` + 4-prep `dd73dd7` + 4.3 `57a8e30` + 4.3-fix `132d552` + 4.4 `a110178` + **4-fix** (this slice — P1 deterministic writer (writer.py 437 → 259 cloc; LLM removed entirely; rendering is `Claim.text` only; closes the residual self-declared-binding hole), P2 real-pipeline planted-failure E2E (drives `trace_claim_graph` against fixture clients before SPAR — proves planted scenarios actually generate failed traces, not just that the gate works on synthetic ones), plus a SPECIFICITY proof (clean MASTERS scenario passes through with no gate trigger — the reviewer's missing-test concern); 559/559 total). |
| 5 | `submit_adapter.py` + gutted `render.py` + new `app.py` + `mcp_server.py` + first end-to-end metformin run. | `runs/metformin-001/` contains 8 mandatory outputs; SPAR verdict accept_clean or accept_caveated; quality bar met against MASTERS / MET-PREVENT / Konopka 2019 standard. | **PARTIAL** — 5.1 `agent/orchestrator.py` (this slice — 277 cloc + 12 tests; emits 8 mandatory receipts; reviewer-cleared 3 P1s + 4 P2s before commit); 5.2 fixture-replay E2E + 5.3 first-metformin script + 5.4 render gut ☐ pending |

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

**Days 1-4 ✅ COMPLETE.** Day 5 in progress — orchestrator landed in 5.1.

### Day 5 progress

| Slice | Ship | Status |
|---|---|---|
| **5.1** | `agent/orchestrator.py` — single-call pipeline + 8 mandatory receipts | ✅ `1987105` |
| **5.1-fix** | P1 fact_extractor claim-text overlap gate + P2 atomic paper.md + Gap-1 force_overwrite + P3 doc drift | ✅ `2a01f17` |
| **5.2** | fixture-replay full-pipeline E2E (clean + gate-fired scenarios end-to-end) | ✅ this slice |
| **5.3** | `scripts/e2e_metformin_proof_001.py` — first LIVE metformin run | ☐ |
| **5.4** | gut `render.py` V1.1 stub (saves ~278 cloc) | ☐ |

### LOC budget after 5.1-fix
Current: **5,257 / 5,500 cloc** (4.4% headroom). Gut of `render.py`
(Day 5.4) reclaims ~270 cloc — gives plenty of headroom for the
optional `submit_adapter.py` / `app.py` / `mcp_server.py` from the
original Day 5 plan if they're needed. They're NOT required for the
"first metformin run produces all 8 receipts" done-when.

### Day 5.2 design notes — closes Day 4's specificity gap
The fixture-replay E2E must include BOTH scenarios explicitly:
1. **Clean path** — real metformin corpus, mocked LLM extracts valid
   facts, mocked SPAR judges accept, NO failed traces. Asserts
   `accept_clean` verdict, gate does NOT fire, `paper.md` renders the
   thesis cleanly. This closes the specificity gap the reviewer flagged
   on Day 4 (sensitivity proven; specificity unproven without a clean
   passthrough test).
2. **Gate-fired path** — same corpus but with one trace deliberately
   failing (e.g., a fabricated NCT injected). Asserts gate fires,
   `paper.md` is the rejection notice with `gate_override` prominent.

Both scenarios verify all 8 receipts produce JSON-loadable output.
