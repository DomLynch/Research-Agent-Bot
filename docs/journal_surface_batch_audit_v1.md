# Journal Surface Batch Audit v1

Read-only batch QA for public manuscript surfaces.

## Command

```bash
python scripts/journal_surface_batch_audit.py RUN_DIR [RUN_DIR ...] \
  --json-out journal_surface_audit.json \
  --csv-out journal_surface_audit.csv \
  --md-out journal_surface_audit.md
```

If `--json-out` is omitted, JSON is printed to stdout. Exit code is `0` only
when every run passes.

## Scope

The CLI reads `full_paper.md`, `paper.md`, or `paper_synthesis.md` from each run
directory. It does not edit manuscripts, run dirs, manifests, or bundles.

Only the public manuscript body is scanned. The body ends before these headings:

- `## Publication Appendix`
- `## Researka Submitter Block`
- `## Researka Submission Block`
- `## Data and Code Availability`
- `## Search Provenance`
- `## AI Disclosure`
- `## Accountability`
- `## References`

## Checks

- forbidden audit/meta/template phrases in the public body
- deterministic backfill and fallback prose leaks
- duplicate long paragraphs by token overlap
- citation artifact tokens such as placeholder refs
- malformed public QEI rows
- standalone hedge fragments

## Outputs

JSON is the canonical output and includes schema, pass status, run count, issue
count, and per-run issues. CSV is one row per issue. Markdown is a compact human
summary for review notes.

This audit has no network behavior and no credential inputs.
