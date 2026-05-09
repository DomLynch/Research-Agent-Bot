# Wiring Guide — Phase 3-8 Adapters Into the Live Synthesis Runner

**Audience:** Codex (lane: `scripts/run_v06_synthesis.py`).
**Purpose:** Concrete line-level snippets showing where to call each Claude-lane adapter so the live runner consumes the Phase 3-8 primitives. Reduces the wiring diff from ~80 lines of orchestration to ~10 one-liner calls.

---

## TL;DR — six insertion points

| # | Adapter call | Insertion point in `run_v06_synthesis.py` | Output |
|---|---|---|---|
| 1 | `agent.outcome_class_remap.remap_outcome_class(endpoint, raw)` | Wrap inside `_outcome_class_for_endpoint` (line 954) | Bug 2 fix |
| 2 | `agent.framework_section.build_framework_section(...)` | After receipts built (~line 1906), before paper render | Section markdown |
| 3 | `agent.quality_methods_bundle.build_quality_methods_bundle(...)` | After RoB/GRADE JSON written | Markdown + coverage floats |
| 4 | `agent.forest_plot_svg.render_forest_plot_svg(rows, pool)` | After `pool_random_effects` (or after `scripts.meta_analysis.pool_fixed_effect`) | SVG file |
| 5 | `agent.template_gate_adapter.evaluate_template_gate(paper_text)` | After `paper_path.write_text(...)` of `full_paper.md` | TemplateGateReport |
| 6 | `agent.final_gate_mapper.build_gate_inputs_from_artifacts(...)` + `agent.final_gate.evaluate_final_gate(inputs)` | Around `_compute_unified_verdict` (line 3424) | GateInputs + GateResult |

---

## 1. Outcome-class remap (Bug 2 fix)

**Where:** `scripts/run_v06_synthesis.py::_outcome_class_for_endpoint` at line ~954.

**Current code:**

```python
def _outcome_class_for_endpoint(endpoint: str) -> str:
    return (
        _ENDPOINT_TO_OUTCOME_CLASS.get(endpoint)
        or _domain_outcome_class(endpoint)
        or _infer_outcome_class(endpoint)
    )
```

**Wired code (one-line change):**

```python
from agent.outcome_class_remap import remap_outcome_class

def _outcome_class_for_endpoint(endpoint: str) -> str:
    raw = (
        _ENDPOINT_TO_OUTCOME_CLASS.get(endpoint)
        or _domain_outcome_class(endpoint)
        or _infer_outcome_class(endpoint)
    )
    return remap_outcome_class(endpoint, raw)
```

**What this fixes:** PEARL trial endpoints "emotional well-being / general health / self-reported pain" no longer resolve to `cognitive` / `frailty`; they route to `healthspan_qol`. The remap is idempotent — already-correct endpoints pass through unchanged.

**Verification:** `pytest tests/test_outcome_class_remap.py` (36 tests cover the remap path).

---

## 2. Framework engagement section (Phase 3)

**Where:** After receipts are assembled and before the writer renders the paper sections. The most natural spot is wherever the writer module composes section content from receipts.

**Inputs needed:**
- `receipts: list[dict]` — manifest receipts (each with `receipt_id`, `outcome_class`, `effect_direction`).
- `citation_registry: dict[str, dict]` — loaded from `citation_registry.json` (maps receipt_id → `{"body_citation": "Author Year", ...}`).
- Optional: `background_refs: list[dict]` from manifest's background literature.

**Snippet:**

```python
from agent.framework_section import build_framework_section

# After receipts + citation_registry are loaded
engagement_md = build_framework_section(
    receipts=manifest["receipts"],
    citation_registry=citation_registry,
    background_refs=manifest.get("background_refs", ()),
)
# Insert engagement_md as a paper section — typically just before
# Cross-Domain Synthesis or after Background.
```

**What it produces:** `## Engagement with Established Frameworks` section with one paragraph per named field framework (Mannick / Lamming / Kennedy / Kaeberlein / Lopez-Otin), status-driven (support / challenge / extends / insufficient). Insufficient frameworks are marked `[provisional]`. Honest — never invents framework support that doesn't exist in the corpus.

**Audit hook:** the section is deterministic given inputs. Same manifest → same markdown.

---

## 3. Quality-methods bundle (Phase 4)

**Where:** After RoB JSON and GRADE JSON are written (or computed) and before the final gate runs.

**Inputs needed:**
- `rob_payload: list[dict]` — RoB assessments (one per study; conforms to `agent.risk_of_bias_schema` shape).
- `grade_payload: list[dict]` — GRADE per-outcome assessments.
- `receipt_count: int` — denominator for `rob_coverage`.
- `outcome_count: int` — denominator for `grade_coverage` (count of distinct `outcome_class` in the manifest).

**Snippet:**

```python
from agent.quality_methods_bundle import build_quality_methods_bundle

quality_bundle = build_quality_methods_bundle(
    rob_payload=rob_payload,           # list[dict] or None
    grade_payload=grade_payload,       # list[dict] or None
    receipt_count=len(manifest["receipts"]),
    outcome_count=len({r["outcome_class"] for r in manifest["receipts"]}),
)

# Persist alongside other audit artifacts:
(paper_path.with_suffix(".quality_methods.md")
).write_text(quality_bundle.markdown, encoding="utf-8")

# Coverage values feed into the final gate (see #6 below):
rob_coverage = quality_bundle.rob_coverage     # 0.0–1.0
grade_coverage = quality_bundle.grade_coverage # 0.0–1.0
```

**Fail-closed behavior:** Missing RoB or GRADE payloads → coverage 0.0 + explicit `_No data provided._` placeholder in the markdown. Final gate then fails on coverage threshold (correct outcome — don't certify what wasn't measured).

---

## 4. Forest plot SVG (Phase 5, optional)

**Where:** After meta-analysis pooling produces a `PoolResult`. Only fires when an outcome has ≥3 studies on a single comparable metric.

**Inputs needed:**
- `rows: list[EffectRow]` — the input rows that went into the pool.
- `pool: PoolResult` — the FE or RE result.

**Snippet:**

```python
from agent.forest_plot_svg import render_forest_plot_svg

if len(rows) >= 3:  # required by assert_poolable
    svg = render_forest_plot_svg(
        rows, pool, title=f"{topic.capitalize()}: {outcome_class}"
    )
    (paper_path.parent / f"forest_{outcome_class}.svg").write_text(
        svg, encoding="utf-8"
    )
```

**Note:** Two `meta_analysis` modules currently exist — Codex's `scripts/meta_analysis.py` (older API: takes outcome string + dicts, returns `fail_closed`/`reason`) and my `agent/meta_analysis.py` (newer API: `EffectRow`/`PoolResult` dataclasses with Q/I²/τ²). The forest renderer consumes the newer dataclass shape. If wiring against `scripts/meta_analysis.py`, add a small adapter that converts its output to `PoolResult` first.

---

## 5. Template-language gate (Phase 6)

**Where:** Immediately after the final paper markdown is written to disk (around line 2193 / wherever `paper_path.write_text(...)` happens for `full_paper.md`).

**Inputs needed:**
- `paper_text: str` — the rendered `full_paper.md` content.

**Snippet:**

```python
from agent.template_gate_adapter import evaluate_template_gate

paper_text = paper_path.read_text(encoding="utf-8")
template_report = evaluate_template_gate(paper_text, source=paper_path.name)

# Persist for audit transparency
paper_path.with_suffix(".template_gate.md").write_text(
    template_report.markdown_report, encoding="utf-8"
)
paper_path.with_suffix(".template_gate.json").write_text(
    template_report.json_report, encoding="utf-8"
)

# template_report.template_language_blocking feeds the final gate
```

**Fail-closed behavior:** any P1 (unsupported authority) or P2 (cliché / AI-tell / vague limitation) hit sets `template_language_blocking=True`, which blocks the final gate.

---

## 6. Final gate (Phase 8)

**Where:** Inside or alongside `_compute_unified_verdict` at line ~3424. The existing function already has the audit + journal-surface signals; the new one bundles them into `GateInputs` and runs the deterministic gate.

**Inputs needed:**
- `audit: dict` — loaded from `paper_path.with_suffix(".audit.json")` (already present).
- `journal_surface: dict` — loaded from `journal_surface.json` (already present).
- `reviewer_patches: dict` — loaded from `paper_path.with_suffix(".review_patches.json")` (already present).
- `template_report` — from #5 above.
- `quality_bundle` — from #3 above.
- `numeric_coverage: float` — already computed somewhere upstream (or default 1.0 if Q2/numeric trace passed).
- `citation_registry_complete: bool` — True if every receipt_id in the prose maps into citation_registry.json.
- `n_tensions, n_receipts: int` — from manifest.

**Snippet:**

```python
import json
from agent.final_gate import evaluate_final_gate
from agent.final_gate_mapper import build_gate_inputs_from_artifacts

audit = json.loads(audit_path.read_text())
journal_surface = json.loads(journal_surface_path.read_text())
reviewer_patches = json.loads(review_patches_path.read_text())

gate_inputs = build_gate_inputs_from_artifacts(
    audit=audit,
    journal_surface=journal_surface,
    reviewer_patches=reviewer_patches,
    template_gate=template_report,
    quality_methods=quality_bundle,
    numeric_coverage=numeric_coverage,             # see note below
    citation_registry_complete=citation_complete,  # see note below
    n_tensions=manifest["n_non_orthogonal_tensions"],
    n_receipts=manifest["n_receipts"],
)
gate_result = evaluate_final_gate(gate_inputs)

# Persist
paper_path.with_suffix(".final_gate.json").write_text(
    json.dumps({
        "passed": gate_result.passed,
        "failures": list(gate_result.failures),
        "warnings": list(gate_result.warnings),
        "summary": gate_result.summary,
    }, indent=2)
)

if not gate_result.passed:
    print(f"FINAL GATE FAILED: {gate_result.summary}", file=sys.stderr)
    # raise / sys.exit(1) per existing cert-floor convention
```

**Note on `numeric_coverage` and `citation_registry_complete`:** These need to come from existing computations in the runner (Q2 numeric trace coverage, citation registry traversal). If they aren't already exposed as floats/bools, a small helper in the same function can derive them from the audit_report dict.

**Threshold tuning:** if the AAA-SCOP track needs relaxed thresholds, instantiate a custom `GateThresholds(...)` and pass to `evaluate_final_gate(inputs, thresholds=custom)`. See `agent/final_gate.py::DEFAULT_THRESHOLDS`.

---

## End-to-end flow after wiring

```
manifest
  ↓
build_receipts_from_quant_claims()
  ↓
[NEW] build_framework_section(receipts, citation_registry)  →  engagement_md
  ↓
writer composes paper sections (existing path)
  ↓
paper_path.write_text(full_paper_md)
  ↓
[NEW] evaluate_template_gate(paper_text)  →  template_report
  ↓
audit + journal_surface + reviewer_patches written (existing path)
  ↓
[NEW] build_quality_methods_bundle(rob, grade, n_receipts, n_outcomes)
  →  quality_bundle (markdown persisted; coverage floats kept)
  ↓
[NEW, optional, per outcome] render_forest_plot_svg(rows, pool)
  ↓
[NEW] build_gate_inputs_from_artifacts(audit, journal_surface,
        reviewer_patches, template_report, quality_bundle, ...)
  ↓
[NEW] evaluate_final_gate(inputs)  →  PASS / FAIL with named blockers
  ↓
[existing] _compute_unified_verdict + cert.md generation
```

The new calls are **5 lines of orchestration plus 1 wrapper line in `_outcome_class_for_endpoint`**. All adapters fail-closed on missing inputs, so partial wiring is safe (e.g. if quality bundle isn't ready yet, the final gate fails on coverage, with a named blocker, rather than producing a misleading PASS).

---

## Validation contract

After wiring:

1. **Synthesis runs to completion** on a clean rapamycin corpus.
2. **`paper_path.with_suffix(".template_gate.json")`** exists and is well-formed.
3. **`paper_path.with_suffix(".quality_methods.md")`** exists (or carries placeholders if RoB/GRADE not yet active).
4. **`paper_path.with_suffix(".final_gate.json")`** exists and `passed` matches the existing `_compute_unified_verdict` PASS/FAIL.
5. **No regression** on the existing 14/14 audit + journal-surface gate.
6. **Re-running on the same corpus** produces byte-identical engagement section + template-gate report (determinism).

If validation #4 disagrees (final_gate FAIL where unified_verdict PASS, or vice versa), surface the divergence — that's likely a coverage threshold mismatch and informs whether to tighten or loosen `GateThresholds` defaults.

---

## What this guide does NOT cover

- **Cert-floor logic:** existing per-track cert floors (AAA-CLIN / INF / MECH / SCOP) stay where they are. The final gate is an *additional* layer, not a replacement.
- **Reproducibility checker (L6):** comparison of two consecutive runs. Out of scope; needs a separate primitive.
- **Bug 2 vocab fix:** updating `scripts/vocab/rapamycin.py` line 61 (`"emotional well-being": "cognitive"` → `"healthspan_qol"`). The `outcome_class_remap` wrapper handles it without modifying the vocab; if you'd rather fix at source, the vocab edit is one line.

---

**Open questions for Codex:**

1. Where exactly does the writer module receive section content? `agent/paper_writer.py::render_full_paper` is a likely spot — the engagement section needs an insertion point in that pipeline.
2. Is `numeric_coverage` already computed? If not, add `audit_report.get("numeric_coverage", 1.0 if all_q2_pass else 0.5)` as a placeholder.
3. Does the AAA-SCOP track need relaxed `GateThresholds`? If so, wire a track-aware threshold selector around `evaluate_final_gate`.

These are integration-level questions only Codex can answer in the live runner. The adapters are otherwise self-contained.
