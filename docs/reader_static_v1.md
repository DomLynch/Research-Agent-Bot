# Static Reader Scaffold v1

This is a read-only scaffold for local run artifacts. It is not the full
researka.io reader or public site.

## Basket Stability Matrix

`scripts/basket_stability_matrix.py` reads run directories and emits CSV or
JSON rows with topic, maturity, receipt count, tension count, verdict, Grok
flags, auto-strips, JavaScript check status, and quarantine counts.

It never writes into run directories.

## Static Reader Export

`scripts/export_static_reader.py` accepts either a run directory or a
`researka_reader_manifest.json` file and writes static `index.html` plus a
minimal `versions.html` scaffold. It is separate from Decentralized Web export
and does not publish, deploy, register, or mutate bundles.

The reader uses only the Python standard library. It renders a safe minimal
Markdown subset, escapes HTML, blocks absolute/scheme/traversal links, emits a
trust panel from local verdict/certification/audit files, and includes JSON-LD
citation metadata when manifest fields exist.

Framework, styling, routing, hosting, search, and researka.io integration are
deferred.
