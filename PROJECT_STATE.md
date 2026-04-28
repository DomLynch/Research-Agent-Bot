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

## Status — 2026-04-28 — Day 4.1 thesis tournament shipped (6-dim deterministic, wired into compiler); Day 4.2 SPAR next

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
**Tests:** 475/475 passing in 0.41s. ruff clean. git diff --check clean.
**Runtime LOC (cloc-style, the canonical count enforced by `tests/test_loc_budget.py`):** 4,205 / 4,800 ceiling (12% headroom). `wc -l` reports higher because it counts docstrings; the budget test excludes blanks + comment-only lines.

**Per-file (cloc-style, soft cap 300, hard cap 600):**
- `citation_trace.py` 355 (over soft cap — Day 3.1 trace orchestrator; trim or split with Day 3.3)
- `fact_extractor.py` 314 (just over soft cap — 7-layer trace + load-bearing prompt)
- `render.py` 278, `evidence_cards.py` 261, `llm_client.py` 239, `trace_clients.py` 228, `schemas.py` 226, `topic_pack.py` 218, `validators.py` 207
- Day 3.3 will push `trace_clients.py` past the 300 soft cap with httpx backends → split into a package then.

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
- `thesis_tournament.py` (Day 4.1a — 6-dim deterministic thesis selector: directness > tier > confidence > replication (-len(supporting_refs)) > recency (baseline_year - latest_year) > specificity (-min(50, word_count)), tiebreak by claim_id. `pick_thesis(claims, items_by_ref=None)` returns the chosen claim_id; `score_all` exposes per-claim scores for SPAR audit consumption in Day 4.2)
- `llm_client.py` (Day 3.2b — single-dep LLM surface: httpx OpenAI-compatible `chat_json` + `CallSpec` chain with skip-on-empty-key fallback + `CostLedger` (cost_log.json shape) + robust `extract_json` (strips `<think>` / fences / prose); `build_extract_chain(settings)` yields MiMo→Mistral; judge/write chains land Day 4)
- `fact_extractor.py` (Day 3.2c + 3.2c-fix + 3.2c-fix-2 — first LLM in the spine. `extract_facts_from_item / from_bundle` proposes facts via `chat_json`; CODE DISPOSES via SEVEN layers: (1) ref/kind PINNED from item.source.ref + role (LLM never proposes either), (2) schema check on claim, (3) `check_verb_ban` (planted case 1's 5th defense), (4) `check_p_value_in_source` on claim text, (5) `_check_p_value_field` — TWO-stage: grammar gate via `_PVALUE_DECIMAL_RE` rejects malformed values ('NS', 'not reported', '0', '1.2', etc.) BEFORE source-tracing (3.2c-fix-2 closes the vacuous-success bypass); then (operator, digits) tuple must appear in abstract via PVALUE_RE, (6) `_trace_field_in_source` whitespace-normalized substring match for `estimate` (3.2c-fix P2), (7) same for `ci`, plus within-item dedupe. `require_source_trace` flag (renamed from `require_p_value_trace` after fix expanded scope). off_domain skipped pre-call.)
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
| 4 | `thesis_tournament.py` + `spar.py` + writer prompt with quality-bar block + judge checklist. Plant-corpus prompt iteration. `gap_analysis.py` only if time permits (non-gating). | All 5 planted failures caught; thesis tournament selects defensible thesis on real corpus. | **PARTIAL** — 4.1 thesis_tournament shipped (6-dim deterministic, wired into compiler.compile_claim_graph; `_pick_thesis`/`_thesis_score` removed; 22 tournament tests + integrated through Day 3.4 E2E); 4.2 SPAR + 4.3 writer + 4.4 planted-failures-through-SPAR ☐ pending |
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

**Day 3 ✅ COMPLETE.** All four done-when criteria met (commits below).
Next: **Day 4 — thesis tournament + SPAR + writer.**

### Day 3 close summary (for reviewer audit)
- ✅ Citation_trace catches planted cases 2, 3, 4 (multi-layer defense)
- ✅ httpx backend smoke-tested live against CT.gov / ChEMBL / Europe PMC (`70e897a`)
- ✅ First LLM stage shipped + tested: 7 trust-spine layers, all source-traced
  (3.2c `207ffbf` + 3.2c-fix `848dba6` + 3.2c-fix-2 `743b35e`)
- ✅ Day-3 E2E green (`9e3caf8`): real metformin corpus → 8-claim ClaimGraph,
  MASTERS thesis-pick correct, sub-second perf

### Day 4 plan (per reviewer-suggested commit sequence)

| Slice | Ship | Risk |
|---|---|---|
| **4.1a** | `agent/thesis_tournament.py` — 6-dim deterministic scorer + selector + tests | Low (pure function, no LLM) |
| **4.1b** | Wire tournament into `compiler.compile_claim_graph`; drop the temporary `_pick_thesis` heuristic; E2E still green | Low (integration swap) |
| **4.2** | `agent/spar.py` — 3-judge panel (Evidence Auditor / Domain Skeptic / Final Judge), explicit tie-break, dissent always published | Medium (LLM orchestration) |
| **4.3** | `agent/writer.py` — claim-graph-gated prose drafter; LLM proposes prose, gate rejects any claim not in `claim_graph.json` | Medium (LLM + guard) |
| **4.4** | All 5 planted failures through SPAR → assert each caught at expected gate | Low (orchestration test) |

**Why thesis_tournament first:** deterministic (no LLM mocking hell);
property-test the 6-dim scoring math first; SPAR consumes its output, so
locking the interface first lets judge prompts be tuned against a stable
contract; replaces real debt (the temporary `_pick_thesis` in compiler.py).

**Reviewer cadence:** save the next reviewer pass for after 4.2 or 4.3 —
that's where the LLM prompts and tie-break logic live; tournament is
straightforward enough to ship without review.

### LOC budget for Day 4
Current: 4,089 / 4,800 cloc (15% headroom). Day 4 estimated 600-800 cloc
of runtime + matching tests. Total projected ~4,700-4,900 cloc — at or
near the ceiling. Plan: ship Day 4.1a/b first (small additions), then
re-evaluate before 4.2. If the SPAR module pushes us over, raise to 5,500
with a DECISIONS.md entry following the pattern from 2026-04-27.
