# database.researka.org — Scoping Document

**Purpose:** Self-contained brief for a parallel Claude session to build `database.researka.org` — a separate service that closes the search/verification gap between the Researka synthesis bot and tools like Elicit, while preserving the bot's audit-trail trust spine.

**Owner:** Dominic Lynch (solo dev).
**Generated:** 2026-05-09 by Claude (synthesis-bot lane).
**Status:** Scoping. New project; new repo. Not yet started.

---

## 1. Vision in one paragraph

`database.researka.org` is a separate service that exposes two surfaces over an MCP interface (or REST as a fallback):

1. **A vector-indexed corpus** of biomedical abstracts (~250M papers from Semantic Scholar bulk dataset), letting the synthesis bot pull high-recall candidate sets per topic without making live API calls per run.
2. **A curated facts ontology** (~1,000–2,000 high-leverage facts across 20 anti-aging topics, each tied to a source paper + numeric value + unit + 95% CI where applicable), letting the synthesis bot's audit gates *verify* that prose claims match canonical numbers — a deterministic verifier the LLM cannot bypass.

The synthesis bot calls into this service via MCP tools; the service is independently versioned, ingested, and scaled. The bot stays under its 18.5K LOC ceiling.

---

## 2. Why both, why separate

### Why both surfaces

| Surface | Solves | Without it |
|---|---|---|
| Vector corpus | Recall gap vs Elicit | Bot's 4-source live API retrieval misses 60–80% of relevant papers |
| Curated facts | Numeric hallucination | Bot's `numeric_role_guard` catches obvious fabrication but cannot verify "rapamycin extends mouse lifespan by 14%" against a known canonical |

These are different problems with different solutions. A vector corpus alone doesn't *verify* numbers — it surfaces candidates. A facts ontology alone doesn't *discover* new evidence — it checks known evidence. Both together = recall + precision.

### Why a separate service

- **LOC ceiling.** Bot is at ~24K raw / ~20K cloc against an 18.5K ceiling. Embedding 1,000+ facts + a vector index in `agent/` blows past it permanently.
- **Different update cadence.** Corpus reindexes weekly (Semantic Scholar bulk drops); facts curate manually with quarterly cadence; bot runs per-paper-render. Different services, different release schedules.
- **Different compute profile.** Vector index needs a vector DB (pgvector, qdrant, weaviate, or chroma). Bot is stdlib + httpx. Mixing them couples deploy.
- **Reusability.** Researka public reader, briefs V2, and any future research-agent variant all want to call into the same database. MCP-exposed = clean reuse.
- **Trust spine separation.** Bot's audit gates are deterministic and code-disposable. Database is data. Keeping them separate keeps the trust spine auditable in isolation.

---

## 3. Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  Synthesis bot (research-agent-bot)                          │
│  - run_v06_synthesis.py                                      │
│  - audit / cert / template-gate (deterministic)              │
└─────────────────────┬────────────────────────────────────────┘
                      │ MCP tool calls
                      ▼
┌──────────────────────────────────────────────────────────────┐
│  database.researka.org  (NEW REPO + SERVICE)                 │
│                                                              │
│  ┌─────────────────────┐    ┌────────────────────────────┐   │
│  │  Vector corpus      │    │  Curated facts ontology    │   │
│  │  - ~250M abstracts  │    │  - ~1-2k canonical facts   │   │
│  │  - pgvector / etc   │    │  - per-topic, per-claim    │   │
│  │  - LLM-extracted    │    │  - numeric + unit + CI     │   │
│  │    metadata at      │    │  - source paper anchored   │   │
│  │    ingest time      │    │  - audit-grade traceable   │   │
│  └─────────────────────┘    └────────────────────────────┘   │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  MCP server                                            │  │
│  │  - corpus_search(query, ...) → list[paper_hit]         │  │
│  │  - lookup_fact(topic, fact_id) → Fact                  │  │
│  │  - verify_claim(prose, expected_fact_id) → match/diff  │  │
│  │  - list_facts_for_topic(topic) → list[Fact]            │  │
│  └────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

---

## 4. Data model

### 4.1 Fact (curated ontology)

```python
@dataclass(frozen=True, slots=True)
class Fact:
    fact_id: str               # "rapamycin/itp/harrison_2009/lifespan_male"
    topic: str                 # "rapamycin"
    sub_topic: str             # "lifespan", "immune", "cardiometabolic"
    source_paper: SourceRef    # PMID / DOI / PMCID + author/year/journal
    claim_type: ClaimType      # "effect_size" | "threshold" | "regimen"
    numeric_value: float | None
    units: str | None          # "%", "mmol/mol", "log_RR", ...
    ci_lower: float | None
    ci_upper: float | None
    population: str            # "male heterogeneous-stock mice"
    intervention: str          # "encapsulated rapamycin in feed"
    comparator: str            # "control feed"
    timepoint: str             # "median lifespan"
    canonical_phrase: str      # the source-text quote, verbatim
    canonical_year: int
    last_validated: str        # ISO date — staleness gate
    notes: str
```

Example record:

```json
{
  "fact_id": "rapamycin/itp/harrison_2009/lifespan_male",
  "topic": "rapamycin",
  "sub_topic": "lifespan",
  "source_paper": {"pmid": "19587680", "doi": "10.1038/nature08221", ...},
  "claim_type": "effect_size",
  "numeric_value": 14.0,
  "units": "%",
  "ci_lower": null, "ci_upper": null,
  "population": "male heterogeneous-stock mice (4 sites)",
  "intervention": "encapsulated rapamycin in feed",
  "comparator": "control feed",
  "timepoint": "median lifespan",
  "canonical_phrase": "rapamycin extended median lifespan by 14% in males",
  "canonical_year": 2009,
  "last_validated": "2026-05-09",
  "notes": "Original ITP cohort. Replicated by Miller 2014 with dose-response."
}
```

### 4.2 PaperHit (vector corpus result)

```python
@dataclass(frozen=True, slots=True)
class PaperHit:
    pmid: str | None
    doi: str | None
    pmcid: str | None
    title: str
    abstract: str
    authors: tuple[str, ...]
    year: int
    journal: str
    cited_by_count: int
    similarity_score: float  # 0.0-1.0 from vector search
    metadata: dict           # design type, mesh terms, etc. (LLM-extracted at ingest)
```

### 4.3 ClaimMatch (verifier result)

```python
@dataclass(frozen=True, slots=True)
class ClaimMatch:
    matched: bool
    fact_id: str
    expected_value: float | None
    found_value: float | None
    diff_pct: float          # how far off
    canonical_phrase: str
    error_kind: Literal["exact", "near", "wrong_unit", "wrong_value", "missing"]
    rationale: str
```

---

## 5. MCP tool surface

The synthesis bot calls these via the MCP server. Each tool is stdlib-validated, deterministic given the database snapshot.

```
corpus_search(query: str, *,
              year_min: int = 2000,
              year_max: int = current,
              top_k: int = 50,
              filter_designs: list[str] | None = None,
              filter_topics: list[str] | None = None,
              ) -> list[PaperHit]
  # Vector search over abstracts.

list_facts_for_topic(topic: str, *,
                     sub_topic: str | None = None,
                     ) -> list[Fact]
  # Return all curated facts for a topic. The bot calls this at the start
  # of a run to build a verifier registry.

lookup_fact(fact_id: str) -> Fact
  # Retrieve one canonical fact.

verify_claim(prose: str, fact_id: str) -> ClaimMatch
  # Given a prose snippet and an expected fact_id, check whether the prose
  # quotes the canonical numeric value (with unit + tolerance). Used by
  # the bot's audit gate to catch hallucination.

batch_verify_claims(prose_chunks: list[str],
                    expected_fact_ids: list[str]
                    ) -> list[ClaimMatch]
  # Bulk version for whole-paper audit.
```

Synthesis-bot integration point: `agent/audit/canonical_fact_check.py` (new file in the bot, calls into the MCP). Keeps the bot's existing audit code path; adds one verifier alongside the existing Q1-Q14 checks.

---

## 6. Phased build plan

### Phase 0 — repo + scoping (week 0, ~4 hours)

- New repo: `researka-database` (or similar).
- README + DECISIONS.md + AGENTS.md per Vibe Coding Playbook v4.
- Choose tech stack (see §7).
- Stub MCP server with no tools wired (just `list_tools` returns empty).
- CI: ruff + pytest + type-check passing on empty stub.

### Phase 1 — curated facts MVP (week 1, ~3 days)

**Goal:** Manual curation of 50 rapamycin facts, queryable via MCP.

- Define `Fact` dataclass + JSON-on-disk storage in `facts/rapamycin/*.json`.
- Hand-curate 50 facts from the Researka rapamycin AAA4 paper's reference set + the 8 must-have papers in `docs/paper_quality/claude_parallel/missing_literature_audit.md`.
- Implement `lookup_fact`, `list_facts_for_topic`, `verify_claim` (numeric tolerance: ±5% for effect sizes, ±0.1 absolute for HbA1c, etc. — codified in `verifier_tolerances.py`).
- 30 tests covering exact match, near match, wrong unit, wrong value, missing fact.
- Deploy MVP to a local FastAPI + a real MCP transport (stdio or HTTP).

**Out of scope:** vector search, batch ingestion. This phase is "make the verifier work end-to-end on one topic."

### Phase 2 — wire into synthesis bot (week 2, ~2 days)

- Synthesis bot adds `agent/audit/canonical_fact_check.py` (stdlib + httpx for MCP).
- Bot's audit pipeline calls `verify_claim` on every numeric in prose where `fact_id` is known (build the prose→fact_id map from the citation registry).
- Verifier hits are persisted to `paper_path.with_suffix(".canonical_fact_check.json")` and surface as Q15 in the audit (extending the existing 14-question gate).
- Test on rapamycin AAA4 paper: how many numerics resolve to canonical facts? How many catch the existing bot's hallucinations?

**Output:** the bot now has a deterministic verifier for known claims. Hallucinated numbers fail Q15 → block cert.

### Phase 3 — bulk ingestion of Semantic Scholar (week 3-4, ~5 days)

- Download Semantic Scholar Academic Graph (~250M papers; bulk dataset dump is publicly available).
- Filter to biomedical (MeSH terms or topical filter).
- Ingest abstracts into pgvector / qdrant / weaviate.
- Implement `corpus_search` with vector embedding (sentence-transformers or OpenAI embeddings).
- LLM-extract metadata at ingestion (design type, primary outcome, sample size, …) and store as structured fields. ~1¢ per paper × 250M = ~$2.5M one-time. **Critical: use a small + cheap model** (Haiku or local Llama-3-8B) for the extraction. For MVP, do this only on the top 100K most-cited papers — that gets >90% of recall at <1% of cost.

**Cost note:** the bulk ingestion is the major spend. Start with 100K papers (~$1K with Haiku); expand later. Vector storage for 100K abstracts is <1GB.

### Phase 4 — synthesis bot uses corpus_search (week 5, ~2 days)

- Bot's retrieval lane (currently `agent/retrieve.py` calling 4 live APIs) gets a new client `agent/sources/researka_corpus.py` that calls `corpus_search` via MCP.
- Existing live-API path stays as a fallback for papers post-database-snapshot.
- Recall delta measured on a held-out test set (rapamycin, metformin, glp1) — expect 2-5× improvement.

### Phase 5 — fact ontology expansion (week 6-8, parallel work)

- Curate 50 facts/topic across 20 topics → ~1,000 facts total.
- LLM-assisted curation (extractor prompts vs canonical sources; human review).
- Quarterly review cadence to add new facts and validate `last_validated` timestamps.

### Phase 6+ — discovery + UI surfaces (post-MVP)

- Semantic Scholar updates ingested weekly.
- Public-facing web UI at database.researka.org showing facts + sources (read-only).
- API for external researchers (rate-limited, free tier).
- Researka public reader integration.

---

## 7. Tech stack recommendations

### Default stack

| Layer | Recommendation | Why |
|---|---|---|
| Language | Python 3.11+ | Matches synthesis bot |
| Web framework | FastAPI | Stdlib-friendly, async, auto-OpenAPI |
| MCP transport | stdio (dev) + HTTP (prod) | MCP-Python SDK supports both |
| DB (facts) | SQLite + SQLAlchemy (MVP) → Postgres (Phase 3+) | Curated facts < 10K rows; can stay SQLite for MVP |
| DB (vectors) | pgvector | Postgres extension; same DB as facts |
| Embeddings | `all-MiniLM-L6-v2` (sentence-transformers) | Free, local, 384-dim, good enough for paper retrieval; upgrade to OpenAI text-embedding-3-small ($0.02/1M tokens) for Phase 4+ |
| Bulk ingest | Semantic Scholar Academic Graph dump | Free, downloadable, ~50GB compressed |
| LLM for metadata extraction | Anthropic Haiku 4.5 (fastest + cheapest tier) | ~$0.25/MTok output ≪ Sonnet/Opus |
| Deploy | Hetzner VPS (same as bot) or Fly.io | Single small box for MVP; scale when needed |
| Auth | API token (header) | Simple; rate limit by token |

### Things to avoid

- **Don't build a custom vector index.** pgvector / qdrant / chroma are battle-tested.
- **Don't ingest the full 250M papers in MVP.** Start with 100K most-cited biomedical; expand later.
- **Don't use proprietary embeddings as primary.** Local embeddings work for retrieval; reserve OpenAI/Cohere for the cases where retrieval quality is genuinely insufficient.
- **Don't couple to the synthesis bot's deploy.** Different repo, different service, different release cadence.
- **Don't store paper full-text.** Abstracts only — full-text retrieval is a different system (Unpaywall / SciHub policy / publisher APIs).

---

## 8. Key decisions to make at project kickoff

| Decision | Recommendation | Why |
|---|---|---|
| Single repo or polyrepo | Single repo `researka-database` | One service, one deploy. Avoid premature splitting. |
| MCP-only or also REST | Both: MCP for the bot, REST for future UIs | REST adds <100 LOC; future-proof |
| Free tier or paid only | Free for academic; paid for enterprise | Researka's brand = open audit trail |
| Open-source the curated facts | Yes (CC-BY-SA) | Strengthens the protocol-play strategic option |
| Open-source the code | Yes (MIT or Apache-2) | Same strategic logic |
| Use Anthropic API for ingestion or local? | Anthropic Haiku for MVP; explore local for cost reduction at scale | Tradeoff cost vs quality; reassess at 1M paper scale |
| Cert mark for facts | Yes — each fact carries `last_validated` + `validator` (human or LLM-assisted) | Audit transparency; users see freshness |

---

## 9. Open risks

1. **Ingestion cost.** 250M papers × $0.001/paper = $250K. MVP with 100K papers is $100. Start small.
2. **Embedding drift.** If you start with `all-MiniLM-L6-v2` and later switch to OpenAI, you must re-embed everything. Decide once at Phase 3.
3. **Fact staleness.** A 2009 fact about rapamycin lifespan can become obsolete as new ITP runs land. The `last_validated` timestamp + quarterly review handles this, but only if discipline holds.
4. **MCP transport fragility.** Stdio MCP requires the bot and database to share a process boundary. HTTP MCP is more decoupled but adds latency. Test both on the actual bot pipeline before committing.
5. **License compliance.** Semantic Scholar bulk dataset has its own license. Read it carefully. Abstracts are typically OK; full-text is not.
6. **Vector quality on niche topics.** Geroscience-specific terminology may not embed well with general-purpose models. Plan for a domain-specific fine-tune at Phase 5 if recall is poor.

---

## 10. First-sprint scope (week 1 — what to build first)

Concrete deliverables for the new Claude session's week 1:

| Day | Deliverable |
|---|---|
| 1 | New repo `researka-database`. Empty MCP stub server runs locally. README + AGENTS.md + DECISIONS.md per playbook v4. |
| 2 | `Fact` dataclass + JSON storage + `lookup_fact` + `list_facts_for_topic` + 10 unit tests. |
| 3 | Manually curate 25 rapamycin facts (lifespan, immune, cardiometabolic; 8 source papers from missing_literature_audit). Each fact validated against PMID/DOI. |
| 4 | `verify_claim` with tolerance config + 15 tests covering match types (exact, near, wrong unit, wrong value, missing). |
| 5 | Deploy MVP to Hetzner (or local Docker). Synthesis bot wires `verify_claim` into a smoke test against the AAA4 paper. Measure: how many existing numerics resolve to canonical facts? Goal: 5/18 for the AAA4 corpus (the high-confidence quant claims). |

**End-of-week-1 verdict:** if 5+ AAA4 numerics resolve and verify, the architecture works. Proceed to Phase 2 (full bot integration). If <3 resolve, the fact ontology is too thin for verification — expand curation before integration.

---

## 11. Integration contract with the synthesis bot

What the bot expects from `database.researka.org`:

```python
# In agent/audit/canonical_fact_check.py (new file in synthesis bot):

from agent.researka_corpus_client import ResearkaCorpusClient

client = ResearkaCorpusClient(base_url=os.environ["RESEARKA_DATABASE_URL"])

def audit_canonical_facts(paper_text, citation_registry) -> list[ClaimMatch]:
    """Q15: every prose numeric whose receipt has a known fact_id must
    match the canonical value within tolerance."""
    matches = []
    for receipt_id, claim_text in extract_numeric_claims(paper_text):
        fact_ids = lookup_fact_ids_for_receipt(citation_registry, receipt_id)
        for fact_id in fact_ids:
            match = client.verify_claim(claim_text, fact_id)
            matches.append(match)
    return matches
```

What the bot does with `ClaimMatch.matched=False`:
- Adds to `audit.json` Q15 failures
- Surfaces in `consistency.json` as P1 issue
- Blocks final-gate cert (per `agent.final_gate.evaluate_final_gate`)

The bot's contract: every numeric in prose that the bot already ties to a receipt should have a `fact_id` lookup. The database's contract: every `verify_claim` call returns deterministic, audit-grade results within 200ms.

---

## 12. What this scoping doc deliberately leaves open

- **Exact embedding model choice** — depends on Phase 3 evaluation.
- **Exact deployment target** — depends on traffic projection (Hetzner is fine for MVP; Fly/Railway/AWS for scale).
- **Multi-tenancy** — out of scope for MVP. Single Researka instance.
- **Versioning of facts** — needs decision: append-only history vs current-state-only? Recommend append-only for audit purposes.
- **Public vs private split** — start fully open; add private tier later if a use case emerges.

---

## 13. Why this is the right move

1. **Closes the recall gap with Elicit** without abandoning the trust spine.
2. **Adds a verifier the synthesis bot doesn't have** — catches numeric hallucination at audit time.
3. **Architecturally clean** — separate service, separate deploy, MCP-decoupled.
4. **Strategic optionality** — works for both Option A (acquisition: a database is more sellable than a bot) and Option B (protocol play: open-source canonical facts = trust infrastructure).
5. **Bounded scope** — Phase 1 is 5 days, ships value immediately, doesn't block anything else.

The synthesis bot stays small and deterministic; the database scales independently. Two services, one product surface.

---

## 14. Brief for the new Claude session

Paste this into a new session to kick it off:

```
TASK: Build researka-database — a separate service that exposes a
curated facts ontology + (later) vector-indexed corpus over MCP.
The Researka synthesis bot will call into this for numeric verification
and high-recall paper retrieval.

Context: see docs/paper_quality/claude_parallel/researka_database_scoping.md
in the research-agent-bot repo for the full scoping doc.

Phase 0 + Phase 1 deliverables (week 1):
  - New repo: researka-database
  - FastAPI + MCP server stub
  - Fact dataclass + JSON storage + lookup_fact / list_facts_for_topic
  - 25 manually curated rapamycin facts (sourced from the AAA4 paper's
    reference set and missing_literature_audit.md tier-1 list)
  - verify_claim(prose, fact_id) with numeric tolerance
  - 30 tests (exact match, near match, wrong unit, wrong value, missing)
  - Deploy to Hetzner or local Docker for smoke test

Constraints:
  - Stdlib + FastAPI + sentence-transformers; no other deps.
  - Each module <300 LOC.
  - AAA grade with 2x audit per step.
  - Stay isolated from the synthesis bot's repo; integration is via MCP
    only.

End-of-week-1 success criterion: smoke test against the rapamycin AAA4
paper resolves ≥5 numerics to canonical facts, verifies them, and
returns ClaimMatch results.

Lane discipline:
  - This is a NEW project. Do not modify research-agent-bot.
  - Commits on a new repo's main branch.
  - Document architectural decisions in DECISIONS.md per Vibe Coding
    Playbook v4.
```

---

**End of scoping doc.** Total length: ~3,400 words. Self-contained — the new Claude session can read this once and start coding without needing the synthesis bot's source.
