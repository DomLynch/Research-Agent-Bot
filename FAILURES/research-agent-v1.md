# Failure: V1.1 — LLM-in-the-spine architecture

## Date
2026-04-27 (archive day; V1.1 last shipped 2026-04-26 at commit `89ee064`, tagged `v1.1-final`)

## Trigger
After three months / two prior rebuild attempts, V1.1 (`agent/`) shipped a three-LLM pipeline (relevance → writer → judge) with deterministic gates as the spine. The pipeline produced rapid-review markdown drafts at ~$0.002–0.005 per run. 166 tests green, deployed at `research-agent.domlynch.com`.

But the architecture had three load-bearing LLMs in the production path. The judge would catch some of the writer's drift, but not all. The relevance-classifier would override deterministic directness when LLMs disagreed. Trust-layer fixes were piling up — visible UNVERIFIED banners, dual-rejection branches, judge re-runs after revision. Each fix added complexity to a system whose core problem was structural, not procedural.

## Symptom
Three repeated failure modes that the LLM-coupled gates never fully closed:

1. **Protocol cited as results.** RAPA-EX-01 (PMID 39354527) is a registered protocol; its abstract uses results-shaped phrasing ("evaluates the safety and efficacy"). The writer LLM, given the abstract, would generate prose claiming the trial *demonstrated* outcomes. Judge sometimes caught it, sometimes didn't.

2. **Mechanism inflated to clinic.** Mechanistic studies (mTORC1 transcriptomics, AMPK signaling) would be cited as evidence of clinical geroprotection. The relevance LLM would mark them direct; the writer would conflate.

3. **Off-domain extrapolation.** Oncology-context metformin studies cited as evidence in healthy-aging context. Topic-anchor gate caught most; LLM relevance override leaked some through.

The fixes (V1.0 → V1.1) added: 3-tier LLM fallback chains, hyper-critical judge prompts, judge re-runs after writer revision, dual-rejection UNVERIFIED banners, judge-skipped explicit marking. Each shipped. Each helped. None solved.

## Root cause
**LLMs were inside the trust spine.** Role classification, fact identity, citation accuracy, and final adjudication all routed through model judgment. The deterministic gates wrapped LLM output rather than constraining LLM input.

This is the wrong shape. Models are good at prose, summarization, attack-surface generation, and thesis ideation. They are bad at — and structurally cannot be made reliable for — categorical role assignment, citation identity preservation, and deterministic gate logic. Every reliability improvement we shipped was treating a symptom of one model deciding something a deterministic table should have decided.

The deeper architectural confusion: **markdown was the source of truth.** The writer produced prose; the judge graded prose; the QA gates parsed prose for invariant violations. There was no canonical structured representation of claims and evidence that prose was forced to render. The text was both the artifact and the database.

## Fix
The Proof 001 architecture (per `docs/DESIGN-001.md`):

1. **Claim graph is the source of truth.** Markdown is a downstream rendering. LLMs cannot add claims, change citation roles, or modify the graph after compile. Validators reject any prose claim that doesn't trace to a `Claim` object in `claim_graph.json`.

2. **Code disposes; LLM proposes.** Role assignment for any source with a registry ID (NCT, ISRCTN) is hard-coded in `topic_pack.toml`. Abstract classification is deterministic (refactored `bundle.py`). LLM never overrides. Verbatim hard rule, posted at the top of `compiler.py`:
   - Role assignment: registry override > deterministic abstract classifier. Never LLM.
   - Fact identity: extracted by LLM, schema-validated, source-text-traced.
   - Claim membership in paper.md: gated by `claim_graph.json`. LLM cannot add claims.

3. **Citation-trace as the moat.** Every claim's cited refs are verified against external sources (registry lookups, p-value text-grep, role match) before SPAR sees them. The Auditor judge reads `citation_trace.json` rather than re-deriving trust from the abstract.

4. **SPAR replaces single-LLM judging.** Three role-bound agents (Evidence Auditor, Domain Skeptic, Final Judge) with explicit tie-breaking and *always-published dissent*. "Agent consensus" without published dissent is just averaging.

5. **Quality bar lives in prompts as quoted reference passages.** The 7-PDF reference corpus (MASTERS / Konopka / MILES / MET-PREVENT / Kulkarni 2022 / Keys 2025 / Mohammed 2021) supplies gold-standard prose passages embedded in the writer prompt and judge checklist. The bar is concrete, not abstract.

## Prevention
The pattern to never repeat: **putting an LLM in the path of a categorical decision that a deterministic table can make.**

Specifically:
- Any role/tier/design classification → deterministic table or registry override, never LLM.
- Any "is this claim supported by this citation" → text-grep / registry lookup, never LLM.
- Any tie-breaking or final adjudication → pure-code rule, with LLM rationales captured but not ruling.
- Any "did the writer say something not in the source" → claim-graph guard, not LLM-judge inspection.

LLMs are routed to: prose generation under quoted-quality constraint, attack-surface enumeration, thesis-tournament ideation. Nowhere else.

The 5-case planted-failure corpus (`tests/planted_failures/metformin/`) is the regression that locks this in. If a future change re-routes role classification through an LLM, planted case 1 (protocol-as-results) breaks immediately.

## Related skills
- `agent_archived/proof001/` — preserved code for archaeology per v4 Rule 58. Do not import.
- `docs/DESIGN-001.md` — the rebuild design doc; v2 with all 5 audit amendments applied.
- `tests/test_no_legacy_imports.py` — extend to also block `agent_archived` imports during Day 1.
- `tests/planted_failures/metformin/` (Day 1 deliverable) — the regression that prevents this failure class from returning.

## What carried forward
The deterministic spine was right and survives intact:
- `agent/types.py` — frozen-dataclass invariants, role↔fact-kind pairing rule.
- `agent/retrieve.py` + `agent/sources/` — async parallel retrieval, multi-key dedup.
- `agent/bundle.py` — role/tier/directness classifier with topic-anchor gate (refactored on Day 1 into 4 single-purpose files per v4 Rule 54).
- `tests/fixtures/` — captured PubMed/OpenAlex/EuropePMC/CT.gov responses, including the rapamycin contradiction case that V1.1 fixed.
- 128 of the 166 V1.1 tests stay green throughout the rebuild — the deterministic ones.

V1.1 was not wasted. It was the experiment that revealed the architectural shape.
