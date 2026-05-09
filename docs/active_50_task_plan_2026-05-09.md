# Active 50+ Task Plan - 2026-05-09

## Operating Rule

Reload this file after every compaction before continuing. Keep the task list intact.
Advance step by step, double-audit each completed step, and commit/deploy only from a
clean, tested state.

## Current Critical Path

1. Finish active basket stabilization renders.
2. Audit verdicts twice: JSON verdict + manuscript surface.
3. Update recovery reports.
4. Run targeted tests, ruff, diff check, secret scan.
5. Commit, push, and sync MacBook/GitHub/VPS clean.
6. Start the next 15-20 topic overnight lane with floor-gated renders only.

## Phase 1 - Stabilize Current Basket

1. Commit rapamycin L6 supporting metadata.
2. Document model stack rationale, limitations, and rollback plan. Status: done.
3. Run senolytics full synthesis and verify verdict. Status: done, AAA/L5.
4. Run aspirin full guarded render on 83-receipt corpus.
5. Run sleep_health full guarded render on 67-receipt corpus.
6. Complete taurine reseed/re-extract and floor gate. Status: done, 88 receipts / 1068 tensions.
7. Complete spermidine reseed/re-extract and floor gate. Status: done, 31 receipts / 130 tensions.
8. Triage everolimus failure. Status: done, floor failed at 5 receipts / 24 claims / 2 tensions.

## Phase 2 - Reviewer Recall Validation

9. Build `scripts/reviewer_replay.py` for historical reviewer replay.
10. Run replay on 15 historical papers.
11. Compute DeepSeek recall, novel-find rate, and false-positive rate.
12. Add conditional Grok fallback only if replay data justifies it.

## Phase 3 - Mistral Arbitrator Load Reduction

13. Add deterministic duplicate-paragraph guard.
14. Sharpen Mistral prompt for ambiguous BEFORE cases.
15. Aggregate arbitration APPLY/REJECT/ESCALATE counts into manifest and cert.
16. Benchmark Mistral-small, Mistral-medium, and Granite on the same cases.

## Phase 4 - AAA-SCOP Cert Track

17. Add AAA-SCOP certification track without inflating full AAA/L5.
18. Add scoping L4/L5 maturity labels.
19. Update verdict taxonomy spec with SCOP definitions.
20. Re-evaluate applicable thin/high-quality papers under SCOP.

## Phase 5 - Topic-Pack Generator

21. Build `agent/topic_pack_generator.py`.
22. Add topic classifier for pseudoscience and contested-topic handling.
23. Add adaptive retrieval expansion loop.
24. Persist generated packs with version lineage.
25. Add topic-name-to-paper synthesize CLI.
26. Test generator on five fresh topics.
27. Document topic-pack generator V1.

## Phase 6 - Cross-Topic Meta-Synthesis

28. Build cross-topic aggregator.
29. Build convergence detector.
30. Build contradiction detector.
31. Build meta-writer.
32. Run first geroscience meta-synthesis.
33. Review meta-paper for real convergences and contradictions.

## Phase 7 - Public Reader Experience

34. Wire run completion hook to `provenance.researka.org`.
35. Backfill existing AAA papers to public reader.
36. Build per-sentence provenance index.
37. Track click-to-receipts UI follow-up.
38. Track Trust Panel UI follow-up.
39. Add RSS/Atom and JSON-LD citation feed.
40. Add SEO metadata, sitemap, and structured data.

## Phase 8 - Methodology And Open Standards

41. Run validation study against 10 published Cochrane reviews.
42. Compile validation study report.
43. Draft Researka methodology paper v1.
44. Finish bundle schema, tri-agent protocol, and verdict taxonomy specs.
45. Prepare bioRxiv preprint package.
46. Prepare PRISMA-AI extension submission package.

## Phase 9 - Wow Surface

47. Build or stage demo query surface.
48. Build rapamycin L6 showcase spec/assets.
49. Draft announcement/blog thread.
50. Compile state-of-platform report.

## Persistence Task

51. After every compaction, reload this file and restore the full task queue before doing new work.
