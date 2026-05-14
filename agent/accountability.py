"""Accountability-model selector — Researka-native vs legacy-journal.

Reviewer doctrine 2026-05-14: "machine-verifiable evidence synthesis"
products should not require a human-author signoff as their L5 trust
anchor — the contradiction would defeat the product thesis. For
legacy journal submission, ICMJE / COPE rules still require named
human author accountability, so that path stays available.

This module defines two accountability models:

  - researka_agent_certified (default):
      L5 trust comes from reproducible run + claim registry + citation
      registry + numeric trace + audit pass + journal-surface pass +
      artifact consistency + public corrective path. NO human signoff
      file required.

  - legacy_journal_submission:
      Adds named human author signoff (`human_signoff.json:
      ready_to_submit == true`) as a required artifact, on top of all
      the researka-mode artifacts. Use this when the manuscript will
      be submitted to a journal that requires human-author rules
      (ICMJE / COPE compliance).

Universal — no topic-specific logic. Selection lives in
`manifest.accountability_model`. Default is researka_agent_certified.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Final

ACCOUNTABILITY_MODELS: Final[tuple[str, ...]] = (
    "researka_agent_certified",
    "legacy_journal_submission",
)
DEFAULT_MODEL: Final[str] = "researka_agent_certified"


def resolve_model(token: str | None) -> str:
    """Validate + normalise. Empty/None/unknown → default. Universal."""
    if not token:
        return DEFAULT_MODEL
    norm = str(token).strip().lower()
    return norm if norm in ACCOUNTABILITY_MODELS else DEFAULT_MODEL


def accountability_pass(
    run_dir: Path, declared_model: str | None,
) -> tuple[bool, str]:
    """Check whether the run satisfies the declared accountability
    model. Returns (passed, detail). Universal."""
    model = resolve_model(declared_model)
    if model == "researka_agent_certified":
        return _researka_check(run_dir)
    return _legacy_journal_check(run_dir)


def _researka_check(run_dir: Path) -> tuple[bool, str]:
    """Researka-native trust: artifact-only. No human file required.
    Checks the artifacts the reviewer named as the machine accountability
    layer (audit + journal-surface + pre-submit + artifact consistency
    + citation registry). Other 6-dimension gates (audit, journal_surface,
    pre_submit) are evaluated SEPARATELY by final_status.py; here we
    only verify the artifacts the *human_signoff* slot used to require
    are met by the agent layer instead."""
    required = (
        ("citation_registry.json", "citation registry"),
        ("artifact_consistency.json", "artifact consistency sidecar"),
    )
    missing: list[str] = []
    for filename, label in required:
        path = run_dir / filename
        if not path.is_file():
            missing.append(label)
            continue
        # Artifact consistency must report passed
        if filename == "artifact_consistency.json":
            try:
                d = json.loads(path.read_text())
                if d.get("passed") is False:
                    missing.append(
                        f"{label} reported failed",
                    )
            except (OSError, json.JSONDecodeError):
                missing.append(f"{label} unreadable")
    if missing:
        return (False, "researka model missing: " + ", ".join(missing))
    return (True, "")


def _legacy_journal_check(run_dir: Path) -> tuple[bool, str]:
    """Legacy journal submission: requires the artifact spine PLUS a
    named human author signoff. Maintains ICMJE / COPE compliance for
    runs whose target is an external journal."""
    ok, reason = _researka_check(run_dir)
    if not ok:
        return (False, reason)
    signoff_path = run_dir / "human_signoff.json"
    if not signoff_path.is_file():
        return (False, "legacy model missing: human_signoff.json")
    try:
        d = json.loads(signoff_path.read_text())
    except (OSError, json.JSONDecodeError):
        return (False, "legacy model: human_signoff.json unreadable")
    if not bool(d.get("ready_to_submit")):
        return (False, "legacy model: human signoff present but "
                       "ready_to_submit=false")
    return (True, "")
