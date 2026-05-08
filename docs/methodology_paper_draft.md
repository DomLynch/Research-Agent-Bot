# Methodology Paper Draft

Working title: *A Deterministic Trust Spine for AI-Assisted Evidence Synthesis*

Status: draft outline. This document distinguishes implemented platform
behavior from planned validation work. It is not a submission manuscript.

## Abstract

AI-assisted evidence synthesis can accelerate literature review, but generated
prose alone does not provide a reliable basis for scientific trust. We describe
Researka, an evidence-synthesis pipeline built around a deterministic trust
spine: language models may draft, extract, critique, and arbitrate bounded
patches, while code owns artifact schemas, citation identity, numeric
traceability, quarantine, verdict computation, and publication gates. The
method outputs inspectable paper bundles containing manuscripts, manifests,
audit reports, review logs, quarantine records, and final verdicts. Early
internal runs show that fail-closed gates can prevent unsupported numerics and
surface corpus weaknesses rather than silently certifying weak papers. Planned
external validation will benchmark extraction, risk judgments, verdict
stability, and arbitration decisions against human-consensus reference sets.

## Introduction

Evidence reviews increasingly rely on AI systems for retrieval, extraction, and
drafting. The central risk is not that AI text sounds weak; it is that fluent
text can hide unsupported claims, malformed citations, numeric drift, or
reviewer-side patch errors. Existing review standards emphasize human
screening, protocol transparency, and reproducibility, but most AI review tools
do not expose a comparable machine-verifiable decision trail.

Researka's thesis is narrow: AI systems can propose and critique, but
categorical trust decisions must be deterministic, logged, and reproducible.
The platform should be judged by inspectable artifacts rather than by prose
quality alone.

## Methods

### System Architecture

The pipeline ingests topic packs, retrieves and classifies sources, extracts
claims, compiles receipt and tension structures, renders manuscripts, and runs
deterministic audits before assigning a verdict. Markdown is downstream
rendering. Structured artifacts are the source of truth.

### Trust Spine

The trust spine enforces:

- citation identity through registries and deterministic compiler logic
- numeric traceability from public prose back to extracted claims
- quarantine for unsafe claims, rows, or public-render artifacts
- journal-surface checks for placeholder text, internal labels, malformed
  numerics, and manuscript leakage
- final verdict computation from audit state, review state, and maturity rules

### Tri-Agent Review Boundary

The current review stack may include a writer, an adversarial reviewer, and a
Mistral judge-only arbitrator. Mistral is not allowed to rewrite the
manuscript or introduce new content. It can only decide whether an existing
proposed patch should `APPLY`, `REJECT`, or `ESCALATE`. Invalid output,
timeouts, bad JSON, non-unique replacement targets, or failed post-apply audit
all fail closed.

Internal validation to date indicates that small arbitrator models are not
reliable as unconstrained semantic judges. The implemented defensible claim is
more limited: Mistral can provide a logged third-reviewer signal inside a
deterministic wrapper that only permits narrow, audited decisions.

### Bundle and Provenance

Each run can be rendered as a public bundle with manuscript, manifest, audit,
review, citation, checksum, and verdict artifacts. Provenance and registry
publication are downstream services. Derivation Web records provenance chains;
an independent OSF publisher may register approved artifacts and write registry
records back to provenance.

## Validation Study

The planned validation study will compare Researka outputs against
human-consensus references. Target benchmarks:

- extraction agreement on included studies and claim direction
- numeric traceability error rate
- citation role and registry correctness
- risk-of-bias and GRADE-lite agreement where available
- arbitration agreement on contested patch cases
- repeat-run stability for L6 reproducibility claims

Reference cases should be predeclared and should include both positive and
negative controls. Rejected runs, quarantines, and failed verdicts should remain
available for audit.

## Results

This section is pending a locked validation report. Internal sprint artifacts
already demonstrate three relevant behaviors:

- weak or malformed manuscripts can be blocked rather than falsely certified
- corpus-retuning can materially increase receipt depth for under-retrieved
  topics
- third-model arbitration must remain constrained because raw model agreement
  has not yet met a human-consensus threshold

No external clinical-validity or Cochrane-equivalence claim should be made
until validation fixtures and agreement statistics are finalized.

## Discussion

The main contribution is a methodological separation between AI generation and
trust assignment. This separation supports transparent failure: thin corpora,
untraceable numerics, malformed public prose, and disputed reviewer patches are
visible artifacts rather than hidden editorial problems.

The main limitation is that an auditable AI-generated synthesis is not the same
as a completed human-led systematic review. Formal claims about Cochrane RoB 2,
GRADE, PRISMA compliance, or journal readiness require the corresponding
instruments and human/editorial review where applicable. The platform can
produce strong evidence-synthesis artifacts, but publication claims must follow
the actual validation state.

## Code and Data Availability

Code, run manifests, final verdict files, audit sidecars, and bundle schemas
should be released with commit hashes and checksums. Public reader URLs, OSF
records, and provenance-chain URLs should be emitted only after the relevant
sibling services verify those records. Secrets, local filesystem paths, and
private API credentials must never appear in public bundles.
