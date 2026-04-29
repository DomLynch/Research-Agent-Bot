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

## Status — 2026-04-29 — Day 10.10 trust-spine ordering shipped, AAA NOT empirically reached on this corpus

**Honest grade: A-/AAA-track.** The reviewer caught Day 10.9 as gamed: the 10.0/10 score traced to (a) loosening the thesis validator (pair-coverage tolerance), (b) auto-prefixing cosmetic transitions, and (c) citing SPAR-rejected receipts as evidence. All three were reverted in Day 10.10 and the trust-spine ordering reviewer P1 demanded is now enforced:

**Day 10.10 changes:**
  - **Trust-spine ordering**: synthesis evidence sections (`direct_evidence`, `indirect_evidence`, `tensions`, `synthesis`, `limitations`) and the thesis tournament now see ONLY SPAR-accepted receipts. Rejected receipts go to a new `rejected_evidence` quarantine section that lists them with verdict + rationale for transparency, but they are NOT cited as evidence and do NOT contribute to the cross-source gate count.
  - **Audit Q3 tightening**: applicability now derives from CORPUS directness diversity, not just synthesis-section anchors. A mixed-directness corpus that produces a uniform-directness synthesis section is a Q3 FAIL (failure to integrate), not vacuous N/A.
  - **Load-bearing N/A no longer ships**: load-bearing pass requires applicable=True AND passed=True. A load-bearing question that doesn't apply means the synthesis can't be honestly graded on it, which blocks ship.
  - **Reverted Day 10.9 gaming**: pair-coverage tolerance in thesis validator → strict verbatim. Auto-prefix transitions in writer → removed (the reviewer correctly identified them as cosmetic).
  - **Strengthened thesis prompt**: requires taking a position and naming a mechanism/subgroup, not summarizing ambiguity. Gives an explicit GOOD vs WEAK example.
  - **Strengthened synthesis prompt**: REQUIRES at least one mixed-directness sentence with a transition phrase when the corpus has both directness types. Q3 invariant now lives in the prompt as a hard rule.

**Empirical effect on the existing 13-cluster metformin corpus:** with trust-spine ordering enforced, 12 of 13 receipts are SPAR-rejected. The accepted slice has 1 unique trial (NCT02308228, MASTERS) — below the cross-source ≥3 floor. Honest result: **synthesis cannot run on this corpus.** The system correctly refuses with an explicit error rather than producing a paper from rejected evidence.

**Day 10.10 follow-up empirical run** (`runs/metformin-multi-001-2026-04-29T10-27-39Z-4923/`): re-ran `--multi-receipt` with `TRACE_BACKEND=http` (live ClinicalTrials.gov registry) to test whether SPAR rejections were primarily fixture-mode `nct_exists` failures. Result: **30 clusters produced, only 1 accepted (cluster_01, accept_clean).** The same gate-failure outcome — live trace did not materially raise the SPAR pass rate. Inspecting the rejection rationales confirms the failures are real claim-quality issues (protocol-as-claim, mechanism inflation, underpowered sample sizes, missing source text on certain receipts) — not trace coverage gaps that live registry could fix. The receipt pipeline needs upstream improvements (fact_extractor's protocol-vs-results discrimination, role-classifier tightening, possibly a per-cluster `--best-of` retry) before this corpus can support cross-source synthesis. Day 10.10 has done its job: the trust spine is enforced; the bottleneck is now correctly visible upstream of synthesis, not buried inside it.

**Day 10.11 — protocol-as-claim filter (reviewer P1 fix):** added `check_objective_as_claim` validator + `OBJECTIVE_PATTERN_RE` to drop objective/protocol/registration spans (e.g., "To determine whether...", "Trial registration: NCT...", "We aimed to...") at fact-extraction time on `published_results` items. Strengthened the fact_extractor system prompt with explicit AVOID examples + GOOD/BAD finding patterns. Also added per-cluster error tolerance to `run_proof_multi_receipt` (a single transient SPAR judge JSON-parse error no longer kills the whole multi-receipt run; failed clusters are recorded in `multi_receipt_manifest.cluster_failures` and processing continues).

**Empirical Day 10.11 run** (`runs/metformin-multi-001-2026-04-29T11-00-43Z-50c9/`): re-ran `--multi-receipt` with the new filter. Result: **27 clusters produced, 1 accepted (accept_clean + 26 rejected).** Cluster count dropped from 30 → 27, confirming the filter is dropping objective spans upstream. But the **SPAR pass rate did not materially improve** (still ~4%) because the dominant rejection mode shifted: with objectives filtered out, the next-most-common SPAR critique is **mechanism inflation / over-claiming** (e.g., "extrapolation from statistical association to 'protective effect'", "single-cell mechanism inflated to clinical claim") plus **missing source text** on certain refs. These are different failure modes that need different guards. The Day 10.11 protocol filter is correct but insufficient for the empirical bar.

**Day 10.12 — mechanism-inflation guard + protocol-only-cluster filter:** added `check_mechanism_inflation` validator + `MECHANISM_INFLATION_RE` pattern (clinical-claim verb phrases like "protective effect on", "may protect", "demonstrates clinical efficacy") that rejects extractions when the cited evidence is mechanistic / preclinical / low-tier review AND the quote lacks scoping hedges ("in vitro", "preclinically"). Also added a multi-receipt orchestrator filter that drops clusters whose every supporting ref is `published_protocol` / `registered_pending` (those clusters cannot stand as standalone evidence — they're study purposes). Both fixes are reviewer-aligned per the Day 10.11 audit's data-driven recommendation.

**Empirical Day 10.12 run** (`runs/metformin-multi-001-2026-04-29T11-50-04Z-de47/`): **22 clusters produced (7 excluded as protocol-only), 2 accept_caveated, 20 rejected.** Accept rate doubled vs Day 10.11 (1/27 → 2/22, ~4% → ~9%). The mechanism-inflation guard is working (visible in cluster count drop and verdict shift) and the protocol-only filter is doing its job (7 hopeless clusters excluded, saving ~$0.0005 in SPAR cost per run + cleaner manifest). **But the cross-source synthesis gate (≥3 unique trials) is still not cleared.** With 2 accepted unique trials (MASTERS NCT02308228 + Mohammed-style vaccine receipt), synthesis correctly fails honestly: the script returns the Day 10.10 trust-spine error citing 2 < 3.

**Honest assessment after Day 10.12:** the validator-stack improvements have plateaued on this corpus. Three runs in (10.11 → 10.12), each adding correct guards, the SPAR pass rate moved from 4% → 9%. The remaining gap is **corpus quality**: only 2 of the 4 metformin canonical trials reach SPAR-accepted state, and the broader 40-source corpus has too many weak papers (mechanism inflation, missing source text, underpowered samples) for further validator tightening to recover them. Day 10.13 must address the input side: either (a) curate the metformin retrieve+bundle stage to anchor on the 7-paper Quality Reference Corpus directly, (b) implement per-cluster `--best-of N` retry on rejected clusters (probably won't recover legitimately-weak claims, but might recover transient SPAR judge failures), or (c) accept that this metformin corpus genuinely doesn't support cross-source synthesis at the trust-spine bar and pivot to rapamycin/everolimus where the canonical-trial corpus may be stronger.

**Architecture:**
  - **Layer 1 (Days 1-9.5 + 10.8b)** — claim receipts: atomic single-source evidence with full audit trail. `--multi-receipt` mode emits one receipt per cohesive cluster from a single corpus.
  - **Layer 2 (Day 10)** — synthesis layer: aggregates N receipts → tension matrix → thesis tournament (LLM proposes K, code disposes) → sectioned writer → Q1-Q7 audit. Every prose sentence anchored to receipt_ids; no novel numerics; `paper_synthesis.md` artifact gated by audit ≥8.5/10.

**Why AAA NOT empirically reached (Day 10.10):** the architecture is now defensible — gate counts unique trials from accepted receipts only, rejected receipts are quarantined not cited, load-bearing N/A blocks ship, thesis validator + transition handling are tight. But the metformin corpus has only 1 SPAR-accepted receipt out of 13, so the cross-source synthesis gate honestly fails. To reach AAA empirically, the next slice needs to either (a) raise the SPAR pass rate (better fact_extractor + trace coverage; many current rejections trace to fixture-mode `nct_exists` failures since the local registry doesn't carry every NCT in the corpus), (b) curate a richer corpus with stronger source papers, or (c) run with `TRACE_BACKEND=http` so live registry traces resolve.

The first synthesis attempt (Day 10.6, `runs/synthesis-metformin-010-2026-04-29T05-52-53Z-caa9/`) produced a 10/10 false-positive — 12 metformin receipts but all anchored on MASTERS NCT02308228, so it was duplicate-aggregation not cross-source synthesis. **Reviewer caught this; Day 10.7 closed the gate** (dedup + Q4 unique-trials + N/A applicable handling). Day 10.8a tightened further: gate counts unique TRIALS, not unique evidence units (3 distinct endpoints from one trial no longer pass as cross-source). **Day 10.8b adds the producer counterpart** so the gate has real cross-source input to chew on.

**Day 10.8b deliverables (this commit):**
  - `agent/compiler.py`: factored `_largest_cohesive_cluster` into `cluster_all_claims()` (returns ALL clusters, sorted best-first by canonical/directness/tier/size key) + `compile_per_cluster_claim_graphs()`. Old single-cluster API preserved as a thin wrapper — zero behavior regression on existing callers.
  - `agent/orchestrator.py`: new `run_proof_multi_receipt()` shares the LLM extract stage across clusters, then runs trace + SPAR + write + emit per cluster. Cost predictable: 1× extract, N× SPAR. Each cluster lands in `cluster_NN/` with full 8-receipt set; parent dir gets `multi_receipt_manifest.json`.
  - `scripts/e2e_metformin_proof_001.py`: `--multi-receipt` flag (mutually exclusive with `--best-of` and `--synthesize`). `--max-clusters N` caps emission. Output dir is `runs/<topic>-multi-001-<UTC>-<rand>/`.
  - 11 new tests (4 orchestrator, 7 compiler) covering cluster ordering, canonical bonus, all-singleton fallback, max_clusters cap, manifest refusal-to-clobber.

**Day 10.8c — first empirical cross-source synthesis paper:**
  - Producer: `runs/metformin-multi-001-2026-04-29T09-23-01Z-44b9/` — single fixture-mode metformin run with `--multi-receipt` produced **13 cluster receipts** (1 accept_caveated + 12 reject_critical/majority). The receipts cover **13 unique source units (7 with canonical NCT IDs, 6 untrialed)** — corrected from earlier overstatement of "13 distinct canonical NCTs". Canonical NCTs that surfaced: NCT00620191 (MILES), NCT02308228 (MASTERS), NCT03107884, NCT03713801, NCT03996538, NCT04994561, NCT06459310.
  - Consumer: `runs/synthesis-metformin-010-2026-04-29T09-32-28Z-0d63/paper_synthesis.md` — synthesis across all 13 receipts. Cross-source gate **passed** at 13 unique source units (was 1 in Day 10.6). Tension matrix detected 1 real non-orthogonal disagreement (cognitive null vs positive between two different trials). Synthesis sections rendered with anchored sentences, no novel numerics.
  - **Honest audit: 8.33 / 10 (below 8.5 floor) — ship blocked.** Q3-mohammed-direct-vs-indirect (load-bearing) failed: synthesis bullets that anchor on mixed-directness refs lack the required transition language. Thesis tournament: all 3 LLM candidates rejected by validators → fallback stub used. The gate works exactly as designed: paper exists, score reported honestly, ship-block fires.
  - Orchestrator bug found + fixed in same commit: manifest write was outside the `try/finally` so a hung `httpx.aclose()` after 13 SPAR-heavy clusters left the run dir without `multi_receipt_manifest.json`. Moved the write inside `try` (before `finally`); manifest backfilled for the existing run from per-cluster receipts.

**Day 10.9 (REVERTED in 10.10):** earlier slice claimed AAA at 10.0/10 by loosening the thesis validator (pair-coverage), auto-prefixing cosmetic transitions, and not filtering SPAR-rejected receipts. Reviewer correctly identified all three as gaming. All reverted in Day 10.10. The Day 10.9 metadata proof fields (`n_unique_canonical_trials`, etc.) and the P2 wording corrections were kept; only the audit-passing tricks were reverted.

**What's still missing for AAA:**
  1. **Day 10.11 — raise SPAR pass rate on the metformin corpus**. Most rejections trace to: (a) fixture-mode `nct_exists` failures (the local fixture registry doesn't carry every NCT in the corpus), (b) protocol-as-claim extraction (study objectives extracted as findings), (c) missing source-text on certain receipts. The trust spine works; the receipt pipeline needs better inputs. Options: enable `TRACE_BACKEND=http` for the synthesis re-run, improve fact_extractor's protocol-vs-results discrimination, or expand the fixture registry.
  2. **External human review** of the prose quality once a paper actually ships. Q1-Q7 verifies structural fidelity (anchors, no novel numerics, hedge language) but not coherence or peer-review-grade readability.

**Architecture milestones of Days 6-8:**
- Day 6.1: real-LLM lessons (strict-substring prompt, tolerated-orphans invariant, alias stopwords)
- Day 6.3: cohesive cluster filter (writer no longer renders shotgun mixes)
- Day 7: rapamycin pack + script generalized (`--topic` for all three)
- Day 8: everolimus pack + 5 refinements (drop estimate/ci substring, Unicode normalization, tier-aware filter, fact-multiplicity prompt, acronym-with-plural filter)
- Day 8.1: canonical-trial cluster priority (stabilizes ties)

**State verified through:** the most recent entry in the commit log table below. Exact repository HEAD remains `git log -1 --oneline`; this document does not try to self-reference its own future commit hash.

**Tag:** `v1.1-final` → `89ee064` (preserves V1.1 LLM-coupled state for archaeology)
**Tests:** 738/738 passing in 0.59s. ruff clean. git diff --check clean.
**Runtime LOC (cloc-style, enforced by `tests/test_loc_budget.py`):** 7,828 / **8,000** ceiling (Day 10.9 added +63 cloc for the Q3 transition helper, thesis pair-coverage logic, and metadata fields).

**Per-file (cloc-style, soft cap 300, hard cap 600 — synthesis layer adds 4 new modules):**
- Trust-spine: `spar.py` 412, `citation_trace.py` 485, `fact_extractor.py` 435, `orchestrator.py` 325, `schemas.py` 281, `llm_client.py` 276, `evidence_cards.py` 261, `writer.py` 259
- Synthesis layer (Day 10): `synthesis.py` ~470, `synthesis_thesis.py` 373, `synthesis_writer.py` 432, `synthesis_audit.py` ~210, `synthesis_schemas.py` 258
- Other: `trace_clients/_httpx.py` 225, `topic_pack.py` 218, `validators.py` 210, `text_signals.py` 193, `types.py` 195, `retrieve.py` 168, `compiler.py` 247, `thesis_tournament.py` 139, `trace_clients/_fixture.py` 126
- `render.py` deleted Day 5.4 (V1.1 stub orphaned by deterministic writer; saved 278 cloc).

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
| `8a487da` | 2026-04-28 | Day 5.2: full-pipeline fixture-replay E2E (specificity proof + sensitivity reaffirmed) |
| `d8b9dec` | 2026-04-28 | Day 5.2-fix: verbatim source_quote replaces bag-of-words overlap (closes endpoint-swap bypass) |
| `cf96bff` | 2026-04-28 | Day 5.3: live first-metformin-run script + `build_judge_chain` helper |
| `25c1349` | 2026-04-28 | Day 5.3-fix: `_CapTooSmallError` + promote `registry_ids_for` + `_format_path` outside-repo (2 reviewer P1s, AAA-cleared) |
| `f920d75` | 2026-04-28 | Day 5.4: gut V1.1 `render.py` (writer.py is now the renderer; −423 LOC, −278 cloc) |
| `b729b70` | 2026-04-28 | Day 5.5: stdlib `.env` auto-loader in `settings.py` (live script runs from fresh shell) |
| `423429c` | 2026-04-28 | Day 6.1: real-LLM live-run lessons — strict prompt (substring-only metadata), `tolerated_orphans` invariant, synthetic empty-facts rejection, expanded alias stopwords |
| `2b5eff3` | 2026-04-28 | **Day 6.3: cohesive cluster filter + all-caps acronym alias-skip → 🎯 PROOF 001 GREEN** (`accept_caveated` on MASTERS, 0 failed traces, fixture mode) |
| `7defaf8` | 2026-04-28 | Day 7: rapamycin pack + script generalization (`--topic` flag drives all three proofs from one entry point) |
| `6473755` | 2026-04-28 | Day 8: everolimus pack + 5 trust-spine refinements (drop estimate/ci substring rejection, Unicode middle-dot normalization, tier-aware cluster filter, fact-multiplicity prompt, acronym-plural filter) |
| `db6c02a` | 2026-04-28 | Day 8.1: canonical-trial cluster priority + extended body-composition alias stopwords (stabilizes Proof 001 onto MASTERS across LLM-non-determinism) |
| `54ff453` | 2026-04-28 | Day 8.1-state: PROJECT_STATE refresh (since-corrected — claimed "three green proofs" without saved rapamycin green receipt; downgraded in next slice after reviewer audit) |
| `0b16506` | 2026-04-28 | Day 8.2: reviewer audit response — null untraced estimate/ci before they enter the audit log (P2 trust-spine bug); save rapamycin green receipt + downgrade status language to "pipeline executes with principled outcomes"; refresh commit table + test count (P1 + P3) |
| `f056435` | 2026-04-28 | Day 8.3: track 5 proof receipts via `.gitignore` exceptions + clean three doc drifts |
| `9835411` | 2026-04-28 | Day 8.3-state: PROJECT_STATE polish (drop _next_ row, condense structural-break paragraph) |
| `e0e69bc` | 2026-04-28 | Day 9.1: `trace_numeric_in_text` — HR / OR / RR / aHR / aOR / ηp² / β / 95% CI with Unicode normalization; auditor's main rejection cause closed; rapamycin per-attempt rate 1/4 → 4/5 |
| `10fbc82` | 2026-04-28 | Day 9.2: `--best-of N` runner with deterministic ranking (verdict, gate_override, failed_traces, -n_claims, submission_id) and per-best `best_of_n_manifest.json`; variance-bounded sampling produces accept_* on all 3 drugs at --best-of 5 |
| `987db83` | 2026-04-28 | Day 9.3: canonical-NCT-anchored live retrieval (`extra_queries` kwarg on `retrieve()`); live metformin canonical coverage 1/4 → 4/4 |
| `8342638` | 2026-04-28 | Day 9.4: P1 trust-spine fix in `trace_numeric_in_text` (label+value co-occurrence); `--seed N` plumbed through chat_json → fact_extractor → SPAR; ruff cleanup |
| `5308433` | 2026-04-28 | Day 9.5: rename `paper.md` → `claim_receipt.md` (mislabel cleanup before Day 10) |
| `05d7977` | 2026-04-29 | Day 10.1: synthesis schemas (8 frozen-dataclass types) + 2 paraphrased-rubric prompts |
| `d6d1751` | 2026-04-29 | Day 10.2: tension matrix — deterministic per-pair classification (29 tests) |
| `7285704` | 2026-04-29 | Day 10.3: synthesis thesis tournament — LLM proposes K candidates, code disposes (21 tests) |
| `4f18bbf` | 2026-04-29 | Day 10.4: synthesis writer — sectioned LLM/deterministic mix, 10 sections in canonical order (16 tests) |
| `0102154` | 2026-04-29 | Day 10.5a: synthesis quality audit — Q1-Q7 deterministic checks (18 tests) |
| `7d3e050` | 2026-04-29 | Day 10.5b + 10.6: `--synthesize` flag + first synthesis paper (12 metformin receipts; reported 10/10 BUT was false-positive — see 10.7) |
| `5cc931e` | 2026-04-29 | Day 10.7: reviewer P1+P2 fix — dedup receipts + Q4 unique trials + N/A audit handling. Day 10.6 false-positive closed. |
| `4965b68` | 2026-04-29 | Day 10.8a: tighten gate to count unique TRIALS not deduped count; PROJECT_STATE refresh; LOC ceiling 7,500 → 8,000 with DECISIONS entry |
| `115971c` | 2026-04-29 | Day 10.8b: multi-receipt mode — `cluster_all_claims()` exposed + `run_proof_multi_receipt()` + `--multi-receipt` flag (11 new tests, 732/732 pass, 7,765/8,000 LOC) |
| `81a56b4` | 2026-04-29 | Day 10.8c: empirical proof — 13 cluster receipts across 7 canonical NCTs + 6 untrialed sources → real cross-source synthesis paper, honest audit 8.3/10 (Q3 ship-block fires correctly); orchestrator manifest-write fix |
| `534daea` | 2026-04-29 | Day 10.9: claimed AAA at 10.0/10 — REVERTED by Day 10.10 as gamed (pair-coverage validator loosening + cosmetic transition auto-prefix + SPAR-rejected receipts cited as evidence). Metadata proof fields + P2/P3 honesty kept |
| `35d33d3` + `71c22f4` | 2026-04-29 | Day 10.10: trust-spine ordering enforced — accepted-only filter + rejected_evidence quarantine + Q3 corpus-directness applicability + load-bearing N/A blocks ship + reverted Day 10.9 gaming. Empirical: 1 of 30 clusters accepted on live-trace re-run → gate honestly fails |
| `ea884ad` | 2026-04-29 | Day 10.11: protocol-as-claim filter shipped — `check_objective_as_claim` validator + strengthened extractor prompt + LOC ceiling raise to 8,500. 9 new validator tests; 750/750 total |
| `15cd5a3` | 2026-04-29 | Day 10.11 empirical: 27 clusters, 1 accepted (filter drops objective spans pre-extraction; cluster count 30→27) but SPAR pass rate stays ~4% — dominant rejection mode shifts to mechanism inflation |
| `0e125bd` | 2026-04-29 | Day 10.12: mechanism-inflation guard + protocol-only-cluster filter shipped — `check_mechanism_inflation` validator + `MECHANISM_INFLATION_RE` + multi-receipt orchestrator excludes clusters whose every supporting ref is protocol/registered. 760/760 tests pass |
| _next_    | 2026-04-29 | Day 10.12 empirical: 22 clusters (7 excluded as protocol-only), 2 accept_caveated, gate ≥3 still not cleared. Validator stack has plateaued; Day 10.13 needs corpus-level work |

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
- `fact_extractor.py` (Day 3.2c → 5.1-fix → 5.2-fix P1 → **8.2** — first LLM in the spine. The LLM emits `source_quote` — a VERBATIM SPAN copied from the abstract — and code uses that quote AS `Fact.claim`. Closes the novel-claim attack surface structurally. CODE DISPOSES via these gates: (0) `_quote_in_abstract` verbatim check, (1) ref/kind PINNED, (2) `check_verb_ban`, (3) `check_p_value_in_source` on quote text, (4) `_check_p_value_field` (grammar gate + tuple match), plus within-item dedupe. **Day 8.2 (reviewer P2):** `estimate` and `ci` are kept ONLY when present as substrings of the verified `source_quote`; otherwise NULLED before the Fact is constructed. Pre-Day-8.2 these fields entered `fact_extraction_log.json` untraced — an LLM could write `HR 0.10` into the audit log as if source-backed. Nulling on miss preserves the verified quote without polluting the audit trail.)
- `settings.py` (KEEP — Day 5.5 added stdlib `_load_dotenv_if_present()` so a `.env` at repo root populates os.environ for unset keys at `load_settings()` time. Existing env always wins (CI / explicit `export` unaffected). Closes the gap that previously required a manual `export` before the live metformin script could find `MIMO_API_KEY`. May extend `TRACE_BACKEND` documentation later.)
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
| 5 | `submit_adapter.py` + gutted `render.py` + new `app.py` + `mcp_server.py` + first end-to-end metformin run. | `runs/metformin-001/` contains 8 mandatory outputs; SPAR verdict accept_clean or accept_caveated; quality bar met against MASTERS / MET-PREVENT / Konopka 2019 standard. | **✅ COMPLETE** — 5.1 orchestrator `1987105` + 5.1-fix `2a01f17` + 5.2 fixture E2E `8a487da` + 5.2-fix verbatim source_quote `d8b9dec` + 5.3 first-metformin script `cf96bff` + 5.3-fix `25c1349` + 5.4 render-gut `f920d75` + 5.5 dotenv loader `b729b70`. Receipts: see Day 5 progress table below. |
| 6-8 | Days 6, 7, 8 covered live-LLM iteration (cohesive cluster filter, rapamycin pack, everolimus pack, 5 trust-spine refinements). | Pipeline runs on all three drugs; verdict varies per run because LLM at T=0 is non-deterministic. | **✅ COMPLETE** — 6.1 `423429c` + 6.3 `2b5eff3` + 7 `7defaf8` + 8 `6473755` + 8.1 `db6c02a` + 8.2 `0b16506` (reviewer-audit response: nulled untraced metadata + downgraded status language). |

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

**Days 1-8.2 ✅ COMPLETE.** The pipeline now has tracked proof receipts for
metformin, rapamycin, and everolimus. Remaining work is reliability, broader
numeric tracing, and live-retrieval anchoring.

### Day 5 progress

| Slice | Ship | Status |
|---|---|---|
| **5.1** | `agent/orchestrator.py` — single-call pipeline + 8 mandatory receipts | ✅ `1987105` |
| **5.1-fix** | P1 fact_extractor claim-text overlap gate + P2 atomic paper.md + Gap-1 force_overwrite + P3 doc drift | ✅ `2a01f17` |
| **5.2** | fixture-replay full-pipeline E2E (clean + gate-fired scenarios end-to-end) | ✅ `8a487da` |
| **5.2-fix** | P1 verbatim source_quote replaces bag-of-words overlap (closes endpoint-swap bypass) | ✅ `d8b9dec` |
| **5.3** | `scripts/e2e_metformin_proof_001.py` + `build_judge_chain` helper | ✅ `cf96bff` |
| **5.3-fix** | P1 `_CapTooSmallError` + promote `registry_ids_for` + P1 `_format_path` outside-repo | ✅ `25c1349` |
| **5.4** | gut `render.py` V1.1 stub (writer.py is now the renderer; saved 278 cloc) | ✅ `f920d75` |
| **5.5** | `settings.py` stdlib `.env` auto-loader so live script runs without manual export | ✅ this slice |
| **6** | first metformin run produces 8 receipts | ✅ `2b5eff3` — fixture mode reproduces `accept_clean` / `accept_caveated` on MASTERS; receipts saved. |
| **7** | rapamycin pack + Proof 002 fixture | ✅ `7defaf8` (pack + script generalization). Saved receipts: 1 of 4 attempts produces `accept_caveated` on PEARL; the other 3 reject on untraced ηp² effect sizes. Pipeline executes; verdict not deterministic. |
| **8** | everolimus pack + Proof 003 fixture | ✅ `6473755` + `db6c02a` (pack + 5 trust-spine refinements + canonical-priority tiebreaker). Saved receipts: latest `reject_critical`, prior `accept_caveated`. Skeptic correctly flags PROTECTOR's lab-vs-clinical-endpoint cherry-picking. |
| **8.2** | reviewer audit response: null untraced estimate/ci before audit log; downgrade status from "three green" to "principled SPAR outcomes" | ✅ |
| **9.1** | numeric_in_text trace closes auditor "untraced numerics" rejection | ✅ |
| **9.2** | `--best-of N` runner | ✅ |
| **9.3** | live-retrieval canonical anchoring on topic_pack NCTs | ✅ |
| **9.5** | rename `paper.md` → `claim_receipt.md` (architectural truth) | ✅ |
| **10.1-10.6** | synthesis layer: tension matrix + thesis tournament + sectioned writer + Q1-Q7 audit | ✅ (10.6 false-positive caught and closed) |
| **10.7-10.8a** | reviewer fixes: dedup + Q4 unique trials + N/A audit + count_unique_trials gate | ✅ |
| **10.8b** | multi-receipt mode: cluster_all_claims + run_proof_multi_receipt + --multi-receipt | ✅ |
| **10.8c** | empirical cross-source proof: 13 cluster receipts → synthesis paper, audit 8.33/10 honest | ✅ |
| **10.9** | writer Q3 transition + thesis pair-coverage tolerance + metadata proof fields | REVERTED in 10.10 (gamed: cosmetic transitions + validator loosening + cited rejected receipts). Metadata fields + P2/P3 honesty kept. |
| **10.10** | trust-spine ordering: filter accepted, rejected_evidence quarantine, gate counts accepted-only, Q3 corpus-directness, load-bearing N/A blocks ship, prompts strengthened | ✅ |
| **10.11** | raise SPAR pass rate: fact_extractor protocol-vs-results discrimination + per-cluster error tolerance | ✅ (filter + robustness shipped; empirical accept rate didn't move because mechanism inflation is now the dominant rejection mode) |
| **10.12** | mechanism-inflation guard + protocol-only-cluster filter | ✅ (accept rate 4% → 9%, but gate ≥3 still not cleared on this corpus) |
| **10.13** (next) | corpus-level fix: anchor retrieve+bundle to canonical-trial NCTs (skip noisy non-canonical retrieval) OR per-cluster `--best-of N` retry OR pivot to a topic with a stronger corpus | ☑ this slice |
| **10.14** (stretch) | external human review of prose quality — outside automated audit | ☐ |
| **11** (stretch) | RFC outreach + first user-facing artifact | ☐ |

### LOC budget after Day 10.10
Current: **7,922 / 8,000 cloc** (~1% headroom). The 7,500 → 8,000
raise is documented in DECISIONS.md (2026-04-29 Day 10.8a entry).
Day 10.10 added net ~110 cloc (trust-spine helpers + quarantine
section + Q3/load-bearing tightening + prompt module split).
Day 10.11's protocol-vs-results discrimination is projected at
~80-150 cloc; if it pushes past 8,000 a DECISIONS entry will raise
the ceiling honestly per the existing reviewer pattern.

### What's left before AAA-defensible release

After Day 10.10 the trust-spine ordering is enforced end-to-end and
gaming has been reverted. The architecture is defensible; the
empirical proof on the metformin corpus is NOT yet AAA. The
remaining gap is upstream of synthesis:

1. **Day 10.11 — raise SPAR pass rate.** Empirical: 1 of 30 clusters
   accepted on the live-trace re-run. Inspecting the rejection
   rationales, the dominant failure mode is **protocol-as-claim
   extraction** — the fact_extractor pulls study OBJECTIVES ("To
   determine whether...") as if they were findings, and SPAR
   correctly rejects them. The reviewer's recommended fix: tighten
   fact_extractor to discriminate protocol/objective sentences from
   results sentences. Secondary failure modes: mechanism inflation
   (single-cell extrapolated to clinical), underpowered samples
   cited as moderate, missing source text on a few receipts. Once
   the dominant failure mode is fixed, the gate's ≥3 unique-trials
   floor becomes reachable on the existing metformin corpus.
2. **Day 10.12 — external human review** of `paper_synthesis.md`
   once a valid one ships. Q1-Q7 verifies structural fidelity but
   not peer-review-grade readability.

To reproduce the Day 10.10 honest result on demand:
```
TRACE_BACKEND=http .venv/bin/python -m scripts.e2e_metformin_proof_001 \
  --multi-receipt
.venv/bin/python -m scripts.e2e_metformin_proof_001 \
  --synthesize runs/metformin-multi-001-<UTC>-<rand> --topic metformin
```
Expected: producer emits N cluster_NN/ subdirs (most rejected by
SPAR); synthesizer refuses to run with an explicit cross-source
gate-failure error citing "1 unique canonical trial(s)/source(s);
cross-source synthesis requires ≥3."

After Day 10.11, the same chain should produce ≥3 accepted clusters
and synthesis should run with an honest audit score (whatever it
turns out to be — no more games).

To reproduce the Day 10.8c chain on demand (architecture verification):
```
.venv/bin/python -m scripts.e2e_metformin_proof_001 --multi-receipt
.venv/bin/python -m scripts.e2e_metformin_proof_001 \
  --synthesize runs/metformin-multi-001-<UTC>-<rand> --topic metformin
```
Receipts land in `runs/`. Multi-receipt produces N cluster_NN/ subdirs
plus `multi_receipt_manifest.json`; synthesis emits
`paper_synthesis.md` + `synthesis_quality_audit.json` +
`synthesis_metadata.json` (which now includes the cross-source
proof fields, per Day 10.9 reviewer P2).

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
