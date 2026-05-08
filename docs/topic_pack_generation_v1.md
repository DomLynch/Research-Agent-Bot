# Generated Topic Packs v1

Status: next-sprint specification. Do not replace file-backed topic packs inside
the current 72-task stabilization sprint.

## Goal

Generate a validated topic pack from a user-supplied topic name, persist the
pack as a versioned record, run synthesis against that exact version, and feed
run outcomes back into future pack tuning.

## Non-Goals

- No topic-specific Python.
- No silent overwrite of existing TOML packs.
- No public multi-tenant API until generation quality is benchmarked.
- No L5 inflation from generated packs; normal verdict gates still apply.

## Layer 1 — Generator

Input: `topic_name`.

Output: `GeneratedTopicPack`.

Required steps:

1. Classify domain and topic tier: `mainstream`, `adjacent`, `emerging`,
   `contested`, or `pseudo`.
2. Reject out-of-scope or pseudoscientific topics before retrieval.
3. Draft aliases, topic terms, scope terms, exclusion terms, active/placebo arm
   synonyms, and known landmark trials where applicable.
4. Run retrieval dry-run across the configured biomedical sources.
5. If unique candidates are below floor, ask the generator for additional terms
   based only on observed retrieval misses; retry up to three rounds.
6. If still thin, mark `thin_but_plausible=true` and proceed with stricter
   certification disclosure.

## Layer 2 — Persistence

Use DB records, not new TOML files, for generated packs.

```sql
CREATE TABLE topic_packs (
    id uuid PRIMARY KEY,
    topic_name text NOT NULL,
    version integer NOT NULL,
    domain text NOT NULL,
    tier text NOT NULL,
    pack_data jsonb NOT NULL,
    parent_id uuid REFERENCES topic_packs(id),
    generated_by text NOT NULL,
    validated_at timestamptz NOT NULL,
    candidate_count integer NOT NULL,
    UNIQUE(topic_name, version)
);
```

Every synthesis run records `topic_pack_id`, `topic_pack_version`, and
`topic_pack_hash`.

## Layer 3 — Migration

One-shot importer:

1. Read each existing `topic_packs/*.toml` except `_biomedical_default.toml`.
2. Validate against the current topic-pack loader.
3. Persist as version `1`.
4. Record source path and Git commit in metadata.
5. Do not delete TOML packs until generated-pack parity is demonstrated.

## Layer 4 — Continuous Tuning

After each run, record:

- receipt count
- claim count
- tension count
- verdict and maturity level
- quarantine counts
- reviewer flags
- journal-surface status
- cost and run duration

Trigger a pack-retune nomination when a topic has repeated L2/L3/SHIP-BLOCKED
outcomes, thin retrieval despite plausible literature, or excessive quarantine
rate. Retuning produces a new version; old runs remain pinned to old versions.

## Layer 5 — Public Submission API

V1 API shape:

```http
POST /api/topics
```

```json
{
  "topic_name": "vitamin K2 cardiovascular aging",
  "submitter_orcid": "0000-0000-0000-0000"
}
```

Response:

```json
{
  "topic_pack_id": "uuid",
  "status": "queued",
  "tier": "adjacent",
  "candidate_count": 72
}
```

Rate-limit by authenticated submitter. Contested topics must carry explicit
disclosure in generated manuscripts.

## Acceptance Tests

- Import current TOML packs to DB without changing run behavior.
- Generate 25 known basket packs from names; at least 80% match or improve
  receipt counts versus current TOML packs.
- Reject pseudoscientific and out-of-domain topics deterministically.
- Preserve provenance: every generated paper names the exact pack version used.
- Retune creates version `n+1` without mutating version `n`.
- Generated packs cannot bypass audit, review, journal-surface, or maturity
  gates.
