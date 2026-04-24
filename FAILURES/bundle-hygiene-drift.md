# Failure: bundle-hygiene drift under prose-improving iterations

## Date
2026-04-24

## Trigger
Repeated live draft iterations improved prose while bundle hygiene stayed weak or regressed. Review feedback kept flagging the same issues: off-topic fillers, duplicate papers, and tier inflation.

## Symptom
- Live metformin drafts still retained irrelevant support papers such as `REMAP Trial for Optimizing Surgical Outcomes at UPMC`.
- Senolytic drafts could retain preclinical/model review noise such as `Galleria mellonella pathogen infection models`.
- Source bundles looked cleaner in prose but the underlying retained evidence set was not reliably constrained by a hard judge.

## Root cause
The bundle selector relied on permissive support-signal heuristics after retrieval and ranking. Two concrete failures mattered:

1. `card.context` could inject false aging support into unrelated human papers, which let off-topic support records survive.
2. Preclinical/model cues like `Galleria mellonella` were not classified strongly enough as `animal_model`, so they could survive as Tier B review support when the topic text happened to overlap.

At the process level, the protected eval measured prose-axis quality but did not measure bundle hygiene explicitly. That created a Goodhart loop: iterations that improved prose could look like progress while bundle discipline stayed weak or regressed, because the scoreboard was blind to the structural axis.

## Fix
- Added `tests/test_bundle_contract.py` as a discriminating bundle judge over metformin, rapamycin, and senolytics under the current 12-source Researka contract.
- Removed `card.context` from `_longevity_support_signal()` in `agent/drafter.py`, so support-tier retention no longer inherits noisy context labels.
- Expanded `animal_model` detection in `agent/citation_roles.py` to catch insect-model cues such as `galleria mellonella` and `insect infection models`.
- Verified locally:
  - pre-fix parent reproduction with current judge test: `1 failed, 2 passed`
  - current head: `459 passed, 6 skipped, 5 xfailed`
- Verified live on VPS `9ed8e16`:
  - metformin: REMAP gone, duplicate therapeutic-paradox entry collapsed
  - senolytics: Galleria leak gone

## Prevention
- Keep `tests/test_bundle_contract.py` in the default `tests/` CI path so prose-only changes cannot bypass bundle hygiene checks.
- Treat support-tier heuristics as suspect whenever they depend on inferred context labels rather than title/excerpt/population/outcome evidence.
- For thin-topic reviews, verify one live draft plus one synthetic discriminating test before accepting any “cleaner prose” claim.
- Extend the protected eval with explicit bundle-contract scoring so duplicate leaks, off-topic survivors, and tier-distribution failures move the scoreboard, not just prose and direction metrics.
- Continue measuring gold-topic quality separately; the Karpathy diff between `dbdb8eb` and `9ed8e16` was flat (`+0.0000` on all metrics), which confirmed the original harness was blind to bundle hygiene rather than proving the structural fix had no value.

## Related skills
- Bundle contract judge via `tests/test_bundle_contract.py`
- Generic role-tier classification hardening in `agent/citation_roles.py`
