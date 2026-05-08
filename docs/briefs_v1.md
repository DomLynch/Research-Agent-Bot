# BRIEFS V1

Focused briefs are deterministic slices of a certified run manifest.

`scripts/generate_brief.py` writes a five-file bundle:

- `brief.md`
- `brief.audit.json`
- `brief.citations.json`
- `brief.provenance.json`
- `numeric_quarantine.json`

Hardening rules:

- Receipts are filtered before rendering.
- Rendered citation tokens must be a subset of the filtered receipts.
- Provenance records the source run, source manifest hash, optional citation registry hash, filtered receipt IDs, and citation whitelist.
- If the source run has `numeric_quarantine.json` or `numeric_claim_quarantine.json`, its list or `items` list is copied into a typed brief sidecar. Missing quarantine input preserves the legacy empty-list sidecar. Malformed quarantine input fails closed.

No live LLM call is made by BRIEFS V1 generation.
