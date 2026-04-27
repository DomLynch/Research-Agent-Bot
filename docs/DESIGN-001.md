# DESIGN-001 — Proof 001: Metformin Claim Court

**Status:** DRAFT v2 — awaiting sign-off before any code changes
**Date:** 2026-04-27
**Next gate:** founder review of this page. If schemas / SPAR cast / quality bar / LOC budget pass smell, Day 1 begins.
**Authors / reviewers:** Dom (founder/operator), Claude (architecture)
**Compliance:** v4 Vibe Coding Playbook — Rules 1, 7, 12, 14, 47, 49, 51, 52, 53, 54, 56, 57. AAA Build Protocol — Rules 1–4, 7, 12, 13, 14.

**Changelog v1 → v2 (post-audit amendments, all 5 reviewer blockers resolved):**
1. **YAML → TOML.** `topic_packs/metformin.toml` parses with stdlib `tomllib`, honoring V1.1's `httpx`-only runtime dep.
2. **MCP runtime decoupled.** New `trace_clients.py` defines three Protocol interfaces (`TrialRegistryClient` / `DrugAliasClient` / `LiteratureClient`) each with three swappable backends (MCP / direct httpx / fixture), selected by `TRACE_BACKEND` env var. Citation-trace works on VPS and CI without MCP availability.
3. **Receipt count consistent.** All sections now read "paper.md + 7 mandatory JSON receipts (8 files); gap_analysis.json optional 9th." §18 gate updated to 8/8.
4. **Quality reference corpus on disk.** [`docs/quality-reference/metformin/README.md`](quality-reference/metformin/README.md) created with structured metadata (DOI/PMID, expected role, gold passages) for all 7 papers. PDFs not committed (binary bloat); metadata is what feeds prompts.
5. **`gap_analysis.py` made optional.** Non-gating in v0; defers to Proof 002 if Day 4 is squeezed. Eval gates do not require it.

LOC delta: +150 (`trace_clients.py`); runtime ceiling stays 4,800 with 947 LOC headroom.

---

## 0. One-paragraph restatement (v4 Rule 51)

Proof 001 ships a single end-to-end metformin artifact that demonstrates the asymmetric thesis: **agent compiles deterministic evidence; SPAR court adjudicates; markdown is the rendering, not the source of truth.** The bot retrieves real metformin papers via PubMed / OpenAlex / EuropePMC / ClinicalTrials.gov, classifies their roles deterministically (with topic-pack overrides for canonical NCTs), extracts numeric facts under schema validation, builds a claim graph, runs a thesis tournament, runs the 3-agent SPAR court (Evidence Auditor / Domain Skeptic / Final Judge) with explicit tie-breaking and dissent publication, citation-traces every claim against a swappable trace-client interface (MCP / direct httpx / fixture backends), and renders `paper.md` plus 7 mandatory JSON receipts (8 files total; `gap_analysis.json` is an optional 9th, non-gating). **Quality target:** the prose must read at the level of MASTERS / MET-PREVENT / Konopka 2019 — the 7 quality-reference PDFs are the bar, not the input. Pass = thesis defensible from corpus, all 5 planted failures caught, full receipt bundle on disk. Fail = iterate. Three greens (metformin, rapamycin, everolimus) before any RFC outreach.

---

## 1. Constraint surface (v4 Rule 1)

**Must NOT break:**
- V1.1 deterministic spine (`agent/types.py` invariants, `agent/bundle.py` role/tier classifier with topic-anchor gate, `agent/retrieve.py` async fanout, `agent/sources/` adapter set). All **deterministic tests** (types, retrieve, evidence-cards classification, fixture snapshots, no-legacy-imports) stay green at all times during Day 1–5. LLM-coupled tests (`test_judge.py`, `test_draft.py`, `test_qa.py`) are archived in Day 0 alongside their modules — they don't apply post-rebuild.
- Existing fixture corpus in `tests/fixtures/` — captured real PubMed / OpenAlex / EuropePMC / CT.gov responses. Do not re-capture; do not invalidate.
- Cost ceiling: ~$0.005–$0.015 per Proof 001 run end-to-end. Daily cap from `DAILY_COST_CAP_USD` honored.

**Perf bounds:**
- Topic pack ingest → evidence cards: <30 s p95 (mostly retrieval IO).
- Citation-trace per claim: <2 s p95 (registry lookups via MCP).
- 3-agent SPAR adjudication: <90 s p95.
- End-to-end run (cold cache): <5 min p95. (Generous — we optimize after correctness.)

**Data sensitivity:** all input/output public. API keys vault-only. No PII in logs. (v4 Rule 1 sensitivity classification: public, except API credentials = secrets.)

**Hard rule, posted at top of `compiler.py` and re-printed in every relevant prompt:**

```
LLM PROPOSES. CODE DISPOSES.
- Role assignment: registry override > deterministic abstract classifier. Never LLM.
- Fact identity: extracted by LLM, schema-validated, source-text-traced.
- Claim membership in paper.md: gated by claim_graph.json. LLM cannot add claims.
```

**Escalation triggers (v4 high-blast-radius):** any change to `validators.py`, `topic_pack.toml` role overrides, or SPAR tie-breaking logic is treated as high-blast-radius. Mandatory adversarial pass + maker/judge separation per v4 Rules 12 & 14 before merge.

---

## 2. Goal / Non-goals / Refusals (v4 Build Doctrine)

**Goal:** one publishable metformin artifact (`paper.md` + 7 JSON receipts) where every claim has a survival trail, every citation is verified, every adjudication step is auditable, and the thesis is contestable rather than generic.

**Non-goals (v0):**
- No Researka platform (DID:web, PageRank, T1/T2/T3 tier graph). Deferred until 3 green proofs.
- No reputation graph or PageRank.
- No public RFC outreach.
- No automatic submission to arXiv / bioRxiv.
- No domain expansion beyond longevity/metformin.
- No multi-tenant, auth, or accounts.
- No real-time UI; output is files on disk + a static read-only viewer.

**Refusals (v4 Build Doctrine §G):**
- ORM (raw SQL or pure dataclass JSON; we have neither yet).
- Background job framework (Proof 001 runs synchronously).
- Plugin / extension system.
- Migration framework (one schema, one shape; rebuild fixtures if it changes).
- "Future-proof" abstractions for rapamycin/everolimus we don't yet need.
- LLM-generated role classifications (registry+deterministic only).
- Markdown as source of truth (claim_graph.json is canonical).

---

## 3. Pipeline at a glance (the 9 stages)

```
Stage 0  topic_pack ingest          DETERMINISTIC
Stage 1  source retrieve+normalize  DETERMINISTIC (existing V1.1 retrieve.py)
Stage 2  evidence_cards             DETERMINISTIC + REGISTRY OVERRIDE
                                    (refactor of bundle.py + new overrides table)
Stage 3  fact extraction            LLM proposes, schema disposes
Stage 4  claim graph compile        DETERMINISTIC edges + LLM attack surfaces
Stage 5  thesis tournament          LLM generates, deterministic selector
Stage 6  citation_trace             DETERMINISTIC (bio-research MCP wiring)
Stage 7  SPAR adjudication          3 LLM agents, deterministic tie-break
Stage 8  drafting                   LLM writes prose from claim_graph only
Stage 9  render + bundle            DETERMINISTIC (gutted render.py salvage)
```

Output bundle in `runs/metformin-001/`:

```
MANDATORY (8 files — all required to ship Proof 001):
  paper.md                    ← the artifact, judged against quality reference corpus
  evidence_cards.json         ← every source classified
  claim_graph.json            ← every claim + edges + attack surfaces
  citation_trace.json         ← every cite verified or failed
  thesis_tournament.json      ← all candidates + scores + winner
  spar_review.json            ← 3-agent verdicts + dissent
  qa_report.json              ← deterministic gate results
  submission.jsonld           ← Researka-platform-ready payload (stub for v0)

OPTIONAL (1 file — non-gating stretch; defers to Proof 002 if Day 4 is squeezed):
  gap_analysis.json           ← what canonical reviews missed (the "groundbreaking" lever)
```

---

## 4. Data model — six frozen-dataclass schemas (v4 Rule 53)

Lives in `agent/schemas.py` (additive; existing `agent/types.py` stays as-is).

```python
# All frozen=True, slots=True. Stdlib dataclasses. No pydantic.

@dataclass(frozen=True, slots=True)
class Claim:
    claim_id: str               # e.g. "C03"
    text: str                   # one-sentence, contestable
    claim_type: Literal["efficacy", "safety", "mechanism", "indirect", "context"]
    supporting_refs: tuple[int, ...]   # 1-indexed source refs
    opposing_refs: tuple[int, ...]
    directness: Literal["direct", "indirect", "mechanistic"]
    evidence_tier: Literal["A1", "A2", "B", "mixed"]
    confidence: Literal["high", "moderate", "low"]
    attack_surface: tuple[str, ...]    # named opposing arguments
    falsifiability: tuple[str, ...] = ()  # populated for thesis claim; default empty

@dataclass(frozen=True, slots=True)
class ClaimEdge:
    from_claim: str             # "C03"
    to_claim: str               # "C05"
    kind: Literal["supports", "qualifies", "contradicts", "mechanism_of"]

@dataclass(frozen=True, slots=True)
class ClaimGraph:
    claims: tuple[Claim, ...]
    edges: tuple[ClaimEdge, ...]
    thesis_claim_id: str        # the spine — winner of thesis tournament

@dataclass(frozen=True, slots=True)
class CitationTrace:
    claim_id: str
    ref: int
    trace_type: Literal["nct_exists", "percentage_in_text", "p_value_in_text",
                        "alias_match", "role_match"]
    passed: bool
    detail: str                 # human-readable detail
    source_excerpt: str | None  # quoted span if applicable

@dataclass(frozen=True, slots=True)
class JudgeReview:
    judge_role: Literal["evidence_auditor", "domain_skeptic", "final_judge"]
    model: str                  # e.g. "mistral-small-4"
    verdict: Literal["accept", "reject"]
    score: int                  # 0-10
    rationale: str
    flagged_claims: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class SPARReview:
    submission_id: str          # e.g. "metformin-001"
    reviews: tuple[JudgeReview, ...]   # always exactly 3
    verdict: Literal["accept_clean", "accept_caveated", "reject_majority", "reject_critical"]
    dissent: JudgeReview | None        # the minority voice if 2-1
    final_judge_resolution: str        # always present, always published
```

**Hard rule:** every field above is published in the receipt JSON. Nothing is hidden. The audit trail IS the moat.

---

## 5. Quality Reference Corpus

These 7 PDFs are **the quality bar, not the input.** The bot retrieves its own metformin evidence; we judge the output against these. **Metadata** (DOI/PMID, expected role/tier classification, gold passages) lives at [`docs/quality-reference/metformin/README.md`](quality-reference/metformin/README.md). The PDFs themselves are NOT committed (binary bloat); the structured metadata is what feeds prompts and tests at runtime. PDFs can be re-acquired via DOI by anyone reproducing the build.

### 5.1 The corpus

| # | Paper | One-line | Demonstrates |
|---|---|---|---|
| 1 | **Walton 2019 — MASTERS** (Aging Cell, NCT02308228) | RCT: metformin blunts hypertrophy from resistance training in healthy older adults | Numeric precision; explicit negative finding without spin |
| 2 | **Konopka 2019** (Aging Cell) | RCT: metformin blunts aerobic exercise adaptations | Honest hedging on p=0.08; surfaces 58/42 responder split |
| 3 | **Kulkarni 2018 — MILES** (Aging Cell) | Crossover RCT, n=14: 647 muscle DEGs, mTORC1↓ | Validation-gap acknowledgment; mechanism vs clinic separation |
| 4 | **Witham 2025 — MET-PREVENT** (Lancet HL, ISRCTN29932357) | RCT: metformin null on walk speed in sarcopenic frail elders | Clean null reporting with full CI; adverse event accounting |
| 5 | **Kulkarni 2022 — Geroscience repurposing** (Aging Cell) | Methodology: 12-point gerotherapeutic prioritization | Regulatory framing; methodology rigor |
| 6 | **Keys 2025 — Emerging uncertainty** (Ageing Res Rev) | Critical review: ITP failure, observational confounds | Review-level synthesis with proper hedging |
| 7 | **Mohammed 2021 — Critical review** (Front Endocrinol) | Concludes anti-aging effects "primarily indirect" | Separating direct from indirect mechanisms |

### 5.2 Gold passages (referenced in writer prompt & judge checklist)

**MASTERS — explicit negative finding, no spin:**
> "These results underscore the benefits of PRT in older adults, but metformin negatively impacts the hypertrophic response to resistance training in healthy older individuals."

**MASTERS — distinguishing significant from trend in one sentence:**
> "Metformin led to an increase in AMPK signaling, and a trend for blunted increases in mTORC1 signaling in response to PRT."

**Konopka — magnitude AND non-significance honestly stated:**
> "Metformin attenuated the increase in VO₂max following 12 weeks of AET by approximately 50%, although this did not reach statistical significance (p = 0.08)."

**Konopka — heterogeneity surfaced, not averaged away:**
> "There was a dichotomous response to AET with metformin where 58% of participants were positive responders with increased insulin sensitivity and 42% responded negatively with decreased insulin sensitivity."

**MILES — explicit validation gap:**
> "These findings remain to be validated in other tissues and study designs and do not yet allow us to identify the primary site of action of metformin."

**MET-PREVENT — full numeric reporting, no rounding-to-essentially-zero:**
> "Mean 4-m walk speed at 4 months was 0.57 m/s (SD 0.19) in the metformin group and 0.58 m/s (0.24) in the placebo group (adjusted treatment effect 0.001 m/s [95% CI –0.06 to 0.06]; p=0.96)."

**MET-PREVENT — clean null in conclusion, no spin:**
> "Metformin did not improve 4-m walk speed and was poorly tolerated in this population."

**Mohammed 2021 — direct vs indirect mechanism separation:**
> "The beneficial effects of metformin on aging and healthspan are primarily indirect via its effects on cellular metabolism and result from its anti-hyperglycemic action..."

These passages are quoted (with attribution) in `agent/prompts/writer_quality_bar.md` and `agent/prompts/judge_quality_checklist.md`.

### 5.3 Why this corpus, not others

- **Coverage:** 4 RCTs (direct evidence), 3 reviews (context). Both ends.
- **Span:** earliest 2018, latest 2025 — tracks how the field's confidence has actually moved.
- **Stylistic range:** from Aging Cell precision (MASTERS) to Lancet null-reporting discipline (MET-PREVENT) to review-paper synthesis (Keys, Mohammed).
- **Adversarial pressure:** every quoted passage demonstrates a habit LLMs default-fail on (averaging heterogeneity away, rounding null results, conflating mechanism with clinic, omitting validation gaps).

---

## 6. Topic pack — `topic_packs/metformin.toml`

**TOML, not YAML.** Reason: V1.1 constraint surface caps runtime deps at `httpx` only. YAML would require PyYAML; TOML parses with stdlib `tomllib` (Python ≥3.11). Zero dependency cost.

```toml
topic   = "metformin"
class   = "biguanide"
aliases = [
  "metformin",
  "biguanide",
  "Glucophage",
  "1,1-dimethylbiguanide",
  "dimethylbiguanide",
]

expected_evidence_slots = [
  "human_rcts",
  "human_observational",
  "human_mechanism",
  "preclinical_lifespan",
  "safety_tolerability",
  "dosing_regimen",
  "exercise_interaction",   # specific to metformin's controversial cluster
  "ongoing_trials",
]

[[canonical_trials]]
id            = "NCT02308228"
name          = "MASTERS"
expected_role = "published_results"
design        = "rct"

[[canonical_trials]]
id            = "ISRCTN29932357"
name          = "MET-PREVENT"
expected_role = "published_results"
design        = "rct"

[[canonical_trials]]
id            = "NCT04264897"
name          = "TAME"
expected_role = "registered_pending"
design        = "rct"

[[canonical_trials]]
id            = "NCT01765946"
name          = "MILES"
expected_role = "published_results"
design        = "rct"

# Hard-coded role overrides. evidence_cards.py checks this BEFORE any
# abstract-classifier runs. If a registry ID hits here, the role is fixed.
# LLM cannot override.
[known_role_overrides.NCT02308228]
role   = "published_results"
design = "rct"
tier   = "A1"

[known_role_overrides.ISRCTN29932357]
role   = "published_results"
design = "rct"
tier   = "A1"

[known_role_overrides.NCT04264897]
role   = "registered_pending"
design = "rct"
tier   = "A1"

[known_role_overrides.NCT01765946]
role   = "published_results"
design = "rct"
tier   = "A1"

special_rules = [
  "oncology / transplant evidence is INDIRECT; tier B at best for longevity claims",
  "exercise-interaction RCTs are DIRECT for healthy older adults claims",
  "observational mortality data must be flagged with indication-bias caveat",
  'any claim citing TAME must be marked "registered_pending" — not "shows" / "demonstrates"',
]

forbidden_verbs_for_protocol_role = [
  "found", "showed", "improved", "reduced", "demonstrated", "established", "proved",
]
forbidden_verbs_for_results_role_with_protocol_keywords = [
  "planned", "will assess", "pending", "ongoing", "awaiting",
]
```

`topic_pack.py` (~120 LOC) calls `tomllib.load()`, validates the schema, and exposes lookups. No third-party YAML lib.

---

## 7. Pipeline detail — what's deterministic, what's LLM (v4 Rule 56)

| Stage | Module | Deterministic | LLM | Hard guard |
|---|---|---|---|---|
| 0. Topic pack | `topic_pack.py` | `tomllib.load()` + schema validate | none | aliases must be non-empty |
| 1. Retrieve | `retrieve.py` (salvaged) | async fanout PubMed/OpenAlex/EPMC/CT.gov | none | 12+ sources required |
| 2. Evidence cards | `evidence_cards.py` (refactor of bundle.py) + `registry_overrides.py` | role/tier/design/direct/strict + topic-anchor gate; **registry override checked first** | none | every NCT in topic pack hits override; no LLM in this stage |
| 3. Fact extraction | `validators.py` + LLM call in `compiler.py` | schema validates every fact; rejects facts whose role/kind don't pair (existing `assert_invariants`) | extracts numerics, p-values, CIs, outcomes | every numeric must trace to source-text span |
| 4. Claim compile | `compiler.py` | edge construction; supporting_refs validated against bundle | writes attack surfaces | claim_type matches evidence directness |
| 5. Thesis tournament | `thesis_tournament.py` | 6-dim scoring rubric (0-10 each); deterministic top-pick by total score | generates 5–10 candidate theses; scores each | scoring rubric is pure code, not LLM judgment |
| 6. Citation trace | `citation_trace.py` + `trace_clients.py` (3 swappable backends) | NCT existence, drug alias, p-value text-grep, role-match — all via `TrialRegistryClient` / `DrugAliasClient` / `LiteratureClient` | none | every claim's refs traced; backend selectable via env (MCP / direct httpx / fixture) |
| 7. SPAR | `spar.py` | tie-breaking table; dissent capture | 3 role-bound agents (auditor, skeptic, judge) | tie-break is pure code; minority always published |
| 8. Drafting | `compiler.py` + LLM | claim-graph guard: every paragraph claim must trace to a Claim in graph | writes prose only | post-draft validator rejects any prose claim absent from claim_graph |
| 9. Render | `render.py` (gutted salvage) | pure templating: claim_graph + spar_review → markdown | none | output bundle bit-deterministic given inputs |

**Trace-client abstraction (Stage 6, the moat):**

The MCP toolkit (`bio-research:c-trials`, `bio-research:chembl`, `bio-research:biorxiv`) is only available in dev/Codex environments. Production VPS and CI need a different backend. Solution: `trace_clients.py` defines three Protocol interfaces, each with three implementations selected by env var `TRACE_BACKEND ∈ {mcp, http, fixture}`. `citation_trace.py` only knows about the Protocols, never the backends.

```python
# trace_clients.py — Protocol interfaces

class TrialRegistryClient(Protocol):
    def get_trial(self, trial_id: str) -> TrialRecord | None: ...
    # backends: MCPTrialRegistryClient (bio-research:c-trials)
    #           HttpxTrialRegistryClient (clinicaltrials.gov direct API)
    #           FixtureTrialRegistryClient (tests/fixtures/trials/*.json)

class DrugAliasClient(Protocol):
    def lookup(self, alias: str) -> CompoundRecord | None: ...
    # backends: MCPDrugAliasClient (bio-research:chembl)
    #           HttpxDrugAliasClient (ebi.ac.uk/chembl REST)
    #           FixtureDrugAliasClient (topic_pack alias whitelist)

class LiteratureClient(Protocol):
    def fetch(self, doi_or_pmid: str) -> LiteratureRecord | None: ...
    # backends: MCPLiteratureClient (bio-research:biorxiv)
    #           HttpxLiteratureClient (existing retrieve.py adapters reused)
    #           FixtureLiteratureClient (tests/fixtures/literature/*.json)

# citation_trace.py — uses Protocols only

def trace_nct(claim, ref, registry: TrialRegistryClient) -> CitationTrace:
    """Backend-agnostic. Same call site, swappable transport."""
    nct_id = source_for(ref).nct
    if not nct_id:
        return CitationTrace(passed=False, detail="no NCT for results-role citation")
    record = registry.get_trial(nct_id)
    if record is None:
        return CitationTrace(passed=False, detail=f"trial {nct_id} not found in registry")
    if record.status != claim.role_implication:
        return CitationTrace(passed=False,
                             detail=f"status={record.status}, claim implies {claim.role_implication}")
    return CitationTrace(passed=True, ...)

def trace_pvalue(claim, ref) -> CitationTrace:
    """Pure-text grep — no backend dependency."""
    # local check only
```

The 4 trace types for v0: **nct_exists, percentage_in_text, p_value_in_text, role_match.** Drug-alias is a bonus when topic pack lists aliases.

**Runtime backend selection** (in `agent/settings.py`):
- `TRACE_BACKEND=fixture` → CI default; deterministic; no network
- `TRACE_BACKEND=http` → VPS production; direct httpx to public APIs (existing `agent/sources/` adapters reused for literature)
- `TRACE_BACKEND=mcp` → dev/Codex; uses bio-research MCP tools directly

This means citation-trace is **not blocked on MCP availability** — VPS and CI both work without it.

---

## 8. SPAR — 3-agent cast, tie-breaking, dissent (Amendment 2 wired in)

**Cast (locked for Proof 001):**

| Agent | Model | Job |
|---|---|---|
| Evidence Auditor | Mistral Small 4 | Reads `citation_trace.json` + `evidence_cards.json`. Fails on role mismatch, untraced citations, fabricated NCTs. |
| Domain Skeptic | MiMo V2.5-Pro | Attacks the thesis with the strongest opposing case. Forced to name 3 specific opposing references or dissent on insufficient. |
| Final Judge | MiMo V2.5-Pro | Reads both verdicts. Resolves, scores, writes resolution. Never overrides Auditor on factual grounds. |

Methodologist, Statistician, Domain Advocate, Translation Judge, Editor: **deferred to Proof 002+.**

**Tie-breaking table (locked, in code at `spar.py`):**

| Vote | Verdict | Receipt entry |
|---|---|---|
| 3-0 accept | `accept_clean` | clean |
| 2-1 accept | `accept_caveated` | dissent rationale published verbatim |
| 1-2 reject | `reject_majority` | majority rationale primary; minority published |
| 0-3 reject | `reject_critical` | "critical issues" flag |

**Dissent rule:** the minority opinion is **always written into `spar_review.json`** under a top-level `dissent` field. Never compressed, never paraphrased. This is the single most important auditability discipline in the system — without it, "agent consensus" is just averaging.

**Adversarial prompt iteration (Day 4–5):** plant the 5 broken submissions (§10) and tune until Auditor + Skeptic catch all 5. If they don't, schemas or prompts get reworked before Proof 002.

---

## 9. Citation-trace — the moat (Amendment 1 wired in)

`citation_trace.py` writes every catch — pass or fail — to `runs/<id>/citation_trace.json` from the first metformin run. Format:

```json
{
  "submission_id": "metformin-001",
  "traces": [
    {"claim_id": "C03", "ref": 4, "trace_type": "nct_exists", "passed": true,
     "detail": "ISRCTN29932357 found in registry, status=Completed"},
    {"claim_id": "C05", "ref": 7, "trace_type": "role_match", "passed": false,
     "detail": "Source role=review but claim implies primary RCT result",
     "source_excerpt": "Mohammed 2021 abstract: 'In this review we summarize...'"}
  ],
  "summary": {"total": 47, "passed": 41, "failed": 6, "fail_rate": 0.128}
}
```

**Public dashboard (deferred):** ships when ~150 datapoints accumulate (3 proofs × ~50 traces). Until then, `citation_trace.json` is local-only.

---

## 10. Thesis tournament — 6-dim scoring (re-introduced for "groundbreaking" bar)

`thesis_tournament.py` (~250 LOC).

**Process:**
1. LLM (MiMo) generates 5–10 candidate thesis statements from `claim_graph.json`.
2. LLM (Mistral) scores each on 6 dimensions, 0–10:
   - **Novelty** — does this exceed generic summary?
   - **Defensibility** — can corpus support it?
   - **Falsifiability** — what evidence would overturn it?
   - **Counterevidence handling** — does it survive named attack?
   - **Field relevance** — would serious readers care?
   - **Actionability** — does it change interpretation, research, or practice?
3. Deterministic selector picks the candidate with the highest total score; tie broken by Defensibility, then Falsifiability.
4. Winner becomes `claim_graph.thesis_claim_id`.

Output: `thesis_tournament.json` records all candidates, all scores, the winner, and the runner-up margin. Reviewable evidence that the spine wasn't picked arbitrarily.

---

## 11. Gap analysis — what canonical reviews missed (OPTIONAL, non-gating in v0)

`gap_analysis.py` (~150 LOC). **Status: optional v0, non-gating.** Valuable but not required to prove the claim court works. If Day 4 is squeezed, this defers to Proof 002 without blocking sign-off. The eval gates do NOT require gap_analysis.json to ship.

**Process (when run):**
1. Pull 5 canonical metformin-aging reviews via PubMed (Barzilai 2016, Soukas 2019, Mohammed 2021, Keys 2025, Kulkarni 2022).
2. Extract their cited evidence sets.
3. Diff against bot's evidence cards. Surface high-quality post-cutoff sources NOT cited in the canon.
4. Surface canonical-cited sources the bot's classifier DOES cite but with a different role (e.g., review treats as "shows benefit," bot classifies as observational with confounds).

Output: `gap_analysis.json` — when produced, feeds the writer prompt as "what's underweighted in the existing literature." This is the lever that *upgrades* Proof 001 from "demonstrates the system" to "produces a real contribution." Without it, Proof 001 still ships; the contribution case is just less sharp until Proof 002.

---

## 12. Writer prompt — quality bar block (referenced from `agent/prompts/writer_quality_bar.md`)

The writer's system prompt includes (verbatim):

```
QUALITY BAR — your output must read at the level of these passages:

[Walton 2019 - explicit negative finding]
"These results underscore the benefits of PRT in older adults, but metformin
 negatively impacts the hypertrophic response to resistance training in
 healthy older individuals."

[Konopka 2019 - honest p-value hedging]
"Metformin attenuated the increase in VO2max following 12 weeks of AET by
 approximately 50%, although this did not reach statistical significance
 (p = 0.08)."

[Witham 2025 - clean null]
"Metformin did not improve 4-m walk speed and was poorly tolerated in this
 population."

[Kulkarni 2018 - validation gap]
"These findings remain to be validated in other tissues and study designs."

HABITS YOU MUST EMULATE:
- Report point estimates with 95% CI and p-values, never round to "essentially zero"
- Distinguish "significant" from "trend" in one sentence when both apply
- Surface heterogeneity (responder/non-responder splits) — never average it away
- Separate mechanism from clinical claim explicitly
- State validation gaps openly
- Use the verb "did not" for null results — do not soften to "showed limited"

HARD CONSTRAINTS:
- Every claim in your output must exist in claim_graph.json. Validators reject otherwise.
- Every cited p-value must trace to source text (citation_trace.json verifies).
- Use the role assigned by evidence_cards.py. If the card says "review", do not call it "trial."
```

---

## 13. Judge prompt — quality checklist (referenced from `agent/prompts/judge_quality_checklist.md`)

Each SPAR judge gets this checklist (excerpts):

```
Q1. Does the draft round any p-value to "essentially zero"? (Konopka p=0.08
    must NOT be reported as significant. MET-PREVENT p=0.96 must be reported
    with full CI.) FAIL → reject.

Q2. Does the draft surface responder heterogeneity where it exists?
    (Konopka 58/42 split must appear. If averaged away → reject.)

Q3. Does the draft separate mechanism (mTORC1, AMPK) from clinical outcome
    (walk speed, hypertrophy)? Mixing the two → reject.

Q4. Does the draft state at least one validation gap explicitly?
    (Kulkarni 2018 standard. None present → quality flag.)

Q5. Are review citations classified as "review" or pumped to "shows"?
    (Mohammed 2021, Keys 2025 must be tier B. Cited as evidence of effect → reject.)

Q6. Are NCTs cited with status matching the claim verb? (Protocol cited as
    "demonstrated" → reject. Verified by citation_trace.json.)

Q7. Does the draft include any claim absent from claim_graph.json?
    (claim-graph guard. If yes, automatic reject regardless of other quality.)
```

---

## 14. Planted-failure corpus (5 cases, Amendment 3 wired in via topic_pack overrides)

`tests/planted_failures/metformin/` — 5 hand-crafted broken submissions. Pipeline must catch all 5 before Day 5 closes.

| # | Failure type | Construction | Should be caught by |
|---|---|---|---|
| 1 | Protocol cited as results | Take TAME (NCT04264897, registered_pending) and write a claim "TAME demonstrated cardiovascular benefit" | `evidence_cards.py` registry override + `validators.py` verb-ban |
| 2 | Fabricated NCT | Inject "NCT99999999 — METFORMIN-X showed 30% mortality reduction" | `citation_trace.py` via bio-research:c-trials MCP (no record found) |
| 3 | Inflated p-value | Cite Konopka 2019 with "p<0.001 for VO2max" (real value p=0.08) | `citation_trace.py` p-value text-grep |
| 4 | Alias drift | Use "Glufomin" (made-up) as metformin alias | `topic_pack.toml` alias whitelist + `DrugAliasClient` (any backend) |
| 5 | Off-domain extrapolation | Cite an oncology-context metformin paper as evidence of geroprotection in healthy older adults | `evidence_cards.py` topic-anchor gate (existing V1.1 logic) + `validators.py` directness check |

Each case is a fixture under `tests/planted_failures/`. Test asserts: pipeline rejects with the expected validator code.

---

## 15. Worked metformin example — ~6 claims with attack surfaces

This is the "does the data model survive contact with the corpus" check. Built from the bot's own retrieval, not from the 7 reference PDFs. **YAML below is for human readability only — actual storage is JSON in `claim_graph.json` per the `Claim` dataclass at §4.** Illustrative shape:

```yaml
claim_id: C01
text: "Metformin blunts the hypertrophic response to resistance training in
       healthy older adults."
claim_type: efficacy
supporting_refs: [refs to MASTERS-equivalent retrievals]
opposing_refs: [refs to any counter-RCT in retrieval]
directness: direct
evidence_tier: A1
confidence: high
attack_surface:
  - "Single trial; replication pending"
  - "Effect size for fiber-type-specific outcomes was modest"
  - "Population was healthy older adults; may not generalize to frail"
---
claim_id: C02
text: "Metformin attenuates aerobic-exercise-induced gains in VO2max and
       insulin sensitivity in non-diabetic older adults."
claim_type: efficacy
supporting_refs: [Konopka-equivalent]
opposing_refs: []
directness: direct
evidence_tier: A1
confidence: moderate         # p=0.08 on VO2max
attack_surface:
  - "VO2max attenuation was ~50% but did not reach statistical significance"
  - "58/42 responder split suggests baseline-dependent effect"
  - "Sample size limits subgroup inference"
---
claim_id: C03
text: "Metformin's mechanism in human skeletal muscle includes mTORC1
       inhibition and AMPK activation, consistent with attenuated anabolic
       response."
claim_type: mechanism
supporting_refs: [MILES-equivalent + MASTERS biopsy data]
directness: mechanistic
evidence_tier: A1
confidence: moderate
attack_surface:
  - "Transcriptomic prediction of regulators is not direct enzymatic readout"
  - "Validation in other tissues and study designs not yet completed"
---
claim_id: C04
text: "In sarcopenic, frail older adults, metformin does not improve walk
       speed and is poorly tolerated."
claim_type: efficacy
supporting_refs: [MET-PREVENT-equivalent]
directness: direct
evidence_tier: A1
confidence: high
attack_surface:
  - "4-month duration may be insufficient"
  - "500 mg TID dose may be sub-therapeutic for some mechanisms"
---
claim_id: C05
text: "Observational mortality benefits of metformin are subject to
       indication bias and immortal-time bias; effect size attenuates on
       adjustment."
claim_type: indirect
supporting_refs: [Keys 2025-equivalent + observational corpus]
directness: indirect
evidence_tier: B
confidence: moderate
attack_surface:
  - "Active-comparator designs (vs sulfonylurea) show smaller effects"
  - "Bannister 2014 critique not universally accepted"
---
claim_id: C06_THESIS
text: "Metformin and exercise are antagonistic, not additive, geroprotective
       interventions in non-diabetic older adults: the same mTORC1-suppressing
       mechanism that defines metformin's geroscience rationale also blunts
       the adaptive response to both resistance and aerobic training, while
       providing no compensatory benefit in frail populations where exercise
       capacity is already compromised."
claim_type: efficacy
supporting_refs: [union of C01–C04]
opposing_refs: [observational +signal in C05]
directness: direct
evidence_tier: A1
confidence: high
attack_surface:
  - "Restricted to non-diabetic older adults; T2D context may differ"
  - "TAME results pending — would change the picture"
  - "Mechanism→clinic translation argument is inferential, not directly tested"
falsifiability:
  - "An RCT showing additive benefit of metformin+exercise vs exercise alone
     in healthy older adults would falsify"
  - "TAME positive result on composite endpoint would qualify (not falsify)"
```

If the data model can't carry this shape end-to-end without contortion, the schemas are wrong and we fix the page.

---

## 16. Salvage decision (concrete, file-by-file)

### KEEP as-is

| File | LOC | Notes |
|---|---|---|
| `agent/types.py` | 245 | `assert_invariants` is the role↔fact-kind invariant. Perfect. |
| `agent/retrieve.py` | 195 | async fanout with shared httpx.AsyncClient |
| `agent/sources/` (6 files: `_base.py`, `pubmed.py`, `openalex.py`, `europepmc.py`, `clinicaltrials.py`, `__init__.py`) | 513 | adapters behind shared `SourceClient` Protocol |
| `tests/test_*.py` (deterministic tests only — `test_types` 184, `test_retrieve` 91, `test_bundle` 570, `test_sources` 77, `test_render` 114, `test_loc_budget` 56, `test_no_legacy_imports` 27, `test_retrieval_quality` 235, `conftest.py` 75) | 1,429 | rapamycin regression cases stay green; add metformin tests on top |
| `tests/fixtures/` | — | captured real responses; do not invalidate |

### GUT and reuse

| File | LOC before | After | Action |
|---|---|---|---|
| `agent/bundle.py` | 591 | split → `evidence_cards.py` (~200) + `role_classifier.py` (~250) + `registry_overrides.py` (~80) + `text_signals.py` (~150) | rename and split per v4 Rule 54 (file <300). Add registry override layer. Otherwise classifier logic preserved. |
| `agent/render.py` | 309 | ~150 | strip every LLM-aware branch; pure claim_graph → markdown |

### ARCHIVE (to `agent_archived/proof001/` with a one-line README)

| File | LOC | Why archived |
|---|---|---|
| `agent/relevance.py` | 178 | LLM #1 directness override — replaced by topic-anchor gate (already in bundle) |
| `agent/llm.py` | 368 | old writer — replaced by claim-graph-driven drafter |
| `agent/judge.py` | 228 | replaced by SPAR (3 role-bound agents) |
| `agent/draft.py` | 338 | LLM-orchestrator — replaced by `compiler.py` |
| `agent/qa.py` | 340 | LLM-coupled QA — replaced by pure `validators.py` |
| `tests/test_judge.py` | — | tested archived `judge.py` |
| `tests/test_draft.py` | — | tested archived `draft.py` |
| `tests/test_qa.py` | — | tested archived `qa.py` |

Day 0 step: `git tag v1.1-final && git mv` the archived files (modules + their tests). **Not** `rm` — retain for archaeology per v4 Rule 58. `agent_legacy/` from prior rebuild stays where it is.

### NEW for Proof 001

| File | LOC | Purpose |
|---|---|---|
| `agent/schemas.py` | 180 | the 6 frozen-dataclasses |
| `agent/topic_pack.py` | 120 | `tomllib` load + override lookup |
| `agent/citation_trace.py` | 220 | client-agnostic trace logic + p-value grep |
| `agent/trace_clients.py` | 150 | 3 Protocols (Trial/Drug/Literature) × 3 backends (MCP/httpx/fixture) |
| `agent/spar.py` | 260 | 3 agents + tie-break + dissent |
| `agent/compiler.py` | 220 | facts → claims → graph; LLM extraction guarded |
| `agent/thesis_tournament.py` | 250 | 6-dim scoring + selector |
| `agent/gap_analysis.py` | 150 | **OPTIONAL v0** — canonical-review diff; non-gating |
| `agent/validators.py` | 180 | pure-function gates (verb ban, role match, p-value trace, etc.) |
| `agent/submit_adapter.py` | 120 | produces JSON-LD Researka-platform-stub payload |
| `agent/app.py` / `mcp_server.py` | 220 | CLI + MCP surface (5 tools per prior agreement) |
| new tests + planted-failure fixtures | 300 | 5 cases + thesis tournament tests + claim-graph guard test + trace-client backend tests |

---

## 17. LOC budget (honest, includes salvage and tests)

**Runtime LOC (subject to 4,800 ceiling):**

```
RETAINED RUNTIME:
  types.py                                245
  retrieve.py                             195
  sources/ (6 files)                      513
  evidence_cards.py (refactor of bundle)  200
  role_classifier.py (split from bundle)  250
  registry_overrides.py (new in split)     80
  text_signals.py (split from bundle)     150
  render.py (gutted)                      150
  ──────────────────────────────────────────
  RETAINED RUNTIME SUBTOTAL             1,783

NEW RUNTIME:
  schemas.py                              180
  topic_pack.py                           120
  citation_trace.py                       220
  trace_clients.py                        150   (Protocols + 3 backends each)
  spar.py                                 260
  compiler.py                             220
  thesis_tournament.py                    250
  gap_analysis.py (OPTIONAL v0)           150
  validators.py                           180
  submit_adapter.py                       120
  app.py / mcp_server.py                  220
  ──────────────────────────────────────────
  NEW RUNTIME SUBTOTAL                  2,070

  ──────────────────────────────────────────
  TOTAL RUNTIME                         3,853
  Hard ceiling                          4,800   (947 LOC headroom)
  Soft per-file budget (v4 Rule 54)      300
  Soft per-function budget (v4 Rule 54)   50
  Friday deletion-pass discipline (Rule 59)  enforced weekly

  Note: bundle.py (591 LOC) → 4-file split (200+250+80+150 = 680 LOC).
  +89 LOC overhead is the file-split cost; v4 Rule 54 compliance worth it.
```

**Test LOC (separate budget, no hard ceiling):**

```
RETAINED TESTS:
  test_types.py                           184
  test_retrieve.py                         91
  test_bundle.py                          570
  test_sources.py                          77
  test_render.py                          114
  test_loc_budget.py                       56
  test_no_legacy_imports.py                27
  test_retrieval_quality.py               235
  conftest.py                              75
  ──────────────────────────────────────────
  RETAINED TESTS SUBTOTAL               1,429

NEW TESTS:
  planted-failure corpus (5 cases)        ~120
  thesis_tournament tests                  ~60
  spar tie-breaking + dissent tests        ~50
  citation_trace + MCP wiring tests        ~70
  ──────────────────────────────────────────
  NEW TESTS SUBTOTAL                      300

  ──────────────────────────────────────────
  TOTAL TESTS                           1,729
```

**Grand total Proof 001 footprint: 3,853 runtime + 1,729 tests = 5,582 LOC.** The 4,800 ceiling applies to runtime only.

---

## 18. Eval gates (pass/fail, locked from prior agreement)

```
Role accuracy:          10/10  (no protocol cited as result; every NCT in topic
                                 pack hits override)
Citation accuracy:      10/10  (every NCT/DOI resolves and matches role; every
                                 numeric traces to source text)
Numeric fidelity:        9/10  (cited %s and p-values match source within
                                 rounding tolerance)
Directness discipline: 10/10  (mechanism ≠ clinical, oncology ≠ longevity)
Planted failures:       5/5   (all 5 caught at the gate they should be caught at)
Final artifact quality: 8.5+/10 (judged by SPAR Final Judge against the
                                 7-quote quality checklist; AND visually
                                 readable at the level of MASTERS / MET-PREVENT)
Receipt completeness:   8/8   mandatory (paper.md + 7 JSON receipts).
                                gap_analysis.json is a bonus 9th — not required.
```

**Stop conditions (locked):**
- Proof 001 fails any gate → iterate Proof 001. **Do not start rapamycin.**
- Proof 001 + 002 green, Proof 003 (everolimus) red → likely topic-pack issue (RAD001 alias, oncology indirectness). Fix and re-run, do not escalate.
- All 3 green → publish RFCs. Until then, no outreach.
- Cost per run >$0.05 sustained → re-route Mistral judge calls; if still >$0.05, switch to Gemma self-host before continuing.

---

## 19. Day-by-day sequence (5 days, target — not deadline)

| Day | Ship | Done when |
|---|---|---|
| 0 | Tag `v1.1-final`. Archive 5 LLM-coupled modules + their 3 test files (`test_judge.py`, `test_draft.py`, `test_qa.py`) to `agent_archived/proof001/`. Write `FAILURES/research-agent-v1.md` post-mortem (one page: why LLM-in-the-spine was the wrong shape). | git log shows tag; archived files in new dir; remaining deterministic test suite (~80–100 tests) green |
| 1 | `schemas.py` + `topic_pack.py` + `topic_packs/metformin.toml` + planted-failure fixtures + tests for schemas. Refactor `bundle.py` into 4 files. **No LLM yet.** | All schemas frozen-dataclassed; `tomllib` parses topic pack; tests pass on planted failures at the deterministic gates (cases 1, 4, 5) |
| 2 | `evidence_cards.py` + `validators.py` + `compiler.py` (deterministic part only) + `trace_clients.py` (fixture backend first). Real metformin retrieval works end-to-end via existing `retrieve.py`. | metformin retrieval surfaces ≥12 sources; cards classify correctly; planted case 1 caught at evidence_cards |
| 3 | `citation_trace.py` against `trace_clients.py` (fixture + httpx backends). MCP backend wired but optional. **First LLM stage:** fact extraction in `compiler.py` (LLM proposes, schema disposes). | citation_trace catches planted cases 2, 3 against fixture backend; httpx backend smoke-tests against real clinicaltrials.gov |
| 4 | `thesis_tournament.py` + `spar.py` + writer prompt with quality-bar block + judge checklist. Plant-corpus prompt iteration. **`gap_analysis.py` ONLY if time permits** — non-gating. | All 5 planted failures caught; thesis tournament selects a defensible thesis on real corpus |
| 5 | `submit_adapter.py` + `render.py` gutted + `app.py` + first end-to-end metformin run + receipt bundle. | `runs/metformin-001/` contains 8 mandatory outputs (gap_analysis.json optional 9th); SPAR verdict `accept_clean` or `accept_caveated`; quality bar met |

If any day's "done when" doesn't hold, Day N+1 doesn't start.

---

## 20. v4 playbook compliance check

| Rule | Application here |
|---|---|
| 1 — Constraint surface | §1 above |
| 7 — Deletion check | §16 ARCHIVE; old LLM-coupled files removed before any new code |
| 12 — Maker vs judge | SPAR is structurally maker/judge separation |
| 14 — Adversarial pass | planted-failure corpus IS the adversarial pass |
| 47 — Output discipline | this page leads with decision, evidence, tradeoffs |
| 49 — One module, one reason to change | bundle.py split into 4 single-purpose files |
| 51 — One-page design note | this document |
| 52 — Vertical slice | Proof 001 IS the slice; no platform creep |
| 53 — Data model first | §4 schemas frozen before any new code |
| 54 — Soft complexity budgets | per-file ≤300 LOC enforced via the bundle.py split; per-function ≤50 |
| 56 — Constrained agent edit scope | every new file has explicit purpose in §16 |
| 57 — Test the seams | tests target schema invariants, planted failures, claim-graph guard, tier protocol |
| 58 — Separate experimental from core | thesis_tournament + gap_analysis live in core but with explicit "Proof 001 only" scoping |
| 59 — Deletion as strategy | Friday deletion pass enforced weekly |

**MCP toolkit leverage:**
- `bio-research:c-trials` — every NCT in topic pack + every cited NCT in submitted paper. The single biggest "moat-for-free" lever.
- `bio-research:chembl` — drug-alias verification (catches alias drift planted failure).
- `bio-research:biorxiv` — preprint metadata for non-canonical recent evidence (used by gap_analysis).
- `knowledge` MCP — DECISIONS.md updates and skill capture after Proof 001 ships.

**AAA Build Protocol compliance:**
- Define done before coding ✅ (§18 eval gates)
- Small bounded tasks ✅ (§19 day-by-day)
- Simplest architecture ✅ (no platform layer; 9 stages)
- Strict contracts ✅ (§4 frozen-dataclasses)
- Reversibility ✅ (small commits, archive-not-delete)
- Stop loops by rule ✅ (§18 stop conditions)
- Validate continuously ✅ (V1.1 tests stay green throughout)
- Quality gate before "done" ✅ (§18 + this audit)

---

## 21. What this design refuses to be

- A spec for a generic publishing platform.
- A monorepo expansion into Researka-the-platform.
- A "future-proof" thesis-tournament framework that will support 12 topics. (Hardcoded for metformin in v0; generalize after Proof 003.)
- A claim of certainty about the exercise-orthogonality thesis. The corpus picks it; the SPAR court must defend it.

---

## 22. Open questions for founder before Day 1

1. **Corpus closed?** Or add other reference PDFs (PEARL, TAME-protocol, Bannister 2014, Martin-Montalvo 2013, ITP results) as additional quality benchmarks?
2. **Thesis lock vs tournament-decides?** Strong recommend tournament-decides — the corpus will pick exercise-orthogonality, but having the tournament run gives us the receipt that the spine wasn't pre-ordained.
3. **Hosting / deploy:** v0 stays on the existing `research-agent.domlynch.com` VPS, or do we need a new endpoint for Proof 001 outputs?
4. **MCP server tools:** confirm the 5-tool surface — `run_topic`, `get_evidence_cards`, `get_claim_graph`, `produce_submission_payload`, `audit_claim`?
5. **Day 0 archive path:** `agent_archived/proof001/` or a new top-level `archive/2026-04-27-llm-spine/`?

---

## 23. Sign-off line

**Founder:** _________________ Date: ________

By signing, founder confirms:
- LOC ceiling of 4,800 is acceptable for the "groundbreaking metformin paper" bar.
- The 7-paper quality reference corpus is closed for v0 (or adds noted in Q1 above).
- The exercise-orthogonality thesis (or the tournament's selection) is acceptable as the spine.
- The salvage decisions in §16 are correct.
- Stop conditions in §18 are binding — no skipping ahead on red gates.

After sign-off, Day 0 begins. Until then, this page is the only artifact — no code changes.
