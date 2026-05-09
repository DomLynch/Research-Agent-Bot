# Topic Pack Generator v1

Status: local V1 slice. The generator can create, adapt, validate, and persist
generated topic-pack records. It does not yet run retrieval or full synthesis
for generated packs.

## Implemented

- `agent/topic_pack_generator.py`
  - deterministic generation from a free-text topic
  - tiering: `mainstream`, `adjacent`, `emerging`, `contested`, `pseudo`,
    `out_of_scope`
  - strict `proceed` / `stop` decision
  - pseudo and out-of-scope topics stop before retrieval
  - precursor expansion for known topic families
  - deterministic adaptive expansion from observed candidate counts
  - TOML-style dict compatible with current `TopicPack` fields
- `agent/topic_pack_store.py`
  - immutable JSON records in `topic_packs_db/<slug>/vN.json`
  - `latest.json` pointer per topic
  - `topic_pack_id`, version, hash, parent lineage, candidate count
  - stopped or invalid packs cannot persist
- `scripts/synthesize.py`
  - safe front door for topic-name submission
  - emits JSON status
  - optional `--persist` writes a generated-pack record
  - does not silently call full synthesis for generated topics

## CLI

```bash
python scripts/synthesize.py \
  --topic "vitamin K2 cardiovascular" \
  --candidate-count 20 \
  --candidate-count 80 \
  --persist
```

Output includes `status`, `slug`, `tier`, `topic_terms`,
`corpus_search_queries`, and, when persisted, `topic_pack_id`,
`topic_pack_version`, and `topic_pack_hash`.

## Still Gated

The generator can become an active V1 path only after these are true:

1. Every generated-pack run records `topic_pack_id`, `topic_pack_version`, and
   `topic_pack_hash`.
2. Existing curated TOML packs are imported as immutable version `1`.
3. Generated packs pass the same loader/schema checks as curated packs.
4. Dry-run retrieval benchmarking covers at least 25 known basket topics.
5. Generated packs cannot lower certification floors.
6. Generated packs cannot bypass audit, reviewer, journal-surface,
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
- If topic tier is `out_of_scope`, status must be `stop`.
- If candidate count remains thin, output may be SCOP/AAA-SCOP only after that
  track is separately wired and tested; never full AAA by default.

## Tests

- `tests/test_topic_pack_generator.py`
- `tests/test_topic_pack_store.py`
- `tests/test_synthesize_cli.py`

Fresh-topic coverage:

- vitamin K2 cardiovascular
- magnesium glycinate sleep
- alpha-lipoic acid neuropathy
- lithium orotate mood
- glycine sleep

## Open Risks

- Heuristic tiering may be too crude for public submissions.
- Candidate count alone can hide off-thesis retrieval.
- Generated aliases can over-broaden topics and inflate receipts.
- Activation needs provenance UI before user-submitted topics are safe.
- Full synthesis is intentionally not wired for generated packs until corpus
  and run-manifest provenance are pinned.
