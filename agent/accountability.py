"""Validate machine-certified and human-signoff accountability models."""
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
    """Validate + normalise. Empty/None uses the default; unknown fails."""
    if not token:
        return DEFAULT_MODEL
    norm = str(token).strip().lower()
    if not norm:
        return DEFAULT_MODEL
    if norm not in ACCOUNTABILITY_MODELS:
        raise ValueError(f"unknown accountability model: {token!r}")
    return norm


def accountability_pass(
    run_dir: Path, declared_model: str | None,
) -> tuple[bool, str]:
    """Check whether the run satisfies the declared accountability
    model. Returns (passed, detail). Universal."""
    try:
        model = resolve_model(declared_model)
    except ValueError as exc:
        return (False, str(exc))
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
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            missing.append(f"{label} unreadable")
            continue
        if not isinstance(data, dict):
            missing.append(f"{label} malformed")
        elif filename == "artifact_consistency.json" and data.get("passed") is not True:
            missing.append(f"{label} not passed")
        elif filename == "citation_registry.json":
            if not data:
                missing.append(f"{label} empty")
            elif any(not isinstance(entry, dict) for entry in data.values()):
                missing.append(f"{label} malformed")
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
    from agent.human_signoff import load_and_validate
    signoff, issues = load_and_validate(run_dir)
    if signoff is None:
        return (False, "legacy model missing: human_signoff.json")
    if issues:
        return (False, "legacy model: invalid human signoff: " + ",".join(issue.code for issue in issues))
    return (True, "")
