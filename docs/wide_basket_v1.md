# Wide Basket V1

Read-only planning lane for expanding anti-aging topic coverage from local
topic packs and run artifacts.

## Build Queue

```bash
python scripts/wide_basket_queue.py \
  --json-out reports/wide_basket/queue.json \
  --markdown-out reports/wide_basket/queue.md
```

The script derives:

- topic-pack inventory from `topic_packs/*.toml`;
- run inventory from `runs/synthesis-*`;
- rich topics from run names containing `RICH`;
- next queue from topic packs without rich reruns;
- rich-vs-baseline deltas from latest rich run vs oldest acceptable non-rich
  baseline for the same topic.

## Status Rubric

- `ready`: topic pack has sufficient corpus queries and no local JS/Grok/thin
  corpus block on the latest run.
- `needs corpus tuning`: latest local run is JS/Grok/corpus-thin blocked, or the
  pack has too few corpus search queries.
- `needs-pack`: advisory only; not emitted into the queue JSON unless a topic
  pack exists.

## First Run Shape

```bash
python scripts/seed_topic_corpus.py --topic <topic> --max-per-source 25
python scripts/run_v06_synthesis.py --topic <topic> --dry-run
```

Remove `--dry-run` only after the dry path builds the expected receipts,
matrix, and thesis artifacts.

## Review Order

1. Read `reports/wide_basket/README.md`.
2. Inspect `reports/wide_basket/queue.json` for machine-readable ordering.
3. Run ready topics first.
4. Reseed `needs corpus tuning` topics before synthesis.
5. Run L6 confirmations only after latest rich runs remain L5.
