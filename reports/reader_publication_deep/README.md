# Deep Reader Publication Report

Generated from the existing static reader exports with:

```bash
.venv/bin/python scripts/reader_publication_deep_report.py reports/reader_publication/static reports/reader_publication_deep
```

The source static export directory is not part of this lane's write scope; this
directory keeps only the captured deep-readiness report.

## Result

Foundation-safe candidates:

- `synthesis-caloric_restriction-v06-PATH2RICHFIX2-2026-05-08T15-10-00Z`
- `synthesis-glp1-v06-CONTRIBFIX-2026-05-08T01-22-44Z`
- `synthesis-omega3-v06-PATH2RICHFIX2-2026-05-08T14-00-00Z`
- `synthesis-rapamycin-v06-PATH2RICHFIX3-2026-05-08TCLASSIFIER`

No export is v2-public-ready yet. All six are missing citation exports, bundle
hash manifests, topic indexes, and true version indexes. Metformin and statins
are additionally blocked by audit P1 failure.

## Next Slice

Implement a bundle-manifest/citation-export generator, then topic/version index
generation. Keep DW and OSF verification separate.
