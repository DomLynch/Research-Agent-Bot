# Proof 002 — Rapamycin Corpus Seeding Plan

Status as of 2026-05-04: **Pipeline is rapamycin-ready; corpus is the
last blocker.**

## What's already done

| Workstream | Status | Reference |
|---|---|---|
| **A. Pipeline topic-parameterization** | ✅ done | commit `7c7e96e` (Fix #20-50 series) |
| **B. Rapamycin background literature** | ✅ done (4 canonical entries) | `docs/background_literature.json`: Harrison 2009 (14% mouse lifespan), Lamming 2012 (mTORC2 disruption at 2 weeks), Mannick 2014 (5 mg PEARL-style intermittent dose), Kahan 2000 (5-15 ng/mL transplant trough) |
| **Topic pack + aliases** | ✅ pre-existing | `topic_packs/rapamycin.toml` |
| **Smoke-test of `--topic rapamycin` CLI** | ✅ verified | Exits with actionable error pointing at the missing `docs/quality-reference/rapamycin/quant_claims/` directory |
| **C1. Triage step (no LLM cost)** | ✅ done | `scripts/seed_rapamycin_corpus.py --triage` — 67 seed cards → 23 candidates after off-topic filter → 15 selected (5 pinned canonical NCTs + PEARL bubbled to top of unpinned ranking). Output: `docs/quality-reference/rapamycin/_triage.json`. Tests: `tests/test_seed_rapamycin_triage.py` (8 tests, gracefully skip on machines without local seed pool). |
| **C2. Extraction step (LLM cost ~$2-3)** | ⏸️ blocked on user approval | Extracts quant_claims + paper_sections for the 15 triaged papers. Detailed gate below. |
| **C3. Pipeline run (`--topic rapamycin`)** | ⏸️ blocked on C2 | Once C2 produces the corpus, the elite-grade pipeline runs unchanged. |

Once Workstream C is done, the elite-grade metformin pipeline runs unchanged on rapamycin via:

```
python scripts/run_v06_synthesis.py --topic rapamycin
```

## What Workstream C requires

The v0.6 pipeline reads two corpus structures:

```
docs/quality-reference/rapamycin/
  ├── quant_claims/
  │   ├── <paper_id>.quant_claims.json   (one per paper)
  │   └── ...
  └── parsed/
      ├── <paper_id>.paper_sections.json (one per paper)
      └── ...
```

Both files must exist for every paper in the corpus. For metformin we have 15 papers.

### Paper acquisition (~15 papers needed)

Already-curated assets in this repo:

- `tests/fixtures/rapamycin/` — `clinicaltrials.json`, `europepmc.json`, `openalex.json`, `pubmed.json` (registry/database fixtures from earlier pipeline)
- `runs/rapamycin-002-2026-04-28T19-03-28Z-4ab9/evidence_cards.json` — **67 evidence cards already retrieved** with abstract + design + role + tier from the OLD pipeline. This is the seed pool.

**Recommendation:** triage the 67 existing cards down to ~15 high-confidence canonical papers covering the slots the topic pack defines:

```
human_rcts                         (PEARL, Mannick 2014/2018, Kraig 2018, Konopka 2019-RAP)
human_observational                (large diabetes/transplant cohorts)
human_mechanism                    (RAD001 immune function, gene expression)
preclinical_lifespan               (Harrison 2009, ITP follow-ups)
safety_tolerability                (Mannick safety profiles, transplant data)
dosing_regimen                     (intermittent vs daily; PEARL design)
exercise_interaction               (rapamycin × exercise studies)
ongoing_trials                     (NCT04488601 PEARL, NCT04629495 Alzheimer's RAP)
transplant_indication_bias         (acknowledge confounding from transplant indication)
```

### Schema generation (~30 min per paper if scripted, ~10 hours total)

Each `paper_sections.json` needs:

```json
{
  "paper_id": "Author_YYYY_short_label",
  "doi": "10.x/y",
  "pmid": "...",
  "title": "...",
  "year": 2024,
  "venue": "...",
  "authors": [...],
  "abstract": "...",
  "introduction": "...",
  "methods": "...",
  "results": "...",
  "discussion": "..."
}
```

Each `quant_claims.json` needs:

```json
{
  "paper_id": "...",
  "doi": "...",
  "extracted_at": "...",
  "extractor_version": "v0.6.0",
  "claims_count_by_type": {"p_value": 5, "percentage": 8, ...},
  "claims": [
    {
      "claim_id": "Author_YYYY-msd-NNN",
      "claim_type": "p_value | percentage | unit_value | sample_size | mean_sd | ratio | ci",
      "raw_text": "p < 0.001",
      "numeric_values": [0.001],
      "units": "",
      "source_section": "results",
      "source_offset": 1234,
      "sentence": "...source-sentence context — used by Fix #37 change-value detection...",
      "endpoint": "muscle_function",
      "arm": "rapamycin",
      "direction": "positive",
      "binding_confidence": "high"
    },
    ...
  ]
}
```

Existing infra that can help:

- `agent/fact_extractor.py` — LLM-driven claim extraction (would need `--topic rapamycin` adapter)
- `scripts/pdf_ingest.py` — PDF → paper_sections (needs `fitz` / PyMuPDF)
- `scripts/quant_endpoints.py` + `scripts/vocab/rapamycin.py` — endpoint/vocab classification

### Three execution paths

**Path 1 — Full automation (~$2-5 in LLM costs, ~2 hours wall-clock)**
Build a `scripts/seed_rapamycin_corpus.py` that:
1. Reads the 67 evidence_cards from the prior run
2. Triages to top-15 by tier+role
3. For each: fetches full text (PMC/PubMed API), parses to paper_sections.json
4. Runs `agent/fact_extractor` to produce quant_claims.json
5. Validates each artifact against existing schema tests

Risk: LLM extraction quality varies; need spot-check.

**Path 2 — Hybrid (recommended)**
Auto-extract on the 15 papers, then human spot-checks the 5 highest-tier (RCT) papers' claim files for accuracy. ~30 min human review.

**Path 3 — Manual curation**
Hand-curate all 15 papers' claim files using the metformin examples as template. ~10-15 hours.

### Recommendation

**Path 2 (hybrid)**. Concrete next step:

```bash
# DONE — triage already ran. Inspect the output:
cat docs/quality-reference/rapamycin/_triage.json

# COST GATE — needs explicit user approval before running:
python scripts/seed_rapamycin_corpus.py --extract --top-n 15
# → writes docs/quality-reference/rapamycin/{quant_claims,parsed}/

# After extract, the pipeline runs unchanged:
python scripts/run_v06_synthesis.py --topic rapamycin
```

### Cost gate — what `--extract` will do

For each of the 15 triaged papers (output of C1), `--extract` will:

1. **Fetch full text** — try PMC OA → Europe PMC → fallback to abstract-only
2. **Parse to paper_sections.json** — split intro/methods/results/discussion (deterministic regex on heading patterns)
3. **Extract quant_claims** via `agent.fact_extractor` — LLM-driven; ~$0.10-0.20/paper at temperature 0.02
4. **Validate** against the metformin schema (existing tests in `tests/test_quant_claims_schema.py`)
5. **Write** to `docs/quality-reference/rapamycin/{quant_claims,parsed}/<paper_id>.{quant_claims,paper_sections}.json`

**Estimated cost**: $1.50-3.00 (15 papers × $0.10-0.20). Wall-clock ~30 min.

**Risk profile**: extraction quality varies; the metformin pipeline showed extractor-rate of ~80% high-confidence claims. Spot-check the top-5 RCT extractions (PEARL, Konopka, etc.) before running synthesis. The fact_extractor's `binding_confidence: high` filter does most of the quality control automatically.

**Why this is gated**: $2-3 is small but non-zero, and the user's CLAUDE.md doesn't list LLM extraction as a pre-authorized action. Run `--extract` only after user confirms.

## Estimated time-to-Proof-002-AAA

| Step | Time | Cost |
|---|---|---|
| Build `seed_rapamycin_corpus.py` (triage + extract) | 2-3 hours | $0 |
| Run extraction over 15 papers | 30 min | ~$2-3 |
| Human spot-check (top 5 RCTs) | 30 min | $0 |
| Run elite-grade synthesis pipeline | 5 min | ~$0.02 |
| Reproducibility run | 5 min | ~$0.02 |
| **Total to first AAA rapamycin artifact** | **~4 hours** | **~$2-3** |

Pipeline architecture is mature; this is now standard execution work, not architectural design.
