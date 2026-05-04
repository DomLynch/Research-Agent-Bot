# Researka Public Bundle — synthesis-metformin-v06-fix54-verify2-2026-05-04T09-38-22Z

**Status:** AAA
**Final verdict:** AAA
**Bundled at:** 2026-05-04T09:57:08Z
**Git SHA:** `274648e`

## What's in this bundle

Every artifact the pipeline produced for this run, in a self-contained directory. No external dependencies; everything you need to audit the manuscript is here.

## Layout

| File | Purpose |
|---|---|
| `paper.md` | The manuscript |
| `certification.md` | Researka A2A-AAA cert + dissent log |
| `final_verdict.md` | Unified pipeline verdict |
| `audit.md` | Stage-1 quantitative audit (Q1-Q13) |
| `consistency.md` | Stage-2 consistency check (C01-C14) |
| `no_regression_report.md` | Diff vs prior baseline |
| `patches.json` | Full Grok review patch list (raw) |
| `patch_log.json` | Orchestrator decisions per patch |
| `fix_log.json` | Deterministic auto-fix interventions |
| `citation_registry.json` | Every citation with traceback |
| `manifest.json` | Run metadata (corpus, costs, etc.) |

## Run-level summary

- Receipts: 15
- High-confidence claims: 134
- Non-orthogonal tensions: 42
- No-regression vs baseline: PASS

## How to verify

1. Read `certification.md` for the A2A-AAA gate result.
2. Read `audit.md` for Q1-Q13 quantitative checks (numeric traceability, citation coverage, depth floors, etc.).
3. Read `consistency.md` for C01-C14 surface integrity checks (no duplicate sections, no internal labels, no change-value misreads, etc.).
4. Read `patches.json` + `patch_log.json` for the full reviewer-intervention trail. Every change to the paper after initial render is logged.
5. Cross-check `citation_registry.json` against the manuscript's `## References` block — every claim cites a registry entry; every entry resolves to a corpus paper.

## Researka manifesto note

This bundle is the **public error surface**: every intervention, every patch, every audit decision is here for inspection. If you find an error not surfaced by the audit/cert artifacts, that is a bug in the trust-spine and we want to know.

Trust-spine principle: **LLM proposes, code disposes.** Every claim, citation, and numeric traces to source via deterministic registries; every reviewer suggestion is gate-checked before application.
