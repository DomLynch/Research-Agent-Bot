# Researka Certified A2A-AAA (single-run pending consecutive)

**Run ID:** `synthesis-metformin-v06-AAA2-2026-05-04T15-22-03Z`
**Git SHA:** `faea18c`
**Certified at:** 2026-05-04T15:33:43Z
**Final verdict:** AAA

## Trust-Spine Criteria

- AAA verdict: ✅
- Q2 numeric traceability: 100.0% (✅)
- Stage-1 audit: 13/13
- Stage-2 consistency: P1=0 P2=0 (✅)
- Grok unresolved P1: 0 (✅)
- No-regression gate: PASS ✅
- Old-defect scan: CLEAN ✅

## Public Error Surface (Patch Trail)

- Patches applied: 19
- Patches repaired (via repair loop): 0
- Patches auto-stripped (smart-gate fallback): 0
- Patches rejected: 0
- Patches flagged for manual review: 2

Every reviewer intervention is logged. Inspect `full_paper.review_patches.json` for the full trail.

## Run Metadata

- Word count: 12487
- Cost (USD): $0.3609

### Model Stack

- extractor: `MiMo-VL-7B-RL-2508`
- reviewer: `Grok-4.3-Reasoning`
- writer: `MiMo-VL-7B-RL-2508`

## What This Certification Means

This is a single-run cert. The full Researka A2A-AAA seal requires ≥2 consecutive AAA runs (run `scripts/certification_report.py --consecutive run1 run2`). The trust-spine architecture (LLM proposes, code disposes) ensures that every claim, citation, and numeric in this paper traces to the source corpus AND survives an adversarial review pass with logged interventions.

## What This Certification Does NOT Mean

- This is NOT a peer-reviewed publication.
- This is NOT a definitive review of the topic.
- This IS a demonstration that an autonomous agent-to-agent pipeline can produce a traceable, reviewer-constrained synthesis whose error surface is publicly inspectable.
