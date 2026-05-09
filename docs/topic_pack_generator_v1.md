# Topic Pack Generator v1 Activation Requirements

Status: activation spec. Current implementation is dry-run only:
`agent/topic_pack_generator.py`. Background design is in
`docs/topic_pack_generation_v1.md`.

## Current Scaffold

Implemented today:

- deterministic tiering: `mainstream`, `adjacent`, `emerging`, `contested`,
  `pseudo`
- strict `proceed` / `stop` status
- pseudo topics stop before retrieval
- generated TOML-style dict compatible with current `TopicPack` fields
- pure adaptive expansion over observed retrieval counts
- no writes to `topic_packs/`
- no DB writes
- no retrieval, LLM, synthesis, or public API integration

## V1 Activation Gate

The generator can become an active V1 path only after these are true:

1. Generated packs are persisted as versioned records, not silent TOML edits.
2. Every run records `topic_pack_id`, `topic_pack_version`, and
   `topic_pack_hash`.
3. Existing curated TOML packs are imported as immutable version `1`.
4. Generated packs pass the same loader/schema checks as curated packs.
5. Dry-run retrieval benchmarking covers at least 25 known basket topics.
6. Pseudo/out-of-scope topics fail closed before retrieval.
7. Generated packs cannot lower certification floors.
8. Generated packs cannot bypass audit, reviewer, journal-surface,
   arbitration, maturity, or L6 gates.

## Required Benchmarks

Before live use:

- >=80% of generated known-topic packs match or improve current receipt count
  without increasing off-thesis rate.
- No pseudo-topic false proceed in the adversarial test set.
- No species hard filter unless explicitly approved in the persisted pack.
- No overwrite of an existing curated pack.
- Retune creates a new version and leaves old run provenance pinned.

## Runtime Integration Sequence

1. Add a read-only CLI that prints candidate pack JSON.
2. Add retrieval dry-run mode that reports candidates, kept papers, extracted
   papers, high-binding claims, and projected receipt count.
3. Add DB persistence behind an explicit flag.
4. Add a run flag that accepts `topic_pack_id` and refuses mutable input.
5. Add dashboard labels for generated-pack runs.
6. Add retune nomination reports from repeated L2/L3/thin outcomes.
7. Add public submission API only after local benchmarks pass.

## Machine-Readable Fields

Persisted pack record:

- `topic_pack_id`
- `topic_name`
- `version`
- `tier`
- `status`
- `pack_data`
- `pack_hash`
- `generated_by`
- `validated_at`
- `candidate_count`
- `parent_id`
- `source_path` for imported TOML packs
- `source_git_sha`

Run manifest additions:

- `topic_pack_id`
- `topic_pack_version`
- `topic_pack_hash`
- `topic_pack_generated`
- `topic_pack_parent_id`

## Fail-Closed Rules

- If pack validation fails, do not retrieve.
- If generated pack provenance is missing, do not synthesize.
- If a generated pack is retuned, old runs stay pinned to the old hash.
- If topic tier is `pseudo`, status must be `stop`.
- If candidate count remains thin, output may be SCOP/AAA-SCOP only after that
  track is separately wired and tested; never full AAA by default.

## Tests To Add Before Activation

- CLI emits stable JSON for fixed inputs.
- Generated pack imports through the same loader as TOML.
- DB versioning refuses duplicate `(topic_name, version)`.
- Run manifest pins pack identity and hash.
- Pack retune creates version `n+1` without mutating `n`.
- Generated pack cannot reduce global cert floors.
- Pseudo and contested examples fail or disclose as specified.

## Open Risks

- Heuristic tiering may be too crude for public submissions.
- Candidate count alone can hide off-thesis retrieval.
- Generated aliases can over-broaden topics and inflate receipts.
- Activation needs provenance UI before user-submitted topics are safe.
