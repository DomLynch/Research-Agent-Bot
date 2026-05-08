# Run Bundle Inventory

`build_run_bundle_report()` checks source run directories before reader export.
Minimum metadata for public reader export:

- topic
- title or thesis
- generated date
- `full_paper.md`
- `full_paper.audit.json`
- audit P1 pass
- receipt count
- tension count
- final verdict
- certification

This is a pre-export inventory only. It does not publish, mutate, or verify DW
state.
