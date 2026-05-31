# v3 Curated Examples

This folder is intentionally small. Public examples should be copied here only
after a run has:

- `full_paper.md` with no platform wrapper or compiler-dump lead-in;
- `paper_ir.json`, `paper_quality_score.json`, and `public_export_manifest.json`;
- `structured_evidence_tables.md` as supplement, not main-manuscript dump;
- `references.bib`, `evidence_table.csv`, `contradiction_map.json`, and DOCX/PDF
  exports where available;
- Researka accept/review proof stored outside the manuscript body.

Do not bulk-commit generated `runs/` output. Keep at most 2-3 polished examples
here, each with a short README explaining why it is representative.

Use `scripts/curate_v3_examples.py --runs-dir runs --out-dir examples/v3` to
copy only runs that already have PaperIR, export manifest, and quality-score
sidecars.
