# Research Agent Bot

Research Agent Bot is an audited biomedical evidence-synthesis engine. It is
not a generic drafting demo: retrieval, source admission, claim extraction,
manuscript compilation, and publish gates are separate stages with sidecar
artifacts for review.

## Pipeline

```text
topic pack
  -> source retrieval and corpus seeding
  -> source admission and evidence-tier classification
  -> claim cards, citation registry, and tension matrix
  -> v3 synthesis compiler
  -> public manuscript plus supplemental evidence tables
  -> deterministic surface, audit, and pre-submit gates
  -> Researka submission
```

## Outputs

- `full_paper.md` - reader-facing manuscript. It should contain prose, compact
  evidence snapshots, references, and no raw compiler dumps.
- `structured_evidence_tables.md` - supplemental evidence tables and full
  evidence-map detail.
- `manifest.json`, `claim_graph.json`, `citation_registry.json`, and audit
  sidecars - machine-readable trust-spine artifacts.
- Optional polish outputs - Typst PDF, sciwrite-lint report, and offline eval
  JSON when those tools are installed.

## Trust Spine

```text
LLM PROPOSES. CODE DISPOSES.
```

LLMs may draft and revise prose. Deterministic code owns evidence admission,
categorical labels, source-traced numerics, maturity status, and submit
eligibility. Markdown is a rendering target, not the source of truth.

## Local Checks

```bash
.venv/bin/python -m ruff check agent scripts tests
.venv/bin/python -m mypy --no-incremental --explicit-package-bases --ignore-missing-imports scripts/run_v06_synthesis.py scripts/table_renderer.py agent/journal_surface_gate.py
.venv/bin/python -m pytest -q
```

## Deployment

The live bot runs from `/opt/research-agent-bot` on the VPS. Deploy only from a
clean tree, fast-forward both VPS checkouts, then verify the service and HTTP
status endpoint.
