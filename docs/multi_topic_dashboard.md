# Researka Multi-Topic Dashboard

**Topics attempted:** 18
**Topics at L5 (Journal-Ready):** 0
**Topics with ≥1 AAA run:** 11
**Topics with consecutive-AAA cert:** 2
**Total runs across all topics:** 120
**Cumulative LLM cost:** $3.527
**Total reviewer interventions logged:** 166 applied (13 via repair loop)

## Per-Topic Status

| Topic | Maturity | Best verdict | Journal | n_runs | AAA | Stage1 | S2 P1/P2 | Q2 | Words | Cost |
|---|---|---|---|---|---|---|---|---|---|---|
| metformin | L4 — ANALYTICALLY CERTIFIED | AAA | — | 58 | 25 | 13/13 | 0/0 | 100% | 26,967 | $0.258 |
| acarbose | L4 — ANALYTICALLY CERTIFIED | AAA | — | 1 | 1 | 13/13 | 0/0 | 100% | 15,045 | $0.188 |
| caloric_restriction | L4 — ANALYTICALLY CERTIFIED | AAA | — | 1 | 1 | 13/13 | 0/0 | 100% | 12,583 | $0.156 |
| creatine | L4 — ANALYTICALLY CERTIFIED | AAA | — | 1 | 1 | 13/13 | 0/0 | 100% | 14,414 | $0.165 |
| glp1 | L4 — ANALYTICALLY CERTIFIED | AAA | — | 5 | 1 | 13/13 | 0/0 | 100% | 19,809 | $0.254 |
| intermittent_fasting | L4 — ANALYTICALLY CERTIFIED | AAA | — | 1 | 1 | 13/13 | 0/0 | 100% | 19,576 | $0.243 |
| protein_nutrition | L4 — ANALYTICALLY CERTIFIED | AAA | — | 2 | 1 | 13/13 | 0/0 | 100% | 57,960 | $0.540 |
| resistance_training | L4 — ANALYTICALLY CERTIFIED | AAA | — | 1 | 1 | 13/13 | 0/0 | 100% | 15,993 | $0.211 |
| rapamycin | L2 — PARTIAL | Trust-Spine Pass | — | 24 | 5 | 13/13 | 0/0 | 100% | 11,403 | $0.143 |
| statins | L2 — PARTIAL | Trust-Spine Pass | — | 12 | 1 | 11/13 | 0/0 | 100% | 8,716 | $0.122 |
| aerobic_exercise | L2 — PARTIAL | Trust-Spine Pass | — | 1 | 0 | 13/13 | 0/0 | 100% | 10,210 | $0.116 |
| berberine | L2 — PARTIAL | Trust-Spine Pass | — | 1 | 0 | 13/13 | 0/0 | 100% | 9,892 | $0.146 |
| nad_precursors | L2 — PARTIAL | Trust-Spine Pass | — | 1 | 0 | 13/13 | 0/0 | 100% | 8,559 | $0.136 |
| zone2_training | L2 — PARTIAL | Trust-Spine Pass | — | 1 | 0 | 13/13 | 0/0 | 100% | 10,066 | $0.152 |
| vitamin_d | L2 — PARTIAL | Trust-Spine Pass — Agent Review Unresolved | — | 1 | 0 | 12/13 | 0/0 | 100% | 9,806 | $0.122 |
| omega3 | L2 — PARTIAL | SHIP-BLOCKED | — | 1 | 0 | 10/13 | 1/1 | 100% | 8,308 | $0.159 |
| aspirin | L? — pre-Wave-7 | AAA | — | 7 | 1 | 13/13 | 0/0 | 100% | 7,553 | $0.236 |
| senolytics | L? — pre-Wave-7 | SHIP-BLOCKED | — | 1 | 0 | 10/13 | 1/0 | 100% | 6,462 | $0.178 |

## Best Run per Topic

### acarbose — L4 — ANALYTICALLY CERTIFIED

- **Best run:** `synthesis-acarbose-v06-ACTIVE-2026-05-05T22-49-00Z`
- **Verdict:** AAA
- **Journal-Ready:** no
- **Cert (consecutive-AAA gate):** pending
- **Stage-1 audit:** 13/13
- **Stage-2 consistency:** P1=0 P2=0
- **Q2 numeric traceability:** 100%
- **Reviewer unresolved P1:** 0
- **Word count:** 15,045
- **LLM cost:** $0.188
- **Patches applied:** 8 (0 via repair loop)
- **Next expansion targets** (from corpus_gaps):
  - **Outcome diversity: only 2 classes (cardiometabolic, immune); floor 3** → Broaden retrieval queries to capture complementary endpoints (additional outcome classes).
- **Corpus funnel** (retrieved → keep → core / background / adjacent): 2014 → 346 → 71 / 34 / 241

### caloric_restriction — L4 — ANALYTICALLY CERTIFIED

- **Best run:** `synthesis-caloric_restriction-v06-ACTIVE-2026-05-05T22-49-00Z`
- **Verdict:** AAA
- **Journal-Ready:** no
- **Cert (consecutive-AAA gate):** pending
- **Stage-1 audit:** 13/13
- **Stage-2 consistency:** P1=0 P2=0
- **Q2 numeric traceability:** 100%
- **Reviewer unresolved P1:** 0
- **Word count:** 12,583
- **LLM cost:** $0.156
- **Patches applied:** 7 (2 via repair loop)
- **Next expansion targets** (from corpus_gaps):
  - **Direct-evidence receipts: 0/2 (have only reviews/indirect/mechanistic)** → Add ≥2 direct trial/RCT receipts (ClinicalTrials.gov, pragmatic-trial queries).
  - **A-tier receipts: 1/2 (corpus leans on B/C tier)** → Add ≥1 A1/A2 sources (Cochrane review / large RCT / pragmatic trial).
- **Corpus funnel** (retrieved → keep → core / background / adjacent): 2660 → 1349 → 104 / 750 / 495

### creatine — L4 — ANALYTICALLY CERTIFIED

- **Best run:** `synthesis-creatine-v06-ACTIVE-2026-05-05T22-47-50Z`
- **Verdict:** AAA
- **Journal-Ready:** no
- **Cert (consecutive-AAA gate):** pending
- **Stage-1 audit:** 13/13
- **Stage-2 consistency:** P1=0 P2=0
- **Q2 numeric traceability:** 100%
- **Reviewer unresolved P1:** 0
- **Word count:** 14,414
- **LLM cost:** $0.165
- **Patches applied:** 15 (2 via repair loop)
- **Corpus funnel** (retrieved → keep → core / background / adjacent): 2381 → 456 → 35 / 90 / 331

### glp1 — L4 — ANALYTICALLY CERTIFIED

- **Best run:** `synthesis-glp1-v06-ACTIVE3-2026-05-05T22-18-50Z`
- **Verdict:** AAA
- **Journal-Ready:** no
- **Cert (consecutive-AAA gate):** pending
- **Stage-1 audit:** 13/13
- **Stage-2 consistency:** P1=0 P2=0
- **Q2 numeric traceability:** 100%
- **Reviewer unresolved P1:** 0
- **Word count:** 19,809
- **LLM cost:** $0.254
- **Patches applied:** 9 (1 via repair loop)
- **Corpus funnel** (retrieved → keep → core / background / adjacent): 3123 → 895 → 124 / 57 / 714

### intermittent_fasting — L4 — ANALYTICALLY CERTIFIED

- **Best run:** `synthesis-intermittent_fasting-v06-ACTIVE-2026-05-05T22-34-23Z`
- **Verdict:** AAA
- **Journal-Ready:** no
- **Cert (consecutive-AAA gate):** pending
- **Stage-1 audit:** 13/13
- **Stage-2 consistency:** P1=0 P2=0
- **Q2 numeric traceability:** 100%
- **Reviewer unresolved P1:** 0
- **Word count:** 19,576
- **LLM cost:** $0.243
- **Patches applied:** 8 (0 via repair loop)
- **Corpus funnel** (retrieved → keep → core / background / adjacent): 2490 → 777 → 216 / 155 / 406

### metformin — L4 — ANALYTICALLY CERTIFIED

- **Best run:** `synthesis-metformin-v06-CODEXFIX2-2026-05-05T22-30-00Z`
- **Verdict:** AAA
- **Journal-Ready:** no
- **Cert (consecutive-AAA gate):** PASS 🏆
- **Stage-1 audit:** 13/13
- **Stage-2 consistency:** P1=0 P2=0
- **Q2 numeric traceability:** 100%
- **Reviewer unresolved P1:** 0
- **Word count:** 26,967
- **LLM cost:** $0.258
- **Patches applied:** 22 (1 via repair loop)
- **Corpus funnel** (retrieved → keep → core / background / adjacent): 1962 → 378 → 146 / 232 / 0

### protein_nutrition — L4 — ANALYTICALLY CERTIFIED

- **Best run:** `synthesis-protein_nutrition-v06-FIXED-2026-05-05T23-37-32Z`
- **Verdict:** AAA
- **Journal-Ready:** no
- **Cert (consecutive-AAA gate):** pending
- **Stage-1 audit:** 13/13
- **Stage-2 consistency:** P1=0 P2=0
- **Q2 numeric traceability:** 100%
- **Reviewer unresolved P1:** 0
- **Word count:** 57,960
- **LLM cost:** $0.540
- **Patches applied:** 8 (0 via repair loop)
- **Corpus funnel** (retrieved → keep → core / background / adjacent): 2934 → 1773 → 122 / 435 / 1216

### resistance_training — L4 — ANALYTICALLY CERTIFIED

- **Best run:** `synthesis-resistance_training-v06-ACTIVE-2026-05-05T22-34-24Z`
- **Verdict:** AAA
- **Journal-Ready:** no
- **Cert (consecutive-AAA gate):** pending
- **Stage-1 audit:** 13/13
- **Stage-2 consistency:** P1=0 P2=0
- **Q2 numeric traceability:** 100%
- **Reviewer unresolved P1:** 0
- **Word count:** 15,993
- **LLM cost:** $0.211
- **Patches applied:** 7 (0 via repair loop)
- **Corpus funnel** (retrieved → keep → core / background / adjacent): 3044 → 1635 → 281 / 114 / 1240

### aerobic_exercise — L2 — PARTIAL

- **Best run:** `synthesis-aerobic_exercise-v06-DIAG-2026-05-05T23-06-41Z`
- **Verdict:** Trust-Spine Pass
- **Journal-Ready:** no
- **Cert (consecutive-AAA gate):** pending
- **Stage-1 audit:** 13/13
- **Stage-2 consistency:** P1=0 P2=0
- **Q2 numeric traceability:** 100%
- **Reviewer unresolved P1:** 0
- **Word count:** 10,210
- **LLM cost:** $0.116
- **Patches applied:** 5 (0 via repair loop)
- **Next expansion targets** (from corpus_gaps):
  - **Receipts: 5/10 (short by 5)** → Add ≥5 more topic-fit receipts via `scripts/seed_topic_corpus.py --topic <T> --max-papers 20`.
  - **High-confidence claims: 37/50 (short by 13)** → Re-run extraction on existing parsed papers and/or expand corpus; need ≥13 more bound numeric claims.
  - **Non-orthogonal tensions: 1/10 (short by 9)** → Add receipts that contradict or complicate existing findings; need ≥9 more cross-receipt tensions.
  - **Direct-evidence receipts: 0/2 (have only reviews/indirect/mechanistic)** → Add ≥2 direct trial/RCT receipts (ClinicalTrials.gov, pragmatic-trial queries).
  - **A-tier receipts: 0/2 (corpus leans on B/C tier)** → Add ≥2 A1/A2 sources (Cochrane review / large RCT / pragmatic trial).
- **Corpus funnel** (retrieved → keep → core / background / adjacent): 3146 → 569 → 105 / 24 / 440

### berberine — L2 — PARTIAL

- **Best run:** `synthesis-berberine-v06-DIAG-2026-05-05T22-55-51Z`
- **Verdict:** Trust-Spine Pass
- **Journal-Ready:** no
- **Cert (consecutive-AAA gate):** pending
- **Stage-1 audit:** 13/13
- **Stage-2 consistency:** P1=0 P2=0
- **Q2 numeric traceability:** 100%
- **Reviewer unresolved P1:** 0
- **Word count:** 9,892
- **LLM cost:** $0.146
- **Patches applied:** 10 (0 via repair loop)
- **Next expansion targets** (from corpus_gaps):
  - **Receipts: 8/10 (short by 2)** → Add ≥2 more topic-fit receipts via `scripts/seed_topic_corpus.py --topic <T> --max-papers 20`.
  - **Outcome diversity: only 2 classes (cardiometabolic, immune); floor 3** → Broaden retrieval queries to capture complementary endpoints (additional outcome classes).
- **Corpus funnel** (retrieved → keep → core / background / adjacent): 1839 → 469 → 40 / 256 / 173

### nad_precursors — L2 — PARTIAL

- **Best run:** `synthesis-nad_precursors-v06-DIAG-2026-05-05T23-06-41Z`
- **Verdict:** Trust-Spine Pass
- **Journal-Ready:** no
- **Cert (consecutive-AAA gate):** pending
- **Stage-1 audit:** 13/13
- **Stage-2 consistency:** P1=0 P2=0
- **Q2 numeric traceability:** 100%
- **Reviewer unresolved P1:** 0
- **Word count:** 8,559
- **LLM cost:** $0.136
- **Patches applied:** 15 (4 via repair loop)
- **Next expansion targets** (from corpus_gaps):
  - **Receipts: 6/10 (short by 4)** → Add ≥4 more topic-fit receipts via `scripts/seed_topic_corpus.py --topic <T> --max-papers 20`.
  - **High-confidence claims: 38/50 (short by 12)** → Re-run extraction on existing parsed papers and/or expand corpus; need ≥12 more bound numeric claims.
  - **Non-orthogonal tensions: 6/10 (short by 4)** → Add receipts that contradict or complicate existing findings; need ≥4 more cross-receipt tensions.
  - **Outcome diversity: only 2 classes (cardiometabolic, muscle_function); floor 3** → Broaden retrieval queries to capture complementary endpoints (additional outcome classes).
- **Corpus funnel** (retrieved → keep → core / background / adjacent): 2007 → 371 → 15 / 186 / 170

### rapamycin — L2 — PARTIAL

- **Best run:** `synthesis-rapamycin-v06-CALIBRATED-2026-05-05T19-30-00Z`
- **Verdict:** Trust-Spine Pass
- **Journal-Ready:** no
- **Cert (consecutive-AAA gate):** PASS 🏆
- **Stage-1 audit:** 13/13
- **Stage-2 consistency:** P1=0 P2=0
- **Q2 numeric traceability:** 100%
- **Reviewer unresolved P1:** 0
- **Word count:** 11,403
- **LLM cost:** $0.143
- **Patches applied:** 14 (3 via repair loop)
- **Next expansion targets** (from corpus_gaps):
  - **High-confidence claims: 49/50 (short by 1)** → Re-run extraction on existing parsed papers and/or expand corpus; need ≥1 more bound numeric claims.
  - **Outcome diversity: only 2 classes (cardiometabolic, longevity); floor 3** → Broaden retrieval queries to capture complementary endpoints (additional outcome classes).
- **Corpus funnel** (retrieved → keep → core / background / adjacent): 444 → 118 → 1 / 77 / 40

### statins — L2 — PARTIAL

- **Best run:** `synthesis-statins-v06-DIAG-2026-05-05T23-21-22Z`
- **Verdict:** Trust-Spine Pass
- **Journal-Ready:** no
- **Cert (consecutive-AAA gate):** pending
- **Stage-1 audit:** 11/13
- **Stage-2 consistency:** P1=0 P2=0
- **Q2 numeric traceability:** 100%
- **Reviewer unresolved P1:** 0
- **Word count:** 8,716
- **LLM cost:** $0.122
- **Patches applied:** 9 (0 via repair loop)
- **Next expansion targets** (from corpus_gaps):
  - **Receipts: 3/10 (short by 7)** → Add ≥7 more topic-fit receipts via `scripts/seed_topic_corpus.py --topic <T> --max-papers 28`.
  - **High-confidence claims: 49/50 (short by 1)** → Re-run extraction on existing parsed papers and/or expand corpus; need ≥1 more bound numeric claims.
  - **Non-orthogonal tensions: 3/10 (short by 7)** → Add receipts that contradict or complicate existing findings; need ≥7 more cross-receipt tensions.
  - **Outcome diversity: only 1 classes (longevity); floor 3** → Broaden retrieval queries to capture complementary endpoints (additional outcome classes).
  - **Direct-evidence receipts: 0/2 (have only reviews/indirect/mechanistic)** → Add ≥2 direct trial/RCT receipts (ClinicalTrials.gov, pragmatic-trial queries).
- **Corpus funnel** (retrieved → keep → core / background / adjacent): 2612 → 705 → 136 / 105 / 464

### zone2_training — L2 — PARTIAL

- **Best run:** `synthesis-zone2_training-v06-DIAG-2026-05-05T22-58-40Z`
- **Verdict:** Trust-Spine Pass
- **Journal-Ready:** no
- **Cert (consecutive-AAA gate):** pending
- **Stage-1 audit:** 13/13
- **Stage-2 consistency:** P1=0 P2=0
- **Q2 numeric traceability:** 100%
- **Reviewer unresolved P1:** 0
- **Word count:** 10,066
- **LLM cost:** $0.152
- **Patches applied:** 10 (0 via repair loop)
- **Next expansion targets** (from corpus_gaps):
  - **Receipts: 9/10 (short by 1)** → Add ≥1 more topic-fit receipts via `scripts/seed_topic_corpus.py --topic <T> --max-papers 20`.
  - **Outcome diversity: only 2 classes (cardiometabolic, muscle_function); floor 3** → Broaden retrieval queries to capture complementary endpoints (additional outcome classes).
  - **Direct-evidence receipts: 1/2 (have only reviews/indirect/mechanistic)** → Add ≥1 direct trial/RCT receipts (ClinicalTrials.gov, pragmatic-trial queries).
  - **A-tier receipts: 1/2 (corpus leans on B/C tier)** → Add ≥1 A1/A2 sources (Cochrane review / large RCT / pragmatic trial).
- **Corpus funnel** (retrieved → keep → core / background / adjacent): 2079 → 401 → 86 / 66 / 249

### vitamin_d — L2 — PARTIAL

- **Best run:** `synthesis-vitamin_d-v06-DIAG-2026-05-05T23-22-44Z`
- **Verdict:** Trust-Spine Pass — Agent Review Unresolved
- **Journal-Ready:** no
- **Cert (consecutive-AAA gate):** pending
- **Stage-1 audit:** 12/13
- **Stage-2 consistency:** P1=0 P2=0
- **Q2 numeric traceability:** 100%
- **Reviewer unresolved P1:** 3
- **Word count:** 9,806
- **LLM cost:** $0.122
- **Patches applied:** 4 (0 via repair loop)
- **Next expansion targets** (from corpus_gaps):
  - **Receipts: 2/10 (short by 8)** → Add ≥8 more topic-fit receipts via `scripts/seed_topic_corpus.py --topic <T> --max-papers 32`.
  - **High-confidence claims: 28/50 (short by 22)** → Re-run extraction on existing parsed papers and/or expand corpus; need ≥22 more bound numeric claims.
  - **Non-orthogonal tensions: 0/10 (short by 10)** → Add receipts that contradict or complicate existing findings; need ≥10 more cross-receipt tensions.
  - **Outcome diversity: only 2 classes (immune, longevity); floor 3** → Broaden retrieval queries to capture complementary endpoints (additional outcome classes).
  - **Direct-evidence receipts: 1/2 (have only reviews/indirect/mechanistic)** → Add ≥1 direct trial/RCT receipts (ClinicalTrials.gov, pragmatic-trial queries).
- **Corpus funnel** (retrieved → keep → core / background / adjacent): 2771 → 667 → 126 / 49 / 492

### omega3 — L2 — PARTIAL

- **Best run:** `synthesis-omega3-v06-DIAG-2026-05-05T23-22-44Z`
- **Verdict:** SHIP-BLOCKED
- **Journal-Ready:** no
- **Cert (consecutive-AAA gate):** pending
- **Stage-1 audit:** 10/13
- **Stage-2 consistency:** P1=1 P2=1
- **Q2 numeric traceability:** 100%
- **Reviewer unresolved P1:** 0
- **Word count:** 8,308
- **LLM cost:** $0.159
- **Patches applied:** 8 (0 via repair loop)
- **Next expansion targets** (from corpus_gaps):
  - **Receipts: 2/10 (short by 8)** → Add ≥8 more topic-fit receipts via `scripts/seed_topic_corpus.py --topic <T> --max-papers 32`.
  - **High-confidence claims: 7/50 (short by 43)** → Re-run extraction on existing parsed papers and/or expand corpus; need ≥43 more bound numeric claims.
  - **Non-orthogonal tensions: 0/10 (short by 10)** → Add receipts that contradict or complicate existing findings; need ≥10 more cross-receipt tensions.
  - **Outcome diversity: only 2 classes (cardiometabolic, longevity); floor 3** → Broaden retrieval queries to capture complementary endpoints (additional outcome classes).
  - **Direct-evidence receipts: 0/2 (have only reviews/indirect/mechanistic)** → Add ≥2 direct trial/RCT receipts (ClinicalTrials.gov, pragmatic-trial queries).
- **Corpus funnel** (retrieved → keep → core / background / adjacent): 3080 → 732 → 71 / 151 / 510

### aspirin — L? — pre-Wave-7

- **Best run:** `synthesis-aspirin-v06-AAA4-2026-05-04T17-30-00Z`
- **Verdict:** AAA
- **Journal-Ready:** no
- **Cert (consecutive-AAA gate):** pending
- **Stage-1 audit:** 13/13
- **Stage-2 consistency:** P1=0 P2=0
- **Q2 numeric traceability:** 100%
- **Reviewer unresolved P1:** 0
- **Word count:** 7,553
- **LLM cost:** $0.236
- **Patches applied:** 4 (0 via repair loop)
- **Corpus funnel** (retrieved → keep → core / background / adjacent): 3128 → 339 → 153 / 12 / 174

### senolytics — L? — pre-Wave-7

- **Best run:** `synthesis-senolytics-v06-proof005-2026-05-04T12-17-51Z`
- **Verdict:** SHIP-BLOCKED
- **Journal-Ready:** no
- **Cert (consecutive-AAA gate):** pending
- **Stage-1 audit:** 10/13
- **Stage-2 consistency:** P1=1 P2=0
- **Q2 numeric traceability:** 100%
- **Reviewer unresolved P1:** 1
- **Word count:** 6,462
- **LLM cost:** $0.178
- **Patches applied:** 3 (0 via repair loop)
- **Corpus funnel** (retrieved → keep → core / background / adjacent): 2946 → 274 → 10 / 118 / 146

## What this dashboard demonstrates

Each topic is a separate test of the Researka generic pipeline. **No Python code differs between topics** — the only difference is `topic_packs/<topic>.toml` and the auto-discovered corpus from `scripts/seed_topic_corpus.py --topic <X>`. A topic that hits AAA via the same code path that other topics use is structural evidence of architecture portability, not topic-tuned overfitting.

Per-run public bundles live in `bundles/<run-id>/` (18-file inspectable archive: paper + audit + cert + patch trail + manifest + composed README). Drop-in to OSF / Zenodo / GitHub Pages for public release.

Trust-spine principle: **LLM proposes, code disposes.** Every claim, citation, and numeric in every paper traces to the source corpus AND survives an adversarial review pass with logged interventions.
