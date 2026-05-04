# Researka Multi-Topic Dashboard

**Topics attempted:** 5
**Topics with ≥1 AAA run:** 2
**Topics with consecutive-AAA cert:** 2
**Total runs across all topics:** 77
**Cumulative LLM cost:** $1.340
**Total reviewer interventions logged:** 55 applied (1 via repair loop)

## Per-Topic Status

| Topic | Best verdict | Cert | n_runs | AAA-runs | Stage1 | Stage2 P1/P2 | Q2 trace | Words | Cost |
|---|---|---|---|---|---|---|---|---|---|
| metformin | AAA | 🏆 | 47 | 21 | 13/13 | 0/0 | 100% | 12,487 | $0.361 |
| rapamycin | AAA | 🏆 | 20 | 5 | 13/13 | 0/0 | 100% | 9,002 | $0.306 |
| statins | Trust-Spine Pass | — | 7 | 0 | 12/13 | 0/0 | 100% | 10,127 | $0.226 |
| glp1 | SHIP-BLOCKED | — | 2 | 0 | 8/13 | 0/0 | 100% | 4,732 | $0.269 |
| senolytics | SHIP-BLOCKED | — | 1 | 0 | 10/13 | 1/0 | 100% | 6,462 | $0.178 |

## Best Run per Topic

### metformin

- **Best run:** `synthesis-metformin-v06-AAA2-2026-05-04T15-22-03Z`
- **Verdict:** AAA
- **Cert (consecutive-AAA gate):** PASS 🏆
- **Stage-1 audit:** 13/13
- **Stage-2 consistency:** P1=0 P2=0
- **Q2 numeric traceability:** 100%
- **Grok unresolved P1:** 0
- **Word count:** 12,487
- **LLM cost:** $0.361
- **Patches applied:** 19 (0 via repair loop)

### rapamycin

- **Best run:** `synthesis-rapamycin-v06-AAA4-2026-05-04T15-50-14Z`
- **Verdict:** AAA
- **Cert (consecutive-AAA gate):** PASS 🏆
- **Stage-1 audit:** 13/13
- **Stage-2 consistency:** P1=0 P2=0
- **Q2 numeric traceability:** 100%
- **Grok unresolved P1:** 0
- **Word count:** 9,002
- **LLM cost:** $0.306
- **Patches applied:** 8 (0 via repair loop)

### statins

- **Best run:** `synthesis-statins-v06-FINAL-2026-05-04T14-38-15Z`
- **Verdict:** Trust-Spine Pass
- **Cert (consecutive-AAA gate):** pending
- **Stage-1 audit:** 12/13
- **Stage-2 consistency:** P1=0 P2=0
- **Q2 numeric traceability:** 100%
- **Grok unresolved P1:** 0
- **Word count:** 10,127
- **LLM cost:** $0.226
- **Patches applied:** 12 (0 via repair loop)

### glp1

- **Best run:** `synthesis-glp1-v06-proof004-2026-05-04T12-04-29Z`
- **Verdict:** SHIP-BLOCKED
- **Cert (consecutive-AAA gate):** pending
- **Stage-1 audit:** 8/13
- **Stage-2 consistency:** P1=0 P2=0
- **Q2 numeric traceability:** 100%
- **Grok unresolved P1:** 0
- **Word count:** 4,732
- **LLM cost:** $0.269
- **Patches applied:** 13 (1 via repair loop)

### senolytics

- **Best run:** `synthesis-senolytics-v06-proof005-2026-05-04T12-17-51Z`
- **Verdict:** SHIP-BLOCKED
- **Cert (consecutive-AAA gate):** pending
- **Stage-1 audit:** 10/13
- **Stage-2 consistency:** P1=1 P2=0
- **Q2 numeric traceability:** 100%
- **Grok unresolved P1:** 1
- **Word count:** 6,462
- **LLM cost:** $0.178
- **Patches applied:** 3 (0 via repair loop)

## What this dashboard demonstrates

Each topic is a separate test of the Researka generic pipeline. **No Python code differs between topics** — the only difference is `topic_packs/<topic>.toml` and the auto-discovered corpus from `scripts/seed_topic_corpus.py --topic <X>`. A topic that hits AAA via the same code path that other topics use is structural evidence of architecture portability, not topic-tuned overfitting.

Per-run public bundles live in `bundles/<run-id>/` (18-file inspectable archive: paper + audit + cert + patch trail + manifest + composed README). Drop-in to OSF / Zenodo / GitHub Pages for public release.

Trust-spine principle: **LLM proposes, code disposes.** Every claim, citation, and numeric in every paper traces to the source corpus AND survives an adversarial review pass with logged interventions.
