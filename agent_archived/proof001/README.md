# agent_archived/proof001/ — V1.1 LLM-coupled spine (frozen 2026-04-27)

**Status:** archived for git archaeology. **Do NOT import from this directory.** New code in `agent/` must use only the deterministic spine + Proof 001 modules.

## What's here

This directory preserves the 6 LLM-coupled modules (and 3 test files) that V1.1 shipped on 2026-04-26 (commit `89ee064`, tagged `v1.1-final`). They were archived during Day 0 of the Proof 001 rebuild because the architecture put LLMs inside the trust spine — the bug class V1.1 could not close without restructuring.

```
agent_archived/proof001/
├── README.md                ← this file
├── agent/
│   ├── relevance.py         ← LLM #1: directness override
│   ├── llm.py               ← LLM #2: writer (MiMo 2.5 Pro)
│   ├── judge.py             ← LLM #3: post-write adjudicator
│   ├── draft.py             ← orchestrator that wired the 3 LLMs
│   ├── qa.py                ← LLM-coupled QA gates
│   └── app.py               ← CLI + dashboard built on draft.py
└── tests/
    ├── test_judge.py
    ├── test_draft.py
    └── test_qa.py
```

## Why archived, not deleted

Per v4 Vibe Coding Playbook Rule 58 ("Separate experimental from core"). These modules represent ~38 tests of behavioral specifications, plus the prompt engineering that produced V1.1's $0.002–0.005/run cost target. Future work may reference:
- Prompt construction patterns for hyper-critical judging.
- Relevance-classifier directness override logic (replaced by topic-anchor gate + registry overrides in Proof 001).
- Three-tier LLM fallback chain implementations (MiMo → Mistral → Gemma).

If a Proof 001 module needs to mimic a V1.1 behavior, look here first; do not re-derive.

## Why this code was the wrong shape

See [`FAILURES/research-agent-v1.md`](../../FAILURES/research-agent-v1.md) for the full post-mortem. Three structural issues:

1. **Categorical decisions routed through LLMs.** Role classification, fact identity, and final adjudication should be deterministic table lookups or pure-code rules, not model judgments.
2. **Markdown was the source of truth.** Prose was both the artifact and the database. Proof 001 inverts this — `claim_graph.json` is canonical; markdown is the rendering.
3. **Each fix treated symptoms.** 3-tier fallback chains, hyper-critical judge prompts, judge re-runs after revision — all shipped, all helped, none solved. The bug class needed a different pipeline shape, not more validators.

## Replacement modules in Proof 001

| Archived | Replaced by | Notes |
|---|---|---|
| `relevance.py` | `evidence_cards.py` topic-anchor gate + `registry_overrides.py` | LLM directness override is gone; code disposes |
| `llm.py` | `compiler.py` LLM extraction stage + claim-graph guard | LLM proposes facts; cannot add claims to paper |
| `judge.py` | `spar.py` (3 role-bound agents + tie-breaking + dissent) | Single-LLM judging replaced by maker/judge separation |
| `draft.py` | `compiler.py` + `render.py` (gutted) | Orchestrator splits into deterministic compile + pure rendering |
| `qa.py` | `validators.py` (pure functions) | LLM-coupled QA replaced by deterministic gates |
| `app.py` | new `app.py` + `mcp_server.py` (Day 5) | CLI + 5-tool MCP surface, claim-graph-driven |

## Re-running these modules

These modules were last functional at commit `89ee064` (before the Day 0 archive). To execute them:

```sh
git checkout v1.1-final
.venv/bin/pip install -e .
.venv/bin/python -m agent.app run --topic "metformin" --domain "longevity older adults"
```

Then return to `main` for current Proof 001 work.

## Lessons — read before re-architecting

- Do NOT put an LLM in the path of a categorical decision a deterministic table can make.
- Do NOT make markdown the source of truth — pick a structured representation.
- Do NOT treat repeat reliability fixes as additive — if 3 fixes don't close a failure mode, the architecture is wrong, not the procedure.

These are encoded as planted-failure regression tests in `tests/planted_failures/metformin/` (Day 1 deliverable). If a future change re-routes role classification through an LLM, the planted protocol-as-results case breaks immediately.
